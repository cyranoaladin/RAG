"""Contrat `NEXUS-PRODUCTION-READINESS-V1` — ce qu'il refuse.

Un manifeste de readiness n'est utile que par ce qu'il rend
irreprésentable. Chaque test ci-dessous nomme une manière précise de
mentir sur une promotion, et prouve qu'elle est refusée.

Les graines de test sont des valeurs triviales et déterministes
(``"11" * 32``) : rien ici ne ressemble à un secret utilisable, et aucune
ancre réelle n'est écrite dans le dépôt.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from nexus_contracts.production_readiness import (
    PRODUCTION_READINESS_PROTOCOL_VERSION,
    ProductionReadinessError,
    ProductionReadinessManifestV1,
    ProductionReadinessTrustAnchor,
    parse_production_readiness_trust_anchor,
    parse_signed_production_readiness_manifest,
    public_readiness_key_hex,
    require_manifest_matches_release,
    sign_production_readiness_manifest,
    verify_production_readiness_manifest,
)
from pydantic import ValidationError

READINESS_SEED = "11" * 32
#: Graine *différente*, jouant le rôle de la clé de liaison de revue.
REVIEW_BINDING_SEED = "22" * 32
KEY_ID = "nexus-readiness-test-1"
MERGE_SHA = "a" * 40
TREE_SHA = "b" * 40
PR_HEAD_SHA = "c" * 40
ISSUED_AT = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def _manifest_fields(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "protocol_version": PRODUCTION_READINESS_PROTOCOL_VERSION,
        "repository": "cyranoaladin/RAG",
        "pr_number": 95,
        "pr_head_sha": PR_HEAD_SHA,
        "pr_head_tree_sha": TREE_SHA,
        "merge_sha": MERGE_SHA,
        "merge_tree_sha": TREE_SHA,
        "release_tag": f"release/rag/20260811-{MERGE_SHA[:12]}",
        "environment": "production",
        "review_binding_digest": "11" * 32,
        "authorization_digest": "22" * 32,
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
        "run_id": 4242,
        "run_attempt": 1,
        "issued_at": ISSUED_AT,
        "key_id": KEY_ID,
    }
    fields.update(overrides)
    return fields


def _manifest(**overrides: object) -> ProductionReadinessManifestV1:
    return ProductionReadinessManifestV1(**_manifest_fields(**overrides))  # type: ignore[arg-type]


def _anchor(
    *, seed: str = READINESS_SEED, key_id: str = KEY_ID, environment: str = "production"
) -> ProductionReadinessTrustAnchor:
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


def _signed_bytes(**overrides: object) -> bytes:
    return sign_production_readiness_manifest(
        _manifest(**overrides), private_key_hex=READINESS_SEED, key_id=KEY_ID
    ).canonical_bytes()


class TestCanonicalisation:
    def test_the_bytes_round_trip(self) -> None:
        raw = _signed_bytes()
        assert parse_signed_production_readiness_manifest(raw).canonical_bytes() == raw

    def test_the_bytes_are_stable_across_constructions(self) -> None:
        assert _manifest().canonical_bytes() == _manifest().canonical_bytes()

    def test_the_digest_is_stable(self) -> None:
        assert _manifest().digest() == _manifest().digest()

    def test_map_ordering_does_not_change_the_bytes(self) -> None:
        """Deux workflows peuvent émettre les mêmes digests dans un ordre
        différent : cela ne doit pas produire deux manifestes distincts."""
        forward = _manifest(
            application_image_digests={
                "a-service": "ghcr.io/o/a@sha256:" + "1" * 64,
                "b-service": "ghcr.io/o/b@sha256:" + "2" * 64,
            }
        )
        reverse = _manifest(
            application_image_digests={
                "b-service": "ghcr.io/o/b@sha256:" + "2" * 64,
                "a-service": "ghcr.io/o/a@sha256:" + "1" * 64,
            }
        )
        assert forward.canonical_bytes() == reverse.canonical_bytes()

    def test_non_canonical_bytes_are_refused(self) -> None:
        document = json.loads(_signed_bytes().decode("utf-8"))
        compact = json.dumps(document, sort_keys=True).encode("utf-8")
        with pytest.raises(ProductionReadinessError, match="not in canonical form"):
            parse_signed_production_readiness_manifest(compact)


class TestSignature:
    def test_a_valid_signature_verifies(self) -> None:
        manifest = verify_production_readiness_manifest(
            _signed_bytes(), trust_anchor=_anchor()
        )
        assert manifest.merge_sha == MERGE_SHA

    def test_a_tampered_payload_is_refused(self) -> None:
        document = json.loads(_signed_bytes().decode("utf-8"))
        document["manifest"]["run_id"] = 9999
        raw = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")
        with pytest.raises(ProductionReadinessError):
            verify_production_readiness_manifest(raw, trust_anchor=_anchor())

    def test_a_tampered_signature_is_refused(self) -> None:
        document = json.loads(_signed_bytes().decode("utf-8"))
        document["signature"] = "0" * 128
        raw = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")
        with pytest.raises(ProductionReadinessError, match="signature is invalid"):
            verify_production_readiness_manifest(raw, trust_anchor=_anchor())

    def test_an_unknown_key_id_is_refused(self) -> None:
        with pytest.raises(ProductionReadinessError, match="not declared"):
            verify_production_readiness_manifest(
                _signed_bytes(), trust_anchor=_anchor(key_id="another-key")
            )

    def test_a_test_environment_key_never_validates_production(self) -> None:
        with pytest.raises(ProductionReadinessError, match="can never be accepted"):
            verify_production_readiness_manifest(
                _signed_bytes(), trust_anchor=_anchor(environment="test")
            )


class TestKeySeparation:
    """La clé de liaison de revue n'autorise jamais un déploiement."""

    def test_a_review_binding_signature_is_not_accepted_by_a_readiness_anchor(
        self,
    ) -> None:
        raw = sign_production_readiness_manifest(
            _manifest(), private_key_hex=REVIEW_BINDING_SEED, key_id=KEY_ID
        ).canonical_bytes()
        # L'ancre readiness ne déclare que la clé publique readiness.
        with pytest.raises(ProductionReadinessError, match="signature is invalid"):
            verify_production_readiness_manifest(raw, trust_anchor=_anchor())

    def test_a_review_binding_anchor_object_is_refused_outright(self) -> None:
        """Une ancre d'un autre usage n'est pas seulement « sans la bonne
        clé » : elle n'est pas du bon type d'autorité."""
        from nexus_contracts.review_binding import parse_trust_anchor, public_key_hex

        review_anchor = parse_trust_anchor(
            json.dumps(
                {
                    "protocol_version": "NEXUS-REVIEW-BINDING-V1",
                    "keys": [
                        {
                            "key_id": KEY_ID,
                            "algorithm": "ed25519",
                            "public_key": public_key_hex(READINESS_SEED),
                            "environment": "production",
                        }
                    ],
                }
            ).encode("utf-8")
        )
        with pytest.raises(TypeError, match="different authority"):
            verify_production_readiness_manifest(
                _signed_bytes(), trust_anchor=review_anchor
            )

    def test_a_readiness_anchor_refuses_the_review_binding_protocol(self) -> None:
        with pytest.raises(ProductionReadinessError, match="failed strict validation"):
            parse_production_readiness_trust_anchor(
                json.dumps(
                    {
                        "protocol_version": "NEXUS-REVIEW-BINDING-V1",
                        "keys": [
                            {
                                "key_id": KEY_ID,
                                "algorithm": "ed25519",
                                "public_key": public_readiness_key_hex(READINESS_SEED),
                                "environment": "production",
                            }
                        ],
                    }
                ).encode("utf-8")
            )

    def test_signing_with_a_key_id_the_manifest_does_not_name_is_refused(self) -> None:
        with pytest.raises(ProductionReadinessError, match="never names a signer"):
            sign_production_readiness_manifest(
                _manifest(), private_key_hex=READINESS_SEED, key_id="other-key"
            )


