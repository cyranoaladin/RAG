"""Ingestion pipeline v2 — governance-compliant write path (FE-03).

All 3 ingestion routes (upload, URLs, Drive) call this pipeline.
Guarantees:
- resolve_collection_v2 (no auto-creation, instanciee required)
- F-01 (rights, source_label, doc_id non NULL)
- review_status = needs_review (never servable without human review)
- Provenance (route, timestamp, token hash)
- Heading-aware chunking (pedagogical_chunker)
- e5-large 1024 dim embedding (same as retrieval)
- Base64/artifact filtering
- pgvector write (rag_chunks table)
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass

import psycopg
from pydantic import BaseModel, Field

try:
    from .collection_config import (
        CollectionConfigError,
        load_collection_config,
        resolve_collection_v2,
    )
    from .embedding_contract import (
        CANONICAL_EMBED_MODEL,
        EmbeddingContractError,
        load_embedding_model,
        validate_runtime_embedding_contract,
    )
    from .pedagogical_chunker import (
        RawChunk,
        TaggingConfig,
        _flatten_section,
        parse_sections,
        tag_chunk,
    )
except (ImportError, ValueError):
    from collection_config import (  # type: ignore[no-redef]
        CollectionConfigError,
        load_collection_config,
        resolve_collection_v2,
    )
    from embedding_contract import (  # type: ignore[no-redef]
        CANONICAL_EMBED_MODEL,
        EmbeddingContractError,
        load_embedding_model,
        validate_runtime_embedding_contract,
    )
    from pedagogical_chunker import (  # type: ignore[no-redef]
        RawChunk,
        TaggingConfig,
        _flatten_section,
        parse_sections,
        tag_chunk,
    )

logger = logging.getLogger(__name__)

EMBED_MODEL = CANONICAL_EMBED_MODEL
_embed_model = None


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        logger.info("Loading embedding model %s (one-time, ingest)", EMBED_MODEL)
        _embed_model = load_embedding_model()
    return _embed_model


def _get_pg_dsn() -> str:
    dsn = os.environ.get("PG_RAG_DSN") or os.environ.get("DATABASE_URL_SYNC")
    if not dsn:
        raise RuntimeError("PG_RAG_DSN or DATABASE_URL_SYNC not configured")
    return dsn


# --- Collection ingestion quota (LOT43) ---

MAX_CHUNKS_PER_COLLECTION_PER_DAY = int(
    os.environ.get("MAX_CHUNKS_PER_COLLECTION_PER_DAY", 5000)
)


class CollectionQuotaExceededError(ValueError):
    """Raised when a collection's ingestion quota for the current period is exceeded."""


