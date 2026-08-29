"""Le statut de revue ne doit jamais être hérité d'un défaut.

Le script d'ingestion canonique inscrivait un littéral `"reviewed"` dans ses
deux INSERT — la table des chunks et celle des placements. Il AFFIRMAIT donc
qu'une décision humaine avait été prise sur tout contenu qu'il ingérerait
jamais, y compris un contenu que personne n'aurait examiné.

Le contrat distingue les deux notions : `REVIEWED` signifie « la décision
humaine a été validée », quand `RETRIEVAL_ELIGIBLE` n'est qu'un constat
automatique. Affirmer l'un pour l'autre est le défaut que ce dépôt a rencontré
à répétition — un contrôle qui affirme plus qu'il n'a vérifié — appliqué ici à
la revue elle-même.

Ce que ces tests verrouillent : l'**absence** du paramètre doit faire échouer,
jamais défauter. Un défaut, fût-il `needs_review`, redeviendrait une affirmation
que personne n'a prononcée.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "infra"
    / "scripts"
    / "canonical_release_corpus_ingestion.py"
)


def _argument_review_status() -> ast.Call:
    """Retourner l'appel `add_argument("--review-status", …)` du script.

    L'analyse est syntaxique et non par exécution : importer le module
    exigerait la base, l'artefact embedding et le registre scellé.
    """
    arbre = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        if getattr(noeud.func, "attr", None) != "add_argument":
            continue
        if noeud.args and getattr(noeud.args[0], "value", None) == "--review-status":
            return noeud
    pytest.fail("le script ne déclare aucun argument --review-status")


def test_review_status_est_requis() -> None:
    """`required=True` : l'omission échoue au lieu d'hériter."""
    mots = {mot.arg: mot.value for mot in _argument_review_status().keywords}
    assert "required" in mots, "--review-status doit être déclaré requis"
    assert getattr(mots["required"], "value", None) is True


def test_review_status_n_a_aucun_defaut() -> None:
    """Aucun défaut, pas même `needs_review`.

    C'est le cœur de la non-régression : un défaut ferait de nouveau porter au
    script une affirmation que l'opérateur n'a pas prononcée.
    """
    mots = {mot.arg for mot in _argument_review_status().keywords}
    assert "default" not in mots, (
        "--review-status ne doit porter AUCUN défaut : un statut de revue "
        "hérité est une affirmation que personne n'a prononcée"
    )


def test_valeurs_admises_limitees_au_contrat() -> None:
    """Seuls `needs_review` et `reviewed` passent.

    `auto_reviewed` a existé dans une base vestige et a induit en erreur à
    trois reprises. Il n'appartient pas au contrat et ne doit pas être ingérable.
    """
    mots = {mot.arg: mot.value for mot in _argument_review_status().keywords}
    assert "choices" in mots, "--review-status doit restreindre ses valeurs"
    choix = {element.value for element in mots["choices"].elts}
    assert choix == {"needs_review", "reviewed"}


def test_aucun_statut_de_revue_en_dur_dans_les_insert() -> None:
    """Les deux INSERT lisent le paramètre, aucun ne porte de littéral.

    Le premier correctif n'avait touché que l'INSERT des chunks ; celui des
    placements gardait son littéral. Ce test couvre le fichier entier plutôt
    qu'un site, parce qu'un contrôle doit s'exercer sur tout son périmètre.
    """
    lignes = SCRIPT.read_text(encoding="utf-8").splitlines()
    fautes = [
        f"{numero}: {ligne.strip()}"
        for numero, ligne in enumerate(lignes, 1)
        if '"reviewed"' in ligne
        and not ligne.lstrip().startswith("#")
        and "choices" not in ligne
    ]
    assert not fautes, "statut de revue en dur hors du paramètre : " + "; ".join(fautes)


def test_le_parametre_est_propage_jusqu_a_l_ingestion() -> None:
    """`main` transmet la valeur ; sans cela le requis serait décoratif."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "review_status=args.review_status" in source
    assert "    review_status: str," in source, (
        "ingest_first_servable_release doit accepter le statut en paramètre"
    )
