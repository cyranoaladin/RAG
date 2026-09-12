"""Cohérence des artefacts de décision versionnés.

Ces épreuves existent à cause d'une erreur réelle : un rapport source a été
régénéré et rendu bloquant, mais le snapshot de readiness versionné, lui, est
resté celui d'un lot antérieur. Le code était juste ; les artefacts sur
lesquels on décide ne l'étaient pas.

C'est la pire forme d'incohérence, parce qu'elle ne se voit pas : chaque
fichier est plausible isolément. Seule leur confrontation la révèle.

Ces tests portent sur les fichiers VERSIONNÉS du dépôt, pas sur des fixtures.
Ils échouent si l'on commite un snapshot périmé.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]

ETAT = RACINE / "docs/reports/go_live/go_live_readiness_state.json"
ECART_RECHERCHE = RACINE / "docs/reports/go_live/rag_searchability_gap.json"
MARKDOWN = RACINE / "docs/reports/go_live/GO_LIVE_READINESS.md"

#: Champs que le readiness doit porter pour que l'exploitabilité par recherche
#: soit décidable en le lisant seul.
CHAMPS_RECHERCHE = (
    "rag_searchable",
    "staging_vectors_present",
    "target_scope_searchable",
    "production_searchable",
    "retrieval_contract_validated",
    "rag_searchability_blocker",
    "rag_searchability_conditions_not_met",
)


@pytest.fixture(scope="module")
def etat() -> dict:
    return json.loads(ETAT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ecart() -> dict:
    return json.loads(ECART_RECHERCHE.read_text(encoding="utf-8"))


def test_le_readiness_porte_tous_les_champs_de_recherche(etat):
    manquants = [champ for champ in CHAMPS_RECHERCHE if champ not in etat]
    assert not manquants, (
        f"le readiness versionné ne porte pas {manquants} : "
        "l'exploitabilité par recherche ne serait pas décidable en le lisant"
    )


def test_un_ecart_bloquant_apparait_dans_les_raisons_de_refus(etat, ecart):
    """Le test qui aurait attrapé le snapshot périmé.

    Si le rapport d'écart bloque et que le readiness ne le dit pas, l'un des
    deux est en retard sur l'autre — et c'est toujours celui qui décide.
    """
    if not ecart["rag_searchability_blocker"]:
        pytest.skip("l'écart de recherche ne bloque pas : rien à confronter")
    assert etat["rag_searchability_blocker"] is True, (
        "le rapport d'écart bloque mais le readiness versionné dit l'inverse : "
        "le snapshot est périmé"
    )
    assert "rag_searchability_blocker" in etat["blocking_reasons"], (
        "le rapport d'écart bloque mais la raison n'est pas dans "
        "blocking_reasons : le snapshot est périmé"
    )
    assert etat["go_live_ready"] is False


def test_les_valeurs_de_recherche_du_readiness_suivent_le_rapport(etat, ecart):
    """Ni l'un ni l'autre ne doit dériver : ce sont les mêmes faits."""
    assert etat["rag_searchable"] == ecart["rag_searchable"]
    assert etat["target_scope_searchable"] == ecart["target_scope_searchable"]
    assert etat["production_searchable"] == ecart["production_searchable"]
    assert (
        etat["retrieval_contract_validated"] == ecart["retrieval_contract_validated"]
    )
    assert (
        etat["staging_vectors_present"]
        == ecart["measured"]["staging_vectors_present"]
    )


def test_le_snapshot_nomme_le_commit_qu_il_evalue(etat):
    """Un snapshot qui ne dit pas ce qu'il a évalué n'est pas opposable."""
    for champ in ("evaluated_ref", "evaluated_head", "main_head"):
        valeur = etat.get(champ)
        assert valeur, f"{champ} absent du snapshot"
        assert valeur != champ, f"{champ} contient son propre nom"
    assert len(etat["evaluated_head"]) == 40
    assert len(etat["main_head"]) == 40


def test_le_markdown_derive_reste_aligne_sur_l_etat(etat):
    rendu = MARKDOWN.read_text(encoding="utf-8")
    attendu = "true" if etat["go_live_ready"] else "false"
    assert f"GO_LIVE_READY={attendu}" in rendu
    for raison in etat["blocking_reasons"]:
        assert raison in rendu, f"raison de refus absente du markdown : {raison}"


def test_aucun_go_live_vert_ne_peut_etre_commite(etat):
    """Un garde-fou de dernier recours, sur l'artefact lui-même."""
    if etat["blocking_reasons"]:
        assert etat["go_live_ready"] is False



