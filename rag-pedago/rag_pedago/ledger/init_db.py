from __future__ import annotations

import argparse
from pathlib import Path

from rag_pedago.ledger.diagnostics import check_integrity
from rag_pedago.ledger.migrations import DEFAULT_LEDGER_PATH, initialize_database


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize the Nexus RAG Pedago SQLite ledger.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--check", action="store_true", help="Initialize if needed and verify the file exists.")
    args = parser.parse_args()

    initialize_database(args.db_path)
    if args.check and not args.db_path.exists():
        raise SystemExit(f"ledger check failed: {args.db_path}")

    print(f"ledger initialized: {args.db_path}")
    if args.check:
        diagnostic = check_integrity(args.db_path)
        print(f"db path: {diagnostic['db_path']}")
        print(f"tables OK: {diagnostic['tables_ok']}")
        print(f"integrity_check: {diagnostic['integrity_check']}")
        foreign_key_status = (
            "OK" if diagnostic["foreign_key_check"] == [] else diagnostic["foreign_key_check"]
        )
        print(f"foreign_key_check: {foreign_key_status}")
        print(f"migrations: {diagnostic['migrations_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
