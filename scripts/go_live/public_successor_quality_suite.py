#!/usr/bin/env python3
"""Valide la golden figée du successeur public contre les manifests 40b.

Ce contrôle est statique. Il n'affirme aucune qualité HTTP avant la publication
réelle et l'exécution de la suite sur le staging final.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/contracts/src"))

from nexus_contracts import RetrievalScopeArtifactV3  # noqa: E402

SUITE_PATH = Path("services/rag-engine/tests/fixtures/public_successor_quality_40b.json")
EXPECTED_THRESHOLDS = {
    "positive_nonempty": 33,
    "expected_source_hits_min": 33,
    "expected_source_hits_per_collection_min": 3,
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


def _server_filter_digest(scope: RetrievalScopeArtifactV3) -> str:
    """Rejoue les prédicats de `ServerRetrievalScope.filter_digest` pour student V3."""
    evidence = scope.evidence_subject
    payload = {
        "tenant": evidence.tenant,
        "niveau": evidence.niveau.value,
        "voie": evidence.voie.value,
        "matiere": evidence.matiere,
        "statut_enseignement": evidence.statut_enseignement.value,
        "candidat": evidence.candidat.value,
        "audiences": tuple(evidence.audiences),
        "rights": tuple(right.value for right in evidence.rights),
        "visibilities": (evidence.visibility,),
        "school_year": evidence.school_year,
        "collection": evidence.collection,
        "programme_version": evidence.programme_version,
        "scope_id": scope.scope_id,
        "scope_digest": scope.sha256_digest(),
        "source_sha256": scope.source_sha256,
        "review_status": "reviewed",
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


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
        policy_path = root / suite["scope_policy_path"]
        _same_digest(policy_path, suite["scope_policy_sha256"])
        policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        if (policy["release_id"] != manifest["release_id"]
            or policy["release_manifest_sha256"] != suite["release_manifest_sha256"]):
            raise QualitySuiteError("politique de scope liée à une autre release")
        policies = {row["collection"]: row for row in policy["collections"]}
        if set(policies) != set(scopes):
            raise QualitySuiteError("politique de scope incomplète")
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
            entry = policies[name]
            subject_sha = next(ref["sha256"] for ref in manifest["subjects"] if ref["collection"] == name)
            if (entry["subject_manifest_sha256"] != subject_sha
                or entry["policy_visibility"] != "public"
                or entry["evidence_visibility"] != "public"
                or entry["rights"] != ["public_allowed"]):
                raise QualitySuiteError(f"politique publique divergente : {name}")
            scope = RetrievalScopeArtifactV3.model_validate({
                "artifact_version": "3", "scope_id": scopes[name],
                "status": "eligible_for_promotion", "source_sha256": subject_sha,
                "target_policy": {
                    key: entry[key] for key in (
                        "tenant", "niveau", "voie", "matiere", "statut_enseignement"
                    )
                } | {
                    "audiences": [entry["target_audience"]],
                    "candidates": entry["target_candidates"], "roles": ["student"],
                },
                "evidence_subject": {
                    key: entry[key] for key in (
                        "collection", "tenant", "niveau", "voie", "matiere",
                        "statut_enseignement", "candidat", "audiences", "rights",
                        "programme_version",
                    )
                } | {
                    "visibility": entry["policy_visibility"],
                    "school_year": policy["school_year"],
                },
            })
            if (spec["scope_id"] != scopes[name] or spec["student_expected_http"] != 200
                or spec["signed_scope_sha256"] != scope.sha256_digest()
                or spec["server_filter_sha256"] != _server_filter_digest(scope)
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
                expected_chunks = [chunk for chunk in index[name][content]["chunks"]
                                   if chunk["chunk_id"] == row["expected_chunk_id"]]
                if (len(expected_pages) != 1 or len(expected_chunks) != 1
                    or expected_chunks[0]["page_start"] != expected_pages[0]
                    or expected_chunks[0]["chunk_sha256"] != row["expected_chunk_sha256"]):
                    raise QualitySuiteError(f"chunk probant divergent : {name}")
                anchor = row["expected_text_anchor"]
                if (not isinstance(anchor, str) or len(anchor.split()) < 12
                    or len(anchor) < 75 or len(anchor) > 350
                    or hashlib.sha256(anchor.encode()).hexdigest() != row["expected_anchor_sha256"]):
                    raise QualitySuiteError(f"ancre pédagogique absente ou divergente : {name}")
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


def verify_text_anchors(suite: dict[str, Any], derivative_dir: Path) -> int:
    """Relit les octets privés exacts et vérifie l'ancre dans le corps de sa page."""
    checked = 0
    for name, spec in suite["collections"].items():
        for row in spec["positive"]:
            content = row["expected_content_sha256"]
            path = derivative_dir / f"{content}.txt"
            _same_digest(path, content)
            raw = path.read_text(encoding="utf-8")
            page = row["expected_pages_any"][0]
            anchor = row["expected_text_anchor"]
            bodies: list[str] = []
            marker = re.compile(r"\[PAGE (\d+) BLOCK \d+\]\n")
            matches = list(marker.finditer(raw))
            for position, match in enumerate(matches):
                if int(match.group(1)) != page:
                    continue
                end = matches[position + 1].start() if position + 1 < len(matches) else len(raw)
                lines = raw[match.end():end].splitlines()
                if len(lines) > 1 and lines[0].startswith("{"):
                    bodies.append(" ".join(" ".join(lines[1:]).split()))
            if not any(anchor in body for body in bodies):
                raise QualitySuiteError(f"{name}/{row['id']} : ancre absente du corps de la page {page}")
            checked += 1
    return checked


