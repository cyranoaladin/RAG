"""Le validateur 006 vérifie la définition entière de la contrainte."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from tests.integration._pg_authority import requires_docker, start_rag_retrieval_postgres

pytestmark = [pytest.mark.integration, requires_docker]

LIBRARY = (
    Path(__file__).resolve().parents[2]
    / "infra/scripts/lib/pgvector_migration_state.sh"
)
FINGERPRINTS = LIBRARY.parents[2] / "postgres/schema_head_006_fingerprints.env"


@pytest.fixture(scope="module")
def postgres() -> Iterator[dict[str, str]]:
    yield from start_rag_retrieval_postgres("schema-006-sabotage")


def _validation_sql(name: str = "validate_006_sql") -> str:
    return subprocess.run(
        ["bash", "-c", 'source "$1"; "$2"', "bash", str(LIBRARY), name],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_shell_validator_and_runtime_pin_same_constraint_definition() -> None:
    source = FINGERPRINTS.read_text(encoding="utf-8")
    match = re.search(r"^RAG_ARTIFACTS_PUBLIC_ATTRIBUTION_CHECK_MD5=([0-9a-f]{32})$", source, re.M)
    assert match is not None
    assert f"md5(pg_get_constraintdef(oid, true)) = '{match.group(1)}'" in _validation_sql()


def test_schema_006_refuses_check_true_under_the_expected_name(
    postgres: dict[str, str],
) -> None:
    sql = _validation_sql()
    with psycopg.connect(postgres["dsn"]) as conn:
        conn.execute(sql)
        conn.execute(
            "ALTER TABLE public.rag_artifacts DROP CONSTRAINT "
            "rag_artifacts_public_attribution_complete_check"
        )
        conn.execute(
            "ALTER TABLE public.rag_artifacts ADD CONSTRAINT "
            "rag_artifacts_public_attribution_complete_check CHECK (true)"
        )
        with pytest.raises(psycopg.errors.RaiseException, match="attribution constraint"):
            conn.execute(sql)
        conn.rollback()


def test_schema_004_validator_remains_valid_on_head_006(
    postgres: dict[str, str],
) -> None:
    with psycopg.connect(postgres["dsn"]) as conn:
        conn.execute(_validation_sql("validate_004_sql"))


def test_schema_004_stays_strict_on_the_historical_ten_columns(
    postgres: dict[str, str],
) -> None:
    with psycopg.connect(postgres["dsn"]) as conn:
        conn.execute(
            "ALTER TABLE public.rag_artifacts DROP CONSTRAINT "
            "rag_artifacts_public_attribution_complete_check"
        )
        for name in (
            "is_text_derivative", "licensor", "licence_id",
            "source_updated_at", "derivative_notice",
        ):
            conn.execute(f"ALTER TABLE public.rag_artifacts DROP COLUMN {name}")
        sql = _validation_sql("validate_004_sql")
        conn.execute(sql)
        conn.execute("ALTER TABLE public.rag_artifacts ADD COLUMN unexpected text")
        with pytest.raises(psycopg.errors.RaiseException, match="column count"):
            conn.execute(sql)
        conn.rollback()
