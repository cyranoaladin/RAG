"""ADR-0035 — contrat du reçu de liaison de revue scellé.

Ce fichier prouve les propriétés du **contrat partagé** : canonicalisation
déterministe, digest, signature, ancre de confiance, séparation
production/test, et liaison à l'autorisation. Les vérifications en ligne
(GitHub) sont couvertes côté producteur ; le gate final hors ligne côté
`rag-pedago`.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from nexus_contracts.authority_artifacts import git_blob_sha1
from nexus_contracts.review_binding import (
    ACCEPTED_REVIEWER_PERMISSIONS,
    REVIEW_BINDING_PROTOCOL_VERSION,
    ReviewBindingError,
    ScopeAuthorizationReviewBindingV1,
    TrustAnchor,
    expected_challenge_digest,
    parse_signed_review_binding,
    parse_trust_anchor,
    public_key_hex,
    require_challenge_is_bound,
    require_matches_authorization,
    sign_review_binding,
    verify_review_binding,
)

#: Graine Ed25519 de test — **jamais** une clé de production. L'ancre qui la
#: déclare porte ``environment="test"``, et le contrat refuse d'exercer une
#: clé de test en mode production (cf. ``test_a_fixture_key_never_validates_
#: a_production_gate``).
TEST_SEED = "11" * 32
OTHER_SEED = "22" * 32

REPOSITORY = "cyranoaladin/RAG"
AUTHORIZATION_ID = "h2f-corpus-eduscol-v1"
AUTHORIZATION_BYTES = '{"decision":"AUTHORIZE_INGESTION_SCOPE"}\n'.encode()
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _binding_document(**overrides: Any) -> dict[str, Any]:
    import hashlib

    document: dict[str, Any] = {
        "protocol_version": REVIEW_BINDING_PROTOCOL_VERSION,
        "repository": REPOSITORY,
        "pull_request": 95,
        "base_ref": "main",
        "base_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "authorization_artifact_path": (
            f"governance/authorizations/{AUTHORIZATION_ID}.json"
        ),
        "authorization_artifact_sha256": hashlib.sha256(
            AUTHORIZATION_BYTES
        ).hexdigest(),
        "authorization_artifact_git_blob_sha1": git_blob_sha1(AUTHORIZATION_BYTES),
        "authorization_id": AUTHORIZATION_ID,
        "authorization_decision": "AUTHORIZE_INGESTION_SCOPE",
        "review_id": 777,
        "reviewer_login": "abenrhouma",
        "reviewer_permission": "admin",
        "author_login": "cyranoaladin",
        "submitted_at": "2026-08-09T10:00:00Z",
        "challenge_protocol": "NEXUS-TRUSTED-REVIEW-V1",
        "challenge_digest": expected_challenge_digest(
            repository=REPOSITORY,
            pull_request=95,
            base_ref="main",
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
            author="cyranoaladin",
            reviewer="abenrhouma",
        ),
        "verified_at": "2026-08-10T09:00:00Z",
        "verifier_version": "nexus-review-binding/1",
        "expires_at": "2026-09-09T09:00:00Z",
    }
    document.update(overrides)
    return document


def _binding(**overrides: Any) -> ScopeAuthorizationReviewBindingV1:
    return ScopeAuthorizationReviewBindingV1.model_validate(
        _binding_document(**overrides)
    )


def _trust_anchor(*, environment: str = "test", seed: str = TEST_SEED) -> TrustAnchor:
    return TrustAnchor.model_validate(
        {
            "protocol_version": REVIEW_BINDING_PROTOCOL_VERSION,
            "keys": [
                {
                    "key_id": "nexus-governance-test-1",
                    "algorithm": "ed25519",
                    "public_key": public_key_hex(seed),
                    "environment": environment,
                }
            ],
        }
    )


def _signed_bytes(**overrides: Any) -> bytes:
    return sign_review_binding(
        _binding(**overrides),
        private_key_hex=TEST_SEED,
        key_id="nexus-governance-test-1",
    ).canonical_bytes()


# ---------------------------------------------------------------------------
# Canonicalisation
# ---------------------------------------------------------------------------


class TestCanonicalization:
    def test_canonical_bytes_are_deterministic(self) -> None:
        assert _binding().canonical_bytes() == _binding().canonical_bytes()

    def test_field_order_of_the_input_never_changes_the_digest(self) -> None:
        """Le document d'entrée peut arriver dans n'importe quel ordre ; la
        forme canonique n'en dépend jamais."""
        forward = _binding_document()
        reversed_document = dict(reversed(list(forward.items())))
        assert ScopeAuthorizationReviewBindingV1.model_validate(
            forward
        ).digest() == ScopeAuthorizationReviewBindingV1.model_validate(
            reversed_document
        ).digest()

    def test_unicode_is_preserved_not_escaped(self) -> None:
        binding = _binding(verifier_version="nexus-vérificateur/1—é")
        raw = binding.canonical_bytes()
        assert "nexus-vérificateur/1—é" in raw.decode("utf-8")
        assert b"\\u" not in raw

    def test_timezones_are_normalized_to_utc(self) -> None:
        """Deux écritures du même instant produisent le même digest — sinon
        un fuseau serait un vecteur de divergence silencieuse."""
        utc = _binding(submitted_at="2026-08-09T10:00:00Z")
        offset = _binding(submitted_at="2026-08-09T12:00:00+02:00")
        assert utc.digest() == offset.digest()

    def test_non_canonical_receipt_bytes_are_refused(self) -> None:
        signed = sign_review_binding(
            _binding(), private_key_hex=TEST_SEED, key_id="nexus-governance-test-1"
        )
        reindented = json.dumps(signed.canonical_document(), indent=4).encode()
        with pytest.raises(ReviewBindingError, match="not in canonical form"):
            parse_signed_review_binding(reindented)

    def test_a_path_outside_governance_is_refused(self) -> None:
        with pytest.raises(Exception, match="governance/authorizations"):
            _binding(authorization_artifact_path="corpus/evil.json")

    def test_a_traversal_path_is_refused(self) -> None:
        with pytest.raises(Exception, match="repository path"):
            _binding(
                authorization_artifact_path="governance/authorizations/../../etc/x.json"
            )