def verify_anchor_chunks(
    root: Path, suite: dict[str, Any], index: dict[str, dict[str, Any]],
    derivative_dir: Path, tokenizer_snapshot: Path,
) -> int:
    """Rejoue le chunker scellé et lie chaque ancre à un seul chunk exact."""
    script_dir = root / "services/rag-pedago/scripts"
    sys.path.insert(0, str(script_dir))
    try:
        from build_student_public_successor import PinnedE5TokenCounter  # type: ignore[import-not-found]
        from nexus_release_chain.publication_chunking import chunk_verified_derivative
    except ImportError as exc:
        raise QualitySuiteError("dépendances du chunker de publication absentes") from exc
    counter = PinnedE5TokenCounter(tokenizer_snapshot)
    verified = 0
    for name, spec in suite["collections"].items():
        for row in spec["positive"]:
            sha = row["expected_content_sha256"]
            artifact = index[name][sha]
            content = (derivative_dir / f"{sha}.txt").read_bytes()
            if hashlib.sha256(content).hexdigest() != sha:
                raise QualitySuiteError(f"dérivé divergent : {name}/{row['id']}")
            receipt_sha = artifact["derivative_receipt_sha256"]
            receipt_path = (root / "docs/reports/go_live/student_rights_evidence/derivative_receipts"
                            / receipt_sha[:2] / f"{receipt_sha}.json")
            _same_digest(receipt_path, receipt_sha)
            receipt = _json(receipt_path)
            chunks = chunk_verified_derivative(
                content=content, receipt=receipt, token_counter=counter, target_tokens=384,
            )
            public_chunks = artifact["chunks"]
            if len(chunks) != len(public_chunks):
                raise QualitySuiteError(f"population de chunks divergente : {name}/{row['id']}")
            matching: list[str] = []
            anchor = " ".join(row["expected_text_anchor"].split())
            for position, (chunk, public) in enumerate(zip(chunks, public_chunks, strict=True)):
                chunk_sha = hashlib.sha256(chunk.text.encode()).hexdigest()
                chunk_id = hashlib.sha256(f"{sha}:{position}:{chunk_sha}".encode()).hexdigest()
                if (chunk_id != public["chunk_id"] or chunk_sha != public["chunk_sha256"]
                    or chunk.page_start != public["page_start"]
                    or chunk.page_end != public["page_end"]):
                    raise QualitySuiteError(f"chunker ou manifeste divergent : {name}/{row['id']}")
                if anchor in " ".join(chunk.text.split()):
                    matching.append(chunk_id)
            if matching != [row["expected_chunk_id"]]:
                raise QualitySuiteError(f"ancre sans chunk unique : {name}/{row['id']}")
            verified += 1
    return verified


