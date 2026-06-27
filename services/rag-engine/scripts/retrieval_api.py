#!/usr/bin/env python3
"""Retrieval API — read-only search over pgvector (ADR-0011).

Filtrage niveau/audience IMPOSÉ par le serveur selon le profil résolu.
Le client fournit uniquement la requête textuelle. Aucune route d'écriture.

Gated by server_start_allowed AND runtime_api_allowed (rag-pedago contract).
"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
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
# Profile resolution — server-side, NOT from client body
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StudentProfile:
    """Server-resolved profile. Determines filtering — never from client."""
    niveau: str
    audience: str


# Profile registry: maps token/header → profile.
# In production, this would query a user database or decode a JWT.
# For this lot: header-based resolution with known profiles.
PROFILE_REGISTRY: dict[str, StudentProfile] = {
    "terminale-libre": StudentProfile(niveau="terminale", audience="libre"),
    "terminale-aefe": StudentProfile(niveau="terminale", audience="aefe"),
    "premiere-libre": StudentProfile(niveau="premiere", audience="libre"),
    "premiere-aefe": StudentProfile(niveau="premiere", audience="aefe"),
}


def resolve_profile(x_student_profile: str = Header(...)) -> StudentProfile:
    """Resolve profile from server-controlled header.

    In production: JWT decode or session lookup.
    For this lot: X-Student-Profile header maps to known profiles.
    The client cannot forge arbitrary niveau/audience.
    """
    profile = PROFILE_REGISTRY.get(x_student_profile)
    if profile is None:
        raise HTTPException(status_code=403, detail="Unknown profile")
    return profile


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
        FROM rag_chunks
        WHERE niveau = %s AND (%s = ANY(audience) OR 'tous' = ANY(audience))
        ORDER BY vector <=> %s::vector
        LIMIT %s
    """
    params = [vector_str, niveau, audience, vector_str, top_k]

    with conn.cursor() as cur:
        cur.execute(query, params)
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
