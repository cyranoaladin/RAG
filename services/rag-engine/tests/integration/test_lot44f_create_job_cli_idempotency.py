"""LOT44f (remédiation revue PR#90, passe 2) : ``ingestion_worker.
create_job_cli`` — idempotence collection-scopée (Cubic P1
``3725929007``) et absence de run orphelin sur soumission dupliquée
(Cubic P2 ``3725929028``) — PostgreSQL réel.
"""
from __future__ import annotations

import os
import secrets
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
import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[2]
INFRA_ROOT = ENGINE_ROOT / "infra"
BOOTSTRAP_SCRIPT = INFRA_ROOT / "scripts" / "bootstrap_ingestion_control_schema.sh"
PROVISION_SCRIPT = INFRA_ROOT / "scripts" / "provision_ingestion_control_roles.sh"

sys.path.insert(0, str(ENGINE_ROOT / "src"))

from nexus_contracts.ingestion import CollectionProfile  # noqa: E402

from ingestor.ingestion_profiles.registry import profile_fingerprint  # noqa: E402
from ingestor.ingestion_worker import create_job_cli  # noqa: E402

PG_IMAGE = "pgvector/pgvector:pg16"
PG_SUPERUSER = "raguser"
PG_SUPERUSER_PASSWORD = secrets.token_urlsafe(24)  # revue PR#90 : jamais un litteral statique
PG_DB = "ragdb"
APP_PASSWORD = secrets.token_urlsafe(24)  # revue PR#90 : jamais un litteral statique
MIGRATOR_PASSWORD = secrets.token_urlsafe(24)  # revue PR#90 : jamais un litteral statique
AUTHORITY_PASSWORD = secrets.token_urlsafe(24)  # revue PR#90 : jamais un litteral statique
ATTESTOR_PASSWORD = secrets.token_urlsafe(24)  # revue PR#90 : jamais un litteral statique

_DOCKER_AVAILABLE = shutil.which("docker") is not None and (
    subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DOCKER_AVAILABLE, reason="Docker not available"),
]

COLLECTION = "rag_nexus_nsi_terminale_specialite"
VALID_SCOPE = {
    "tenant": "libre_terminale",
    "collection": COLLECTION,
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
            capture_output=True, check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise TimeoutError(f"Postgres not ready on port {port} after {timeout_s}s")


@pytest.fixture(scope="module")
def pg_container() -> Iterator[dict[str, str]]:
    container_name = f"nexus-lot44f-createjob-{uuid.uuid4().hex[:10]}"
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
            "INGESTION_CONTROL_AUTHORITY_PASSWORD": AUTHORITY_PASSWORD,
            "INGESTION_CONTROL_ATTESTOR_PASSWORD": ATTESTOR_PASSWORD,
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


def _superuser_conn(pg_container: dict[str, str]) -> psycopg.Connection:
    return psycopg.connect(
        host=pg_container["host"], port=pg_container["port"], dbname=pg_container["dbname"],
        user=PG_SUPERUSER, password=PG_SUPERUSER_PASSWORD, autocommit=True,
    )


@pytest.fixture
def clean_db(pg_container: dict[str, str]) -> None:
    with _superuser_conn(pg_container) as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE ingestion_control.jobs, ingestion_control.workflow_events, "
            "ingestion_control.artifacts, ingestion_control.resource_candidates, "
            "ingestion_control.resources, ingestion_control.ingestion_runs CASCADE"
        )


def _profile_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "profile_version": "v1",
        "enabled": True,
        "scope": VALID_SCOPE,
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
    return payload


@pytest.fixture
def profiles_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "profiles"
    directory.mkdir()
    (directory / "a.yml").write_text(yaml.safe_dump(_profile_payload()), encoding="utf-8")
    return directory


