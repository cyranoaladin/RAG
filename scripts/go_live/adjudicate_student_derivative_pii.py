"""Décide la PII des 253 dérivés exacts, sans texte ni match brut en sortie.

La décision complète le scan intégral #300 par un contrôle des octets dérivés et
de leur lignage natif. Elle ne qualifie ni l'actualité ni la révocation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from scan_student_derivative_pii import _canonical, _sha, _write_atomic, scan_repository
from student_derivative_pii_currentness_gate import EVIDENCE_RELATIVE

ROOT = Path(__file__).resolve().parents[2]
POLICY_RELATIVE = Path(
    "governance/student_public_rights/derivative_pii_adjudication_policy_v1.yml"
)
SCREEN_RELATIVE = Path(
    "docs/reports/go_live/student_derivative_pii_pattern_screen_20261010.json"
)

REQUIRED_POLICY = {
    "policy_id": "NEXUS_STUDENT_DERIVATIVE_PII_ADJUDICATION_V1",
    "decision_mode": "deterministic_fail_closed",
    "population": "exact_253_candidate_derivatives",
    "source_pii_status_required": "CLEARED",
    "source_full_document_scan_required": True,
    "source_annexes_scan_required": True,
    "source_pdf_exact_bytes_required": True,
    "native_block_exact_subset_required": True,
    "selected_block_class_required": "SAFE_TEXT_CANDIDATE",
    "all_derivative_bytes_pattern_scanned": True,
    "canonical_source_sha_metadata_matches_explained_only": True,
    "unresolved_pattern_hits_allowed": 0,
    "ocr_allowed": False,
    "images_allowed": False,
    "graphic_renders_allowed": False,
    "pii_pass_scope": "deterministic_known_pattern_and_source_review",
    "currentness_or_revocation_inferred": False,
    "unknown_or_conflicting_evidence_disposition": "BLOCKED",
}


def decide_artifact(
    screen: Mapping[str, Any], packet: Mapping[str, Any],
    source: Mapping[str, Any], receipt: Mapping[str, Any],
    *, native_blocks_reverified: int,
) -> dict[str, Any]:
    """Fonction pure : tout fait absent ou contradictoire bloque."""
    reasons = []
    derivative_sha = screen.get("content_sha256")
    source_sha = screen.get("source_pdf_sha256")
    if (not isinstance(derivative_sha, str)
            or re.fullmatch(r"[0-9a-f]{64}", derivative_sha) is None
            or not isinstance(source_sha, str)
            or re.fullmatch(r"[0-9a-f]{64}", source_sha) is None
            or derivative_sha == source_sha
            or packet.get("content_sha256") != source_sha
            or source.get("content_sha256") != source_sha
            or receipt.get("source_content_sha256") != source_sha
            or receipt.get("derivative_content_sha256") != derivative_sha):
        reasons.append("IDENTITY_MISMATCH")
    if (screen.get("derivative_receipt_sha256") is None
            or type(screen.get("text_byte_count")) is not int
            or screen["text_byte_count"] <= 0
            or screen.get("status") != "PATTERN_SCREEN_CLEAR_ONLY"
            or type(screen.get("unresolved_hits")) is not int
            or screen["unresolved_hits"] != 0
            or type(screen.get("source_hash_metadata_hits")) is not int
            or not isinstance(screen.get("pattern_hits"), dict)
            or not all(type(value) is int and value >= 0
                       for value in screen["pattern_hits"].values())
            or sum(screen["pattern_hits"].values())
            != screen["source_hash_metadata_hits"]):
        reasons.append("DERIVATIVE_PATTERN_SCREEN_UNCLEAR")
    if (packet.get("source_pii_status") != "CLEARED"
            or packet.get("source_pdf_sha256_verified") is not True):
        reasons.append("SOURCE_PII_UNCLEARED")
    scan = source.get("pdf_scan_evidence")
    if (source.get("scan_complete") is not True
            or source.get("images_and_annexes_checked") is not True
            or not isinstance(scan, dict)
            or scan.get("content_sha256") != source_sha
            or scan.get("exact_bytes_match") is not True
            or scan.get("full_document_scan_complete") is not True
            or scan.get("annexes_scan_complete") is not True):
        reasons.append("SOURCE_FULL_SCAN_UNPROVEN")
    if (receipt.get("all_source_pages_inspected") is not True
            or any(receipt.get(field) is not False for field in (
                "ocr_used", "images_copied", "graphic_renders_copied"))):
        reasons.append("DERIVATIVE_NON_TEXT_OR_UNINSPECTED")
    pages = receipt.get("pages")
    selected_count = 0
    if not isinstance(pages, list) or not pages:
        reasons.append("NATIVE_BLOCK_SUBSET_UNPROVEN")
    else:
        for page in pages:
            if not isinstance(page, dict):
                reasons.append("NATIVE_BLOCK_SUBSET_UNPROVEN")
                break
            selected = page.get("selected_block_indices")
            blocks = page.get("all_blocks")
            if (page.get("packet_pii_status") != "CLEARED"
                    or not isinstance(selected, list) or not isinstance(blocks, list)):
                reasons.append("NATIVE_BLOCK_SUBSET_UNPROVEN")
                break
            by_index = {block.get("block_index"): block for block in blocks
                        if isinstance(block, dict)}
            if (len(by_index) != len(blocks)
                    or any(by_index.get(index, {}).get("block_class")
                           != "SAFE_TEXT_CANDIDATE" for index in selected)):
                reasons.append("NATIVE_BLOCK_SUBSET_UNPROVEN")
                break
            selected_count += len(selected)
    if (type(native_blocks_reverified) is not int
            or native_blocks_reverified != selected_count or selected_count < 1):
        reasons.append("NATIVE_BLOCK_SUBSET_UNPROVEN")
    return {
        "derivative_content_sha256": derivative_sha,
        "source_pdf_sha256": source_sha,
        "derivative_receipt_sha256": screen.get("derivative_receipt_sha256"),
        "text_byte_count": screen.get("text_byte_count"),
        "native_blocks_reverified": native_blocks_reverified,
        "pii_scan_scope": "FULL_DERIVATIVE_TEXT",
        "pii_status": "PASS" if not reasons else "BLOCKED",
        "reason_codes": sorted(set(reasons)),
    }


def require_matching_screen(fresh: Mapping[str, Any], sealed: Mapping[str, Any]) -> None:
    """Le reçu scellé doit se rejouer exactement, hormis l'horodatage."""
    fresh_fields = {key: value for key, value in fresh.items()
                    if key != "scanned_at_utc"}
    sealed_fields = {key: value for key, value in sealed.items()
                     if key != "scanned_at_utc"}
    if fresh_fields != sealed_fields:
        raise ValueError("PATTERN_SCREEN_REPLAY_MISMATCH")


