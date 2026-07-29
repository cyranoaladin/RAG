"""Retrieval v2 endpoint — FastAPI router (FE-01).

Exposes POST /search/v2 wrapping the certified LOT 24 pipeline:
  resolve_collection_v2 → gate retrievable (fail-closed) → dense e5-large 1024
  → rerank CrossEncoder MiniLM-L-6 → seuil +1.90.

Models are cached at module level (loaded once, not per request).
DSN via PG_RAG_DSN or DATABASE_URL_SYNC env var (R-01: no default).
answer_generation_allowed = false (retrieval only, no LLM generation).
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal, cast

import psycopg  # noqa: F811 — also in requirements.v2.txt
import requests
from fastapi import APIRouter, HTTPException, Request
from nexus_contracts import (
    ChatCitation,
    ChatRequest,
    ChatResponse,
    Citation,
    RetrievalResult,
)
from pydantic import BaseModel, Field

try:
    from .collection_config import (
        CollectionConfigError,
        list_instanciated_collections,
        load_collection_config,
        resolve_collection_v2,
    )
    from .embedding_contract import (
        CANONICAL_EMBED_MODEL,
        load_embedding_model,
    )
    from .security_v2 import SecurityRole, require_role
except (ImportError, ValueError):
    from collection_config import (  # type: ignore[no-redef]
        CollectionConfigError,
        list_instanciated_collections,
        load_collection_config,
        resolve_collection_v2,
    )
    from embedding_contract import (  # type: ignore[no-redef]
        CANONICAL_EMBED_MODEL,
        load_embedding_model,
    )
    from security_v2 import SecurityRole, require_role  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

OPENROUTER_URL = os.environ.get(
    "OPENROUTER_BASE_URL",
    "https://openrouter.ai/api/v1/chat/completions",
)
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini").strip()
OPENROUTER_TIMEOUT_S = int(os.environ.get("OPENROUTER_TIMEOUT_S", "8"))
MIN_COLLECTION_SUBSTANCE_CHUNKS = int(os.environ.get("RAG_MIN_COLLECTION_SUBSTANCE_CHUNKS", "1"))

router = APIRouter(tags=["retrieval_v2"])

# --- Cache retrieval+rerank (SCALE-V1-1) ---
# Key = normalized(query, collection, k). Value = (hits, timestamp).
# Invalidation: TTL-based (chunks may change review_status).
#
# IMPORTANT: cache is per-process. With N uvicorn workers,
# POST /cache/v2/invalidate only clears the worker handling that request.
# A chunk quarantined after caching could still be served by other workers
# until TTL expires.
#
# Safety rule: in production (RAG_ENV=production), cache is DISABLED by default
# to guarantee zero stale-after-quarantine risk. To enable in production,
# set RERANK_CACHE=1 explicitly (only if cross-worker invalidation is in place).
_rag_env_cache = (os.environ.get("RAG_ENV") or "").strip().lower()
CACHE_TTL_S = int(os.environ.get("RERANK_CACHE_TTL", "300"))  # 5 min default
if _rag_env_cache == "production":
    CACHE_ENABLED = os.environ.get("RERANK_CACHE", "0") == "1"
else:
    CACHE_ENABLED = os.environ.get("RERANK_CACHE", "1") != "0"
_cache: dict[str, tuple[list, float]] = {}
_cache_lock = threading.Lock()
_cache_hits = 0
_cache_misses = 0


def _filter_reviewed_candidates(candidates: list[tuple]) -> list[tuple]:
    """Keep only reviewed candidates in case DB returns unexpected statuses."""
    return [candidate for candidate in candidates if candidate[8] == "reviewed"]


def _format_embedding_query(text: str) -> str:
    try:
        from nexus_contracts.embedding_utils import format_query
    except (ImportError, ModuleNotFoundError) as exc:
        raise HTTPException(
            status_code=503,
            detail="/search/v2: embedding query formatter unavailable",
        ) from exc
    return cast(str, format_query(text))


def _cache_key(query: str, collection: str, k: int) -> str:
    """Normalized cache key. Lowercased, stripped, unicode-normalized."""
    import unicodedata
    normalized = unicodedata.normalize("NFKC", query).strip().lower()
    # Collapse curly quotes/apostrophes to ASCII equivalents
    normalized = normalized.replace("\u2019", "'").replace("\u2018", "'")
    normalized = normalized.replace("\u201c", '"').replace("\u201d", '"')
    raw = f"{normalized}|{collection}|{k}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_get(key: str) -> list | None:
    global _cache_hits
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        hits, ts = entry
        if time.monotonic() - ts > CACHE_TTL_S:
            del _cache[key]
            return None
        _cache_hits += 1
        return hits


def _cache_put(key: str, hits: list) -> None:
    with _cache_lock:
        _cache[key] = (hits, time.monotonic())


def invalidate_cache() -> int:
    """Invalidate all cache entries. Called when review_status changes."""
    with _cache_lock:
        n = len(_cache)
        _cache.clear()
        return n

# --- Configuration figée (D-CONFIG-RETRIEVAL-PREPROD, LAT-05) ---
# Seuil rerank: +1.90 (LOT 24 FF-02b, marge 1.00 LOT 25a)
RERANK_SCORE_THRESHOLD = float(os.environ.get("RERANK_SCORE_THRESHOLD", "1.90"))
# Reranker: MiniLM-L-6 conservé (L-2 écarté: marge 1.00→0.71)
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
# Embedding: e5-large 1024 dim
EMBED_MODEL = CANONICAL_EMBED_MODEL
# Pool rerank: 10 candidats (V1-5: 15/15 in, 10/10 out, marge +5.69 vs +4.07 à RC=20)
# Latence miss: 0.43s rerank (vs 0.84s à RC=20) — divise le coût miss par 2
RERANK_CANDIDATES = int(os.environ.get("RERANK_CANDIDATES", "10"))

CHAT_MIN_SUBSTANCE_CHUNKS = int(os.environ.get("CHAT_MIN_SUBSTANCE_CHUNKS", "1"))

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
    chunk_id: str
    doc_id: str
    source_label: str
    source_uri: str
    rights: str
    type_doc: str
    review_status: Literal["reviewed"]  # SCALE-04: reviewed only
    preview: str
    rerank_score: float
    dense_sim: float


class SearchV2Response(BaseModel):
    query: str
    collection: str
    seuil: float
    returned: int
    answer_generation_allowed: bool = False
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
            "hits": _cache_hits,
            "misses": _cache_misses,
            "hit_rate": round(_cache_hits / max(_cache_hits + _cache_misses, 1), 3),
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

    Runs retrieval+rerank for a set of probable queries and caches results.
    Call at startup or after invalidation to eliminate cold-start misses.
    """
    _enforce_security_v2(
        request,
        allowed_roles={SecurityRole.ADMIN, SecurityRole.REVIEWER},
        endpoint="/cache/v2/warmup",
    )

    cfg = load_collection_config()
    collections = list_instanciated_collections(cfg)
    # Only warm retrievable collections
    domains = cfg.get("domains", {})
    retrievable_cols = []
    for name in collections:
        try:
            defn = resolve_collection_v2(name, cfg)
        except Exception:
            continue
        domain = defn.get("domain")
        if isinstance(domain, str) and isinstance(domains.get(domain), dict):
            if domains[domain].get("retrievable") is True:
                retrievable_cols.append(name)

    # Common pedagogical queries derived from NSI programme
    warmup_queries = [
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
    ]

    warmed = 0
    for col in retrievable_cols:
        for q in warmup_queries:
            key = _cache_key(q, col, 5)
            if _cache_get(key) is not None:
                continue  # Already cached
            # Full pipeline: embed → dense → rerank → cache
            from nexus_contracts.embedding_utils import format_query
            pg_dsn = _get_pg_dsn()
            embed_model = _get_embed_model()
            q_vec = embed_model.encode(format_query(q), normalize_embeddings=True)
            vec_str = "[" + ",".join(str(float(v)) for v in q_vec) + "]"
            try:
                conn = psycopg.connect(pg_dsn)
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT chunk_id, doc_id, source_label, source_uri, rights, type_doc,
                               text, 1 - (vector <=> %s::vector) AS sim, review_status
                        FROM rag_chunks
                        WHERE collection = %s AND review_status = 'reviewed'
                        ORDER BY vector <=> %s::vector LIMIT %s
                    """, (vec_str, col, vec_str, RERANK_CANDIDATES))
                    candidates = _filter_reviewed_candidates(cur.fetchall())
                conn.close()
            except Exception:
                continue
            if not candidates:
                continue
            reranker = _get_reranker()
            pairs = [(q, c[6] or "") for c in candidates]
            rerank_scores = reranker.predict(pairs)
            hits_data = []
            for candidate, score in sorted(
                zip(candidates, rerank_scores, strict=False), key=lambda x: x[1], reverse=True
            ):
                if candidate[8] != "reviewed":
                    continue
                if float(score) < RERANK_SCORE_THRESHOLD:
                    continue
                hits_data.append(SearchV2Hit(
                    chunk_id=candidate[0], doc_id=candidate[1],
                    source_label=candidate[2] or "", source_uri=candidate[3] or "",
                    rights=candidate[4] or "", type_doc=candidate[5] or "",
                    review_status="reviewed",
                    preview=(candidate[6] or "")[:200],
                    rerank_score=round(float(score), 4),
                    dense_sim=round(float(candidate[7]), 4),
                ).model_dump())
                if len(hits_data) >= 5:
                    break
            if hits_data:
                _cache_put(key, hits_data)
                warmed += 1

    return {"warmed": warmed, "collections": len(retrievable_cols), "queries": len(warmup_queries)}


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


def _retrieve_reviewed_hits(query: str, collection: str, k: int) -> list[SearchV2Hit]:
    """Run the certified retrieval pipeline after callers applied their gates."""
    pg_dsn = _get_pg_dsn()
    formatted_query = _format_embedding_query(query)
    embed_model = _get_embed_model()
    q_vec = embed_model.encode(formatted_query, normalize_embeddings=True)
    vec_str = "[" + ",".join(str(float(v)) for v in q_vec) + "]"

    try:
        conn = psycopg.connect(pg_dsn)
    except Exception as exc:
        logger.error("pgvector connection failed: %s", exc)
        raise HTTPException(status_code=503, detail="pgvector connection failed") from exc

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT chunk_id, doc_id, source_label, source_uri, rights, type_doc,
                       text, 1 - (vector <=> %s::vector) AS sim, review_status
                FROM rag_chunks
                WHERE collection = %s AND review_status = 'reviewed'
                ORDER BY vector <=> %s::vector
                LIMIT %s
                """,
                (vec_str, collection, vec_str, RERANK_CANDIDATES),
            )
            candidates = _filter_reviewed_candidates(cur.fetchall())
    finally:
        conn.close()

    if not candidates:
        return []

    pairs = [(query, candidate[6] or "") for candidate in candidates]
    rerank_scores = _get_reranker().predict(pairs)
    hits: list[SearchV2Hit] = []
    for candidate, score in sorted(
        zip(candidates, rerank_scores, strict=False), key=lambda item: item[1], reverse=True,
    ):
        if candidate[8] != "reviewed" or float(score) < RERANK_SCORE_THRESHOLD:
            continue
        hits.append(
            SearchV2Hit(
                chunk_id=candidate[0],
                doc_id=candidate[1],
                source_label=candidate[2] or "",
                source_uri=candidate[3] or "",
                rights=candidate[4] or "",
                type_doc=candidate[5] or "",
                review_status="reviewed",
                preview=(candidate[6] or "")[:200],
                rerank_score=round(float(score), 4),
                dense_sim=round(float(candidate[7]), 4),
            ),
        )
        if len(hits) >= k:
            break
    return hits


