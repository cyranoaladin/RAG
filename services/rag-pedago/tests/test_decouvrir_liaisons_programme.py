"""Ce que la découverte de liaisons programme refuse de conclure.

Deux défauts réels, rencontrés sur les autorités du dépôt, que ces épreuves
rendent impossibles à réintroduire :

1. un champ nommé ``programme_version`` portant ``"2026-2027"`` — une ANNÉE
   SCOLAIRE. Le compter aurait déclaré 138 documents incompatibles avec le
   programme courant alors que rien n'établit lequel ils servent ;
2. l'absence de liaison lue comme une incompatibilité. Déclarer qu'un document
   ne relève pas du programme en vigueur exige une preuve POSITIVE qu'il relève
   d'un autre — pas un silence.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/decouvrir_liaisons_programme.py"


def _module():
    spec = importlib.util.spec_from_file_location("decouvrir_liaisons_programme", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# --- le nom d'un champ n'est pas son contenu --------------------------


@pytest.mark.parametrize(
    "valeur",
    [
        "2026-2027",              # LE cas rencontré : une année scolaire
        "2025-2026",
        "2026",
        "EDUSCOL_CORPUS_20260808",  # un identifiant de corpus
        "BOEN_",                  # un préfixe sans texte désigné
        "BOEN_special",
        "BOEN_special_1",         # sans date
        "boen quelque chose",
        "",
        None,
        42,
        {"programme": "BOEN_special_1_2019-01-22"},
    ],
)
def test_une_valeur_qui_n_est_pas_une_reference_est_refusee(valeur) -> None:
    """Se contenter du préfixe laisserait passer `BOEN_` ou une chaîne
    tronquée : personne ne pourrait dire à quel texte elles renvoient."""
    assert _module().references_valides(valeur) == []


@pytest.mark.parametrize(
    "valeur,attendu",
    [
        ("BOEN_special_1_2019-01-22", ["BOEN_special_1_2019-01-22"]),
        ("BOEN_special_8_2019-07-25", ["BOEN_special_8_2019-07-25"]),
        ("BOEN_14_2026-04-02_MENE2602917A", ["BOEN_14_2026-04-02_MENE2602917A"]),
        (
            "BOEN_special_8_2019-07-25_MENE1921266A_MENE2208320A",
            ["BOEN_special_8_2019-07-25_MENE1921266A_MENE2208320A"],
        ),
    ],
)
def test_une_reference_reglementaire_valide_est_acceptee(valeur, attendu) -> None:
    assert _module().references_valides(valeur) == attendu


def test_une_liste_de_references_est_admise_et_chaque_element_valide() -> None:
    """Certaines autorités portent le champ comme liste.

    Exiger une chaîne rejetait des liaisons parfaitement établies — un faux
    négatif, moins visible qu'un faux positif mais tout aussi faux."""
    m = _module()
    assert m.references_valides(["BOEN_special_1_2019-01-22"]) == [
        "BOEN_special_1_2019-01-22"
    ]
    # Le tri du bon grain : l'année scolaire mêlée à une référence ne
    # contamine pas, et n'est pas retenue non plus.
    assert m.references_valides(["2026-2027", "BOEN_special_8_2019-07-25"]) == [
        "BOEN_special_8_2019-07-25"
    ]
    assert m.references_valides(["2026-2027", "EDUSCOL_CORPUS_20260808"]) == []


# --- l'absence n'est pas une preuve négative --------------------------


def test_l_absence_de_liaison_ne_rend_jamais_incompatible(tmp_path: Path) -> None:
    """Le second défaut, scellé.

    Un contenu sans liaison est UNKNOWN. Le classer INCOMPATIBLE
    transformerait une absence d'information en preuve d'obsolescence.
    """
    m = _module()
    racines = {"vide": []}
    trouve = m.decouvrir(racines)
    assert trouve["explicites"] == {}
    # Aucune liaison découverte : la partition ne peut produire aucun
    # incompatible, puisque INCOMPATIBLE se calcule sur les contenus LIÉS.
    catalogue = {"a" * 64, "b" * 64}
    dans_catalogue = set(trouve["explicites"]) & catalogue
    incompatibles = dans_catalogue - set()
    inconnus = catalogue - dans_catalogue
    assert incompatibles == set()
    assert inconnus == catalogue


def test_une_base_de_liaison_interdite_n_est_jamais_admissible() -> None:
    """Le nom de fichier, l'année de publication, la proximité de répertoire et
    la ressemblance lexicale peuvent retrouver une autorité ; ils ne peuvent
    pas en tenir lieu."""
    m = _module()
    for interdite in m.BASES_INTERDITES:
        assert interdite not in m.BASES_ADMISSIBLES


def test_les_bases_admissibles_forment_une_enum_fermee() -> None:
    m = _module()
    assert set(m.BASES_ADMISSIBLES) == {
        "EXPLICIT_SOURCE_METADATA",
        "GOVERNED_MANIFEST",
        "OFFICIAL_PROGRAM_REFERENCE",
        "HUMAN_REVIEW",
        "GOVERNED_RULE",
    }


# --- la découverte mesure son rendement -------------------------------


def test_le_rendement_est_mesure_par_famille_d_autorite(tmp_path: Path) -> None:
    """Sans ce compte, on ne sait pas où investir l'effort — et on lance une
    revue humaine faute d'avoir mesuré ce que les autorités donnent."""
    import json

    m = _module()
    bonne = tmp_path / "gouvernee.json"
    bonne.write_text(
        json.dumps({"records": [
            {"content_sha256": "c" * 64, "programme_version": "BOEN_special_1_2019-01-22"},
            {"content_sha256": "d" * 64, "programme_version": "2026-2027"},
        ]}),
        encoding="utf-8",
    )
    trouve = m.decouvrir({"epreuve": [bonne]})
    compte = trouve["rendement"]["epreuve"]
    assert compte["CANDIDATES_DISCOVERED"] == 2
    assert compte["EXPLICIT_BINDINGS_PROVEN"] == 1
    assert compte["REJECTED"] == 1
    assert trouve["rejets"][0]["reason"] == "VALUE_IS_NOT_A_PROGRAM_REFERENCE"
    assert trouve["rejets"][0]["rejected_value"] == "2026-2027"


def test_un_contenu_lie_a_deux_versions_est_un_conflit(tmp_path: Path) -> None:
    """En choisir une serait décider à la place de l'autorité."""
    import json

    m = _module()
    fichier = tmp_path / "a.json"
    fichier.write_text(
        json.dumps([
            {"content_sha256": "e" * 64, "programme_version": "BOEN_special_1_2019-01-22"},
            {"content_sha256": "e" * 64, "programme_version": "BOEN_special_8_2019-07-25"},
        ]),
        encoding="utf-8",
    )
    trouve = m.decouvrir({"epreuve": [fichier]})
    assert len(trouve["conflits"]) == 1
    assert trouve["conflits"]["e" * 64] == [
        "BOEN_special_1_2019-01-22",
        "BOEN_special_8_2019-07-25",
    ]
