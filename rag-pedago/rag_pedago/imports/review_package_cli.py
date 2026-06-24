from __future__ import annotations

import argparse
from pathlib import Path

from rag_pedago.imports.quality import QualityPolicy, strict_quality_policy
from rag_pedago.imports.review import build_review_package


DEFAULT_TAXONOMIES = [
    Path("taxonomy/maths/terminale_specialite.yml"),
    Path("taxonomy/nsi/terminale.yml"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a human review package for manifests.")
    parser.add_argument("directory_path", type=Path)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--taxonomy", action="append", type=Path, default=[])
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--allow-unknown-rights", action="store_true")
    parser.add_argument("--priority-notion", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, default=Path("data/reports"))
    parser.add_argument("--audit-ledger", type=Path)
    args = parser.parse_args()

    policy = (
        strict_quality_policy(allow_unknown_rights=args.allow_unknown_rights)
        if args.strict
        else QualityPolicy(block_on_unknown_rights=False)
    )
    package = build_review_package(
        directory_path=args.directory_path,
        batch_id=args.batch_id,
        taxonomy_paths=args.taxonomy or DEFAULT_TAXONOMIES,
        policy=policy,
        priority_notions=args.priority_notion,
        output_dir=args.output_dir,
        ledger_db_path=args.audit_ledger,
    )
    print(f"review package generated: {package.markdown_path}")
    print(f"batch_id: {package.batch_id}")
    print(f"status: {package.status.value}")
    print(f"gate_status: {package.gate_status}")
    print(f"gate_json_sha256: {package.gate_json_sha256}")
    print(f"markdown: {package.markdown_path}")
    print(f"json: {package.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