#: Les entrées du gate, telles que le gate lui-même les déclare. On les lit
#: chez lui pour que le garde-fou ne puisse pas surveiller une liste figée
#: pendant que le gate en consomme une autre.
def entrees_declarees_par_le_gate() -> tuple[str, ...]:
    source = (RACINE / "scripts/go_live/check_go_live_readiness.py").read_text(
        encoding="utf-8"
    )
    bloc = re.search(r"ENTREES_VERSIONNEES = \(\n(.*?)\n\)", source, re.S)
    assert bloc, "le gate ne déclare plus ses entrées sous ENTREES_VERSIONNEES"
    noms = [ligne.strip().rstrip(",") for ligne in bloc.group(1).splitlines()]
    # Certaines constantes tiennent sur deux lignes (parenthésées par le
    # formateur). Les ignorer ferait croire que le gate ne déclare pas
    # l'entrée, alors qu'il la lit.
    constantes = dict(
        re.findall(r'^([A-Z_]+) = \(?\s*"([^"]+)"\s*\)?$', source, re.M)
    )
    manquantes = [nom for nom in noms if nom not in constantes]
    assert not manquantes, f"constantes d'entrée introuvables : {manquantes}"
    return tuple(constantes[nom] for nom in noms)


def empreinte_du_fichier(chemin: Path) -> str:
    if not chemin.is_file():
        return "ABSENT"
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def entrees_qui_ont_bouge(racine: Path, empreintes: dict[str, str]) -> list[str]:
    """Les entrées dont le contenu ne correspond plus à ce que le snapshot a lu.

    Non vide ⇒ le snapshot décide sur des faits plus vieux que ceux du dépôt.
    C'est exactement la panne survenue deux fois : un rapport source régénéré
    et rendu bloquant, un snapshot resté au lot précédent.
    """
    return sorted(
        relatif
        for relatif, attendue in empreintes.items()
        if empreinte_du_fichier(racine / relatif) != attendue
    )


def test_le_snapshot_publie_l_empreinte_de_ses_entrees(etat):
    empreintes = etat.get("input_digests")
    assert empreintes, (
        "le snapshot ne publie pas l'empreinte de ses entrées : sa fraîcheur "
        "ne serait pas vérifiable"
    )
    attendues = set(entrees_declarees_par_le_gate())
    oubliees = attendues - set(empreintes)
    assert not oubliees, (
        f"le gate lit des entrées dont le snapshot ne publie pas l'empreinte : "
        f"{sorted(oubliees)}"
    )


def test_le_snapshot_n_est_pas_en_retard_sur_ses_entrees(etat):
    """Le garde-fou qui manquait vraiment.

    Une première version comparait `evaluated_head` à HEAD par égalité. C'était
    intenable, et le gate le dit lui-même dans `snapshot_freshness_note` : un
    instantané est produit AVANT le commit qui le porte, donc il nomme toujours
    le parent. Cette version-là ne tenait que tant qu'on ne la lançait pas
    après un commit — et la CI ne la lançait pas du tout.

    Ce qui compte n'est pas que le snapshot nomme HEAD, mais qu'aucune de ses
    entrées n'ait changé depuis qu'il a été calculé.
    """
    bougees = entrees_qui_ont_bouge(RACINE, etat["input_digests"])
    assert not bougees, (
        "snapshot périmé : ces entrées ont changé depuis qu'il a été "
        f"calculé, sans qu'il soit régénéré : {bougees}"
    )


def test_le_snapshot_nomme_un_commit_bien_forme(etat):
    """Le commit évalué reste une trace utile, même s'il ne prouve pas la fraîcheur."""
    assert etat["main_head"] == etat["evaluated_head"] or etat["evaluated_ref"] != "main"
    for champ in ("evaluated_head", "main_head"):
        assert len(etat[champ]) == 40
        assert all(c in "0123456789abcdef" for c in etat[champ])


