#!/usr/bin/env python3
"""Retrieval v2 — dense + rerank CrossEncoder + seuil (LOT 24, D-CONFIG-FINALE).

Chemin de service v2 : resolve_collection_v2 → gate retrievable → dense e5-large
→ rerank CrossEncoder → seuil.
PAS d'hybride BM25/RRF (DD-01 : collision lexicale inter-domaine sur mono-matière).

Usage:
    PG_RAG_DSN=... python scripts/retrieval_v2.py --query "arbre binaire" --collection rag_nexus_nsi_terminale_specialite
    python scripts/retrieval_v2.py --help  # fonctionne sans PG_RAG_DSN (FF-07)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ENGINE_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT.parent.parent / "packages" / "contracts" / "src"))

from ingestor.collection_config import load_collection_config, resolve_collection_v2  # noqa: E402

# --- Configuration figée LOT 24 (D-CONFIG-FINALE-LOT24) ---

# Seuil rerank recalé FF-02b : plus bas in-domain (+2.30) vs plus haut
# hors-domaine (+1.51), milieu de marge = +1.90. 15/15 in conservé, 10/10 out rejeté.
# PROVISOIRE : lié au chunking actuel (proxy phrases/tokens). Après ré-ingestion
# LOT 25 (chunker heading-aware), le plancher in-domain montera → seuil à réviser.
RERANK_SCORE_THRESHOLD = float(os.environ.get("RERANK_SCORE_THRESHOLD", "1.90"))

RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
EMBED_MODEL = "intfloat/multilingual-e5-large"
RERANK_CANDIDATES = 20  # top-N dense candidates sent to rerank

# Hybride BM25/RRF : DÉSACTIVÉ.
# Mécanisme DD-01 : BM25 remonte du bruit lexical inter-domaine sur corpus mono-matière
# (ex. "française" → sujet bac NSI sur souveraineté numérique française).
# À RE-TESTER quand le corpus deviendra multi-matières. Code dans hybrid_search.py.
HYBRID_ENABLED = False


class CollectionNotRetrievableError(ValueError):
    """Raised when a collection is not retrievable (FF-01, M-04/I-06)."""


def _check_retrievable(collection: str, cfg: dict) -> None:
    """Gate retrievable : refuse les collections non-retrievable AVANT toute query.

    FF-01 : rag_nexus_quarantine (domain=quarantine, retrievable:false) doit être
    rejetée explicitement, pas seulement filtrée par review_status.
    """
    defn = resolve_collection_v2(collection, cfg)
    # Derive domain from collection name
    if "quarantine" in collection:
        domain = "quarantine"
    else:
        domain = "education"
    domains = cfg.get("domains", {})
    domain_cfg = domains.get(domain, {})
    if domain_cfg.get("retrievable") is False:
        raise CollectionNotRetrievableError(
            f"Collection '{collection}' is not retrievable (domain '{domain}', "
            f"retrievable:false). Quarantine collections cannot be searched."
        )
    return defn


def search(query: str, collection: str, top_k: int = 5, *, pg_dsn: str) -> list[dict]:
    """Dense → rerank → seuil. Retourne les hits au-dessus du seuil."""
    import psycopg
    from nexus_contracts.embedding_utils import format_query
    from sentence_transformers import CrossEncoder, SentenceTransformer

    # FF-01: Gate retrievable — refuse quarantine BEFORE any query
    cfg = load_collection_config()
    _check_retrievable(collection, cfg)

    embed_model = SentenceTransformer(EMBED_MODEL)
    reranker = CrossEncoder(RERANK_MODEL, max_length=512)

    q_vec = embed_model.encode(format_query(query), normalize_embeddings=True)
    vec_str = "[" + ",".join(str(float(v)) for v in q_vec) + "]"

    conn = psycopg.connect(pg_dsn)

    # Step 1: Dense retrieval (top RERANK_CANDIDATES)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT chunk_id, doc_id, source_label, source_uri, rights, type_doc,
                   text, 1 - (vector <=> %s::vector) AS sim
            FROM rag_chunks
            WHERE collection = %s AND review_status IN ('reviewed', 'needs_review')
            ORDER BY vector <=> %s::vector
            LIMIT %s
        """, (vec_str, collection, vec_str, RERANK_CANDIDATES))
        candidates = cur.fetchall()

    conn.close()

    if not candidates:
        return []

    # Step 2: Rerank with CrossEncoder
    # FF-02: pass FULL chunk text — let the model's max_length=512 TOKENS handle truncation.
    # Do NOT pre-truncate to 512 CHARACTERS (which sabotages scoring on longer chunks).
    pairs = [(query, c[6] or "") for c in candidates]
    rerank_scores = reranker.predict(pairs)

    # Step 3: Filter by seuil + sort
    results = []
    for candidate, score in sorted(
        zip(candidates, rerank_scores, strict=False), key=lambda x: x[1], reverse=True
    ):
        if float(score) < RERANK_SCORE_THRESHOLD:
            continue
        results.append({
            "chunk_id": candidate[0],
            "doc_id": candidate[1],
            "source_label": candidate[2],
            "source_uri": candidate[3],
            "rights": candidate[4],
            "type_doc": candidate[5],
            "preview": (candidate[6] or "")[:200],
            "rerank_score": round(float(score), 4),
            "dense_sim": round(float(candidate[7]), 4),
        })
        if len(results) >= top_k:
            break

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrieval v2 (dense+rerank+seuil)")
    parser.add_argument("--query", required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    # FF-07: DSN validation AFTER argparse (so --help works without PG_RAG_DSN)
    pg_dsn = os.environ.get("PG_RAG_DSN")
    if not pg_dsn:
        print("Error: PG_RAG_DSN environment variable required", file=sys.stderr)
        sys.exit(1)

    results = search(args.query, args.collection, args.top_k, pg_dsn=pg_dsn)

    print(f"Query: {args.query}")
    print(f"Collection: {args.collection}")
    print(f"Seuil: {RERANK_SCORE_THRESHOLD}")
    print(f"Résultats: {len(results)}")
    for r in results:
        print(f"  rerank={r['rerank_score']:+7.2f}  {r['source_label'][:40]:40s}  rights={r['rights']}")
    if not results:
        print("  (aucun résultat au-dessus du seuil)")


if __name__ == "__main__":
    main()
