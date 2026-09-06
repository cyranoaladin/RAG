#!/usr/bin/env python3
"""Construire l'inventaire gouverné des dix collections multi-niveaux."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import nexus_pdf_page_policy as page_policy
import yaml
from nexus_contracts.ingestion import CollectionProfile
from nexus_release_chain.publication_chunking import DEFAULT_TARGET_TOKENS

INVENTORY_KIND = "MULTILEVEL_CANDIDATE_INVENTORY_V1"
CATALOG_DELTA_KIND = "MULTILEVEL_CATALOG_VNEXT_DESCRIPTOR_V1"
PLACEMENT_DELTA_KIND = "APPEND_ONLY_EXACT_PLACEMENT_DELTA_V1"
CURRENTNESS_EVIDENCE_KIND = "MULTILEVEL_ARTIFACT_CURRENTNESS_V1"
CURRENTNESS_AUDIT_KIND = "MULTILEVEL_CURRENTNESS_NETWORK_AUDIT_V1"
#: Schéma du préflight consommé ici. **Pourquoi V2 et non V1.** Depuis la
#: politique de pages (PR #142), l'extraction distingue une page vide qui rend
#: le document incomplet d'une page structurellement incapable de porter un
#: glyphe, que l'extracteur conserve. Et le découpage — donc chaque
#: `chunk_sha256` — dépend de la version de pypdf et du prédicat de pages.
#:
#: V1 n'a d'emplacement ni pour l'un ni pour l'autre : il ne connaît qu'un
#: compteur de pages vides, et ne nomme aucun runtime. Deux préflights V1 issus
#: de deux extracteurs différents sont indiscernables — c'est la panne
#: constatée, la release scellée le 13/08 et le banc d'ingestion actuel
#: divergeant de plusieurs centaines de chunks sans qu'aucune preuve ne dise
#: sous quel extracteur le sceau avait été apposé.
#:
#: V2 DÉCLARE ces deux faits. Il n'élargit aucune porte : un artefact portant
#: une page structurellement vide est nommé, et reste refusé à la release.
PREFLIGHT_EVIDENCE_KIND = "MULTILEVEL_RELEASE_PREFLIGHT_V2"
SUBJECT_RELEASE_KIND = "MULTILEVEL_SUBJECT_RELEASE_V1"
AGGREGATE_RELEASE_KIND = "MULTILEVEL_AGGREGATE_RELEASE_V1"
SCHOOL_YEAR = "2026-2027"
EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
EMBEDDING_INVENTORY_SHA256 = "e2c7384ba36096b3f3bdfff4973f728596104aff0f1d38f1b6463e60765fe22a"
#: Révision amont du tokenizer. `real_e5_tokens` n'a de sens que rapporté à
#: elle : deux révisions ne segmentent pas le même texte de la même façon.
EMBEDDING_MODEL_REVISION = "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"
#: Budget de découpage du chunker gouverné, lu chez lui plutôt que redéclaré.
CHUNK_TARGET_TOKENS = DEFAULT_TARGET_TOKENS
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANKER_INVENTORY_SHA256 = "bdcedc4d7cfe647b9aaa5a7546822dfee7826ebb3c64472bf89eae7592e08fe1"
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")


def canonical_json_bytes(value: object) -> bytes:
    """Sérialiser sans timestamp, avec ordre canonique et LF final."""
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


class _DigestBoundDocument(dict[str, Any]):
    """Document chargé depuis des octets exacts et protégé contre la mutation."""

    source_sha256: str
    canonical_sha256: str

    def __init__(self, document: Mapping[str, Any], *, source_sha256: str) -> None:
        super().__init__(document)
        self.source_sha256 = source_sha256
        self.canonical_sha256 = hashlib.sha256(canonical_json_bytes(self)).hexdigest()


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

_RELEASE_PATHS = {
    "rag_nexus_maths_seconde_tc": "seconde/maths.release.json",
    "rag_nexus_francais_seconde_tc": "seconde/francais.release.json",
    "rag_nexus_maths_quatrieme_tc": "quatrieme/maths.release.json",
    "rag_nexus_francais_quatrieme_tc": "quatrieme/francais.release.json",
    "rag_nexus_maths_premiere_gen_specialite": ("premiere/maths_specialite.release.json"),
    "rag_nexus_nsi_premiere_specialite": "premiere/nsi_specialite.release.json",
    "rag_nexus_francais_premiere_tc": "premiere/francais.release.json",
    "rag_nexus_maths_terminale_gen_specialite": ("terminale/maths_specialite.release.json"),
    "rag_nexus_nsi_terminale_specialite": "terminale/nsi_specialite.release.json",
    "rag_nexus_pc_terminale_specialite": ("terminale/physique_chimie_specialite.release.json"),
}


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
        predicate=lambda placement: (
            same_subject_scope(placement) and placement.get("level") == "multi-niveaux"
        ),
    )
    non_classe = _matching_placements(
        artifacts,
        predicate=lambda placement: (
            same_subject_scope(placement) and placement.get("level") == "non-classe"
        ),
    )
    programmes = _matching_placements(
        artifacts,
        predicate=lambda placement: (
            placement.get("subject") == target["external_subject"]
            and placement.get("document_type") == "programme-officiel"
        ),
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


def _compact_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _set_digest(values: Sequence[object]) -> str:
    canonical = [_compact_json_bytes(value) for value in values]
    if len(canonical) != len(set(canonical)):
        raise ValueError("canonical set contains duplicates")
    ordered = sorted(values, key=_compact_json_bytes)
    return hashlib.sha256(_compact_json_bytes(ordered)).hexdigest()


def _require_document_digest(document: Mapping[str, Any], expected_sha256: str, label: str) -> None:
    expected = _require_sha(expected_sha256, f"{label} SHA")
    canonical = hashlib.sha256(canonical_json_bytes(document)).hexdigest()
    if isinstance(document, _DigestBoundDocument):
        valid = document.source_sha256 == expected and document.canonical_sha256 == canonical
    else:
        valid = canonical == expected
    if not valid:
        raise ValueError(f"{label} digest differs")


def _profile_fingerprint(profile: CollectionProfile) -> str:
    canonical = json.dumps(
        profile.model_dump(mode="json"),
        ensure_ascii=True,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _inventory_release_rows(
    inventory: Mapping[str, Any], candidate_inventory_sha256: str
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, set[str]],
]:
    _require_document_digest(inventory, candidate_inventory_sha256, "candidate inventory")
    if inventory.get("inventory_kind") != INVENTORY_KIND:
        raise ValueError("candidate inventory kind is invalid")
    if inventory.get("school_year") != SCHOOL_YEAR:
        raise ValueError("candidate inventory school year is invalid")
    raw_collections = inventory.get("collections")
    if not isinstance(raw_collections, list) or len(raw_collections) != len(TARGET_MATRIX):
        raise ValueError("candidate inventory collections are invalid")
    expected_collections = [target["collection"] for target in TARGET_MATRIX]
    if [row.get("collection") for row in raw_collections if isinstance(row, Mapping)] != (
        expected_collections
    ):
        raise ValueError("candidate inventory collection order differs")

    artifacts: dict[str, dict[str, Any]] = {}
    candidates_by_collection: dict[str, list[dict[str, Any]]] = {}
    collections_by_sha: dict[str, set[str]] = {}
    placement_identities: set[tuple[str, str]] = set()
    for raw_collection in raw_collections:
        collection = _require_mapping(raw_collection, "candidate collection")
        collection_id = _require_text(collection.get("collection"), "collection")
        raw_candidates = collection.get("candidates")
        if not isinstance(raw_candidates, list):
            raise ValueError("candidate collection artifacts are invalid")
        normalized: list[dict[str, Any]] = []
        for raw_candidate in raw_candidates:
            candidate = dict(_require_mapping(raw_candidate, "candidate artifact"))
            sha = _require_sha(candidate.get("content_sha256"), "candidate SHA")
            path = _require_text(candidate.get("physical_path"), "candidate path")
            placements = candidate.get("placements")
            if not isinstance(placements, list) or not placements:
                raise ValueError(f"candidate {sha} placements are absent")
            normalized_placements: list[dict[str, Any]] = []
            for raw_placement in placements:
                placement = dict(_require_mapping(raw_placement, "candidate placement"))
                source_id = _require_text(
                    placement.get("source_placement_id"), "source placement id"
                )
                identity = (sha, source_id)
                if identity in placement_identities:
                    raise ValueError("candidate placement identity is duplicated")
                placement_identities.add(identity)
                normalized_placements.append(placement)
            candidate["placements"] = sorted(
                normalized_placements,
                key=lambda row: str(row["source_placement_id"]),
            )
            normalized.append(candidate)
            existing = artifacts.get(sha)
            if existing is not None and existing["physical_path"] != path:
                raise ValueError(f"candidate {sha} physical path differs")
            artifacts.setdefault(sha, candidate)
            collections_by_sha.setdefault(sha, set()).add(collection_id)
        candidates_by_collection[collection_id] = sorted(
            normalized, key=lambda row: str(row["content_sha256"])
        )
    counts = _require_mapping(inventory.get("counts"), "candidate inventory counts")
    if (
        counts.get("target_collections") != len(TARGET_MATRIX)
        or counts.get("unique_artifacts") != len(artifacts)
        or counts.get("placements") != len(placement_identities)
    ):
        raise ValueError("candidate inventory counts differ")
    return artifacts, candidates_by_collection, collections_by_sha


def _rows_by_sha(
    evidence: Mapping[str, Any], *, field: str, expected_shas: set[str]
) -> dict[str, dict[str, Any]]:
    raw_rows = evidence.get(field)
    if not isinstance(raw_rows, list):
        raise ValueError(f"{field} must be a list")
    rows: dict[str, dict[str, Any]] = {}
    for raw in raw_rows:
        row = dict(_require_mapping(raw, f"{field} row"))
        sha = _require_sha(row.get("content_sha256"), f"{field} SHA")
        if sha in rows:
            raise ValueError(f"{field} contains a duplicate SHA")
        rows[sha] = row
    if set(rows) != expected_shas:
        raise ValueError(f"{field} artifact set differs from candidate inventory")
    return rows


def _validate_currentness_release_evidence(
    evidence: Mapping[str, Any],
    *,
    evidence_sha256: str,
    candidate_inventory_sha256: str,
    artifacts: Mapping[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    _require_document_digest(evidence, evidence_sha256, "currentness evidence")
    if evidence.get("evidence_kind") != CURRENTNESS_EVIDENCE_KIND:
        raise ValueError("currentness evidence kind is invalid")
    if (
        evidence.get("school_year") != SCHOOL_YEAR
        or evidence.get("candidate_inventory_sha256") != candidate_inventory_sha256
    ):
        raise ValueError("currentness evidence authority differs")
    rows = _rows_by_sha(evidence, field="artifacts", expected_shas=set(artifacts))
    current = sorted(
        sha
        for sha, row in rows.items()
        if row.get("decision") == "CURRENT" and row.get("effective_currentness") == "actuel"
    )
    review = sorted(set(rows) - set(current))
    partition = _require_mapping(evidence.get("partition"), "currentness partition")
    if (
        partition.get("current") != current
        or sorted(partition.get("review_required", [])) != review
        or partition.get("unevaluated") != []
    ):
        raise ValueError("currentness evidence partition differs")
    for sha in current:
        row = rows[sha]
        if (
            row.get("exact_path") != artifacts[sha]["physical_path"]
            or row.get("current_for_school_year") != SCHOOL_YEAR
            or row.get("current_download_sha256") != sha
            or row.get("byte_identity") is not True
        ):
            raise ValueError("currentness artifact binding differs")
    return rows


def _validate_pii_release_evidence(
    evidence: Mapping[str, Any],
    *,
    evidence_sha256: str,
    candidate_inventory_sha256: str,
    corpus_manifest_sha256: str,
    expected_shas: set[str],
) -> dict[str, dict[str, Any]]:
    _require_document_digest(evidence, evidence_sha256, "PII evidence")
    if evidence.get("evidence_kind") != "REAL_CORPUS_PII_SCAN":
        raise ValueError("PII evidence kind is invalid")
    if (
        evidence.get("candidate_inventory_sha256") != candidate_inventory_sha256
        or evidence.get("corpus_manifest_sha256") != corpus_manifest_sha256
        or evidence.get("school_year") != SCHOOL_YEAR
    ):
        raise ValueError("PII evidence authority differs")
    _require_sha(evidence.get("policy_sha256"), "PII policy SHA")
    _require_sha(evidence.get("scanner_sha256"), "PII scanner SHA")
    if (
        evidence.get("remote_access_mode") != "READ_ONLY"
        or evidence.get("remote_write_operations") != 0
        or evidence.get("raw_pii_in_output") is not False
        or evidence.get("raw_pii_in_logs") is not False
    ):
        raise ValueError("PII evidence safety contract differs")
    rows = _rows_by_sha(evidence, field="results", expected_shas=expected_shas)
    summary = _require_mapping(evidence.get("summary"), "PII summary")
    if (
        summary.get("pii_scan_required") != len(expected_shas)
        or summary.get("pii_scanned") != len(expected_shas)
        or summary.get("pii_not_scanned") != 0
        or summary.get("sha256_mismatches") != 0
        or float(summary.get("pii_scan_coverage", 0.0)) != 1.0
    ):
        raise ValueError("PII evidence coverage differs")
    return rows


def _validate_rights_registry(
    registry: Mapping[str, Any], *, registry_sha256: str, corpus_manifest_sha256: str
) -> tuple[str, frozenset[str], str, str]:
    _require_document_digest(registry, registry_sha256, "rights registry")
    decisions = _require_mapping(registry.get("human_rights_decisions"), "human rights decisions")
    sources = _require_mapping(registry.get("source_evidence"), "rights sources")
    matches = [
        _require_mapping(source, "Eduscol rights source")
        for source in sources.values()
        if isinstance(source, Mapping) and source.get("zone") == "01_EDUSCOL_OFFICIEL/"
    ]
    if len(matches) != 1:
        raise ValueError("Eduscol rights source is absent or ambiguous")
    source = matches[0]
    decision_ref = _require_text(source.get("rights_decision_ref"), "rights decision ref")
    decision = _require_mapping(decisions.get(decision_ref), "rights decision")
    if (
        source.get("rights_status") != "CLEARED_BY_HUMAN_DECISION"
        or source.get("recommended_rights_category") != "officiel_public"
        or decision.get("scope_manifest_sha256") != corpus_manifest_sha256
        or decision.get("approved_for_internal_rag") is not True
        or decision.get("approved_for_production_rag") is not True
        or decision.get("generic_rights_blocker") is not False
    ):
        raise ValueError("Eduscol rights authority is not cleared")
    raw_exceptions = registry.get("document_specific_exceptions") or []
    if not isinstance(raw_exceptions, list):
        raise ValueError("rights document exceptions must be a list")
    excepted: set[str] = set()
    for raw in raw_exceptions:
        exception = _require_mapping(raw, "rights document exception")
        sha = _require_sha(exception.get("content_sha256"), "rights exception SHA")
        if sha in excepted:
            raise ValueError("rights document exception is duplicated")
        excepted.add(sha)
    # La décision et la zone sont rendues parce que la preuve de préflight les
    # inscrit : un artefact y déclare SOUS QUELLE décision humaine il est admis,
    # et non la seule catégorie de droits qui en résulte.
    return "officiel_public", frozenset(excepted), decision_ref, "01_EDUSCOL_OFFICIEL/"


def _validate_mapping(
    document: Mapping[str, Any],
    *,
    expected_sha256: str,
    kind: str,
    values_field: str,
    label: str,
) -> dict[str, str]:
    _require_document_digest(document, expected_sha256, label)
    if document.get("mapping_kind") != kind:
        raise ValueError(f"{label} kind is invalid")
    if set(document) != {"mapping_kind", values_field}:
        raise ValueError(f"{label} fields are not exact")
    values = _require_mapping(document.get(values_field), label)
    if not values or any(
        not isinstance(key, str) or not key or not isinstance(value, str) or not value
        for key, value in values.items()
    ):
        raise ValueError(f"{label} entries are invalid")
    return {str(key): str(value) for key, value in values.items()}


def _validate_programme_registry(
    registry: Mapping[str, Any],
    *,
    registry_sha256: str,
    programme_indexes_by_path: Mapping[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """Rend les faits de programme ET les empreintes d'index qu'il faut retrouver.

    La confrontation au préflight n'est plus faite ici : elle appartient à la
    validation du préflight, et l'y avoir laissée obligeait le registre à
    connaître un document que le producteur du préflight ne possède pas
    encore. Le contrôle est identique, exercé à l'endroit qui le comprend."""
    _require_document_digest(registry, registry_sha256, "programme registry")
    if (
        registry.get("registry_kind") != "NEXUS_PROGRAMME_INDEX_REGISTRY_V3"
        or registry.get("school_year") != SCHOOL_YEAR
    ):
        raise ValueError("programme registry authority is invalid")
    if set(registry) != {"registry_kind", "school_year", "indexes", "taxonomies"}:
        raise ValueError("programme registry fields are not exact")
    indexes = registry.get("indexes")
    if not isinstance(indexes, list) or not indexes:
        raise ValueError("programme registry indexes are absent")
    index_digests: dict[str, str] = {}
    for raw in indexes:
        entry = _require_mapping(raw, "programme registry index")
        path = _require_text(entry.get("path"), "programme index path")
        if path in index_digests:
            raise ValueError("programme index path is duplicated")
        index_digests[path] = _require_sha(entry.get("sha256"), "programme index SHA")
        document = _require_mapping(programme_indexes_by_path.get(path), f"programme index {path}")
        _require_document_digest(document, index_digests[path], f"programme index {path}")
        if not isinstance(document.get("fiches"), list):
            raise ValueError("programme index entries are absent")
    raw_taxonomies = registry.get("taxonomies")
    if not isinstance(raw_taxonomies, list) or len(raw_taxonomies) != len(TARGET_MATRIX):
        raise ValueError("programme registry taxonomy facts are absent")
    facts: dict[str, dict[str, str]] = {}
    required = (
        "niveau",
        "voie",
        "matiere",
        "statut_enseignement",
        "programme_version",
    )
    for raw in raw_taxonomies:
        entry = _require_mapping(raw, "programme registry taxonomy")
        collection = _require_text(entry.get("collection"), "taxonomy collection")
        if collection in facts:
            raise ValueError("programme registry collection is duplicated")
        _require_text(entry.get("path"), "taxonomy path")
        _require_sha(entry.get("sha256"), "taxonomy SHA")
        facts[collection] = {
            field: _require_text(entry.get(field), f"taxonomy {field}") for field in required
        }
    if set(facts) != {target["collection"] for target in TARGET_MATRIX}:
        raise ValueError("programme registry collection set differs")
    return facts, index_digests


