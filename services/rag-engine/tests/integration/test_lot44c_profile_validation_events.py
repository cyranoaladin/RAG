"""LOT44c : persistance des résultats de validation — PostgreSQL réel.

Périmètre strict : vérifie que ``record_validation_result`` insère
correctement dans ``ingestion_control.workflow_events`` (LOT44b, migration
003, non modifiée) — aucune nouvelle table, aucune nouvelle migration.
Aucun worker, aucun scheduler, aucun agent, aucun endpoint.

Convention reprise de tests/integration/test_ingestion_control_concurrency.py
(LOT44b, non modifié) : conteneur Docker jetable, nom aléatoire, port libre,
`--rm`, nettoyage `finally`, vraies connexions PostgreSQL indépendantes.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
INFRA_ROOT = ENGINE_ROOT / "infra"
BOOTSTRAP_SCRIPT = INFRA_ROOT / "scripts" / "bootstrap_ingestion_control_schema.sh"
PROVISION_SCRIPT = INFRA_ROOT / "scripts" / "provision_ingestion_control_roles.sh"

import sys  # noqa: E402

sys.path.insert(0, str(ENGINE_ROOT / "src"))

from ingestor.ingestion_profiles.events import (  # noqa: E402
    PROFILE_VALIDATION_EVENT_TYPE,
    PayloadTooLargeError,
    detect_profile_drift,
    record_validation_result,
)
from ingestor.ingestion_profiles.validation import ValidationIssue, ValidationResult  # noqa: E402

PG_IMAGE = "pgvector/pgvector:pg16"
PG_SUPERUSER = "raguser"
PG_SUPERUSER_PASSWORD = "test-password"
PG_DB = "ragdb"
APP_PASSWORD = "ingestion-control-app-test-pw"
MIGRATOR_PASSWORD = "ingestion-control-migrator-test-pw"

_DOCKER_AVAILABLE = shutil.which("docker") is not None and (
    subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DOCKER_AVAILABLE, reason="Docker not available"),
]

VALID_SCOPE = {
    "tenant": "libre_terminale",
    "collection": "rag_nexus_nsi_terminale_specialite",
    "niveau": "terminale",
    "voie": "generale",
    "matiere": "nsi",
    "candidat": "libre",
    "audience": ["libre", "tous"],
    "visibility": "internal",
    "school_year": "2026-2027",
    "programme_version": "BOEN_special_8_2019-07-25",
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_pg_isready(port: int, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["pg_isready", "-h", "127.0.0.1", "-p", str(port), "-U", PG_SUPERUSER],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise TimeoutError(f"Postgres not ready on port {port} after {timeout_s}s")


@pytest.fixture(scope="module")
def pg_container() -> Iterator[dict[str, str]]:
    container_name = f"nexus-lot44c-profile-validation-{uuid.uuid4().hex[:10]}"
    port = _free_port()
    subprocess.run(
        [
            "docker", "run", "-d", "--rm",
            "--name", container_name,
            "-e", f"POSTGRES_USER={PG_SUPERUSER}",
            "-e", f"POSTGRES_PASSWORD={PG_SUPERUSER_PASSWORD}",
            "-e", f"POSTGRES_DB={PG_DB}",
            "-p", f"{port}:5432",
            PG_IMAGE,
        ],
        check=True,
        capture_output=True,
    )
    try:
        _wait_pg_isready(port)
        env = os.environ.copy()
        env.update({
            "PGHOST": "127.0.0.1",
            "PGPORT": str(port),
            "PGUSER": PG_SUPERUSER,
            "PGPASSWORD": PG_SUPERUSER_PASSWORD,
            "PGDATABASE": PG_DB,
        })

        bootstrap = subprocess.run(
            [str(BOOTSTRAP_SCRIPT)], cwd=ENGINE_ROOT, env=env,
            capture_output=True, text=True, check=False,
        )
        assert bootstrap.returncode == 0, bootstrap.stderr
        assert "BOOTSTRAP_COMPLETE" in bootstrap.stdout

        provision_env = dict(env)
        provision_env.update({
            "INGESTION_CONTROL_MIGRATOR_PASSWORD": MIGRATOR_PASSWORD,
            "INGESTION_CONTROL_APP_PASSWORD": APP_PASSWORD,
        })
        provision = subprocess.run(
            [str(PROVISION_SCRIPT)], cwd=ENGINE_ROOT, env=provision_env,
            capture_output=True, text=True, check=False,
        )
        assert provision.returncode == 0, provision.stderr
        assert "ROLES_PROVISIONED=1" in provision.stdout

        yield {"host": "127.0.0.1", "port": str(port), "dbname": PG_DB}
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)


def _superuser_dsn(pg_container: dict[str, str]) -> str:
    return (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
    )


def _app_dsn(pg_container: dict[str, str]) -> str:
    return (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user=ingestion_control_app password={APP_PASSWORD}"
    )


@pytest.fixture
def superuser_conn(pg_container: dict[str, str]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_superuser_dsn(pg_container), autocommit=True) as conn:
        yield conn


@pytest.fixture
def app_conn(pg_container: dict[str, str]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_app_dsn(pg_container), autocommit=False) as conn:
        yield conn


@pytest.fixture
def clean_db(superuser_conn: psycopg.Connection) -> None:
    with superuser_conn.cursor() as cur:
        cur.execute(
            "TRUNCATE ingestion_control.workflow_events, "
            "ingestion_control.artifacts, ingestion_control.resource_candidates, "
            "ingestion_control.resources, ingestion_control.ingestion_runs CASCADE"
        )


def _insert_run(conn: psycopg.Connection, **overrides: object) -> uuid.UUID:
    scope = {**VALID_SCOPE, **overrides}
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.ingestion_runs
                (tenant, collection, niveau, voie, matiere, candidat, audience,
                 visibility, school_year, programme_version, profile_version, trigger)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING run_id
            """,
            (
                scope["tenant"], scope["collection"], scope["niveau"], scope["voie"],
                scope["matiere"], scope["candidat"], scope["audience"], scope["visibility"],
                scope["school_year"], scope["programme_version"], "v1", "manual",
            ),
        )
        row = cur.fetchone()
        assert row is not None
        return row[0]


