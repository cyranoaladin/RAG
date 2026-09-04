"""LOT44f (remédiation revue PR#90, passe 2, item I) : attestation du rôle
runtime du worker — PostgreSQL réel.

Périmètre strict : ``ingestion_control.attestation.attest_runtime_role`` et
son câblage dans ``ingestion_worker.cli.main`` — même convention Docker
jetable que les suites LOT44b/44e/44f (``pg_container`` bootstrappé +
provisionné via les scripts réels, jamais une base simulée).
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

from ingestor.ingestion_control.attestation import (  # noqa: E402
    WorkerAttestationError,
    attest_runtime_role,
)
from ingestor.ingestion_profiles.registry import profile_fingerprint  # noqa: E402
from ingestor.ingestion_worker import cli as worker_cli  # noqa: E402
from tests.test_lot44f_worker_heartbeat import _readiness_stub, write_sealed_evidence  # noqa: E402

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
            capture_output=True, check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise TimeoutError(f"Postgres not ready on port {port} after {timeout_s}s")


@pytest.fixture(scope="module")
def pg_container() -> Iterator[dict[str, str]]:
    container_name = f"nexus-lot44f-attestation-{uuid.uuid4().hex[:10]}"
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
        assert "BOOTSTRAP_COMPLETE" in bootstrap.stdout

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
        assert "ROLES_PROVISIONED=1" in provision.stdout

        yield {"host": "127.0.0.1", "port": str(port), "dbname": PG_DB}
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)


def _app_dsn(pg_container: dict[str, str]) -> str:
    return (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user=ingestion_control_app password={APP_PASSWORD}"
    )


def _superuser_dsn(pg_container: dict[str, str]) -> str:
    return (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
    )


def _migrator_dsn(pg_container: dict[str, str]) -> str:
    return (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user=ingestion_control_migrator password={MIGRATOR_PASSWORD}"
    )


class TestAttestRuntimeRoleDirect:
    def test_legitimate_app_role_passes_attestation(self, pg_container: dict[str, str]) -> None:
        with psycopg.connect(_app_dsn(pg_container)) as conn:
            attestation = attest_runtime_role(conn, expected_role="ingestion_control_app")
        assert attestation.current_user == "ingestion_control_app"
        assert attestation.is_superuser is False
        assert attestation.owns_ingestion_control_schema is False
        assert attestation.has_excessive_workflow_events_grant is False
        assert attestation.member_of_other_roles is False

    def test_superuser_connection_is_refused(self, pg_container: dict[str, str]) -> None:
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            with pytest.raises(WorkerAttestationError, match="SUPERUSER"):
                attest_runtime_role(conn, expected_role=PG_SUPERUSER)

    def test_migrator_role_is_refused_as_worker_identity(self, pg_container: dict[str, str]) -> None:
        """Le rôle de migration possède le schéma — même sans être
        superutilisateur, il ne doit jamais être accepté comme identité
        runtime du worker."""
        with psycopg.connect(_migrator_dsn(pg_container)) as conn:
            with pytest.raises(WorkerAttestationError, match="owns schema"):
                attest_runtime_role(conn, expected_role="ingestion_control_migrator")

    def test_mismatched_expected_role_is_refused(self, pg_container: dict[str, str]) -> None:
        with psycopg.connect(_app_dsn(pg_container)) as conn:
            with pytest.raises(WorkerAttestationError, match="does not match expected"):
                attest_runtime_role(conn, expected_role="some_other_role_name")


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
                "provenance": "test-attestation",
                "generated_at": "2026-08-05T00:00:00Z",
                "profiles": [
                    {
                        "collection": "rag_nexus_nsi_terminale_specialite",
                        "profile_version": "v1",
                        "fingerprint": profile_fingerprint(profile),
                        "approved_by": "test-attestation-authority",
                        "approved_at": "2026-08-05T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _worker_argv(
    *, profiles_dir: Path, manifest_path: Path, artifact_dir: Path, expected_role: str
) -> list[str]:
    """L'argv complet qu'un worker de production exige aujourd'hui.

    Ce test appelait `main` avec six arguments. Depuis, toutes les autorités
    de gouvernance sont devenues OBLIGATOIRES sur la ligne de commande, si
    bien que `argparse` sortait en code 2 avant même d'atteindre
    l'attestation : le test ne mesurait plus rien, et son échec ressemblait
    à un défaut d'infrastructure.

    Le durcissement du CLI est la bonne évolution — c'est le banc qui devait
    suivre. Les autorités sont ici des fichiers de forme correcte : leur
    contenu n'est pas le sujet, leur PRÉSENCE l'est. Ce que ce test mesure —
    l'attestation de rôle contre un vrai PostgreSQL — reste entièrement réel.
    """
    root = artifact_dir.parent
    return [
        "--profiles-dir", str(profiles_dir),
        "--manifest-path", str(manifest_path),
        "--artifact-store-dir", str(artifact_dir),
        "--expected-role", expected_role,
        "--owner", "attestation-test",
        *write_sealed_evidence(root),
        "--catalog-path", str(root / "catalog.json"),
        "--catalog-sha256", "3" * 64,
        "--candidate-inventory-path", str(root / "inventory.json"),
        "--candidate-inventory-sha256", "4" * 64,
        "--currentness-evidence-path", str(root / "currentness.yml"),
        "--currentness-evidence-sha256", "5" * 64,
        "--mapping-path", str(root / "mapping.yml"),
        "--mapping-sha256", "6" * 64,
        "--release-manifest-path", str(root / "release.json"),
        "--release-manifest-sha256", "7" * 64,
        "--programme-index-path", str(root / "programme.yml"),
        "--programme-index-sha256", "8" * 64,
        "--collection-config-path", str(root / "collections.yml"),
        "--collection-config-sha256", "9" * 64,
        "--once",
    ]


def _isolate_everything_but_the_attestation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise ce qui n'est PAS mesuré ici — et rien d'autre.

    `attest_runtime_role` et la connexion PostgreSQL réelle restent
    intactes : c'est exactement la garde que ce fichier prouve."""
    from types import SimpleNamespace

    monkeypatch.setattr(worker_cli, "enforce_readiness_gate", _readiness_stub)
    monkeypatch.setattr(
        worker_cli,
        "load_governed_runtime_authorities",
        lambda *_a, **_k: SimpleNamespace(
            pii_evidence_registry=SimpleNamespace(evidence_sha256="1" * 64, cleared_count=1),
            rights_evidence_registry=SimpleNamespace(
                registry_sha256="2" * 64, registry_id="attestation-test"
            ),
            placement_resolver=SimpleNamespace(release_manifest_sha256="3" * 64),
        ),
    )
    monkeypatch.setattr(worker_cli, "_reap_expired_leases", lambda _conn: None)


