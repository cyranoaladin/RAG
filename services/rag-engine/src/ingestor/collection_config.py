from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ENGINE_ROOT / "configs" / "rag_collections.yml"
MAPPING_PATH = ENGINE_ROOT / "configs" / "legacy_collection_mapping.yml"

logger = logging.getLogger(__name__)


class CollectionConfigError(ValueError):
    """Raised when a collection or routing key is outside the versioned config."""


@dataclass(frozen=True)
class CollectionResolution:
    requested: str
    nexus_collection: str
    physical_collection: str
    domain: str
    retrievable: bool
    legacy_collection: str | None = None
    used_legacy: bool = False


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CollectionConfigError(f"Invalid YAML mapping in {path.name}")
    return cast(dict[str, Any], data)


def load_collection_config(path: Path | None = None) -> dict[str, Any]:
    return _read_yaml(path or CONFIG_PATH)


def load_legacy_mapping(path: Path | None = None) -> dict[str, str]:
    raw = _read_yaml(path or MAPPING_PATH)
    mapping: dict[str, str] = {}
    for legacy, target in raw.items():
        if not isinstance(legacy, str) or not isinstance(target, str):
            raise CollectionConfigError("Legacy collection mapping must be string -> string")
        mapping[legacy] = target
    return mapping


def _chroma_collections(config: Mapping[str, Any]) -> Mapping[str, Any]:
    backends = config.get("physical_backends")
    if not isinstance(backends, Mapping):
        raise CollectionConfigError("Missing physical_backends")
    chroma = backends.get("chroma")
    if not isinstance(chroma, Mapping):
        raise CollectionConfigError("Missing chroma backend")
    collections = chroma.get("collections")
    if not isinstance(collections, Mapping):
        raise CollectionConfigError("Missing chroma collections")
    return collections


def _routing_sections(config: Mapping[str, Any]) -> Mapping[str, Any]:
    routing = config.get("routing")
    if not isinstance(routing, Mapping):
        raise CollectionConfigError("Missing routing")
    sections = routing.get("sections")
    if not isinstance(sections, Mapping):
        raise CollectionConfigError("Missing routing sections")
    return sections


def _domains(config: Mapping[str, Any]) -> Mapping[str, Any]:
    domains = config.get("domains")
    if not isinstance(domains, Mapping):
        raise CollectionConfigError("Missing domains")
    return domains


def _collection_domain(config: Mapping[str, Any], nexus_collection: str) -> str:
    collections = _chroma_collections(config)
    definition = collections.get(nexus_collection)
    if not isinstance(definition, Mapping):
        raise CollectionConfigError(f"Unknown Nexus collection: {nexus_collection}")
    allowed_domains = definition.get("allowed_domains")
    if not isinstance(allowed_domains, list) or not allowed_domains:
        raise CollectionConfigError(f"Collection {nexus_collection} has no allowed domains")
    if len(allowed_domains) != 1:
        raise CollectionConfigError(f"Collection {nexus_collection} mixes multiple domains")
    domain = allowed_domains[0]
    if not isinstance(domain, str):
        raise CollectionConfigError(f"Collection {nexus_collection} has an invalid domain")
    return domain


def _domain_is_retrievable(config: Mapping[str, Any], domain: str) -> bool:
    definition = _domains(config).get(domain)
    if not isinstance(definition, Mapping):
        raise CollectionConfigError(f"Unknown domain: {domain}")
    return definition.get("retrievable", True) is not False


def _section_resolution(
    section: str,
    config: Mapping[str, Any],
) -> CollectionResolution:
    sections = _routing_sections(config)
    key = section.strip().lower() if section and section.strip() else "default"
    route = sections.get(key) or sections.get("default")
    if not isinstance(route, Mapping):
        raise CollectionConfigError(f"Unknown section: {section}")
    nexus_collection = route.get("nexus_collection")
    legacy_collection = route.get("legacy_collection")
    domain = route.get("domain")
    if not isinstance(nexus_collection, str) or not isinstance(legacy_collection, str):
        raise CollectionConfigError(f"Invalid routing for section: {section}")
    if not isinstance(domain, str):
        domain = _collection_domain(config, nexus_collection)
    return CollectionResolution(
        requested=key,
        nexus_collection=nexus_collection,
        physical_collection=legacy_collection,
        domain=domain,
        retrievable=_domain_is_retrievable(config, domain),
        legacy_collection=legacy_collection,
        used_legacy=True,
    )


def resolve_collection(
    *,
    section: str | None = None,
    collection: str | None = None,
    allow_non_retrievable: bool = True,
    config: Mapping[str, Any] | None = None,
    legacy_mapping: Mapping[str, str] | None = None,
) -> CollectionResolution:
    """Resolve client-facing routing into a controlled Nexus collection.

    Legacy Chroma names remain accepted only when they are listed in
    `legacy_collection_mapping.yml`. Unknown client-provided collections are
    rejected instead of being passed to ChromaDB.
    """
    cfg = config or load_collection_config()
    mapping = legacy_mapping or load_legacy_mapping()
    raw_collection = (collection or "").strip().lower()

    if raw_collection:
        if raw_collection in mapping:
            nexus_collection = mapping[raw_collection]
            domain = _collection_domain(cfg, nexus_collection)
            resolution = CollectionResolution(
                requested=raw_collection,
                nexus_collection=nexus_collection,
                physical_collection=raw_collection,
                domain=domain,
                retrievable=_domain_is_retrievable(cfg, domain),
                legacy_collection=raw_collection,
                used_legacy=True,
            )
        elif raw_collection in _chroma_collections(cfg):
            domain = _collection_domain(cfg, raw_collection)
            resolution = CollectionResolution(
                requested=raw_collection,
                nexus_collection=raw_collection,
                physical_collection=raw_collection,
                domain=domain,
                retrievable=_domain_is_retrievable(cfg, domain),
            )
        else:
            raise CollectionConfigError(f"Unknown collection: {raw_collection}")
    else:
        resolution = _section_resolution(section or "default", cfg)

    if not allow_non_retrievable and not resolution.retrievable:
        raise CollectionConfigError(
            f"Collection {resolution.nexus_collection} is not retrievable"
        )
    if resolution.used_legacy:
        logger.warning(
            "Legacy Chroma collection '%s' resolved to Nexus collection '%s'",
            resolution.physical_collection,
            resolution.nexus_collection,
        )
    return resolution


def nexus_collection_domain(collection_name: str, config: Mapping[str, Any] | None = None) -> str:
    return _collection_domain(config or load_collection_config(), collection_name)
