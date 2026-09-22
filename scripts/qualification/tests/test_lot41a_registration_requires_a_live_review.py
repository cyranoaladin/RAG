"""Une autorisation LOT41A ne s'enregistre que depuis une revue VIVANTE (lot CH5).

Le lot CH4 a été fusionné avant que les onze autorisations ne soient
enregistrées. `authorize_scope_cli record-authorization` a alors refusé les
onze, identiquement :

    AUTHORIZATION_DENIED: PR #232 is not APPROVED at head c70a7cff…
      — reason=pull_request_not_open

Ce n'est pas un défaut : `evaluate_trusted_review` exige `state == "open"`.
Une PR fusionnée ne peut plus porter une autorisation, sans quoi une décision
pourrait être enregistrée indéfiniment après que son contexte de revue a
disparu. Ces épreuves fixent cette contrainte d'ORDRE, pour qu'elle ne soit
pas redécouverte une seconde fois sur le terrain.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from _lot41a_active_set import artefacts_actifs

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "scripts/github"))

from trusted_human_review import (  # noqa: E402
    TrustedReviewerConfig,
    build_challenge,
    evaluate_trusted_review,
)

AUTORISATIONS = RACINE / "governance/authorizations"
PREFIXE = "lot41a-staging-v2-"
RELECTEUR = "abenrhouma"
DEPOT = "cyranoaladin/RAG"

HEAD = "c70a7cff821dd8f12e03a301387be9bee2666cef"
AUTRE_HEAD = "1" * 40
BASE = "cabc7c928d1bae2762736880c88e67d3825b363a"

#: Le commit de merge de CH4 : la référence contre laquelle le payload métier
#: des onze autorisations doit rester identique.
MERGE_CH4 = "25b88f31a38e71170913693ef60b25f67aeb530d"


def _config() -> TrustedReviewerConfig:
    return TrustedReviewerConfig(
        protocol="NEXUS-TRUSTED-REVIEW-V1",
        repository=DEPOT,
        base_ref="main",
        reviewers=(RELECTEUR,),
    )


def _pr(*, numero: int = 999, state: str = "open", head: str = HEAD) -> dict[str, Any]:
    return {
        "number": numero,
        "state": state,
        "draft": False,
        "base": {"ref": "main", "sha": BASE},
        "head": {"sha": head, "repo": {"full_name": DEPOT}},
        "user": {"login": "cyranoaladin"},
    }


def _challenge(*, numero: int = 999, head: str = HEAD) -> str:
    """Le challenge lie les sept dimensions : il ne vaut que pour ce head."""
    return build_challenge(
        {
            "repository": DEPOT,
            "pull_request": numero,
            "base_ref": "main",
            "base_sha": BASE,
            "head_sha": head,
            "author": "cyranoaladin",
            "reviewer": RELECTEUR,
            "protocol": "NEXUS-TRUSTED-REVIEW-V1",
        }
    )


def _review(
    *, head: str = HEAD, state: str = "APPROVED", numero: int = 999
) -> dict[str, Any]:
    return {
        "id": 1,
        "state": state,
        "commit_id": head,
        "user": {"login": RELECTEUR},
        "body": _challenge(numero=numero, head=head),
        "submitted_at": "2026-09-20T07:22:39Z",
    }


def _permissions(login: str = RELECTEUR) -> dict[str, Any]:
    return {login: {"permission": "write", "role_name": "write"}}


def _decide(**kwargs: Any) -> Any:
    return evaluate_trusted_review(
        pull_request=kwargs.pop("pull_request", _pr()),
        reviews=kwargs.pop("reviews", [_review()]),
        permissions=kwargs.pop("permissions", _permissions()),
        config=_config(),
        reviews_complete=True,
    )


# --- 1 / 5 — une PR fermée n'autorise plus rien -------------------------


@pytest.mark.parametrize("etat", ["closed", "merged"])
def test_une_pr_fermee_est_refusee(etat: str) -> None:
    """Le cas exact rencontré sur #232 après sa fusion."""
    decision = _decide(pull_request=_pr(state=etat))
    assert decision.approved is False
    assert decision.reason == "pull_request_not_open"


def test_une_autorisation_ne_peut_pas_etre_enregistree_apres_la_fusion() -> None:
    """Formulation explicite de la contrainte d'ordre du lot CH5.

    Enregistrer PUIS fusionner. L'inverse ne marche pas, et c'est voulu.
    """
    fusionnee = _decide(
        pull_request=_pr(numero=232, state="closed"), reviews=[_review(numero=232)]
    )
    ouverte = _decide(
        pull_request=_pr(numero=233, state="open"), reviews=[_review(numero=233)]
    )
    assert fusionnee.approved is False
    assert ouverte.approved is True


# --- 2 — ouverte mais non approuvée --------------------------------------


@pytest.mark.parametrize("etat_revue", ["COMMENTED", "CHANGES_REQUESTED", "DISMISSED"])
def test_une_pr_ouverte_sans_approbation_est_refusee(etat_revue: str) -> None:
    decision = _decide(reviews=[_review(state=etat_revue)])
    assert decision.approved is False


def test_une_pr_ouverte_sans_aucune_revue_est_refusee() -> None:
    assert _decide(reviews=[]).approved is False


# --- 3 — approuvée, mais sur un autre head -------------------------------


def test_une_approbation_sur_un_autre_head_est_refusee() -> None:
    """C'est l'incident de dérive de head du 2026-08-15, en test."""
    decision = _decide(reviews=[_review(head=AUTRE_HEAD)])
    assert decision.approved is False


