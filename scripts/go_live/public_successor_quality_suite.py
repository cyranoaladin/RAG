#!/usr/bin/env python3
"""Valide la golden figée du successeur public contre les manifests 40b.

Ce contrôle est statique. Il n'affirme aucune qualité HTTP avant la publication
réelle et l'exécution de la suite sur le staging final.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SUITE_PATH = Path("services/rag-engine/tests/fixtures/public_successor_quality_40b.json")
EXPECTED_THRESHOLDS = {
    "positive_nonempty": 33,
    "expected_source_hits_min": 26,
    "expected_source_hits_per_collection_min": 2,
    "zero_result_pass": 11,
    "student_positive_pass": 11,
    "teacher_refusals": 11,
    "unauthenticated_refusals": 11,
    "scope_mismatch_refusals": 11,
    "collection_mismatch_refusals": 11,
    "dense_misses": 0,
    "dense_tie_overflow": 0,
    "out_of_scope_results": 0,
    "missing_citations": 0,
    "attribution_missing": 0,
}
EXPECTED_POPULATION = {"collections": 11, "artifacts": 253, "placements": 377, "chunks": 3975}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class QualitySuiteError(RuntimeError):
    """La suite n'est pas opposable à la release publique."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise QualitySuiteError(f"objet JSON attendu : {path.name}")
    return value


def _same_digest(path: Path, digest: str) -> None:
    if not SHA256.fullmatch(str(digest)) or _sha(path) != digest:
        raise QualitySuiteError(f"digest divergent : {path.name}")