def _to_retrieval_result(hit: SearchV2Hit, collection: str) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=hit.chunk_id,
        doc_id=hit.doc_id,
        score=max(hit.rerank_score, 0.0),
        title=hit.source_label or None,
        excerpt=hit.preview,
        citation=Citation(
            source_label=hit.source_label,
            source_uri=hit.source_uri,
            rights=hit.rights,
        ) if hit.source_label and hit.source_uri and hit.rights else None,
        metadata={
            "collection": collection,
            "type_doc": hit.type_doc,
            "review_status": hit.review_status,
            "dense_sim": hit.dense_sim,
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


def _openrouter_answer(payload: ChatRequest, hits: list[SearchV2Hit]) -> str | None:
    """Generate only from reviewed excerpts; never send the learner profile upstream."""
    if not OPENROUTER_API_KEY:
        return None
    source_context = "\n\n".join(
        (
            f"[S{index}] {hit.source_label}\n"
            f"URI: {hit.source_uri}\n"
            f"Extrait: {hit.preview}"
        )
        for index, hit in enumerate(hits, start=1)
    )
    system_prompt = (
        "Tu es un assistant pédagogique français. Réponds uniquement à partir "
        "des sources ci-dessous. Toute affirmation factuelle doit citer une source "
        "au format [S1]. Si les sources ne suffisent pas, dis-le clairement. "
        "N'invente ni citation ni information.\n\nSources:\n"
        f"{source_context}"
    )
    history = [
        {"role": message.role, "content": message.content}
        for message in payload.history[-12:]
        if message.role in {"user", "assistant"}
    ]
    messages = [{"role": "system", "content": system_prompt}, *history, {
        "role": "user", "content": payload.query,
    }]
    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": messages,
                "max_tokens": max(100, min(1000, payload.answer_max_chars // 3)),
                "temperature": 0.2,
            },
            timeout=OPENROUTER_TIMEOUT_S,
        )
        if not response.ok:
            logger.warning("OpenRouter request failed with status %s", response.status_code)
            return None
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        return content.strip() if isinstance(content, str) and content.strip() else None
    except (KeyError, IndexError, TypeError, ValueError, requests.RequestException):
        logger.warning("OpenRouter response unavailable", exc_info=True)
        return None


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Return a cited OpenRouter answer or an explicit, non-factual refusal."""
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
    all_hits: list[tuple[str, SearchV2Hit]] = []
    for collection in dict.fromkeys(payload.collections):
        try:
            _check_retrievable(collection, cfg)
        except CollectionConfigError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        all_hits.extend((collection, hit) for hit in _retrieve_reviewed_hits(payload.query, collection, payload.top_k))

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
    source_hits = [hit for _, hit in unique_hits]
    if len(source_hits) < CHAT_MIN_SUBSTANCE_CHUNKS:
        return _chat_refusal(
            "Je ne peux pas répondre de manière fiable : les sources validées sont insuffisantes.",
            "insufficient_reviewed_evidence",
            retrieval_hits,
        )

    answer = _openrouter_answer(payload, source_hits)
    if not answer:
        return _chat_refusal(
            "La réponse conversationnelle est temporairement indisponible.",
            "generation_unavailable",
            retrieval_hits,
        )
    cited_indexes = {int(match) for match in re.findall(r"\[S(\d+)\]", answer)}
    if not cited_indexes or any(index < 1 or index > len(source_hits) for index in cited_indexes):
        return _chat_refusal(
            "Je ne peux pas répondre de manière fiable sans citation vérifiable.",
            "missing_or_invalid_citations",
            retrieval_hits,
        )
    citations = [
        ChatCitation(
            chunk_id=source_hits[index - 1].chunk_id,
            doc_id=source_hits[index - 1].doc_id,
            source_label=source_hits[index - 1].source_label,
            source_uri=source_hits[index - 1].source_uri,
            rights=source_hits[index - 1].rights,
        )
        for index in sorted(cited_indexes)
    ]
    if any(not citation.source_label or not citation.source_uri or not citation.rights for citation in citations):
        return _chat_refusal(
            "Je ne peux pas répondre de manière fiable sans provenance complète.",
            "incomplete_citation_provenance",
            retrieval_hits,
        )
    return ChatResponse(
        answer=answer,
        grounded=True,
        citations=citations,
        warnings=[],
        retrieval_hits=retrieval_hits,
    )


# --- Main search endpoint ---

@router.post("/search/v2", response_model=SearchV2Response)
def search_v2(payload: SearchV2Request, request: Request) -> SearchV2Response:
    """Retrieval v2: dense e5-large → rerank CrossEncoder → seuil +1.90.

    Certified pipeline LOT 24. Gate retrievable fail-closed (GG-01).
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

    # Cache check (SCALE-V1-1)
    global _cache_misses
    cache_k = _cache_key(payload.q, payload.collection, payload.k) if CACHE_ENABLED else ""

    # LOT 26.2 fail-closed: do not serve student/public search from cache.
    # A cached hit may have lost review_status=reviewed after caching.
    # Cache serving can be reintroduced only with DB revalidation of current statuses.
    if CACHE_ENABLED:
        _cache_misses += 1

    # Get DSN (R-01: no default)
    pg_dsn = _get_pg_dsn()

    # Embedding
    formatted_query = _format_embedding_query(payload.q)
    embed_model = _get_embed_model()
    q_vec = embed_model.encode(formatted_query, normalize_embeddings=True)
    vec_str = "[" + ",".join(str(float(v)) for v in q_vec) + "]"

    # Dense retrieval (top RERANK_CANDIDATES)
    try:
        conn = psycopg.connect(pg_dsn)
    except Exception as exc:
        logger.error("pgvector connection failed: %s", exc)
        raise HTTPException(status_code=503, detail="pgvector connection failed") from exc

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT chunk_id, doc_id, source_label, source_uri, rights, type_doc,
                       text, 1 - (vector <=> %s::vector) AS sim, review_status
                FROM rag_chunks
                WHERE collection = %s AND review_status = 'reviewed'
                ORDER BY vector <=> %s::vector
                LIMIT %s
            """, (vec_str, payload.collection, vec_str, RERANK_CANDIDATES))
            candidates = _filter_reviewed_candidates(cur.fetchall())
    finally:
        conn.close()

    if not candidates:
        return SearchV2Response(
            query=payload.q,
            collection=payload.collection,
            seuil=RERANK_SCORE_THRESHOLD,
            returned=0,
            hits=[],
        )

    # Rerank with CrossEncoder
    # FF-02: pass FULL chunk text — let the model's max_length=512 TOKENS handle truncation.
    pairs = [(payload.q, c[6] or "") for c in candidates]
    reranker = _get_reranker()
    rerank_scores = reranker.predict(pairs)

    # Filter by seuil + sort
    hits: list[SearchV2Hit] = []
    for candidate, score in sorted(
        zip(candidates, rerank_scores, strict=False), key=lambda x: x[1], reverse=True
    ):
        if candidate[8] != "reviewed":
            continue
        if float(score) < RERANK_SCORE_THRESHOLD:
            continue
        hits.append(SearchV2Hit(
            chunk_id=candidate[0],
            doc_id=candidate[1],
            source_label=candidate[2] or "",
            source_uri=candidate[3] or "",
            rights=candidate[4] or "",
            type_doc=candidate[5] or "",
            review_status="reviewed",
            preview=(candidate[6] or "")[:200],
            rerank_score=round(float(score), 4),
            dense_sim=round(float(candidate[7]), 4),
        ))
        if len(hits) >= payload.k:
            break

    # Cache store (SCALE-V1-1)
    if CACHE_ENABLED and hits:
        _cache_put(cache_k, [h.model_dump() for h in hits])

    return SearchV2Response(
        query=payload.q,
        collection=payload.collection,
        seuil=RERANK_SCORE_THRESHOLD,
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
