"""LOT44f/ADR-0029 : reprise multi-claims réelle — PostgreSQL réel.

Périmètre strict : la persistance ResourceCandidate/ArtifactRecord
(migration 006, ``ingestion_control.provisioning``) et son exploitation par
``runner.py`` pour sauter Scout/Fetcher lors d'une reprise après crash —
pas une ré-vérification du chemin nominal (déjà couvert par
``test_lot44e_worker_e2e.py``) ni des primitives de bail elles-mêmes
(``JobLeaseConflictError``, déjà couvert par
``test_lot44e_jobs_control.py``).

Même convention Docker jetable que les autres suites LOT44b/44c/44d/44e :
un conteneur PostgreSQL dédié à ce module, migrations + rôles provisionnés
une fois.
"""
from __future__ import annotations

import dataclasses
import hashlib
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg
import pytest
import yaml
from nexus_contracts.ingestion import CollectionProfile

ENGINE_ROOT = Path(__file__).resolve().parents[2]
INFRA_ROOT = ENGINE_ROOT / "infra"
BOOTSTRAP_SCRIPT = INFRA_ROOT / "scripts" / "bootstrap_ingestion_control_schema.sh"
PROVISION_SCRIPT = INFRA_ROOT / "scripts" / "provision_ingestion_control_roles.sh"

sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests"))
sys.path.insert(0, str(ENGINE_ROOT / "scripts"))

from _authorization_stub import (  # noqa: E402
    STUB_AUTHORIZATION_ID,
    verified_authorization,
)
from nexus_contracts.authority_artifacts import (  # noqa: E402
    parse_scope_authorization_artifact,
)
from nexus_contracts.authorization_set import parse_authorization_set  # noqa: E402
from test_sign_production_readiness_manifest_cli import _v2_material  # noqa: E402

from ingestor.ingestion_control.jobs import create_job  # noqa: E402
from ingestor.ingestion_control.scope_authority import (  # noqa: E402
    ScopeAuthorizationDeniedError,
)
from ingestor.ingestion_profiles import readiness_gate as readiness_v2  # noqa: E402
from ingestor.ingestion_profiles.registry import (  # noqa: E402
    load_profile_registry,
    profile_fingerprint,
    select_profile,
)
from ingestor.ingestion_worker.runner import WorkerDeps, run_worker_iteration  # noqa: E402
from ingestor.ingestion_worker.storage import (  # noqa: E402
    make_filesystem_artifact_reader,
    make_filesystem_artifact_store,
)

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


def _profile_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "profile_version": "v1",
        "enabled": True,
        "scope": VALID_SCOPE,
        "title": "NSI Terminale Spécialité",
        "owner": "equipe-nsi",
        "expected_topics": ["algorithmique"],
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
        "min_extraction_quality": 0.1,
    }
    payload.update(overrides)
    return payload


def _job_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "scope": VALID_SCOPE,
        "dedup_key": "r" * 64,
        "source_url": "https://eduscol.education.fr/nsi/resume",
        "canonical_url": "https://eduscol.education.fr/nsi/resume",
        "domain": "eduscol.education.fr",
        "proposed_type_doc": "cours",
        "profile_version": "v1",
        # Item C : un job nomme TOUJOURS son autorisation, explicitement.
        "scope_authorization_id": STUB_AUTHORIZATION_ID,
        "license": "CC-BY-SA",
    }
    payload.update(overrides)
    return payload


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
    container_name = f"nexus-lot44f-worker-resume-{uuid.uuid4().hex[:10]}"
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


@pytest.fixture
def app_conn(pg_container: dict[str, str]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_app_dsn(pg_container), autocommit=False) as conn:
        yield conn


@pytest.fixture
def superuser_conn(pg_container: dict[str, str]) -> Iterator[psycopg.Connection]:
    dsn = (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
    )
    with psycopg.connect(dsn, autocommit=False) as conn:
        yield conn


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


