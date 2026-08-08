"""LOT41A/LOT42 — artefacts d'autorité canoniques (remédiation GATE H1,
items **B** et **E**).

Ce fichier prouve la propriété dont dépend toute la chaîne d'autorité :
**une décision a une et une seule forme d'octets, et son digest ne peut
pas être obtenu depuis d'autres octets.** Sans cela, « l'humain a approuvé
ce digest » ne dirait rien sur ce que la machine applique.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from nexus_contracts.authority_artifacts import (
    CanonicalArtifactError,
    PublicationReviewArtifact,
    ScopeAuthorizationArtifact,
    canonical_authorization_path,
    canonical_publication_review_path,
    git_blob_sha1,
    normalize_hostname,
    parse_publication_review_artifact,
    parse_scope_authorization_artifact,
)

VALID_SCOPE: dict[str, Any] = {
    "tenant": "libre_terminale",
    "collection": "rag_nexus_nsi_terminale_specialite",
    "niveau": "terminale",
    "voie": "generale",
    "matiere": "nsi",
    "candidat": "libre",
    "audience": ["libre", "tous"],
    "visibility": "internal",
    "school_year": "2026-2027",
    "programme_version": "BOEN_special_8_2019-07-25",
}


def authorization_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "protocol_version": "LOT41A-V1",
        "authorization_id": "auth-nsi-terminale-2026",
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "scope": dict(VALID_SCOPE),
        "manifest_digest": "a" * 64,
        "profile_id": "rag_nexus_nsi_terminale_specialite",
        "profile_version": "v1",
        "profile_fingerprint": "b" * 64,
        "allowed_domains": ["eduscol.education.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "pii_absence_attested": True,
        "pii_absence_evidence": "Corpus officiel, aucune donnee personnelle.",
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
    }
    document.update(overrides)
    return document


def canonical_authorization_bytes(**overrides: Any) -> bytes:
    return ScopeAuthorizationArtifact.model_validate(
        authorization_document(**overrides)
    ).canonical_bytes()


class TestCanonicalFormIsUnique:
    def test_round_trip_is_byte_stable(self) -> None:
        raw = canonical_authorization_bytes()
        assert parse_scope_authorization_artifact(raw).canonical_bytes() == raw

    def test_digest_is_deterministic_across_parses(self) -> None:
        raw = canonical_authorization_bytes()
        first = parse_scope_authorization_artifact(raw).digest()
        second = parse_scope_authorization_artifact(raw).digest()
        assert first == second
        assert len(first) == 64

    @pytest.mark.parametrize(
        ("label", "mutate"),
        [
            ("compact separators", lambda d: json.dumps(d, sort_keys=True).encode()),
            ("four-space indent", lambda d: json.dumps(d, sort_keys=True, indent=4).encode()),
            ("unsorted keys", lambda d: json.dumps(d, sort_keys=False, indent=2).encode()),
            ("no trailing newline",
             lambda d: json.dumps(d, sort_keys=True, indent=2).encode()),
        ],
    )
    def test_non_canonical_encodings_are_refused(
        self, label: str, mutate: Any
    ) -> None:
        """Un fichier logiquement équivalent mais encodé autrement est
        refusé : sinon deux fichiers différents porteraient la même
        décision, et « les octets revus » cesserait d'avoir un sens."""
        document = json.loads(canonical_authorization_bytes().decode())
        with pytest.raises(CanonicalArtifactError, match="canonical"):
            parse_scope_authorization_artifact(mutate(document))

    def test_single_byte_change_changes_the_digest(self) -> None:
        base = parse_scope_authorization_artifact(canonical_authorization_bytes()).digest()
        other = parse_scope_authorization_artifact(
            canonical_authorization_bytes(manifest_digest="a" * 63 + "b")
        ).digest()
        assert base != other

    def test_git_blob_sha_matches_real_git(self, tmp_path: Path) -> None:
        """``git_blob_sha1`` doit être le VRAI identifiant Git — vérifié
        contre ``git hash-object`` lui-même, jamais seulement contre une
        réimplémentation de la même formule."""
        raw = canonical_authorization_bytes()
        target = tmp_path / "artifact.json"
        target.write_bytes(raw)
        result = subprocess.run(
            ["git", "hash-object", str(target)],
            capture_output=True, text=True, check=True,
        )
        assert git_blob_sha1(raw) == result.stdout.strip()


