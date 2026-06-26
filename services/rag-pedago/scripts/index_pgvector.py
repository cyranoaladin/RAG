#!/usr/bin/env python3
"""Index embeddings into pgvector + retrieval demo.

Gated by ingestion_allowed AND a review artefact (quality→gate→review).
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
REVIEW_ARTEFACT = ROOT / "data" / "embeddings" / "REVIEW.ok"

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


def check_review_approved(review_path: Path | None = None) -> bool:
    """Gate: review artefact must exist (quality→gate→review per AGENTS.md)."""
    path = review_path or REVIEW_ARTEFACT
    return path.is_file()


def _create_schema(conn: Any) -> None:
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
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_rag_chunks_vector
            ON rag_chunks USING hnsw (vector vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)
        conn.commit()


def _preload_texts() -> dict[str, str]:
    """Preload all chunk texts into a map (O(1) lookup)."""
    texts: dict[str, str] = {}
    for jsonl in CHUNKS_DIR.rglob("*.jsonl"):
        for line in jsonl.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                chunk = json.loads(line)
                texts[chunk["chunk_id"]] = chunk.get("text", "")
    return texts


def _load_embeddings() -> list[dict]:
    entries = []
    for jsonl in sorted(EMBEDDINGS_DIR.rglob("*.jsonl")):
        for line in jsonl.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                entries.append(json.loads(line))
    return entries


def _validate_embedding(entry: dict) -> list[str]:
    """Quality check before admission."""
    issues = []
    if entry.get("dim") != VECTOR_DIM:
        issues.append(f"dim {entry.get('dim')} ≠ {VECTOR_DIM}")
    if not entry.get("niveau"):
        issues.append("missing niveau")
    if not entry.get("matiere"):
        issues.append("missing matiere")
    vec = entry.get("vector", [])
    if not vec or len(vec) != VECTOR_DIM:
        issues.append(f"vector length {len(vec)}")
    return issues


def index_embeddings(conn: Any) -> dict[str, int]:
    texts = _preload_texts()
    entries = _load_embeddings()
    indexed = 0
    rejected = 0

    with conn.cursor() as cur:
        for entry in entries:
            issues = _validate_embedding(entry)
            if issues:
                print(f"  REJECT {entry.get('chunk_id', '?')}: {issues}")
                rejected += 1
                continue

            vector_str = "[" + ",".join(str(v) for v in entry["vector"]) + "]"
            audience = entry.get("audience", ["tous"])
            if isinstance(audience, str):
                audience = [audience]

            text = texts.get(entry["chunk_id"], "")

            cur.execute("""
                INSERT INTO rag_chunks (chunk_id, doc_id, vector, niveau, voie, audience, matiere, notions, text, model)
                VALUES (%s, %s, %s::vector, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    vector = EXCLUDED.vector, niveau = EXCLUDED.niveau,
                    voie = EXCLUDED.voie, audience = EXCLUDED.audience,
                    matiere = EXCLUDED.matiere, notions = EXCLUDED.notions,
                    text = EXCLUDED.text, model = EXCLUDED.model
            """, (
                entry["chunk_id"], entry["doc_id"], vector_str,
                entry.get("niveau", ""), entry.get("voie", "generale"),
                audience, entry.get("matiere", ""), entry.get("notions", []),
                text, entry.get("model", ""),
            ))
            indexed += 1

    conn.commit()
    return {"indexed": indexed, "rejected": rejected, "total": len(entries)}


def search(
    conn: Any,
    query_vector: list[float],
    niveau: str | None = None,
    audience: str | None = None,
    top_k: int = 5,
) -> list[dict]:
    """Search by cosine similarity with filters. Params bound in placeholder order."""
    vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    conditions = []
    filter_params: list[Any] = []

    if niveau:
        conditions.append("niveau = %s")
        filter_params.append(niveau)
    if audience:
        conditions.append("%s = ANY(audience)")
        filter_params.append(audience)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    query = f"""
        SELECT chunk_id, doc_id, niveau, matiere, notions,
               1 - (vector <=> %s::vector) AS similarity,
               LEFT(text, 200) AS preview
        FROM rag_chunks
        {where_clause}
        ORDER BY vector <=> %s::vector
        LIMIT %s
    """
    # Params order matches placeholders: similarity_calc, [filters], order_by, limit
    all_params = [vector_str, *filter_params, vector_str, top_k]

    with conn.cursor() as cur:
        cur.execute(query, all_params)
        return [
            {
                "chunk_id": row[0], "doc_id": row[1], "niveau": row[2],
                "matiere": row[3], "notions": row[4],
                "similarity": round(float(row[5]), 4), "preview": row[6],
            }
            for row in cur.fetchall()
        ]


def main() -> int:
    if not check_ingestion_allowed():
        print("BLOCKED: ingestion_allowed is false")
        return 1

    if not check_review_approved():
        print("BLOCKED: review artefact not found (data/embeddings/REVIEW.ok)")
        print("Run quality check and create the artefact before indexing.")
        return 1

    import psycopg
    conn = psycopg.connect(PG_DSN)

    print("Creating schema...")
    _create_schema(conn)

    print("Indexing embeddings...")
    stats = index_embeddings(conn)
    print(f"Indexed: {stats['indexed']}, rejected: {stats['rejected']}, total: {stats['total']}")

    # Count in DB
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM rag_chunks")
        count = cur.fetchone()[0]  # type: ignore[index]
        print(f"DB count: {count}")

    # Demo retrieval
    from sentence_transformers import SentenceTransformer

    from scrapers.embedding_utils import format_query

    model = SentenceTransformer("intfloat/multilingual-e5-large")

    queries = [
        ("comment calculer la dérivée d'une fonction", "terminale", None),
        ("la justice dans la philosophie", "terminale", None),
        ("pile et file informatique", "terminale", None),
        ("les suites numériques", "terminale", None),
        ("dérivée d'une fonction", "premiere", None),  # 0 results expected
    ]

    print("\n=== RETRIEVAL DEMO (REAL EXECUTION) ===")
    for query_text, niveau, audience in queries:
        qv = model.encode([format_query(query_text)], normalize_embeddings=True)[0].tolist()
        results = search(conn, qv, niveau=niveau, audience=audience, top_k=3)
        print(f"\nQ: '{query_text}' (niveau={niveau})")
        if results:
            for r in results:
                print(f"  [{r['similarity']:.3f}] {r['matiere']}/{r['notions']} — {r['preview'][:80]}...")
        else:
            print("  (0 results — filter excludes)")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
