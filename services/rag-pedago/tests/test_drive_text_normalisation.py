"""La normalisation textuelle : ce qu'elle retire, et ce qu'elle ne touche pas.

`pypdf` émet U+0000 pour un glyphe sans correspondance Unicode. Mesuré sur le
corpus gouverné, il s'agit systématiquement d'un appel de note de bas de page.
Le caractère ne porte aucune information — et PostgreSQL refuse de le stocker
en colonne `text`, ce qui faisait échouer l'ingestion de documents par ailleurs
parfaitement lisibles.

Ce que ces épreuves refusent : qu'une normalisation muette rende le découpage
irreproductible, qu'elle touche autre chose que la représentation textuelle,
ou qu'elle modifie un document qui n'en a pas besoin.
"""

from __future__ import annotations

import hashlib

from rag_pedago.governance.drive_extraction import (
    TEXT_NORMALISATION_ID,
    normalise_texte_page,
)


def test_le_nul_est_retire_et_compte() -> None:
    texte = "les vérités que l'on vous cache 1. \nN\x001. Œuvres de Jean Meslier"
    normalise, retires = normalise_texte_page(texte)
    assert "\x00" not in normalise
    assert retires == 1
    assert normalise == "les vérités que l'on vous cache 1. \nN1. Œuvres de Jean Meslier"


def test_un_texte_sans_nul_n_est_pas_touche() -> None:
    """Une normalisation qui réécrirait un texte sain changerait l'empreinte
    de ses chunks sans raison, et rendrait incomparables deux corpus dont un
    seul contient l'artefact."""
    texte = "Un texte parfaitement ordinaire, avec accents : é, à, ç."
    normalise, retires = normalise_texte_page(texte)
    assert normalise is texte or normalise == texte
    assert retires == 0


def test_la_normalisation_est_deterministe() -> None:
    """Deux exécutions sur les mêmes octets rendent le même texte — sans quoi
    le découpage ne serait reproductible que par hasard."""
    texte = "a\x00b\x00c"
    premier = normalise_texte_page(texte)
    second = normalise_texte_page(texte)
    assert premier == second == ("abc", 2)
    assert hashlib.sha256(premier[0].encode()).hexdigest() == (
        hashlib.sha256(second[0].encode()).hexdigest()
    )


def test_seul_le_nul_est_retire() -> None:
    """La normalisation a un périmètre NOMMÉ. Retirer d'autres caractères de
    contrôle — sauts de ligne, tabulations — détruirait la structure de page
    dont le découpage dépend."""
    texte = "ligne\nsuite\ttabulée\r\nfin\x00"
    normalise, retires = normalise_texte_page(texte)
    assert normalise == "ligne\nsuite\ttabulée\r\nfin"
    assert retires == 1


def test_la_normalisation_porte_une_identite_versionnee() -> None:
    """Deux corpus découpés sous des normalisations différentes ne sont pas
    comparables. L'identité existe pour être attestée, pas décorative."""
    assert TEXT_NORMALISATION_ID == "NEXUS-DRIVE-TEXT-NORMALISATION-V1"
