"""ADR-0059 §6 : l'entrée de revue canonique porte EXACTEMENT la population
de la release, déclarée par fichier et par empreinte — jamais « tout ce que
le run a détecté »."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/exporter_entree_revue_canonique.py"
A, B, C = "a" * 64, "b" * 64, "c" * 64


def _module():
    spec = importlib.util.spec_from_file_location("exporter_entree_revue_canonique", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _digest(shas: list[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(shas)) + "\n").encode()).hexdigest()


def _fichier(tmp_path: Path, lignes: list[str]) -> Path:
    chemin = tmp_path / "population.txt"
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return chemin


def test_la_population_declaree_remplace_les_detections(tmp_path: Path) -> None:
    exporteur = _module()
    chemin = _fichier(tmp_path, [B, A, C])

    population = exporteur.choisir_population(
        detectes=[A], content_set=chemin, content_set_sha256=_digest([A, B, C])
    )

    assert population == [A, B, C]


def test_sans_population_declaree_le_comportement_historique_reste(tmp_path: Path) -> None:
    exporteur = _module()
    assert exporteur.choisir_population(detectes=[B, A], content_set=None, content_set_sha256=None) == [A, B]


@pytest.mark.parametrize(
    ("lignes", "motif"),
    [
        ([A, A], "dupliqu"),
        ([A, "pas-un-sha"], "empreinte"),
        ([A, B], "diffère"),
    ],
)
def test_une_population_mal_formee_ou_d_une_autre_empreinte_est_refusee(
    tmp_path: Path, lignes: list[str], motif: str
) -> None:
    exporteur = _module()
    with pytest.raises(exporteur.CanonicalReviewInputError, match=motif):
        exporteur.choisir_population(
            detectes=[A], content_set=_fichier(tmp_path, lignes), content_set_sha256=_digest([A])
        )


def test_une_population_sans_empreinte_attendue_est_refusee(tmp_path: Path) -> None:
    exporteur = _module()
    with pytest.raises(exporteur.CanonicalReviewInputError, match="empreinte attendue"):
        exporteur.choisir_population(
            detectes=[A], content_set=_fichier(tmp_path, [A]), content_set_sha256=None
        )


def test_une_detection_hors_population_est_signalee_sans_etre_exportee(tmp_path: Path) -> None:
    """Une détection du run hors release n'entre pas dans la revue de la
    release : elle n'est pas exportée."""
    exporteur = _module()
    population = exporteur.choisir_population(
        detectes=[A, C], content_set=_fichier(tmp_path, [A, B]), content_set_sha256=_digest([A, B])
    )
    assert C not in population
