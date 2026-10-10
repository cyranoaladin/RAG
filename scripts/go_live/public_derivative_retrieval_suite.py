#!/usr/bin/env python3
"""Validate the public text-derivative acceptance oracle before live measurement.

The prepared suite is a question/source plan, not a quality verdict. It cannot
be bound to the V4/V5 PDF rehearsal or to the unpromotable #312 candidate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SUITE = Path(
    "services/rag-engine/tests/fixtures/public_derivative_acceptance_prepared_20261010.json"
)
CANDIDATE = Path(
    "docs/reports/go_live/student_rights_evidence/public_derivative_candidate_manifest_20261010.json"
)
EXPECTED_POPULATION = {
    "collections": 11,
    "artifacts": 253,
    "placements": 377,
    "segments": 2504,
}
THRESHOLDS = {
    "student_positive_nonempty": 33,
    "student_expected_source_hits_min": 26,
    "expected_source_hits_per_collection_min": 2,
    "teacher_refusals": 11,
    "zero_result_pass": 11,
    "boundary_scope_pass": 11,
    "scope_mismatch_refusals": 11,
    "out_of_scope_results": 0,
    "missing_citations": 0,
    "dense_misses": 0,
    "dense_tie_overflow_evidence_per_collection": 11,
}
CITATION_KEYS = {
    "source_uri",
    "source_label",
    "source_updated_at",
    "licensor",
    "licence_id",
    "derivative_notice",
}
FINAL_KEYS = (
    "final_release_manifest_path",
    "final_release_manifest_sha256",
    "final_scope_registry_path",
    "final_scope_registry_sha256",
    "final_checkout_sha",
)


class SuiteFailure(ValueError):
    """The acceptance oracle has missing, stale or contradictory evidence."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SuiteFailure("JSON object required")
    return value


