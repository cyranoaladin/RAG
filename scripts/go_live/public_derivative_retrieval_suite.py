#!/usr/bin/env python3
"""Validate the public text-derivative acceptance oracle before live measurement.

The prepared suite is a question/source plan bound to the immutable #323 V2
preparation package, not a live quality verdict or a promoted release.
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

from nexus_contracts import RetrievalResponse

ROOT = Path(__file__).resolve().parents[2]
SUITE = Path(
    "services/rag-engine/tests/fixtures/public_derivative_acceptance_prepared_20261010.json"
)
SUITE_SHA256 = "3d876dde1a14afd316131ad6de3fef22f3142d6f9b84061666f02ba8b8bd23df"
CANDIDATE = Path(
    "docs/reports/go_live/student_rights_evidence/public_derivative_candidate_manifest_20261010.json"
)
PREPARATION_ROOT = Path(
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_student_public_successor_v1/release-fcc84331e7700042"
)
PREPARATION_INDEX = PREPARATION_ROOT / "preparation-index.json"
PREPARATION_MANIFEST = PREPARATION_ROOT / "profile_gate/production-profile-gate.release.json"
PREPARATION_INDEX_SHA256 = (
    "bd1f714594ca17dbbe7d3cfdf255c8c270003c63bd4d267971a17b2afdb08ca4"
)
PREPARATION_MANIFEST_SHA256 = (
    "b79246ff356b919aeb3dcb7f640a1a554e338899128a7c5acdcfaa9b7bcb1c78"
)
PREPARATION_RELEASE_ID = "student-public-successor-20261010-fcc84331e7700042"
PREPARATION_COUNTS = {
    "subjects": 11,
    "unique_artifacts": 253,
    "placements": 377,
    "unique_chunks": 3975,
}
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


def _validate_preparation_v2(
    root: Path, suite: dict[str, Any], cases: dict[str, Any]
) -> None:
    """Bind every prepared oracle to the immutable, unpromoted #323 package."""
    if (
        suite.get("preparation_index_path") != str(PREPARATION_INDEX)
        or suite.get("preparation_index_sha256") != PREPARATION_INDEX_SHA256
        or suite.get("preparation_manifest_path") != str(PREPARATION_MANIFEST)
        or suite.get("preparation_manifest_sha256") != PREPARATION_MANIFEST_SHA256
        or suite.get("expected_preparation_population") != PREPARATION_COUNTS
        or _sha(root / PREPARATION_INDEX) != PREPARATION_INDEX_SHA256
        or _sha(root / PREPARATION_MANIFEST) != PREPARATION_MANIFEST_SHA256
    ):
        raise SuiteFailure("#323 preparation identity or population differs")
    index = _json(root / PREPARATION_INDEX)
    manifest = _json(root / PREPARATION_MANIFEST)
    if (
        index.get("kind") != "NEXUS_STUDENT_PUBLIC_SUCCESSOR_PREPARATION_V2"
        or index.get("status") != "PREPARATION_ONLY_NOT_ACTIVABLE"
        or index.get("release_id") != PREPARATION_RELEASE_ID
        or index.get("release_manifest_sha256") != PREPARATION_MANIFEST_SHA256
        or index.get("expected_counts") != PREPARATION_COUNTS
        or index.get("complete_profile_count") != 11
        or manifest.get("release_id") != PREPARATION_RELEASE_ID
        or manifest.get("expected_counts") != PREPARATION_COUNTS
        or manifest.get("release_mode") != "candidate"
        or manifest.get("promotion_status") != "NOT_PROMOTABLE"
        or manifest.get("activation_status") != "NO_PRODUCTION_ACTIVATION"
        or manifest.get("review_status") != "PRE_REVIEW"
    ):
        raise SuiteFailure("#323 package is not the sealed preparation-only successor")
    profiles = index.get("complete_profiles")
    if not isinstance(profiles, list) or {p.get("collection") for p in profiles} != set(cases):
        raise SuiteFailure("#323 complete profile coverage differs")
    for profile in profiles:
        if _sha(root / PREPARATION_ROOT / profile["path"]) != profile["sha256"]:
            raise SuiteFailure("#323 complete profile SHA differs")
    scopes = index.get("proposed_scopes")
    if (
        not isinstance(scopes, list)
        or {s.get("collection") for s in scopes} != set(cases)
        or any(s.get("status") != "NOT_ISSUED" for s in scopes)
    ):
        raise SuiteFailure("#323 scopes are not the unissued proposals")
    manifest_dir = root / PREPARATION_MANIFEST.parent
    registry_ref = manifest.get("artifact_registry")
    if not isinstance(registry_ref, dict):
        raise SuiteFailure("#323 artifact registry reference absent")
    registry_path = manifest_dir / registry_ref["path"]
    if _sha(registry_path) != registry_ref.get("sha256"):
        raise SuiteFailure("#323 artifact registry SHA differs")
    registry = _json(registry_path)
    artifacts = registry.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 253:
        raise SuiteFailure("#323 artifact count differs")
    by_sha = {a.get("content_sha256"): a for a in artifacts}
    if (
        len(by_sha) != 253
        or registry.get("expected_counts") != {
            "unique_artifacts": 253, "unique_chunks": 3975
        }
        or sum(len(a.get("chunks", [])) for a in artifacts) != 3975
    ):
        raise SuiteFailure("#323 artifact identities or chunks differ")
    refs = manifest.get("subjects")
    if not isinstance(refs, list) or {r.get("collection") for r in refs} != set(cases):
        raise SuiteFailure("#323 subject coverage differs")
    placements_count = 0
    for ref in refs:
        collection = ref["collection"]
        subject_path = manifest_dir / ref["path"]
        if _sha(subject_path) != ref.get("sha256"):
            raise SuiteFailure(f"#323 subject SHA differs: {collection}")
        subject = _json(subject_path)
        placements = subject.get("placements")
        if subject.get("collection") != collection or not isinstance(placements, list):
            raise SuiteFailure(f"#323 subject placements absent: {collection}")
        placed = {p.get("artifact_id") for p in placements}
        if len(placed) != len(placements) or not placed <= by_sha.keys():
            raise SuiteFailure(f"#323 subject placement identities differ: {collection}")
        placements_count += len(placements)
        spec = cases[collection]
        for case in spec["positive"]:
            sha = case["expected_content_sha256"]
            artifact = by_sha.get(sha)
            if (
                sha not in placed
                or not isinstance(artifact, dict)
                or artifact.get("source_pdf_sha256") != spec["expected_source_pdf_sha256"]
                or artifact.get("media_type") != "text/plain; charset=utf-8"
                or not artifact.get("chunks")
                or any(
                    artifact.get("citation", {}).get(key) != value
                    for key, value in spec["expected_citation"].items()
                )
            ):
                raise SuiteFailure(f"oracle differs from #323 V2 placement: {collection}")
    if placements_count != 377:
        raise SuiteFailure("#323 placement count differs")


