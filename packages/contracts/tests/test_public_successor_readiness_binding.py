"""La signature production doit lier A et C sans changer les octets V2 historiques."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from nexus_contracts.production_readiness import ProductionReadinessManifestV2
from pydantic import ValidationError

FIXTURE = Path(__file__).parent / "fixtures/legacy_v2/production_readiness_manifest_v2.json"


def _fields() -> dict[str, object]:
    return json.loads(FIXTURE.read_bytes())


def _successor_fields() -> dict[str, object]:
    fields = _fields()
    fields["public_successor_content_manifest_digest"] = fields["sealed_manifest_digest"]
    fields["public_successor_content_anchor_digest"] = "a" * 64
    fields["public_successor_authority_envelope_digest"] = "b" * 64
    fields["public_successor_target_pin_digest"] = "c" * 64
    fields["public_successor_c_expires_at_utc"] = (
        datetime.fromisoformat(str(fields["issued_at"]))
        + timedelta(days=1)
    )
    fields["public_successor_c_verified_at_utc"] = (
        datetime.fromisoformat(str(fields["issued_at"]))
        + timedelta(minutes=1)
    )
    fields["public_successor_lot42_review_binding"] = (
        "1" * 40, "2" * 40, "3" * 40, 42,
        "NEXUS-TRUSTED-REVIEW-V1:" + "4" * 64, "abenrhouma",
    )
    return fields


def test_legacy_v2_canonical_bytes_remain_unchanged() -> None:
    legacy = ProductionReadinessManifestV2.model_validate(_fields())
    assert legacy.canonical_bytes() == FIXTURE.read_bytes()


def test_successor_requires_complete_a_and_c_binding() -> None:
    fields = _successor_fields()
    successor = ProductionReadinessManifestV2.model_validate(fields)
    document = successor.canonical_document()
    assert document["public_successor_content_manifest_digest"] == "6" * 64
    assert document["public_successor_content_anchor_digest"] == "a" * 64
    assert document["public_successor_authority_envelope_digest"] == "b" * 64
    assert document["public_successor_target_pin_digest"] == "c" * 64
    assert document["public_successor_c_expires_at_utc"]
    assert document["public_successor_c_verified_at_utc"]
    assert document["public_successor_lot42_review_binding"][3] == 42
    for removed in (
        "public_successor_content_manifest_digest",
        "public_successor_content_anchor_digest",
        "public_successor_authority_envelope_digest",
        "public_successor_target_pin_digest",
        "public_successor_c_expires_at_utc",
        "public_successor_c_verified_at_utc",
        "public_successor_lot42_review_binding",
    ):
        incomplete = dict(fields)
        del incomplete[removed]
        with pytest.raises(ValidationError, match="public successor"):
            ProductionReadinessManifestV2.model_validate(incomplete)
    mismatched = dict(fields)
    mismatched["public_successor_content_manifest_digest"] = "c" * 64
    with pytest.raises(ValidationError, match="sealed_manifest_digest"):
        ProductionReadinessManifestV2.model_validate(mismatched)


def test_target_pin_digest_alone_does_not_activate_successor() -> None:
    fields = _fields()
    fields["public_successor_target_pin_digest"] = "c" * 64
    with pytest.raises(ValidationError, match="public successor"):
        ProductionReadinessManifestV2.model_validate(fields)


def test_successor_rejects_expired_or_mutated_c_expiry_and_review_binding() -> None:
    fields = _successor_fields()
    issued = datetime.fromisoformat(str(fields["issued_at"]))
    for bad_expiry in (issued, issued - timedelta(seconds=1), "not-a-date"):
        changed = dict(fields, public_successor_c_expires_at_utc=bad_expiry)
        with pytest.raises(ValidationError):
            ProductionReadinessManifestV2.model_validate(changed)
    for bad_verified_at in (
        issued - timedelta(seconds=1),
        issued + timedelta(hours=2),
        fields["public_successor_c_expires_at_utc"],
    ):
        changed = dict(fields, public_successor_c_verified_at_utc=bad_verified_at)
        with pytest.raises(ValidationError):
            ProductionReadinessManifestV2.model_validate(changed)
    for bad_binding in (
        ("0" * 40, "2" * 40, "3" * 40, 0,
         "NEXUS-TRUSTED-REVIEW-V1:" + "4" * 64, "abenrhouma"),
        ("1" * 40, "2" * 40, "3" * 40, 42, "bad", "abenrhouma"),
        ("1" * 40, "2" * 40, "3" * 40, 42,
         "NEXUS-TRUSTED-REVIEW-V1:" + "4" * 64, "not-abenrhouma"),
    ):
        changed = dict(fields, public_successor_lot42_review_binding=bad_binding)
        with pytest.raises(ValidationError):
            ProductionReadinessManifestV2.model_validate(changed)
