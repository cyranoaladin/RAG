"""Autorité temporelle A2 du contenu public A1, sans mutation de sa préparation.

Les rapports d'entrée doivent être rejoués depuis les captures privées par le
producteur canonique avant l'appel. Ce module recoupe la population exacte et
les horloges ; il n'accorde ni publication ni accès à la base de données.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .public_successor_activation import PublicSuccessorContentVerdict, _read

KIND = "NEXUS_PUBLIC_SUCCESSOR_TEMPORAL_CONTINUITY_A2_V1"
SOURCE_KIND = "NEXUS_STUDENT_DERIVATIVE_SOURCE_CURRENTNESS_ATTESTATION_V1"
POLICY_ID = "PUBLIC_SUCCESSOR_A2_SEVEN_DAY_CURRENTNESS_V1"
POLICY_SHA256 = "13a9f27279c552968326920f9186735eeb55cc0f248a1094eb428ce15df8577c"
APPROVED_A1_ANCHOR_SHA256 = "1731e2a5690c4043dd21d02576d843f90dc90c7a2f7ec2cc736f7dd3563df7e0"
APPROVED_A1_RELEASE_ID = "student-public-successor-20261010-40b956c6f5ec0c60"
APPROVED_A2_AUTHORITY_SHA256 = "5beccf115b3d23473dd310f20fdd6ce31cc8bc38e0cc23918d936300c1fec9b4"
CFTR_SHA256 = "3f1ab328a0c11f40a0abf85dccdf29dc17d80159dc01bee189a10017d0fbd3e6"
VALIDITY = timedelta(days=7)
CAPTURE_WINDOW = timedelta(hours=1)
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class PublicSuccessorTemporalError(ValueError):
    """Une preuve de continuité, de source ou de révocation est absente."""


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _time(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PublicSuccessorTemporalError("UTC timestamp missing")
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise PublicSuccessorTemporalError("UTC timestamp invalid") from error
    if stamp.utcoffset() != UTC.utcoffset(stamp):
        raise PublicSuccessorTemporalError("non-UTC timestamp")
    return stamp


def _stamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise PublicSuccessorTemporalError("UTC clock required")
    return value.isoformat().replace("+00:00", "Z")


def _document(raw: bytes, label: str) -> dict[str, Any]:
    try:
        result = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicSuccessorTemporalError(f"{label} JSON invalid") from error
    if not isinstance(result, dict) or raw != canonical_bytes(result):
        raise PublicSuccessorTemporalError(f"{label} JSON not canonical")
    return result


def _identity(content: PublicSuccessorContentVerdict, release_root: Path) -> tuple[dict[str, Any], dict[str, str], dict[str, dict[str, Any]], str, str]:
    """Rejouer les octets A1, y compris la population de 253 sources et CFTR."""
    if (content.content_anchor_sha256 != APPROVED_A1_ANCHOR_SHA256
            or content.release_id != APPROVED_A1_RELEASE_ID):
        raise PublicSuccessorTemporalError("approved A1 anchor/release identity differs")
    if content.expected_counts != {
        "subjects": 11, "unique_artifacts": 253, "placements": 377, "unique_chunks": 3975,
    } or content.activation_allowed:
        raise PublicSuccessorTemporalError("A1 content counts or status differ")
    index = _read(release_root, "preparation-index.json", content.preparation_index_sha256)
    registry = _read(
        release_root / "profile_gate", "public_currentness_registry.json",
        content.currentness_registry_sha256,
    )
    artifacts = _read(
        release_root / "profile_gate", "artifacts.release.json",
        content.artifact_registry_sha256,
    )
    inclusion = _read(
        release_root / "profile_gate", "inclusion_attestation.json",
        index["inclusion_attestation_sha256"],
    )
    rows = artifacts.get("artifacts")
    entries = registry.get("entries")
    if (index.get("release_id") != content.release_id
            or index.get("private_cas_manifest_sha256") != registry.get("private_cas_manifest_sha256")
            or index.get("source_currentness_attestation_sha256")
            != registry.get("source_currentness_attestation_sha256")
            or inclusion.get("source_currentness_attestation_sha256")
            != index.get("source_currentness_attestation_sha256")
            or inclusion.get("private_cas_manifest_sha256")
            != index.get("private_cas_manifest_sha256")
            or registry.get("release_id") != content.release_id
            or not isinstance(rows, list) or len(rows) != 253
            or not isinstance(entries, list) or len(entries) != 253):
        raise PublicSuccessorTemporalError("A1 source/CAS identity differs")
    pairs: dict[str, str] = {}
    artifact_by_sha: dict[str, dict[str, Any]] = {}
    sealed_pairs: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("content_sha256"), str) or not isinstance(row.get("source_pdf_sha256"), str):
            raise PublicSuccessorTemporalError("A1 artifact identity malformed")
        pairs[row["content_sha256"]] = row["source_pdf_sha256"]
        artifact_by_sha[row["content_sha256"]] = row
    for row in entries:
        if not isinstance(row, dict) or not isinstance(row.get("content_sha256"), str) or not isinstance(row.get("source_pdf_sha256"), str):
            raise PublicSuccessorTemporalError("A1 currentness identity malformed")
        sealed_pairs[row["content_sha256"]] = row["source_pdf_sha256"]
    if (len(pairs) != 253 or len(sealed_pairs) != 253 or pairs != sealed_pairs
            or CFTR_SHA256 in pairs.values()
            or any(not isinstance(a, str) or not SHA256.fullmatch(a)
                   or not isinstance(b, str) or not SHA256.fullmatch(b)
                   for a, b in pairs.items())
            or any(row.get("currentness_status") != "PASS"
                   or row.get("revocation_status") != "PASS_CURRENT_OFFICIAL_PUBLICATION"
                   for row in entries)):
        raise PublicSuccessorTemporalError("A1 source population/CFTR differs")
    cas_sha = index["private_cas_manifest_sha256"]
    if not isinstance(cas_sha, str) or not SHA256.fullmatch(cas_sha):
        raise PublicSuccessorTemporalError("A1 private CAS digest invalid")
    candidate_sha = inclusion.get("source_candidate_manifest_sha256")
    if not isinstance(candidate_sha, str) or not SHA256.fullmatch(candidate_sha):
        raise PublicSuccessorTemporalError("candidate derivative manifest digest invalid")
    return index, pairs, artifact_by_sha, cas_sha, candidate_sha


def _verify_source_report(
    raw: bytes, pairs: dict[str, str], artifact_by_sha: dict[str, dict[str, Any]],
    expected_candidate_sha: str, *, as_of: datetime,
) -> dict[str, Any]:
    """Une capture tardive ne peut être remplacée par une date d'index réécrite."""
    report = _document(raw, "source attestation")
    checked = _time(report.get("fresh_source_checked_at_utc"))
    attested = _time(report.get("attested_at_utc"))
    if (report.get("kind") != SOURCE_KIND
            or report.get("candidate_manifest_sha256") != expected_candidate_sha
            or report.get("successor_release_binding") != "NOT_YET_SEALED"
            or report.get("decision_count") != 253
            or report.get("status_counts") != {"PASS": 253}
            or not checked <= attested <= as_of
            or as_of - checked > CAPTURE_WINDOW):
        raise PublicSuccessorTemporalError("source attestation status or capture window invalid")
    for field in ("fresh_source_index_file_sha256", "fresh_source_index_logical_sha256",
                  "producer_code_sha256"):
        if not isinstance(report.get(field), str) or not SHA256.fullmatch(report[field]):
            raise PublicSuccessorTemporalError(f"source {field} absent")
    rows = report.get("rows")
    if not isinstance(rows, list) or len(rows) != 253:
        raise PublicSuccessorTemporalError("source report count invalid")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise PublicSuccessorTemporalError("source row malformed")
        derivative = row.get("derivative_content_sha256")
        source = row.get("source_pdf_sha256")
        artifact = artifact_by_sha.get(derivative) if isinstance(derivative, str) else None
        if artifact is None:
            raise PublicSuccessorTemporalError("source derivative absent from A1")
        citation = artifact.get("citation") if isinstance(artifact, dict) else None
        unsigned = {k: v for k, v in row.items() if k != "evidence_sha256"}
        if (not isinstance(derivative, str) or derivative in seen
                or pairs.get(derivative) != source or source == CFTR_SHA256
                or not isinstance(citation, dict)
                or row.get("source_uri") != citation.get("source_uri")
                or row.get("derivative_receipt_sha256")
                != artifact.get("derivative_receipt_sha256")
                or row.get("status") != "PASS" or row.get("reason_codes") != []
                or row.get("evidence_sha256") != _sha(canonical_bytes(unsigned))):
            raise PublicSuccessorTemporalError("source row identity, status or digest differs")
        seen.add(derivative)
        for field in ("derivative_receipt_sha256", "fresh_listing_receipt_sha256",
                      "fresh_pdf_fetch_receipt_sha256", "fresh_source_checkpoint_file_sha256",
                      "fresh_source_checkpoint_sha256"):
            if not isinstance(row.get(field), str) or not SHA256.fullmatch(row[field]):
                raise PublicSuccessorTemporalError(f"source {field} absent")
        current = _time(row.get("currentness_observed_at_utc"))
        revocation = _time(row.get("revocation_observed_at_utc"))
        if any(not checked - CAPTURE_WINDOW <= value <= checked
               for value in (current, revocation)):
            raise PublicSuccessorTemporalError("source/revocation observation stale or future")
    if seen != set(pairs):
        raise PublicSuccessorTemporalError("source exact population differs")
    return report


