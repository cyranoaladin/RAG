from __future__ import annotations

import pathlib

import yaml

from schema.taxonomy import TaxonomySpec


ROOT = pathlib.Path(__file__).resolve().parents[2]


def load_taxonomy(relative_path: str) -> TaxonomySpec:
    payload = yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8"))
    return TaxonomySpec.model_validate(payload)


def load_common_competences() -> set[str]:
    payload = yaml.safe_load(
        (ROOT / "taxonomy/common/competences_transversales.yml").read_text(encoding="utf-8")
    )
    return set(payload["competences"])


def test_maths_terminale_specialite_contains_required_notion_ids() -> None:
    taxonomy = load_taxonomy("taxonomy/maths/terminale_specialite.yml")

    expected = {
        "recurrence",
        "limites_de_suites",
        "suites_monotones",
        "suites_geometriques",
        "raisonnement_par_recurrence",
        "asymptotes",
        "fonction_exponentielle",
        "fonction_logarithme",
        "integrales",
        "equations_differentielles_y_prime_ay_plus_b",
        "independance",
        "concentration",
        "geometrie_espace_vecteurs",
        "representations_parametriques",
        "algorithmique_python",
    }

    assert expected <= taxonomy.known_notion_ids
    assert all(notion_id == notion_id.strip() for notion_id in taxonomy.known_notion_ids)


def test_nsi_terminale_contains_required_notion_ids() -> None:
    taxonomy = load_taxonomy("taxonomy/nsi/terminale.yml")

    expected = {
        "listes",
        "piles",
        "files",
        "arbres",
        "graphes",
        "dictionnaires",
        "recursivite",
        "diviser_pour_regner",
        "programmation_dynamique",
        "modele_relationnel",
        "sql",
        "jointures",
        "processus",
        "protocoles",
        "routage",
        "poo",
        "classes",
        "invariants",
    }

    assert expected <= taxonomy.known_notion_ids
    assert all(notion_id == notion_id.strip() for notion_id in taxonomy.known_notion_ids)


def test_taxonomy_competences_are_declared_common_competences() -> None:
    common_competences = load_common_competences()

    for path in ["taxonomy/maths/terminale_specialite.yml", "taxonomy/nsi/terminale.yml"]:
        taxonomy = load_taxonomy(path)
        assert set(taxonomy.competences) <= common_competences