def validate_draft_suite(root: Path, suite: dict[str, Any]) -> None:
    """Check all planned cases against #312 identities and the #323 V2 package."""
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
    _validate_preparation_v2(root, suite, cases)


def load_draft_suite(root: Path) -> dict[str, Any]:
    if _sha(root / SUITE) != SUITE_SHA256:
        raise SuiteFailure("prepared fixture SHA differs")
    suite = _json(root / SUITE)
    validate_draft_suite(root, suite)
    return suite


def check_public_positive(
    case: dict[str, str], spec: dict[str, Any], response: RetrievalResponse,
    verified_index: dict[str, dict[str, dict[str, Any]]],
) -> tuple[bool, list[dict[str, Any]]]:
    """Check every HTTP hit against an independently verified final index.

    This pure check does not establish the provenance of ``verified_index``;
    ``require_final_binding`` must still refuse live qualification until the
    external release authority has verified that index and the target.
    """
    collection = case["collection"]
    expected = case["expected_content_sha256"]
    if not response.results:
        raise SuiteFailure(f"HTTP empty positive result: {collection}")
    selected = verified_index.get(collection, {})
    if expected not in selected:
        raise SuiteFailure(f"HTTP expected derivative outside verified index: {collection}")
    expected_artifact = selected[expected]
    oracle_citation = spec.get("expected_citation")
    index_citation = expected_artifact.get("citation")
    if (
        not isinstance(oracle_citation, dict)
        or not isinstance(index_citation, dict)
        or any(
            index_citation.get(key) != oracle_citation.get(key)
            for key in CITATION_KEYS
        )
        or expected_artifact.get("source_pdf_sha256")
        != spec.get("expected_source_pdf_sha256")
    ):
        raise SuiteFailure(f"HTTP prepared oracle differs from verified index: {collection}")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in response.results:
        metadata = result.metadata
        content = metadata.get("content_sha256")
        artifact = selected.get(str(content))
        if (
            metadata.get("collection") != collection
            or artifact is None
            or not _digest(content)
            or artifact.get("content_sha256") != content
            or not _digest(artifact.get("source_pdf_sha256"))
            or artifact.get("source_pdf_sha256") == content
            or artifact.get("media_type") != "text/plain; charset=utf-8"
            or result.doc_id != content
            or metadata.get("artifact_id") != content
            or metadata.get("placement_id") not in artifact.get("placements", ())
            or metadata.get("review_status") != "reviewed"
        ):
            raise SuiteFailure(f"HTTP derivative identity or scope differs: {collection}")
        locator = artifact.get("chunks", {}).get(result.chunk_id)
        if (
            not isinstance(locator, dict)
            or type(locator.get("page_start")) is not int
            or type(locator.get("page_end")) is not int
            or not 1 <= locator["page_start"] <= locator["page_end"]
        ):
            raise SuiteFailure(f"HTTP derivative chunk/page differs: {collection}")
        citation = result.citation
        expected_citation = artifact.get("citation")
        if (
            citation is None
            or not isinstance(expected_citation, dict)
            or any(
                not isinstance(expected_citation.get(key), str)
                or not expected_citation[key].strip()
                or getattr(citation, key) != expected_citation[key]
                for key in CITATION_KEYS
            )
            or citation.page != locator["page_start"]
            or citation.rights != "public_allowed"
            or result.title != citation.source_label
        ):
            raise SuiteFailure(f"HTTP derivative citation differs: {collection}")
        records.append({
            "collection": collection,
            "content_sha256": content,
            "chunk_id": result.chunk_id,
            "placement_id": metadata["placement_id"],
            "page_start": locator["page_start"],
            "page_end": locator["page_end"],
            "rights": citation.rights,
            **{key: getattr(citation, key) for key in CITATION_KEYS},
        })
        seen.add(content)
    return expected in seen, records


