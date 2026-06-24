from __future__ import annotations

import argparse
from pathlib import Path

from rag_pedago.imports.coverage import build_coverage_report

DEFAULT_TAXONOMIES = [
    Path("taxonomy/maths/terminale_specialite.yml"),
    Path("taxonomy/nsi/terminale.yml"),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a pedagogical coverage report from local JSONL manifests."
    )
    parser.add_argument("directory_path", type=Path)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--taxonomy", action="append", type=Path, default=[])
    parser.add_argument("--priority-notion", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, default=Path("data/reports"))
    args = parser.parse_args()

    taxonomy_paths = args.taxonomy or DEFAULT_TAXONOMIES
    report = build_coverage_report(
        directory_path=args.directory_path,
        batch_id=args.batch_id,
        taxonomy_paths=taxonomy_paths,
        priority_notions=args.priority_notion,
        output_dir=args.output_dir,
    )
    print(f"coverage report generated: {report.markdown_path}")
    print(f"batch_id: {report.batch_id}")
    print(f"status: {report.status.value}")
    print(f"documents_valid: {report.documents_valid}")
    print(f"notions_known: {len(report.notions_known)}")
    print(f"notions_unknown: {len(report.notions_unknown)}")
    print(f"missing_priority_notions: {len(report.missing_priority_notions)}")
    print(f"markdown: {report.markdown_path}")
    print(f"json: {report.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