def adjudicate_repository(
    root: Path, private_root: Path, source_pdf_root: Path,
    *, decided_at_utc: str,
) -> dict[str, Any]:
    """Rejoue le scan privé et lie les décisions à #300 et #312."""
    policy_raw = (root / POLICY_RELATIVE).read_bytes()
    if yaml.safe_load(policy_raw) != REQUIRED_POLICY:
        raise ValueError("DERIVATIVE_PII_POLICY_MISMATCH")
    screen = scan_repository(
        root, private_root, scanned_at_utc=decided_at_utc,
        source_pdf_root=source_pdf_root,
    )
    if (screen["artifact_count"] != 253
            or screen["source_pdf_reverified_count"] != 253
            or screen["unresolved_artifact_count"] != 0):
        raise ValueError("DERIVATIVE_PII_POPULATION_OR_SOURCE_MISMATCH")
    screen_raw = (root / SCREEN_RELATIVE).read_bytes()
    sealed_screen = json.loads(screen_raw)
    require_matching_screen(screen, sealed_screen)
    evidence = root / EVIDENCE_RELATIVE
    packet_raw = (root / "docs/reports/go_live/"
                  "student_public_rights_individual_review_packet_20261009.json").read_bytes()
    approval = json.loads((evidence / "pr300_final_authority_approval.json").read_bytes())
    if approval.get("sha256", {}).get("inventory_packet") != _sha(packet_raw):
        raise ValueError("PR300_SOURCE_PACKET_UNAPPROVED")
    packet = json.loads(packet_raw)
    by_source = {row["content_sha256"]: row for row in packet["artifacts"]}
    if len(by_source) != 315:
        raise ValueError("PR300_SOURCE_PACKET_INVALID")
    index = json.loads((evidence / "index.json").read_bytes())
    rows = []
    selected_total = 0
    for item in screen["rows"]:
        source_sha = item["source_pdf_sha256"]
        receipt_sha = item["derivative_receipt_sha256"]
        source_raw = (evidence / f"{source_sha}.json").read_bytes()
        if index.get("artifacts", {}).get(source_sha, {}).get("sha256") != _sha(source_raw):
            raise ValueError("PR300_SOURCE_EVIDENCE_DIGEST_MISMATCH")
        receipt_raw = (evidence / "derivative_receipts" / receipt_sha[:2]
                       / f"{receipt_sha}.json").read_bytes()
        if _sha(receipt_raw) != receipt_sha:
            raise ValueError("DERIVATIVE_RECEIPT_DIGEST_MISMATCH")
        receipt = json.loads(receipt_raw)
        selected = sum(len(page["selected_block_indices"]) for page in receipt["pages"])
        selected_total += selected
        decision = decide_artifact(
            item, by_source.get(source_sha, {}), json.loads(source_raw), receipt,
            native_blocks_reverified=selected,
        )
        decision.update({
            "source_evidence_sha256": _sha(source_raw),
            "source_inventory_packet_sha256": _sha(packet_raw),
            "policy_sha256": _sha(policy_raw),
            "pattern_screen_sha256": _sha(_canonical(item)),
            "decision_kind": "NEXUS_STUDENT_DERIVATIVE_PII_DECISION_V1",
        })
        decision["evidence_sha256"] = _sha(_canonical(decision))
        rows.append(decision)
    if selected_total != screen["native_block_reverified_count"]:
        raise ValueError("NATIVE_BLOCK_REVERIFICATION_COUNT_MISMATCH")
    status_counts = Counter(row["pii_status"] for row in rows)
    return {
        "kind": "NEXUS_STUDENT_DERIVATIVE_PII_ADJUDICATION_V1",
        "decided_at_utc": decided_at_utc,
        "candidate_manifest_sha256": screen["candidate_manifest_sha256"],
        "artifact_registry_sha256": screen["artifact_registry_sha256"],
        "pr300_evidence_index_sha256": screen["pr300_evidence_index_sha256"],
        "source_inventory_packet_sha256": _sha(packet_raw),
        "policy_sha256": _sha(policy_raw),
        "pattern_screen_sha256": _sha(screen_raw),
        "producer_code_sha256": _sha(Path(__file__).read_bytes()),
        "source_pdf_reverified_count": screen["source_pdf_reverified_count"],
        "native_block_reverified_count": selected_total,
        "decision_count": len(rows),
        "status_counts": dict(status_counts),
        "pii_decision_scope": "DETERMINISTIC_FULL_DERIVATIVE_TEXT_AND_SOURCE_REVIEW",
        "currentness_revocation_status": "UNPROVEN_FOR_SUCCESSOR",
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--source-pdf-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    result = adjudicate_repository(args.repository_root, args.private_root,
                                   args.source_pdf_root, decided_at_utc=now)
    raw = _canonical(result)
    _write_atomic(args.output, raw)
    _write_atomic(args.output.with_suffix(args.output.suffix + ".sha256"),
                  f"{hashlib.sha256(raw).hexdigest()}  {args.output.name}\n".encode())
    print(json.dumps({"decision_count": result["decision_count"],
                      "status_counts": result["status_counts"],
                      "report_sha256": _sha(raw),
                      "currentness_revocation_status": result["currentness_revocation_status"]},
                     sort_keys=True))
    return 0 if result["status_counts"] == {"PASS": 253} else 1


if __name__ == "__main__":
    raise SystemExit(main())
