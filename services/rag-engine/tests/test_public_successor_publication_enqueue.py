"""La mise en file publique exige C et la population LOT42 exacte."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from ingestor.ingestion_worker import public_text_enqueue_cli as enqueue

COLLECTION = "rag_nexus_svt_premiere_specialite"
SHA = "a" * 64


def _row(number: int = 1) -> tuple[object, ...]:
    return (
        UUID(int=number), UUID(int=number + 100), UUID(int=number + 200),
        SHA, COLLECTION, UUID(int=number + 300), 1, "NEEDS_REVIEW",
        UUID(int=number + 300),
    )


def _facts(number: int = 1) -> SimpleNamespace:
    row = _row(number)
    return SimpleNamespace(par_ressource={row[1]: (row[2], row[3], row[4], "authorization")})


def test_missing_c_refuses_before_database_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        enqueue, "_verified_runtime",
        lambda _root: (_ for _ in ()).throw(ValueError("C absent")),
    )
    opened: list[object] = []
    monkeypatch.setattr(enqueue.psycopg, "connect", lambda *_args: opened.append(1))

    assert enqueue.main(["--public-successor-bundle-root", "/missing", "--expected-role", "ingestion_control_app"]) == 1
    assert opened == []


def test_other_role_refuses_before_database_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[object] = []
    monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", "postgresql://example.invalid/rag")
    monkeypatch.setattr(enqueue, "_verified_runtime", lambda _root: (
        SimpleNamespace(release_id="release", manifest_sha256=SHA),
        SimpleNamespace(
            release_id="release", content_manifest_sha256=SHA,
            subject_sha256_by_collection={f"collection_{n}": SHA for n in range(11)},
            expires_at_utc=datetime.now(UTC) + timedelta(hours=1),
        ),
        object(),
    ))
    monkeypatch.setattr(enqueue.psycopg, "connect", lambda *_args: opened.append(1))
    assert enqueue.main([
        "--public-successor-bundle-root", "/missing",
        "--expected-role", "ingestion_control_attestor",
    ]) == 1
    assert opened == []


def test_exact_lot42_row_creates_one_publication_job() -> None:
    row = _row()
    created: list[dict[str, object]] = []

    def create(_conn: object, **kwargs: object) -> tuple[UUID, bool]:
        created.append(kwargs)
        return UUID(int=999), True

    result = enqueue.enqueue_public_successor_jobs(
        object(), [row], facts=_facts(), collections={COLLECTION},
        expected_placements=1, find_or_create_job=create,
    )
    assert result == 1
    assert created == [{
        "run_id": row[5], "collection": COLLECTION,
        "job_type": "publication_resume",
        "dedup_key": f"publication:{row[0]}", "resource_id": row[1],
        "payload": {
            "resource_id": str(row[1]), "run_id": str(row[5]),
            "expected_state_version": 1,
            "publication_attestation_id": str(row[0]),
            "artifact_id": str(row[2]),
        },
    }]


@pytest.mark.parametrize("mutation", ["foreign_sha", "missing", "wrong_state", "wrong_run", "duplicate"])
def test_population_drift_refuses_before_any_job(mutation: str) -> None:
    row = list(_row())
    rows = [tuple(row)]
    if mutation == "foreign_sha":
        row[3] = "b" * 64
        rows = [tuple(row)]
    elif mutation == "missing":
        rows = []
    elif mutation == "wrong_state":
        row[7] = "RETRIEVAL_ELIGIBLE"
        rows = [tuple(row)]
    elif mutation == "wrong_run":
        row[8] = UUID(int=999)
        rows = [tuple(row)]
    else:
        rows.append(tuple(row))
    created: list[object] = []

    with pytest.raises(ValueError):
        enqueue.enqueue_public_successor_jobs(
            object(), rows, facts=_facts(), collections={COLLECTION},
            expected_placements=1,
            find_or_create_job=lambda *_args, **_kwargs: created.append(1),
        )
    assert created == []


def test_existing_job_refuses_transaction() -> None:
    with pytest.raises(ValueError, match="already exists"):
        enqueue.enqueue_public_successor_jobs(
            object(), [_row()], facts=_facts(), collections={COLLECTION},
            expected_placements=1,
            find_or_create_job=lambda *_args, **_kwargs: (UUID(int=999), False),
        )