def _validate_profiles(
    profiles_by_collection: Mapping[str, dict[str, Any]],
    *,
    profile_manifest: Mapping[str, Any],
    profile_manifest_sha256: str,
    programme_facts: Mapping[str, dict[str, str]],
    level_mapping: Mapping[str, str],
    subject_mapping: Mapping[str, str],
) -> dict[str, tuple[CollectionProfile, str]]:
    _require_document_digest(profile_manifest, profile_manifest_sha256, "profile manifest")
    if (
        profile_manifest.get("manifest_kind") != "NEXUS_STAGING_PROFILE_MANIFEST_V1"
        or profile_manifest.get("authority_mode") != "STAGING_LOCAL_GITHUB_ONLY"
        or profile_manifest.get("production_approval") is not False
    ):
        raise ValueError("profile manifest authority is invalid")
    if set(profile_manifest) != {
        "manifest_kind",
        "provenance",
        "generated_at",
        "authority_mode",
        "production_approval",
        "profiles",
    }:
        raise ValueError("profile manifest fields are not exact")
    entries = profile_manifest.get("profiles")
    if not isinstance(entries, list) or len(entries) != len(TARGET_MATRIX):
        raise ValueError("profile manifest collection set differs")
    declared: dict[str, Mapping[str, Any]] = {}
    for raw in entries:
        entry = _require_mapping(raw, "profile manifest entry")
        collection = _require_text(entry.get("collection"), "profile collection")
        if collection in declared:
            raise ValueError("profile manifest collection is duplicated")
        declared[collection] = entry
    if set(declared) != set(profiles_by_collection) or set(declared) != set(programme_facts):
        raise ValueError("profile manifest collection set differs")

    targets = {target["collection"]: target for target in TARGET_MATRIX}
    profiles: dict[str, tuple[CollectionProfile, str]] = {}
    for collection, raw_profile in profiles_by_collection.items():
        profile = CollectionProfile.model_validate(raw_profile)
        fingerprint = _profile_fingerprint(profile)
        declared_profile = declared[collection]
        if (
            declared_profile.get("profile_version") != profile.profile_version
            or declared_profile.get("fingerprint") != fingerprint
            or profile.enabled is not True
        ):
            raise ValueError("runtime profile differs from profile manifest")
        target = targets[collection]
        programme = programme_facts[collection]
        if (
            profile.scope.collection != collection
            or profile.scope.niveau.value != level_mapping[target["external_level"]]
            or profile.scope.matiere != subject_mapping[target["external_subject"]]
            or profile.scope.niveau.value != programme["niveau"]
            or profile.scope.voie.value != programme["voie"]
            or profile.scope.matiere != programme["matiere"]
            or str(profile.scope.programme_version) != programme["programme_version"]
            or profile.scope.school_year != SCHOOL_YEAR
        ):
            raise ValueError("profile scope differs from programme authority")
        profiles[collection] = (profile, fingerprint)
    return profiles


