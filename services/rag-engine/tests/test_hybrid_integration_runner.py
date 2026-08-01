"""Garde-fous du runner Docker ephemere LOT40."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
RUNNER = SERVICE_ROOT / "infra" / "scripts" / "test_hybrid_integration.sh"
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
case "${1:-}" in
  volume)
    case "${2:-}" in
      create)
        [[ "${3:-}" =~ ^lot40-pg-volume-[A-Za-z0-9_.-]+$ ]] || exit 91
        if [[ "${LOT40_FAIL_VOLUME_CREATE_BEFORE_CREATE:-0}" == 1 ]]; then exit 77; fi
        touch "$volume_state"
        if [[ "${LOT40_FAIL_VOLUME_CREATE:-0}" == 1 ]]; then exit 77; fi
        printf '%s\\n' "${3:-}"
        ;;
      rm)
        [[ "${3:-}" =~ ^lot40-pg-volume-[A-Za-z0-9_.-]+$ ]] || exit 92
        if [[ ! -e "$volume_state" ]]; then
          printf '%s\\n' "${LOT40_FAKE_VOLUME_ABSENT_MESSAGE:-Error response from daemon: get ${3:-}: no such volume}" >&2
          exit 1
        fi
        if [[ "${LOT40_FAKE_LEAK_VOLUME:-0}" != 1 ]]; then rm -f "$volume_state"; fi
        ;;
      inspect)
        [[ "${3:-}" =~ ^lot40-pg-volume-[A-Za-z0-9_.-]+$ ]] || exit 103
        if [[ -e "$volume_state" ]]; then printf '%s\\n' '{}'; exit 0; fi
        printf '%s\\n' "${LOT40_FAKE_VOLUME_ABSENT_MESSAGE:-Error response from daemon: get ${3:-}: no such volume}" >&2
        exit 1
        ;;
      *) exit 93 ;;
    esac
    ;;
  run)
    args=" $* "
    [[ "$args" == *" --name lot40-pg-"* ]] || exit 94
    [[ "$args" == *" -p 127.0.0.1::5432 "* ]] || exit 95
    [[ "$args" == *" -e POSTGRES_HOST_AUTH_METHOD=trust "* ]] || exit 96
    [[ "$args" == *" ${LOT40_EXPECTED_IMAGE} "* ]] || exit 97
    if [[ "${LOT40_FAIL_RUN_BEFORE_CREATE:-0}" == 1 ]]; then exit 78; fi
    touch "$container_state"
    if [[ "${LOT40_FAIL_RUN:-0}" == 1 ]]; then exit 78; fi
    printf '%s\\n' fake-container-id
    ;;
  exec)
    target="${2:-}"
    [[ "$target" =~ ^lot40-pg-[A-Za-z0-9_.-]+$ ]] || exit 98
    if [[ " $* " == *" pg_isready "* ]]; then
      exit 1
    fi
    exit 99
    ;;
  rm)
    [[ "${2:-}" == "-f" ]] || exit 100
    [[ "${3:-}" =~ ^lot40-pg-[A-Za-z0-9_.-]+$ ]] || exit 101
    if [[ ! -e "$container_state" ]]; then
      printf '%s\\n' "${LOT40_FAKE_CONTAINER_ABSENT_MESSAGE:-Error response from daemon: No such container: ${3:-}}" >&2
      exit 1
    fi
    if [[ "${LOT40_FAKE_LEAK_CONTAINER:-0}" != 1 ]]; then rm -f "$container_state"; fi
    ;;
  container)
    [[ "${2:-}" == "inspect" ]] || exit 104
    [[ "${3:-}" =~ ^lot40-pg-[A-Za-z0-9_.-]+$ ]] || exit 105
    if [[ -e "$container_state" ]]; then printf '%s\\n' '{}'; exit 0; fi
    printf '%s\\n' "${LOT40_FAKE_CONTAINER_ABSENT_MESSAGE:-Error response from daemon: No such container: ${3:-}}" >&2
    exit 1
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
    assert len([line for line in calls if line.startswith("exec ")]) == 2
    rm_calls = [line for line in calls if line.startswith("rm -f ")]
    volume_rm_calls = [line for line in calls if line.startswith("volume rm ")]
    assert len(rm_calls) == 1
    assert len(volume_rm_calls) == 1
    assert re.fullmatch(r"rm -f lot40-pg-[A-Za-z0-9_.-]+", rm_calls[0])
    assert re.fullmatch(
        r"volume rm lot40-pg-volume-[A-Za-z0-9_.-]+", volume_rm_calls[0]
    )
    assert len([line for line in calls if line.startswith("container inspect ")]) == 1
    assert len([line for line in calls if line.startswith("volume inspect ")]) == 1


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
    assert not any((tmp_path / "docker-state").iterdir())


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
    assert any(line.startswith("rm -f ") for line in absent_calls)
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
            "LOT40_CLEANUP_CONTAINER_INSPECT_FAILED",
            True,
        ),
        (
            {
                "LOT40_FAIL_RUN_BEFORE_CREATE": "1",
                "LOT40_FAKE_CONTAINER_ABSENT_MESSAGE": "Error: No such container: lot40-pg-wrong",
            },
            "LOT40_CLEANUP_CONTAINER_INSPECT_FAILED",
            True,
        ),
        (
            {
                "LOT40_FAIL_RUN_BEFORE_CREATE": "1",
                "LOT40_FAKE_CONTAINER_ABSENT_MESSAGE": "Error: no such volume: lot40-pg-wrong-kind",
            },
            "LOT40_CLEANUP_CONTAINER_INSPECT_FAILED",
            True,
        ),
        (
            {
                "LOT40_FAIL_VOLUME_CREATE_BEFORE_CREATE": "1",
                "LOT40_FAKE_VOLUME_ABSENT_MESSAGE": "Error: context not found",
            },
            "LOT40_CLEANUP_VOLUME_INSPECT_FAILED",
            True,
        ),
        (
            {
                "LOT40_FAIL_VOLUME_CREATE_BEFORE_CREATE": "1",
                "LOT40_FAKE_VOLUME_ABSENT_MESSAGE": "Error: no such volume: lot40-pg-volume-wrong",
            },
            "LOT40_CLEANUP_VOLUME_INSPECT_FAILED",
            True,
        ),
        (
            {
                "LOT40_FAIL_VOLUME_CREATE_BEFORE_CREATE": "1",
                "LOT40_FAKE_VOLUME_ABSENT_MESSAGE": "Error: No such container: lot40-pg-volume-wrong-kind",
            },
            "LOT40_CLEANUP_VOLUME_INSPECT_FAILED",
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
    assert content.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert IMAGE in content
    assert "127.0.0.1::5432" in content
    assert "POSTGRES_HOST_AUTH_METHOD=trust" in content
    assert "trap cleanup EXIT INT TERM" in content
    assert content.index("trap cleanup EXIT INT TERM") < content.index(
        "docker volume create"
    )
    assert content.index("volume_cleanup_armed=1") < content.index(
        "docker volume create"
    )
    assert content.index("container_cleanup_armed=1") < content.index("docker run -d")
    assert "LOT40_PG_READY_ATTEMPTS:-30" in content
    assert "LOT40_PG_READY_DELAY_S:-1" in content
    assert "postgresql://$PGVECTOR_USER@127.0.0.1:" in content
    assert "postgresql://$PGVECTOR_APP_USER@127.0.0.1:" in content
    assert "LOT40_PG_ADMIN_DSN" in content
    assert "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE" in content
    assert "GRANT SELECT ON TABLE rag_chunks" in content
    assert "GRANT INSERT" not in content
    assert "GRANT TRUNCATE" not in content
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
    assert "expect_failure FRESH_HEAD_002_NEGATIVE" in content
    assert "apply_pgvector_migrations.sh" in content
    assert "rollback_pgvector_migration.sh" in content
    assert "MIGRATION_CYCLE_001_002_001_002=PASS" in content
    assert content.count("SELECT 1 / 0;") == 2
    assert "ATOMIC_UP_ROLLBACK=PASS" in content
    assert "ATOMIC_DOWN_ROLLBACK=PASS" in content
    assert "MIGRATION_FINAL_HEAD_002=PASS" in content


def test_runner_invokes_only_the_lot40_real_pgvector_module() -> None:
    content = RUNNER.read_text(encoding="utf-8")
    assert (
        'PYTHONPATH="$SERVICE_ROOT/src" "$SERVICE_ROOT/.venv/bin/pytest" '
        '"$SERVICE_ROOT/tests/integration/test_lot40_hybrid_pgvector.py" -q'
        in content
    )
    assert 'LOT40_PG_DSN="$LOT40_PG_DSN"' in content
    assert 'LOT40_PG_ADMIN_DSN="$LOT40_PG_ADMIN_DSN"' in content


def test_real_module_explains_the_exact_production_lexical_sql() -> None:
    content = INTEGRATION_TEST.read_text(encoding="utf-8")
    assert "_LEXICAL_PLAN_SQL" not in content
    assert "_DENSE_SQL," in content
    assert "_LEXICAL_SQL," in content
    assert "PgCandidateStore," in content
    assert "(QUERY, TARGET_COLLECTION, 50)," in content
