"""Validation fail-closed de la politique de convergence des moteurs RAG."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode

_PROTOCOL_VERSION = "NEXUS-ENGINE-CONVERGENCE-V1"
_CANONICAL_ENGINE = "B"
_CONTRACT_PACKAGE = "nexus-contracts"
_CONTRACT_SOURCE = "packages/contracts"
_CONTRACT_VERSION = "0.14.0"
_EXPECTED_CAPABILITY_MATRIX = {
    "governed_reingestion": ("B", "blocked", 2),
    "file_ingestion": ("B", "compatibility_only", 3),
    "external_api": ("B", "blocked", 3),
    "web_ingestion": ("B", "compatibility_only", 4),
    "drive_ingestion": ("B", "compatibility_only", 5),
    "cockpit": ("B", "blocked", 6),
    "retrieval": ("B", "compatibility_only", 8),
    "rollback": ("B", "rollback_only", 8),
}
_EXPECTED_LEGACY_COLLECTIONS = frozenset(
    {
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
)
_NSI_TARGETS = (
    "rag_nexus_nsi_premiere_specialite",
    "rag_nexus_nsi_terminale_specialite",
)
_EXPECTED_LEGACY_TARGETS = {
    name: _NSI_TARGETS if name in {"nsi_corpus", "nsi_corpus_v2"} else ()
    for name in _EXPECTED_LEGACY_COLLECTIONS
}
_EXPECTED_LEGACY_DEFAULTS = {
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
_DEFAULT_COLLECTION_CATALOGUE = (
    Path(__file__).resolve().parents[2] / "configs" / "rag_collections.yml"
)


class EngineConvergencePolicyError(ValueError):
    """La politique ne respecte pas le contrat de convergence fermé."""


class _DuplicateYamlKeyError(yaml.YAMLError):
    """Signal interne sans reprise de la clé du document."""


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader qui refuse les clés dupliquées à toute profondeur."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise _DuplicateYamlKeyError from exc
        if duplicate:
            raise _DuplicateYamlKeyError
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _strict_yaml_load(content: str) -> Any:
    try:
        return yaml.load(content, Loader=_UniqueKeySafeLoader)
    except _DuplicateYamlKeyError as exc:
        raise EngineConvergencePolicyError(
            "YAML document contains duplicate keys"
        ) from exc
    except yaml.YAMLError as exc:
        raise EngineConvergencePolicyError("YAML document is invalid") from exc


class EngineAState(StrEnum):
    """États normatifs fermés des capacités du moteur A."""

    COMPATIBILITY_ONLY = "compatibility_only"
    ROLLBACK_ONLY = "rollback_only"
    BLOCKED = "blocked"


class LegacyDisposition(StrEnum):
    """Dispositions fermées d'un objet legacy."""

    REINGEST_GOVERNED = "REINGEST_GOVERNED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    QUARANTINE = "QUARANTINE"
    IGNORE_EMPTY = "IGNORE_EMPTY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ContractBinding:
    """Référence immuable vers le contrat partagé canonique."""

    package: str
    source: str
    version: str


@dataclass(frozen=True)
class CapabilityPolicy:
    """Propriétaire et état de transition d'une capacité nommée."""

    name: str
    canonical_owner: str
    engine_a_state: EngineAState
    responsible_lot: int


@dataclass(frozen=True)
class LegacyCollectionPolicy:
    """Disposition par défaut et cibles fines autorisées d'une collection A."""

    name: str
    default_disposition: LegacyDisposition
    allowed_targets: tuple[str, ...]


@dataclass(frozen=True)
class EngineConvergencePolicy:
    """Partie validée de la politique de convergence."""

    protocol_version: str
    canonical_engine: str
    contract: ContractBinding
    capabilities: tuple[CapabilityPolicy, ...]
    cutover_status: str
    discovered_legacy_collections: tuple[str, ...]
    legacy_collections: tuple[LegacyCollectionPolicy, ...]


def _require_mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise EngineConvergencePolicyError(f"{field} must be a mapping")
    return value