@dataclass(frozen=True)
class PreflightRequirements:
    """Ce que les autorités versionnées exigent d'un préflight, avant lui.

    **Pourquoi cet objet existe.** La sélection — quels contenus sont actuels,
    déchargés de PII et couverts par les droits — était calculée à l'intérieur
    de la validation du préflight, donc inaccessible à qui doit PRODUIRE ce
    préflight. Le producteur aurait dû réimplémenter la même algèbre, et deux
    implémentations d'une même sélection finissent par diverger en silence.
    Elle est calculée une fois, ici, et les deux appelants la lisent."""

    artifacts: dict[str, dict[str, Any]]
    candidates_by_collection: dict[str, list[dict[str, Any]]]
    collections_by_sha: dict[str, set[str]]
    currentness_rows: dict[str, dict[str, Any]]
    pii_rows: dict[str, dict[str, Any]]
    profiles: dict[str, tuple[CollectionProfile, str]]
    programme_facts: dict[str, dict[str, str]]
    programme_index_sha256_by_path: dict[str, str]
    document_types: dict[str, str]
    physical_path_by_sha: dict[str, str]
    bindings: dict[str, str]
    authorities: dict[str, str]
    current_shas: frozenset[str]
    pii_cleared_shas: frozenset[str]
    rights_cleared_shas: frozenset[str]
    type_clear_shas: frozenset[str]
    required_shas: frozenset[str]
    excluded_current_pii_shas: frozenset[str]
    rights_decision_id: str
    rights_zone: str
    rights_category: str