def validate_suite(root: Path, suite: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Retourne l'oracle physique vérifié par collection ou refuse tout écart."""
    try:
        if suite["schema_version"] != 1 or suite["thresholds"] != EXPECTED_THRESHOLDS:
            raise QualitySuiteError("seuils ou version divergents")
        if suite["expected_population"] != EXPECTED_POPULATION:
            raise QualitySuiteError("population attendue divergente")
        manifest_path = root / suite["release_manifest_path"]
        _same_digest(manifest_path, suite["release_manifest_sha256"])
        manifest = _json(manifest_path)
        if manifest["release_id"] != suite["release_id"] or len(manifest["subjects"]) != 11:
            raise QualitySuiteError("release ou sujets divergents")
        base = manifest_path.parent
        registry = manifest["artifact_registry"]
        artifacts_path = base / registry["path"]
        _same_digest(artifacts_path, registry["sha256"])
        artifacts = {row["artifact_id"]: row for row in _json(artifacts_path)["artifacts"]}
        if len(artifacts) != 253 or any(
            row["artifact_id"] != row["content_sha256"]
            or row["media_type"] != "text/plain; charset=utf-8"
            for row in artifacts.values()
        ):
            raise QualitySuiteError("registre des dérivés public divergent")
        names_path = root / suite["scope_names_path"]
        _same_digest(names_path, suite["scope_names_sha256"])
        names = yaml.safe_load(names_path.read_text(encoding="utf-8"))
        if names["release_id"] != manifest["release_id"]:
            raise QualitySuiteError("nommage lié à une autre release")
        scopes = {row["collection"]: row["scope_id"] for row in names["bindings"]}
        if len(scopes) != 11:
            raise QualitySuiteError("nommage incomplet")
        index: dict[str, dict[str, Any]] = {}
        placement_ids: set[str] = set()
        chunk_ids: set[str] = set()
        seen_artifacts: set[str] = set()
        for ref in manifest["subjects"]:
            name = ref["collection"]
            path = base / ref["path"]
            _same_digest(path, ref["sha256"])
            subject = _json(path)
            if subject["collection"] != name:
                raise QualitySuiteError("sujet divergent")
            selected: dict[str, Any] = {}
            for placement in subject["placements"]:
                if (placement["collection"] != name or placement["visibility"] != "public"
                    or placement["placement_status"] != "active"
                    or placement["review_status"] != "reviewed"
                    or placement["currentness"] not in {"current", "official_snapshot"}):
                    raise QualitySuiteError("placement non public ou non revu")
                artifact = artifacts[placement["artifact_id"]]
                content = artifact["content_sha256"]
                selected.setdefault(content, {**artifact, "placement_ids": set()})[
                    "placement_ids"
                ].add(placement["placement_id"])
                seen_artifacts.add(content)
                placement_ids.add(placement["placement_id"])
                chunk_ids.update(chunk["chunk_id"] for chunk in artifact["chunks"])
            if not selected:
                raise QualitySuiteError("collection publique vide")
            index[name] = selected
        population = {"collections": len(index), "artifacts": len(seen_artifacts),
                      "placements": len(placement_ids), "chunks": len(chunk_ids)}
        if population != EXPECTED_POPULATION or set(index) != set(scopes):
            raise QualitySuiteError("population réelle du manifeste divergente")
        if set(suite["collections"]) != set(index):
            raise QualitySuiteError("couverture des onze collections incomplète")
        for name, spec in suite["collections"].items():
            if (spec["scope_id"] != scopes[name] or spec["student_expected_http"] != 200
                or spec["teacher_expected_http"] != 403
                or spec["unauthenticated_expected_http"] != 401
                or spec["scope_mismatch_expected_http"] != 403
                or spec["collection_mismatch_expected_http"] != 403
                or not spec["zero_result_query"].strip()):
                raise QualitySuiteError(f"cas de sécurité absents : {name}")
            positive = spec["positive"]
            if len(positive) != 3 or {row["id"] for row in positive} != {"factual", "no_accent", "notion"}:
                raise QualitySuiteError(f"trois types de requêtes requis : {name}")
            if len({row["query"] for row in positive}) != 3:
                raise QualitySuiteError(f"requêtes dupliquées : {name}")
            for row in positive:
                content = row["expected_content_sha256"]
                if (row["collection"] != name or not row["query"].strip()
                    or content not in index[name] or not SHA256.fullmatch(content)):
                    raise QualitySuiteError(f"source attendue hors manifeste : {name}")
                pages = {chunk["page_start"] for chunk in index[name][content]["chunks"]}
                expected_pages = row["expected_pages_any"]
                if (not expected_pages or not all(isinstance(n, int) and not isinstance(n, bool) for n in expected_pages)
                    or not set(expected_pages) <= pages):
                    raise QualitySuiteError(f"pages attendues hors manifeste : {name}")
                citation = index[name][content]["citation"]
                keys = ("source_uri", "source_label", "licensor", "licence_id",
                        "source_updated_at", "derivative_notice")
                if (row["expected_citation"] != {key: citation[key] for key in keys}
                    or citation["licence_id"] != "ETALAB-2.0"
                    or not all(citation[key] for key in keys)):
                    raise QualitySuiteError(f"attribution divergente : {name}")
                if row["id"] == "no_accent" and any(
                    unicodedata.combining(char)
                    for char in unicodedata.normalize("NFD", row["query"])
                ):
                    raise QualitySuiteError(f"requête non accentuée requise : {name}")
        return index
    except (KeyError, TypeError, ValueError, OSError, IndexError) as exc:
        raise QualitySuiteError(f"suite incomplète ou invalide : {type(exc).__name__}") from exc


def check_positive(
    case: dict[str, Any], response: dict[str, Any], index: dict[str, dict[str, Any]]
) -> bool:
    """Contrôle tous les résultats servis ; retourne le hit source/page attendu."""
    try:
        collection = case["collection"]
        filters = response["filters_applied"]
        if (filters["collection"] != collection
            or not SHA256.fullmatch(str(filters["scope_digest"]))):
            raise QualitySuiteError(f"{collection} : filtres serveur divergents")
        results = response["results"]
        if not isinstance(results, list) or not results:
            raise QualitySuiteError(f"{collection} : résultat vide")
        expected_hit = False
        for result in results:
            metadata = result["metadata"]
            if metadata["collection"] != collection:
                raise QualitySuiteError(f"{collection} : résultat hors scope")
            content = metadata["content_sha256"]
            artifact = index[collection].get(content)
            if (artifact is None or result["doc_id"] != content
                or metadata["artifact_id"] != content
                or metadata["placement_id"] not in artifact["placement_ids"]
                or metadata["review_status"] != "reviewed"):
                raise QualitySuiteError(f"{collection} : identité ou revue divergente")
            chunks = {row["chunk_id"]: row for row in artifact["chunks"]}
            chunk = chunks.get(result["chunk_id"])
            if chunk is None or chunk["page_start"] is None or chunk["page_end"] is None:
                raise QualitySuiteError(f"{collection} : chunk/page hors manifeste")
            citation = result["citation"]
            expected = artifact["citation"]
            fields = ("source_uri", "source_label", "licensor", "licence_id",
                      "source_updated_at", "derivative_notice")
            if (not isinstance(citation, dict)
                or citation["rights"] != "public_allowed"
                or citation["page"] != chunk["page_start"]
                or any(citation[key] != expected[key] or not citation[key] for key in fields)):
                raise QualitySuiteError(f"{collection} : citation ou attribution divergente")
            if (content == case["expected_content_sha256"]
                and citation["page"] in case["expected_pages_any"]):
                expected_hit = True
        return expected_hit
    except (KeyError, TypeError, ValueError) as exc:
        raise QualitySuiteError(f"réponse incomplète : {type(exc).__name__}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        suite = _json(args.repository_root / SUITE_PATH)
        validate_suite(args.repository_root, suite)
    except QualitySuiteError as exc:
        print(f"PUBLIC_SUCCESSOR_QUALITY_SUITE=FAIL reason={exc}")
        return 1
    print("PUBLIC_SUCCESSOR_QUALITY_SUITE=PASS collections=11 positive_cases=33")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
