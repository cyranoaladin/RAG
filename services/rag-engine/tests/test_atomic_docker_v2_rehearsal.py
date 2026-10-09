from __future__ import annotations

import hashlib
import inspect
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import atomic_docker_v2_rehearsal as rehearsal  # noqa: E402
import atomic_docker_v2_rehearsal_fixture as fixture  # noqa: E402
from nexus_contracts.authorization_set import parse_authorization_set  # noqa: E402
from nexus_contracts.production_readiness import (  # noqa: E402
    parse_production_readiness_trust_anchor,
    verify_production_readiness_manifest_v2,
)


def test_project_name_is_unique_rehearsal_namespace() -> None:
    name = "nexus-go-live-rehearsal-v2-1234abcd-main"
    assert rehearsal.require_rehearsal_project_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "infra",
        "nexus-go-live-rehearsal-v2-1234abcd",
        "nexus-go-live-rehearsal-v2-1234abcd-unknown",
        "NEXUS-go-live-rehearsal-v2-1234abcd-main",
        "nexus-go-live-rehearsal-v2-1234abcd-main\nATTACK=1",
    ],
)
def test_project_name_refuses_production_and_noncanonical_names(name: str) -> None:
    with pytest.raises(rehearsal.RehearsalError, match="project name"):
        rehearsal.require_rehearsal_project_name(name)


def test_foreign_snapshot_diff_ignores_only_generated_projects() -> None:
    before = {
        "foreign-a": {
            "id": "foreign-a",
            "started_at": "2026-08-25T00:00:00Z",
            "project": "korrigo-local",
            "service": "api",
        },
        "generated": {
            "id": "generated",
            "started_at": "2026-08-25T00:00:00Z",
            "project": "nexus-go-live-rehearsal-v2-1234abcd-main",
            "service": "ingestor",
        },
    }
    after = {
        "foreign-a": dict(before["foreign-a"]),
        "generated-new": {
            **before["generated"],
            "id": "generated-new",
        },
    }

    assert rehearsal.foreign_snapshot_changes(
        before,
        after,
        generated_projects={"nexus-go-live-rehearsal-v2-1234abcd-main"},
    ) == []

    after["foreign-a"]["started_at"] = "2026-08-25T01:00:00Z"
    assert rehearsal.foreign_snapshot_changes(
        before,
        after,
        generated_projects={"nexus-go-live-rehearsal-v2-1234abcd-main"},
    ) == ["foreign-a:changed"]


def test_foreign_witness_is_never_excluded_from_foreign_diff() -> None:
    before = {
        "witness": {
            "id": "witness",
            "started_at": "2026-08-25T00:00:00Z",
            "project": "nexus-go-live-rehearsal-v2-1234abcd-witness",
            "service": "foreign-witness",
        }
    }
    after = {"witness": {**before["witness"], "started_at": "changed"}}
    assert rehearsal.foreign_snapshot_changes(
        before,
        after,
        generated_projects={"nexus-go-live-rehearsal-v2-1234abcd-main"},
    ) == ["witness:changed"]


def test_evidence_json_is_canonical_and_newline_free() -> None:
    raw = rehearsal.canonical_json_bytes({"z": 1, "a": {"é": True}})
    assert raw == b'{"a":{"\xc3\xa9":true},"z":1}'
    assert json.loads(raw) == {"a": {"é": True}, "z": 1}


def test_bundle_member_attestation_uses_context_free_hash_fields(
    tmp_path: Path,
) -> None:
    member = "release-material/governance/authorizations/example.json"
    path = tmp_path / member
    path.parent.mkdir(parents=True)
    path.write_bytes(b"contract")
    expected = hashlib.sha256(b"contract").hexdigest()
    assert rehearsal.bundle_member_attestation(
        tmp_path,
        {member: expected},
    ) == [{"path": member, "sha256": expected}]


def test_transcript_refuses_secret_or_absolute_path() -> None:
    assert rehearsal.sanitize_transcript_line(
        "SCENARIO valid PASS",
        forbidden_values=("secret-seed",),
    ) == "SCENARIO valid PASS"

    with pytest.raises(rehearsal.RehearsalError, match="forbidden value"):
        rehearsal.sanitize_transcript_line(
            "seed=secret-seed",
            forbidden_values=("secret-seed",),
        )
    with pytest.raises(rehearsal.RehearsalError, match="absolute path"):
        rehearsal.sanitize_transcript_line(
            "bundle=/tmp/private/bundle",
            forbidden_values=(),
        )