def test_le_garde_fou_attrape_une_entree_regeneree_apres_coup(tmp_path):
    """Rejoue la panne réelle.

    Sans cette épreuve, rien ne prouve que le garde-fou détecte quoi que ce
    soit : il pourrait ne jamais rien trouver et rester vert pour toujours.
    """
    entree = "docs/reports/go_live/rag_searchability_gap.json"
    (tmp_path / "docs/reports/go_live").mkdir(parents=True)
    cible = tmp_path / entree
    cible.write_text('{"rag_searchability_blocker": false}', encoding="utf-8")
    empreintes = {entree: empreinte_du_fichier(cible)}
    assert entrees_qui_ont_bouge(tmp_path, empreintes) == []

    # Le lot suivant régénère l'entrée et la rend bloquante, mais laisse le
    # snapshot en arrière.
    cible.write_text('{"rag_searchability_blocker": true}', encoding="utf-8")
    assert entrees_qui_ont_bouge(tmp_path, empreintes) == [entree]


def test_une_entree_disparue_n_est_pas_un_silence(tmp_path):
    """Supprimer une entrée ne doit pas rendre le garde-fou muet."""
    entree = "docs/reports/go_live/qualification_blockers.json"
    (tmp_path / "docs/reports/go_live").mkdir(parents=True)
    cible = tmp_path / entree
    cible.write_text("[]", encoding="utf-8")
    empreintes = {entree: empreinte_du_fichier(cible)}
    cible.unlink()
    assert entrees_qui_ont_bouge(tmp_path, empreintes) == [entree]


def test_le_garde_fou_ne_crie_pas_sur_une_sortie_derivee(tmp_path):
    """Le commit qui PORTE le snapshot ne doit pas le déclarer périmé.

    C'est le défaut exact de la version précédente : elle refusait l'état
    normal du dépôt juste après un merge.
    """
    entree = "docs/reports/go_live/rag_searchability_gap.json"
    (tmp_path / "docs/reports/go_live").mkdir(parents=True)
    (tmp_path / entree).write_text("{}", encoding="utf-8")
    empreintes = {entree: empreinte_du_fichier(tmp_path / entree)}
    # Une sortie dérivée change ; elle n'est pas une entrée.
    (tmp_path / "docs/reports/go_live/go_live_readiness_state.json").write_text(
        '{"go_live_ready": false}', encoding="utf-8"
    )
    assert entrees_qui_ont_bouge(tmp_path, empreintes) == []


def test_les_sorties_du_gate_ne_sont_pas_surveillees_comme_des_entrees(etat):
    """Surveiller ses propres sorties rendrait le garde-fou toujours rouge."""
    sorties = {
        "docs/reports/go_live/go_live_readiness_state.json",
        "docs/reports/go_live/blocker_closure_ledger.json",
        "docs/reports/go_live/closure_plan.json",
    }
    assert not (sorties & set(etat["input_digests"]))


def test_les_entrees_surveillees_existent_toutes(etat):
    """Une entrée renommée ne doit pas sortir du périmètre en silence."""
    absentes = [
        relatif
        for relatif, empreinte in etat["input_digests"].items()
        if empreinte == "ABSENT"
    ]
    assert not absentes, (
        f"entrées déclarées mais introuvables : {absentes} — le gate a décidé "
        "sans elles"
    )


def test_aucune_entree_du_gate_n_echappe_a_la_surveillance():
    """Le gate ne doit pas pouvoir lire un fichier hors du périmètre surveillé.

    Sans ceci, ajouter une entrée au gate sans l'ajouter à
    `ENTREES_VERSIONNEES` la rendrait invisible : le snapshot pourrait devenir
    périmé sur elle sans que rien ne le dise.
    """
    source = (RACINE / "scripts/go_live/check_go_live_readiness.py").read_text(
        encoding="utf-8"
    )
    cites = set(
        re.findall(r'"((?:docs|services)/[^"]+\.(?:json|yml))"', source)
    )
    # Ce que le gate PRODUIT, et le reconciliateur qu il invoque en sous-
    # traitance : ni les uns ni l autre ne sont des entrees dont il lit l etat.
    sorties = {
        "docs/reports/go_live/go_live_readiness_state.json",
        "docs/reports/go_live/blocker_closure_ledger.json",
        "docs/reports/go_live/closure_plan.json",
    }
    surveillees = set(entrees_declarees_par_le_gate())
    echappees = cites - sorties - surveillees
    assert not echappees, (
        f"le gate cite des fichiers non surveillés : {sorted(echappees)} — "
        "ajoutez-les à ENTREES_VERSIONNEES ou justifiez leur exclusion"
    )
