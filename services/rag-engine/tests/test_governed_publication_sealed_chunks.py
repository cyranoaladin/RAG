"""ADR-0060 — une release scellée publie exactement les chunks qu'elle scelle.

Le chemin unitaire filtre après découpage les fragments non textuels puis
renumérote. Appliqué à une release scellée, ce filtre publiait un autre jeu que
celui que la release déclare — et rien ne le vérifiait. Sur le chemin scellé,
les chunks publiés sont ceux de la release, contrôlés par leur empreinte, dans
l'ordre ; un écart est un refus.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor.governed_publisher_v2 import (  # noqa: E402
    GovernedPublicationError,
    select_publication_chunks,
)
from ingestor.publication_chunking import PublicationChunk  # noqa: E402

TEXTE = "La photosynthèse transforme l'énergie lumineuse en énergie chimique."
PARASITE = "==== //// ++++ ==== //// ++++"


def _chunk(texte: str) -> PublicationChunk:
    return PublicationChunk(text=texte, page_start=1, page_end=1)


def _sha(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def test_le_chemin_unitaire_filtre_les_fragments_non_textuels() -> None:
    choisis = select_publication_chunks([_chunk(TEXTE), _chunk(PARASITE)], sealed_chunk_sha256=None)
    assert [c.text for c in choisis] == [TEXTE]


def test_le_chemin_scelle_publie_exactement_les_chunks_scelles() -> None:
    scelles = (_sha(TEXTE), _sha(PARASITE))
    choisis = select_publication_chunks(
        [_chunk(TEXTE), _chunk(PARASITE)], sealed_chunk_sha256=scelles
    )
    assert [c.text for c in choisis] == [TEXTE, PARASITE]


def test_un_chunk_manquant_refuse_la_publication_scellee() -> None:
    with pytest.raises(GovernedPublicationError, match="sealed"):
        select_publication_chunks(
            [_chunk(TEXTE)], sealed_chunk_sha256=(_sha(TEXTE), _sha(PARASITE))
        )


def test_un_ordre_different_refuse_la_publication_scellee() -> None:
    with pytest.raises(GovernedPublicationError, match="sealed"):
        select_publication_chunks(
            [_chunk(PARASITE), _chunk(TEXTE)], sealed_chunk_sha256=(_sha(TEXTE), _sha(PARASITE))
        )


def test_une_liste_scellee_vide_est_refusee() -> None:
    with pytest.raises(GovernedPublicationError):
        select_publication_chunks([_chunk(TEXTE)], sealed_chunk_sha256=())
