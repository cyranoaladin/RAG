#!/usr/bin/env python3
"""Construire l'inventaire gouverné des dix collections multi-niveaux."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

INVENTORY_KIND = "MULTILEVEL_CANDIDATE_INVENTORY_V1"
CATALOG_DELTA_KIND = "MULTILEVEL_CATALOG_VNEXT_DESCRIPTOR_V1"
PLACEMENT_DELTA_KIND = "APPEND_ONLY_EXACT_PLACEMENT_DELTA_V1"
CURRENTNESS_EVIDENCE_KIND = "MULTILEVEL_ARTIFACT_CURRENTNESS_V1"
CURRENTNESS_AUDIT_KIND = "MULTILEVEL_CURRENTNESS_NETWORK_AUDIT_V1"
SCHOOL_YEAR = "2026-2027"
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")


def canonical_json_bytes(value: object) -> bytes:
    """Sérialiser sans timestamp, avec ordre canonique et LF final."""
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


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
    if not physical_path.startswith("01_EDUSCOL_OFFICIEL/") or not physical_path.endswith(".pdf"):
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
                "placement_origin": str(
                    placement.get("_placement_origin", "SEALED_PARENT_CATALOG")
                ),
                "placement_reason_code": placement.get("_placement_reason_code"),
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


def _require_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _apply_catalog_delta(
    catalog: dict[str, Any],
    *,
    sealed_catalog_sha256: str,
    catalog_delta: dict[str, Any],
    catalog_delta_sha256: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    _require_sha(catalog_delta_sha256, "catalog delta SHA")
    if catalog_delta.get("descriptor_kind") != CATALOG_DELTA_KIND:
        raise ValueError("catalog delta descriptor kind is invalid")
    if catalog_delta.get("school_year") != SCHOOL_YEAR:
        raise ValueError(f"catalog delta school_year must be {SCHOOL_YEAR}")
    parent = _require_mapping(catalog_delta.get("parent"), "catalog delta parent")
    if parent.get("sealed_catalog_sha256") != sealed_catalog_sha256:
        raise ValueError("catalog delta parent sealed catalog SHA differs")
    if parent.get("corpus_manifest_sha256") != catalog.get("manifest_sha256"):
        raise ValueError("catalog delta parent corpus manifest SHA differs")
    if parent.get("placement_catalog_sha256") != catalog.get("placement_catalog_sha256"):
        raise ValueError("catalog delta parent placement catalog SHA differs")

    parent_counts = {
        "content_artifact_count": _require_int(
            catalog.get("content_artifact_count"), "parent content artifact count"
        ),
        "physical_object_count": _require_int(
            catalog.get("physical_object_count"), "parent physical object count"
        ),
        "pedagogical_placement_count": _require_int(
            catalog.get("eduscol_placement_count"), "parent placement count"
        ),
    }
    for field, value in parent_counts.items():
        if parent.get(field) != value:
            raise ValueError(f"catalog delta parent {field} differs")

    raw_delta = _require_mapping(catalog_delta.get("delta"), "catalog delta")
    if raw_delta.get("delta_kind") != PLACEMENT_DELTA_KIND:
        raise ValueError("placement delta kind is invalid")
    if raw_delta.get("physical_object_additions") != []:
        raise ValueError("placement-only delta cannot add physical objects")
    additions = raw_delta.get("placement_additions")
    if not isinstance(additions, list) or not additions:
        raise ValueError("placement delta additions must be a non-empty list")
    payload_sha = _require_sha(
        raw_delta.get("placement_additions_sha256"),
        "placement additions digest",
    )
    actual_payload_sha = hashlib.sha256(canonical_json_bytes(additions)).hexdigest()
    if payload_sha != actual_payload_sha:
        raise ValueError("placement additions digest differs")

    expected_counts = _require_mapping(
        catalog_delta.get("expected_vnext_counts"), "expected vNext counts"
    )
    expected = {
        "content_artifacts": parent_counts["content_artifact_count"],
        "physical_objects": parent_counts["physical_object_count"],
        "pedagogical_placements": parent_counts["pedagogical_placement_count"] + len(additions),
    }
    if dict(expected_counts) != expected:
        raise ValueError("catalog delta expected vNext counts differ")

    effective = copy.deepcopy(catalog)
    parent_artifacts = _require_mapping(catalog.get("artifacts"), "parent artifacts")
    effective_artifacts = _require_mapping(effective.get("artifacts"), "effective artifacts")
    targets = {target["collection"]: target for target in TARGET_MATRIX}
    addition_keys: set[tuple[str, str]] = set()
    immutable_fields = (
        "document_type",
        "status",
        "title",
        "year",
        "source_url",
        "source_object",
    )
    for index, raw_addition in enumerate(additions):
        addition = _require_mapping(raw_addition, f"placement addition {index}")
        sha = _require_sha(addition.get("content_sha256"), "placement addition SHA")
        target_collection = _require_text(addition.get("target_collection"), "target collection")
        target = targets.get(target_collection)
        if target is None:
            raise ValueError("placement addition target collection is unknown")
        parent_artifact = _require_mapping(parent_artifacts.get(sha), f"parent artifact {sha}")
        effective_artifact = effective_artifacts.get(sha)
        if not isinstance(effective_artifact, dict):
            raise ValueError(f"effective artifact {sha} must be a mutable mapping")
        physical_path = _require_text(addition.get("physical_path"), "physical path")
        physical_objects = parent_artifact.get("physical_objects")
        if not isinstance(physical_objects, list) or len(physical_objects) != 1:
            raise ValueError(f"parent artifact {sha} physical object is ambiguous")
        physical = _require_mapping(physical_objects[0], f"parent artifact {sha} physical object")
        if physical.get("content_sha256") != sha or physical.get("path") != physical_path:
            raise ValueError(f"placement addition {sha} physical binding differs")

        source_placement_id = _require_text(
            addition.get("source_placement_id"), "source placement id"
        )
        parent_placements = parent_artifact.get("pedagogical_placements")
        if not isinstance(parent_placements, list):
            raise ValueError(f"parent artifact {sha} placements must be a list")
        source_matches = [
            _require_mapping(value, f"parent artifact {sha} placement")
            for value in parent_placements
            if isinstance(value, Mapping) and value.get("scope_path") == source_placement_id
        ]
        if len(source_matches) != 1:
            raise ValueError(f"placement addition {sha} source placement is not exact")
        source = source_matches[0]

        if addition.get("reason_code") != "EXACT_GRADE_PLACEMENT_PROOF":
            raise ValueError("placement addition reason code is invalid")
        proof = _require_mapping(addition.get("placement_proof"), "placement proof")
        if proof != {
            "proof_kind": "EXPLICIT_GOVERNED_EXACT_GRADE_PLACEMENT_V1",
            "source_catalog_placement_id": source_placement_id,
            "physical_object_reused": True,
            "pdf_bytes_added": False,
        }:
            raise ValueError("placement addition proof is invalid")

        new_placement = dict(_require_mapping(addition.get("placement"), "new exact placement"))
        if new_placement.get("content_sha256") != sha:
            raise ValueError("placement addition content SHA differs")
        expected_fields = {
            "level": target["external_level"],
            "subject": target["external_subject"],
            "scope": target["external_scope"],
        }
        if any(new_placement.get(field) != value for field, value in expected_fields.items()):
            raise ValueError("placement addition does not match target matrix")
        for field in immutable_fields:
            if field in source and new_placement.get(field) != source.get(field):
                raise ValueError(f"placement addition changes source field {field}")
        new_placement_id = _require_text(new_placement.get("scope_path"), "new exact scope path")
        key = (sha, new_placement_id)
        existing_ids = {
            str(value.get("scope_path"))
            for value in parent_placements
            if isinstance(value, Mapping)
        }
        if key in addition_keys or new_placement_id in existing_ids:
            raise ValueError("placement delta contains a duplicate placement")
        addition_keys.add(key)
        for field in ("level_path", "technical_path", "source_object", "family"):
            _require_text(new_placement.get(field), f"new placement {field}")
        new_placement["_placement_origin"] = PLACEMENT_DELTA_KIND
        new_placement["_placement_reason_code"] = addition["reason_code"]
        effective_placements = effective_artifact.get("pedagogical_placements")
        if not isinstance(effective_placements, list):
            raise ValueError(f"effective artifact {sha} placements must be a list")
        effective_placements.append(new_placement)
        effective_artifact["pedagogical_placement_count"] = len(effective_placements)

    effective["eduscol_placement_count"] = expected["pedagogical_placements"]
    authority = {
        "catalog_delta_sha256": catalog_delta_sha256,
        "catalog_delta_payload_sha256": payload_sha,
        "effective_catalog_authority_sha256": hashlib.sha256(
            canonical_json_bytes(
                {
                    "parent_sealed_catalog_sha256": sealed_catalog_sha256,
                    "catalog_delta_sha256": catalog_delta_sha256,
                    "catalog_delta_payload_sha256": payload_sha,
                }
            )
        ).hexdigest(),
    }
    return effective, authority


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
                    "source_placement_id": _require_text(placement.get("scope_path"), "scope path"),
                    "level": _require_text(placement.get("level"), "level"),
                    "subject": _require_text(placement.get("subject"), "subject"),
                    "scope": _require_text(placement.get("scope"), "scope"),
                    "document_type": _require_text(placement.get("document_type"), "document type"),
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


def _physical_path_route(artifacts: Mapping[str, Any], target: Mapping[str, str]) -> dict[str, Any]:
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


def _official_source_route(official_sources: Mapping[str, Any], collection: str) -> dict[str, Any]:
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
    exact_matches = [placement for candidate in candidates for placement in candidate["placements"]]
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
        predicate=lambda placement: placement.get("subject") == target["external_subject"]
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
    catalog_delta: dict[str, Any] | None = None,
    catalog_delta_sha256: str | None = None,
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
    if catalog_delta is None:
        if catalog_delta_sha256 is not None:
            raise ValueError("catalog delta SHA provided without catalog delta")
        effective_catalog = catalog
        delta_authority: dict[str, str] = {}
    else:
        if catalog_delta_sha256 is None:
            raise ValueError("catalog delta SHA is required")
        effective_catalog, delta_authority = _apply_catalog_delta(
            catalog,
            sealed_catalog_sha256=sealed_catalog_sha256,
            catalog_delta=catalog_delta,
            catalog_delta_sha256=catalog_delta_sha256,
        )
    artifacts = _require_mapping(effective_catalog.get("artifacts"), "catalog artifacts")
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
        **delta_authority,
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
                if row["inventory_disposition"] == "PLACEMENT_PROOF_OR_CORPUS_DELTA_REQUIRED"
            ],
            "unevaluated": [],
        },
        "collections": collection_rows,
    }


def _require_official_url(value: object, label: str) -> str:
    url = _require_text(value, label)
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if parsed.scheme != "https" or not (
        hostname == "education.gouv.fr" or hostname.endswith(".education.gouv.fr")
    ):
        raise ValueError(f"{label} must be an official HTTPS URL")
    return url


def _inventory_artifacts(
    inventory: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    raw_collections = inventory.get("collections")
    if not isinstance(raw_collections, list) or len(raw_collections) != len(TARGET_MATRIX):
        raise ValueError("candidate inventory collections are invalid")
    artifacts: dict[str, dict[str, Any]] = {}
    collections_by_sha: dict[str, set[str]] = {}
    for raw_collection in raw_collections:
        collection = _require_mapping(raw_collection, "candidate collection")
        collection_id = _require_text(collection.get("collection"), "collection id")
        raw_candidates = collection.get("candidates")
        if not isinstance(raw_candidates, list):
            raise ValueError(f"collection {collection_id} candidates must be a list")
        for raw_candidate in raw_candidates:
            candidate = _require_mapping(raw_candidate, "candidate artifact")
            sha = _require_sha(candidate.get("content_sha256"), "candidate SHA")
            path = _require_text(candidate.get("physical_path"), "candidate path")
            raw_placements = candidate.get("placements")
            if not isinstance(raw_placements, list) or not raw_placements:
                raise ValueError(f"candidate {sha} placements are absent")
            placement_facts = sorted(
                [
                    {
                        "collection": collection_id,
                        "source_placement_id": _require_text(
                            _require_mapping(raw, "candidate placement").get("source_placement_id"),
                            "source placement id",
                        ),
                        "external_level": _require_text(
                            _require_mapping(raw, "candidate placement").get("external_level"),
                            "external level",
                        ),
                        "external_subject": _require_text(
                            _require_mapping(raw, "candidate placement").get("external_subject"),
                            "external subject",
                        ),
                        "external_scope": _require_text(
                            _require_mapping(raw, "candidate placement").get("external_scope"),
                            "external scope",
                        ),
                        "external_document_type": _require_text(
                            _require_mapping(raw, "candidate placement").get(
                                "external_document_type"
                            ),
                            "external document type",
                        ),
                    }
                    for raw in raw_placements
                ],
                key=lambda row: (row["collection"], row["source_placement_id"]),
            )
            if sha in artifacts and artifacts[sha]["exact_path"] != path:
                raise ValueError(f"candidate {sha} has conflicting physical paths")
            artifact = artifacts.setdefault(
                sha,
                {
                    "content_sha256": sha,
                    "exact_path": path,
                    "placement_facts": [],
                },
            )
            artifact["placement_facts"].extend(placement_facts)
            collections_by_sha.setdefault(sha, set()).add(collection_id)
    for artifact in artifacts.values():
        artifact["placement_facts"] = sorted(
            artifact["placement_facts"],
            key=lambda row: (row["collection"], row["source_placement_id"]),
        )
    return artifacts, collections_by_sha


def _review_reason_codes(artifact: Mapping[str, Any]) -> list[str]:
    codes = ["CURRENT_SOURCE_BYTE_IDENTITY_NOT_AUDITED"]
    path = str(artifact.get("exact_path", ""))
    placement_facts = artifact.get("placement_facts")
    if isinstance(placement_facts, list) and any(
        isinstance(fact, Mapping) and fact.get("external_subject") == "francais" and "/HLP/" in path
        for fact in placement_facts
    ):
        codes.append("PHYSICAL_SUBJECT_ALIGNMENT_REVIEW_REQUIRED")
    if isinstance(placement_facts, list) and any(
        isinstance(fact, Mapping) and fact.get("external_document_type") == "programme-officiel"
        for fact in placement_facts
    ):
        codes.append("PROGRAMME_ALIGNMENT_REVIEW_REQUIRED")
    return codes


def build_currentness_evidence(
    inventory: dict[str, Any],
    *,
    candidate_inventory_sha256: str,
    audited_currentness: dict[str, Any],
    audited_currentness_sha256: str,
) -> dict[str, Any]:
    """Partitionner tout l'inventaire sans inférer le currentness du catalogue."""
    _require_sha(candidate_inventory_sha256, "candidate inventory SHA")
    _require_sha(audited_currentness_sha256, "currentness audit SHA")
    if inventory.get("inventory_kind") != INVENTORY_KIND:
        raise ValueError("candidate inventory kind is invalid")
    if inventory.get("school_year") != SCHOOL_YEAR:
        raise ValueError("candidate inventory school year is invalid")
    if audited_currentness.get("audit_kind") != CURRENTNESS_AUDIT_KIND:
        raise ValueError("currentness audit kind is invalid")
    if audited_currentness.get("school_year") != SCHOOL_YEAR:
        raise ValueError("currentness audit school year is invalid")
    if audited_currentness.get("candidate_inventory_sha256") != candidate_inventory_sha256:
        raise ValueError("currentness audit candidate inventory differs")
    if audited_currentness.get("audit_mode") != "READ_ONLY_REUSED_RESULTS":
        raise ValueError("currentness audit mode is invalid")

    inventory_artifacts, collections_by_sha = _inventory_artifacts(inventory)
    raw_results = audited_currentness.get("results")
    if not isinstance(raw_results, list):
        raise ValueError("currentness audit results must be a list")
    current_by_sha: dict[str, dict[str, Any]] = {}
    for raw_result in raw_results:
        result = _require_mapping(raw_result, "currentness audit result")
        sha = _require_sha(result.get("content_sha256"), "currentness audit SHA")
        if sha in current_by_sha:
            raise ValueError(f"currentness audit contains duplicate SHA {sha}")
        if sha not in inventory_artifacts:
            raise ValueError(f"currentness audit SHA {sha} is outside candidate inventory")
        if result.get("current_for_school_year") != SCHOOL_YEAR:
            raise ValueError("currentness audit artifact school year differs")
        if result.get("current_download_sha256") != sha:
            raise ValueError("currentness audit download SHA differs")
        if result.get("byte_identity") is not True:
            raise ValueError("currentness audit byte identity is not exact")
        current_by_sha[sha] = {
            "current_source_listing_url": _require_official_url(
                result.get("current_source_listing_url"), "source listing URL"
            ),
            "current_download_url": _require_official_url(
                result.get("current_download_url"), "current download URL"
            ),
        }

    artifact_rows: list[dict[str, Any]] = []
    current_shas: list[str] = []
    review_shas: list[str] = []
    by_collection: dict[str, dict[str, int]] = {}
    for collection in TARGET_MATRIX:
        collection_id = collection["collection"]
        shas = sorted(
            sha for sha, memberships in collections_by_sha.items() if collection_id in memberships
        )
        if not shas:
            continue
        by_collection[collection_id] = {
            "artifacts": len(shas),
            "current": sum(sha in current_by_sha for sha in shas),
            "review_required": sum(sha not in current_by_sha for sha in shas),
        }

    for sha in sorted(inventory_artifacts):
        base = inventory_artifacts[sha]
        common = {
            "content_sha256": sha,
            "exact_path": base["exact_path"],
            "collections": sorted(collections_by_sha[sha]),
            "placement_facts": base["placement_facts"],
            "current_for_school_year": SCHOOL_YEAR,
        }
        audit = current_by_sha.get(sha)
        if audit is not None:
            current_shas.append(sha)
            artifact_rows.append(
                {
                    **common,
                    "decision": "CURRENT",
                    "reason_codes": ["OFFICIAL_CURRENT_BYTE_IDENTITY_EXACT"],
                    "effective_currentness": "actuel",
                    **audit,
                    "current_download_sha256": sha,
                    "byte_identity": True,
                }
            )
        else:
            review_shas.append(sha)
            artifact_rows.append(
                {
                    **common,
                    "decision": "REVIEW_REQUIRED",
                    "reason_codes": _review_reason_codes(base),
                    "effective_currentness": None,
                    "current_source_listing_url": None,
                    "current_download_url": None,
                    "current_download_sha256": None,
                    "byte_identity": None,
                }
            )

    return {
        "evidence_kind": CURRENTNESS_EVIDENCE_KIND,
        "school_year": SCHOOL_YEAR,
        "candidate_inventory_sha256": candidate_inventory_sha256,
        "currentness_audit_sha256": audited_currentness_sha256,
        "corpus_manifest_sha256": inventory.get("corpus_manifest_sha256"),
        "sealed_catalog_sha256": inventory.get("sealed_catalog_sha256"),
        "placement_catalog_sha256": inventory.get("placement_catalog_sha256"),
        "catalog_delta_sha256": inventory.get("catalog_delta_sha256"),
        "effective_catalog_authority_sha256": inventory.get("effective_catalog_authority_sha256"),
        "decision_basis": "READ_ONLY_OFFICIAL_NETWORK_AUDIT_REUSED_FAIL_CLOSED",
        "counts": {
            "artifacts": len(artifact_rows),
            "evaluated": len(artifact_rows),
            "current": len(current_shas),
            "review_required": len(review_shas),
            "unevaluated": 0,
            "by_collection": by_collection,
        },
        "partition": {
            "current": current_shas,
            "review_required": review_shas,
            "unevaluated": [],
        },
        "artifacts": artifact_rows,
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
    inventory_parser.add_argument("--catalog-delta", type=Path)
    inventory_parser.add_argument("--output", type=Path, required=True)
    inventory_parser.add_argument(
        "--official-sources",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "configs" / "eduscol_sources.yml",
    )
    currentness_parser = subparsers.add_parser("currentness")
    currentness_parser.add_argument("--inventory", type=Path, required=True)
    currentness_parser.add_argument("--audit-results", type=Path, required=True)
    currentness_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output_path: Path = args.output
    if args.command == "inventory":
        catalog_path: Path = args.catalog
        sources_path: Path = args.official_sources
        delta_path: Path | None = args.catalog_delta
        document = build_candidate_inventory(
            _load_json(catalog_path),
            sealed_catalog_sha256=file_sha256(catalog_path),
            official_sources=_load_yaml(sources_path),
            catalog_delta=_load_json(delta_path) if delta_path is not None else None,
            catalog_delta_sha256=(file_sha256(delta_path) if delta_path is not None else None),
        )
    elif args.command == "currentness":
        inventory_path: Path = args.inventory
        audit_path: Path = args.audit_results
        document = build_currentness_evidence(
            _load_json(inventory_path),
            candidate_inventory_sha256=file_sha256(inventory_path),
            audited_currentness=_load_json(audit_path),
            audited_currentness_sha256=file_sha256(audit_path),
        )
    else:
        parser.error(f"unsupported command: {args.command}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(canonical_json_bytes(document))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