def check_positive(
    case: dict[str, Any], response: dict[str, Any], index: dict[str, dict[str, Any]],
    *, server_filter_sha256: str, chunk_text_by_id: Mapping[str, str],
) -> bool:
    """Contrôle tous les résultats servis ; retourne le hit source/page attendu."""
    try:
        collection = case["collection"]
        filters = response["filters_applied"]
        if (filters["collection"] != collection
            or filters["scope_digest"] != server_filter_sha256):
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
            score = result["score"]
            if (result["title"] != artifact["citation"]["source_label"]
                or not isinstance(result["excerpt"], str)
                or not result["excerpt"].strip()
                or isinstance(score, bool) or not isinstance(score, (int, float))
                or not math.isfinite(score) or score < 0):
                raise QualitySuiteError(f"{collection} : passage, titre ou score invalide")
            chunks = {row["chunk_id"]: row for row in artifact["chunks"]}
            chunk = chunks.get(result["chunk_id"])
            if chunk is None or chunk["page_start"] is None or chunk["page_end"] is None:
                raise QualitySuiteError(f"{collection} : chunk/page hors manifeste")
            chunk_text = chunk_text_by_id.get(result["chunk_id"])
            if (not isinstance(chunk_text, str)
                or hashlib.sha256(chunk_text.encode()).hexdigest() != chunk["chunk_sha256"]
                or result["excerpt"] not in chunk_text):
                raise QualitySuiteError(f"{collection} : preview non lié au chunk servi")
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
                and result["chunk_id"] == case["expected_chunk_id"]
                and citation["page"] in case["expected_pages_any"]):
                if " ".join(case["expected_text_anchor"].split()) not in " ".join(chunk_text.split()):
                    raise QualitySuiteError(f"{collection} : ancre absente du chunk servi")
                expected_hit = True
        return expected_hit
    except (KeyError, TypeError, ValueError) as exc:
        raise QualitySuiteError(f"réponse incomplète : {type(exc).__name__}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--derivative-dir", type=Path,
                        help="Répertoire privé des dérivés exacts, requis pour prouver les ancres")
    parser.add_argument("--tokenizer-snapshot", type=Path,
                        help="Snapshot local du tokenizer E5 piné pour rejouer les chunks privés")
    args = parser.parse_args()
    try:
        suite = _json(args.repository_root / SUITE_PATH)
        validate_suite(args.repository_root, suite)
        if args.derivative_dir is not None:
            if args.tokenizer_snapshot is None:
                raise QualitySuiteError("--tokenizer-snapshot requis avec --derivative-dir")
            count = verify_text_anchors(suite, args.derivative_dir)
            if count != 33:
                raise QualitySuiteError(f"ancrage incomplet : {count}/33")
            index = validate_suite(args.repository_root, suite)
            if verify_anchor_chunks(args.repository_root, suite, index,
                                    args.derivative_dir, args.tokenizer_snapshot) != 33:
                raise QualitySuiteError("liaison aux chunks incomplète")
    except QualitySuiteError as exc:
        print(f"PUBLIC_SUCCESSOR_QUALITY_SUITE=FAIL reason={exc}")
        return 1
    print("PUBLIC_SUCCESSOR_QUALITY_SUITE=PASS collections=11 positive_cases=33 "
          f"anchors_and_chunks_verified={'33' if args.derivative_dir is not None else 'not_run'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
