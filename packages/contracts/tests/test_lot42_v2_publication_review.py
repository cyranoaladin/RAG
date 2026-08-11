"""LOT42-V2 — la revue de publication lie l'attribution publiée (ADR-0035).

Le défaut fermé ici (constat F3) : un artefact LOT42-V1 ne nommait nulle
part les quatre faits d'attribution qui seraient effectivement publiés.
L'humain approuvait donc une publication sans jamais relire sa provenance.
V2 place le digest d'attribution dans les octets canoniques eux-mêmes.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from nexus_contracts.authority_artifacts import (
    LOT42_PROTOCOL_VERSION,
    LOT42_V2_PROTOCOL_VERSION,
    CanonicalArtifactError,
    PublicationReviewArtifactV1,
    PublicationReviewArtifactV2,
    parse_publication_review_artifact,
    require_publication_review_v2,
)
from pydantic import ValidationError

ATTRIBUTION_DIGEST = "ab" * 32
OTHER_DIGEST = "cd" * 32
MOMENT = datetime(2026, 6, 1, tzinfo=UTC)


def _base_fields() -> dict[str, object]:
    return {
        "review_id": "lot42-v2-review",
        "decision": "AUTHORIZE_PUBLICATION",
        "resource_id": "11111111-1111-4111-8111-111111111111",
        "artifact_id": "22222222-2222-4222-8222-222222222222",
        "collection": "eduscol_terminale",
        "canonical_url": "https://eduscol.education.gouv.fr/doc",
        "content_sha256": "11" * 32,
        "scope_authorization_id": "h2f-authorization",
        "profile_id": "profile-a",
        "profile_version": "1",
        "profile_fingerprint": "22" * 32,
        "manifest_digest": "33" * 32,
        "rights_status": "officiel_public",
        "rights_assessed_at": MOMENT,
        "quality_passed": True,
        "quality_report_digest": "44" * 32,
        "quality_assessed_at": MOMENT,
        "gate_passed": True,
        "gate_name": "h2f-gate",
        "gate_evaluated_at": MOMENT,
        "evidence_event_ids": ("33333333-3333-4333-8333-333333333333",),
    }


def _v2(**overrides: object) -> PublicationReviewArtifactV2:
    fields = _base_fields()
    fields.update(
        protocol_version=LOT42_V2_PROTOCOL_VERSION,
        attributed_facts_digest=ATTRIBUTION_DIGEST,
    )
    fields.update(overrides)
    return PublicationReviewArtifactV2(**fields)  # type: ignore[arg-type]


def _v1(**overrides: object) -> PublicationReviewArtifactV1:
    fields = _base_fields()
    fields.update(protocol_version=LOT42_PROTOCOL_VERSION)
    fields.update(overrides)
    return PublicationReviewArtifactV1(**fields)  # type: ignore[arg-type]


class TestTheDigestIsMandatory:
    def test_a_v2_artifact_without_the_digest_is_irrepresentable(self) -> None:
        """Pas « invalide » : impossible à construire."""
        fields = _base_fields()
        fields["protocol_version"] = LOT42_V2_PROTOCOL_VERSION
        with pytest.raises(ValidationError, match="attributed_facts_digest"):
            PublicationReviewArtifactV2(**fields)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "malformed",
        ["", "not-hex", "AB" * 32, "ab" * 31, "ab" * 33],
        ids=["blank", "non-hex", "uppercase", "too-short", "too-long"],
    )
    def test_a_malformed_digest_is_refused(self, malformed: str) -> None:
        with pytest.raises(ValidationError):
            _v2(attributed_facts_digest=malformed)

    def test_a_valid_v2_artifact_is_accepted(self) -> None:
        artifact = _v2()
        assert artifact.protocol_version == LOT42_V2_PROTOCOL_VERSION
        assert artifact.attributed_facts_digest == ATTRIBUTION_DIGEST


class TestTheDigestIsInsideTheReviewedBytes:
    def test_the_digest_appears_in_the_canonical_document(self) -> None:
        document = json.loads(_v2().canonical_bytes().decode("utf-8"))
        assert document["attributed_facts_digest"] == ATTRIBUTION_DIGEST

    def test_changing_the_digest_changes_the_canonical_bytes(self) -> None:
        assert _v2().canonical_bytes() != _v2(
            attributed_facts_digest=OTHER_DIGEST
        ).canonical_bytes()

    def test_changing_the_digest_changes_the_artifact_digest(self) -> None:
        """Conséquence voulue : le digest de l'artefact est ce que
        l'attestation enregistre et ce que la review humaine désigne."""
        assert _v2().digest() != _v2(attributed_facts_digest=OTHER_DIGEST).digest()

    def test_changing_the_digest_changes_the_canonical_path(self) -> None:
        """Une attribution modifiée après la revue déplace le chemin
        canonique : les octets approuvés ne sont plus là où l'attestation
        les cherche."""
        assert _v2().canonical_path() != _v2(
            attributed_facts_digest=OTHER_DIGEST
        ).canonical_path()

    def test_a_v2_artifact_never_shares_a_digest_with_its_v1_shadow(self) -> None:
        assert _v2().digest() != _v1().digest()


