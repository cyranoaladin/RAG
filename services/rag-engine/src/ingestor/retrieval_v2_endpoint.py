"""Retrieval v2 endpoint — FastAPI router (FE-01).

Exposes POST /search/v2 wrapping the canonical LOT40 hybrid pipeline:
  resolve_collection_v2 → gate retrievable (fail-closed) → dense + lexical
  → RRF → rerank → seuil +1.90 → MMR.

Models are cached at module level (loaded once, not per request).
DSN via PG_RAG_DSN or DATABASE_URL_SYNC env var (R-01: no default).
answer_generation_allowed = false (retrieval only, no LLM generation).
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal

import psycopg  # noqa: F811 — also in requirements.v2.txt
from fastapi import APIRouter, HTTPException, Request
from nexus_contracts import (
    ChatRequest,
    ChatResponse,
    Citation,
    RetrievalResult,
)
from pydantic import BaseModel, ConfigDict, Field, computed_field

try:
    from .collection_config import (
        CollectionConfigError,
        list_instanciated_collections,
        load_collection_config,
        resolve_collection_v2,
    )
    from .embedding_contract import (
        load_embedding_model,
    )
    from .pg_pool import PoolSettings, pool_connection
    from .retrieval_hybrid_v2 import (
        CHANNEL_LIMIT,
        EMBED_MODEL,
        MMR_LAMBDA,  # noqa: F401 -- public endpoint configuration surface
        RERANK_MODEL,
        RERANK_THRESHOLD,
        RRF_K,  # noqa: F401 -- public endpoint configuration surface
        HybridHit,
        retrieve_hybrid,
    )
    from .retrieval_pg_v2 import PgCandidateStore
    from .security_v2 import SecurityRole, require_role
except (ImportError, ValueError):
    from collection_config import (  # type: ignore[no-redef]
        CollectionConfigError,
        list_instanciated_collections,
        load_collection_config,
        resolve_collection_v2,
    )
    from embedding_contract import (  # type: ignore[no-redef]
        load_embedding_model,
    )
    from pg_pool import PoolSettings, pool_connection  # type: ignore[no-redef]
    from retrieval_hybrid_v2 import (  # type: ignore[no-redef]
        CHANNEL_LIMIT,
        EMBED_MODEL,
        MMR_LAMBDA,  # noqa: F401 -- public endpoint configuration surface
        RERANK_MODEL,
        RERANK_THRESHOLD,
        RRF_K,  # noqa: F401 -- public endpoint configuration surface
        HybridHit,
        retrieve_hybrid,
    )
    from retrieval_pg_v2 import PgCandidateStore  # type: ignore[no-redef]
    from security_v2 import SecurityRole, require_role  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

MIN_COLLECTION_SUBSTANCE_CHUNKS = int(os.environ.get("RAG_MIN_COLLECTION_SUBSTANCE_CHUNKS", "1"))

router = APIRouter(tags=["retrieval_v2"])

# --- Cache de warmup/administration (SCALE-V1-1) ---
# Key = normalized(query, collection, k). Value = (hits, timestamp).
# Invalidation is generation-based so a warmup started before a review change
# can never republish its stale snapshot afterward.
# Public search never reads this process-local cache: every request re-runs the
# canonical PostgreSQL pipeline and therefore observes the current review state.
#
# This cache is per-process: invalidate only clears the handling worker. The
# historical enablement flag remains visible in stats, but it cannot authorize
# serving cache entries on public search.
_rag_env_cache = (os.environ.get("RAG_ENV") or "").strip().lower()
CACHE_TTL_S = int(os.environ.get("RERANK_CACHE_TTL", "300"))  # 5 min default
if _rag_env_cache == "production":
    CACHE_ENABLED = os.environ.get("RERANK_CACHE", "0") == "1"
else:
    CACHE_ENABLED = os.environ.get("RERANK_CACHE", "1") != "0"
_cache: dict[str, tuple[list, float]] = {}
_cache_lock = threading.Lock()
_cache_generation = 0


def _cache_key(query: str, collection: str, k: int) -> str:
    """Normalized cache key. Lowercased, stripped, unicode-normalized."""
    import unicodedata
    normalized = unicodedata.normalize("NFKC", query).strip().lower()
    # Collapse curly quotes/apostrophes to ASCII equivalents
    normalized = normalized.replace("\u2019", "'").replace("\u2018", "'")
    normalized = normalized.replace("\u201c", '"').replace("\u201d", '"')
    raw = f"{normalized}|{collection}|{k}"
    return hashlib.sha256(raw.encode()).hexdigest()


def invalidate_cache() -> int:
    """Invalidate all cache entries. Called when review_status changes."""
    global _cache_generation
    with _cache_lock:
        n = len(_cache)
        _cache.clear()
        _cache_generation += 1
        return n

# --- Configuration figée par le noyau hybride LOT40 ---
RERANK_SCORE_THRESHOLD = RERANK_THRESHOLD
RERANK_CANDIDATES = CHANNEL_LIMIT

WARMUP_QUERIES = (
    "Comment fonctionne une boucle while en Python ?",
    "Quelle est la différence entre une pile et une file ?",
    "Qu'est-ce qu'un arbre binaire de recherche ?",
    "Comment fonctionne la récursivité ?",
    "Comment trier une liste en Python ?",
    "Qu'est-ce qu'un dictionnaire en Python ?",
    "Comment fonctionne une requête SQL avec jointure ?",
    "Qu'est-ce qu'une clé étrangère ?",
    "Comment parcourir un graphe en profondeur ?",
    "Comment fonctionne la programmation dynamique ?",
    "Qu'est-ce qu'un processus en système d'exploitation ?",
    "Expliquer le tri par insertion",
    "Comment représenter un entier en binaire ?",
    "À quoi sert le protocole HTTP ?",
    "Qu'est-ce qu'un type construit en Python ?",
    "Comment fonctionne une boucle for en Python ?",
    "Qu'est-ce qu'une variable locale et globale ?",
    "Comment fonctionne le protocole TCP/IP ?",
    "Qu'est-ce qu'un algorithme glouton ?",
    "Comment fonctionne la recherche dichotomique ?",
)

# --- Lazy-loaded models (cached at module level) ---
_embed_model = None
_reranker = None


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        logger.info("Loading embedding model %s (one-time)", EMBED_MODEL)
        _embed_model = load_embedding_model()
    return _embed_model


def _get_reranker():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder
        logger.info("Loading reranker %s (one-time)", RERANK_MODEL)
        _reranker = CrossEncoder(RERANK_MODEL, max_length=512)
    return _reranker



def _get_pg_dsn() -> str:
    """Return pgvector DSN from environment. No default (R-01)."""
    dsn = os.environ.get("PG_RAG_DSN") or os.environ.get("DATABASE_URL_SYNC")
    if not dsn:
        raise HTTPException(
            status_code=503,
            detail="PG_RAG_DSN or DATABASE_URL_SYNC not configured",
        )
    return dsn


def _check_retrievable(collection: str, cfg: dict) -> dict:
    """Gate retrievable FAIL-CLOSED (GG-01).

    Reads domain from the collection's DECLARED definition.
    Refuses if domain absent, domains section malformed, or retrievable not True.
    """
    defn = resolve_collection_v2(collection, cfg)

    domain = defn.get("domain")
    if not isinstance(domain, str) or not domain:
        raise HTTPException(
            status_code=403,
            detail=f"Collection '{collection}' has no declared domain — cannot verify retrievable.",
        )

    domains = cfg.get("domains")
    if not isinstance(domains, dict):
        raise HTTPException(
            status_code=500,
            detail="Config 'domains' section absent or malformed — fail-closed.",
        )

    domain_cfg = domains.get(domain)
    if not isinstance(domain_cfg, dict):
        raise HTTPException(
            status_code=403,
            detail=f"Domain '{domain}' not found — collection '{collection}' not retrievable.",
        )

    if domain_cfg.get("retrievable") is not True:
        raise HTTPException(
            status_code=403,
            detail=f"Collection '{collection}' is not retrievable (domain '{domain}').",
        )

    return defn


# --- Request/Response models ---

class SearchV2Request(BaseModel):
    q: str = Field(..., min_length=1, description="Query text")
    collection: str = Field(..., min_length=1, description="Nexus v2 collection name")
    k: int = Field(default=5, ge=1, le=50, description="Number of results")


class SearchV2Hit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1, pattern=r".*\S.*")
    doc_id: str = Field(min_length=1, pattern=r".*\S.*")
    source_label: str = Field(min_length=1, pattern=r".*\S.*")
    source_uri: str = Field(min_length=1, pattern=r".*\S.*")
    rights: str = Field(min_length=1, pattern=r".*\S.*")
    type_doc: str
    review_status: Literal["reviewed"]  # SCALE-04: reviewed only
    page: int | None = Field(default=None, ge=1)
    preview: str = Field(min_length=1, pattern=r".*\S.*")
    dense_score: float | None
    lexical_score: float | None
    rrf_score: float = Field(ge=0)
    rerank_score: float
    mmr_score: float
    score_final: float = Field(ge=0, le=1)

    @computed_field(  # type: ignore[prop-decorator]
        return_type=float | None,
        json_schema_extra={"deprecated": True},
    )
    @property
    def dense_sim(self) -> float | None:
        """Alias de sérialisation déprécié, dérivé de l'unique score dense."""
        return self.dense_score


