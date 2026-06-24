from __future__ import annotations

import argparse
from pathlib import Path

from rag_pedago.imports.quality import QualityPolicy, strict_quality_policy
from rag_pedago.imports.readiness import build_readiness_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a pre-ingestion readiness report from local JSONL manifests."
    )
    parser.add_argument("directory_path", type=Path)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--allow-unknown-rights", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("data/reports"))
    args = parser.parse_args()

    if args.strict:
        policy = strict_quality_policy(allow_unknown_rights=args.allow_unknown_rights)
    else:
        policy = QualityPolicy(block_on_unknown_rights=False)

    report = build_readiness_report(
        directory_path=args.directory_path,
        batch_id=args.batch_id,
        policy=policy,
        output_dir=args.output_dir,
    )
    print(f"readiness report generated: {report.markdown_path}")
    print(f"batch_id: {report.batch_id}")
    print(f"status: {report.status.value}")
    print(f"blocking_issue_count: {report.blocking_issue_count}")
    print(f"warning_count: {report.warning_count}")
    print(f"markdown: {report.markdown_path}")
    print(f"json: {report.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
