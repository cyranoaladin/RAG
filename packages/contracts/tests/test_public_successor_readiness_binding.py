"""La signature production doit lier A et C sans changer les octets V2 historiques."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from nexus_contracts.production_readiness import ProductionReadinessManifestV2
from pydantic import ValidationError

FIXTURE = Path(__file__).parent / "fixtures/legacy_v2/production_readiness_manifest_v2.json"


def _fields() -> dict[str, object]:
    return json.loads(FIXTURE.read_bytes())


def test_legacy_v2_canonical_bytes_remain_unchanged() -> None:
    legacy = ProductionReadinessManifestV2.model_validate(_fields())
    assert legacy.canonical_bytes() == FIXTURE.read_bytes()


def test_successor_requires_complete_a_and_c_binding() -> None:
    fields = _fields()
    fields["public_successor_content_manifest_digest"] = fields["sealed_manifest_digest"]
    fields["public_successor_content_anchor_digest"] = "a" * 64
    fields["public_successor_authority_envelope_digest"] = "b" * 64
    successor = ProductionReadinessManifestV2.model_validate(fields)
    document = successor.canonical_document()
    assert document["public_successor_content_manifest_digest"] == "6" * 64
    assert document["public_successor_content_anchor_digest"] == "a" * 64
    assert document["public_successor_authority_envelope_digest"] == "b" * 64
    for removed in (
        "public_successor_content_manifest_digest",
        "public_successor_content_anchor_digest",
        "public_successor_authority_envelope_digest",
    ):
        incomplete = dict(fields)
        del incomplete[removed]
        with pytest.raises(ValidationError, match="public successor"):
            ProductionReadinessManifestV2.model_validate(incomplete)
    mismatched = dict(fields)
    mismatched["public_successor_content_manifest_digest"] = "c" * 64
    with pytest.raises(ValidationError, match="sealed_manifest_digest"):
        ProductionReadinessManifestV2.model_validate(mismatched)