def test_all_required_verdicts_drive_global_pass() -> None:
    verdicts = {
        "BAD_DIGEST_REFUSED": True,
        "BAD_READINESS_REFUSED": True,
        "BAD_AUTHORIZATION_SET_REFUSED": True,
        "FOREIGN_COLLISION_REFUSED": True,
        "ISOLATION_PREFLIGHT_PASS": True,
        "FOREIGN_SERVICES_TOUCHED": 0,
        "PRODUCTION_PORTS_PUBLISHED": 0,
        "PRODUCTION_PROJECT_NAME_USED": False,
        "REMOVE_ORPHANS_USED": False,
        "ROLLBACK_REHEARSAL_PASS": True,
        "PROJECT_CONTAINERS_REMAINING": 0,
    }
    assert rehearsal.global_rehearsal_pass(verdicts) is True
    for key in verdicts:
        changed = dict(verdicts)
        changed[key] = (
            1
            if key.endswith(("TOUCHED", "REMAINING", "PUBLISHED"))
            else not verdicts[key]
        )
        assert rehearsal.global_rehearsal_pass(changed) is False


def test_isolation_preflight_refuses_any_preexisting_generated_resource() -> None:
    clean = {
        "main": {"containers": [], "networks": [], "volumes": []},
        "witness": {"containers": [], "networks": [], "volumes": []},
        "collision": {"containers": [], "networks": [], "volumes": []},
    }
    rehearsal.require_empty_project_inventories(clean)
    dirty = json.loads(json.dumps(clean))
    dirty["main"]["networks"] = ["pre-existing-network"]
    with pytest.raises(rehearsal.RehearsalError, match="pre-existing"):
        rehearsal.require_empty_project_inventories(dirty)


def test_auxiliary_compose_is_registered_before_startup(tmp_path: Path) -> None:
    project = "nexus-go-live-rehearsal-v2-1234abcd-witness"
    registry: dict[str, Path] = {}
    path = rehearsal.prepare_auxiliary_compose(
        root=tmp_path,
        project_name=project,
        service_name="foreign-witness",
        image_ref="alpine@sha256:" + "d" * 64,
        cleanup_registry=registry,
    )
    assert registry == {project: path}
    assert path.is_file()


def test_cleanup_exhausts_all_targets_and_audits_after_exceptions() -> None:
    calls: list[str] = []
    inventory_calls = 0

    def main_cleanup() -> None:
        calls.append("main")
        if calls.count("main") == 1:
            raise rehearsal.RehearsalError("simulated timeout")

    def witness_cleanup() -> None:
        calls.append("witness")
        raise rehearsal.RehearsalError("simulated daemon failure")

    def collision_cleanup() -> None:
        calls.append("collision")

    def inventory() -> dict[str, list[str]]:
        nonlocal inventory_calls
        inventory_calls += 1
        if inventory_calls == 1:
            raise rehearsal.RehearsalError("simulated inventory timeout")
        return {"containers": [], "networks": [], "volumes": []}

    residue, failures = rehearsal.exhaust_cleanup(
        {
            "main": main_cleanup,
            "witness": witness_cleanup,
            "collision": collision_cleanup,
        },
        inventory,
    )
    assert calls == [
        "main",
        "witness",
        "collision",
        "main",
        "witness",
        "collision",
    ]
    assert inventory_calls == 2
    assert residue == {"containers": [], "networks": [], "volumes": []}
    assert any("main cleanup attempt 1" in failure for failure in failures)
    assert any("witness cleanup attempt 2" in failure for failure in failures)
    assert any("inventory attempt 1" in failure for failure in failures)


def test_fixture_builder_requires_private_seed_explicitly() -> None:
    signature = inspect.signature(fixture.build_release_material_fixture)
    assert signature.parameters["review_binding_private_key_hex"].default is inspect.Parameter.empty

    signature = inspect.signature(fixture.sign_readiness_fixture)
    assert signature.parameters["readiness_private_key_hex"].default is inspect.Parameter.empty


