"""Frontière de review LOT41 : identité, scope et transitions sans IDOR."""

from __future__ import annotations

from contextlib import AbstractContextManager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from nexus_contracts import Rights

from ingestor import review_v2_endpoint as review
from ingestor.retrieval_scope_v2 import ServerRetrievalScope

SCOPE = ServerRetrievalScope(
    tenant="libre_terminale",
    niveau="terminale",
    voie="generale",
    matiere="nsi",
    statut_enseignement="specialite",
    candidat="individuel",
    audiences=("libre", "tous"),
    rights=(Rights.usage_interne,),
    visibilities=("internal",),
    school_year="2026-2027",
    collection="rag_nexus_nsi_terminale_specialite",
    programme_version="BOEN_special_8_2019-07-25",
    scope_id="lot41_review_scope",
    scope_digest="a" * 64,
    source_sha256="b" * 64,
)


def _verified(role: str = "reviewer") -> SimpleNamespace:
    identity = SimpleNamespace(role=role, tenant=SCOPE.tenant)
    envelope = SimpleNamespace(
        identity=identity,
        allowed_collections=[SCOPE.collection],
    )
    return SimpleNamespace(envelope=envelope, scope_digest=SCOPE.scope_digest)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(review.router)
    return TestClient(app)


class FakeCursor:
    def __init__(self, *, rowcount: int = 0) -> None:
        self.rowcount = rowcount
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: object = ()) -> None:
        normalized = " ".join(sql.split())
        self.executions.append((normalized, tuple(params or ())))

    def fetchone(self) -> tuple[int]:
        return (0,)

    def fetchall(self) -> list[tuple[object, ...]]:
        return []


class FakeConnection(AbstractContextManager["FakeConnection"]):
    def __init__(self, *, rowcount: int = 0) -> None:
        self.cursor_spy = FakeCursor(rowcount=rowcount)
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self.cursor_spy

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed += 1


def _prepare(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rowcount: int = 0,
) -> FakeConnection:
    connection = FakeConnection(rowcount=rowcount)
    monkeypatch.setattr(review, "_require_review_identity", lambda *_a, **_k: _verified())
    monkeypatch.setattr(review, "load_collection_config", lambda: {})
    monkeypatch.setattr(review, "_resolve_review_scopes", lambda *_a, **_k: (SCOPE,))
    monkeypatch.setattr(review.psycopg, "connect", lambda *_a, **_k: connection)
    monkeypatch.setattr(review, "_get_pg_dsn", lambda: "postgresql://private")
    return connection


def test_missing_identity_stops_before_configuration_and_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        review,
        "_require_review_identity",
        lambda *_a, **_k: (_ for _ in ()).throw(
            HTTPException(status_code=401, detail="Unauthorized")
        ),
    )
    load_config = MagicMock(side_effect=AssertionError("config read before identity"))
    connect = MagicMock(side_effect=AssertionError("database read before identity"))
    monkeypatch.setattr(review, "load_collection_config", load_config)
    monkeypatch.setattr(review.psycopg, "connect", connect)

    response = _client().get("/review/v2/queue")

    assert response.status_code == 401
    load_config.assert_not_called()
    connect.assert_not_called()


def test_review_writer_dsn_is_mandatory_and_has_no_retrieval_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PG_REVIEW_DSN", raising=False)
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://select-only")
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql://owner")

    with pytest.raises(HTTPException) as exc_info:
        review._get_pg_dsn()

    assert exc_info.value.status_code == 503
    monkeypatch.setenv("PG_REVIEW_DSN", "postgresql://review-writer")
    assert review._get_pg_dsn() == "postgresql://review-writer"


def test_review_identity_rejects_non_human_review_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(review, "require_bff_service", lambda *_a, **_k: None)
    monkeypatch.setattr(review, "require_internal_identity", lambda *_a, **_k: _verified("teacher"))

    with pytest.raises(HTTPException) as exc_info:
        review._require_review_identity(MagicMock(), endpoint="/review/v2/queue")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Forbidden"


