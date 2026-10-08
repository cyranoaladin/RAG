#!/usr/bin/env python3
"""Recette HTTP lecture seule des onze collections V4/V5, liée aux manifests.

Le jeu de questions et ses seuils sont scellés dans le commit AVANT la mesure.
À exécuter dans un environnement opérateur de confiance : le secret interne
sert uniquement à émettre des identités courtes et n'entre jamais au rapport.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from functools import partial
from pathlib import Path
from typing import Any

from nexus_contracts import RetrievalResponse

ROOT = Path(__file__).resolve().parents[2]
SUITE = Path("services/rag-engine/tests/fixtures/final_v4_v5_acceptance.json")
RELEASE_BASE = Path("services/rag-pedago/data/releases/prerentree_2026_2027")


class AcceptanceFailure(RuntimeError):
    """Une entrée ou preuve manque ou diverge : aucun succès par défaut."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise AcceptanceFailure(f"JSON invalide : {path.name}")
    return document


def load_suite(root: Path) -> tuple[dict[str, Any], dict[str, dict[str, dict[str, Any]]]]:
    """Charger questions et oracle physique depuis les deux manifests scellés."""
    suite = _read_json(root / SUITE)
    return suite, validate_suite(root, suite)


def validate_suite(
    root: Path, suite: dict[str, Any]
) -> dict[str, dict[str, dict[str, Any]]]:
    registry_path = root / suite["mixed_registry_path"]
    if _sha256(registry_path) != suite["mixed_registry_sha256"]:
        raise AcceptanceFailure("registre mixte SHA-256 divergent")
    registry = _read_json(registry_path)
    releases = registry.get("releases", [])
    if registry.get("registry_version") != "2" or len(releases) != 2:
        raise AcceptanceFailure("registre mixte inattendu")

    # Le résolveur canonique vérifie aussi les autorités des onze scopes.
    from staging_retrieval_probe import mixed_authorities  # noqa: PLC0415

    scopes, programmes, owners = mixed_authorities(
        root, registry_path, suite["mixed_registry_sha256"]
    )
    if set(suite["collections"]) != set(scopes) or len(scopes) != 11:
        raise AcceptanceFailure("la suite doit couvrir exactement 11 collections")
    thresholds = suite.get("thresholds", {})
    if thresholds != {
        "dense_misses": 0,
        "positive_nonempty": 33,
        "expected_source_hits_min": 26,
        "expected_source_hits_per_collection_min": 2,
        "zero_result_pass": 11,
        "student_refusals": 11,
        "scope_mismatch_refusals": 11,
        "out_of_scope_results": 0,
        "missing_citations": 0,
    }:
        raise AcceptanceFailure("seuils d'acceptation inattendus")

    index: dict[str, dict[str, dict[str, Any]]] = {}
    for release in releases:
        release_id = release["release_id"]
        manifest_path = root / RELEASE_BASE / release["manifest_path"]
        expected_sha = suite["release_manifest_sha256"].get(release_id)
        if expected_sha != release["expected_manifest_sha256"] or _sha256(manifest_path) != expected_sha:
            raise AcceptanceFailure(f"manifeste divergent : {release_id}")
        manifest = _read_json(manifest_path)
        artifact_path = manifest_path.parent / manifest["artifact_registry"]["path"]
        if _sha256(artifact_path) != manifest["artifact_registry"]["sha256"]:
            raise AcceptanceFailure(f"registre d'artefacts divergent : {release_id}")
        artifacts = {
            record["artifact_id"]: record
            for record in _read_json(artifact_path)["artifacts"]
        }
        for ref in manifest["subjects"]:
            collection = ref["collection"]
            if collection not in release["collections"]:
                continue  # HGGSP V4 historique conservé, mais non servi dans l'union.
            subject_path = manifest_path.parent / ref["path"]
            if _sha256(subject_path) != ref["sha256"]:
                raise AcceptanceFailure(f"manifeste sujet divergent : {collection}")
            subject = _read_json(subject_path)
            if (subject["collection"] != collection
                    or subject["release_id"] != f"{release_id}-{collection}"):
                raise AcceptanceFailure(f"propriétaire du sujet divergent : {collection}")
            selected: dict[str, dict[str, Any]] = {}
            for placement in subject["placements"]:
                if (placement["placement_status"] != "active"
                        or placement["currentness"] not in {"current", "official_snapshot"}
                        or placement["review_status"] != "reviewed"
                        or placement["visibility"] != "internal"):
                    raise AcceptanceFailure(f"placement non servable : {collection}")
                artifact = artifacts[placement["artifact_id"]]
                content = artifact["content_sha256"]
                entry = selected.setdefault(content, {
                    "content_sha256": content,
                    "source_url": artifact["source_url"],
                    "source_path": artifact["source_path"],
                    "title": artifact["title"],
                    "chunks": {c["chunk_id"]: c for c in artifact["chunks"]},
                    "placements": set(),
                })
                entry["placements"].add(placement["placement_id"])
            index[collection] = selected
    if set(index) != set(scopes):
        raise AcceptanceFailure("oracle physique incomplet")
    population = {
        "collections": len(index),
        "artifacts": len({sha for selected in index.values() for sha in selected}),
        "placements": sum(
            len(artifact["placements"])
            for selected in index.values() for artifact in selected.values()
        ),
        "chunks": len({
            chunk_id
            for selected in index.values()
            for artifact in selected.values()
            for chunk_id in artifact["chunks"]
        }),
    }
    if population != suite.get("expected_population"):
        raise AcceptanceFailure("population des manifests divergente")
    dense_visits = sum(
        len({chunk_id for artifact in selected.values() for chunk_id in artifact["chunks"]})
        for selected in index.values()
    )
    if dense_visits != suite.get("expected_dense_scope_chunk_visits"):
        raise AcceptanceFailure("population dense des scopes divergente")
    for collection, spec in suite["collections"].items():
        if (spec["scope_id"] != scopes[collection]
                or spec["release_id"] != owners[collection]
                or spec["programme_version"] != programmes[collection]):
            raise AcceptanceFailure(f"scope ou programme divergent : {collection}")
        positive = spec["positive"]
        if len(positive) != 3 or {c["id"] for c in positive} != {"factual", "no_accent", "notion"}:
            raise AcceptanceFailure(f"trois types de requêtes requis : {collection}")
        if not spec.get("zero_result_query") or spec["student_expected_http"] != 403 or spec["scope_mismatch_expected_http"] != 403:
            raise AcceptanceFailure(f"cas négatifs incomplets : {collection}")
        for case in positive:
            if case["collection"] != collection or not case["query"].strip():
                raise AcceptanceFailure(f"requête positive invalide : {collection}")
            if case["id"] == "no_accent" and any(
                unicodedata.combining(char)
                for char in unicodedata.normalize("NFD", case["query"])
            ):
                raise AcceptanceFailure(f"requête sans accents requise : {collection}")
            if case["expected_content_sha256"] not in index[collection]:
                raise AcceptanceFailure(f"source attendue hors manifeste : {collection}")
    return index


