"""Tests des attestations PostgreSQL partagées par la readiness v2."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.ingestor import readiness_db


class _FakeCursor:
    def __init__(self, row: object) -> None:
        self._row = row
        self.query = ""

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str) -> None:
        self.query = query

    def fetchone(self) -> object:
        return self._row


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self._cursor


def test_auxiliary_relation_predicate_uses_an_explicit_safe_allowlist() -> None:
    sql = readiness_db.no_auxiliary_relation_privileges_sql(
        (("public", "rag_chunks"), ("public", "rag_schema_migrations"))
    )

    normalized = sql.upper()
    assert normalized.lstrip().startswith("NOT EXISTS")
    assert "('PUBLIC', 'RAG_CHUNKS')" in normalized
    assert "('PUBLIC', 'RAG_SCHEMA_MIGRATIONS')" in normalized
    assert "HAS_TABLE_PRIVILEGE" in normalized
    assert "HAS_ANY_COLUMN_PRIVILEGE" in normalized
    assert "HAS_SEQUENCE_PRIVILEGE" in normalized
    assert "MAINTAIN" not in normalized  # PostgreSQL 16 ne supporte pas ce droit.


@pytest.mark.parametrize(
    "allowlist",
    (
        (),
        (("public", "rag_chunks"), ("public", "rag_chunks")),
        (("public;drop schema public", "rag_chunks"),),
        (("public", "rag-chunks"),),
    ),
)
def test_auxiliary_relation_predicate_rejects_unsafe_allowlists(
    allowlist: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(ValueError, match="allowlist"):
        readiness_db.no_auxiliary_relation_privileges_sql(allowlist)


def test_security_definer_predicate_rejects_every_executable_user_routine() -> None:
    sql = readiness_db.no_executable_security_definer_routines_sql()

    normalized = sql.upper()
    assert normalized.lstrip().startswith("NOT EXISTS")
    assert "PG_PROC" in normalized
    assert "PROSECDEF" in normalized
    assert "PROKIND" not in normalized
    assert "HAS_FUNCTION_PRIVILEGE" in normalized
    assert "'EXECUTE'" in normalized
    assert "PRIVILEGED_ROUTINE.OID >= 16384" in normalized
    assert "NSPNAME NOT IN" not in normalized


def test_user_schema_predicate_rejects_effective_create_and_ownership() -> None:
    sql = readiness_db.no_user_schema_create_privileges_sql()

    normalized = sql.upper()
    assert normalized.lstrip().startswith("NOT EXISTS")
    assert "PG_NAMESPACE" in normalized
    assert "HAS_SCHEMA_PRIVILEGE" in normalized
    assert "'CREATE'" in normalized
    assert "PG_HAS_ROLE" in normalized
    assert "NSPOWNER" in normalized
    assert "INFORMATION_SCHEMA" in normalized
    assert "NOT LIKE E'PG\\\\_%' ESCAPE E'\\\\'" in normalized


def test_postgres_database_identity_is_bounded_read_only_and_cluster_specific(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _FakeCursor(("7549392456182038712", "nexus"))
    observed: dict[str, object] = {}

    def connect(dsn: str, **kwargs: object) -> _FakeConnection:
        observed.update({"dsn": dsn, **kwargs})
        return _FakeConnection(cursor)

    monkeypatch.setattr(
        readiness_db,
        "psycopg",
        SimpleNamespace(connect=connect),
        raising=False,
    )

    identity = readiness_db.postgres_database_identity("postgresql://runtime")

    assert identity == ("7549392456182038712", "nexus")
    assert observed == {
        "dsn": "postgresql://runtime",
        "connect_timeout": readiness_db.READINESS_CONNECT_TIMEOUT_S,
        "options": readiness_db.readiness_connection_options(),
    }
    assert "pg_control_system()" in cursor.query
    assert "current_database()" in cursor.query


@pytest.mark.parametrize(
    "row",
    (None, (None, "nexus"), ("123", ""), ("123",), ("123", "nexus", "extra")),
)
def test_postgres_database_identity_rejects_incomplete_results(
    monkeypatch: pytest.MonkeyPatch,
    row: object,
) -> None:
    cursor = _FakeCursor(row)
    monkeypatch.setattr(
        readiness_db,
        "psycopg",
        SimpleNamespace(
            connect=lambda *_args, **_kwargs: _FakeConnection(cursor),
        ),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="database identity unavailable"):
        readiness_db.postgres_database_identity("postgresql://runtime")


def test_shared_readiness_budget_shrinks_every_database_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr(readiness_db.time, "monotonic", lambda: now[0])

    with readiness_db.readiness_database_budget() as deadline:
        assert deadline == 107.0
        now[0] = 104.5
        assert readiness_db.remaining_readiness_budget_ms() == 2500
        assert readiness_db.readiness_connect_timeout_s() == 2
        assert "statement_timeout=2500" in readiness_db.readiness_connection_options()

        now[0] = 105.1
        with pytest.raises(RuntimeError, match="budget exhausted"):
            readiness_db.readiness_connect_timeout_s()

        now[0] = 107.1
        with pytest.raises(RuntimeError, match="budget exhausted"):
            readiness_db.remaining_readiness_budget_ms()

    assert (
        readiness_db.remaining_readiness_budget_ms()
        == readiness_db.READINESS_AGGREGATE_BUDGET_MS
    )


@pytest.mark.parametrize(
    ("review_acquires_challenge", "expected"),
    ((False, True), (True, False)),
)
def test_live_instance_challenge_rejects_a_split_database(
    monkeypatch: pytest.MonkeyPatch,
    review_acquires_challenge: bool,
    expected: bool,
) -> None:
    class _ChallengeCursor:
        def __init__(self, *, acquires_challenge: bool) -> None:
            self.acquires_challenge = acquires_challenge
            self.row: object = None
            self.queries: list[str] = []

        def __enter__(self) -> _ChallengeCursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, query: str, _params: object = None) -> None:
            self.queries.append(query)
            if "pg_control_system" in query:
                self.row = ("cluster-1", "nexus")
            elif "pg_try_advisory_lock" in query:
                self.row = (self.acquires_challenge,)
            elif "pg_advisory_unlock" in query:
                self.row = (True,)

        def fetchone(self) -> object:
            return self.row

    class _ChallengeConnection:
        def __init__(self, cursor: _ChallengeCursor) -> None:
            self._cursor = cursor

        def __enter__(self) -> _ChallengeConnection:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def cursor(self) -> _ChallengeCursor:
            return self._cursor

    reader = _ChallengeCursor(acquires_challenge=True)
    reviewer = _ChallengeCursor(acquires_challenge=review_acquires_challenge)
    connections = iter((_ChallengeConnection(reader), _ChallengeConnection(reviewer)))
    monkeypatch.setattr(
        readiness_db,
        "psycopg",
        SimpleNamespace(connect=lambda *_args, **_kwargs: next(connections)),
    )
    monkeypatch.setattr(readiness_db.secrets, "randbits", lambda _bits: 4242)

    assert (
        readiness_db.postgres_database_authorities_share_instance(
            "postgresql://reader",
            "postgresql://reviewer",
        )
        is expected
    )
    assert any("pg_try_advisory_lock" in query for query in reader.queries)
    assert any("pg_try_advisory_lock" in query for query in reviewer.queries)
    assert any("pg_advisory_unlock" in query for query in reader.queries)
    assert any("pg_advisory_unlock" in query for query in reviewer.queries) is (
        review_acquires_challenge
    )