def test_collection_and_tenant_overrides_can_only_restrict_signed_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build = MagicMock(return_value=SCOPE)
    monkeypatch.setattr(review, "build_server_retrieval_scope", build)

    scopes = review._resolve_review_scopes(
        _verified(),
        collection=SCOPE.collection,
        tenant=SCOPE.tenant,
        collection_config={},
    )

    assert scopes == (SCOPE,)
    with pytest.raises(HTTPException) as collection_error:
        review._resolve_review_scopes(
            _verified(),
            collection="other_collection",
            tenant=SCOPE.tenant,
            collection_config={},
        )
    assert collection_error.value.status_code == 403
    with pytest.raises(HTTPException) as tenant_error:
        review._resolve_review_scopes(
            _verified(),
            collection=SCOPE.collection,
            tenant="other_tenant",
            collection_config={},
        )
    assert tenant_error.value.status_code == 403


def test_queue_sql_applies_every_scope_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _prepare(monkeypatch)

    response = _client().get("/review/v2/queue")

    assert response.status_code == 200
    assert len(connection.cursor_spy.executions) == 2
    for sql, params in connection.cursor_spy.executions:
        assert "collection = %s" in sql
        assert "tenant = %s" in sql
        assert "niveau = %s" in sql
        assert "voie IS NOT DISTINCT FROM %s" in sql
        assert "matiere = %s" in sql
        assert "statut_enseignement = %s" in sql
        assert "candidat = ANY(%s::text[])" in sql
        assert "audience && %s::text[]" in sql
        assert "rights = ANY(%s::text[])" in sql
        assert "visibility = ANY(%s::text[])" in sql
        assert "school_year = %s" in sql
        assert "programme_version = %s" in sql
        assert SCOPE.tenant in params
        assert SCOPE.collection in params


@pytest.mark.parametrize(
    ("decision", "expected_states"),
    [
        ("reviewed", ("needs_review",)),
        ("quarantined", ("needs_review", "reviewed")),
    ],
)
def test_decision_transitions_are_scoped_and_asymmetric(
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
    expected_states: tuple[str, ...],
) -> None:
    connection = _prepare(monkeypatch, rowcount=2)
    monkeypatch.setattr(review, "invalidate_cache", lambda: 0)

    response = _client().post(
        "/review/v2/decide",
        json={
            "target_type": "doc",
            "target_id": "doc-123",
            "decision": decision,
            "collection": SCOPE.collection,
            "tenant": SCOPE.tenant,
        },
    )

    assert response.status_code == 200
    sql, params = connection.cursor_spy.executions[0]
    assert "doc_id = %s" in sql
    assert "review_status = ANY(%s::text[])" in sql
    assert "collection = %s" in sql
    assert "tenant = %s" in sql
    assert list(expected_states) in params
    assert connection.commits == 1
    assert response.json()["cache_invalidated_this_worker"] is True
    assert response.json()["max_stale_other_workers_s"] == 0


@pytest.mark.parametrize("target_type", ["doc", "chunk"])
def test_idor_and_invalid_transition_have_the_same_generic_response(
    monkeypatch: pytest.MonkeyPatch,
    target_type: str,
) -> None:
    connection = _prepare(monkeypatch, rowcount=0)
    target_id = "private-target-that-must-not-be-reflected"

    response = _client().post(
        "/review/v2/decide",
        json={
            "target_type": target_type,
            "target_id": target_id,
            "decision": "reviewed",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "review target unavailable"}
    assert target_id not in response.text
    assert connection.commits == 1


def test_committed_decision_is_not_reported_as_failed_if_local_cache_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _prepare(monkeypatch, rowcount=1)
    monkeypatch.setattr(
        review,
        "invalidate_cache",
        MagicMock(side_effect=RuntimeError("local cache unavailable")),
    )

    response = _client().post(
        "/review/v2/decide",
        json={
            "target_type": "chunk",
            "target_id": "chunk-123",
            "decision": "quarantined",
        },
    )

    assert response.status_code == 200
    assert response.json()["cache_invalidated_this_worker"] is False
    assert response.json()["max_stale_other_workers_s"] == 0
    assert connection.commits == 1