def _require_exact_keys(
    document: dict[str, Any], *, expected: frozenset[str], field: str
) -> None:
    if frozenset(document) != expected:
        raise EngineConvergencePolicyError(f"{field} keys are invalid")


def _parse_capabilities(value: Any) -> tuple[CapabilityPolicy, ...]:
    if not isinstance(value, list) or not value:
        raise EngineConvergencePolicyError("capabilities must be a non-empty list")

    capabilities: list[CapabilityPolicy] = []
    names: set[str] = set()
    for item in value:
        document = _require_mapping(item, field="capability")
        _require_exact_keys(
            document,
            expected=frozenset(
                {"name", "canonical_owner", "engine_a_state", "responsible_lot"}
            ),
            field="capability",
        )
        name = document.get("name")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise EngineConvergencePolicyError("capability name is invalid")
        names.add(name)
        if document.get("canonical_owner") != _CANONICAL_ENGINE:
            raise EngineConvergencePolicyError("capability canonical_owner is invalid")
        raw_state = document.get("engine_a_state")
        if not isinstance(raw_state, str):
            raise EngineConvergencePolicyError("capability engine_a_state is invalid")
        try:
            state = EngineAState(raw_state)
        except ValueError as exc:
            raise EngineConvergencePolicyError("capability engine_a_state is invalid") from exc
        responsible_lot = document.get("responsible_lot")
        if not isinstance(responsible_lot, int) or isinstance(responsible_lot, bool):
            raise EngineConvergencePolicyError("capability responsible_lot is invalid")
        capabilities.append(
            CapabilityPolicy(
                name=name,
                canonical_owner=_CANONICAL_ENGINE,
                engine_a_state=state,
                responsible_lot=responsible_lot,
            )
        )
    parsed = tuple(capabilities)
    if {
        capability.name: (
            capability.canonical_owner,
            capability.engine_a_state.value,
            capability.responsible_lot,
        )
        for capability in parsed
    } != _EXPECTED_CAPABILITY_MATRIX:
        raise EngineConvergencePolicyError("capability matrix is invalid")
    return parsed