def _insert_run(conn: psycopg.Connection) -> uuid.UUID:
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
                VALID_SCOPE["tenant"], VALID_SCOPE["collection"], VALID_SCOPE["niveau"],
                VALID_SCOPE["voie"], VALID_SCOPE["matiere"], VALID_SCOPE["candidat"],
                VALID_SCOPE["audience"], VALID_SCOPE["visibility"], VALID_SCOPE["school_year"],
                VALID_SCOPE["programme_version"], "v1", "manual",
            ),
        )
        row = cur.fetchone()
        assert row is not None
        return row[0]


def _write_profile(profiles_dir: Path) -> None:
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "nsi.yml").write_text(yaml.safe_dump(_profile_payload()), encoding="utf-8")


#: Digest de manifest arbitraire mais FIXE de ces suites : le worker le
#: porte, l'autorisation stub le déclare, et le point de contrôle pre_fetch
#: les compare pour de vrai (item D).
STUB_MANIFEST_DIGEST = "7" * 64

_STUB_PROFILE = CollectionProfile.model_validate(_profile_payload())


def _stub_registry():
    """Registre équivalent à celui que le worker charge — construit depuis
    le MÊME ``_profile_payload()``, donc de même empreinte."""
    return {
        (_STUB_PROFILE.scope.collection, _STUB_PROFILE.profile_version): _STUB_PROFILE
    }


def _always_authorized(conn, *, authorization_id, scope=None, now=None):
    """Stub LOT41A (ADR-0032) : ce fichier teste la chaîne d'ingestion, jamais
    la frontière GitHub d'autorisation de scope elle-même — reconstruire une
    PR/review/blob GitHub réels ici serait hors périmètre, et c'est couvert
    par les suites dédiées (``test_lot41a_scope_authority.py``, …).

    L'autorisation rendue reste **cohérente avec le job** (mêmes domaines,
    mêmes droits, même profil, même manifest) : les points de contrôle
    d'enforcement (item D) s'exécutent donc réellement ici, et un job hors
    périmètre y échouerait comme en production. Le stub refuse d'ailleurs un
    ``authorization_id`` qu'il ne connaît pas, exactement comme la
    vérification réelle."""
    if authorization_id != STUB_AUTHORIZATION_ID:
        raise ScopeAuthorizationDeniedError(
            f"no scope_authorizations row with authorization_id={authorization_id!r}"
        )
    profile = select_profile(
        _stub_registry(), collection=VALID_SCOPE["collection"], profile_version="v1"
    )
    return verified_authorization(
        scope=scope if scope is not None else VALID_SCOPE,
        manifest_digest=STUB_MANIFEST_DIGEST,
        profile_id=profile.scope.collection,
        profile_version=profile.profile_version,
        profile_fingerprint=profile_fingerprint(profile),
    )
    return verified_authorization(
        scope=scope if scope is not None else VALID_SCOPE,
        manifest_digest=STUB_MANIFEST_DIGEST,
        profile_id=profile.scope.collection,
        profile_version=profile.profile_version,
        profile_fingerprint=profile_fingerprint(profile),
    )


_RESUME_CONTENT = b"<p>Cours d'algorithmique pour la terminale (reprise).</p>"
#: Manifeste de corpus des preuves scellées de ce banc.
_CORPUS_MANIFEST_SHA = "d" * 64


