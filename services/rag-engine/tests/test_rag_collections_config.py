from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from src.ingestor.collection_config import (
    CollectionConfigError,
    load_collection_config,
    load_legacy_mapping,
    resolve_collection,
)

ENGINE_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ENGINE_ROOT / "configs" / "rag_collections.yml"
MAPPING_PATH = ENGINE_ROOT / "configs" / "legacy_collection_mapping.yml"
COLLECTION_CONFIG_MODULE = ENGINE_ROOT / "src" / "ingestor" / "collection_config.py"
DOCKER_COMPOSE_PROD = ENGINE_ROOT / "infra" / "docker-compose.prod.yml"


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


# --- v2 config tests (ADR-0013) ---


def test_collections_are_unique_and_have_matiere() -> None:
    config = _load_yaml(CONFIG_PATH)
    collections = config["collections"]

    assert len(collections) == len(set(collections))
    for name, definition in collections.items():
        if name != "rag_nexus_quarantine":
            assert definition.get("matiere"), f"{name} missing matiere"


def test_quarantine_is_not_retrievable() -> None:
    config = _load_yaml(CONFIG_PATH)
    assert "rag_nexus_quarantine" in config["collections"]
    assert config["domains"]["quarantine"]["retrievable"] is False


def test_all_required_metadata_are_declared() -> None:
    config = _load_yaml(CONFIG_PATH)

    expected = {
        "domain",
        "audience",
        "niveau",
        "voie",
        "matiere",
        "statut_enseignement",
        "type_doc",
        "source_kind",
        "rights",
        "review_status",
        "source_label",
        "source_uri",
        "doc_id",
        "chunk_id",
        "chunk_sha256",
    }
    assert expected <= set(config["metadata_required"])


def test_pgvector_v2_backend() -> None:
    config = _load_yaml(CONFIG_PATH)
    assert config.get("physical_backend", {}).get("type") == "pgvector"
    assert config["physical_backend"]["table"] == "rag_chunks"
    assert config["physical_backend"]["vector_dim"] == 1024


def test_pgvector_declares_target_table() -> None:
    config = _load_yaml(CONFIG_PATH)
    pgvector = config["physical_backend"]

    assert pgvector["table"] == "rag_chunks"
    assert pgvector["type"] == "pgvector"
    assert pgvector["vector_dim"] == 1024


def test_no_collection_per_notion() -> None:
    config = _load_yaml(CONFIG_PATH)
    names = set(config["collections"])

    forbidden_fragments = {"notion", "chapitre", "theme", "sequence"}
    assert not any(fragment in name for name in names for fragment in forbidden_fragments)


def test_instanciation_flags_present() -> None:
    config = _load_yaml(CONFIG_PATH)
    for name, defn in config["collections"].items():
        assert "instanciee" in defn, f"{name} missing instanciee flag"


def test_instanciated_collections_match_perimetre() -> None:
    """D-PERIMETRE: only NSI + quarantine are instanciated."""
    config = _load_yaml(CONFIG_PATH)
    instanciated = {
        name for name, defn in config["collections"].items() if defn.get("instanciee")
    }
    assert instanciated == {
        "rag_nexus_nsi_premiere_specialite",
        "rag_nexus_nsi_terminale_specialite",
        "rag_nexus_quarantine",
    }


