"""Descripteur de campagne multi-scope — ce qu'il refuse
(`NEXUS-CORPUS-CAMPAIGN-V2`, ADR-0044).

Aucune campagne de production n'est écrite ici : toutes les valeurs sont
des digests de test triviaux et déterministes.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from rag_pedago.governance.corpus_campaign import (
    CORPUS_CAMPAIGN_V2_PROTOCOL_VERSION,
    CorpusCampaignError,
    CorpusCampaignV1,
    CorpusCampaignV2,
    parse_corpus_campaign_v2,
)

OCI = "sha256:" + "1" * 64
ARCHIVE = "2" * 64
TREE = "3" * 64


def _fields(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "protocol_version": CORPUS_CAMPAIGN_V2_PROTOCOL_VERSION,
        "campaign_id": "prerentree-2026-2027-test",
        "source_kind": "ghcr-oci",
        "source_registry": "ghcr.io",
        "source_repository": "cyranoaladin/rag-corpus",
        "source_oci_digest": OCI,
        "source_archive_sha256": ARCHIVE,
        "source_tree_digest": TREE,
        "archive_format": "tar.zst",
        "source_root": "corpus",
        "expected_manifest_sha256": "4" * 64,
        "expected_catalog_digest": "5" * 64,
        "authorization_set_digest": "a" * 64,
        "compiler_version": "corpus-catalog-compiler/1",
        "routing_config_digest": "6" * 64,
        "rights_config_digest": "7" * 64,
        "pii_config_digest": "8" * 64,
        "golden_spec_digest": "9" * 64,
        "environment": "rehearsal",
        "retention_days": 90,
    }
    fields.update(overrides)
    return fields


def _campaign(**overrides: object) -> CorpusCampaignV2:
    return CorpusCampaignV2.model_validate(_fields(**overrides))


class TestNoScopeIdentity:
    def test_constructs_without_a_scope_field(self) -> None:
        campaign = _campaign()
        assert not hasattr(campaign, "scope")

    def test_canonical_document_never_carries_scope_dimensions(self) -> None:
        document = _campaign().canonical_document()
        assert "scope" not in document
        for dimension in (
            "tenant", "niveau", "voie", "matiere", "candidat", "audience",
            "visibility", "school_year", "programme_version",
        ):
            assert dimension not in document

    def test_rejects_a_v1_shaped_scope_field(self) -> None:
        fields = _fields()
        fields["scope"] = {
            "tenant": "libre_terminale", "collection": "c", "niveau": "terminale",
            "voie": "generale", "matiere": "philosophie", "candidat": "libre",
            "audience": ["libre"], "visibility": "internal", "school_year": "2026-2027",
            "programme_version": "BOEN_special_8_2019-07-25",
        }
        with pytest.raises(ValidationError):
            CorpusCampaignV2.model_validate(fields)

    def test_rejects_a_v1_shaped_authorization_id_field(self) -> None:
        fields = _fields()
        fields["authorization_id"] = "some-authorization"
        with pytest.raises(ValidationError):
            CorpusCampaignV2.model_validate(fields)


class TestAuthorizationSetDigest:
    def test_single_authorization_set_digest_field(self) -> None:
        campaign = _campaign()
        assert campaign.authorization_set_digest == "a" * 64

    def test_rejects_a_malformed_digest(self) -> None:
        with pytest.raises(ValidationError):
            CorpusCampaignV2.model_validate(_fields(authorization_set_digest="not-hex"))


class TestIdentitiesAreDistinct:
    def test_rejects_collapsed_source_identities(self) -> None:
        same = "9" * 64
        with pytest.raises(ValidationError, match="distinct"):
            CorpusCampaignV2.model_validate(
                _fields(
                    source_oci_digest=f"sha256:{same}",
                    source_archive_sha256=same,
                    source_tree_digest=same,
                )
            )


class TestCanonicalizationAndParsing:
    def test_canonical_bytes_are_deterministic(self) -> None:
        a = _campaign()
        b = _campaign()
        assert a.canonical_bytes() == b.canonical_bytes()

    def test_round_trip_parses_canonical_bytes(self) -> None:
        raw = _campaign().canonical_bytes()
        parsed = parse_corpus_campaign_v2(raw)
        assert parsed.authorization_set_digest == "a" * 64

    def test_refuses_non_canonical_bytes(self) -> None:
        canonical = _campaign().canonical_bytes()
        non_canonical = canonical.replace(b'"protocol_version"', b'"protocol_version" ')
        assert non_canonical != canonical
        with pytest.raises(CorpusCampaignError, match="canonical form"):
            parse_corpus_campaign_v2(non_canonical)

    def test_refuses_wrong_protocol_version(self) -> None:
        with pytest.raises(CorpusCampaignError, match="protocol_version"):
            parse_corpus_campaign_v2(b'{"protocol_version": "NEXUS-CORPUS-CAMPAIGN-V1"}')


class TestV1AndV2AreNeverInterchangeable:
    def test_v2_document_is_never_parseable_as_v1_model(self) -> None:
        raw_document = _fields()
        with pytest.raises(ValidationError):
            CorpusCampaignV1.model_validate(raw_document)
