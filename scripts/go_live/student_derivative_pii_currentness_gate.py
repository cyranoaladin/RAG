"""Préqualification pure, fail-closed, des dérivés étudiants #300/#312.

Une preuve portée par le PDF n'est jamais une preuve PII du texte transformé.
La candidate et le registre PII ``PASS_BY_PR300_FULL_DOCUMENT_GATE`` restent
non activables sans revue du texte exact et reçu source courant/revocation.
Ce contrôle ne publie, ne rescelle et ne modifie aucun environnement.
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

EVIDENCE_RELATIVE = Path("docs/reports/go_live/student_rights_evidence")
RELEASE_RELATIVE = Path(
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_student_public_v1/release-eb39f6cd0423e184/profile_gate"
)
SHA64 = re.compile(r"[0-9a-f]{64}\Z")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(raw: bytes) -> Mapping[str, Any] | None:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.utcoffset() == timezone.utc.utcoffset(parsed) else None


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and SHA64.fullmatch(value) is not None


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False) + "\n").encode("utf-8")


def _source_checkpoint_ok(
    checkpoint: Mapping[str, Any], source_sha: str, source_uri: str,
    attribution_date: str, logical_sha: str,
) -> bool:
    source = checkpoint.get("source_provenance")
    if not isinstance(source, dict):
        return False
    unsigned = dict(checkpoint)
    unsigned.pop("checkpoint_sha256", None)
    current_ref = source.get("currentness_evidence_ref")
    revocation_ref = source.get("revocation_evidence_ref")
    update = source.get("source_updated_at")
    return (
        checkpoint.get("kind") == "NEXUS-STUDENT-SOURCE-PROVENANCE-CHECKPOINT-V1"
        and checkpoint.get("checkpoint_sha256") == logical_sha
        and _sha(_canonical(unsigned)) == logical_sha
        and checkpoint.get("content_sha256") == source_sha
        and source.get("status") == "EXACT_CURRENT_SOURCE"
        and source.get("currentness_status") == "PASS"
        and source.get("revocation_status") == "PASS_CURRENT_OFFICIAL_PUBLICATION"
        and source.get("retraction_notice_associated") is False
        and isinstance(current_ref, dict)
        and current_ref.get("pdf_sha256") == source_sha
        and current_ref.get("pdf_url") == source_uri
        and isinstance(revocation_ref, dict)
        and revocation_ref.get("pdf_sha256") == source_sha
        and revocation_ref.get("pdf_url") == source_uri
        and _valid_sha(revocation_ref.get("listing_capture_receipt_sha256"))
        and isinstance(update, dict)
        and update.get("date") == attribution_date
        and _utc(source.get("currentness_observed_at_utc")) is not None
        and _utc(source.get("revocation_observed_at_utc")) is not None
    )


def assess_derivative(
    *, text: bytes | None, receipt_raw: bytes | None, artifact: Mapping[str, Any],
    manifest_entry: Mapping[str, Any], source_raw: bytes | None,
    source_index_ref: Mapping[str, Any] | None, provenance: Mapping[str, Any] | None,
    source_checkpoint_raw: bytes | None, independent: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Évalue des octets fournis par le lecteur ; aucun accès disque/réseau."""
    reasons: set[str] = set()
    derivative_sha = artifact.get("content_sha256")
    source_sha = artifact.get("source_pdf_sha256")
    receipt_sha = artifact.get("derivative_receipt_sha256")
    if not _valid_sha(derivative_sha) or not isinstance(text, bytes) or _sha(text) != derivative_sha:
        reasons.add("DERIVATIVE_TEXT_SHA_MISMATCH")
    if (not _valid_sha(receipt_sha) or not isinstance(receipt_raw, bytes)
            or _sha(receipt_raw) != receipt_sha):
        reasons.add("DERIVATIVE_RECEIPT_SHA_MISMATCH")
    receipt = _json(receipt_raw) if isinstance(receipt_raw, bytes) else None
    if receipt is None:
        reasons.add("DERIVATIVE_RECEIPT_INVALID")
        receipt = {}
    if (manifest_entry.get("derivative_content_sha256") != derivative_sha
            or manifest_entry.get("source_content_sha256") != source_sha
            or manifest_entry.get("derivative_receipt_sha256") != receipt_sha
            or manifest_entry.get("source_disposition") != "REPLACE_WITH_NEW_CONTENT"
            or manifest_entry.get("derivative_disposition") != "APPROVE_PUBLIC"
            or source_sha == derivative_sha):
        reasons.add("CANDIDATE_IDENTITY_MISMATCH")
    if (receipt.get("kind") != "NEXUS-STUDENT-NATIVE-TEXT-DERIVATIVE-V1"
            or receipt.get("source_content_sha256") != source_sha
            or receipt.get("derivative_content_sha256") != derivative_sha
            or not isinstance(text, bytes)
            or receipt.get("derivative_byte_count") != len(text)
            or receipt.get("status") != "PREPARED_PRIVATE"
            or receipt.get("all_source_pages_inspected") is not True
            or any(receipt.get(key) is not False for key in (
                "ocr_used", "images_copied", "graphic_renders_copied"))):
        reasons.add("DERIVATIVE_RECEIPT_INCOMPLETE")
    attribution = receipt.get("source_attribution")
    citation = artifact.get("citation")
    if not isinstance(attribution, dict) or not isinstance(citation, dict):
        reasons.add("ATTRIBUTION_MISSING")
        attribution, citation = {}, {}
    if (manifest_entry.get("citation") != attribution
            or any(citation.get(key) != val for key, val in attribution.items())
            or citation.get("source_pdf_sha256") != source_sha
            or _utc(attribution.get("source_updated_at")) is None
            or not isinstance(attribution.get("source_uri"), str)
            or not attribution["source_uri"].startswith("https://eduscol.education.gouv.fr/")
            or not all(attribution.get(key) for key in (
                "source_label", "licensor", "licence_id", "derivative_notice"))):
        reasons.add("ATTRIBUTION_DATE_MISMATCH")
    if (not isinstance(source_raw, bytes) or source_index_ref is None
            or source_index_ref.get("sha256") != _sha(source_raw)):
        reasons.add("PR300_SOURCE_EVIDENCE_DIGEST_MISMATCH")
    source = _json(source_raw) if isinstance(source_raw, bytes) else None
    if (source is None or source.get("content_sha256") != source_sha
            or source.get("derivative_content_sha256") != derivative_sha
            or source.get("derivative_receipt_sha256") != receipt_sha
            or not isinstance(provenance, dict)
            or source.get("source_receipt_sha256")
            != provenance.get("checkpoint_file_sha256")
            or source.get("source_disposition") != "REPLACE_WITH_NEW_CONTENT"
            or source.get("derivative_disposition") != "APPROVE_PUBLIC"
            or source.get("scan_complete") is not True
            or source.get("images_and_annexes_checked") is not True):
        reasons.add("PR300_SOURCE_DECISION_MISMATCH")

    pages = receipt.get("pages")
    page_count = receipt.get("source_page_count")
    if (not isinstance(pages, list) or not isinstance(page_count, int)
            or isinstance(page_count, bool) or page_count < 1
            or [p.get("page_number") for p in pages if isinstance(p, dict)]
            != list(range(1, page_count + 1))
            or len(pages) != page_count or artifact.get("page_count") != page_count):
        reasons.add("PAGE_COVERAGE_INVALID")
        pages = []
        page_count = 0
    excluded_pages: list[int] = []
    header = (
        b"NEXUS-STUDENT-TEXT-DERIVATIVE-V2\n"
        + json.dumps({"source_pdf_sha256": source_sha, **attribution},
                     sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        + b"\n"
    )
    if not isinstance(text, bytes) or not text.startswith(header):
        reasons.add("DERIVATIVE_HEADER_MISMATCH")
    previous_end = len(header)
    for page in pages:
        start, end = page.get("byte_start"), page.get("byte_end")
        if (not isinstance(text, bytes) or type(start) is not int or type(end) is not int
                or start != previous_end or end < start or end > len(text)
                or page.get("derived_page_text_sha256") != _sha(text[start:end])):
            reasons.add("PAGE_TEXT_LINEAGE_MISMATCH")
            break
        previous_end = end
        selected = page.get("selected_block_indices")
        blocks = page.get("all_blocks")
        excluded = page.get("excluded_blocks")
        groups = page.get("review_groups")
        if (not isinstance(selected, list) or not isinstance(blocks, list)
                or not isinstance(excluded, list) or not isinstance(groups, list)
                or page.get("packet_pii_status") != "CLEARED"):
            reasons.add("PAGE_BLOCK_POLICY_INVALID")
            continue
        selected_set = set(selected)
        excluded_set = {b.get("block_index") for b in excluded if isinstance(b, dict)}
        all_set = {b.get("block_index") for b in blocks if isinstance(b, dict)}
        if (selected_set & excluded_set or selected_set | excluded_set != all_set
                or len(all_set) != len(blocks)
                or any(b.get("block_class") != "SAFE_TEXT_CANDIDATE"
                       for b in blocks if b.get("block_index") in selected_set)
                or any(not isinstance(b.get("reason_code"), str) or not b["reason_code"]
                       for b in excluded)):
            reasons.add("PAGE_BLOCK_POLICY_INVALID")
        if selected and not groups or not selected and groups:
            reasons.add("PAGE_GROUP_LINEAGE_MISMATCH")
        if not selected:
            excluded_pages.append(page["page_number"])
        for group in groups:
            gstart, gend = group.get("byte_start"), group.get("byte_end")
            group_indices = group.get("block_indices")
            if (type(gstart) is not int or type(gend) is not int
                    or gstart < start or gend > end or gend <= gstart
                    or not isinstance(group_indices, list) or not group_indices
                    or not set(group_indices) <= selected_set):
                reasons.add("PAGE_GROUP_LINEAGE_MISMATCH")
                continue
            by_index = {block.get("block_index"): block for block in blocks}
            group_parts = []
            for block_index in group_indices:
                block = by_index.get(block_index)
                if not isinstance(block, dict):
                    reasons.add("PAGE_GROUP_LINEAGE_MISMATCH")
                    break
                bstart, bend = block.get("byte_start"), block.get("byte_end")
                if (type(bstart) is not int or type(bend) is not int
                        or bstart < gstart or bend > gend or bend <= bstart):
                    reasons.add("PAGE_GROUP_LINEAGE_MISMATCH")
                    break
                group_parts.append(text[bstart:bend])
            if (group_parts and (gstart != by_index[group_indices[0]].get("byte_start")
                                 or gend != by_index[group_indices[-1]].get("byte_end")
                                 or group.get("group_text_sha256")
                                 != _sha(b"\n\n".join(group_parts)))):
                reasons.add("PAGE_GROUP_LINEAGE_MISMATCH")
    if pages and isinstance(text, bytes) and previous_end != len(text):
        reasons.add("PAGE_TEXT_LINEAGE_MISMATCH")
    if artifact.get("excluded_source_pages") != excluded_pages:
        reasons.add("EXCLUDED_PAGES_MISMATCH")
    chunks = artifact.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        reasons.add("CHUNK_PAGE_LINEAGE_INVALID")
    else:
        for chunk in chunks:
            start, end = chunk.get("page_start"), chunk.get("page_end")
            if (type(start) is not int or type(end) is not int or start < 1
                    or end < start or end > page_count):
                reasons.add("CHUNK_PAGE_LINEAGE_INVALID")
                break
            if set(range(start, end + 1)) & set(excluded_pages):
                reasons.add("CHUNK_ON_EXCLUDED_PAGE")
                break

    structural_reasons = set(reasons)
    if independent is None:
        reasons.add("DERIVATIVE_PII_REVIEW_MISSING")
    elif (independent.get("kind") != "NEXUS_STUDENT_DERIVATIVE_PII_CURRENTNESS_EVIDENCE_V1"
          or independent.get("derivative_content_sha256") != derivative_sha
          or independent.get("source_pdf_sha256") != source_sha
          or independent.get("derivative_receipt_sha256") != receipt_sha
          or independent.get("reviewed_derivative_text_sha256") != derivative_sha
          or independent.get("pii_scan_scope") != "FULL_DERIVATIVE_TEXT"
          or independent.get("pii_status") != "PASS"):
        reasons.add("DERIVATIVE_PII_REVIEW_MISMATCH")

    checkpoint_sha = receipt.get("source_provenance_checkpoint_sha256")
    checkpoint_file_sha = provenance.get("checkpoint_file_sha256") if isinstance(provenance, dict) else None
    if (not isinstance(provenance, dict)
            or provenance.get("content_sha256") != source_sha
            or not _valid_sha(checkpoint_file_sha)
            or provenance.get("source_status") != "EXACT_CURRENT_SOURCE"
            or provenance.get("currentness_status") != "PASS"):
        reasons.add("SOURCE_CURRENTNESS_UNBOUND")
    if not isinstance(source_checkpoint_raw, bytes):
        reasons.add("CURRENTNESS_CHECKPOINT_MISSING")
    elif _sha(source_checkpoint_raw) != checkpoint_file_sha or not _source_checkpoint_ok(
        _json(source_checkpoint_raw) or {}, source_sha,
        str(attribution.get("source_uri", "")), str(attribution.get("source_updated_at", "")),
        str(checkpoint_sha),
    ):
        reasons.add("SOURCE_CURRENTNESS_UNBOUND")
    if (independent is not None and (
            independent.get("source_provenance_checkpoint_sha256") != checkpoint_sha
            or independent.get("source_checkpoint_file_sha256") != checkpoint_file_sha
            or independent.get("source_checkpoint_exact_bytes_match") is not True
            or independent.get("source_uri") != attribution.get("source_uri")
            or independent.get("source_updated_at") != attribution.get("source_updated_at")
            or _utc(independent.get("verified_at_utc")) is None
            or (_utc(independent.get("verified_at_utc")) is not None
                and _utc(attribution.get("source_updated_at")) is not None
                and _utc(independent["verified_at_utc"]) < _utc(attribution["source_updated_at"])))):
        reasons.add("ATTRIBUTION_DATE_MISMATCH")
    if (not isinstance(provenance, dict)
            or provenance.get("revocation_status") != "PASS_CURRENT_OFFICIAL_PUBLICATION"
            or independent is None
            or independent.get("revocation_status") != "PASS_CURRENT_OFFICIAL_PUBLICATION"
            or independent.get("revocation_check_source_uri") != attribution.get("source_uri")
            or independent.get("currentness_status") != "PASS"):
        reasons.add("REVOCATION_UNPROVEN")
    return {
        "content_sha256": derivative_sha,
        "source_pdf_sha256": source_sha,
        "structural_status": "PASS" if not structural_reasons else "BLOCKED",
        "publication_status": "PASS" if not reasons else "BLOCKED",
        "reasons": sorted(reasons),
    }


def _safe_child(root: Path, relative: str) -> Path | None:
    child = (root / relative).resolve()
    return child if child.is_relative_to(root.resolve()) else None


def assess_repository(
    root: Path, private_root: Path, *, independent_root: Path | None = None,
    source_checkpoint_root: Path | None = None,
) -> dict[str, Any]:
    """Lecture seule du candidat #312 et du pack approuvé #300."""
    evidence = root / EVIDENCE_RELATIVE
    release = root / RELEASE_RELATIVE
    approval = json.loads((evidence / "pr300_final_authority_approval.json").read_bytes())
    index_raw = (evidence / "index.json").read_bytes()
    manifest_raw = (evidence / "public_derivative_candidate_manifest_20261010.json").read_bytes()
    if (approval.get("sha256", {}).get("evidence_index") != _sha(index_raw)
            or approval.get("sha256", {}).get("candidate_manifest") != _sha(manifest_raw)):
        raise ValueError("PR300_APPROVED_PACK_DIGEST_MISMATCH")
    index, manifest = json.loads(index_raw), json.loads(manifest_raw)
    aggregate = json.loads((release / "production-profile-gate.release.json").read_bytes())
    artifacts_raw = (release / "artifacts.release.json").read_bytes()
    if (aggregate.get("authorities", {}).get("candidate_manifest_sha256") != _sha(manifest_raw)
            or aggregate["authorities"].get("delegated_evidence_pack_sha256") != _sha(index_raw)
            or aggregate["authorities"].get("pr300_final_authority_receipt_sha256")
            != _sha((evidence / "pr300_final_authority_approval.json").read_bytes())
            or aggregate.get("artifact_registry", {}).get("sha256") != _sha(artifacts_raw)
            or aggregate.get("release_mode") != "candidate"):
        raise ValueError("PR312_CANDIDATE_BINDING_MISMATCH")
    artifacts = json.loads(artifacts_raw).get("artifacts")
    entries = manifest.get("entries")
    if (not isinstance(artifacts, list) or not isinstance(entries, list)
            or len(artifacts) != 253 or len(entries) != 253):
        raise ValueError("DERIVATIVE_POPULATION_INVALID")
    by_derivative = {e["derivative_content_sha256"]: e for e in entries}
    by_source = {e["source_content_sha256"]: e for e in entries}
    if len(by_derivative) != 253 or len(by_source) != 253:
        raise ValueError("DERIVATIVE_POPULATION_DUPLICATE")
    independent_entries: Mapping[str, str] = {}
    if independent_root is not None:
        index_file = independent_root / "index.json"
        if not index_file.is_file():
            raise ValueError("INDEPENDENT_EVIDENCE_INDEX_MISSING")
        independent_index_raw = index_file.read_bytes()
        if (aggregate["authorities"].get(
                "derivative_pii_currentness_evidence_index_sha256")
                != _sha(independent_index_raw)):
            raise ValueError("INDEPENDENT_EVIDENCE_INDEX_UNSEALED")
        independent_index = _json(independent_index_raw)
        if (independent_index is None
                or independent_index.get("kind")
                != "NEXUS_STUDENT_DERIVATIVE_PII_CURRENTNESS_INDEX_V1"
                or independent_index.get("candidate_manifest_sha256") != _sha(manifest_raw)
                or not isinstance(independent_index.get("entries"), dict)
                or set(independent_index["entries"]) != set(by_derivative)
                or not all(_valid_sha(v) for v in independent_index["entries"].values())):
            raise ValueError("INDEPENDENT_EVIDENCE_INDEX_INVALID")
        independent_entries = independent_index["entries"]
    provenance_index = json.loads((evidence / "provenance/index.json").read_bytes())
    provenance_rows = {row["content_sha256"]: row for row in provenance_index["rows"]}
    results = []
    for artifact in artifacts:
        derivative_sha = artifact["content_sha256"]
        entry = by_derivative.get(derivative_sha)
        if entry is None:
            raise ValueError("DERIVATIVE_CANDIDATE_SET_MISMATCH")
        source_sha = artifact["source_pdf_sha256"]
        if by_source.get(source_sha) != entry:
            raise ValueError("DERIVATIVE_SOURCE_SET_MISMATCH")
        receipt_sha = artifact["derivative_receipt_sha256"]
        receipt_file = evidence / "derivative_receipts" / receipt_sha[:2] / f"{receipt_sha}.json"
        source_file = evidence / f"{source_sha}.json"
        checkpoint_ref = provenance_rows.get(source_sha)
        checkpoint_path = (
            _safe_child(source_checkpoint_root or root, checkpoint_ref["checkpoint_relpath"])
            if checkpoint_ref is not None else None
        )
        qualification_path = (
            independent_root / f"{derivative_sha}.json"
            if independent_root is not None else None
        )
        qualification_raw = (
            qualification_path.read_bytes()
            if qualification_path is not None and qualification_path.is_file() else None
        )
        if qualification_raw is not None and _sha(qualification_raw) != independent_entries[derivative_sha]:
            raise ValueError("INDEPENDENT_EVIDENCE_DIGEST_MISMATCH")
        result = assess_derivative(
            text=(private_root / f"{derivative_sha}.txt").read_bytes()
            if (private_root / f"{derivative_sha}.txt").is_file() else None,
            receipt_raw=receipt_file.read_bytes() if receipt_file.is_file() else None,
            artifact=artifact, manifest_entry=entry,
            source_raw=source_file.read_bytes() if source_file.is_file() else None,
            source_index_ref=index["artifacts"].get(source_sha),
            provenance=checkpoint_ref,
            source_checkpoint_raw=checkpoint_path.read_bytes()
            if checkpoint_path is not None and checkpoint_path.is_file() else None,
            independent=_json(qualification_raw) if qualification_raw is not None else None,
        )
        results.append(result)
    reasons = Counter(reason for result in results for reason in result["reasons"])
    passed = sum(row["publication_status"] == "PASS" for row in results)
    return {
        "kind": "NEXUS_STUDENT_DERIVATIVE_PII_CURRENTNESS_PREFLIGHT_V1",
        "release_id": aggregate["release_id"],
        "candidate_manifest_sha256": _sha(manifest_raw),
        "pr300_evidence_index_sha256": _sha(index_raw),
        "artifact_registry_sha256": _sha(artifacts_raw),
        "artifact_count": len(results),
        "structural_pass_count": sum(row["structural_status"] == "PASS" for row in results),
        "publication_pass_count": passed,
        "publication_blocked_count": len(results) - passed,
        "missing_derivative_pii_review_count": reasons["DERIVATIVE_PII_REVIEW_MISSING"],
        "missing_currentness_checkpoint_count": reasons["CURRENTNESS_CHECKPOINT_MISSING"],
        "reason_counts": dict(sorted(reasons.items())),
        "verdict": "PASS" if passed == 253 else "BLOCKED",
        "rows": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path,
                        default=Path(__file__).resolve().parents[2])
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--independent-evidence-root", type=Path)
    parser.add_argument("--source-checkpoint-root", type=Path)
    args = parser.parse_args()
    result = assess_repository(args.repository_root, args.private_root,
                               independent_root=args.independent_evidence_root,
                               source_checkpoint_root=args.source_checkpoint_root)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"},
                     sort_keys=True, ensure_ascii=False))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