def _require_page_partition(
    row: Mapping[str, Any],
    *,
    sha: str,
    page_count: int,
    covered_pages: set[int],
) -> None:
    """Exiger que chaque page du document soit expliquée, une fois exactement.

    Depuis la politique de pages, un document complet peut porter des pages
    sans texte extractible : celles que le prédicat structurel déclare
    incapables de porter un glyphe. Elles ne sont couvertes par aucun chunk et
    ne sont pas pour autant une extraction manquante. La preuve doit donc
    NOMMER ces pages, et la partition doit être totale et disjointe — sans
    quoi une page jamais lue passerait pour une page volontairement écartée."""
    raw_ignored = row.get("ignored_empty_pages")
    if not isinstance(raw_ignored, list) or any(
        type(page) is not int for page in raw_ignored
    ):
        raise ValueError("preflight ignored empty pages must be strict integers")
    ignored = list(raw_ignored)
    if ignored != sorted(set(ignored)):
        raise ValueError("preflight ignored empty pages must be strictly increasing")
    if any(page < 1 or page > page_count for page in ignored):
        raise ValueError("preflight ignored empty pages are out of bounds")
    if row.get("empty_extracted_pages") != len(ignored):
        raise ValueError("preflight empty page count differs from the named pages")
    overlap = covered_pages & set(ignored)
    if overlap:
        raise ValueError(f"preflight artifact {sha} covers a page it also ignores")
    if covered_pages | set(ignored) != set(range(1, page_count + 1)):
        raise ValueError("preflight page coverage differs")


def _validate_preflight_document(
    preflight: Mapping[str, Any],
    *,
    preflight_sha256: str,
    requirements: PreflightRequirements,
) -> dict[str, dict[str, Any]]:
    """Confronter un préflight aux exigences dérivées des autorités."""
    bindings = requirements.bindings
    expected_shas = set(requirements.required_shas)
    profiles = requirements.profiles
    programme_facts = requirements.programme_facts
    _require_document_digest(preflight, preflight_sha256, "preflight evidence")
    if (
        preflight.get("evidence_kind") != PREFLIGHT_EVIDENCE_KIND
        or preflight.get("school_year") != SCHOOL_YEAR
    ):
        raise ValueError("preflight evidence authority is invalid")
    for field in (
        "candidate_inventory_sha256",
        "currentness_evidence_sha256",
        "pii_evidence_sha256",
        "pii_policy_sha256",
        "rights_registry_sha256",
        "profile_manifest_sha256",
        "programme_registry_sha256",
        "embedding_inventory_sha256",
    ):
        if preflight.get(field) != bindings[field]:
            raise ValueError(f"preflight authority {field} differs")
    if (
        preflight.get("corpus_manifest_sha256") != bindings["corpus_manifest_sha256"]
        or preflight.get("profile_manifest_declared_count") != len(profiles)
        or preflight.get("embedding_model_id") != EMBEDDING_MODEL
        or preflight.get("embedding_model_revision") != EMBEDDING_MODEL_REVISION
        or preflight.get("embedding_dimension") != 1024
        or preflight.get("raw_pii_in_evidence") is not False
        or preflight.get("raw_text_in_evidence") is not False
    ):
        raise ValueError("preflight authority contract differs")
    # D-41 : les empreintes de chunks ne veulent rien dire hors du runtime qui
    # les a produites. Un préflight scellé sous un autre extracteur ou une
    # autre politique de pages décrit un autre découpage, et le dire est le
    # seul moyen de ne pas resceller une release sur une sémantique périmée.
    if preflight.get("extraction_runtime") != {
        "pypdf_version": page_policy.CANONICAL_PYPDF_VERSION,
        "page_policy_id": page_policy.POLICY_ID,
        "page_policy_sha256": page_policy.policy_source_sha256(),
    }:
        raise ValueError("preflight extraction runtime differs")
    if preflight.get("chunk_target_tokens") != CHUNK_TARGET_TOKENS:
        raise ValueError("preflight chunk budget differs from the governed chunker")
    if (
        dict(_require_mapping(
            preflight.get("programme_index_sha256_by_path"), "preflight programme indexes"
        ))
        != requirements.programme_index_sha256_by_path
    ):
        raise ValueError("preflight programme index authority differs")
    raw_rows = preflight.get("artifacts")
    if not isinstance(raw_rows, list):
        raise ValueError("preflight artifacts are absent")
    rows: dict[str, dict[str, Any]] = {}
    for raw in raw_rows:
        row = dict(_require_mapping(raw, "preflight artifact"))
        sha = _require_sha(row.get("content_sha256"), "preflight SHA")
        if sha in rows:
            raise ValueError("preflight artifact is duplicated")
        rows[sha] = row
    if set(rows) != expected_shas:
        raise ValueError("preflight artifact set differs from release gate set")
    selection = _require_mapping(preflight.get("selection"), "preflight selection")
    raw_excluded = selection.get("excluded_current_pii_sha256")
    if not isinstance(raw_excluded, list) or sorted(raw_excluded) != sorted(
        requirements.excluded_current_pii_shas
    ):
        raise ValueError("preflight excluded current PII set differs")
    if selection.get("current_artifacts") != len(requirements.current_shas) or selection.get(
        "current_and_pii_cleared"
    ) != len(expected_shas):
        raise ValueError("preflight selection counts differ")
    summary = _require_mapping(preflight.get("summary"), "preflight summary")
    total_chunks = 0
    total_pages = 0
    for sha, row in rows.items():
        raw_collections = row.get("collections")
        if not isinstance(raw_collections, list) or not raw_collections:
            raise ValueError("preflight artifact collections are absent")
        observed_collections: set[str] = set()
        for raw_collection in raw_collections:
            collection_row = _require_mapping(raw_collection, "preflight collection")
            collection = _require_text(collection_row.get("collection"), "collection")
            if collection in observed_collections:
                raise ValueError("preflight collection is duplicated")
            observed_collections.add(collection)
            if collection not in profiles:
                raise ValueError("preflight collection is unknown")
            profile, fingerprint = profiles[collection]
            if (
                collection_row.get("profile_version") != profile.profile_version
                or collection_row.get("profile_fingerprint") != fingerprint
                or collection_row.get("programme_version")
                != programme_facts[collection]["programme_version"]
            ):
                raise ValueError("preflight collection authority differs")
        if observed_collections != requirements.collections_by_sha[sha]:
            raise ValueError("preflight collection set differs from inventory")
        chunks = row.get("chunks")
        if not isinstance(chunks, list) or not chunks:
            raise ValueError(f"preflight artifact {sha} chunks are absent")
        page_count = row.get("page_count")
        if not isinstance(page_count, int) or page_count < 1:
            raise ValueError("preflight page count is invalid")
        if row.get("error_code") is not None:
            raise ValueError("preflight artifact records an extraction error")
        # La porte reste celle d'avant V2 : aucune page structurellement vide
        # n'est ADMISE. V2 les nomme pour que le refus soit lisible ; les
        # admettre serait une décision de gouvernance, pas un effet de schéma.
        if (
            row.get("extraction_complete") is not True
            or row.get("empty_extracted_pages") != 0
            or row.get("chunking_complete") is not True
            or float(row.get("page_coverage", 0.0)) != 1.0
            or row.get("empty_chunks") != 0
            or row.get("oversized_model_chunks") != 0
            or row.get("null_page_metadata") != 0
            or row.get("rights") != requirements.rights_category
            or row.get("profile_conformity") is not True
            or row.get("programme_conformity") is not True
            or row.get("placement_clear") is not True
        ):
            raise ValueError("preflight artifact gate is not clear")
        pages: set[int] = set()
        chunk_ids: list[str] = []
        chunk_shas: list[str] = []
        for index, raw_chunk in enumerate(chunks):
            chunk = _require_mapping(raw_chunk, "preflight chunk")
            if chunk.get("chunk_index") != index:
                raise ValueError("preflight chunk indexes are not contiguous")
            chunk_id = _require_sha(chunk.get("chunk_id"), "chunk ID")
            chunk_sha = _require_sha(chunk.get("chunk_sha256"), "chunk SHA")
            expected_chunk_id = hashlib.sha256(
                f"{sha}:{index}:{chunk_sha}".encode()
            ).hexdigest()
            if chunk_id != expected_chunk_id:
                raise ValueError("preflight chunk differs from canonical publisher identity")
            if chunk_id in chunk_ids:
                raise ValueError("preflight chunk ID is duplicated")
            chunk_ids.append(chunk_id)
            chunk_shas.append(chunk_sha)
            start = chunk.get("page_start")
            end = chunk.get("page_end")
            tokens = chunk.get("real_e5_tokens")
            if (
                not isinstance(start, int)
                or not isinstance(end, int)
                or start < 1
                or end < start
                or end > page_count
                or not isinstance(tokens, int)
                or tokens < 1
                or tokens > CHUNK_TARGET_TOKENS
                or tokens > int(preflight.get("embedding_max_sequence_length", 0))
            ):
                raise ValueError("preflight chunk metadata is invalid")
            pages.update(range(start, end + 1))
        _require_page_partition(row, sha=sha, page_count=page_count, covered_pages=pages)
        # Les trois digests scellent les ensembles que la release rescellera :
        # produits par la même fonction, ils se contredisent au premier écart.
        if (
            row.get("chunk_id_set_digest") != _set_digest(chunk_ids)
            or row.get("chunk_sha256_set_digest") != _set_digest(chunk_shas)
            or row.get("page_coverage_digest") != _set_digest(sorted(pages))
        ):
            raise ValueError("preflight chunk set digest differs")
        total_chunks += len(chunks)
        total_pages += page_count
    if (
        summary.get("required") != len(rows)
        or summary.get("evaluated") != len(rows)
        or summary.get("pass") != len(rows)
        or summary.get("full_page_coverage_artifacts") != len(rows)
        or summary.get("review_required") != 0
        or summary.get("total_chunks") != total_chunks
        or summary.get("total_pages") != total_pages
        or summary.get("extraction_failures") != 0
        or summary.get("empty_chunks") != 0
        or summary.get("oversized_model_chunks") != 0
        or summary.get("null_page_metadata") != 0
    ):
        raise ValueError("preflight summary differs from artifact facts")
    return rows
