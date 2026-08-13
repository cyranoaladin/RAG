"""Deux collections réelles à travers les entrypoints Worker A/B multi-niveaux."""

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
from urllib.parse import urlparse

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
from ingestor.ingestion_profiles.registry import (  # noqa: E402
    load_profile_registry,
    profile_fingerprint,
)
from ingestor.release_readiness import load_release_expectation  # noqa: E402

pytestmark = [pytest.mark.integration, requires_docker]

RELEASE_SHA = "d8ee6703d3497e34e6e5273bee00da90ab9c82094f0f9a1257eef0ff91da1828"
INVENTORY_SHA = "86531933e0779a739f20c347d32dd02e54672f058024d16e1198809cef965300"
CURRENTNESS_SHA = "2ad7209f28cd7cbf9f1ea91724b687983579c36c91619e8d107d28b72b849122"
PII_SHA = "46d6c738ebc230dedb95ada2d07bd17a0907d75ee8aedcd556d27027ad50daa8"
RIGHTS_SHA = "e3c9a157f1f78171c0052750fa08b7726b99ea4dd348728f1b90db07f93ef1ff"
PROGRAMME_SHA = "9822f795f7c293618305a7ed9ad9087f68a96267415472fc0c3e39d3c89aa58c"
PROFILE_MANIFEST_SHA = "47c86091687fc7a4a7e6d76aa8ff65eb02f3ab861dd15c7600dc93e6eb98b753"
LEVELS_SHA = "8ad9e7a6d62e26e5c233f8a3c62fba7a1df72da29f690a3c17d5e7660e740e1e"
SUBJECTS_SHA = "c3c2d20bd27243a77795b3a056441d256f0b0b9b73306b3a1e710eee61407ed6"
DOCUMENT_TYPES_SHA = "ce5e51b7c6890120bec1e7394d2f649ce0b4a2590ea8765d964a5576b99f871f"
CORPUS_SHA = "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
E5_SHA = "e2c7384ba36096b3f3bdfff4973f728596104aff0f1d38f1b6463e60765fe22a"
TARGET_COLLECTIONS = (
    "rag_nexus_maths_quatrieme_tc",
    "rag_nexus_nsi_premiere_specialite",
)

RELEASE_ROOT = REPOSITORY_ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027/multilevel"
RELEASE_PATH = RELEASE_ROOT / "multilevel.release.json"
INVENTORY_PATH = RELEASE_ROOT / "candidate_inventory.json"
CURRENTNESS_PATH = (
    REPOSITORY_ROOT
    / "services/rag-pedago/configs/prerentree_2026_2027/multilevel_currentness_evidence.yml"
)
PROFILES_DIR = ENGINE_ROOT / "configs/ingestion_profiles/staging/multilevel"
PROFILE_MANIFEST = ENGINE_ROOT / "configs/ingestion_profiles/staging/multilevel_manifest.json"
COLLECTION_CONFIG = ENGINE_ROOT / "configs/rag_collections.yml"
PROGRAMME_PATH = ENGINE_ROOT / "configs/programme_indexes/multilevel_2026_2027.yml"
LEVELS_PATH = ENGINE_ROOT / "configs/mappings/eduscol_multilevel_levels.yml"
SUBJECTS_PATH = ENGINE_ROOT / "configs/mappings/eduscol_multilevel_subjects.yml"
DOCUMENT_TYPES_PATH = ENGINE_ROOT / "configs/mappings/eduscol_multilevel_document_types.yml"
RIGHTS_PATH = REPOSITORY_ROOT / "services/rag-pedago/configs/rights_evidence_registry.yml"

if os.environ.get("NEXUS_MULTILEVEL_CLI_E2E") != "1":
    pytest.skip("multilevel subprocess CLI acceptance not requested", allow_module_level=True)

PII_PATH = Path(os.environ["NEXUS_MULTILEVEL_PII_EVIDENCE_PATH"])
E5_PATH = Path(os.environ["RAG_EMBEDDING_MODEL_CACHE_DIR"])


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def control_pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("multilevel-cli-e2e")


