"""ADR-0035 — le producteur du reçu de liaison de revue.

Aucun appel réseau : la frontière GitHub (``verify_review``,
``pull_request_actor_context``, ``fetch_blob_at_ref``) est substituée par
des doubles qui rendent **les structures réelles** de ce dépôt —
``ReviewVerification``, ``PullRequestActorContext``, ``GitHubBlob``. Les
scénarios de transport, de pagination et de politique de reviewers sont
couverts par leurs suites dédiées (``test_lot41a_github_authority_
transport.py``, ``scripts/tests/test-trusted-human-review.py``) ; ce
fichier mesure ce que le producteur fait de leurs résultats.

Le contrôle qui compte : chaque refus doit se produire **avant** toute
émission d'octets. Un reçu partiel n'existe jamais.
"""
from __future__ import annotations

import argparse
import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest
from nexus_contracts.authority_artifacts import (
    ScopeAuthorizationArtifactV2,
    canonical_authorization_path,
    git_blob_sha1,
)
from nexus_contracts.review_binding import (
    ReviewBindingError,
    TrustAnchor,
    expected_challenge_digest,
    public_key_hex,
    verify_review_binding,
)

import ingestor.ingestion_worker.issue_review_binding_cli as producer
from ingestor.ingestion_control.github_authority import (
    GitHubAuthorityError,
    GitHubBlob,
    PullRequestActorContext,
    ReviewVerification,
)

#: Graine de test — l'ancre qui la déclare porte ``environment="test"``, et
#: le contrat refuse de l'exercer en mode production.
TEST_SEED = "33" * 32
KEY_ID = "nexus-governance-test-1"

REPOSITORY = "cyranoaladin/RAG"
PULL_REQUEST = 95
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
REVIEW_ID = 4242
REVIEWER = "abenrhouma"
AUTHOR = "cyranoaladin"
AUTHORIZATION_ID = "h2f-corpus-eduscol-v1"
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)

