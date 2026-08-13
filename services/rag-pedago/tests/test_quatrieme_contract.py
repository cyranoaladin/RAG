from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
TAXONOMY_ROOT = SERVICE_ROOT / "taxonomy"
LEVELS_PATH = TAXONOMY_ROOT / "common" / "niveaux.yml"
INDEX_PATH = REPO_ROOT / "corpus" / "College" / "Quatrieme" / "_index.yml"
PROGRAMME_VERSION = "BOEN_special_11_2018-07-26_aj_2020"


def _load_yaml(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_quatrieme_taxonomies_are_exact_and_current_for_2026_2027() -> None:
    expected = {
        "maths/quatrieme.yml": ("maths", "maths_quatrieme"),
        "francais/quatrieme.yml": ("francais", "francais_quatrieme"),
    }

    for relative_path, (matiere, taxonomy_id) in expected.items():
        taxonomy = _load_yaml(TAXONOMY_ROOT / relative_path)
        assert taxonomy["id"] == taxonomy_id
        assert taxonomy["matiere"] == matiere
        assert taxonomy["niveau"] == "quatrieme"
        assert taxonomy["voie"] == "college"
        assert taxonomy["statut_enseignement"] == "tronc_commun"
        assert taxonomy["programme_version"] == PROGRAMME_VERSION
        assert taxonomy["themes"]
        assert taxonomy["competences"]


def test_quatrieme_is_declared_in_common_taxonomy_levels() -> None:
    levels = _load_yaml(LEVELS_PATH)

    assert {
        "id": "quatrieme",
        "label": "Quatrieme",
        "cycle": "cycle4",
    } in levels["levels"]


def test_quatrieme_programme_index_is_closed_and_exact() -> None:
    index = _load_yaml(INDEX_PATH)

    assert index["index_version"] == "1.0"
    assert index["niveau"] == "quatrieme"
    assert index["voie"] == "college"
    assert index["school_year"] == "2026-2027"
    assert index["programme_version"] == PROGRAMME_VERSION
    assert index["fiches"] == [
        {
            "fichier": "C4_FRANCAIS.md",
            "matiere": "francais",
            "statut_enseignement": "tronc_commun",
            "collection_cible": "rag_nexus_francais_quatrieme_tc",
            "taxonomy_file": "francais/quatrieme.yml",
            "programme_version": PROGRAMME_VERSION,
        },
        {
            "fichier": "C4_MATHEMATIQUES.md",
            "matiere": "maths",
            "statut_enseignement": "tronc_commun",
            "collection_cible": "rag_nexus_maths_quatrieme_tc",
            "taxonomy_file": "maths/quatrieme.yml",
            "programme_version": PROGRAMME_VERSION,
        },
    ]


def test_quatrieme_programme_version_has_no_fallback() -> None:
    index = _load_yaml(INDEX_PATH)
    versions = {
        str(fiche["programme_version"])
        for fiche in index["fiches"]
    }

    assert versions == {PROGRAMME_VERSION}