def _release_fixture(seed: str) -> fixture.ReleaseMaterialFixture:
    return fixture.build_release_material_fixture(
        review_binding_private_key_hex=seed,
        merge_sha="a" * 40,
        merge_tree_sha="b" * 40,
        now=datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
    )


def test_two_fresh_review_keys_produce_distinct_public_anchor_digests() -> None:
    first = _release_fixture(secrets.token_hex(32))
    second = _release_fixture(secrets.token_hex(32))
    assert first.review_binding_public_anchor_sha256 != second.review_binding_public_anchor_sha256


def test_private_review_seed_is_not_serialized_in_release_material() -> None:
    seed = secrets.token_hex(32)
    built = _release_fixture(seed)
    serialized = b"\n".join(
        [
            built.material.authorization_set_raw,
            built.material.review_binding_trust_anchor_raw,
            *built.material.release_files.values(),
            *built.material.evidence_files.values(),
        ]
    )
    assert seed.encode() not in serialized


def test_fixture_never_impersonates_prescribed_human_identities() -> None:
    built = _release_fixture(secrets.token_hex(32))
    serialized = b"\n".join(
        [
            *built.material.release_files.values(),
            built.material.profile_manifest_raw,
            built.material.trusted_reviewers_raw,
        ]
    )
    assert b'"reviewer_login": "abenrhouma"' not in serialized
    assert b'"author_login": "cyranoaladin"' not in serialized
    assert b"approved_by: abenrhouma" not in serialized
    assert b"nexus-fixture-reviewer" in serialized
    assert b"nexus-fixture-author" in serialized


def test_authorization_set_fixture_is_real_v1_and_verified() -> None:
    built = _release_fixture(secrets.token_hex(32))
    authorization_set = parse_authorization_set(built.material.authorization_set_raw)
    assert authorization_set.protocol_version == "NEXUS-AUTHORIZATION-SET-V1"
    verified = fixture.signer.verify_v2_release_material(built.material)
    assert verified.authorization_set.digest() == authorization_set.digest()


def test_readiness_fixture_is_valid_v2_and_private_seed_is_absent() -> None:
    built = _release_fixture(secrets.token_hex(32))
    readiness_seed = secrets.token_hex(32)
    signed = fixture.sign_readiness_fixture(
        material=built.material,
        readiness_private_key_hex=readiness_seed,
        compose_digest="c" * 64,
        application_image_digests={
            "ingestor": "alpine@sha256:" + "d" * 64,
            "multilevel-worker-a-production": "alpine@sha256:" + "d" * 64,
            "multilevel-worker-b-production": "alpine@sha256:" + "d" * 64,
        },
        upstream_image_digests={
            "fixture-upstream": "alpine@sha256:" + "d" * 64,
        },
    )
    anchor = parse_production_readiness_trust_anchor(signed.trust_anchor_raw)
    manifest = verify_production_readiness_manifest_v2(
        signed.signed_manifest_raw,
        trust_anchor=anchor,
        environment="production",
    )
    assert manifest.protocol_version == "NEXUS-PRODUCTION-READINESS-V2"
    assert manifest.compose_digest == "c" * 64
    assert readiness_seed.encode() not in signed.signed_manifest_raw
    assert readiness_seed.encode() not in signed.trust_anchor_raw
    assert signed.public_anchor_sha256 == hashlib.sha256(signed.trust_anchor_raw).hexdigest()


def test_compose_fixture_has_exact_images_read_only_binds_and_no_ports() -> None:
    image = "alpine@sha256:" + "d" * 64
    sources = fixture.compose_source_bytes(image_ref=image)
    assert set(sources) == {
        "docker-compose.v2.yml",
        "docker-compose.production-workers.yml",
        "docker-compose.production-release.yml",
    }
    joined = b"\n".join(sources.values())
    assert b"ports:" not in joined
    assert joined.count(image.encode()) == 4
    assert joined.count(b"/app/production/authorization-set.json:ro") == 2
    assert joined.count(b"/app/production/v2-material:ro") == 2