@pytest.fixture(scope="module")
def product_pg() -> Iterator[dict[str, str]]:
    port = free_port()
    container = f"nexus-multilevel-cli-product-{uuid.uuid4().hex[:10]}"
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
        migrations = ENGINE_ROOT / "infra/postgres/migrations"
        names = (
            "001_rag_chunks_v2_schema.sql",
            "002_hybrid_retrieval.sql",
            "003_profile_filtering.sql",
            "004_artifact_placements.sql",
        )
        for name in names:
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
                "file_name text NOT NULL UNIQUE, sha256 text NOT NULL, "
                "applied_at timestamptz NOT NULL DEFAULT now())"
            )
            for version, name in enumerate(names, start=1):
                conn.execute(
                    "INSERT INTO rag_schema_migrations (version,file_name,sha256) "
                    "VALUES (%s,%s,%s)",
                    (version, name, _sha(migrations / name)),
                )
        publisher_password = secrets.token_urlsafe(32)
        provision = subprocess.run(
            [str(ENGINE_ROOT / "infra/postgres/provision_runtime_roles.sh")],
            env={
                **admin_env,
                "POSTGRES_USER": PG_SUPERUSER,
                "POSTGRES_DB": PG_DB,
                "PGVECTOR_RETRIEVAL_USER": "multi_cli_retrieval",
                "PGVECTOR_RETRIEVAL_PASSWORD": secrets.token_urlsafe(32),
                "PGVECTOR_REVIEW_USER": "multi_cli_review",
                "PGVECTOR_REVIEW_PASSWORD": secrets.token_urlsafe(32),
                "PGVECTOR_PUBLISHER_USER": "multi_cli_publisher",
                "PGVECTOR_PUBLISHER_PASSWORD": publisher_password,
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert provision.returncode == 0, provision.stderr
        yield {
            "admin_dsn": admin_dsn,
            "publisher_dsn": (
                f"host=127.0.0.1 port={port} dbname={PG_DB} "
                f"user=multi_cli_publisher password={publisher_password}"
            ),
        }
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)


def _readiness_env(tmp_path: Path) -> dict[str, str]:
    seed = secrets.token_hex(32)
    key_id = f"multilevel-cli-{uuid.uuid4().hex}"
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
        catalog_digest="5" * 64,
        sealed_manifest_digest=CORPUS_SHA,
        h2b_report_digest="6" * 64,
        gate_result="pass",
        application_image_digests={"ingestion-worker": "ghcr.io/nexus/x@sha256:" + "7" * 64},
        upstream_image_digests={"pgvector": "pgvector/pgvector@sha256:" + "8" * 64},
        compose_digest="9" * 64,
        workflow_path=".github/workflows/promote-rag-production.yml",
        workflow_ref="refs/heads/main",
        run_id=99001,
        run_attempt=1,
        issued_at=datetime(2026, 8, 12, 20, 0, tzinfo=UTC),
        key_id=key_id,
    )
    manifest_path = tmp_path / "readiness.json"
    manifest_path.write_bytes(
        sign_production_readiness_manifest(
            manifest,
            private_key_hex=seed,
            key_id=key_id,
        ).canonical_bytes()
    )
    manifest_path.chmod(0o444)
    anchor_path = tmp_path / "anchor.json"
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
    anchor_path.chmod(0o444)
    return {
        "NEXUS_ENVIRONMENT": "rehearsal",
        "NEXUS_READINESS_MANIFEST_PATH": str(manifest_path),
        "NEXUS_READINESS_REHEARSAL_TRUST_ANCHOR": str(anchor_path),
        "NEXUS_RELEASE_SHA": merge_sha,
    }


