"""La preuve de revue scellée — ce qu'elle établit, et ce qu'elle refuse."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "scripts/github"))

import trusted_human_review as adr0025  # noqa: E402

from nexus_contracts.trusted_review_evidence import (  # noqa: E402
    SEALED_TRUSTED_REVIEW_EVIDENCE_PROTOCOL,
    TRUSTED_REVIEW_CHALLENGE_PROTOCOL,
    SealedTrustedReviewEvidenceError,
    SealedTrustedReviewEvidenceV1,
    parse_sealed_trusted_review_evidence,
    require_challenge_is_self_consistent,
    require_evidence_matches_authorization,
    require_trusted_reviewer,
)

REPO = "cyranoaladin/RAG"
BASE = "f66a04cb364191c53eb56c9a9e1208e9e386ae16"
HEAD = "44bf8360a5f5b272b0377835fd871099f817e955"
AUTEUR = "cyranoaladin"
RELECTEUR = "abenrhouma"
AUTH_ID = "lot41a-staging-v2-dgemc-terminale-option"


def _challenge(**overrides: Any) -> str:
    payload = {
        "repository": REPO, "pull_request": 241, "base_ref": "main",
        "base_sha": BASE, "head_sha": HEAD, "author": AUTEUR,
        "reviewer": RELECTEUR, "protocol": adr0025.PROTOCOL,
    }
    payload.update(overrides)
    return adr0025.build_challenge(payload)


def _evidence(**overrides: Any) -> SealedTrustedReviewEvidenceV1:
    champs: dict[str, Any] = {
        "protocol_version": SEALED_TRUSTED_REVIEW_EVIDENCE_PROTOCOL,
        "repository": REPO,
        "pull_request": 241,
        "pull_request_base_ref": "main",
        "pull_request_base_sha": BASE,
        "pull_request_head_sha": HEAD,
        "pull_request_author": AUTEUR,
        "authorization_id": AUTH_ID,
        "artifact_path": "governance/authorizations/lot41a-staging-v2-dgemc.json",
        "artifact_sha256": "c" * 64,
        "artifact_blob_sha": "d" * 40,
        "reviewer": RELECTEUR,
        "review_id": 987654321,
        "review_node_id": "PRR_kwDOabcdef",
        "review_submitted_at": datetime.now(UTC) - timedelta(hours=1),
        "challenge_protocol": TRUSTED_REVIEW_CHALLENGE_PROTOCOL,
        "challenge": _challenge(),
        "head_pinned_status": "success",
        "head_pinned_context": "trusted-human-review/head-pinned",
        "recorded_at": datetime.now(UTC),
        "recorder_version": "authorize_scope_cli/ADR-0058",
    }
    champs.update(overrides)
    return SealedTrustedReviewEvidenceV1(**champs)


# --------------------------------------------------------------------------
# Le challenge se redérive — c'est ce qui distingue une preuve d'une copie
# --------------------------------------------------------------------------


def test_le_challenge_scelle_se_rederive_de_ses_propres_dimensions() -> None:
    evidence = _evidence()
    assert evidence.expected_challenge() == evidence.challenge
    require_challenge_is_self_consistent(evidence)


def test_le_recalcul_reproduit_exactement_celui_d_adr_0025() -> None:
    """Un recalcul qui divergerait d'ADR-0025 ne prouverait rien."""
    evidence = _evidence()
    assert evidence.expected_challenge() == _challenge()


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [
        ("pull_request_author", "quelquun-dautre"),
        ("pull_request_base_ref", "release"),
        ("pull_request_base_sha", "a" * 40),
        ("pull_request_head_sha", "b" * 40),
        ("pull_request", 9999),
        ("reviewer", "un-autre-relecteur"),
    ],
)
def test_alterer_une_dimension_casse_le_challenge(champ: str, valeur: Any) -> None:
    evidence = _evidence(**{champ: valeur})
    with pytest.raises(SealedTrustedReviewEvidenceError, match="does not derive"):
        require_challenge_is_self_consistent(evidence)


def test_un_challenge_altere_est_refuse() -> None:
    evidence = _evidence(challenge=f"{TRUSTED_REVIEW_CHALLENGE_PROTOCOL}:{'0' * 64}")
    with pytest.raises(SealedTrustedReviewEvidenceError, match="does not derive"):
        require_challenge_is_self_consistent(evidence)


def test_un_challenge_absent_ne_peut_pas_etre_construit() -> None:
    with pytest.raises(ValueError, match="challenge"):
        _evidence(challenge="")


def test_un_challenge_d_un_autre_protocole_est_refuse() -> None:
    with pytest.raises(ValueError):
        _evidence(challenge="NEXUS-TRUSTED-REVIEW-V2:" + "a" * 64)


# --------------------------------------------------------------------------
# Le relecteur reste soumis à l'allowlist courante
# --------------------------------------------------------------------------


def test_un_relecteur_de_l_allowlist_est_accepte() -> None:
    require_trusted_reviewer(_evidence(), allowed_reviewers=(RELECTEUR, "autre"))


def test_un_relecteur_hors_allowlist_est_refuse() -> None:
    """Retirer une identité de l'allowlist éteint ses signatures passées."""
    with pytest.raises(SealedTrustedReviewEvidenceError, match="not in the governed"):
        require_trusted_reviewer(_evidence(), allowed_reviewers=("quelquun-dautre",))