def derive_preflight_requirements(
    *,
    inventory: dict[str, Any],
    candidate_inventory_sha256: str,
    currentness_evidence: dict[str, Any],
    currentness_evidence_sha256: str,
    pii_evidence: dict[str, Any],
    pii_evidence_sha256: str,
    rights_registry: dict[str, Any],
    rights_registry_sha256: str,
    profiles_by_collection: dict[str, dict[str, Any]],
    profile_manifest: dict[str, Any],
    profile_manifest_sha256: str,
    programme_registry: dict[str, Any],
    programme_registry_sha256: str,
    programme_indexes_by_path: dict[str, dict[str, Any]],
    level_mapping: dict[str, Any],
    level_mapping_sha256: str,
    subject_mapping: dict[str, Any],
    subject_mapping_sha256: str,
    document_type_mapping: dict[str, Any],
    document_type_mapping_sha256: str,
) -> PreflightRequirements:
    """Dériver, des seules autorités versionnées, ce qu'un préflight doit dire.

    Aucun préflight n'entre ici : c'est la condition pour qu'un producteur de
    préflight puisse s'en servir sans circularité."""
    artifacts, candidates_by_collection, collections_by_sha = _inventory_release_rows(
        inventory, candidate_inventory_sha256
    )
    corpus_manifest_sha = _require_sha(
        inventory.get("corpus_manifest_sha256"), "corpus manifest SHA"
    )
    currentness_rows = _validate_currentness_release_evidence(
        currentness_evidence,
        evidence_sha256=currentness_evidence_sha256,
        candidate_inventory_sha256=candidate_inventory_sha256,
        artifacts=artifacts,
    )
    pii_rows = _validate_pii_release_evidence(
        pii_evidence,
        evidence_sha256=pii_evidence_sha256,
        candidate_inventory_sha256=candidate_inventory_sha256,
        corpus_manifest_sha256=corpus_manifest_sha,
        expected_shas=set(artifacts),
    )
    rights, rights_exceptions, rights_decision_id, rights_zone = _validate_rights_registry(
        rights_registry,
        registry_sha256=rights_registry_sha256,
        corpus_manifest_sha256=corpus_manifest_sha,
    )
    levels = _validate_mapping(
        level_mapping,
        expected_sha256=level_mapping_sha256,
        kind="EDUSCOL_MULTILEVEL_LEVELS_V1",
        values_field="external_levels",
        label="level mapping",
    )
    subjects = _validate_mapping(
        subject_mapping,
        expected_sha256=subject_mapping_sha256,
        kind="EDUSCOL_MULTILEVEL_SUBJECTS_V1",
        values_field="external_subjects",
        label="subject mapping",
    )
    document_types = _validate_mapping(
        document_type_mapping,
        expected_sha256=document_type_mapping_sha256,
        kind="EDUSCOL_MULTILEVEL_DOCUMENT_TYPES_V1",
        values_field="document_types",
        label="document type mapping",
    )
    type_clear_shas: set[str] = set()
    for sha, artifact in artifacts.items():
        artifact_types = {
            placement.get("external_document_type") for placement in artifact["placements"]
        }
        if len(artifact_types) == 1 and next(iter(artifact_types)) in document_types:
            type_clear_shas.add(sha)
        for placement in artifact["placements"]:
            if placement.get("external_level") not in levels:
                raise ValueError("unknown external level")
            if placement.get("external_subject") not in subjects:
                raise ValueError("unknown external subject")
    programme_facts, programme_index_digests = _validate_programme_registry(
        programme_registry,
        registry_sha256=programme_registry_sha256,
        programme_indexes_by_path=programme_indexes_by_path,
    )
    profiles = _validate_profiles(
        profiles_by_collection,
        profile_manifest=profile_manifest,
        profile_manifest_sha256=profile_manifest_sha256,
        programme_facts=programme_facts,
        level_mapping=levels,
        subject_mapping=subjects,
    )

    current_shas = {
        sha
        for sha, row in currentness_rows.items()
        if row.get("decision") == "CURRENT" and row.get("effective_currentness") == "actuel"
    }
    pii_cleared_shas = {
        sha
        for sha, row in pii_rows.items()
        if row.get("status") == "CLEARED" and row.get("pii_detected") is False
    }
    rights_cleared_shas = {
        sha
        for sha, artifact in artifacts.items()
        if rights == "officiel_public"
        and sha not in rights_exceptions
        and str(artifact["physical_path"]).startswith("01_EDUSCOL_OFFICIEL/")
    }
    preflight_required = current_shas & pii_cleared_shas & rights_cleared_shas
    bindings = {
        "corpus_manifest_sha256": corpus_manifest_sha,
        "candidate_inventory_sha256": candidate_inventory_sha256,
        "currentness_evidence_sha256": currentness_evidence_sha256,
        "pii_evidence_sha256": pii_evidence_sha256,
        "pii_policy_sha256": _require_sha(pii_evidence.get("policy_sha256"), "PII policy SHA"),
        "rights_registry_sha256": rights_registry_sha256,
        "profile_manifest_sha256": profile_manifest_sha256,
        "programme_registry_sha256": programme_registry_sha256,
        "embedding_inventory_sha256": EMBEDDING_INVENTORY_SHA256,
    }
    return PreflightRequirements(
        artifacts=artifacts,
        candidates_by_collection=candidates_by_collection,
        collections_by_sha=collections_by_sha,
        currentness_rows=currentness_rows,
        pii_rows=pii_rows,
        profiles=profiles,
        programme_facts=programme_facts,
        programme_index_sha256_by_path=programme_index_digests,
        document_types=document_types,
        physical_path_by_sha={
            sha: str(artifact["physical_path"]) for sha, artifact in artifacts.items()
        },
        bindings=bindings,
        authorities={
            "corpus_manifest_sha256": corpus_manifest_sha,
            "parent_sealed_catalog_sha256": _require_sha(
                inventory.get("sealed_catalog_sha256"), "parent catalog SHA"
            ),
            "placement_catalog_sha256": _require_sha(
                inventory.get("placement_catalog_sha256"), "placement catalog SHA"
            ),
            "catalog_delta_sha256": _require_sha(
                inventory.get("catalog_delta_sha256"), "catalog delta SHA"
            ),
            "effective_catalog_authority_sha256": _require_sha(
                inventory.get("effective_catalog_authority_sha256"),
                "effective catalog authority SHA",
            ),
            "candidate_inventory_sha256": candidate_inventory_sha256,
            "currentness_evidence_sha256": currentness_evidence_sha256,
            "pii_evidence_sha256": pii_evidence_sha256,
            "pii_policy_sha256": bindings["pii_policy_sha256"],
            "pii_scanner_sha256": _require_sha(
                pii_evidence.get("scanner_sha256"), "PII scanner SHA"
            ),
            "rights_registry_sha256": rights_registry_sha256,
            "programme_registry_sha256": programme_registry_sha256,
            "profile_manifest_sha256": profile_manifest_sha256,
            "level_mapping_sha256": _require_sha(level_mapping_sha256, "level mapping SHA"),
            "subject_mapping_sha256": _require_sha(subject_mapping_sha256, "subject mapping SHA"),
            "document_type_mapping_sha256": _require_sha(
                document_type_mapping_sha256, "document type mapping SHA"
            ),
            "embedding_inventory_sha256": EMBEDDING_INVENTORY_SHA256,
            "reranker_inventory_sha256": RERANKER_INVENTORY_SHA256,
        },
        current_shas=frozenset(current_shas),
        pii_cleared_shas=frozenset(pii_cleared_shas),
        rights_cleared_shas=frozenset(rights_cleared_shas),
        type_clear_shas=frozenset(type_clear_shas),
        required_shas=frozenset(preflight_required),
        excluded_current_pii_shas=frozenset(current_shas - preflight_required),
        rights_decision_id=rights_decision_id,
        rights_zone=rights_zone,
        rights_category=rights,
    )