SCOPE: dict[str, Any] = {
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


def _authorization_bytes(**overrides: Any) -> bytes:
    document: dict[str, Any] = {
        "protocol_version": "LOT41A-V2",
        "authorization_id": AUTHORIZATION_ID,
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "scope": dict(SCOPE),
        "manifest_digest": "c" * 64,
        "profile_id": SCOPE["collection"],
        "profile_version": "v1",
        "profile_fingerprint": "d" * 64,
        "allowed_domains": ["eduscol.education.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "allowed_content_sha256": ["e" * 64],
        "pii_absence_attested": True,
        "pii_absence_evidence": "Corpus officiel, aucune donnee personnelle.",
        "valid_from": "2026-01-01T00:00:00.000000Z",
        "valid_until": "2026-12-31T23:59:59.999999Z",
    }
    document.update(overrides)
    return ScopeAuthorizationArtifactV2.model_validate(document).canonical_bytes()


def _challenge(**overrides: Any) -> str:
    values: dict[str, Any] = {
        "repository": REPOSITORY,
        "pull_request": PULL_REQUEST,
        "base_ref": "main",
        "base_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "author": AUTHOR,
        "reviewer": REVIEWER,
    }
    values.update(overrides)
    return "NEXUS-TRUSTED-REVIEW-V1:" + expected_challenge_digest(**values)


def _verification(**overrides: Any) -> ReviewVerification:
    values: dict[str, Any] = {
        "approved": True,
        "reason": "approved",
        "repository": REPOSITORY,
        "pull_request": PULL_REQUEST,
        "base_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "reviewer": REVIEWER,
        "review_id": REVIEW_ID,
        "submitted_at": "2026-08-09T10:00:00Z",
        "challenge": _challenge(),
    }
    values.update(overrides)
    return ReviewVerification(**values)


def _context(**overrides: Any) -> PullRequestActorContext:
    values: dict[str, Any] = {
        "repository": REPOSITORY,
        "pull_request": PULL_REQUEST,
        "author": AUTHOR,
        "base_ref": "main",
        "reviewer": REVIEWER,
        "reviewer_permission": "admin",
        "reviewer_role_name": "admin",
    }
    values.update(overrides)
    return PullRequestActorContext(**values)


def _blob(content: bytes | None = None) -> GitHubBlob:
    raw = content if content is not None else _authorization_bytes()
    return GitHubBlob(
        repository=REPOSITORY,
        path=canonical_authorization_path(AUTHORIZATION_ID),
        ref=HEAD_SHA,
        blob_sha=git_blob_sha1(raw),
        content=raw,
    )


def _args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "repository": REPOSITORY,
        "pull_request": PULL_REQUEST,
        "expected_head": HEAD_SHA,
        "authorization_id": AUTHORIZATION_ID,
        "validity_days": 30,
        "key_id": KEY_ID,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Frontière GitHub substituée — jamais un vrai appel."""
    state: dict[str, Any] = {
        "verification": _verification(),
        "context": _context(),
        "blob": _blob(),
        "verify_error": None,
        "blob_error": None,
        "context_error": None,
    }

    def verify_review(**_kwargs: Any) -> ReviewVerification:
        if state["verify_error"] is not None:
            raise state["verify_error"]
        return state["verification"]

    def actor_context(**_kwargs: Any) -> PullRequestActorContext:
        if state["context_error"] is not None:
            raise state["context_error"]
        return state["context"]

    def fetch_blob(**_kwargs: Any) -> GitHubBlob:
        if state["blob_error"] is not None:
            raise state["blob_error"]
        return state["blob"]

    monkeypatch.setattr(producer, "verify_review", verify_review)
    monkeypatch.setattr(producer, "pull_request_actor_context", actor_context)
    monkeypatch.setattr(producer, "fetch_blob_at_ref", fetch_blob)
    monkeypatch.setenv(producer.SIGNING_KEY_ENV, TEST_SEED)
    return state


def _trust_anchor(environment: str = "test") -> TrustAnchor:
    return TrustAnchor.model_validate(
        {
            "protocol_version": "NEXUS-REVIEW-BINDING-V1",
            "keys": [
                {
                    "key_id": KEY_ID,
                    "algorithm": "ed25519",
                    "public_key": public_key_hex(TEST_SEED),
                    "environment": environment,
                }
            ],
        }
    )


class TestNominalIssuance:
    def test_an_exact_review_produces_a_verifiable_receipt(
        self, github: dict[str, Any]
    ) -> None:
        raw = producer._issue_binding(_args(), now=NOW)
        binding = verify_review_binding(
            raw, trust_anchor=_trust_anchor(), environment="test", now=NOW
        )
        assert binding.repository == REPOSITORY
        assert binding.pull_request == PULL_REQUEST
        assert binding.base_sha == BASE_SHA
        assert binding.head_sha == HEAD_SHA
        assert binding.review_id == REVIEW_ID
        assert binding.reviewer_login == REVIEWER
        assert binding.author_login == AUTHOR
        assert binding.reviewer_permission == "admin"
        assert binding.authorization_id == AUTHORIZATION_ID
        assert binding.authorization_decision == "AUTHORIZE_INGESTION_SCOPE"
        assert binding.authorization_artifact_sha256 == hashlib.sha256(
            _authorization_bytes()
        ).hexdigest()
        assert binding.authorization_artifact_git_blob_sha1 == git_blob_sha1(
            _authorization_bytes()
        )
        assert binding.verifier_version == producer.VERIFIER_VERSION

    def test_the_receipt_is_bound_to_the_canonical_path_not_an_argument(
        self, github: dict[str, Any]
    ) -> None:
        raw = producer._issue_binding(_args(), now=NOW)
        binding = verify_review_binding(
            raw, trust_anchor=_trust_anchor(), environment="test", now=NOW
        )
        assert binding.authorization_artifact_path == (
            f"governance/authorizations/{AUTHORIZATION_ID}.json"
        )

    def test_a_receipt_signed_with_a_test_key_never_passes_production(
        self, github: dict[str, Any]
    ) -> None:
        raw = producer._issue_binding(_args(), now=NOW)
        with pytest.raises(ReviewBindingError, match="'test' environment"):
            verify_review_binding(
                raw,
                trust_anchor=_trust_anchor("test"),
                environment="production",
                now=NOW,
            )


class TestFailsClosed:
    def test_github_unavailable_emits_nothing(self, github: dict[str, Any]) -> None:
        """Le cas le plus important : indisponibilité ≠ absence de problème."""
        github["verify_error"] = GitHubAuthorityError("connection reset")
        with pytest.raises(
            producer.ReviewBindingProductionError, match="LIVE_REVIEW_VERIFICATION_FAILED"
        ):
            producer._issue_binding(_args(), now=NOW)

    def test_a_non_approved_review_emits_nothing(self, github: dict[str, Any]) -> None:
        github["verification"] = _verification(
            approved=False, reason="approval_revoked", reviewer=None,
            review_id=None, challenge=None, submitted_at=None,
        )
        with pytest.raises(
            producer.ReviewBindingProductionError, match="REVIEW_NOT_APPROVED"
        ):
            producer._issue_binding(_args(), now=NOW)

    def test_another_head_is_refused(self, github: dict[str, Any]) -> None:
        """``verify_review`` refuse déjà un head divergent ; ce test mesure
        que le producteur propage ce refus au lieu de le contourner."""
        github["verification"] = _verification(
            approved=False, reason="expected_head_mismatch", reviewer=None,
            review_id=None, challenge=None, submitted_at=None,
        )
        with pytest.raises(
            producer.ReviewBindingProductionError, match="expected_head_mismatch"
        ):
            producer._issue_binding(_args(expected_head="c" * 40), now=NOW)

    def test_another_base_ref_is_refused(self, github: dict[str, Any]) -> None:
        github["context"] = _context(base_ref="release/2026")
        with pytest.raises(
            producer.ReviewBindingProductionError, match="BASE_REF_UNSUPPORTED"
        ):
            producer._issue_binding(_args(), now=NOW)

    def test_reviewer_equal_to_author_is_refused(self, github: dict[str, Any]) -> None:
        github["context"] = _context(author=REVIEWER)
        with pytest.raises(
            producer.ReviewBindingProductionError, match="SELF_APPROVAL"
        ):
            producer._issue_binding(_args(), now=NOW)

    @pytest.mark.parametrize("permission", ("read", "triage", "none"))
    def test_insufficient_permission_is_refused(
        self, github: dict[str, Any], permission: str
    ) -> None:
        github["context"] = _context(reviewer_permission=permission)
        with pytest.raises(
            producer.ReviewBindingProductionError, match="INSUFFICIENT_PERMISSION"
        ):
            producer._issue_binding(_args(), now=NOW)

    def test_a_diverging_challenge_is_refused(self, github: dict[str, Any]) -> None:
        """Un challenge recopié depuis un autre HEAD ne peut pas être scellé."""
        github["verification"] = _verification(challenge=_challenge(head_sha="c" * 40))
        with pytest.raises(
            producer.ReviewBindingProductionError, match="CHALLENGE_MISMATCH"
        ):
            producer._issue_binding(_args(), now=NOW)

    def test_a_challenge_from_another_pull_request_is_refused(
        self, github: dict[str, Any]
    ) -> None:
        github["verification"] = _verification(challenge=_challenge(pull_request=96))
        with pytest.raises(
            producer.ReviewBindingProductionError, match="CHALLENGE_MISMATCH"
        ):
            producer._issue_binding(_args(), now=NOW)

    def test_an_unreadable_authorization_is_refused(
        self, github: dict[str, Any]
    ) -> None:
        github["blob_error"] = GitHubAuthorityError("404 for governance/…")
        with pytest.raises(
            producer.ReviewBindingProductionError, match="AUTHORIZATION_UNREADABLE"
        ):
            producer._issue_binding(_args(), now=NOW)

    def test_a_non_canonical_authorization_is_refused(
        self, github: dict[str, Any]
    ) -> None:
        github["blob"] = _blob(b'{"protocol_version":"LOT41A-V2"}\n')
        with pytest.raises(
            producer.ReviewBindingProductionError, match="AUTHORIZATION_NOT_CANONICAL"
        ):
            producer._issue_binding(_args(), now=NOW)

    def test_a_v1_authorization_is_refused(self, github: dict[str, Any]) -> None:
        """Le gate final se lie au contenu : une V1 sans allowlist ne peut
        rien prouver sur un objet précis du corpus."""
        from nexus_contracts.authority_artifacts import ScopeAuthorizationArtifactV1

        document = {
            "protocol_version": "LOT41A-V1",
            "authorization_id": AUTHORIZATION_ID,
            "decision": "AUTHORIZE_INGESTION_SCOPE",
            "scope": dict(SCOPE),
            "manifest_digest": "c" * 64,
            "profile_id": SCOPE["collection"],
            "profile_version": "v1",
            "profile_fingerprint": "d" * 64,
            "allowed_domains": ["eduscol.education.fr"],
            "rights_categories": ["officiel_public"],
            "exclusions": [],
            "pii_absence_attested": True,
            "pii_absence_evidence": "Corpus officiel.",
            "valid_from": "2026-01-01T00:00:00.000000Z",
            "valid_until": "2026-12-31T23:59:59.999999Z",
        }
        github["blob"] = _blob(
            ScopeAuthorizationArtifactV1.model_validate(document).canonical_bytes()
        )
        with pytest.raises(
            producer.ReviewBindingProductionError,
            match="AUTHORIZATION_PROTOCOL_UNSUPPORTED",
        ):
            producer._issue_binding(_args(), now=NOW)

    def test_an_authorization_naming_another_id_is_refused(
        self, github: dict[str, Any]
    ) -> None:
        github["blob"] = _blob(
            _authorization_bytes(authorization_id="another-authority-v1")
        )
        with pytest.raises(
            producer.ReviewBindingProductionError, match="AUTHORIZATION_ID_MISMATCH"
        ):
            producer._issue_binding(_args(), now=NOW)

    def test_a_blob_sha_that_does_not_hash_the_bytes_is_refused(
        self, github: dict[str, Any]
    ) -> None:
        """L'autorisation modifiée après la review : les octets relus ne
        hachent plus vers le blob annoncé."""
        raw = _authorization_bytes()
        github["blob"] = GitHubBlob(
            repository=REPOSITORY,
            path=canonical_authorization_path(AUTHORIZATION_ID),
            ref=HEAD_SHA,
            blob_sha="f" * 40,
            content=raw,
        )
        with pytest.raises(
            producer.ReviewBindingProductionError, match="AUTHORIZATION_BLOB_MISMATCH"
        ):
            producer._issue_binding(_args(), now=NOW)

    def test_an_unavailable_actor_context_is_refused(
        self, github: dict[str, Any]
    ) -> None:
        github["context_error"] = GitHubAuthorityError("permission endpoint 403")
        with pytest.raises(
            producer.ReviewBindingProductionError, match="ACTOR_CONTEXT_UNAVAILABLE"
        ):
            producer._issue_binding(_args(), now=NOW)


class TestSecretHandling:
    def test_a_missing_signing_key_fails_before_any_network_use(
        self, github: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(producer.SIGNING_KEY_ENV, raising=False)
        github["verify_error"] = AssertionError("must not reach GitHub")
        with pytest.raises(
            producer.ReviewBindingProductionError, match="is not configured"
        ):
            producer._issue_binding(_args(), now=NOW)

    def test_a_malformed_signing_key_never_appears_in_the_error(
        self, github: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(producer.SIGNING_KEY_ENV, "not-a-valid-seed-value")
        with pytest.raises(ReviewBindingError) as excinfo:
            producer._issue_binding(_args(), now=NOW)
        assert "not-a-valid-seed-value" not in str(excinfo.value)

    def test_the_cli_never_prints_the_private_key(
        self, github: dict[str, Any], capsys: Any
    ) -> None:
        assert producer.main(
            ["public-key", "--key-id", KEY_ID, "--environment", "test"]
        ) == 0
        captured = capsys.readouterr()
        assert TEST_SEED not in captured.out + captured.err
        assert public_key_hex(TEST_SEED) in captured.out

    def test_the_source_reads_the_key_from_the_environment_only(self) -> None:
        """Garde-fou de surface : aucune option ne doit jamais accepter la
        clé privée en argument, où elle apparaîtrait dans `ps` et les logs
        CI."""
        from pathlib import Path

        source = Path(producer.__file__).read_text(encoding="utf-8")
        for forbidden in ('"--signing-key"', '"--private-key"', '"--key"'):
            assert forbidden not in source, f"{forbidden} must never be accepted"


class TestBoundedValidity:
    @pytest.mark.parametrize("days", (0, -1, 366))
    def test_an_unbounded_validity_is_refused(
        self, github: dict[str, Any], days: int
    ) -> None:
        with pytest.raises(
            producer.ReviewBindingProductionError, match="validity-days"
        ):
            producer._issue_binding(_args(validity_days=days), now=NOW)

    def test_the_receipt_expires(self, github: dict[str, Any]) -> None:
        raw = producer._issue_binding(_args(validity_days=1), now=NOW)
        verify_review_binding(
            raw, trust_anchor=_trust_anchor(), environment="test", now=NOW
        )
        with pytest.raises(ReviewBindingError, match="expired"):
            verify_review_binding(
                raw,
                trust_anchor=_trust_anchor(),
                environment="test",
                now=datetime(2026, 8, 12, tzinfo=UTC),
            )
