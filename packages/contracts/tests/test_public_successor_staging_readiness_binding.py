"""Readiness staging signée : A et l'autorité de phase sont indivisibles."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from nexus_contracts.staging_readiness import (
    StagingReadinessManifestV1,
    parse_staging_readiness_trust_anchor,
    sign_staging_readiness_manifest,
    staging_public_key_hex,
    verify_staging_readiness_manifest,
)
from pydantic import ValidationError

SEED = "12" * 32  # graine déterministe de test, jamais une clé opérateur
KEY_ID = "rehearsal-readiness-public-test"
NOW = datetime(2026, 10, 10, 20, 0, tzinfo=UTC)


def _fields() -> dict[str, object]:
    return {
        "protocol_version": "NEXUS-STAGING-READINESS-V1",
        "environment": "rehearsal",
        "repository": "cyranoaladin/RAG",
        "merge_sha": "a" * 40,
        "worker_image": "ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:" + "1" * 64,
        "allowed_release_id": "student-public-successor-20261010-fcc84331e7700042",
        "allowed_release_manifest_sha256": "b" * 64,
        "control_dsn_differs_from_product": True,
        "key_id": KEY_ID,
        "issued_at": NOW - timedelta(minutes=1),
        "expires_at": NOW + timedelta(hours=1),
    }


def _anchor() -> object:
    return parse_staging_readiness_trust_anchor(json.dumps({
        "protocol_version": "NEXUS-STAGING-READINESS-V1",
        "keys": [{
            "key_id": KEY_ID,
            "algorithm": "ed25519",
            "public_key": staging_public_key_hex(SEED),
            "environment": "rehearsal",
        }],
    }).encode())


def test_legacy_staging_manifest_has_no_new_fields() -> None:
    model = StagingReadinessManifestV1.model_validate(_fields())
    assert "public_successor_phase" not in model.canonical_document()


def test_signed_staging_phase_binds_a_and_b_or_c() -> None:
    fields = _fields()
    fields.update({
        "public_successor_phase": "INGESTION",
        "public_successor_content_anchor_digest": "c" * 64,
        "public_successor_phase_authority_digest": "d" * 64,
    })
    model = StagingReadinessManifestV1.model_validate(fields)
    signed = sign_staging_readiness_manifest(model, private_key_hex=SEED, key_id=KEY_ID)
    verified = verify_staging_readiness_manifest(
        signed.canonical_bytes(), trust_anchor=_anchor(), now=NOW,
    )
    assert verified.public_successor_phase == "INGESTION"
    assert verified.public_successor_content_anchor_digest == "c" * 64
    assert verified.public_successor_phase_authority_digest == "d" * 64
    for missing in (
        "public_successor_phase", "public_successor_content_anchor_digest",
        "public_successor_phase_authority_digest",
    ):
        incomplete = dict(fields)
        del incomplete[missing]
        with pytest.raises(ValidationError, match="public successor"):
            StagingReadinessManifestV1.model_validate(incomplete)