def reconcile_public_db_rows(
    http_records: list[dict[str, Any]], db_rows: list[dict[str, Any]],
) -> int:
    """Compare HTTP projections with read-only DB rows; this does no I/O."""
    if not http_records or len(db_rows) != len(http_records):
        raise SuiteFailure("DB derivative result population differs")
    by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for row in db_rows:
        pair = (row.get("chunk_id"), row.get("placement_id"))
        if pair in by_pair:
            raise SuiteFailure("DB duplicate chunk/placement pair")
        by_pair[pair] = row
    for result in http_records:
        pair = (result["chunk_id"], result["placement_id"])
        row = by_pair.pop(pair, None)
        if (
            row is None
            or any(row.get(key) != value for key, value in result.items())
            or row.get("placement_status") != "active"
            or row.get("review_status") != "reviewed"
            or row.get("currentness") not in {"current", "official_snapshot"}
            or row.get("visibility") != "public"
            or row.get("is_text_derivative") is not True
        ):
            raise SuiteFailure("DB derivative identity, scope or attribution differs")
    if by_pair:
        raise SuiteFailure("DB unexpected derivative rows")
    return len(http_records)


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

    The #323 package remains preparation-only. It has no promoted public
    successor authority, and this
    module has no exact scope/review/checkout or live HTTP/DB proof. Declared
    hashes and status strings cannot substitute for those proofs.
    """
    if suite.get("status") != "BOUND" or any(not suite.get(key) for key in FINAL_KEYS):
        raise SuiteFailure("final successor binding missing")
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
