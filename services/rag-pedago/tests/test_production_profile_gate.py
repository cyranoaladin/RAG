"""Contrat fail-closed du gate de profils production du 25 août 2026."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_PATH = Path(__file__).parent / "fixtures/production_profile_gate_expected.json"
PROPOSED_MATRIX_PATH = (
    REPO_ROOT / "docs/reports/proposed_production_profile_matrix_20260823.json"
)
PRIMARY_EVIDENCE_PATH = (
    REPO_ROOT / "docs/reports/production_profile_primary_evidence_20260825.json"
)
RESOLUTION_PATH = (
    REPO_ROOT / "docs/reports/production_profile_resolution_records_20260825.json"
)
FINAL_MATRIX_PATH = (
    REPO_ROOT / "docs/reports/final_production_profile_matrix_20260825.json"
)
PROFILE_ROOT = REPO_ROOT / "services/rag-engine/configs/ingestion_profiles"
STAGING_MULTILEVEL_ROOT = PROFILE_ROOT / "staging/multilevel"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_RESOLUTION_FIELDS = {
    "content_sha256",
    "canonical_path",
    "niveau",
    "niveau_evidence",
    "voie",
    "voie_evidence",
    "matiere",
    "matiere_evidence",
    "programme_version",
    "programme_version_evidence",
    "tenant",
    "collection",
    "candidat",
    "audience",
    "visibility",
    "school_year",
    "profile_id",
    "profile_version",
    "profile_fingerprint",
    "resolution_status",
    "reason_code",
}
FORBIDDEN_PROGRAMME_VERSIONS = {
    "latest",
    "current",
    "2026-2027",
    "generic",
    "unknown",
    "NEXUS_CURRENT",
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _expected() -> dict[str, Any]:
    value = _load(EXPECTED_PATH)
    assert isinstance(value, dict)
    return value


def _p11_p23_input_contents() -> set[str]:
    matrix = _load(PROPOSED_MATRIX_PATH)
    return {
        content
        for partition in matrix
        if re.fullmatch(r"P(?:1[1-9]|2[0-3])", partition["partition_id"])
        for content in partition["content_sha256"]
    }


def test_primary_evidence_is_content_bound_and_exhaustive() -> None:
    expected = _expected()
    raw = PRIMARY_EVIDENCE_PATH.read_bytes()
    evidence = json.loads(raw)
    records = evidence["records"]

    assert hashlib.sha256(raw).hexdigest() == expected["primary_evidence_sha256"]
    assert evidence["source_tree_commit"] == (
        "3f0317e91c9ac8eff8ff1089d100a25f7c875793"
    )
    assert evidence["source_tree_sha256"] == (
        "5bc5234ea395486810638d553c3c9bc2e7d57d75"
    )
    assert evidence["input_content_count"] == expected["input_content_count"]
    assert {record["content_sha256"] for record in records} == (
        _p11_p23_input_contents()
    )
    assert len(records) == len({record["content_sha256"] for record in records})

    for record in records:
        assert SHA256_RE.fullmatch(record["mirrored_pdf_sha256"])
        assert record["mirrored_pdf_sha256"] == record["content_sha256"]
        assert record["canonical_path"].endswith(".pdf")
        assert record["drive_file_id"]
        assert record["official_mirror_url"].endswith(
            f"/{record['drive_file_id']}/view"
        )
        assert record["page_count"] > 0
        assert record["section_locators"]
        assert record["bounded_decisive_facts"]
        assert all(
            0 < len(fact) <= 240 for fact in record["bounded_decisive_facts"]
        )


def test_primary_evidence_proves_only_the_exact_ten() -> None:
    expected = _expected()
    evidence = _load(PRIMARY_EVIDENCE_PATH)
    grounded = {
        record["content_sha256"]
        for record in evidence["records"]
        if record["evidence_disposition"] == "EXACT_SCOPE_GROUNDED"
    }

    assert grounded == set(expected["p11_p23_exactly_grounded"])
    assert evidence["exact_scope_grounded_count"] == 10
    assert evidence["review_required_count"] == 46
    for record in evidence["records"]:
        if record["content_sha256"] in grounded:
            assert record["official_source_url"]
            assert record["primary_identifiers"]


def test_resolution_records_are_exhaustive_and_fail_closed() -> None:
    expected = _expected()
    resolution = _load(RESOLUTION_PATH)
    records = resolution["records"]

    assert resolution["input_content_count"] == expected["input_content_count"]
    assert len(records) == 56
    assert {record["content_sha256"] for record in records} == (
        _p11_p23_input_contents()
    )
    assert all(REQUIRED_RESOLUTION_FIELDS <= record.keys() for record in records)

    grounded = [
        record for record in records if record["resolution_status"] == "EXACTLY_GROUNDED"
    ]
    residuals = [
        record for record in records if record["resolution_status"] != "EXACTLY_GROUNDED"
    ]
    assert len(grounded) == expected["exactly_grounded_count"]
    assert len(residuals) == expected["review_required_count"]
    assert {record["content_sha256"] for record in grounded} == set(
        expected["p11_p23_exactly_grounded"]
    )
    assert {record["resolution_status"] for record in residuals} <= {
        "AMBIGUOUS",
        "UNRESOLVED",
    }
    assert all(record["reason_code"] for record in residuals)

    for record in grounded:
        assert record["niveau"] not in {"unknown", "multi-niveaux", "non-classe"}
        assert record["voie"] != "unknown"
        assert record["tenant"] != "libre_lycee_gt"
        assert record["matiere"] not in {"unknown", "arts"}
        assert record["programme_version"] not in FORBIDDEN_PROGRAMME_VERSIONS
        assert record["profile_id"] == record["collection"]
        assert SHA256_RE.fullmatch(record["profile_fingerprint"])

    for record in residuals:
        assert record["tenant"] is None
        assert record["collection"] is None
        assert record["profile_id"] is None
        assert record["profile_version"] is None
        assert record["profile_fingerprint"] is None


def test_new_profile_identities_cover_exactly_the_ten_grounded_contents() -> None:
    expected = _expected()
    resolution = _load(RESOLUTION_PATH)
    grounded = [
        record
        for record in resolution["records"]
        if record["resolution_status"] == "EXACTLY_GROUNDED"
    ]
    actual: dict[tuple[str, str], set[str]] = {}
    for record in grounded:
        key = (record["profile_id"], record["profile_version"])
        actual.setdefault(key, set()).add(record["content_sha256"])

    wanted = {
        (profile["profile_id"], profile["profile_version"]): set(
            profile["content_sha256"]
        )
        for profile in expected["new_profiles"]
    }
    assert actual == wanted


def test_final_matrix_contains_only_grounded_p11_p23_rows() -> None:
    expected = _expected()
    rows = _load(FINAL_MATRIX_PATH)
    assert isinstance(rows, list)
    p11_p23_rows = [
        row
        for row in rows
        if re.match(r"P(?:1[1-9]|2[0-3])(?:-|$)", row["partition_id"])
    ]

    assert {content for row in p11_p23_rows for content in row["content_sha256"]} == set(
        expected["p11_p23_exactly_grounded"]
    )
    assert all(row["profile_decision_required"] is False for row in p11_p23_rows)
    assert all(
        dimension["grounded"] is True
        for row in p11_p23_rows
        for dimension in row["dimensions"].values()
    )
    assert all(
        "/staging/" not in source
        for row in rows
        for source in row["evidence_sources"]
    )
    assert all(
        "/staging/" not in dimension["source_of_truth"]
        for row in rows
        for dimension in row["dimensions"].values()
    )


def test_p01_p10_profiles_are_promoted_with_identical_bytes() -> None:
    proposed = _load(PROPOSED_MATRIX_PATH)
    sources = {
        dimension["source_of_truth"]
        for row in proposed
        if re.fullmatch(r"P(?:0[1-9]|10)", row["partition_id"])
        for dimension in row["dimensions"].values()
    }
    staging_paths = {
        REPO_ROOT / source
        for source in sources
        if "/staging/multilevel/" in source
    }

    assert len(staging_paths) == 10
    for staging_path in staging_paths:
        production_path = PROFILE_ROOT / staging_path.name
        assert production_path.is_file(), production_path
        assert production_path.read_bytes() == staging_path.read_bytes()
