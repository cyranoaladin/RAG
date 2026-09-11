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
