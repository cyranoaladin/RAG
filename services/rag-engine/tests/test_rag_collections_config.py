"""Tests for rag_collections.yml (v2, ADR-0013) + legacy isolation (S-04)."""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from src.ingestor.collection_config import (
    CollectionConfigError,
    CollectionRoutingError,
    CollectionUnknownError,
    load_collection_config,
    load_legacy_collection_config,
    load_legacy_mapping,
    resolve_collection,
    resolve_collection_v2,
)

ENGINE_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ENGINE_ROOT / "configs" / "rag_collections.yml"
LEGACY_CONFIG_PATH = ENGINE_ROOT / "configs" / "rag_collections_legacy.yml"
MAPPING_PATH = ENGINE_ROOT / "configs" / "legacy_collection_mapping.yml"
COLLECTION_CONFIG_MODULE = ENGINE_ROOT / "src" / "ingestor" / "collection_config.py"


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


# ===================================================================
# v2 catalogue tests (rag_collections.yml)
# ===================================================================


def test_config_is_v2() -> None:
    config = _load_yaml(CONFIG_PATH)
    assert config["version"] == 2


def test_no_chroma_no_routing_in_v2() -> None:
    """v2 YAML must not contain physical_backends or routing (ADR-0013)."""
    config = _load_yaml(CONFIG_PATH)
    assert "physical_backends" not in config
    assert "routing" not in config


def test_collections_have_matiere() -> None:
    config = _load_yaml(CONFIG_PATH)
    for name, defn in config["collections"].items():
        if name != "rag_nexus_quarantine":
            assert defn.get("matiere"), f"{name} missing matiere"


def test_quarantine_domain_not_retrievable() -> None:
    config = _load_yaml(CONFIG_PATH)
    assert config["domains"]["quarantine"]["retrievable"] is False


def test_all_required_metadata() -> None:
    config = _load_yaml(CONFIG_PATH)
    expected = {
        "domain", "audience", "niveau", "voie", "matiere",
        "statut_enseignement", "type_doc", "source_kind",
        "rights", "review_status", "source_label", "source_uri",
        "doc_id", "chunk_id", "chunk_sha256",
    }
    assert expected <= set(config["metadata_required"])


def test_pgvector_v2_backend() -> None:
    config = _load_yaml(CONFIG_PATH)
    assert config["physical_backend"]["type"] == "pgvector"
    assert config["physical_backend"]["table"] == "rag_chunks"
    assert config["physical_backend"]["vector_dim"] == 1024


def test_instanciation_flags_present() -> None:
    config = _load_yaml(CONFIG_PATH)
    for name, defn in config["collections"].items():
        assert "instanciee" in defn, f"{name} missing instanciee"


def test_instanciated_match_perimetre() -> None:
    config = _load_yaml(CONFIG_PATH)
    inst = {n for n, d in config["collections"].items() if d.get("instanciee") is True}
    assert inst == {
        "rag_nexus_nsi_premiere_specialite",
        "rag_nexus_nsi_terminale_specialite",
        "rag_nexus_quarantine",
    }


def test_no_web3_domain() -> None:
    config = _load_yaml(CONFIG_PATH)
    assert "web3" not in config.get("domains", {})


def test_no_collection_per_notion() -> None:
    config = _load_yaml(CONFIG_PATH)
    forbidden = {"notion", "chapitre", "theme", "sequence"}
    assert not any(f in n for n in config["collections"] for f in forbidden)


def test_v2_sole_source_guard() -> None:
    """resolve_collection_v2 reads v2 catalogue, rejects unknowns."""
    config = _load_yaml(CONFIG_PATH)
    assert "physical_backends" not in config
    result = resolve_collection_v2("rag_nexus_nsi_terminale_specialite", config)
    assert result["instanciee"] is True
    with pytest.raises(CollectionUnknownError):
        resolve_collection_v2("rag_nexus_education", config)


# ===================================================================
# Legacy config tests (rag_collections_legacy.yml) — S-04
# ===================================================================


