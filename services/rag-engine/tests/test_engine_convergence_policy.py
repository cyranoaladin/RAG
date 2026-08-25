"""Garde-fous de convergence des moteurs A et B."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.ingestor.engine_convergence_policy import (
    EngineConvergencePolicyError,
    load_engine_convergence_policy,
)

ENGINE_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ENGINE_ROOT / "configs" / "engine_convergence_v1.yml"
COLLECTION_CATALOGUE_PATH = ENGINE_ROOT / "configs" / "rag_collections.yml"
OBSERVED_LEGACY_COLLECTIONS = {
    "nsi_corpus",
    "nsi_corpus_v2",
    "rag_education",
    "rag_francais_premiere",
    "rag_maths_premiere",
    "rag_math_correction",
    "rag_web3",
    "rag_divers",
    "ressources_pedagogiques_terminale",
}
EXPECTED_CAPABILITY_MATRIX = {
    "governed_reingestion": ("B", "blocked", 2),
    "file_ingestion": ("B", "compatibility_only", 3),
    "external_api": ("B", "blocked", 3),
    "web_ingestion": ("B", "compatibility_only", 4),
    "drive_ingestion": ("B", "compatibility_only", 5),
    "cockpit": ("B", "blocked", 6),
    "retrieval": ("B", "compatibility_only", 8),
    "rollback": ("B", "rollback_only", 8),
}
NSI_TARGETS = (
    "rag_nexus_nsi_premiere_specialite",
    "rag_nexus_nsi_terminale_specialite",
)
EXPECTED_LEGACY_DEFAULTS = {
    "nsi_corpus": "REVIEW_REQUIRED",
    "nsi_corpus_v2": "REVIEW_REQUIRED",
    "rag_education": "REVIEW_REQUIRED",
    "rag_francais_premiere": "REVIEW_REQUIRED",
    "rag_maths_premiere": "REVIEW_REQUIRED",
    "rag_math_correction": "REVIEW_REQUIRED",
    "rag_web3": "QUARANTINE",
    "rag_divers": "QUARANTINE",
    "ressources_pedagogiques_terminale": "REVIEW_REQUIRED",
}
def _policy_document() -> dict[str, Any]:
    document = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _write_policy(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def _write_raw(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_policy_requires_v1_protocol_and_engine_b(tmp_path: Path) -> None:
    policy = load_engine_convergence_policy(POLICY_PATH)

    assert policy.protocol_version == "NEXUS-ENGINE-CONVERGENCE-V1"
    assert policy.canonical_engine == "B"
    assert policy.contract.package == "nexus-contracts"
    assert policy.contract.source == "packages/contracts"
    assert policy.contract.version == "0.14.0"
    with pytest.raises(FrozenInstanceError):
        policy.canonical_engine = "A"  # type: ignore[misc]

    for field, invalid_value in (
        ("protocol_version", "NEXUS-ENGINE-CONVERGENCE-V2"),
        ("canonical_engine", "A"),
    ):
        invalid = _policy_document()
        invalid[field] = invalid_value
        with pytest.raises(EngineConvergencePolicyError):
            load_engine_convergence_policy(
                _write_policy(tmp_path / f"invalid-{field}.yml", invalid)
            )

    invalid_contract = _policy_document()
    invalid_contract["contract"] = {
        "package": "nexus-contracts",
        "source": "services/rag-engine",
        "version": "0.14.0",
    }
    with pytest.raises(EngineConvergencePolicyError):
        load_engine_convergence_policy(
            _write_policy(tmp_path / "invalid-contract.yml", invalid_contract)
        )


def test_policy_rejects_unknown_state_or_ownerless_capability(tmp_path: Path) -> None:
    policy = load_engine_convergence_policy(POLICY_PATH)

    capabilities = {capability.name: capability for capability in policy.capabilities}
    assert capabilities
    assert {capability.canonical_owner for capability in capabilities.values()} == {"B"}
    assert {capability.engine_a_state.value for capability in capabilities.values()} <= {
        "compatibility_only",
        "rollback_only",
        "blocked",
    }
    assert {capability.responsible_lot for capability in capabilities.values()} <= {
        2,
        3,
        4,
        5,
        6,
        8,
    }

    invalid_state = _policy_document()
    invalid_state["capabilities"][0]["engine_a_state"] = "experimental"
    with pytest.raises(EngineConvergencePolicyError):
        load_engine_convergence_policy(
            _write_policy(tmp_path / "unknown-state.yml", invalid_state)
        )

    ownerless = _policy_document()
    del ownerless["capabilities"][0]["canonical_owner"]
    with pytest.raises(EngineConvergencePolicyError):
        load_engine_convergence_policy(
            _write_policy(tmp_path / "ownerless.yml", ownerless)
        )

    writer_a = _policy_document()
    writer_a["capabilities"][0]["writer"] = "A"
    with pytest.raises(EngineConvergencePolicyError):
        load_engine_convergence_policy(_write_policy(tmp_path / "writer-a.yml", writer_a))

    invalid_lot = _policy_document()
    invalid_lot["capabilities"][0]["responsible_lot"] = 7
    with pytest.raises(EngineConvergencePolicyError):
        load_engine_convergence_policy(
            _write_policy(tmp_path / "invalid-lot.yml", invalid_lot)
        )


def test_policy_requires_exact_capability_matrix(tmp_path: Path) -> None:
    policy = load_engine_convergence_policy(POLICY_PATH)

    assert {
        capability.name: (
            capability.canonical_owner,
            capability.engine_a_state.value,
            capability.responsible_lot,
        )
        for capability in policy.capabilities
    } == EXPECTED_CAPABILITY_MATRIX

    missing = _policy_document()
    missing["capabilities"] = missing["capabilities"][:-1]
    surplus = _policy_document()
    surplus["capabilities"].append(
        {
            "name": "undeclared_capability",
            "canonical_owner": "B",
            "engine_a_state": "blocked",
            "responsible_lot": 2,
        }
    )
    wrong_lot = _policy_document()
    wrong_lot["capabilities"][0]["responsible_lot"] = 3
    wrong_state = _policy_document()
    wrong_state["capabilities"][0]["engine_a_state"] = "compatibility_only"

    for name, invalid in (
        ("missing", missing),
        ("surplus", surplus),
        ("wrong-lot", wrong_lot),
        ("wrong-state", wrong_state),
    ):
        with pytest.raises(EngineConvergencePolicyError):
            load_engine_convergence_policy(
                _write_policy(tmp_path / f"capability-{name}.yml", invalid)
            )


def test_policy_requires_exact_no_go_cutover_status(tmp_path: Path) -> None:
    policy = load_engine_convergence_policy(POLICY_PATH)

    assert policy.cutover_status == "NO_GO"

    for name, value in (("go", "GO"), ("boolean", False)):
        invalid = _policy_document()
        invalid["cutover_status"] = value
        with pytest.raises(EngineConvergencePolicyError):
            load_engine_convergence_policy(
                _write_policy(tmp_path / f"cutover-status-{name}.yml", invalid)
            )


def test_policy_closes_legacy_collections_and_rejects_silos(tmp_path: Path) -> None:
    policy = load_engine_convergence_policy(
        POLICY_PATH,
        collection_catalogue_path=COLLECTION_CATALOGUE_PATH,
    )

    assert set(policy.discovered_legacy_collections) == OBSERVED_LEGACY_COLLECTIONS
    assert {item.name for item in policy.legacy_collections} == OBSERVED_LEGACY_COLLECTIONS
    assert {item.default_disposition.value for item in policy.legacy_collections} <= {
        "REINGEST_GOVERNED",
        "REVIEW_REQUIRED",
        "QUARANTINE",
        "IGNORE_EMPTY",
        "BLOCKED",
    }

    missing = _policy_document()
    missing["legacy_collections"] = missing["legacy_collections"][:-1]
    with pytest.raises(EngineConvergencePolicyError):
        load_engine_convergence_policy(
            _write_policy(tmp_path / "missing-collection.yml", missing),
            collection_catalogue_path=COLLECTION_CATALOGUE_PATH,
        )

    duplicate = _policy_document()
    duplicate["legacy_collections"].append(duplicate["legacy_collections"][0])
    with pytest.raises(EngineConvergencePolicyError):
        load_engine_convergence_policy(
            _write_policy(tmp_path / "duplicate-collection.yml", duplicate),
            collection_catalogue_path=COLLECTION_CATALOGUE_PATH,
        )

    for silo in ("rag_nexus_education", "rag_nexus_web3"):
        generic_target = _policy_document()
        generic_target["legacy_collections"][0]["allowed_targets"] = [silo]
        with pytest.raises(EngineConvergencePolicyError):
            load_engine_convergence_policy(
                _write_policy(tmp_path / f"generic-{silo}.yml", generic_target),
                collection_catalogue_path=COLLECTION_CATALOGUE_PATH,
            )

    absent_target = _policy_document()
    absent_target["legacy_collections"][0]["allowed_targets"] = ["rag_nexus_absent"]
    with pytest.raises(EngineConvergencePolicyError):
        load_engine_convergence_policy(
            _write_policy(tmp_path / "absent-target.yml", absent_target),
            collection_catalogue_path=COLLECTION_CATALOGUE_PATH,
        )


def test_policy_allows_only_exact_nsi_targets_and_safe_defaults(tmp_path: Path) -> None:
    policy = load_engine_convergence_policy(POLICY_PATH)

    assert {
        item.name: item.allowed_targets for item in policy.legacy_collections
    } == {
        name: NSI_TARGETS if name in {"nsi_corpus", "nsi_corpus_v2"} else ()
        for name in OBSERVED_LEGACY_COLLECTIONS
    }
    assert not {
        "REINGEST_GOVERNED",
        "IGNORE_EMPTY",
    } & {item.default_disposition.value for item in policy.legacy_collections}
    assert {
        item.name: item.default_disposition.value
        for item in policy.legacy_collections
    } == EXPECTED_LEGACY_DEFAULTS

    wrong_safe_default = _policy_document()
    web3 = next(
        item
        for item in wrong_safe_default["legacy_collections"]
        if item["name"] == "rag_web3"
    )
    web3["default_disposition"] = "REVIEW_REQUIRED"
    with pytest.raises(EngineConvergencePolicyError):
        load_engine_convergence_policy(
            _write_policy(tmp_path / "wrong-safe-default.yml", wrong_safe_default)
        )

    incomplete_nsi = _policy_document()
    incomplete_nsi["legacy_collections"][0]["allowed_targets"] = [NSI_TARGETS[0]]
    with pytest.raises(EngineConvergencePolicyError):
        load_engine_convergence_policy(
            _write_policy(tmp_path / "incomplete-nsi-targets.yml", incomplete_nsi)
        )

    for index, name in enumerate(sorted(OBSERVED_LEGACY_COLLECTIONS - {"nsi_corpus", "nsi_corpus_v2"})):
        invalid = _policy_document()
        policy_index = next(
            position
            for position, item in enumerate(invalid["legacy_collections"])
            if item["name"] == name
        )
        invalid["legacy_collections"][policy_index]["allowed_targets"] = [NSI_TARGETS[0]]
        with pytest.raises(EngineConvergencePolicyError):
            load_engine_convergence_policy(
                _write_policy(tmp_path / f"non-nsi-target-{index}.yml", invalid)
            )

    for disposition in ("REINGEST_GOVERNED", "IGNORE_EMPTY"):
        invalid = _policy_document()
        invalid["legacy_collections"][0]["default_disposition"] = disposition
        with pytest.raises(EngineConvergencePolicyError):
            load_engine_convergence_policy(
                _write_policy(tmp_path / f"forbidden-{disposition}.yml", invalid)
            )


def test_yaml_loader_rejects_duplicate_policy_and_catalogue_keys(tmp_path: Path) -> None:
    duplicate_policy = _write_raw(
        tmp_path / "duplicate-policy.yml",
        POLICY_PATH.read_text(encoding="utf-8") + "\ncanonical_engine: B\n",
    )
    with pytest.raises(
        EngineConvergencePolicyError,
        match="^YAML document contains duplicate keys$",
    ):
        load_engine_convergence_policy(duplicate_policy)

    duplicate_catalogue = _write_raw(
        tmp_path / "duplicate-catalogue.yml",
        COLLECTION_CATALOGUE_PATH.read_text(encoding="utf-8") + "\nversion: 3\n",
    )
    with pytest.raises(
        EngineConvergencePolicyError,
        match="^YAML document contains duplicate keys$",
    ):
        load_engine_convergence_policy(
            POLICY_PATH,
            collection_catalogue_path=duplicate_catalogue,
        )

