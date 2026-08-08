"""Black-box tests for the pgvector migration runners using command doubles.

These tests prove preflight and SQL composition/order only. Task 8 exercises the
same SQL against an ephemeral PostgreSQL/pgvector server to prove atomicity.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
INFRA_ROOT = ENGINE_ROOT / "infra"
UP_RUNNER = INFRA_ROOT / "scripts" / "apply_pgvector_migrations.sh"
DOWN_RUNNER = INFRA_ROOT / "scripts" / "rollback_pgvector_migration.sh"
PROFILE_DOWN_RUNNER = (
    INFRA_ROOT / "scripts" / "rollback_pgvector_profile_filtering.sh"
)
MIGRATIONS = INFRA_ROOT / "postgres" / "migrations"


def _digest(name: str) -> str:
    return hashlib.sha256((MIGRATIONS / name).read_bytes()).hexdigest()


def _valid_rows(head: int = 3) -> list[dict[str, object]]:
    rows = [
        {
            "version": 1,
            "file_name": "001_rag_chunks_v2_schema.sql",
            "sha256": _digest("001_rag_chunks_v2_schema.sql"),
        },
        {
            "version": 2,
            "file_name": "002_hybrid_retrieval.sql",
            "sha256": _digest("002_hybrid_retrieval.sql"),
        },
        {
            "version": 3,
            "file_name": "003_profile_filtering.sql",
            "sha256": _digest("003_profile_filtering.sql"),
        },
    ]
    return rows[:head]


@pytest.fixture
def runner_env(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_file = tmp_path / "docker-events.jsonl"
    state_file = tmp_path / "state.json"
    snapshot_root = tmp_path / "snapshots"
    snapshot_root.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import pathlib
            import sys

            args = sys.argv[1:]
            log_path = pathlib.Path(os.environ["FAKE_DOCKER_LOG"])
            state = json.loads(pathlib.Path(os.environ["FAKE_DOCKER_STATE"]).read_text())
            fail_at = os.environ.get("FAKE_DOCKER_FAIL", "")

            def record(event, stdin=""):
                with log_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"event": event, "args": args, "stdin": stdin}) + "\\n")

            if args and args[0] == "inspect":
                record("INSPECT")
                print("true")
                raise SystemExit(0)

            if args and args[0] == "cp":
                record("DOCKER_CP")
                if fail_at == "DOCKER_CP":
                    raise SystemExit(41)
                destination = pathlib.Path(args[-1])
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"fake-custom-dump")
                raise SystemExit(0)

            if not args or args[0] != "exec":
                record("UNEXPECTED")
                raise SystemExit(90)

            if "pg_dump" in args:
                record("PG_DUMP")
                if state.get("mutate_source_during_dump"):
                    pathlib.Path(state["mutation_target"]).write_text(
                        state["mutated_source_content"],
                        encoding="utf-8",
                    )
                raise SystemExit(40 if fail_at == "PG_DUMP" else 0)

            if "rm" in args:
                record("REMOVE_REMOTE_DUMP")
                raise SystemExit(0)

            if "psql" not in args:
                record("UNEXPECTED_EXEC")
                raise SystemExit(91)

            stdin = sys.stdin.read()
            if "NEXUS_READ_MIGRATION_STATE" in stdin:
                record("READ_STATE", stdin)
                print("REGISTRY_PRESENT|" + ("1" if state.get("registry_present") else "0"))
                print("RAG_CHUNKS_PRESENT|" + ("1" if state.get("rag_chunks_present") else "0"))

                for row in state.get("rows", []):
                    print("MIGRATION|{version}|{file_name}|{sha256}".format(**row))
                raise SystemExit(0)

            if "NEXUS_READ_UNREGISTERED_HYBRID_STATE" in stdin:
                record("READ_UNREGISTERED_SCHEMA", stdin)
                print(
                    "HYBRID_COLUMN_PRESENT|"
                    + ("1" if state.get("hybrid_column_present") else "0")
                )
                print(
                    "HYBRID_INDEX_PRESENT|"
                    + ("1" if state.get("hybrid_index_present") else "0")
                )
                raise SystemExit(0)

            if "DELETE FROM rag_schema_migrations" in stdin:
                if "WHERE version = 3" in stdin:
                    record("DOWN_003", stdin)
                else:
                    record("DOWN_002", stdin)
                raise SystemExit(0)

            if "INSERT INTO rag_schema_migrations" in stdin:
                if "NEXUS_ADOPT_SCHEMA_HEAD_002" in stdin:
                    record("ADOPT_002", stdin)
                    raise SystemExit(46 if fail_at == "ADOPT_002" else 0)
                if "NEXUS_ADOPT_SCHEMA_HEAD_001" in stdin:
                    record("ADOPT_001", stdin)
                    raise SystemExit(46 if fail_at == "ADOPT_001" else 0)
                version = "UNKNOWN"
                for item in args:
                    if item.startswith("migration_version="):
                        version = item.split("=", 1)[1]
                record("APPLY_" + version.zfill(3), stdin)
                raise SystemExit(0)

            marker_001 = "-- NEXUS_VALIDATE_SCHEMA_001\\n"
            marker_002 = "-- NEXUS_VALIDATE_SCHEMA_002\\n"
            marker_002_absent = "-- NEXUS_VALIDATE_SCHEMA_002_ABSENT\\n"
            marker_registry = "-- NEXUS_VALIDATE_REGISTRY\\n"

            if marker_001 in stdin and state.get("partial_001"):
                record("VALIDATE_001", stdin)
                raise SystemExit(42)
            if (
                state.get("hybrid_column_present")
                and marker_002_absent in stdin
            ) or (
                state.get("hybrid_index_present")
                and marker_002_absent in stdin
            ):
                record("VALIDATE_002_ABSENT", stdin)
                raise SystemExit(45)
            if marker_002 in stdin and state.get("partial_002"):
                record("VALIDATE_002", stdin)
                raise SystemExit(43)
            if (
                marker_registry in stdin
                and state.get("invalid_registry_contract")
            ):
                record("VALIDATE_REGISTRY", stdin)
                raise SystemExit(44)
            if marker_001 in stdin:
                record("VALIDATE_001", stdin)
                raise SystemExit(0)
            if marker_002 in stdin:
                record("VALIDATE_002", stdin)
                raise SystemExit(0)
            if marker_registry in stdin:
                record("VALIDATE_REGISTRY", stdin)
                raise SystemExit(0)

            record("UNCLASSIFIED_PSQL", stdin)
            raise SystemExit(92)
            """
        ),
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "FAKE_DOCKER_LOG": str(log_file),
            "FAKE_DOCKER_STATE": str(state_file),
            "BACKUP_ROOT": str(tmp_path / "backups"),
            "PGVECTOR_CONTAINER": "lot40-test-pgvector",
            "PGVECTOR_DB": "testdb",
            "PGVECTOR_USER": "testuser",
            "TMPDIR": str(snapshot_root),
        }
    )
    return env, state_file, log_file