def _release_context(
    *,
    preflight_evidence: dict[str, Any],
    preflight_evidence_sha256: str,
    **inputs: Any,
) -> dict[str, Any]:
    """Confronter le préflight aux exigences, puis partitionner les candidats."""
    requirements = derive_preflight_requirements(**inputs)
    preflight_rows = _validate_preflight_document(
        preflight_evidence,
        preflight_sha256=preflight_evidence_sha256,
        requirements=requirements,
    )
    artifacts = requirements.artifacts
    collections_by_sha = requirements.collections_by_sha

    by_content: dict[str, dict[str, Any]] = {}
    release_eligible: list[str] = []
    named_noneligible: list[str] = []
    for sha in sorted(artifacts):
        reasons: list[str] = []
        if sha not in requirements.current_shas:
            reasons.append("CURRENTNESS_NOT_CURRENT")
        if sha not in requirements.pii_cleared_shas:
            reasons.append("PII_NOT_CLEARED")
        if sha not in requirements.rights_cleared_shas:
            reasons.append("RIGHTS_NOT_CLEARED")
        if sha not in requirements.type_clear_shas:
            reasons.append("TYPE_DOC_UNMAPPED")
        if sha in requirements.required_shas:
            row = preflight_rows[sha]
            if row.get("extraction_complete") is not True:
                reasons.append("EXTRACTION_INCOMPLETE")
            if row.get("chunking_complete") is not True:
                reasons.append("CHUNKING_INCOMPLETE")
            if row.get("profile_conformity") is not True:
                reasons.append("PROFILE_NOT_CONFORM")
            if row.get("programme_conformity") is not True:
                reasons.append("PROGRAMME_NOT_CONFORM")
            if row.get("placement_clear") is not True:
                reasons.append("PLACEMENT_NOT_CLEAR")
        eligible = not reasons
        if eligible:
            release_eligible.append(sha)
        else:
            named_noneligible.append(sha)
        by_content[sha] = {
            "release_eligible": eligible,
            "reason_codes": reasons,
            "collections": sorted(collections_by_sha[sha]),
        }

    return {
        "artifacts": artifacts,
        "candidates_by_collection": requirements.candidates_by_collection,
        "currentness_rows": requirements.currentness_rows,
        "preflight_rows": preflight_rows,
        "profiles": requirements.profiles,
        "programme_facts": requirements.programme_facts,
        "document_types": requirements.document_types,
        "eligibility": {
            "counts": {
                "candidate_artifacts": len(artifacts),
                "release_eligible": len(release_eligible),
                "named_noneligible": len(named_noneligible),
                "unevaluated": 0,
            },
            "partition": {
                "release_eligible": release_eligible,
                "named_noneligible": named_noneligible,
                "unevaluated": [],
            },
            "by_content": by_content,
        },
        "authorities": {
            **requirements.authorities,
            "preflight_evidence_sha256": _require_sha(
                preflight_evidence_sha256, "preflight evidence SHA"
            ),
        },
    }


def evaluate_release_eligibility(
    **inputs: Any,
) -> dict[str, Any]:
    """Évaluer exhaustivement les gates sans produire de manifest partiel."""
    context = _release_context(**inputs)
    return {
        "evidence_kind": "MULTILEVEL_RELEASE_ELIGIBILITY_V1",
        "school_year": SCHOOL_YEAR,
        "authorities": context["authorities"],
        **context["eligibility"],
    }


