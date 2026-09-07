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


# --- l'applicabilité n'est pas la date de publication -----------------


class TestLApplicabiliteNeSeDeduitPasDeLaDate:
    """Le défaut que ce groupe interdit : « le BO le plus récent gagne ».

    Cas réel. Le BO n° 14 du 2 avril 2026 porte DEUX programmes de
    mathématiques :

        maths spécialité Première  → applicable à la rentrée 2026-2027
        maths spécialité Terminale → applicable à la rentrée 2027-2028

    Au 7 septembre 2026, la Première suit donc le nouveau programme pendant que
    la Terminale suit encore le précédent. Un moteur qui choisit la publication
    la plus récente attribue le nouveau programme aux deux — et déclare
    incompatible tout document de Terminale conforme au programme en vigueur.

    `effective_from_school_year` est donc obligatoire, et distinct de
    `bulletin_date` : une date de publication ne dit pas quand un texte
    s'applique.
    """

    #: Une autorité d'épreuve, portant la distinction que le cas réel impose.
    AUTORITES = [
        {
            "niveau": "premiere", "matiere": "maths",
            "programme_version": "BOEN_14_2026-04-02_MENE2602917A",
            "bulletin_date": "2026-04-02",
            "effective_from_school_year": "2026-2027",
        },
        {
            "niveau": "terminale", "matiere": "maths",
            "programme_version": "BOEN_14_2026-04-02_MENE2602914A",
            "bulletin_date": "2026-04-02",
            "effective_from_school_year": "2027-2028",
        },
        {
            "niveau": "terminale", "matiere": "maths",
            "programme_version": "BOEN_special_8_2019-07-25",
            "bulletin_date": "2019-07-25",
            "effective_from_school_year": "2020-2021",
        },
    ]

    @staticmethod
    def resoudre_courant(niveau, matiere, annee_scolaire, autorites):
        """Le programme applicable à CE scope pour CETTE année scolaire.

        Rend ``(verdict, entrées)``. ``MULTIPLE`` est un refus de gouvernance,
        pas un choix par date ni par ordre de fichier."""
        applicables = [
            a for a in autorites
            if a["niveau"] == niveau
            and a["matiere"] == matiere
            and a["effective_from_school_year"] <= annee_scolaire
        ]
        if not applicables:
            return "NONE", []
        # Plusieurs textes déjà en vigueur : sans chaîne de supersession
        # explicite, on ne tranche pas — le plus récent n'est pas
        # automatiquement celui qui s'applique.
        if len(applicables) > 1:
            return "MULTIPLE", applicables
        return "EXACTLY_ONE", applicables

    def test_la_premiere_suit_le_nouveau_programme_en_2026_2027(self) -> None:
        verdict, entrees = self.resoudre_courant(
            "premiere", "maths", "2026-2027", self.AUTORITES
        )
        assert verdict == "EXACTLY_ONE"
        assert entrees[0]["programme_version"] == "BOEN_14_2026-04-02_MENE2602917A"

    def test_la_terminale_ne_suit_PAS_encore_le_nouveau_en_2026_2027(self) -> None:
        """LE mutant. Choisir « le BO le plus récent » donnerait ici le
        programme de 2026, applicable seulement en 2027-2028."""
        verdict, entrees = self.resoudre_courant(
            "terminale", "maths", "2026-2027", self.AUTORITES
        )
        assert verdict == "EXACTLY_ONE"
        assert entrees[0]["programme_version"] == "BOEN_special_8_2019-07-25"
        assert entrees[0]["bulletin_date"] < "2026-04-02", (
            "le texte applicable est PLUS ANCIEN que le plus récemment publié"
        )

    def test_le_nouveau_programme_de_terminale_devient_applicable_en_2027_2028(
        self,
    ) -> None:
        """Deux textes en vigueur, aucune chaîne de supersession déclarée :
        c'est un refus de gouvernance, pas un arbitrage par date."""
        verdict, entrees = self.resoudre_courant(
            "terminale", "maths", "2027-2028", self.AUTORITES
        )
        assert verdict == "MULTIPLE"
        assert {e["programme_version"] for e in entrees} == {
            "BOEN_14_2026-04-02_MENE2602914A",
            "BOEN_special_8_2019-07-25",
        }

    def test_un_scope_sans_autorite_rend_none_jamais_un_repli(self) -> None:
        assert self.resoudre_courant("terminale", "danse", "2026-2027", self.AUTORITES) == (
            "NONE",
            [],
        )

    def test_choisir_la_publication_la_plus_recente_serait_faux(self) -> None:
        """La règle naïve, exécutée, donne un résultat que l'épreuve refuse."""
        naif = max(
            (a for a in self.AUTORITES if a["niveau"] == "terminale" and a["matiere"] == "maths"),
            key=lambda a: a["bulletin_date"],
        )
        correct, entrees = self.resoudre_courant(
            "terminale", "maths", "2026-2027", self.AUTORITES
        )
        assert naif["programme_version"] != entrees[0]["programme_version"], (
            "la règle naïve et la règle correcte doivent diverger sur ce cas"
        )

    def test_la_date_de_bulletin_ne_suffit_jamais(self) -> None:
        """`effective_from_school_year` est obligatoire dans le schéma."""
        for autorite in self.AUTORITES:
            assert "effective_from_school_year" in autorite
            assert autorite["effective_from_school_year"] != autorite["bulletin_date"]
