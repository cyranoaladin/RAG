"""A2 preserves A1 bytes while renewing only observed source authority."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from nexus_release_chain.public_successor_activation import verify_content_anchor
from nexus_release_chain.public_successor_temporal import (
    PublicSuccessorTemporalError,
    build_temporal_successor,
    verify_temporal_successor,
)

ROOT = Path(__file__).resolve().parents[3]
ANCHOR = ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261011.json"
RELEASE = ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_student_public_successor_v1/release-40b956c6f5ec0c60"
ATTESTATION = ROOT / "docs/reports/go_live/student_derivative_source_currentness_20261011.json"
SOURCE_PACKET = ROOT / "docs/reports/go_live/student_public_rights_individual_review_packet_20261009.json"
APPROVAL = ROOT / "docs/reports/go_live/student_rights_evidence/pr300_final_authority_approval.json"
PROOFS = {"source_packet_raw": SOURCE_PACKET.read_bytes(), "approval_raw": APPROVAL.read_bytes()}
ISSUED = datetime.fromisoformat("2026-10-11T15:06:00+00:00")


@pytest.fixture(scope="module")
def content():
    return verify_content_anchor(ANCHOR, hashlib.sha256(ANCHOR.read_bytes()).hexdigest(), RELEASE)


@pytest.fixture
def report():
    # Synthetic later capture for unit tests only. Production requires private
    # Chromium/PDF receipt replay, enforced by the producer CLI.
    result = json.loads(ATTESTATION.read_bytes())
    shift = timedelta(hours=1)
    result["fresh_source_index_file_sha256"] = "f" * 64
    result["fresh_source_index_logical_sha256"] = "e" * 64
    for field in ("fresh_source_checked_at_utc", "attested_at_utc"):
        result[field] = (datetime.fromisoformat(result[field])
                         + shift).isoformat().replace("+00:00", "Z")
    for row in result["rows"]:
        for field in ("currentness_observed_at_utc", "revocation_observed_at_utc"):
            row[field] = (datetime.fromisoformat(row[field])
                          + shift).isoformat().replace("+00:00", "Z")
        seal_row(row)
    return result


def canonical(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def seal_row(row: dict) -> None:
    row["evidence_sha256"] = hashlib.sha256(canonical({k: v for k, v in row.items() if k != "evidence_sha256"})).hexdigest()


def later_pulse(report: dict, shift: timedelta) -> dict:
    pulse = copy.deepcopy(report)
    for field in ("fresh_source_checked_at_utc", "attested_at_utc"):
        pulse[field] = (datetime.fromisoformat(pulse[field])
                        + shift).isoformat().replace("+00:00", "Z")
    for row in pulse["rows"]:
        for field in ("currentness_observed_at_utc", "revocation_observed_at_utc"):
            row[field] = (datetime.fromisoformat(row[field])
                          + shift).isoformat().replace("+00:00", "Z")
        seal_row(row)
    return pulse


def test_a2_seven_day_authority_and_fresh_c_pulse(content, report):
    raw = canonical(report)
    authority = build_temporal_successor(content, RELEASE, raw, issued_at_utc=ISSUED, **PROOFS)
    assert authority["valid_until_utc"] == "2026-10-18T15:06:00Z"
    assert authority["valid_from_utc"] == authority["issued_at_utc"]
    assert authority["expected_counts"] == {"subjects": 11, "unique_artifacts": 253, "placements": 377, "unique_chunks": 3975}
    assert authority["activation_allowed"] is False
    assert authority["policy_sha256"] == hashlib.sha256((
        ROOT / "governance/student_public_rights/public_successor_temporal_policy_a2_v1.yml"
    ).read_bytes()).hexdigest()
    expiry = verify_temporal_successor(
        content, RELEASE, canonical(authority), raw,
        canonical(later_pulse(report, timedelta(minutes=10))),
        now_utc=ISSUED + timedelta(minutes=10),
        min_remaining=timedelta(hours=24), **PROOFS,
    )
    assert expiry == ISSUED + timedelta(days=7)
    assert authority["excluded_source_count"] == 62
    assert authority["cftr_disposition"] == "EXCLUDE"


@pytest.mark.parametrize("mutation", [
    "missing", "duplicate", "source_drift", "revoked", "missing_page_proof",
    "cftr", "forged_time", "stale_capture", "source_uri", "receipt_identity",
])
def test_a2_refuses_incomplete_or_stale_253_source_proof(content, report, mutation):
    bad = copy.deepcopy(report)
    if mutation == "missing":
        bad["rows"].pop()
    elif mutation == "duplicate":
        bad["rows"][1] = copy.deepcopy(bad["rows"][0])
    elif mutation == "source_drift":
        bad["rows"][0]["source_pdf_sha256"] = "0" * 64
        seal_row(bad["rows"][0])
    elif mutation == "revoked":
        bad["rows"][0]["status"] = "BLOCKED"
        bad["rows"][0]["reason_codes"] = ["SOURCE_REVOKED"]
        seal_row(bad["rows"][0])
    elif mutation == "missing_page_proof":
        bad["rows"][0]["fresh_listing_receipt_sha256"] = None
        seal_row(bad["rows"][0])
    elif mutation == "cftr":
        bad["rows"][0]["source_pdf_sha256"] = "3f1ab328a0c11f40a0abf85dccdf29dc17d80159dc01bee189a10017d0fbd3e6"
        seal_row(bad["rows"][0])
    elif mutation == "forged_time":
        bad["rows"][0]["currentness_observed_at_utc"] = "2026-10-11T16:00:00Z"
        seal_row(bad["rows"][0])
    elif mutation == "source_uri":
        bad["rows"][0]["source_uri"] = "https://example.org/wrong.pdf"
        seal_row(bad["rows"][0])
    elif mutation == "receipt_identity":
        bad["rows"][0]["derivative_receipt_sha256"] = "0" * 64
        seal_row(bad["rows"][0])
    else:
        bad["fresh_source_checked_at_utc"] = "2026-10-10T14:00:00Z"
    with pytest.raises(PublicSuccessorTemporalError):
        build_temporal_successor(content, RELEASE, canonical(bad), issued_at_utc=ISSUED, **PROOFS)


def test_a2_refuses_reuse_of_a1_source_report(content):
    with pytest.raises(PublicSuccessorTemporalError):
        build_temporal_successor(
            content, RELEASE, ATTESTATION.read_bytes(),
            issued_at_utc=datetime.fromisoformat("2026-10-11T14:06:00+00:00"),
            **PROOFS,
        )


def test_a2_refuses_alternate_anchor_or_release(content, report):
    for alternate in (replace(content, content_anchor_sha256="0" * 64),
                      replace(content, release_id="other-release")):
        with pytest.raises(PublicSuccessorTemporalError):
            build_temporal_successor(alternate, RELEASE, canonical(report),
                                     issued_at_utc=ISSUED, **PROOFS)


def test_a2_refuses_changed_exclusion_inventory(content, report):
    packet = json.loads(SOURCE_PACKET.read_bytes())
    packet["artifacts"][0]["content_sha256"] = "0" * 64
    with pytest.raises(PublicSuccessorTemporalError):
        build_temporal_successor(content, RELEASE, canonical(report),
                                 source_packet_raw=canonical(packet),
                                 approval_raw=APPROVAL.read_bytes(),
                                 issued_at_utc=ISSUED)


def test_c_refuses_revoked_source_even_during_a2_seven_day_window(content, report):
    initial = canonical(report)
    authority = build_temporal_successor(content, RELEASE, initial, issued_at_utc=ISSUED, **PROOFS)
    revoked = later_pulse(report, timedelta(minutes=10))
    revoked["rows"][0]["status"] = "BLOCKED"
    revoked["rows"][0]["reason_codes"] = ["SOURCE_REVOKED"]
    seal_row(revoked["rows"][0])
    with pytest.raises(PublicSuccessorTemporalError):
        verify_temporal_successor(content, RELEASE, canonical(authority), initial,
                                  canonical(revoked), now_utc=ISSUED + timedelta(minutes=10),
                                  min_remaining=timedelta(hours=24), **PROOFS)


def test_c_can_accept_independent_later_pulse_without_changing_a2_sha(content, report):
    initial = canonical(report)
    authority = build_temporal_successor(content, RELEASE, initial, issued_at_utc=ISSUED, **PROOFS)
    sealed = canonical(authority)
    shift = timedelta(days=2)
    pulse = later_pulse(report, shift)
    assert verify_temporal_successor(
        content, RELEASE, sealed, initial, canonical(pulse),
        now_utc=ISSUED + shift, min_remaining=timedelta(hours=24), **PROOFS,
    ) == ISSUED + timedelta(days=7)
    assert hashlib.sha256(sealed).hexdigest() == hashlib.sha256(canonical(authority)).hexdigest()


def test_c_refuses_expired_authority_and_short_residual(content, report):
    raw = canonical(report)
    authority = build_temporal_successor(content, RELEASE, raw, issued_at_utc=ISSUED, **PROOFS)
    for now in (ISSUED + timedelta(days=6, minutes=1), ISSUED + timedelta(days=7)):
        with pytest.raises(PublicSuccessorTemporalError):
            verify_temporal_successor(content, RELEASE, canonical(authority), raw, raw,
                                      now_utc=now, min_remaining=timedelta(hours=24), **PROOFS)


def test_c_refuses_tampered_authority_or_old_pulse(content, report):
    raw = canonical(report)
    authority = build_temporal_successor(content, RELEASE, raw, issued_at_utc=ISSUED, **PROOFS)
    altered = copy.deepcopy(authority)
    altered["private_cas_manifest_sha256"] = "0" * 64
    pulse = canonical(later_pulse(report, timedelta(minutes=10)))
    with pytest.raises(PublicSuccessorTemporalError):
        verify_temporal_successor(content, RELEASE, canonical(altered), raw, pulse,
                                  now_utc=ISSUED + timedelta(minutes=10),
                                  min_remaining=timedelta(hours=24), **PROOFS)
    with pytest.raises(PublicSuccessorTemporalError):
        verify_temporal_successor(content, RELEASE, canonical(authority), raw, raw,
                                  now_utc=ISSUED + timedelta(minutes=10),
                                  min_remaining=timedelta(hours=24), **PROOFS)
