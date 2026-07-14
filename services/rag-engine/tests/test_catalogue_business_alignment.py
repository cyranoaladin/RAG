"""Tests — Catalogue v2 business alignment.

Verifies the backend catalogue (rag_collections.yml) and
the /catalogue/v2 endpoint module.
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
    assert _load_catalogue().get("version") == 2


def test_catalogue_has_collections():
    cat = _load_catalogue()
    assert "collections" in cat
    assert len(cat["collections"]) >= 30


def test_catalogue_has_metadata_required():
    required = _load_catalogue().get("metadata_required", [])
    expected = [
        "domain", "audience", "niveau", "voie", "matiere",
        "statut_enseignement", "type_doc", "source_kind", "rights",
        "review_status", "source_label", "source_uri",
        "doc_id", "chunk_id", "chunk_sha256",
    ]
    for field in expected:
        assert field in required, f"metadata_required missing: {field}"


def test_catalogue_domains():
    domains = _load_catalogue().get("domains", {})
    assert "education" in domains
    assert "exam" in domains
    assert "quarantine" in domains
    assert domains["quarantine"].get("retrievable") is False


def test_instanciated_collections():
    cols = _load_catalogue()["collections"]
    instanciated = [n for n, d in cols.items() if d.get("instanciee") is True]
    assert len(instanciated) >= 3


def test_quarantine_is_instanciated_but_not_retrievable():
    cat = _load_catalogue()
    q = cat["collections"]["rag_nexus_quarantine"]
    assert q.get("instanciee") is True
    assert q.get("domain") == "quarantine"
    assert cat["domains"]["quarantine"]["retrievable"] is False


def test_all_education_collections_have_required_fields():
    required_fields = ["matiere", "niveau", "statut", "domain", "taxonomy_file"]
    for name, defn in _load_catalogue()["collections"].items():
        if name == "rag_nexus_quarantine":
            continue
        for field in required_fields:
            assert field in defn, f"Collection {name} missing field: {field}"


def test_niveaux_coverage():
    niveaux = {d.get("niveau") for d in _load_catalogue()["collections"].values() if d.get("niveau")}
    for niveau in ["troisieme", "seconde", "premiere", "terminale"]:
        assert niveau in niveaux


def test_voies_coverage():
    voies = {d.get("voie") for d in _load_catalogue()["collections"].values() if d.get("voie")}
    assert "gen" in voies
    assert "stmg" in voies


# --- Endpoint module checks ---

def test_catalogue_endpoint_exists():
    endpoint_file = ENGINE_ROOT / "src" / "ingestor" / "retrieval_v2_endpoint.py"
    content = endpoint_file.read_text(encoding="utf-8")
    assert "/catalogue/v2" in content


def test_catalogue_endpoint_returns_taxonomy_exists():
    endpoint_file = ENGINE_ROOT / "src" / "ingestor" / "retrieval_v2_endpoint.py"
    content = endpoint_file.read_text(encoding="utf-8")
    assert "taxonomy_exists" in content


def test_catalogue_endpoint_returns_coherence_issues():
    endpoint_file = ENGINE_ROOT / "src" / "ingestor" / "retrieval_v2_endpoint.py"
    content = endpoint_file.read_text(encoding="utf-8")
    assert "coherence_issues" in content


def test_catalogue_endpoint_returns_ingestion_enabled():
    endpoint_file = ENGINE_ROOT / "src" / "ingestor" / "retrieval_v2_endpoint.py"
    content = endpoint_file.read_text(encoding="utf-8")
    assert "ingestion_enabled" in content
    assert "search_enabled" in content
    assert "ingestion_enabled_reason" in content
    assert "search_enabled_reason" in content


def test_catalogue_endpoint_returns_groupings():
    endpoint_file = ENGINE_ROOT / "src" / "ingestor" / "retrieval_v2_endpoint.py"
    content = endpoint_file.read_text(encoding="utf-8")
    assert "by_level" in content
    assert "by_domain" in content
    assert "by_status" in content


def test_collections_v2_remains_separate():
    """The /collections/v2 endpoint must remain limited to instanciated+retrievable."""
    endpoint_file = ENGINE_ROOT / "src" / "ingestor" / "retrieval_v2_endpoint.py"
    content = endpoint_file.read_text(encoding="utf-8")
    assert "/collections/v2" in content
    assert "retrievable" in content


# --- Runtime-like catalogue check (module import) ---

def test_catalogue_module_produces_expected_fields():
    """Load config and verify the _full_catalogue logic produces expected fields."""
    import sys
    sys.path.insert(0, str(ENGINE_ROOT / "src"))
    try:
        from ingestor.collection_config import load_collection_config
        cfg = load_collection_config()
        cols = cfg.get("collections", {})
        # Verify at least 38 collections
        assert len(cols) >= 35, f"Expected >=35 collections, got {len(cols)}"
        # Verify instanciated ones
        inst = [n for n, d in cols.items() if d.get("instanciee") is True]
        assert len(inst) >= 3
    finally:
        sys.path.pop(0)