def _insert_resource(
    conn: psycopg.Connection, run_id: uuid.UUID, *, dedup_key: str = "a" * 64, **overrides: object
) -> uuid.UUID:
    scope = {**VALID_SCOPE, **overrides}
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.resources
                (run_id, dedup_key, tenant, collection, niveau, voie, matiere, candidat,
                 audience, visibility, school_year, programme_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING resource_id
            """,
            (
                run_id, dedup_key, scope["tenant"], scope["collection"], scope["niveau"],
                scope["voie"], scope["matiere"], scope["candidat"], scope["audience"],
                scope["visibility"], scope["school_year"], scope["programme_version"],
            ),
        )
        row = cur.fetchone()
        assert row is not None
        return row[0]


class TestRecordValidationResult:
    def test_records_passing_result_with_app_role(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(superuser_conn)
        resource_id = _insert_resource(superuser_conn, run_id)
        result = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"], profile_version="v1"
        )

        event_id = record_validation_result(
            app_conn, run_id=run_id, resource_id=resource_id, result=result, actor="test",
        )
        app_conn.commit()

        with superuser_conn.cursor() as cur:
            cur.execute(
                "SELECT event_type, run_id, resource_id, job_id, from_state, to_state, payload "
                "FROM ingestion_control.workflow_events WHERE event_id = %s",
                (event_id,),
            )
            row = cur.fetchone()
        assert row is not None
        event_type, db_run_id, db_resource_id, job_id, from_state, to_state, payload = row
        assert event_type == PROFILE_VALIDATION_EVENT_TYPE
        assert db_run_id == run_id
        assert db_resource_id == resource_id
        assert job_id is None
        assert from_state is None
        assert to_state is None
        assert payload["status"] == "passed"

    def test_payload_contract_mandatory_fields_always_present_optional_fields_absent(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        """Contrat exact du payload : kind/event_contract_version/status/
        collection/profile_version/profile_fingerprint/issues toujours
        présents (même si null/vide) ; candidate_id/artifact_id absents du
        payload — pas seulement null — quand l'appelant ne les fournit
        pas."""
        run_id = _insert_run(superuser_conn)
        result = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"], profile_version="v1"
        )
        event_id = record_validation_result(app_conn, run_id=run_id, result=result, actor="test")
        app_conn.commit()

        with superuser_conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM ingestion_control.workflow_events WHERE event_id = %s",
                (event_id,),
            )
            row = cur.fetchone()
        assert row is not None
        payload = row[0]

        for mandatory_field in (
            "kind", "event_contract_version", "status", "collection",
            "profile_version", "profile_fingerprint", "issues",
        ):
            assert mandatory_field in payload, f"missing mandatory field: {mandatory_field}"
        assert payload["event_contract_version"] == "1"
        assert payload["kind"] == PROFILE_VALIDATION_EVENT_TYPE
        assert "candidate_id" not in payload
        assert "artifact_id" not in payload

    def test_records_failing_result_with_structured_issues(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(superuser_conn)
        result = ValidationResult(
            status="failed",
            issues=(ValidationIssue(code="SCOPE_DIMENSION_MISMATCH", path="niveau", message="x"),),
            collection=VALID_SCOPE["collection"],
            profile_version="v1",
        )

        event_id = record_validation_result(
            app_conn, run_id=run_id, result=result, actor="test",
        )
        app_conn.commit()

        with superuser_conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM ingestion_control.workflow_events WHERE event_id = %s",
                (event_id,),
            )
            row = cur.fetchone()
        assert row is not None
        payload = row[0]
        assert payload["issues"][0]["code"] == "SCOPE_DIMENSION_MISMATCH"

    def test_resource_id_is_nullable_for_run_level_validation(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(superuser_conn)
        result = ValidationResult(
            status="profile_unknown", issues=(), collection="x", profile_version="v1"
        )
        event_id = record_validation_result(app_conn, run_id=run_id, result=result, actor="test")
        app_conn.commit()

        with superuser_conn.cursor() as cur:
            cur.execute(
                "SELECT resource_id FROM ingestion_control.workflow_events WHERE event_id = %s",
                (event_id,),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] is None

    def test_candidate_and_artifact_id_are_carried_in_payload_not_columns(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(superuser_conn)
        candidate_id = uuid.uuid4()
        artifact_id = uuid.uuid4()
        result = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"], profile_version="v1"
        )
        event_id = record_validation_result(
            app_conn, run_id=run_id, result=result, actor="test",
            candidate_id=candidate_id, artifact_id=artifact_id,
        )
        app_conn.commit()

        with superuser_conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM ingestion_control.workflow_events WHERE event_id = %s",
                (event_id,),
            )
            row = cur.fetchone()
        assert row is not None
        payload = row[0]
        assert payload["candidate_id"] == str(candidate_id)
        assert payload["artifact_id"] == str(artifact_id)

    def test_does_not_commit_transaction_itself(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(superuser_conn)
        result = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"], profile_version="v1"
        )
        event_id = record_validation_result(app_conn, run_id=run_id, result=result, actor="test")
        app_conn.rollback()

        with superuser_conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM ingestion_control.workflow_events WHERE event_id = %s",
                (event_id,),
            )
            row = cur.fetchone()
        assert row is None

    def test_no_idempotency_key_by_default(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(superuser_conn)
        result = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"], profile_version="v1"
        )
        event_id = record_validation_result(app_conn, run_id=run_id, result=result, actor="test")
        app_conn.commit()

        with superuser_conn.cursor() as cur:
            cur.execute(
                "SELECT idempotency_key FROM ingestion_control.workflow_events WHERE event_id = %s",
                (event_id,),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] is None

    def test_repeated_validation_without_idempotency_key_creates_distinct_events(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        """Comportement par défaut documenté explicitement : un
        enregistrement répété (sans clé d'idempotence) crée un nouvel
        événement à chaque appel — jamais un remplacement, jamais un rejet.
        Le "dernier résultat" se retrouve par ORDER BY occurred_at DESC
        (cf. ADR-0026, interface LOT44d/LOT44e)."""
        run_id = _insert_run(superuser_conn)
        result = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"], profile_version="v1"
        )
        first_id = record_validation_result(app_conn, run_id=run_id, result=result, actor="test")
        second_id = record_validation_result(app_conn, run_id=run_id, result=result, actor="test")
        app_conn.commit()

        assert first_id != second_id
        with superuser_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM ingestion_control.workflow_events WHERE run_id = %s",
                (run_id,),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == 2

    def test_inconsistent_run_and_resource_pairing_is_not_rejected_by_the_schema(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        """Documente un comportement actuel non corrigé ici, hérité du
        schéma LOT44b figé (migration 003) : workflow_events porte deux FK
        indépendantes (run_id -> ingestion_runs, resource_id -> resources)
        mais aucune contrainte composite ne vérifie que resource_id
        appartient réellement à run_id. Ce test prouve le comportement
        actuel plutôt que de le cacher — cf. ADR-0026, réserve héritée de
        LOT44b, non modifiable sans toucher une migration déjà commitée."""
        run_a = _insert_run(superuser_conn)
        run_b = _insert_run(superuser_conn)
        resource_of_run_b = _insert_resource(superuser_conn, run_b)

        result = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"], profile_version="v1"
        )
        event_id = record_validation_result(
            app_conn, run_id=run_a, resource_id=resource_of_run_b, result=result, actor="test",
        )
        app_conn.commit()

        with superuser_conn.cursor() as cur:
            cur.execute(
                "SELECT run_id, resource_id FROM ingestion_control.workflow_events "
                "WHERE event_id = %s",
                (event_id,),
            )
            row = cur.fetchone()
        assert row is not None
        assert row == (run_a, resource_of_run_b)

    def test_app_role_has_insufficient_privilege_for_update(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        """Append-only réel — même garantie que LOT44b : le rôle runtime ne
        peut jamais UPDATE workflow_events, y compris pour un événement de
        validation de profil."""
        run_id = _insert_run(superuser_conn)
        result = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"], profile_version="v1"
        )
        event_id = record_validation_result(app_conn, run_id=run_id, result=result, actor="test")
        app_conn.commit()

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with app_conn.cursor() as cur:
                cur.execute(
                    "UPDATE ingestion_control.workflow_events SET actor = 'x' WHERE event_id = %s",
                    (event_id,),
                )
        app_conn.rollback()

    def test_missing_run_id_is_rejected_by_foreign_key(
        self, clean_db, app_conn: psycopg.Connection
    ) -> None:
        result = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"], profile_version="v1"
        )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            record_validation_result(app_conn, run_id=uuid.uuid4(), result=result, actor="test")
        app_conn.rollback()


class TestDuplicateDetectionKeyContractB:
    """``idempotency_key`` : contrat B explicitement choisi — DÉTECTION DE
    DOUBLON, PAS UNE IDEMPOTENCE COMPLÈTE (contrat A). Une répétition avec
    la même clé échoue toujours (UniqueViolation) ; elle ne renvoie jamais
    le résultat déjà enregistré, et l'unicité ne porte que sur la colonne
    ``idempotency_key`` seule — jamais sur une combinaison avec run_id ou
    resource_id. Les cinq scénarios ci-dessous couvrent exactement cette
    matrice, avec de vraies connexions PostgreSQL indépendantes."""

    def test_same_key_same_payload_fails_on_repeat(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(superuser_conn)
        result = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"], profile_version="v1"
        )
        record_validation_result(
            app_conn, run_id=run_id, result=result, actor="test", idempotency_key="key-a",
        )
        app_conn.commit()

        with pytest.raises(psycopg.errors.UniqueViolation):
            record_validation_result(
                app_conn, run_id=run_id, result=result, actor="test", idempotency_key="key-a",
            )
        app_conn.rollback()

    def test_same_key_different_payload_fails_identically(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        """Preuve que le contrat B ignore le contenu du payload : même clé
        + payload DIFFÉRENT échoue exactement comme même clé + payload
        identique — ce n'est jamais une comparaison de contenu."""
        run_id = _insert_run(superuser_conn)
        first = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"], profile_version="v1"
        )
        record_validation_result(
            app_conn, run_id=run_id, result=first, actor="test", idempotency_key="key-b",
        )
        app_conn.commit()

        different = ValidationResult(
            status="failed",
            issues=(ValidationIssue(code="SCOPE_DIMENSION_MISMATCH", path="niveau", message="x"),),
            collection=VALID_SCOPE["collection"], profile_version="v1",
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            record_validation_result(
                app_conn, run_id=run_id, result=different, actor="test", idempotency_key="key-b",
            )
        app_conn.rollback()

    def test_no_key_never_conflicts(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(superuser_conn)
        result = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"], profile_version="v1"
        )
        first_id = record_validation_result(app_conn, run_id=run_id, result=result, actor="test")
        second_id = record_validation_result(app_conn, run_id=run_id, result=result, actor="test")
        app_conn.commit()
        assert first_id != second_id

    def test_same_key_different_run_id_still_fails(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        """L'unicité porte sur idempotency_key SEUL — jamais sur
        (idempotency_key, run_id). Réutiliser la même clé pour un run_id
        différent échoue tout autant."""
        run_a = _insert_run(superuser_conn)
        run_b = _insert_run(superuser_conn)
        result = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"], profile_version="v1"
        )
        record_validation_result(
            app_conn, run_id=run_a, result=result, actor="test", idempotency_key="key-c",
        )
        app_conn.commit()

        with pytest.raises(psycopg.errors.UniqueViolation):
            record_validation_result(
                app_conn, run_id=run_b, result=result, actor="test", idempotency_key="key-c",
            )
        app_conn.rollback()

    def test_same_key_different_resource_id_still_fails(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        """Même démonstration que ci-dessus pour resource_id : l'unicité
        ne porte pas sur (idempotency_key, resource_id) non plus."""
        run_id = _insert_run(superuser_conn)
        resource_a = _insert_resource(superuser_conn, run_id, dedup_key="a" * 64)
        resource_b = _insert_resource(superuser_conn, run_id, dedup_key="b" * 64)
        result = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"], profile_version="v1"
        )
        record_validation_result(
            app_conn, run_id=run_id, resource_id=resource_a, result=result, actor="test",
            idempotency_key="key-d",
        )
        app_conn.commit()

        with pytest.raises(psycopg.errors.UniqueViolation):
            record_validation_result(
                app_conn, run_id=run_id, resource_id=resource_b, result=result, actor="test",
                idempotency_key="key-d",
            )
        app_conn.rollback()


class TestPayloadSizeLimit:
    def test_oversized_payload_is_rejected_before_insertion(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        """Un plafond réel, pas un nombre de champs supposé petit : une
        liste d'issues artificiellement énorme doit être rejetée avant
        toute tentative d'INSERT, jamais laissée à PostgreSQL."""
        run_id = _insert_run(superuser_conn)
        huge_issues = tuple(
            ValidationIssue(code="X", path="p", message="m" * 100) for _ in range(10_000)
        )
        result = ValidationResult(
            status="failed", issues=huge_issues,
            collection=VALID_SCOPE["collection"], profile_version="v1",
        )
        with pytest.raises(PayloadTooLargeError):
            record_validation_result(app_conn, run_id=run_id, result=result, actor="test")

    def test_ordinary_payload_is_well_within_the_limit(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(superuser_conn)
        result = ValidationResult(
            status="failed",
            issues=tuple(
                ValidationIssue(code="SCOPE_DIMENSION_MISMATCH", path=d, message="x")
                for d in ("tenant", "niveau", "voie")
            ),
            collection=VALID_SCOPE["collection"], profile_version="v1",
        )
        event_id = record_validation_result(app_conn, run_id=run_id, result=result, actor="test")
        app_conn.commit()
        assert event_id is not None


class TestDetectProfileDrift:
    """Une simple primitive SHA-256 ne constitue pas une détection de
    dérive : ces tests prouvent la comparaison réelle contre l'historique
    persisté, avec de vraies connexions PostgreSQL indépendantes."""

    def test_no_history_is_never_treated_as_drift(
        self, clean_db, app_conn: psycopg.Connection
    ) -> None:
        result = detect_profile_drift(
            app_conn,
            collection=VALID_SCOPE["collection"],
            profile_version="v1",
            current_fingerprint="a" * 64,
        )
        assert result.has_history is False
        assert result.drift_detected is False
        assert result.previous_fingerprint is None

    def test_identical_fingerprint_across_runs_is_not_drift(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(superuser_conn)
        stable_fingerprint = "b" * 64
        result = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"],
            profile_version="v1", profile_fingerprint=stable_fingerprint,
        )
        record_validation_result(app_conn, run_id=run_id, result=result, actor="test")
        app_conn.commit()

        drift = detect_profile_drift(
            app_conn,
            collection=VALID_SCOPE["collection"],
            profile_version="v1",
            current_fingerprint=stable_fingerprint,
        )
        assert drift.has_history is True
        assert drift.drift_detected is False
        assert drift.previous_fingerprint == stable_fingerprint

    def test_different_fingerprint_across_runs_is_drift(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(superuser_conn)
        first_result = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"],
            profile_version="v1", profile_fingerprint="c" * 64,
        )
        record_validation_result(app_conn, run_id=run_id, result=first_result, actor="test")
        app_conn.commit()

        drift = detect_profile_drift(
            app_conn,
            collection=VALID_SCOPE["collection"],
            profile_version="v1",
            current_fingerprint="d" * 64,
        )
        assert drift.has_history is True
        assert drift.drift_detected is True
        assert drift.previous_fingerprint == "c" * 64
        assert drift.current_fingerprint == "d" * 64

    def test_drift_check_uses_the_most_recent_persisted_fingerprint(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        """Scénario réaliste : chaque validation est commitée séparément
        (comme le ferait un appelant réel, jamais trois écritures dans une
        seule transaction non commitée) — occurred_at progresse réellement
        entre chaque insertion."""
        run_id = _insert_run(superuser_conn)
        for fingerprint in ("e" * 64, "f" * 64, "0" * 64):
            result = ValidationResult(
                status="passed", issues=(), collection=VALID_SCOPE["collection"],
                profile_version="v1", profile_fingerprint=fingerprint,
            )
            record_validation_result(app_conn, run_id=run_id, result=result, actor="test")
            app_conn.commit()

        drift = detect_profile_drift(
            app_conn,
            collection=VALID_SCOPE["collection"],
            profile_version="v1",
            current_fingerprint="0" * 64,
        )
        assert drift.previous_fingerprint == "0" * 64
        assert drift.drift_detected is False

    def test_same_transaction_inserts_share_occurred_at_but_query_is_reproducible(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        """Réserve prouvée, pas cachée : PostgreSQL ``now()`` renvoie
        l'heure de DÉBUT de transaction (``transaction_timestamp()``),
        constante pour toute la transaction — deux événements insérés sans
        commit intermédiaire partagent donc exactement le même
        ``occurred_at``. ``ORDER BY occurred_at DESC, event_id DESC``
        départage désormais sur ``event_id`` (UUID immuable, jamais NULL) :
        la REQUÊTE devient reproductible (même résultat à chaque appel sur
        les mêmes données) — ce test le prouve en appelant deux fois. Cela
        ne restaure PAS un ordre chronologique réel (event_id n'est pas
        corrélé à l'ordre d'écriture) : ce test ne prétend pas choisir
        "la vraiment dernière" empreinte dans ce cas précis, seulement que
        le résultat ne varie jamais d'un appel à l'autre. Non améliorable
        sans colonne de séquence sur ``workflow_events`` (migration 003
        gelée, hors périmètre LOT44c) — cf. ADR-0026."""
        run_id = _insert_run(superuser_conn)
        for fingerprint in ("3" * 64, "4" * 64):
            result = ValidationResult(
                status="passed", issues=(), collection=VALID_SCOPE["collection"],
                profile_version="v1", profile_fingerprint=fingerprint,
            )
            record_validation_result(app_conn, run_id=run_id, result=result, actor="test")
        app_conn.commit()

        first = detect_profile_drift(
            app_conn, collection=VALID_SCOPE["collection"],
            profile_version="v1", current_fingerprint="5" * 64,
        )
        second = detect_profile_drift(
            app_conn, collection=VALID_SCOPE["collection"],
            profile_version="v1", current_fingerprint="5" * 64,
        )
        assert first.has_history is True
        assert first.previous_fingerprint in {"3" * 64, "4" * 64}
        assert first == second

    def test_exclude_event_id_prevents_comparing_the_current_event_to_itself(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        """Sans exclude_event_id, appeler detect_profile_drift APRÈS avoir
        enregistré l'événement courant le retrouverait lui-même comme
        "dernier historique", produisant toujours drift_detected=False de
        façon triviale. exclude_event_id corrige ce piège d'ordre d'appel."""
        run_id = _insert_run(superuser_conn)
        earlier = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"],
            profile_version="v1", profile_fingerprint="6" * 64,
        )
        record_validation_result(app_conn, run_id=run_id, result=earlier, actor="test")
        app_conn.commit()

        current = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"],
            profile_version="v1", profile_fingerprint="7" * 64,
        )
        current_event_id = record_validation_result(
            app_conn, run_id=run_id, result=current, actor="test"
        )
        app_conn.commit()

        naive = detect_profile_drift(
            app_conn, collection=VALID_SCOPE["collection"],
            profile_version="v1", current_fingerprint="7" * 64,
        )
        assert naive.previous_fingerprint == "7" * 64
        assert naive.drift_detected is False  # comparaison triviale à soi-même

        corrected = detect_profile_drift(
            app_conn, collection=VALID_SCOPE["collection"],
            profile_version="v1", current_fingerprint="7" * 64,
            exclude_event_id=current_event_id,
        )
        assert corrected.previous_fingerprint == "6" * 64
        assert corrected.drift_detected is True

    def test_events_without_fingerprint_are_skipped_by_drift_check(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        """Un profile_unknown (sans empreinte) intercalé entre deux
        validations réussies ne doit jamais devenir "le dernier historique"
        — la comparaison remonte au dernier événement qui portait
        réellement une empreinte."""
        run_id = _insert_run(superuser_conn)
        first = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"],
            profile_version="v1", profile_fingerprint="8" * 64,
        )
        record_validation_result(app_conn, run_id=run_id, result=first, actor="test")
        app_conn.commit()

        unknown = ValidationResult(
            status="profile_unknown", issues=(), collection=VALID_SCOPE["collection"],
            profile_version="v1", profile_fingerprint=None,
        )
        record_validation_result(app_conn, run_id=run_id, result=unknown, actor="test")
        app_conn.commit()

        drift = detect_profile_drift(
            app_conn, collection=VALID_SCOPE["collection"],
            profile_version="v1", current_fingerprint="8" * 64,
        )
        assert drift.has_history is True
        assert drift.previous_fingerprint == "8" * 64
        assert drift.drift_detected is False

    def test_drift_check_is_scoped_to_the_exact_identity(
        self, clean_db, superuser_conn: psycopg.Connection, app_conn: psycopg.Connection
    ) -> None:
        """Un historique existant pour une autre (collection, version) ne
        doit jamais être confondu avec l'identité recherchée."""
        run_id = _insert_run(superuser_conn)
        other_result = ValidationResult(
            status="passed", issues=(), collection=VALID_SCOPE["collection"],
            profile_version="v2", profile_fingerprint="1" * 64,
        )
        record_validation_result(app_conn, run_id=run_id, result=other_result, actor="test")
        app_conn.commit()

        drift = detect_profile_drift(
            app_conn,
            collection=VALID_SCOPE["collection"],
            profile_version="v1",
            current_fingerprint="2" * 64,
        )
        assert drift.has_history is False
