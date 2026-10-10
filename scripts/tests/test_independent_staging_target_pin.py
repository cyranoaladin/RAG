"""Le pin de staging exige une autorité indépendante du transfert V2."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import types
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))
from independent_staging_target_pin import (  # noqa: E402
    LiveTargetObservation,
    PinRefused,
    approved_pin_sha256,
    canonical,
    main,
    verify_docker_postgres_binding,
    verify_target_pin,
)


NOW = datetime(2026, 10, 10, 20, 0, tzinfo=UTC)
ANCHOR = "a" * 64
CONTAINER = "b" * 64
HEAD = "c" * 40
BASE = "d" * 40


def fixture(tmp_path: Path) -> tuple[bytes, Path, LiveTargetObservation]:
    destination = tmp_path / "destination"
    destination.mkdir()
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
])
def test_live_identity_sabotage_refused(tmp_path: Path, field: str, value: str) -> None:
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
    }
    verify_docker_postgres_binding(inspected, CONTAINER, "172.19.0.4")
    for server_ip in (None, "127.0.0.1", "172.19.0.5"):
        with pytest.raises(PinRefused):
            verify_docker_postgres_binding(inspected, CONTAINER, server_ip)
    with pytest.raises(PinRefused):
        verify_docker_postgres_binding(inspected, "f" * 64, "172.19.0.4")
    with pytest.raises(PinRefused):
        verify_docker_postgres_binding(
            {**inspected, "State": {"Running": False}}, CONTAINER, "172.19.0.4"
        )


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
