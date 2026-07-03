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
import threading
import time
from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .collection_config import (
    CollectionConfigError,
    list_instanciated_collections,
    load_collection_config,
    resolve_collection_v2,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["retrieval_v2"])

# --- Cache retrieval+rerank (SCALE-V1-1) ---
# Key = normalized(query, collection, k). Value = (hits, timestamp).
# Invalidation: TTL-based (chunks may change review_status).
# A chunk that becomes quarantined is never served from cache after TTL expires.
CACHE_TTL_S = int(os.environ.get("RERANK_CACHE_TTL", "300"))  # 5 min default
CACHE_ENABLED = os.environ.get("RERANK_CACHE", "1") != "0"
_cache: dict[str, tuple[list, float]] = {}
_cache_lock = threading.Lock()
_cache_hits = 0
_cache_misses = 0


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
EMBED_MODEL = "intfloat/multilingual-e5-large"
# Pool rerank: 10 candidats (V1-5: 15/15 in, 10/10 out, marge +5.69 vs +4.07 à RC=20)
# Latence miss: 0.43s rerank (vs 0.84s à RC=20) — divise le coût miss par 2
RERANK_CANDIDATES = int(os.environ.get("RERANK_CANDIDATES", "10"))

# --- Lazy-loaded models (cached at module level) ---
_embed_model = None
_reranker = None


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model %s (one-time)", EMBED_MODEL)
        _embed_model = SentenceTransformer(EMBED_MODEL)
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
    review_status: str  # SCALE-04: reviewed | needs_review (quarantined never served)
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


# --- Cache management endpoints ---

@router.get("/cache/v2/stats")
def cache_stats() -> dict[str, Any]:
    """Cache statistics for monitoring."""
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
    _enforce_security_v2(request)
    n = invalidate_cache()
    return {"invalidated": n}


@router.post("/cache/v2/warmup")
def cache_warmup(request: Request) -> dict[str, Any]:
    """Pre-warm cache with common pedagogical queries (SCALE-V1-6).

    Runs retrieval+rerank for a set of probable queries and caches results.
    Call at startup or after invalidation to eliminate cold-start misses.
    """
    _enforce_security_v2(request)

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
            embed_model = _get_embed_model()
            q_vec = embed_model.encode(format_query(q), normalize_embeddings=True)
            vec_str = "[" + ",".join(str(float(v)) for v in q_vec) + "]"
            pg_dsn = _get_pg_dsn()
            try:
                conn = psycopg.connect(pg_dsn)
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT chunk_id, doc_id, source_label, source_uri, rights, type_doc,
                               text, 1 - (vector <=> %s::vector) AS sim, review_status
                        FROM rag_chunks
                        WHERE collection = %s AND review_status IN ('reviewed', 'needs_review')
                        ORDER BY vector <=> %s::vector LIMIT %s
                    """, (vec_str, col, vec_str, RERANK_CANDIDATES))
                    candidates = cur.fetchall()
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
                if float(score) < RERANK_SCORE_THRESHOLD:
                    continue
                hits_data.append(SearchV2Hit(
                    chunk_id=candidate[0], doc_id=candidate[1],
                    source_label=candidate[2] or "", source_uri=candidate[3] or "",
                    rights=candidate[4] or "", type_doc=candidate[5] or "",
                    review_status=candidate[8] or "",
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

@router.get("/collections/v2")
def list_retrievable_collections() -> dict[str, Any]:
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


# --- Main search endpoint ---

@router.post("/search/v2", response_model=SearchV2Response)
def search_v2(payload: SearchV2Request, request: Request) -> SearchV2Response:
    """Retrieval v2: dense e5-large → rerank CrossEncoder → seuil +1.90.

    Certified pipeline LOT 24. Gate retrievable fail-closed (GG-01).
    answer_generation_allowed = false.
    """
    # Auth: same Bearer token as legacy endpoints
    _enforce_security_v2(request)

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
    if CACHE_ENABLED:
        cached = _cache_get(cache_k)
        if cached is not None:
            return SearchV2Response(
                query=payload.q,
                collection=payload.collection,
                seuil=RERANK_SCORE_THRESHOLD,
                returned=len(cached),
                hits=[SearchV2Hit(**h) for h in cached],
            )
        _cache_misses += 1

    # Get DSN (R-01: no default)
    pg_dsn = _get_pg_dsn()

    # Embedding
    from nexus_contracts.embedding_utils import format_query

    embed_model = _get_embed_model()
    q_vec = embed_model.encode(format_query(payload.q), normalize_embeddings=True)
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
                WHERE collection = %s AND review_status IN ('reviewed', 'needs_review')
                ORDER BY vector <=> %s::vector
                LIMIT %s
            """, (vec_str, payload.collection, vec_str, RERANK_CANDIDATES))
            candidates = cur.fetchall()
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
        if float(score) < RERANK_SCORE_THRESHOLD:
            continue
        hits.append(SearchV2Hit(
            chunk_id=candidate[0],
            doc_id=candidate[1],
            source_label=candidate[2] or "",
            source_uri=candidate[3] or "",
            rights=candidate[4] or "",
            type_doc=candidate[5] or "",
            review_status=candidate[8] or "",
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


def _enforce_security_v2(request: Request) -> None:
    """Auth check — same token as legacy endpoints."""
    token_env = os.getenv("INGESTOR_API_TOKEN") or os.getenv("INGEST_AUTH_TOKEN")
    if not token_env:
        raise HTTPException(status_code=503, detail="API token not configured")

    headers = request.headers
    header_token = headers.get("x-api-token")
    if not header_token:
        auth = headers.get("authorization")
        if isinstance(auth, str) and auth.strip():
            value = auth.strip()
            if value.lower().startswith("bearer "):
                header_token = value.split(" ", 1)[1].strip()
            else:
                header_token = value
    if header_token != token_env:
        raise HTTPException(status_code=401, detail="Unauthorized")