@pytest.mark.legacy_engine
def test_legacy_config_is_v1() -> None:
    config = _load_yaml(LEGACY_CONFIG_PATH)
    assert config["version"] == 1
    assert "physical_backends" in config
    assert "routing" in config


@pytest.mark.legacy_engine
def test_legacy_chroma_collections() -> None:
    config = _load_yaml(LEGACY_CONFIG_PATH)
    cols = config["physical_backends"]["chroma"]["collections"]
    assert "rag_nexus_education" in cols
    assert "rag_nexus_web3" in cols


@pytest.mark.legacy_engine
def test_legacy_routing_sections() -> None:
    config = _load_yaml(LEGACY_CONFIG_PATH)
    sections = config["routing"]["sections"]
    assert "education" in sections
    assert "web3" in sections
    assert "default" in sections


@pytest.mark.legacy_engine
def test_legacy_resolve_collection() -> None:
    """Legacy resolver works on legacy config, not v2."""
    legacy_config = _load_yaml(LEGACY_CONFIG_PATH)
    mapping = _load_yaml(MAPPING_PATH)
    resolution = resolve_collection(
        section="education",
        config=legacy_config,
        legacy_mapping=mapping,
    )
    assert resolution.nexus_collection == "rag_nexus_education"


@pytest.mark.legacy_engine
def test_legacy_pgvector_tables() -> None:
    config = _load_yaml(LEGACY_CONFIG_PATH)
    pgvector = config["physical_backends"]["pgvector"]
    assert pgvector["table"] == "rag_chunks"
    assert pgvector["legacy_table"] == "rag_chunks_pilote"


@pytest.mark.legacy_engine
def test_legacy_unknown_section_rejected() -> None:
    legacy_config = _load_yaml(LEGACY_CONFIG_PATH)
    mapping = _load_yaml(MAPPING_PATH)
    with pytest.raises(CollectionRoutingError, match="Unknown section"):
        resolve_collection(
            section="hacked",
            config=legacy_config,
            legacy_mapping=mapping,
        )


@pytest.mark.legacy_engine
def test_legacy_mapping_content() -> None:
    mapping = _load_yaml(MAPPING_PATH)
    assert mapping == {
        "rag_education": "rag_nexus_education",
        "rag_francais_premiere": "rag_nexus_education",
        "rag_maths_premiere": "rag_nexus_education",
        "rag_web3": "rag_nexus_web3",
        "rag_divers": "rag_nexus_quarantine",
    }


# ===================================================================
# Config loading tests
# ===================================================================


def test_load_v2_config() -> None:
    config = load_collection_config()
    assert config["version"] == 2


def test_load_legacy_config() -> None:
    config = load_legacy_collection_config()
    assert config["version"] == 1


