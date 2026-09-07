"""Le parseur d'identifiants officiels : ce qu'il refuse de deviner.

Une citation réglementaire explicite dans un document — « Bulletin officiel
spécial n° 1 du 22 janvier 2019 » — est une preuve : le document nomme le texte
qu'il met en œuvre. La ressemblance de vocabulaire, le nom du chapitre, l'année
de publication, le slug ou le répertoire n'en sont pas.

Le défaut d'origine : ``2026-2027`` accepté comme version de programme. Une
année scolaire n'est pas une référence réglementaire, et l'accepter avait failli
déclarer 138 documents incompatibles avec le programme en vigueur alors que
rien n'établissait lequel ils servent.
"""

from __future__ import annotations

import pytest

from rag_pedago.governance.reference_programme import (
    PARSER_ID,
    citations_officielles,
    est_reference_canonique,
    references_canoniques,
    resoudre,
)

AUTORITES = {
    "BOEN_special_1_2019-01-22",
    "BOEN_special_8_2019-07-25",
    "BOEN_special_11_2018-07-26_aj_2020",
    "BOEN_14_2026-04-02_MENE2602917A",
    "BOEN_14_2026-04-02_MENE2602914A",
    "BOEN_special_8_2019-07-25_MENE1921266A_MENE2208320A",
}


# --- la forme canonique -----------------------------------------------


@pytest.mark.parametrize(
    "valide",
    [
        "BOEN_special_1_2019-01-22",
        "BOEN_special_8_2019-07-25",
        "BOEN_14_2026-04-02_MENE2602917A",
        "BOEN_special_11_2018-07-26_aj_2020",
    ],
)
def test_une_reference_canonique_est_reconnue(valide) -> None:
    assert est_reference_canonique(valide)


@pytest.mark.parametrize(
    "invalide",
    [
        "2026-2027",                 # LE défaut d'origine : une année scolaire
        "2025-2026",
        "2026",
        "EDUSCOL_CORPUS_20260808",   # un identifiant de corpus
        "BOEN_",                     # un préfixe sans texte désigné
        "BOEN_special",
        "BOEN_special_1",            # sans date : ne désigne aucun texte
        "BOEN_special_1_2019",
        "boen quelque chose",
        "",
        None,
        42,
    ],
)
def test_ce_qui_n_est_pas_une_reference_est_refuse(invalide) -> None:
    assert not est_reference_canonique(invalide)
    assert references_canoniques(invalide) == []


def test_une_liste_est_une_cardinalite_pas_un_autre_type() -> None:
    """Exiger une chaîne rejetait des liaisons parfaitement établies."""
    assert references_canoniques(["BOEN_special_1_2019-01-22"]) == [
        "BOEN_special_1_2019-01-22"
    ]
    assert references_canoniques(
        ["2026-2027", "BOEN_special_8_2019-07-25"]
    ) == ["BOEN_special_8_2019-07-25"]
    assert references_canoniques(["2026-2027", "EDUSCOL_CORPUS_20260808"]) == []


def test_plusieurs_references_valides_sont_toutes_rendues() -> None:
    """MULTI_PROGRAM_REFERENCE : ne jamais choisir arbitrairement la première."""
    assert references_canoniques(
        ["BOEN_special_1_2019-01-22", "BOEN_special_8_2019-07-25"]
    ) == ["BOEN_special_1_2019-01-22", "BOEN_special_8_2019-07-25"]


# --- les citations dans le texte --------------------------------------


@pytest.mark.parametrize(
    "texte,attendu",
    [
        ("Bulletin officiel spécial n° 1 du 22 janvier 2019", "BOEN_special_1_2019-01-22"),
        ("BO spécial n°8 du 25 juillet 2019", "BOEN_special_8_2019-07-25"),
        ("B.O. n° 14 du 2 avril 2026", "BOEN_14_2026-04-02"),
        ("BO spécial n° 1 du 22-1-2019", "BOEN_special_1_2019-01-22"),
        ("bulletin officiel special no 8 du 25 juillet 2019", "BOEN_special_8_2019-07-25"),
        ("BO n° 3 du 1er février 2021", "BOEN_3_2021-02-01"),
    ],
)
def test_une_citation_explicite_est_normalisee(texte, attendu) -> None:
    assert citations_officielles(f"Programme publié au {texte}, applicable.") == [attendu]


@pytest.mark.parametrize(
    "texte",
    [
        "année scolaire 2026-2027",
        "corpus EDUSCOL_CORPUS_20260808",
        "ce document traite du programme de mathématiques",
        "publié en 2019",
        "voir le bulletin officiel",           # sans numéro ni date
        "BO spécial du 25 juillet 2019",       # sans numéro
        "BO spécial n° 8",                     # sans date
        "chapitre 8, page 2019",
    ],
)
def test_ce_qui_n_est_pas_une_citation_n_est_pas_devine(texte) -> None:
    """Une forme non reconnue est absente du résultat, jamais approximée."""
    assert citations_officielles(texte) == []


def test_les_citations_sont_dedupliquees_et_ordonnees() -> None:
    texte = (
        "Voir le BO spécial n° 1 du 22 janvier 2019. "
        "Conformément au BO spécial n°8 du 25 juillet 2019. "
        "Rappel : bulletin officiel spécial n° 1 du 22 janvier 2019."
    )
    assert citations_officielles(texte) == [
        "BOEN_special_1_2019-01-22",
        "BOEN_special_8_2019-07-25",
    ]


def test_une_date_impossible_n_est_pas_normalisee() -> None:
    assert citations_officielles("BO spécial n° 1 du 45-13-2019") == []


# --- la résolution vers l'autorité courante ---------------------------


def test_une_citation_qui_designe_deux_textes_est_ambigue() -> None:
    """`BOEN_14_2026-04-02` préfixe deux entrées de l'autorité.

    Choisir la plus courte ou la première ferait décider au parseur ce qui
    relève de l'autorité — et une citation qui désigne deux textes n'en
    désigne aucun."""
    verdict, candidats = resoudre("BOEN_14_2026-04-02", AUTORITES)
    assert verdict == "AMBIGUOUS"
    assert candidats == [
        "BOEN_14_2026-04-02_MENE2602914A",
        "BOEN_14_2026-04-02_MENE2602917A",
    ]


def test_une_citation_exacte_se_resout() -> None:
    assert resoudre("BOEN_special_1_2019-01-22", AUTORITES) == (
        "RESOLVED",
        ["BOEN_special_1_2019-01-22"],
    )


def test_une_citation_absente_de_l_autorite_reste_inconnue() -> None:
    """UNKNOWN, jamais INCOMPATIBLE : ne pas trouver n'est pas réfuter."""
    assert resoudre("BOEN_special_3_2020-01-01", AUTORITES) == ("UNKNOWN", [])


def test_un_prefixe_unique_se_resout_vers_son_unique_candidat() -> None:
    assert resoudre("BOEN_special_11_2018-07-26", AUTORITES) == (
        "RESOLVED",
        ["BOEN_special_11_2018-07-26_aj_2020"],
    )


def test_le_parseur_est_versionne() -> None:
    """Deux corpus analysés sous des parseurs différents ne sont pas
    comparables : l'identifiant doit entrer dans la preuve."""
    assert PARSER_ID == "NEXUS-OFFICIAL-PROGRAM-REFERENCE-PARSER-V1"