def _exclusion_set(
    content: PublicSuccessorContentVerdict, release_root: Path,
    source_packet_raw: bytes, approval_raw: bytes,
    included_pairs: dict[str, str],
) -> tuple[str, str]:
    """Lier les 62 exclusions à l'inventaire de 315 approuvé dans #300."""
    try:
        packet = json.loads(source_packet_raw)
        approval = json.loads(approval_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicSuccessorTemporalError("PR300 authority JSON invalid") from error
    if not isinstance(packet, dict) or not isinstance(approval, dict):
        raise PublicSuccessorTemporalError("PR300 authority malformed")
    manifest = _read(
        release_root / "profile_gate", "production-profile-gate.release.json",
        content.content_manifest_sha256,
    )
    if (manifest.get("authorities", {}).get("pr300_final_authority_receipt_sha256")
            != _sha(approval_raw)
            or approval.get("sha256", {}).get("inventory_packet")
            != _sha(source_packet_raw)):
        raise PublicSuccessorTemporalError("PR300 packet not bound to A1 approval")
    rows = packet.get("artifacts")
    if not isinstance(rows, list) or len(rows) != 315:
        raise PublicSuccessorTemporalError("PR300 exact inventory count differs")
    source_shas = [row.get("content_sha256") for row in rows if isinstance(row, dict)]
    if (len(source_shas) != 315 or len(set(source_shas)) != 315
            or any(not isinstance(sha, str) or not SHA256.fullmatch(sha)
                   for sha in source_shas)):
        raise PublicSuccessorTemporalError("PR300 source identities invalid")
    excluded = sorted({str(sha) for sha in source_shas} - set(included_pairs.values()))
    if (not set(included_pairs.values()).issubset(source_shas)
            or len(excluded) != 62 or CFTR_SHA256 not in excluded):
        raise PublicSuccessorTemporalError("A1 exclusion set or CFTR differs")
    return _sha(canonical_bytes(excluded)), _sha(source_packet_raw)


def build_temporal_successor(
    content: PublicSuccessorContentVerdict, release_root: Path,
    issue_attestation_raw: bytes, *, source_packet_raw: bytes,
    approval_raw: bytes, issued_at_utc: datetime,
) -> dict[str, Any]:
    """Émettre A2 pour sept jours ; l'attestation privée a été rejouée en amont."""
    _stamp(issued_at_utc)
    index, pairs, artifact_by_sha, cas_sha, candidate_sha = _identity(content, release_root)
    report = _verify_source_report(
        issue_attestation_raw, pairs, artifact_by_sha, candidate_sha,
        as_of=issued_at_utc,
    )
    if (_sha(issue_attestation_raw) == index.get("source_currentness_attestation_sha256")
            or report["fresh_source_index_file_sha256"]
            == index.get("fresh_source_index_file_sha256")):
        raise PublicSuccessorTemporalError("A2 requires new source capture, not A1 replay")
    manifest = _read(
        release_root / "profile_gate", "production-profile-gate.release.json",
        content.content_manifest_sha256,
    )
    authorities = manifest.get("authorities")
    if not isinstance(authorities, dict) or any(
        not isinstance(authorities.get(field), str)
        or not SHA256.fullmatch(authorities[field])
        for field in ("public_rights_registry_sha256", "public_pii_registry_sha256")
    ):
        raise PublicSuccessorTemporalError("A1 rights/PII authority missing")
    pair_rows = [{"content_sha256": key, "source_pdf_sha256": pairs[key]}
                 for key in sorted(pairs)]
    exclusion_sha, packet_sha = _exclusion_set(
        content, release_root, source_packet_raw, approval_raw, pairs,
    )
    return {
        "kind": KIND,
        "policy_id": POLICY_ID,
        "policy_sha256": POLICY_SHA256,
        "status": "TEMPORAL_AUTHORITY_ONLY_NOT_ACTIVABLE",
        "activation_allowed": False,
        "content_anchor_sha256": content.content_anchor_sha256,
        "release_id": content.release_id,
        "content_manifest_sha256": content.content_manifest_sha256,
        "preparation_index_sha256": content.preparation_index_sha256,
        "artifact_registry_sha256": content.artifact_registry_sha256,
        "candidate_inventory_sha256": content.candidate_inventory_sha256,
        "currentness_registry_sha256": content.currentness_registry_sha256,
        "release_registry_sha256": content.release_registry_sha256,
        "private_cas_manifest_sha256": cas_sha,
        "rights_registry_sha256": authorities["public_rights_registry_sha256"],
        "pii_registry_sha256": authorities["public_pii_registry_sha256"],
        "source_population_sha256": _sha(canonical_bytes(pair_rows)),
        "source_inventory_packet_sha256": packet_sha,
        "excluded_source_set_sha256": exclusion_sha,
        "excluded_source_count": 62,
        "cftr_disposition": "EXCLUDE",
        "expected_counts": content.expected_counts,
        "subject_sha256_by_collection": content.subject_sha256_by_collection,
        "profile_sha256_by_collection": content.profile_sha256_by_collection,
        "initial_source_attestation_sha256": _sha(issue_attestation_raw),
        "initial_source_index_file_sha256": report["fresh_source_index_file_sha256"],
        "initial_source_index_logical_sha256": report["fresh_source_index_logical_sha256"],
        "issued_at_utc": _stamp(issued_at_utc),
        "valid_from_utc": _stamp(issued_at_utc),
        "valid_until_utc": _stamp(issued_at_utc + VALIDITY),
        "c_time_source_revalidation_required": True,
    }


def verify_temporal_authority_preissuance(
    content: PublicSuccessorContentVerdict, authority_raw: bytes, *, now_utc: datetime,
) -> datetime:
    """Lire l'autorité A2 figée pour proposer B, sans prétendre à la preuve C.

    Son empreinte est celle de l'émission dont les captures privées ont été
    rejouées. Le constat indépendant de révocation reste obligatoire à C.
    """
    _stamp(now_utc)
    if _sha(authority_raw) != APPROVED_A2_AUTHORITY_SHA256:
        raise PublicSuccessorTemporalError("approved A2 authority digest differs")
    authority = _document(authority_raw, "A2 authority")
    issued = _time(authority.get("issued_at_utc"))
    valid_from = _time(authority.get("valid_from_utc"))
    expiry = _time(authority.get("valid_until_utc"))
    if (content.content_anchor_sha256 != APPROVED_A1_ANCHOR_SHA256
            or content.release_id != APPROVED_A1_RELEASE_ID
            or authority.get("content_anchor_sha256") != content.content_anchor_sha256
            or authority.get("release_id") != content.release_id
            or authority.get("content_manifest_sha256") != content.content_manifest_sha256
            or authority.get("preparation_index_sha256") != content.preparation_index_sha256
            or authority.get("artifact_registry_sha256") != content.artifact_registry_sha256
            or authority.get("currentness_registry_sha256") != content.currentness_registry_sha256
            or authority.get("release_registry_sha256") != content.release_registry_sha256
            or authority.get("expected_counts") != content.expected_counts
            or authority.get("subject_sha256_by_collection") != content.subject_sha256_by_collection
            or authority.get("profile_sha256_by_collection") != content.profile_sha256_by_collection
            or authority.get("kind") != KIND or authority.get("policy_id") != POLICY_ID
            or authority.get("policy_sha256") != POLICY_SHA256
            or authority.get("status") != "TEMPORAL_AUTHORITY_ONLY_NOT_ACTIVABLE"
            or authority.get("activation_allowed") is not False
            or authority.get("c_time_source_revalidation_required") is not True
            or authority.get("excluded_source_count") != 62
            or authority.get("cftr_disposition") != "EXCLUDE"
            or issued != valid_from or expiry - issued != VALIDITY
            or not valid_from <= now_utc < expiry
            or expiry - now_utc < timedelta(hours=24)):
        raise PublicSuccessorTemporalError("A2 preissuance identity or validity differs")
    return expiry


def verify_temporal_successor(
    content: PublicSuccessorContentVerdict, release_root: Path,
    authority_raw: bytes, issue_attestation_raw: bytes,
    c_time_attestation_raw: bytes, *, source_packet_raw: bytes,
    approval_raw: bytes, now_utc: datetime,
    min_remaining: timedelta = timedelta(hours=24),
) -> datetime:
    """Vérifier A2 et un nouveau constat C, sans prolonger implicitement A1."""
    _stamp(now_utc)
    if min_remaining < timedelta(hours=24):
        raise PublicSuccessorTemporalError("C residual policy cannot be weakened")
    authority = _document(authority_raw, "A2 authority")
    issued = _time(authority.get("issued_at_utc"))
    valid_from = _time(authority.get("valid_from_utc"))
    if issued != valid_from or not valid_from <= now_utc:
        raise PublicSuccessorTemporalError("A2 issued in future")
    rebuilt = build_temporal_successor(
        content, release_root, issue_attestation_raw,
        source_packet_raw=source_packet_raw, approval_raw=approval_raw,
        issued_at_utc=issued,
    )
    if authority != rebuilt:
        raise PublicSuccessorTemporalError("A2 authority differs from exact evidence")
    expiry = _time(authority["valid_until_utc"])
    if expiry - now_utc < min_remaining:
        raise PublicSuccessorTemporalError("A2 residual validity insufficient")
    if _sha(c_time_attestation_raw) == _sha(issue_attestation_raw):
        raise PublicSuccessorTemporalError("C requires independent post-A2 source capture")
    _, pairs, artifact_by_sha, _, candidate_sha = _identity(content, release_root)
    pulse = _verify_source_report(
        c_time_attestation_raw, pairs, artifact_by_sha, candidate_sha,
        as_of=now_utc,
    )
    if (_time(pulse["fresh_source_checked_at_utc"]) <= issued
            or any(_time(row["currentness_observed_at_utc"]) <= issued
                   or _time(row["revocation_observed_at_utc"]) <= issued
                   for row in pulse["rows"])):
        raise PublicSuccessorTemporalError("C source observation predates A2 issuance")
    return expiry
