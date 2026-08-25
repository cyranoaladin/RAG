"""Contrat des candidats d'autorisation production 2026-2027."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any, Protocol, cast

import pytest
from nexus_contracts import (
    ScopeAuthorizationArtifactV2,
    canonical_authorization_path,
    parse_release_scope_placement,
    parse_scope_authorization_artifact,
    scope_digest,
)
from nexus_contracts.profile_manifest import strict_yaml_mapping

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "services"
    / "rag-pedago"
    / "scripts"
    / "build_production_authorization_candidates.py"
)
PLACEMENT_PATH = "docs/reports/release_scope_placement_20260825.jsonl"
FINAL_SET_PATH = "docs/reports/final_production_eligible_set_20260825.txt"
VERIFIED_PROFILES_PATH = "docs/reports/verified_production_profiles_20260825.json"
AGGREGATE_PATH = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/"
    "production-profile-gate.release.json"
)
PII_EVIDENCE_PATH = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/"
    "pii_evidence.json"
)
CURRENTNESS_EVIDENCE_PATH = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/"
    "currentness_evidence.json"
)
CURRENTNESS_AUDIT_PATH = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/"
    "currentness_network_audit.json"
)
RIGHTS_EVIDENCE_PATH = "services/rag-pedago/configs/rights_evidence_registry.yml"

SOURCE_COMMIT_SHA = "3566cafb44138d6a7f00296dc0654257f9bf0ad6"
SOURCE_TREE_SHA = "8c5081a52096d531f1bd027790e600eb83b05bd5"
OTHER_COMMIT_SHA = "94549f7f44e4efd6ccd60df8635e71b372ddee2f"
AUTHORIZATION_COUNT = 18
FINAL_CONTENT_COUNT = 26
FINAL_SET_SHA256 = "fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0"
PROFILE_MANIFEST_FINGERPRINT = (
    "57d532ca0c80f0e70218e74902f1d47a4ca9f21d7e6bafa209f6f89426125b6c"
)
PII_EVIDENCE_SHA256 = (
    "cec9baca680439afa0dd6b4aadbb0f805514424a853a10303e6216dd8ffa7e99"
)
PII_EVIDENCE_REFERENCE = (
    "sha256:cec9baca680439afa0dd6b4aadbb0f805514424a853a10303e6216dd8ffa7e99 "
    "path:services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/"
    "pii_evidence.json"
)


class Provenance(Protocol):
    source_commit_sha: str
    source_tree_sha: str
    input_blob_sha256: Mapping[str, str]
    input_git_entries: Mapping[str, str]


class CandidateResult(Protocol):
    candidates: tuple[ScopeAuthorizationArtifactV2, ...]
    provenance: Provenance


class Producer(Protocol):
    subprocess: object
    AUTHORIZATION_COUNT: int
    FINAL_CONTENT_COUNT: int
    FINAL_SET_SHA256: str
    PROFILE_MANIFEST_FINGERPRINT: str
    PII_EVIDENCE_REFERENCE: str

    def build_authorization_candidates(
        self, *, repository_root: Path, source_commit_sha: str
    ) -> CandidateResult: ...

    def authorization_candidate_outputs(
        self, result: CandidateResult
    ) -> Mapping[str, bytes]: ...

    def write_authorization_candidates(
        self, result: CandidateResult, *, output_root: Path
    ) -> None: ...

    def check_authorization_candidates(
        self, result: CandidateResult, *, output_root: Path
    ) -> None: ...

    def _canonical_official_source_path(self, value: object) -> str: ...

    def _require_artifact_collection(
        self,
        *,
        content_sha256: str,
        expected_collection: str,
        actual_collection: str | None,
    ) -> None: ...

    def _verify_pii(
        self,
        document: dict[str, object],
        *,
        final_contents: set[str],
        artifacts: Mapping[str, Mapping[str, object]],
    ) -> None: ...

    def _verify_currentness(
        self,
        document: dict[str, object],
        *,
        final_contents: set[str],
        network_audit: dict[str, object],
        network_audit_sha256: str,
        artifacts: Mapping[str, Mapping[str, object]],
    ) -> None: ...

    def _verify_rights(self, document: dict[str, object]) -> None: ...


def _module() -> Producer:
    spec = importlib.util.spec_from_file_location(
        "build_production_authorization_candidates", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return cast(Producer, module)


def _set_digest(values: set[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(values)) + "\n").encode()).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _git(*args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        capture_output=True,
    ).stdout


def _exact_tree_blob(provenance: Provenance, relative_path: str) -> bytes:
    entry = provenance.input_git_entries[relative_path]
    mode, object_type, object_id = entry.split()
    observed_entry = _git(
        "ls-tree", provenance.source_tree_sha, "--", relative_path
    ).decode()
    assert observed_entry == (
        f"{mode} {object_type} {object_id}\t{relative_path}\n"
    )
    raw = _git("cat-file", "blob", object_id)
    assert hashlib.sha256(raw).hexdigest() == provenance.input_blob_sha256[
        relative_path
    ]
    return raw


def _build() -> CandidateResult:
    return _module().build_authorization_candidates(
        repository_root=ROOT,
        source_commit_sha=SOURCE_COMMIT_SHA,
    )


def _candidate_contents(result: CandidateResult) -> set[str]:
    return {
        content
        for candidate in result.candidates
        for content in candidate.allowed_content_sha256
    }


def _exact_json_document(result: CandidateResult, path: str) -> dict[str, object]:
    document = json.loads(_exact_tree_blob(result.provenance, path))
    assert isinstance(document, dict)
    return document


def _subject_artifacts_from_currentness(
    document: Mapping[str, object],
) -> dict[str, Mapping[str, object]]:
    rows = document["artifacts"]
    assert isinstance(rows, list)
    result: dict[str, Mapping[str, object]] = {}
    for raw in rows:
        assert isinstance(raw, dict)
        content = raw["content_sha256"]
        source_path = raw["exact_path"]
        source_url = raw["current_download_url"]
        assert isinstance(content, str)
        result[content] = {
            "content_sha256": content,
            "source_path": source_path,
            "source_url": source_url,
        }
    return result


def _pii_artifacts(document: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    rows = document["results"]
    assert isinstance(rows, list)
    result: dict[str, Mapping[str, object]] = {}
    for raw in rows:
        assert isinstance(raw, dict)
        content = raw["content_sha256"]
        assert isinstance(content, str)
        result[content] = {
            "content_sha256": content,
            "page_count": raw["pages_scanned"],
            "source_path": raw["source_path"],
        }
    return result


def _verify_exact_currentness(
    producer: Producer,
    result: CandidateResult,
    document: dict[str, object],
) -> None:
    audit_raw = _exact_tree_blob(result.provenance, CURRENTNESS_AUDIT_PATH)
    audit = json.loads(audit_raw)
    assert isinstance(audit, dict)
    producer._verify_currentness(
        document,
        final_contents=_candidate_contents(result),
        network_audit=audit,
        network_audit_sha256=hashlib.sha256(audit_raw).hexdigest(),
        artifacts=_subject_artifacts_from_currentness(
            _exact_json_document(result, CURRENTNESS_EVIDENCE_PATH)
        ),
    )


def _mutate_reader_blob(
    producer: Producer,
    monkeypatch: pytest.MonkeyPatch,
    *,
    path: str,
    mutation: Callable[[bytes], bytes],
) -> None:
    reader_type = cast(Any, producer)._ExactGitTreeReader
    original = reader_type.read_blob

    def read_blob(instance: object, current_path: str) -> bytes:
        raw = cast(bytes, original(instance, current_path))
        return mutation(raw) if current_path == path else raw

    monkeypatch.setattr(reader_type, "read_blob", read_blob)


def test_candidates_partition_the_frozen_production_set_exactly() -> None:
    producer = _module()
    assert producer.AUTHORIZATION_COUNT == AUTHORIZATION_COUNT
    assert producer.FINAL_CONTENT_COUNT == FINAL_CONTENT_COUNT
    assert producer.FINAL_SET_SHA256 == FINAL_SET_SHA256
    assert producer.PROFILE_MANIFEST_FINGERPRINT == PROFILE_MANIFEST_FINGERPRINT
    assert producer.PII_EVIDENCE_REFERENCE == PII_EVIDENCE_REFERENCE

    result = producer.build_authorization_candidates(
        repository_root=ROOT,
        source_commit_sha=SOURCE_COMMIT_SHA,
    )
    assert result.provenance.source_commit_sha == SOURCE_COMMIT_SHA
    assert result.provenance.source_tree_sha == SOURCE_TREE_SHA
    assert _git("rev-parse", f"{SOURCE_COMMIT_SHA}^{{tree}}").decode().strip() == (
        SOURCE_TREE_SHA
    )
    assert set(result.provenance.input_blob_sha256) == set(
        result.provenance.input_git_entries
    )

    contents = [
        content
        for candidate in result.candidates
        for content in candidate.allowed_content_sha256
    ]

    assert len(result.candidates) == AUTHORIZATION_COUNT
    assert len(contents) == len(set(contents)) == FINAL_CONTENT_COUNT
    assert _set_digest(set(contents)) == FINAL_SET_SHA256


def test_every_candidate_matches_placement_profile_scope_and_manifest() -> None:
    result = _build()
    placement = parse_release_scope_placement(
        _exact_tree_blob(result.provenance, PLACEMENT_PATH)
    )
    verified_document = json.loads(
        _exact_tree_blob(result.provenance, VERIFIED_PROFILES_PATH)
    )
    verified_profiles = {
        (profile["profile_id"], profile["profile_version"]): profile
        for profile in verified_document["profiles"]
    }
    candidate_by_content = {
        content: candidate
        for candidate in result.candidates
        for content in candidate.allowed_content_sha256
    }
    placement_contents = {entry.content_sha256 for entry in placement.placements}

    assert set(candidate_by_content) == placement_contents
    assert placement.profile_manifest_digest == PROFILE_MANIFEST_FINGERPRINT
    assert verified_document["profile_manifest_digest"] == (
        PROFILE_MANIFEST_FINGERPRINT
    )
    assert len(
        {scope_digest(candidate.scope) for candidate in result.candidates}
    ) == AUTHORIZATION_COUNT
    for entry in placement.placements:
        candidate = candidate_by_content[entry.content_sha256]
        profile = verified_profiles[(entry.profile_id, entry.profile_version)]
        assert candidate.manifest_digest == PROFILE_MANIFEST_FINGERPRINT
        assert candidate.profile_id == entry.profile_id
        assert candidate.profile_version == entry.profile_version
        assert candidate.profile_fingerprint == entry.profile_fingerprint
        assert scope_digest(candidate.scope) == scope_digest(entry.scope)
        assert profile["profile_fingerprint"] == entry.profile_fingerprint
        assert profile["scope"] == entry.scope.model_dump(mode="json")


def test_candidates_bind_the_pii_reference_byte_for_byte() -> None:
    result = _build()
    assert hashlib.sha256(
        _exact_tree_blob(result.provenance, PII_EVIDENCE_PATH)
    ).hexdigest() == PII_EVIDENCE_SHA256
    assert {
        candidate.pii_absence_evidence for candidate in result.candidates
    } == {PII_EVIDENCE_REFERENCE}


def test_another_commit_is_refused() -> None:
    with pytest.raises(ValueError, match="source_commit_sha"):
        _module().build_authorization_candidates(
            repository_root=ROOT,
            source_commit_sha=OTHER_COMMIT_SHA,
        )


def test_a_tree_object_cannot_be_used_as_the_source_commit() -> None:
    with pytest.raises(ValueError, match="source_commit_sha"):
        _module().build_authorization_candidates(
            repository_root=ROOT,
            source_commit_sha=SOURCE_TREE_SHA,
        )


def test_git_object_reads_disable_local_replace_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    producer = _module()
    actual_run = subprocess.run
    replace_guards: list[str | None] = []

    def observed_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        environment = kwargs.get("env")
        assert isinstance(environment, dict)
        replace_guards.append(environment.get("GIT_NO_REPLACE_OBJECTS"))
        return actual_run(*args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(subprocess, "run", observed_run)
    producer.build_authorization_candidates(
        repository_root=ROOT,
        source_commit_sha=SOURCE_COMMIT_SHA,
    )

    assert replace_guards
    assert set(replace_guards) == {"1"}


def test_official_source_path_cannot_escape_the_approved_zone() -> None:
    producer = _module()
    valid = "01_EDUSCOL_OFFICIEL/LYCEE/programme.pdf"
    assert producer._canonical_official_source_path(valid) == valid

    for invalid in (
        "01_EDUSCOL_OFFICIEL/../secret.pdf",
        "01_EDUSCOL_OFFICIEL//programme.pdf",
        "01_EDUSCOL_OFFICIEL\\programme.pdf",
        "/01_EDUSCOL_OFFICIEL/programme.pdf",
    ):
        with pytest.raises(ValueError, match="SOURCE_PATH"):
            producer._canonical_official_source_path(invalid)


def test_artifact_must_belong_to_the_placed_collection() -> None:
    with pytest.raises(ValueError, match="SUBJECT_RELEASE_MISMATCH"):
        _module()._require_artifact_collection(
            content_sha256="a" * 64,
            expected_collection="rag_nexus_maths_seconde_tc",
            actual_collection="rag_nexus_philo_terminale_tc",
        )


def test_cli_rejects_a_wrong_source_commit() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source-commit",
            "definitely-wrong",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": "packages/contracts/src:services/rag-pedago",
        },
    )

    assert completed.returncode != 0
    assert "source_commit_sha" in completed.stderr


@pytest.mark.parametrize(
    ("mutation_path", "mutated_value"),
    [
        (("evidence_kind",), "DECLARATIVE_PII_ASSERTION"),
        (("school_year",), "2025-2026"),
        (("corpus_manifest_sha256",), "0" * 64),
        (("summary", "pii_scan_coverage"), 0.5),
    ],
)
def test_pii_verifier_rejects_non_real_or_partial_evidence(
    mutation_path: tuple[str, ...], mutated_value: object
) -> None:
    producer = _module()
    result = _build()
    document = deepcopy(_exact_json_document(result, PII_EVIDENCE_PATH))
    target: dict[str, object] = document
    for key in mutation_path[:-1]:
        nested = target[key]
        assert isinstance(nested, dict)
        target = nested
    target[mutation_path[-1]] = mutated_value

    with pytest.raises(ValueError, match="PII_EVIDENCE_MISMATCH"):
        producer._verify_pii(
            document,
            final_contents=_candidate_contents(result),
            artifacts=_pii_artifacts(
                _exact_json_document(result, PII_EVIDENCE_PATH)
            ),
        )


@pytest.mark.parametrize(
    ("field", "mutated_value"),
    [
        ("characters_scanned", 0),
        ("pages_scanned", 0),
        ("evidence_sha256", "not-a-sha256"),
        ("source_path", "01_EDUSCOL_OFFICIEL/../escape.pdf"),
    ],
)
def test_pii_verifier_rejects_an_empty_or_unbound_scan_result(
    field: str, mutated_value: object
) -> None:
    producer = _module()
    result = _build()
    exact_document = _exact_json_document(result, PII_EVIDENCE_PATH)
    document = deepcopy(exact_document)
    rows = document["results"]
    assert isinstance(rows, list) and rows
    first = rows[0]
    assert isinstance(first, dict)
    first[field] = mutated_value

    with pytest.raises(ValueError, match="PII_EVIDENCE_MISMATCH"):
        producer._verify_pii(
            document,
            final_contents=_candidate_contents(result),
            artifacts=_pii_artifacts(exact_document),
        )


def test_pii_verifier_rejects_a_well_formed_but_false_evidence_digest() -> None:
    producer = _module()
    result = _build()
    exact_document = _exact_json_document(result, PII_EVIDENCE_PATH)
    document = deepcopy(exact_document)
    rows = document["results"]
    assert isinstance(rows, list) and rows
    first = rows[0]
    assert isinstance(first, dict)
    first["evidence_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="PII_EVIDENCE_MISMATCH"):
        producer._verify_pii(
            document,
            final_contents=_candidate_contents(result),
            artifacts=_pii_artifacts(exact_document),
        )


def test_pii_verifier_rejects_a_digest_valid_partial_page_scan() -> None:
    producer = _module()
    result = _build()
    exact_document = _exact_json_document(result, PII_EVIDENCE_PATH)
    document = deepcopy(exact_document)
    rows = document["results"]
    assert isinstance(rows, list) and rows
    first = rows[0]
    assert isinstance(first, dict)
    first["pages_scanned"] = 1
    core = {
        "content_sha256": first["content_sha256"],
        "pages_scanned": first["pages_scanned"],
        "characters_scanned": first["characters_scanned"],
        "status": first["status"],
        "pii_detected": first["pii_detected"],
    }
    first["evidence_sha256"] = hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    with pytest.raises(ValueError, match="PII_EVIDENCE_MISMATCH"):
        producer._verify_pii(
            document,
            final_contents=_candidate_contents(result),
            artifacts=_pii_artifacts(exact_document),
        )


@pytest.mark.parametrize(
    ("field", "mutated_value"),
    [
        ("evidence_kind", "DECLARATIVE_CURRENTNESS"),
        ("school_year", "2025-2026"),
    ],
)
def test_currentness_verifier_rejects_wrong_evidence_identity(
    field: str, mutated_value: object
) -> None:
    producer = _module()
    result = _build()
    document = deepcopy(_exact_json_document(result, CURRENTNESS_EVIDENCE_PATH))
    document[field] = mutated_value

    with pytest.raises(ValueError, match="CURRENTNESS_EVIDENCE_MISMATCH"):
        _verify_exact_currentness(producer, result, document)


def test_currentness_verifier_rejects_an_unapproved_download_domain() -> None:
    producer = _module()
    result = _build()
    document = deepcopy(_exact_json_document(result, CURRENTNESS_EVIDENCE_PATH))
    artifacts = document["artifacts"]
    assert isinstance(artifacts, list) and artifacts
    first = artifacts[0]
    assert isinstance(first, dict)
    first["current_download_url"] = "https://attacker.invalid/programme.pdf"

    with pytest.raises(ValueError, match="CURRENTNESS_EVIDENCE_MISMATCH"):
        _verify_exact_currentness(producer, result, document)


@pytest.mark.parametrize(
    ("field", "mutated_value"),
    [
        ("effective_currentness", "obsolete"),
        ("exact_path", "01_EDUSCOL_OFFICIEL/../escape.pdf"),
        (
            "current_download_url",
            "https://eduscol.education.gouv.fr/substituted-programme.pdf",
        ),
        (
            "current_source_listing_url",
            "https://eduscol.education.gouv.fr/substituted-listing",
        ),
    ],
)
def test_currentness_verifier_rejects_an_obsolete_or_substituted_source_fact(
    field: str, mutated_value: object
) -> None:
    producer = _module()
    result = _build()
    document = deepcopy(_exact_json_document(result, CURRENTNESS_EVIDENCE_PATH))
    rows = document["artifacts"]
    assert isinstance(rows, list) and rows
    first = rows[0]
    assert isinstance(first, dict)
    first[field] = mutated_value

    with pytest.raises(ValueError, match="CURRENTNESS_EVIDENCE_MISMATCH"):
        _verify_exact_currentness(producer, result, document)


def test_currentness_verifier_rejects_an_unbound_network_audit() -> None:
    producer = _module()
    result = _build()
    document = _exact_json_document(result, CURRENTNESS_EVIDENCE_PATH)
    audit_raw = _exact_tree_blob(result.provenance, CURRENTNESS_AUDIT_PATH)
    audit = json.loads(audit_raw)
    assert isinstance(audit, dict)

    with pytest.raises(ValueError, match="CURRENTNESS_EVIDENCE_MISMATCH"):
        producer._verify_currentness(
            document,
            final_contents=_candidate_contents(result),
            network_audit=audit,
            network_audit_sha256="0" * 64,
            artifacts=_subject_artifacts_from_currentness(document),
        )


def test_rights_verifier_rejects_a_relabelled_human_decision() -> None:
    producer = _module()
    result = _build()
    document = strict_yaml_mapping(
        _exact_tree_blob(result.provenance, RIGHTS_EVIDENCE_PATH),
        source=RIGHTS_EVIDENCE_PATH,
    )
    decisions = document["human_rights_decisions"]
    assert isinstance(decisions, dict)
    approval = decisions["eduscol_generic_approval"]
    assert isinstance(approval, dict)
    approval["decision_source"] = "SYNTHETIC_FALLBACK"

    with pytest.raises(ValueError, match="RIGHTS_EVIDENCE_MISMATCH"):
        producer._verify_rights(document)


def test_builder_rejects_a_mutated_aggregate_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    producer = _module()
    _mutate_reader_blob(
        producer,
        monkeypatch,
        path=AGGREGATE_PATH,
        mutation=lambda raw: raw + b" ",
    )

    with pytest.raises(ValueError, match="AGGREGATE_MISMATCH"):
        producer.build_authorization_candidates(
            repository_root=ROOT,
            source_commit_sha=SOURCE_COMMIT_SHA,
        )


def test_builder_rejects_a_mutated_profile_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    producer = _module()

    def mutate(raw: bytes) -> bytes:
        document = json.loads(raw)
        profiles = document["profiles"]
        assert isinstance(profiles, list) and profiles
        first = profiles[0]
        assert isinstance(first, dict)
        first["profile_fingerprint"] = "0" * 64
        return (
            json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
            + b"\n"
        )

    _mutate_reader_blob(
        producer,
        monkeypatch,
        path=VERIFIED_PROFILES_PATH,
        mutation=mutate,
    )

    with pytest.raises(ValueError, match="PROFILE_MISMATCH"):
        producer.build_authorization_candidates(
            repository_root=ROOT,
            source_commit_sha=SOURCE_COMMIT_SHA,
        )


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_builder_rejects_a_final_set_gap_or_extra(
    mutation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    producer = _module()

    def mutate(raw: bytes) -> bytes:
        values = raw.decode("ascii").splitlines()
        if mutation == "missing":
            values.pop()
        else:
            values.append("f" * 64)
        return ("\n".join(sorted(values)) + "\n").encode("ascii")

    _mutate_reader_blob(
        producer,
        monkeypatch,
        path=FINAL_SET_PATH,
        mutation=mutate,
    )

    with pytest.raises(ValueError, match="INVALID_FINAL_SET"):
        producer.build_authorization_candidates(
            repository_root=ROOT,
            source_commit_sha=SOURCE_COMMIT_SHA,
        )


def test_builder_rejects_an_overlapping_placement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    producer = _module()
    original = _git("show", f"{SOURCE_COMMIT_SHA}:{PLACEMENT_PATH}")
    duplicate = original.splitlines(keepends=True)[1]
    mutated = original + duplicate
    monkeypatch.setattr(
        cast(Any, producer),
        "RELEASE_SCOPE_PLACEMENT_SHA256",
        hashlib.sha256(mutated).hexdigest(),
    )
    _mutate_reader_blob(
        producer,
        monkeypatch,
        path=PLACEMENT_PATH,
        mutation=lambda _raw: mutated,
    )

    with pytest.raises(ValueError, match="repeats content_sha256"):
        producer.build_authorization_candidates(
            repository_root=ROOT,
            source_commit_sha=SOURCE_COMMIT_SHA,
        )


def test_materialized_outputs_are_canonical_and_fully_auditable() -> None:
    producer = _module()
    result = _build()
    outputs = producer.authorization_candidate_outputs(result)
    authorization_paths = {
        canonical_authorization_path(candidate.authorization_id)
        for candidate in result.candidates
    }
    matrix_path = "docs/reports/production_authorization_matrix_20260825.json"

    assert set(outputs) == authorization_paths | {matrix_path}
    for candidate in result.candidates:
        raw = outputs[canonical_authorization_path(candidate.authorization_id)]
        parsed = parse_scope_authorization_artifact(raw)
        assert isinstance(parsed, ScopeAuthorizationArtifactV2)
        assert parsed == candidate
        assert raw == candidate.canonical_bytes()

    matrix = json.loads(outputs[matrix_path])
    assert matrix["protocol_version"] == "NEXUS-PRODUCTION-AUTHORIZATION-MATRIX-V1"
    assert matrix["source_commit_sha"] == SOURCE_COMMIT_SHA
    assert matrix["source_tree_sha"] == SOURCE_TREE_SHA
    assert matrix["authorization_count"] == AUTHORIZATION_COUNT
    assert matrix["authorization_content_union"] == FINAL_CONTENT_COUNT
    assert matrix["authorization_overlap"] == 0
    assert matrix["authorization_gap"] == 0
    assert matrix["authorization_extra"] == 0
    assert matrix["authorization_union_sha256"] == FINAL_SET_SHA256
    assert len(matrix["authorizations"]) == AUTHORIZATION_COUNT
    assert len(matrix["input_blobs"]) == len(result.provenance.input_blob_sha256)
    matrix_contents: list[str] = []
    for row in matrix["authorizations"]:
        assert row["authorization_path"] in authorization_paths
        assert _is_sha256(row["authorization_digest"])
        assert _is_sha256(row["scope_digest"])
        assert _is_sha256(row["content_set_sha256"])
        assert row["rights_evidence_path"] == RIGHTS_EVIDENCE_PATH
        assert row["currentness_evidence_path"] == CURRENTNESS_EVIDENCE_PATH
        assert row["currentness_audit_path"] == CURRENTNESS_AUDIT_PATH
        assert row["pii_evidence_path"] == PII_EVIDENCE_PATH
        assert row["subject_release_path"] in result.provenance.input_blob_sha256
        assert row["allowed_content_sha256"] == sorted(
            row["allowed_content_sha256"]
        )
        assert len(row["allowed_content_sha256"]) == row["content_count"]
        assert _set_digest(set(row["allowed_content_sha256"])) == row[
            "content_set_sha256"
        ]
        matrix_contents.extend(row["allowed_content_sha256"])
    assert len(matrix_contents) == len(set(matrix_contents)) == FINAL_CONTENT_COUNT
    assert _set_digest(set(matrix_contents)) == FINAL_SET_SHA256


def test_write_replays_byte_identical_outputs(tmp_path: Path) -> None:
    producer = _module()
    result = _build()
    expected = producer.authorization_candidate_outputs(result)

    producer.write_authorization_candidates(result, output_root=tmp_path)
    first_replay = {
        path: (tmp_path / path).read_bytes() for path in sorted(expected)
    }
    producer.write_authorization_candidates(result, output_root=tmp_path)
    second_replay = {
        path: (tmp_path / path).read_bytes() for path in sorted(expected)
    }

    assert first_replay == second_replay == expected
    producer.check_authorization_candidates(result, output_root=tmp_path)


@pytest.mark.parametrize("mutation", ["missing", "modified", "extra"])
def test_check_rejects_missing_modified_or_extra_outputs(
    mutation: str, tmp_path: Path
) -> None:
    producer = _module()
    result = _build()
    producer.write_authorization_candidates(result, output_root=tmp_path)
    target = tmp_path / canonical_authorization_path(
        result.candidates[0].authorization_id
    )
    if mutation == "missing":
        target.unlink()
    elif mutation == "modified":
        target.write_bytes(b"{}\n")
    else:
        extra = tmp_path / "governance/authorizations/unexpected.json"
        extra.write_bytes(b"{}\n")

    with pytest.raises(ValueError, match="MATERIALIZATION_MISMATCH"):
        producer.check_authorization_candidates(result, output_root=tmp_path)


@pytest.mark.parametrize("ancestor", ["governance", "docs"])
def test_write_rejects_a_symlinked_output_ancestor(
    ancestor: str, tmp_path: Path
) -> None:
    producer = _module()
    result = _build()
    redirected = tmp_path / f"redirected-{ancestor}"
    redirected.mkdir()
    (tmp_path / ancestor).symlink_to(redirected, target_is_directory=True)

    with pytest.raises(ValueError, match="MATERIALIZATION_MISMATCH"):
        producer.write_authorization_candidates(result, output_root=tmp_path)
