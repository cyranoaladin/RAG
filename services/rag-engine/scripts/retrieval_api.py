#!/usr/bin/env python3
"""Retrieval API — read-only search over pgvector (ADR-0011).

Filtrage niveau/audience IMPOSÉ par le serveur selon le profil SIGNÉ (HMAC).
Le client fournit uniquement la requête textuelle. Aucune route d'écriture.
Le profil est transporté via un jeton signé HMAC-SHA256 avec un secret serveur.

Gated by server_start_allowed AND runtime_api_allowed (rag-pedago contract).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import psycopg.errors
import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Paths (cross-service, ADR-0010)
# ---------------------------------------------------------------------------
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
PEDAGO_ROOT = WORKSPACE_ROOT / "services" / "rag-pedago"
CONTRACT = PEDAGO_ROOT / "configs" / "pedago_interface_contract.yml"

_PG_PORT = os.environ.get("PGVECTOR_PORT", "5433")
PG_DSN = os.environ.get("PG_DSN", f"postgresql://nexus:nexus@localhost:{_PG_PORT}/nexus_rag")
VECTOR_DIM = 1024
MAX_QUERY_LENGTH = 500
MAX_TOP_K = 20

logger = logging.getLogger("retrieval_api")

# ---------------------------------------------------------------------------
# Governance gating
# ---------------------------------------------------------------------------

def check_runtime_allowed(contract_path: Path | None = None) -> dict[str, bool]:
    """Check server_start_allowed AND runtime_api_allowed."""
    path = contract_path or CONTRACT
    if not path.is_file():
        return {"server_start_allowed": False, "runtime_api_allowed": False}
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {"server_start_allowed": False, "runtime_api_allowed": False}
    if not isinstance(config, dict):
        return {"server_start_allowed": False, "runtime_api_allowed": False}
    return {
        "server_start_allowed": config.get("server_start_allowed") is True,
        "runtime_api_allowed": config.get("runtime_api_allowed") is True,
    }


# ---------------------------------------------------------------------------
# Profile resolution — HMAC-signed, server-verified
# ---------------------------------------------------------------------------

PROFILE_SECRET = os.environ.get("PROFILE_SECRET", "")
VALID_NIVEAUX = {"terminale", "premiere", "seconde", "troisieme"}
VALID_AUDIENCES = {"libre", "aefe", "tous"}


@dataclass(frozen=True)
class StudentProfile:
    """Server-verified profile. Determines filtering — cryptographically bound."""
    niveau: str
    audience: str


def _b64url_encode(data: bytes) -> str:
    """Base64url encode without padding (RFC 7515)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """Base64url decode with padding restoration."""
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


# Token characters: [A-Za-z0-9_-] for base64url + hex + the dot separator.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+\.[0-9a-f]{64}$")


def sign_profile(niveau: str, audience: str, secret: str) -> str:
    """Create a signed profile token: b64url(payload_json).hmac_hex.

    The payload is a canonical JSON {"niveau":...,"audience":...} encoded as
    base64url (no padding). The HMAC-SHA256 is computed over the encoded
    payload string. The resulting token contains only header-safe characters.
    """
    payload_json = json.dumps(
        {"niveau": niveau, "audience": audience}, separators=(",", ":")
    )
    encoded = _b64url_encode(payload_json.encode())
    sig = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{sig}"