def _release_artifact(
    *,
    candidate: Mapping[str, Any],
    currentness: Mapping[str, Any],
    collection: str,
    profile: CollectionProfile,
    programme: Mapping[str, str],
    preflight: Mapping[str, Any],
    type_doc_by_external: Mapping[str, str],
) -> dict[str, Any]:
    sha = _require_sha(candidate.get("content_sha256"), "release content SHA")
    raw_placements = candidate.get("placements")
    if not isinstance(raw_placements, list) or not raw_placements:
        raise ValueError("release candidate placements are absent")
    types = {
        _require_text(
            _require_mapping(raw, "release candidate placement").get("external_document_type"),
            "external document type",
        )
        for raw in raw_placements
    }
    if len(types) != 1:
        raise ValueError("release artifact document type is ambiguous")
    source_facts = {
        (
            source.get("source_url"),
            source.get("title"),
            source.get("external_scope"),
        )
        for source in (
            _require_mapping(raw, "release candidate placement") for raw in raw_placements
        )
    }
    if len(source_facts) != 1:
        raise ValueError("release artifact source metadata is ambiguous")
    type_doc = type_doc_by_external[next(iter(types))]
    statut = programme["statut_enseignement"]
    placement_template = {
        "source_scope": _require_text(
            _require_mapping(raw_placements[0], "release placement").get("external_scope"),
            "source scope",
        ),
        "collection": collection,
        "tenant": str(profile.scope.tenant),
        "niveau": profile.scope.niveau.value,
        "voie": profile.scope.voie.value,
        "matiere": str(profile.scope.matiere),
        "statut_enseignement": statut,
        "candidat": profile.scope.candidat.value,
        "visibility": str(profile.scope.visibility),
        "school_year": str(profile.scope.school_year),
        "programme_version": str(profile.scope.programme_version),
        "currentness": "current",
        "placement_status": "active",
        "review_status": "reviewed",
    }
    placement_document = {
        "artifact_id": sha,
        "audience": sorted(value.value for value in profile.scope.audience),
        "candidat": profile.scope.candidat.value,
        "collection": str(profile.scope.collection),
        "matiere": str(profile.scope.matiere),
        "niveau": profile.scope.niveau.value,
        "programme_version": str(profile.scope.programme_version),
        "school_year": str(profile.scope.school_year),
        "statut_enseignement": statut,
        "tenant": str(profile.scope.tenant),
        "visibility": str(profile.scope.visibility),
        "voie": profile.scope.voie.value,
    }
    placement_id = hashlib.sha256(_compact_json_bytes(placement_document)).hexdigest()
    placements = []
    for raw in raw_placements:
        source = _require_mapping(raw, "release placement")
        placements.append(
            {
                "placement_id": placement_id,
                "source_placement_id": _require_text(
                    source.get("source_placement_id"), "source placement id"
                ),
                **placement_template,
            }
        )
    placement_ids = [row["placement_id"] for row in placements]
    if len(placement_ids) != len(set(placement_ids)):
        raise ValueError("release candidate has ambiguous canonical placements")

    raw_chunks = preflight.get("chunks")
    if not isinstance(raw_chunks, list) or not raw_chunks:
        raise ValueError("release chunks are absent")
    chunks = [
        {
            "chunk_index": row["chunk_index"],
            "chunk_id": row["chunk_id"],
            "chunk_sha256": row["chunk_sha256"],
            "page_start": row["page_start"],
            "page_end": row["page_end"],
        }
        for row in raw_chunks
        if isinstance(row, Mapping)
    ]
    pages = sorted(
        {page for chunk in chunks for page in range(chunk["page_start"], chunk["page_end"] + 1)}
    )
    first = _require_mapping(raw_placements[0], "release placement")
    return {
        "content_sha256": sha,
        "source_path": _require_text(candidate.get("physical_path"), "release path"),
        "source_url": _require_official_url(
            currentness.get("current_download_url"), "release download URL"
        ),
        "title": _require_text(first.get("title"), "release title"),
        "type_doc": type_doc,
        "page_count": preflight["page_count"],
        "placements": placements,
        "chunks": chunks,
        "placement_id_set_digest": _set_digest(placement_ids),
        "chunk_id_set_digest": _set_digest([row["chunk_id"] for row in chunks]),
        "chunk_sha256_set_digest": _set_digest([row["chunk_sha256"] for row in chunks]),
        "page_coverage_digest": _set_digest(pages),
    }