def check_positive(
    case: dict[str, str], response: RetrievalResponse,
    index: dict[str, dict[str, dict[str, Any]]],
) -> bool:
    """Contrôler chaque résultat, puis noter si la source opposable est trouvée."""
    collection = case["collection"]
    if not response.results:
        raise AcceptanceFailure(f"{collection} : aucun résultat")
    seen: set[str] = set()
    for result in response.results:
        metadata = result.metadata
        if metadata.get("collection") != collection:
            raise AcceptanceFailure(f"{collection} : résultat hors scope")
        content = metadata.get("content_sha256")
        artifact = index[collection].get(str(content))
        if artifact is None or metadata.get("artifact_id") != content or result.doc_id != content:
            raise AcceptanceFailure(f"{collection} : identité de contenu hors manifeste")
        if metadata.get("placement_id") not in artifact["placements"]:
            raise AcceptanceFailure(f"{collection} : placement hors manifeste")
        if metadata.get("review_status") != "reviewed":
            raise AcceptanceFailure(f"{collection} : résultat non revu")
        locator = artifact["chunks"].get(result.chunk_id)
        if locator is None or locator["page_start"] is None or locator["page_end"] is None:
            raise AcceptanceFailure(f"{collection} : chunk ou pages hors manifeste")
        citation = result.citation
        if (citation is None or not citation.source_label.strip()
                or result.title != citation.source_label
                or citation.source_uri != artifact["source_url"]
                or citation.page != locator["page_start"]
                or citation.rights != "officiel_public"):
            raise AcceptanceFailure(f"{collection} : citation manquante ou divergente")
        seen.add(str(content))
    return case["expected_content_sha256"] in seen