class SearchV2Response(BaseModel):
    query: str
    collection: str
    seuil: float = Field(
        default=RERANK_SCORE_THRESHOLD,
        ge=RERANK_SCORE_THRESHOLD,
        le=RERANK_SCORE_THRESHOLD,
    )
    returned: int
    answer_generation_allowed: Literal[False] = False
    hits: list[SearchV2Hit]


def _build_launch_readiness(
    cfg: Mapping[str, Any],
    reviewed_counts: Mapping[str, int],
    *,
    min_chunks: int,
) -> dict[str, Any]:
    """Assess every declared collection, without inferring missing evidence.

    This is deliberately stricter than the retrieval gate. A collection can be
    searchable internally while public launch remains closed because a corpus
    is absent or has not reached the required reviewed-chunk threshold.
    """
    collections_raw = cfg.get("collections")
    domains = cfg.get("domains")
    if not isinstance(collections_raw, Mapping) or not isinstance(domains, Mapping):
        raise ValueError("collections or domains config is malformed")

    collections: list[dict[str, Any]] = []
    blockers: list[str] = []
    for name in sorted(collections_raw):
        definition = collections_raw[name]
        if not isinstance(definition, Mapping):
            blockers.append(f"{name}: définition de collection invalide")
            collections.append({
                "name": name,
                "instanciee": False,
                "retrievable": False,
                "reviewed_chunks": 0,
                "substantial": False,
                "ready": False,
                "reasons": ["définition de collection invalide"],
            })
            continue

        instanciee = definition.get("instanciee") is True
        domain = definition.get("domain")
        domain_cfg = domains.get(domain) if isinstance(domain, str) else None
        retrievable = isinstance(domain_cfg, Mapping) and domain_cfg.get("retrievable") is True
        reviewed_chunks = max(0, int(reviewed_counts.get(name, 0)))
        substantial = reviewed_chunks >= min_chunks
        reasons: list[str] = []
        if not instanciee:
            reasons.append("collection non instanciée")
        if not retrievable:
            reasons.append("domaine non retrievable")
        if not substantial:
            reasons.append(
                f"corpus validé insuffisant ({reviewed_chunks}/{min_chunks} chunks reviewed)",
            )
        ready = not reasons
        if not ready:
            blockers.append(f"{name}: {', '.join(reasons)}")
        collections.append({
            "name": name,
            "instanciee": instanciee,
            "retrievable": retrievable,
            "reviewed_chunks": reviewed_chunks,
            "substantial": substantial,
            "ready": ready,
            "reasons": reasons,
        })

    return {
        "launch_ready": not blockers,
        "total_collections": len(collections),
        "ready_collections": sum(1 for item in collections if item["ready"]),
        "minimum_reviewed_chunks": min_chunks,
        "blockers": blockers,
        "collections": collections,
    }


