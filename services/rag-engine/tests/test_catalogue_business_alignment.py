"""Red tests — Catalogue v2 business alignment.

Tests that the backend catalogue endpoint returns the full
business catalogue (declared + instanciated + retrievable).
"""
from __future__ import annotations

from pathlib import Path

import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[1]
CONFIGS_DIR = ENGINE_ROOT / "configs"
RAG_COLLECTIONS = CONFIGS_DIR / "rag_collections.yml"


def _load_catalogue() -> dict:
    return yaml.safe_load(RAG_COLLECTIONS.read_text(encoding="utf-8"))


def test_catalogue_has_version_2():
    cat = _load_catalogue()
    assert cat.get("version") == 2


def test_catalogue_has_collections():
    cat = _load_catalogue()
    assert "collections" in cat
    assert len(cat["collections"]) >= 30, (
        f"Expected at least 30 declared collections, got {len(cat['collections'])}"
    )


def test_catalogue_has_metadata_required():
    cat = _load_catalogue()
    required = cat.get("metadata_required", [])
    expected = [
        "domain", "audience", "niveau", "voie", "matiere",
        "statut_enseignement", "type_doc", "source_kind", "rights",
        "review_status", "source_label", "source_uri",
        "doc_id", "chunk_id", "chunk_sha256",
    ]
    for field in expected:
        assert field in required, f"metadata_required missing: {field}"


def test_catalogue_domains():
    cat = _load_catalogue()
    domains = cat.get("domains", {})
    assert "education" in domains
    assert "exam" in domains
    assert "quarantine" in domains
    assert domains["quarantine"].get("retrievable") is False


def test_instanciated_collections():
    cat = _load_catalogue()
    cols = cat["collections"]
    instanciated = [n for n, d in cols.items() if d.get("instanciee") is True]
    # At least NSI premiere + terminale + quarantine
    assert len(instanciated) >= 3, (
        f"Expected at least 3 instanciated collections, got {instanciated}"
    )


def test_quarantine_is_instanciated_but_not_retrievable():
    cat = _load_catalogue()
    q = cat["collections"].get("rag_nexus_quarantine")
    assert q is not None
    assert q.get("instanciee") is True
    assert q.get("domain") == "quarantine"
    domains = cat.get("domains", {})
    assert domains.get("quarantine", {}).get("retrievable") is False


def test_all_education_collections_have_required_fields():
    cat = _load_catalogue()
    required_fields = ["matiere", "niveau", "statut", "domain", "taxonomy_file"]
    for name, defn in cat["collections"].items():
        if name == "rag_nexus_quarantine":
            continue  # quarantine is special
        for field in required_fields:
            assert field in defn, (
                f"Collection {name} missing required field: {field}"
            )


def test_niveaux_coverage():
    """Catalogue must cover all school levels."""
    cat = _load_catalogue()
    niveaux = {d.get("niveau") for d in cat["collections"].values() if d.get("niveau")}
    for niveau in ["troisieme", "seconde", "premiere", "terminale"]:
        assert niveau in niveaux, f"Missing niveau in catalogue: {niveau}"


def test_voies_coverage():
    """Catalogue must cover general and STMG tracks."""
    cat = _load_catalogue()
    voies = {d.get("voie") for d in cat["collections"].values() if d.get("voie")}
    assert "gen" in voies, "Missing voie: gen"
    assert "stmg" in voies, "Missing voie: stmg"


def test_catalogue_endpoint_module_exists():
    """The retrieval_v2_endpoint module should expose a catalogue route."""
    endpoint_file = ENGINE_ROOT / "src" / "ingestor" / "retrieval_v2_endpoint.py"
    content = endpoint_file.read_text(encoding="utf-8")
    assert "/catalogue/v2" in content, (
        "retrieval_v2_endpoint.py does not expose /catalogue/v2 endpoint"
    )
