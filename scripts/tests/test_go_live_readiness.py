"""Le gate de readiness, eprouve par l adversaire.

Ce qui est protege ici n est pas un chiffre : c est l impossibilite d obtenir
`go_live_ready=true` tant qu un seul bloqueur reste non nul, et l impossibilite
qu une entree manquante passe pour un zero.

Un gate qui ne sait pas refuser n est pas un gate.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys

import pytest

SCRIPT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "go_live"
    / "check_go_live_readiness.py"
)

MATRICE = "docs/reports/handoff/servability_matrix_v1.json"
NON_PDF = "docs/reports/evidence-index/non_pdf_disposition_consolidation_20260907.json"
POLITIQUE = "services/rag-pedago/configs/proposals/nexus_rag_currentness_policy_v1.yml"
DISPOSITIONS = "docs/reports/go_live/open_pr_dispositions.json"
QUALIFICATION = "docs/reports/go_live/qualification_blockers.json"
ECART_RECHERCHE = "docs/reports/go_live/rag_searchability_gap.json"
ATTENDUS = "docs/reports/go_live/expected_worktrees.json"

FAITS_PROPRES = {
    "production_db_writes": 0,
    "production_deployments": 0,
    "current_switch": 0,
}


def _module(racine: pathlib.Path, monkeypatch):
    monkeypatch.setenv("NEXUS_REPO_ROOT", str(racine))
    spec = importlib.util.spec_from_file_location("go_live_readiness", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _ecrire(racine: pathlib.Path, relative: str, contenu) -> None:
    chemin = racine / relative
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(contenu, str):
        chemin.write_text(contenu, encoding="utf-8")
    else:
        chemin.write_text(json.dumps(contenu, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def depot_sans_bloqueur(tmp_path: pathlib.Path) -> pathlib.Path:
    """Un depot fictif ou TOUT est ferme. Sans ce cas, on ne saurait pas si le
    gate sait dire oui — et un gate qui ne dit jamais oui ne prouve rien."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _ecrire(
        tmp_path,
        MATRICE,
        {
            "by_verdict": {"CANDIDATE_NO_BLOCKING_DIMENSION": 10},
            "by_pii": {"PII_CLEARED_OR_NOT_SCANNED": 10},
            # Le contenu promu doit être recensé par la matrice : sans sa
            # ligne, l'impact de release n'est pas mesurable, et un dépôt
            # « sans bloqueur » en aurait un.
            "rows": [
                {
                    "content_sha256": "a" * 64,
                    "verdict": "CANDIDATE_NO_BLOCKING_DIMENSION",
                }
            ],
        },
    )
    _ecrire(
        tmp_path,
        NON_PDF,
        {"NON_PDF_SERVABLE": 3, "NON_PDF_LOCAL_COPY_RETAINED": 3, "NON_PDF_TOTAL": 3},
    )
    _ecrire(tmp_path, POLITIQUE, "policy_id: X\nstatus: ACCEPTED\napplied: true\n")
    _ecrire(
        tmp_path,
        DISPOSITIONS,
        {
            "dispositions": {
                "1": {"disposition": "KEEP_OPEN_EXTERNAL_REVIEW", "reason": "x"}
            }
        },
    )
    _ecrire(tmp_path, QUALIFICATION, {"blockers": [{"id": "C1", "closed": True}]})
    _ecrire(tmp_path, ECART_RECHERCHE, _ecart_recherche())
    _ecrire(
        tmp_path,
        ATTENDUS,
        {
            "expected_basenames": {tmp_path.name: "le depot fictif lui-meme"},
            "session_temporary_path_marker": "/scratchpad/",
        },
    )
    _poser_calculateur_promu(tmp_path, contenus=["a" * 64])
    return tmp_path


def _ecart_recherche(**surcharges) -> dict:
    """Un ecart de recherche FERME : le corpus est indexe et le retrieval valide.

    C est le seul etat qui ne bloque pas. Tout le reste — vecteurs absents,
    retrieval non valide, portee cible non couverte — doit refuser.
    """
    base = {
        "kind": "NEXUS-RAG-SEARCHABILITY-GAP-V1",
        "measured": {"staging_vectors_present": 10, "target_scope_contents": 10},
        "rag_searchable": True,
        "target_scope_searchable": True,
        "production_searchable": True,
        "retrieval_contract_validated": True,
        "rag_searchability_blocker": False,
        "conditions_not_met": [],
    }
    base.update(surcharges)
    return base


#: Le gate delegue l ensemble promu au calculateur canonique. Les epreuves
#: posent donc un calculateur de banc qui rend ce qu on lui demande — jamais
#: une reimplementation de la regle, seulement une source controlable.
CALCULATEUR = "scripts/qualification/compute_promoted_content_set.py"


def _poser_calculateur_promu(
    racine: pathlib.Path,
    *,
    contenus: list[str] | None,
    echoue: bool = False,
) -> None:
    chemin = racine / CALCULATEUR
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if echoue:
        chemin.write_text(
            "import sys\n"
            "print('PROMOTED_CONTENT_SET_INVALID: refus simule', file=sys.stderr)\n"
            "sys.exit(2)\n",
            encoding="utf-8",
        )
        return
    charge = {
        "content_sha256": contenus or [],
        "content_set_sha256": "f" * 64,
        "count": len(contenus or []),
        "release_authority": {"mechanism": "REGISTRY_FILE"},
        "release_registry_source": "DEFAULT",
    }
    chemin.write_text(
        "import argparse, json, pathlib\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--output', required=True)\n"
        "a = p.parse_args()\n"
        f"pathlib.Path(a.output).write_text(json.dumps({charge!r}))\n",
        encoding="utf-8",
    )


def _evaluer(racine, monkeypatch):
    return _module(racine, monkeypatch).evaluer(declared_lot_facts=FAITS_PROPRES)


# --- le gate sait dire oui, et seulement alors ------------------------


def test_tout_ferme_donne_go_live_ready(depot_sans_bloqueur, monkeypatch) -> None:
    etat = _evaluer(depot_sans_bloqueur, monkeypatch)
    assert etat["blocking_reasons"] == []
    assert etat["go_live_ready"] is True


# --- un seul bloqueur suffit -----------------------------------------


def test_une_pii_non_tranchee_bloque(depot_sans_bloqueur, monkeypatch) -> None:
    _ecrire(
        depot_sans_bloqueur,
        MATRICE,
        {
            "by_verdict": {"CANDIDATE_NO_BLOCKING_DIMENSION": 9},
            "by_pii": {"PII_UNDECIDED": 1},
        },
    )
    etat = _evaluer(depot_sans_bloqueur, monkeypatch)
    assert etat["go_live_ready"] is False
    assert "pii_undecided" in etat["blocking_reasons"]