def _count_recent_chunks(collection: str, pg_dsn: str) -> int:
    """Count chunks indexed for a collection in the last 24h (rolling window)."""
    conn = psycopg.connect(pg_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM rag_chunks "
                "WHERE collection = %s AND indexed_at > now() - interval '1 day'",
                (collection,),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0
    finally:
        conn.close()


def _check_collection_quota(collection: str, pg_dsn: str) -> None:
    limit = MAX_CHUNKS_PER_COLLECTION_PER_DAY
    if limit <= 0:
        return
    count = _count_recent_chunks(collection, pg_dsn)
    if count >= limit:
        raise CollectionQuotaExceededError(
            f"Collection quota exceeded: '{collection}' has {count} chunks "
            f"indexed in the last 24h (limit {limit})"
        )


# --- Server-side scope defaults (LOT43, provisional) ---
#
# tenant/candidat/visibility/school_year/programme_version are governed scope
# columns (LOT41, migration 003_profile_filtering.sql) that ingest_document
# never populated: every v2-ingested chunk had them NULL. Retrieval filters
# with e.g. `WHERE c.tenant = $2` (database.py), and NULL never satisfies an
# equality comparison in SQL — so no chunk ingested via /ingest/v2 could ever
# be returned by a tenant-scoped search, even after human review.
#
# This is a MINIMAL, server-side, fail-closed fix: one configured default
# value per dimension for the whole deployment. It does NOT model true
# multi-tenancy or per-collection population — `candidat` genuinely varies
# per collection per the tenant naming convention `{population}_{niveau}`
# documented in AGENTS.md (e.g. libre_terminale, aefe_seconde). Modelling
# that properly requires extending the 59-entry collection catalogue
# (configs/rag_collections.yml) with a governed per-collection scope and a
# dedicated ADR — tracked as a known limitation, not implemented here.
_ALLOWED_CANDIDAT = {
    "scolarise", "individuel", "libre", "cned_reglemente",
    "cned_libre", "aefe", "both",
}
_ALLOWED_VISIBILITY = {"public", "internal", "restricted", "private"}
_SCHOOL_YEAR_RE = re.compile(r"^(\d{4})-(\d{4})$")


class ScopeConfigurationError(RuntimeError):
    """Raised when the server-side default ingestion scope is missing or invalid."""


@dataclass(frozen=True)
class DefaultScope:
    tenant: str
    candidat: str
    visibility: str
    school_year: str
    programme_version: str


def _get_default_scope() -> DefaultScope:
    """Read and validate the deployment-wide default scope from the environment.

    Fails closed (raises) rather than writing any of these columns as NULL
    or guessing a value — matches AGENTS.md: "toute ambiguïté doit produire
    une quarantaine, jamais une affectation arbitraire".
    """
    tenant = os.environ.get("NEXUS_DEFAULT_TENANT", "").strip()
    candidat = os.environ.get("NEXUS_DEFAULT_CANDIDAT", "").strip()
    visibility = os.environ.get("NEXUS_DEFAULT_VISIBILITY", "").strip()
    school_year = os.environ.get("NEXUS_DEFAULT_SCHOOL_YEAR", "").strip()
    programme_version = os.environ.get("NEXUS_DEFAULT_PROGRAMME_VERSION", "").strip()

    missing = [
        name
        for name, value in (
            ("NEXUS_DEFAULT_TENANT", tenant),
            ("NEXUS_DEFAULT_CANDIDAT", candidat),
            ("NEXUS_DEFAULT_VISIBILITY", visibility),
            ("NEXUS_DEFAULT_SCHOOL_YEAR", school_year),
            ("NEXUS_DEFAULT_PROGRAMME_VERSION", programme_version),
        )
        if not value
    ]
    if missing:
        raise ScopeConfigurationError(
            f"Missing required scope configuration: {', '.join(missing)}"
        )
    if candidat not in _ALLOWED_CANDIDAT:
        raise ScopeConfigurationError(f"NEXUS_DEFAULT_CANDIDAT invalid: {candidat!r}")
    if visibility not in _ALLOWED_VISIBILITY:
        raise ScopeConfigurationError(f"NEXUS_DEFAULT_VISIBILITY invalid: {visibility!r}")
    match = _SCHOOL_YEAR_RE.match(school_year)
    if not match or int(match.group(2)) != int(match.group(1)) + 1:
        raise ScopeConfigurationError(f"NEXUS_DEFAULT_SCHOOL_YEAR invalid: {school_year!r}")

    return DefaultScope(
        tenant=tenant,
        candidat=candidat,
        visibility=visibility,
        school_year=school_year,
        programme_version=programme_version,
    )


# --- Base64/artifact filter (LOT 25a) ---
_BASE64_RE = re.compile(r"[A-Za-z0-9+/=]{40,}")


def _is_artifact(text: str) -> bool:
    """Return True if chunk is mostly base64 or non-textual."""
    if not text.strip():
        return True
    alnum = sum(1 for c in text if c.isalnum())
    total = sum(1 for c in text if not c.isspace())
    if total == 0:
        return True
    ratio = alnum / total
    if ratio < 0.5:
        return True
    # Check base64 density
    b64_chars = sum(len(m.group()) for m in _BASE64_RE.finditer(text))
    if b64_chars > len(text) * 0.5:
        return True
    return False


# --- Request model ---

class IngestV2Request(BaseModel):
    """Request to ingest a document via the v2 pipeline."""
    collection: str = Field(..., min_length=1)
    source_label: str = Field(..., min_length=1)
    source_uri: str = Field(..., min_length=1)
    rights: str = Field(..., min_length=1)
    type_doc: str = Field(default="cours")
    matiere: str = Field(..., min_length=1)
    niveau: str = Field(..., min_length=1)
    voie: str = Field(default="gen")
    audience: list[str] = Field(default_factory=lambda: ["tous"])
    official: bool = False


@dataclass
class IngestV2Result:
    """Result of an ingestion."""
    doc_id: str
    chunks_total: int
    chunks_written: int
    chunks_filtered: int  # base64/artifact
    chunks_dedup: int  # already existed
    collection: str
    review_status: str = "needs_review"


@dataclass
class Provenance:
    """Provenance tracking for each ingestion."""
    route: str  # "upload" | "urls" | "drive"
    timestamp: float
    token_hash: str  # Short SHA256 fingerprint of the complete token (R-01)
    source_type: str  # "file" | "url" | "gdrive"


def ingest_document(
    text: str,
    request: IngestV2Request,
    provenance: Provenance,
    *,
    doc_id: str | None = None,
) -> IngestV2Result:
    """Ingest a single document through the v2 pipeline.

    1. Validate collection (resolve_collection_v2, fail if not instanciated)
    2. Chunk with heading-aware chunker
    3. Filter base64/artifacts
    4. Embed with e5-large 1024
    5. Write to pgvector with F-01 metadata + review_status=needs_review
    """
    from nexus_contracts.embedding_utils import format_passage

    # --- Gate: collection must be instanciated ---
    cfg = load_collection_config()
    try:
        defn = resolve_collection_v2(request.collection, cfg)
    except CollectionConfigError as exc:
        raise ValueError(f"Collection gate: {exc}") from exc

    # --- Gate: collection ingestion quota (fail fast, before chunking/embedding) ---
    pg_dsn = _get_pg_dsn()
    _check_collection_quota(request.collection, pg_dsn)

    # --- Gate: server-side default scope (LOT43, provisional — see comment above) ---
    default_scope = _get_default_scope()

    # --- Generate doc_id ---
    if not doc_id:
        doc_id = hashlib.sha256(
            f"{request.collection}|{request.source_uri}|{request.source_label}".encode()
        ).hexdigest()

    # --- Chunk ---
    sections = parse_sections(text)
    raw_chunks: list[RawChunk] = []
    for section in sections:
        raw_chunks.extend(_flatten_section(section))

    # If no sections found (e.g., plain text), create a single chunk
    if not raw_chunks:
        raw_chunks = [RawChunk(text=text, section_path=[], section_title="")]

    # --- Tag ---
    tagging = TaggingConfig(
        doc_id=doc_id,
        matiere=request.matiere,
        audience=request.audience,
        type_doc_default=request.type_doc,
        source_label=request.source_label,
        source_uri=request.source_uri,
        rights=request.rights,
        official=request.official,
    )
    tagged = [tag_chunk(raw, tagging, i) for i, raw in enumerate(raw_chunks)]

    # --- Filter base64/artifacts ---
    clean = []
    filtered_count = 0
    for chunk in tagged:
        if _is_artifact(chunk["text"]):
            filtered_count += 1
            continue
        clean.append(chunk)

    if not clean:
        return IngestV2Result(
            doc_id=doc_id,
            chunks_total=len(tagged),
            chunks_written=0,
            chunks_filtered=filtered_count,
            chunks_dedup=0,
            collection=request.collection,
        )

    # --- Embed ---
    embed_model = _get_embed_model()
    try:
        validate_runtime_embedding_contract(embed_model, pg_dsn)
    except EmbeddingContractError as exc:
        raise ValueError(f"Embedding contract: {exc}") from exc
    texts_to_embed = [format_passage(c["text"]) for c in clean]
    vectors = embed_model.encode(texts_to_embed, normalize_embeddings=True)

    # --- Write to pgvector ---
    conn = psycopg.connect(pg_dsn)

    written = 0
    dedup = 0
    try:
        with conn.cursor() as cur:
            for i, chunk in enumerate(clean):
                chunk_text = chunk["text"].replace("\x00", "")
                chunk_sha = hashlib.sha256(chunk_text.encode()).hexdigest()
                chunk_id = f"{doc_id}_{i:04d}"
                meta = chunk["metadata"]
                vec = vectors[i]
                vec_str = "[" + ",".join(str(float(v)) for v in vec) + "]"

                cur.execute("""
                    INSERT INTO rag_chunks (
                        chunk_id, doc_id, chunk_sha256, vector,
                        collection, niveau, voie, audience, matiere,
                        statut_enseignement, domain,
                        source_label, source_uri, rights, type_doc, official,
                        text, chunk_index, review_status, model, source_kind,
                        tenant, candidat, visibility, school_year, programme_version
                    ) VALUES (
                        %s, %s, %s, %s::vector,
                        %s, %s, %s, %s, %s,
                        %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        chunk_sha256 = EXCLUDED.chunk_sha256,
                        vector = EXCLUDED.vector,
                        collection = EXCLUDED.collection,
                        niveau = EXCLUDED.niveau,
                        voie = EXCLUDED.voie,
                        audience = EXCLUDED.audience,
                        matiere = EXCLUDED.matiere,
                        statut_enseignement = EXCLUDED.statut_enseignement,
                        domain = EXCLUDED.domain,
                        source_label = EXCLUDED.source_label,
                        source_uri = EXCLUDED.source_uri,
                        rights = EXCLUDED.rights,
                        type_doc = EXCLUDED.type_doc,
                        official = EXCLUDED.official,
                        text = EXCLUDED.text,
                        review_status = 'needs_review',
                        model = EXCLUDED.model,
                        source_kind = EXCLUDED.source_kind,
                        tenant = EXCLUDED.tenant,
                        candidat = EXCLUDED.candidat,
                        visibility = EXCLUDED.visibility,
                        school_year = EXCLUDED.school_year,
                        programme_version = EXCLUDED.programme_version,
                        indexed_at = NOW()
                    WHERE rag_chunks.chunk_sha256 <> EXCLUDED.chunk_sha256
                       OR rag_chunks.collection <> EXCLUDED.collection
                       OR rag_chunks.rights <> EXCLUDED.rights
                       OR rag_chunks.review_status <> 'needs_review'
                """, (
                    chunk_id, doc_id, chunk_sha, vec_str,
                    request.collection, request.niveau, request.voie,
                    request.audience, request.matiere,
                    defn.get("statut", "unknown"),
                    defn.get("domain", "education"),
                    request.source_label, request.source_uri,
                    request.rights, meta.get("type_doc", request.type_doc),
                    request.official,
                    chunk_text, i,
                    "needs_review",  # ALWAYS needs_review
                    EMBED_MODEL, provenance.source_type,
                    default_scope.tenant, default_scope.candidat,
                    default_scope.visibility, default_scope.school_year,
                    default_scope.programme_version,
                ))
                if cur.rowcount > 0:
                    written += 1
                else:
                    dedup += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    logger.info(
        "Ingested doc_id=%s collection=%s chunks=%d written=%d filtered=%d dedup=%d "
        "route=%s actor=%s",
        doc_id, request.collection, len(tagged), written, filtered_count, dedup,
        provenance.route, provenance.token_hash,
    )

    return IngestV2Result(
        doc_id=doc_id,
        chunks_total=len(tagged),
        chunks_written=written,
        chunks_filtered=filtered_count,
        chunks_dedup=dedup,
        collection=request.collection,
    )