class TestFieldDiscipline:
    def test_a_missing_field_is_refused(self) -> None:
        fields = _manifest_fields()
        del fields["merge_tree_sha"]
        with pytest.raises(ValidationError):
            ProductionReadinessManifestV1(**fields)  # type: ignore[arg-type]

    def test_an_extra_field_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            ProductionReadinessManifestV1(
                **_manifest_fields(approved_by_operator=True)  # type: ignore[arg-type]
            )

    def test_an_unknown_protocol_version_is_refused(self) -> None:
        document = json.loads(_signed_bytes().decode("utf-8"))
        document["manifest"]["protocol_version"] = "NEXUS-PRODUCTION-READINESS-V2"
        raw = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")
        with pytest.raises(ProductionReadinessError, match="protocol_version is not"):
            parse_signed_production_readiness_manifest(raw)

    @pytest.mark.parametrize(
        "field",
        ["pr_head_sha", "merge_sha", "pr_head_tree_sha", "merge_tree_sha"],
    )
    def test_a_malformed_git_sha_is_refused(self, field: str) -> None:
        with pytest.raises(ValidationError):
            _manifest(**{field: "abc"})

    def test_a_non_production_environment_is_irrepresentable(self) -> None:
        """Le contrat n'est pas affaibli pour accueillir un rehearsal : un
        mode répétition utilise ses propres fixtures et sa propre ancre."""
        with pytest.raises(ValidationError):
            _manifest(environment="rehearsal")

    def test_a_non_passing_gate_is_irrepresentable(self) -> None:
        with pytest.raises(ValidationError):
            _manifest(gate_result="fail")

    def test_an_invalid_timestamp_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _manifest(issued_at=datetime(2026, 8, 11, 12, 0))  # naive

    @pytest.mark.parametrize("field", ["run_id", "run_attempt", "pr_number"])
    def test_a_non_positive_counter_is_refused(self, field: str) -> None:
        with pytest.raises(ValidationError):
            _manifest(**{field: 0})


