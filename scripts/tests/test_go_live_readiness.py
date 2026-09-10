"""Le gate de readiness, eprouve par l adversaire.

Ce qui est protege ici n est pas un chiffre : c est l impossibilite d obtenir
`go_live_ready=true` tant qu un seul bloqueur reste non nul, et l impossibilite
qu une entree manquante passe pour un zero.

Un gate qui ne sait pas refuser n est pas un gate.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess

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
    return tmp_path


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


def test_un_programme_incompatible_bloque(depot_sans_bloqueur, monkeypatch) -> None:
    _ecrire(
        depot_sans_bloqueur,
        MATRICE,
        {
            "by_verdict": {"REFUSED_PROGRAM_INCOMPATIBLE": 1},
            "by_pii": {"PII_CLEARED_OR_NOT_SCANNED": 1},
        },
    )
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


def test_le_json_est_stable_entre_deux_calculs(
    depot_sans_bloqueur, monkeypatch
) -> None:
    module = _module(depot_sans_bloqueur, monkeypatch)
    un = module.evaluer(declared_lot_facts=FAITS_PROPRES)
    deux = module.evaluer(declared_lot_facts=FAITS_PROPRES)
    assert un == deux


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
        {"by_verdict": {"REFUSED_PROGRAM_INCOMPATIBLE": 1}, "by_pii": {}},
    )
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
    assert etat["computed_from_head"], "le commit lu doit toujours etre nomme"
    # Aucun `origin/main` dans ce depot fictif : le champ doit rester vide
    # plutot que de recopier le HEAD courant.
    assert etat["main_head"] != etat["computed_from_head"]
