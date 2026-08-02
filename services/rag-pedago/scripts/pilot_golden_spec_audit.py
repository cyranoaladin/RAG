"""Diagnostic local de la spécification golden LOT39bis."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from pathlib import Path  # noqa: E402

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from rag_pedago.governance.pilot_golden import audit_pilot_golden  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """Affiche les verdicts sans modifier l'état local."""

    if argv:
        print("PILOT_GOLDEN_AUDIT_ERROR: unexpected_argument", file=sys.stderr)
        return 2
    result = audit_pilot_golden(service_root=SERVICE_ROOT)
    print("# Audit de la spécification golden LOT39bis")
    print()
    print(f"- Spécification: {result.specification_verdict}")
    print(f"- Revue humaine: {result.human_review_verdict}")
    print(f"- Verrou: {result.lock_verdict}")
    print(f"- Requêtes validées: {result.query_count}")
    digest = result.specification_digest or "indisponible"
    print(f"- Digest normatif: `{digest}`")
    print("- GO_LIVE: NO_GO")
    for reason in result.reasons:
        print(f"PILOT_GOLDEN_AUDIT_ERROR: {reason}", file=sys.stderr)
    if (
        result.specification_verdict != "SPECIFICATION_VALID"
        or result.human_review_verdict == "HUMAN_REVIEW_INVALID"
        or result.lock_verdict != "LOCK_VALID"
    ):
        return 1
    if result.human_review_verdict == "HUMAN_REVIEW_PENDING":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
