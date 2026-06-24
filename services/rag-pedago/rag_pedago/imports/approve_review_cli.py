from __future__ import annotations

import argparse
from pathlib import Path

from rag_pedago.imports.review import ReviewerPolicy, approve_review_package


def main() -> int:
    parser = argparse.ArgumentParser(description="Approve or reject a manifest review package.")
    parser.add_argument("review_package_json", type=Path)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--decision", required=True, choices=["approved", "rejected"])
    parser.add_argument("--notes")
    parser.add_argument("--output-dir", type=Path, default=Path("data/reviews"))
    parser.add_argument("--allowed-reviewer", action="append", default=[])
    parser.add_argument("--require-known-reviewer", action="store_true")
    parser.add_argument("--audit-ledger", type=Path)
    args = parser.parse_args()

    decision = approve_review_package(
        review_package_json=args.review_package_json,
        reviewer=args.reviewer,
        decision=args.decision,
        notes=args.notes,
        output_dir=args.output_dir,
        reviewer_policy=ReviewerPolicy(
            allowed_reviewers=args.allowed_reviewer,
            require_known_reviewer=args.require_known_reviewer,
        ),
        ledger_db_path=args.audit_ledger,
    )
    path = args.output_dir / f"review_{decision.review_id}.json"
    print(f"review decision written: {path}")
    print(f"review_id: {decision.review_id}")
    print(f"batch_id: {decision.batch_id}")
    print(f"decision: {decision.decision}")
    print(f"reviewer: {decision.reviewer}")
    print(f"gate_json_sha256: {decision.gate_json_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
