"""LOT44f : réconciliation jobs.status (SQL <-> Python <-> code réellement écrit).

Périmètre : garantir que la contrainte SQL ``jobs_status_valid`` (telle
qu'elle résulte de l'application successive des migrations
``ingestion_control``) et le type Python ``JobStatus``
(``ingestor.ingestion_control.jobs``) déclarent exactement le même ensemble
de valeurs — la divergence historique (7 valeurs SQL dont ``'claimed'``,
6 valeurs Python) est documentée en dette dans
``docs/reports/rag_project_global_state_2026-08-04.md`` (section 16.3) et
fermée par la migration ``005_jobs_status_reconcile.sql`` (ADR-0029).

Aucun test ici ne nécessite PostgreSQL : la contrainte SQL "finale" est
obtenue en rejouant, par lecture pure de fichiers, l'état cumulatif de
``jobs_status_valid`` à travers toutes les migrations numérotées, dans
l'ordre — exactement ce que ``bootstrap_ingestion_control_schema.sh``
appliquerait sur une base réelle, sans avoir besoin d'une base réelle pour
ce contrôle statique.
"""
from __future__ import annotations

import re
import sys
import typing
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ENGINE_ROOT / "infra" / "postgres" / "ingestion_control" / "migrations"

sys.path.insert(0, str(ENGINE_ROOT / "src"))

from ingestor.ingestion_control.jobs import JobStatus  # noqa: E402

_CONSTRAINT_PATTERN = re.compile(
    r"jobs_status_valid\s*\n?\s*CHECK \(status IN \((.*?)\)\)", re.DOTALL
)
_VALUE_PATTERN = re.compile(r"'([a-z_]+)'")


def _numbered_migration_files() -> list[Path]:
    files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    assert files, f"no numbered migration files found in {MIGRATIONS_DIR}"
    return files


def _final_sql_declared_statuses() -> frozenset[str]:
    """Rejoue jobs_status_valid à travers toutes les migrations numérotées,
    dans l'ordre, et retourne l'ensemble de valeurs déclaré par la dernière
    migration qui redéfinit la contrainte (CREATE TABLE ou ALTER TABLE)."""
    declared: frozenset[str] | None = None
    for migration_file in _numbered_migration_files():
        text = migration_file.read_text(encoding="utf-8")
        match = _CONSTRAINT_PATTERN.search(text)
        if match is None:
            continue
        declared = frozenset(_VALUE_PATTERN.findall(match.group(1)))
    assert declared is not None, "jobs_status_valid never declared by any migration"
    return declared


def _python_declared_statuses() -> frozenset[str]:
    return frozenset(typing.get_args(JobStatus))


class TestJobStatusSqlPythonReconciliation:
    def test_sql_constraint_matches_python_literal_exactly(self) -> None:
        sql_statuses = _final_sql_declared_statuses()
        python_statuses = _python_declared_statuses()
        assert sql_statuses == python_statuses, (
            f"jobs_status_valid (SQL, final state) = {sorted(sql_statuses)} "
            f"but JobStatus (Python) = {sorted(python_statuses)} — these must "
            "be identical after migration 005 (ADR-0029)."
        )

    def test_claimed_is_not_declared_anywhere_after_reconciliation(self) -> None:
        assert "claimed" not in _final_sql_declared_statuses()
        assert "claimed" not in _python_declared_statuses()

    def test_reconciliation_migration_present_and_head_at_least_005(self) -> None:
        migration = MIGRATIONS_DIR / "005_jobs_status_reconcile.sql"
        head = MIGRATIONS_DIR / "HEAD"
        assert migration.is_file()
        # >= 005, pas nécessairement == : des migrations additives ultérieures
        # (ex. 006, LOT44f) font légitimement avancer HEAD sans invalider la
        # réconciliation elle-même — seule sa présence dans la chaîne compte.
        head_number = int(head.read_text(encoding="utf-8").strip().split("_", 1)[0])
        assert head_number >= 5

    def test_rollback_for_005_exists(self) -> None:
        rollback = (
            MIGRATIONS_DIR.parent / "rollbacks" / "005_jobs_status_reconcile.down.sql"
        )
        assert rollback.is_file()
        text = rollback.read_text(encoding="utf-8")
        assert "'claimed'" in text, "rollback must restore the pre-005 7-value constraint"


class TestJobStatusValuesExpectedSet:
    """Verrouille explicitement l'ensemble canonique attendu — si ce test
    doit changer, c'est le signal qu'une évolution de jobs.status est en
    cours et doit être documentée (nouvel ADR), pas une régression
    silencieuse."""

    EXPECTED = frozenset(
        {"queued", "running", "succeeded", "failed", "dead_letter", "cancelled"}
    )

    def test_python_literal_matches_expected_canonical_set(self) -> None:
        assert _python_declared_statuses() == self.EXPECTED

    def test_sql_final_state_matches_expected_canonical_set(self) -> None:
        assert _final_sql_declared_statuses() == self.EXPECTED