def _parse_closed_string_list(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise EngineConvergencePolicyError(f"{field} must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise EngineConvergencePolicyError(f"{field} entries are invalid")
    if len(value) != len(set(value)):
        raise EngineConvergencePolicyError(f"{field} contains duplicates")
    return tuple(value)


def _load_collection_names(path: Path) -> frozenset[str]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EngineConvergencePolicyError("collection catalogue is unavailable") from exc
    raw = _strict_yaml_load(content)
    document = _require_mapping(raw, field="collection catalogue")
    collections = _require_mapping(document.get("collections"), field="catalogue collections")
    return frozenset(collections)


def _parse_legacy_collections(
    value: Any,
    *,
    catalogue_collections: frozenset[str],
) -> tuple[LegacyCollectionPolicy, ...]:
    if not isinstance(value, list) or not value:
        raise EngineConvergencePolicyError("legacy_collections must be a non-empty list")

    policies: list[LegacyCollectionPolicy] = []
    names: set[str] = set()
    for item in value:
        document = _require_mapping(item, field="legacy collection")
        _require_exact_keys(
            document,
            expected=frozenset({"name", "default_disposition", "allowed_targets"}),
            field="legacy collection",
        )
        name = document.get("name")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise EngineConvergencePolicyError("legacy collection name is invalid")
        names.add(name)
        raw_disposition = document.get("default_disposition")
        if not isinstance(raw_disposition, str):
            raise EngineConvergencePolicyError(
                "legacy collection default_disposition is invalid"
            )
        try:
            disposition = LegacyDisposition(raw_disposition)
        except ValueError as exc:
            raise EngineConvergencePolicyError(
                "legacy collection default_disposition is invalid"
            ) from exc
        if disposition in {
            LegacyDisposition.REINGEST_GOVERNED,
            LegacyDisposition.IGNORE_EMPTY,
        }:
            raise EngineConvergencePolicyError(
                "legacy collection default_disposition is forbidden"
            )
        raw_targets = document.get("allowed_targets")
        if not isinstance(raw_targets, list) or not all(
            isinstance(target, str) and target.strip() for target in raw_targets
        ):
            raise EngineConvergencePolicyError("legacy collection targets are invalid")
        if len(raw_targets) != len(set(raw_targets)):
            raise EngineConvergencePolicyError("legacy collection targets contain duplicates")
        targets = tuple(raw_targets)
        if any(target not in catalogue_collections for target in targets):
            raise EngineConvergencePolicyError("legacy collection target is not canonical")
        policies.append(
            LegacyCollectionPolicy(
                name=name,
                default_disposition=disposition,
                allowed_targets=targets,
            )
        )
    parsed = tuple(policies)
    if {item.name: item.allowed_targets for item in parsed} != _EXPECTED_LEGACY_TARGETS:
        raise EngineConvergencePolicyError("legacy collection targets are not exact")
    if {
        item.name: item.default_disposition.value for item in parsed
    } != _EXPECTED_LEGACY_DEFAULTS:
        raise EngineConvergencePolicyError("legacy collection defaults are not exact")
    return parsed


def load_engine_convergence_policy(
    path: Path,
    *,
    collection_catalogue_path: Path = _DEFAULT_COLLECTION_CATALOGUE,
) -> EngineConvergencePolicy:
    """Charger une politique V1 en refusant toute valeur hors contrat."""

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EngineConvergencePolicyError("policy document is unavailable") from exc
    raw = _strict_yaml_load(content)

    document = _require_mapping(raw, field="policy")
    _require_exact_keys(
        document,
        expected=frozenset(
            {
                "protocol_version",
                "canonical_engine",
                "contract",
                "capabilities",
                "cutover_status",
                "discovered_legacy_collections",
                "legacy_collections",
            }
        ),
        field="policy",
    )
    if document.get("protocol_version") != _PROTOCOL_VERSION:
        raise EngineConvergencePolicyError("policy protocol_version is invalid")
    if document.get("canonical_engine") != _CANONICAL_ENGINE:
        raise EngineConvergencePolicyError("policy canonical_engine is invalid")
    if document.get("cutover_status") != "NO_GO":
        raise EngineConvergencePolicyError("policy cutover_status is invalid")

    contract_document = _require_mapping(document.get("contract"), field="contract")
    _require_exact_keys(
        contract_document,
        expected=frozenset({"package", "source", "version"}),
        field="contract",
    )
    if contract_document.get("package") != _CONTRACT_PACKAGE:
        raise EngineConvergencePolicyError("contract package is invalid")
    if contract_document.get("source") != _CONTRACT_SOURCE:
        raise EngineConvergencePolicyError("contract source is invalid")
    if contract_document.get("version") != _CONTRACT_VERSION:
        raise EngineConvergencePolicyError("contract version is invalid")

    discovered = _parse_closed_string_list(
        document.get("discovered_legacy_collections"),
        field="discovered_legacy_collections",
    )
    if frozenset(discovered) != _EXPECTED_LEGACY_COLLECTIONS:
        raise EngineConvergencePolicyError("discovered legacy collections are incomplete")
    legacy_collections = _parse_legacy_collections(
        document.get("legacy_collections"),
        catalogue_collections=_load_collection_names(collection_catalogue_path),
    )
    if {item.name for item in legacy_collections} != set(discovered):
        raise EngineConvergencePolicyError("discovered and governed collections differ")

    return EngineConvergencePolicy(
        protocol_version=_PROTOCOL_VERSION,
        canonical_engine=_CANONICAL_ENGINE,
        contract=ContractBinding(
            package=_CONTRACT_PACKAGE,
            source=_CONTRACT_SOURCE,
            version=_CONTRACT_VERSION,
        ),
        capabilities=_parse_capabilities(document.get("capabilities")),
        cutover_status="NO_GO",
        discovered_legacy_collections=discovered,
        legacy_collections=legacy_collections,
    )
