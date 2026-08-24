"""Entrée publique scellée par un tree Git exact et sortie CLI atomique."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from nexus_contracts.authorization_set import VerifiedProfileFactV1
from nexus_contracts.ingestion import (
    CollectionProfile,
    collection_profile_fingerprint,
    profile_manifest_fingerprint,
)
from nexus_contracts.release_scope_placement import (
    produce_release_scope_placement_from_blobs,
)

from rag_pedago.governance.cli import main
from rag_pedago.governance.release_scope_placement import (
    ReleaseScopePlacementProducerError,
    _GitTreeReader,
    _parse_git_tree_entry,
    produce_release_scope_placement_from_git,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
MANIFEST = "d" * 64
MATRIX_PATH = "governance/profile-matrix.json"
PLACEMENTS_PATH = "governance/placements.json"
REGISTRY_PATH = "governance/release-registry.json"
CONTENTS_PATH = "governance/expected-contents.txt"
PROFILES_PATH = "governance/verified-profiles.json"
PROFILE_MANIFEST_PATH = "governance/profile-manifest.yml"
MATHS_PROFILE_PATH = "profiles/maths.yml"
FR_PROFILE_PATH = "profiles/francais.yml"
UNUSED_PROFILE_PATH = "profiles/unused.yml"


def _scope(collection: str) -> dict[str, Any]:
    return {
        "tenant": "libre_terminale",
        "collection": collection,
        "niveau": "terminale",
        "voie": "generale",
        "matiere": "mathematiques" if collection.endswith("maths") else "francais",
        "candidat": "libre",
        "audience": ["libre", "tous"],
        "visibility": "internal",
        "school_year": "2026-2027",
        "programme_version": "BOEN_test_v1",
    }


def _profile_document(collection: str, *, enabled: bool = True) -> dict[str, Any]:
    return {
        "profile_version": "v1",
        "enabled": enabled,
        "scope": _scope(collection),
        "title": f"Profil {collection}",
        "owner": "tests",
        "expected_topics": ["notion"],
        "expected_resource_types": ["cours"],
        "allowed_domains": ["education.gouv.fr"],
        "source_authority": "official",
        "search_cadence": "weekly",
        "max_queries_per_run": 1,
        "max_documents_per_run": 1,
        "max_chunk_size": 800,
        "chunk_overlap": 100,
        "min_source_confidence": 0.7,
        "min_scope_confidence": 0.7,
        "min_extraction_quality": 0.7,
    }


def _fact(collection: str) -> VerifiedProfileFactV1:
    profile = CollectionProfile.model_validate(_profile_document(collection))
    return VerifiedProfileFactV1(
        profile_id=collection,
        profile_version=profile.profile_version,
        profile_fingerprint=collection_profile_fingerprint(profile),
        scope=profile.scope,
    )


def _matrix() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, (content, collection, source) in enumerate(
        (
            (SHA_A, "collection_maths", MATHS_PROFILE_PATH),
            (SHA_B, "collection_francais", FR_PROFILE_PATH),
        ),
        start=1,
    ):
        rows.append(
            {
                "partition_id": f"P{index:02d}",
                "partition_kind": "EXACT_VERSIONED_RELEASE_PROFILE",
                "content_count": 1,
                "content_sha256": [content],
                "profile_decision_required": False,
                "evidence_sources": [source],
                "dimensions": {
                    name: {
                        "value": value,
                        "grounded": True,
                        "source_of_truth": source,
                    }
                    for name, value in _scope(collection).items()
                },
            }
        )
    return rows


def _placements() -> list[dict[str, str]]:
    return [
        {
            "content_sha256": SHA_A,
            "release_id": "release-a",
            "collection": "collection_maths",
            "profile_version": "v1",
        },
        {
            "content_sha256": SHA_B,
            "release_id": "release-a",
            "collection": "collection_francais",
            "profile_version": "v1",
        },
    ]


def _registry() -> dict[str, Any]:
    return {
        "registry_version": "1",
        "school_year": "2026-2027",
        "releases": [
            {
                "release_id": "release-a",
                "collections": ["collection_maths", "collection_francais"],
            }
        ],
    }


def _profile_manifest_document() -> dict[str, Any]:
    return {
        "manifest_version": "1",
        "provenance": "fixture exacte",
        "generated_at": "2026-08-23T00:00:00Z",
        "profiles": [
            {
                "collection": fact.profile_id,
                "profile_version": fact.profile_version,
                "fingerprint": fact.profile_fingerprint,
                "approved_by": "test-authority",
                "approved_at": "2026-08-23T00:00:00Z",
            }
            for fact in (_fact("collection_maths"), _fact("collection_francais"))
        ],
    }


def _profiles_document(manifest_digest: str = MANIFEST) -> dict[str, Any]:
    return {
        "profile_manifest_digest": manifest_digest,
        "profiles": [
            {
                **_fact("collection_maths").model_dump(mode="json"),
                "source_path": MATHS_PROFILE_PATH,
            },
            {
                **_fact("collection_francais").model_dump(mode="json"),
                "source_path": FR_PROFILE_PATH,
            },
        ],
    }


def _write(repo: Path, relative: str, raw: bytes) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def _json_bytes(document: Any) -> bytes:
    return (json.dumps(document, sort_keys=True, indent=2) + "\n").encode()


def _commit(repo: Path, message: str = "fixture") -> str:
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Nexus Tests",
            "-c",
            "user.email=tests@nexus.invalid",
            "commit",
            "-qm",
            message,
        ],
        cwd=repo,
        check=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repository"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    _write(repo, MATRIX_PATH, _json_bytes(_matrix()))
    _write(repo, PLACEMENTS_PATH, _json_bytes(_placements()))
    _write(repo, REGISTRY_PATH, _json_bytes(_registry()))
    _write(repo, CONTENTS_PATH, f"{SHA_A}\n{SHA_B}\n".encode())
    manifest_document = _profile_manifest_document()
    manifest_raw = yaml.safe_dump(manifest_document, sort_keys=True).encode()
    _write(repo, PROFILE_MANIFEST_PATH, manifest_raw)
    _write(
        repo,
        PROFILES_PATH,
        _json_bytes(_profiles_document(profile_manifest_fingerprint(manifest_document))),
    )
    _write(repo, MATHS_PROFILE_PATH, yaml.safe_dump(_profile_document("collection_maths")).encode())
    _write(repo, FR_PROFILE_PATH, yaml.safe_dump(_profile_document("collection_francais")).encode())
    return repo, _commit(repo)


def _produce(repo: Path, tree: str):
    return produce_release_scope_placement_from_git(
        repository_root=repo,
        source_tree_sha=tree,
        profile_proposal_matrix_path=MATRIX_PATH,
        accepted_placements_path=PLACEMENTS_PATH,
        release_registry_path=REGISTRY_PATH,
        expected_contents_path=CONTENTS_PATH,
        verified_profiles_path=PROFILES_PATH,
        profile_manifest_path=PROFILE_MANIFEST_PATH,
    )


def _cli_args(repo: Path, tree: str, output: Path) -> list[str]:
    return [
        "release-scope-placement",
        "--repository-root",
        str(repo),
        "--source-tree-sha",
        tree,
        "--profile-proposal-matrix",
        MATRIX_PATH,
        "--placements",
        PLACEMENTS_PATH,
        "--release-registry",
        REGISTRY_PATH,
        "--verified-profiles",
        PROFILES_PATH,
        "--profile-manifest",
        PROFILE_MANIFEST_PATH,
        "--expected-contents",
        CONTENTS_PATH,
        "--output",
        str(output),
    ]


def test_public_producer_reads_and_binds_only_exact_tree_blobs(tmp_path: Path) -> None:
    repo, tree = _repository(tmp_path)

    produced = _produce(repo, tree)

    assert [row.content_sha256 for row in produced.placement.placements] == [SHA_A, SHA_B]
    assert produced.placement.profile_manifest_digest == profile_manifest_fingerprint(
        _profile_manifest_document()
    )
    assert produced.provenance.source_tree_sha == tree
    assert produced.verified_profile_facts == (
        _fact("collection_francais"),
        _fact("collection_maths"),
    )
    expected_inputs = {
        MATRIX_PATH,
        PLACEMENTS_PATH,
        REGISTRY_PATH,
        CONTENTS_PATH,
        PROFILES_PATH,
        PROFILE_MANIFEST_PATH,
        MATHS_PROFILE_PATH,
        FR_PROFILE_PATH,
    }
    assert set(produced.provenance.input_blob_sha256) == expected_inputs
    assert set(produced.provenance.input_git_entries) == expected_inputs
    assert all(
        entry.startswith("100644 blob ") for entry in produced.provenance.input_git_entries.values()
    )


def test_service_git_wrapper_matches_shared_frozen_blob_verifier(tmp_path: Path) -> None:
    repo, tree = _repository(tmp_path)
    paths = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "-z", tree],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout.rstrip(b"\0").split(b"\0")
    blobs = {
        path.decode(): subprocess.run(
            ["git", "show", f"{tree}:{path.decode()}"],
            cwd=repo,
            check=True,
            capture_output=True,
        ).stdout
        for path in paths
    }

    shared = produce_release_scope_placement_from_blobs(
        source_blobs=blobs,
        profile_proposal_matrix_path=MATRIX_PATH,
        accepted_placements_path=PLACEMENTS_PATH,
        release_registry_path=REGISTRY_PATH,
        expected_contents_path=CONTENTS_PATH,
        verified_profiles_path=PROFILES_PATH,
        profile_manifest_path=PROFILE_MANIFEST_PATH,
    )
    service = _produce(repo, tree)

    assert shared.placement == service.placement
    assert shared.verified_profile_facts == service.verified_profile_facts
    assert shared.input_blob_sha256 == service.provenance.input_blob_sha256


def test_every_verified_profile_fact_requires_exact_tree_source(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    profiles = _profiles_document(profile_manifest_fingerprint(_profile_manifest_document()))
    profiles["profiles"][0].pop("source_path")
    _write(repo, PROFILES_PATH, _json_bytes(profiles))
    tree = _commit(repo, "missing profile source")

    with pytest.raises(ReleaseScopePlacementProducerError, match="MISSING_PROFILE_SOURCE"):
        _produce(repo, tree)


def test_unused_manifest_profile_with_exact_tree_source_is_proven_and_bound(
    tmp_path: Path,
) -> None:
    repo, _ = _repository(tmp_path)
    unused_document = _profile_document("collection_unused")
    unused_profile = CollectionProfile.model_validate(unused_document)
    unused_fact = VerifiedProfileFactV1(
        profile_id=unused_profile.scope.collection,
        profile_version=unused_profile.profile_version,
        profile_fingerprint=collection_profile_fingerprint(unused_profile),
        scope=unused_profile.scope,
    )
    manifest = _profile_manifest_document()
    manifest["profiles"].append(
        {
            "collection": unused_fact.profile_id,
            "profile_version": unused_fact.profile_version,
            "fingerprint": unused_fact.profile_fingerprint,
            "approved_by": "test-authority",
            "approved_at": "2026-08-23T00:00:00Z",
        }
    )
    profile_sources = (MATHS_PROFILE_PATH, FR_PROFILE_PATH)
    profiles = _profiles_document(profile_manifest_fingerprint(manifest))
    for record, source_path in zip(profiles["profiles"], profile_sources, strict=True):
        record["source_path"] = source_path
    profiles["profiles"].append(
        {**unused_fact.model_dump(mode="json"), "source_path": UNUSED_PROFILE_PATH}
    )
    _write(repo, PROFILE_MANIFEST_PATH, yaml.safe_dump(manifest, sort_keys=True).encode())
    _write(repo, PROFILES_PATH, _json_bytes(profiles))
    _write(repo, UNUSED_PROFILE_PATH, yaml.safe_dump(unused_document).encode())
    tree = _commit(repo, "unused profile proved")

    produced = _produce(repo, tree)

    assert UNUSED_PROFILE_PATH in produced.provenance.input_blob_sha256


def test_verified_fact_unrelated_source_is_refused(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    profiles = _profiles_document(profile_manifest_fingerprint(_profile_manifest_document()))
    profiles["profiles"][0]["source_path"] = UNUSED_PROFILE_PATH
    profiles["profiles"][1]["source_path"] = FR_PROFILE_PATH
    _write(repo, PROFILES_PATH, _json_bytes(profiles))
    _write(
        repo,
        UNUSED_PROFILE_PATH,
        yaml.safe_dump(_profile_document("collection_unrelated")).encode(),
    )
    tree = _commit(repo, "unrelated profile source")

    with pytest.raises(ReleaseScopePlacementProducerError, match="PROFILE_SOURCE_MISMATCH"):
        _produce(repo, tree)


def test_matrix_cannot_substitute_an_identical_unbound_profile_source(
    tmp_path: Path,
) -> None:
    repo, _ = _repository(tmp_path)
    substitute = "profiles/maths-copy.yml"
    matrix = _matrix()
    matrix[0]["evidence_sources"] = [substitute]
    for dimension in matrix[0]["dimensions"].values():
        dimension["source_of_truth"] = substitute
    _write(repo, MATRIX_PATH, _json_bytes(matrix))
    _write(
        repo,
        substitute,
        yaml.safe_dump(_profile_document("collection_maths")).encode(),
    )
    tree = _commit(repo, "unbound profile copy")

    with pytest.raises(ReleaseScopePlacementProducerError, match="MATRIX_PROFILE_SOURCE_MISMATCH"):
        _produce(repo, tree)


def test_provenance_binds_every_declared_evidence_blob(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    support_path = "proofs/versioned-support.json"
    _write(repo, support_path, b'{"decision":"accepted"}\n')
    matrix = _matrix()
    matrix[0]["evidence_sources"].append(support_path)
    _write(repo, MATRIX_PATH, _json_bytes(matrix))
    tree = _commit(repo, "additional evidence")

    produced = _produce(repo, tree)

    assert (
        produced.provenance.input_blob_sha256[support_path]
        == hashlib.sha256(b'{"decision":"accepted"}\n').hexdigest()
    )


def test_dirty_tracked_replacement_cannot_change_exact_tree_result(tmp_path: Path) -> None:
    repo, tree = _repository(tmp_path)
    before = _produce(repo, tree)
    _write(repo, PLACEMENTS_PATH, b"[]\n")
    _write(repo, REGISTRY_PATH, b"{}\n")
    _write(
        repo,
        MATHS_PROFILE_PATH,
        yaml.safe_dump(_profile_document("collection_maths", enabled=False)).encode(),
    )

    after = _produce(repo, tree)

    assert after == before


def test_exact_current_matrix_still_refuses_thirteen_partitions_fifty_six_contents(
    tmp_path: Path,
) -> None:
    repo, _ = _repository(tmp_path)
    root = Path(__file__).resolve().parents[3]
    _write(
        repo,
        MATRIX_PATH,
        (root / "docs/reports/proposed_production_profile_matrix_20260823.json").read_bytes(),
    )
    _write(
        repo,
        CONTENTS_PATH,
        (root / "docs/reports/final_authority_required_set_20260823.txt").read_bytes(),
    )
    _write(
        repo,
        REGISTRY_PATH,
        (
            root / "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json"
        ).read_bytes(),
    )
    _write(repo, PLACEMENTS_PATH, b"[]\n")
    tree = _commit(repo, "current matrix")

    with pytest.raises(
        ReleaseScopePlacementProducerError,
        match="PROFILE_DECISION_REQUIRED: 13 partitions / 56 contents",
    ):
        _produce(repo, tree)


def test_symlink_and_untracked_substitution_cannot_change_tree_bytes(tmp_path: Path) -> None:
    repo, tree = _repository(tmp_path)
    matrix_path = repo / MATRIX_PATH
    matrix_path.unlink()
    fabricated = repo / "untracked-matrix.json"
    fabricated.write_text("[]\n", encoding="utf-8")
    matrix_path.symlink_to(fabricated)

    assert _produce(repo, tree).placement.placements


def test_exact_tree_reader_refuses_tracked_symlink_blob(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    profile_path = repo / MATHS_PROFILE_PATH
    profile_path.unlink()
    profile_path.symlink_to("maths-target.yml")
    tree = _commit(repo, "tracked profile symlink")
    reader = _GitTreeReader(repository_root=repo, source_tree_sha=tree)

    with pytest.raises(
        ReleaseScopePlacementProducerError,
        match="INVALID_GIT_TREE_ENTRY: .*mode 120000",
    ):
        reader.read_blob(MATHS_PROFILE_PATH)


def test_git_tree_entry_parser_is_nul_safe_for_unusual_literal_path() -> None:
    path = "profiles/unusual\tline\né.yml"
    object_id = "a" * 40

    entry = _parse_git_tree_entry(
        f"100644 blob {object_id}\t{path}\0".encode(),
        expected_path=path,
    )

    assert entry.mode == "100644"
    assert entry.object_type == "blob"
    assert entry.object_id == object_id
    assert entry.path == path


def test_exact_tree_reader_uses_unusual_governed_path_literally(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    support_path = "proofs/unusual\tline\né.json"
    matrix = _matrix()
    matrix[0]["evidence_sources"].append(support_path)
    _write(repo, MATRIX_PATH, _json_bytes(matrix))
    _write(repo, support_path, b'{"decision":"accepted"}\n')
    tree = _commit(repo, "unusual literal evidence path")

    produced = _produce(repo, tree)

    assert support_path in produced.provenance.input_git_entries


@pytest.mark.parametrize(
    ("raw", "detail"),
    [
        (f"120000 blob {'a' * 40}\tprofiles/source.yml\0".encode(), "mode 120000"),
        (f"100755 blob {'a' * 40}\tprofiles/source.yml\0".encode(), "mode 100755"),
        (f"040000 tree {'a' * 40}\tprofiles/source.yml\0".encode(), "type tree"),
        (f"160000 commit {'a' * 40}\tprofiles/source.yml\0".encode(), "type commit"),
    ],
)
def test_git_tree_entry_parser_refuses_non_regular_data_entries(
    raw: bytes,
    detail: str,
) -> None:
    with pytest.raises(
        ReleaseScopePlacementProducerError,
        match=rf"INVALID_GIT_TREE_ENTRY: .*{detail}",
    ):
        _parse_git_tree_entry(raw, expected_path="profiles/source.yml")


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        f"100644 blob {'a' * 40}\tprofiles/source.yml".encode(),
        (
            f"100644 blob {'a' * 40}\tprofiles/source.yml\0"
            f"100644 blob {'b' * 40}\tprofiles/source.yml\0"
        ).encode(),
        f"100644 blob {'a' * 40}\tprofiles/other.yml\0".encode(),
        f"100644 blob {'z' * 40}\tprofiles/source.yml\0".encode(),
    ],
)
def test_git_tree_entry_parser_refuses_missing_ambiguous_or_mismatched_entry(
    raw: bytes,
) -> None:
    with pytest.raises(ReleaseScopePlacementProducerError, match="INVALID_GIT_TREE_ENTRY"):
        _parse_git_tree_entry(raw, expected_path="profiles/source.yml")


def test_matrix_is_mandatory_in_public_api_and_cli(tmp_path: Path) -> None:
    parameter = inspect.signature(produce_release_scope_placement_from_git).parameters[
        "profile_proposal_matrix_path"
    ]
    assert parameter.default is inspect.Parameter.empty

    repo, tree = _repository(tmp_path)
    args = _cli_args(repo, tree, tmp_path / "placement.jsonl")
    index = args.index("--profile-proposal-matrix")
    del args[index : index + 2]
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


@pytest.mark.parametrize(
    ("relative_path", "needle"),
    [
        (MATRIX_PATH, '"grounded": true'),
        (PLACEMENTS_PATH, f'"content_sha256": "{SHA_A}"'),
        (REGISTRY_PATH, '"release_id": "release-a"'),
        (PROFILES_PATH, '"profile_id": "collection_maths"'),
    ],
)
def test_every_governance_json_recursively_rejects_duplicate_keys(
    tmp_path: Path, relative_path: str, needle: str
) -> None:
    repo, _ = _repository(tmp_path)
    path = repo / relative_path
    raw = path.read_text(encoding="utf-8")
    key, value = needle.split(": ", maxsplit=1)
    path.write_text(raw.replace(needle, f"{key}: {value}, {needle}", 1), encoding="utf-8")
    tree = _commit(repo, "duplicate key")

    with pytest.raises(ReleaseScopePlacementProducerError, match="DUPLICATE_JSON_KEY"):
        _produce(repo, tree)


def test_unrelated_tracked_file_cannot_ground_profile_dimensions(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    proof = "proofs/unrelated.txt"
    _write(repo, proof, b"unrelated\n")
    matrix = _matrix()
    matrix[0]["evidence_sources"] = [proof]
    for dimension in matrix[0]["dimensions"].values():
        dimension["source_of_truth"] = proof
    _write(repo, MATRIX_PATH, _json_bytes(matrix))
    tree = _commit(repo, "unrelated proof")

    with pytest.raises(ReleaseScopePlacementProducerError, match="MATRIX_PROFILE_SOURCE_MISMATCH"):
        _produce(repo, tree)


def test_fabricated_verified_profile_fact_is_refused(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    manifest = _profile_manifest_document()
    manifest["profiles"][0]["fingerprint"] = "f" * 64
    manifest_raw = yaml.safe_dump(manifest, sort_keys=True).encode()
    _write(repo, PROFILE_MANIFEST_PATH, manifest_raw)
    profiles = _profiles_document(profile_manifest_fingerprint(manifest))
    profiles["profiles"][0]["profile_fingerprint"] = "f" * 64
    _write(repo, PROFILES_PATH, _json_bytes(profiles))
    tree = _commit(repo, "fabricated fact")

    with pytest.raises(ReleaseScopePlacementProducerError, match="PROFILE_SOURCE_MISMATCH"):
        _produce(repo, tree)


def test_manifest_missing_approval_is_refused_before_projection(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    manifest = _profile_manifest_document()
    manifest["profiles"][0].pop("approved_by")
    _write(repo, PROFILE_MANIFEST_PATH, yaml.safe_dump(manifest, sort_keys=True).encode())
    _write(
        repo,
        PROFILES_PATH,
        _json_bytes(_profiles_document(profile_manifest_fingerprint(manifest))),
    )
    tree = _commit(repo, "missing approval")

    with pytest.raises(ReleaseScopePlacementProducerError, match="approved_by"):
        _produce(repo, tree)


def test_duplicate_manifest_yaml_key_is_refused(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    path = repo / PROFILE_MANIFEST_PATH
    raw = path.read_text(encoding="utf-8")
    path.write_text(
        raw.replace(
            "provenance: fixture exacte", "provenance: fixture exacte\nprovenance: fixture exacte"
        ),
        encoding="utf-8",
    )
    tree = _commit(repo, "duplicate manifest key")

    with pytest.raises(ReleaseScopePlacementProducerError, match="duplicate"):
        _produce(repo, tree)


def test_duplicate_profile_yaml_key_is_refused(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    path = repo / MATHS_PROFILE_PATH
    raw = path.read_text(encoding="utf-8")
    path.write_text(
        raw.replace("enabled: true", "enabled: true\nenabled: true"),
        encoding="utf-8",
    )
    tree = _commit(repo, "duplicate profile key")

    with pytest.raises(ReleaseScopePlacementProducerError, match="duplicate"):
        _produce(repo, tree)


def test_noncanonical_exact_tree_profile_version_is_refused(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    profile = _profile_document("collection_maths")
    profile["profile_version"] = "bad version"
    _write(repo, MATHS_PROFILE_PATH, yaml.safe_dump(profile).encode())
    tree = _commit(repo, "noncanonical profile version")

    with pytest.raises(
        ReleaseScopePlacementProducerError,
        match="INVALID_PROFILE_SOURCE: .*profile_version",
    ):
        _produce(repo, tree)


def test_cli_refuses_symlink_output_and_input_alias(tmp_path: Path) -> None:
    repo, tree = _repository(tmp_path)
    target = tmp_path / "target.jsonl"
    target.write_text("unchanged\n", encoding="utf-8")
    symlink = tmp_path / "output.jsonl"
    symlink.symlink_to(target)

    assert main(_cli_args(repo, tree, symlink)) == 1
    assert target.read_text(encoding="utf-8") == "unchanged\n"
    for input_path in (
        MATRIX_PATH,
        PLACEMENTS_PATH,
        REGISTRY_PATH,
        CONTENTS_PATH,
        PROFILES_PATH,
        PROFILE_MANIFEST_PATH,
        MATHS_PROFILE_PATH,
        FR_PROFILE_PATH,
    ):
        assert main(_cli_args(repo, tree, repo / input_path)) == 1


def test_cli_refuses_parent_symlink_and_hardlink_aliases(tmp_path: Path) -> None:
    repo, tree = _repository(tmp_path)
    parent_alias = tmp_path / "governance-alias"
    parent_alias.symlink_to(repo / "governance", target_is_directory=True)
    assert main(_cli_args(repo, tree, parent_alias / "profile-matrix.json")) == 1

    hardlink = tmp_path / "matrix-hardlink.json"
    hardlink.hardlink_to(repo / PLACEMENTS_PATH)
    assert main(_cli_args(repo, tree, hardlink)) == 1


def test_cli_refuses_unrelated_symlink_parent_component(tmp_path: Path) -> None:
    repo, tree = _repository(tmp_path)
    real_parent = tmp_path / "real-output"
    real_parent.mkdir()
    parent_alias = tmp_path / "output-alias"
    parent_alias.symlink_to(real_parent, target_is_directory=True)

    assert main(_cli_args(repo, tree, parent_alias / "placement.jsonl")) == 1
    assert not (real_parent / "placement.jsonl").exists()


def test_cli_parent_component_swap_cannot_redirect_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, tree = _repository(tmp_path)
    safe_root = tmp_path / "safe-root"
    safe_parent = safe_root / "leaf"
    safe_parent.mkdir(parents=True)
    attacker_root = tmp_path / "attacker-root"
    attacker_parent = attacker_root / "leaf"
    attacker_parent.mkdir(parents=True)
    parked_root = tmp_path / "parked-root"
    real_open = os.open
    swapped = False

    def swap_then_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if not swapped and Path(path) == Path(safe_root.name):
            safe_root.rename(parked_root)
            safe_root.symlink_to(attacker_root, target_is_directory=True)
            swapped = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr("rag_pedago.governance.cli.os.open", swap_then_open)
    assert main(_cli_args(repo, tree, safe_parent / "placement.jsonl")) == 1
    assert not (attacker_parent / "placement.jsonl").exists()
    assert not (parked_root / "leaf" / "placement.jsonl").exists()


def test_cli_component_swap_before_parent_stat_cannot_redirect_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, tree = _repository(tmp_path)
    safe_root = tmp_path / "prestat-safe-root"
    safe_parent = safe_root / "leaf"
    safe_parent.mkdir(parents=True)
    attacker_root = tmp_path / "prestat-attacker-root"
    attacker_parent = attacker_root / "leaf"
    attacker_parent.mkdir(parents=True)
    parked_root = tmp_path / "prestat-parked-root"
    real_stat = os.stat
    swapped = False

    def swap_then_stat(
        path: str | os.PathLike[str],
        *,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> os.stat_result:
        nonlocal swapped
        if not swapped and Path(path) == safe_parent and not follow_symlinks:
            safe_root.rename(parked_root)
            safe_root.symlink_to(attacker_root, target_is_directory=True)
            swapped = True
        return real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    monkeypatch.setattr("rag_pedago.governance.cli.os.stat", swap_then_stat)
    assert main(_cli_args(repo, tree, safe_parent / "placement.jsonl")) == 1
    assert not (attacker_parent / "placement.jsonl").exists()
    assert not (parked_root / "leaf" / "placement.jsonl").exists()


def test_cli_validation_failure_creates_no_output(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    profiles = _profiles_document("0" * 64)
    _write(repo, PROFILES_PATH, _json_bytes(profiles))
    tree = _commit(repo, "bad manifest identity")
    output = tmp_path / "must-not-exist.jsonl"

    assert main(_cli_args(repo, tree, output)) == 1
    assert not output.exists()


def test_cli_atomic_write_failure_preserves_existing_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, tree = _repository(tmp_path)
    output = tmp_path / "placement.jsonl"
    output.write_text("previous\n", encoding="utf-8")

    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("induced replace failure")

    monkeypatch.setattr("rag_pedago.governance.cli.os.replace", fail_replace)
    assert main(_cli_args(repo, tree, output)) == 1
    assert output.read_text(encoding="utf-8") == "previous\n"
    assert list(tmp_path.glob(".placement.jsonl.*.tmp")) == []
