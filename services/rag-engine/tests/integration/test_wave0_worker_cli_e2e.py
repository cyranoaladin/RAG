"""E2E subprocess des deux workers Wave 0 sur PostgreSQL jetable.

Ce test opt-in n'appelle jamais ``main()`` et ne remplace aucune fonction
des CLIs. Les opérateurs LOT41A/LOT42 et les workers A/B s'exécutent dans
des processus Python distincts, avec les preuves réelles et l'artefact E5
réel nommés par l'environnement d'acceptance.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import uuid
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ENGINE_ROOT.parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _local_github import (  # noqa: E402
    REPOSITORY,
    VALID_TOKEN,
    LocalGitHub,
    local_github_server,
)
from _pg_authority import (  # noqa: E402
    PG_DB,
    PG_IMAGE,
    PG_SUPERUSER,
    PG_SUPERUSER_PASSWORD,
    _wait_pg_isready,
    app_dsn,
    attestor_dsn,
    authority_dsn,
    free_port,
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)
from nexus_contracts.authority_artifacts import (  # noqa: E402
    ScopeAuthorizationArtifactV2,
    canonical_authorization_path,
)
from nexus_contracts.document import Rights  # noqa: E402
from nexus_contracts.production_readiness import (  # noqa: E402
    PRODUCTION_READINESS_PROTOCOL_VERSION,
    ProductionReadinessManifestV1,
    public_readiness_key_hex,
    sign_production_readiness_manifest,
)

from ingestor.ingestion_control.jobs import create_job  # noqa: E402
from ingestor.ingestion_profiles.manifest import verify_profile_manifest  # noqa: E402
from ingestor.ingestion_profiles.registry import (  # noqa: E402
    load_profile_registry,
    profile_fingerprint,
)

pytestmark = [pytest.mark.integration, requires_docker]

MATHS_SHA = "49ccdca4d97ba4cf25875dfc731474e84d0332985c15396d3abfb9107f5f545a"
CORPUS_MANIFEST_SHA = "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
CATALOG_SHA = "301c0dcce4e49cd9b6e524708bde82b262a09b05bd52e0431233813ecf8ae04b"
CURRENTNESS_SHA = "75d77994809a81ed9f9452eace75448d3869ef4b8ee1942693f66f430ec27f36"
PROGRAMME_INDEX_SHA = "d5b2bbfe97d0a2e8b85f446c2d3f862798d03db4f8cf48a22cf22e1cb4da0f45"
PII_SHA = "63d0879358a844b44f41c82d21c0b67349e0f7a2f1cdabe7becff2affc58f9f1"
RIGHTS_SHA = "e3c9a157f1f78171c0052750fa08b7726b99ea4dd348728f1b90db07f93ef1ff"
INVENTORY_SHA = "0c203af33d97f787f4fcbbf96ae822d37464d571be96074babf5abb529aaf882"
MAPPING_SHA = "f2c940d979bd6cc740c44882fcba6e44090636f9f793226c2a627ff0c9cbcc1c"
RELEASE_SHA = "0cf9c5d8ceaa2766aa97195743e949ec0a907ed0f609f116275a7d1f8202498d"
EMBEDDING_INVENTORY_SHA = "e2c7384ba36096b3f3bdfff4973f728596104aff0f1d38f1b6463e60765fe22a"
COLLECTION = "rag_nexus_maths_troisieme_tc"
PROFILE_VERSION = "wave0-v1"
AUTHORIZATION_ID = "wave0-maths-troisieme-cli-e2e-v1"
REVIEW_ID = "wave0-maths-troisieme-cli-publication-v1"
AUTH_PR = 9591
PUB_PR = 9592
BASE_HEAD = "9" * 40
AUTH_HEAD = "a" * 40
PUB_HEAD = "b" * 40
SOURCE_URL = (
    "https://eduscol.education.gouv.fr/sites/default/files/document/"
    "18-maths-3e-attendus-eduscol1114748pdf-74688.pdf"
)
CANONICAL_URL = (
    "https://eduscol.education.gouv.fr/5736/"
    "ressources-d-accompagnement-du-programme-de-mathematiques-au-cycle-4"
)
SOURCE_PATH = (
    "01_EDUSCOL_OFFICIEL/COLLEGE/3E/MATHEMATIQUES/02_REPERES_ATTENDUS/2019/"
    "attendus-de-fin-d-annee-en-mathematiques-en-3e-pdf-1-26-mo--49ccdca4d9.pdf"
)

PROFILES_DIR = ENGINE_ROOT / "configs" / "ingestion_profiles" / "staging"
PROFILE_MANIFEST = ENGINE_ROOT / "configs" / "ingestion_manifest_wave0_staging.yml"
COLLECTION_CONFIG = ENGINE_ROOT / "configs" / "staging" / "rag_collections_wave0.yml"
MAPPING_PATH = ENGINE_ROOT / "configs" / "mappings" / "eduscol_wave0_document_types.yml"
CURRENTNESS_PATH = (
    REPOSITORY_ROOT
    / "services"
    / "rag-pedago"
    / "configs"
    / "prerentree_2026_2027"
    / "wave0_currentness_evidence_v2.yml"
)
RELEASE_ROOT = (
    REPOSITORY_ROOT
    / "services"
    / "rag-pedago"
    / "data"
    / "releases"
    / "prerentree_2026_2027"
    / "wave0"
)
INVENTORY_PATH = RELEASE_ROOT / "wave0_candidate_inventory.json"
RELEASE_PATH = RELEASE_ROOT / "wave0.release.json"
RIGHTS_PATH = (
    REPOSITORY_ROOT / "services" / "rag-pedago" / "configs" / "rights_evidence_registry.yml"
)
PROGRAMME_INDEX_PATH = REPOSITORY_ROOT / "corpus" / "College" / "Troisieme" / "_index.yml"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _required_external_path(name: str) -> Path:
    raw = os.environ.get(name, "").strip()
    if not raw:
        pytest.fail(f"{name} is required when NEXUS_WAVE0_CLI_E2E=1")
    path = Path(raw)
    if not path.is_file() and not path.is_dir():
        pytest.fail(f"{name} does not exist: {path}")
    return path


if os.environ.get("NEXUS_WAVE0_CLI_E2E") != "1":
    pytest.skip("Wave 0 subprocess CLI acceptance not requested", allow_module_level=True)

CATALOG_PATH = _required_external_path("NEXUS_WAVE0_CATALOG_PATH")
PII_PATH = _required_external_path("NEXUS_WAVE0_PII_EVIDENCE_PATH")
EMBEDDING_ROOT = _required_external_path("RAG_EMBEDDING_MODEL_CACHE_DIR")


@pytest.fixture(scope="module")
def control_pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("wave0-cli-e2e")


@pytest.fixture(scope="module")
def product_pg() -> Iterator[dict[str, str]]:
    """Produit pgvector réel avec un rôle publisher au moindre privilège."""
    port = free_port()
    container = f"nexus-wave0-cli-product-{uuid.uuid4().hex[:10]}"
    publisher_user = "wave0_cli_publisher"
    publisher_password = secrets.token_urlsafe(32)
    retrieval_password = secrets.token_urlsafe(32)
    review_password = secrets.token_urlsafe(32)
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            container,
            "-e",
            f"POSTGRES_USER={PG_SUPERUSER}",
            "-e",
            f"POSTGRES_PASSWORD={PG_SUPERUSER_PASSWORD}",
            "-e",
            f"POSTGRES_DB={PG_DB}",
            "-p",
            f"{port}:5432",
            PG_IMAGE,
        ],
        check=True,
        capture_output=True,
    )
    try:
        _wait_pg_isready(port)
        admin_env = {
            "PATH": os.environ["PATH"],
            "PGHOST": "127.0.0.1",
            "PGPORT": str(port),
            "PGUSER": PG_SUPERUSER,
            "PGPASSWORD": PG_SUPERUSER_PASSWORD,
            "PGDATABASE": PG_DB,
        }
        migrations = ENGINE_ROOT / "infra" / "postgres" / "migrations"
        migration_names = (
            "001_rag_chunks_v2_schema.sql",
            "002_hybrid_retrieval.sql",
            "003_profile_filtering.sql",
            "004_artifact_placements.sql",
        )
        for name in migration_names:
            result = subprocess.run(
                ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(migrations / name)],
                env=admin_env,
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, result.stderr
        admin_dsn = (
            f"host=127.0.0.1 port={port} dbname={PG_DB} "
            f"user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
        )
        with psycopg.connect(admin_dsn) as conn:
            conn.execute(
                "CREATE TABLE public.rag_schema_migrations ("
                "version integer PRIMARY KEY CHECK (version > 0), "
                "file_name text NOT NULL UNIQUE CHECK (btrim(file_name) <> ''), "
                "sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'), "
                "applied_at timestamptz NOT NULL DEFAULT now())"
            )
            for version, name in enumerate(migration_names, start=1):
                conn.execute(
                    "INSERT INTO public.rag_schema_migrations "
                    "(version, file_name, sha256) VALUES (%s, %s, %s)",
                    (version, name, _sha(migrations / name)),
                )
        provision_env = {
            **admin_env,
            "POSTGRES_USER": PG_SUPERUSER,
            "POSTGRES_DB": PG_DB,
            "PGVECTOR_RETRIEVAL_USER": "wave0_cli_retrieval",
            "PGVECTOR_RETRIEVAL_PASSWORD": retrieval_password,
            "PGVECTOR_REVIEW_USER": "wave0_cli_review",
            "PGVECTOR_REVIEW_PASSWORD": review_password,
            "PGVECTOR_PUBLISHER_USER": publisher_user,
            "PGVECTOR_PUBLISHER_PASSWORD": publisher_password,
        }
        provision = subprocess.run(
            [str(ENGINE_ROOT / "infra" / "postgres" / "provision_runtime_roles.sh")],
            env=provision_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert provision.returncode == 0, provision.stderr
        yield {
            "admin_dsn": admin_dsn,
            "publisher_dsn": (
                f"host=127.0.0.1 port={port} dbname={PG_DB} "
                f"user={publisher_user} password={publisher_password}"
            ),
        }
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)


def _readiness_environment(tmp_path: Path) -> dict[str, str]:
    seed = secrets.token_hex(32)
    key_id = f"wave0-cli-{uuid.uuid4().hex}"
    merge_sha = "c" * 40
    manifest = ProductionReadinessManifestV1(
        protocol_version=PRODUCTION_READINESS_PROTOCOL_VERSION,
        repository=REPOSITORY,
        pr_number=95,
        pr_head_sha="d" * 40,
        pr_head_tree_sha="e" * 40,
        merge_sha=merge_sha,
        merge_tree_sha="e" * 40,
        release_tag=f"release/rag/20260812-{merge_sha[:12]}",
        environment="production",
        review_binding_digest="1" * 64,
        authorization_digest="2" * 64,
        trust_anchor_digest="3" * 64,
        revocation_registry_digest="4" * 64,
        catalog_digest=CATALOG_SHA,
        sealed_manifest_digest=CORPUS_MANIFEST_SHA,
        h2b_report_digest="5" * 64,
        gate_result="pass",
        application_image_digests={
            "ingestion-worker": "ghcr.io/nexus/ingestion-worker@sha256:" + "6" * 64
        },
        upstream_image_digests={"pgvector": "pgvector/pgvector@sha256:" + "7" * 64},
        compose_digest="8" * 64,
        workflow_path=".github/workflows/promote-rag-production.yml",
        workflow_ref="refs/heads/main",
        run_id=9592001,
        run_attempt=1,
        issued_at=datetime(2026, 8, 12, 16, 0, tzinfo=UTC),
        key_id=key_id,
    )
    manifest_path = tmp_path / "readiness.json"
    manifest_path.write_bytes(
        sign_production_readiness_manifest(
            manifest, private_key_hex=seed, key_id=key_id
        ).canonical_bytes()
    )
    manifest_path.chmod(0o444)
    anchor_path = tmp_path / "readiness-anchor.json"
    anchor_path.write_text(
        json.dumps(
            {
                "protocol_version": PRODUCTION_READINESS_PROTOCOL_VERSION,
                "keys": [
                    {
                        "key_id": key_id,
                        "algorithm": "ed25519",
                        "public_key": public_readiness_key_hex(seed),
                        "environment": "production",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return {
        "NEXUS_ENVIRONMENT": "rehearsal",
        "NEXUS_READINESS_MANIFEST_PATH": str(manifest_path),
        "NEXUS_READINESS_REHEARSAL_TRUST_ANCHOR": str(anchor_path),
        "NEXUS_RELEASE_SHA": merge_sha,
    }


def _runtime_authority_args() -> list[str]:
    return [
        "--pii-evidence-path",
        str(PII_PATH),
        "--pii-evidence-sha256",
        PII_SHA,
        "--rights-evidence-path",
        str(RIGHTS_PATH),
        "--rights-evidence-sha256",
        RIGHTS_SHA,
        "--corpus-manifest-sha256",
        CORPUS_MANIFEST_SHA,
        "--catalog-path",
        str(CATALOG_PATH),
        "--catalog-sha256",
        CATALOG_SHA,
        "--candidate-inventory-path",
        str(INVENTORY_PATH),
        "--candidate-inventory-sha256",
        INVENTORY_SHA,
        "--currentness-evidence-path",
        str(CURRENTNESS_PATH),
        "--currentness-evidence-sha256",
        CURRENTNESS_SHA,
        "--mapping-path",
        str(MAPPING_PATH),
        "--mapping-sha256",
        MAPPING_SHA,
        "--release-manifest-path",
        str(RELEASE_PATH),
        "--release-manifest-sha256",
        RELEASE_SHA,
        "--programme-index-path",
        str(PROGRAMME_INDEX_PATH),
        "--programme-index-sha256",
        PROGRAMME_INDEX_SHA,
        "--collection-config-path",
        str(COLLECTION_CONFIG),
        "--collection-config-sha256",
        _sha(COLLECTION_CONFIG),
    ]


def _run_module(
    module: str,
    args: Sequence[str],
    *,
    env: Mapping[str, str],
    timeout: float = 180.0,
) -> subprocess.CompletedProcess[str]:
    complete_env = os.environ.copy()
    complete_env.update(env)
    complete_env["PYTHONPATH"] = str(ENGINE_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=ENGINE_ROOT,
        env=complete_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _authorization(profile: Any, manifest_digest: str) -> ScopeAuthorizationArtifactV2:
    return ScopeAuthorizationArtifactV2.model_validate(
        {
            "protocol_version": "LOT41A-V2",
            "authorization_id": AUTHORIZATION_ID,
            "decision": "AUTHORIZE_INGESTION_SCOPE",
            "scope": profile.scope.model_dump(mode="json"),
            "manifest_digest": manifest_digest,
            "profile_id": COLLECTION,
            "profile_version": PROFILE_VERSION,
            "profile_fingerprint": profile_fingerprint(profile),
            "allowed_domains": ["eduscol.education.gouv.fr"],
            "rights_categories": [Rights.officiel_public.value],
            "exclusions": [],
            "allowed_content_sha256": [MATHS_SHA],
            "pii_absence_attested": True,
            "pii_absence_evidence": f"Wave0 PII evidence sha256={PII_SHA}; status=CLEARED",
            "valid_from": "2026-08-11T00:00:00Z",
            "valid_until": "2027-08-12T00:00:00Z",
        }
    )


def _create_run(conn: psycopg.Connection[Any], profile: Any) -> uuid.UUID:
    scope = profile.scope.model_dump(mode="json")
    row = conn.execute(
        """
        INSERT INTO ingestion_control.ingestion_runs
            (tenant, collection, niveau, voie, matiere, candidat, audience,
             visibility, school_year, programme_version, profile_version,
             trigger, status)
        VALUES (%(tenant)s, %(collection)s, %(niveau)s, %(voie)s, %(matiere)s,
                %(candidat)s, %(audience)s, %(visibility)s, %(school_year)s,
                %(programme_version)s, %(profile_version)s, 'manual', 'planned')
        RETURNING run_id
        """,
        {**scope, "audience": sorted(scope["audience"]), "profile_version": PROFILE_VERSION},
    ).fetchone()
    assert row is not None
    run_id = row[0]
    assert isinstance(run_id, uuid.UUID)
    conn.commit()
    return run_id


def _parse_review_proposal(output: str) -> tuple[str, bytes]:
    lines = output.splitlines(keepends=True)
    position = next(
        index for index, line in enumerate(lines) if line.startswith("REVIEW_ARTIFACT_PATH ")
    )
    path = lines[position].split(" ", 1)[1].strip()
    assert lines[position + 1].startswith("REVIEW_ARTIFACT_DIGEST ")
    return path, "".join(lines[position + 2 :]).encode("utf-8")


def test_worker_a_and_worker_b_cli_once_real_wave0(
    control_pg: dict[str, str],
    product_pg: dict[str, str],
    tmp_path: Path,
) -> None:
    assert _sha(CATALOG_PATH) == CATALOG_SHA
    assert _sha(PII_PATH) == PII_SHA
    assert _sha(EMBEDDING_ROOT / "SHA256SUMS") == EMBEDDING_INVENTORY_SHA
    profiles = load_profile_registry(PROFILES_DIR)
    manifest = verify_profile_manifest(profiles, PROFILE_MANIFEST)
    profile = profiles[(COLLECTION, PROFILE_VERSION)]
    artifact_store = tmp_path / "artifacts"
    artifact_store.mkdir()
    token_file = tmp_path / "github-token"
    token_file.write_text(VALID_TOKEN, encoding="utf-8")
    github = LocalGitHub()
    github.add_approved_pr(number=AUTH_PR, head_sha=AUTH_HEAD, base_sha=BASE_HEAD, review_id=95911)
    github.add_approved_pr(
        number=PUB_PR,
        head_sha=PUB_HEAD,
        base_sha=BASE_HEAD,
        review_id=95921,
        submitted_at="2026-08-12T16:30:00Z",
    )
    github.put_blob(
        path=canonical_authorization_path(AUTHORIZATION_ID),
        ref=AUTH_HEAD,
        content=_authorization(profile, manifest.manifest_fingerprint).canonical_bytes(),
    )

    with local_github_server(github) as github_url:
        readiness_env = _readiness_environment(tmp_path)
        common_env = {
            **readiness_env,
            "NEXUS_GITHUB_API_BASE": github_url,
            "NEXUS_GITHUB_TOKEN_FILE": str(token_file),
            "PG_INGESTION_CONTROL_DSN": app_dsn(control_pg),
            "PG_INGESTION_CONTROL_AUTHORITY_DSN": authority_dsn(control_pg),
            "PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            # L'acceptance est explicitement CPU : elle doit rester
            # reproductible sur les runners sans mémoire GPU suffisante.
            "CUDA_VISIBLE_DEVICES": "",
        }
        authorization_result = _run_module(
            "ingestor.ingestion_worker.authorize_scope_cli",
            [
                "record-authorization",
                "--authorization-id",
                AUTHORIZATION_ID,
                "--repository",
                REPOSITORY,
                "--pull-request",
                str(AUTH_PR),
                "--expected-head",
                AUTH_HEAD,
            ],
            env=common_env,
        )
        assert authorization_result.returncode == 0, authorization_result.stderr

        with psycopg.connect(app_dsn(control_pg)) as conn:
            run_id = _create_run(conn, profile)
            create_job(
                conn,
                run_id=run_id,
                job_type="resource_pipeline",
                payload={
                    "scope": profile.scope.model_dump(mode="json"),
                    "dedup_key": hashlib.sha256(CANONICAL_URL.encode()).hexdigest(),
                    "source_url": SOURCE_URL,
                    "canonical_url": CANONICAL_URL,
                    "source_path": SOURCE_PATH,
                    "domain": "eduscol.education.gouv.fr",
                    "proposed_type_doc": "ressource_officielle",
                    "profile_version": PROFILE_VERSION,
                    "scope_authorization_id": AUTHORIZATION_ID,
                },
            )
            conn.commit()

        worker_a = _run_module(
            "ingestor.ingestion_worker.cli",
            [
                "--profiles-dir",
                str(PROFILES_DIR),
                "--manifest-path",
                str(PROFILE_MANIFEST),
                "--artifact-store-dir",
                str(artifact_store),
                "--owner",
                "wave0-cli-worker-a",
                "--expected-role",
                "ingestion_control_app",
                "--once",
                *_runtime_authority_args(),
            ],
            env=common_env,
        )
        assert worker_a.returncode == 0, worker_a.stderr
        assert "WORKER_ATTESTATION_OK current_user=ingestion_control_app" in worker_a.stdout
        assert "status=succeeded" in worker_a.stdout

        with psycopg.connect(superuser_dsn(control_pg)) as conn:
            resource_row = conn.execute(
                "SELECT resource_id, resource_state, state_version FROM "
                "ingestion_control.resources WHERE collection = %s",
                (COLLECTION,),
            ).fetchone()
            assert resource_row is not None
            resource_id, state, state_version = resource_row
            assert state == "NEEDS_REVIEW"
            artifact_row = conn.execute(
                "SELECT artifact_id FROM ingestion_control.artifacts "
                "WHERE resource_id = %s AND sha256 = %s",
                (resource_id, MATHS_SHA),
            ).fetchone()
            assert artifact_row is not None
            artifact_id = artifact_row[0]

        proposal = _run_module(
            "ingestor.ingestion_worker.attest_publication_cli",
            [
                "propose-review",
                "--resource-id",
                str(resource_id),
                "--artifact-id",
                str(artifact_id),
                "--scope-authorization-id",
                AUTHORIZATION_ID,
                "--review-id",
                REVIEW_ID,
            ],
            env=common_env,
        )
        assert proposal.returncode == 0, proposal.stderr
        proposal_path, proposal_bytes = _parse_review_proposal(proposal.stdout)
        github.put_blob(path=proposal_path, ref=PUB_HEAD, content=proposal_bytes)
        attestation = _run_module(
            "ingestor.ingestion_worker.attest_publication_cli",
            [
                "record-attestation",
                "--resource-id",
                str(resource_id),
                "--artifact-id",
                str(artifact_id),
                "--scope-authorization-id",
                AUTHORIZATION_ID,
                "--review-id",
                REVIEW_ID,
                "--repository",
                REPOSITORY,
                "--pull-request",
                str(PUB_PR),
                "--expected-head",
                PUB_HEAD,
            ],
            env=common_env,
        )
        assert attestation.returncode == 0, attestation.stderr

        with psycopg.connect(app_dsn(control_pg)) as conn:
            attestation_row = conn.execute(
                "SELECT attestation_id FROM ingestion_control.publication_attestations "
                "WHERE resource_id = %s AND invalidated_at IS NULL",
                (resource_id,),
            ).fetchone()
            assert attestation_row is not None
            publication_job_id = create_job(
                conn,
                run_id=run_id,
                resource_id=resource_id,
                job_type="publication_resume",
                payload={
                    "resource_id": str(resource_id),
                    "run_id": str(run_id),
                    "expected_state_version": state_version,
                    "publication_attestation_id": str(attestation_row[0]),
                },
            )
            conn.commit()

        worker_b = _run_module(
            "ingestor.ingestion_worker.publication_resume_cli",
            [
                "--profiles-dir",
                str(PROFILES_DIR),
                "--manifest-path",
                str(PROFILE_MANIFEST),
                "--artifact-store-dir",
                str(artifact_store),
                "--owner",
                "wave0-cli-worker-b",
                "--expected-role",
                "ingestion_control_app",
                "--embedding-artifact-root",
                str(EMBEDDING_ROOT),
                "--embedding-inventory-sha256",
                EMBEDDING_INVENTORY_SHA,
                "--once",
                *_runtime_authority_args(),
            ],
            env={**common_env, "PG_RAG_DSN": product_pg["publisher_dsn"]},
            timeout=900.0,
        )
        assert worker_b.returncode == 0, worker_b.stderr
        assert "PUBLICATION_WORKER_ATTESTATION_OK" in worker_b.stdout
        assert f"job_id={publication_job_id}" in worker_b.stdout
        assert "status=succeeded" in worker_b.stdout

    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        assert conn.execute(
            "SELECT resource_state FROM ingestion_control.resources WHERE resource_id = %s",
            (resource_id,),
        ).fetchone() == ("RETRIEVAL_ELIGIBLE",)
    with psycopg.connect(product_pg["admin_dsn"]) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM public.rag_artifacts WHERE artifact_id = %s", (MATHS_SHA,)
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT COUNT(*) FROM public.rag_artifact_placements WHERE artifact_id = %s",
            (MATHS_SHA,),
        ).fetchone() == (1,)
        chunk_row = conn.execute(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE model <> %s), "
            "COUNT(*) FILTER (WHERE vector IS NULL OR vector_dims(vector) <> 1024) "
            "FROM public.rag_chunks WHERE artifact_id = %s",
            ("intfloat/multilingual-e5-large", MATHS_SHA),
        ).fetchone()
        assert chunk_row is not None
        assert chunk_row[0] > 1
        assert chunk_row[1:] == (0, 0)
    assert github.non_get_requests == []