def test_collection_config_loads_from_flat_prod_layout(tmp_path, monkeypatch) -> None:
    compose_root = tmp_path / "rag-ui" / "compose"
    ingestor_dir = compose_root / "ingestor"
    config_dir = compose_root / "configs"
    ingestor_dir.mkdir(parents=True)
    config_dir.mkdir()

    module_path = ingestor_dir / "collection_config.py"
    shutil.copyfile(COLLECTION_CONFIG_MODULE, module_path)
    shutil.copyfile(CONFIG_PATH, config_dir / "rag_collections.yml")
    shutil.copyfile(MAPPING_PATH, config_dir / "legacy_collection_mapping.yml")
    monkeypatch.delenv("RAG_COLLECTIONS_CONFIG", raising=False)
    monkeypatch.delenv("RAG_LEGACY_COLLECTION_MAPPING", raising=False)
    monkeypatch.delenv("RAG_ENGINE_CONFIG_DIR", raising=False)

    spec = importlib.util.spec_from_file_location("flat_collection_config", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert module.load_collection_config()["version"] == 2
    assert module.load_legacy_mapping()["rag_web3"] == "rag_nexus_web3"


def test_collection_config_uses_config_dir_env(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    shutil.copyfile(CONFIG_PATH, config_dir / "rag_collections.yml")
    shutil.copyfile(MAPPING_PATH, config_dir / "legacy_collection_mapping.yml")
    monkeypatch.delenv("RAG_COLLECTIONS_CONFIG", raising=False)
    monkeypatch.delenv("RAG_LEGACY_COLLECTION_MAPPING", raising=False)
    monkeypatch.setenv("RAG_ENGINE_CONFIG_DIR", str(config_dir))

    spec = importlib.util.spec_from_file_location("env_collection_config", COLLECTION_CONFIG_MODULE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert module.load_collection_config()["version"] == 2
    assert module.load_legacy_mapping()["rag_education"] == "rag_nexus_education"


def test_explicit_collection_config_file_env_fails_closed_when_missing(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("RAG_COLLECTIONS_CONFIG", str(tmp_path / "missing.yml"))
    monkeypatch.delenv("RAG_LEGACY_COLLECTION_MAPPING", raising=False)
    monkeypatch.delenv("RAG_ENGINE_CONFIG_DIR", raising=False)

    with pytest.raises(CollectionConfigError, match="RAG_COLLECTIONS_CONFIG"):
        load_collection_config()


def test_explicit_legacy_mapping_file_env_fails_closed_when_missing(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("RAG_COLLECTIONS_CONFIG", raising=False)
    monkeypatch.setenv("RAG_LEGACY_COLLECTION_MAPPING", str(tmp_path / "missing.yml"))
    monkeypatch.delenv("RAG_ENGINE_CONFIG_DIR", raising=False)

    with pytest.raises(CollectionConfigError, match="RAG_LEGACY_COLLECTION_MAPPING"):
        load_legacy_mapping()


def test_explicit_config_dir_env_fails_closed_when_files_are_missing(
    tmp_path, monkeypatch
) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    monkeypatch.delenv("RAG_COLLECTIONS_CONFIG", raising=False)
    monkeypatch.delenv("RAG_LEGACY_COLLECTION_MAPPING", raising=False)
    monkeypatch.setenv("RAG_ENGINE_CONFIG_DIR", str(config_dir))

    with pytest.raises(CollectionConfigError, match="RAG_ENGINE_CONFIG_DIR"):
        load_collection_config()


def test_explicit_config_dir_env_missing_mapping_fails_closed(
    tmp_path, monkeypatch
) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    shutil.copyfile(CONFIG_PATH, config_dir / "rag_collections.yml")
    monkeypatch.delenv("RAG_COLLECTIONS_CONFIG", raising=False)
    monkeypatch.delenv("RAG_LEGACY_COLLECTION_MAPPING", raising=False)
    monkeypatch.setenv("RAG_ENGINE_CONFIG_DIR", str(config_dir))

    with pytest.raises(CollectionConfigError, match="RAG_ENGINE_CONFIG_DIR"):
        load_legacy_mapping()


def test_repo_fallback_without_env(monkeypatch) -> None:
    monkeypatch.delenv("RAG_COLLECTIONS_CONFIG", raising=False)
    monkeypatch.delenv("RAG_LEGACY_COLLECTION_MAPPING", raising=False)
    monkeypatch.delenv("RAG_ENGINE_CONFIG_DIR", raising=False)

    assert load_collection_config()["version"] == 2
    assert load_legacy_mapping()["rag_web3"] == "rag_nexus_web3"


def test_unknown_section_is_rejected_without_default_fallback() -> None:
    with pytest.raises(CollectionConfigError, match="Unknown section"):
        resolve_collection(
            section="hacked",
            config=_load_yaml(CONFIG_PATH),
            legacy_mapping=_load_yaml(MAPPING_PATH),
        )
