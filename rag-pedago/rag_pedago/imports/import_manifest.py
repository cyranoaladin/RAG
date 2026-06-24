from __future__ import annotations

import argparse
from pathlib import Path

from rag_pedago.imports.manifest import import_manifest
from rag_pedago.ledger.migrations import DEFAULT_LEDGER_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a local JSONL manifest into the ledger.")
    parser.add_argument("manifest_path", type=Path)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    report = import_manifest(args.manifest_path, args.db_path, run_id=args.run_id)
    print(f"manifest imported: {report.manifest_path}")
    print(f"run_id: {report.run_id}")
    print(f"status: {report.status}")
    print(f"manifest_sha256: {report.manifest_sha256}")
    print(f"documents_valid: {report.documents_valid}")
    print(f"documents_invalid: {report.documents_invalid}")
    print(f"documents_not_retrievable: {report.documents_not_retrievable}")
    print(f"report: {report.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
