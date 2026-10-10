"""Déploiement Docker du bundle public : frontières et refus avant mutation."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import threading
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
        "deployment_state_root": tmp_path / "state",
        "prometheus_probe": lambda _port: True,
        "host_local_guard": lambda: True,
        "project_inventory": lambda _project: {"containers": [], "networks": [], "volumes": []},
        "project_containers": lambda _project: _owned_containers(bundle),
    }
    return bundle, anchor, config, options


def _ok(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, 0, "", "")


def _owned_containers(bundle: Path) -> list[dict]:
    files = ",".join(str(bundle / name) for name in dep.vri._PUBLIC_CANDIDATE_COMPOSE_FILES)
    return [{"Id": f"container-{name}", "Labels": {
        "com.docker.compose.project": "nexus-rag-blue",
        "com.docker.compose.service": name,
        "com.docker.compose.project.working_dir": str(bundle),
        "com.docker.compose.project.config_files": files,
    }} for name in sorted(dep.vri._PUBLIC_CANDIDATE_SERVICES)]


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
    with pytest.raises(dep.DeploymentWrapperError, match="readiness|signature"):
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
    options["project_containers"] = lambda _project: _owned_containers(bundle)
    with pytest.raises(dep.DeploymentWrapperError, match="up failed.*rollback"):
        dep.deploy_from_bundle(**options)
    assert [word for call in calls for word in call if word in {"pull", "up", "down"}] == [
        "pull", "up", "down"
    ]
    assert all(call[call.index("--project-name") + 1] == "nexus-rag-blue" for call in calls)
    assert "-v" not in calls[-1]


def test_timed_out_public_up_still_rolls_back_candidate(tmp_path: Path) -> None:
    bundle, _, _, options = _inputs(tmp_path)
    calls: list[list[str]] = []

    def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if "up" in args:
            raise subprocess.TimeoutExpired(args, 600)
        return _ok(args, cwd)

    options["run_subprocess"] = run
    options["project_containers"] = lambda _project: _owned_containers(bundle)
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
    dep.deploy_from_bundle(**options)
    calls.clear()
    dep.rollback_public_candidate_from_bundle(
        bundle_dir=bundle,
        merge_sha=SHA,
        public_color="blue",
        run_bundle_compose_config=options["run_bundle_compose_config"],
        run_subprocess=run,
        deployment_state_root=options["deployment_state_root"],
        project_containers=lambda _project: _owned_containers(bundle),
        host_local_guard=lambda: True,
    )
    assert len(calls) == 1
    assert calls[0][-3:] == ["down", "--timeout", "10"]
    assert calls[0][calls[0].index("--project-name") + 1] == "nexus-rag-blue"


def test_old_bundle_cannot_rollback_new_generation(tmp_path: Path) -> None:
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    old_root.mkdir(mode=0o700)
    new_root.mkdir(mode=0o700)
    old_bundle, _, _, old = _inputs(old_root)
    new_bundle, _, _, new = _inputs(new_root)
    new["deployment_state_root"] = tmp_path / "shared-state"
    new["project_containers"] = lambda _project: _owned_containers(new_bundle)
    new["run_subprocess"] = _ok
    dep.deploy_from_bundle(**new)
    with pytest.raises(dep.DeploymentWrapperError, match="generation|bundle"):
        dep.rollback_public_candidate_from_bundle(
            bundle_dir=old_bundle, merge_sha=SHA, public_color="blue",
            run_bundle_compose_config=old["run_bundle_compose_config"],
            run_subprocess=lambda *_: pytest.fail("down from old bundle"),
            deployment_state_root=new["deployment_state_root"],
            project_containers=lambda _project: _owned_containers(new_bundle),
            host_local_guard=lambda: True,
        )


def test_public_rollback_maps_state_delete_failure_to_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _, _, options = _inputs(tmp_path)
    options["run_subprocess"] = _ok
    dep.deploy_from_bundle(**options)
    real_unlink = os.unlink

    def fail_state_unlink(path: str, **kwargs: object) -> None:
        if path == "public-blue.json":
            raise OSError("injected state delete failure")
        real_unlink(path, **kwargs)

    monkeypatch.setattr(dep.os, "unlink", fail_state_unlink)
    with pytest.raises(dep.DeploymentWrapperError, match="state"):
        dep.rollback_public_candidate_from_bundle(
            bundle_dir=bundle, merge_sha=SHA, public_color="blue",
            run_bundle_compose_config=options["run_bundle_compose_config"],
            run_subprocess=_ok,
            deployment_state_root=options["deployment_state_root"],
            project_containers=lambda _project: _owned_containers(bundle),
            host_local_guard=lambda: True,
        )


def test_rollback_retained_volumes_block_color_reuse_before_docker(tmp_path: Path) -> None:
    bundle, _, _, options = _inputs(tmp_path)
    options["run_subprocess"] = _ok
    dep.deploy_from_bundle(**options)
    dep.rollback_public_candidate_from_bundle(
        bundle_dir=bundle, merge_sha=SHA, public_color="blue",
        run_bundle_compose_config=options["run_bundle_compose_config"],
        run_subprocess=_ok,
        deployment_state_root=options["deployment_state_root"],
        project_containers=lambda _project: _owned_containers(bundle),
        host_local_guard=lambda: True,
    )
    options["project_inventory"] = lambda _project: {
        "containers": [], "networks": [],
        "volumes": ["nexus-rag-blue_rag_pgvector_data"],
    }
    options["run_subprocess"] = lambda *_: pytest.fail("Docker mutation after retained volume")
    with pytest.raises(dep.DeploymentWrapperError, match="pre-existing resources"):
        dep.deploy_from_bundle(**options)


def test_failed_up_refuses_down_when_container_identity_is_ambiguous(tmp_path: Path) -> None:
    _, _, _, options = _inputs(tmp_path)
    calls: list[list[str]] = []
    options["project_containers"] = lambda _project: [{"Id": "foreign", "Labels": {}}]

    def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 1 if "up" in args else 0, "", "")

    options["run_subprocess"] = run
    with pytest.raises(dep.DeploymentWrapperError, match="identity|ownership"):
        dep.deploy_from_bundle(**options)
    assert not any("down" in call for call in calls)


def test_concurrent_candidate_deploy_refused_before_second_inventory(tmp_path: Path) -> None:
    _, _, _, options = _inputs(tmp_path)
    pulling = threading.Event()
    release = threading.Event()
    result: list[BaseException] = []

    def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if "pull" in args:
            pulling.set()
            assert release.wait(10)
        return _ok(args, cwd)

    options["run_subprocess"] = run

    def first() -> None:
        try:
            dep.deploy_from_bundle(**options)
        except BaseException as exc:
            result.append(exc)

    worker = threading.Thread(target=first)
    worker.start()
    assert pulling.wait(10)
    try:
        second = dict(options)
        second["deployment_state_root"] = tmp_path / "different-state-root"
        second["project_inventory"] = lambda _project: pytest.fail("second inventory")
        with pytest.raises(dep.DeploymentWrapperError, match="lock|busy"):
            dep.deploy_from_bundle(**second)
    finally:
        release.set()
        worker.join(10)
    assert not result


def test_prometheus_rules_probe_failure_refuses_success_and_rolls_back(tmp_path: Path) -> None:
    _, _, _, options = _inputs(tmp_path)
    calls: list[list[str]] = []

    def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return _ok(args, cwd)

    options["run_subprocess"] = run
    options["prometheus_probe"] = lambda _port: False
    with pytest.raises(dep.DeploymentWrapperError, match="Prometheus|prometheus"):
        dep.deploy_from_bundle(**options)
    assert [word for call in calls for word in call if word in {"pull", "up", "down"}] == [
        "pull", "up", "down"
    ]


def test_state_publish_fsync_failure_rolls_back_without_stale_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, options = _inputs(tmp_path)
    calls: list[list[str]] = []
    state_file = options["deployment_state_root"] / "public-blue.json"
    real_fsync = os.fsync
    failed = False

    def fsync(fd: int) -> None:
        nonlocal failed
        if state_file.exists() and not failed:
            failed = True
            raise OSError("injected state fsync failure after link")
        real_fsync(fd)

    monkeypatch.setattr(dep.os, "fsync", fsync)

    def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return _ok(args, cwd)

    options["run_subprocess"] = run
    with pytest.raises(dep.DeploymentWrapperError, match="rollback passed"):
        dep.deploy_from_bundle(**options)
    assert failed
    assert not state_file.exists()
    assert [word for call in calls for word in call if word in {"pull", "up", "down"}] == [
        "pull", "up", "down"
    ]


def test_real_prometheus_probe_requires_loaded_retrieval_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response(io.BytesIO):
        status = 200

    def urlopen(url: str, **_kwargs: object) -> Response:
        if url.endswith("/-/ready"):
            return Response(b"ready")
        return Response(b'{"status":"success","data":{"groups":[]}}')

    ticks = iter([0, 0, 91])
    monkeypatch.setattr(dep.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(dep.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(dep.time, "sleep", lambda _seconds: None)
    assert dep._default_public_prometheus_probe(19090) is False


@pytest.mark.parametrize(
    "targets",
    [[], [{"metric": {"job": "rag-engine-v2"}, "value": [1, "0"]}],
     [{"metric": {"job": "rag-engine-v2"}, "value": [1, "1"]},
      {"metric": {"job": "rag-engine-v2"}, "value": [1, "0"]}]],
)
def test_real_prometheus_probe_refuses_uncollected_api_target(
    monkeypatch: pytest.MonkeyPatch, targets: list[dict],
) -> None:
    class Response(io.BytesIO):
        status = 200

    alerts = [
        {"type": "alerting", "name": name}
        for name in (
            "RAGRetrievalMetricsScrapeFailed", "RAGRetrievalUnavailable",
            "RAGRetrievalTieOverflow", "RAGRetrievalP95High",
        )
    ]

    def urlopen(url: str, **_kwargs: object) -> Response:
        if url.endswith("/-/ready"):
            return Response(b"ready")
        if url.endswith("/api/v1/rules"):
            return Response(json.dumps({"status": "success", "data": {"groups": [
                {"name": "retrieval-v2", "rules": alerts}
            ]}}).encode())
        if "/api/v1/query?" in url:
            return Response(json.dumps({"status": "success", "data": {
                "resultType": "vector", "result": targets,
            }}).encode())
        pytest.fail(f"unexpected Prometheus URL: {url}")

    ticks = iter([0, 0, 91])
    monkeypatch.setattr(dep.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(dep.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(dep.time, "sleep", lambda _seconds: None)
    assert dep._default_public_prometheus_probe(19090) is False


def test_real_prometheus_probe_accepts_loaded_alerts_and_collected_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response(io.BytesIO):
        status = 200

    alerts = [
        {"type": "alerting", "name": name}
        for name in (
            "RAGRetrievalMetricsScrapeFailed", "RAGRetrievalUnavailable",
            "RAGRetrievalTieOverflow", "RAGRetrievalP95High",
        )
    ]
    queried: list[str] = []

    def urlopen(url: str, **_kwargs: object) -> Response:
        if url.endswith("/-/ready"):
            return Response(b"ready")
        if url.endswith("/api/v1/rules"):
            return Response(json.dumps({"status": "success", "data": {"groups": [
                {"name": "retrieval-v2", "rules": alerts}
            ]}}).encode())
        if "/api/v1/query?" in url:
            queried.append(url)
            return Response(json.dumps({"status": "success", "data": {
                "resultType": "vector", "result": [
                    {"metric": {"job": "rag-engine-v2"}, "value": [1, "1"]}
                ],
            }}).encode())
        pytest.fail(f"unexpected Prometheus URL: {url}")

    monkeypatch.setattr(dep.urllib.request, "urlopen", urlopen)
    assert dep._default_public_prometheus_probe(19090) is True
    assert len(queried) == 1
    assert "up%7Bjob%3D%22rag-engine-v2%22%7D" in queried[0]


def test_real_prometheus_probe_waits_for_first_scrape_after_thirty_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response(io.BytesIO):
        status = 200

    alerts = [
        {"type": "alerting", "name": name}
        for name in (
            "RAGRetrievalMetricsScrapeFailed", "RAGRetrievalUnavailable",
            "RAGRetrievalTieOverflow", "RAGRetrievalP95High",
        )
    ]
    queries = 0

    def urlopen(url: str, **_kwargs: object) -> Response:
        nonlocal queries
        if url.endswith("/-/ready"):
            return Response(b"ready")
        if url.endswith("/api/v1/rules"):
            return Response(json.dumps({"status": "success", "data": {"groups": [
                {"name": "retrieval-v2", "rules": alerts}
            ]}}).encode())
        if "/api/v1/query?" in url:
            queries += 1
            targets = [] if queries == 1 else [
                {"metric": {"job": "rag-engine-v2"}, "value": [31, "1"]}
            ]
            return Response(json.dumps({"status": "success", "data": {
                "resultType": "vector", "result": targets,
            }}).encode())
        pytest.fail(f"unexpected Prometheus URL: {url}")

    ticks = iter([0, 0, 31])
    monkeypatch.setattr(dep.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(dep.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(dep.time, "sleep", lambda _seconds: None)
    assert dep._default_public_prometheus_probe(19090) is True
    assert queries == 2


def test_public_host_guard_refuses_remote_docker_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote.example:2376")
    assert dep._require_host_local_docker_daemon() is False


def test_public_host_guard_refuses_named_remote_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setenv("DOCKER_CONTEXT", "remote")
    assert dep._require_host_local_docker_daemon() is False


def test_public_host_guard_refuses_nonlocal_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setattr(dep.subprocess, "run", lambda args, **_kw:
        subprocess.CompletedProcess(args, 0, '"tcp://remote.example:2376"\n', ""))
    assert dep._require_host_local_docker_daemon() is False


def test_public_execution_refuses_nonlocal_daemon_before_inventory(tmp_path: Path) -> None:
    _, _, _, options = _inputs(tmp_path)
    options["host_local_guard"] = lambda: False
    options["project_inventory"] = lambda _project: pytest.fail("inventory")
    options["run_subprocess"] = lambda *_: pytest.fail("Docker mutation")
    with pytest.raises(dep.DeploymentWrapperError, match="host-local"):
        dep.deploy_from_bundle(**options)


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


def test_public_cli_execute_requires_stable_state_root_before_materialization(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = dep.main([
        "--merge-sha", SHA, "--merge-tree-sha", "b" * 40,
        "--provenance-run-id", "777", "--provenance-run-attempt", "1",
        "--bundle-dir", str(tmp_path / "absent"),
        "--readiness-protocol", "NEXUS-PRODUCTION-READINESS-V2",
        "--public-candidate", "--execute", "--final-cutover-go",
    ])
    assert result == 1
    assert "deployment-state-root" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("extra", "missing"),
    [
        ([], "public-color"),
        (["--public-color", "blue"], "public-material-root"),
        (["--public-color", "blue", "--public-material-root", "{material}"],
         "public-secrets-root"),
    ],
)
def test_public_cli_requires_candidate_target_before_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], extra: list[str], missing: str,
) -> None:
    monkeypatch.setattr(dep, "materialize_verified_bundle", lambda **_kw: pytest.fail(
        "materialized before public target validation"
    ))
    result = dep.main([
        "--merge-sha", SHA, "--merge-tree-sha", "b" * 40,
        "--provenance-run-id", "777", "--provenance-run-attempt", "1",
        "--bundle-dir", str(tmp_path / "absent"),
        "--readiness-protocol", "NEXUS-PRODUCTION-READINESS-V2",
        "--public-candidate", "--execute", "--final-cutover-go",
        "--deployment-state-root", str(tmp_path / "state"),
        "--readiness-manifest-file", str(tmp_path / "readiness"),
        "--trust-anchor-file", str(tmp_path / "anchor"),
        *(str(tmp_path / "material") if value == "{material}" else value
          for value in extra),
    ])
    assert result == 1
    assert missing in capsys.readouterr().err


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
        deployment_state_root=tmp_path / "state", json_output=True,
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
        "--deployment-state-root", str(tmp_path / "state"),
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
