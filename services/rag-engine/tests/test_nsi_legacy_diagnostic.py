"""Diagnostic read-only des lignes NSI historiques et gouvernées."""

from __future__ import annotations

from typing import Any

from ingestor.nsi_legacy_diagnostic import inspect_nsi_legacy_rows


class _Result:
    def __init__(self, row: tuple[Any, ...]) -> None:
        self._row = row

    def fetchone(self) -> tuple[Any, ...]:
        return self._row


class _Connection:
    def __init__(self, *, has_artifact_id: bool) -> None:
        self.has_artifact_id = has_artifact_id
        self.executed: list[tuple[str, object]] = []

    def execute(self, query: str, params: object = None) -> _Result:
        self.executed.append((query, params))
        if "information_schema.columns" in query:
            return _Result((self.has_artifact_id, True, True, self.has_artifact_id))
        if not self.has_artifact_id and "programme_version" in query:
            raise AssertionError("pre-004 schema has no programme_version column")
        collection = str(params[0])  # type: ignore[index]
        if self.has_artifact_id:
            if collection.endswith("premiere_specialite"):
                return _Result(
                    (19, 19, 0, ["intfloat/multilingual-e5-large"], ["reviewed"], ["NSI-1"])
                )
            return _Result(
                (43, 19, 24, ["legacy", "intfloat/multilingual-e5-large"], ["reviewed"], ["NSI-T"])
            )
        if collection.endswith("premiere_specialite"):
            return _Result((0, [], [], []))
        programmes = [] if "NULL::text[]" in query else ["NSI-T"]
        return _Result((24, ["intfloat/multilingual-e5-large"], ["reviewed"], programmes))


def test_diagnostic_partitions_schema_004_rows_without_certifying_legacy() -> None:
    diagnostics = inspect_nsi_legacy_rows(_Connection(has_artifact_id=True))

    premiere, terminale = diagnostics
    assert (premiere.total_existing_rows, premiere.governed_release_rows, premiere.legacy_rows) == (
        19,
        19,
        0,
    )
    assert (
        terminale.total_existing_rows,
        terminale.governed_release_rows,
        terminale.legacy_rows,
    ) == (
        43,
        19,
        24,
    )
    assert all(item.legacy_certified_as_governed is False for item in diagnostics)


def test_diagnostic_treats_pre_004_rows_as_legacy_without_mutation() -> None:
    connection = _Connection(has_artifact_id=False)

    premiere, terminale = inspect_nsi_legacy_rows(connection)

    assert premiere.total_existing_rows == premiere.legacy_rows == 0
    assert terminale.total_existing_rows == terminale.legacy_rows == 24
    assert terminale.governed_release_rows == 0
    assert terminale.programme_values == ()
    assert all(
        not query.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for query, _ in connection.executed
    )