def test_une_allowlist_vide_n_autorise_personne() -> None:
    with pytest.raises(SealedTrustedReviewEvidenceError):
        require_trusted_reviewer(_evidence(), allowed_reviewers=())


# --------------------------------------------------------------------------
# Le contexte de protection est scellé au vert, et ne peut pas l'être autrement
# --------------------------------------------------------------------------


@pytest.mark.parametrize("statut", ["failure", "pending", "error", "success_but_no"])
def test_un_contexte_non_reussi_ne_peut_pas_etre_scelle(statut: str) -> None:
    with pytest.raises(ValueError, match="head_pinned_status"):
        _evidence(head_pinned_status=statut)


# --------------------------------------------------------------------------
# Preuve absente ou incomplète
# --------------------------------------------------------------------------


def test_une_preuve_vide_est_refusee() -> None:
    with pytest.raises(SealedTrustedReviewEvidenceError, match="carries no proof"):
        parse_sealed_trusted_review_evidence({})


@pytest.mark.parametrize(
    "champ",
    [
        "repository", "pull_request", "pull_request_base_ref",
        "pull_request_base_sha", "pull_request_head_sha", "pull_request_author",
        "authorization_id", "artifact_path", "artifact_sha256",
        "artifact_blob_sha", "reviewer", "review_id", "review_node_id",
        "review_submitted_at", "challenge_protocol", "challenge",
        "head_pinned_status", "head_pinned_context", "recorded_at",
        "recorder_version",
    ],
)
def test_une_preuve_amputee_d_un_champ_est_refusee(champ: str) -> None:
    document = _evidence().canonical_document()
    del document[champ]
    with pytest.raises(SealedTrustedReviewEvidenceError, match="strict validation"):
        parse_sealed_trusted_review_evidence(document)


def test_un_champ_inconnu_est_refuse() -> None:
    document = _evidence().canonical_document()
    document["tolerance"] = "aucune"
    with pytest.raises(SealedTrustedReviewEvidenceError, match="strict validation"):
        parse_sealed_trusted_review_evidence(document)


def test_une_preuve_complete_se_relit_a_l_identique() -> None:
    evidence = _evidence()
    relue = parse_sealed_trusted_review_evidence(evidence.canonical_document())
    assert relue.digest() == evidence.digest()
    assert relue.canonical_bytes() == evidence.canonical_bytes()


def test_la_preuve_se_relit_depuis_ses_octets() -> None:
    evidence = _evidence()
    relue = parse_sealed_trusted_review_evidence(evidence.canonical_bytes())
    assert relue.digest() == evidence.digest()


def test_le_digest_change_des_qu_un_champ_change() -> None:
    avant = _evidence().digest()
    apres = _evidence(review_node_id="PRR_autre").digest()
    assert avant != apres


# --------------------------------------------------------------------------
# La preuve et la ligne enregistrée décrivent la même revue
# --------------------------------------------------------------------------


def _concordant(evidence: SealedTrustedReviewEvidenceV1, **overrides: Any) -> None:
    champs: dict[str, Any] = {
        "authorization_id": evidence.authorization_id,
        "artifact_path": evidence.artifact_path,
        "artifact_blob_sha": evidence.artifact_blob_sha,
        "repository": evidence.repository,
        "pull_request": evidence.pull_request,
        "base_sha": evidence.pull_request_base_sha,
        "head_sha": evidence.pull_request_head_sha,
        "reviewer": evidence.reviewer,
        "review_id": evidence.review_id,
        "challenge": evidence.challenge,
    }
    champs.update(overrides)
    require_evidence_matches_authorization(evidence, **champs)


def test_une_preuve_concordante_passe() -> None:
    _concordant(_evidence())


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [
        ("authorization_id", "lot41a-autre-chose"),
        ("artifact_path", "governance/authorizations/autre.json"),
        ("artifact_blob_sha", "e" * 40),
        ("repository", "quelquun/autre"),
        ("pull_request", 1),
        ("base_sha", "f" * 40),
        ("head_sha", "0" * 40),
        ("reviewer", "un-autre"),
        ("review_id", 42),
        ("challenge", f"{TRUSTED_REVIEW_CHALLENGE_PROTOCOL}:{'1' * 64}"),
    ],
)
def test_une_divergence_entre_preuve_et_ligne_est_refusee(
    champ: str, valeur: Any
) -> None:
    with pytest.raises(SealedTrustedReviewEvidenceError, match="disagrees"):
        _concordant(_evidence(), **{champ: valeur})


# --------------------------------------------------------------------------
# Canonicité
# --------------------------------------------------------------------------


def test_les_octets_canoniques_sont_tries_et_stables() -> None:
    evidence = _evidence()
    document = json.loads(evidence.canonical_bytes())
    assert list(document) == sorted(document)
    assert evidence.canonical_bytes().endswith(b"\n")


def test_le_run_de_workflow_est_optionnel_et_absent_du_canonique_s_il_manque() -> None:
    sans = _evidence()
    avec = _evidence(workflow_run_id=35535013039)
    assert "workflow_run_id" not in sans.canonical_document()
    assert avec.canonical_document()["workflow_run_id"] == 35535013039
    assert sans.digest() != avec.digest()
