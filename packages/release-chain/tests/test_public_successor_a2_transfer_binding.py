"""Le lien A2/pin/plan est explicite et ne publie rien."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from nexus_release_chain.public_successor_a2_transfer_binding import (
    A2TransferBindingError,
    build_a2_transfer_binding,
    canonical_bytes,
    verify_a2_transfer_binding,
)

ROOT = Path(__file__).resolve().parents[3]
A2 = (ROOT / "docs/reports/go_live/student_public_successor_temporal_continuity_a2_20261011_v2.json").read_bytes()
PIN = (ROOT / "governance/staging_target_pins/student-public-successor-release40b-20261011.json").read_bytes()
PLAN = (ROOT / "docs/reports/go_live/student_public_successor_v2_transfer_plan_release40b_20261011.json").read_bytes()
NOW = datetime(2026, 10, 12, 0, tzinfo=UTC)


def test_binding_seals_a2_pin_and_identical_release40b_plan() -> None:
    raw = canonical_bytes(build_a2_transfer_binding(A2, PIN, PLAN))
    result = verify_a2_transfer_binding(raw, A2, PIN, PLAN, now_utc=NOW)
    assert result["status"] == "REVIEW_CANDIDATE_NOT_AUTHORIZED"
    assert result["counts"] == {"collections": 11, "derivatives": 253, "placements": 377}


@pytest.mark.parametrize("which", ["a2", "pin", "plan", "binding_a2", "binding_pin", "binding_plan"])
def test_binding_refuses_any_digest_substitution(which: str) -> None:
    raw = canonical_bytes(build_a2_transfer_binding(A2, PIN, PLAN))
    values = {"a2": A2, "pin": PIN, "plan": PLAN}
    if which.startswith("binding_"):
        altered = json.loads(raw)
        altered[f"{which.removeprefix('binding_')}_sha256"] = "0" * 64
        raw = canonical_bytes(altered)
    else:
        values[which] += b"\n"
    with pytest.raises(A2TransferBindingError):
        verify_a2_transfer_binding(raw, values["a2"], values["pin"], values["plan"], now_utc=NOW)


def test_binding_refuses_expired_pin() -> None:
    raw = canonical_bytes(build_a2_transfer_binding(A2, PIN, PLAN))
    with pytest.raises(A2TransferBindingError):
        verify_a2_transfer_binding(raw, A2, PIN, PLAN, now_utc=datetime(2026, 10, 13, tzinfo=UTC))


def test_versioned_candidate_binding_matches_exact_files() -> None:
    pin = (ROOT / "governance/staging_target_pins/student-public-successor-release40b-a2-20261012.json").read_bytes()
    plan = (ROOT / "docs/reports/go_live/student_public_successor_v2_transfer_plan_release40b_a2_20261012.json").read_bytes()
    binding = (ROOT / "governance/student_public_rights/public_successor_a2_transfer_binding_20261012.json").read_bytes()
    assert binding == canonical_bytes(build_a2_transfer_binding(A2, pin, plan))
    verify_a2_transfer_binding(binding, A2, pin, plan, now_utc=NOW)
    assert plan == PLAN


def test_renewed_target_pin_and_binding_keep_a2_content_and_plan() -> None:
    pin_raw = (ROOT / "governance/staging_target_pins/student-public-successor-release40b-a2-20261013.json").read_bytes()
    binding_raw = (ROOT / "governance/student_public_rights/public_successor_a2_transfer_binding_20261013.json").read_bytes()
    pin = json.loads(pin_raw)
    binding = json.loads(binding_raw)
    assert pin["content_anchor_sha256"] == "1731e2a5690c4043dd21d02576d843f90dc90c7a2f7ec2cc736f7dd3563df7e0"
    assert pin["release_id"] == "student-public-successor-20261010-40b956c6f5ec0c60"
    assert pin["postgres_system_identifier"] == "7696000243730169894"
    assert pin["database_name"] == "ragdb_student_public_qual_20261013"
    assert pin["destination_realpath"] == "/srv/nexus-public-qual-20261013/servable-text"
    assert pin["target_identity"] != json.loads(
        (ROOT / "governance/staging_target_pins/student-public-successor-release40b-a2-20261012.json").read_bytes()
    )["target_identity"]
    assert binding_raw == canonical_bytes(build_a2_transfer_binding(A2, pin_raw, PLAN))
    assert binding["status"] == "REVIEW_CANDIDATE_NOT_AUTHORIZED"
    captured = datetime.fromisoformat(pin["pinned_at_utc"])
    verify_a2_transfer_binding(binding_raw, A2, pin_raw, PLAN, now_utc=captured)