def test_un_programme_incompatible_PROMU_bloque(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """Ce qui bloque, c est un incompatible encore PROMU.

    Une version anterieure de cette epreuve suffisait a bloquer avec un simple
    compteur d histogramme, sans qu aucune release ne contienne le contenu.
    Elle figeait donc une semantique fausse : un contenu que la matrice refuse
    n est pas servi.
    """
    _ecrire(
        depot_sans_bloqueur,
        MATRICE,
        {
            "by_verdict": {"REFUSED_PROGRAM_INCOMPATIBLE": 1},
            "by_pii": {"PII_CLEARED_OR_NOT_SCANNED": 1},
            "rows": [
                {
                    "content_sha256": "d" * 64,
                    "program": "INCOMPATIBLE_PROVEN",
                    "verdict": "REFUSED_PROGRAM_INCOMPATIBLE",
                }
            ],
        },
    )
    _poser_calculateur_promu(depot_sans_bloqueur, contenus=["d" * 64])
    etat = _evaluer(depot_sans_bloqueur, monkeypatch)
    assert etat["go_live_ready"] is False
    assert "program_incompatible_in_servable_set" in etat["blocking_reasons"]


def test_une_politique_d_actualite_non_appliquee_bloque(
    depot_sans_bloqueur, monkeypatch
) -> None:
    _ecrire(depot_sans_bloqueur, POLITIQUE, "status: PROPOSED\napplied: false\n")
    etat = _evaluer(depot_sans_bloqueur, monkeypatch)
    assert etat["go_live_ready"] is False
    assert "currentness_policy_applied" in etat["blocking_reasons"]


def test_une_reacquisition_incomplete_bloque(depot_sans_bloqueur, monkeypatch) -> None:
    _ecrire(
        depot_sans_bloqueur,
        NON_PDF,
        {"NON_PDF_SERVABLE": 3, "NON_PDF_LOCAL_COPY_RETAINED": 2, "NON_PDF_TOTAL": 3},
    )
    etat = _evaluer(depot_sans_bloqueur, monkeypatch)
    assert etat["go_live_ready"] is False
    assert "non_pdf_servable_reacquired" in etat["blocking_reasons"]


def test_une_pr_inconnue_bloque(depot_sans_bloqueur, monkeypatch) -> None:
    """Une PR qu on n a pas classee est une PR qu on n a pas lue."""
    _ecrire(
        depot_sans_bloqueur,
        DISPOSITIONS,
        {"dispositions": {"7": {"disposition": "UNKNOWN", "reason": "?"}}},
    )
    etat = _evaluer(depot_sans_bloqueur, monkeypatch)
    assert etat["go_live_ready"] is False
    assert "open_prs_disposition_unknown" in etat["blocking_reasons"]
    assert "open_prs_blocking" in etat["blocking_reasons"]


def test_une_pr_bloquante_bloque(depot_sans_bloqueur, monkeypatch) -> None:
    _ecrire(
        depot_sans_bloqueur,
        DISPOSITIONS,
        {"dispositions": {"7": {"disposition": "BLOCKING", "reason": "dette"}}},
    )
    etat = _evaluer(depot_sans_bloqueur, monkeypatch)
    assert etat["go_live_ready"] is False
    assert etat["open_prs_blocking"] == 1


def test_une_disposition_inventee_est_refusee(depot_sans_bloqueur, monkeypatch) -> None:
    """Inventer un nom de disposition contournerait le gate en silence."""
    _ecrire(
        depot_sans_bloqueur,
        DISPOSITIONS,
        {"dispositions": {"7": {"disposition": "PROBABLEMENT_OK", "reason": "?"}}},
    )
    module = _module(depot_sans_bloqueur, monkeypatch)
    with pytest.raises(module.EntreeManquante, match="non reconnues"):
        module.evaluer(declared_lot_facts=FAITS_PROPRES)


def test_un_bloqueur_de_qualification_ouvert_bloque(
    depot_sans_bloqueur, monkeypatch
) -> None:
    _ecrire(
        depot_sans_bloqueur,
        QUALIFICATION,
        {"blockers": [{"id": "ROLLBACK", "closed": False}]},
    )
    etat = _evaluer(depot_sans_bloqueur, monkeypatch)
    assert etat["go_live_ready"] is False
    assert "go_live_qualification_blockers" in etat["blocking_reasons"]


@pytest.mark.parametrize(
    "fait", ["production_db_writes", "production_deployments", "current_switch"]
)
def test_une_action_de_production_declaree_bloque(
    depot_sans_bloqueur, monkeypatch, fait: str
) -> None:
    module = _module(depot_sans_bloqueur, monkeypatch)
    faits = dict(FAITS_PROPRES)
    faits[fait] = 1
    etat = module.evaluer(declared_lot_facts=faits)
    assert etat["go_live_ready"] is False
    assert fait in etat["blocking_reasons"]


# --- une entree manquante n est pas un zero ---------------------------


@pytest.mark.parametrize(
    "relative", [MATRICE, NON_PDF, POLITIQUE, DISPOSITIONS, QUALIFICATION, ATTENDUS]
)
def test_une_entree_manquante_est_un_refus(
    depot_sans_bloqueur, monkeypatch, relative: str
) -> None:
    """Ne pas savoir n est pas savoir que c est bon."""
    (depot_sans_bloqueur / relative).unlink()
    module = _module(depot_sans_bloqueur, monkeypatch)
    with pytest.raises(module.EntreeManquante):
        module.evaluer(declared_lot_facts=FAITS_PROPRES)


def test_une_politique_sans_champ_applied_est_un_refus(
    depot_sans_bloqueur, monkeypatch
) -> None:
    _ecrire(depot_sans_bloqueur, POLITIQUE, "status: PROPOSED\n")
    module = _module(depot_sans_bloqueur, monkeypatch)
    with pytest.raises(module.EntreeManquante, match="applied"):
        module.evaluer(declared_lot_facts=FAITS_PROPRES)


# --- la sortie est generee, jamais ecrite a la main --------------------


def test_le_markdown_se_declare_derive(depot_sans_bloqueur, monkeypatch) -> None:
    module = _module(depot_sans_bloqueur, monkeypatch)
    etat = module.evaluer(declared_lot_facts=FAITS_PROPRES)
    rendu = module.rendre_markdown(etat)
    assert "Fichier derive" in rendu
    assert "Ne pas l editer a la main" in rendu


def test_le_markdown_dit_ce_qu_il_ne_mesure_pas(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """Presenter un fait declare comme une mesure serait une fausse assurance."""
    module = _module(depot_sans_bloqueur, monkeypatch)
    etat = module.evaluer(declared_lot_facts=FAITS_PROPRES)
    assert etat["production_facts_are_declared_not_measured"] is True
    rendu = module.rendre_markdown(etat)
    assert "declares par le lot" in rendu


#: Le seul champ que deux calculs successifs peuvent legitimement rendre
#: different : l espace disque bouge tout seul.
CHAMPS_VOLATILS = {"disk_free_bytes", "disk_used_percent"}


def test_le_json_est_stable_entre_deux_calculs(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """Tout doit etre stable SAUF le disque, qui bouge sans qu on y touche.

    Une premiere version comparait les deux etats entiers : elle etait donc
    instable par intermittence, et une epreuve intermittente finit par etre
    ignoree plutot que corrigee.
    """
    module = _module(depot_sans_bloqueur, monkeypatch)
    un = module.evaluer(declared_lot_facts=FAITS_PROPRES)
    deux = module.evaluer(declared_lot_facts=FAITS_PROPRES)
    def sans_volatils(etat: dict) -> dict:
        return {k: v for k, v in etat.items() if k not in CHAMPS_VOLATILS}

    assert sans_volatils(un) == sans_volatils(deux)


# --- les residus que git ne voit pas ----------------------------------


def test_un_residu_sous_worktrees_bloque(depot_sans_bloqueur, monkeypatch) -> None:
    """Un repertoire sous `.worktrees/` qui n est plus un worktree git est
    invisible a `git worktree list` — c est precisement pour cela qu il passe
    inapercu, et pour cela qu il doit bloquer.
    """
    residu = depot_sans_bloqueur / ".worktrees" / "ancien-lot"
    residu.mkdir(parents=True)
    (residu / "reste.txt").write_text("x", encoding="utf-8")

    etat = _evaluer(depot_sans_bloqueur, monkeypatch)
    assert etat["root_owned_worktree_residues"] == 1
    assert ".worktrees/ancien-lot" in etat["root_owned_worktree_residue_paths"]
    assert etat["go_live_ready"] is False
    assert "root_owned_worktree_residues" in etat["blocking_reasons"]


def test_un_worktree_supplementaire_non_nomme_bloque(
    depot_sans_bloqueur, monkeypatch, tmp_path_factory
) -> None:
    """Nommer les worktrees legitimes est le seul moyen de reconnaitre ceux
    qui ne le sont pas.

    Le checkout PRINCIPAL, lui, est toujours legitime : le declarer obsolete
    n aurait aucun sens, et une premiere version de cette epreuve l attendait
    a tort.
    """
    subprocess.run(
        ["git", "-C", str(depot_sans_bloqueur), "add", "-A"], check=True
    )
    subprocess.run(
        [
            "git", "-C", str(depot_sans_bloqueur),
            "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-qm", "base",
        ],
        check=True,
    )
    intrus = tmp_path_factory.mktemp("intrus") / "lot-oublie"
    subprocess.run(
        [
            "git", "-C", str(depot_sans_bloqueur),
            "worktree", "add", "--detach", str(intrus),
        ],
        check=True,
        capture_output=True,
    )

    etat = _evaluer(depot_sans_bloqueur, monkeypatch)
    assert etat["obsolete_worktrees_remaining"] == 1
    assert "obsolete_worktrees_remaining" in etat["blocking_reasons"]
    assert etat["go_live_ready"] is False


# --- pourquoi ce lecteur est admis par le garde-fou d unicite ---------


def test_le_lecteur_de_readiness_ne_peut_que_refuser(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """Ce script LIT la matrice de servabilite et le drapeau `applied` de la
    politique d actualite. Le garde-fou d unicite d autorite l epingle a ce
    titre, et cette epreuve est la justification de cet epinglage.

    La propriete : quelle que soit la valeur lue, ce script ne peut jamais
    RENDRE un contenu servable ni RENDRE la politique effective. Il peut
    seulement refuser le go-live. Lire un drapeau pour signaler qu il n est
    pas leve est l inverse de l appliquer.
    """
    module = _module(depot_sans_bloqueur, monkeypatch)

    # Aucun verdict de servabilite n est produit : le script ne porte aucune
    # des valeurs par lesquelles la matrice decide.
    etat = module.evaluer(declared_lot_facts=FAITS_PROPRES)
    interdits = {
        "CANDIDATE_NO_BLOCKING_DIMENSION",
        "GOVERNED_NOT_SERVABLE",
        "SERVABLE",
    }
    rendu = json.dumps(etat)
    assert not (interdits & set(rendu.split('"'))), (
        "l evaluateur de readiness rend un verdict de servabilite : il "
        "deviendrait une seconde autorite"
    )

    # `applied: true` ne suffit jamais a rendre le go-live vrai : d autres
    # bloqueurs continuent de compter. Le lecteur ne peut donc pas, a lui
    # seul, faire passer quoi que ce soit.
    _ecrire(depot_sans_bloqueur, POLITIQUE, "applied: true\n")
    _ecrire(
        depot_sans_bloqueur,
        MATRICE,
        {
            "by_verdict": {"REFUSED_PROGRAM_INCOMPATIBLE": 1},
            "by_pii": {},
            "rows": [
                {
                    "content_sha256": "d" * 64,
                    "program": "INCOMPATIBLE_PROVEN",
                    "verdict": "REFUSED_PROGRAM_INCOMPATIBLE",
                }
            ],
        },
    )
    _poser_calculateur_promu(depot_sans_bloqueur, contenus=["d" * 64])
    etat = _evaluer(depot_sans_bloqueur, monkeypatch)
    assert etat["go_live_ready"] is False


def test_le_lecteur_n_ecrit_jamais_dans_ses_entrees(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """Un lecteur qui ecrit dans sa source n est plus un lecteur."""
    import hashlib

    entrees = [MATRICE, NON_PDF, POLITIQUE, DISPOSITIONS, QUALIFICATION, ATTENDUS]
    avant = {
        r: hashlib.sha256((depot_sans_bloqueur / r).read_bytes()).hexdigest()
        for r in entrees
    }
    module = _module(depot_sans_bloqueur, monkeypatch)
    module.evaluer(declared_lot_facts=FAITS_PROPRES)
    apres = {
        r: hashlib.sha256((depot_sans_bloqueur / r).read_bytes()).hexdigest()
        for r in entrees
    }
    assert avant == apres


def test_main_head_n_est_pas_le_head_courant(depot_sans_bloqueur, monkeypatch) -> None:
    """`main_head` doit venir de `origin/main`, pas de la branche courante.

    Les confondre ferait dire au fichier d etat qu une branche de travail EST
    main — et un etat de go-live attribue au mauvais commit ne vaut rien.
    """
    subprocess.run(["git", "-C", str(depot_sans_bloqueur), "add", "-A"], check=True)
    subprocess.run(
        [
            "git", "-C", str(depot_sans_bloqueur),
            "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-qm", "base",
        ],
        check=True,
    )
    etat = _evaluer(depot_sans_bloqueur, monkeypatch)
    assert etat["evaluated_head"], "le commit lu doit toujours etre nomme"
    # Aucun `origin/main` dans ce depot fictif : le champ doit rester vide
    # plutot que de recopier le HEAD courant.
    assert etat["main_head"] != etat["evaluated_head"]


# --- fraicheur : un instantane n autorise rien ------------------------


def test_un_instantane_ne_pretend_jamais_etre_l_etat_courant(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """La question que ce lot ferme : le fichier committe est-il l etat
    courant ?

    Non, et il ne peut pas l etre : genere AVANT le commit qui le contient, il
    ne contiendra jamais ce commit. Le dire une fois ferme l ambiguite pour de
    bon, au lieu de la laisser se reposer a chaque lecture.
    """
    etat = _evaluer(depot_sans_bloqueur, monkeypatch)
    assert etat["state_freshness_kind"] == "COMMITTED_SNAPSHOT"
    assert etat["snapshot_contains_self_commit"] is False
    assert etat["snapshot_is_operational_current"] is False
    assert "relancer le script en direct" in etat["snapshot_freshness_note"]


def test_l_instantane_nomme_la_ref_et_le_commit_evalues(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """Un depot sans commit n a pas de HEAD, et le champ doit rester vide.

    Avant la correction de `rev-parse`, il portait la chaine `HEAD` : le
    fichier nommait alors un commit qui n existe pas, sans que rien ne le
    signale.
    """
    etat = _evaluer(depot_sans_bloqueur, monkeypatch)
    assert etat["evaluated_head"] is None, "sans commit, aucun HEAD a nommer"

    subprocess.run(["git", "-C", str(depot_sans_bloqueur), "add", "-A"], check=True)
    subprocess.run(
        [
            "git", "-C", str(depot_sans_bloqueur),
            "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-qm", "base",
        ],
        check=True,
    )
    etat = _evaluer(depot_sans_bloqueur, monkeypatch)
    assert etat["evaluated_head"] and len(etat["evaluated_head"]) == 40
    assert etat["evaluated_ref"]
    assert "origin_main_at_generation" in etat


def test_un_instantane_perime_est_detecte_a_la_lecture(
    depot_sans_bloqueur, monkeypatch, tmp_path
) -> None:
    """`snapshot_is_operational_current` ne peut pas etre une valeur STOCKEE :
    elle serait vraie l instant de l ecriture et fausse aussitot apres. Elle se
    calcule donc a la lecture."""
    module = _module(depot_sans_bloqueur, monkeypatch)
    chemin = tmp_path / "vieux.json"
    chemin.write_text(
        json.dumps(
            {
                "evaluated_head": "0" * 40,
                "origin_main_at_generation": "1" * 40,
                "go_live_ready": True,
            }
        ),
        encoding="utf-8",
    )
    verdict = module.verifier_instantane(chemin)
    assert verdict["snapshot_is_operational_current"] is False
    # Meme un instantane qui se declare pret n autorise rien.
    assert verdict["snapshot_go_live_ready"] is True
    assert verdict["snapshot_may_authorize_go_live"] is False


def test_un_instantane_a_jour_n_autorise_pas_davantage(
    depot_sans_bloqueur, monkeypatch, tmp_path
) -> None:
    """Un instantane concordant n est pas une autorisation : il concorde."""
    module = _module(depot_sans_bloqueur, monkeypatch)
    subprocess.run(["git", "-C", str(depot_sans_bloqueur), "add", "-A"], check=True)
    subprocess.run(
        [
            "git", "-C", str(depot_sans_bloqueur),
            "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-qm", "base",
        ],
        check=True,
    )
    etat = module.evaluer(declared_lot_facts=FAITS_PROPRES)
    chemin = tmp_path / "frais.json"
    chemin.write_text(json.dumps(etat), encoding="utf-8")

    verdict = module.verifier_instantane(chemin)
    assert verdict["snapshot_is_operational_current"] is True
    assert verdict["snapshot_may_authorize_go_live"] is False


def test_le_markdown_dirige_vers_le_calcul_en_direct(
    depot_sans_bloqueur, monkeypatch
) -> None:
    module = _module(depot_sans_bloqueur, monkeypatch)
    rendu = module.rendre_markdown(module.evaluer(declared_lot_facts=FAITS_PROPRES))
    assert "n autorise aucun deploiement" in rendu
    assert "--verify-snapshot" in rendu
    assert "relance en direct" in rendu


def test_un_instantane_absent_est_un_refus(depot_sans_bloqueur, monkeypatch) -> None:
    module = _module(depot_sans_bloqueur, monkeypatch)
    with pytest.raises(module.EntreeManquante):
        module.verifier_instantane(depot_sans_bloqueur / "inexistant.json")


# --- le ledger est derive, jamais saisi -------------------------------


def test_le_ledger_derive_ses_valeurs_de_l_etat(depot_sans_bloqueur, monkeypatch) -> None:
    """Ecrire les valeurs du ledger a la main recreerait une seconde source."""
    incompatibles = [f"{i:064x}" for i in range(1, 5)]
    _ecrire(
        depot_sans_bloqueur,
        MATRICE,
        {
            "by_verdict": {"REFUSED_PROGRAM_INCOMPATIBLE": 4},
            "by_pii": {"PII_UNDECIDED": 17},
            "rows": [
                {
                    "content_sha256": sha,
                    "program": "INCOMPATIBLE_PROVEN",
                    "verdict": "REFUSED_PROGRAM_INCOMPATIBLE",
                }
                for sha in incompatibles
            ],
        },
    )
    _poser_calculateur_promu(depot_sans_bloqueur, contenus=incompatibles)
    module = _module(depot_sans_bloqueur, monkeypatch)
    etat = module.evaluer(declared_lot_facts=FAITS_PROPRES)
    ledger = module.construire_ledger(etat)
    par_id = {b["id"]: b for b in ledger["blockers"]}
    assert par_id["PII_UNDECIDED"]["current_value"] == 17
    assert par_id["PROGRAM_INCOMPATIBLE_IN_SERVABLE_SET"]["current_value"] == 4


def test_chaque_bloqueur_du_ledger_est_actionnable(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """Un bloqueur sans action requise ni condition de fermeture n avance a
    rien : il constate."""
    module = _module(depot_sans_bloqueur, monkeypatch)
    ledger = module.construire_ledger(
        module.evaluer(declared_lot_facts=FAITS_PROPRES)
    )
    for b in ledger["blockers"]:
        assert b["required_action"].strip(), b["id"]
        assert b["close_condition"].strip(), b["id"]
        assert b["evidence_source"].strip(), b["id"]
        assert b["owner_type"], b["id"]


def test_l_agregat_ne_se_ferme_jamais_directement(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """`PRE_RELEASE_BLOCKERS` derive de trois autres. Le fermer par lui-meme
    reviendrait a maquiller les trois."""
    module = _module(depot_sans_bloqueur, monkeypatch)
    ledger = module.construire_ledger(
        module.evaluer(declared_lot_facts=FAITS_PROPRES)
    )
    agregat = next(
        b for b in ledger["blockers"] if b["id"] == "PRE_RELEASE_BLOCKERS"
    )
    assert agregat["category"] == "AGGREGATE"
    assert agregat["owner_type"] == "DERIVED"
    assert "Se ferme seul" in agregat["close_condition"]


def test_le_ledger_compte_les_bloqueurs_ouverts(
    depot_sans_bloqueur, monkeypatch
) -> None:
    module = _module(depot_sans_bloqueur, monkeypatch)
    ledger = module.construire_ledger(
        module.evaluer(declared_lot_facts=FAITS_PROPRES)
    )
    assert ledger["blockers_open"] == sum(
        1 for b in ledger["blockers"] if b["blocking"]
    )
    assert ledger["blockers_total"] == len(ledger["blockers"])


def test_le_ledger_markdown_se_declare_derive(
    depot_sans_bloqueur, monkeypatch
) -> None:
    module = _module(depot_sans_bloqueur, monkeypatch)
    rendu = module.rendre_ledger_markdown(
        module.construire_ledger(module.evaluer(declared_lot_facts=FAITS_PROPRES))
    )
    assert "Fichier derive" in rendu
    assert "les editer a la main" in rendu


def test_un_head_different_suffit_a_perimer_l_instantane(
    depot_sans_bloqueur, monkeypatch, tmp_path
) -> None:
    """Un seul champ discordant suffit, et il faut l eprouver SEUL.

    Une premiere version de l epreuve du perime faisait diverger le HEAD ET
    l origin/main a la fois : elle passait donc meme si la comparaison de HEAD
    disparaissait. Une mutation l a montre.
    """
    module = _module(depot_sans_bloqueur, monkeypatch)
    chemin = tmp_path / "head_seul.json"
    chemin.write_text(
        json.dumps(
            {
                # `origin_main_at_generation` concorde (aucun origin/main ici,
                # donc None des deux cotes) ; SEUL le HEAD differe.
                "evaluated_head": "0" * 40,
                "origin_main_at_generation": None,
                "go_live_ready": False,
            }
        ),
        encoding="utf-8",
    )
    verdict = module.verifier_instantane(chemin)
    assert verdict["snapshot_is_operational_current"] is False


def test_un_origin_main_different_suffit_aussi(
    depot_sans_bloqueur, monkeypatch, tmp_path
) -> None:
    """L autre moitie de la comparaison, eprouvee seule elle aussi."""
    module = _module(depot_sans_bloqueur, monkeypatch)
    tete = module._git_sha("HEAD")
    chemin = tmp_path / "main_seul.json"
    chemin.write_text(
        json.dumps(
            {
                "evaluated_head": tete,
                "origin_main_at_generation": "9" * 40,
                "go_live_ready": False,
            }
        ),
        encoding="utf-8",
    )
    verdict = module.verifier_instantane(chemin)
    assert verdict["snapshot_is_operational_current"] is False


def test_une_ref_absente_ne_donne_pas_une_empreinte_bidon(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """`git rev-parse <ref>` RECOPIE la chaine quand la ref n existe pas.

    Sans `--verify`, `main_head` portait le texte `origin/main` au lieu d une
    empreinte : une valeur absurde d apparence plausible, invisible sur un
    depot ou la ref existe. Un etat de go-live qui nomme un commit inexistant
    ne vaut rien.
    """
    module = _module(depot_sans_bloqueur, monkeypatch)
    assert module._git_sha("origin/main") is None
    assert module._git_sha("une-ref-qui-n-existe-pas") is None

    subprocess.run(["git", "-C", str(depot_sans_bloqueur), "add", "-A"], check=True)
    subprocess.run(
        [
            "git", "-C", str(depot_sans_bloqueur),
            "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-qm", "base",
        ],
        check=True,
    )
    etat = module.evaluer(declared_lot_facts=FAITS_PROPRES)
    assert etat["main_head"] is None
    assert etat["evaluated_head"] is not None
    assert len(etat["evaluated_head"]) == 40


# --- trois modes, et un seul est un garde -----------------------------

def _lancer(racine: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, NEXUS_REPO_ROOT=str(racine))
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_assert_ready_echoue_quand_le_systeme_n_est_pas_pret(
    depot_sans_bloqueur,
) -> None:
    """LE garde. Un code de retour non nul est le seul signal fiable pour une
    chaine de deploiement."""
    _ecrire(
        depot_sans_bloqueur,
        MATRICE,
        {"by_verdict": {}, "by_pii": {"PII_UNDECIDED": 1}},
    )
    resultat = _lancer(depot_sans_bloqueur, "--assert-ready")
    assert resultat.returncode == 1
    assert "GO_LIVE_READY=false" in resultat.stdout
    assert "blocking_reasons=" in resultat.stdout


def test_assert_ready_rend_zero_seulement_si_tout_est_ferme(
    depot_sans_bloqueur,
) -> None:
    resultat = _lancer(depot_sans_bloqueur, "--assert-ready")
    assert resultat.returncode == 0, resultat.stderr
    assert "GO_LIVE_READY=true" in resultat.stdout


@pytest.mark.parametrize(
    "relative, contenu",
    [
        (MATRICE, {"by_verdict": {}, "by_pii": {"PII_UNDECIDED": 1}}),
        # Le cas programme n est PAS ici : il exige d ecrire deux fichiers, la
        # matrice et une release qui promeut le contenu. Il est eprouve seul,
        # dans les deux sens, par test_un_programme_incompatible_PROMU_bloque
        # et test_un_incompatible_absent_des_releases_ne_bloque_pas.
        (POLITIQUE, "applied: false\n"),
        (
            NON_PDF,
            {
                "NON_PDF_SERVABLE": 3,
                "NON_PDF_LOCAL_COPY_RETAINED": 1,
                "NON_PDF_TOTAL": 3,
            },
        ),
        (
            DISPOSITIONS,
            {"dispositions": {"9": {"disposition": "BLOCKING", "reason": "x"}}},
        ),
        (QUALIFICATION, {"blockers": [{"id": "C1", "closed": False}]}),
    ],
)
def test_un_seul_bloqueur_suffit_a_faire_echouer_assert_ready(
    depot_sans_bloqueur, relative: str, contenu
) -> None:
    """Chaque bloqueur, isole, doit suffire. Sans cela, un seul oubli suffirait
    a rendre le garde permissif."""
    _ecrire(depot_sans_bloqueur, relative, contenu)
    resultat = _lancer(depot_sans_bloqueur, "--assert-ready")
    assert resultat.returncode == 1, f"{relative} n a pas fait echouer le garde"


def test_assert_ready_rend_deux_si_une_entree_manque(depot_sans_bloqueur) -> None:
    """Ne pas pouvoir conclure n est pas la meme chose que conclure non.

    Un code distinct evite qu une chaine de deploiement traite une entree
    manquante comme un simple refus, ou pire, comme un accord.
    """
    (depot_sans_bloqueur / MATRICE).unlink()
    resultat = _lancer(depot_sans_bloqueur, "--assert-ready")
    assert resultat.returncode == 2
    assert "GO_LIVE_READY=unknown" in resultat.stderr


def test_assert_ready_n_ecrit_aucun_fichier(depot_sans_bloqueur) -> None:
    """Un garde qui ecrit modifie ce qu il mesure."""
    _ecrire(
        depot_sans_bloqueur,
        MATRICE,
        {"by_verdict": {}, "by_pii": {"PII_UNDECIDED": 1}},
    )
    avant = sorted(p.name for p in (depot_sans_bloqueur / "docs/reports/go_live").iterdir())
    _lancer(depot_sans_bloqueur, "--assert-ready")
    apres = sorted(p.name for p in (depot_sans_bloqueur / "docs/reports/go_live").iterdir())
    assert avant == apres


def test_check_only_est_un_diagnostic_pas_un_garde(depot_sans_bloqueur) -> None:
    """`--check-only` rend 0 MEME quand rien n est pret.

    Ce n est pas un defaut : c est un mode diagnostic. Mais s en servir comme
    garde serait un faux vert, et cette epreuve fige la distinction pour que
    personne ne les confonde par megarde.
    """
    _ecrire(
        depot_sans_bloqueur,
        MATRICE,
        {"by_verdict": {}, "by_pii": {"PII_UNDECIDED": 1}},
    )
    diagnostic = _lancer(depot_sans_bloqueur, "--check-only")
    garde = _lancer(depot_sans_bloqueur, "--assert-ready")

    assert diagnostic.returncode == 0
    assert "GO_LIVE_READY=false" in diagnostic.stdout
    assert garde.returncode == 1
    # Les deux disent la meme chose ; seul le code de retour differe.
    assert "GO_LIVE_READY=false" in garde.stdout


def test_le_module_documente_que_seul_assert_ready_est_un_garde() -> None:
    """La distinction entre diagnostic et garde doit etre ECRITE, pas devinee.

    On la cherche sur le texte normalise : la mise en page du docstring coupe
    les phrases, et une epreuve qui depend de l endroit ou tombe un retour a la
    ligne casse au premier reformatage.
    """
    source = " ".join(SCRIPT.read_text(encoding="utf-8").split())
    assert "seul mode utilisable comme condition de deploiement" in source
    assert "faux vert" in source
    assert "--assert-ready" in source


# --- verify-snapshot n autorise jamais --------------------------------


def test_verify_snapshot_dit_explicitement_qu_il_n_autorise_rien(
    depot_sans_bloqueur, tmp_path
) -> None:
    subprocess.run(["git", "-C", str(depot_sans_bloqueur), "add", "-A"], check=True)
    subprocess.run(
        [
            "git", "-C", str(depot_sans_bloqueur),
            "-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-qm", "base",
        ],
        check=True,
    )
    _lancer(depot_sans_bloqueur, "--json", "docs/reports/go_live/s.json")
    resultat = _lancer(
        depot_sans_bloqueur, "--verify-snapshot", "docs/reports/go_live/s.json"
    )
    assert "snapshot_may_authorize_go_live=False" in resultat.stdout
    assert "SNAPSHOT_AUTHORIZATION=false" in resultat.stdout
    assert "USE_ASSERT_READY_TO_GATE_A_DEPLOYMENT=true" in resultat.stdout
    # Concordant rend 0 — mais concordant n est pas autorise, et la sortie le dit.
    assert resultat.returncode == 0


# --- programme incompatible : la portee du compteur -------------------

SHA_INCOMPATIBLE = "d" * 64
RELEASES = "services/rag-pedago/data/releases/prerentree_2026_2027/multilevel"


def _matrice_avec_incompatible(candidat: bool = False) -> dict:
    """Une matrice portant UN contenu prouve incompatible."""
    return {
        "by_verdict": {
            "CANDIDATE_NO_BLOCKING_DIMENSION": 1 if candidat else 0,
            "REFUSED_PROGRAM_INCOMPATIBLE": 0 if candidat else 1,
        },
        "by_pii": {},
        "rows": [
            {
                "content_sha256": SHA_INCOMPATIBLE,
                "program": "INCOMPATIBLE_PROVEN",
                "verdict": (
                    "CANDIDATE_NO_BLOCKING_DIMENSION"
                    if candidat
                    else "REFUSED_PROGRAM_INCOMPATIBLE"
                ),
            }
        ],
    }


def test_un_incompatible_absent_du_set_promu_ne_bloque_pas(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """LE defaut d origine. Le compteur lisait un histogramme de TOUTE la
    population et comptait comme « dans le perimetre servable » un contenu que
    la matrice REFUSE — ce que son propre verdict dit.
    """
    _ecrire(depot_sans_bloqueur, MATRICE, _matrice_avec_incompatible())
    _poser_calculateur_promu(depot_sans_bloqueur, contenus=["a" * 64])
    etat = _evaluer(depot_sans_bloqueur, monkeypatch)

    assert etat["program_incompatible_total"] == 1, "l incompatibilite reste visible"
    assert etat["program_incompatible_refused_by_matrix"] == 1
    assert etat["program_incompatible_in_servable_set"] == 0
    assert "program_incompatible_in_servable_set" not in etat["blocking_reasons"]


def test_un_incompatible_PROMU_par_l_autorite_canonique_bloque(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """Sans cette epreuve, le compteur corrige serait vide de sens : une mesure
    qui ne peut pas alerter ne protege rien."""
    _ecrire(depot_sans_bloqueur, MATRICE, _matrice_avec_incompatible())
    _poser_calculateur_promu(
        depot_sans_bloqueur, contenus=["a" * 64, SHA_INCOMPATIBLE]
    )
    etat = _evaluer(depot_sans_bloqueur, monkeypatch)

    assert etat["program_incompatible_in_servable_set"] == 1
    assert SHA_INCOMPATIBLE in etat["program_incompatible_in_servable_set_ids"]
    assert "program_incompatible_in_servable_set" in etat["blocking_reasons"]
    assert etat["go_live_ready"] is False


def test_une_empreinte_technique_dans_un_json_de_release_ne_bloque_pas(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """Le defaut que cette remediation corrige.

    Une premiere version balayait tous les JSON de `data/releases` a la
    recherche de chaines de 64 caracteres hexadecimaux, et trouvait 20739
    empreintes la ou l autorite canonique en compte 319 : elle ramassait des
    empreintes d arbres, de modeles, de manifestes — tout ce qui a la FORME
    d un sha256 sans en avoir le ROLE.
    """
    _ecrire(depot_sans_bloqueur, MATRICE, _matrice_avec_incompatible())
    _poser_calculateur_promu(depot_sans_bloqueur, contenus=["a" * 64])
    _ecrire(
        depot_sans_bloqueur,
        "services/rag-pedago/data/releases/r/models.json",
        {"embedding_model_sha256": SHA_INCOMPATIBLE, "tree_sha": "b" * 64},
    )
    etat = _evaluer(depot_sans_bloqueur, monkeypatch)

    assert etat["program_incompatible_in_servable_set"] == 0
    assert etat["promoted_content_set_size"] == 1


def test_le_gate_ne_definit_pas_lui_meme_l_ensemble_promu() -> None:
    """Le readiness ne redefinit pas ce qu est un contenu promu : il le demande
    a l autorite qui le sait."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "compute_promoted_content_set.py" in source
    corps = source.split("def _ensemble_promu", 1)[1].split("\ndef ", 1)[0]
    assert "rglob" not in corps, "le gate rescanne des fichiers de release"
    assert "0-9a-f" not in corps, "le gate redefinit une empreinte"
    assert "CALCULATEUR_ENSEMBLE_PROMU" in corps


def test_un_calculateur_canonique_absent_est_un_refus(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """Ne pas pouvoir calculer l ensemble promu n est pas « rien n est promu »."""
    (depot_sans_bloqueur / CALCULATEUR).unlink()
    module = _module(depot_sans_bloqueur, monkeypatch)
    with pytest.raises(module.EntreeManquante, match="calculateur canonique absent"):
        module.evaluer(declared_lot_facts=FAITS_PROPRES)


def test_un_refus_du_calculateur_canonique_remonte(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """Un refus de l autorite n est jamais traduit en ensemble vide."""
    _poser_calculateur_promu(depot_sans_bloqueur, contenus=None, echoue=True)
    module = _module(depot_sans_bloqueur, monkeypatch)
    with pytest.raises(module.EntreeManquante, match="refuse de rendre"):
        module.evaluer(declared_lot_facts=FAITS_PROPRES)


def test_un_ensemble_promu_vide_est_refuse(depot_sans_bloqueur, monkeypatch) -> None:
    """Comparer avec un ensemble vide serait vrai par vacuite."""
    _poser_calculateur_promu(depot_sans_bloqueur, contenus=[])
    module = _module(depot_sans_bloqueur, monkeypatch)
    with pytest.raises(module.EntreeManquante, match="vide"):
        module.evaluer(declared_lot_facts=FAITS_PROPRES)


def test_la_provenance_du_set_promu_est_publiee(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """Un chiffre sans provenance ne se verifie pas."""
    etat = _evaluer(depot_sans_bloqueur, monkeypatch)
    assert etat["promoted_content_set_source"].endswith(
        "compute_promoted_content_set.py"
    )
    assert etat["promoted_content_set_sha256"]
    assert etat["promoted_release_authority_mechanism"] == "REGISTRY_FILE"
    assert etat["promoted_release_registry_source"] == "DEFAULT"


def test_le_gate_ne_selectionne_aucune_release(depot_sans_bloqueur) -> None:
    """Il NOMME l autorite de selection, il ne l exerce pas.

    Le garde-fou d unicite d autorite l epingle a ce titre ; cette epreuve est
    la justification de cet epinglage. Nommer l autorite a laquelle on delegue
    n est pas decider a sa place.
    """
    corps = SCRIPT.read_text(encoding="utf-8").split("def _ensemble_promu", 1)[1]
    corps = corps.split("\ndef ", 1)[0]
    for interdit in (
        "select_release_authority(",
        "resoudre_source_du_registre(",
        "ReleaseRegistryExpectation",
        "load_release_registry",
    ):
        assert interdit not in corps, (
            f"le gate exerce lui-meme la selection de release : {interdit}"
        )
    # Le corps passe par la constante, pas par le nom de fichier en dur.
    assert "CALCULATEUR_ENSEMBLE_PROMU" in corps


# --- le plan de cloture : derive, ordonne, honnete ---------------------


def _plan(racine, monkeypatch):
    module = _module(racine, monkeypatch)
    etat = module.evaluer(declared_lot_facts=FAITS_PROPRES)
    return module, etat, module.construire_plan(etat, module.construire_ledger(etat))


def test_trois_niveaux_sur_cinq_sont_declares_non_mesurables(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """Ingere, exploitable et servi en production ne se mesurent PAS depuis le
    depot. Rendre zero pour eux serait une fausse assurance."""
    _module_, _etat, plan = _plan(depot_sans_bloqueur, monkeypatch)
    par_id = {n["id"]: n for n in plan["content_levels"]}
    assert len(par_id) == 5
    for identifiant in ("INGESTED", "SEARCHABLE", "SERVED_IN_PRODUCTION"):
        niveau = par_id[identifiant]
        assert niveau["measurable_from_repository"] is False
        assert niveau["value"] is None
        assert "fausse assurance" in niveau["why_not_measured"]
    for identifiant in ("PROMOTED", "SERVABLE_CANDIDATE"):
        assert par_id[identifiant]["measurable_from_repository"] is True
        assert par_id[identifiant]["value"] is not None


def test_promu_et_candidat_ne_sont_pas_le_meme_nombre(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """Les confondre ferait croire qu un candidat est servi."""
    _ecrire(
        depot_sans_bloqueur,
        MATRICE,
        {
            "by_verdict": {"CANDIDATE_NO_BLOCKING_DIMENSION": 7},
            "by_pii": {},
            "rows": [],
        },
    )
    _poser_calculateur_promu(depot_sans_bloqueur, contenus=["a" * 64, "b" * 64])
    _module_, etat, plan = _plan(depot_sans_bloqueur, monkeypatch)
    par_id = {n["id"]: n for n in plan["content_levels"]}
    assert par_id["PROMOTED"]["value"] == 2
    assert par_id["SERVABLE_CANDIDATE"]["value"] == 7
    assert etat["promoted_content_set_size"] != etat["servable_candidate_count"]


def test_une_phase_aval_reste_fermee_tant_que_l_amont_est_ouverte(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """Qualifier un staging avant d avoir les octets oblige a tout refaire."""
    _ecrire(
        depot_sans_bloqueur,
        NON_PDF,
        {"NON_PDF_SERVABLE": 3, "NON_PDF_LOCAL_COPY_RETAINED": 0, "NON_PDF_TOTAL": 3},
    )
    _ecrire(
        depot_sans_bloqueur,
        QUALIFICATION,
        {"blockers": [{"id": "C1", "closed": False}]},
    )
    _module_, _etat, plan = _plan(depot_sans_bloqueur, monkeypatch)
    par_id = {p["id"]: p for p in plan["phases"]}

    assert par_id["P3_OCTETS"]["actionable_now"] is True
    assert par_id["P4_QUALIFICATION"]["actionable_now"] is False
    assert "P3_OCTETS" in par_id["P4_QUALIFICATION"]["blocked_by_phases"]
    assert par_id["P5_DEPLOIEMENT"]["closed"] is False


def test_le_deploiement_est_la_derniere_phase(
    depot_sans_bloqueur, monkeypatch
) -> None:
    _module_, _etat, plan = _plan(depot_sans_bloqueur, monkeypatch)
    derniere = plan["phases"][-1]
    assert derniere["id"] == "P5_DEPLOIEMENT"
    assert derniere["depends_on"] == ["P4_QUALIFICATION"]
    assert "--assert-ready" in derniere["gate"]


def test_chaque_phase_nomme_qui_agit(depot_sans_bloqueur, monkeypatch) -> None:
    """Une phase sans proprietaire n avance pas."""
    _ecrire(
        depot_sans_bloqueur,
        MATRICE,
        {"by_verdict": {}, "by_pii": {"PII_UNDECIDED": 3}, "rows": []},
    )
    _module_, _etat, plan = _plan(depot_sans_bloqueur, monkeypatch)
    ouvertes = [p for p in plan["phases"] if p["open_blockers"]]
    assert ouvertes, "le depot fictif doit avoir au moins une phase ouverte"
    for p in ouvertes:
        assert p["owners"], f"{p['id']} n a pas de proprietaire"


def test_le_plan_n_autorise_rien(depot_sans_bloqueur, monkeypatch) -> None:
    module, _etat, plan = _plan(depot_sans_bloqueur, monkeypatch)
    rendu = module.rendre_plan_markdown(plan)
    assert "il n autorise rien" in rendu
    assert "--assert-ready" in rendu
    assert "Fichier derive" in rendu


def test_le_plan_se_ferme_quand_tout_se_ferme(
    depot_sans_bloqueur, monkeypatch
) -> None:
    """Sans ce cas, on ne saurait pas si le plan sait dire « fini »."""
    _module_, etat, plan = _plan(depot_sans_bloqueur, monkeypatch)
    assert etat["go_live_ready"] is True
    assert plan["phases_closed"] == plan["phases_total"]


# --- Retention non-PDF : le compteur MESURE, sous politique versionnee -------
#
# Avant ce lot, le gate lisait une valeur figee. Une valeur figee ne peut ni
# se fermer par le travail, ni s ouvrir quand le magasin disparait. Ces
# epreuves tiennent la seule chose qui doit fermer ce bloqueur : des octets
# presents, verifies, dans un magasin nomme par une politique versionnee.

POLITIQUE_RETENTION = "docs/reports/go_live/non_pdf_retention_policy.json"
MANIFESTE_REACQ = "docs/reports/handoff/non_pdf_reacquisition_manifest.json"
CONSOLIDATION_NON_PDF = NON_PDF


def _poser_retention(
    depot: pathlib.Path,
    magasin: pathlib.Path,
    *,
    servables: int = 3,
    non_indexables: int = 2,
    octets_par_fichier: dict[str, bytes] | None = None,
    politique: bool = True,
    adoptee: bool = True,
) -> None:
    """Pose une politique, un manifeste et un magasin coherents."""
    import hashlib

    demandes = []
    octets_par_fichier = octets_par_fichier or {}
    for index in range(servables):
        ident = f"serv-{index}"
        octets = octets_par_fichier.get(ident, f"servable-{index}".encode())
        demandes.append(
            {
                "drive_file_id": ident,
                "drive_path": f"zone/{ident}.ggb",
                "expected_content_sha256": hashlib.sha256(octets).hexdigest(),
                "expected_size": len(octets),
                "classification": "INTERACTIVE_RESOURCE_SERVABLE",
                "target_disposition": "INTERACTIVE_RESOURCE_SERVABLE",
            }
        )
    for index in range(non_indexables):
        ident = f"trace-{index}"
        octets = f"trace-{index}".encode()
        demandes.append(
            {
                "drive_file_id": ident,
                "drive_path": f"zone/{ident}.yaml",
                "expected_content_sha256": hashlib.sha256(octets).hexdigest(),
                "expected_size": len(octets),
                "classification": "DIAGNOSTIC_QUESTION_BANK_NON_INDEXABLE",
                "target_disposition": "DIAGNOSTIC_QUESTION_BANK_NON_INDEXABLE",
            }
        )
    _ecrire(depot, MANIFESTE_REACQ, {"requests": demandes})
    _ecrire(
        depot,
        CONSOLIDATION_NON_PDF,
        {
            "NON_PDF_SERVABLE": servables,
            "NON_PDF_LOCAL_COPY_RETAINED": 0,
            "NON_PDF_TOTAL": servables + non_indexables,
        },
    )
    if politique:
        _ecrire(
            depot,
            POLITIQUE_RETENTION,
            {
                "kind": "NEXUS-NON-PDF-RETENTION-POLICY-V1",
                "adopted": adoptee,
                "durable_store": {
                    "canonical_root": "/inexistant/pour/le/test",
                    "env_override": "NEXUS_NON_PDF_STORE",
                },
            },
        )
    # Le reconciliateur canonique doit exister : le gate lui delegue la mesure.
    source = pathlib.Path("scripts/go_live/reconcile_non_pdf_counts.py").resolve()
    cible = depot / "scripts/go_live/reconcile_non_pdf_counts.py"
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    magasin.mkdir(parents=True, exist_ok=True)


def _remplir_magasin(depot: pathlib.Path, magasin: pathlib.Path, *, sauf=()) -> None:
    demandes = json.loads((depot / MANIFESTE_REACQ).read_text(encoding="utf-8"))["requests"]
    for demande in demandes:
        ident = demande["drive_file_id"]
        if ident in sauf:
            continue
        nom = ident.split("-")[0]
        index = ident.split("-")[1]
        octets = (f"servable-{index}" if nom == "serv" else f"trace-{index}").encode()
        (magasin / ident).write_bytes(octets)


def _mesurer(depot: pathlib.Path, magasin: pathlib.Path | None) -> dict:
    environnement = {"NEXUS_REPO_ROOT": str(depot)}
    if magasin is not None:
        environnement["NEXUS_NON_PDF_STORE"] = str(magasin)
    return _etat(depot, env=environnement)


def _etat(depot: pathlib.Path, env: dict | None = None) -> dict:
    sortie = depot / "etat.json"
    execution = subprocess.run(
        [
            sys.executable,
            str(pathlib.Path("scripts/go_live/check_go_live_readiness.py").resolve()),
            "--json",
            "etat.json",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {"NEXUS_REPO_ROOT": str(depot)})},
    )
    assert sortie.is_file(), execution.stderr[-600:]
    return json.loads(sortie.read_text(encoding="utf-8"))


def test_des_octets_verifies_au_magasin_ferment_le_bloqueur_non_pdf(
    depot_sans_bloqueur, tmp_path
):
    magasin = tmp_path / "magasin"
    _poser_retention(depot_sans_bloqueur, magasin)
    _remplir_magasin(depot_sans_bloqueur, magasin)
    etat = _mesurer(depot_sans_bloqueur, magasin)
    assert etat["non_pdf_servable_reacquired"] == 3
    assert etat["non_pdf_servable_total"] == 3
    assert etat["non_pdf_servable_complete"] is True
    assert etat["non_pdf_retention_reason"] == "MEASURED"


def test_un_seul_fichier_manquant_laisse_le_bloqueur_ouvert(
    depot_sans_bloqueur, tmp_path
):
    magasin = tmp_path / "magasin"
    _poser_retention(depot_sans_bloqueur, magasin)
    _remplir_magasin(depot_sans_bloqueur, magasin, sauf=("serv-2",))
    etat = _mesurer(depot_sans_bloqueur, magasin)
    assert etat["non_pdf_servable_reacquired"] == 2
    assert etat["non_pdf_servable_complete"] is False


def test_une_empreinte_differente_laisse_le_bloqueur_ouvert(
    depot_sans_bloqueur, tmp_path
):
    """Meme taille, autres octets : seul le SHA peut l attraper."""
    magasin = tmp_path / "magasin"
    _poser_retention(depot_sans_bloqueur, magasin)
    _remplir_magasin(depot_sans_bloqueur, magasin)
    original = (magasin / "serv-0").read_bytes()
    (magasin / "serv-0").write_bytes(b"X" * len(original))
    etat = _mesurer(depot_sans_bloqueur, magasin)
    assert etat["non_pdf_servable_reacquired"] == 2
    assert etat["non_pdf_servable_complete"] is False


def test_une_taille_differente_laisse_le_bloqueur_ouvert(
    depot_sans_bloqueur, tmp_path
):
    magasin = tmp_path / "magasin"
    _poser_retention(depot_sans_bloqueur, magasin)
    _remplir_magasin(depot_sans_bloqueur, magasin)
    (magasin / "serv-1").write_bytes(b"beaucoup plus long que l attendu")
    etat = _mesurer(depot_sans_bloqueur, magasin)
    assert etat["non_pdf_servable_complete"] is False


def test_les_non_indexables_ne_comptent_jamais_au_numerateur(
    depot_sans_bloqueur, tmp_path
):
    """Retenir les 20 traces ne doit pas faire croire que les servables le sont."""
    magasin = tmp_path / "magasin"
    _poser_retention(depot_sans_bloqueur, magasin, servables=3, non_indexables=5)
    # Seules les traces sont deposees.
    _remplir_magasin(
        depot_sans_bloqueur, magasin, sauf=("serv-0", "serv-1", "serv-2")
    )
    etat = _mesurer(depot_sans_bloqueur, magasin)
    assert etat["non_pdf_servable_reacquired"] == 0
    assert etat["non_pdf_servable_complete"] is False


def test_un_identifiant_drive_seul_ne_ferme_rien(depot_sans_bloqueur, tmp_path):
    """Le manifeste porte les identifiants ; aucun octet n est depose."""
    magasin = tmp_path / "magasin"
    _poser_retention(depot_sans_bloqueur, magasin)
    etat = _mesurer(depot_sans_bloqueur, magasin)
    assert etat["non_pdf_servable_reacquired"] == 0
    assert etat["non_pdf_servable_complete"] is False


def test_sans_politique_versionnee_le_bloqueur_reste_ouvert(
    depot_sans_bloqueur, tmp_path
):
    """Des octets presents ne suffisent pas : la politique doit exister."""
    magasin = tmp_path / "magasin"
    _poser_retention(depot_sans_bloqueur, magasin, politique=False)
    _remplir_magasin(depot_sans_bloqueur, magasin)
    etat = _mesurer(depot_sans_bloqueur, magasin)
    assert etat["non_pdf_servable_reacquired"] == 0
    assert etat["non_pdf_retention_policy_versioned"] is False
    assert etat["non_pdf_retention_reason"] == "POLICY_ABSENT"


def test_une_politique_non_adoptee_ne_ferme_rien(depot_sans_bloqueur, tmp_path):
    magasin = tmp_path / "magasin"
    _poser_retention(depot_sans_bloqueur, magasin, adoptee=False)
    _remplir_magasin(depot_sans_bloqueur, magasin)
    etat = _mesurer(depot_sans_bloqueur, magasin)
    assert etat["non_pdf_servable_reacquired"] == 0
    assert etat["non_pdf_retention_reason"] == "POLICY_NOT_ADOPTED"


def test_un_magasin_non_nomme_laisse_le_bloqueur_ouvert(
    depot_sans_bloqueur, tmp_path
):
    """Un magasin hors politique n est pas un magasin gouverne."""
    magasin = tmp_path / "magasin"
    _poser_retention(depot_sans_bloqueur, magasin)
    _remplir_magasin(depot_sans_bloqueur, magasin)
    etat = _mesurer(depot_sans_bloqueur, None)  # aucun override : racine absente
    assert etat["non_pdf_servable_reacquired"] == 0
    assert etat["non_pdf_retention_reason"] == "DURABLE_STORE_UNREADABLE"


def test_le_compteur_fige_reste_un_plancher(depot_sans_bloqueur, tmp_path):
    """La mesure ne peut pas faire BAISSER un compteur deja acquis."""
    magasin = tmp_path / "magasin"
    _poser_retention(depot_sans_bloqueur, magasin)
    _ecrire(
        depot_sans_bloqueur,
        CONSOLIDATION_NON_PDF,
        {"NON_PDF_SERVABLE": 3, "NON_PDF_LOCAL_COPY_RETAINED": 3, "NON_PDF_TOTAL": 5},
    )
    etat = _mesurer(depot_sans_bloqueur, magasin)  # magasin vide
    assert etat["non_pdf_servable_reacquired"] == 3


def test_une_reconciliation_refusee_ne_ferme_rien(depot_sans_bloqueur, tmp_path):
    """Si les totaux ne se reconcilient pas, la mesure n est pas opposable.

    Des octets peuvent etre presents et verifies alors que le recensement est
    incoherent — un compteur de consolidation qui ne correspond plus au
    manifeste. Compter quand meme reviendrait a fermer un bloqueur sur un
    denombrement dont personne ne peut dire ce qu il denombre.
    """
    magasin = tmp_path / "magasin"
    _poser_retention(depot_sans_bloqueur, magasin)
    _remplir_magasin(depot_sans_bloqueur, magasin)
    # Le compteur servable ne correspond plus au manifeste : reconciliation NON.
    _ecrire(
        depot_sans_bloqueur,
        CONSOLIDATION_NON_PDF,
        {"NON_PDF_SERVABLE": 99, "NON_PDF_LOCAL_COPY_RETAINED": 0, "NON_PDF_TOTAL": 5},
    )
    etat = _mesurer(depot_sans_bloqueur, magasin)
    assert etat["non_pdf_servable_reacquired"] == 0
    assert etat["non_pdf_retention_reason"] == "RECONCILIATION_REFUSED"


def test_un_magasin_declare_mais_inexistant_est_refuse(depot_sans_bloqueur, tmp_path):
    """Nommer un magasin ne le rend pas lisible."""
    magasin = tmp_path / "magasin"
    _poser_retention(depot_sans_bloqueur, magasin)
    _remplir_magasin(depot_sans_bloqueur, magasin)
    etat = _mesurer(depot_sans_bloqueur, tmp_path / "magasin-qui-n-existe-pas")
    assert etat["non_pdf_servable_reacquired"] == 0
    assert etat["non_pdf_retention_reason"] == "DURABLE_STORE_UNREADABLE"


# --- Incohérence de release : un contenu promu que le gate refuse -----------
#
# Le cas se produit quand une dimension se met à bloquer APRÈS la promotion.
# Le contenu reste dans la release, et plus rien ne le signale — d'autant
# moins que le drapeau qui l'a révélé, lui, vient de se fermer.

VERDICT_CANDIDAT = "CANDIDATE_NO_BLOCKING_DIMENSION"
VERDICT_NON_ACTUEL = "BLOCKED_NOT_CURRENT_BY_SOURCE"
VERDICT_PII = "BLOCKED_PII_HUMAN_REVIEW"


def _poser_matrice_par_contenu(depot: pathlib.Path, verdicts: dict[str, str]) -> None:
    """Pose une matrice avec des lignes nommées, pas seulement des totaux."""
    par_verdict: dict[str, int] = {}
    for verdict in verdicts.values():
        par_verdict[verdict] = par_verdict.get(verdict, 0) + 1
    _ecrire(
        depot,
        MATRICE,
        {
            "by_verdict": par_verdict,
            "by_pii": {"PII_CLEARED_OR_NOT_SCANNED": len(verdicts)},
            "rows": [
                {"content_sha256": sha, "verdict": verdict}
                for sha, verdict in sorted(verdicts.items())
            ],
        },
    )


def test_un_contenu_promu_refuse_par_l_actualite_bloque_le_go_live(
    depot_sans_bloqueur,
):
    promu = "a" * 64
    _poser_matrice_par_contenu(depot_sans_bloqueur, {promu: VERDICT_NON_ACTUEL})
    _poser_calculateur_promu(depot_sans_bloqueur, contenus=[promu])
    etat = _etat(depot_sans_bloqueur)

    assert etat["release_promoted_refused_contents"] == 1
    assert etat["release_promoted_refused_by_currentness"] == 1
    assert etat["release_promoted_refused_content_ids"] == [promu]
    assert etat["release_reseal_required"] is True
    assert "release_promoted_refused_contents" in etat["blocking_reasons"]
    assert etat["go_live_ready"] is False


def test_l_actualite_appliquee_ne_suffit_pas_si_la_release_est_incoherente(
    depot_sans_bloqueur,
):
    """Fermer le drapeau ne doit pas faire disparaître ce qu'il a révélé."""
    promu = "b" * 64
    _poser_matrice_par_contenu(depot_sans_bloqueur, {promu: VERDICT_NON_ACTUEL})
    _poser_calculateur_promu(depot_sans_bloqueur, contenus=[promu])
    etat = _etat(depot_sans_bloqueur)

    assert etat["currentness_policy_applied"] is True
    assert "currentness_policy_applied" not in etat["blocking_reasons"]
    # Et pourtant le go-live reste refusé, pour une autre raison, nommée.
    assert etat["go_live_ready"] is False
    assert "release_promoted_refused_contents" in etat["blocking_reasons"]


def test_une_release_sans_contenu_refuse_ne_declenche_pas_ce_blocage(
    depot_sans_bloqueur,
):
    promu = "c" * 64
    _poser_matrice_par_contenu(depot_sans_bloqueur, {promu: VERDICT_CANDIDAT})
    _poser_calculateur_promu(depot_sans_bloqueur, contenus=[promu])
    etat = _etat(depot_sans_bloqueur)

    assert etat["release_promoted_refused_contents"] == 0
    assert etat["release_reseal_required"] is False
    assert "release_promoted_refused_contents" not in etat["blocking_reasons"]


def test_un_contenu_refuse_mais_NON_promu_ne_declenche_pas_ce_blocage(
    depot_sans_bloqueur,
):
    """Le blocage porte sur l'incohérence de RELEASE, pas sur les refus."""
    promu, autre = "d" * 64, "e" * 64
    _poser_matrice_par_contenu(
        depot_sans_bloqueur, {promu: VERDICT_CANDIDAT, autre: VERDICT_NON_ACTUEL}
    )
    _poser_calculateur_promu(depot_sans_bloqueur, contenus=[promu])
    etat = _etat(depot_sans_bloqueur)
    assert etat["release_promoted_refused_contents"] == 0


def test_les_raisons_de_refus_ne_sont_pas_fondues(depot_sans_bloqueur):
    """PII et actualité disent deux choses différentes ; les fondre ferait
    disparaître l'une derrière l'autre."""
    par_pii, par_actualite = "f" * 64, "9" * 64
    _poser_matrice_par_contenu(
        depot_sans_bloqueur,
        {par_pii: VERDICT_PII, par_actualite: VERDICT_NON_ACTUEL},
    )
    _poser_calculateur_promu(depot_sans_bloqueur, contenus=[par_pii, par_actualite])
    etat = _etat(depot_sans_bloqueur)

    assert etat["release_promoted_refused_contents"] == 2
    assert etat["release_promoted_refused_by_currentness"] == 1
    assert etat["release_promoted_refused_by_verdict"] == {
        VERDICT_NON_ACTUEL: 1,
        VERDICT_PII: 1,
    }
    # Le contenu bloqué par l'actualité est nommé à part.
    assert etat["release_currentness_impact"] == [par_actualite]


def test_les_contenus_refuses_sont_nommes_pas_seulement_comptes(
    depot_sans_bloqueur,
):
    """Un compteur seul n'est pas actionnable : il faut savoir lesquels."""
    a, b = "1" * 64, "2" * 64
    _poser_matrice_par_contenu(
        depot_sans_bloqueur, {a: VERDICT_NON_ACTUEL, b: VERDICT_PII}
    )
    _poser_calculateur_promu(depot_sans_bloqueur, contenus=[a, b])
    etat = _etat(depot_sans_bloqueur)
    assert sorted(etat["release_promoted_refused_content_ids"]) == sorted([a, b])


def test_un_promu_absent_de_la_matrice_n_est_pas_repute_candidat(
    depot_sans_bloqueur,
):
    """Ne pas avoir pu croiser n'est pas la même chose que n'avoir rien trouvé.

    Sans cette épreuve, un contenu promu que la matrice ne recense pas serait
    compté comme candidat : un zéro NON mesuré présenté comme un zéro mesuré,
    exactement ce que ce compteur existe pour empêcher.
    """
    promu, recense = "7" * 64, "8" * 64
    _poser_matrice_par_contenu(depot_sans_bloqueur, {recense: VERDICT_CANDIDAT})
    _poser_calculateur_promu(depot_sans_bloqueur, contenus=[promu])
    etat = _etat(depot_sans_bloqueur)

    assert etat["release_promoted_unmatched_in_matrix"] == 1
    assert etat["release_impact_measurable"] is False
    assert "release_impact_measurable" in etat["blocking_reasons"]
    assert etat["go_live_ready"] is False
    # Et il n'est surtout pas compté comme un refus : on ne sait pas.
    assert etat["release_promoted_refused_contents"] == 0


def test_exclure_les_contenus_d_actualite_laisse_ceux_de_la_pii(
    depot_sans_bloqueur,
):
    """Simule le reseal d'actualité : il ne ferme pas tout, et doit le montrer.

    Le piège serait de présenter ce reseal comme assainissant la release.
    Après lui, les contenus promus bloqués par la PII restent promus, restent
    refusés, et le compteur reste non nul.
    """
    par_actualite = "3" * 64
    par_pii = "4" * 64
    _poser_matrice_par_contenu(
        depot_sans_bloqueur,
        {par_actualite: VERDICT_NON_ACTUEL, par_pii: VERDICT_PII},
    )
    _poser_calculateur_promu(
        depot_sans_bloqueur, contenus=[par_actualite, par_pii]
    )
    avant = _etat(depot_sans_bloqueur)
    assert avant["release_promoted_refused_contents"] == 2
    assert avant["release_promoted_refused_by_currentness"] == 1

    # Le reseal exclut le contenu archivé, et lui seul.
    _poser_calculateur_promu(depot_sans_bloqueur, contenus=[par_pii])
    apres = _etat(depot_sans_bloqueur)

    assert apres["release_promoted_refused_by_currentness"] == 0
    # Mais la release reste incohérente, pour l'autre raison.
    assert apres["release_promoted_refused_contents"] == 1
    assert apres["release_promoted_refused_by_verdict"] == {VERDICT_PII: 1}
    assert "release_promoted_refused_contents" in apres["blocking_reasons"]
    assert apres["go_live_ready"] is False


# --- Exploitabilité par recherche : un corpus gouverné n'est pas interrogeable -


def test_sans_vecteur_le_go_live_est_refuse(depot_sans_bloqueur):
    """Le cas réel : tout le corpus est ingéré, aucun vecteur ne le référence."""
    _ecrire(
        depot_sans_bloqueur,
        ECART_RECHERCHE,
        _ecart_recherche(
            measured={"staging_vectors_present": 0, "target_scope_contents": 2529},
            rag_searchable=False,
            target_scope_searchable=False,
            rag_searchability_blocker=True,
            conditions_not_met=["staging_vectors_present", "target_scope_searchable"],
        ),
    )
    etat = _etat(depot_sans_bloqueur)
    assert etat["staging_vectors_present"] == 0
    assert etat["rag_searchable"] is False
    assert etat["rag_searchability_blocker"] is True
    assert "rag_searchability_blocker" in etat["blocking_reasons"]
    assert etat["go_live_ready"] is False


def test_un_retrieval_non_valide_bloque_meme_avec_des_vecteurs(depot_sans_bloqueur):
    """Des vecteurs sans retrieval validé ne servent personne."""
    _ecrire(
        depot_sans_bloqueur,
        ECART_RECHERCHE,
        _ecart_recherche(
            rag_searchable=False,
            retrieval_contract_validated=False,
            rag_searchability_blocker=True,
            conditions_not_met=["retrieval_top_k_validated"],
        ),
    )
    etat = _etat(depot_sans_bloqueur)
    assert etat["retrieval_contract_validated"] is False
    assert "rag_searchability_blocker" in etat["blocking_reasons"]
    assert etat["go_live_ready"] is False


def test_une_portee_cible_non_couverte_bloque(depot_sans_bloqueur):
    """Un retrieval validé sur un échantillon ne dit rien du périmètre cible."""
    _ecrire(
        depot_sans_bloqueur,
        ECART_RECHERCHE,
        _ecart_recherche(
            measured={"staging_vectors_present": 5, "target_scope_contents": 2529},
            rag_searchable=False,
            target_scope_searchable=False,
            rag_searchability_blocker=True,
            conditions_not_met=["target_scope_searchable"],
        ),
    )
    etat = _etat(depot_sans_bloqueur)
    assert etat["target_scope_searchable"] is False
    assert etat["go_live_ready"] is False


def test_un_rapport_purement_documentaire_ne_suffit_pas(depot_sans_bloqueur):
    """Le drapeau du blocage est LU ; il ne se déduit pas du ton du rapport.

    Un rapport qui décrirait l'écart sans lever le drapeau laisserait passer le
    go-live — c'est exactement ce que ce test interdit.
    """
    _ecrire(
        depot_sans_bloqueur,
        ECART_RECHERCHE,
        _ecart_recherche(
            measured={"staging_vectors_present": 0, "target_scope_contents": 2529},
            rag_searchable=False,
            rag_searchability_blocker=True,
        ),
    )
    etat = _etat(depot_sans_bloqueur)
    assert "rag_searchability_blocker" in etat["blocking_reasons"]


def test_fermer_la_gouvernance_ne_rend_pas_le_corpus_interrogeable(
    depot_sans_bloqueur,
):
    """PII, release et PR fermées, mais aucun vecteur : le go-live reste refusé.

    C'est le piège central : un go-live prononcé sur les seuls compteurs de
    gouvernance livrerait un RAG qui ne répond à rien.
    """
    _ecrire(
        depot_sans_bloqueur,
        ECART_RECHERCHE,
        _ecart_recherche(
            measured={"staging_vectors_present": 0, "target_scope_contents": 2529},
            rag_searchable=False,
            rag_searchability_blocker=True,
        ),
    )
    etat = _etat(depot_sans_bloqueur)
    # La gouvernance est close dans cette fixture.
    assert etat["pii_undecided"] == 0
    assert etat["release_promoted_refused_contents"] == 0
    assert etat["open_prs_blocking"] == 0
    # Et pourtant :
    assert etat["blocking_reasons"] == ["rag_searchability_blocker"]
    assert etat["go_live_ready"] is False


def test_un_corpus_indexe_et_valide_ne_bloque_pas(depot_sans_bloqueur):
    """Sans ce cas, on ne saurait pas si le gate sait dire oui."""
    etat = _etat(depot_sans_bloqueur)
    assert etat["rag_searchable"] is True
    assert etat["rag_searchability_blocker"] is False
    assert "rag_searchability_blocker" not in etat["blocking_reasons"]


def test_l_ecart_de_recherche_absent_est_refuse(depot_sans_bloqueur):
    """Ne pas savoir si le corpus est atteignable n'est pas une autorisation."""
    (depot_sans_bloqueur / ECART_RECHERCHE).unlink()
    execution = subprocess.run(
        [
            sys.executable,
            str(pathlib.Path("scripts/go_live/check_go_live_readiness.py").resolve()),
            "--assert-ready",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "NEXUS_REPO_ROOT": str(depot_sans_bloqueur)},
    )
    assert execution.returncode == 2, execution.stdout[-400:]
