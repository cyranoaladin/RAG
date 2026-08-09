"""LOT41A — points de contrôle d'ingestion (remédiation GATE H1, item **D**).

Une ``VerifiedAuthorization`` qui n'est pas *appliquée* n'autorise rien. Ce
fichier exerce chaque point de contrôle isolément, sur des faits qui
correspondent exactement à ceux que le pipeline produit : scope, digest de
manifest, empreinte de profil, hôte réellement contacté, redirection,
catégorie de droits, fenêtre de validité, PII.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from nexus_contracts.document import Rights
from nexus_contracts.ingestion import ResourceScope

from ingestor.ingestion_control import scope_enforcement as scope_enforcement_module
from ingestor.ingestion_control.scope_authority import (
    VerifiedAuthorization,
    authorization_allows_rights,
)
from ingestor.ingestion_control.scope_enforcement import (
    ScopeEnforcementViolation,
    enforce_before_fetch,
    enforce_content_sha256,
    enforce_destination,
    enforce_pii,
    enforce_rights,
    enforce_validity_window,
    require_h2_content_bound_authority,
)

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)

SCOPE = ResourceScope(
    tenant="libre_terminale",
    collection="rag_nexus_nsi_terminale_specialite",
    niveau="terminale",
    voie="generale",
    matiere="nsi",
    candidat="libre",
    audience=["libre", "tous"],
    visibility="internal",
    school_year="2026-2027",
    programme_version="BOEN_special_8_2019-07-25",
)

MANIFEST = "a" * 64
FINGERPRINT = "b" * 64
CONTENT_SHA = "1" * 64


def authorization(**overrides: Any) -> VerifiedAuthorization:
    defaults: dict[str, Any] = {
        "authorization_id": "auth-nsi-terminale-2026",
        "scope": SCOPE,
        "manifest_digest": MANIFEST,
        "profile_id": "rag_nexus_nsi_terminale_specialite",
        "profile_version": "v1",
        "profile_fingerprint": FINGERPRINT,
        "allowed_domains": ("eduscol.education.fr",),
        "rights_categories": ("officiel_public",),
        "exclusions": (),
        "pii_absence_attested": True,
        "valid_from": NOW - timedelta(days=1),
        "valid_until": NOW + timedelta(days=30),
        "artifact_path": "governance/authorizations/auth-nsi-terminale-2026.json",
        "artifact_blob_sha": "c" * 40,
        "authorization_digest": "d" * 64,
        "evidence_repository": "cyranoaladin/RAG",
        "evidence_pull_request": 4242,
        "evidence_base_sha": "e" * 40,
        "evidence_head_sha": "f" * 40,
        "evidence_review_id": 777,
        "evidence_reviewer": "abenrhouma",
        "evidence_challenge": "NEXUS-TRUSTED-REVIEW-V1:" + "0" * 64,
        "verified_at": NOW,
    }
    defaults.update(overrides)
    return VerifiedAuthorization(**defaults)


def before_fetch(auth: VerifiedAuthorization, **overrides: Any) -> None:
    kwargs: dict[str, Any] = {
        "authorization_id": auth.authorization_id,
        "scope": SCOPE,
        "manifest_digest": MANIFEST,
        "profile_id": "rag_nexus_nsi_terminale_specialite",
        "profile_version": "v1",
        "profile_fingerprint": FINGERPRINT,
        "now": NOW,
    }
    kwargs.update(overrides)
    enforce_before_fetch(auth, **kwargs)


class TestPreFetchCheckpoint:
    def test_matching_facts_pass(self) -> None:
        before_fetch(authorization())

    def test_a_different_authorization_id_is_refused(self) -> None:
        """Item C au niveau du point de contrôle : le job nomme une
        autorisation ; la vérifier puis en appliquer une autre serait
        exactement le glissement d'autorité que l'item interdit."""
        with pytest.raises(ScopeEnforcementViolation, match="job names"):
            before_fetch(authorization(), authorization_id="auth-other")

    def test_a_different_scope_is_refused(self) -> None:
        other = SCOPE.model_copy(update={"niveau": "premiere"})
        with pytest.raises(ScopeEnforcementViolation, match="not the job scope"):
            before_fetch(authorization(), scope=other)

    def test_manifest_drift_is_refused(self) -> None:
        with pytest.raises(ScopeEnforcementViolation, match="manifest drift"):
            before_fetch(authorization(), manifest_digest="9" * 64)

    @pytest.mark.parametrize(
        "override",
        [
            {"profile_id": "another_collection"},
            {"profile_version": "v2"},
            {"profile_fingerprint": "9" * 64},
        ],
    )
    def test_profile_drift_is_refused(self, override: dict[str, Any]) -> None:
        with pytest.raises(ScopeEnforcementViolation, match="profile drift"):
            before_fetch(authorization(), **override)

    def test_authorization_not_yet_valid_is_refused(self) -> None:
        auth = authorization(
            valid_from=NOW + timedelta(days=1), valid_until=NOW + timedelta(days=2)
        )
        with pytest.raises(ScopeEnforcementViolation, match="not valid yet"):
            before_fetch(auth)

    def test_expired_authorization_is_refused(self) -> None:
        auth = authorization(
            valid_from=NOW - timedelta(days=2), valid_until=NOW - timedelta(seconds=1)
        )
        with pytest.raises(ScopeEnforcementViolation, match="expired"):
            before_fetch(auth)


class TestValidityIsReEvaluatedAtEveryCheckpoint:
    def test_expiry_during_processing_stops_the_next_step(self) -> None:
        """Une autorisation valide au démarrage mais expirée quand les
        droits sont évalués ne doit pas laisser la ressource avancer."""
        auth = authorization(valid_until=NOW + timedelta(minutes=5))
        before_fetch(auth)  # passe au démarrage
        later = NOW + timedelta(minutes=10)
        with pytest.raises(ScopeEnforcementViolation, match="expired"):
            enforce_validity_window(auth, now=later, checkpoint="rights")
        with pytest.raises(ScopeEnforcementViolation, match="expired"):
            enforce_rights(auth, rights=Rights.officiel_public, now=later)


class TestDestinationCheckpoint:
    def test_authorized_host_passes(self) -> None:
        assert (
            enforce_destination(authorization(), url="https://eduscol.education.fr/nsi")
            == "eduscol.education.fr"
        )

    def test_host_is_normalized_before_comparison(self) -> None:
        assert (
            enforce_destination(authorization(), url="https://EDUSCOL.Education.FR./x")
            == "eduscol.education.fr"
        )

    @pytest.mark.parametrize(
        "url",
        [
            "https://attacker.test/nsi",
            # Suffixe : autorise education.fr ne doit jamais autoriser un
            # domaine qui le contient comme préfixe de label.
            "https://eduscol.education.fr.attacker.test/nsi",
            # Sous-domaine non nommé : jamais implicitement autorisé.
            "https://www.eduscol.education.fr/nsi",
            # Domaine parent : jamais implicitement autorisé non plus.
            "https://education.fr/nsi",
        ],
    )
    def test_unauthorized_hosts_are_refused(self, url: str) -> None:
        with pytest.raises(ScopeEnforcementViolation, match="not in the authorized domains"):
            enforce_destination(authorization(), url=url)

    def test_url_without_host_is_refused(self) -> None:
        with pytest.raises(ScopeEnforcementViolation, match="no hostname"):
            enforce_destination(authorization(), url="file:///etc/passwd")

    def test_host_exclusion_is_applied(self) -> None:
        auth = authorization(
            allowed_domains=("eduscol.education.fr", "www.education.fr"),
            exclusions=("www.education.fr",),
        )
        enforce_destination(auth, url="https://eduscol.education.fr/x")
        with pytest.raises(ScopeEnforcementViolation, match="matches exclusion"):
            enforce_destination(auth, url="https://www.education.fr/x")

    def test_path_prefix_exclusion_is_applied(self) -> None:
        auth = authorization(exclusions=("/prive",))
        enforce_destination(auth, url="https://eduscol.education.fr/public/doc")
        with pytest.raises(ScopeEnforcementViolation, match="matches exclusion"):
            enforce_destination(auth, url="https://eduscol.education.fr/prive/doc")

    def test_path_prefix_exclusion_does_not_match_a_similar_prefix(self) -> None:
        """``/prive`` ne doit pas exclure ``/privelege`` — une exclusion est
        un préfixe de segment, jamais un préfixe de chaîne."""
        auth = authorization(exclusions=("/prive",))
        enforce_destination(auth, url="https://eduscol.education.fr/privelege/doc")

    def test_host_scoped_path_exclusion_is_applied(self) -> None:
        auth = authorization(exclusions=("eduscol.education.fr/interne",))
        enforce_destination(auth, url="https://eduscol.education.fr/public")
        with pytest.raises(ScopeEnforcementViolation, match="matches exclusion"):
            enforce_destination(auth, url="https://eduscol.education.fr/interne/x")


class TestContentCheckpoint:
    def test_v2_allowed_content_passes(self) -> None:
        auth = authorization(
            protocol_version="LOT41A-V2",
            allowed_content_sha256=(CONTENT_SHA, "2" * 64),
        )
        enforce_content_sha256(auth, content_sha256=CONTENT_SHA)

    def test_v2_unlisted_content_is_refused_at_content_checkpoint(self) -> None:
        auth = authorization(
            protocol_version="LOT41A-V2",
            allowed_content_sha256=(CONTENT_SHA,),
        )
        with pytest.raises(ScopeEnforcementViolation) as excinfo:
            enforce_content_sha256(auth, content_sha256="2" * 64)
        assert excinfo.value.checkpoint == "content"
        assert "not in" in str(excinfo.value)

    def test_mut_h2b_13_same_host_unlisted_content_stops_before_extraction(
        self,
    ) -> None:
        auth = authorization(
            protocol_version="LOT41A-V2",
            allowed_content_sha256=(CONTENT_SHA,),
        )
        enforce_destination(auth, url="https://eduscol.education.fr/other.pdf")
        extractor_called = False
        try:
            enforce_content_sha256(auth, content_sha256="2" * 64)
            extractor_called = True
        except ScopeEnforcementViolation as exc:
            assert exc.checkpoint == "content"
            assert extractor_called is False
            return
        pytest.fail("MUT-H2B-13 content allowlist guard was neutralized")

    @pytest.mark.parametrize(
        "allowlist",
        [
            None,
            (),
            ("not-a-sha",),
            ("A" * 64,),
            ("2" * 64, "1" * 64),
            ("1" * 64, "1" * 64),
        ],
    )
    def test_injected_noncanonical_v2_state_fails_closed(
        self, allowlist: tuple[str, ...] | None
    ) -> None:
        auth = authorization(
            protocol_version="LOT41A-V2",
            allowed_content_sha256=allowlist,
        )
        with pytest.raises(ScopeEnforcementViolation) as excinfo:
            enforce_content_sha256(auth, content_sha256=CONTENT_SHA)
        assert excinfo.value.checkpoint == "content"

    def test_injected_non_string_v2_allowlist_entry_fails_as_content_violation(
        self,
    ) -> None:
        auth = authorization(
            protocol_version="LOT41A-V2",
            allowed_content_sha256=(1,),
        )
        with pytest.raises(ScopeEnforcementViolation) as excinfo:
            enforce_content_sha256(auth, content_sha256=CONTENT_SHA)
        assert excinfo.value.checkpoint == "content"

    @pytest.mark.parametrize(
        "content_sha256", [None, 123, b"1" * 64, "", "x" * 64, "A" * 64, "1" * 63]
    )
    def test_invalid_supplied_sha_fails_closed(self, content_sha256: object) -> None:
        auth = authorization(
            protocol_version="LOT41A-V2",
            allowed_content_sha256=(CONTENT_SHA,),
        )
        with pytest.raises(ScopeEnforcementViolation) as excinfo:
            enforce_content_sha256(auth, content_sha256=content_sha256)
        assert excinfo.value.checkpoint == "content"

    def test_v1_content_checkpoint_preserves_historical_runtime_behavior(self) -> None:
        enforce_content_sha256(
            authorization(protocol_version="LOT41A-V1", allowed_content_sha256=None),
            content_sha256=CONTENT_SHA,
        )

    def test_unknown_protocol_injected_state_fails_closed(self) -> None:
        auth = authorization(
            protocol_version="LOT41A-V3",
            allowed_content_sha256=(CONTENT_SHA,),
        )
        with pytest.raises(ScopeEnforcementViolation, match="unsupported protocol"):
            enforce_content_sha256(auth, content_sha256=CONTENT_SHA)

    def test_h2_policy_rejects_v1_with_stable_reason(self) -> None:
        with pytest.raises(
            ScopeEnforcementViolation, match="CONTENT_ALLOWLIST_AUTHORITY_REQUIRED"
        ) as excinfo:
            require_h2_content_bound_authority(authorization())
        assert excinfo.value.checkpoint == "content"

    def test_h2_policy_accepts_a_canonical_v2_authorization(self) -> None:
        require_h2_content_bound_authority(
            authorization(
                protocol_version="LOT41A-V2",
                allowed_content_sha256=(CONTENT_SHA,),
            )
        )

    def test_content_guards_are_explicit_public_exports(self) -> None:
        assert {
            "enforce_content_sha256",
            "require_h2_content_bound_authority",
        } <= set(scope_enforcement_module.__all__)


class TestRightsCheckpoint:
    def test_authorized_category_passes(self) -> None:
        enforce_rights(authorization(), rights=Rights.officiel_public)

    def test_forbidden_category_is_refused(self) -> None:
        with pytest.raises(ScopeEnforcementViolation, match="not among the authorized"):
            enforce_rights(authorization(), rights=Rights.commercial_confidential)

    def test_unknown_is_always_refused(self) -> None:
        """Même si une autorisation listait ``unknown`` (impossible via
        l'artefact, mais la défense reste explicite), des droits
        indéterminés ne sont jamais couverts."""
        auth = authorization(rights_categories=("officiel_public", "unknown"))
        with pytest.raises(ScopeEnforcementViolation, match="undetermined rights"):
            enforce_rights(auth, rights=Rights.unknown)

    def test_helper_agrees_with_the_checkpoint(self) -> None:
        auth = authorization()
        assert authorization_allows_rights(auth, Rights.officiel_public) is True
        assert authorization_allows_rights(auth, Rights.restricted) is False
        assert authorization_allows_rights(auth, "officiel_public") is True


class TestPiiCheckpoint:
    def test_absence_of_pii_passes(self) -> None:
        enforce_pii(authorization(), pii_detected=False)

    def test_detected_pii_is_refused(self) -> None:
        with pytest.raises(ScopeEnforcementViolation, match="ingests no PII"):
            enforce_pii(authorization(), pii_detected=True)


class TestViolationsCarryTheirCheckpoint:
    def test_checkpoint_is_machine_readable(self) -> None:
        """Un refus au fetch et un refus aux droits ne sont pas le même
        événement d'audit — le nom du point de contrôle est porté par
        l'exception, jamais seulement dans son texte."""
        with pytest.raises(ScopeEnforcementViolation) as excinfo:
            enforce_destination(authorization(), url="https://attacker.test/x")
        assert excinfo.value.checkpoint == "destination"

        with pytest.raises(ScopeEnforcementViolation) as excinfo:
            enforce_rights(authorization(), rights=Rights.restricted)
        assert excinfo.value.checkpoint == "rights"
