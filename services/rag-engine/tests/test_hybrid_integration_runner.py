"""Garde-fous du runner Docker ephemere LOT40."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
RUNNER = SERVICE_ROOT / "infra" / "scripts" / "test_hybrid_integration.sh"
ROLE_PROVISIONING = (
    SERVICE_ROOT / "infra" / "postgres" / "provision_runtime_roles.sh"
)
MAKEFILE = SERVICE_ROOT / "Makefile"
INTEGRATION_TEST = SERVICE_ROOT / "tests" / "integration" / "test_lot40_hybrid_pgvector.py"
IMAGE = (
    "pgvector/pgvector:pg16@sha256:"
    "00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc"
)


def _write_fake_docker(bin_dir: Path) -> Path:
    log = bin_dir.parent / "docker.log"
    state_dir = bin_dir.parent / "docker-state"
    state_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$LOT40_FAKE_DOCKER_LOG"
volume_state="$LOT40_FAKE_DOCKER_STATE/volume"
container_state="$LOT40_FAKE_DOCKER_STATE/container"
owner_key="com.nexus.lot40.owner"
last_arg="${!#:-}"
default_container_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
foreign_container_id="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
substitute_container_id="cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
default_created_at="2026-08-01T18:00:00Z"
foreign_created_at="2026-07-31T18:00:00Z"
substitute_created_at="2026-08-01T18:00:01Z"

seed_preexisting() {
  local kind="$1" state="$2" seeded="$3" name="$4"
  local enabled_var="LOT40_FAKE_PREEXISTING_${kind^^}"
  local label_var="LOT40_FAKE_PREEXISTING_${kind^^}_LABEL"
  if [[ "${!enabled_var:-0}" == 1 && ! -e "$seeded" ]]; then
    touch "$seeded"
    if [[ "$kind" == "volume" ]]; then
      printf '%s|%s' "${!label_var:-}" "$foreign_created_at" > "$state"
    else
      printf '%s|/%s|%s' \
        "$foreign_container_id" "$name" "${!label_var:-}" > "$state"
    fi
  fi
}

label_from_args() {
  local previous="" argument
  for argument in "$@"; do
    if [[ "$previous" == "--label" && "$argument" == "$owner_key="* ]]; then
      printf '%s' "${argument#*=}"
      return 0
    fi
    previous="$argument"
  done
  return 1
}

increment_counter() {
  local counter_file="$1" count=0
  if [[ -f "$counter_file" ]]; then count="$(cat "$counter_file")"; fi
  count=$((count + 1))
  printf '%s' "$count" > "$counter_file"
  printf '%s' "$count"
}

inspect_resource() {
  local kind="$1" target="$2" state="$3" absent="$4"
  shift 4
  local error_var="LOT40_FAKE_${kind^^}_INSPECT_ERROR"
  local raw label fingerprint count
  seed_preexisting "$kind" "$state" \
    "$LOT40_FAKE_DOCKER_STATE/${kind}-seeded" "$target"
  if [[ "${!error_var:-0}" == 1 && -e "$state" ]]; then
    printf '%s\\n' 'Error response from daemon: ownership inspect unavailable' >&2
    exit 66
  fi
  if [[ -e "$state" ]]; then
    raw="$(cat "$state")"
    if [[ "$kind" == "container" ]]; then
      IFS='|' read -r current_id current_name label <<< "$raw"
      if [[ "$target" != "${current_name#/}" && "$target" != "$current_id" ]]; then
        printf '%s\\n' "Error response from daemon: No such container: $target" >&2
        exit 1
      fi
      if [[ " $* " == *" --format "* ]]; then
        count="$(increment_counter "$LOT40_FAKE_DOCKER_STATE/container-inspects")"
        if [[ "${LOT40_SUBSTITUTE_CONTAINER_BEFORE_CLEANUP:-0}" == 1 \
           && "$count" == 2 ]]; then
          printf '%s|%s|%s' "$substitute_container_id" "$current_name" "$label" \
            > "$state"
          if [[ "$target" == "$current_id" ]]; then
            printf '%s\\n' "Error response from daemon: No such container: $target" >&2
            exit 1
          fi
          raw="$(cat "$state")"
          IFS='|' read -r current_id current_name label <<< "$raw"
        fi
        if [[ " $* " == *".Id"* ]]; then
          printf '%s\\n' "$raw"
        else
          printf '%s\\n' "$label"
        fi
      else
        printf '%s\\n' '{}'
      fi
    else
      IFS='|' read -r label fingerprint <<< "$raw"
      if [[ " $* " == *" --format "* ]]; then
        count="$(increment_counter "$LOT40_FAKE_DOCKER_STATE/volume-inspects")"
        if [[ "${LOT40_SUBSTITUTE_VOLUME_BEFORE_CLEANUP:-0}" == 1 \
           && "$count" == 2 ]]; then
          printf '%s|%s' "$label" "$substitute_created_at" > "$state"
          fingerprint="$substitute_created_at"
        fi
        if [[ " $* " == *".CreatedAt"* ]]; then
          printf '%s|%s\\n' "$label" "$fingerprint"
        else
          printf '%s\\n' "$label"
        fi
      else
        printf '%s\\n' '{}'
      fi
    fi
    exit 0
  fi
  printf '%s\\n' "$absent" >&2
  exit 1
}
case "${1:-}" in
  volume)
    case "${2:-}" in
      create)
        [[ "$last_arg" =~ ^lot40-pg-volume-[A-Za-z0-9_.-]+$ ]] || exit 91
        owner="$(label_from_args "$@")" || exit 107
        [[ "$owner" =~ ^[0-9a-f]{32}$ ]] || exit 108
        [[ "$owner" != "${last_arg#lot40-pg-volume-}" ]] || exit 109
        if [[ "${LOT40_FAIL_VOLUME_CREATE_BEFORE_CREATE:-0}" == 1 ]]; then exit 77; fi
        if [[ "${LOT40_RACE_VOLUME_WRONG_LABEL:-0}" == 1 ]]; then
          printf '%s|%s' old-owner "$foreign_created_at" > "$volume_state"
          printf '%s\\n' "$last_arg"
          exit 0
        fi
        printf '%s|%s' "$owner" "$default_created_at" > "$volume_state"
        if [[ "${LOT40_FAIL_VOLUME_CREATE:-0}" == 1 ]]; then exit 77; fi
        printf '%s\\n' "$last_arg"
        ;;
      rm)
        [[ "$last_arg" =~ ^lot40-pg-volume-[A-Za-z0-9_.-]+$ ]] || exit 92
        if [[ ! -e "$volume_state" ]]; then
          printf '%s\\n' "${LOT40_FAKE_VOLUME_ABSENT_MESSAGE:-Error response from daemon: get ${last_arg}: no such volume}" >&2
          exit 1
        fi
        if [[ "${LOT40_FAKE_LEAK_VOLUME:-0}" != 1 ]]; then rm -f "$volume_state"; fi
        ;;
      inspect)
        [[ "$last_arg" =~ ^lot40-pg-volume-[A-Za-z0-9_.-]+$ ]] || exit 103
        inspect_resource volume "$last_arg" "$volume_state" \
          "${LOT40_FAKE_VOLUME_ABSENT_MESSAGE:-Error response from daemon: get ${last_arg}: no such volume}" "$@"
        ;;
      *) exit 93 ;;
    esac
    ;;
  run)
    args=" $* "
    [[ "$args" == *" --name lot40-pg-"* ]] || exit 94
    [[ "$args" == *" -p 127.0.0.1::5432 "* ]] || exit 95
    [[ "$args" == *" -e POSTGRES_HOST_AUTH_METHOD=trust "* ]] || exit 96
    [[ "$args" == *"/postgres/init.sql:/docker-entrypoint-initdb.d/00_init.sql:ro"* ]] || exit 106
    [[ "$args" == *" ${LOT40_EXPECTED_IMAGE} "* ]] || exit 97
    owner="$(label_from_args "$@")" || exit 109
    container_name=""
    previous=""
    for argument in "$@"; do
      if [[ "$previous" == "--name" ]]; then container_name="$argument"; fi
      previous="$argument"
    done
    [[ "$owner" =~ ^[0-9a-f]{32}$ ]] || exit 110
    [[ "$owner" != "${container_name#lot40-pg-}" ]] || exit 111
    if [[ "${LOT40_FAIL_RUN_BEFORE_CREATE:-0}" == 1 ]]; then exit 78; fi
    if [[ "${LOT40_RACE_CONTAINER_WRONG_LABEL:-0}" == 1 ]]; then
      printf '%s|/%s|%s' "$foreign_container_id" "$container_name" old-owner \
        > "$container_state"
      exit 78
    fi
    printf '%s|/%s|%s' "$default_container_id" "$container_name" "$owner" \
      > "$container_state"
    if [[ "${LOT40_FAIL_RUN:-0}" == 1 ]]; then exit 78; fi
    if [[ "${LOT40_RUN_RETURN_WRONG_ID:-0}" == 1 ]]; then
      printf '%s\\n' "$foreign_container_id"
    else
      printf '%s\\n' "$default_container_id"
    fi
    ;;
  exec)
    target="${2:-}"
    [[ "$target" =~ ^[0-9a-f]{64}$ ]] || exit 98
    if [[ " $* " == *" pg_isready "* ]]; then
      exit 1
    fi
    exit 99
    ;;
  rm)
    [[ "${2:-}" == "-f" ]] || exit 100
    [[ "${3:-}" =~ ^[0-9a-f]{64}$ ]] || exit 101
    if [[ ! -e "$container_state" ]]; then
      printf '%s\\n' "${LOT40_FAKE_CONTAINER_ABSENT_MESSAGE:-Error response from daemon: No such container: ${3:-}}" >&2
      exit 1
    fi
    raw="$(cat "$container_state")"
    current_id="${raw%%|*}"
    if [[ "${3:-}" != "$current_id" ]]; then
      printf '%s\\n' "Error response from daemon: No such container: ${3:-}" >&2
      exit 1
    fi
    if [[ "${LOT40_FAKE_LEAK_CONTAINER:-0}" != 1 ]]; then rm -f "$container_state"; fi
    ;;
  container)
    [[ "${2:-}" == "inspect" ]] || exit 104
    [[ "$last_arg" =~ ^lot40-pg-[A-Za-z0-9_.-]+$ \
       || "$last_arg" =~ ^[0-9a-f]{64}$ ]] || exit 105
    inspect_resource container "$last_arg" "$container_state" \
      "${LOT40_FAKE_CONTAINER_ABSENT_MESSAGE:-Error response from daemon: No such container: ${last_arg}}" "$@"
    ;;
  *) exit 102 ;;
esac
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return log


def _fake_env(bin_dir: Path, log: Path, **overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "LOT40_FAKE_DOCKER_LOG": str(log),
            "LOT40_FAKE_DOCKER_STATE": str(bin_dir.parent / "docker-state"),
            "LOT40_EXPECTED_IMAGE": IMAGE,
            **overrides,
        }
    )
    return env


def test_runner_timeout_is_bounded_sanitized_and_cleans_exact_resources(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _write_fake_docker(bin_dir)
    env = _fake_env(
        bin_dir,
        log,
        LOT40_PG_READY_ATTEMPTS="2",
        LOT40_PG_READY_DELAY_S="0",
    )

    result = subprocess.run(
        ["bash", str(RUNNER)],
        cwd=SERVICE_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "LOT40_DB_READINESS_TIMEOUT" in combined
    assert "postgresql://" not in combined
    calls = log.read_text(encoding="utf-8").splitlines()
    exec_calls = [line for line in calls if line.startswith("exec ")]
    assert len(exec_calls) == 2
    assert all(re.match(r"exec [0-9a-f]{64} ", line) for line in exec_calls)
    rm_calls = [line for line in calls if line.startswith("rm -f ")]
    volume_rm_calls = [line for line in calls if line.startswith("volume rm ")]
    assert len(rm_calls) == 1
    assert len(volume_rm_calls) == 1
    assert re.fullmatch(r"rm -f [0-9a-f]{64}", rm_calls[0])
    assert re.fullmatch(
        r"volume rm lot40-pg-volume-[A-Za-z0-9_.-]+", volume_rm_calls[0]
    )
    volume_create = next(line for line in calls if line.startswith("volume create "))
    owner_match = re.search(
        r"--label com[.]nexus[.]lot40[.]owner=([0-9a-f]{32}) "
        r"lot40-pg-volume-([A-Za-z0-9_.-]+)$",
        volume_create,
    )
    assert owner_match is not None
    owner_token, name_suffix = owner_match.groups()
    assert owner_token != name_suffix
    run_call = next(line for line in calls if line.startswith("run "))
    assert f"--label com.nexus.lot40.owner={owner_token}" in run_call
    assert owner_token not in combined
    container_inspects = [
        line for line in calls if line.startswith("container inspect ")
    ]
    volume_inspects = [line for line in calls if line.startswith("volume inspect ")]
    assert len(container_inspects) >= 5
    assert len(volume_inspects) >= 5
    assert any(".Id" in line and ".Name" in line for line in container_inspects)
    assert any(".CreatedAt" in line for line in volume_inspects)


@pytest.mark.parametrize(
    ("failure", "expected_removals"),
    [
        ("LOT40_FAIL_VOLUME_CREATE", (False, True)),
        ("LOT40_FAIL_RUN", (True, True)),
    ],
)
def test_cleanup_is_armed_before_partial_docker_creation(
    tmp_path: Path,
    failure: str,
    expected_removals: tuple[bool, bool],
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _write_fake_docker(bin_dir)
    result = subprocess.run(
        ["bash", str(RUNNER)],
        cwd=SERVICE_ROOT,
        env=_fake_env(bin_dir, log, **{failure: "1"}),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    calls = log.read_text(encoding="utf-8").splitlines()
    has_container_rm = any(line.startswith("rm -f ") for line in calls)
    has_volume_rm = any(line.startswith("volume rm ") for line in calls)
    assert (has_container_rm, has_volume_rm) == expected_removals
    if has_container_rm:
        assert any(line.startswith("container inspect ") for line in calls)
    assert any(line.startswith("volume inspect ") for line in calls)
    assert not (tmp_path / "docker-state" / "container").exists()
    assert not (tmp_path / "docker-state" / "volume").exists()


@pytest.mark.parametrize("kind", ["container", "volume"])
@pytest.mark.parametrize("label", ["", "wrong-owner"], ids=["no-label", "wrong-label"])
def test_preexisting_same_name_is_never_removed(
    tmp_path: Path,
    kind: str,
    label: str,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _write_fake_docker(bin_dir)
    result = subprocess.run(
        ["bash", str(RUNNER)],
        cwd=SERVICE_ROOT,
        env=_fake_env(
            bin_dir,
            log,
            **{
                f"LOT40_FAKE_PREEXISTING_{kind.upper()}": "1",
                f"LOT40_FAKE_PREEXISTING_{kind.upper()}_LABEL": label,
            },
        ),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert f"LOT40_{kind.upper()}_NAME_COLLISION" in result.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    assert not any(line.startswith("rm -f ") for line in calls)
    assert not any(line.startswith("volume rm ") for line in calls)
    sentinel = tmp_path / "docker-state" / kind
    assert sentinel.is_file()
    identity = sentinel.read_text(encoding="utf-8")
    if kind == "volume":
        assert identity.startswith(f"{label}|")
    else:
        assert identity.endswith(f"|{label}")


@pytest.mark.parametrize(
    ("race", "forbidden_prefix", "expected_diagnostic"),
    [
        (
            "LOT40_RACE_VOLUME_WRONG_LABEL",
            "volume rm ",
            "LOT40_VOLUME_IDENTITY_MISMATCH",
        ),
        (
            "LOT40_RACE_CONTAINER_WRONG_LABEL",
            "rm -f ",
            "LOT40_CLEANUP_CONTAINER_OWNERSHIP_MISMATCH",
        ),
    ],
)
def test_name_race_with_wrong_owner_is_never_removed(
    tmp_path: Path,
    race: str,
    forbidden_prefix: str,
    expected_diagnostic: str,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _write_fake_docker(bin_dir)
    result = subprocess.run(
        ["bash", str(RUNNER)],
        cwd=SERVICE_ROOT,
        env=_fake_env(bin_dir, log, **{race: "1"}),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert expected_diagnostic in result.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    if race == "LOT40_RACE_VOLUME_WRONG_LABEL":
        assert not any(line.startswith("run ") for line in calls)
    assert not any(line.startswith(forbidden_prefix) for line in calls)
    state_name = "volume" if "VOLUME" in expected_diagnostic else "container"
    sentinel = tmp_path / "docker-state" / state_name
    identity = sentinel.read_text(encoding="utf-8")
    if state_name == "volume":
        assert identity == "old-owner|2026-07-31T18:00:00Z"
    else:
        assert identity.endswith("|old-owner")


def test_volume_fingerprint_substitution_is_never_removed(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _write_fake_docker(bin_dir)
    result = subprocess.run(
        ["bash", str(RUNNER)],
        cwd=SERVICE_ROOT,
        env=_fake_env(
            bin_dir,
            log,
            LOT40_SUBSTITUTE_VOLUME_BEFORE_CLEANUP="1",
            LOT40_PG_READY_ATTEMPTS="1",
            LOT40_PG_READY_DELAY_S="0",
        ),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "LOT40_CLEANUP_VOLUME_IDENTITY_CHANGED" in result.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    assert not any(line.startswith("volume rm ") for line in calls)
    volume_identity = (tmp_path / "docker-state" / "volume").read_text(
        encoding="utf-8"
    )
    owner, created_at = volume_identity.split("|", 1)
    assert re.fullmatch(r"[0-9a-f]{32}", owner)
    assert created_at == "2026-08-01T18:00:01Z"


def test_container_homonym_substitution_is_never_removed(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _write_fake_docker(bin_dir)
    result = subprocess.run(
        ["bash", str(RUNNER)],
        cwd=SERVICE_ROOT,
        env=_fake_env(
            bin_dir,
            log,
            LOT40_SUBSTITUTE_CONTAINER_BEFORE_CLEANUP="1",
            LOT40_PG_READY_ATTEMPTS="1",
            LOT40_PG_READY_DELAY_S="0",
        ),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "LOT40_CLEANUP_CONTAINER_IDENTITY_CHANGED" in result.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    assert not any(line.startswith("rm -f ") for line in calls)
    container_identity = (tmp_path / "docker-state" / "container").read_text(
        encoding="utf-8"
    )
    assert container_identity.startswith("c" * 64 + "|/lot40-pg-")


def test_wrong_run_id_is_rejected_then_owned_container_is_recovered_by_id(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _write_fake_docker(bin_dir)
    result = subprocess.run(
        ["bash", str(RUNNER)],
        cwd=SERVICE_ROOT,
        env=_fake_env(bin_dir, log, LOT40_RUN_RETURN_WRONG_ID="1"),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "LOT40_CONTAINER_IDENTITY_MISMATCH" in result.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    assert f"rm -f {'a' * 64}" in calls
    assert not (tmp_path / "docker-state" / "container").exists()


@pytest.mark.parametrize(
    ("failure", "inspect_error", "diagnostic"),
    [
        (
            "LOT40_FAIL_VOLUME_CREATE",
            "LOT40_FAKE_VOLUME_INSPECT_ERROR",
            "LOT40_CLEANUP_VOLUME_INSPECT_FAILED",
        ),
        (
            "LOT40_FAIL_RUN",
            "LOT40_FAKE_CONTAINER_INSPECT_ERROR",
            "LOT40_CLEANUP_CONTAINER_INSPECT_FAILED",
        ),
    ],
)
def test_cleanup_label_inspection_error_fails_hard_without_removing_resource(
    tmp_path: Path,
    failure: str,
    inspect_error: str,
    diagnostic: str,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _write_fake_docker(bin_dir)
    result = subprocess.run(
        ["bash", str(RUNNER)],
        cwd=SERVICE_ROOT,
        env=_fake_env(bin_dir, log, **{failure: "1", inspect_error: "1"}),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert diagnostic in result.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    forbidden = "volume rm " if "VOLUME" in diagnostic else "rm -f "
    assert not any(line.startswith(forbidden) for line in calls)


def test_cleanup_confirms_not_found_and_fails_hard_on_a_real_leak(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _write_fake_docker(bin_dir)
    absent = subprocess.run(
        ["bash", str(RUNNER)],
        cwd=SERVICE_ROOT,
        env=_fake_env(bin_dir, log, LOT40_FAIL_RUN_BEFORE_CREATE="1"),
        text=True,
        capture_output=True,
        check=False,
    )
    absent_calls = log.read_text(encoding="utf-8").splitlines()
    assert absent.returncode != 0
    assert not any(line.startswith("rm -f ") for line in absent_calls)
    assert any(line.startswith("container inspect ") for line in absent_calls)
    assert "LOT40_CLEANUP_CONTAINER_" not in absent.stderr

    log.unlink()
    leaked = subprocess.run(
        ["bash", str(RUNNER)],
        cwd=SERVICE_ROOT,
        env=_fake_env(
            bin_dir,
            log,
            LOT40_FAIL_RUN="1",
            LOT40_FAKE_LEAK_CONTAINER="1",
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    assert leaked.returncode != 0
    assert "LOT40_CLEANUP_CONTAINER_LEAK" in leaked.stderr


def test_cleanup_accepts_only_exact_kind_and_name_not_found_diagnostics(
    tmp_path: Path,
) -> None:
    cases = [
        (
            {"LOT40_FAIL_RUN_BEFORE_CREATE": "1"},
            "LOT40_CLEANUP_CONTAINER_",
            False,
        ),
        (
            {"LOT40_FAIL_VOLUME_CREATE_BEFORE_CREATE": "1"},
            "LOT40_CLEANUP_VOLUME_",
            False,
        ),
        (
            {
                "LOT40_FAIL_RUN_BEFORE_CREATE": "1",
                "LOT40_FAKE_CONTAINER_ABSENT_MESSAGE": "Error: context not found",
            },
            "LOT40_CONTAINER_ABSENCE_INSPECT_FAILED",
            True,
        ),
        (
            {
                "LOT40_FAIL_RUN_BEFORE_CREATE": "1",
                "LOT40_FAKE_CONTAINER_ABSENT_MESSAGE": "Error: No such container: lot40-pg-wrong",
            },
            "LOT40_CONTAINER_ABSENCE_INSPECT_FAILED",
            True,
        ),
        (
            {
                "LOT40_FAIL_RUN_BEFORE_CREATE": "1",
                "LOT40_FAKE_CONTAINER_ABSENT_MESSAGE": "Error: no such volume: lot40-pg-wrong-kind",
            },
            "LOT40_CONTAINER_ABSENCE_INSPECT_FAILED",
            True,
        ),
        (
            {
                "LOT40_FAIL_VOLUME_CREATE_BEFORE_CREATE": "1",
                "LOT40_FAKE_VOLUME_ABSENT_MESSAGE": "Error: context not found",
            },
            "LOT40_VOLUME_ABSENCE_INSPECT_FAILED",
            True,
        ),
        (
            {
                "LOT40_FAIL_VOLUME_CREATE_BEFORE_CREATE": "1",
                "LOT40_FAKE_VOLUME_ABSENT_MESSAGE": "Error: no such volume: lot40-pg-volume-wrong",
            },
            "LOT40_VOLUME_ABSENCE_INSPECT_FAILED",
            True,
        ),
        (
            {
                "LOT40_FAIL_VOLUME_CREATE_BEFORE_CREATE": "1",
                "LOT40_FAKE_VOLUME_ABSENT_MESSAGE": "Error: No such container: lot40-pg-volume-wrong-kind",
            },
            "LOT40_VOLUME_ABSENCE_INSPECT_FAILED",
            True,
        ),
    ]
    for index, (overrides, diagnostic, expected) in enumerate(cases):
        case_root = tmp_path / f"case-{index}"
        bin_dir = case_root / "bin"
        bin_dir.mkdir(parents=True)
        log = _write_fake_docker(bin_dir)
        result = subprocess.run(
            ["bash", str(RUNNER)],
            cwd=SERVICE_ROOT,
            env=_fake_env(bin_dir, log, **overrides),
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0
        assert (diagnostic in result.stderr) is expected


@pytest.mark.parametrize(
    ("variable", "value", "diagnostic"),
    [
        ("LOT40_PG_READY_ATTEMPTS", "0", "LOT40_READY_ATTEMPTS_INVALID"),
        ("LOT40_PG_READY_ATTEMPTS", "121", "LOT40_READY_ATTEMPTS_INVALID"),
        ("LOT40_PG_READY_ATTEMPTS", "x", "LOT40_READY_ATTEMPTS_INVALID"),
        ("LOT40_PG_READY_DELAY_S", "-1", "LOT40_READY_DELAY_INVALID"),
        ("LOT40_PG_READY_DELAY_S", "10.1", "LOT40_READY_DELAY_INVALID"),
        ("LOT40_PG_READY_DELAY_S", "x", "LOT40_READY_DELAY_INVALID"),
    ],
)
def test_runner_rejects_readiness_values_before_creating_docker_resources(
    tmp_path: Path,
    variable: str,
    value: str,
    diagnostic: str,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _write_fake_docker(bin_dir)
    env = _fake_env(bin_dir, log, **{variable: value})

    result = subprocess.run(
        ["bash", str(RUNNER)],
        cwd=SERVICE_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert diagnostic in result.stderr
    assert not log.exists()


def test_runner_pins_security_bounds_and_cleanup_contract() -> None:
    content = RUNNER.read_text(encoding="utf-8")
    provisioning = ROLE_PROVISIONING.read_text(encoding="utf-8")
    assert content.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert IMAGE in content
    assert "127.0.0.1::5432" in content
    assert "POSTGRES_HOST_AUTH_METHOD=trust" in content
    assert "trap cleanup EXIT INT TERM" in content
    assert "com.nexus.lot40.owner" in content
    assert '--label "$LOT40_OWNER_LABEL"' in content
    assert "/dev/urandom" in content
    assert "LOT40_OWNER_VALUE=\"$suffix\"" not in content
    assert "LOT40_OWNER_TOKEN" in content
    assert "^[0-9a-f]{32}$" in content
    assert ".CreatedAt" in content
    assert ".Id" in content
    assert ".Name" in content
    assert 'docker rm -f "$PGVECTOR_CONTAINER_ID"' in content
    assert 'docker exec "$PGVECTOR_CONTAINER_ID"' in content
    assert 'docker port "$PGVECTOR_CONTAINER_ID"' in content
    assert "assert_resource_absent container" in content
    assert "assert_resource_absent volume" in content
    assert content.index("trap cleanup EXIT INT TERM") < content.index(
        "docker volume create"
    )
    assert content.index("assert_resource_absent container") < content.index(
        "docker volume create"
    )
    assert content.index("assert_resource_absent volume") < content.index(
        "docker volume create"
    )
    assert content.index("volume_cleanup_armed=1") < content.index(
        "docker volume create"
    )
    assert content.index("container_cleanup_armed=1") < content.index("docker run -d")
    assert "LOT40_PG_READY_ATTEMPTS:-30" in content
    assert "LOT40_PG_READY_DELAY_S:-1" in content
    assert "pg_isready --host 127.0.0.1 --port 5432" in content
    assert "postgresql://$PGVECTOR_USER@127.0.0.1:" in content
    assert "postgresql://$PGVECTOR_APP_USER@127.0.0.1:" in content
    assert "LOT40_PG_ADMIN_DSN" in content
    assert "provision_runtime_roles.sh" in content
    assert "LOGIN PASSWORD :'retrieval_password'" in provisioning
    assert "LOGIN PASSWORD :'review_password'" in provisioning
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE" in provisioning
    assert "GRANT SELECT ON TABLE rag_chunks" in provisioning
    assert provisioning.count("GRANT SELECT ON TABLE rag_schema_migrations") == 1
    assert (
        provisioning.index("GRANT SELECT ON TABLE rag_schema_migrations")
        < provisioning.index('CREATE ROLE :"review_user"')
    )
    assert "GRANT UPDATE (review_status) ON TABLE rag_chunks" in provisioning
    assert "GRANT INSERT" not in provisioning
    assert "GRANT TRUNCATE" not in provisioning
    assert '[[ "$1" =~ [Nn]o[[:space:]]such' not in content
    assert '[[ "$1" =~ [Nn]ot[[:space:]]found' not in content
    assert "rag_pgvector" not in content


def test_make_target_runs_the_dedicated_runner_after_dev_install() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert re.search(
        r"^test-integration-hybrid: install-dev\n"
        r"\tbash infra/scripts/test_hybrid_integration[.]sh$",
        content,
        re.MULTILINE,
    )


def test_runner_exercises_canonical_cycle_and_both_atomic_rollbacks() -> None:
    content = RUNNER.read_text(encoding="utf-8")
    assert "/postgres/init.sql:/docker-entrypoint-initdb.d/00_init.sql:ro" in content
    assert "BOOTSTRAP_002_UNREGISTERED=PASS" in content
    assert "ATOMIC_ADOPTION_002_ROLLBACK=PASS" in content
    assert "BOOTSTRAP_ADOPTION_002=PASS" in content
    assert "expect_failure FRESH_HEAD_003_NEGATIVE" in content
    assert "apply_pgvector_migrations.sh" in content
    assert "rollback_pgvector_migration.sh" in content
    assert "rollback_pgvector_profile_filtering.sh" in content
    assert "MIGRATION_CYCLE_001_002_003_002_001_003=PASS" in content
    assert content.count("SELECT 1 / 0;") == 3
    assert "ATOMIC_UP_ROLLBACK=PASS" in content
    assert "ATOMIC_DOWN_ROLLBACK=PASS" in content
    assert "ROLLBACK_003_DATA_GUARD=PASS" in content
    assert "MIGRATION_FINAL_HEAD_003=PASS" in content


def test_runner_invokes_only_the_lot40_real_pgvector_module() -> None:
    content = RUNNER.read_text(encoding="utf-8")
    assert (
        'PYTHONPATH="$SERVICE_ROOT/src" "$PYTEST_BIN" '
        '"$SERVICE_ROOT/tests/integration/test_lot40_hybrid_pgvector.py" -q'
        in content
    )
    assert 'PYTEST_BIN="${NEXUS_RAG_ENGINE_PYTEST:-' in content
    assert 'LOT40_PG_DSN="$LOT40_PG_DSN"' in content
    assert 'LOT40_PG_ADMIN_DSN="$LOT40_PG_ADMIN_DSN"' in content
    assert 'LOT41_PG_REVIEW_DSN="$LOT41_PG_REVIEW_DSN"' in content


def test_real_module_explains_the_exact_production_lexical_sql() -> None:
    content = INTEGRATION_TEST.read_text(encoding="utf-8")
    assert "_LEXICAL_PLAN_SQL" not in content
    assert "_DENSE_SQL," in content
    assert "_LEXICAL_SQL," in content
    assert "PgCandidateStore," in content
    assert "(QUERY, *_scope_sql_params(TARGET_COLLECTION), 50)," in content
