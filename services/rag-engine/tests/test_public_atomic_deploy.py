"""Déploiement Docker du bundle public : frontières et refus avant mutation."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import deploy_verified_release_cli as dep  # noqa: E402

from tests.test_public_blue_green_preflight import SHA  # noqa: E402
from tests.test_sign_production_readiness_manifest_cli import _v2_material  # noqa: E402
from tests.test_signed_public_candidate_plan import _signed_public_bundle  # noqa: E402


def _inputs(tmp_path: Path) -> tuple[Path, bytes, dict, dict]:
    bundle, anchor, config = _signed_public_bundle(tmp_path)
    options = {
        "bundle_dir": bundle,
        "merge_sha": SHA,
        "execute": True,
        "trusted_readiness_anchor_raw": anchor,
        "run_bundle_compose_config": lambda *_: config,
        "public_color": "blue",
        "public_material_root": tmp_path / "release-x",
        "public_secrets_root": tmp_path / "secrets",
        "public_repo_root": tmp_path / "checkout",
        "public_final_cutover_go": True,
        "assert_readiness": lambda: True,
        "project_inventory": lambda _project: {"containers": [], "networks": [], "volumes": []},
    }
    return bundle, anchor, config, options


def _ok(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, 0, "", "")


def test_public_execute_requires_final_go_before_docker(tmp_path: Path) -> None:
    _, _, _, options = _inputs(tmp_path)
    options["public_final_cutover_go"] = False
    options["run_subprocess"] = lambda *_: pytest.fail("Docker mutation called")
    with pytest.raises(dep.DeploymentWrapperError, match="cutover.*GO"):
        dep.deploy_from_bundle(**options)


def test_public_execute_requires_fresh_assert_ready_before_docker(tmp_path: Path) -> None:
    _, _, _, options = _inputs(tmp_path)
    options["assert_readiness"] = lambda: False
    options["run_subprocess"] = lambda *_: pytest.fail("Docker mutation called")
    with pytest.raises(dep.DeploymentWrapperError, match="assert-ready"):
        dep.deploy_from_bundle(**options)


def test_public_execute_pulls_then_waits_for_exact_services_in_isolated_project(
    tmp_path: Path,
) -> None:
    bundle, _, _, options = _inputs(tmp_path)
    calls: list[list[str]] = []

    def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        assert cwd == bundle
        calls.append(args)
        return _ok(args, cwd)

    options["run_subprocess"] = run
    result = dep.deploy_from_bundle(**options)
    assert len(calls) == 2
    assert ["pull", "up"] == [next(word for word in call if word in {"pull", "up"}) for call in calls]
    for call in calls:
        assert call[call.index("--project-name") + 1] == "nexus-rag-blue"
        assert "--remove-orphans" not in call
        assert "--build" not in call
        assert "infra" not in call
        assert all(str(bundle / name) in call for name in dep.vri._PUBLIC_CANDIDATE_COMPOSE_FILES)
    assert calls[0][calls[0].index("pull") + 1 :] == sorted(
        ["pgvector", "ingestor", "prometheus", "session-redis", "cockpit"]
    )
    assert calls[1][calls[1].index("up") + 1 :] == [
        "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "300",
        *sorted(["pgvector", "ingestor", "prometheus", "session-redis", "cockpit"]),
    ]
    assert result == ["PUBLIC_CANDIDATE_DEPLOYED=true", "EDGE_SWITCHED=false"]


def test_public_execute_refuses_existing_candidate_resources(tmp_path: Path) -> None:
    _, _, _, options = _inputs(tmp_path)
    options["project_inventory"] = lambda _project: {
        "containers": ["existing"], "networks": [], "volumes": []
    }
    options["run_subprocess"] = lambda *_: pytest.fail("Docker mutation called")
    with pytest.raises(dep.DeploymentWrapperError, match="pre-existing.*project"):
        dep.deploy_from_bundle(**options)


def test_public_execute_refuses_preflight_project_outside_selected_color(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, _, options = _inputs(tmp_path)
    monkeypatch.setattr(
        dep.public_preflight, "require_public_candidate", lambda **_kw: {"project": "infra"}
    )
    options["run_subprocess"] = lambda *_: pytest.fail("Docker mutation called")
    with pytest.raises(dep.DeploymentWrapperError, match="selected color"):
        dep.deploy_from_bundle(**options)


def test_public_execute_refuses_rehashed_bad_readiness_before_docker(tmp_path: Path) -> None:
    bundle, _, _, options = _inputs(tmp_path)
    readiness = bundle / dep._READINESS_MANIFEST_BUNDLE_NAME
    document = json.loads(readiness.read_bytes())
    document["signature"] = "0" * 128
    readiness.write_bytes(dep._canonical_json_bytes(document))
    manifest = bundle / dep._BUNDLE_MANIFEST_NAME
    outer = json.loads(manifest.read_bytes())
    outer.pop("bundle_digest")
    outer["files"][readiness.name] = hashlib.sha256(readiness.read_bytes()).hexdigest()
    outer["bundle_digest"] = hashlib.sha256(dep._canonical_json_bytes(outer)).hexdigest()
    manifest.write_bytes(dep._canonical_json_bytes(outer))
    options["run_subprocess"] = lambda *_: pytest.fail("Docker mutation called")
    with pytest.raises(dep.DeploymentWrapperError):
        dep.deploy_from_bundle(**options)


def test_public_execute_refuses_bad_image_digest_before_docker(tmp_path: Path) -> None:
    _, _, config, options = _inputs(tmp_path)
    changed = json.loads(json.dumps(config))
    changed["services"]["cockpit"]["image"] = changed["services"]["cockpit"]["image"].replace(
        "e" * 64, "0" * 64
    )
    options["run_bundle_compose_config"] = lambda *_: changed
    options["run_subprocess"] = lambda *_: pytest.fail("Docker mutation called")
    with pytest.raises(dep.DeploymentWrapperError, match="effective compose"):
        dep.deploy_from_bundle(**options)


def test_failed_public_up_rolls_back_only_candidate_project(tmp_path: Path) -> None:
    bundle, _, _, options = _inputs(tmp_path)
    calls: list[list[str]] = []

    def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        assert cwd == bundle
        calls.append(args)
        return subprocess.CompletedProcess(args, 1 if "up" in args else 0, "", "failed")

    options["run_subprocess"] = run
    with pytest.raises(dep.DeploymentWrapperError, match="up failed.*rollback"):
        dep.deploy_from_bundle(**options)
    assert [word for call in calls for word in call if word in {"pull", "up", "down"}] == [
        "pull", "up", "down"
    ]
    assert all(call[call.index("--project-name") + 1] == "nexus-rag-blue" for call in calls)
    assert "-v" not in calls[-1]


def test_timed_out_public_up_still_rolls_back_candidate(tmp_path: Path) -> None:
    _, _, _, options = _inputs(tmp_path)
    calls: list[list[str]] = []

    def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if "up" in args:
            raise subprocess.TimeoutExpired(args, 600)
        return _ok(args, cwd)

    options["run_subprocess"] = run
    with pytest.raises(dep.DeploymentWrapperError, match="up failed.*rollback passed"):
        dep.deploy_from_bundle(**options)
    assert [word for call in calls for word in call if word in {"pull", "up", "down"}] == [
        "pull", "up", "down"
    ]


def test_explicit_public_rollback_uses_only_candidate_bundle(tmp_path: Path) -> None:
    bundle, _, _, options = _inputs(tmp_path)
    calls: list[list[str]] = []

    def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        assert cwd == bundle
        return _ok(args, cwd)

    options["run_subprocess"] = run
    dep.rollback_public_candidate_from_bundle(
        bundle_dir=bundle,
        merge_sha=SHA,
        public_color="blue",
        run_bundle_compose_config=options["run_bundle_compose_config"],
        run_subprocess=run,
    )
    assert len(calls) == 1
    assert calls[0][-3:] == ["down", "--timeout", "10"]
    assert calls[0][calls[0].index("--project-name") + 1] == "nexus-rag-blue"


def test_public_cli_execute_requires_explicit_final_go_before_materialization(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = dep.main([
        "--merge-sha", SHA,
        "--merge-tree-sha", "b" * 40,
        "--provenance-run-id", "777",
        "--provenance-run-attempt", "1",
        "--bundle-dir", str(tmp_path / "absent"),
        "--readiness-protocol", "NEXUS-PRODUCTION-READINESS-V2",
        "--public-candidate", "--execute",
    ])
    assert result == 1
    assert "final cutover GO" in capsys.readouterr().err


def test_public_cli_forwards_final_go_and_returns_candidate_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args = Namespace(
        public_candidate=True, execute=True, final_cutover_go=True,
        readiness_protocol="NEXUS-PRODUCTION-READINESS-V2",
        readiness_manifest_file=tmp_path / "readiness.json",
        trust_anchor_file=tmp_path / "anchor.json", env_file=None, repo_root=tmp_path,
        merge_sha=SHA, merge_tree_sha="b" * 40,
        provenance_run_id=777, provenance_run_attempt=1,
        environment="production", bundle_dir=tmp_path / "bundle",
        deployment_state_root=None, json_output=True,
        public_color="blue", public_material_root=tmp_path / "release-x",
        public_secrets_root=tmp_path / "secrets",
    )
    for name in (
        "authorization_set_file", "governed_root", "review_binding_trust_anchor_file",
        "trusted_reviewers_file", "revocation_registry_file", "release_scope_placement_file",
        "verified_profiles_file", "profile_manifest_file", "authority_required_file",
        "h2b_report_file", "h2_evidence_bundle_file", "promotion_evidence_file",
        "catalog_file", "sealed_manifest_file", "routing_file", "rights_file",
        "pii_file", "golden_file", "currentness_file", "profile_proposal_matrix_path",
        "accepted_placements_path", "release_registry_path", "expected_contents_path",
        "verified_profiles_path", "profile_manifest_path",
    ):
        setattr(args, name, tmp_path / name)
    monkeypatch.setattr(dep, "_build_arg_parser", lambda: Namespace(parse_args=lambda _argv: args))
    monkeypatch.setattr(dep.signer, "_load_v2_release_material", lambda *_args, **_kw: _v2_material())
    monkeypatch.setattr(dep.signer, "_read_bytes_no_follow", lambda *_args, **_kw: b"anchor")
    monkeypatch.setattr(dep, "materialize_verified_bundle", lambda **_kw: {
        "bundle_digest": "a" * 64,
        "readiness_protocol": "NEXUS-PRODUCTION-READINESS-V2",
        "verified_images": {"ingestor": "sha256:" + "1" * 64},
    })
    captured: dict = {}

    def deploy(**kwargs: object) -> list[str]:
        captured.update(kwargs)
        return ["PUBLIC_CANDIDATE_DEPLOYED=true", "EDGE_SWITCHED=false"]

    monkeypatch.setattr(dep, "deploy_from_bundle", deploy)
    assert dep.main([]) == 0
    assert captured["public_final_cutover_go"] is True
    assert captured["public_color"] == "blue"
    assert captured["public_material_root"] == tmp_path / "release-x"
    assert captured["public_secrets_root"] == tmp_path / "secrets"
    output = json.loads(capsys.readouterr().out)
    assert output["deployed"] is True
    assert output["edge_switched"] is False


def test_public_cli_rollback_uses_existing_bundle_without_rematerialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    called: dict = {}

    def rollback(**kwargs: object) -> None:
        called.update(kwargs)

    monkeypatch.setattr(dep, "rollback_public_candidate_from_bundle", rollback)
    monkeypatch.setattr(dep, "materialize_verified_bundle", lambda **_kw: pytest.fail("rematerialized"))
    assert dep.main([
        "--merge-sha", SHA,
        "--merge-tree-sha", "b" * 40,
        "--provenance-run-id", "777",
        "--provenance-run-attempt", "1",
        "--bundle-dir", str(tmp_path / "candidate-bundle"),
        "--public-candidate", "--public-color", "blue",
        "--rollback-public-candidate", "--json-output",
    ]) == 0
    assert called["bundle_dir"] == tmp_path / "candidate-bundle"
    assert called["public_color"] == "blue"
    assert json.loads(capsys.readouterr().out) == {
        "rolled_back": True, "edge_switched": False
    }


def test_public_cli_rejects_rollback_combined_with_execute(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert dep.main([
        "--merge-sha", SHA,
        "--merge-tree-sha", "b" * 40,
        "--provenance-run-id", "777",
        "--provenance-run-attempt", "1",
        "--bundle-dir", str(tmp_path / "absent"),
        "--public-candidate", "--public-color", "blue",
        "--rollback-public-candidate", "--execute", "--final-cutover-go",
    ]) == 1
    assert "rollback" in capsys.readouterr().err


def test_canonical_assert_ready_refuses_dirty_final_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if "rev-parse" in command:
            return subprocess.CompletedProcess(command, 0, SHA + "\n", "")
        if "status" in command:
            return subprocess.CompletedProcess(command, 0, " M scripts/go_live/check_go_live_readiness.py\n", "")
        return subprocess.CompletedProcess(command, 0, "GO_LIVE_READY=true\n", "")

    monkeypatch.setattr(dep.subprocess, "run", run)
    assert dep._assert_go_live_ready(tmp_path, SHA) is False
    assert not any("--assert-ready" in command for command in calls)
