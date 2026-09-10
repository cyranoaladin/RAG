"""La pile PDF est un EXTRA de `nexus-release-chain`, jamais une dépendance du cœur.

Le contrôle porte sur les métadonnées RÉELLEMENT PRODUITES par le backend de
construction (PEP 517), pas sur le texte de `pyproject.toml`. Lire le texte
laisserait passer une dépendance introduite par un `dynamic`, un plugin de
build ou une réécriture du backend : le fichier dirait une chose et la roue
installée en dirait une autre.

Pourquoi ce contrôle existe : `release_readiness.py` — l'autorité que le
runtime de lecture importe — n'a besoin d'aucun parseur PDF. L'image
`Dockerfile.ingestor-v2` vérifie d'ailleurs elle-même que `pypdf` en est
absent. Faire entrer la pile PDF dans le cœur du paquet la ferait entrer dans
ce runtime par la porte de derrière, sans qu'aucune allowlist ne le signale.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from email.parser import Parser
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PDF_NAMES = ("pypdf", "nexus-pdf-page-policy", "nexus_pdf_page_policy")


def _built_metadata() -> tuple[list[str], list[str], dict[str, list[str]]]:
    """Construire les métadonnées par le backend déclaré, hors réseau.

    Renvoie (extras déclarés, dépendances du cœur, dépendances par extra).
    """
    from setuptools import build_meta

    workdir = Path(tempfile.mkdtemp(prefix="nexus-release-chain-metadata-"))
    previous = Path.cwd()
    try:
        import os

        os.chdir(PACKAGE_ROOT)
        dist_info = build_meta.prepare_metadata_for_build_wheel(str(workdir))
        metadata = Parser().parsestr((workdir / dist_info / "METADATA").read_text(encoding="utf-8"))
    finally:
        import os

        os.chdir(previous)
        shutil.rmtree(workdir, ignore_errors=True)

    extras = metadata.get_all("Provides-Extra") or []
    core: list[str] = []
    per_extra: dict[str, list[str]] = {name: [] for name in extras}
    for requirement in metadata.get_all("Requires-Dist") or []:
        head, _, marker = requirement.partition(";")
        name = head.strip()
        if 'extra ==' in marker:
            extra = marker.split('extra ==')[1].strip().strip('"').strip("'")
            per_extra.setdefault(extra, []).append(name)
        else:
            core.append(name)
    return extras, core, per_extra


@pytest.fixture(scope="module")
def metadata() -> tuple[list[str], list[str], dict[str, list[str]]]:
    if sys.version_info < (3, 11):  # pragma: no cover - le paquet exige 3.11+
        pytest.skip("métadonnées construites avec le backend déclaré, Python >= 3.11")
    return _built_metadata()


def test_le_coeur_ne_depend_d_aucune_pile_pdf(metadata) -> None:
    """`CORE_REQUIRES_PYPDF=false` — mesuré sur les métadonnées construites."""
    _, core, _ = metadata
    coupables = [r for r in core if any(n in r.lower().replace("_", "-") for n in ("pypdf", "pdf-page-policy"))]
    assert not coupables, (
        "la pile PDF est entrée dans les dépendances du CŒUR de nexus-release-chain : "
        f"{coupables}. Elle doit rester un extra ; le runtime de lecture ne parse aucun PDF."
    )


def test_l_extra_pdf_est_declare_et_porte_la_pile(metadata) -> None:
    """`PDF_EXTRA_DECLARED=true` et l'extra porte bien le foyer du prédicat PDF."""
    extras, _, per_extra = metadata
    assert "pdf" in extras, f"l'extra `pdf` n'est plus déclaré : {extras}"
    porte = [r for r in per_extra.get("pdf", []) if "pdf-page-policy" in r.lower().replace("_", "-")]
    assert porte, f"l'extra `pdf` ne porte plus nexus-pdf-page-policy : {per_extra.get('pdf')}"


def test_la_version_canonique_de_pypdf_a_une_seule_autorite() -> None:
    """`CANONICAL_PYPDF_VERSION` vient du foyer du prédicat, pas d'une constante recopiée."""
    from nexus_pdf_page_policy import CANONICAL_PYPDF_VERSION

    assert CANONICAL_PYPDF_VERSION == "6.14.2"
