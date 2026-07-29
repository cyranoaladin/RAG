#!/usr/bin/env python3
"""Vérifie la cohérence des snapshots cockpit avec leurs catalogues canoniques."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:
    print("PyYAML est requis pour vérifier les snapshots cockpit.", file=sys.stderr)
    raise SystemExit(2)


class UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader qui refuse les clés YAML dupliquées."""


def construct_unique_mapping(
    loader: UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"clé dupliquée: {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_unique_mapping,
)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Lecture JSON impossible ({path.name}): {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def load_yaml(path: Path) -> Any:
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except (OSError, yaml.YAMLError) as exc:
        print(f"Lecture YAML impossible ({path.name}): {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def index_entries(
    entries: Any,
    *,
    label: str,
    identifier: str,
    duplicate_label: str,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(entries, list):
        errors.append(f"{label}: une liste est requise")
        return {}

    indexed: dict[str, dict[str, Any]] = {}
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"{label}[{position}]: une entrée objet est requise")
            continue
        entry_id = entry.get(identifier)
        if not isinstance(entry_id, str) or not entry_id:
            errors.append(f"{label}[{position}]: {identifier} non vide requis")
            continue
        if entry_id in indexed:
            errors.append(f"{label}: {duplicate_label} dupliqué: {entry_id}")
            continue
        indexed[entry_id] = entry
    return indexed


def compare_indexed_entries(
    snapshot: dict[str, dict[str, Any]],
    canonical: dict[str, dict[str, Any]],
    *,
    snapshot_label: str,
    field_mapping: tuple[tuple[str, str], ...],
    errors: list[str],
) -> None:
    snapshot_ids = set(snapshot)
    canonical_ids = set(canonical)
    for entry_id in sorted(canonical_ids - snapshot_ids):
        errors.append(f"{snapshot_label}: entrée manquante: {entry_id}")
    for entry_id in sorted(snapshot_ids - canonical_ids):
        errors.append(f"{snapshot_label}: entrée surnuméraire: {entry_id}")

    for entry_id in sorted(snapshot_ids & canonical_ids):
        snapshot_entry = snapshot[entry_id]
        canonical_entry = canonical[entry_id]
        for snapshot_field, canonical_field in field_mapping:
            if snapshot_field not in snapshot_entry:
                errors.append(
                    f"{entry_id}: champ {snapshot_label} manquant: {snapshot_field}"
                )
                continue
            if canonical_field not in canonical_entry:
                errors.append(
                    f"{entry_id}: champ canonique manquant: {canonical_field}"
                )
                continue
            snapshot_value = snapshot_entry[snapshot_field]
            canonical_value = canonical_entry[canonical_field]
            if snapshot_value != canonical_value:
                errors.append(
                    f"{entry_id}.{snapshot_field}: "
                    f"{snapshot_label}="
                    f"{json.dumps(snapshot_value, ensure_ascii=False, sort_keys=True)} "
                    "canonique="
                    f"{json.dumps(canonical_value, ensure_ascii=False, sort_keys=True)}"
                )


def validate_sources(
    snapshot_document: Any,
    canonical_document: Any,
) -> tuple[list[str], int]:
    errors: list[str] = []
    canonical_entries = (
        canonical_document.get("sources")
        if isinstance(canonical_document, dict)
        else None
    )
    snapshot = index_entries(
        snapshot_document,
        label="JSON sources",
        identifier="id",
        duplicate_label="id",
        errors=errors,
    )
    canonical = index_entries(
        canonical_entries,
        label="YAML sources",
        identifier="id",
        duplicate_label="id",
        errors=errors,
    )
    compare_indexed_entries(
        snapshot,
        canonical,
        snapshot_label="JSON sources",
        field_mapping=(
            ("id", "id"),
            ("url", "url"),
            ("status", "status"),
            ("matiere", "matiere"),
            ("niveaux", "niveaux"),
            ("collections", "collections_cibles"),
        ),
        errors=errors,
    )
    return errors, len(snapshot)


def validate_collections(
    snapshot_document: Any,
    canonical_document: Any,
) -> tuple[list[str], int]:
    errors: list[str] = []
    canonical_mapping = (
        canonical_document.get("collections")
        if isinstance(canonical_document, dict)
        else None
    )
    snapshot = index_entries(
        snapshot_document,
        label="JSON collections",
        identifier="name",
        duplicate_label="nom",
        errors=errors,
    )
    if not isinstance(canonical_mapping, dict):
        errors.append("YAML collections: un objet de collections est requis")
        canonical: dict[str, dict[str, Any]] = {}
    else:
        canonical = {}
        for name, value in canonical_mapping.items():
            if not isinstance(name, str) or not name:
                errors.append("YAML collections: nom non vide requis")
            elif not isinstance(value, dict):
                errors.append(f"YAML collections.{name}: un objet est requis")
            else:
                canonical[name] = {"name": name, **value}

    if len(snapshot) != 59:
        errors.append(
            f"JSON collections: 59 entrées requises, trouvé={len(snapshot)}"
        )
    if len(canonical) != 59:
        errors.append(
            f"YAML collections: 59 entrées requises, trouvé={len(canonical)}"
        )

    compare_indexed_entries(
        snapshot,
        canonical,
        snapshot_label="JSON collections",
        field_mapping=(
            ("name", "name"),
            ("matiere", "matiere"),
            ("niveau", "niveau"),
            ("voie", "voie"),
            ("statut", "statut"),
            ("domain", "domain"),
            ("taxonomy_file", "taxonomy_file"),
            ("instanciee", "instanciee"),
        ),
        errors=errors,
    )
    return errors, len(snapshot)


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(
            "Usage: validate_cockpit_snapshots.py "
            "sources.json eduscol_sources.yml collections.json rag_collections.yml",
            file=sys.stderr,
        )
        return 2

    sources_json, sources_yaml, collections_json, collections_yaml = map(
        Path, argv[1:]
    )
    source_errors, source_count = validate_sources(
        load_json(sources_json),
        load_yaml(sources_yaml),
    )
    collection_errors, collection_count = validate_collections(
        load_json(collections_json),
        load_yaml(collections_yaml),
    )
    errors = [*source_errors, *collection_errors]

    if errors:
        print(
            f"Concordance snapshots cockpit: ÉCHEC ({len(errors)} divergence(s))",
            file=sys.stderr,
        )
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Concordance sources cockpit/Eduscol: PASS ({source_count} sources)")
    print(
        "Concordance collections cockpit/rag-engine: "
        f"PASS ({collection_count} collections; "
        "catalogue uniquement, corpus non validé)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