def _digest(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def validate_draft_suite(root: Path, suite: dict[str, Any]) -> None:
    """Check all planned cases against the exact #312 derivative identities."""
    if (
        suite.get("schema_version") != 1
        or suite.get("status") not in {"PREPARED_UNBOUND", "BOUND"}
        or suite.get("candidate_manifest_path") != str(CANDIDATE)
        or not _digest(suite.get("candidate_manifest_sha256"))
        or suite.get("expected_candidate_population") != EXPECTED_POPULATION
        or suite.get("thresholds") != THRESHOLDS
    ):
        raise SuiteFailure("candidate binding or fixed thresholds differ")
    if suite["status"] == "PREPARED_UNBOUND" and any(
        suite.get(key) is not None for key in FINAL_KEYS
    ):
        raise SuiteFailure("unbound suite claims final binding")
    candidate_path = root / CANDIDATE
    if _sha(candidate_path) != suite["candidate_manifest_sha256"]:
        raise SuiteFailure("candidate manifest SHA differs")
    candidate = _json(candidate_path)
    counts = candidate.get("counts", {})
    if (
        candidate.get("status") != "PRE_REVIEW_NOT_PROMOTABLE"
        or counts.get("source_pdfs") != 315
        or counts.get("public_collections") != 11
        or counts.get("public_derivative_artifacts") != 253
        or counts.get("public_placements") != 377
        or counts.get("public_derivative_segments") != 2504
        or counts.get("original_pdf_public_count") != 0
    ):
        raise SuiteFailure("#312 candidate identity or population differs")
    entries = candidate.get("entries")
    if not isinstance(entries, list) or len(entries) != 253:
        raise SuiteFailure("candidate derivative population differs")
    by_collection: dict[str, dict[str, dict[str, Any]]] = {}
    unique: set[str] = set()
    for entry in entries:
        derivative = entry.get("derivative_content_sha256")
        source = entry.get("source_content_sha256")
        if (
            not _digest(derivative)
            or not _digest(source)
            or derivative == source
            or derivative in unique
            or entry.get("derivative_disposition") != "APPROVE_PUBLIC"
            or entry.get("source_disposition") != "REPLACE_WITH_NEW_CONTENT"
        ):
            raise SuiteFailure("candidate derivative/source identity invalid")
        unique.add(derivative)
        for collection in entry.get("collections", []):
            by_collection.setdefault(collection, {})[derivative] = entry
    cases = suite.get("collections")
    if (
        not isinstance(cases, dict)
        or set(cases) != set(by_collection)
        or len(cases) != 11
    ):
        raise SuiteFailure("exact eleven-collection coverage required")
    factual_queries: dict[str, str] = {}
    for collection, spec in cases.items():
        positive = spec.get("positive")
        if (
            not isinstance(positive, list)
            or len(positive) != 3
            or {case.get("id") for case in positive}
            != {"factual", "no_accent", "notion"}
            or spec.get("student_expected_http") != 200
            or spec.get("teacher_expected_http") != 403
            or spec.get("scope_mismatch_expected_http") != 403
            or spec.get("boundary_expected_scope") != "same_collection_only"
            or not isinstance(spec.get("boundary_query"), str)
            or not spec["boundary_query"].strip()
            or not isinstance(spec.get("zero_result_query"), str)
            or not spec["zero_result_query"].strip()
        ):
            raise SuiteFailure(f"cases or roles incomplete: {collection}")
        citation = spec.get("expected_citation")
        if (
            not isinstance(citation, dict)
            or set(citation) != CITATION_KEYS
            or any(
                not isinstance(value, str) or not value.strip()
                for value in citation.values()
            )
        ):
            raise SuiteFailure(f"expected citation incomplete: {collection}")
        source = spec.get("expected_source_pdf_sha256")
        if not _digest(source):
            raise SuiteFailure(f"source PDF identity absent: {collection}")
        for case in positive:
            query = case.get("query")
            derivative = case.get("expected_content_sha256")
            if (
                not isinstance(query, str)
                or not query.strip()
                or not _digest(derivative)
            ):
                raise SuiteFailure(
                    f"positive query or derivative invalid: {collection}"
                )
            entry = by_collection[collection].get(derivative)
            if entry is None or derivative == source:
                raise SuiteFailure(
                    f"expected derivative outside #312 candidate: {collection}"
                )
            entry_citation = entry.get("citation")
            if (
                entry["source_content_sha256"] != source
                or not isinstance(entry_citation, dict)
                or any(
                    entry_citation.get(key) != value for key, value in citation.items()
                )
            ):
                raise SuiteFailure(
                    f"derivative lineage or citation differs: {collection}"
                )
            if case["id"] == "no_accent" and any(
                unicodedata.combining(char)
                for char in unicodedata.normalize("NFD", query)
            ):
                raise SuiteFailure(f"no-accent query contains accents: {collection}")
        factual_queries[collection] = next(
            case["query"] for case in positive if case["id"] == "factual"
        )
    for collection, spec in cases.items():
        if spec["boundary_query"] not in {
            query for other, query in factual_queries.items() if other != collection
        }:
            raise SuiteFailure(
                f"boundary query is not a neighbouring scope: {collection}"
            )


def load_draft_suite(root: Path) -> dict[str, Any]:
    suite = _json(root / SUITE)
    validate_draft_suite(root, suite)
    return suite


def check_dense_tie_probe(
    suite: dict[str, Any],
    probe: dict[str, Any],
    expected_scope_chunks: dict[str, int],
    final_manifest_sha256: str,
    checkout_sha: str,
) -> int:
    """Reconcile all scoped chunks, including ANN ties, to a fresh final release.

    The caller must derive ``expected_scope_chunks`` from the final sealed
    manifest and verify the live DB fingerprint separately. An overflow is
    reported, never silently converted into a miss or a success.
    """
    provenance = probe.get("provenance")
    if not isinstance(provenance, dict):
        raise SuiteFailure("dense probe provenance missing")
    try:
        generated = datetime.strptime(
            provenance["generated_at_utc"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)
    except (KeyError, TypeError, ValueError):
        raise SuiteFailure("dense probe timestamp invalid") from None
    age = datetime.now(UTC) - generated
    if (
        age < -timedelta(minutes=5)
        or age > timedelta(hours=6)
        or provenance.get("final_release_manifest_sha256") != final_manifest_sha256
        or provenance.get("checkout_sha") != checkout_sha
        or not _digest(final_manifest_sha256)
        or not re.fullmatch(r"[0-9a-f]{40}", checkout_sha)
    ):
        raise SuiteFailure("dense probe final provenance differs or is stale")
    rows = probe.get("collections")
    if (
        not isinstance(rows, dict)
        or set(rows) != set(suite["collections"])
        or set(expected_scope_chunks) != set(rows)
        or len(rows)
        != suite["thresholds"]["dense_tie_overflow_evidence_per_collection"]
    ):
        raise SuiteFailure("dense tie overflow evidence incomplete")
    overflow_total = 0
    for collection, row in rows.items():
        values = [
            row.get(key)
            for key in (
                "chunks",
                "rappel_a_1",
                "rappel_a_5",
                "manques",
                "refus_egalite",
            )
        ]
        if (
            any(type(value) is not int or value < 0 for value in values)
            or values[0] != expected_scope_chunks[collection]
            or not 0 <= values[1] <= values[2] <= values[0]
            or values[3] != suite["thresholds"]["dense_misses"]
            or values[2] + values[3] + values[4] != values[0]
        ):
            raise SuiteFailure(f"dense tie overflow or miss inconsistent: {collection}")
        overflow_total += values[4]
    return overflow_total


def require_final_binding(root: Path, suite: dict[str, Any]) -> None:
    """Never turn draft structural checks into an authoritative release verdict.

    The current canonical release verifier accepts the #312 candidate only in
    candidate mode. It has no promoted public successor authority, and this
    module has no exact scope/review/checkout or live HTTP/DB proof. Declared
    hashes and status strings cannot substitute for those proofs.
    """
    if suite.get("status") != "BOUND" or any(not suite.get(key) for key in FINAL_KEYS):
        raise SuiteFailure("final successor binding missing")
    validate_draft_suite(root, suite)
    raise SuiteFailure("canonical release verifier required before final binding")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--assert-bound", action="store_true")
    args = parser.parse_args()
    try:
        suite = load_draft_suite(args.repository_root)
        if args.assert_bound:
            require_final_binding(args.repository_root, suite)
    except (SuiteFailure, OSError, KeyError, ValueError) as exc:
        print(f"PUBLIC_DERIVATIVE_ACCEPTANCE_SUITE=FAIL reason={type(exc).__name__}")
        return 1
    print(
        "PUBLIC_DERIVATIVE_ACCEPTANCE_SUITE=PREPARED QUALITY_PASS=false FINAL_BINDING=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