def test_collection_config_loads_from_flat_layout(tmp_path, monkeypatch) -> None:
    compose_root = tmp_path / "rag-ui" / "compose"
    ingestor_dir = compose_root / "ingestor"
    config_dir = compose_root / "configs"
    ingestor_dir.mkdir(parents=True)
    config_dir.mkdir()

    module_path = ingestor_dir / "collection_config.py"
    shutil.copyfile(COLLECTION_CONFIG_MODULE, module_path)
    shutil.copyfile(CONFIG_PATH, config_dir / "rag_collections.yml")
    shutil.copyfile(LEGACY_CONFIG_PATH, config_dir / "rag_collections_legacy.yml")
    shutil.copyfile(MAPPING_PATH, config_dir / "legacy_collection_mapping.yml")
    monkeypatch.delenv("RAG_COLLECTIONS_CONFIG", raising=False)
    monkeypatch.delenv("RAG_LEGACY_COLLECTIONS_CONFIG", raising=False)
    monkeypatch.delenv("RAG_LEGACY_COLLECTION_MAPPING", raising=False)
    monkeypatch.delenv("RAG_ENGINE_CONFIG_DIR", raising=False)

    spec = importlib.util.spec_from_file_location("flat_cc", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert module.load_collection_config()["version"] == 2


def test_config_dir_env(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    shutil.copyfile(CONFIG_PATH, config_dir / "rag_collections.yml")
    shutil.copyfile(LEGACY_CONFIG_PATH, config_dir / "rag_collections_legacy.yml")
    shutil.copyfile(MAPPING_PATH, config_dir / "legacy_collection_mapping.yml")
    monkeypatch.delenv("RAG_COLLECTIONS_CONFIG", raising=False)
    monkeypatch.delenv("RAG_LEGACY_COLLECTIONS_CONFIG", raising=False)
    monkeypatch.delenv("RAG_LEGACY_COLLECTION_MAPPING", raising=False)
    monkeypatch.setenv("RAG_ENGINE_CONFIG_DIR", str(config_dir))

    spec = importlib.util.spec_from_file_location("env_cc", COLLECTION_CONFIG_MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert module.load_collection_config()["version"] == 2


def test_missing_config_env_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RAG_COLLECTIONS_CONFIG", str(tmp_path / "missing.yml"))
    monkeypatch.delenv("RAG_LEGACY_COLLECTION_MAPPING", raising=False)
    monkeypatch.delenv("RAG_ENGINE_CONFIG_DIR", raising=False)
    with pytest.raises(CollectionConfigError, match="RAG_COLLECTIONS_CONFIG"):
        load_collection_config()


def test_missing_mapping_env_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("RAG_COLLECTIONS_CONFIG", raising=False)
    monkeypatch.setenv("RAG_LEGACY_COLLECTION_MAPPING", str(tmp_path / "missing.yml"))
    monkeypatch.delenv("RAG_ENGINE_CONFIG_DIR", raising=False)
    with pytest.raises(CollectionConfigError, match="RAG_LEGACY_COLLECTION_MAPPING"):
        load_legacy_mapping()


def test_missing_dir_config_fails(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    monkeypatch.delenv("RAG_COLLECTIONS_CONFIG", raising=False)
    monkeypatch.delenv("RAG_LEGACY_COLLECTION_MAPPING", raising=False)
    monkeypatch.setenv("RAG_ENGINE_CONFIG_DIR", str(config_dir))
    with pytest.raises(CollectionConfigError, match="RAG_ENGINE_CONFIG_DIR"):
        load_collection_config()


def test_missing_dir_mapping_fails(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    shutil.copyfile(CONFIG_PATH, config_dir / "rag_collections.yml")
    monkeypatch.delenv("RAG_COLLECTIONS_CONFIG", raising=False)
    monkeypatch.delenv("RAG_LEGACY_COLLECTION_MAPPING", raising=False)
    monkeypatch.setenv("RAG_ENGINE_CONFIG_DIR", str(config_dir))
    with pytest.raises(CollectionConfigError, match="RAG_ENGINE_CONFIG_DIR"):
        load_legacy_mapping()


def test_repo_fallback_v2_config_without_env(monkeypatch) -> None:
    monkeypatch.delenv("RAG_COLLECTIONS_CONFIG", raising=False)
    monkeypatch.delenv("RAG_LEGACY_COLLECTIONS_CONFIG", raising=False)
    monkeypatch.delenv("RAG_LEGACY_COLLECTION_MAPPING", raising=False)
    monkeypatch.delenv("RAG_ENGINE_CONFIG_DIR", raising=False)
    assert load_collection_config()["version"] == 2


@pytest.mark.legacy_engine
def test_repo_fallback_legacy_mapping_without_env(monkeypatch) -> None:
    monkeypatch.delenv("RAG_COLLECTIONS_CONFIG", raising=False)
    monkeypatch.delenv("RAG_LEGACY_COLLECTIONS_CONFIG", raising=False)
    monkeypatch.delenv("RAG_LEGACY_COLLECTION_MAPPING", raising=False)
    monkeypatch.delenv("RAG_ENGINE_CONFIG_DIR", raising=False)
    assert load_legacy_mapping()["rag_web3"] == "rag_nexus_web3"