def _sealed_registries(tmp_path: Path) -> dict[str, object]:
    """Registres scellés RÉELS, couvrant le contenu de ce banc.

    Ce fichier construisait des `WorkerDeps` sans registres. Depuis que la
    preuve scellée est obligatoire, chaque itération échouait avant d'agir et
    les trois tests de reprise observaient `retried` au lieu de `succeeded` :
    ils ne mesuraient plus la reprise du tout.

    `non_publishable=True` les aurait rendus verts en sautant la mise en
    revue — donc en supprimant précisément l'étape dont ces tests vérifient
    qu'elle n'est PAS rejouée. Les registres sont réels, et la zone approuvée
    couvre l'URL de ce banc pour que le job puisse réussir."""
    import hashlib
    import json

    from ingestor.ingestion_control.sealed_evidence import (
        VerifiedPIIEvidenceRegistry,
        VerifiedRightsEvidenceRegistry,
    )

    root = tmp_path / "sealed"
    root.mkdir(parents=True, exist_ok=True)
    zone = "https://eduscol.education.fr/"
    pii = root / "pii.json"
    pii.write_text(
        json.dumps(
            {
                "evidence_kind": "REAL_CORPUS_PII_SCAN",
                "corpus_manifest_sha256": _CORPUS_MANIFEST_SHA,
                "remote_access_mode": "READ_ONLY",
                "remote_write_operations": 0,
                "raw_pii_in_output": False,
                "raw_pii_in_logs": False,
                "results": [
                    {
                        "content_sha256": hashlib.sha256(_RESUME_CONTENT).hexdigest(),
                        "status": "CLEARED",
                        "pii_detected": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    rights = root / "rights.yml"
    rights.write_text(
        "registry_id: worker-resume\n"
        "human_rights_decisions:\n"
        "  eduscol:\n"
        f'    scope_manifest_sha256: "{_CORPUS_MANIFEST_SHA}"\n'
        f"    scope_zone: {zone}\n"
        "    approved_for_production_rag: true\n"
        "source_evidence:\n"
        "  eduscol:\n"
        f"    zone: {zone}\n"
        "    recommended_rights_category: officiel_public\n",
        encoding="utf-8",
    )
    return {
        "pii_evidence_registry": VerifiedPIIEvidenceRegistry.load(
            pii,
            expected_evidence_sha256=hashlib.sha256(pii.read_bytes()).hexdigest(),
            expected_corpus_manifest_sha256=_CORPUS_MANIFEST_SHA,
        ),
        "rights_evidence_registry": VerifiedRightsEvidenceRegistry.load(
            rights,
            expected_registry_sha256=hashlib.sha256(rights.read_bytes()).hexdigest(),
            expected_corpus_manifest_sha256=_CORPUS_MANIFEST_SHA,
        ),
    }


def _worker_deps(tmp_path: Path, *, safe_fetch, owner: str = "worker-e2e") -> WorkerDeps:
    profiles_dir = tmp_path / "profiles"
    _write_profile(profiles_dir)
    return WorkerDeps(
        owner=owner,
        profile_registry=load_profile_registry(profiles_dir),
        artifact_store=make_filesystem_artifact_store(tmp_path / "artifacts"),
        artifact_reader=make_filesystem_artifact_reader(tmp_path / "artifacts"),
        validate_destination=lambda url: url,
        safe_fetch=safe_fetch,
        verify_scope_authorization=_always_authorized,
        manifest_digest=STUB_MANIFEST_DIGEST,
        **_sealed_registries(tmp_path),
    )


def _real_v2_runtime() -> tuple[
    readiness_v2.RuntimeAuthorizationContext,
    object,
]:
    material = _v2_material()
    runtime = readiness_v2.RuntimeV2ReleaseMaterial.from_signing_material(material)
    _verified, mapping = readiness_v2._verify_v2_material(runtime)
    member = parse_authorization_set(material.authorization_set_raw).members[0]
    authorization = parse_scope_authorization_artifact(
        material.release_files[member.authorization_path]
    )

    def refresh():
        _, refreshed = readiness_v2._verify_v2_material(
            dataclasses.replace(runtime, now=datetime.now(UTC))
        )
        return refreshed

    return readiness_v2.RuntimeAuthorizationContext(mapping, refresh), authorization


def _v2_worker_deps(tmp_path: Path, *, safe_fetch, artifact_store=None) -> WorkerDeps:
    context, authorization = _real_v2_runtime()
    base = _worker_deps(tmp_path, safe_fetch=safe_fetch)
    profiles_dir = tmp_path / "profiles"
    (profiles_dir / "nsi.yml").write_bytes(
        _v2_material().release_scope_source_blobs["profiles/nsi.yml"]
    )
    live = verified_authorization(
        scope=authorization.scope,
        manifest_digest=authorization.manifest_digest,
        profile_id=authorization.profile_id,
        profile_version=authorization.profile_version,
        profile_fingerprint=authorization.profile_fingerprint,
        allowed_domains=tuple(authorization.allowed_domains),
        rights_categories=tuple(value.value for value in authorization.rights_categories),
        protocol_version="LOT41A-V2",
        allowed_content_sha256=tuple(authorization.allowed_content_sha256),
        authorization_id=authorization.authorization_id,
        valid_from=authorization.valid_from,
        valid_until=authorization.valid_until,
    )
    live = dataclasses.replace(
        live,
        authorization_digest=context.mapping.authorization_digest(
            authorization.authorization_id
        ),
    )

    def verify_live(_conn, *, authorization_id, scope=None, now=None):
        if authorization_id != live.authorization_id:
            raise ScopeAuthorizationDeniedError("unknown authorization")
        return live

    return dataclasses.replace(
        base,
        profile_registry=load_profile_registry(profiles_dir),
        artifact_store=artifact_store or base.artifact_store,
        verify_scope_authorization=verify_live,
        manifest_digest=authorization.manifest_digest,
        authorization_mapping=context.mapping,
        authorization_context=context,
    )


def _fake_safe_fetch_success(url: str, *, max_bytes: int, **kwargs: object) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/html"},
        content=b"<p>Cours d'algorithmique pour la terminale (reprise).</p>",
        request=httpx.Request("GET", url),
    )


class TestRuntimeAuthorizationSetCheckpoints:
    def test_unknown_downloaded_sha_is_refused_before_artifact_write(
        self, tmp_path: Path, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        context, authorization = _real_v2_runtime()
        run_id = _insert_run(app_conn)
        create_job(
            app_conn,
            run_id=run_id,
            job_type="resource_pipeline",
            payload=_job_payload(
                scope_authorization_id=authorization.authorization_id,
            ),
        )
        app_conn.commit()
        writes: list[bytes] = []

        def store(*, artifact_id, content):
            writes.append(content)
            return str(tmp_path / str(artifact_id))

        deps = _v2_worker_deps(
            tmp_path,
            safe_fetch=_fake_safe_fetch_success,
            artifact_store=store,
        )
        outcome = run_worker_iteration(app_conn, deps=deps)

        assert outcome.status == "retried"
        assert "unknown content_sha256" in (outcome.error or "")
        assert writes == []
        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM ingestion_control.artifacts",
            )
            assert cur.fetchone()[0] == 0

    def test_revocation_between_prefetch_and_live_check_stops_before_fetch_or_write(
        self, tmp_path: Path, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        context, authorization = _real_v2_runtime()
        run_id = _insert_run(app_conn)
        create_job(
            app_conn,
            run_id=run_id,
            job_type="resource_pipeline",
            payload=_job_payload(
                scope_authorization_id=authorization.authorization_id,
            ),
        )
        app_conn.commit()

        class RevokedAfterPrefetch:
            mapping = context.mapping
            calls = 0

            def reverify(self):
                self.calls += 1
                if self.calls > 1:
                    raise readiness_v2.ReadinessGateError("authorization revoked")
                return context.reverify()

        fetches: list[str] = []

        def forbidden_fetch(url: str, *, max_bytes: int, **kwargs: object):
            fetches.append(url)
            raise AssertionError("fetch reached after runtime revocation")

        deps = dataclasses.replace(
            _v2_worker_deps(tmp_path, safe_fetch=forbidden_fetch),
            authorization_context=RevokedAfterPrefetch(),
        )
        outcome = run_worker_iteration(app_conn, deps=deps)

        assert outcome.status == "retried"
        assert "revoked" in (outcome.error or "")
        assert fetches == []
        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM ingestion_control.artifacts",
            )
            assert cur.fetchone()[0] == 0

    def test_stored_resume_cannot_bypass_the_real_set_postfetch_checkpoint(
        self, tmp_path: Path, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        context, authorization = _real_v2_runtime()
        run_id = _insert_run(app_conn)
        job_id = create_job(
            app_conn,
            run_id=run_id,
            job_type="resource_pipeline",
            payload=_job_payload(
                scope_authorization_id=authorization.authorization_id,
            ),
        )
        app_conn.commit()
        downloaded = b"<p>Cours d'algorithmique pour la terminale (reprise).</p>"
        downloaded_sha = hashlib.sha256(downloaded).hexdigest()
        permissive = verified_authorization(
            scope=authorization.scope,
            manifest_digest=authorization.manifest_digest,
            profile_id=authorization.profile_id,
            profile_version=authorization.profile_version,
            profile_fingerprint=authorization.profile_fingerprint,
            allowed_domains=tuple(authorization.allowed_domains),
            rights_categories=tuple(
                value.value for value in authorization.rights_categories
            ),
            protocol_version="LOT41A-V2",
            allowed_content_sha256=(downloaded_sha,),
            authorization_id=authorization.authorization_id,
            valid_from=authorization.valid_from,
            valid_until=authorization.valid_until,
        )
        permissive = dataclasses.replace(
            permissive,
            authorization_digest=context.mapping.authorization_digest(
                authorization.authorization_id
            ),
        )

        def verify_permissive(_conn, *, authorization_id, scope=None, now=None):
            assert authorization_id == permissive.authorization_id
            return permissive

        first_deps = dataclasses.replace(
            _v2_worker_deps(tmp_path, safe_fetch=_fake_safe_fetch_success),
            authorization_mapping=None,
            authorization_context=None,
            verify_scope_authorization=verify_permissive,
            artifact_reader=lambda _path: (_ for _ in ()).throw(
                RuntimeError("crash after STORED")
            ),
        )
        first = run_worker_iteration(app_conn, deps=first_deps)
        assert first.status == "retried"
        _reset_next_attempt_now(app_conn, job_id=job_id)

        reads: list[str] = []

        def forbidden_read(path: str) -> bytes:
            reads.append(path)
            raise AssertionError("extractor reached after STORED mapping refusal")

        second_deps = dataclasses.replace(
            _v2_worker_deps(tmp_path, safe_fetch=lambda *_a, **_k: pytest.fail("refetch")),
            artifact_reader=forbidden_read,
        )
        second = run_worker_iteration(app_conn, deps=second_deps)

        assert second.status == "retried"
        assert "unknown content_sha256" in (second.error or "")
        assert reads == []


def _reset_next_attempt_now(conn: psycopg.Connection, *, job_id: uuid.UUID) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE ingestion_control.jobs SET next_attempt_at = now() WHERE job_id = %s",
            (job_id,),
        )
    conn.commit()


class TestCrashAfterScoutResumesFromFetcher:
    def test_scout_not_rerun_candidate_reused(
        self, tmp_path: Path, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(app_conn)
        job_id = create_job(
            app_conn, run_id=run_id, job_type="resource_pipeline", payload=_job_payload()
        )
        app_conn.commit()

        def failing_safe_fetch(url: str, *, max_bytes: int, **kwargs: object) -> httpx.Response:
            raise RuntimeError("simulated crash inside Fetcher")

        failing_deps = _worker_deps(tmp_path, safe_fetch=failing_safe_fetch, owner="worker-A")
        first = run_worker_iteration(app_conn, deps=failing_deps)
        assert first.status == "retried"

        # Point de contrôle durable : Scout a committé (CANDIDATE), un seul
        # candidat persisté, resource_id rattaché au job (LOT44f).
        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT resource_state, resource_id FROM ingestion_control.resources "
                "WHERE run_id = %s",
                (run_id,),
            )
            resource_state, resource_id_after_crash = cur.fetchone()
            cur.execute(
                "SELECT candidate_id FROM ingestion_control.resource_candidates "
                "WHERE resource_id = %s",
                (resource_id_after_crash,),
            )
            candidate_rows = cur.fetchall()
            cur.execute(
                "SELECT resource_id FROM ingestion_control.jobs WHERE job_id = %s", (job_id,)
            )
            (job_resource_id,) = cur.fetchone()
        assert resource_state == "CANDIDATE"
        assert len(candidate_rows) == 1
        first_candidate_id = candidate_rows[0][0]
        assert job_resource_id == resource_id_after_crash

        _reset_next_attempt_now(app_conn, job_id=job_id)

        succeeding_deps = _worker_deps(tmp_path, safe_fetch=_fake_safe_fetch_success, owner="worker-B")
        second = run_worker_iteration(app_conn, deps=succeeding_deps)
        assert second.status == "succeeded"
        assert second.job_id == job_id

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT candidate_id FROM ingestion_control.resource_candidates "
                "WHERE resource_id = %s",
                (resource_id_after_crash,),
            )
            candidate_rows_after = cur.fetchall()
            cur.execute(
                "SELECT resource_state FROM ingestion_control.resources WHERE run_id = %s",
                (run_id,),
            )
            (final_state,) = cur.fetchone()
        assert len(candidate_rows_after) == 1, "Scout ne doit jamais être rejoué : un seul candidat"
        assert candidate_rows_after[0][0] == first_candidate_id, (
            "le candidat repris doit être exactement celui persisté avant le crash"
        )
        assert final_state == "QUALITY_CHECKED"


class TestCrashAfterFetcherResumesFromExtractor:
    def test_fetcher_not_rerun_artifact_reused(
        self, tmp_path: Path, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(app_conn)
        job_id = create_job(
            app_conn, run_id=run_id, job_type="resource_pipeline", payload=_job_payload()
        )
        app_conn.commit()

        profiles_dir = tmp_path / "profiles"
        _write_profile(profiles_dir)

        def failing_read_artifact(path: str) -> bytes:
            raise RuntimeError("simulated crash inside Extractor")

        from ingestor.ingestion_worker.storage import make_filesystem_artifact_store

        crashing_deps = WorkerDeps(
            owner="worker-A",
            profile_registry=load_profile_registry(profiles_dir),
            artifact_store=make_filesystem_artifact_store(tmp_path / "artifacts"),
            artifact_reader=failing_read_artifact,
            validate_destination=lambda url: url,
            safe_fetch=_fake_safe_fetch_success,
            verify_scope_authorization=_always_authorized,
            manifest_digest=STUB_MANIFEST_DIGEST,
            **_sealed_registries(tmp_path),
        )
        first = run_worker_iteration(app_conn, deps=crashing_deps)
        assert first.status == "retried"

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT resource_state, resource_id FROM ingestion_control.resources "
                "WHERE run_id = %s",
                (run_id,),
            )
            resource_state, resource_id_after_crash = cur.fetchone()
            cur.execute(
                "SELECT artifact_id FROM ingestion_control.artifacts WHERE resource_id = %s",
                (resource_id_after_crash,),
            )
            artifact_rows = cur.fetchall()
        assert resource_state == "STORED"
        assert len(artifact_rows) == 1
        first_artifact_id = artifact_rows[0][0]

        _reset_next_attempt_now(app_conn, job_id=job_id)

        succeeding_deps = _worker_deps(tmp_path, safe_fetch=_fake_safe_fetch_success, owner="worker-B")
        second = run_worker_iteration(app_conn, deps=succeeding_deps)
        assert second.status == "succeeded"

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT artifact_id FROM ingestion_control.artifacts WHERE resource_id = %s",
                (resource_id_after_crash,),
            )
            artifact_rows_after = cur.fetchall()
            cur.execute(
                "SELECT resource_state FROM ingestion_control.resources WHERE run_id = %s",
                (run_id,),
            )
            (final_state,) = cur.fetchone()
        assert len(artifact_rows_after) == 1, "Fetcher ne doit jamais être rejoué : un seul artefact"
        assert artifact_rows_after[0][0] == first_artifact_id
        assert final_state == "QUALITY_CHECKED"


class TestResumeByDifferentWorker:
    def test_a_different_worker_completes_the_job_after_retry(
        self, tmp_path: Path, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        """Après un échec géré par record_job_retry (bail relâché,
        status='queued'), n'importe quel worker peut réclamer et terminer
        le job — pas nécessairement celui qui a échoué."""
        run_id = _insert_run(app_conn)
        job_id = create_job(
            app_conn, run_id=run_id, job_type="resource_pipeline", payload=_job_payload()
        )
        app_conn.commit()

        def failing_safe_fetch(url: str, *, max_bytes: int, **kwargs: object) -> httpx.Response:
            raise RuntimeError("simulated crash")

        first = run_worker_iteration(
            app_conn, deps=_worker_deps(tmp_path, safe_fetch=failing_safe_fetch, owner="worker-A")
        )
        assert first.status == "retried"

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT claimed_by FROM ingestion_control.jobs WHERE job_id = %s", (job_id,)
            )
            (claimed_by_after_retry,) = cur.fetchone()
        assert claimed_by_after_retry is None, "le bail doit être relâché après un retry"

        _reset_next_attempt_now(app_conn, job_id=job_id)

        second = run_worker_iteration(
            app_conn,
            deps=_worker_deps(tmp_path, safe_fetch=_fake_safe_fetch_success, owner="worker-B"),
        )
        assert second.status == "succeeded"

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT claimed_by, status FROM ingestion_control.jobs WHERE job_id = %s",
                (job_id,),
            )
            claimed_by_final, status_final = cur.fetchone()
        assert status_final == "succeeded"
        # complete_job libère le bail (claimed_by=NULL) même en cas de succès —
        # ce test vérifie seulement que worker-B a bien pu réclamer et
        # terminer un job laissé par worker-A, pas l'état final du bail.
        assert claimed_by_final is None


class TestDoubleExecutionIsPrevented:
    def test_second_claim_finds_no_job_while_first_holds_the_lease(
        self, clean_db: None, pg_container: dict[str, str]
    ) -> None:
        """Deux workers ne peuvent jamais traiter le même job en parallèle :
        claim_job utilise FOR UPDATE SKIP LOCKED (LOT44b/44e) — une
        connexion distincte ne voit aucun job réclamable tant que la
        première détient le bail (non commité)."""
        with psycopg.connect(_app_dsn(pg_container), autocommit=False) as conn_a, \
             psycopg.connect(_app_dsn(pg_container), autocommit=False) as conn_b:
            run_id = _insert_run(conn_a)
            job_id = create_job(
                conn_a, run_id=run_id, job_type="resource_pipeline", payload=_job_payload()
            )
            conn_a.commit()

            from ingestor.ingestion_control.jobs import claim_job

            claim_a = claim_job(conn_a, owner="worker-A")
            assert claim_a is not None
            assert claim_a.job_id == job_id
            # conn_a.commit() volontairement omis : simule un worker qui a
            # réclamé le job et n'a pas encore relâché sa transaction — le
            # verrou FOR UPDATE SKIP LOCKED reste posé tant que non commité.

            claim_b = claim_job(conn_b, owner="worker-B")
            assert claim_b is None, "un deuxième worker ne doit jamais réclamer le même job"

            conn_a.rollback()
