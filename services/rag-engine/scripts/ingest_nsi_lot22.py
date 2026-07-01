#!/usr/bin/env python3
"""LOT 22 — Ingestion NSI gouvernée (T-22-1→T-22-3).

Reads the ratified manifest, extracts text, chunks with real e5 tokenizer
at 480 tokens, embeds with e5-large 1024, upserts into pgvector.

Usage:
    PG_RAG_DSN=postgresql://nexus_rag:xxx@localhost:5436/nexus_rag \
    python scripts/ingest_nsi_lot22.py [--dry-run] [--resume]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

# Resolve paths
SCRIPT_DIR = Path(__file__).resolve().parent
ENGINE_ROOT = SCRIPT_DIR.parent
REPO_ROOT = ENGINE_ROOT.parent.parent
MANIFEST_PATH = REPO_ROOT / "docs" / "audits" / "manifest_nsi_dryrun.json.gz"

sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "contracts" / "src"))

from ingestor.collection_config import load_collection_config, resolve_collection_v2  # noqa: E402

# --- Config ---
CORPUS_ROOT = Path(os.environ.get(
    "NSI_CORPUS_ROOT",
    os.path.expanduser("~/Documents/NSI/scrapping_NSI/ressources_nsi_centralisees")
))
PG_DSN = os.environ.get("PG_RAG_DSN")
if not PG_DSN:
    raise RuntimeError("PG_RAG_DSN environment variable required (no default — R-01)")
BUDGET_TOKENS = 480
MODEL_NAME = "intfloat/multilingual-e5-large"
BATCH_SIZE = 32


def load_manifest() -> dict[str, Any]:
    with gzip.open(MANIFEST_PATH, "rt", encoding="utf-8") as f:
        return json.load(f)


def extract_text(fpath: Path) -> str:
    ext = fpath.suffix.lower()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(fpath))
            return " ".join((p.extract_text() or "") for p in reader.pages)
        elif ext == ".ipynb":
            nb = json.loads(fpath.read_text(encoding="utf-8", errors="replace"))
            texts = []
            for cell in nb.get("cells", []):
                if cell.get("cell_type") in ("markdown", "code"):
                    texts.append("".join(cell.get("source", [])))
            return "\n".join(texts)
        elif ext == ".tex":
            return fpath.read_text(encoding="utf-8", errors="replace")
        elif ext == ".docx":
            from docx import Document
            doc = Document(str(fpath))
            return "\n".join(p.text for p in doc.paragraphs)
        elif ext == ".odt":
            from odf.opendocument import load as odf_load
            from odf.text import P
            doc = odf_load(str(fpath))
            texts = []
            for p in doc.getElementsByType(P):
                t = ""
                for node in p.childNodes:
                    if hasattr(node, "data"):
                        t += node.data
                texts.append(t)
            return "\n".join(texts)
    except Exception:
        pass
    return ""


def chunk_text(text: str, tokenizer: Any, max_tokens: int = BUDGET_TOKENS) -> list[str]:
    """Split text into chunks of at most max_tokens (counted by real e5 tokenizer)."""
    if not text.strip():
        return []
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for sent in sentences:
        sent_tokens = len(tokenizer.encode(sent, add_special_tokens=False))
        if sent_tokens > max_tokens:
            # Split long sentence by words
            words = sent.split()
            buf: list[str] = []
            buf_tok = 0
            for w in words:
                w_tok = len(tokenizer.encode(w, add_special_tokens=False))
                if buf_tok + w_tok > max_tokens and buf:
                    if current:
                        chunks.append(" ".join(current + buf))
                        current = []
                        current_tokens = 0
                    else:
                        chunks.append(" ".join(buf))
                    buf = []
                    buf_tok = 0
                buf.append(w)
                buf_tok += w_tok
            if buf:
                current.extend(buf)
                current_tokens += buf_tok
            continue

        if current_tokens + sent_tokens > max_tokens and current:
            chunks.append(" ".join(current))
            current = []
            current_tokens = 0
        current.append(sent)
        current_tokens += sent_tokens

    if current:
        chunks.append(" ".join(current))
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Parse and chunk but don't embed/insert")
    parser.add_argument("--resume", action="store_true", help="Skip docs already in ingestion_progress")
    args = parser.parse_args()

    # Validate collections
    cfg = load_collection_config()
    for col in ["rag_nexus_nsi_premiere_specialite", "rag_nexus_nsi_terminale_specialite"]:
        resolve_collection_v2(col, cfg)
    print("Collections v2 validated.")

    # Load manifest
    manifest = load_manifest()
    entries = [e for e in manifest["manifest"] if e["dedup"]["kept"] and not e["quarantine"]["flag"]]
    print(f"Manifest loaded: {len(entries)} docs to ingest.")

    if not args.dry_run:
        # Load model
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(MODEL_NAME)
        print(f"Model loaded: {MODEL_NAME}")

        # Connect to pgvector
        import psycopg
        conn = psycopg.connect(PG_DSN)
        conn.autocommit = False
        print(f"Connected to pgvector: {PG_DSN.split('@')[1] if '@' in PG_DSN else PG_DSN}")

        # Create progress table
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ingestion_progress (
                    doc_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'pending',
                    chunks_inserted INT DEFAULT 0,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            conn.commit()

    # Load tokenizer
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    print("Tokenizer loaded.")

    from nexus_contracts.embedding_utils import format_passage

    total_chunks = 0
    total_docs = 0
    skipped = 0
    errors = 0
    t0 = time.time()

    for i, entry in enumerate(entries):
        fpath = CORPUS_ROOT / entry["file"]

        if not fpath.exists():
            print(f"  SKIP {entry['file']}: file not found")
            errors += 1
            continue

        # Compute full doc_id
        doc_id = hashlib.sha256(fpath.read_bytes()).hexdigest()

        if args.resume and not args.dry_run:
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM ingestion_progress WHERE doc_id = %s", (doc_id,))
                row = cur.fetchone()
                if row and row[0] == "done":
                    skipped += 1
                    continue

        # Extract text (strip NUL bytes — PostgreSQL rejects \x00)
        text = extract_text(fpath).replace("\x00", "")
        if len(text.strip()) < 50:
            continue

        # Chunk with real tokenizer
        chunks = chunk_text(text, tokenizer, BUDGET_TOKENS)
        if not chunks:
            continue

        if args.dry_run:
            total_chunks += len(chunks)
            total_docs += 1
            if (i + 1) % 200 == 0:
                print(f"  [{i+1}/{len(entries)}] {total_docs} docs, {total_chunks} chunks")
            continue

        # Embed
        passages = [format_passage(c) for c in chunks]
        embeddings = model.encode(passages, normalize_embeddings=True, batch_size=BATCH_SIZE)

        # Upsert
        with conn.cursor() as cur:
            for ci, (chunk, emb) in enumerate(zip(chunks, embeddings, strict=False)):
                chunk_id = f"{doc_id}:{ci}"
                chunk_sha = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
                vec_str = "[" + ",".join(str(float(v)) for v in emb) + "]"

                cur.execute("""
                    INSERT INTO rag_chunks (
                        chunk_id, doc_id, chunk_sha256, vector, collection,
                        niveau, voie, audience, matiere, statut_enseignement,
                        notions, domain, source_label, source_uri, rights,
                        type_doc, official, text, chunk_index, review_status,
                        model, source_kind
                    ) VALUES (
                        %s, %s, %s, %s::vector, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s
                    )
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        chunk_sha256 = EXCLUDED.chunk_sha256,
                        vector = EXCLUDED.vector,
                        text = EXCLUDED.text,
                        indexed_at = NOW()
                    WHERE rag_chunks.chunk_sha256 <> EXCLUDED.chunk_sha256
                """, (
                    chunk_id, doc_id, chunk_sha, vec_str, entry["collection"],
                    entry["niveau"], "generale", ["tous"], "nsi", "specialite",
                    [], "education", entry["source_label"], entry["source_uri"],
                    entry["rights"],
                    entry["type_doc"], entry["official"], chunk, ci, "needs_review",
                    MODEL_NAME, entry["source_kind"],
                ))

            # Mark progress
            cur.execute("""
                INSERT INTO ingestion_progress (doc_id, status, chunks_inserted, updated_at)
                VALUES (%s, 'done', %s, NOW())
                ON CONFLICT (doc_id) DO UPDATE SET status = 'done', chunks_inserted = %s, updated_at = NOW()
            """, (doc_id, len(chunks), len(chunks)))

            conn.commit()

        total_chunks += len(chunks)
        total_docs += 1

        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            rate = total_chunks / (elapsed / 60) if elapsed > 0 else 0
            print(f"  [{i+1}/{len(entries)}] {total_docs} docs, {total_chunks} chunks, {rate:.0f} ch/min")

    elapsed = time.time() - t0
    print("\n=== DONE ===")
    print(f"  Docs: {total_docs}, Chunks: {total_chunks}, Skipped: {skipped}, Errors: {errors}")
    print(f"  Duration: {elapsed/60:.1f} min")

    if not args.dry_run:
        conn.close()


if __name__ == "__main__":
    main()
