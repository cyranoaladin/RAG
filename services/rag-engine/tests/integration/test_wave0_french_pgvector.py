"""Vertical slice Wave 0 réel : Français 3e jusqu'à pgvector staging.

Les octets et preuves restent hors Git. Le test est donc opt-in, mais il
exerce le runtime de production sur deux PostgreSQL jetables et les vraies
preuves scellées indiquées par variables d'environnement.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import subprocess
import sys
import time
import unicodedata
import uuid
from collections.abc import Iterator
from pathlib import Path
from statistics import median
from typing import Any

import httpx
import psycopg
import pytest
import yaml

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
from nexus_contracts import (  # noqa: E402
    InternalIdentityEnvelope,
    RetrievalResponse,
    RetrievalScopeArtifactV2,
    load_retrieval_scope_artifact,
)
from nexus_contracts.authority_artifacts import (  # noqa: E402
    ScopeAuthorizationArtifactV2,
    canonical_authorization_path,
)
from nexus_contracts.document import Rights  # noqa: E402
from nexus_contracts.resource_state import ResourceState  # noqa: E402

from ingestor.collection_config import load_collection_config  # noqa: E402
from ingestor.embedding_contract import CANONICAL_EMBED_MODEL  # noqa: E402
from ingestor.embedding_provider import (  # noqa: E402
    DEBUG_EMBED_MODEL,
    CallableEmbeddingProvider,
    VerifiedE5EmbeddingProvider,
)
from ingestor.ingestion_control.jobs import create_job  # noqa: E402
from ingestor.ingestion_control.provisioning import (  # noqa: E402
    get_resource_state,
)
from ingestor.ingestion_control.sealed_evidence import (  # noqa: E402
    VerifiedPIIEvidenceRegistry,
    VerifiedRightsEvidenceRegistry,
)
from ingestor.ingestion_profiles.manifest import verify_profile_manifest  # noqa: E402
from ingestor.ingestion_profiles.registry import (  # noqa: E402
    load_profile_registry,
    profile_fingerprint,
)
from ingestor.ingestion_worker.attest_publication_cli import main as attest_main  # noqa: E402
from ingestor.ingestion_worker.authorize_scope_cli import main as authorize_scope_main  # noqa: E402
from ingestor.ingestion_worker.publication_resume import (  # noqa: E402
    PublicationResumeDeps,
    run_publication_resume_iteration,
)
from ingestor.ingestion_worker.runner import WorkerDeps, run_worker_iteration  # noqa: E402
from ingestor.ingestion_worker.storage import (  # noqa: E402
    make_filesystem_artifact_reader,
    make_filesystem_artifact_store,
)
from ingestor.retrieval_hybrid_v2 import EMBED_DIMENSION  # noqa: E402
from ingestor.verified_pedagogical_placement import (  # noqa: E402
    VerifiedPedagogicalPlacementResolver,
)

pytestmark = [pytest.mark.integration, requires_docker]

FR_SHA = "c8662b03ca8a7f08bedad5081bafc7da8d2cc8a31b07fa967421fb15304d76bf"
CORPUS_MANIFEST_SHA = "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
CATALOG_SHA = "301c0dcce4e49cd9b6e524708bde82b262a09b05bd52e0431233813ecf8ae04b"
CURRENTNESS_SHA = "25d92eb97acc30467bd2dcfea401c94ea3ce273f341a574edb2bb48f4ab2aa13"
PROGRAMME_INDEX_SHA = "d5b2bbfe97d0a2e8b85f446c2d3f862798d03db4f8cf48a22cf22e1cb4da0f45"
PII_SHA = "e1049c9d4b39b57acce9becadf5029de5b82a20afd8e38c699835bf1e649e125"
RIGHTS_SHA = "e3c9a157f1f78171c0052750fa08b7726b99ea4dd348728f1b90db07f93ef1ff"
AUTHORIZATION_ID = "-".join(("wave0", "francais", "troisieme", "v1"))
AUTH_PR, AUTH_HEAD, BASE_HEAD, AUTH_REVIEW = 9501, "a" * 40, "9" * 40, 95011
PUB_PR, PUB_HEAD, PUB_REVIEW = 9502, "b" * 40, 95021
REVIEW_ID = "wave0-francais-troisieme-publication-v1"
PROFILE_VERSION = "wave0-v1"
COLLECTION = "rag_nexus_francais_troisieme_tc"
SOURCE_URL = "https://eduscol.education.gouv.fr/document/14062/download"
CANONICAL_URL = (
    "https://eduscol.education.gouv.fr/5733/"
    "ressources-d-accompagnement-du-programme-de-francais-au-cycle-4"
)
SOURCE_PATH = (
    "01_EDUSCOL_OFFICIEL/COLLEGE/3E/FRANCAIS/02_REPERES_ATTENDUS/2019/"
    "attendus-de-fin-d-annee-en-francais-en-3e-pdf-971-01-ko--c8662b03ca.pdf"
)
MATHS_SHA = "49ccdca4d97ba4cf25875dfc731474e84d0332985c15396d3abfb9107f5f545a"
MATHS_COLLECTION = "rag_nexus_maths_troisieme_tc"
MATHS_SOURCE_URL = (
    "https://eduscol.education.gouv.fr/sites/default/files/document/"
    "18-maths-3e-attendus-eduscol1114748pdf-74688.pdf"
)
MATHS_CANONICAL_URL = (
    "https://eduscol.education.gouv.fr/5736/"
    "ressources-d-accompagnement-du-programme-de-mathematiques-au-cycle-4"
)
MATHS_SOURCE_PATH = (
    "01_EDUSCOL_OFFICIEL/COLLEGE/3E/MATHEMATIQUES/02_REPERES_ATTENDUS/2019/"
    "attendus-de-fin-d-annee-en-mathematiques-en-3e-pdf-1-26-mo--49ccdca4d9.pdf"
)
MATHS_AUTHORIZATION_ID = "-".join(("wave0", "maths", "troisieme", "v1"))
MATHS_AUTH_PR, MATHS_AUTH_HEAD, MATHS_AUTH_REVIEW = 9511, "c" * 40, 95111
MATHS_PUB_PR, MATHS_PUB_HEAD, MATHS_PUB_REVIEW = 9512, "d" * 40, 95121
MATHS_REVIEW_ID = "wave0-maths-troisieme-publication-v1"
WAVE0_SEARCH_DATASET = ENGINE_ROOT / "tests" / "fixtures" / "wave0_search_acceptance.yml"
WAVE0_COLLECTIONS_CONFIG = ENGINE_ROOT / "configs" / "staging" / "rag_collections_wave0.yml"

PDF_PATH = Path(os.environ.get("NEXUS_WAVE0_FR_PDF_PATH", ""))
MATHS_PDF_PATH = Path(os.environ.get("NEXUS_WAVE0_MATHS_PDF_PATH", ""))
CATALOG_PATH = Path(os.environ.get("NEXUS_WAVE0_CATALOG_PATH", ""))
PII_PATH = Path(os.environ.get("NEXUS_WAVE0_PII_EVIDENCE_PATH", ""))
if not all(
    os.environ.get(name, "").strip()
    for name in (
        "NEXUS_WAVE0_FR_PDF_PATH",
        "NEXUS_WAVE0_MATHS_PDF_PATH",
        "NEXUS_WAVE0_CATALOG_PATH",
        "NEXUS_WAVE0_PII_EVIDENCE_PATH",
    )
):
    pytest.skip("Wave 0 real inputs not requested", allow_module_level=True)

PROFILES_DIR = ENGINE_ROOT / "configs" / "ingestion_profiles" / "staging"
PROFILE_MANIFEST = ENGINE_ROOT / "configs" / "ingestion_manifest_wave0_staging.yml"
CURRENTNESS_PATH = (
    REPOSITORY_ROOT
    / "services"
    / "rag-pedago"
    / "configs"
    / "prerentree_2026_2027"
    / "wave0_currentness_evidence.yml"
)
RIGHTS_PATH = (
    REPOSITORY_ROOT / "services" / "rag-pedago" / "configs" / "rights_evidence_registry.yml"
)
PROGRAMME_INDEX_PATH = REPOSITORY_ROOT / "corpus" / "College" / "Troisieme" / "_index.yml"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def control_pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("wave0-fr")


@pytest.fixture(scope="module")
def product_pg() -> Iterator[dict[str, str]]:
    """PostgreSQL+pgvector produit jetable, distinct du plan de contrôle."""
    port = free_port()
    container = f"nexus-wave0-fr-product-{uuid.uuid4().hex[:10]}"
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
        for name in (
            "001_rag_chunks_v2_schema.sql",
            "002_hybrid_retrieval.sql",
            "003_profile_filtering.sql",
            "004_artifact_placements.sql",
        ):
            result = subprocess.run(
                ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(migrations / name)],
                env=admin_env,
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, f"{name}: {result.stderr}"
        registry_sql = (
            "CREATE TABLE public.rag_schema_migrations ("
            "version integer PRIMARY KEY CHECK (version > 0), "
            "file_name text NOT NULL UNIQUE CHECK (btrim(file_name) <> ''), "
            "sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'), "
            "applied_at timestamptz NOT NULL DEFAULT now())"
        )
        with psycopg.connect(
            f"host=127.0.0.1 port={port} dbname={PG_DB} "
            f"user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
        ) as registry_conn:
            registry_conn.execute(registry_sql)
            for version, name in enumerate(
                (
                    "001_rag_chunks_v2_schema.sql",
                    "002_hybrid_retrieval.sql",
                    "003_profile_filtering.sql",
                    "004_artifact_placements.sql",
                ),
                start=1,
            ):
                registry_conn.execute(
                    "INSERT INTO public.rag_schema_migrations "
                    "(version, file_name, sha256) VALUES (%s, %s, %s)",
                    (version, name, _sha(migrations / name)),
                )
        publisher_password = "wave0_publisher_password_2026_08_12"
        provision_env = {
            **admin_env,
            "POSTGRES_USER": PG_SUPERUSER,
            "POSTGRES_DB": PG_DB,
            "PGVECTOR_RETRIEVAL_USER": "wave0_retrieval",
            "PGVECTOR_RETRIEVAL_PASSWORD": "wave0_retrieval_password_2026_08_12",
            "PGVECTOR_REVIEW_USER": "wave0_review",
            "PGVECTOR_REVIEW_PASSWORD": "wave0_review_password_2026_08_12___",
            "PGVECTOR_PUBLISHER_USER": "wave0_publisher",
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
            "host": "127.0.0.1",
            "port": str(port),
            "dbname": PG_DB,
            "admin_dsn": (
                f"host=127.0.0.1 port={port} dbname={PG_DB} "
                f"user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
            ),
            "publisher_dsn": (
                f"host=127.0.0.1 port={port} dbname={PG_DB} "
                f"user=wave0_publisher password={publisher_password}"
            ),
            "retrieval_dsn": (
                f"host=127.0.0.1 port={port} dbname={PG_DB} "
                "user=wave0_retrieval "
                "password=wave0_retrieval_password_2026_08_12"
            ),
            "review_dsn": (
                f"host=127.0.0.1 port={port} dbname={PG_DB} "
                "user=wave0_review "
                "password=wave0_review_password_2026_08_12___"
            ),
        }
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)


@pytest.fixture(scope="module")
def real_inputs() -> dict[str, Any]:
    assert _sha(PDF_PATH) == FR_SHA
    assert _sha(MATHS_PDF_PATH) == MATHS_SHA
    assert _sha(CATALOG_PATH) == CATALOG_SHA
    assert _sha(CURRENTNESS_PATH) == CURRENTNESS_SHA
    assert _sha(PII_PATH) == PII_SHA
    assert _sha(RIGHTS_PATH) == RIGHTS_SHA

    profiles = load_profile_registry(PROFILES_DIR)
    manifest = verify_profile_manifest(profiles, PROFILE_MANIFEST)
    resolver = VerifiedPedagogicalPlacementResolver.load(
        catalog_path=CATALOG_PATH,
        expected_catalog_sha256=CATALOG_SHA,
        currentness_evidence_path=CURRENTNESS_PATH,
        expected_currentness_evidence_sha256=CURRENTNESS_SHA,
        expected_manifest_sha256=CORPUS_MANIFEST_SHA,
        profile_registry=profiles,
        collection_config=load_collection_config(),
        programme_index_path=PROGRAMME_INDEX_PATH,
        expected_programme_index_sha256=PROGRAMME_INDEX_SHA,
    )
    pii = VerifiedPIIEvidenceRegistry.load(
        PII_PATH,
        expected_evidence_sha256=PII_SHA,
        expected_corpus_manifest_sha256=CORPUS_MANIFEST_SHA,
    )
    rights = VerifiedRightsEvidenceRegistry.load(
        RIGHTS_PATH,
        expected_registry_sha256=RIGHTS_SHA,
        expected_corpus_manifest_sha256=CORPUS_MANIFEST_SHA,
    )
    return {
        "raw": {FR_SHA: PDF_PATH.read_bytes(), MATHS_SHA: MATHS_PDF_PATH.read_bytes()},
        "profiles": profiles,
        "resolver": resolver,
        "pii": pii,
        "rights": rights,
        "manifest_digest": manifest.manifest_fingerprint,
    }


@pytest.fixture
def github(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    real_inputs: dict[str, Any],
) -> Iterator[LocalGitHub]:
    profile = real_inputs["profiles"][(COLLECTION, PROFILE_VERSION)]
    manifest_digest = real_inputs["manifest_digest"]
    state = LocalGitHub()
    state.add_approved_pr(
        number=AUTH_PR,
        head_sha=AUTH_HEAD,
        base_sha=BASE_HEAD,
        review_id=AUTH_REVIEW,
    )
    state.add_approved_pr(
        number=PUB_PR,
        head_sha=PUB_HEAD,
        base_sha=BASE_HEAD,
        review_id=PUB_REVIEW,
        submitted_at="2026-08-12T10:30:00Z",
    )
    state.put_blob(
        path=canonical_authorization_path(AUTHORIZATION_ID),
        ref=AUTH_HEAD,
        content=_authorization_document(
            profile, manifest_digest, AUTHORIZATION_ID, COLLECTION, FR_SHA
        ).canonical_bytes(),
    )
    token_file = tmp_path / "github-token"
    token_file.write_text(VALID_TOKEN, encoding="utf-8")
    with local_github_server(state) as base_url:
        monkeypatch.setenv("NEXUS_GITHUB_API_BASE", base_url)
        monkeypatch.setenv("NEXUS_GITHUB_TOKEN_FILE", str(token_file))
        monkeypatch.delenv("NEXUS_GITHUB_TOKEN", raising=False)
        yield state


@pytest.fixture
def maths_github(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    real_inputs: dict[str, Any],
) -> Iterator[LocalGitHub]:
    profile = real_inputs["profiles"][(MATHS_COLLECTION, PROFILE_VERSION)]
    manifest_digest = real_inputs["manifest_digest"]
    state = LocalGitHub()
    state.add_approved_pr(
        number=MATHS_AUTH_PR,
        head_sha=MATHS_AUTH_HEAD,
        base_sha=BASE_HEAD,
        review_id=MATHS_AUTH_REVIEW,
    )
    state.add_approved_pr(
        number=MATHS_PUB_PR,
        head_sha=MATHS_PUB_HEAD,
        base_sha=BASE_HEAD,
        review_id=MATHS_PUB_REVIEW,
        submitted_at="2026-08-12T10:35:00Z",
    )
    state.put_blob(
        path=canonical_authorization_path(MATHS_AUTHORIZATION_ID),
        ref=MATHS_AUTH_HEAD,
        content=_authorization_document(
            profile,
            manifest_digest,
            MATHS_AUTHORIZATION_ID,
            MATHS_COLLECTION,
            MATHS_SHA,
        ).canonical_bytes(),
    )
    token_file = tmp_path / "maths-github-token"
    token_file.write_text(VALID_TOKEN, encoding="utf-8")
    with local_github_server(state) as base_url:
        monkeypatch.setenv("NEXUS_GITHUB_API_BASE", base_url)
        monkeypatch.setenv("NEXUS_GITHUB_TOKEN_FILE", str(token_file))
        monkeypatch.delenv("NEXUS_GITHUB_TOKEN", raising=False)
        yield state


@pytest.fixture
def operator_env(control_pg: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_INGESTION_CONTROL_AUTHORITY_DSN", authority_dsn(control_pg))
    monkeypatch.setenv("PG_INGESTION_CONTROL_ATTESTOR_DSN", attestor_dsn(control_pg))
    monkeypatch.delenv("PG_INGESTION_CONTROL_DSN", raising=False)


def _authorization_document(
    profile: Any,
    manifest_digest: str,
    authorization_id: str,
    collection: str,
    content_sha256: str,
) -> ScopeAuthorizationArtifactV2:
    return ScopeAuthorizationArtifactV2.model_validate(
        {
            "protocol_version": "LOT41A-V2",
            "authorization_id": authorization_id,
            "decision": "AUTHORIZE_INGESTION_SCOPE",
            "scope": profile.scope.model_dump(mode="json"),
            "manifest_digest": manifest_digest,
            "profile_id": collection,
            "profile_version": PROFILE_VERSION,
            "profile_fingerprint": profile_fingerprint(profile),
            "allowed_domains": ["eduscol.education.gouv.fr"],
            "rights_categories": [Rights.officiel_public.value],
            "exclusions": [],
            "allowed_content_sha256": [content_sha256],
            "pii_absence_attested": True,
            "pii_absence_evidence": f"Wave0 PII evidence sha256={PII_SHA}; status=CLEARED",
            "valid_from": "2026-08-11T00:00:00Z",
            "valid_until": "2027-08-12T00:00:00Z",
        }
    )


def _make_run(conn: psycopg.Connection[Any], profile: Any) -> uuid.UUID:
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
    conn.commit()
    return row[0]


@pytest.fixture(scope="module")
def french_needs_review(
    control_pg: dict[str, str],
    real_inputs: dict[str, Any],
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Any]:
    raw = real_inputs["raw"][FR_SHA]
    profile = real_inputs["profiles"][(COLLECTION, PROFILE_VERSION)]
    resolver = real_inputs["resolver"]
    pii = real_inputs["pii"]
    rights = real_inputs["rights"]
    manifest_digest = real_inputs["manifest_digest"]
    storage = tmp_path_factory.mktemp("wave0-fr-artifacts")

    def fetch(url: str, *, on_destination: Any = None, **_kwargs: Any) -> httpx.Response:
        if on_destination is not None:
            on_destination(url)
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=raw,
            request=httpx.Request("GET", url),
        )

    deps = WorkerDeps(
        owner="wave0-fr-worker-a",
        profile_registry={(COLLECTION, PROFILE_VERSION): profile},
        artifact_store=make_filesystem_artifact_store(storage),
        artifact_reader=make_filesystem_artifact_reader(storage),
        validate_destination=lambda url: url,
        safe_fetch=fetch,
        manifest_digest=manifest_digest,
        pii_evidence_registry=pii,
        rights_evidence_registry=rights,
        placement_resolver=resolver,
    )
    assert deps.verify_scope_authorization.__module__.endswith("scope_authority")
    authority = LocalGitHub()
    authority.add_approved_pr(
        number=AUTH_PR,
        head_sha=AUTH_HEAD,
        base_sha=BASE_HEAD,
        review_id=AUTH_REVIEW,
    )
    authority.put_blob(
        path=canonical_authorization_path(AUTHORIZATION_ID),
        ref=AUTH_HEAD,
        content=_authorization_document(
            profile, manifest_digest, AUTHORIZATION_ID, COLLECTION, FR_SHA
        ).canonical_bytes(),
    )
    token_file = storage / "github-token"
    token_file.write_text(VALID_TOKEN, encoding="utf-8")
    with local_github_server(authority) as base_url, pytest.MonkeyPatch.context() as patch:
        patch.setenv("NEXUS_GITHUB_API_BASE", base_url)
        patch.setenv("NEXUS_GITHUB_TOKEN_FILE", str(token_file))
        patch.delenv("NEXUS_GITHUB_TOKEN", raising=False)
        patch.setenv("PG_INGESTION_CONTROL_AUTHORITY_DSN", authority_dsn(control_pg))
        patch.setenv("PG_INGESTION_CONTROL_ATTESTOR_DSN", attestor_dsn(control_pg))
        patch.delenv("PG_INGESTION_CONTROL_DSN", raising=False)
        assert (
            authorize_scope_main(
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
                ]
            )
            == 0
        )
        with psycopg.connect(app_dsn(control_pg)) as conn:
            run_id = _make_run(conn, profile)
            job_id = create_job(
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
            outcome = run_worker_iteration(conn, deps=deps)
            assert outcome.status == "succeeded", outcome.error
            row = conn.execute(
                "SELECT resource_id, resource_state, state_version "
                "FROM ingestion_control.resources"
            ).fetchone()
            assert row is not None
            resource_id, state, state_version = row
            artifact_row = conn.execute(
                "SELECT artifact_id FROM ingestion_control.artifacts " "WHERE resource_id = %s",
                (resource_id,),
            ).fetchone()
            assert artifact_row is not None
            quality = conn.execute(
                "SELECT payload FROM ingestion_control.workflow_events "
                "WHERE resource_id = %s AND to_state = 'QUALITY_CHECKED'",
                (resource_id,),
            ).fetchone()
            classified = conn.execute(
                "SELECT payload FROM ingestion_control.workflow_events "
                "WHERE resource_id = %s AND to_state = 'CLASSIFIED'",
                (resource_id,),
            ).fetchone()
    assert authority.non_get_requests == []
    return {
        "resource_id": resource_id,
        "artifact_id": artifact_row[0],
        "run_id": run_id,
        "job_id": job_id,
        "state": state,
        "state_version": state_version,
        "quality": quality[0] if quality else None,
        "classified": classified[0] if classified else None,
        "artifact_reader": deps.artifact_reader,
        "resolver": resolver,
        "profile": profile,
        "manifest_digest": manifest_digest,
        "pii": pii,
        "rights": rights,
    }


def test_worker_a_routes_real_french_to_needs_review(
    control_pg: dict[str, str], french_needs_review: dict[str, Any]
) -> None:
    assert french_needs_review["state"] == ResourceState.NEEDS_REVIEW.value
    assert french_needs_review["quality"]["rejection_reasons"] == []
    classified = french_needs_review["classified"]
    assert classified["conformity_source"] == "sealed_pedagogical_placement"
    assert classified["content_sha256"] == FR_SHA
    assert classified["niveau_conformity"] is True
    assert classified["voie_conformity"] is True
    assert classified["matiere_conformity"] is True
    assert classified["programme_conformity"] is True
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM ingestion_control.workflow_events "
            "WHERE resource_id = %s AND to_state = 'NEEDS_REVIEW'",
            (french_needs_review["resource_id"],),
        ).fetchone() == (1,)


@pytest.fixture(scope="module")
def maths_needs_review(
    control_pg: dict[str, str],
    real_inputs: dict[str, Any],
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Any]:
    raw = real_inputs["raw"][MATHS_SHA]
    profile = real_inputs["profiles"][(MATHS_COLLECTION, PROFILE_VERSION)]
    resolver = real_inputs["resolver"]
    pii = real_inputs["pii"]
    rights = real_inputs["rights"]
    manifest_digest = real_inputs["manifest_digest"]
    storage = tmp_path_factory.mktemp("wave0-maths-artifacts")

    def fetch(url: str, *, on_destination: Any = None, **_kwargs: Any) -> httpx.Response:
        if on_destination is not None:
            on_destination(url)
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=raw,
            request=httpx.Request("GET", url),
        )

    deps = WorkerDeps(
        owner="wave0-maths-worker-a",
        profile_registry={(MATHS_COLLECTION, PROFILE_VERSION): profile},
        artifact_store=make_filesystem_artifact_store(storage),
        artifact_reader=make_filesystem_artifact_reader(storage),
        validate_destination=lambda url: url,
        safe_fetch=fetch,
        manifest_digest=manifest_digest,
        pii_evidence_registry=pii,
        rights_evidence_registry=rights,
        placement_resolver=resolver,
    )
    assert deps.verify_scope_authorization.__module__.endswith("scope_authority")
    authority = LocalGitHub()
    authority.add_approved_pr(
        number=MATHS_AUTH_PR,
        head_sha=MATHS_AUTH_HEAD,
        base_sha=BASE_HEAD,
        review_id=MATHS_AUTH_REVIEW,
    )
    authority.put_blob(
        path=canonical_authorization_path(MATHS_AUTHORIZATION_ID),
        ref=MATHS_AUTH_HEAD,
        content=_authorization_document(
            profile,
            manifest_digest,
            MATHS_AUTHORIZATION_ID,
            MATHS_COLLECTION,
            MATHS_SHA,
        ).canonical_bytes(),
    )
    token_file = storage / "github-token"
    token_file.write_text(VALID_TOKEN, encoding="utf-8")
    with local_github_server(authority) as base_url, pytest.MonkeyPatch.context() as patch:
        patch.setenv("NEXUS_GITHUB_API_BASE", base_url)
        patch.setenv("NEXUS_GITHUB_TOKEN_FILE", str(token_file))
        patch.delenv("NEXUS_GITHUB_TOKEN", raising=False)
        patch.setenv("PG_INGESTION_CONTROL_AUTHORITY_DSN", authority_dsn(control_pg))
        patch.setenv("PG_INGESTION_CONTROL_ATTESTOR_DSN", attestor_dsn(control_pg))
        patch.delenv("PG_INGESTION_CONTROL_DSN", raising=False)
        assert (
            authorize_scope_main(
                [
                    "record-authorization",
                    "--authorization-id",
                    MATHS_AUTHORIZATION_ID,
                    "--repository",
                    REPOSITORY,
                    "--pull-request",
                    str(MATHS_AUTH_PR),
                    "--expected-head",
                    MATHS_AUTH_HEAD,
                ]
            )
            == 0
        )
        with psycopg.connect(app_dsn(control_pg)) as conn:
            run_id = _make_run(conn, profile)
            job_id = create_job(
                conn,
                run_id=run_id,
                job_type="resource_pipeline",
                payload={
                    "scope": profile.scope.model_dump(mode="json"),
                    "dedup_key": hashlib.sha256(MATHS_CANONICAL_URL.encode()).hexdigest(),
                    "source_url": MATHS_SOURCE_URL,
                    "canonical_url": MATHS_CANONICAL_URL,
                    "source_path": MATHS_SOURCE_PATH,
                    "domain": "eduscol.education.gouv.fr",
                    "proposed_type_doc": "ressource_officielle",
                    "profile_version": PROFILE_VERSION,
                    "scope_authorization_id": MATHS_AUTHORIZATION_ID,
                },
            )
            conn.commit()
            outcome = run_worker_iteration(conn, deps=deps)
            assert outcome.status == "succeeded", outcome.error
            row = conn.execute(
                "SELECT resource_id, resource_state, state_version "
                "FROM ingestion_control.resources WHERE collection = %s",
                (MATHS_COLLECTION,),
            ).fetchone()
            assert row is not None
            resource_id, state, state_version = row
            artifact_row = conn.execute(
                "SELECT artifact_id FROM ingestion_control.artifacts " "WHERE resource_id = %s",
                (resource_id,),
            ).fetchone()
            assert artifact_row is not None
            quality = conn.execute(
                "SELECT payload FROM ingestion_control.workflow_events "
                "WHERE resource_id = %s AND to_state = 'QUALITY_CHECKED'",
                (resource_id,),
            ).fetchone()
            classified = conn.execute(
                "SELECT payload FROM ingestion_control.workflow_events "
                "WHERE resource_id = %s AND to_state = 'CLASSIFIED'",
                (resource_id,),
            ).fetchone()
    assert authority.non_get_requests == []
    return {
        "resource_id": resource_id,
        "artifact_id": artifact_row[0],
        "run_id": run_id,
        "job_id": job_id,
        "state": state,
        "state_version": state_version,
        "quality": quality[0] if quality else None,
        "classified": classified[0] if classified else None,
        "artifact_reader": deps.artifact_reader,
        "resolver": resolver,
        "profile": profile,
        "manifest_digest": manifest_digest,
        "pii": pii,
        "rights": rights,
    }


def test_worker_a_routes_real_maths_to_needs_review(
    control_pg: dict[str, str], maths_needs_review: dict[str, Any]
) -> None:
    assert maths_needs_review["state"] == ResourceState.NEEDS_REVIEW.value
    assert maths_needs_review["quality"]["rejection_reasons"] == []
    classified = maths_needs_review["classified"]
    assert classified["conformity_source"] == "sealed_pedagogical_placement"
    assert classified["content_sha256"] == MATHS_SHA
    assert classified["niveau_conformity"] is True
    assert classified["voie_conformity"] is True
    assert classified["matiere_conformity"] is True
    assert classified["programme_conformity"] is True
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM ingestion_control.workflow_events "
            "WHERE resource_id = %s AND to_state = 'NEEDS_REVIEW'",
            (maths_needs_review["resource_id"],),
        ).fetchone() == (1,)


def _parse_proposal(output: str) -> tuple[str, bytes]:
    lines = output.splitlines(keepends=True)
    index = next(
        position for position, line in enumerate(lines) if line.startswith("REVIEW_ARTIFACT_PATH ")
    )
    path = lines[index].split(" ", 1)[1].strip()
    assert lines[index + 1].startswith("REVIEW_ARTIFACT_DIGEST ")
    return path, "".join(lines[index + 2 :]).encode("utf-8")


@pytest.fixture
def french_attested(
    control_pg: dict[str, str],
    french_needs_review: dict[str, Any],
    github: LocalGitHub,
    operator_env: None,
    capsys: pytest.CaptureFixture[str],
) -> dict[str, Any]:
    del operator_env
    assert (
        attest_main(
            [
                "propose-review",
                "--resource-id",
                str(french_needs_review["resource_id"]),
                "--artifact-id",
                str(french_needs_review["artifact_id"]),
                "--scope-authorization-id",
                AUTHORIZATION_ID,
                "--review-id",
                REVIEW_ID,
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    proposal_path, proposal_bytes = _parse_proposal(captured.out)
    github.put_blob(path=proposal_path, ref=PUB_HEAD, content=proposal_bytes)
    assert (
        attest_main(
            [
                "record-attestation",
                "--resource-id",
                str(french_needs_review["resource_id"]),
                "--artifact-id",
                str(french_needs_review["artifact_id"]),
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
            ]
        )
        == 0
    )
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        rows = conn.execute(
            "SELECT attestation_id FROM ingestion_control.publication_attestations "
            "WHERE resource_id = %s AND review_id = %s AND invalidated_at IS NULL",
            (french_needs_review["resource_id"], REVIEW_ID),
        ).fetchall()
        assert len(rows) == 1
        state = get_resource_state(conn, resource_id=french_needs_review["resource_id"])
        assert state is not None
        assert state[0] == ResourceState.NEEDS_REVIEW.value
    return {
        **french_needs_review,
        "publication_attestation_id": rows[0][0],
        "expected_state_version": state[1],
        "proposal_path": proposal_path,
        "proposal_bytes": proposal_bytes,
    }


@pytest.fixture
def maths_attested(
    control_pg: dict[str, str],
    maths_needs_review: dict[str, Any],
    maths_github: LocalGitHub,
    operator_env: None,
    capsys: pytest.CaptureFixture[str],
) -> dict[str, Any]:
    del operator_env
    assert (
        attest_main(
            [
                "propose-review",
                "--resource-id",
                str(maths_needs_review["resource_id"]),
                "--artifact-id",
                str(maths_needs_review["artifact_id"]),
                "--scope-authorization-id",
                MATHS_AUTHORIZATION_ID,
                "--review-id",
                MATHS_REVIEW_ID,
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    proposal_path, proposal_bytes = _parse_proposal(captured.out)
    maths_github.put_blob(path=proposal_path, ref=MATHS_PUB_HEAD, content=proposal_bytes)
    assert (
        attest_main(
            [
                "record-attestation",
                "--resource-id",
                str(maths_needs_review["resource_id"]),
                "--artifact-id",
                str(maths_needs_review["artifact_id"]),
                "--scope-authorization-id",
                MATHS_AUTHORIZATION_ID,
                "--review-id",
                MATHS_REVIEW_ID,
                "--repository",
                REPOSITORY,
                "--pull-request",
                str(MATHS_PUB_PR),
                "--expected-head",
                MATHS_PUB_HEAD,
            ]
        )
        == 0
    )
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        rows = conn.execute(
            "SELECT attestation_id FROM ingestion_control.publication_attestations "
            "WHERE resource_id = %s AND review_id = %s AND invalidated_at IS NULL",
            (maths_needs_review["resource_id"], MATHS_REVIEW_ID),
        ).fetchall()
        assert len(rows) == 1
        state = get_resource_state(conn, resource_id=maths_needs_review["resource_id"])
        assert state is not None
        assert state[0] == ResourceState.NEEDS_REVIEW.value
    return {
        **maths_needs_review,
        "publication_attestation_id": rows[0][0],
        "expected_state_version": state[1],
        "proposal_path": proposal_path,
        "proposal_bytes": proposal_bytes,
    }


def _reject_duplicate_pdf_extraction(_raw: bytes) -> str:
    raise AssertionError("PDF text must come only from extract_pdf_pages")


def _fake_vector(text: str) -> tuple[float, ...]:
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
    raw = [math.sin(seed + index) for index in range(EMBED_DIMENSION)]
    norm = math.sqrt(sum(value * value for value in raw))
    return tuple(value / norm for value in raw)


@pytest.fixture(scope="module")
def publication_embedding_provider(product_pg: dict[str, str]) -> Any:
    """Le même E2E accepte le provider debug ou l'E5 matériel vérifié.

    Sans configuration explicite, le test historique garde un encodeur
    déterministe qui s'annonce honnêtement comme debug. Avec les deux ancres
    de modèle, l'intégralité du même chemin Worker B publie les vrais vecteurs.
    """
    artifact_root = os.environ.get("RAG_EMBEDDING_MODEL_CACHE_DIR", "").strip()
    inventory_sha256 = os.environ.get("RAG_EMBEDDING_MODEL_INVENTORY_SHA256", "").strip()
    if bool(artifact_root) != bool(inventory_sha256):
        pytest.fail(
            "real embedding acceptance requires both the artifact path and "
            "its external inventory anchor"
        )
    if artifact_root:
        return VerifiedE5EmbeddingProvider.from_artifact(
            artifact_root=Path(artifact_root),
            inventory_sha256=inventory_sha256,
            pg_dsn=product_pg["admin_dsn"],
        )
    return CallableEmbeddingProvider(
        encoder=lambda passages: [_fake_vector(passage) for passage in passages]
    )


def _publish_and_assert_french(
    control_pg: dict[str, str],
    product_pg: dict[str, str],
    french_attested: dict[str, Any],
    publication_embedding_provider: Any,
) -> None:
    """Une attestation A active ne peut pas satisfaire un job qui cite B."""
    with psycopg.connect(app_dsn(control_pg)) as control_conn:
        publication_job_id = create_job(
            control_conn,
            run_id=french_attested["run_id"],
            resource_id=french_attested["resource_id"],
            job_type="publication_resume",
            payload={
                "resource_id": str(french_attested["resource_id"]),
                "run_id": str(french_attested["run_id"]),
                "expected_state_version": french_attested["expected_state_version"],
                "publication_attestation_id": str(uuid.uuid4()),
            },
        )
        control_conn.commit()
        outcome = run_publication_resume_iteration(
            control_conn,
            deps=PublicationResumeDeps(
                owner="wave0-fr-worker-b-wrong-attestation",
                product_dsn=product_pg["publisher_dsn"],
                artifact_reader=french_attested["artifact_reader"],
                extract_text=_reject_duplicate_pdf_extraction,
                embedding_provider=publication_embedding_provider,
                pii_evidence_registry=french_attested["pii"],
                rights_evidence_registry=french_attested["rights"],
                manifest_digest=french_attested["manifest_digest"],
                placement_resolver=french_attested["resolver"],
            ),
            build_placements=None,
        )
        assert outcome.job_id == publication_job_id
        assert outcome.status == "retried"
        assert outcome.error is not None and "attestation" in outcome.error
        state = get_resource_state(control_conn, resource_id=french_attested["resource_id"])
        assert state is not None
        assert state[0] == ResourceState.NEEDS_REVIEW.value
        transition_counts = control_conn.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE to_state = 'REVIEWED'),
              COUNT(*) FILTER (WHERE to_state = 'RETRIEVAL_ELIGIBLE')
            FROM ingestion_control.workflow_events
            WHERE resource_id = %s AND event_type = 'transition'
            """,
            (french_attested["resource_id"],),
        ).fetchone()
        assert transition_counts == (0, 0)
        # Le scénario négatif a fini : il ne doit pas redevenir réclamable
        # pendant l'inférence CPU, puis voler l'itération du pilote suivant.
        assert (
            control_conn.execute(
                "UPDATE ingestion_control.jobs SET status = 'cancelled' "
                "WHERE job_id = %s AND status = 'queued'",
                (publication_job_id,),
            ).rowcount
            == 1
        )
        control_conn.commit()

    with psycopg.connect(product_pg["admin_dsn"]) as product_admin:
        product_rows = product_admin.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM public.rag_artifacts),
              (SELECT COUNT(*) FROM public.rag_artifact_placements),
              (SELECT COUNT(*) FROM public.rag_chunks)
            """
        ).fetchone()
        assert product_rows == (0, 0, 0)

    manifest_digest = french_attested["manifest_digest"]

    with psycopg.connect(app_dsn(control_pg)) as control_conn:
        publication_job_id = create_job(
            control_conn,
            run_id=french_attested["run_id"],
            resource_id=french_attested["resource_id"],
            job_type="publication_resume",
            payload={
                "resource_id": str(french_attested["resource_id"]),
                "run_id": str(french_attested["run_id"]),
                "expected_state_version": french_attested["expected_state_version"],
                "publication_attestation_id": str(french_attested["publication_attestation_id"]),
            },
        )
        control_conn.commit()
        outcome = run_publication_resume_iteration(
            control_conn,
            deps=PublicationResumeDeps(
                owner="wave0-fr-worker-b",
                product_dsn=product_pg["publisher_dsn"],
                artifact_reader=french_attested["artifact_reader"],
                extract_text=_reject_duplicate_pdf_extraction,
                embedding_provider=publication_embedding_provider,
                pii_evidence_registry=french_attested["pii"],
                rights_evidence_registry=french_attested["rights"],
                manifest_digest=manifest_digest,
                placement_resolver=french_attested["resolver"],
            ),
            build_placements=None,
        )
        assert outcome.status == "succeeded", outcome.error
        assert outcome.job_id == publication_job_id
        assert outcome.artifact_id == FR_SHA
        assert outcome.placement_rows == 1
        assert outcome.chunk_rows > 1
        state = get_resource_state(control_conn, resource_id=french_attested["resource_id"])
        assert state is not None
        assert state[0] == ResourceState.RETRIEVAL_ELIGIBLE.value
        control_conn.commit()

    with psycopg.connect(product_pg["admin_dsn"]) as product_admin:
        assert product_admin.execute(
            "SELECT COUNT(*) FROM public.rag_artifacts WHERE artifact_id = %s",
            (FR_SHA,),
        ).fetchone() == (1,)
        placement_count = product_admin.execute(
            "SELECT COUNT(*) FROM public.rag_artifact_placements WHERE artifact_id = %s",
            (FR_SHA,),
        ).fetchone()
        chunk_metrics = product_admin.execute(
            """
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE page_start IS NULL OR page_end IS NULL),
                   MIN(page_start), MAX(page_end),
                   array_agg(DISTINCT page_start ORDER BY page_start),
                   array_agg(DISTINCT model ORDER BY model),
                   COUNT(*) FILTER (WHERE vector IS NULL),
                   COUNT(*) FILTER (WHERE vector_dims(vector) <> %s),
                   COUNT(*) FILTER (WHERE page_start <> page_end)
            FROM public.rag_chunks WHERE artifact_id = %s
            """,
            (EMBED_DIMENSION, FR_SHA),
        ).fetchone()
        chunk_texts = product_admin.execute(
            "SELECT text FROM public.rag_chunks WHERE artifact_id = %s " "ORDER BY chunk_index",
            (FR_SHA,),
        ).fetchall()
        assert placement_count == (1,)
        assert chunk_metrics is not None
        assert chunk_metrics[0] > 1
        assert chunk_metrics[1:] == (
            0,
            1,
            8,
            list(range(1, 9)),
            [publication_embedding_provider.model_id],
            0,
            0,
            0,
        )
        assert all(
            publication_embedding_provider.passage_token_count(row[0])
            <= publication_embedding_provider.max_sequence_length
            for row in chunk_texts
        )
        token_counts = [
            publication_embedding_provider.passage_token_count(row[0]) for row in chunk_texts
        ]

    with psycopg.connect(product_pg["admin_dsn"]) as product_admin:
        duplicates = product_admin.execute(
            """
            SELECT
              (SELECT COUNT(*) - COUNT(DISTINCT artifact_id) FROM public.rag_artifacts),
              (SELECT COUNT(*) - COUNT(DISTINCT placement_id)
                 FROM public.rag_artifact_placements),
              (SELECT COUNT(*) - COUNT(DISTINCT chunk_id) FROM public.rag_chunks),
              (SELECT COUNT(*) FROM public.rag_chunks WHERE vector IS NULL)
            """
        ).fetchone()
        assert duplicates == (0, 0, 0, 0)
        print("FR_3E_ARTIFACT_ROWS=1")
        print(f"FR_3E_PLACEMENT_ROWS={placement_count[0]}")
        print(f"FR_3E_CHUNKS={chunk_metrics[0]}")
        print(f"FR_MIN_TOKENS={min(token_counts)}")
        print(f"FR_MEDIAN_TOKENS={median(token_counts):g}")
        print(f"FR_MAX_TOKENS={max(token_counts)}")


def test_publication_resume_publishes_real_french_with_page_metadata(
    control_pg: dict[str, str],
    product_pg: dict[str, str],
    french_attested: dict[str, Any],
    publication_embedding_provider: Any,
) -> None:
    _publish_and_assert_french(
        control_pg,
        product_pg,
        french_attested,
        publication_embedding_provider,
    )


def _publish_and_assert_maths(
    control_pg: dict[str, str],
    product_pg: dict[str, str],
    maths_attested: dict[str, Any],
    publication_embedding_provider: Any,
) -> None:
    manifest_digest = maths_attested["manifest_digest"]

    with psycopg.connect(app_dsn(control_pg)) as control_conn:
        publication_job_id = create_job(
            control_conn,
            run_id=maths_attested["run_id"],
            resource_id=maths_attested["resource_id"],
            job_type="publication_resume",
            payload={
                "resource_id": str(maths_attested["resource_id"]),
                "run_id": str(maths_attested["run_id"]),
                "expected_state_version": maths_attested["expected_state_version"],
                "publication_attestation_id": str(maths_attested["publication_attestation_id"]),
            },
        )
        control_conn.commit()
        outcome = run_publication_resume_iteration(
            control_conn,
            deps=PublicationResumeDeps(
                owner="wave0-maths-worker-b",
                product_dsn=product_pg["publisher_dsn"],
                artifact_reader=maths_attested["artifact_reader"],
                extract_text=_reject_duplicate_pdf_extraction,
                embedding_provider=publication_embedding_provider,
                pii_evidence_registry=maths_attested["pii"],
                rights_evidence_registry=maths_attested["rights"],
                manifest_digest=manifest_digest,
                placement_resolver=maths_attested["resolver"],
            ),
            build_placements=None,
        )
        assert outcome.status == "succeeded", outcome.error
        assert outcome.job_id == publication_job_id
        assert outcome.artifact_id == MATHS_SHA
        assert outcome.placement_rows == 1
        assert outcome.chunk_rows > 1
        state = get_resource_state(control_conn, resource_id=maths_attested["resource_id"])
        assert state is not None
        assert state[0] == ResourceState.RETRIEVAL_ELIGIBLE.value
        control_conn.commit()

    with psycopg.connect(product_pg["admin_dsn"]) as product_admin:
        artifact_count = product_admin.execute(
            "SELECT COUNT(*) FROM public.rag_artifacts WHERE artifact_id = %s",
            (MATHS_SHA,),
        ).fetchone()
        placement_count = product_admin.execute(
            "SELECT COUNT(*) FROM public.rag_artifact_placements WHERE artifact_id = %s",
            (MATHS_SHA,),
        ).fetchone()
        chunk_metrics = product_admin.execute(
            """
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE page_start IS NULL OR page_end IS NULL),
                   MIN(page_start), MAX(page_end),
                   array_agg(DISTINCT page_start ORDER BY page_start),
                   array_agg(DISTINCT model ORDER BY model),
                   COUNT(*) FILTER (WHERE vector IS NULL),
                   COUNT(*) FILTER (WHERE vector_dims(vector) <> %s),
                   COUNT(*) FILTER (WHERE page_start <> page_end)
            FROM public.rag_chunks WHERE artifact_id = %s
            """,
            (EMBED_DIMENSION, MATHS_SHA),
        ).fetchone()
        chunk_texts = product_admin.execute(
            "SELECT text FROM public.rag_chunks WHERE artifact_id = %s " "ORDER BY chunk_index",
            (MATHS_SHA,),
        ).fetchall()
        assert artifact_count == (1,)
        assert placement_count == (1,)
        assert chunk_metrics is not None
        assert chunk_metrics[0] > 1
        assert chunk_metrics[1:] == (
            0,
            1,
            11,
            list(range(1, 12)),
            [publication_embedding_provider.model_id],
            0,
            0,
            0,
        )
        assert all(
            publication_embedding_provider.passage_token_count(row[0])
            <= publication_embedding_provider.max_sequence_length
            for row in chunk_texts
        )
        token_counts = [
            publication_embedding_provider.passage_token_count(row[0]) for row in chunk_texts
        ]

    with psycopg.connect(product_pg["admin_dsn"]) as product_admin:
        duplicates = product_admin.execute(
            """
            SELECT
              (SELECT COUNT(*) - COUNT(DISTINCT artifact_id) FROM public.rag_artifacts),
              (SELECT COUNT(*) - COUNT(DISTINCT placement_id)
                 FROM public.rag_artifact_placements),
              (SELECT COUNT(*) - COUNT(DISTINCT chunk_id) FROM public.rag_chunks),
              (SELECT COUNT(*) FROM public.rag_chunks WHERE vector IS NULL)
            """
        ).fetchone()
        assert duplicates == (0, 0, 0, 0)
        print(f"MATHS_3E_ARTIFACT_ROWS={artifact_count[0]}")
        print(f"MATHS_3E_PLACEMENT_ROWS={placement_count[0]}")
        print(f"MATHS_3E_CHUNKS={chunk_metrics[0]}")
        print(f"MATHS_MIN_TOKENS={min(token_counts)}")
        print(f"MATHS_MEDIAN_TOKENS={median(token_counts):g}")
        print(f"MATHS_MAX_TOKENS={max(token_counts)}")


def test_publication_resume_publishes_real_maths_with_page_metadata(
    control_pg: dict[str, str],
    product_pg: dict[str, str],
    maths_attested: dict[str, Any],
    publication_embedding_provider: Any,
) -> None:
    _publish_and_assert_maths(
        control_pg,
        product_pg,
        maths_attested,
        publication_embedding_provider,
    )


def _urlsafe_json(value: dict[str, object]) -> str:
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _signed_identity_token(
    scope_id: str,
    *,
    secret: str,
    issuer: str,
    audience: str,
    identity_issuer: str,
    identity_audience: str,
    role: str = "teacher",
    now: int | None = None,
    expires_in: int = 600,
    signed_scope_id: str | None = None,
    scope_digest: str | None = None,
) -> str:
    artifact = load_retrieval_scope_artifact(scope_id)
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    target = artifact.target_identity
    evidence = artifact.evidence_subject
    issued_at = int(time.time()) if now is None else now
    expires_at = issued_at + expires_in
    jti = f"wave0-{uuid.uuid4().hex}"
    payload = {
        "protocol_version": "1",
        "iss": issuer,
        "aud": audience,
        "sub": "psn_wave0_search_acceptance",
        "jti": jti,
        "iat": issued_at,
        "exp": expires_at,
        "identity": {
            "iss": identity_issuer,
            "aud": identity_audience,
            "sub": "psn_wave0_search_acceptance",
            "jti": jti,
            "exp": expires_at,
            "tenant": target.tenant,
            "niveau": target.niveau.value,
            "role": role,
            "school_year": evidence.school_year,
            "pedagogical_profile": {
                "voie": target.voie.value,
                "matieres": [target.matiere],
                "statut_enseignement": target.statut_enseignement.value,
                "candidat": target.candidates[0].value,
                "audience": target.audience,
            },
        },
        "scope_id": signed_scope_id or artifact.scope_id,
        "scope_digest": scope_digest or artifact.sha256_digest(),
        "allowed_collections": [evidence.collection],
    }
    InternalIdentityEnvelope.model_validate(payload)
    header = _urlsafe_json({"alg": "HS256", "typ": "JWT"})
    body = _urlsafe_json(payload)
    signed = f"{header}.{body}"
    signature = hmac.new(secret.encode("utf-8"), signed.encode("ascii"), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{signed}.{encoded_signature}"


def _search_payload(scope_id: str, query: str) -> dict[str, object]:
    artifact = load_retrieval_scope_artifact(scope_id)
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    target = artifact.target_identity
    evidence = artifact.evidence_subject
    return {
        "student_profile": {
            "niveau": target.niveau.value,
            "voie": target.voie.value,
            "matieres": [target.matiere],
            "statut_enseignement": target.statut_enseignement.value,
            "candidat": target.candidates[0].value,
            "school_year": evidence.school_year,
            "zone": target.audience,
        },
        "curriculum_scope": {
            "niveau": evidence.niveau.value,
            "voie": evidence.voie.value,
            "matiere": evidence.matiere,
            "statut_enseignement": evidence.statut_enseignement.value,
        },
        "need": {"intent": "remediation", "query": query},
        "retrieval": {
            "k": 5,
            "hybrid": True,
            "rerank": True,
            "include_citations": True,
        },
    }


def _normalized(value: str) -> str:
    expanded = value.casefold().replace("œ", "oe")
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", expanded)
        if not unicodedata.combining(character)
    )


@pytest.fixture
def wave0_published_acceptance(
    request: pytest.FixtureRequest,
    control_pg: dict[str, str],
    product_pg: dict[str, str],
    publication_embedding_provider: Any,
) -> dict[str, str]:
    """Publier explicitement les pilotes absents avant l'acceptance HTTP.

    Le module complet réutilise les lignes déjà écrites par les tests Worker B.
    Une invocation ciblée du seul test HTTP exécute elle-même le même chemin
    gouverné Worker A → LOT42 → Worker B, sans dépendre de l'ordre de collecte.
    """
    assert publication_embedding_provider.model_id == CANONICAL_EMBED_MODEL
    assert isinstance(publication_embedding_provider, VerifiedE5EmbeddingProvider)
    assert publication_embedding_provider.verified_artifact is not None
    assert publication_embedding_provider.inventory_sha256

    with psycopg.connect(product_pg["admin_dsn"]) as product_admin:
        existing = {
            row[0]
            for row in product_admin.execute(
                "SELECT artifact_id FROM public.rag_artifacts "
                "WHERE artifact_id = ANY(%s)",
                ([FR_SHA, MATHS_SHA],),
            ).fetchall()
        }
    if FR_SHA not in existing:
        _publish_and_assert_french(
            control_pg,
            product_pg,
            request.getfixturevalue("french_attested"),
            publication_embedding_provider,
        )
    if MATHS_SHA not in existing:
        _publish_and_assert_maths(
            control_pg,
            product_pg,
            request.getfixturevalue("maths_attested"),
            publication_embedding_provider,
        )

    with psycopg.connect(product_pg["admin_dsn"]) as product_admin:
        rows = product_admin.execute(
            """
            SELECT artifact_id, COUNT(*), array_agg(DISTINCT model ORDER BY model)
            FROM public.rag_chunks
            WHERE artifact_id = ANY(%s)
            GROUP BY artifact_id
            ORDER BY artifact_id
            """,
            ([FR_SHA, MATHS_SHA],),
        ).fetchall()
        vector_counts = product_admin.execute(
            """
            SELECT COUNT(*) FILTER (WHERE model = %s),
                   COUNT(*) FILTER (WHERE model = %s),
                   COUNT(*) FILTER (WHERE vector IS NULL),
                   COUNT(*) FILTER (WHERE vector_dims(vector) <> %s)
            FROM public.rag_chunks
            """,
            (DEBUG_EMBED_MODEL, CANONICAL_EMBED_MODEL, EMBED_DIMENSION),
        ).fetchone()
    by_artifact = {row[0]: (row[1], row[2]) for row in rows}
    assert set(by_artifact) == {FR_SHA, MATHS_SHA}, (
        "run the complete Wave 0 module: HTTP acceptance requires both governed "
        "Worker B publications"
    )
    assert all(count > 1 for count, _models in by_artifact.values())
    assert all(models == [CANONICAL_EMBED_MODEL] for _count, models in by_artifact.values())
    assert vector_counts is not None
    assert vector_counts[0] == 0
    assert vector_counts[1] == sum(count for count, _models in by_artifact.values())
    assert vector_counts[2:] == (0, 0)
    return product_pg


def test_wave0_real_http_search_is_authenticated_isolated_and_semantic(
    wave0_published_acceptance: dict[str, str],
) -> None:
    product_pg = wave0_published_acceptance
    embedding_root = os.environ.get("RAG_EMBEDDING_MODEL_CACHE_DIR", "").strip()
    embedding_inventory = os.environ.get("RAG_EMBEDDING_MODEL_INVENTORY_SHA256", "").strip()
    reranker_root = os.environ.get("RAG_RERANKER_MODEL_CACHE_DIR", "").strip()
    reranker_inventory = os.environ.get("RAG_RERANKER_MODEL_INVENTORY_SHA256", "").strip()
    assert all(
        (embedding_root, embedding_inventory, reranker_root, reranker_inventory)
    ), "real HTTP acceptance requires both verified local model artifacts"

    dataset = yaml.safe_load(WAVE0_SEARCH_DATASET.read_text(encoding="utf-8"))
    assert isinstance(dataset, dict)
    assert all(len(cases) >= 10 for cases in dataset.values())

    bff_token = uuid.uuid4().hex + uuid.uuid4().hex
    identity_secret = uuid.uuid4().hex + uuid.uuid4().hex
    token_issuer = "wave0-http-bff"
    token_audience = "wave0-rag-engine"
    identity_issuer = "wave0-nexus-sso"
    identity_audience = "wave0-nexus-cockpit"
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    child_env = {
        **os.environ,
        "PYTHONPATH": str(ENGINE_ROOT),
        "RAG_ENV": "production",
        "RAG_BFF_SERVICE_TOKEN": bff_token,
        "NEXUS_INTERNAL_TOKEN_SECRET": identity_secret,
        "NEXUS_INTERNAL_TOKEN_ISSUER": token_issuer,
        "NEXUS_INTERNAL_TOKEN_AUDIENCE": token_audience,
        "NEXUS_SSO_ISSUER": identity_issuer,
        "NEXUS_SSO_AUDIENCE": identity_audience,
        "PG_RAG_DSN": product_pg["retrieval_dsn"],
        "PG_REVIEW_DSN": product_pg["review_dsn"],
        "RAG_COLLECTIONS_CONFIG": str(WAVE0_COLLECTIONS_CONFIG),
        "RAG_EMBEDDING_MODEL_CACHE_DIR": embedding_root,
        "RAG_EMBEDDING_MODEL_INVENTORY_SHA256": embedding_inventory,
        "RAG_RERANKER_MODEL_CACHE_DIR": reranker_root,
        "RAG_RERANKER_MODEL_INVENTORY_SHA256": reranker_inventory,
        "EMBED_MODEL": CANONICAL_EMBED_MODEL,
        "EMBED_DIM": str(EMBED_DIMENSION),
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.ingestor.api_v2:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=ENGINE_ROOT,
        env=child_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 300
        with httpx.Client(base_url=base_url, timeout=30.0) as client:
            while True:
                if process.poll() is not None:
                    pytest.fail("uvicorn exited before Wave 0 readiness")
                try:
                    health = client.get("/health")
                    if health.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() >= deadline:
                    pytest.fail("uvicorn did not become ready within the bounded deadline")
                time.sleep(0.25)
            assert health.json()["schema_head"] == "004_artifact_placements"

            maths_token = _signed_identity_token(
                "entree_seconde_maths_v1",
                secret=identity_secret,
                issuer=token_issuer,
                audience=token_audience,
                identity_issuer=identity_issuer,
                identity_audience=identity_audience,
            )
            french_token = _signed_identity_token(
                "entree_seconde_francais_v1",
                secret=identity_secret,
                issuer=token_issuer,
                audience=token_audience,
                identity_issuer=identity_issuer,
                identity_audience=identity_audience,
            )
            bff_headers = {"Authorization": f"Bearer {bff_token}"}
            maths_headers = {**bff_headers, "X-Nexus-Identity": maths_token}
            french_headers = {**bff_headers, "X-Nexus-Identity": french_token}
            sample_payload = _search_payload(
                "entree_seconde_maths_v1", dataset["entree_seconde_maths_v1"][0]["query"]
            )

            assert client.post("/search/v2", json=sample_payload).status_code == 401
            assert (
                client.post(
                    "/search/v2",
                    json=sample_payload,
                    headers={"Authorization": "Bearer invalid-bff-token"},
                ).status_code
                == 401
            )
            assert (
                client.post("/search/v2", json=sample_payload, headers=bff_headers).status_code
                == 401
            )
            bad_signature = f"A{maths_token[1:]}"
            assert (
                client.post(
                    "/search/v2",
                    json=sample_payload,
                    headers={**bff_headers, "X-Nexus-Identity": bad_signature},
                ).status_code
                == 401
            )
            expired_token = _signed_identity_token(
                "entree_seconde_maths_v1",
                secret=identity_secret,
                issuer=token_issuer,
                audience=token_audience,
                identity_issuer=identity_issuer,
                identity_audience=identity_audience,
                now=int(time.time()) - 700,
                expires_in=600,
            )
            assert (
                client.post(
                    "/search/v2",
                    json=sample_payload,
                    headers={**bff_headers, "X-Nexus-Identity": expired_token},
                ).status_code
                == 401
            )
            unknown_scope_token = _signed_identity_token(
                "entree_seconde_maths_v1",
                secret=identity_secret,
                issuer=token_issuer,
                audience=token_audience,
                identity_issuer=identity_issuer,
                identity_audience=identity_audience,
                signed_scope_id="scope_absent_wave0",
            )
            assert (
                client.post(
                    "/search/v2",
                    json=sample_payload,
                    headers={**bff_headers, "X-Nexus-Identity": unknown_scope_token},
                ).status_code
                == 403
            )
            wrong_digest_token = _signed_identity_token(
                "entree_seconde_maths_v1",
                secret=identity_secret,
                issuer=token_issuer,
                audience=token_audience,
                identity_issuer=identity_issuer,
                identity_audience=identity_audience,
                scope_digest="0" * 64,
            )
            assert (
                client.post(
                    "/search/v2",
                    json=sample_payload,
                    headers={**bff_headers, "X-Nexus-Identity": wrong_digest_token},
                ).status_code
                == 403
            )
            french_payload = _search_payload(
                "entree_seconde_francais_v1",
                dataset["entree_seconde_francais_v1"][0]["query"],
            )
            assert (
                client.post("/search/v2", json=french_payload, headers=maths_headers).status_code
                == 403
            )
            wrong_curriculum_payload = json.loads(json.dumps(sample_payload))
            wrong_curriculum_payload["curriculum_scope"]["niveau"] = "seconde"
            assert (
                client.post(
                    "/search/v2", json=wrong_curriculum_payload, headers=maths_headers
                ).status_code
                == 403
            )
            wrong_target_payload = json.loads(json.dumps(sample_payload))
            wrong_target_payload["student_profile"]["niveau"] = "terminale"
            assert (
                client.post(
                    "/search/v2", json=wrong_target_payload, headers=maths_headers
                ).status_code
                == 403
            )
            student_token = _signed_identity_token(
                "entree_seconde_maths_v1",
                secret=identity_secret,
                issuer=token_issuer,
                audience=token_audience,
                identity_issuer=identity_issuer,
                identity_audience=identity_audience,
                role="student",
            )
            assert (
                client.get(
                    "/collections/v2",
                    headers={**bff_headers, "X-Nexus-Identity": student_token},
                ).status_code
                == 403
            )

            maths_collections = client.get("/collections/v2", headers=maths_headers)
            french_collections = client.get("/collections/v2", headers=french_headers)
            assert maths_collections.status_code == 200
            assert french_collections.status_code == 200
            assert [item["name"] for item in maths_collections.json()["collections"]] == [
                MATHS_COLLECTION
            ]
            assert [item["name"] for item in french_collections.json()["collections"]] == [
                COLLECTION
            ]

            scope_expectations = {
                "entree_seconde_maths_v1": (
                    maths_headers,
                    MATHS_COLLECTION,
                    MATHS_SHA,
                    MATHS_SOURCE_PATH,
                ),
                "entree_seconde_francais_v1": (
                    french_headers,
                    COLLECTION,
                    FR_SHA,
                    SOURCE_PATH,
                ),
            }
            passed: dict[str, int] = {}
            for scope_id, cases in dataset.items():
                headers, collection, expected_sha, expected_path = scope_expectations[scope_id]
                passed[scope_id] = 0
                for case in cases:
                    response = client.post(
                        "/search/v2",
                        json=_search_payload(scope_id, case["query"]),
                        headers=headers,
                    )
                    assert response.status_code == 200, (
                        scope_id,
                        response.status_code,
                    )
                    parsed = RetrievalResponse.model_validate(response.json())
                    assert parsed.results, scope_id
                    top = parsed.results[0]
                    metadata = top.metadata
                    assert metadata["collection"] == collection
                    assert metadata["content_sha256"] == expected_sha
                    assert metadata["artifact_id"] == expected_sha
                    assert metadata["review_status"] == "reviewed"
                    assert metadata["placement_source_path"] == expected_path
                    assert top.doc_id == expected_sha
                    assert top.citation is not None
                    assert top.citation.page is not None
                    assert top.citation.page == case["expected_page"]
                    assert top.citation.rights == Rights.officiel_public.value
                    normalized_excerpt = _normalized(top.excerpt)
                    assert any(
                        _normalized(concept) in normalized_excerpt
                        for concept in case["expected_concepts_any"]
                    ), (
                        scope_id,
                        case["query"],
                        metadata["dense_score"],
                        metadata["lexical_score"],
                        metadata["rrf_score"],
                        metadata["rerank_score"],
                        metadata["score_final"],
                    )
                    assert all(
                        result.metadata.get("collection") == collection
                        and result.metadata.get("content_sha256") == expected_sha
                        for result in parsed.results
                    )
                    passed[scope_id] += 1

            assert passed["entree_seconde_maths_v1"] == len(dataset["entree_seconde_maths_v1"])
            assert passed["entree_seconde_francais_v1"] == len(
                dataset["entree_seconde_francais_v1"]
            )
            print("API_V2_REAL_HTTP=true")
            print("BFF_AUTH_PASS=true")
            print("SIGNED_IDENTITY_PASS=true")
            print("SCOPE_ISOLATION_AUTH_PASS=true")
            print("SIGNED_COLLECTION_PICKER_ISOLATED=true")
            print("REAL_RERANKER_USED=true")
            print(f"MATHS_3E_QUERY_TOTAL={len(dataset['entree_seconde_maths_v1'])}")
            print(f"MATHS_3E_QUERY_PASS={passed['entree_seconde_maths_v1']}")
            print(f"FR_3E_QUERY_TOTAL={len(dataset['entree_seconde_francais_v1'])}")
            print(f"FR_3E_QUERY_PASS={passed['entree_seconde_francais_v1']}")
            print("CROSS_COLLECTION_LEAKS=0")
            print("WRONG_SCOPE_LEAKS=0")
    finally:
        stderr = ""
        process.terminate()
        try:
            _stdout, stderr = process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            _stdout, stderr = process.communicate(timeout=15)
        if process.returncode not in (0, -15):
            sanitized = "\n".join(stderr.splitlines()[-40:])[:8_000]
            pytest.fail(f"uvicorn failed during Wave 0 acceptance:\n{sanitized}")
