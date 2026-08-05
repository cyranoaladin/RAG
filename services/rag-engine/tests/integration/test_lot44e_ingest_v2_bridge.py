"""LOT44e : pont best-effort /ingest/v2 -> job — PostgreSQL réel.

Périmètre strict : le cas nominal réel (écriture réussie) de
``best_effort_create_ingest_job``. Le cas "échec ne lève jamais" (scope
invalide, DSN injoignable) est couvert sans réseau réel dans
``tests/test_lot44e_ingest_v2_bridge.py``.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
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

sys.path.insert(0, str(ENGINE_ROOT / "src"))

from ingestor.ingestion_worker.ingest_v2_bridge import (  # noqa: E402
    UNSPECIFIED_PROFILE_VERSION,
    best_effort_create_ingest_job,
)

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


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_pg_isready(port: int, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["pg_isready", "-h", "127.0.0.1", "-p", str(port), "-U", PG_SUPERUSER],
            capture_output=True, check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise TimeoutError(f"Postgres not ready on port {port} after {timeout_s}s")


@pytest.fixture(scope="module")
def pg_container() -> Iterator[dict[str, str]]:
    container_name = f"nexus-lot44e-ingest-v2-bridge-{uuid.uuid4().hex[:10]}"
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
        check=True, capture_output=True,
    )
    try:
        _wait_pg_isready(port)
        env = os.environ.copy()
        env.update({
            "PGHOST": "127.0.0.1", "PGPORT": str(port), "PGUSER": PG_SUPERUSER,
            "PGPASSWORD": PG_SUPERUSER_PASSWORD, "PGDATABASE": PG_DB,
        })
        bootstrap = subprocess.run(
            [str(BOOTSTRAP_SCRIPT)], cwd=ENGINE_ROOT, env=env,
            capture_output=True, text=True, check=False,
        )
        assert bootstrap.returncode == 0, bootstrap.stderr

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

        yield {"host": "127.0.0.1", "port": str(port), "dbname": PG_DB}
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)


def _app_dsn(pg_container: dict[str, str]) -> str:
    return (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user=ingestion_control_app password={APP_PASSWORD}"
    )


@pytest.fixture
def clean_db(pg_container: dict[str, str]) -> None:
    dsn = (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
    )
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE ingestion_control.jobs, ingestion_control.workflow_events, "
            "ingestion_control.artifacts, ingestion_control.resource_candidates, "
            "ingestion_control.resources, ingestion_control.ingestion_runs CASCADE"
        )


class TestBestEffortCreateIngestJobRealPostgres:
    def test_valid_scope_creates_a_real_job_never_a_resource(
        self, pg_container: dict[str, str], clean_db: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", _app_dsn(pg_container))

        job_id = best_effort_create_ingest_job(
            collection="rag_nexus_nsi_terminale_specialite",
            source_label="eduscol.education.fr",
            source_uri="https://eduscol.education.fr/nsi/algo",
            rights="public_allowed",
            type_doc="cours",
            matiere="nsi",
            niveau="terminale",
            voie="generale",
            audience=["tous"],
            default_tenant="libre_terminale",
            default_candidat="libre",
            default_visibility="internal",
            default_school_year="2026-2027",
            default_programme_version="BOEN_special_8_2019-07-25",
            dedup_key="a" * 64,
        )

        assert job_id is not None

        dsn = (
            f"host={pg_container['host']} port={pg_container['port']} "
            f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
        )
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT status, resource_id, payload FROM ingestion_control.jobs WHERE job_id = %s",
                (job_id,),
            )
            status, resource_id, payload = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM ingestion_control.resources")
            (resource_count,) = cur.fetchone()

        assert status == "queued"
        assert resource_id is None, "aucune resource ne doit être créée par le pont, seulement le worker"
        assert resource_count == 0
        assert payload["profile_version"] == UNSPECIFIED_PROFILE_VERSION
        assert payload["source_url"] == "https://eduscol.education.fr/nsi/algo"


class TestIngestV2HttpEndpointCreatesJobWithoutChangingResponse:
    """Preuve HTTP réelle (FastAPI TestClient) : /ingest/v2/upload-files
    crée un job best-effort sans altérer sa réponse existante — même
    ``ingest_document`` mocké que ``tests/test_ingest_v2.py`` (LOT43, non
    modifié), seule la présence best-effort du job est nouvelle ici."""

    def test_upload_creates_job_and_response_is_unchanged(
        self,
        pg_container: dict[str, str],
        clean_db: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ingestor import ingest_v2_endpoint
        from ingestor.ingest_v2 import IngestV2Result, Provenance

        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", _app_dsn(pg_container))
        monkeypatch.setenv("NEXUS_DEFAULT_TENANT", "libre_terminale")
        monkeypatch.setenv("NEXUS_DEFAULT_CANDIDAT", "libre")
        monkeypatch.setenv("NEXUS_DEFAULT_VISIBILITY", "internal")
        monkeypatch.setenv("NEXUS_DEFAULT_SCHOOL_YEAR", "2026-2027")
        monkeypatch.setenv("NEXUS_DEFAULT_PROGRAMME_VERSION", "BOEN_special_8_2019-07-25")

        monkeypatch.setattr(ingest_v2_endpoint, "_enforce_security", lambda request: "test-token")

        def fake_ingest_document(
            text: str, req: object, provenance: Provenance, *, doc_id: str
        ) -> IngestV2Result:
            return IngestV2Result(
                doc_id=doc_id, chunks_total=1, chunks_written=1,
                chunks_filtered=0, chunks_dedup=0,
                collection="rag_nexus_nsi_terminale_specialite",
                review_status="needs_review",
            )

        monkeypatch.setattr(ingest_v2_endpoint, "ingest_document", fake_ingest_document)

        app = FastAPI()
        app.include_router(ingest_v2_endpoint.router)
        response = TestClient(app).post(
            "/ingest/v2/upload-files",
            params={
                "collection": "rag_nexus_nsi_terminale_specialite",
                "rights": "usage_interne",
                "matiere": "nsi",
                "niveau": "terminale",
                "voie": "generale",
            },
            files={"files": ("cours.txt", b"contenu", "text/plain")},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["route"] == "upload_v2"
        assert body["results"][0]["review_status"] == "needs_review"
        assert "job_id" not in body, "la réponse existante ne doit jamais être modifiée"
        assert set(body["results"][0].keys()) == {
            "file", "doc_id", "chunks_written", "chunks_filtered", "chunks_dedup", "review_status",
        }

        dsn = (
            f"host={pg_container['host']} port={pg_container['port']} "
            f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
        )
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ingestion_control.jobs")
            (job_count,) = cur.fetchone()
        assert job_count == 1


# -- LOT44f (ADR-0029) : résolution réelle de profile_version + idempotence --


def _write_profile(directory: Path, filename: str, **overrides: object) -> None:
    payload: dict[str, object] = {
        "profile_version": "v1",
        "enabled": True,
        "scope": {
            "tenant": "libre_terminale",
            "collection": "rag_nexus_nsi_terminale_specialite",
            "niveau": "terminale",
            "voie": "generale",
            "matiere": "nsi",
            "candidat": "libre",
            "audience": ["tous"],
            "visibility": "internal",
            "school_year": "2026-2027",
            "programme_version": "BOEN_special_8_2019-07-25",
        },
        "title": "Profil de test — non production",
        "owner": "equipe-test",
        "expected_topics": ["sujet"],
        "expected_resource_types": ["cours"],
        "allowed_domains": ["eduscol.education.fr"],
        "source_authority": "official",
        "search_cadence": "weekly",
        "max_queries_per_run": 10,
        "max_documents_per_run": 20,
        "max_chunk_size": 800,
        "chunk_overlap": 100,
        "min_source_confidence": 0.7,
        "min_scope_confidence": 0.7,
        "min_extraction_quality": 0.6,
    }
    payload.update(overrides)
    import yaml
    (directory / filename).write_text(yaml.safe_dump(payload), encoding="utf-8")


class TestBridgeResolvesRealProfileVersion:
    def test_exactly_one_matching_profile_resolves_and_governs(
        self, pg_container: dict[str, str], clean_db: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write_profile(tmp_path, "a.yml")
        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", _app_dsn(pg_container))
        monkeypatch.setenv("RAG_ENGINE_INGESTION_PROFILES_DIR", str(tmp_path))

        job_id = best_effort_create_ingest_job(
            collection="rag_nexus_nsi_terminale_specialite",
            source_label="eduscol.education.fr",
            source_uri="https://eduscol.education.fr/nsi/algo",
            rights="public_allowed",
            type_doc="cours",
            matiere="nsi",
            niveau="terminale",
            voie="generale",
            audience=["tous"],
            default_tenant="libre_terminale",
            default_candidat="libre",
            default_visibility="internal",
            default_school_year="2026-2027",
            default_programme_version="BOEN_special_8_2019-07-25",
            dedup_key="b" * 64,
        )
        assert job_id is not None

        dsn = (
            f"host={pg_container['host']} port={pg_container['port']} "
            f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
        )
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM ingestion_control.jobs WHERE job_id = %s", (job_id,)
            )
            (payload,) = cur.fetchone()
        assert payload["profile_version"] == "v1"
        assert payload["governed"] is True

    def test_two_matching_profiles_is_ambiguous_falls_back_to_legacy(
        self, pg_container: dict[str, str], clean_db: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write_profile(tmp_path, "a.yml", profile_version="v1")
        _write_profile(tmp_path, "b.yml", profile_version="v2")
        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", _app_dsn(pg_container))
        monkeypatch.setenv("RAG_ENGINE_INGESTION_PROFILES_DIR", str(tmp_path))

        job_id = best_effort_create_ingest_job(
            collection="rag_nexus_nsi_terminale_specialite",
            source_label="eduscol.education.fr",
            source_uri="https://eduscol.education.fr/nsi/algo",
            rights="public_allowed",
            type_doc="cours",
            matiere="nsi",
            niveau="terminale",
            voie="generale",
            audience=["tous"],
            default_tenant="libre_terminale",
            default_candidat="libre",
            default_visibility="internal",
            default_school_year="2026-2027",
            default_programme_version="BOEN_special_8_2019-07-25",
            dedup_key="c" * 64,
        )
        assert job_id is not None

        dsn = (
            f"host={pg_container['host']} port={pg_container['port']} "
            f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
        )
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM ingestion_control.jobs WHERE job_id = %s", (job_id,)
            )
            (payload,) = cur.fetchone()
        assert payload["profile_version"] == UNSPECIFIED_PROFILE_VERSION
        assert payload["governed"] is False

    def test_matching_profile_but_disabled_falls_back_to_legacy(
        self, pg_container: dict[str, str], clean_db: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write_profile(tmp_path, "a.yml", enabled=False)
        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", _app_dsn(pg_container))
        monkeypatch.setenv("RAG_ENGINE_INGESTION_PROFILES_DIR", str(tmp_path))

        job_id = best_effort_create_ingest_job(
            collection="rag_nexus_nsi_terminale_specialite",
            source_label="eduscol.education.fr",
            source_uri="https://eduscol.education.fr/nsi/algo",
            rights="public_allowed",
            type_doc="cours",
            matiere="nsi",
            niveau="terminale",
            voie="generale",
            audience=["tous"],
            default_tenant="libre_terminale",
            default_candidat="libre",
            default_visibility="internal",
            default_school_year="2026-2027",
            default_programme_version="BOEN_special_8_2019-07-25",
            dedup_key="d" * 64,
        )
        assert job_id is not None

        dsn = (
            f"host={pg_container['host']} port={pg_container['port']} "
            f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
        )
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM ingestion_control.jobs WHERE job_id = %s", (job_id,)
            )
            (payload,) = cur.fetchone()
        assert payload["profile_version"] == UNSPECIFIED_PROFILE_VERSION


class TestBridgeIdempotency:
    def test_same_dedup_key_twice_returns_same_job_id_no_duplicate(
        self, pg_container: dict[str, str], clean_db: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", _app_dsn(pg_container))
        kwargs = dict(
            collection="rag_nexus_nsi_terminale_specialite",
            source_label="eduscol.education.fr",
            source_uri="https://eduscol.education.fr/nsi/algo",
            rights="public_allowed",
            type_doc="cours",
            matiere="nsi",
            niveau="terminale",
            voie="generale",
            audience=["tous"],
            default_tenant="libre_terminale",
            default_candidat="libre",
            default_visibility="internal",
            default_school_year="2026-2027",
            default_programme_version="BOEN_special_8_2019-07-25",
            dedup_key="e" * 64,
        )

        first_job_id = best_effort_create_ingest_job(**kwargs)
        second_job_id = best_effort_create_ingest_job(**kwargs)

        assert first_job_id is not None
        assert second_job_id == first_job_id

        dsn = (
            f"host={pg_container['host']} port={pg_container['port']} "
            f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
        )
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ingestion_control.jobs")
            (job_count,) = cur.fetchone()
        assert job_count == 1

    def test_different_dedup_key_creates_a_second_job(
        self, pg_container: dict[str, str], clean_db: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", _app_dsn(pg_container))
        base_kwargs = dict(
            collection="rag_nexus_nsi_terminale_specialite",
            source_label="eduscol.education.fr",
            source_uri="https://eduscol.education.fr/nsi/algo",
            rights="public_allowed",
            type_doc="cours",
            matiere="nsi",
            niveau="terminale",
            voie="generale",
            audience=["tous"],
            default_tenant="libre_terminale",
            default_candidat="libre",
            default_visibility="internal",
            default_school_year="2026-2027",
            default_programme_version="BOEN_special_8_2019-07-25",
        )

        first_job_id = best_effort_create_ingest_job(dedup_key="1" * 64, **base_kwargs)
        second_job_id = best_effort_create_ingest_job(dedup_key="2" * 64, **base_kwargs)

        assert first_job_id is not None
        assert second_job_id is not None
        assert second_job_id != first_job_id

        dsn = (
            f"host={pg_container['host']} port={pg_container['port']} "
            f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
        )
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ingestion_control.jobs")
            (job_count,) = cur.fetchone()
        assert job_count == 2

    def test_terminal_job_does_not_block_a_new_job_with_same_dedup_key(
        self, pg_container: dict[str, str], clean_db: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", _app_dsn(pg_container))
        kwargs = dict(
            collection="rag_nexus_nsi_terminale_specialite",
            source_label="eduscol.education.fr",
            source_uri="https://eduscol.education.fr/nsi/algo",
            rights="public_allowed",
            type_doc="cours",
            matiere="nsi",
            niveau="terminale",
            voie="generale",
            audience=["tous"],
            default_tenant="libre_terminale",
            default_candidat="libre",
            default_visibility="internal",
            default_school_year="2026-2027",
            default_programme_version="BOEN_special_8_2019-07-25",
            dedup_key="3" * 64,
        )

        first_job_id = best_effort_create_ingest_job(**kwargs)
        assert first_job_id is not None

        dsn = (
            f"host={pg_container['host']} port={pg_container['port']} "
            f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
        )
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_control.jobs SET status = 'succeeded' WHERE job_id = %s",
                (first_job_id,),
            )
            conn.commit()

        second_job_id = best_effort_create_ingest_job(**kwargs)
        assert second_job_id is not None
        assert second_job_id != first_job_id

        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ingestion_control.jobs")
            (job_count,) = cur.fetchone()
        assert job_count == 2