def test_un_head_de_pr_different_de_la_revue_est_refuse() -> None:
    decision = _decide(pull_request=_pr(head=AUTRE_HEAD), reviews=[_review(head=HEAD)])
    assert decision.approved is False


# --- 4 / 6 — ouverte, approuvée, head exact ------------------------------


def test_une_pr_ouverte_approuvee_sur_le_head_exact_est_acceptee() -> None:
    decision = _decide()
    assert decision.approved is True, decision.reason


def test_un_relecteur_hors_allowlist_est_refuse() -> None:
    revue = _review()
    revue["user"] = {"login": "quelqu-un-dautre"}
    autre = _permissions("quelqu-un-dautre")
    assert _decide(reviews=[revue], permissions=autre).approved is False


# --- 7 — le payload métier est inchangé depuis CH4 -----------------------


def _fichiers() -> list[Path]:
    return artefacts_actifs(PREFIXE)


def test_le_payload_metier_est_identique_a_celui_de_ch4() -> None:
    """CH5 ne rejoue pas une décision : il rouvre une fenêtre de revue.

    Si un seul octet changeait, ce ne serait plus la décision que le lot CH4
    a fait approuver.
    """
    for chemin in _fichiers():
        local = chemin.read_bytes()
        relatif = chemin.relative_to(RACINE).as_posix()
        r = subprocess.run(
            ["git", "show", f"{MERGE_CH4}:{relatif}"],
            cwd=RACINE, capture_output=True, check=False,
        )
        if r.returncode != 0:
            pytest.skip(f"commit {MERGE_CH4} indisponible localement")
        assert r.stdout == local, chemin.name


def test_les_artefacts_ne_portent_aucune_liaison_de_revue() -> None:
    """C'est pourquoi aucun « rebind » n'est nécessaire pour CH5.

    Un artefact ne peut pas contenir la preuve de sa propre approbation : le
    dépôt, la PR, le head et le relecteur sont fournis à l'ENREGISTREMENT et
    relus en direct. Les mêmes octets valent donc pour n'importe quelle revue
    vivante qui les approuve.
    """
    interdits = {"pull_request", "expected_head", "head_sha", "evidence_head_sha",
                 "evidence_pull_request", "evidence_reviewer", "reviewer", "approved_by"}
    for chemin in _fichiers():
        document = json.loads(chemin.read_text(encoding="utf-8"))
        assert interdits & set(document) == set(), chemin.name


# --- 8 / 9 / 10 — onze, ni plus, ni moins --------------------------------


def _collections_v2() -> set[str]:
    manifeste = RACINE / (
        "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2/"
        "release-1b9eba0c0eb0ab13/profile_gate/production-profile-gate.release.json"
    )
    return {str(s["collection"]) for s in json.loads(manifeste.read_bytes())["subjects"]}


def test_exactement_onze_autorisations() -> None:
    assert len(_fichiers()) == 11


def test_une_autorisation_par_collection_v2_sans_surplus_ni_manque() -> None:
    portees = {
        json.loads(p.read_text(encoding="utf-8"))["scope"]["collection"] for p in _fichiers()
    }
    assert portees == _collections_v2()


def test_les_trois_collections_decidees_sont_couvertes() -> None:
    portees = {
        json.loads(p.read_text(encoding="utf-8"))["scope"]["collection"] for p in _fichiers()
    }
    for collection in (
        "rag_nexus_hggsp_premiere_specialite",
        "rag_nexus_hggsp_terminale_specialite",
        "rag_nexus_hlp_terminale_specialite",
    ):
        assert collection in portees


# --- 13 / 14 — CH5 ne crée aucun job et ne déclenche aucune ingestion ----


#: Le commit du lot CH5 sur `main` (PR #233). L'épreuve juge CE lot : la
#: comparer à `merge-base(HEAD, main)` jugeait n'importe quelle branche
#: ultérieure contre le périmètre de CH5 — et, en CI (clone superficiel), ne
#: jugeait rien du tout, `merge-base` échouant.
CH5_COMMIT = "d21610c9"


def _changements() -> list[tuple[str, str]] | None:
    try:
        diff = subprocess.run(
            ["git", "diff", "--name-status", f"{CH5_COMMIT}^", CH5_COMMIT],
            cwd=RACINE, capture_output=True, text=True, timeout=30, check=False,
        )
        if diff.returncode != 0:
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    lignes = [ligne for ligne in diff.stdout.splitlines() if ligne]
    return [(ligne.split("\t")[0], ligne.split("\t")[-1]) for ligne in lignes]


def test_ch5_ne_touche_ni_release_ni_scope_ni_runtime_d_ingestion() -> None:
    changements = _changements()
    if changements is None:
        pytest.skip("dépôt git indisponible")
    interdits = (
        "services/rag-pedago/data/releases/",
        "packages/contracts/src/nexus_contracts/artifacts/",
        "services/rag-engine/src/ingestor/ingestion_worker/",
    )
    for statut, chemin in changements:
        for prefixe in interdits:
            assert not chemin.startswith(prefixe), (statut, chemin)


def test_ch5_ne_modifie_aucune_autorisation() -> None:
    """CH5 rouvre une fenêtre de revue ; il ne redéfinit aucune décision."""
    changements = _changements()
    if changements is None:
        pytest.skip("dépôt git indisponible")
    for statut, chemin in changements:
        assert not chemin.startswith("governance/authorizations/"), (statut, chemin)