def _authority_args() -> list[str]:
    return [
        "--candidate-inventory-path",
        str(INVENTORY_PATH),
        "--candidate-inventory-sha256",
        INVENTORY_SHA,
        "--currentness-evidence-path",
        str(CURRENTNESS_PATH),
        "--currentness-evidence-sha256",
        CURRENTNESS_SHA,
        "--levels-mapping-path",
        str(LEVELS_PATH),
        "--levels-mapping-sha256",
        LEVELS_SHA,
        "--subjects-mapping-path",
        str(SUBJECTS_PATH),
        "--subjects-mapping-sha256",
        SUBJECTS_SHA,
        "--document-types-mapping-path",
        str(DOCUMENT_TYPES_PATH),
        "--document-types-mapping-sha256",
        DOCUMENT_TYPES_SHA,
        "--release-manifest-path",
        str(RELEASE_PATH),
        "--release-manifest-sha256",
        RELEASE_SHA,
        "--programme-registry-path",
        str(PROGRAMME_PATH),
        "--programme-registry-sha256",
        PROGRAMME_SHA,
        "--profile-manifest-path",
        str(PROFILE_MANIFEST),
        "--profile-manifest-sha256",
        PROFILE_MANIFEST_SHA,
        "--collection-config-path",
        str(COLLECTION_CONFIG),
        "--collection-config-sha256",
        _sha(COLLECTION_CONFIG),
        "--pii-evidence-path",
        str(PII_PATH),
        "--pii-evidence-sha256",
        PII_SHA,
        "--rights-evidence-path",
        str(RIGHTS_PATH),
        "--rights-evidence-sha256",
        RIGHTS_SHA,
        "--corpus-manifest-sha256",
        CORPUS_SHA,
        "--repository-root",
        str(REPOSITORY_ROOT),
    ]


def _run(
    module: str, args: Sequence[str], env: Mapping[str, str], timeout: int = 300
) -> subprocess.CompletedProcess[str]:
    child_env = {**os.environ, **env, "PYTHONPATH": str(ENGINE_ROOT / "src")}
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=ENGINE_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _make_run(conn: psycopg.Connection[Any], profile: Any) -> uuid.UUID:
    scope = profile.scope.model_dump(mode="json")
    row = conn.execute(
        "INSERT INTO ingestion_control.ingestion_runs "
        "(tenant,collection,niveau,voie,matiere,candidat,audience,visibility,"
        "school_year,programme_version,profile_version,trigger,status) VALUES "
        "(%(tenant)s,%(collection)s,%(niveau)s,%(voie)s,%(matiere)s,%(candidat)s,"
        "%(audience)s,%(visibility)s,%(school_year)s,%(programme_version)s,"
        "%(profile_version)s,'manual','planned') RETURNING run_id",
        {
            **scope,
            "audience": sorted(scope["audience"]),
            "profile_version": profile.profile_version,
        },
    ).fetchone()
    assert row is not None
    return uuid.UUID(str(row[0]))


def _authorization(profile: Any, authorization_id: str, sha: str) -> ScopeAuthorizationArtifactV2:
    return ScopeAuthorizationArtifactV2.model_validate(
        {
            "protocol_version": "LOT41A-V2",
            "authorization_id": authorization_id,
            "decision": "AUTHORIZE_INGESTION_SCOPE",
            "scope": profile.scope.model_dump(mode="json"),
            "manifest_digest": PROFILE_MANIFEST_SHA,
            "profile_id": profile.scope.collection,
            "profile_version": profile.profile_version,
            "profile_fingerprint": profile_fingerprint(profile),
            "allowed_domains": sorted(profile.allowed_domains),
            "rights_categories": [Rights.officiel_public.value],
            "exclusions": [],
            "allowed_content_sha256": [sha],
            "pii_absence_attested": True,
            "pii_absence_evidence": f"multilevel PII sha256={PII_SHA}; CLEARED",
            "valid_from": "2026-08-12T00:00:00Z",
            "valid_until": "2027-08-12T00:00:00Z",
        }
    )


def _parse_proposal(stdout: str) -> tuple[str, bytes]:
    lines = stdout.splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines) if line.startswith("REVIEW_ARTIFACT_PATH "))
    return lines[index].split(" ", 1)[1].strip(), "".join(lines[index + 2 :]).encode()


