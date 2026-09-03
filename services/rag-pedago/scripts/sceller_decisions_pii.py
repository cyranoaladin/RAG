#!/usr/bin/env python3
"""Scelle structurellement un ensemble de décisions PII rédigé par le reviewer (ADR-0047).

Cet outil ne décide rien. Il confronte un BROUILLON (hors dépôt, une entrée par
paquet de revue) à l'index des paquets : chaque contenu de l'index doit avoir
sa décision, aucune décision ne peut viser un contenu hors index, et tout ce
qui lie la décision à sa mesure — instruments, empreinte du paquet, classes,
compte, pages — vient de l'INDEX, jamais du brouillon. Il écrit ensuite la
forme canonique versionnable (`governance/pii-review-decisions/<id>.json`),
que seuls la review GitHub (ADR-0025) et le reçu de liaison (ADR-0035) rendent
opposables.

    # 1. générer le brouillon à remplir par le reviewer (hors dépôt)
    python scripts/sceller_decisions_pii.py brouillon \\
        --index docs/reports/evidence-index/pii_review_index_20260902.json \\
        --decision-set-id pii-review-2026-09-02-lot-1-2 \\
        --corpus-manifest-sha256 <sha> --reviewer-login abenrhouma \\
        --sortie ~/nexus-pii-review-20260902/decisions.draft.json

    # 2. sceller le brouillon rempli en forme canonique
    python scripts/sceller_decisions_pii.py sceller \\
        --draft ~/nexus-pii-review-20260902/decisions.draft.json \\
        --index docs/reports/evidence-index/pii_review_index_20260902.json \\
        --sortie governance/pii-review-decisions/pii-review-2026-09-02-lot-1-2.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
for root in (SERVICE_ROOT, SERVICE_ROOT.parents[1] / "packages/contracts/src"):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from nexus_contracts import (  # noqa: E402
    PII_REVIEW_DECISIONS_PROTOCOL_VERSION,
    PiiReviewDecisionSetV1,
    canonical_pii_review_decisions_path,
    parse_pii_review_decision_set,
)
from nexus_contracts.authority_artifacts import git_blob_sha1  # noqa: E402
from nexus_contracts.review_binding import (  # noqa: E402
    ReviewBindingError,
    TrustAnchor,
    require_challenge_is_bound,
    require_matches_pii_review_decision_set,
    verify_review_binding,
)

PLACEHOLDER = "__A_DECIDER__"
_DRAFT_FIELDS = {"decision", "decided_at", "justification", "findings"}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def brouillon(
    *,
    index_path: Path,
    sortie: Path,
    decision_set_id: str,
    corpus_manifest_sha256: str,
    reviewer_login: str,
) -> None:
    """Un brouillon nomme chaque paquet et attend une décision par paquet."""
    canonical_pii_review_decisions_path(decision_set_id)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    decisions = {
        entry["content_sha256"]: {
            "_titre": entry.get("title"),
            "_paquet": entry.get("bundle_dir"),
            "_classes": entry.get("signal_classes"),
            "_pages": entry.get("pages"),
            "findings": {
                finding["finding_id"]: {
                    "_pattern_id": finding["pattern_id"],
                    "_page": finding["page"],
                    **({"_checksum_valid": finding["checksum_valid"]} if "checksum_valid" in finding else {}),
                    "disposition": PLACEHOLDER,
                }
                for finding in sorted(entry.get("findings", []), key=lambda f: f["finding_id"])
            },
            "decision": PLACEHOLDER,
            "decided_at": PLACEHOLDER,
            "justification": {"category": PLACEHOLDER, "statement": PLACEHOLDER},
        }
        for entry in sorted(index["bundles"], key=lambda e: e["content_sha256"])
    }
    draft = {
        "_instructions": (
            "Une entrée par paquet, une disposition par finding (FALSE_POSITIVE_TECHNICAL | "
            "PUBLIC_INSTITUTIONAL_DATA | SYNTHETIC_EXAMPLE | PERSONAL_DATA_PRESENT). "
            "Un APPROVED exige que TOUS les findings soient admissibles ; un REJECTED "
            "exige au moins un PERSONAL_DATA_PRESENT. Remplir `decision` (APPROVED | REJECTED), "
            "`decided_at` (ISO 8601 avec fuseau), `justification.category` "
            "(INSTITUTIONAL_CONTACT | PEDAGOGICAL_EXAMPLE | FICTIONAL_IDENTITY | "
            "TECHNICAL_FALSE_POSITIVE | PUBLIC_OFFICIAL_PUBLICATION | "
            "PERSONAL_DATA_PRESENT) et `justification.statement` (20 à 1000 "
            "caractères, sans citer la matière brute). Les champs `_...` sont "
            "informatifs et ignorés au scellement. Un APPROVED ne peut pas porter "
            "PERSONAL_DATA_PRESENT."
        ),
        "decision_set_id": decision_set_id,
        "corpus_manifest_sha256": corpus_manifest_sha256,
        "reviewer_login": reviewer_login,
        "decisions": decisions,
    }
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")


def sceller(*, draft: Path, index_path: Path, sortie: Path) -> str:
    """Rend l'empreinte de l'ensemble scellé, ou lève (aucune écriture partielle)."""
    document = json.loads(draft.read_text(encoding="utf-8"))
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index.get("protocol_version") != "NEXUS-PII-REVIEW-INDEX-V1":
        raise ValueError("review index protocol is not supported")
    bundles = {entry["content_sha256"]: entry for entry in index["bundles"]}
    drafted = document.get("decisions")
    if not isinstance(drafted, dict):
        raise ValueError("draft decisions must be an object keyed by content_sha256")
    unknown = sorted(set(drafted) - set(bundles))
    if unknown:
        raise ValueError(f"draft decides contents not in the review index: {unknown}")
    undecided = sorted(set(bundles) - set(drafted))
    if undecided:
        raise ValueError(f"review index bundles left undecided: {undecided}")
    decisions = []
    for sha in sorted(bundles):
        entry = bundles[sha]
        raw = drafted[sha]
        if not isinstance(raw, dict):
            raise ValueError(f"draft entry for {sha} must be an object")
        provided = {key for key in raw if not key.startswith("_")}
        extra = provided - _DRAFT_FIELDS
        if extra:
            # Instruments, empreinte du paquet, classes, compte et pages viennent
            # de l'index : un brouillon ne peut pas les surcharger.
            raise ValueError(f"draft entry for {sha} may not set {sorted(extra)} — bound by the index")
        drafted_findings = raw.get("findings")
        if not isinstance(drafted_findings, dict):
            raise ValueError(f"draft entry for {sha} must disposition its findings")
        indexed = {finding["finding_id"]: finding for finding in entry.get("findings", [])}
        if set(drafted_findings) != set(indexed):
            raise ValueError(
                f"draft findings for {sha} differ from the review index "
                f"(undecided: {sorted(set(indexed) - set(drafted_findings))}, "
                f"unknown: {sorted(set(drafted_findings) - set(indexed))})"
            )
        findings = [
            {
                "finding_id": finding_id,
                "pattern_id": indexed[finding_id]["pattern_id"],
                "page": indexed[finding_id]["page"],
                "match_sha256": indexed[finding_id]["match_sha256"],
                "context_sha256": indexed[finding_id]["context_sha256"],
                "disposition": (drafted_findings[finding_id] or {}).get("disposition")
                if isinstance(drafted_findings[finding_id], dict)
                else drafted_findings[finding_id],
            }
            for finding_id in sorted(indexed)
        ]
        decisions.append(
            {
                "content_sha256": sha,
                "findings": findings,
                "policy_id": Path(str(index["policy_path"])).stem,
                "policy_sha256": index["policy_sha256"],
                "scanner_sha256": index["scanner_sha256"],
                "page_policy_id": index["page_policy_id"],
                "page_policy_sha256": index["page_policy_sha256"],
                "review_bundle_sha256": entry["bundle_sha256"],
                "signal_classes": list(entry["signal_classes"]),
                "signal_count": entry["signal_count"],
                "pages": list(entry["pages"]),
                "decision": raw.get("decision"),
                "justification": {**(raw.get("justification") or {}), "raw_pii_quoted": False},
                "reviewer_login": document.get("reviewer_login"),
                "decided_at": raw.get("decided_at"),
            }
        )
    decision_set = PiiReviewDecisionSetV1.model_validate(
        {
            "protocol_version": PII_REVIEW_DECISIONS_PROTOCOL_VERSION,
            "decision_set_id": document.get("decision_set_id"),
            "corpus_manifest_sha256": document.get("corpus_manifest_sha256"),
            "policy_id": Path(str(index["policy_path"])).stem,
            "policy_sha256": index["policy_sha256"],
            "scanner_sha256": index["scanner_sha256"],
            "page_policy_id": index["page_policy_id"],
            "page_policy_sha256": index["page_policy_sha256"],
            "review_index_sha256": _sha256_file(index_path),
            "decisions": decisions,
        }
    )
    raw_bytes = decision_set.canonical_bytes()
    parse_pii_review_decision_set(raw_bytes)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_bytes(raw_bytes)
    return decision_set.digest()


def verifier_recu(
    *,
    receipt: Path,
    decision_set: Path,
    anchor: Path,
    environment: str,
    repository: str,
    accepted_reviewers: tuple[str, ...],
    now: datetime | None = None,
) -> dict[str, object]:
    """Vérification hors ligne, sans secret, d'un reçu couvrant un ensemble de décisions."""
    raw = decision_set.read_bytes()
    parsed = parse_pii_review_decision_set(raw)
    trust_anchor = TrustAnchor.model_validate(json.loads(anchor.read_text(encoding="utf-8")))
    if now is None:
        now = datetime.now(UTC)
    try:
        binding = verify_review_binding(
            receipt.read_bytes(), trust_anchor=trust_anchor, environment=environment, now=now
        )
        require_challenge_is_bound(binding)
        require_matches_pii_review_decision_set(
            binding,
            decision_set_id=parsed.decision_set_id,
            decision_set_bytes=raw,
            decision_set_git_blob_sha1=git_blob_sha1(raw),
            expected_repository=repository,
            accepted_reviewers=accepted_reviewers,
        )
    except ReviewBindingError as exc:
        raise ValueError(f"receipt does not prove this decision set: {exc}") from exc
    return {
        "decision_set_id": parsed.decision_set_id,
        "decision_set_sha256": parsed.digest(),
        "reviewer_login": binding.reviewer_login,
        "review_id": binding.review_id,
        "pull_request": binding.pull_request,
        "head_sha": binding.head_sha,
        "expires_at": binding.expires_at.isoformat(),
        "approved_content_sha256": sorted(parsed.approved_content_sha256),
        "rejected_content_sha256": sorted(
            d.content_sha256 for d in parsed.decisions if d.decision == "REJECTED"
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("brouillon")
    b.add_argument("--index", type=Path, required=True)
    b.add_argument("--decision-set-id", required=True)
    b.add_argument("--corpus-manifest-sha256", required=True)
    b.add_argument("--reviewer-login", required=True)
    b.add_argument("--sortie", type=Path, required=True)
    s = sub.add_parser("sceller")
    s.add_argument("--draft", type=Path, required=True)
    s.add_argument("--index", type=Path, required=True)
    s.add_argument("--sortie", type=Path, required=True)
    v = sub.add_parser("verifier-recu")
    v.add_argument("--recu", type=Path, required=True)
    v.add_argument("--decision-set", type=Path, required=True)
    v.add_argument(
        "--anchor",
        type=Path,
        default=SERVICE_ROOT.parents[1] / "governance/trust-anchors/review-binding-v1.json",
    )
    v.add_argument("--environment", default="production")
    v.add_argument("--repository", default="cyranoaladin/RAG")
    v.add_argument("--reviewer", action="append", default=None)
    args = parser.parse_args(argv)
    if args.command == "verifier-recu":
        try:
            verdict = verifier_recu(
                receipt=args.recu, decision_set=args.decision_set, anchor=args.anchor,
                environment=args.environment, repository=args.repository,
                accepted_reviewers=tuple(args.reviewer or ("abenrhouma",)),
            )
        except (ValueError, Exception) as exc:  # noqa: BLE001 - frontière CLI, motif imprimé
            print(f"REFUS: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
        return 0
    if args.command == "brouillon":
        brouillon(
            index_path=args.index, sortie=args.sortie, decision_set_id=args.decision_set_id,
            corpus_manifest_sha256=args.corpus_manifest_sha256, reviewer_login=args.reviewer_login,
        )
        print(json.dumps({"brouillon": str(args.sortie)}))
        return 0
    try:
        digest = sceller(draft=args.draft, index_path=args.index, sortie=args.sortie)
    except ValueError as exc:
        print(f"REFUS: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"sortie": str(args.sortie), "sha256": digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