def check_zero_result(response: RetrievalResponse) -> None:
    if response.results:
        raise AcceptanceFailure("requête hors corpus : zéro résultat exigé")


def check_dense_probe(
    probe: dict[str, Any], suite: dict[str, Any],
    index: dict[str, dict[str, dict[str, Any]]],
    *, expected_checkout_sha: str | None = None,
) -> int:
    """Réconcilier la sonde exhaustive qui constate les refus ANN à la source."""
    provenance = probe.get("provenance")
    if not isinstance(provenance, dict):
        raise AcceptanceFailure("sonde dense : provenance absente")
    fingerprint = provenance.get("db_fingerprint")
    if (not isinstance(fingerprint, dict)
            or not re.fullmatch(r"[0-9a-f]{40}", str(provenance.get("checkout_sha", "")))
            or (expected_checkout_sha is not None
                and provenance["checkout_sha"] != expected_checkout_sha)
            or provenance.get("mixed_registry_sha256") != suite["mixed_registry_sha256"]
            or provenance.get("release_manifest_sha256") != suite["release_manifest_sha256"]
            or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", str(provenance.get("generated_at_utc", "")))
            or not isinstance(fingerprint.get("database"), str)
            or not isinstance(fingerprint.get("database_oid"), int)
            or {key: fingerprint.get(key) for key in ("chunks", "artifacts", "placements")}
            != {key: suite["expected_population"][key] for key in ("chunks", "artifacts", "placements")}
            or any(not fingerprint.get(key) for key in (
                "max_chunk_indexed_at", "max_artifact_created_at", "max_placement_created_at"
            ))):
        raise AcceptanceFailure("sonde dense : provenance divergente")
    collections = probe.get("collections", {})
    totals = probe.get("totaux", {})
    if (probe.get("release_id") != "mixed-v4-hggsp"
            or set(collections) != set(suite["collections"])
            or totals.get("chunks") != suite["expected_dense_scope_chunk_visits"]):
        raise AcceptanceFailure("sonde dense : population ou release divergente")
    for name, row in collections.items():
        chunks = row.get("chunks")
        first = row.get("rappel_a_1")
        found = row.get("rappel_a_5")
        missed = row.get("manques")
        overflow = row.get("refus_egalite")
        expected_chunks = len({
            chunk_id for artifact in index[name].values() for chunk_id in artifact["chunks"]
        })
        if (not all(isinstance(value, int) and not isinstance(value, bool)
                    for value in (chunks, first, found, missed, overflow))
                or min(chunks, first, found, missed, overflow) < 0
                or chunks != expected_chunks or first > found or found > chunks
                or missed != suite["thresholds"]["dense_misses"]
                or found + missed + overflow != chunks
                or row.get("scope_id") != suite["collections"][name]["scope_id"]
                or row.get("programme_version") != suite["collections"][name]["programme_version"]
                or row.get("student") != "refuse"):
            raise AcceptanceFailure(f"sonde dense : scope, population ou rappel incohérent : {name}")
    for key in ("chunks", "rappel_a_1", "rappel_a_5", "manques", "refus_egalite"):
        if totals.get(key) != sum(row.get(key, 0) for row in collections.values()):
            raise AcceptanceFailure(f"sonde dense : total {key} divergent")
    return totals["refus_egalite"]


def _http_code(call: Any) -> int:
    """Évaluer un refus HTTP sans afficher ni conserver les credentials."""
    from rag_query_external import RagQueryExternalClientError  # noqa: PLC0415

    try:
        call()
    except RagQueryExternalClientError as exc:
        message = str(exc)
        if message.startswith("API HTTP ") and message[9:].isdigit():
            return int(message[9:])
        raise AcceptanceFailure("erreur transport du cas négatif") from None
    return 200


