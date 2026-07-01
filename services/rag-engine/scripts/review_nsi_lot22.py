#!/usr/bin/env python3
"""LOT 22 — N-02 Script de revue NSI (D-REVIEW).

Met à jour review_status pour les documents validés par le lead.
Dry-run par défaut. Exécution réelle uniquement avec --execute.

Usage:
    # Voir combien de chunks seraient modifiés
    PG_RAG_DSN=... python scripts/review_nsi_lot22.py \
        --source-labels "fichier1.pdf,fichier2.odt"

    # Exécuter réellement
    PG_RAG_DSN=... python scripts/review_nsi_lot22.py \
        --source-labels "fichier1.pdf,fichier2.odt" --execute

    # Valider par type_doc entier (sondage provenance confirmée)
    PG_RAG_DSN=... python scripts/review_nsi_lot22.py \
        --type-doc annale --execute

    # Consulter la priorité HAUTE (type_doc=autre)
    PG_RAG_DSN=... python scripts/review_nsi_lot22.py --consult-high
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

PG_DSN = os.environ.get("PG_RAG_DSN")
if not PG_DSN:
    raise RuntimeError("PG_RAG_DSN environment variable required")


def main() -> None:
    import psycopg

    parser = argparse.ArgumentParser(description="Revue NSI — D-REVIEW")
    parser.add_argument("--source-labels", type=str, help="Liste de source_label séparés par virgule")
    parser.add_argument("--type-doc", type=str, help="Valider un type_doc entier")
    parser.add_argument("--execute", action="store_true", help="Exécuter l'UPDATE (défaut: dry-run)")
    parser.add_argument("--consult-high", action="store_true", help="Consulter la priorité HAUTE")
    args = parser.parse_args()

    conn = psycopg.connect(PG_DSN)

    if args.consult_high:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT source_label, niveau, type_doc, count(*) AS chunks,
                       LEFT(MIN(text), 150) AS extrait
                FROM rag_chunks
                WHERE type_doc = 'autre' AND review_status = 'needs_review'
                GROUP BY source_label, niveau, type_doc
                ORDER BY count(*) DESC
            """)
            rows = cur.fetchall()
            print(f"=== PRIORITÉ HAUTE: {len(rows)} documents type_doc='autre' needs_review ===")
            for r in rows:
                print(f"  {r[0]:50s} {r[1]:10s} {r[3]:5d}ch  {(r[4] or '').replace(chr(10), ' ')[:80]}")
        conn.close()
        return

    if not args.source_labels and not args.type_doc:
        print("Erreur: --source-labels ou --type-doc requis")
        sys.exit(1)

    # Build WHERE clause
    if args.source_labels:
        labels = [s.strip() for s in args.source_labels.split(",") if s.strip()]
        placeholders = ",".join(["%s"] * len(labels))
        where = f"source_label IN ({placeholders})"
        params = labels
    else:
        where = "type_doc = %s"
        params = [args.type_doc]

    # Dry-run: show what would be modified
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT count(*) FROM rag_chunks
            WHERE {where} AND review_status = 'needs_review'
        """, params)
        count = cur.fetchone()[0]

        cur.execute(f"""
            SELECT count(DISTINCT source_label) FROM rag_chunks
            WHERE {where} AND review_status = 'needs_review'
        """, params)
        doc_count = cur.fetchone()[0]

    print(f"{'EXECUTE' if args.execute else 'DRY-RUN'}: {count} chunks ({doc_count} documents) → reviewed")

    if not args.execute:
        print("(Ajouter --execute pour appliquer)")
        conn.close()
        return

    # Guard: never UPDATE without explicit list
    if not args.source_labels and not args.type_doc:
        print("ABORT: pas d'UPDATE sans liste explicite")
        conn.close()
        sys.exit(1)

    # Execute
    with conn.cursor() as cur:
        cur.execute(f"""
            UPDATE rag_chunks SET review_status = 'reviewed'
            WHERE {where} AND review_status = 'needs_review'
        """, params)
        updated = cur.rowcount
        conn.commit()

    timestamp = datetime.now(datetime.UTC).isoformat()
    print(f"DONE: {updated} chunks passés reviewed à {timestamp}")
    print(f"  Critère: {where}")
    print(f"  Params: {params}")

    # Show remaining needs_review
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM rag_chunks WHERE review_status = 'needs_review'")
        remaining = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM rag_chunks WHERE review_status = 'reviewed'")
        reviewed = cur.fetchone()[0]
    print(f"  Restant needs_review: {remaining}")
    print(f"  Total reviewed: {reviewed}")

    conn.close()


if __name__ == "__main__":
    main()
