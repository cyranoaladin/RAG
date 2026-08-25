"""Contrat exact du bundle de release des profils production 2026-2027."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Protocol, cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "services"
    / "rag-pedago"
    / "scripts"
    / "build_production_profile_release.py"
)
RELEASE_ROOT = (
    ROOT
    / "services"
    / "rag-pedago"
    / "data"
    / "releases"
    / "prerentree_2026_2027"
    / "profile_gate"
)
AGGREGATE = RELEASE_ROOT / "production-profile-gate.release.json"
BINDINGS = RELEASE_ROOT / "authority_bindings.json"
REGISTRY = RELEASE_ROOT.parent / "release-registry.json"
FINAL_MATRIX = ROOT / "docs/reports/final_production_profile_matrix_20260825.json"
PROFILE_MANIFEST = ROOT / "services/rag-engine/configs/ingestion_manifest.yml"

FINAL_SET_SHA256 = "fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0"
PROFILE_MANIFEST_FINGERPRINT = (
    "57d532ca0c80f0e70218e74902f1d47a4ca9f21d7e6bafa209f6f89426125b6c"
)


class Builder(Protocol):
    CANONICAL_EMBEDDING_MODEL: str
    CANONICAL_EMBEDDING_REVISION: str

    def canonical_json_bytes(self, value: object) -> bytes: ...

    def validate_pdf_mirror(
        self, *, pdf_root: Path, content_sha256: list[str]
    ) -> dict[str, Path]: ...

    def validate_authority_bindings(
        self,
        *,
        repository_root: Path,
        bindings: dict[str, Any],
        aggregate: dict[str, Any],
    ) -> None: ...

    def stable_release_order(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]: ...

    def require_canonical_token_counter(self, token_counter: object) -> None: ...


def _module() -> Builder:
    spec = importlib.util.spec_from_file_location(
        "build_production_profile_release", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(Builder, module)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _final_set() -> set[str]:
    return {
        content
        for row in _load(FINAL_MATRIX)
        for content in row["content_sha256"]
    }


def _set_digest(values: set[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(values)) + "\n").encode()).hexdigest()


def test_final_input_is_exactly_the_frozen_twenty_six() -> None:
    final_set = _final_set()
    assert len(final_set) == 26
    assert _set_digest(final_set) == FINAL_SET_SHA256


def test_registered_release_is_the_only_active_release_and_exact() -> None:
    registry = _load(REGISTRY)
    assert registry["registry_version"] == "1"
    assert registry["school_year"] == "2026-2027"
    assert len(registry["releases"]) == 1
    entry = registry["releases"][0]
    assert entry["release_id"] == "production-profile-gate-2026-2027-v1"
    assert entry["release_kind"] == "MULTILEVEL_AGGREGATE_RELEASE_V1"
    assert entry["manifest_path"] == (
        "profile_gate/production-profile-gate.release.json"
    )
    assert len(entry["collections"]) == 18
    assert entry["expected_manifest_sha256"] == _sha256(AGGREGATE)


def test_aggregate_covers_exactly_26_contents_and_18_profiles() -> None:
    aggregate = _load(AGGREGATE)
    assert aggregate["release_kind"] == "MULTILEVEL_AGGREGATE_RELEASE_V1"
    assert aggregate["release_id"] == "production-profile-gate-2026-2027-v1"
    assert aggregate["expected_counts"]["artifacts"] == 26
    assert len(aggregate["subjects"]) == 18
    assert aggregate["authorities"]["profile_manifest_sha256"] == (
        PROFILE_MANIFEST_FINGERPRINT
    )

    contents: set[str] = set()
    collections: set[str] = set()
    for subject in aggregate["subjects"]:
        subject_path = RELEASE_ROOT / subject["path"]
        assert subject["sha256"] == _sha256(subject_path)
        document = _load(subject_path)
        collections.add(document["collection"])
        for artifact in document["artifacts"]:
            assert artifact["content_sha256"] not in contents
            contents.add(artifact["content_sha256"])
            assert artifact["chunks"]
            assert {
                page
                for chunk in artifact["chunks"]
                for page in range(chunk["page_start"], chunk["page_end"] + 1)
            } == set(range(1, artifact["page_count"] + 1))
    assert contents == _final_set()
    assert len(collections) == 18


def test_every_authority_is_named_path_bound_and_digest_checked() -> None:
    builder = _module()
    bindings = _load(BINDINGS)
    aggregate = _load(AGGREGATE)
    builder.validate_authority_bindings(
        repository_root=ROOT,
        bindings=bindings,
        aggregate=aggregate,
    )
    assert bindings["profile_manifest_fingerprint"] == (
        PROFILE_MANIFEST_FINGERPRINT
    )
    assert bindings["profile_manifest_file_sha256"] == _sha256(PROFILE_MANIFEST)
    assert set(bindings["bindings"]) == set(aggregate["authorities"])


def test_any_authority_binding_mutation_is_refused() -> None:
    builder = _module()
    bindings = _load(BINDINGS)
    aggregate = _load(AGGREGATE)
    for name in sorted(bindings["bindings"]):
        mutated = copy.deepcopy(bindings)
        mutated["bindings"][name]["file_sha256"] = "0" * 64
        with pytest.raises(ValueError, match="digest"):
            builder.validate_authority_bindings(
                repository_root=ROOT,
                bindings=mutated,
                aggregate=aggregate,
            )


def test_pdf_mirror_refuses_missing_and_digest_drift(tmp_path: Path) -> None:
    builder = _module()
    content = "a" * 64
    with pytest.raises(ValueError, match="missing"):
        builder.validate_pdf_mirror(pdf_root=tmp_path, content_sha256=[content])
    (tmp_path / f"{content}.pdf").write_bytes(b"not the declared content")
    with pytest.raises(ValueError, match="digest"):
        builder.validate_pdf_mirror(pdf_root=tmp_path, content_sha256=[content])


def test_release_order_is_stable_and_duplicate_content_is_refused() -> None:
    builder = _module()
    rows = [
        {"collection": "z", "content_sha256": "b" * 64},
        {"collection": "a", "content_sha256": "c" * 64},
        {"collection": "a", "content_sha256": "a" * 64},
    ]
    assert builder.stable_release_order(rows) == [rows[2], rows[1], rows[0]]
    with pytest.raises(ValueError, match="duplicate"):
        builder.stable_release_order([rows[0], copy.deepcopy(rows[0])])


def test_noncanonical_e5_counter_is_refused() -> None:
    builder = _module()
    impostor = type(
        "Counter",
        (),
        {
            "model_id": builder.CANONICAL_EMBEDDING_MODEL,
            "model_revision": "mutable-main",
            "max_sequence_length": 512,
            "passage_token_count": lambda _self, _text: 1,
        },
    )()
    with pytest.raises(ValueError, match="revision"):
        builder.require_canonical_token_counter(impostor)


def test_preflight_proves_real_e5_bounds_and_no_empty_page() -> None:
    preflight_path = Path(
        _load(BINDINGS)["bindings"]["preflight_evidence_sha256"]["path"]
    )
    preflight = _load(ROOT / preflight_path)
    assert preflight["model_id"] == "intfloat/multilingual-e5-large"
    assert preflight["model_revision"] == (
        "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"
    )
    assert preflight["counts"]["artifacts"] == 26
    assert preflight["counts"]["empty_pages"] == 0
    assert preflight["counts"]["empty_chunks"] == 0
    assert preflight["counts"]["oversized_chunks"] == 0
    assert max(
        chunk["token_count"]
        for artifact in preflight["artifacts"]
        for chunk in artifact["chunks"]
    ) <= 384
