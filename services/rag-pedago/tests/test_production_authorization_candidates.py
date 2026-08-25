"""Contrat des candidats d'autorisation production 2026-2027."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Protocol, cast

from nexus_contracts import (
    ScopeAuthorizationArtifactV2,
    parse_release_scope_placement,
    scope_digest,
)

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "services"
    / "rag-pedago"
    / "scripts"
    / "build_production_authorization_candidates.py"
)
PLACEMENT_PATH = ROOT / "docs/reports/release_scope_placement_20260825.jsonl"
VERIFIED_PROFILES_PATH = (
    ROOT / "docs/reports/verified_production_profiles_20260825.json"
)

AUTHORIZATION_COUNT = 18
FINAL_CONTENT_COUNT = 26
FINAL_SET_SHA256 = "fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0"
PROFILE_MANIFEST_FINGERPRINT = (
    "57d532ca0c80f0e70218e74902f1d47a4ca9f21d7e6bafa209f6f89426125b6c"
)


class Producer(Protocol):
    AUTHORIZATION_COUNT: int
    FINAL_CONTENT_COUNT: int
    FINAL_SET_SHA256: str
    PROFILE_MANIFEST_FINGERPRINT: str

    def build_authorization_candidates(
        self,
    ) -> tuple[ScopeAuthorizationArtifactV2, ...]: ...


def _module() -> Producer:
    spec = importlib.util.spec_from_file_location(
        "build_production_authorization_candidates", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(Producer, module)


def _set_digest(values: set[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(values)) + "\n").encode()).hexdigest()


def test_candidates_partition_the_frozen_production_set_exactly() -> None:
    producer = _module()
    assert producer.AUTHORIZATION_COUNT == AUTHORIZATION_COUNT
    assert producer.FINAL_CONTENT_COUNT == FINAL_CONTENT_COUNT
    assert producer.FINAL_SET_SHA256 == FINAL_SET_SHA256
    assert producer.PROFILE_MANIFEST_FINGERPRINT == PROFILE_MANIFEST_FINGERPRINT

    candidates = producer.build_authorization_candidates()
    contents = [
        content
        for candidate in candidates
        for content in candidate.allowed_content_sha256
    ]

    assert len(candidates) == AUTHORIZATION_COUNT
    assert len(contents) == len(set(contents)) == FINAL_CONTENT_COUNT
    assert _set_digest(set(contents)) == FINAL_SET_SHA256


def test_every_candidate_matches_placement_profile_scope_and_manifest() -> None:
    candidates = _module().build_authorization_candidates()
    placement = parse_release_scope_placement(PLACEMENT_PATH.read_bytes())
    verified_document = json.loads(VERIFIED_PROFILES_PATH.read_text(encoding="utf-8"))
    verified_profiles = {
        (profile["profile_id"], profile["profile_version"]): profile
        for profile in verified_document["profiles"]
    }
    candidate_by_content = {
        content: candidate
        for candidate in candidates
        for content in candidate.allowed_content_sha256
    }

    assert verified_document["profile_manifest_digest"] == (
        PROFILE_MANIFEST_FINGERPRINT
    )
    assert len({scope_digest(candidate.scope) for candidate in candidates}) == (
        AUTHORIZATION_COUNT
    )
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