# ---------------------------------------------------------------------------
# Signature et ancre de confiance
# ---------------------------------------------------------------------------


class TestSignature:
    def test_a_valid_receipt_verifies(self) -> None:
        binding = verify_review_binding(
            _signed_bytes(),
            trust_anchor=_trust_anchor(),
            environment="test",
            now=NOW,
        )
        assert binding.authorization_id == AUTHORIZATION_ID
        assert binding.reviewer_permission in ACCEPTED_REVIEWER_PERMISSIONS

    def test_a_tampered_payload_is_refused(self) -> None:
        """Le cœur du lot : modifier un fait après signature doit invalider
        la preuve. Le digest est recalculé, donc la falsification est
        détectée avant même la signature."""
        signed = sign_review_binding(
            _binding(), private_key_hex=TEST_SEED, key_id="nexus-governance-test-1"
        )
        document = signed.canonical_document()
        document["binding"]["reviewer_login"] = "cyranoaladin"
        raw = (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        with pytest.raises(ReviewBindingError, match="binding_digest does not describe"):
            verify_review_binding(
                raw, trust_anchor=_trust_anchor(), environment="test", now=NOW
            )

    def test_a_tampered_payload_with_recomputed_digest_still_fails_the_signature(
        self,
    ) -> None:
        """Recalculer le digest ne suffit pas : seule la clé privée peut
        produire une signature valide sur les nouveaux octets."""
        import hashlib

        forged = _binding(reviewer_login="cyranoaladin")
        signed = sign_review_binding(
            _binding(), private_key_hex=TEST_SEED, key_id="nexus-governance-test-1"
        )
        document = signed.canonical_document()
        document["binding"] = forged.canonical_document()
        document["binding_digest"] = hashlib.sha256(forged.canonical_bytes()).hexdigest()
        raw = (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        with pytest.raises(ReviewBindingError, match="signature does not verify"):
            verify_review_binding(
                raw, trust_anchor=_trust_anchor(), environment="test", now=NOW
            )

    def test_a_signature_from_another_key_is_refused(self) -> None:
        raw = sign_review_binding(
            _binding(), private_key_hex=OTHER_SEED, key_id="nexus-governance-test-1"
        ).canonical_bytes()
        with pytest.raises(ReviewBindingError, match="signature does not verify"):
            verify_review_binding(
                raw, trust_anchor=_trust_anchor(), environment="test", now=NOW
            )

    def test_an_unknown_key_id_is_refused(self) -> None:
        raw = sign_review_binding(
            _binding(), private_key_hex=TEST_SEED, key_id="rogue-signer"
        ).canonical_bytes()
        with pytest.raises(ReviewBindingError, match="not declared in the trust anchor"):
            verify_review_binding(
                raw, trust_anchor=_trust_anchor(), environment="test", now=NOW
            )

    def test_an_unknown_algorithm_is_refused(self) -> None:
        signed = sign_review_binding(
            _binding(), private_key_hex=TEST_SEED, key_id="nexus-governance-test-1"
        )
        document = signed.canonical_document()
        document["signature_algorithm"] = "rsa-pkcs1"
        raw = (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        with pytest.raises(ReviewBindingError, match="failed strict validation"):
            verify_review_binding(
                raw, trust_anchor=_trust_anchor(), environment="test", now=NOW
            )

    def test_an_unsigned_caller_authored_json_is_refused(self) -> None:
        """Un JSON écrit à la main, sans signature, ne doit jamais passer —
        c'est exactement l'attaque que ce lot ferme."""
        raw = (json.dumps(_binding_document(), indent=2, sort_keys=True) + "\n").encode()
        with pytest.raises(ReviewBindingError, match="failed strict validation"):
            verify_review_binding(
                raw, trust_anchor=_trust_anchor(), environment="test", now=NOW
            )

    def test_a_fixture_key_never_validates_a_production_gate(self) -> None:
        """La barrière la plus importante du lot : la clé de test de ce
        fichier ne peut jamais rendre un gate de production vert."""
        raw = _signed_bytes()
        with pytest.raises(
            ReviewBindingError, match="declared for the 'test' environment"
        ):
            verify_review_binding(
                raw,
                trust_anchor=_trust_anchor(environment="test"),
                environment="production",
                now=NOW,
            )

    def test_a_production_key_is_never_exercised_by_a_rehearsal(self) -> None:
        raw = _signed_bytes()
        with pytest.raises(
            ReviewBindingError, match="declared for the 'production' environment"
        ):
            verify_review_binding(
                raw,
                trust_anchor=_trust_anchor(environment="production"),
                environment="test",
                now=NOW,
            )

    def test_a_malformed_signing_key_never_leaks_its_value(self) -> None:
        with pytest.raises(ReviewBindingError) as excinfo:
            sign_review_binding(
                _binding(), private_key_hex="deadbeef", key_id="nexus-governance-test-1"
            )
        assert "deadbeef" not in str(excinfo.value)


class TestTrustAnchorParsing:
    def test_governed_production_anchor_declares_only_the_rotated_key(self) -> None:
        repository_root = Path(__file__).resolve().parents[3]
        anchor = parse_trust_anchor(
            (
                repository_root
                / "governance/trust-anchors/review-binding-v1.json"
            ).read_bytes()
        )

        assert anchor.protocol_version == REVIEW_BINDING_PROTOCOL_VERSION
        assert len(anchor.keys) == 1
        key = anchor.keys[0]
        assert key.key_id == "review-binding-v1-2026-08-25"
        assert key.algorithm == "ed25519"
        assert key.environment == "production"
        assert (
            key.public_key
            == "1f34648789fe7ebdfde6c64197039c0ffa0cd36b98317ce7cad4836a26a058d8"
        )
        with pytest.raises(ReviewBindingError, match="not declared"):
            anchor.key("review-binding-v1-2026-08-13", environment="production")

    def test_duplicate_key_ids_are_refused(self) -> None:
        key = {
            "key_id": "dup",
            "algorithm": "ed25519",
            "public_key": public_key_hex(TEST_SEED),
            "environment": "test",
        }
        raw = json.dumps(
            {"protocol_version": REVIEW_BINDING_PROTOCOL_VERSION, "keys": [key, key]}
        ).encode()
        with pytest.raises(ReviewBindingError, match="must be unique"):
            parse_trust_anchor(raw)

    def test_an_empty_trust_anchor_is_refused(self) -> None:
        raw = json.dumps(
            {"protocol_version": REVIEW_BINDING_PROTOCOL_VERSION, "keys": []}
        ).encode()
        with pytest.raises(ReviewBindingError, match="failed strict validation"):
            parse_trust_anchor(raw)

    def test_malformed_json_is_refused(self) -> None:
        with pytest.raises(ReviewBindingError, match="not valid UTF-8 JSON"):
            parse_trust_anchor(b"{not json")


# ---------------------------------------------------------------------------
# Fenêtre temporelle
# ---------------------------------------------------------------------------


class TestValidityWindow:
    def test_an_expired_receipt_is_refused(self) -> None:
        with pytest.raises(ReviewBindingError, match="expired"):
            verify_review_binding(
                _signed_bytes(),
                trust_anchor=_trust_anchor(),
                environment="test",
                now=NOW + timedelta(days=365),
            )

    def test_a_receipt_verified_in_the_future_is_refused(self) -> None:
        with pytest.raises(ReviewBindingError, match="in the future"):
            verify_review_binding(
                _signed_bytes(),
                trust_anchor=_trust_anchor(),
                environment="test",
                now=datetime(2026, 1, 1, tzinfo=UTC),
            )

    def test_a_naive_now_is_refused(self) -> None:
        with pytest.raises(ReviewBindingError, match="timezone-aware"):
            verify_review_binding(
                _signed_bytes(),
                trust_anchor=_trust_anchor(),
                environment="test",
                now=datetime(2026, 8, 10, 12, 0),  # noqa: DTZ001 - volontairement naïf
            )


# ---------------------------------------------------------------------------
# Liaison à l'autorisation
# ---------------------------------------------------------------------------


def _require(**overrides: Any) -> None:
    kwargs: dict[str, Any] = {
        "authorization_id": AUTHORIZATION_ID,
        "authorization_bytes": AUTHORIZATION_BYTES,
        "authorization_git_blob_sha1": git_blob_sha1(AUTHORIZATION_BYTES),
        "expected_repository": REPOSITORY,
    }
    binding = overrides.pop("binding", _binding())
    kwargs.update(overrides)
    require_matches_authorization(binding, **kwargs)


class TestAuthorizationBinding:
    def test_the_nominal_binding_matches(self) -> None:
        _require()

    def test_another_repository_is_refused(self) -> None:
        with pytest.raises(ReviewBindingError, match="another repository"):
            _require(binding=_binding(repository="attacker/RAG"))

    def test_another_authorization_id_is_refused(self) -> None:
        with pytest.raises(ReviewBindingError, match="covers authorization"):
            _require(binding=_binding(
                authorization_id="other-authority-v1",
                authorization_artifact_path=(
                    "governance/authorizations/other-authority-v1.json"
                ),
            ))

    def test_a_path_that_is_not_the_canonical_one_is_refused(self) -> None:
        """Le chemin est dérivé de l'identifiant : un producteur ne peut
        jamais faire pointer un reçu vers un autre fichier."""
        with pytest.raises(ReviewBindingError, match="canonical path"):
            _require(binding=_binding(
                authorization_artifact_path="governance/authorizations/decoy.json"
            ))

    def test_other_authorization_bytes_are_refused(self) -> None:
        with pytest.raises(ReviewBindingError, match="different authorization bytes"):
            _require(authorization_bytes=b'{"decision":"OTHER"}\n')

    def test_another_git_blob_sha1_is_refused(self) -> None:
        """Deux identités indépendantes des mêmes octets : falsifier l'une
        sans l'autre est détecté."""
        with pytest.raises(ReviewBindingError, match="Git blob SHA-1"):
            _require(authorization_git_blob_sha1="f" * 40)

    def test_reviewer_equal_to_author_is_refused(self) -> None:
        binding = _binding(
            author_login="abenrhouma",
            challenge_digest=expected_challenge_digest(
                repository=REPOSITORY,
                pull_request=95,
                base_ref="main",
                base_sha=BASE_SHA,
                head_sha=HEAD_SHA,
                author="abenrhouma",
                reviewer="abenrhouma",
            ),
        )
        with pytest.raises(ReviewBindingError, match="self-approval"):
            _require(binding=binding)

    def test_an_untrusted_reviewer_is_refused(self) -> None:
        with pytest.raises(ReviewBindingError, match="not among the trusted"):
            _require(
                binding=_binding(reviewer_login="stranger"),
                accepted_reviewers=("abenrhouma",),
            )

    def test_an_insufficient_permission_is_unrepresentable(self) -> None:
        """``read``/``triage`` ne peuvent pas exister dans un reçu : le
        contrat les rend irreprésentables plutôt que de les refuser après
        coup."""
        with pytest.raises(Exception, match="reviewer_permission"):
            _binding(reviewer_permission="read")


class TestChallengeBinding:
    def test_the_nominal_challenge_is_bound(self) -> None:
        require_challenge_is_bound(_binding())

    def test_a_challenge_recycled_from_another_head_is_refused(self) -> None:
        """Un challenge d'ADR-0025 dérive du HEAD : le recopier sur un autre
        HEAD est détecté par recalcul."""
        recycled = expected_challenge_digest(
            repository=REPOSITORY,
            pull_request=95,
            base_ref="main",
            base_sha=BASE_SHA,
            head_sha="c" * 40,
            author="cyranoaladin",
            reviewer="abenrhouma",
        )
        with pytest.raises(ReviewBindingError, match="challenge recycled"):
            require_challenge_is_bound(_binding(challenge_digest=recycled))

    def test_a_challenge_recycled_from_another_pull_request_is_refused(self) -> None:
        recycled = expected_challenge_digest(
            repository=REPOSITORY,
            pull_request=96,
            base_ref="main",
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
            author="cyranoaladin",
            reviewer="abenrhouma",
        )
        with pytest.raises(ReviewBindingError, match="challenge recycled"):
            require_challenge_is_bound(_binding(challenge_digest=recycled))

    def test_the_digest_matches_the_adr_0025_implementation(self) -> None:
        """Garde-fou anti-divergence : ``packages/contracts`` ne peut pas
        importer ``scripts/``, donc les deux implémentations du challenge
        sont comparées ici plutôt que supposées égales."""
        import importlib.util
        import sys
        from pathlib import Path

        module_path = (
            Path(__file__).resolve().parents[3]
            / "scripts"
            / "github"
            / "trusted_human_review.py"
        )
        spec = importlib.util.spec_from_file_location("trusted_human_review", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        # Enregistré avant exécution : ``@dataclass`` résout son module par
        # ``sys.modules``, et échoue sur un module chargé hors registre.
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(spec.name, None)

        payload = {
            "repository": REPOSITORY,
            "pull_request": 95,
            "base_ref": "main",
            "base_sha": BASE_SHA,
            "head_sha": HEAD_SHA,
            "author": "cyranoaladin",
            "reviewer": "abenrhouma",
            "protocol": "NEXUS-TRUSTED-REVIEW-V1",
        }
        assert module.build_challenge(payload) == (
            "NEXUS-TRUSTED-REVIEW-V1:"
            + expected_challenge_digest(
                repository=REPOSITORY,
                pull_request=95,
                base_ref="main",
                base_sha=BASE_SHA,
                head_sha=HEAD_SHA,
                author="cyranoaladin",
                reviewer="abenrhouma",
            )
        )


def test_public_key_hex_refuses_a_malformed_seed_without_quoting_it() -> None:
    """Un secret mal formé reste un secret, et le refus reste typé.

    Sans cette barrière, ``bytes.fromhex`` remontait une ``ValueError`` brute —
    un type que les appelants du producteur ne rattrapent pas, sur le chemin
    qui manipule précisément la clé de signature.
    """
    for malformed in ("not-a-valid-seed-value", "AB" * 32, "ab" * 31, "", "  "):
        with pytest.raises(ReviewBindingError) as failure:
            public_key_hex(malformed)
        if malformed.strip():
            assert malformed.strip() not in str(failure.value)
        assert "64 lowercase hexadecimal" in str(failure.value)


def test_public_key_hex_still_accepts_a_canonical_seed() -> None:
    seed = "33" * 32
    derived = public_key_hex(seed)
    assert len(derived) == 64
    assert derived == derived.lower()
    assert public_key_hex(f"  {seed}  ") == derived


# ═══════════════════════════════════════════════════════════════════════
# P0-L1B — modèle de sûreté du chemin de consommation
#
# Une clé courante valide ne suffit jamais : le reçu doit encore porter sur
# les octets consommés ET sur le HEAD attendu.
# ═══════════════════════════════════════════════════════════════════════


def test_a_recycled_challenge_is_refused_even_with_a_valid_signature() -> None:
    """Un challenge emprunté à une autre revue ne lie rien.

    `challenge_digest` est recalculé depuis les sept dimensions que le reçu
    nomme lui-même, `head_sha` compris : un reçu qui déclare un HEAD tout en
    portant le challenge d'un autre est structurellement incohérent.
    """
    binding = _binding()
    forged = binding.model_copy(update={"head_sha": "d" * 40})

    with pytest.raises(ReviewBindingError) as failure:
        require_challenge_is_bound(forged)
    assert "challenge recycled from another review binds nothing" in str(failure.value)


def test_a_stale_head_is_refused_when_the_consumer_pins_the_expected_head() -> None:
    """Reçu authentique, signature valide, octets identiques — mais vieux HEAD.

    Sans épinglage, ce cas est accepté : la revue porte sur des octets, et ces
    octets n'ont pas bougé. C'est défendable, mais ce n'est pas fail-closed pour
    un consommateur qui sait de quel HEAD il publie. `expected_head_sha` rend
    ce refus disponible et vérifiable.
    """
    binding = _binding()
    raw = AUTHORIZATION_BYTES

    require_matches_authorization(
        binding,
        authorization_id=binding.authorization_id,
        authorization_bytes=raw,
        authorization_git_blob_sha1=git_blob_sha1(raw),
        expected_repository=binding.repository,
        expected_head_sha=binding.head_sha,
    )

    with pytest.raises(ReviewBindingError) as failure:
        require_matches_authorization(
            binding,
            authorization_id=binding.authorization_id,
            authorization_bytes=raw,
            authorization_git_blob_sha1=git_blob_sha1(raw),
            expected_repository=binding.repository,
            expected_head_sha="e" * 40,
        )
    assert "was reviewed at head" in str(failure.value)


def test_changed_authorization_bytes_are_refused_whatever_the_head() -> None:
    """L'autre jambe : la revue est liée aux octets, pas seulement au commit."""
    binding = _binding()
    mutated = b'{"decision":"AUTHORIZE_INGESTION_SCOPE","v":2}\n'

    with pytest.raises(ReviewBindingError) as failure:
        require_matches_authorization(
            binding,
            authorization_id=binding.authorization_id,
            authorization_bytes=mutated,
            authorization_git_blob_sha1=git_blob_sha1(mutated),
            expected_repository=binding.repository,
            expected_head_sha=binding.head_sha,
        )
    assert "different authorization bytes" in str(failure.value)