class TestWorkerCliRefusesSuperuserDsn:
    def test_main_returns_nonzero_and_prints_attestation_failure_for_superuser_dsn(
        self,
        monkeypatch: pytest.MonkeyPatch,
        pg_container: dict[str, str],
        profiles_dir: Path,
        manifest_path: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Revue incrémentale PR#90 (Cubic P1, item I) : preuve directe
        bout-en-bout — ``worker_cli.main`` connecté avec un DSN
        superutilisateur (mauvaise configuration plausible : confusion
        avec le DSN du service ``pgvector`` existant) doit refuser de
        démarrer, jamais entrer dans sa boucle de traitement."""
        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", _superuser_dsn(pg_container))
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir()

        _isolate_everything_but_the_attestation(monkeypatch)
        exit_code = worker_cli.main(
            _worker_argv(
                profiles_dir=profiles_dir,
                manifest_path=manifest_path,
                artifact_dir=artifact_dir,
                expected_role=PG_SUPERUSER,
            )
        )

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "WORKER_ATTESTATION_FAILED" in captured.err
        assert "SUPERUSER" in captured.err

    def test_main_succeeds_past_attestation_with_legitimate_app_role(
        self,
        monkeypatch: pytest.MonkeyPatch,
        pg_container: dict[str, str],
        profiles_dir: Path,
        manifest_path: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Contrôle positif : avec le rôle applicatif légitime, l'attestation
        réussit et le worker atteint sa boucle (``--once`` sans job
        disponible, retour 0) — prouve que le test de refus ci-dessus
        teste bien l'attestation, pas un défaut plus large du montage."""
        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", _app_dsn(pg_container))
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir()

        _isolate_everything_but_the_attestation(monkeypatch)
        exit_code = worker_cli.main(
            _worker_argv(
                profiles_dir=profiles_dir,
                manifest_path=manifest_path,
                artifact_dir=artifact_dir,
                expected_role="ingestion_control_app",
            )
        )

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "WORKER_ATTESTATION_OK current_user=ingestion_control_app" in captured.out
        assert "WORKER_ATTESTATION_FAILED" not in captured.err