class TestDeploymentUnitIsImmutable:
    def test_a_mutable_tag_is_refused_as_an_image_reference(self) -> None:
        with pytest.raises(ValidationError, match="never a deployment unit"):
            _manifest(
                application_image_digests={"ingestor": "ghcr.io/o/rag-ingestor:v1.2.3"}
            )

    def test_a_malformed_digest_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _manifest(application_image_digests={"ingestor": "ghcr.io/o/x@sha256:zz"})

    def test_an_empty_image_map_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _manifest(application_image_digests={})

    def test_an_upstream_image_must_be_pinned_too(self) -> None:
        with pytest.raises(ValidationError, match="never a deployment unit"):
            _manifest(upstream_image_digests={"pgvector": "pgvector/pgvector:pg16"})

    def test_a_malformed_service_name_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _manifest(
                application_image_digests={"Bad Name": "ghcr.io/o/x@sha256:" + "1" * 64}
            )


class TestTreeAndTagBindings:
    def test_a_diverging_tree_is_refused(self) -> None:
        """Le cœur du contrat : le code déployé est celui qui a été relu."""
        with pytest.raises(ValidationError, match="does not carry the exact tree"):
            _manifest(merge_tree_sha="d" * 40)

    def test_a_tag_that_does_not_name_the_merge_commit_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="does not match the first"):
            _manifest(release_tag="release/rag/20260811-" + "f" * 12)

    @pytest.mark.parametrize(
        "tag",
        [
            "release/rag/2026811-" + MERGE_SHA[:12],
            "release/" + MERGE_SHA[:12],
            "main",
            f"release/rag/20260811-{MERGE_SHA[:11]}",
        ],
    )
    def test_a_non_canonical_tag_is_refused(self, tag: str) -> None:
        with pytest.raises(ValidationError):
            _manifest(release_tag=tag)


class TestReleaseBinding:
    def test_the_manifest_must_attest_the_release_being_deployed(self) -> None:
        manifest = _manifest()
        require_manifest_matches_release(manifest, release_sha=MERGE_SHA)

    def test_another_release_sha_is_refused(self) -> None:
        with pytest.raises(ProductionReadinessError, match="but the release being"):
            require_manifest_matches_release(_manifest(), release_sha="e" * 40)

    def test_a_branch_name_can_never_identify_a_release(self) -> None:
        with pytest.raises(ProductionReadinessError, match="mutable"):
            require_manifest_matches_release(_manifest(), release_sha="main")

    def test_a_diverging_compose_digest_is_refused(self) -> None:
        with pytest.raises(ProductionReadinessError, match="resolved compose"):
            require_manifest_matches_release(
                _manifest(), release_sha=MERGE_SHA, compose_digest="99" * 32
            )