def test_refusal_scenario_requires_zero_mutating_subprocess_calls(tmp_path: Path) -> None:
    def refused_before_mutation(
        runner: Callable[[list[str], Path], subprocess.CompletedProcess[str]],
    ) -> None:
        del runner
        raise rehearsal.RehearsalError("bad readiness")

    passed = rehearsal.run_refusal_scenario(
        name="bad_readiness",
        operation=refused_before_mutation,
        cwd=tmp_path,
    )
    assert passed["refused"] is True
    assert passed["mutation_boundary_calls"] == 0
    assert passed["passed"] is True

    def refused_after_mutation(
        runner: Callable[[list[str], Path], subprocess.CompletedProcess[str]],
    ) -> None:
        runner(["docker", "compose", "pull"], tmp_path)
        raise rehearsal.RehearsalError("too late")

    late = rehearsal.run_refusal_scenario(
        name="late",
        operation=refused_after_mutation,
        cwd=tmp_path,
    )
    assert late["refused"] is True
    assert late["mutation_boundary_calls"] == 1
    assert late["passed"] is False


def test_rewrite_outer_bundle_manifest_rehashes_only_selected_file(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    readiness = bundle / "readiness-manifest.json"
    authorization = bundle / "authorization-set.json"
    readiness.write_bytes(b"original-readiness")
    authorization.write_bytes(b"original-authorization")
    original = {
        "protocol_version": "NEXUS-DEPLOYMENT-BUNDLE-V1",
        "files": {
            readiness.name: hashlib.sha256(readiness.read_bytes()).hexdigest(),
            authorization.name: hashlib.sha256(authorization.read_bytes()).hexdigest(),
        },
    }
    unsigned = rehearsal.canonical_json_bytes(original)
    original["bundle_digest"] = hashlib.sha256(unsigned).hexdigest()
    (bundle / "bundle_manifest.json").write_bytes(
        rehearsal.canonical_json_bytes(original)
    )

    authorization.write_bytes(b"changed-authorization")
    updated = rehearsal.rewrite_outer_bundle_manifest(
        bundle,
        changed_file=authorization.name,
    )

    assert updated["files"][readiness.name] == original["files"][readiness.name]
    assert updated["files"][authorization.name] == hashlib.sha256(
        authorization.read_bytes()
    ).hexdigest()
    claimed = updated.pop("bundle_digest")
    assert claimed == hashlib.sha256(rehearsal.canonical_json_bytes(updated)).hexdigest()


def test_rollback_command_is_exact_and_never_removes_orphans(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    command = rehearsal.rollback_command(bundle)
    assert command[-3:] == ["down", "--timeout", "10"]
    assert "--remove-orphans" not in command
    assert command.count("-f") == 3
    assert command[0:2] == ["docker", "compose"]


def test_generated_project_inventory_must_include_networks_and_volumes() -> None:
    inventory = {
        "containers": [],
        "networks": ["network-id"],
        "volumes": [],
    }
    assert rehearsal.project_inventory_count(inventory) == 1


@pytest.mark.skipif(
    os.environ.get("NEXUS_RUN_DOCKER_V2_REHEARSAL") != "1",
    reason="explicit real-Docker rehearsal opt-in required",
)
def test_real_docker_v2_rehearsal_end_to_end(tmp_path: Path) -> None:
    result = rehearsal.run_rehearsal(
        repo_root=Path(__file__).resolve().parents[3],
        private_root=tmp_path,
        image_tag="alpine:3.20",
    )
    verdicts = result["verdicts"]
    assert verdicts == {
        "ATOMIC_DOCKER_V2_REHEARSAL_PASS": True,
        "BAD_DIGEST_REFUSED": True,
        "BAD_READINESS_REFUSED": True,
        "BAD_AUTHORIZATION_SET_REFUSED": True,
        "FOREIGN_COLLISION_REFUSED": True,
        "ISOLATION_PREFLIGHT_PASS": True,
        "FOREIGN_SERVICES_TOUCHED": 0,
        "PRODUCTION_PORTS_PUBLISHED": 0,
        "PRODUCTION_PROJECT_NAME_USED": False,
        "REMOVE_ORPHANS_USED": False,
        "ROLLBACK_REHEARSAL_PASS": True,
        "PROJECT_CONTAINERS_REMAINING": 0,
    }
    for scenario in (
        "bad_digest",
        "bad_readiness",
        "bad_authorization_set",
        "foreign_collision",
    ):
        assert result["scenarios"][scenario]["mutation_boundary_calls"] == 0
    assert result["generated_project_residue"] == {
        "containers": [],
        "networks": [],
        "volumes": [],
    }