def run_http(
    root: Path, suite: dict[str, Any], index: dict[str, dict[str, dict[str, Any]]],
    *, api_url: str,
) -> dict[str, Any]:
    """33 cas positifs et 33 refus/vides sur la vraie route `/search/v2`."""
    sys.path.insert(0, str(root / "scripts"))
    import rag_query
    from nexus_contracts import load_retrieval_scope_artifact
    from rag_query_external import (
        ExternalClientConfig,
        build_request,
        post_search,
    )

    source = dict(os.environ)
    source["RAG_API_URL"] = api_url
    operator = rag_query.load_client_config(source)
    api_key = source.get("RAG_API_KEY", "").strip() or source.get(
        "COCKPIT_STAGING_API_KEY", ""
    ).strip()
    if not api_key:
        raise AcceptanceFailure("RAG_API_KEY ou COCKPIT_STAGING_API_KEY requis")
    rows: list[dict[str, Any]] = []
    collections = sorted(suite["collections"])
    totals = {"positive_nonempty": 0, "expected_source_hits": 0,
              "zero_result_pass": 0, "student_refusals": 0,
              "scope_mismatch_refusals": 0, "out_of_scope_results": 0,
              "missing_citations": 0}
    for number, collection in enumerate(collections):
        spec = suite["collections"][collection]
        scope_id = spec["scope_id"]
        teacher_token, artifact = rag_query.issue_scope_identity(scope_id, config=operator)
        teacher = ExternalClientConfig(api_url=operator.api_url, bff_token=operator.bff_token,
                                       api_key=api_key, identity_token=teacher_token)
        for case in spec["positive"]:
            started = time.monotonic()
            row: dict[str, Any] = {"collection": collection, "case": case["id"],
                                   "expected_content_sha256": case["expected_content_sha256"]}
            try:
                response = post_search(build_request(case["query"], artifact), config=teacher)
                totals["positive_nonempty"] += bool(response.results)
                totals["out_of_scope_results"] += sum(
                    result.metadata.get("collection") != collection
                    or str(result.metadata.get("content_sha256")) not in index[collection]
                    for result in response.results
                )
                totals["missing_citations"] += sum(
                    result.citation is None or not result.citation.source_label.strip()
                    or not result.citation.source_uri or result.citation.page is None
                    for result in response.results
                )
                row["expected_source_hit"] = check_positive(case, response, index)
                row["result_count"] = len(response.results)
                row["results"] = [
                    {
                        "chunk_id": result.chunk_id,
                        "content_sha256": result.metadata["content_sha256"],
                        "placement_id": result.metadata["placement_id"],
                        "source_uri": result.citation.source_uri,
                        "source_label": result.citation.source_label,
                        "page_start": result.citation.page,
                        "page_end_manifest": index[collection][str(result.metadata["content_sha256"])]["chunks"][result.chunk_id]["page_end"],
                        "rights": result.citation.rights,
                    }
                    for result in response.results
                ]
                totals["expected_source_hits"] += bool(row["expected_source_hit"])
                row["verdict"] = "pass" if row["expected_source_hit"] else "source_miss"
            except Exception as exc:  # collecter toutes les lacunes, jamais un succès implicite
                row["verdict"] = "fail"
                row["reason"] = str(exc) if isinstance(exc, AcceptanceFailure) else type(exc).__name__
            row["latency_ms"] = round((time.monotonic() - started) * 1000)
            rows.append(row)
        try:
            response = post_search(build_request(spec["zero_result_query"], artifact), config=teacher)
            check_zero_result(response)
            totals["zero_result_pass"] += 1
            rows.append({"collection": collection, "case": "zero_result", "verdict": "pass"})
        except Exception as exc:
            rows.append({"collection": collection, "case": "zero_result", "verdict": "fail",
                         "reason": str(exc) if isinstance(exc, AcceptanceFailure) else type(exc).__name__})
        student_token, _ = rag_query.issue_scope_identity(scope_id, config=operator, role="student")
        student = ExternalClientConfig(api_url=operator.api_url, bff_token=operator.bff_token,
                                       api_key=api_key, identity_token=student_token)
        student_payload = build_request(spec["positive"][0]["query"], artifact)
        student_code = _http_code(partial(post_search, student_payload, config=student))
        totals["student_refusals"] += student_code == 403
        rows.append({"collection": collection, "case": "student", "http": student_code,
                     "verdict": "pass" if student_code == 403 else "fail"})
        other = suite["collections"][collections[(number + 1) % len(collections)]]
        other_artifact = load_retrieval_scope_artifact(other["scope_id"])
        mismatch_payload = build_request("Quels thèmes sont étudiés ?", other_artifact)
        mismatch_code = _http_code(partial(post_search, mismatch_payload, config=teacher))
        totals["scope_mismatch_refusals"] += mismatch_code == 403
        rows.append({"collection": collection, "case": "scope_mismatch", "http": mismatch_code,
                     "verdict": "pass" if mismatch_code == 403 else "fail"})
    per_collection = {
        name: sum(row.get("expected_source_hit") is True for row in rows if row["collection"] == name)
        for name in collections
    }
    thresholds = suite["thresholds"]
    passed = (
        totals["positive_nonempty"] == thresholds["positive_nonempty"]
        and totals["expected_source_hits"] >= thresholds["expected_source_hits_min"]
        and all(value >= thresholds["expected_source_hits_per_collection_min"] for value in per_collection.values())
        and totals["zero_result_pass"] == thresholds["zero_result_pass"]
        and totals["student_refusals"] == thresholds["student_refusals"]
        and totals["scope_mismatch_refusals"] == thresholds["scope_mismatch_refusals"]
        and totals["out_of_scope_results"] == thresholds["out_of_scope_results"]
        and totals["missing_citations"] == thresholds["missing_citations"]
        and all(row["verdict"] != "fail" for row in rows)
    )
    return {"schema_version": 1, "checkout_sha": _git_head(root),
            "http_path": "direct_api_v2",
            "page_end_evidence": "manifest_only_db_check_required",
            "suite_sha256": _sha256(root / SUITE),
            "mixed_registry_sha256": suite["mixed_registry_sha256"],
            "release_manifest_sha256": suite["release_manifest_sha256"],
            "target_api_url": operator.api_url, "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "thresholds": thresholds, "totals": totals,
            "expected_source_hits_per_collection": per_collection,
            "cases": rows, "verdict": "pass" if passed else "fail"}


