from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_chroma_to_pgvector.py"
EXPECTED_STDERR = (
    "Migration directe ChromaDB vers pgvector desactivee : "
    "utilisez la preparation de convergence gouvernee.\n"
)
SECRET_CANARY = "postgresql://canary-user:canary-secret@invalid.example/rag"


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--option-inconnue"],
        ["--pg-dsn", SECRET_CANARY, "--tenant", "canary-tenant"],
    ],
)
def test_tombstone_refuses_every_invocation_without_echoing_arguments(
    arguments: list[str],
) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=3,
    )

    assert result.returncode == 78
    assert result.stdout == ""
    assert result.stderr == EXPECTED_STDERR
    assert all(argument not in result.stderr for argument in arguments)


def test_tombstone_message_is_constant_in_ascii_locale() -> None:
    environment = dict(
        os.environ,
        LC_ALL="C",
        PYTHONCOERCECLOCALE="0",
        PYTHONUTF8="0",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        check=False,
        capture_output=True,
        env=environment,
        timeout=3,
    )

    assert result.returncode == 78
    assert result.stdout == b""
    assert result.stderr == EXPECTED_STDERR.encode("ascii")


def test_tombstone_contains_no_migration_or_connection_primitive() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.partition(".")[0])
    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    called_names = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute | ast.Name)
    }
    sys_argv_accesses = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
    }

    assert imported_roots <= {"__future__", "sys"}
    assert "migrate" not in function_names
    assert "INSERT" not in source.upper()
    assert "__import__" not in source
    assert "argv" not in sys_argv_accesses
    assert called_names.isdisjoint(
        {"connect", "create_pool", "HttpClient", "PersistentClient", "open", "socket"}
    )
