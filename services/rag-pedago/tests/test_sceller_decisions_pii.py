"""Scellement structurel d'un ensemble de décisions PII rédigé par le reviewer.

Le reviewer remplit un brouillon hors dépôt (une entrée par paquet de revue) ;
cet outil le confronte à l'index des paquets et aux instruments, refuse tout
brouillon incomplet ou incohérent, et écrit la forme canonique versionnable.
L'autorité humaine ne vient pas de cet outil : elle vient de la review GitHub
(ADR-0025) et du reçu de liaison (ADR-0035). Cet outil ne décide rien.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from nexus_contracts import parse_pii_review_decision_set

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
SHA_A = "a" * 64
SHA_B = "b" * 64
F_A1 = "c1" * 32
F_A2 = "c2" * 32
F_B1 = "c3" * 32


def _module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "sceller_decisions_pii", SCRIPT_DIR / "sceller_decisions_pii.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _index(tmp_path: Path) -> Path:
    index = {
        "protocol_version": "NEXUS-PII-REVIEW-INDEX-V1",
        "campaign_id": "pii-review-test",
        "policy_path": "services/rag-pedago/configs/pii_gate_policy.yml",
        "policy_sha256": "1" * 64,
        "scanner_sha256": "2" * 64,
        "page_policy_id": "NEXUS-PDF-PAGE-POLICY-V1",
        "page_policy_sha256": "3" * 64,
        "bundles": [
            {"content_sha256": SHA_A, "bundle_sha256": "4" * 64, "signal_classes": ["phone_french"],
             "signal_count": 2, "pages": [3, 7],
             "findings": [
                 {"finding_id": F_A1, "pattern_id": "phone_french", "page": 3,
                  "match_sha256": "a1" * 32, "context_sha256": "b1" * 32, "match_length": 14},
                 {"finding_id": F_A2, "pattern_id": "phone_french", "page": 7,
                  "match_sha256": "a2" * 32, "context_sha256": "b2" * 32, "match_length": 14},
             ]},
            {"content_sha256": SHA_B, "bundle_sha256": "5" * 64, "signal_classes": ["email_address"],
             "signal_count": 1, "pages": [1],
             "findings": [
                 {"finding_id": F_B1, "pattern_id": "email_address", "page": 1,
                  "match_sha256": "a3" * 32, "context_sha256": "b3" * 32, "match_length": 24},
             ]},
        ],
    }
    path = tmp_path / "index.json"
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _draft(tmp_path: Path, **overrides: object) -> Path:
    draft = {
        "decision_set_id": "pii-review-test",
        "corpus_manifest_sha256": "7" * 64,
        "reviewer_login": "abenrhouma",
        "decisions": {
            SHA_A: {
                "findings": {F_A1: {"disposition": "PUBLIC_INSTITUTIONAL_DATA"},
                             F_A2: {"disposition": "PUBLIC_INSTITUTIONAL_DATA"}},
                "decision": "APPROVED",
                "decided_at": "2026-09-03T10:00:00+00:00",
                "justification": {
                    "category": "INSTITUTIONAL_CONTACT",
                    "statement": "Numéro de standard d'un rectorat en en-tête de document officiel.",
                },
            },
            SHA_B: {
                "findings": {F_B1: {"disposition": "PERSONAL_DATA_PRESENT"}},
                "decision": "REJECTED",
                "decided_at": "2026-09-03T10:05:00+00:00",
                "justification": {
                    "category": "PERSONAL_DATA_PRESENT",
                    "statement": "Courriel nominatif d'un particulier identifiable, page 1.",
                },
            },
        },
    }
    draft.update(overrides)
    path = tmp_path / "decisions.draft.json"
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_a_complete_draft_is_sealed_into_the_canonical_decision_set(tmp_path: Path) -> None:
    sceller = _module()
    index = _index(tmp_path)
    sortie = tmp_path / "governance" / "pii-review-decisions" / "pii-review-test.json"

    digest = sceller.sceller(draft=_draft(tmp_path), index_path=index, sortie=sortie)

    decision_set = parse_pii_review_decision_set(sortie.read_bytes())
    assert digest == decision_set.digest() == _sha(sortie)
    assert decision_set.review_index_sha256 == _sha(index)
    assert decision_set.policy_sha256 == "1" * 64
    assert decision_set.approved_content_sha256 == frozenset({SHA_A})
    a = decision_set.decision_for(SHA_A)
    assert a is not None and a.review_bundle_sha256 == "4" * 64
    assert a.signal_classes == ("phone_french",) and a.pages == (3, 7) and a.signal_count == 2
    assert a.reviewer_login == "abenrhouma"
    assert [f.finding_id for f in a.findings] == sorted([F_A1, F_A2])
    assert {f.disposition for f in a.findings} == {"PUBLIC_INSTITUTIONAL_DATA"}


def test_a_draft_that_leaves_a_bundle_undecided_is_refused(tmp_path: Path) -> None:
    sceller = _module()
    draft = _draft(tmp_path)
    document = json.loads(draft.read_text(encoding="utf-8"))
    del document["decisions"][SHA_B]
    draft.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="undecided"):
        sceller.sceller(draft=draft, index_path=_index(tmp_path), sortie=tmp_path / "out.json")


def test_a_draft_that_decides_a_content_absent_from_the_index_is_refused(tmp_path: Path) -> None:
    sceller = _module()
    draft = _draft(tmp_path)
    document = json.loads(draft.read_text(encoding="utf-8"))
    document["decisions"]["c" * 64] = document["decisions"][SHA_A]
    draft.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="not in the review index"):
        sceller.sceller(draft=draft, index_path=_index(tmp_path), sortie=tmp_path / "out.json")


def test_a_placeholder_decision_is_refused(tmp_path: Path) -> None:
    sceller = _module()
    draft = _draft(tmp_path)
    document = json.loads(draft.read_text(encoding="utf-8"))
    document["decisions"][SHA_A]["decision"] = "__A_DECIDER__"
    draft.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError):
        sceller.sceller(draft=draft, index_path=_index(tmp_path), sortie=tmp_path / "out.json")


def test_the_draft_cannot_override_instruments_or_bundle_digests(tmp_path: Path) -> None:
    """Les instruments et l'empreinte du paquet viennent de l'index, jamais du
    brouillon : un reviewer ne peut pas lier sa décision à un autre paquet."""
    sceller = _module()
    draft = _draft(tmp_path)
    document = json.loads(draft.read_text(encoding="utf-8"))
    document["decisions"][SHA_A]["review_bundle_sha256"] = "9" * 64
    draft.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="review_bundle_sha256"):
        sceller.sceller(draft=draft, index_path=_index(tmp_path), sortie=tmp_path / "out.json")


def test_the_generated_draft_names_every_bundle_and_is_refused_until_filled(tmp_path: Path) -> None:
    sceller = _module()
    index = _index(tmp_path)
    draft = tmp_path / "decisions.draft.json"
    sceller.brouillon(index_path=index, sortie=draft, decision_set_id="pii-review-test",
                      corpus_manifest_sha256="7" * 64, reviewer_login="abenrhouma")
    document = json.loads(draft.read_text(encoding="utf-8"))
    assert set(document["decisions"]) == {SHA_A, SHA_B}
    assert document["decisions"][SHA_A]["decision"] == "__A_DECIDER__"
    assert set(document["decisions"][SHA_A]["findings"]) == {F_A1, F_A2}
    assert document["decisions"][SHA_A]["findings"][F_A1]["disposition"] == "__A_DECIDER__"
    with pytest.raises(ValueError):
        sceller.sceller(draft=draft, index_path=index, sortie=tmp_path / "out.json")


def test_receipt_verification_binds_the_receipt_to_the_sealed_decision_set(tmp_path: Path) -> None:
    """Vérification hors ligne, sans secret : le reçu doit être signé par une clé
    de l'ancre, couvrir exactement ces octets, ce dépôt, cet identifiant, un
    reviewer de l'allowlist distinct de l'auteur, et un challenge lié."""
    from datetime import UTC, datetime

    from nexus_contracts.review_binding import (
        ScopeAuthorizationReviewBindingV1,
        expected_challenge_digest,
        public_key_hex,
        sign_review_binding,
    )

    sceller = _module()
    index = _index(tmp_path)
    decision_set = tmp_path / "pii-review-test.json"
    sceller.sceller(draft=_draft(tmp_path), index_path=index, sortie=decision_set)
    raw = decision_set.read_bytes()
    seed = "44" * 32
    key_id = "review-binding-v1-test"
    anchor = tmp_path / "anchor.json"
    anchor.write_text(
        json.dumps(
            {"protocol_version": "NEXUS-REVIEW-BINDING-V1",
             "keys": [{"key_id": key_id, "algorithm": "ed25519",
                       "public_key": public_key_hex(seed), "environment": "test"}]}
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    challenge = expected_challenge_digest(
        repository="cyranoaladin/RAG", pull_request=210, base_ref="main", base_sha="a" * 40,
        head_sha="b" * 40, author="cyranoaladin", reviewer="abenrhouma",
    )
    binding = ScopeAuthorizationReviewBindingV1.model_validate(
        {
            "protocol_version": "NEXUS-REVIEW-BINDING-V1", "repository": "cyranoaladin/RAG",
            "pull_request": 210, "base_ref": "main", "base_sha": "a" * 40, "head_sha": "b" * 40,
            "authorization_artifact_path": "governance/pii-review-decisions/pii-review-test.json",
            "authorization_artifact_sha256": _sha(decision_set),
            "authorization_artifact_git_blob_sha1": sceller.git_blob_sha1(raw),
            "authorization_id": "pii-review-test",
            "authorization_decision": "APPROVE_PII_REVIEW_DECISIONS",
            "review_id": 777, "reviewer_login": "abenrhouma", "reviewer_permission": "write",
            "author_login": "cyranoaladin", "submitted_at": now.isoformat(),
            "challenge_protocol": "NEXUS-TRUSTED-REVIEW-V1", "challenge_digest": challenge,
            "verified_at": now.isoformat(), "verifier_version": "test/1",
            "expires_at": datetime(2026, 10, 5, tzinfo=UTC).isoformat(),
        }
    )
    receipt = tmp_path / "receipt.json"
    receipt.write_bytes(sign_review_binding(binding, private_key_hex=seed, key_id=key_id).canonical_bytes())

    verdict = sceller.verifier_recu(
        receipt=receipt, decision_set=decision_set, anchor=anchor, environment="test",
        repository="cyranoaladin/RAG", accepted_reviewers=("abenrhouma",), now=now,
    )
    assert verdict["decision_set_id"] == "pii-review-test"
    assert verdict["approved_content_sha256"] == [SHA_A]
    assert verdict["reviewer_login"] == "abenrhouma"

    decision_set.write_bytes(raw.replace(b"REJECTED", b"APPROVED", 1))
    with pytest.raises(ValueError):
        sceller.verifier_recu(
            receipt=receipt, decision_set=decision_set, anchor=anchor, environment="test",
            repository="cyranoaladin/RAG", accepted_reviewers=("abenrhouma",), now=now,
        )


def test_an_approval_with_one_undecided_or_personal_finding_is_refused(tmp_path: Path) -> None:
    """« J'ai vu le premier match, ça semble bon » n'est pas représentable."""
    sceller = _module()
    for disposition in ("__A_DECIDER__", "PERSONAL_DATA_PRESENT"):
        draft = _draft(tmp_path)
        document = json.loads(draft.read_text(encoding="utf-8"))
        document["decisions"][SHA_A]["findings"][F_A2]["disposition"] = disposition
        draft.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(ValueError):
            sceller.sceller(draft=draft, index_path=_index(tmp_path), sortie=tmp_path / "out.json")


def test_a_finding_of_the_index_left_undecided_is_refused(tmp_path: Path) -> None:
    sceller = _module()
    draft = _draft(tmp_path)
    document = json.loads(draft.read_text(encoding="utf-8"))
    del document["decisions"][SHA_A]["findings"][F_A2]
    draft.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="undecided"):
        sceller.sceller(draft=draft, index_path=_index(tmp_path), sortie=tmp_path / "out.json")
