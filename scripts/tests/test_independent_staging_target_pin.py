"""Le pin de staging exige une autorité indépendante du transfert V2."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import types
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "github"))
from independent_staging_target_pin import (  # noqa: E402
    LiveTargetObservation,
    PinRefused,
    _inspect_local_docker_container,
    approved_pin_sha256,
    canonical,
    main,
    observed_peer_endpoint,
    parse_qualified_dsn_endpoint,
    verify_docker_postgres_binding,
    verify_target_pin,
)


NOW = datetime(2026, 10, 10, 20, 0, tzinfo=UTC)
ANCHOR = "a" * 64
CONTAINER = "b" * 64
HEAD = "c" * 40
BASE = "d" * 40


def test_docker_inspection_ignores_remote_context_and_pins_local_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import independent_staging_target_pin as module  # noqa: PLC0415

    docker_socket = tmp_path / "docker.sock"
    with socket.socket(socket.AF_UNIX) as local:
        local.bind(str(docker_socket))
        local.listen()
        monkeypatch.setattr(module, "DOCKER_SOCKET", docker_socket)
        for name in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG",
                     "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
            monkeypatch.setenv(name, "remote.invalid")

        def inspect(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
            assert command == [
                "docker", "--host", f"unix://{docker_socket}", "inspect",
                "--type", "container", CONTAINER,
            ]
            environment = kwargs["env"]
            for name in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG",
                         "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
                assert name not in environment
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps([{"Id": CONTAINER}]).encode(),
            )

        monkeypatch.setattr(module.subprocess, "run", inspect)
        container, identity = _inspect_local_docker_container(CONTAINER)
        assert container["Id"] == CONTAINER
        assert identity == (docker_socket.lstat().st_dev, docker_socket.lstat().st_ino)
        assert _inspect_local_docker_container(
            CONTAINER, expected_socket_identity=identity,
        )[1] == identity


@pytest.mark.parametrize("kind", ["symlink", "regular"])
def test_docker_inspection_refuses_non_socket_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    import independent_staging_target_pin as module  # noqa: PLC0415

    docker_socket = tmp_path / "docker.sock"
    if kind == "symlink":
        docker_socket.symlink_to(tmp_path / "missing.sock")
    else:
        docker_socket.write_text("not a socket")
    monkeypatch.setattr(module, "DOCKER_SOCKET", docker_socket)
    with pytest.raises(PinRefused):
        _inspect_local_docker_container(CONTAINER)


def test_docker_socket_replacement_between_inspections_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import independent_staging_target_pin as module  # noqa: PLC0415

    docker_socket = tmp_path / "docker.sock"
    with socket.socket(socket.AF_UNIX) as first:
        first.bind(str(docker_socket))
        first.listen()
        monkeypatch.setattr(module, "DOCKER_SOCKET", docker_socket)
        monkeypatch.setattr(
            module.subprocess, "run",
            lambda command, **kwargs: subprocess.CompletedProcess(
                command, 0, stdout=json.dumps([{"Id": CONTAINER}]).encode(),
            ),
        )
        _, identity = _inspect_local_docker_container(CONTAINER)
        os.unlink(docker_socket)
        with socket.socket(socket.AF_UNIX) as second:
            second.bind(str(docker_socket))
            second.listen()
            with pytest.raises(PinRefused):
                _inspect_local_docker_container(
                    CONTAINER, expected_socket_identity=identity,
                )


def test_docker_socket_replacement_during_inspection_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import independent_staging_target_pin as module  # noqa: PLC0415

    docker_socket = tmp_path / "docker.sock"
    with socket.socket(socket.AF_UNIX) as first:
        first.bind(str(docker_socket))
        first.listen()
        monkeypatch.setattr(module, "DOCKER_SOCKET", docker_socket)
        with socket.socket(socket.AF_UNIX) as second:
            def replace(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
                os.unlink(docker_socket)
                second.bind(str(docker_socket))
                second.listen()
                return subprocess.CompletedProcess(
                    command, 0, stdout=json.dumps([{"Id": CONTAINER}]).encode(),
                )

            monkeypatch.setattr(module.subprocess, "run", replace)
            with pytest.raises(PinRefused):
                _inspect_local_docker_container(CONTAINER)


def fixture(tmp_path: Path) -> tuple[bytes, Path, LiveTargetObservation]:
    destination = tmp_path / "destination"
    destination.mkdir()
    physical = destination.stat()
    pin = {
        "kind": "NEXUS_STAGING_QUALIFIED_TARGET_PIN_V1",
        "content_anchor_sha256": ANCHOR,
        "release_id": "student-public-successor-test",
        "target_identity": f"docker:{CONTAINER}",
        "hostname": "staging-example",
        "host_machine_id_sha256": "e" * 64,
        "postgres_system_identifier": "12345678901234567890",
        "database_name": "nexus_rag",
        "destination_realpath": str(destination),
        "destination_device": physical.st_dev,
        "destination_inode": physical.st_ino,
        "pinned_at_utc": (NOW - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        "expires_at_utc": (NOW + timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
    }
    observation = LiveTargetObservation(
        hostname="staging-example",
        host_machine_id_sha256="e" * 64,
        container_id=CONTAINER,
        postgres_system_identifier="12345678901234567890",
        database_name="nexus_rag",
        destination_realpath=str(destination),
        destination_device=physical.st_dev,
        destination_inode=physical.st_ino,
    )
    return canonical(pin), destination, observation


def test_pin_matches_live_target_and_approved_head(tmp_path: Path) -> None:
    raw, destination, observation = fixture(tmp_path)
    pin_sha = hashlib.sha256(raw).hexdigest()
    assert verify_target_pin(raw, expected_sha256=pin_sha,
                             expected_content_anchor_sha256=ANCHOR,
                             destination_root=destination, observation=observation,
                             now=NOW) == pin_sha
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    pin_path = Path("governance/staging_target_pins/target.json")
    (repo / pin_path).parent.mkdir(parents=True)
    (repo / pin_path).write_bytes(raw)
    subprocess.run(["git", "-C", str(repo), "add", str(pin_path)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-qm", "pin"], check=True)
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    decision = {
        "approved": True, "repository": "cyranoaladin/RAG", "pull_request": 999,
        "base_sha": BASE, "head_sha": head, "reviewer": "abenrhouma",
        "review_id": 42, "challenge": "NEXUS-TRUSTED-REVIEW-V1:fixture",
    }
    assert approved_pin_sha256(
        repo, pin_path, raw, decision=decision, challenges={"abenrhouma": decision["challenge"]},
        expected_base_sha=BASE, expected_head_sha=head, pull_request=999,
    ) == pin_sha
    (repo / pin_path).write_bytes(b"modified after review")
    with pytest.raises(PinRefused):
        approved_pin_sha256(
            repo, pin_path, (repo / pin_path).read_bytes(), decision=decision,
            challenges={"abenrhouma": decision["challenge"]},
            expected_base_sha=BASE, expected_head_sha=head, pull_request=999,
        )


@pytest.mark.parametrize("field,value", [
    ("hostname", "other-host"),
    ("host_machine_id_sha256", "f" * 64),
    ("container_id", "f" * 64),
    ("postgres_system_identifier", "1"),
    ("database_name", "native_postgres"),
    ("destination_realpath", "/other/path"),
    ("destination_device", -1),
    ("destination_inode", -1),
])
def test_live_identity_sabotage_refused(tmp_path: Path, field: str, value: object) -> None:
    raw, destination, observation = fixture(tmp_path)
    with pytest.raises(PinRefused):
        verify_target_pin(raw, expected_sha256=hashlib.sha256(raw).hexdigest(),
                          expected_content_anchor_sha256=ANCHOR,
                          destination_root=destination,
                          observation=replace(observation, **{field: value}), now=NOW)


@pytest.mark.parametrize("mutation", [
    {"content_anchor_sha256": "f" * 64},
    {"target_identity": "host:pretend"},
    {"expires_at_utc": "2026-10-10T19:00:00Z"},
    {"pinned_at_utc": "2026-10-10T20:01:00Z"},
    {"expires_at_utc": "2026-10-12T21:00:00Z"},
])
def test_pin_digest_anchor_container_and_window_fail_closed(tmp_path: Path, mutation: dict[str, str]) -> None:
    raw, destination, observation = fixture(tmp_path)
    document = json.loads(raw)
    document.update(mutation)
    changed = canonical(document)
    with pytest.raises(PinRefused):
        verify_target_pin(changed, expected_sha256=hashlib.sha256(changed).hexdigest(),
                          expected_content_anchor_sha256=ANCHOR,
                          destination_root=destination, observation=observation, now=NOW)
    with pytest.raises(PinRefused):
        verify_target_pin(raw, expected_sha256="f" * 64,
                          expected_content_anchor_sha256=ANCHOR,
                          destination_root=destination, observation=observation, now=NOW)


def test_symlink_parent_refused(tmp_path: Path) -> None:
    raw, destination, observation = fixture(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(destination, target_is_directory=True)
    with pytest.raises(PinRefused):
        verify_target_pin(raw, expected_sha256=hashlib.sha256(raw).hexdigest(),
                          expected_content_anchor_sha256=ANCHOR,
                          destination_root=alias, observation=observation, now=NOW)


def test_native_or_different_postgres_refused_even_when_dsn_connects() -> None:
    inspected = {
        "Id": CONTAINER, "State": {"Running": True},
        "NetworkSettings": {"Networks": {"rag": {"IPAddress": "172.19.0.4"}}},
        "HostConfig": {"NetworkMode": "rag"},
    }
    inspected["NetworkSettings"]["SandboxKey"] = "/var/run/docker/netns/rag-pin"
    inspected["NetworkSettings"]["Ports"] = {
        "5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "15432"}],
    }
    verify_docker_postgres_binding(
        inspected, CONTAINER, "172.19.0.4", 5432, "127.0.0.1", 15432,
    )
    for server_ip in (None, "127.0.0.1", "172.19.0.5"):
        with pytest.raises(PinRefused):
            verify_docker_postgres_binding(
                inspected, CONTAINER, server_ip, 5432, "127.0.0.1", 15432,
            )
    with pytest.raises(PinRefused):
        verify_docker_postgres_binding(
            inspected, "f" * 64, "172.19.0.4", 5432, "127.0.0.1", 15432,
        )
    with pytest.raises(PinRefused):
        verify_docker_postgres_binding(
            {**inspected, "State": {"Running": False}}, CONTAINER,
            "172.19.0.4", 5432, "127.0.0.1", 15432,
        )


def test_duplicate_bridge_ip_cannot_borrow_foreign_containers_port() -> None:
    pinned = {
        "Id": CONTAINER, "State": {"Running": True},
        "HostConfig": {"NetworkMode": "network_a"},
        "NetworkSettings": {
            "SandboxKey": "/var/run/docker/netns/network_a",
            "Networks": {"network_a": {"IPAddress": "172.19.0.4"}},
            "Ports": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "15432"}]},
        },
    }
    foreign = {
        "Id": "f" * 64, "State": {"Running": True},
        "HostConfig": {"NetworkMode": "network_b"},
        "NetworkSettings": {
            "SandboxKey": "/var/run/docker/netns/network_b",
            "Networks": {"network_b": {"IPAddress": "172.19.0.4"}},
            "Ports": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "15433"}]},
        },
    }
    assert foreign["NetworkSettings"]["Networks"]["network_b"]["IPAddress"] == (
        pinned["NetworkSettings"]["Networks"]["network_a"]["IPAddress"]
    )
    with pytest.raises(PinRefused):
        verify_docker_postgres_binding(
            pinned, CONTAINER, "172.19.0.4", 5432, "127.0.0.1", 15433,
        )
    verify_docker_postgres_binding(
        pinned, CONTAINER, "172.19.0.4", 5432, "127.0.0.1", 15432,
    )
    with pytest.raises(PinRefused):
        verify_docker_postgres_binding(
            {**pinned, "NetworkSettings": {**pinned["NetworkSettings"], "Ports": {}}},
            CONTAINER, "172.19.0.4", 5432, "127.0.0.1", 15432,
        )
    with pytest.raises(PinRefused):
        verify_docker_postgres_binding(
            {**pinned, "NetworkSettings": {
                **pinned["NetworkSettings"],
                "Ports": {"5432/tcp": [{"HostIp": "0.0.0.0", "HostPort": "15432"}]},
            }},
            CONTAINER, "172.19.0.4", 5432, "127.0.0.1", 15432,
        )
    with pytest.raises(PinRefused):
        verify_docker_postgres_binding(
            {**pinned, "HostConfig": {"NetworkMode": f"container:{foreign['Id']}"}},
            CONTAINER, "172.19.0.4", 5432, "127.0.0.1", 15432,
        )


@pytest.mark.parametrize("dsn", [
    "host=172.19.0.4 port=5432 dbname=nexus_rag",
    "host=localhost port=15432 dbname=nexus_rag",
    "host=127.0.0.1,127.0.0.2 port=15432 dbname=nexus_rag",
    "host=/var/run/postgresql port=15432 dbname=nexus_rag",
    "host=127.0.0.1 hostaddr=172.19.0.4 port=15432 dbname=nexus_rag",
    "host=127.0.0.1 service=foreign port=15432 dbname=nexus_rag",
])
def test_ambiguous_or_foreign_dsn_refused(dsn: str) -> None:
    with pytest.raises(PinRefused):
        parse_qualified_dsn_endpoint(dsn)


def test_tcp_peer_endpoint_is_observed_from_real_socket() -> None:
    with socket.create_server(("127.0.0.1", 0)) as server:
        with socket.create_connection(server.getsockname()) as client:
            accepted, _ = server.accept()
            with accepted:
                connection = types.SimpleNamespace(
                    pgconn=types.SimpleNamespace(socket=client.fileno())
                )
                assert observed_peer_endpoint(connection) == server.getsockname()


@pytest.mark.parametrize("decision_mutation", [
    {"approved": False}, {"reviewer": "other"}, {"head_sha": HEAD},
    {"base_sha": HEAD}, {"challenge": "stale"}, {"review_id": None},
])
def test_untrusted_or_stale_review_refused(tmp_path: Path, decision_mutation: dict[str, object]) -> None:
    raw, _, _ = fixture(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    pin_path = Path("governance/staging_target_pins/target.json")
    (repo / pin_path).parent.mkdir(parents=True)
    (repo / pin_path).write_bytes(raw)
    subprocess.run(["git", "-C", str(repo), "add", str(pin_path)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-qm", "pin"], check=True)
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    decision = {
        "approved": True, "repository": "cyranoaladin/RAG", "pull_request": 999,
        "base_sha": BASE, "head_sha": head, "reviewer": "abenrhouma",
        "review_id": 42, "challenge": "NEXUS-TRUSTED-REVIEW-V1:fixture",
    }
    decision.update(decision_mutation)
    with pytest.raises(PinRefused):
        approved_pin_sha256(
            repo, pin_path, raw, decision=decision,
            challenges={"abenrhouma": "NEXUS-TRUSTED-REVIEW-V1:fixture"},
            expected_base_sha=BASE, expected_head_sha=head, pull_request=999,
        )


def test_github_transport_failure_refuses_without_leaking_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    raw, destination, observation = fixture(tmp_path)
    current = datetime.now(UTC)
    document = json.loads(raw)
    document["pinned_at_utc"] = (current - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    document["expires_at_utc"] = (current + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    raw = canonical(document)
    root = tmp_path / "repo"
    pin_path = Path("governance/staging_target_pins/target.json")
    (root / pin_path).parent.mkdir(parents=True)
    (root / pin_path).write_bytes(raw)
    monkeypatch.setenv("NEXUS_TEST_READONLY_DSN", "private-dsn-never-print")
    monkeypatch.setattr("independent_staging_target_pin.observe_live_target",
                        lambda **_: observation)
    module = types.ModuleType("trusted_human_review_github")
    calls: list[bool] = []

    def unavailable(**_: object) -> None:
        calls.append(True)
        raise RuntimeError("private-dsn-never-print")

    module.check_github_review = unavailable  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "trusted_human_review_github", module)
    result = main([
        "verify", "--repository-root", str(root), "--pin-path", str(pin_path),
        "--content-anchor-sha256", ANCHOR,
        "--destination-root", str(destination),
        "--database-dsn-env", "NEXUS_TEST_READONLY_DSN", "--pull-request", "999",
        "--expected-base-sha", BASE, "--expected-head-sha", HEAD,
    ])
    captured = capsys.readouterr()
    assert result == 1
    assert calls == [True]
    assert "private-dsn-never-print" not in captured.err + captured.out


def test_replaced_directory_same_realpath_cannot_reuse_pin(tmp_path: Path) -> None:
    raw, destination, observation = fixture(tmp_path)
    replacement = tmp_path / "previous"
    destination.rename(replacement)
    destination.mkdir()
    assert destination.stat().st_ino != replacement.stat().st_ino
    with pytest.raises(PinRefused):
        verify_target_pin(raw, expected_sha256=hashlib.sha256(raw).hexdigest(),
                          expected_content_anchor_sha256=ANCHOR,
                          destination_root=destination, observation=observation, now=NOW)


def test_sql_identity_functions_are_schema_qualified() -> None:
    import independent_staging_target_pin as module  # noqa: PLC0415

    sql = getattr(module, "IDENTITY_SQL", "")
    assert "pg_catalog.pg_control_system()" in sql
    assert "pg_catalog.current_database()" in sql
    assert "pg_catalog.inet_server_addr()" in sql
    assert "::pg_catalog.text" in sql


def test_capture_output_does_not_follow_broken_symlink_or_parent(
    tmp_path: Path,
) -> None:
    import independent_staging_target_pin as module  # noqa: PLC0415

    outside = tmp_path / "outside.json"
    link = tmp_path / "link.json"
    link.symlink_to(outside)
    with pytest.raises(PinRefused):
        module._write_new_file(link, b"unapproved pin")
    assert not outside.exists()
    real_parent = tmp_path / "parent"
    real_parent.mkdir()
    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(PinRefused):
        module._write_new_file(parent_link / "pin.json", b"unapproved pin")
    assert not (real_parent / "pin.json").exists()


def test_capture_output_is_removed_after_failed_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import independent_staging_target_pin as module  # noqa: PLC0415

    output = tmp_path / "pin.json"
    monkeypatch.setattr(module.os, "fsync", lambda _: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(PinRefused):
        module._write_new_file(output, b"partial")
    assert not output.exists()


def test_expiry_after_github_replay_refuses_final_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    import independent_staging_target_pin as module  # noqa: PLC0415
    from trusted_human_review import TrustedReviewDecision  # noqa: PLC0415

    raw, destination, observation = fixture(tmp_path)
    root = tmp_path / "repo"
    pin_path = Path("governance/staging_target_pins/target.json")
    (root / pin_path).parent.mkdir(parents=True)
    (root / pin_path).write_bytes(raw)
    monkeypatch.setenv("NEXUS_TEST_READONLY_DSN", "unused")
    monkeypatch.setattr(module, "observe_live_target", lambda **_: observation)
    monkeypatch.setattr(module, "approved_pin_sha256", lambda *_, **__: hashlib.sha256(raw).hexdigest())
    times = iter((NOW, NOW + timedelta(hours=3)))

    class Clock:
        @staticmethod
        def now(_: object) -> datetime:
            return next(times)

        @staticmethod
        def fromisoformat(value: str) -> datetime:
            return datetime.fromisoformat(value)

    monkeypatch.setattr(module, "datetime", Clock)
    github = types.ModuleType("trusted_human_review_github")
    github.check_github_review = lambda **_: types.SimpleNamespace(  # type: ignore[attr-defined]
        decision=TrustedReviewDecision(
            approved=True, reason="approved", repository="cyranoaladin/RAG",
            pull_request=999, base_sha=BASE, head_sha=HEAD, reviewer="abenrhouma",
            review_id=42, submitted_at="2026-10-10T19:00:00Z", challenge="test",
        ), challenges={"abenrhouma": "test"},
    )
    monkeypatch.setitem(sys.modules, "trusted_human_review_github", github)
    result = main([
        "verify", "--repository-root", str(root), "--pin-path", str(pin_path),
        "--content-anchor-sha256", ANCHOR, "--destination-root", str(destination),
        "--database-dsn-env", "NEXUS_TEST_READONLY_DSN", "--pull-request", "999",
        "--expected-base-sha", BASE, "--expected-head-sha", HEAD,
    ])
    output = capsys.readouterr()
    assert result == 1
    assert "EXPECTED_TARGET_PIN_SHA256=" not in output.out
