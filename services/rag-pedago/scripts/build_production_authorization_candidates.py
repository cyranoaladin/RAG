#!/usr/bin/env python3
"""Construit les autorisations production depuis un tree Git figé."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from nexus_contracts import (
    ScopeAuthorizationArtifactV2,
    canonical_authorization_path,
    parse_release_scope_placement,
    parse_scope_authorization_artifact,
    scope_digest,
)
from nexus_contracts.profile_manifest import strict_yaml_mapping

SOURCE_COMMIT_SHA = "3566cafb44138d6a7f00296dc0654257f9bf0ad6"
SOURCE_TREE_SHA = "8c5081a52096d531f1bd027790e600eb83b05bd5"
AUTHORIZATION_COUNT = 18
FINAL_CONTENT_COUNT = 26
FINAL_SET_SHA256 = "fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0"
PROFILE_MANIFEST_FINGERPRINT = (
    "57d532ca0c80f0e70218e74902f1d47a4ca9f21d7e6bafa209f6f89426125b6c"
)
CORPUS_MANIFEST_SHA256 = (
    "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
)
RELEASE_SCOPE_PLACEMENT_SHA256 = (
    "b1a36aef251d05f0098bfe88d7eae45b36333452f1613741e15dc6a89de75315"
)
AGGREGATE_RELEASE_SHA256 = (
    "2aadfa96e6ce669abcaa6d336bdd44c680d4d3206d33e464a9eccc90f8a5944c"
)
AUTHORITY_BINDINGS_SHA256 = (
    "5db45988fdbb19be74850f85890647397d514243266f5bb6ad34008fee4b80e1"
)
PII_EVIDENCE_SHA256 = (
    "cec9baca680439afa0dd6b4aadbb0f805514424a853a10303e6216dd8ffa7e99"
)
CURRENTNESS_EVIDENCE_SHA256 = (
    "822677cb14987f1069ff849241e33d6f7c9fb66425a5d00c3e38d71b592b793c"
)
CURRENTNESS_AUDIT_SHA256 = (
    "4c6395e3ce4c9a61a0d3a8a3b7f94da75ba91b00419c3f0c042f2d2e7adcf520"
)
RIGHTS_EVIDENCE_SHA256 = (
    "e3c9a157f1f78171c0052750fa08b7726b99ea4dd348728f1b90db07f93ef1ff"
)

FINAL_SET_PATH = "docs/reports/final_production_eligible_set_20260825.txt"
PLACEMENT_PATH = "docs/reports/release_scope_placement_20260825.jsonl"
VERIFIED_PROFILES_PATH = "docs/reports/verified_production_profiles_20260825.json"
RELEASE_ROOT = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate"
)
AGGREGATE_PATH = f"{RELEASE_ROOT}/production-profile-gate.release.json"
AUTHORITY_BINDINGS_PATH = f"{RELEASE_ROOT}/authority_bindings.json"
PII_EVIDENCE_PATH = f"{RELEASE_ROOT}/pii_evidence.json"
CURRENTNESS_EVIDENCE_PATH = f"{RELEASE_ROOT}/currentness_evidence.json"
CURRENTNESS_AUDIT_PATH = f"{RELEASE_ROOT}/currentness_network_audit.json"
RIGHTS_EVIDENCE_PATH = "services/rag-pedago/configs/rights_evidence_registry.yml"
PII_EVIDENCE_REFERENCE = (
    f"sha256:{PII_EVIDENCE_SHA256} path:{PII_EVIDENCE_PATH}"
)
AUTHORIZATION_MATRIX_PATH = (
    "docs/reports/production_authorization_matrix_20260825.json"
)

VALID_FROM = datetime(2026, 8, 25, tzinfo=UTC)
VALID_UNTIL = datetime(2027, 8, 25, tzinfo=UTC)
ALLOWED_SOURCE_DOMAINS = frozenset(
    {"eduscol.education.gouv.fr", "www.education.gouv.fr"}
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_OID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class AuthorizationCandidateError(ValueError):
    """Une preuve ne permet pas de construire les autorisations exactes."""


@dataclass(frozen=True)
class AuthorizationCandidateProvenance:
    source_commit_sha: str
    source_tree_sha: str
    input_blob_sha256: Mapping[str, str]
    input_git_entries: Mapping[str, str]


@dataclass(frozen=True)
class ProducedAuthorizationCandidates:
    candidates: tuple[ScopeAuthorizationArtifactV2, ...]
    provenance: AuthorizationCandidateProvenance


@dataclass(frozen=True)
class _GitTreeEntry:
    mode: str
    object_type: str
    object_id: str
    path: str


def _fail(code: str, detail: str) -> AuthorizationCandidateError:
    return AuthorizationCandidateError(f"{code}: {detail}")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _content_set_digest(values: set[str]) -> str:
    return _sha256(("\n".join(sorted(values)) + "\n").encode("ascii"))


def _canonical_repo_path(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail("INVALID_REPO_PATH", repr(value))
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or "://" in value
        or path.as_posix() != value
    ):
        raise _fail("INVALID_REPO_PATH", value)
    return value


def _parse_tree_entry(raw: bytes, *, expected_path: str) -> _GitTreeEntry:
    if not raw.endswith(b"\0") or raw.count(b"\0") != 1:
        raise _fail("INVALID_GIT_TREE_ENTRY", expected_path)
    metadata, separator, path_raw = raw[:-1].partition(b"\t")
    if not separator or path_raw != expected_path.encode("utf-8"):
        raise _fail("INVALID_GIT_TREE_ENTRY", expected_path)
    fields = metadata.split(b" ")
    if len(fields) != 3:
        raise _fail("INVALID_GIT_TREE_ENTRY", expected_path)
    try:
        mode, object_type, object_id = (field.decode("ascii") for field in fields)
    except UnicodeDecodeError as exc:
        raise _fail("INVALID_GIT_TREE_ENTRY", expected_path) from exc
    if mode != "100644" or object_type != "blob" or not GIT_OID_RE.fullmatch(object_id):
        raise _fail("INVALID_GIT_TREE_ENTRY", expected_path)
    return _GitTreeEntry(mode, object_type, object_id, expected_path)


class _ExactGitTreeReader:
    def __init__(self, *, repository_root: Path, source_commit_sha: str) -> None:
        if source_commit_sha != SOURCE_COMMIT_SHA:
            raise _fail(
                "INVALID_SOURCE_COMMIT",
                f"source_commit_sha must be {SOURCE_COMMIT_SHA}",
            )
        self.repository_root = repository_root.resolve()
        if self._git("cat-file", "-t", source_commit_sha).decode().strip() != "commit":
            raise _fail("INVALID_SOURCE_COMMIT", "source_commit_sha is not a commit")
        tree = self._git("rev-parse", f"{source_commit_sha}^{{tree}}").decode().strip()
        if tree != SOURCE_TREE_SHA:
            raise _fail(
                "INVALID_SOURCE_TREE",
                f"expected {SOURCE_TREE_SHA}, got {tree}",
            )
        self.source_commit_sha = source_commit_sha
        self.source_tree_sha = tree
        self.input_blob_sha256: dict[str, str] = {}
        self.input_git_entries: dict[str, str] = {}
        self._cache: dict[str, bytes] = {}

    def _git(self, *args: str) -> bytes:
        environment = dict(os.environ)
        environment["GIT_LITERAL_PATHSPECS"] = "1"
        environment["GIT_NO_REPLACE_OBJECTS"] = "1"
        try:
            completed = subprocess.run(
                ["git", "-C", str(self.repository_root), *args],
                check=False,
                capture_output=True,
                env=environment,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise _fail("GIT_READ_FAILED", str(exc)) from exc
        if completed.returncode != 0:
            raise _fail("GIT_READ_FAILED", "git object lookup failed")
        return completed.stdout

    def read_blob(self, path: str) -> bytes:
        canonical = _canonical_repo_path(path)
        cached = self._cache.get(canonical)
        if cached is not None:
            return cached
        entry = _parse_tree_entry(
            self._git("ls-tree", "-z", self.source_tree_sha, "--", canonical),
            expected_path=canonical,
        )
        raw = self._git("cat-file", "blob", entry.object_id)
        self.input_blob_sha256[canonical] = _sha256(raw)
        self.input_git_entries[canonical] = (
            f"{entry.mode} {entry.object_type} {entry.object_id}"
        )
        self._cache[canonical] = raw
        return raw


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _fail("DUPLICATE_JSON_KEY", key)
        result[key] = value
    return result


def _json(raw: bytes, *, path: str) -> Any:
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except AuthorizationCandidateError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail("INVALID_JSON", path) from exc


def _require_mapping(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fail("INVALID_DOCUMENT", f"{label} is not a mapping")
    return value


def _require_list(value: Any, *, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise _fail("INVALID_DOCUMENT", f"{label} is not a list")
    return value


def _parse_final_set(raw: bytes) -> tuple[str, ...]:
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise _fail("INVALID_FINAL_SET", "not ASCII") from exc
    if not text.endswith("\n") or "\r" in text:
        raise _fail("INVALID_FINAL_SET", "not canonical LF-final")
    values = tuple(text[:-1].split("\n"))
    if (
        len(values) != FINAL_CONTENT_COUNT
        or tuple(sorted(values)) != values
        or len(set(values)) != len(values)
        or any(not SHA256_RE.fullmatch(value) for value in values)
        or _sha256(raw) != FINAL_SET_SHA256
    ):
        raise _fail("INVALID_FINAL_SET", "count, order or digest mismatch")
    return values


def _verify_authority_bindings(
    *,
    reader: _ExactGitTreeReader,
    aggregate: dict[str, Any],
) -> dict[str, Any]:
    raw = reader.read_blob(AUTHORITY_BINDINGS_PATH)
    if _sha256(raw) != AUTHORITY_BINDINGS_SHA256:
        raise _fail("AUTHORITY_BINDINGS_MISMATCH", AUTHORITY_BINDINGS_PATH)
    document = _require_mapping(
        _json(raw, path=AUTHORITY_BINDINGS_PATH), label="authority bindings"
    )
    if (
        document.get("binding_kind")
        != "PRODUCTION_PROFILE_RELEASE_AUTHORITY_BINDINGS_V1"
        or document.get("school_year") != "2026-2027"
        or document.get("profile_manifest_fingerprint")
        != PROFILE_MANIFEST_FINGERPRINT
    ):
        raise _fail("AUTHORITY_BINDINGS_MISMATCH", "header")
    declared = _require_mapping(document.get("bindings"), label="bindings")
    aggregate_authorities = _require_mapping(
        aggregate.get("authorities"), label="aggregate authorities"
    )
    if set(declared) != set(aggregate_authorities):
        raise _fail("AUTHORITY_BINDINGS_MISMATCH", "authority names")
    for name in sorted(declared):
        binding = _require_mapping(declared[name], label=f"binding {name}")
        path = binding.get("path")
        if not isinstance(path, str):
            raise _fail("AUTHORITY_BINDINGS_MISMATCH", f"path for {name}")
        actual_file_digest = _sha256(reader.read_blob(path))
        if actual_file_digest != binding.get("file_sha256"):
            raise _fail("AUTHORITY_BINDINGS_MISMATCH", f"file digest for {name}")
        if binding.get("authority_sha256") != aggregate_authorities[name]:
            raise _fail("AUTHORITY_BINDINGS_MISMATCH", f"authority digest for {name}")
    if (
        declared["corpus_manifest_sha256"].get("authority_sha256")
        != CORPUS_MANIFEST_SHA256
        or declared["profile_manifest_sha256"].get("authority_sha256")
        != PROFILE_MANIFEST_FINGERPRINT
        or declared["pii_evidence_sha256"].get("authority_sha256")
        != PII_EVIDENCE_SHA256
        or declared["currentness_evidence_sha256"].get("authority_sha256")
        != CURRENTNESS_EVIDENCE_SHA256
        or declared["rights_registry_sha256"].get("authority_sha256")
        != RIGHTS_EVIDENCE_SHA256
    ):
        raise _fail("AUTHORITY_BINDINGS_MISMATCH", "required authority")
    return document


def _pii_result_digest(row: Mapping[str, Any]) -> str:
    core = {
        "content_sha256": row.get("content_sha256"),
        "pages_scanned": row.get("pages_scanned"),
        "characters_scanned": row.get("characters_scanned"),
        "status": row.get("status"),
        "pii_detected": row.get("pii_detected"),
    }
    raw = json.dumps(
        core,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _sha256(raw)


def _verify_pii(
    document: dict[str, Any],
    *,
    final_contents: set[str],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> None:
    results = _require_list(document.get("results"), label="PII results")
    by_content: dict[str, dict[str, Any]] = {}
    for raw in results:
        row = _require_mapping(raw, label="PII result")
        content = row.get("content_sha256")
        if not isinstance(content, str) or content in by_content:
            raise _fail("PII_EVIDENCE_MISMATCH", "duplicate or missing content")
        by_content[content] = row
    summary = _require_mapping(document.get("summary"), label="PII summary")
    if (
        document.get("evidence_kind") != "REAL_CORPUS_PII_SCAN"
        or document.get("school_year") != "2026-2027"
        or document.get("corpus_manifest_sha256") != CORPUS_MANIFEST_SHA256
        or set(by_content) != final_contents
        or document.get("required_pdf_path_count") != FINAL_CONTENT_COUNT
        or document.get("remote_access_mode") != "READ_ONLY"
        or document.get("remote_write_operations") != 0
        or document.get("raw_pii_in_logs") is not False
        or document.get("raw_pii_in_output") is not False
        or summary.get("pii_scan_required") != FINAL_CONTENT_COUNT
        or summary.get("pii_scanned") != FINAL_CONTENT_COUNT
        or summary.get("pii_scan_coverage") != 1.0
        or summary.get("pii_not_scanned") != 0
        or summary.get("sha256_mismatches") != 0
        or any(
            row.get("status") != "CLEARED"
            or row.get("pii_detected") is not False
            or type(row.get("characters_scanned")) is not int
            or row["characters_scanned"] <= 0
            or type(row.get("pages_scanned")) is not int
            or row["pages_scanned"] <= 0
            or not isinstance(row.get("evidence_sha256"), str)
            or not SHA256_RE.fullmatch(row["evidence_sha256"])
            or row["evidence_sha256"] != _pii_result_digest(row)
            or type(artifacts.get(content, {}).get("page_count")) is not int
            or artifacts[content]["page_count"] != row["pages_scanned"]
            or artifacts.get(content, {}).get("source_path")
            != row.get("source_path")
            for content, row in by_content.items()
        )
    ):
        raise _fail("PII_EVIDENCE_MISMATCH", "not exactly 26 CLEARED results")
    for row in by_content.values():
        try:
            _canonical_official_source_path(row.get("source_path"))
        except AuthorizationCandidateError as exc:
            raise _fail(
                "PII_EVIDENCE_MISMATCH", "PII source path is not canonical"
            ) from exc


def _verify_currentness(
    document: dict[str, Any],
    *,
    final_contents: set[str],
    network_audit: dict[str, Any],
    network_audit_sha256: str,
    artifacts: Mapping[str, Mapping[str, Any]],
) -> None:
    rows = _require_list(document.get("artifacts"), label="currentness artifacts")
    by_content: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = _require_mapping(raw, label="currentness artifact")
        content = row.get("content_sha256")
        if not isinstance(content, str) or content in by_content:
            raise _fail("CURRENTNESS_EVIDENCE_MISMATCH", "duplicate content")
        by_content[content] = row
    counts = _require_mapping(document.get("counts"), label="currentness counts")
    partition = _require_mapping(
        document.get("partition"), label="currentness partition"
    )
    audit_rows = _require_list(
        network_audit.get("artifacts"), label="currentness network artifacts"
    )
    audit_by_content: dict[str, dict[str, Any]] = {}
    for raw in audit_rows:
        audit_row = _require_mapping(raw, label="currentness network artifact")
        content = audit_row.get("content_sha256")
        if not isinstance(content, str) or content in audit_by_content:
            raise _fail("CURRENTNESS_EVIDENCE_MISMATCH", "duplicate audit content")
        audit_by_content[content] = audit_row
    audit_counts = _require_mapping(
        network_audit.get("counts"), label="currentness network counts"
    )
    if (
        document.get("evidence_kind") != "MULTILEVEL_ARTIFACT_CURRENTNESS_V1"
        or document.get("school_year") != "2026-2027"
        or document.get("currentness_audit_sha256") != CURRENTNESS_AUDIT_SHA256
        or network_audit_sha256 != CURRENTNESS_AUDIT_SHA256
        or network_audit.get("audit_kind")
        != "PRODUCTION_PROFILE_GATE_CURRENTNESS_AUDIT_V1"
        or network_audit.get("network_mode") != "READ_ONLY"
        or network_audit.get("write_operations") != 0
        or audit_counts != {"digest_mismatch": 0, "verified": FINAL_CONTENT_COUNT}
        or set(by_content) != final_contents
        or set(audit_by_content) != final_contents
        or counts
        != {
            "artifacts": FINAL_CONTENT_COUNT,
            "current": FINAL_CONTENT_COUNT,
            "evaluated": FINAL_CONTENT_COUNT,
            "review_required": 0,
            "unevaluated": 0,
        }
        or set(partition.get("current", [])) != final_contents
        or partition.get("review_required") != []
        or partition.get("unevaluated") != []
        or any(
            row.get("decision") != "CURRENT"
            or row.get("byte_identity") is not True
            or row.get("effective_currentness") != "actuel"
            or row.get("current_for_school_year") != "2026-2027"
            or row.get("current_download_sha256") != content
            or artifacts.get(content, {}).get("source_path") != row.get("exact_path")
            or artifacts.get(content, {}).get("source_url")
            != row.get("current_download_url")
            or audit_by_content.get(content, {}).get("downloaded_sha256") != content
            or audit_by_content.get(content, {}).get("byte_identity") is not True
            or audit_by_content.get(content, {}).get("current_download_url")
            != row.get("current_download_url")
            or audit_by_content.get(content, {}).get("current_source_listing_url")
            != row.get("current_source_listing_url")
            for content, row in by_content.items()
        )
    ):
        raise _fail("CURRENTNESS_EVIDENCE_MISMATCH", "not exactly 26 CURRENT results")
    for row in by_content.values():
        try:
            _canonical_official_source_path(row.get("exact_path"))
            _source_domain(row.get("current_download_url"))
            _source_domain(row.get("current_source_listing_url"))
        except AuthorizationCandidateError as exc:
            raise _fail(
                "CURRENTNESS_EVIDENCE_MISMATCH",
                "currentness source fact is not canonical or approved",
            ) from exc


def _verify_rights(document: dict[str, Any]) -> None:
    decisions = _require_mapping(
        document.get("human_rights_decisions"), label="human rights decisions"
    )
    decision = _require_mapping(
        decisions.get("eduscol_generic_approval"), label="Eduscol rights decision"
    )
    categories = _require_mapping(
        document.get("rights_categories"), label="rights categories"
    )
    source_evidence = _require_mapping(
        document.get("source_evidence"), label="source evidence"
    )
    eduscol = _require_mapping(
        source_evidence.get("eduscol_education_gouv_fr"),
        label="Eduscol source evidence",
    )
    if (
        decision.get("decision_type") != "HUMAN_ORGANIZATIONAL_RIGHTS_APPROVAL"
        or decision.get("decision_maker") != "Nexus Réussite"
        or decision.get("decision_source") != "EXPLICIT_GO_LIVE_INSTRUCTION"
        or decision.get("decision_date") != "2026-08-08"
        or decision.get("scope_manifest_sha256") != CORPUS_MANIFEST_SHA256
        or decision.get("scope_zone") != "01_EDUSCOL_OFFICIEL/"
        or decision.get("approved_for_internal_rag") is not True
        or decision.get("approved_for_production_rag") is not True
        or decision.get("generic_rights_blocker") is not False
        or "officiel_public" not in categories
        or eduscol.get("zone") != "01_EDUSCOL_OFFICIEL/"
        or eduscol.get("domain") != "eduscol.education.gouv.fr"
        or eduscol.get("provenance_status") != "VERIFIED"
        or eduscol.get("rights_status") != "CLEARED_BY_HUMAN_DECISION"
        or eduscol.get("rights_decision_ref") != "eduscol_generic_approval"
        or eduscol.get("recommended_rights_category") != "officiel_public"
    ):
        raise _fail("RIGHTS_EVIDENCE_MISMATCH", "production rights are not cleared")


def _source_domain(source_url: Any) -> str:
    if not isinstance(source_url, str):
        raise _fail("INVALID_SOURCE_URL", "missing source URL")
    parsed = urlsplit(source_url)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.hostname not in ALLOWED_SOURCE_DOMAINS
    ):
        raise _fail("INVALID_SOURCE_URL", source_url)
    assert parsed.hostname is not None
    return parsed.hostname


def _canonical_official_source_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise _fail("INVALID_SOURCE_PATH", repr(value))
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
        or len(path.parts) < 2
        or path.parts[0] != "01_EDUSCOL_OFFICIEL"
    ):
        raise _fail("INVALID_SOURCE_PATH", value)
    return value


def _require_artifact_collection(
    *,
    content_sha256: str,
    expected_collection: str,
    actual_collection: str | None,
) -> None:
    if actual_collection != expected_collection:
        raise _fail(
            "SUBJECT_RELEASE_MISMATCH",
            f"{content_sha256} belongs to {actual_collection!r}, not {expected_collection!r}",
        )


def _subject_artifacts(
    *,
    reader: _ExactGitTreeReader,
    aggregate: dict[str, Any],
    final_contents: set[str],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, str],
    dict[str, set[str]],
    dict[str, dict[str, Any]],
]:
    subjects = _require_list(aggregate.get("subjects"), label="aggregate subjects")
    if len(subjects) != AUTHORIZATION_COUNT:
        raise _fail("AGGREGATE_MISMATCH", "subject count")
    artifacts: dict[str, dict[str, Any]] = {}
    artifact_collections: dict[str, str] = {}
    domains: dict[str, set[str]] = defaultdict(set)
    subject_by_collection: dict[str, dict[str, Any]] = {}
    for raw_subject_ref in subjects:
        subject_ref = _require_mapping(raw_subject_ref, label="subject reference")
        relative = subject_ref.get("path")
        collection = subject_ref.get("collection")
        if not isinstance(relative, str) or not isinstance(collection, str):
            raise _fail("AGGREGATE_MISMATCH", "subject reference")
        path = f"{RELEASE_ROOT}/{relative}"
        subject_raw = reader.read_blob(path)
        if _sha256(subject_raw) != subject_ref.get("sha256"):
            raise _fail("SUBJECT_RELEASE_MISMATCH", path)
        subject = _require_mapping(_json(subject_raw, path=path), label=path)
        if (
            subject.get("collection") != collection
            or collection in subject_by_collection
            or subject.get("authorities") != aggregate.get("authorities")
        ):
            raise _fail("SUBJECT_RELEASE_MISMATCH", collection)
        subject_by_collection[collection] = subject
        subject_profile = _require_mapping(
            subject.get("profile"), label=f"profile {collection}"
        )
        if subject_profile.get("manifest_digest") != PROFILE_MANIFEST_FINGERPRINT:
            raise _fail("SUBJECT_RELEASE_MISMATCH", f"profile manifest {collection}")
        for raw_artifact in _require_list(
            subject.get("artifacts"), label=f"artifacts {collection}"
        ):
            artifact = _require_mapping(raw_artifact, label=f"artifact {collection}")
            content = artifact.get("content_sha256")
            if (
                not isinstance(content, str)
                or content in artifacts
            ):
                raise _fail("SUBJECT_RELEASE_MISMATCH", f"artifact {content!r}")
            _canonical_official_source_path(artifact.get("source_path"))
            artifacts[content] = artifact
            artifact_collections[content] = collection
            domains[collection].add(_source_domain(artifact.get("source_url")))
    if set(artifacts) != final_contents or set(subject_by_collection) != {
        subject.get("collection") for subject in subjects
    }:
        raise _fail("SUBJECT_RELEASE_MISMATCH", "content or collection union")
    return artifacts, artifact_collections, domains, subject_by_collection


def build_authorization_candidates(
    *, repository_root: Path, source_commit_sha: str
) -> ProducedAuthorizationCandidates:
    """Construit les 18 candidats depuis les seuls blobs du commit prescrit."""
    reader = _ExactGitTreeReader(
        repository_root=repository_root,
        source_commit_sha=source_commit_sha,
    )
    final_values = _parse_final_set(reader.read_blob(FINAL_SET_PATH))
    final_contents = set(final_values)

    placement_raw = reader.read_blob(PLACEMENT_PATH)
    if _sha256(placement_raw) != RELEASE_SCOPE_PLACEMENT_SHA256:
        raise _fail("PLACEMENT_MISMATCH", "file digest")
    placement = parse_release_scope_placement(placement_raw)
    if (
        placement.profile_manifest_digest != PROFILE_MANIFEST_FINGERPRINT
        or {row.content_sha256 for row in placement.placements} != final_contents
    ):
        raise _fail("PLACEMENT_MISMATCH", "header or content union")

    profiles_raw = reader.read_blob(VERIFIED_PROFILES_PATH)
    profiles_document = _require_mapping(
        _json(profiles_raw, path=VERIFIED_PROFILES_PATH),
        label="verified profiles",
    )
    if profiles_document.get("profile_manifest_digest") != PROFILE_MANIFEST_FINGERPRINT:
        raise _fail("PROFILE_MISMATCH", "manifest digest")
    profiles: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_profile in _require_list(
        profiles_document.get("profiles"), label="verified profiles"
    ):
        verified_profile = _require_mapping(raw_profile, label="verified profile")
        identity = (
            verified_profile.get("profile_id"),
            verified_profile.get("profile_version"),
        )
        if not all(isinstance(value, str) for value in identity) or identity in profiles:
            raise _fail("PROFILE_MISMATCH", f"invalid identity {identity!r}")
        profiles[identity] = verified_profile  # type: ignore[index]
    if len(profiles) != AUTHORIZATION_COUNT:
        raise _fail("PROFILE_MISMATCH", "profile count")

    aggregate_raw = reader.read_blob(AGGREGATE_PATH)
    if _sha256(aggregate_raw) != AGGREGATE_RELEASE_SHA256:
        raise _fail("AGGREGATE_MISMATCH", "file digest")
    aggregate = _require_mapping(
        _json(aggregate_raw, path=AGGREGATE_PATH), label="aggregate"
    )
    if (
        aggregate.get("release_id") != "production-profile-gate-2026-2027-v1"
        or aggregate.get("school_year") != "2026-2027"
        or aggregate.get("expected_counts", {}).get("artifacts")
        != FINAL_CONTENT_COUNT
        or aggregate.get("authorities", {}).get("profile_manifest_sha256")
        != PROFILE_MANIFEST_FINGERPRINT
        or aggregate.get("authorities", {}).get("corpus_manifest_sha256")
        != CORPUS_MANIFEST_SHA256
    ):
        raise _fail("AGGREGATE_MISMATCH", "header")
    _verify_authority_bindings(reader=reader, aggregate=aggregate)

    artifacts, artifact_collections, domains_by_collection, subjects = _subject_artifacts(
        reader=reader,
        aggregate=aggregate,
        final_contents=final_contents,
    )
    pii_document = _require_mapping(
        _json(reader.read_blob(PII_EVIDENCE_PATH), path=PII_EVIDENCE_PATH),
        label="PII evidence",
    )
    _verify_pii(
        pii_document,
        final_contents=final_contents,
        artifacts=artifacts,
    )
    currentness_document = _require_mapping(
        _json(
            reader.read_blob(CURRENTNESS_EVIDENCE_PATH),
            path=CURRENTNESS_EVIDENCE_PATH,
        ),
        label="currentness evidence",
    )
    currentness_audit_raw = reader.read_blob(CURRENTNESS_AUDIT_PATH)
    currentness_audit = _require_mapping(
        _json(currentness_audit_raw, path=CURRENTNESS_AUDIT_PATH),
        label="currentness network audit",
    )
    _verify_currentness(
        currentness_document,
        final_contents=final_contents,
        network_audit=currentness_audit,
        network_audit_sha256=_sha256(currentness_audit_raw),
        artifacts=artifacts,
    )
    rights_document = strict_yaml_mapping(
        reader.read_blob(RIGHTS_EVIDENCE_PATH), source=RIGHTS_EVIDENCE_PATH
    )
    _verify_rights(rights_document)

    grouped: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    placement_by_group: dict[tuple[str, str, str, str], Any] = {}
    for row in placement.placements:
        identity = (row.profile_id, row.profile_version)
        profile_fact = profiles.get(identity)
        if (
            profile_fact is None
            or profile_fact.get("profile_fingerprint") != row.profile_fingerprint
            or profile_fact.get("scope") != row.scope.model_dump(mode="json")
        ):
            raise _fail("PROFILE_MISMATCH", row.content_sha256)
        subject = subjects.get(row.scope.collection)
        subject_profile = (
            _require_mapping(subject.get("profile"), label="subject profile")
            if subject is not None
            else None
        )
        if (
            subject_profile is None
            or subject_profile.get("version") != row.profile_version
            or subject_profile.get("fingerprint") != row.profile_fingerprint
            or row.content_sha256 not in artifacts
        ):
            raise _fail("SUBJECT_RELEASE_MISMATCH", row.content_sha256)
        _require_artifact_collection(
            content_sha256=row.content_sha256,
            expected_collection=row.scope.collection,
            actual_collection=artifact_collections.get(row.content_sha256),
        )
        key = (
            row.profile_id,
            row.profile_version,
            row.profile_fingerprint,
            scope_digest(row.scope),
        )
        previous = placement_by_group.get(key)
        if previous is not None and previous.scope != row.scope:
            raise _fail("PLACEMENT_MISMATCH", "scope digest collision")
        placement_by_group[key] = row
        grouped[key].append(row.content_sha256)

    if len(grouped) != AUTHORIZATION_COUNT:
        raise _fail("PLACEMENT_MISMATCH", "scope count")
    candidates: list[ScopeAuthorizationArtifactV2] = []
    for key in sorted(grouped):
        row = placement_by_group[key]
        content_values = tuple(sorted(grouped[key]))
        authorization_id = f"prerentree-2026-2027-{row.profile_id}-v1"
        candidates.append(
            ScopeAuthorizationArtifactV2(
                protocol_version="LOT41A-V2",
                authorization_id=authorization_id,
                decision="AUTHORIZE_INGESTION_SCOPE",
                scope=row.scope,
                manifest_digest=PROFILE_MANIFEST_FINGERPRINT,
                profile_id=row.profile_id,
                profile_version=row.profile_version,
                profile_fingerprint=row.profile_fingerprint,
                allowed_domains=tuple(sorted(domains_by_collection[row.scope.collection])),
                rights_categories=("officiel_public",),
                exclusions=(),
                pii_absence_attested=True,
                pii_absence_evidence=PII_EVIDENCE_REFERENCE,
                valid_from=VALID_FROM,
                valid_until=VALID_UNTIL,
                allowed_content_sha256=content_values,
            )
        )
    candidates.sort(key=lambda candidate: candidate.authorization_id)
    union = {
        content
        for candidate in candidates
        for content in candidate.allowed_content_sha256
    }
    if union != final_contents or _content_set_digest(union) != FINAL_SET_SHA256:
        raise _fail("AUTHORIZATION_UNION_MISMATCH", "gap, extra or digest")
    if len(union) != sum(len(candidate.allowed_content_sha256) for candidate in candidates):
        raise _fail("AUTHORIZATION_OVERLAP", "content has more than one owner")

    return ProducedAuthorizationCandidates(
        candidates=tuple(candidates),
        provenance=AuthorizationCandidateProvenance(
            source_commit_sha=reader.source_commit_sha,
            source_tree_sha=reader.source_tree_sha,
            input_blob_sha256=dict(sorted(reader.input_blob_sha256.items())),
            input_git_entries=dict(sorted(reader.input_git_entries.items())),
        ),
    )


def _canonical_json_bytes(document: object) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _authorization_matrix(
    result: ProducedAuthorizationCandidates,
) -> dict[str, Any]:
    authorization_rows: list[dict[str, Any]] = []
    for candidate in result.candidates:
        subject_path = (
            f"{RELEASE_ROOT}/subjects/{candidate.scope.collection}.release.json"
        )
        subject_sha256 = result.provenance.input_blob_sha256.get(subject_path)
        if subject_sha256 is None:
            raise _fail(
                "MATERIALIZATION_MISMATCH",
                f"missing subject release provenance for {candidate.authorization_id}",
            )
        content_set = set(candidate.allowed_content_sha256)
        authorization_rows.append(
            {
                "allowed_domains": list(candidate.allowed_domains),
                "authorization_digest": candidate.digest(),
                "authorization_id": candidate.authorization_id,
                "authorization_path": canonical_authorization_path(
                    candidate.authorization_id
                ),
                "content_count": len(content_set),
                "content_set_sha256": _content_set_digest(content_set),
                "currentness_audit_path": CURRENTNESS_AUDIT_PATH,
                "currentness_audit_sha256": CURRENTNESS_AUDIT_SHA256,
                "currentness_evidence_path": CURRENTNESS_EVIDENCE_PATH,
                "currentness_evidence_sha256": CURRENTNESS_EVIDENCE_SHA256,
                "pii_evidence_path": PII_EVIDENCE_PATH,
                "pii_evidence_sha256": PII_EVIDENCE_SHA256,
                "profile_fingerprint": candidate.profile_fingerprint,
                "profile_id": candidate.profile_id,
                "profile_version": candidate.profile_version,
                "rights_evidence_path": RIGHTS_EVIDENCE_PATH,
                "rights_evidence_sha256": RIGHTS_EVIDENCE_SHA256,
                "scope": candidate.scope.model_dump(mode="json"),
                "scope_digest": scope_digest(candidate.scope),
                "subject_release_path": subject_path,
                "subject_release_sha256": subject_sha256,
            }
        )
    contents = [
        content
        for candidate in result.candidates
        for content in candidate.allowed_content_sha256
    ]
    unique_contents = set(contents)
    if (
        len(contents) != len(unique_contents)
        or len(unique_contents) != FINAL_CONTENT_COUNT
        or _content_set_digest(unique_contents) != FINAL_SET_SHA256
    ):
        raise _fail("MATERIALIZATION_MISMATCH", "authorization partition")
    return {
        "aggregate_release_path": AGGREGATE_PATH,
        "aggregate_release_sha256": AGGREGATE_RELEASE_SHA256,
        "authorization_candidate_status": (
            "PENDING_TRUSTED_HUMAN_REVIEW_AND_SIGNED_REVIEW_BINDINGS"
        ),
        "authorization_content_union": len(unique_contents),
        "authorization_count": len(result.candidates),
        "authorization_extra": 0,
        "authorization_gap": 0,
        "authorization_overlap": 0,
        "authorization_union_sha256": _content_set_digest(unique_contents),
        "authorizations": authorization_rows,
        "authority_bindings_path": AUTHORITY_BINDINGS_PATH,
        "authority_bindings_sha256": AUTHORITY_BINDINGS_SHA256,
        "corpus_manifest_sha256": CORPUS_MANIFEST_SHA256,
        "currentness_audit_path": CURRENTNESS_AUDIT_PATH,
        "currentness_audit_sha256": CURRENTNESS_AUDIT_SHA256,
        "currentness_evidence_path": CURRENTNESS_EVIDENCE_PATH,
        "currentness_evidence_sha256": CURRENTNESS_EVIDENCE_SHA256,
        "final_content_set_path": FINAL_SET_PATH,
        "final_content_set_sha256": FINAL_SET_SHA256,
        "input_blobs": [
            {
                "file_sha256": digest,
                "git_entry": result.provenance.input_git_entries[path],
                "path": path,
            }
            for path, digest in sorted(result.provenance.input_blob_sha256.items())
        ],
        "pii_evidence_path": PII_EVIDENCE_PATH,
        "pii_evidence_sha256": PII_EVIDENCE_SHA256,
        "profile_manifest_digest": PROFILE_MANIFEST_FINGERPRINT,
        "protocol_version": "NEXUS-PRODUCTION-AUTHORIZATION-MATRIX-V1",
        "release_scope_placement_path": PLACEMENT_PATH,
        "release_scope_placement_sha256": RELEASE_SCOPE_PLACEMENT_SHA256,
        "rights_evidence_path": RIGHTS_EVIDENCE_PATH,
        "rights_evidence_sha256": RIGHTS_EVIDENCE_SHA256,
        "source_commit_sha": result.provenance.source_commit_sha,
        "source_tree_sha": result.provenance.source_tree_sha,
        "valid_from": VALID_FROM.isoformat().replace("+00:00", "Z"),
        "valid_until": VALID_UNTIL.isoformat().replace("+00:00", "Z"),
        "verified_profiles_path": VERIFIED_PROFILES_PATH,
    }


def authorization_candidate_outputs(
    result: ProducedAuthorizationCandidates,
) -> dict[str, bytes]:
    """Retourne les 18 artefacts et leur matrice sous forme canonique."""
    if len(result.candidates) != AUTHORIZATION_COUNT:
        raise _fail("MATERIALIZATION_MISMATCH", "authorization count")
    outputs: dict[str, bytes] = {}
    for candidate in result.candidates:
        path = canonical_authorization_path(candidate.authorization_id)
        raw = candidate.canonical_bytes()
        parsed = parse_scope_authorization_artifact(raw)
        if not isinstance(parsed, ScopeAuthorizationArtifactV2) or parsed != candidate:
            raise _fail("MATERIALIZATION_MISMATCH", path)
        if path in outputs:
            raise _fail("MATERIALIZATION_MISMATCH", f"duplicate path {path}")
        outputs[path] = raw
    outputs[AUTHORIZATION_MATRIX_PATH] = _canonical_json_bytes(
        _authorization_matrix(result)
    )
    return dict(sorted(outputs.items()))


def _output_path(*, output_root: Path, relative_path: str) -> Path:
    canonical = _canonical_repo_path(relative_path)
    root = output_root.resolve()
    target = output_root / canonical
    if not target.resolve(strict=False).is_relative_to(root):
        raise _fail("MATERIALIZATION_MISMATCH", f"unsafe output path {canonical}")
    return target


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def write_authorization_candidates(
    result: ProducedAuthorizationCandidates, *, output_root: Path
) -> None:
    """Écrit chaque sortie de manière atomique dans la racine prescrite."""
    outputs = authorization_candidate_outputs(result)
    for relative_path, raw in outputs.items():
        _atomic_write(
            _output_path(output_root=output_root, relative_path=relative_path),
            raw,
        )
    check_authorization_candidates(result, output_root=output_root)


def check_authorization_candidates(
    result: ProducedAuthorizationCandidates, *, output_root: Path
) -> None:
    """Refuse toute sortie absente, altérée ou autorisation supplémentaire."""
    outputs = authorization_candidate_outputs(result)
    for relative_path, expected in outputs.items():
        target = _output_path(
            output_root=output_root,
            relative_path=relative_path,
        )
        if target.is_symlink() or not target.is_file() or target.read_bytes() != expected:
            raise _fail("MATERIALIZATION_MISMATCH", relative_path)
    authorization_directory = _output_path(
        output_root=output_root,
        relative_path="governance/authorizations",
    )
    expected_authorizations = {
        path
        for path in outputs
        if path.startswith("governance/authorizations/")
    }
    actual_authorizations = (
        {
            f"governance/authorizations/{entry.name}"
            for entry in authorization_directory.iterdir()
        }
        if authorization_directory.is_dir()
        and not authorization_directory.is_symlink()
        else set()
    )
    if actual_authorizations != expected_authorizations:
        raise _fail(
            "MATERIALIZATION_MISMATCH",
            "authorization paths contain missing or extra entries",
        )


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Construit et vérifie les candidats d'autorisation production."
    )
    parser.add_argument(
        "--source-commit",
        required=True,
        help="Commit Git exact contenant les preuves métier fusionnées.",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="Racine du dépôt Git (défaut dérivé de l'emplacement du script).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--write",
        action="store_true",
        help="Matérialise les artefacts et la matrice dans la racine du dépôt.",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="Vérifie les sorties déjà matérialisées sans les modifier.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    try:
        result = build_authorization_candidates(
            repository_root=args.repository_root,
            source_commit_sha=args.source_commit,
        )
        if args.write:
            write_authorization_candidates(result, output_root=args.repository_root)
        elif args.check:
            check_authorization_candidates(result, output_root=args.repository_root)
    except (AuthorizationCandidateError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    contents = {
        content
        for candidate in result.candidates
        for content in candidate.allowed_content_sha256
    }
    print(
        json.dumps(
            {
                "authorization_count": len(result.candidates),
                "content_count": len(contents),
                "content_set_sha256": _content_set_digest(contents),
                "mode": "write" if args.write else "check" if args.check else "verify",
                "source_commit_sha": result.provenance.source_commit_sha,
                "source_tree_sha": result.provenance.source_tree_sha,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


__all__ = [
    "AUTHORIZATION_COUNT",
    "FINAL_CONTENT_COUNT",
    "FINAL_SET_SHA256",
    "PII_EVIDENCE_REFERENCE",
    "PROFILE_MANIFEST_FINGERPRINT",
    "AuthorizationCandidateError",
    "AuthorizationCandidateProvenance",
    "ProducedAuthorizationCandidates",
    "authorization_candidate_outputs",
    "build_authorization_candidates",
    "check_authorization_candidates",
    "main",
    "write_authorization_candidates",
]


if __name__ == "__main__":
    sys.exit(main())
