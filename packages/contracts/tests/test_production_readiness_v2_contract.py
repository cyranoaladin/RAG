"""Contrat `NEXUS-PRODUCTION-READINESS-V2` (ADR-0044) — un seul digest
agrégé (`authorization_set_digest`) remplace les deux champs parallèles
`authorization_digest`/`review_binding_digest` de V1.

Mêmes graines triviales et déterministes que le test V1
(`test_production_readiness_contract.py`) — rien ici ne ressemble à un
secret utilisable.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from nexus_contracts.production_readiness import (
    PRODUCTION_READINESS_PROTOCOL_VERSION,
    PRODUCTION_READINESS_V2_PROTOCOL_VERSION,
    ProductionReadinessError,
    ProductionReadinessManifestV1,
    ProductionReadinessManifestV2,
    ProductionReadinessTrustAnchor,
    parse_production_readiness_trust_anchor,
    parse_signed_production_readiness_manifest_v2,
    public_readiness_key_hex,
    sign_production_readiness_manifest_v2,
    verify_production_readiness_manifest_v2,
)
from pydantic import ValidationError

READINESS_SEED = "11" * 32
KEY_ID = "nexus-readiness-test-1"
MERGE_SHA = "a" * 40
TREE_SHA = "b" * 40
PR_HEAD_SHA = "c" * 40
ISSUED_AT = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _manifest_fields(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "protocol_version": PRODUCTION_READINESS_V2_PROTOCOL_VERSION,
        "repository": "cyranoaladin/RAG",
        "pr_number": 128,
        "pr_head_sha": PR_HEAD_SHA,
        "pr_head_tree_sha": TREE_SHA,
        "merge_sha": MERGE_SHA,
        "merge_tree_sha": TREE_SHA,
        "release_tag": f"release/rag/20260822-{MERGE_SHA[:12]}",
        "environment": "production",
        "authorization_set_digest": "99" * 32,
        "trust_anchor_digest": "33" * 32,
        "revocation_registry_digest": "44" * 32,
        "catalog_digest": "55" * 32,
        "sealed_manifest_digest": "66" * 32,
        "h2b_report_digest": "77" * 32,
        "gate_result": "pass",
        "application_image_digests": {
            "ingestion-worker": "ghcr.io/cyranoaladin/rag-ingestion-worker@sha256:" + "1" * 64,
            "ingestor": "ghcr.io/cyranoaladin/rag-ingestor-v2@sha256:" + "2" * 64,
        },
        "upstream_image_digests": {
            "pgvector": "pgvector/pgvector@sha256:" + "3" * 64,
        },
        "compose_digest": "88" * 32,
        "workflow_path": ".github/workflows/promote-rag-production.yml",
        "workflow_ref": "refs/heads/main",
        "run_id": 4343,
        "run_attempt": 1,
        "issued_at": ISSUED_AT,
        "key_id": KEY_ID,
    }
    fields.update(overrides)
    return fields


def _manifest(**overrides: object) -> ProductionReadinessManifestV2:
    return ProductionReadinessManifestV2(**_manifest_fields(**overrides))  # type: ignore[arg-type]


def _anchor(
    *, seed: str = READINESS_SEED, key_id: str = KEY_ID, environment: str = "production"
) -> ProductionReadinessTrustAnchor:
    #: Ancre **partagée** entre V1 et V2 — son `protocol_version` lui est
    #: propre et ne varie jamais avec la version du manifeste qu'elle
    #: authentifie (`ProductionReadinessTrustAnchor` porte un seul
    #: littéral `NEXUS-PRODUCTION-READINESS-V1`, réutilisé tel quel ici).
    return parse_production_readiness_trust_anchor(
        json.dumps(
            {
                "protocol_version": PRODUCTION_READINESS_PROTOCOL_VERSION,
                "keys": [
                    {
                        "key_id": key_id,
                        "algorithm": "ed25519",
                        "public_key": public_readiness_key_hex(seed),
                        "environment": environment,
                    }
                ],
            }
        ).encode("utf-8")
    )


class TestSingleAggregateDigestReplacesTwoFields:
    def test_v2_has_no_authorization_digest_field(self) -> None:
        with pytest.raises(ValidationError):
            _manifest(authorization_digest="22" * 32)

    def test_v2_has_no_review_binding_digest_field(self) -> None:
        with pytest.raises(ValidationError):
            _manifest(review_binding_digest="11" * 32)

    def test_v2_constructs_with_a_single_authorization_set_digest(self) -> None:
        manifest = _manifest()
        assert manifest.authorization_set_digest == "99" * 32


class TestBindingsHold:
    def test_tree_sha_mismatch_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="does not carry the exact tree"):
            _manifest(merge_tree_sha="d" * 40)

    def test_release_tag_suffix_mismatch_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="does not match the first"):
            _manifest(release_tag=f"release/rag/20260822-{'f' * 12}")

    def test_coherent_bindings_are_accepted(self) -> None:
        manifest = _manifest()
        assert manifest.pr_head_tree_sha == manifest.merge_tree_sha


class TestCanonicalizationAndDigest:
    def test_canonical_bytes_are_deterministic(self) -> None:
        a = _manifest().canonical_bytes()
        b = _manifest().canonical_bytes()
        assert a == b

    def test_changing_authorization_set_digest_changes_the_manifest_digest(self) -> None:
        a = _manifest().digest()
        b = _manifest(authorization_set_digest="aa" * 32).digest()
        assert a != b


class TestSignVerifyRoundTrip:
    def test_sign_then_verify_recovers_the_manifest(self) -> None:
        manifest = _manifest()
        signed = sign_production_readiness_manifest_v2(
            manifest, private_key_hex=READINESS_SEED, key_id=KEY_ID
        )
        raw = signed.canonical_bytes()
        verified = verify_production_readiness_manifest_v2(raw, trust_anchor=_anchor())
        assert verified == manifest

    def test_wrong_signing_key_id_is_refused_before_signing(self) -> None:
        manifest = _manifest(key_id="other-key")
        with pytest.raises(ProductionReadinessError, match="names a signer other than"):
            sign_production_readiness_manifest_v2(
                manifest, private_key_hex=READINESS_SEED, key_id=KEY_ID
            )

    def test_tampered_bytes_fail_signature_verification(self) -> None:
        manifest = _manifest()
        signed = sign_production_readiness_manifest_v2(
            manifest, private_key_hex=READINESS_SEED, key_id=KEY_ID
        )
        tampered = json.loads(signed.canonical_bytes())
        tampered["manifest"]["authorization_set_digest"] = "bb" * 32
        tampered_raw = (
            json.dumps(tampered, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        with pytest.raises(ProductionReadinessError):
            verify_production_readiness_manifest_v2(tampered_raw, trust_anchor=_anchor())

    def test_non_passing_gate_result_is_refused_at_construction(self) -> None:
        with pytest.raises(ValidationError):
            _manifest(gate_result="fail")

    def test_wrong_environment_is_refused_at_verification(self) -> None:
        manifest = _manifest()
        signed = sign_production_readiness_manifest_v2(
            manifest, private_key_hex=READINESS_SEED, key_id=KEY_ID
        )
        with pytest.raises(ProductionReadinessError, match="can never be accepted in"):
            verify_production_readiness_manifest_v2(
                signed.canonical_bytes(), trust_anchor=_anchor(), environment="staging"
            )


class TestV1AndV2AreNeverInterchangeable:
    def test_v2_manifest_is_not_a_v1_manifest(self) -> None:
        assert not isinstance(_manifest(), ProductionReadinessManifestV1)

    def test_parsing_a_v1_shaped_document_as_v2_is_refused(self) -> None:
        v1_fields = _manifest_fields()
        v1_fields["protocol_version"] = "NEXUS-PRODUCTION-READINESS-V1"
        v1_fields["issued_at"] = ISSUED_AT.isoformat()
        del v1_fields["authorization_set_digest"]
        v1_fields["authorization_digest"] = "22" * 32
        v1_fields["review_binding_digest"] = "11" * 32
        signed_document = {
            "manifest": v1_fields,
            "manifest_digest": "0" * 64,
            "signature_algorithm": "ed25519",
            "key_id": KEY_ID,
            "signature": "0" * 128,
        }
        raw = (
            json.dumps(signed_document, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        with pytest.raises(ProductionReadinessError, match="protocol_version"):
            parse_signed_production_readiness_manifest_v2(raw)