def reconcile_db_rows(report: dict[str, Any], db_rows: list[tuple[Any, ...]]) -> int:
    """Rapprocher chaque résultat HTTP des lignes physiques de publication."""
    by_pair: dict[tuple[str, str], tuple[Any, ...]] = {}
    for db_row in db_rows:
        pair = (db_row[0], db_row[1])
        if pair in by_pair:
            raise AcceptanceFailure("DB : couple chunk/placement dupliqué")
        by_pair[pair] = db_row
    checked = 0
    for case in report["cases"]:
        for result in case.get("results", []):
            row = by_pair.get((result["chunk_id"], result["placement_id"]))
            if row is None or (
                row[2] != result["content_sha256"]
                or row[3] != result["page_start"]
                or row[4] != result["page_end_manifest"]
                or row[5] != case["collection"]
                or row[6] != "active"
                or row[7] != "reviewed"
                or row[8] not in {"current", "official_snapshot"}
                or row[9] != "internal"
                or row[10] != result["rights"]
                or row[11] != result["source_uri"]
                or row[12] != result["source_label"]
            ):
                raise AcceptanceFailure("DB : identité, visibilité ou citation divergente")
            result["page_start_db"] = row[3]
            result["page_end_db"] = row[4]
            checked += 1
    return checked


def verify_db_evidence(report: dict[str, Any], dsn: str) -> int:
    """Lecture bornée au rôle reader, transaction explicitement READ ONLY."""
    import psycopg  # noqa: PLC0415
    from staging_retrieval_probe import db_fingerprint  # noqa: PLC0415

    if not dsn:
        raise AcceptanceFailure("PG_RAG_DSN reader requis")
    results = [result for case in report["cases"] for result in case.get("results", [])]
    chunk_ids = sorted({result["chunk_id"] for result in results})
    placement_ids = sorted({result["placement_id"] for result in results})
    try:
        with psycopg.connect(dsn) as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            report["db_fingerprint"] = db_fingerprint(conn)
            rows = conn.execute(
                """SELECT chunk.chunk_id, placement.placement_id, artifact.content_sha256,
                          chunk.page_start, chunk.page_end, placement.collection,
                          placement.placement_status, placement.review_status,
                          placement.currentness, placement.visibility, artifact.rights,
                          placement.source_uri, artifact.source_label
                     FROM public.rag_chunks AS chunk
                     JOIN public.rag_artifacts AS artifact
                       ON artifact.artifact_id = chunk.artifact_id
                     JOIN public.rag_artifact_placements AS placement
                       ON placement.artifact_id = artifact.artifact_id
                    WHERE chunk.chunk_id = ANY(%s::text[])
                      AND placement.placement_id = ANY(%s::text[])""",
                (chunk_ids, placement_ids),
            ).fetchall()
            conn.rollback()
    except psycopg.Error:
        raise AcceptanceFailure("DB reader indisponible") from None
    return reconcile_db_rows(report, rows)


