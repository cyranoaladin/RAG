from __future__ import annotations

import argparse
from pathlib import Path

from rag_pedago.imports.gate import build_gate_report
from rag_pedago.imports.quality import QualityPolicy, strict_quality_policy


DEFAULT_TAXONOMIES = [
    Path("taxonomy/maths/terminale_specialite.yml"),
    Path("taxonomy/nsi/terminale.yml"),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a combined pre-ingestion gate report from local manifests."
    )
    parser.add_argument("directory_path", type=Path)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--taxonomy", action="append", type=Path, default=[])
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--allow-unknown-rights", action="store_true")
    parser.add_argument("--priority-notion", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, default=Path("data/reports"))
    args = parser.parse_args()

    if args.strict:
        policy = strict_quality_policy(allow_unknown_rights=args.allow_unknown_rights)
    else:
        policy = QualityPolicy(block_on_unknown_rights=False)

    report = build_gate_report(
        directory_path=args.directory_path,
        batch_id=args.batch_id,
        taxonomy_paths=args.taxonomy or DEFAULT_TAXONOMIES,
        policy=policy,
        priority_notions=args.priority_notion,
        output_dir=args.output_dir,
    )
    print(f"gate report generated: {report.markdown_path}")
    print(f"batch_id: {report.batch_id}")
    print(f"status: {report.status.value}")
    print(f"readiness_status: {report.readiness_status}")
    print(f"coverage_status: {report.coverage_status}")
    print(f"blocking_issue_count: {report.blocking_issue_count}")
    print(f"warning_count: {report.warning_count}")
    print(f"markdown: {report.markdown_path}")
    print(f"json: {report.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
