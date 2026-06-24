from __future__ import annotations

import pathlib

import pytest
import yaml
from pydantic import ValidationError

from schema.taxonomy import TaxonomySpec

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_minimal_maths_terminale_specialite_taxonomy_is_valid() -> None:
    path = ROOT / "taxonomy" / "maths" / "terminale_specialite.yml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))

    taxonomy = TaxonomySpec.model_validate(payload)

    assert taxonomy.id == "maths_terminale_specialite"
    assert taxonomy.matiere == "mathematiques"
    assert "raisonner" in taxonomy.competences
    assert "suites" in taxonomy.known_notion_ids


def test_taxonomy_with_empty_notion_is_rejected() -> None:
    payload = {
        "id": "bad_taxonomy",
        "matiere": "mathematiques",
        "niveau": "terminale",
        "voie": "generale",
        "statut_enseignement": "specialite",
        "programme_version": "test",
        "themes": [
            {
                "id": "analyse",
                "label": "Analyse",
                "notions": [{"id": "", "label": "Notion vide"}],
            }
        ],
        "competences": ["raisonner"],
    }

    with pytest.raises(ValidationError):
        TaxonomySpec.model_validate(payload)