@pytest.fixture
def manifest_path(tmp_path: Path, profiles_dir: Path) -> Path:
    profile = CollectionProfile.model_validate(_profile_payload())
    path = tmp_path / "manifest.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "manifest_version": "1",
                "provenance": "test-create-job-cli",
                "generated_at": "2026-08-05T00:00:00Z",
                "profiles": [
                    {
                        "collection": COLLECTION,
                        "profile_version": "v1",
                        "fingerprint": profile_fingerprint(profile),
                        "approved_by": "test-create-job-cli-authority",
                        "approved_at": "2026-08-05T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _cli_args(profiles_dir: Path, manifest_path: Path, *, canonical_url: str) -> list[str]:
    return [
        "--profiles-dir", str(profiles_dir),
        "--manifest-path", str(manifest_path),
        "--tenant", VALID_SCOPE["tenant"],
        "--collection", VALID_SCOPE["collection"],
        "--niveau", VALID_SCOPE["niveau"],
        "--voie", VALID_SCOPE["voie"],
        "--matiere", VALID_SCOPE["matiere"],
        "--candidat", VALID_SCOPE["candidat"],
        "--audience", ",".join(VALID_SCOPE["audience"]),
        "--visibility", VALID_SCOPE["visibility"],
        "--school-year", VALID_SCOPE["school_year"],
        "--programme-version", VALID_SCOPE["programme_version"],
        "--profile-version", "v1",
        "--source-url", canonical_url,
        "--canonical-url", canonical_url,
        "--domain", "eduscol.education.fr",
        "--proposed-type-doc", "cours",
    ]


class TestDuplicateSubmissionDoesNotOrphanARun:
    def test_duplicate_submission_leaves_no_orphaned_planned_run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        pg_container: dict[str, str],
        clean_db: None,
        profiles_dir: Path,
        manifest_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Revue incrémentale PR#90 (Cubic P2, ``3725929028``) : avant ce
        correctif, ``create_ingestion_run`` insérait toujours une nouvelle
        ligne ``ingestion_runs`` (``status='planned'``) avant même de
        savoir si un job actif existait déjà — une soumission dupliquée
        laissait cette ligne orpheline, jamais référencée par aucun job,
        bloquée en ``'planned'`` pour toujours. Corrigé en marquant cette
        ligne ``'cancelled'`` (jamais supprimée : le rôle applicatif ne
        détient pas DELETE sur ``ingestion_runs``, privilège
        volontairement absent — cf. ``provision_ingestion_control_roles.
        sh``)."""
        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", _app_dsn(pg_container))
        canonical_url = f"https://eduscol.education.fr/probe-{uuid.uuid4().hex}"

        exit_code_1 = create_job_cli.main(_cli_args(profiles_dir, manifest_path, canonical_url=canonical_url))
        assert exit_code_1 == 0
        first_output = capsys.readouterr().out
        assert "JOB_CREATED" in first_output

        exit_code_2 = create_job_cli.main(_cli_args(profiles_dir, manifest_path, canonical_url=canonical_url))
        assert exit_code_2 == 0
        second_output = capsys.readouterr().out
        assert "JOB_ALREADY_ACTIVE" in second_output

        with _superuser_conn(pg_container) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM ingestion_control.jobs "
                "WHERE payload->>'canonical_url' = %s", (canonical_url,),
            )
            (job_count,) = cur.fetchone()
            assert job_count == 1, "exactly one job must exist after two identical submissions"

            cur.execute(
                "SELECT count(*) FROM ingestion_control.ingestion_runs WHERE status = 'planned' "
                "AND run_id NOT IN (SELECT run_id FROM ingestion_control.jobs)"
            )
            (orphaned_planned_runs,) = cur.fetchone()
            assert orphaned_planned_runs == 0, (
                "the duplicate submission must never leave a 'planned' ingestion_runs "
                "row with no job referencing it"
            )

            cur.execute("SELECT count(*), status FROM ingestion_control.ingestion_runs GROUP BY status")
            rows = cur.fetchall()
            statuses = {status: count for count, status in rows}
            assert statuses.get("cancelled") == 1, (
                "the duplicate submission's own (unreferenced) run must be marked "
                "'cancelled', not left dangling or silently deleted"
            )
            assert sum(statuses.values()) == 2, (
                "exactly two ingestion_runs rows total: the real one (referenced by "
                "the single job) and the cancelled duplicate"
            )

    def test_same_url_in_a_different_collection_creates_a_second_job_and_run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        pg_container: dict[str, str],
        clean_db: None,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Revue incrémentale PR#90 (Cubic P1, ``3725929007``) : preuve
        bout-en-bout, via le CLI opérateur réel, que l'identité
        d'idempotence est ``(collection, dedup_key)`` — la même URL
        soumise pour deux collections distinctes crée deux jobs actifs
        indépendants."""
        second_collection = "rag_nexus_maths_terminale_specialite"
        second_scope = dict(VALID_SCOPE, collection=second_collection)

        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "a.yml").write_text(yaml.safe_dump(_profile_payload()), encoding="utf-8")
        (profiles_dir / "b.yml").write_text(
            yaml.safe_dump(_profile_payload(scope=second_scope)), encoding="utf-8"
        )

        profile_a = CollectionProfile.model_validate(_profile_payload())
        profile_b = CollectionProfile.model_validate(_profile_payload(scope=second_scope))
        manifest_path = tmp_path / "manifest.yml"
        manifest_path.write_text(
            yaml.safe_dump(
                {
                    "manifest_version": "1",
                    "provenance": "test-create-job-cli-multi-collection",
                    "generated_at": "2026-08-05T00:00:00Z",
                    "profiles": [
                        {
                            "collection": COLLECTION, "profile_version": "v1",
                            "fingerprint": profile_fingerprint(profile_a),
                            "approved_by": "test-authority", "approved_at": "2026-08-05T00:00:00Z",
                        },
                        {
                            "collection": second_collection, "profile_version": "v1",
                            "fingerprint": profile_fingerprint(profile_b),
                            "approved_by": "test-authority", "approved_at": "2026-08-05T00:00:00Z",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", _app_dsn(pg_container))
        canonical_url = f"https://eduscol.education.fr/shared-{uuid.uuid4().hex}"

        args_first = _cli_args(profiles_dir, manifest_path, canonical_url=canonical_url)
        exit_code_1 = create_job_cli.main(args_first)
        assert exit_code_1 == 0
        assert "JOB_CREATED" in capsys.readouterr().out

        args_second = _cli_args(profiles_dir, manifest_path, canonical_url=canonical_url)
        collection_index = args_second.index("--collection") + 1
        args_second[collection_index] = second_collection
        exit_code_2 = create_job_cli.main(args_second)
        assert exit_code_2 == 0
        assert "JOB_CREATED" in capsys.readouterr().out, (
            "a submission in a different collection with the same URL must create "
            "its own job, never be treated as a duplicate"
        )

        with _superuser_conn(pg_container) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM ingestion_control.jobs "
                "WHERE payload->>'canonical_url' = %s", (canonical_url,),
            )
            (job_count,) = cur.fetchone()
            assert job_count == 2
