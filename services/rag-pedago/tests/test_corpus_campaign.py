"""Descripteur de campagne — ce qu'il refuse (`NEXUS-CORPUS-CAMPAIGN-V1`).

Aucune campagne de production n'est écrite ici : toutes les valeurs sont
des digests de test triviaux et déterministes, et l'environnement des
fixtures est explicite. Rien dans ce fichier ne peut être pris pour une
identité de corpus réelle.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from rag_pedago.governance.corpus_campaign import (
    CAMPAIGNS_DIR,
    CORPUS_CAMPAIGN_PROTOCOL_VERSION,
    CorpusCampaignError,
    CorpusCampaignV1,
    discover_promoted_campaign,
    parse_corpus_campaign,
)

OCI = "sha256:" + "1" * 64
ARCHIVE = "2" * 64
TREE = "3" * 64
LEGACY_V1_FIXTURE = Path(__file__).parent / "fixtures/legacy_v1/corpus_campaign_v1.json"
LEGACY_V1_FIXTURE_SHA256 = (
    "9b66216795d92977675b2744389bc202ea23bbceaf80af39e966f28b6a3e1169"
)


def _scope() -> dict[str, object]:
    return {
        "tenant": "libre_terminale",
        "collection": "rag_nexus_philo_terminale_tc",
        "niveau": "terminale",
        "voie": "generale",
        "matiere": "philosophie",
        "candidat": "libre",
        "audience": ["libre"],
        "visibility": "internal",
        "school_year": "2026-2027",
        "programme_version": "BOEN_special_8_2019-07-25",
    }


def _fields(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "protocol_version": CORPUS_CAMPAIGN_PROTOCOL_VERSION,
        "campaign_id": "eduscol-philo-terminale-test",
        "scope": _scope(),
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
        "authorization_id": "test-authorization",
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


def _campaign(**overrides: object) -> CorpusCampaignV1:
    return CorpusCampaignV1(**_fields(**overrides))  # type: ignore[arg-type]


class TestTheSourceIsNotSubstitutable:
    def test_another_registry_is_irrepresentable(self) -> None:
        """Un champ libre laisserait une campagne désigner son propre
        registre de confiance."""
        with pytest.raises(ValidationError):
            _campaign(source_registry="docker.io")

    def test_another_repository_is_irrepresentable(self) -> None:
        with pytest.raises(ValidationError):
            _campaign(source_repository="attacker/rag-corpus")

    def test_another_source_kind_is_irrepresentable(self) -> None:
        with pytest.raises(ValidationError):
            _campaign(source_kind="https-url")

    def test_a_tag_cannot_replace_the_digest(self) -> None:
        with pytest.raises(ValidationError):
            _campaign(source_oci_digest="latest")

    @pytest.mark.parametrize(
        "digest", ["sha256:zz", "sha512:" + "1" * 64, "1" * 64, "sha256:" + "1" * 63]
    )
    def test_a_malformed_oci_digest_is_refused(self, digest: str) -> None:
        with pytest.raises(ValidationError):
            _campaign(source_oci_digest=digest)

    def test_there_is_no_url_field_at_all(self) -> None:
        with pytest.raises(ValidationError):
            _campaign(source_url="https://example.org/corpus.tar.zst")

    def test_there_is_no_local_path_field_at_all(self) -> None:
        with pytest.raises(ValidationError):
            _campaign(source_path="/tmp/corpus")

    def test_the_reference_is_always_by_digest(self) -> None:
        assert _campaign().oci_reference() == (
            f"ghcr.io/cyranoaladin/rag-corpus@{OCI}"
        )


class TestThreeIndependentIdentities:
    def test_the_three_digests_must_differ(self) -> None:
        """Deux identités égales rendraient une vérification tautologique."""
        with pytest.raises(ValidationError, match="three distinct values"):
            _campaign(source_archive_sha256="1" * 64)

    def test_distinct_digests_are_accepted(self) -> None:
        assert _campaign().source_tree_digest == TREE


class TestPathConfinement:
    @pytest.mark.parametrize(
        "root", ["/etc", "../escape", "corpus/../../etc", "a/../../b"]
    )
    def test_an_escaping_source_root_is_refused(self, root: str) -> None:
        with pytest.raises(ValidationError):
            _campaign(source_root=root)

    @pytest.mark.parametrize(
        "campaign_id", ["../evil", "Upper", "with space", "a/b", ""]
    )
    def test_a_non_canonical_campaign_id_is_refused(self, campaign_id: str) -> None:
        with pytest.raises(ValidationError):
            _campaign(campaign_id=campaign_id)

    def test_the_canonical_paths_are_derived_from_the_identifier(self) -> None:
        campaign = _campaign()
        base = f"{CAMPAIGNS_DIR}/eduscol-philo-terminale-test"
        assert campaign.canonical_path() == f"{base}/campaign.json"
        assert campaign.sealed_manifest_path() == f"{base}/SHA256SUMS.txt"
        assert campaign.catalog_digest_path() == f"{base}/catalog.digest.json"
        assert campaign.review_view_path() == f"{base}/review-view.json"
        assert (
            campaign.authorization_path()
            == "governance/authorizations/test-authorization.json"
        )


class TestStrictParsing:
    def test_legacy_v1_fixture_bytes_are_immutable(self) -> None:
        raw = LEGACY_V1_FIXTURE.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == LEGACY_V1_FIXTURE_SHA256

        parsed = parse_corpus_campaign(raw)
        assert parsed.protocol_version == "NEXUS-CORPUS-CAMPAIGN-V1"
        assert parsed.canonical_bytes() == raw

    def test_canonical_bytes_round_trip(self) -> None:
        raw = _campaign().canonical_bytes()
        assert parse_corpus_campaign(raw).canonical_bytes() == raw

    def test_the_digest_is_stable(self) -> None:
        assert _campaign().digest() == _campaign().digest()

    def test_an_unknown_protocol_is_refused(self) -> None:
        document = json.loads(_campaign().canonical_bytes().decode("utf-8"))
        document["protocol_version"] = "NEXUS-CORPUS-CAMPAIGN-V2"
        raw = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")
        with pytest.raises(CorpusCampaignError, match="protocol_version is not"):
            parse_corpus_campaign(raw)

    def test_an_unknown_field_is_refused(self) -> None:
        document = json.loads(_campaign().canonical_bytes().decode("utf-8"))
        document["trusted"] = True
        raw = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")
        with pytest.raises(CorpusCampaignError, match="failed strict validation"):
            parse_corpus_campaign(raw)

    def test_non_canonical_bytes_are_refused(self) -> None:
        """Sans égalité octet à octet, le fichier relu et celui dont le
        digest est calculé peuvent différer."""
        document = json.loads(_campaign().canonical_bytes().decode("utf-8"))
        compact = json.dumps(document, sort_keys=True).encode("utf-8")
        with pytest.raises(CorpusCampaignError, match="not in canonical form"):
            parse_corpus_campaign(compact)

    def test_a_malformed_scope_is_refused(self) -> None:
        scope = _scope()
        del scope["visibility"]
        with pytest.raises(ValidationError):
            _campaign(scope=scope)


class TestCampaignDiscovery:
    def test_exactly_one_modified_campaign_is_promoted(self) -> None:
        assert (
            discover_promoted_campaign(
                [
                    f"{CAMPAIGNS_DIR}/eduscol-2026/campaign.json",
                    f"{CAMPAIGNS_DIR}/eduscol-2026/SHA256SUMS.txt",
                    "README.md",
                ]
            )
            == "eduscol-2026"
        )

    def test_no_modified_campaign_is_refused(self) -> None:
        with pytest.raises(CorpusCampaignError, match="no campaign"):
            discover_promoted_campaign(["README.md", "services/x.py"])

    def test_two_modified_campaigns_are_refused(self) -> None:
        """Choisir « la première » laisserait le hasard décider de ce qui
        part en production."""
        with pytest.raises(CorpusCampaignError, match="2 campaigns"):
            discover_promoted_campaign(
                [
                    f"{CAMPAIGNS_DIR}/a/campaign.json",
                    f"{CAMPAIGNS_DIR}/b/campaign.json",
                ]
            )

    def test_a_file_directly_under_the_root_is_refused(self) -> None:
        with pytest.raises(CorpusCampaignError, match="without naming a campaign"):
            discover_promoted_campaign([f"{CAMPAIGNS_DIR}/stray.json"])

    def test_a_non_canonical_discovered_id_is_refused(self) -> None:
        with pytest.raises(CorpusCampaignError, match="not canonical"):
            discover_promoted_campaign([f"{CAMPAIGNS_DIR}/../evil/campaign.json"])
