"""Décisions humaines de revue PII, par contenu (NEXUS-PII-REVIEW-DECISIONS-V1).

Ce que le contrat protège : aucune détection PII n'est admissible sans une
décision humaine INDIVIDUELLE, liée au SHA exact du contenu, à la politique, au
scanner, au foyer de pages et au paquet de revue figé qui l'a fondée. Une
décision ne peut jamais être dérivée du nombre de faux positifs supposés, ni
porter de matière personnelle brute.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256

import pytest

from nexus_contracts import (
    PII_REVIEW_DECISIONS_DIR,
    PII_REVIEW_DECISIONS_PROTOCOL_VERSION,
    PiiReviewDecisionSetV1,
    PiiReviewDecisionV1,
    canonical_pii_review_decisions_path,
    parse_pii_review_decision_set,
)
from nexus_contracts.authority_artifacts import CanonicalArtifactError
from nexus_contracts.authority_artifacts import git_blob_sha1
from nexus_contracts.review_binding import (
    ReviewBindingError,
    ScopeAuthorizationReviewBindingV1,
    TrustAnchor,
    expected_challenge_digest,
    public_key_hex,
    require_matches_pii_review_decision_set,
    sign_review_binding,
    verify_pii_review_decision_authority,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
POLICY = "1" * 64
SCANNER = "2" * 64
PAGE_POLICY = "3" * 64
BUNDLE_A = "4" * 64
BUNDLE_B = "5" * 64
INDEX = "6" * 64
MANIFEST = "7" * 64
MOMENT = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)

FINDING_A = "f1" * 32
FINDING_B = "f2" * 32


def _finding(finding_id: str = FINDING_A, page: int = 3, **overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "finding_id": finding_id,
        "pattern_id": "phone_french",
        "page": page,
        "match_sha256": "a1" * 32,
        "context_sha256": "b1" * 32,
        "disposition": "PUBLIC_INSTITUTIONAL_DATA",
    }
    document.update(overrides)
    return document


def _decision_with_findings(**overrides: object) -> dict[str, object]:
    document = _decision(findings=[_finding(FINDING_A, 3), _finding(FINDING_B, 7)])
    document.update(overrides)
    return document




def _decision(sha: str = SHA_A, bundle: str = BUNDLE_A, **overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "content_sha256": sha,
        "policy_id": "pii_gate_policy_h2b_v5",
        "policy_sha256": POLICY,
        "scanner_sha256": SCANNER,
        "page_policy_id": "NEXUS-PDF-PAGE-POLICY-V1",
        "page_policy_sha256": PAGE_POLICY,
        "review_bundle_sha256": bundle,
        "signal_classes": ["phone_french"],
        "signal_count": 2,
        "pages": [3, 7],
        "findings": [
            {"finding_id": "f1" * 32, "pattern_id": "phone_french", "page": 3,
             "match_sha256": "a1" * 32, "context_sha256": "b1" * 32,
             "disposition": "PUBLIC_INSTITUTIONAL_DATA"},
            {"finding_id": "f2" * 32, "pattern_id": "phone_french", "page": 7,
             "match_sha256": "a2" * 32, "context_sha256": "b2" * 32,
             "disposition": "PUBLIC_INSTITUTIONAL_DATA"},
        ],
        "decision": "APPROVED",
        "justification": {
            "category": "INSTITUTIONAL_CONTACT",
            "statement": "Numéro de standard d'un rectorat en en-tête de document officiel.",
            "raw_pii_quoted": False,
        },
        "reviewer_login": "abenrhouma",
        "decided_at": MOMENT.isoformat(),
    }
    document.update(overrides)
    return document


def _set(*decisions: dict[str, object], **overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "protocol_version": PII_REVIEW_DECISIONS_PROTOCOL_VERSION,
        "decision_set_id": "pii-review-2026-09-02-lot-1-2",
        "corpus_manifest_sha256": MANIFEST,
        "policy_id": "pii_gate_policy_h2b_v5",
        "policy_sha256": POLICY,
        "scanner_sha256": SCANNER,
        "page_policy_id": "NEXUS-PDF-PAGE-POLICY-V1",
        "page_policy_sha256": PAGE_POLICY,
        "review_index_sha256": INDEX,
        "decisions": list(decisions) or [_decision()],
    }
    document.update(overrides)
    return document


class TestDecision:
    def test_a_complete_individual_decision_is_accepted(self) -> None:
        decision = PiiReviewDecisionV1.model_validate(_decision())
        assert decision.decision == "APPROVED"
        assert decision.signal_classes == ("phone_french",)
        assert decision.pages == (3, 7)

    @pytest.mark.parametrize(
        "mutation",
        [
            {"content_sha256": "A" * 64},
            {"review_bundle_sha256": "not-a-sha"},
            {"signal_classes": []},
            {"signal_classes": ["phone_french", "phone_french"]},
            {"signal_classes": ["phone_french", "email_address"]},
            {"signal_count": 0},
            {"signal_count": True},
            {"pages": []},
            {"pages": [7, 3]},
            {"pages": [3, 3]},
            {"pages": [0]},
            {"decision": "DETECTED_RECORDED"},
            {"decision": "approved"},
            {"reviewer_login": ""},
            {"decided_at": "2026-09-03T10:00:00"},
            {"extra": 1},
        ],
    )
    def test_a_malformed_decision_is_refused(self, mutation: dict[str, object]) -> None:
        with pytest.raises(ValueError):
            PiiReviewDecisionV1.model_validate(_decision(**mutation))

    def test_an_approval_cannot_admit_personal_data(self) -> None:
        justification = {
            "category": "PERSONAL_DATA_PRESENT",
            "statement": "Adresse personnelle d'un particulier identifiable, page 3.",
            "raw_pii_quoted": False,
        }
        with pytest.raises(ValueError, match="PERSONAL_DATA_PRESENT"):
            PiiReviewDecisionV1.model_validate(_decision(justification=justification))
        personal = [_finding(FINDING_A, 3), _finding(FINDING_B, 7, disposition="PERSONAL_DATA_PRESENT")]
        rejected = PiiReviewDecisionV1.model_validate(
            _decision(decision="REJECTED", justification=justification, findings=personal)
        )
        assert rejected.decision == "REJECTED"

    def test_a_justification_never_quotes_raw_material(self) -> None:
        justification = {
            "category": "INSTITUTIONAL_CONTACT",
            "statement": "Le numéro 01 23 45 67 89 est celui du standard.",
            "raw_pii_quoted": True,
        }
        with pytest.raises(ValueError, match="raw_pii_quoted"):
            PiiReviewDecisionV1.model_validate(_decision(justification=justification))

    def test_a_statement_must_carry_a_reason(self) -> None:
        justification = {"category": "PEDAGOGICAL_EXAMPLE", "statement": "ok", "raw_pii_quoted": False}
        with pytest.raises(ValueError):
            PiiReviewDecisionV1.model_validate(_decision(justification=justification))


class TestDecisionSet:
    def test_a_set_binds_every_decision_to_the_same_instruments(self) -> None:
        decision_set = PiiReviewDecisionSetV1.model_validate(
            _set(_decision(SHA_A, BUNDLE_A), _decision(SHA_B, BUNDLE_B, decision="REJECTED",
                 findings=[_finding(FINDING_A, 3), _finding(FINDING_B, 7, disposition="PERSONAL_DATA_PRESENT")],
                 justification={"category": "PERSONAL_DATA_PRESENT",
                                "statement": "Coordonnées d'un particulier identifiable en page 3.",
                                "raw_pii_quoted": False}))
        )
        assert decision_set.approved_content_sha256 == frozenset({SHA_A})
        assert decision_set.decision_for(SHA_B).decision == "REJECTED"
        assert decision_set.decision_for("c" * 64) is None

    @pytest.mark.parametrize(
        ("mutation", "message"),
        [
            ({"protocol_version": "NEXUS-PII-REVIEW-DECISIONS-V0"}, "protocol_version"),
            ({"decision_set_id": "Pii Review"}, "decision_set_id"),
            ({"decisions": []}, "decisions"),
            ({"decisions": [_decision(SHA_A), _decision(SHA_A, BUNDLE_B)]}, "twice"),
            ({"decisions": [_decision(SHA_B), _decision(SHA_A)]}, "sorted"),
            ({"decisions": [_decision(policy_sha256="9" * 64)]}, "policy"),
            ({"decisions": [_decision(scanner_sha256="9" * 64)]}, "scanner"),
            ({"decisions": [_decision(page_policy_sha256="9" * 64)]}, "page policy"),
            ({"decisions": [_decision(BUNDLE_A, BUNDLE_A), _decision(SHA_B, BUNDLE_A)]}, "bundle"),
        ],
    )
    def test_an_incoherent_set_is_refused(self, mutation: dict[str, object], message: str) -> None:
        with pytest.raises(ValueError, match=message):
            PiiReviewDecisionSetV1.model_validate(_set(**mutation))

    def test_the_canonical_form_is_the_only_parsable_form(self) -> None:
        decision_set = PiiReviewDecisionSetV1.model_validate(_set())
        raw = decision_set.canonical_bytes()
        assert parse_pii_review_decision_set(raw).digest() == decision_set.digest()
        assert decision_set.digest() == sha256(raw).hexdigest()
        with pytest.raises(CanonicalArtifactError, match="canonical"):
            parse_pii_review_decision_set(json.dumps(_set()).encode("utf-8"))
        with pytest.raises(CanonicalArtifactError):
            parse_pii_review_decision_set(b"{")

    def test_the_canonical_path_derives_from_the_identifier_only(self) -> None:
        assert canonical_pii_review_decisions_path("pii-review-2026-09-02-lot-1-2") == (
            f"{PII_REVIEW_DECISIONS_DIR}/pii-review-2026-09-02-lot-1-2.json"
        )
        with pytest.raises(ValueError):
            canonical_pii_review_decisions_path("../evil")


class TestReviewBindingCoversDecisionSets:
    """Le reçu ADR-0035 peut couvrir un ensemble de décisions PII, sous une
    décision de revue explicite et un chemin canonique dédié."""

    def _binding(self, raw: bytes, **overrides: object) -> ScopeAuthorizationReviewBindingV1:
        document: dict[str, object] = {
            "protocol_version": "NEXUS-REVIEW-BINDING-V1",
            "repository": "cyranoaladin/RAG",
            "pull_request": 200,
            "base_ref": "main",
            "base_sha": "1" * 40,
            "head_sha": "2" * 40,
            "authorization_artifact_path": canonical_pii_review_decisions_path(
                "pii-review-2026-09-02-lot-1-2"
            ),
            "authorization_artifact_sha256": sha256(raw).hexdigest(),
            "authorization_artifact_git_blob_sha1": "3" * 40,
            "authorization_id": "pii-review-2026-09-02-lot-1-2",
            "authorization_decision": "APPROVE_PII_REVIEW_DECISIONS",
            "review_id": 42,
            "reviewer_login": "abenrhouma",
            "reviewer_permission": "write",
            "author_login": "cyranoaladin",
            "submitted_at": MOMENT.isoformat(),
            "challenge_protocol": "NEXUS-TRUSTED-REVIEW-V1",
            "challenge_digest": "8" * 64,
            "verified_at": MOMENT.isoformat(),
            "verifier_version": "nexus-review-binding-producer/1",
            "expires_at": datetime(2026, 10, 3, tzinfo=UTC).isoformat(),
        }
        document.update(overrides)
        return ScopeAuthorizationReviewBindingV1.model_validate(document)

    def test_a_receipt_bound_to_the_exact_decision_set_is_accepted(self) -> None:
        raw = PiiReviewDecisionSetV1.model_validate(_set()).canonical_bytes()
        binding = self._binding(raw)
        require_matches_pii_review_decision_set(
            binding,
            decision_set_id="pii-review-2026-09-02-lot-1-2",
            decision_set_bytes=raw,
            decision_set_git_blob_sha1="3" * 40,
            expected_repository="cyranoaladin/RAG",
            accepted_reviewers=("abenrhouma",),
        )

    def test_a_scope_receipt_cannot_cover_a_decision_set(self) -> None:
        raw = PiiReviewDecisionSetV1.model_validate(_set()).canonical_bytes()
        with pytest.raises(ValueError, match="governance/authorizations"):
            self._binding(raw, authorization_decision="AUTHORIZE_INGESTION_SCOPE")

    def test_a_decision_receipt_cannot_point_outside_its_directory(self) -> None:
        raw = PiiReviewDecisionSetV1.model_validate(_set()).canonical_bytes()
        with pytest.raises(ValueError, match="pii-review-decisions"):
            self._binding(raw, authorization_artifact_path="governance/authorizations/x.json")

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"authorization_artifact_sha256": "9" * 64}, "different decision set bytes"),
            ({"authorization_id": "pii-review-other"}, "covers decision set"),
            ({"repository": "cyranoaladin/other"}, "repository"),
            ({"reviewer_login": "cyranoaladin"}, "self-approval"),
            ({"reviewer_login": "someone"}, "trusted reviewers"),
            ({"authorization_artifact_git_blob_sha1": "9" * 40}, "blob"),
        ],
    )
    def test_a_receipt_for_something_else_is_refused(
        self, overrides: dict[str, object], message: str
    ) -> None:
        raw = PiiReviewDecisionSetV1.model_validate(_set()).canonical_bytes()
        binding = self._binding(raw, **overrides)
        with pytest.raises(ReviewBindingError, match=message):
            require_matches_pii_review_decision_set(
                binding,
                decision_set_id="pii-review-2026-09-02-lot-1-2",
                decision_set_bytes=raw,
                decision_set_git_blob_sha1="3" * 40,
                expected_repository="cyranoaladin/RAG",
                accepted_reviewers=("abenrhouma",),
            )



class TestFindingDispositions:
    """Chaque finding porte une identité et une disposition ; la décision
    documentaire APPROVED n'est possible que si toutes sont admissibles (§8)."""

    def test_every_finding_is_dispositioned_individually(self) -> None:
        decision = PiiReviewDecisionV1.model_validate(_decision_with_findings())
        assert [f.finding_id for f in decision.findings] == [FINDING_A, FINDING_B]
        assert decision.findings[0].disposition == "PUBLIC_INSTITUTIONAL_DATA"

    @pytest.mark.parametrize(
        ("findings", "message"),
        [
            ([], "findings"),
            ([_finding(FINDING_A), _finding(FINDING_A, 7)], "finding_id"),
            ([_finding(FINDING_B, 7), _finding(FINDING_A, 3)], "sorted"),
            ([_finding(FINDING_A, 3)], "signal_count"),
            ([_finding(FINDING_A, 3), _finding(FINDING_B, 9)], "pages"),
            ([_finding(FINDING_A, 3, pattern_id="email_address"), _finding(FINDING_B, 7)], "signal_classes"),
            ([_finding(FINDING_A, 3, disposition="LOOKS_FINE"), _finding(FINDING_B, 7)], "disposition"),
        ],
    )
    def test_findings_must_match_the_measured_signals(self, findings, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            PiiReviewDecisionV1.model_validate(_decision(findings=findings))

    def test_an_approval_requires_every_finding_to_be_admissible(self) -> None:
        findings = [_finding(FINDING_A, 3), _finding(FINDING_B, 7, disposition="PERSONAL_DATA_PRESENT")]
        with pytest.raises(ValueError, match="PERSONAL_DATA_PRESENT"):
            PiiReviewDecisionV1.model_validate(_decision(findings=findings))
        rejected = PiiReviewDecisionV1.model_validate(
            _decision(
                findings=findings,
                decision="REJECTED",
                justification={
                    "category": "PERSONAL_DATA_PRESENT",
                    "statement": "Coordonnées d'un particulier identifiable en page 7.",
                    "raw_pii_quoted": False,
                },
            )
        )
        assert rejected.decision == "REJECTED"

    def test_a_rejection_must_name_at_least_one_personal_finding(self) -> None:
        with pytest.raises(ValueError, match="REJECTED"):
            PiiReviewDecisionV1.model_validate(
                _decision_with_findings(
                    decision="REJECTED",
                    justification={
                        "category": "PERSONAL_DATA_PRESENT",
                        "statement": "Coordonnées d'un particulier identifiable en page 7.",
                        "raw_pii_quoted": False,
                    },
                )
            )

    def test_the_admissible_vocabulary_is_closed(self) -> None:
        from nexus_contracts.pii_review_decisions import ADMISSIBLE_DISPOSITIONS, FINDING_DISPOSITIONS

        assert set(FINDING_DISPOSITIONS) == {
            "FALSE_POSITIVE_TECHNICAL",
            "PUBLIC_INSTITUTIONAL_DATA",
            "SYNTHETIC_EXAMPLE",
            "PERSONAL_DATA_PRESENT",
        }
        assert set(ADMISSIBLE_DISPOSITIONS) == set(FINDING_DISPOSITIONS) - {"PERSONAL_DATA_PRESENT"}


# ─────────────────────────────────────────────────────────────────────────
# Autorité composite : décisions + reçu, vérifiées ensemble (ADR-0047/0035)
# ─────────────────────────────────────────────────────────────────────────

AUTHORITY_SET_ID = "pii-review-2026-09-02-lot-1-2"
SIGNING_SEED = "33" * 32
SIGNING_KEY_ID = "review-binding-contract-test-key"


def _authority_anchor() -> TrustAnchor:
    return TrustAnchor.model_validate(
        {
            "protocol_version": "NEXUS-REVIEW-BINDING-V1",
            "keys": [
                {
                    "algorithm": "ed25519",
                    "key_id": SIGNING_KEY_ID,
                    "public_key": public_key_hex(SIGNING_SEED),
                    "environment": "test",
                    "comment": "Ephemeral contract-test key, never a production anchor.",
                }
            ],
        }
    )


def _authority_receipt_bytes(raw: bytes, *, reviewer: str = "abenrhouma") -> bytes:
    pull_request, base_sha, head_sha, author = 200, "1" * 40, "2" * 40, "cyranoaladin"
    binding = ScopeAuthorizationReviewBindingV1.model_validate(
        {
            "protocol_version": "NEXUS-REVIEW-BINDING-V1",
            "repository": "cyranoaladin/RAG",
            "pull_request": pull_request,
            "base_ref": "main",
            "base_sha": base_sha,
            "head_sha": head_sha,
            "authorization_artifact_path": canonical_pii_review_decisions_path(
                AUTHORITY_SET_ID
            ),
            "authorization_artifact_sha256": sha256(raw).hexdigest(),
            "authorization_artifact_git_blob_sha1": git_blob_sha1(raw),
            "authorization_id": AUTHORITY_SET_ID,
            "authorization_decision": "APPROVE_PII_REVIEW_DECISIONS",
            "review_id": 42,
            "reviewer_login": reviewer,
            "reviewer_permission": "write",
            "author_login": author,
            "submitted_at": MOMENT.isoformat(),
            "challenge_protocol": "NEXUS-TRUSTED-REVIEW-V1",
            "challenge_digest": expected_challenge_digest(
                repository="cyranoaladin/RAG",
                pull_request=pull_request,
                base_ref="main",
                base_sha=base_sha,
                head_sha=head_sha,
                author=author,
                reviewer=reviewer,
            ),
            "verified_at": MOMENT.isoformat(),
            "verifier_version": "nexus-review-binding-producer/1",
            "expires_at": datetime(2026, 10, 3, tzinfo=UTC).isoformat(),
        }
    )
    return sign_review_binding(
        binding, private_key_hex=SIGNING_SEED, key_id=SIGNING_KEY_ID
    ).canonical_bytes()


class TestVerifyPiiReviewDecisionAuthority:
    """Deux services consomment cette chaîne — le worker et le producteur.

    Si chacun compose `verify_review_binding` et
    `require_matches_pii_review_decision_set` de son côté, les deux ordres de
    vérification divergeront un jour, et l'un acceptera ce que l'autre refuse.
    La composition vit donc ici, en un seul endroit, et sans E/S."""

    def _authority(self, **overrides: object):
        raw = PiiReviewDecisionSetV1.model_validate(_set()).canonical_bytes()
        kwargs: dict[str, object] = {
            "decision_set_bytes": raw,
            "receipt_bytes": _authority_receipt_bytes(raw),
            "trust_anchor": _authority_anchor(),
            "environment": "test",
            "expected_repository": "cyranoaladin/RAG",
            "accepted_reviewers": ("abenrhouma",),
            "now": MOMENT,
        }
        kwargs.update(overrides)
        return verify_pii_review_decision_authority(**kwargs)  # type: ignore[arg-type]

    def test_a_matching_pair_is_accepted(self) -> None:
        decision_set, binding = self._authority()
        assert decision_set.decision_set_id == AUTHORITY_SET_ID
        assert binding.authorization_id == AUTHORITY_SET_ID
        assert binding.authorization_decision == "APPROVE_PII_REVIEW_DECISIONS"

    def test_non_canonical_decision_set_bytes_are_refused(self) -> None:
        raw = PiiReviewDecisionSetV1.model_validate(_set()).canonical_bytes()
        with pytest.raises((ReviewBindingError, CanonicalArtifactError)):
            self._authority(decision_set_bytes=b" " + raw)

    def test_a_receipt_issued_for_other_bytes_is_refused(self) -> None:
        other = PiiReviewDecisionSetV1.model_validate(
            _set(_decision(sha=SHA_B, bundle=BUNDLE_B))
        ).canonical_bytes()
        with pytest.raises(ReviewBindingError):
            self._authority(receipt_bytes=_authority_receipt_bytes(other))

    def test_an_unlisted_reviewer_is_refused(self) -> None:
        with pytest.raises(ReviewBindingError):
            self._authority(accepted_reviewers=("quelquun-dautre",))

    def test_an_empty_reviewer_allowlist_is_refused(self) -> None:
        """Ne pas borner les reviewers n'est pas « accepter tout le monde ».

        Le primitif sous-jacent traite `None` comme « pas de contrôle » ; la
        composition, elle, exige une allowlist et refuse sans."""
        with pytest.raises(ReviewBindingError):
            self._authority(accepted_reviewers=())
        with pytest.raises(ReviewBindingError):
            self._authority(accepted_reviewers=None)

    def test_an_expired_receipt_is_refused(self) -> None:
        with pytest.raises(ReviewBindingError):
            self._authority(now=datetime(2026, 11, 1, tzinfo=UTC))

    def test_a_receipt_signed_by_an_unknown_key_is_refused(self) -> None:
        raw = PiiReviewDecisionSetV1.model_validate(_set()).canonical_bytes()
        other_anchor = TrustAnchor.model_validate(
            {
                "protocol_version": "NEXUS-REVIEW-BINDING-V1",
                "keys": [
                    {
                        "algorithm": "ed25519",
                        "key_id": SIGNING_KEY_ID,
                        "public_key": public_key_hex("44" * 32),
                        "environment": "test",
                        "comment": "Another ephemeral test key.",
                    }
                ],
            }
        )
        with pytest.raises(ReviewBindingError):
            self._authority(
                decision_set_bytes=raw,
                receipt_bytes=_authority_receipt_bytes(raw),
                trust_anchor=other_anchor,
            )

    def test_a_receipt_whose_challenge_is_recycled_is_refused(self) -> None:
        """P1 : le challenge doit être celui que les dimensions du reçu produisent.

        `verify_review_binding` ne recalcule pas `challenge_digest`. Sans
        `require_challenge_is_bound`, un reçu authentiquement signé mais portant
        le challenge d'une AUTRE revue est accepté — le champ devient
        décoratif, et la liaison à la revue qu'il prétend couvrir n'existe
        plus."""
        raw = PiiReviewDecisionSetV1.model_validate(_set()).canonical_bytes()
        receipt = json.loads(_authority_receipt_bytes(raw))
        receipt["binding"]["challenge_digest"] = "9" * 64
        binding = ScopeAuthorizationReviewBindingV1.model_validate(receipt["binding"])
        resigned = sign_review_binding(
            binding, private_key_hex=SIGNING_SEED, key_id=SIGNING_KEY_ID
        ).canonical_bytes()
        with pytest.raises(ReviewBindingError, match="challenge"):
            self._authority(decision_set_bytes=raw, receipt_bytes=resigned)