def _git_head(root: Path) -> str:
    import subprocess  # noqa: PLC0415

    expected = os.environ.get("NEXUS_ACCEPTANCE_CHECKOUT_SHA", "").strip()
    if expected and not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise AcceptanceFailure("SHA du checkout invalide")
    try:
        actual = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        if expected and os.environ.get("NEXUS_ACCEPTANCE_CHECKOUT_CLEAN") == "true":
            return expected  # image runtime sans git ; SHA précontrôlé par l'hôte.
        raise AcceptanceFailure("SHA ou attestation de checkout propre indisponible") from None
    if expected and expected != actual:
        raise AcceptanceFailure("SHA du checkout divergent")
    status = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
        text=True, stderr=subprocess.DEVNULL,
    )
    if status:
        raise AcceptanceFailure("checkout non propre")
    return actual


def command_provenance(args: argparse.Namespace) -> dict[str, Any]:
    """Identifier le runner, sa commande sans secret et l'auteur du verdict."""
    return {
        "decision_author": "automated:final_retrieval_acceptance.py",
        "runner_sha256": _sha256(Path(__file__)),
        "command_argv": [
            sys.executable, str(Path(__file__).resolve()),
            "--repository-root", str(args.repository_root),
            "--api-url", args.api_url,
            "--dense-probe-report", str(args.dense_probe_report),
            "--output", str(args.output),
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--dense-probe-report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        suite, index = load_suite(args.repository_root)
        dense_report = _read_json(args.dense_probe_report)
        overflow_count = check_dense_probe(
            dense_report, suite, index,
            expected_checkout_sha=_git_head(args.repository_root),
        )
        report = run_http(args.repository_root, suite, index, api_url=args.api_url)
        if report["verdict"] == "pass":
            report["db_result_rows_verified"] = verify_db_evidence(
                report, os.environ.get("PG_RAG_DSN", "")
            )
            if report["db_fingerprint"] != dense_report["provenance"]["db_fingerprint"]:
                raise AcceptanceFailure("sonde dense : cible DB modifiée ou divergente")
            report["page_end_evidence"] = "live_db_manifest_match"
        report["dense_probe_sha256"] = _sha256(args.dense_probe_report)
        report["dense_tie_overflow_count"] = overflow_count
        report.update(command_provenance(args))
    except (AcceptanceFailure, ValueError, KeyError, OSError) as exc:
        print(f"FINAL_RETRIEVAL_ACCEPTANCE=FAIL reason={type(exc).__name__}", file=sys.stderr)
        return 1
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"FINAL_RETRIEVAL_ACCEPTANCE={report['verdict'].upper()} positive={report['totals']['positive_nonempty']}/33 source_hits={report['totals']['expected_source_hits']}/33 zero={report['totals']['zero_result_pass']}/11")
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