def verify_profile(token: str, secret: str) -> StudentProfile:
    """Verify a signed profile token and return the profile.

    Token format: b64url(payload_json).hmac_hex
    HMAC is recomputed over the b64url-encoded payload and compared in
    constant time. Raises ValueError on any mismatch or malformation.
    """
    if not _TOKEN_RE.fullmatch(token):
        raise ValueError("malformed token")
    encoded_payload, provided_sig = token.rsplit(".", 1)
    expected_sig = hmac.new(
        secret.encode(), encoded_payload.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise ValueError("invalid signature")
    try:
        payload_bytes = _b64url_decode(encoded_payload)
        data = json.loads(payload_bytes)
    except (json.JSONDecodeError, Exception) as exc:
        raise ValueError("malformed payload") from exc
    niveau = data.get("niveau", "")
    audience = data.get("audience", "")
    if niveau not in VALID_NIVEAUX:
        raise ValueError(f"invalid niveau: {niveau}")
    if audience not in VALID_AUDIENCES:
        raise ValueError(f"invalid audience: {audience}")
    return StudentProfile(niveau=niveau, audience=audience)


def resolve_profile(authorization: str = Header(...)) -> StudentProfile:
    """Resolve profile from HMAC-signed Authorization header.

    Format: Authorization: Bearer <b64url_payload>.<hmac_hex>
    The server recalculates the HMAC over the b64url-encoded payload with
    PROFILE_SECRET and rejects (401) if the signature doesn't match.
    """
    if not PROFILE_SECRET:
        raise HTTPException(status_code=500, detail="PROFILE_SECRET not configured")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Expected Bearer token")
    token = authorization[7:]
    try:
        return verify_profile(token, PROFILE_SECRET)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Search (reuse from index_pgvector)
# ---------------------------------------------------------------------------

def _search_pgvector(
    conn: Any,
    query_vector: list[float],
    niveau: str,
    audience: str,
    top_k: int,
) -> list[dict[str, Any]]:
    """Search pgvector with MANDATORY niveau+audience filters."""
    vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    query = """
        SELECT chunk_id, doc_id, niveau, matiere, notions,
               1 - (vector <=> %s::vector) AS similarity,
               LEFT(text, 200) AS preview
        FROM rag_chunks_pilote
        WHERE niveau = %s AND (%s = ANY(audience) OR 'tous' = ANY(audience))
        ORDER BY vector <=> %s::vector
        LIMIT %s
    """
    params = [vector_str, niveau, audience, vector_str, top_k]

    with conn.cursor() as cur:
        try:
            cur.execute(query, params)
        except psycopg.errors.UndefinedTable as exc:
            conn.rollback()
            raise HTTPException(
                status_code=503,
                detail="retrieval index not ready (rag_chunks_pilote not provisioned)",
            ) from exc
        return [
            {
                "chunk_id": row[0],
                "doc_id": row[1],
                "niveau": row[2],
                "matiere": row[3],
                "notions": row[4],
                "similarity": round(float(row[5]), 4),
                "preview": row[6],
            }
            for row in cur.fetchall()
        ]


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=MAX_QUERY_LENGTH)
    top_k: int = Field(default=5, ge=1, le=MAX_TOP_K)


class SearchResult(BaseModel):
    chunk_id: str
    doc_id: str
    niveau: str
    matiere: str
    notions: list[str]
    similarity: float
    preview: str


class SearchResponse(BaseModel):
    results: list[SearchResult]
    profile_niveau: str
    profile_audience: str
    count: int


# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------

class AppState:
    conn: Any = None
    model: Any = None


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """Startup: check governance, connect to pgvector, load model."""
    # Governance gate
    locks = check_runtime_allowed()
    if not locks["server_start_allowed"]:
        logger.error("BLOCKED: server_start_allowed is false")
        sys.exit(1)
    if not locks["runtime_api_allowed"]:
        logger.error("BLOCKED: runtime_api_allowed is false")
        sys.exit(1)
    logger.info("Governance: server_start_allowed=true, runtime_api_allowed=true")

    # Connect to pgvector
    state.conn = psycopg.connect(PG_DSN)
    logger.info("Connected to pgvector at %s", PG_DSN.split("@")[-1])

    # Load embedding model
    from nexus_contracts.embedding_utils import format_query  # noqa: F401
    from sentence_transformers import SentenceTransformer

    state.model = SentenceTransformer("intfloat/multilingual-e5-large")
    logger.info("Embedding model loaded")

    yield

    if state.conn:
        state.conn.close()


app = FastAPI(
    title="Nexus Retrieval API",
    description="Read-only pedagogical retrieval (ADR-0011)",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Endpoints — READ ONLY, no write routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


_resolve_profile_dep = Depends(resolve_profile)


@app.post("/search", response_model=SearchResponse)
def search_endpoint(
    req: SearchRequest,
    request: Request,  # noqa: ARG001
    profile: StudentProfile = _resolve_profile_dep,
):
    """Search pedagogical content.

    Filtering by niveau and audience is IMPOSED by the server-resolved profile.
    The client body contains ONLY the query text and optional top_k.
    Any attempt to inject niveau/audience in the body is ignored
    (SearchRequest schema has no such fields).
    """
    from nexus_contracts.embedding_utils import format_query

    query_vector = (
        state.model.encode(
            [format_query(req.query)], normalize_embeddings=True
        )[0]
        .tolist()
    )

    results = _search_pgvector(
        state.conn,
        query_vector,
        niveau=profile.niveau,
        audience=profile.audience,
        top_k=req.top_k,
    )

    return SearchResponse(
        results=[SearchResult(**r) for r in results],
        profile_niveau=profile.niveau,
        profile_audience=profile.audience,
        count=len(results),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8100)