class TestVersionsAreNeverInterchangeable:
    def test_v1_bytes_parse_as_v1(self) -> None:
        parsed = parse_publication_review_artifact(_v1().canonical_bytes())
        assert parsed.protocol_version == LOT42_PROTOCOL_VERSION
        assert not isinstance(parsed, PublicationReviewArtifactV2)

    def test_v2_bytes_parse_as_v2(self) -> None:
        parsed = parse_publication_review_artifact(_v2().canonical_bytes())
        assert isinstance(parsed, PublicationReviewArtifactV2)

    def test_an_unknown_protocol_version_is_refused(self) -> None:
        document = json.loads(_v2().canonical_bytes().decode("utf-8"))
        document["protocol_version"] = "LOT42-V3"
        raw = json.dumps(document, sort_keys=True, indent=2).encode() + b"\n"
        with pytest.raises(CanonicalArtifactError, match="unsupported publication"):
            parse_publication_review_artifact(raw)

    def test_a_v1_document_carrying_the_digest_is_refused(self) -> None:
        """Le champ ne peut pas voyager clandestinement sous l'étiquette
        V1 : ``extra="forbid"`` le refuse."""
        document = json.loads(_v1().canonical_bytes().decode("utf-8"))
        document["attributed_facts_digest"] = ATTRIBUTION_DIGEST
        raw = json.dumps(document, sort_keys=True, indent=2).encode() + b"\n"
        with pytest.raises(CanonicalArtifactError):
            parse_publication_review_artifact(raw)

    def test_a_v2_document_without_the_digest_is_refused_at_parse(self) -> None:
        document = json.loads(_v1().canonical_bytes().decode("utf-8"))
        document["protocol_version"] = LOT42_V2_PROTOCOL_VERSION
        raw = json.dumps(document, sort_keys=True, indent=2).encode() + b"\n"
        with pytest.raises(CanonicalArtifactError):
            parse_publication_review_artifact(raw)


class TestOnlyV2Authorizes:
    def test_a_v1_artifact_is_refused_by_the_authorization_barrier(self) -> None:
        with pytest.raises(CanonicalArtifactError, match="only LOT42-V2"):
            require_publication_review_v2(_v1())

    def test_a_v2_artifact_passes_the_authorization_barrier(self) -> None:
        artifact = _v2()
        assert require_publication_review_v2(artifact) is artifact

    def test_v1_remains_readable_for_audit(self) -> None:
        """V1 n'est pas supprimé du contrat : il reste lisible, et c'est
        seulement l'autorisation qui lui est retirée."""
        assert parse_publication_review_artifact(_v1().canonical_bytes()) is not None
