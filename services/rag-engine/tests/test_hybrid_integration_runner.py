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
IMAGE = (
    "pgvector/pgvector:pg16@sha256:"
    "00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc"
)


def _write_fake_docker(bin_dir: Path) -> Path:
    log = bin_dir.parent / "docker.log"
    docker = bin_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$LOT40_FAKE_DOCKER_LOG"
case "${1:-}" in
  volume)
    case "${2:-}" in
      create)
        [[ "${3:-}" =~ ^lot40-pg-volume-[A-Za-z0-9_.-]+$ ]] || exit 91
        printf '%s\\n' "${3:-}"
        ;;
      rm)
        [[ "${3:-}" =~ ^lot40-pg-volume-[A-Za-z0-9_.-]+$ ]] || exit 92
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
    ;;
  *) exit 102 ;;
esac
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return log


def test_runner_timeout_is_bounded_sanitized_and_cleans_exact_resources(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _write_fake_docker(bin_dir)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "LOT40_FAKE_DOCKER_LOG": str(log),
            "LOT40_EXPECTED_IMAGE": IMAGE,
            "LOT40_PG_READY_ATTEMPTS": "2",
            "LOT40_PG_READY_DELAY_S": "0",
        }
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
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "LOT40_FAKE_DOCKER_LOG": str(log),
            "LOT40_EXPECTED_IMAGE": IMAGE,
            variable: value,
        }
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
    assert "LOT40_PG_READY_ATTEMPTS:-30" in content
    assert "LOT40_PG_READY_DELAY_S:-1" in content
    assert "postgresql://$PGVECTOR_USER@127.0.0.1:" in content
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
