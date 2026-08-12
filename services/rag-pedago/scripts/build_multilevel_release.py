#!/usr/bin/env python3
"""Construire l'inventaire gouverné des dix collections multi-niveaux."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

INVENTORY_KIND = "MULTILEVEL_CANDIDATE_INVENTORY_V1"
SCHOOL_YEAR = "2026-2027"
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")


def canonical_json_bytes(value: object) -> bytes:
    """Sérialiser sans timestamp, avec ordre canonique et LF final."""
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()

TARGET_MATRIX: tuple[dict[str, str], ...] = (
    {
        "phase": "A",
        "collection": "rag_nexus_maths_seconde_tc",
        "external_level": "seconde",
        "external_subject": "mathematiques",
        "external_scope": "lycee/commun/mathematiques",
    },
    {
        "phase": "A",
        "collection": "rag_nexus_francais_seconde_tc",
        "external_level": "seconde",
        "external_subject": "francais",
        "external_scope": "lycee/commun/francais",
    },
    {
        "phase": "A",
        "collection": "rag_nexus_maths_quatrieme_tc",
        "external_level": "4e",
        "external_subject": "mathematiques",
        "external_scope": "college/cycle-4/mathematiques",
    },
    {
        "phase": "A",
        "collection": "rag_nexus_francais_quatrieme_tc",
        "external_level": "4e",
        "external_subject": "francais",
        "external_scope": "college/cycle-4/francais",
    },
    {
        "phase": "B",
        "collection": "rag_nexus_maths_premiere_gen_specialite",
        "external_level": "premiere",
        "external_subject": "mathematiques",
        "external_scope": "lycee/commun/mathematiques",
    },
    {
        "phase": "B",
        "collection": "rag_nexus_nsi_premiere_specialite",
        "external_level": "premiere",
        "external_subject": "nsi",
        "external_scope": "lycee/general/nsi",
    },
    {
        "phase": "B",
        "collection": "rag_nexus_francais_premiere_tc",
        "external_level": "premiere",
        "external_subject": "francais",
        "external_scope": "lycee/commun/francais",
    },
    {
        "phase": "C",
        "collection": "rag_nexus_maths_terminale_gen_specialite",
        "external_level": "terminale",
        "external_subject": "mathematiques",
        "external_scope": "lycee/commun/mathematiques",
    },
    {
        "phase": "C",
        "collection": "rag_nexus_nsi_terminale_specialite",
        "external_level": "terminale",
        "external_subject": "nsi",
        "external_scope": "lycee/general/nsi",
    },
    {
        "phase": "C",
        "collection": "rag_nexus_pc_terminale_specialite",
        "external_level": "terminale",
        "external_subject": "physique-chimie",
        "external_scope": "lycee/seconde/physique-chimie",
    },
)


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _require_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase 64-hex SHA-256")
    return value


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonblank")
    return value


def _candidate_for_artifact(
    sha: str,
    artifact: Mapping[str, Any],
    selected_placements: list[Mapping[str, Any]],
) -> dict[str, Any]:
    physical_objects = artifact.get("physical_objects")
    if not isinstance(physical_objects, list) or len(physical_objects) != 1:
        raise ValueError(f"artifact {sha} must have exactly one physical object")
    physical = _require_mapping(physical_objects[0], f"artifact {sha} physical object")
    if physical.get("content_sha256") != sha:
        raise ValueError(f"artifact {sha} physical object SHA differs")
    physical_path = _require_text(physical.get("path"), "physical path")
    if not physical_path.startswith("01_EDUSCOL_OFFICIEL/") or not physical_path.endswith(
        ".pdf"
    ):
        raise ValueError(f"artifact {sha} is not an official Eduscol PDF")

    placements: list[dict[str, Any]] = []
    placement_ids: set[str] = set()
    for placement in selected_placements:
        if placement.get("content_sha256") != sha:
            raise ValueError(f"artifact {sha} placement SHA differs")
        placement_id = _require_text(placement.get("scope_path"), "scope path")
        if placement_id in placement_ids:
            raise ValueError(f"artifact {sha} has a duplicate placement")
        placement_ids.add(placement_id)
        placements.append(
            {
                "source_placement_id": placement_id,
                "source_url": _require_text(placement.get("source_url"), "source URL"),
                "title": _require_text(placement.get("title"), "title"),
                "external_level": _require_text(placement.get("level"), "level"),
                "external_subject": _require_text(placement.get("subject"), "subject"),
                "external_scope": _require_text(placement.get("scope"), "scope"),
                "external_document_type": _require_text(
                    placement.get("document_type"), "document type"
                ),
                "pedagogical_status": _require_text(placement.get("status"), "status"),
                "year": str(placement.get("year", "")),
            }
        )
    placements.sort(key=lambda row: row["source_placement_id"])
    return {
        "content_sha256": sha,
        "physical_path": physical_path,
        "physical_currentness_candidate": str(physical.get("currentness", "")),
        "physical_disposition_candidate": str(physical.get("disposition", "")),
        "placements": placements,
    }


def _matching_placements(
    artifacts: Mapping[str, Any],
    *,
    predicate: Any,
) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for raw_sha, raw_artifact in artifacts.items():
        sha = _require_sha(raw_sha, "artifact key")
        artifact = _require_mapping(raw_artifact, f"artifact {sha}")
        placements = artifact.get("pedagogical_placements")
        if not isinstance(placements, list):
            raise ValueError(f"artifact {sha} placements must be a list")
        for raw_placement in placements:
            placement = _require_mapping(raw_placement, f"artifact {sha} placement")
            if not predicate(placement):
                continue
            matches.append(
                {
                    "content_sha256": sha,
                    "source_placement_id": _require_text(
                        placement.get("scope_path"), "scope path"
                    ),
                    "level": _require_text(placement.get("level"), "level"),
                    "subject": _require_text(placement.get("subject"), "subject"),
                    "scope": _require_text(placement.get("scope"), "scope"),
                    "document_type": _require_text(
                        placement.get("document_type"), "document type"
                    ),
                    "status": _require_text(placement.get("status"), "status"),
                    "title": _require_text(placement.get("title"), "title"),
                }
            )
    return sorted(
        matches,
        key=lambda row: (row["content_sha256"], row["source_placement_id"]),
    )


def _placement_route(route_id: str, matches: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "route_id": route_id,
        "unique_artifacts": len({row["content_sha256"] for row in matches}),
        "placement_count": len(matches),
        "matches": matches,
    }


def _physical_path_route(
    artifacts: Mapping[str, Any], target: Mapping[str, str]
) -> dict[str, Any]:
    level = target["external_level"].upper()
    level_fragment = f"/COLLEGE/{level}/" if level == "4E" else f"/LYCEE/{level}/"
    subject_fragment = {
        "francais": "FRANCAIS",
        "mathematiques": "MATHEMATIQUES",
        "nsi": "NSI",
        "physique-chimie": "PHYSIQUE_CHIMIE",
    }[target["external_subject"]]
    matches: list[dict[str, str]] = []
    for raw_sha, raw_artifact in artifacts.items():
        sha = _require_sha(raw_sha, "artifact key")
        artifact = _require_mapping(raw_artifact, f"artifact {sha}")
        physical_objects = artifact.get("physical_objects")
        if not isinstance(physical_objects, list):
            raise ValueError(f"artifact {sha} physical objects must be a list")
        for raw_physical in physical_objects:
            physical = _require_mapping(raw_physical, f"artifact {sha} physical object")
            path = _require_text(physical.get("path"), "physical path")
            if level_fragment in f"/{path}" and f"/{subject_fragment}/" in f"/{path}":
                matches.append({"content_sha256": sha, "physical_path": path})
    matches.sort(key=lambda row: (row["content_sha256"], row["physical_path"]))
    return {
        "route_id": "physical_paths",
        "unique_artifacts": len({row["content_sha256"] for row in matches}),
        "physical_objects": len(matches),
        "matches": matches,
    }


def _official_source_route(
    official_sources: Mapping[str, Any], collection: str
) -> dict[str, Any]:
    raw_sources = official_sources.get("sources")
    if not isinstance(raw_sources, list):
        raise ValueError("official sources.sources must be a list")
    sources: list[dict[str, str]] = []
    for raw_source in raw_sources:
        source = _require_mapping(raw_source, "official source")
        collections = source.get("collections_cibles")
        if not isinstance(collections, list) or collection not in collections:
            continue
        sources.append(
            {
                "id": _require_text(source.get("id"), "official source id"),
                "status": _require_text(source.get("status"), "official source status"),
                "url": _require_text(source.get("url"), "official source URL"),
            }
        )
    sources.sort(key=lambda row: row["id"])
    return {
        "route_id": "configured_official_sources",
        "unique_artifacts": 0,
        "source_count": len(sources),
        "sources": sources,
    }


def _discovery_routes(
    artifacts: Mapping[str, Any],
    target: Mapping[str, str],
    candidates: list[dict[str, Any]],
    official_sources: Mapping[str, Any],
) -> list[dict[str, Any]]:
    exact_matches = [
        placement
        for candidate in candidates
        for placement in candidate["placements"]
    ]
    exact_route_matches = [
        {
            "content_sha256": candidate["content_sha256"],
            "source_placement_id": placement["source_placement_id"],
        }
        for candidate in candidates
        for placement in candidate["placements"]
    ]
    exact_route = {
        "route_id": "exact_placements",
        "unique_artifacts": len({row["content_sha256"] for row in candidates}),
        "placement_count": len(exact_matches),
        "matches": exact_route_matches,
    }
    def same_subject_scope(placement: Mapping[str, Any]) -> bool:
        return (
            placement.get("subject") == target["external_subject"]
            and placement.get("scope") == target["external_scope"]
        )
    multi = _matching_placements(
        artifacts,
        predicate=lambda placement: same_subject_scope(placement)
        and placement.get("level") == "multi-niveaux",
    )
    non_classe = _matching_placements(
        artifacts,
        predicate=lambda placement: same_subject_scope(placement)
        and placement.get("level") == "non-classe",
    )
    programmes = _matching_placements(
        artifacts,
        predicate=lambda placement: placement.get("subject")
        == target["external_subject"]
        and placement.get("document_type") == "programme-officiel",
    )
    return [
        exact_route,
        _physical_path_route(artifacts, target),
        _placement_route("multi_niveaux", multi),
        _placement_route("non_classe", non_classe),
        _placement_route("subject_programme", programmes),
        _official_source_route(official_sources, target["collection"]),
    ]


def build_candidate_inventory(
    catalog: dict[str, Any],
    *,
    sealed_catalog_sha256: str,
    official_sources: dict[str, Any],
) -> dict[str, Any]:
    """Sélectionner les placements exact-grade PDF Eduscol des dix cibles."""
    _require_sha(sealed_catalog_sha256, "sealed catalog SHA")
    if catalog.get("catalog_kind") != "REAL_SEALED_CORPUS":
        raise ValueError("sealed catalog kind is invalid")
    if catalog.get("verification_passed") is not True:
        raise ValueError("sealed catalog is not verified")
    manifest_sha = _require_sha(catalog.get("manifest_sha256"), "manifest SHA")
    placement_catalog_sha = _require_sha(
        catalog.get("placement_catalog_sha256"), "placement catalog SHA"
    )
    artifacts = _require_mapping(catalog.get("artifacts"), "catalog artifacts")
    official_source_mapping = _require_mapping(official_sources, "official sources")

    collection_rows: list[dict[str, Any]] = []
    global_shas: set[str] = set()
    global_placement_ids: set[tuple[str, str]] = set()
    global_physical_paths: set[str] = set()
    global_multi_placement_shas: set[str] = set()

    for target in TARGET_MATRIX:
        candidates: list[dict[str, Any]] = []
        for raw_sha, raw_artifact in artifacts.items():
            sha = _require_sha(raw_sha, "artifact key")
            artifact = _require_mapping(raw_artifact, f"artifact {sha}")
            raw_placements = artifact.get("pedagogical_placements")
            if not isinstance(raw_placements, list):
                raise ValueError(f"artifact {sha} placements must be a list")
            selected = [
                _require_mapping(value, f"artifact {sha} placement")
                for value in raw_placements
                if isinstance(value, Mapping)
                and value.get("level") == target["external_level"]
                and value.get("subject") == target["external_subject"]
                and value.get("scope") == target["external_scope"]
            ]
            if not selected:
                continue
            candidate = _candidate_for_artifact(sha, artifact, selected)
            candidates.append(candidate)

        candidates.sort(key=lambda row: row["content_sha256"])
        collection_shas = {row["content_sha256"] for row in candidates}
        collection_paths = {row["physical_path"] for row in candidates}
        collection_placements = {
            (row["content_sha256"], placement["source_placement_id"])
            for row in candidates
            for placement in row["placements"]
        }
        collection_multi = {
            row["content_sha256"] for row in candidates if len(row["placements"]) > 1
        }
        global_shas.update(collection_shas)
        global_physical_paths.update(collection_paths)
        global_placement_ids.update(collection_placements)
        global_multi_placement_shas.update(collection_multi)
        local_partition = {
            "exact_grade_gate_pending": sorted(collection_shas),
            "named_noneligible": [],
            "unevaluated": [],
        }
        collection_rows.append(
            {
                **target,
                "counts": {
                    "unique_artifacts": len(collection_shas),
                    "placements": len(collection_placements),
                    "physical_objects": len(collection_paths),
                    "multi_placement_artifacts": len(collection_multi),
                },
                "candidates": candidates,
                "observed_values": {
                    "levels": sorted(
                        {
                            placement["external_level"]
                            for candidate in candidates
                            for placement in candidate["placements"]
                        }
                    ),
                    "subjects": sorted(
                        {
                            placement["external_subject"]
                            for candidate in candidates
                            for placement in candidate["placements"]
                        }
                    ),
                    "scopes": sorted(
                        {
                            placement["external_scope"]
                            for candidate in candidates
                            for placement in candidate["placements"]
                        }
                    ),
                    "document_types": sorted(
                        {
                            placement["external_document_type"]
                            for candidate in candidates
                            for placement in candidate["placements"]
                        }
                    ),
                    "pedagogical_statuses": sorted(
                        {
                            placement["pedagogical_status"]
                            for candidate in candidates
                            for placement in candidate["placements"]
                        }
                    ),
                    "physical_paths": sorted(collection_paths),
                },
                "candidate_partition": local_partition,
                "inventory_disposition": (
                    "EXACT_GRADE_GATES_PENDING"
                    if candidates
                    else "PLACEMENT_PROOF_OR_CORPUS_DELTA_REQUIRED"
                ),
                "discovery_routes": _discovery_routes(
                    artifacts, target, candidates, official_source_mapping
                ),
            }
        )

    return {
        "inventory_kind": INVENTORY_KIND,
        "school_year": SCHOOL_YEAR,
        "corpus_manifest_sha256": manifest_sha,
        "sealed_catalog_sha256": sealed_catalog_sha256,
        "placement_catalog_sha256": placement_catalog_sha,
        "counts": {
            "target_collections": len(TARGET_MATRIX),
            "unique_artifacts": len(global_shas),
            "placements": len(global_placement_ids),
            "physical_objects": len(global_physical_paths),
            "multi_placement_artifacts": len(global_multi_placement_shas),
        },
        "candidate_partition": {
            "exact_grade_gate_pending": sorted(global_shas),
            "named_noneligible": [],
            "unevaluated": [],
        },
        "collection_partition": {
            "exact_grade_gates_pending": [
                row["collection"]
                for row in collection_rows
                if row["inventory_disposition"] == "EXACT_GRADE_GATES_PENDING"
            ],
            "placement_proof_or_corpus_delta_required": [
                row["collection"]
                for row in collection_rows
                if row["inventory_disposition"]
                == "PLACEMENT_PROOF_OR_CORPUS_DELTA_REQUIRED"
            ],
            "unevaluated": [],
        },
        "collections": collection_rows,
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory_parser = subparsers.add_parser("inventory")
    inventory_parser.add_argument("--catalog", type=Path, required=True)
    inventory_parser.add_argument("--output", type=Path, required=True)
    inventory_parser.add_argument(
        "--official-sources",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "configs" / "eduscol_sources.yml",
    )
    args = parser.parse_args(argv)
    if args.command != "inventory":
        parser.error(f"unsupported command: {args.command}")
    catalog_path: Path = args.catalog
    output_path: Path = args.output
    sources_path: Path = args.official_sources
    inventory = build_candidate_inventory(
        _load_json(catalog_path),
        sealed_catalog_sha256=file_sha256(catalog_path),
        official_sources=_load_yaml(sources_path),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(canonical_json_bytes(inventory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