def _run(
    runner_env: tuple[dict[str, str], Path, Path],
    state: dict[str, Any],
    *,
    down_argument: str | None = None,
    fail_at: str | None = None,
    runner_path: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, Any]]]:
    env, state_file, log_file = runner_env
    state_file.write_text(json.dumps(state), encoding="utf-8")
    actual_env = env.copy()
    if fail_at is not None:
        actual_env["FAKE_DOCKER_FAIL"] = fail_at
    command = [str(runner_path or UP_RUNNER)]
    if down_argument is not None:
        command = [str(runner_path or DOWN_RUNNER), down_argument]
    result = subprocess.run(
        command,
        cwd=ENGINE_ROOT,
        env=actual_env,
        text=True,
        capture_output=True,
        check=False,
    )
    events = []
    if log_file.exists():
        events = [json.loads(line) for line in log_file.read_text().splitlines()]
    return result, events


def _event_names(events: list[dict[str, Any]]) -> list[str]:
    return [str(event["event"]) for event in events]


def _event(events: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(event for event in events if event["event"] == name)


def _assert_remote_dump_was_cleaned_exactly(
    events: list[dict[str, Any]],
) -> None:
    dump_args = list(_event(events, "PG_DUMP")["args"])
    remote_dump = dump_args[dump_args.index("-f") + 1]
    cleanup = _event(events, "REMOVE_REMOTE_DUMP")
    cleanup_args = list(cleanup["args"])
    assert cleanup_args[-3:-1] == ["rm", "-f"]
    assert cleanup_args[-1] == remote_dump


def _isolated_runner(tmp_path: Path, runner_name: str) -> tuple[Path, Path]:
    isolated_infra = tmp_path / "isolated-infra"
    shutil.copytree(INFRA_ROOT, isolated_infra)
    return isolated_infra / "scripts" / runner_name, isolated_infra


def test_up_from_absent_state_backs_up_then_applies_each_atomic_transition(
    runner_env: tuple[dict[str, str], Path, Path],
) -> None:
    result, events = _run(
        runner_env,
        {"registry_present": False, "rag_chunks_present": False, "rows": []},
    )

    assert result.returncode == 0, result.stderr
    names = _event_names(events)
    assert names.index("READ_STATE") < names.index("PG_DUMP")
    assert names.index("PG_DUMP") < names.index("DOCKER_CP")
    assert names.index("DOCKER_CP") < names.index("APPLY_001")
    assert names.index("APPLY_001") < names.index("APPLY_002")
    assert names.index("APPLY_002") < names.index("APPLY_003")
    assert "BACKUP_COMPLETE" in result.stdout
    _assert_remote_dump_was_cleaned_exactly(events)
    for transition, ddl in (
        ("APPLY_001", "CREATE EXTENSION"),
        ("APPLY_002", "ADD COLUMN"),
        ("APPLY_003", "ADD COLUMN tenant"),
    ):
        event = _event(events, transition)
        stdin = str(event["stdin"])
        assert stdin.index("pg_advisory_xact_lock") < stdin.index(ddl)
        assert stdin.index(ddl) < stdin.index("INSERT INTO rag_schema_migrations")
        assert "--single-transaction" in event["args"]
        assert "ON_ERROR_STOP=1" in event["args"]


def test_up_recognizes_existing_001_only_after_exhaustive_validation(
    runner_env: tuple[dict[str, str], Path, Path],
) -> None:
    result, events = _run(
        runner_env,
        {"registry_present": False, "rag_chunks_present": True, "rows": []},
    )

    assert result.returncode == 0, result.stderr
    names = _event_names(events)
    assert names.index("READ_STATE") < names.index("VALIDATE_001")
    assert names.index("VALIDATE_001") < names.index("PG_DUMP")
    recognition = str(_event(events, "ADOPT_001")["stdin"])
    assert recognition.index("pg_advisory_xact_lock") < recognition.index(
        "SCHEMA_HEAD_001_INVALID"
    )
    assert recognition.index("SCHEMA_HEAD_001_INVALID") < recognition.index(
        "INSERT INTO rag_schema_migrations"
    )
    assert "CREATE EXTENSION" not in recognition
    assert "ADD COLUMN" not in recognition
    assert "MIGRATIONS_ADOPTED=1" in result.stdout
    assert "MIGRATIONS_APPLIED=3" in result.stdout


def test_up_adopts_exact_existing_002_atomically_without_reapplying_ddl(
    runner_env: tuple[dict[str, str], Path, Path],
) -> None:
    result, events = _run(
        runner_env,
        {
            "registry_present": False,
            "rag_chunks_present": True,
            "hybrid_column_present": True,
            "hybrid_index_present": True,
            "rows": [],
        },
    )

    assert result.returncode == 0, result.stderr
    names = _event_names(events)
    assert names.index("READ_STATE") < names.index("VALIDATE_001")
    assert names.index("VALIDATE_001") < names.index("PG_DUMP")
    assert names.index("DOCKER_CP") < names.index("ADOPT_002")
    assert "APPLY_001" not in names
    assert "APPLY_002" not in names
    assert "APPLY_003" in names
    adoption = _event(events, "ADOPT_002")
    stdin = str(adoption["stdin"])
    assert stdin.index("pg_advisory_xact_lock") < stdin.index(
        "CREATE TABLE IF NOT EXISTS rag_schema_migrations"
    )
    assert stdin.count("INSERT INTO rag_schema_migrations") == 2
    assert "CREATE EXTENSION" not in stdin
    assert "ADD COLUMN" not in stdin
    assert "--single-transaction" in adoption["args"]
    for row in _valid_rows(2):
        assert any(str(row["file_name"]) in arg for arg in adoption["args"])
        assert any(str(row["sha256"]) in arg for arg in adoption["args"])
    assert "MIGRATIONS_ADOPTED=2" in result.stdout
    assert "MIGRATIONS_APPLIED=2" in result.stdout


def test_up_adoption_002_failure_stops_without_followup_transition(
    runner_env: tuple[dict[str, str], Path, Path],
) -> None:
    result, events = _run(
        runner_env,
        {
            "registry_present": False,
            "rag_chunks_present": True,
            "hybrid_column_present": True,
            "hybrid_index_present": True,
            "rows": [],
        },
        fail_at="ADOPT_002",
    )

    assert result.returncode != 0
    names = _event_names(events)
    assert names.count("ADOPT_002") == 1
    assert "APPLY_001" not in names
    assert "APPLY_002" not in names
    assert "APPLY_003" not in names
    assert "MIGRATIONS_ADOPTED=" not in result.stdout


@pytest.mark.parametrize(
    ("rows", "diagnostic"),
    [
        (
            [
                {
                    "version": 3,
                    "file_name": "003_unknown.sql",
                    "sha256": "a" * 64,
                }
            ],
            "MIGRATION_UNKNOWN",
        ),
        (
            [
                {
                    **_valid_rows(1)[0],
                    "sha256": "0" * 64,
                }
            ],
            "MIGRATION_CHECKSUM_MISMATCH",
        ),
        (
            [_valid_rows(2)[1]],
            "MIGRATION_GAP",
        ),
    ],
)
def test_up_refuses_invalid_registry_before_backup(
    runner_env: tuple[dict[str, str], Path, Path],
    rows: list[dict[str, object]],
    diagnostic: str,
) -> None:
    result, events = _run(
        runner_env,
        {"registry_present": True, "rag_chunks_present": True, "rows": rows},
    )

    assert result.returncode != 0
    assert diagnostic in result.stderr
    assert "READ_STATE" in _event_names(events)
    assert "PG_DUMP" not in _event_names(events)


def test_up_refuses_partial_unregistered_001_before_backup(
    runner_env: tuple[dict[str, str], Path, Path],
) -> None:
    result, events = _run(
        runner_env,
        {
            "registry_present": False,
            "rag_chunks_present": True,
            "rows": [],
            "partial_001": True,
        },
    )

    assert result.returncode != 0
    assert _event_names(events)[:2] == ["INSPECT", "READ_STATE"]
    assert "VALIDATE_001" in _event_names(events)
    assert "PG_DUMP" not in _event_names(events)


def test_up_refuses_partial_registered_002_before_backup(
    runner_env: tuple[dict[str, str], Path, Path],
) -> None:
    result, events = _run(
        runner_env,
        {
            "registry_present": True,
            "rag_chunks_present": True,
            "rows": _valid_rows(2),
            "partial_002": True,
        },
    )

    assert result.returncode != 0
    names = _event_names(events)
    assert names.index("READ_STATE") < names.index("VALIDATE_002")
    assert "PG_DUMP" not in names


def test_up_refuses_invalid_registry_contract_before_backup(
    runner_env: tuple[dict[str, str], Path, Path],
) -> None:
    result, events = _run(
        runner_env,
        {
            "registry_present": True,
            "rag_chunks_present": True,
            "rows": _valid_rows(1),
            "invalid_registry_contract": True,
        },
    )

    assert result.returncode != 0
    names = _event_names(events)
    assert names.index("READ_STATE") < names.index("VALIDATE_REGISTRY")
    assert "PG_DUMP" not in names


@pytest.mark.parametrize(
    "untracked_002",
    [
        {"hybrid_column_present": True},
        {"hybrid_index_present": True},
    ],
    ids=["column-only", "index-only"],
)
def test_up_refuses_partial_unregistered_002_before_backup(
    runner_env: tuple[dict[str, str], Path, Path],
    untracked_002: dict[str, bool],
) -> None:
    state: dict[str, object] = {
        "registry_present": False,
        "rag_chunks_present": True,
        "rows": [],
        **untracked_002,
    }
    result, events = _run(runner_env, state)

    assert result.returncode != 0
    names = _event_names(events)
    assert names == ["INSPECT", "READ_STATE", "READ_UNREGISTERED_SCHEMA"]
    assert "PG_DUMP" not in names
    assert "UNREGISTERED_SCHEMA_HYBRID_OBJECTS_MISMATCH" in result.stderr


def test_up_refuses_malformed_exact_002_candidate_before_backup(
    runner_env: tuple[dict[str, str], Path, Path],
) -> None:
    result, events = _run(
        runner_env,
        {
            "registry_present": False,
            "rag_chunks_present": True,
            "hybrid_column_present": True,
            "hybrid_index_present": True,
            "partial_002": True,
            "rows": [],
        },
    )

    assert result.returncode != 0
    names = _event_names(events)
    assert names.index("READ_STATE") < names.index("VALIDATE_002")
    assert "PG_DUMP" not in names


def test_up_refuses_untracked_002_when_registry_head_is_001_before_backup(
    runner_env: tuple[dict[str, str], Path, Path],
) -> None:
    result, events = _run(
        runner_env,
        {
            "registry_present": True,
            "rag_chunks_present": True,
            "rows": _valid_rows(1),
            "hybrid_column_present": True,
            "hybrid_index_present": True,
        },
    )

    assert result.returncode != 0
    names = _event_names(events)
    assert names.index("READ_STATE") < names.index("VALIDATE_002_ABSENT")
    assert "PG_DUMP" not in names


@pytest.mark.parametrize("failure", ["PG_DUMP", "DOCKER_CP"])
def test_up_backup_failure_stops_before_mutation(
    runner_env: tuple[dict[str, str], Path, Path],
    failure: str,
) -> None:
    result, events = _run(
        runner_env,
        {"registry_present": False, "rag_chunks_present": False, "rows": []},
        fail_at=failure,
    )

    assert result.returncode != 0
    names = _event_names(events)
    assert names.index("READ_STATE") < names.index("PG_DUMP")
    assert "APPLY_001" not in names
    assert "APPLY_002" not in names
    assert "BACKUP_COMPLETE" not in result.stdout
    if failure == "DOCKER_CP":
        assert names.index("PG_DUMP") < names.index("DOCKER_CP")
    _assert_remote_dump_was_cleaned_exactly(events)
    assert not any(Path(runner_env[0]["TMPDIR"]).iterdir())


def test_down_002_backs_up_then_composes_one_atomic_transition(
    runner_env: tuple[dict[str, str], Path, Path],
) -> None:
    result, events = _run(
        runner_env,
        {
            "registry_present": True,
            "rag_chunks_present": True,
            "rows": _valid_rows(2),
        },
        down_argument="002_hybrid_retrieval",
    )

    assert result.returncode == 0, result.stderr
    names = _event_names(events)
    assert names.index("READ_STATE") < names.index("PG_DUMP")
    assert names.index("PG_DUMP") < names.index("DOCKER_CP")
    assert names.index("DOCKER_CP") < names.index("DOWN_002")
    event = _event(events, "DOWN_002")
    stdin = str(event["stdin"])
    assert stdin.index("pg_advisory_xact_lock") < stdin.index("DROP INDEX")
    assert stdin.index("DROP INDEX") < stdin.index("DROP COLUMN")
    assert stdin.index("DROP COLUMN") < stdin.index(
        "DELETE FROM rag_schema_migrations"
    )
    assert stdin.index("DELETE FROM rag_schema_migrations") < stdin.index(
        "text_tsv still present"
    )
    assert "WHERE version = 2" in stdin
    assert "--single-transaction" in event["args"]
    _assert_remote_dump_was_cleaned_exactly(events)


def test_down_003_backs_up_then_composes_one_atomic_transition(
    runner_env: tuple[dict[str, str], Path, Path],
) -> None:
    result, events = _run(
        runner_env,
        {
            "registry_present": True,
            "rag_chunks_present": True,
            "rows": _valid_rows(3),
        },
        down_argument="003_profile_filtering",
        runner_path=PROFILE_DOWN_RUNNER,
    )

    assert result.returncode == 0, result.stderr
    names = _event_names(events)
    assert names.index("READ_STATE") < names.index("PG_DUMP")
    assert names.index("DOCKER_CP") < names.index("DOWN_003")
    stdin = str(_event(events, "DOWN_003")["stdin"])
    assert stdin.index("pg_advisory_xact_lock") < stdin.index(
        "ROLLBACK_003_DATA_PRESENT"
    )
    assert stdin.index("ROLLBACK_003_DATA_PRESENT") < stdin.index("DROP INDEX")
    assert stdin.index("DROP COLUMN programme_version") < stdin.index(
        "DELETE FROM rag_schema_migrations"
    )
    assert stdin.index("DELETE FROM rag_schema_migrations") < stdin.index(
        "LOT41 columns still present"
    )
    assert "WHERE version = 3" in stdin
    _assert_remote_dump_was_cleaned_exactly(events)


def test_down_003_refuses_wrong_effective_head_before_backup(
    runner_env: tuple[dict[str, str], Path, Path],
) -> None:
    result, events = _run(
        runner_env,
        {
            "registry_present": True,
            "rag_chunks_present": True,
            "rows": _valid_rows(2),
        },
        down_argument="003_profile_filtering",
        runner_path=PROFILE_DOWN_RUNNER,
    )

    assert result.returncode != 0
    assert "ROLLBACK_HEAD_INVALID" in result.stderr
    assert "PG_DUMP" not in _event_names(events)


def test_down_refuses_non_002_argument_without_contacting_docker(
    runner_env: tuple[dict[str, str], Path, Path],
) -> None:
    result, events = _run(
        runner_env,
        {"registry_present": True, "rag_chunks_present": True, "rows": _valid_rows()},
        down_argument="001_rag_chunks_v2_schema",
    )

    assert result.returncode != 0
    assert "ROLLBACK_ARGUMENT_INVALID" in result.stderr
    assert events == []


@pytest.mark.parametrize(
    ("rows", "diagnostic"),
    [
        (_valid_rows(1), "ROLLBACK_HEAD_INVALID"),
        (
            [
                _valid_rows(2)[0],
                {**_valid_rows(2)[1], "sha256": "f" * 64},
            ],
            "MIGRATION_CHECKSUM_MISMATCH",
        ),
    ],
)
def test_down_refuses_wrong_head_or_checksum_before_backup(
    runner_env: tuple[dict[str, str], Path, Path],
    rows: list[dict[str, object]],
    diagnostic: str,
) -> None:
    result, events = _run(
        runner_env,
        {"registry_present": True, "rag_chunks_present": True, "rows": rows},
        down_argument="002_hybrid_retrieval",
    )

    assert result.returncode != 0
    assert diagnostic in result.stderr
    assert "PG_DUMP" not in _event_names(events)


@pytest.mark.parametrize("failure", ["PG_DUMP", "DOCKER_CP"])
def test_down_backup_failure_stops_before_mutation(
    runner_env: tuple[dict[str, str], Path, Path],
    failure: str,
) -> None:
    result, events = _run(
        runner_env,
        {
            "registry_present": True,
            "rag_chunks_present": True,
            "rows": _valid_rows(2),
        },
        down_argument="002_hybrid_retrieval",
        fail_at=failure,
    )

    assert result.returncode != 0
    assert "DOWN_002" not in _event_names(events)
    assert "BACKUP_COMPLETE" not in result.stdout
    _assert_remote_dump_was_cleaned_exactly(events)
    assert not any(Path(runner_env[0]["TMPDIR"]).iterdir())


def test_up_applies_immutable_snapshot_if_source_changes_during_backup(
    runner_env: tuple[dict[str, str], Path, Path],
    tmp_path: Path,
) -> None:
    runner, isolated_infra = _isolated_runner(
        tmp_path,
        "apply_pgvector_migrations.sh",
    )
    migration = (
        isolated_infra
        / "postgres"
        / "migrations"
        / "002_hybrid_retrieval.sql"
    )
    original = migration.read_text(encoding="utf-8") + "\n-- SNAPSHOT_ORIGINAL\n"
    mutation = "SELECT 'MUTATED_SOURCE';\n"
    migration.write_text(original, encoding="utf-8")

    result, events = _run(
        runner_env,
        {
            "registry_present": False,
            "rag_chunks_present": False,
            "rows": [],
            "mutate_source_during_dump": True,
            "mutation_target": str(migration),
            "mutated_source_content": mutation,
        },
        runner_path=runner,
    )

    assert result.returncode == 0, result.stderr
    apply_002 = _event(events, "APPLY_002")
    assert "SNAPSHOT_ORIGINAL" in apply_002["stdin"]
    assert "MUTATED_SOURCE" not in apply_002["stdin"]
    expected_sha = hashlib.sha256(original.encode()).hexdigest()
    assert f"migration_sha={expected_sha}" in apply_002["args"]
    assert migration.read_text(encoding="utf-8") == mutation
    assert not any(Path(runner_env[0]["TMPDIR"]).iterdir())


def test_down_applies_immutable_rollback_snapshot_if_source_changes_during_backup(
    runner_env: tuple[dict[str, str], Path, Path],
    tmp_path: Path,
) -> None:
    runner, isolated_infra = _isolated_runner(
        tmp_path,
        "rollback_pgvector_migration.sh",
    )
    rollback = (
        isolated_infra
        / "postgres"
        / "rollbacks"
        / "002_hybrid_retrieval.down.sql"
    )
    original = rollback.read_text(encoding="utf-8") + "\n-- ROLLBACK_SNAPSHOT_ORIGINAL\n"
    mutation = "DROP TABLE rag_chunks; -- MUTATED_ROLLBACK\n"
    rollback.write_text(original, encoding="utf-8")

    result, events = _run(
        runner_env,
        {
            "registry_present": True,
            "rag_chunks_present": True,
            "rows": _valid_rows(2),
            "mutate_source_during_dump": True,
            "mutation_target": str(rollback),
            "mutated_source_content": mutation,
        },
        down_argument="002_hybrid_retrieval",
        runner_path=runner,
    )

    assert result.returncode == 0, result.stderr
    down = _event(events, "DOWN_002")
    assert "ROLLBACK_SNAPSHOT_ORIGINAL" in down["stdin"]
    assert "MUTATED_ROLLBACK" not in down["stdin"]
    assert rollback.read_text(encoding="utf-8") == mutation
    assert not any(Path(runner_env[0]["TMPDIR"]).iterdir())
