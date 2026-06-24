from __future__ import annotations

import argparse
from pathlib import Path

from rag_pedago.imports.manifest import import_manifest_directory
from rag_pedago.imports.quality import QualityPolicy, strict_quality_policy
from rag_pedago.ledger.migrations import DEFAULT_LEDGER_PATH


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import a local directory of JSONL manifests into the ledger."
    )
    parser.add_argument("directory_path", type=Path)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--batch-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--allow-unknown-rights", action="store_true")
    args = parser.parse_args()

    if args.strict:
        policy = strict_quality_policy(allow_unknown_rights=args.allow_unknown_rights)
    else:
        policy = QualityPolicy(block_on_unknown_rights=False)

    report = import_manifest_directory(
        args.directory_path,
        args.db_path,
        batch_id=args.batch_id,
        dry_run=args.dry_run,
        policy=policy,
    )
    print(f"manifest directory imported: {report.directory_path}")
    print(f"batch_id: {report.batch_id}")
    print(f"status: {report.status}")
    print(f"dry_run: {report.dry_run}")
    print(f"manifest_count: {report.manifest_count}")
    print(f"documents_valid: {report.documents_valid}")
    print(f"documents_invalid: {report.documents_invalid}")
    print(f"documents_not_retrievable: {report.documents_not_retrievable}")
    print(f"duplicate_doc_ids: {len(report.duplicate_doc_ids)}")
    print(f"duplicate_source_uris: {len(report.duplicate_source_uris)}")
    print(f"duplicate_sha256: {len(report.duplicate_sha256)}")
    print(f"quality_status: {report.quality_report.status}")
    print(f"blocking_issue_count: {report.quality_report.blocking_issue_count}")
    print(f"warning_count: {report.quality_report.warning_count}")
    print(f"report: {report.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