class TestStrictValidation:
    def test_unknown_field_is_refused(self) -> None:
        """``extra='forbid'`` : un champ inconnu ne peut pas voyager à côté
        de la décision revue."""
        document = authorization_document()
        document["max_documents"] = 10_000
        with pytest.raises(CanonicalArtifactError, match="strict validation"):
            parse_scope_authorization_artifact(
                (json.dumps(document, sort_keys=True, indent=2) + "\n").encode()
            )

    @pytest.mark.parametrize(
        "overrides",
        [
            {"decision": "AUTHORIZE_EVERYTHING"},
            {"protocol_version": "LOT41A-V2"},
            {"pii_absence_attested": False},
            {"manifest_digest": "not-a-digest"},
            {"allowed_domains": []},
            {"rights_categories": []},
            {"valid_until": "2025-01-01T00:00:00Z"},
        ],
    )
    def test_invalid_decisions_cannot_be_constructed(self, overrides: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            ScopeAuthorizationArtifact.model_validate(authorization_document(**overrides))

    @pytest.mark.parametrize(
        "domains",
        [
            ["*"],
            ["*.education.fr"],
            ["Eduscol.Education.FR"],
            ["https://eduscol.education.fr"],
            ["eduscol.education.fr:443"],
            ["eduscol.education.fr/programmes"],
            ["eduscol.education.fr", "eduscol.education.fr"],
            ["www.education.fr", "eduscol.education.fr"],  # non trié
            ["93.184.216.34"],
            ["éduscol.education.fr"],
        ],
    )
    def test_non_canonical_domains_are_refused(self, domains: list[str]) -> None:
        """Chaque forme non canonique est refusée à la construction : la
        comparaison « hostname ∈ allowed_domains » au moment de
        l'enforcement ne peut donc jamais être ambiguë."""
        with pytest.raises(ValueError):
            ScopeAuthorizationArtifact.model_validate(
                authorization_document(allowed_domains=domains)
            )

    def test_unknown_rights_category_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown"):
            ScopeAuthorizationArtifact.model_validate(
                authorization_document(rights_categories=["officiel_public", "unknown"])
            )

    def test_rights_categories_must_be_sorted(self) -> None:
        with pytest.raises(ValueError, match="sorted"):
            ScopeAuthorizationArtifact.model_validate(
                authorization_document(
                    rights_categories=["public_allowed", "officiel_public"]
                )
            )


class TestCanonicalPathCannotEscape:
    def test_path_is_derived_from_the_identifier_alone(self) -> None:
        assert (
            canonical_authorization_path("auth-nsi-terminale-2026")
            == "governance/authorizations/auth-nsi-terminale-2026.json"
        )

    @pytest.mark.parametrize(
        "identifier",
        [
            "../../etc/passwd",
            "auth/../../secrets",
            "auth/nested",
            "Auth-Uppercase",
            "",
            "-leading-dash",
            "a" * 129,
        ],
    )
    def test_hostile_identifiers_are_refused(self, identifier: str) -> None:
        with pytest.raises(ValueError):
            canonical_authorization_path(identifier)

    def test_publication_review_path_embeds_the_digest(self) -> None:
        digest = "c" * 64
        assert canonical_publication_review_path(review_id="pub-1", digest=digest) == (
            f"governance/publication-reviews/pub-1-{digest}.json"
        )

    def test_publication_review_path_refuses_a_malformed_digest(self) -> None:
        with pytest.raises(ValueError, match="64 lowercase hex"):
            canonical_publication_review_path(review_id="pub-1", digest="short")


class TestHostnameNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("  EDUSCOL.education.FR  ", "eduscol.education.fr"),
            ("eduscol.education.fr.", "eduscol.education.fr"),
        ],
    )
    def test_normalizes_case_whitespace_and_trailing_dot(
        self, raw: str, expected: str
    ) -> None:
        assert normalize_hostname(raw) == expected

    def test_is_idempotent(self) -> None:
        once = normalize_hostname("  EDUSCOL.Education.fr. ")
        assert normalize_hostname(once) == once