def _get_reviewed_chunk_counts(collection_names: Iterable[str]) -> dict[str, int]:
    """Count approved corpus rows for launch readiness, failing closed on DB loss."""
    names = list(collection_names)
    if not names:
        return {}
    try:
        conn = psycopg.connect(_get_pg_dsn())
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("pgvector connection failed while checking launch readiness: %s", exc)
        raise HTTPException(status_code=503, detail="launch readiness unavailable") from exc

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT collection, COUNT(*)
                FROM rag_chunks
                WHERE collection = ANY(%s) AND review_status = 'reviewed'
                GROUP BY collection
                """,
                (names,),
            )
            return {str(collection): int(count) for collection, count in cur.fetchall()}
    except Exception as exc:
        logger.error("pgvector readiness query failed: %s", exc)
        raise HTTPException(status_code=503, detail="launch readiness unavailable") from exc
    finally:
        conn.close()


# --- Cache management endpoints ---

@router.get("/cache/v2/stats")
def cache_stats(request: Request) -> dict[str, Any]:
    """Cache statistics for monitoring."""
    _enforce_security_v2(
        request,
        allowed_roles={
            SecurityRole.ADMIN,
            SecurityRole.REVIEWER,
            SecurityRole.TEACHER,
            SecurityRole.INGEST_AGENT,
            SecurityRole.STUDENT,
        },
        endpoint="/cache/v2/stats",
    )
    with _cache_lock:
        return {
            "enabled": CACHE_ENABLED,
            "ttl_s": CACHE_TTL_S,
            "entries": len(_cache),
            "generation": _cache_generation,
            "public_serving": False,
        }


@router.post("/cache/v2/invalidate")
def cache_invalidate(request: Request) -> dict[str, Any]:
    """Invalidate all cache entries. Call when review_status changes."""
    _enforce_security_v2(
        request,
        allowed_roles={SecurityRole.ADMIN, SecurityRole.REVIEWER},
        endpoint="/cache/v2/invalidate",
    )
    n = invalidate_cache()
    return {"invalidated": n}


@router.post("/cache/v2/warmup")
def cache_warmup(request: Request) -> dict[str, Any]:
    """Pre-warm cache with common pedagogical queries (SCALE-V1-6).

    Runs the canonical hybrid pipeline for probable queries and caches results.
    Call at startup or after invalidation to eliminate cold-start misses.
    """
    _enforce_security_v2(
        request,
        allowed_roles={SecurityRole.ADMIN, SecurityRole.REVIEWER},
        endpoint="/cache/v2/warmup",
    )

    if not CACHE_ENABLED:
        invalidate_cache()
        return {"warmed": 0, "collections": 0, "queries": 0}

    with _cache_lock:
        warmup_generation = _cache_generation

    cfg = load_collection_config()
    collections = list_instanciated_collections(cfg)
    # Only warm retrievable collections
    domains = cfg.get("domains", {})
    retrievable_cols = []
    for name in collections:
        try:
            defn = resolve_collection_v2(name, cfg)
        except Exception:
            raise _retrieval_unavailable() from None
        domain = defn.get("domain")
        if isinstance(domain, str) and isinstance(domains.get(domain), dict):
            if domains[domain].get("retrievable") is True:
                retrievable_cols.append(name)

    staged: dict[str, list[dict[str, Any]]] = {}
    target_keys: set[str] = set()
    for col in retrievable_cols:
        for q in WARMUP_QUERIES:
            key = _cache_key(q, col, 5)
            target_keys.add(key)
            hits_data = [
                hit.model_dump() for hit in _retrieve_endpoint_hits(q, col, 5)
            ]
            if hits_data:
                staged[key] = hits_data

    published_at = time.monotonic()
    with _cache_lock:
        if _cache_generation != warmup_generation:
            raise _retrieval_unavailable()
        for key in target_keys:
            _cache.pop(key, None)
        _cache.update(
            {
                key: (hits_data, published_at)
                for key, hits_data in staged.items()
            }
        )

    return {
        "warmed": len(staged),
        "collections": len(retrievable_cols),
        "queries": len(WARMUP_QUERIES),
    }


# --- Endpoint to list retrievable collections (for UI picker) ---

def _list_retrievable_collections() -> dict[str, Any]:
    """Return collections that are instanciee:true AND retrievable:true.

    The UI picker derives its list from this endpoint (D-PICKER-DERIVE-CATALOGUE).
    Adding a new instanciated collection makes it appear without UI code change.
    """
    cfg = load_collection_config()
    instanciated = list_instanciated_collections(cfg)
    domains = cfg.get("domains", {})

    retrievable = []
    for name in sorted(instanciated):
        try:
            defn = resolve_collection_v2(name, cfg)
        except CollectionConfigError:
            continue
        domain = defn.get("domain")
        if not isinstance(domain, str):
            continue
        domain_cfg = domains.get(domain)
        if not isinstance(domain_cfg, dict):
            continue
        if domain_cfg.get("retrievable") is not True:
            continue
        retrievable.append({
            "name": name,
            "matiere": defn.get("matiere"),
            "niveau": defn.get("niveau"),
            "statut": defn.get("statut"),
            "domain": domain,
        })

    return {"collections": retrievable}


@router.get("/collections/v2")
def list_retrievable_collections(request: Request) -> dict[str, Any]:
    """Public alias kept for direct imports in tests."""
    _enforce_security_v2(
        request,
        allowed_roles={
            SecurityRole.ADMIN,
            SecurityRole.REVIEWER,
            SecurityRole.TEACHER,
            SecurityRole.INGEST_AGENT,
            SecurityRole.STUDENT,
        },
        endpoint="/collections/v2",
    )
    return _list_retrievable_collections()


# --- Full catalogue endpoint (LOT 27) ---

def _full_catalogue() -> dict[str, Any]:
    """Return the complete v2 catalogue with instanciation/retrievable status.

    Unlike /collections/v2 (picker: instanciated+retrievable only),
    this returns ALL declared collections for Dashboard/Administration.
    Includes taxonomy_exists and coherence_issues for governance.
    """
    cfg = load_collection_config()
    collections_raw = cfg.get("collections", {})
    domains = cfg.get("domains", {})
    known_domains = set(domains.keys()) if isinstance(domains, dict) else set()

    # Resolve taxonomy base dir
    config_path = _resolve_taxonomy_base()

    collections = []
    by_level: dict[str, list[str]] = {}
    by_domain: dict[str, list[str]] = {}
    by_status: dict[str, list[str]] = {}

    for name in sorted(collections_raw):
        defn = collections_raw[name]
        if not isinstance(defn, dict):
            continue

        domain = defn.get("domain") or "unknown"
        domain_cfg = domains.get(domain, {}) if isinstance(domains, dict) else {}
        domain_retrievable = domain_cfg.get("retrievable", False) is True
        instanciee = defn.get("instanciee") is True
        retrievable = instanciee and domain_retrievable

        niveau = defn.get("niveau")
        voie = defn.get("voie")
        matiere = defn.get("matiere")
        statut = defn.get("statut")
        taxonomy_file = defn.get("taxonomy_file")

        # Check taxonomy file existence
        taxonomy_exists = True
        if taxonomy_file and config_path:
            taxonomy_exists = (config_path / taxonomy_file).is_file()

        # Coherence checks
        coherence_issues: list[str] = []
        if domain == "quarantine":
            pass  # quarantine is special
        else:
            if not taxonomy_file:
                coherence_issues.append("taxonomy_file absent")
            elif not taxonomy_exists:
                coherence_issues.append(f"taxonomy_file '{taxonomy_file}' non trouv\u00e9")
            if domain not in known_domains:
                coherence_issues.append(f"domaine inconnu: {domain}")
            if instanciee and not domain_retrievable:
                coherence_issues.append("instanci\u00e9e mais domaine non retrievable")
            if retrievable and not instanciee:
                coherence_issues.append("retrievable sans \u00eatre instanci\u00e9e")

        # Reasons
        ingestion_reason = "collection instanci\u00e9e" if instanciee else "collection non instanci\u00e9e"
        search_reason = "instanci\u00e9e + domaine retrievable" if retrievable else (
            "domaine non retrievable" if instanciee else "non instanci\u00e9e"
        )

        entry = {
            "name": name,
            "matiere": matiere,
            "niveau": niveau,
            "voie": voie,
            "statut": statut,
            "domain": domain,
            "instanciee": instanciee,
            "retrievable": retrievable,
            "taxonomy_file": taxonomy_file,
            "taxonomy_exists": taxonomy_exists,
            "ingestion_enabled": instanciee,
            "search_enabled": retrievable,
            "ingestion_enabled_reason": ingestion_reason,
            "search_enabled_reason": search_reason,
            "coherence_issues": coherence_issues,
        }
        collections.append(entry)

        # Group by level
        level_key = niveau or "transversal"
        by_level.setdefault(level_key, []).append(name)

        # Group by domain
        by_domain.setdefault(domain, []).append(name)

        # Group by status
        status_key = statut or "autre"
        by_status.setdefault(status_key, []).append(name)

    return {
        "version": 2,
        "collections": collections,
        "by_level": by_level,
        "by_domain": by_domain,
        "by_status": by_status,
    }


def _resolve_taxonomy_base() -> Path | None:
    """Resolve taxonomy base directory (services/rag-pedago/taxonomy/)."""
    # Navigate from this module: ingestor/ -> src/ -> rag-engine/ -> services/ -> rag-pedago/
    module_dir = Path(__file__).resolve().parent
    for parent in (module_dir, *module_dir.parents):
        candidate = parent / "taxonomy"
        if candidate.is_dir():
            return candidate
        # Also check peer service
        peer = parent.parent / "rag-pedago" / "taxonomy"
        if peer.is_dir():
            return peer
    return None


@router.get("/catalogue/v2")
def get_full_catalogue(request: Request) -> dict[str, Any]:
    """Full catalogue — all declared collections with status flags.

    Used by Dashboard and Administration. Read-only.
    INGEST_AGENT included: the Streamlit UI connects with this role
    (INGESTOR_API_TOKEN) and needs catalogue data for Dashboard,
    Administration, and Ingestion pages.
    STUDENT excluded: catalogue exposes governance details.
    """
    _enforce_security_v2(
        request,
        allowed_roles={
            SecurityRole.ADMIN,
            SecurityRole.REVIEWER,
            SecurityRole.TEACHER,
            SecurityRole.INGEST_AGENT,
        },
        endpoint="/catalogue/v2",
    )
    return _full_catalogue()


@router.get("/collections/readiness")
def get_collection_readiness(request: Request) -> dict[str, Any]:
    """Fail closed when the declared public corpus is not proven complete."""
    _enforce_security_v2(
        request,
        allowed_roles={
            SecurityRole.ADMIN,
            SecurityRole.REVIEWER,
            SecurityRole.TEACHER,
            SecurityRole.INGEST_AGENT,
            SecurityRole.STUDENT,
        },
        endpoint="/collections/readiness",
    )
    try:
        cfg = load_collection_config()
        collections_raw = cfg.get("collections")
        if not isinstance(collections_raw, Mapping):
            raise ValueError("collections config is malformed")
        counts = _get_reviewed_chunk_counts(collections_raw.keys())
        return _build_launch_readiness(
            cfg,
            counts,
            min_chunks=MIN_COLLECTION_SUBSTANCE_CHUNKS,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("launch readiness unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="launch readiness unavailable") from exc


def _retrieval_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="retrieval unavailable")


def _retrieve_hybrid_hits(query: str, collection: str, k: int) -> list[HybridHit]:
    """Compose the one canonical v2 pipeline without exposing failure context."""
    try:
        settings = PoolSettings.from_env()
        store = PgCandidateStore(lambda: pool_connection(settings))
        return retrieve_hybrid(
            query,
            collection,
            k,
            store=store,
            embedder=_get_embed_model(),
            reranker=_get_reranker(),
        )
    except Exception:
        logger.error("hybrid retrieval unavailable")
        raise _retrieval_unavailable() from None


def _retrieve_endpoint_hits(query: str, collection: str, k: int) -> list[SearchV2Hit]:
    try:
        return [_to_search_hit(hit) for hit in _retrieve_hybrid_hits(query, collection, k)]
    except Exception:
        raise _retrieval_unavailable() from None


def _retrieve_reviewed_hits(query: str, collection: str, k: int) -> list[SearchV2Hit]:
    """Compatibility facade for the evaluation harness; delegates to LOT40."""
    return _retrieve_endpoint_hits(query, collection, k)


def _to_search_hit(hit: HybridHit) -> SearchV2Hit:
    candidate = hit.candidate
    return SearchV2Hit(
        chunk_id=candidate.chunk_id,
        doc_id=candidate.doc_id,
        source_label=candidate.source_label,
        source_uri=candidate.source_uri,
        rights=candidate.rights,
        type_doc=candidate.type_doc,
        review_status=candidate.review_status,
        page=candidate.page_start,
        preview=candidate.text.strip()[:200],
        dense_score=candidate.dense_score,
        lexical_score=candidate.lexical_score,
        rrf_score=hit.rrf_score,
        rerank_score=hit.rerank_score,
        mmr_score=hit.mmr_score,
        score_final=hit.score_final,
    )


def _to_retrieval_result(hit: SearchV2Hit, collection: str) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=hit.chunk_id,
        doc_id=hit.doc_id,
        score=hit.score_final,
        title=hit.source_label,
        excerpt=hit.preview,
        citation=Citation(
            source_label=hit.source_label,
            page=hit.page,
            source_uri=hit.source_uri,
            rights=hit.rights,
        ),
        metadata={
            "collection": collection,
            "type_doc": hit.type_doc,
            "review_status": hit.review_status,
            "dense_score": hit.dense_score,
            "lexical_score": hit.lexical_score,
            "rrf_score": hit.rrf_score,
            "rerank_score": hit.rerank_score,
            "mmr_score": hit.mmr_score,
        },
    )


def _chat_refusal(
    message: str,
    reason: str,
    retrieval_hits: list[RetrievalResult],
) -> ChatResponse:
    return ChatResponse(
        answer=message,
        grounded=False,
        citations=[],
        warnings=[reason],
        refusal_reason=reason,
        retrieval_hits=retrieval_hits,
    )


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Retrieve reviewed evidence while generation remains governance-locked."""
    _enforce_security_v2(
        request,
        allowed_roles={
            SecurityRole.ADMIN,
            SecurityRole.REVIEWER,
            SecurityRole.TEACHER,
            SecurityRole.INGEST_AGENT,
            SecurityRole.STUDENT,
        },
        endpoint="/chat",
    )
    cfg = load_collection_config()
    collections = list(dict.fromkeys(payload.collections))
    for collection in collections:
        try:
            _check_retrievable(collection, cfg)
        except CollectionConfigError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    all_hits: list[tuple[str, SearchV2Hit]] = []
    for collection in collections:
        all_hits.extend(
            (collection, hit)
            for hit in _retrieve_endpoint_hits(payload.query, collection, payload.top_k)
        )

    unique_hits: list[tuple[str, SearchV2Hit]] = []
    seen_chunk_ids: set[str] = set()
    for collection, hit in all_hits:
        if hit.chunk_id not in seen_chunk_ids:
            seen_chunk_ids.add(hit.chunk_id)
            unique_hits.append((collection, hit))
    retrieval_hits = [
        _to_retrieval_result(hit, collection)
        for collection, hit in unique_hits
    ] if payload.include_retrieval else []
    return _chat_refusal(
        "La génération de réponse reste verrouillée par la gouvernance.",
        "answer_generation_locked",
        retrieval_hits,
    )