def build_release_bundle(
    **inputs: Any,
) -> dict[str, Any]:
    """Construire dix releases non vides et leur agrégat digest-bound."""
    context = _release_context(**inputs)
    eligibility = {
        "evidence_kind": "MULTILEVEL_RELEASE_ELIGIBILITY_V1",
        "school_year": SCHOOL_YEAR,
        "authorities": context["authorities"],
        **context["eligibility"],
    }
    eligible = set(eligibility["partition"]["release_eligible"])
    models = {
        "embedding": {
            "model_id": EMBEDDING_MODEL,
            "inventory_sha256": EMBEDDING_INVENTORY_SHA256,
            "dimension": 1024,
        },
        "reranker": {
            "model_id": RERANKER_MODEL,
            "inventory_sha256": RERANKER_INVENTORY_SHA256,
        },
    }
    subject_releases: list[dict[str, Any]] = []
    total_counts = {"artifacts": 0, "placements": 0, "chunks": 0}
    for target in TARGET_MATRIX:
        collection = target["collection"]
        profile, fingerprint = context["profiles"][collection]
        candidates = [
            candidate
            for candidate in context["candidates_by_collection"][collection]
            if candidate["content_sha256"] in eligible
        ]
        if not candidates:
            raise ValueError(f"release collection {collection} is empty")
        artifacts = [
            _release_artifact(
                candidate=candidate,
                currentness=context["currentness_rows"][candidate["content_sha256"]],
                collection=collection,
                profile=profile,
                programme=context["programme_facts"][collection],
                preflight=context["preflight_rows"][candidate["content_sha256"]],
                type_doc_by_external=context["document_types"],
            )
            for candidate in candidates
        ]
        counts = {
            "artifacts": len(artifacts),
            "placements": sum(len(row["placements"]) for row in artifacts),
            "chunks": sum(len(row["chunks"]) for row in artifacts),
        }
        for field in total_counts:
            total_counts[field] += counts[field]
        manifest = {
            "release_kind": SUBJECT_RELEASE_KIND,
            "release_id": f"multilevel-{collection}-2026-2027-v1",
            "school_year": SCHOOL_YEAR,
            "collection": collection,
            "programme_version": context["programme_facts"][collection]["programme_version"],
            "authorities": context["authorities"],
            "profile": {
                "version": profile.profile_version,
                "fingerprint": fingerprint,
                "manifest_digest": inputs["profile_manifest_sha256"],
            },
            "models": models,
            "expected_counts": counts,
            "artifacts": artifacts,
        }
        subject_releases.append(
            {
                "path": _RELEASE_PATHS[collection],
                "sha256": hashlib.sha256(canonical_json_bytes(manifest)).hexdigest(),
                "manifest": manifest,
            }
        )
    aggregate = {
        "release_kind": AGGREGATE_RELEASE_KIND,
        "release_id": "multilevel-2026-2027-v1",
        "school_year": SCHOOL_YEAR,
        "authorities": context["authorities"],
        "models": models,
        "expected_counts": total_counts,
        "subjects": [
            {
                "path": release["path"],
                "sha256": release["sha256"],
                "collection": release["manifest"]["collection"],
            }
            for release in subject_releases
        ],
    }
    return {
        "eligibility": eligibility,
        "subject_releases": subject_releases,
        "aggregate_release": aggregate,
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


def _require_file_sha(path: Path, expected_sha256: str, label: str) -> None:
    expected = _require_sha(expected_sha256, f"expected {label} SHA")
    actual = file_sha256(path)
    if actual != expected:
        raise ValueError(f"{label} digest differs")


def _bounded_repository_file(repository_root: Path, relative: object) -> Path:
    value = _require_text(relative, "repository-relative path")
    relative_path = Path(value)
    root = repository_root.resolve()
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("repository-relative path escapes repository root")
    resolved = (root / relative_path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("repository-relative path escapes repository root")
    return resolved


def load_authority_cli_inputs(args: argparse.Namespace) -> dict[str, Any]:
    """Charger les autorités versionnées, sans le préflight.

    Séparé du chargement de release parce que le producteur de préflight a
    besoin d'exactement ces entrées — et d'aucune preuve de préflight, qu'il
    n'a pas encore. Les deux commandes lisent donc les mêmes octets, vérifiés
    par les mêmes empreintes, par un seul chemin de code."""
    document_specs = {
        "inventory": (Path(args.inventory), args.inventory_sha256, _load_json),
        "currentness_evidence": (
            Path(args.currentness),
            args.currentness_sha256,
            _load_json,
        ),
        "pii_evidence": (Path(args.pii), args.pii_sha256, _load_json),
        "rights_registry": (
            Path(args.rights_registry),
            args.rights_registry_sha256,
            _load_yaml,
        ),
        "profile_manifest": (
            Path(args.profile_manifest),
            args.profile_manifest_sha256,
            _load_json,
        ),
        "programme_registry": (
            Path(args.programme_registry),
            args.programme_registry_sha256,
            _load_yaml,
        ),
        "level_mapping": (
            Path(args.level_mapping),
            args.level_mapping_sha256,
            _load_yaml,
        ),
        "subject_mapping": (
            Path(args.subject_mapping),
            args.subject_mapping_sha256,
            _load_yaml,
        ),
        "document_type_mapping": (
            Path(args.document_type_mapping),
            args.document_type_mapping_sha256,
            _load_yaml,
        ),
    }
    inputs: dict[str, Any] = {}
    digest_input_names = {"inventory": "candidate_inventory_sha256"}
    for name, (path, digest, loader) in document_specs.items():
        label = name.replace("_", " ")
        _require_file_sha(path, digest, label)
        inputs[name] = _DigestBoundDocument(loader(path), source_sha256=digest)
        inputs[digest_input_names.get(name, f"{name}_sha256")] = digest

    profiles_dir = Path(args.profiles_dir)
    profile_paths = sorted({*profiles_dir.glob("*.yml"), *profiles_dir.glob("*.yaml")})
    if len(profile_paths) != len(TARGET_MATRIX):
        raise ValueError("profiles directory must contain exactly ten profiles")
    profiles: dict[str, dict[str, Any]] = {}
    for path in profile_paths:
        profile = _load_yaml(path)
        scope = _require_mapping(profile.get("scope"), "profile scope")
        collection = _require_text(scope.get("collection"), "profile collection")
        if collection in profiles:
            raise ValueError("profile collection is duplicated")
        profiles[collection] = profile
    inputs["profiles_by_collection"] = profiles

    repository_root = Path(args.repository_root)
    registry = inputs["programme_registry"]
    raw_indexes = registry.get("indexes")
    if not isinstance(raw_indexes, list) or not raw_indexes:
        raise ValueError("programme registry indexes are absent")
    index_documents: dict[str, dict[str, Any]] = {}
    for raw in raw_indexes:
        entry = _require_mapping(raw, "programme registry index")
        relative = _require_text(entry.get("path"), "programme index path")
        path = _bounded_repository_file(repository_root, relative)
        _require_file_sha(
            path,
            _require_sha(entry.get("sha256"), "programme index SHA"),
            f"programme index {relative}",
        )
        index_documents[relative] = _DigestBoundDocument(
            _load_yaml(path),
            source_sha256=_require_sha(entry.get("sha256"), "programme index SHA"),
        )
    raw_taxonomies = registry.get("taxonomies")
    if not isinstance(raw_taxonomies, list) or len(raw_taxonomies) != len(TARGET_MATRIX):
        raise ValueError("programme registry taxonomies are absent")
    for raw in raw_taxonomies:
        entry = _require_mapping(raw, "programme registry taxonomy")
        relative = _require_text(entry.get("path"), "taxonomy path")
        path = _bounded_repository_file(repository_root, relative)
        _require_file_sha(
            path,
            _require_sha(entry.get("sha256"), "taxonomy SHA"),
            f"taxonomy {relative}",
        )
    inputs["programme_indexes_by_path"] = index_documents
    return inputs


def _load_release_cli_inputs(args: argparse.Namespace) -> dict[str, Any]:
    """Les autorités, plus la preuve de préflight que la release confronte."""
    inputs = load_authority_cli_inputs(args)
    preflight_path = Path(args.preflight)
    _require_file_sha(preflight_path, args.preflight_sha256, "preflight evidence")
    inputs["preflight_evidence"] = _DigestBoundDocument(
        _load_json(preflight_path), source_sha256=args.preflight_sha256
    )
    inputs["preflight_evidence_sha256"] = args.preflight_sha256
    return inputs


def _write_release_bundle(output_root: Path, bundle: Mapping[str, Any]) -> None:
    raw_releases = bundle.get("subject_releases")
    if not isinstance(raw_releases, list) or len(raw_releases) != len(TARGET_MATRIX):
        raise ValueError("release bundle subject set is invalid")
    for raw in raw_releases:
        release = _require_mapping(raw, "subject release bundle")
        relative = _require_text(release.get("path"), "subject release path")
        if relative not in set(_RELEASE_PATHS.values()):
            raise ValueError("subject release path is outside the closed release matrix")
        path = output_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json_bytes(release.get("manifest")))
    aggregate = _require_mapping(bundle.get("aggregate_release"), "aggregate release")
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "multilevel.release.json").write_bytes(canonical_json_bytes(aggregate))
    eligibility = _require_mapping(bundle.get("eligibility"), "release eligibility")
    (output_root / "multilevel.eligibility.json").write_bytes(canonical_json_bytes(eligibility))


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
    release_parser = subparsers.add_parser("release")
    for option in (
        "inventory",
        "currentness",
        "pii",
        "preflight",
        "rights-registry",
        "profile-manifest",
        "programme-registry",
        "level-mapping",
        "subject-mapping",
        "document-type-mapping",
    ):
        release_parser.add_argument(f"--{option}", type=Path, required=True)
        release_parser.add_argument(f"--{option}-sha256", required=True)
    release_parser.add_argument("--profiles-dir", type=Path, required=True)
    release_parser.add_argument("--repository-root", type=Path, required=True)
    release_parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "inventory":
        output_path: Path = args.output
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
        output_path = args.output
        inventory_path: Path = args.inventory
        audit_path: Path = args.audit_results
        document = build_currentness_evidence(
            _load_json(inventory_path),
            candidate_inventory_sha256=file_sha256(inventory_path),
            audited_currentness=_load_json(audit_path),
            audited_currentness_sha256=file_sha256(audit_path),
        )
    elif args.command == "release":
        bundle = build_release_bundle(**_load_release_cli_inputs(args))
        _write_release_bundle(Path(args.output_root), bundle)
        return 0
    else:
        parser.error(f"unsupported command: {args.command}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(canonical_json_bytes(document))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
