from __future__ import annotations

from pathlib import Path

import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ENGINE_ROOT / "configs" / "rag_collections.yml"
MAPPING_PATH = ENGINE_ROOT / "configs" / "legacy_collection_mapping.yml"


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_chroma_collections_are_unique_and_have_allowed_domains() -> None:
    config = _load_yaml(CONFIG_PATH)
    collections = config["physical_backends"]["chroma"]["collections"]

    assert len(collections) == len(set(collections))
    for definition in collections.values():
        assert definition["allowed_domains"]
        assert isinstance(definition["allowed_domains"], list)


def test_quarantine_is_not_retrievable() -> None:
    config = _load_yaml(CONFIG_PATH)
    collections = config["physical_backends"]["chroma"]["collections"]

    assert collections["rag_nexus_quarantine"]["allowed_domains"] == ["quarantine"]
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


def test_legacy_names_are_not_source_of_truth_without_mapping() -> None:
    config = _load_yaml(CONFIG_PATH)
    mapping = _load_yaml(MAPPING_PATH)
    collections = set(config["physical_backends"]["chroma"]["collections"])
    legacy = {"rag_education", "rag_web3", "rag_divers"}

    assert legacy.isdisjoint(collections)
    assert legacy <= set(mapping)


def test_expected_legacy_chroma_mapping() -> None:
    mapping = _load_yaml(MAPPING_PATH)

    assert mapping == {
        "rag_education": "rag_nexus_education",
        "rag_francais_premiere": "rag_nexus_education",
        "rag_maths_premiere": "rag_nexus_education",
        "rag_web3": "rag_nexus_web3",
        "rag_divers": "rag_nexus_quarantine",
    }


def test_no_collection_per_notion() -> None:
    config = _load_yaml(CONFIG_PATH)
    names = set(config["physical_backends"]["chroma"]["collections"])

    forbidden_fragments = {"notion", "chapitre", "theme", "sequence"}
    assert len(names) <= 6
    assert not any(fragment in name for name in names for fragment in forbidden_fragments)


def test_web3_and_education_are_not_mixed_in_same_collection() -> None:
    config = _load_yaml(CONFIG_PATH)
    collections = config["physical_backends"]["chroma"]["collections"]

    for definition in collections.values():
        domains = set(definition["allowed_domains"])
        assert not {"web3", "education"} <= domains


def test_pgvector_declares_target_and_legacy_tables() -> None:
    config = _load_yaml(CONFIG_PATH)
    pgvector = config["physical_backends"]["pgvector"]

    assert pgvector["table"] == "rag_chunks"
    assert pgvector["legacy_table"] == "rag_chunks_pilote"
    assert pgvector["table"] != pgvector["legacy_table"]
