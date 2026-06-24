from __future__ import annotations

import argparse
from pathlib import Path

from rag_pedago.imports.controlled_import import controlled_import_manifest_directory
from rag_pedago.imports.quality import QualityPolicy, strict_quality_policy
from rag_pedago.ledger.migrations import DEFAULT_LEDGER_PATH


DEFAULT_TAXONOMIES = [
    Path("taxonomy/maths/terminale_specialite.yml"),
    Path("taxonomy/nsi/terminale.yml"),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a gate-guarded manifest directory import into the local ledger."
    )
    parser.add_argument("directory_path", type=Path)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--taxonomy", action="append", type=Path, default=[])
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--allow-unknown-rights", action="store_true")
    parser.add_argument("--priority-notion", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, default=Path("data/reports"))
    parser.add_argument("--require-review", action="store_true")
    parser.add_argument("--review-decision", type=Path)
    parser.add_argument("--review-package", type=Path)
    parser.add_argument("--audit-ledger", type=Path)
    args = parser.parse_args()

    if args.strict:
        policy = strict_quality_policy(allow_unknown_rights=args.allow_unknown_rights)
    else:
        policy = QualityPolicy(block_on_unknown_rights=False)

    report = controlled_import_manifest_directory(
        directory_path=args.directory_path,
        db_path=args.db_path,
        batch_id=args.batch_id,
        taxonomy_paths=args.taxonomy or DEFAULT_TAXONOMIES,
        policy=policy,
        priority_notions=args.priority_notion,
        output_dir=args.output_dir,
        require_review=args.require_review,
        review_decision_path=args.review_decision,
        review_package_path=args.review_package,
        audit_ledger_db_path=args.audit_ledger,
    )
    print(f"controlled import report generated: {report.markdown_path}")
    print(f"batch_id: {report.batch_id}")
    print(f"status: {report.status.value}")
    print(f"attempt_id: {report.attempt_id}")
    print(f"gate_status: {report.gate_status}")
    print(f"documents_valid: {report.documents_valid}")
    print(f"documents_invalid: {report.documents_invalid}")
    print(f"documents_not_retrievable: {report.documents_not_retrievable}")
    print(f"run_ids: {','.join(report.run_ids) if report.run_ids else 'none'}")
    print(f"review_required: {str(report.review_required).lower()}")
    print(f"review_decision: {report.review_decision or 'none'}")
    print(f"review_hash_verified: {str(report.review_hash_verified).lower()}")
    print(f"review_package_hash_verified: {str(report.review_package_hash_verified).lower()}")
    print(f"official_reference_hash_verified: {str(report.official_reference_hash_verified).lower()}")
    print(f"taxonomy_hash_verified: {str(report.taxonomy_hash_verified).lower()}")
    print(f"manifest_hashes_verified: {str(report.manifest_hashes_verified).lower()}")
    print(f"markdown: {report.markdown_path}")
    print(f"json: {report.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