# --- Main search endpoint ---

@router.post("/search/v2", response_model=SearchV2Response)
def search_v2(payload: SearchV2Request, request: Request) -> SearchV2Response:
    """Retrieval v2: dense + lexical → RRF → rerank → seuil → MMR.

    Canonical pipeline LOT40. Gate retrievable fail-closed (GG-01).
    answer_generation_allowed = false.
    """
    # Auth (LOT 26.3): all roles use reviewed-only visibility.
    _enforce_security_v2(
        request,
        allowed_roles={
            SecurityRole.ADMIN,
            SecurityRole.REVIEWER,
            SecurityRole.TEACHER,
            SecurityRole.INGEST_AGENT,
            SecurityRole.STUDENT,
        },
        endpoint="/search/v2",
    )

    # Gate: resolve + retrievable check (fail-closed)
    cfg = load_collection_config()
    try:
        _check_retrievable(payload.collection, cfg)
    except HTTPException:
        raise
    except CollectionConfigError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    # Public retrieval always re-reads PostgreSQL through the canonical pipeline.
    hits = _retrieve_endpoint_hits(payload.q, payload.collection, payload.k)

    return SearchV2Response(
        query=payload.q,
        collection=payload.collection,
        seuil=RERANK_THRESHOLD,
        returned=len(hits),
        hits=hits,
    )


def _enforce_security_v2(
    request: Request,
    *,
    allowed_roles: set[SecurityRole],
    endpoint: str,
) -> tuple[SecurityRole, str]:
    """Auth check via centralized role gates."""
    return require_role(request, allowed_roles=allowed_roles, endpoint=endpoint)
