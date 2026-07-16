"""Contrat statique de couverture métier de la page Ingestion v2."""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[1]
APP_V2 = ENGINE_ROOT / "src" / "ui" / "app_v2.py"
CATALOGUE = ENGINE_ROOT / "configs" / "rag_collections.yml"


def _collections() -> dict[str, dict[str, object]]:
    return yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))["collections"]


def _catalogue_parcours_label(entry: dict[str, object]) -> str:
    tree = ast.parse(APP_V2.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_catalogue_parcours_label"
    )
    namespace: dict[str, object] = {"VOIE_LABELS": {"gen": "Générale", "stmg": "STMG"}}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(APP_V2), "exec"), namespace)
    return namespace["_catalogue_parcours_label"](entry)  # type: ignore[operator]


def test_catalogue_declares_the_v1_school_axes() -> None:
    collections = _collections().values()

    assert {"troisieme", "seconde", "premiere", "terminale"} <= {
        item.get("niveau") for item in collections
    }
    assert {"gen", "stmg"} <= {item.get("voie") for item in collections}
    assert any(item.get("voie") is None for item in collections)
    assert {"education", "exam", "quarantine"} <= {
        item.get("domain") for item in collections
    }
    assert {"tronc_commun", "specialite", "option", "examen", "remediation"} <= {
        item.get("statut") for item in collections
    }


def test_exam_catalogue_keeps_declared_voie_in_parcours_label() -> None:
    assert _catalogue_parcours_label(
        {"name": "rag_nexus_exams_bac_general", "domain": "exam", "voie": "gen"}
    ) == "Générale"


def test_catalogue_declares_all_required_subjects_and_transversal_paths() -> None:
    collections = _collections().values()
    required_subjects = {
        "maths", "francais", "histoire_geo", "nsi", "physique_chimie", "svt",
        "ses", "philosophie", "snt", "droit_economie", "msdgn", "grand_oral",
        "exams", "dnb", "candidats_libres",
    }

    assert required_subjects <= {item.get("matiere") for item in collections}


def test_ingestion_renders_a_filterable_full_catalogue_from_catalogue_v2() -> None:
    content = APP_V2.read_text(encoding="utf-8")

    for label in (
        "Catalogue d’ingestion complet",
        "Niveau",
        "Voie / parcours",
        "Matière",
        "Statut",
        "Domaine",
        "Instanciée",
        "Ingestion activée",
        "Retrievable",
        "Raison",
    ):
        assert label in content

    assert "ingestion_catalogue = collections" in content
    assert "catalogue_rows" in content
    assert "ingestion_enabled_reason" in content


def test_quarantine_is_available_as_a_catalogue_derived_status_filter() -> None:
    content = APP_V2.read_text(encoding="utf-8")

    assert 'if c.get("domain") == "quarantine"' in content
    assert 'return "Quarantaine"' in content


def test_full_catalogue_is_not_restricted_to_ingestion_enabled_targets() -> None:
    content = APP_V2.read_text(encoding="utf-8")

    assert 'ingestion_catalogue = [c for c in collections if c.get("ingestion_enabled")]' not in content
    assert "ingestion_targets = [c for c in collections if c.get(\"ingestion_enabled\")]" in content


def test_ingestion_keeps_v2_routes_and_excludes_legacy_routes() -> None:
    content = APP_V2.read_text(encoding="utf-8")

    for route in ("/catalogue/v2", "/ingest/v2/upload-files", "/ingest/v2/urls"):
        assert route in content
    for forbidden in (
        "/stats",
        "/ingest/upload-files",
        "/ingest/urls",
        "/ingest/drive",
        "http://ingestor:8001",
    ):
        assert forbidden not in content