def test_worker_a_and_b_cli_campaign_spans_two_collections(
    control_pg: dict[str, str],
    product_pg: dict[str, str],
    tmp_path: Path,
) -> None:
    assert _sha(RELEASE_PATH) == RELEASE_SHA
    assert _sha(PII_PATH) == PII_SHA
    assert _sha(E5_PATH / "SHA256SUMS") == E5_SHA
    profiles = load_profile_registry(PROFILES_DIR)
    expectation = load_release_expectation(RELEASE_PATH, RELEASE_SHA)
    selected = [
        next(item for item in expectation.artifacts if item.collection == collection)
        for collection in TARGET_COLLECTIONS
    ]
    github = LocalGitHub()
    token = tmp_path / "github-token"
    token.write_text(VALID_TOKEN, encoding="utf-8")
    artifact_store = tmp_path / "artifacts"
    artifact_store.mkdir()
    auth_by_collection: dict[str, str] = {}
    for index, artifact in enumerate(selected, start=1):
        auth_id = f"multilevel-cli-{index}-scope-v1"
        head = hashlib.sha1(f"auth:{artifact.collection}".encode()).hexdigest()
        github.add_approved_pr(
            number=9900 + index, head_sha=head, base_sha="9" * 40, review_id=9910 + index
        )
        github.put_blob(
            path=canonical_authorization_path(auth_id),
            ref=head,
            content=_authorization(
                profiles[(artifact.collection, "multilevel-v1")],
                auth_id,
                artifact.content_sha256,
            ).canonical_bytes(),
        )
        auth_by_collection[artifact.collection] = auth_id

    with local_github_server(github) as github_url:
        common_env = {
            **_readiness_env(tmp_path),
            "NEXUS_GITHUB_API_BASE": github_url,
            "NEXUS_GITHUB_TOKEN_FILE": str(token),
            "PG_INGESTION_CONTROL_DSN": app_dsn(control_pg),
            "PG_INGESTION_CONTROL_AUTHORITY_DSN": authority_dsn(control_pg),
            "PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "CUDA_VISIBLE_DEVICES": "",
        }
        for index, artifact in enumerate(selected, start=1):
            head = hashlib.sha1(f"auth:{artifact.collection}".encode()).hexdigest()
            result = _run(
                "ingestor.ingestion_worker.authorize_scope_cli",
                [
                    "record-authorization",
                    "--authorization-id",
                    auth_by_collection[artifact.collection],
                    "--repository",
                    REPOSITORY,
                    "--pull-request",
                    str(9900 + index),
                    "--expected-head",
                    head,
                ],
                common_env,
            )
            assert result.returncode == 0, result.stderr

        run_by_collection: dict[str, uuid.UUID] = {}
        with psycopg.connect(app_dsn(control_pg)) as conn:
            for artifact in selected:
                profile = profiles[(artifact.collection, "multilevel-v1")]
                run_id = _make_run(conn, profile)
                run_by_collection[artifact.collection] = run_id
                create_job(
                    conn,
                    run_id=run_id,
                    job_type="resource_pipeline",
                    payload={
                        "scope": profile.scope.model_dump(mode="json"),
                        "dedup_key": hashlib.sha256(artifact.source_url.encode()).hexdigest(),
                        "source_url": artifact.source_url,
                        "canonical_url": artifact.source_url,
                        "source_path": artifact.source_path,
                        "domain": urlparse(artifact.source_url).hostname,
                        "proposed_type_doc": artifact.type_doc,
                        "profile_version": profile.profile_version,
                        "scope_authorization_id": auth_by_collection[artifact.collection],
                    },
                )
            conn.commit()

        worker_a = _run(
            "ingestor.ingestion_worker.multilevel_cli",
            [
                "--profiles-dir",
                str(PROFILES_DIR),
                "--artifact-store-dir",
                str(artifact_store),
                "--owner",
                "multi-cli-a",
                "--expected-role",
                "ingestion_control_app",
                "--max-iterations",
                "2",
                *_authority_args(),
            ],
            common_env,
            timeout=600,
        )
        assert worker_a.returncode == 0, worker_a.stderr
        assert worker_a.stdout.count("status=succeeded") == 2, worker_a.stdout

        with psycopg.connect(superuser_dsn(control_pg)) as conn:
            rows = conn.execute(
                "SELECT r.resource_id,a.artifact_id,a.sha256,r.run_id,r.state_version,r.collection "
                "FROM ingestion_control.resources r JOIN ingestion_control.artifacts a USING(resource_id) "
                "WHERE r.collection = ANY(%s) ORDER BY r.collection",
                (list(TARGET_COLLECTIONS),),
            ).fetchall()
        assert {row[5] for row in rows} == set(TARGET_COLLECTIONS)
        assert all(row[4] > 0 for row in rows)

        publication_jobs: list[uuid.UUID] = []
        for index, row in enumerate(rows, start=1):
            resource_id, artifact_id, sha, run_id, state_version, collection = row
            review_id = f"multilevel-cli-{index}-publication-v1"
            head = hashlib.sha1(f"pub:{sha}".encode()).hexdigest()
            github.add_approved_pr(
                number=9950 + index,
                head_sha=head,
                base_sha="9" * 40,
                review_id=9960 + index,
                submitted_at="2026-08-12T20:30:00Z",
            )
            proposal = _run(
                "ingestor.ingestion_worker.attest_publication_cli",
                [
                    "propose-review",
                    "--resource-id",
                    str(resource_id),
                    "--artifact-id",
                    str(artifact_id),
                    "--scope-authorization-id",
                    auth_by_collection[collection],
                    "--review-id",
                    review_id,
                ],
                common_env,
            )
            assert proposal.returncode == 0, proposal.stderr
            proposal_path, proposal_bytes = _parse_proposal(proposal.stdout)
            github.put_blob(path=proposal_path, ref=head, content=proposal_bytes)
            recorded = _run(
                "ingestor.ingestion_worker.attest_publication_cli",
                [
                    "record-attestation",
                    "--resource-id",
                    str(resource_id),
                    "--artifact-id",
                    str(artifact_id),
                    "--scope-authorization-id",
                    auth_by_collection[collection],
                    "--review-id",
                    review_id,
                    "--repository",
                    REPOSITORY,
                    "--pull-request",
                    str(9950 + index),
                    "--expected-head",
                    head,
                ],
                common_env,
            )
            assert recorded.returncode == 0, recorded.stderr
            with psycopg.connect(app_dsn(control_pg)) as conn:
                attestation = conn.execute(
                    "SELECT attestation_id FROM ingestion_control.publication_attestations WHERE resource_id=%s AND invalidated_at IS NULL",
                    (resource_id,),
                ).fetchone()
                assert attestation is not None
                publication_jobs.append(
                    create_job(
                        conn,
                        run_id=run_id,
                        resource_id=resource_id,
                        job_type="publication_resume",
                        payload={
                            "resource_id": str(resource_id),
                            "run_id": str(run_id),
                            "expected_state_version": state_version,
                            "publication_attestation_id": str(attestation[0]),
                        },
                    )
                )
                conn.commit()

        worker_b = _run(
            "ingestor.ingestion_worker.multilevel_publication_resume_cli",
            [
                "--profiles-dir",
                str(PROFILES_DIR),
                "--artifact-store-dir",
                str(artifact_store),
                "--owner",
                "multi-cli-b",
                "--expected-role",
                "ingestion_control_app",
                "--embedding-artifact-root",
                str(E5_PATH),
                "--embedding-inventory-sha256",
                E5_SHA,
                "--max-iterations",
                "2",
                *_authority_args(),
            ],
            {**common_env, "PG_RAG_DSN": product_pg["publisher_dsn"]},
            timeout=1200,
        )
        assert worker_b.returncode == 0, worker_b.stderr
        assert worker_b.stdout.count("status=succeeded") == 2, worker_b.stdout

    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM ingestion_control.resources WHERE collection = ANY(%s) AND resource_state='RETRIEVAL_ELIGIBLE'",
            (list(TARGET_COLLECTIONS),),
        ).fetchone() == (2,)
    with psycopg.connect(product_pg["admin_dsn"]) as conn:
        assert conn.execute(
            "SELECT COUNT(DISTINCT collection) FROM rag_artifact_placements WHERE collection = ANY(%s)",
            (list(TARGET_COLLECTIONS),),
        ).fetchone() == (2,)
        assert conn.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE artifact_id = ANY(%s) AND (model <> %s OR vector IS NULL OR vector_dims(vector) <> 1024)",
            ([artifact.content_sha256 for artifact in selected], "intfloat/multilingual-e5-large"),
        ).fetchone() == (0,)