class TestPublicationReviewArtifactRefusesNegativeChains:
    """Item F, première barrière : une décision de publication négative est
    **irreprésentable**, pas seulement refusée plus tard."""

    @staticmethod
    def _document(**overrides: Any) -> dict[str, Any]:
        document: dict[str, Any] = {
            "protocol_version": "LOT42-V1",
            "review_id": "pub-nsi-001",
            "decision": "AUTHORIZE_PUBLICATION",
            "resource_id": "11111111-1111-4111-8111-111111111111",
            "artifact_id": "22222222-2222-4222-8222-222222222222",
            "collection": "rag_nexus_nsi_terminale_specialite",
            "canonical_url": "https://eduscol.education.fr/nsi",
            "content_sha256": "d" * 64,
            "scope_authorization_id": "auth-nsi-terminale-2026",
            "profile_id": "rag_nexus_nsi_terminale_specialite",
            "profile_version": "v1",
            "profile_fingerprint": "b" * 64,
            "manifest_digest": "a" * 64,
            "rights_status": "officiel_public",
            "rights_assessed_at": "2026-08-08T10:00:00Z",
            "quality_passed": True,
            "quality_report_digest": "e" * 64,
            "quality_assessed_at": "2026-08-08T10:01:00Z",
            "gate_passed": True,
            "gate_name": "routing_gate",
            "gate_evaluated_at": "2026-08-08T10:02:00Z",
            "evidence_event_ids": [
                "33333333-3333-4333-8333-333333333333",
                "44444444-4444-4444-8444-444444444444",
            ],
        }
        document.update(overrides)
        return document

    def test_a_positive_chain_round_trips(self) -> None:
        artifact = PublicationReviewArtifact.model_validate(self._document())
        assert parse_publication_review_artifact(artifact.canonical_bytes()) == artifact

    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            ({"quality_passed": False}, "quality_passed must be true"),
            ({"gate_passed": False}, "gate_passed must be true"),
            ({"rights_status": "unknown"}, "never be 'unknown'"),
        ],
    )
    def test_negative_chains_cannot_be_constructed(
        self, overrides: dict[str, Any], expected: str
    ) -> None:
        with pytest.raises(ValueError, match=expected):
            PublicationReviewArtifact.model_validate(self._document(**overrides))

    def test_evidence_event_ids_must_be_present_and_sorted(self) -> None:
        with pytest.raises(ValueError):
            PublicationReviewArtifact.model_validate(
                self._document(evidence_event_ids=[])
            )
        with pytest.raises(ValueError, match="sorted"):
            PublicationReviewArtifact.model_validate(
                self._document(
                    evidence_event_ids=[
                        "44444444-4444-4444-8444-444444444444",
                        "33333333-3333-4333-8333-333333333333",
                    ]
                )
            )

    def test_path_changes_when_any_field_changes(self) -> None:
        """Le digest fait partie du chemin : une décision modifiée ne peut
        jamais réutiliser le chemin d'une décision déjà approuvée."""
        first = PublicationReviewArtifact.model_validate(self._document())
        second = PublicationReviewArtifact.model_validate(
            self._document(canonical_url="https://eduscol.education.fr/autre")
        )
        assert first.canonical_path() != second.canonical_path()
