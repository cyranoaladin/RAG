#!/usr/bin/env python3
"""Index embeddings into pgvector + demo retrieval.

Gated by ingestion_allowed. Uses psycopg for PostgreSQL.
Requires: PostgreSQL with pgvector extension running.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "configs" / "pedago_interface_contract.yml"
EMBEDDINGS_DIR = ROOT / "data" / "embeddings"
CHUNKS_DIR = ROOT / "data" / "chunks"

# pgvector connection (configurable via env)
PG_DSN = os.environ.get("PG_DSN", "postgresql://nexus:nexus@localhost:5432/nexus_rag")
VECTOR_DIM = 1024


def check_ingestion_allowed(contract_path: Path | None = None) -> bool:
    """Gate: ingestion_allowed must be true."""
    path = contract_path or CONTRACT
    if not path.is_file():
        return False
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(config, dict):
        return False
    return config.get("ingestion_allowed") is True


def _create_schema(conn: Any) -> None:
    """Create the rag_chunks table if not exists."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS rag_chunks (
                chunk_id TEXT PRIMARY KEY,
                doc_id TEXT NOT NULL,
                vector vector({VECTOR_DIM}),
                niveau TEXT NOT NULL,
                voie TEXT NOT NULL DEFAULT 'generale',
                audience TEXT[] NOT NULL DEFAULT '{{"tous"}}',
                matiere TEXT NOT NULL,
                notions TEXT[] NOT NULL DEFAULT '{{}}',
                text TEXT,
                model TEXT
            )
        """)
        # HNSW index for ANN search
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_rag_chunks_vector
            ON rag_chunks USING hnsw (vector vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)
        conn.commit()


def _load_embeddings() -> list[dict]:
    """Load all embedding entries."""
    entries = []
    for jsonl in sorted(EMBEDDINGS_DIR.rglob("*.jsonl")):
        for line in jsonl.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                entries.append(json.loads(line))
    return entries


def _load_chunk_text(chunk_id: str) -> str:
    """Load the text of a chunk from the chunks JSONL."""
    for jsonl in CHUNKS_DIR.rglob("*.jsonl"):
        for line in jsonl.read_text(encoding="utf-8").strip().split("\n"):
            chunk = json.loads(line)
            if chunk.get("chunk_id") == chunk_id:
                return chunk.get("text", "")
    return ""


def index_embeddings(conn: Any) -> dict[str, int]:
    """Upsert all embeddings into pgvector. Returns stats."""
    entries = _load_embeddings()
    inserted = 0

    with conn.cursor() as cur:
        for entry in entries:
            dim = entry.get("dim", 0)
            if dim != VECTOR_DIM:
                print(f"  SKIP {entry['chunk_id']}: dim {dim} ≠ {VECTOR_DIM}")
                continue

            vector_str = "[" + ",".join(str(v) for v in entry["vector"]) + "]"
            audience = entry.get("audience", ["tous"])
            if isinstance(audience, str):
                audience = [audience]
            notions = entry.get("notions", [])

            # Load text from chunks
            text = _load_chunk_text(entry["chunk_id"])

            cur.execute("""
                INSERT INTO rag_chunks (chunk_id, doc_id, vector, niveau, voie, audience, matiere, notions, text, model)
                VALUES (%s, %s, %s::vector, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    vector = EXCLUDED.vector,
                    niveau = EXCLUDED.niveau,
                    voie = EXCLUDED.voie,
                    audience = EXCLUDED.audience,
                    matiere = EXCLUDED.matiere,
                    notions = EXCLUDED.notions,
                    text = EXCLUDED.text,
                    model = EXCLUDED.model
            """, (
                entry["chunk_id"],
                entry["doc_id"],
                vector_str,
                entry.get("niveau", ""),
                entry.get("voie", "generale"),
                audience,
                entry.get("matiere", ""),
                notions,
                text,
                entry.get("model", ""),
            ))
            inserted += 1

    conn.commit()
    return {"indexed": inserted, "total": len(entries)}


def search(
    conn: Any,
    query_vector: list[float],
    niveau: str | None = None,
    audience: str | None = None,
    top_k: int = 5,
) -> list[dict]:
    """Search by cosine similarity with optional filters."""
    vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    conditions = []
    params: list[Any] = [vector_str]

    if niveau:
        conditions.append("niveau = %s")
        params.append(niveau)
    if audience:
        conditions.append("%s = ANY(audience)")
        params.append(audience)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    params.append(top_k)

    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT chunk_id, doc_id, niveau, matiere, notions,
                   1 - (vector <=> %s::vector) AS similarity,
                   LEFT(text, 200) AS preview
            FROM rag_chunks
            {where}
            ORDER BY vector <=> %s::vector
            LIMIT %s
        """, (*params, vector_str, top_k))

        results = []
        for row in cur.fetchall():
            results.append({
                "chunk_id": row[0],
                "doc_id": row[1],
                "niveau": row[2],
                "matiere": row[3],
                "notions": row[4],
                "similarity": round(float(row[5]), 4),
                "preview": row[6],
            })
    return results


def main() -> int:
    if not check_ingestion_allowed():
        print("BLOCKED: ingestion_allowed is false")
        return 1

    import psycopg
    conn = psycopg.connect(PG_DSN)

    print("Creating schema...")
    _create_schema(conn)

    print("Indexing embeddings...")
    stats = index_embeddings(conn)
    print(f"Indexed: {stats['indexed']}/{stats['total']}")

    # Demo retrieval
    from sentence_transformers import SentenceTransformer

    from scrapers.embedding_utils import format_query

    model = SentenceTransformer("intfloat/multilingual-e5-large")

    queries = [
        ("comment calculer la dérivée", "terminale", None),
        ("la justice dans la philosophie", "terminale", None),
        ("pile et file informatique", "terminale", None),
        ("dérivée d'une fonction", "premiere", None),  # Should return 0 (pilot = terminale only)
    ]

    print("\n=== Retrieval demo ===")
    for query_text, niveau, audience in queries:
        qv = model.encode([format_query(query_text)], normalize_embeddings=True)[0].tolist()
        results = search(conn, qv, niveau=niveau, audience=audience, top_k=3)
        print(f"\nQ: '{query_text}' (niveau={niveau})")
        if results:
            for r in results:
                print(f"  [{r['similarity']:.3f}] {r['matiere']}/{r['notions']} — {r['preview'][:80]}...")
        else:
            print("  (no results)")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
