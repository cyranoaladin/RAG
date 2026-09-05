"""Ingestion gouvernée réelle des dix collections multi-niveaux.

Ce test opt-in exerce deux PostgreSQL jetables, LocalGitHub, LOT41A,
Worker A, LOT42, Worker B et le vrai provider E5. Les PDF et preuves PII
restent hors Git et sont désignés uniquement par variables d'environnement.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid
from collections import defaultdict
from collections.abc import Iterator, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
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

from ingestor.collection_config import load_collection_config  # noqa: E402
from ingestor.embedding_contract import CANONICAL_EMBED_MODEL  # noqa: E402
from ingestor.embedding_provider import VerifiedE5EmbeddingProvider  # noqa: E402
from ingestor.ingestion_control.jobs import create_job  # noqa: E402
from ingestor.ingestion_control.sealed_evidence import (  # noqa: E402
    VerifiedPIIEvidenceRegistry,
    VerifiedRightsEvidenceRegistry,
)
from ingestor.ingestion_profiles.registry import (  # noqa: E402
    load_profile_registry,
    profile_fingerprint,
)
from ingestor.ingestion_worker.attest_publication_cli import (  # noqa: E402
    main as attest_main,
)
from ingestor.ingestion_worker.authorize_scope_cli import (  # noqa: E402
    main as authorize_scope_main,
)
from ingestor.ingestion_worker.publication_resume import (  # noqa: E402
    PublicationResumeDeps,
    run_publication_resume_iteration,
)
from ingestor.ingestion_worker.runner import WorkerDeps, run_worker_iteration  # noqa: E402
from ingestor.ingestion_worker.storage import (  # noqa: E402
    make_filesystem_artifact_reader,
    make_filesystem_artifact_store,
)
from ingestor.multilevel_evidence import (  # noqa: E402
    load_multilevel_candidate_inventory,
    load_multilevel_currentness,
)
from ingestor.multilevel_mapping import load_multilevel_mapping  # noqa: E402
from ingestor.multilevel_verified_placement import (  # noqa: E402
    MultilevelVerifiedPedagogicalPlacementResolver,
    load_multilevel_release_eligibility,
)
from ingestor.programme_registry import load_programme_index_registry  # noqa: E402
from ingestor.release_readiness import (  # noqa: E402
    load_release_expectation,
    validate_release_readiness,
)
from ingestor.staging_profile_manifest import (  # noqa: E402
    verify_staging_profile_manifest,
)

pytestmark = [pytest.mark.integration, requires_docker]

TARGET_COLLECTIONS = 10
EXPECTED_ARTIFACTS = 11
EXPECTED_PLACEMENTS = 11
# 353 et non 359 : sous la sémantique d'extraction actuelle (page policy
# introduite par a4b1f96) les mêmes onze artefacts, au même nombre de pages
# (137), rendent 353 chunks. La release a été régénérée en conséquence ;
# l'ancienne est conservée sous multilevel-superseded-20260813/.
EXPECTED_CHUNKS = 353
RELEASE_SHA256 = "6ec1a4f8e0d644540214660c3568b2c169770b7789cd850186b6c3f1d6bd1c26"
INVENTORY_SHA256 = "86531933e0779a739f20c347d32dd02e54672f058024d16e1198809cef965300"
CURRENTNESS_SHA256 = "2ad7209f28cd7cbf9f1ea91724b687983579c36c91619e8d107d28b72b849122"
PII_SHA256 = "46d6c738ebc230dedb95ada2d07bd17a0907d75ee8aedcd556d27027ad50daa8"
RIGHTS_SHA256 = "e3c9a157f1f78171c0052750fa08b7726b99ea4dd348728f1b90db07f93ef1ff"
PROGRAMME_SHA256 = "9822f795f7c293618305a7ed9ad9087f68a96267415472fc0c3e39d3c89aa58c"
PROFILE_MANIFEST_SHA256 = "47c86091687fc7a4a7e6d76aa8ff65eb02f3ab861dd15c7600dc93e6eb98b753"
LEVELS_SHA256 = "8ad9e7a6d62e26e5c233f8a3c62fba7a1df72da29f690a3c17d5e7660e740e1e"
SUBJECTS_SHA256 = "c3c2d20bd27243a77795b3a056441d256f0b0b9b73306b3a1e710eee61407ed6"
DOCUMENT_TYPES_SHA256 = "3518fe87d4394a4615c10887f276d95cfd58f517adb58af6f8efc686f242561b"
CORPUS_MANIFEST_SHA256 = "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
E5_INVENTORY_SHA256 = "e2c7384ba36096b3f3bdfff4973f728596104aff0f1d38f1b6463e60765fe22a"

RELEASE_ROOT = (
    REPOSITORY_ROOT
    / "services"
    / "rag-pedago"
    / "data"
    / "releases"
    / "prerentree_2026_2027"
    / "multilevel"
)
RELEASE_PATH = RELEASE_ROOT / "multilevel.release.json"
INVENTORY_PATH = RELEASE_ROOT / "candidate_inventory.json"
CURRENTNESS_PATH = (
    REPOSITORY_ROOT
    / "services"
    / "rag-pedago"
    / "configs"
    / "prerentree_2026_2027"
    / "multilevel_currentness_evidence.yml"
)
RIGHTS_PATH = (
    REPOSITORY_ROOT / "services" / "rag-pedago" / "configs" / "rights_evidence_registry.yml"
)
PROFILES_DIR = ENGINE_ROOT / "configs" / "ingestion_profiles" / "staging" / "multilevel"
PROFILE_MANIFEST_PATH = (
    ENGINE_ROOT / "configs" / "ingestion_profiles" / "staging" / "multilevel_manifest.json"
)
PROGRAMME_PATH = ENGINE_ROOT / "configs" / "programme_indexes" / "multilevel_2026_2027.yml"
LEVELS_PATH = ENGINE_ROOT / "configs" / "mappings" / "eduscol_multilevel_levels.yml"
SUBJECTS_PATH = ENGINE_ROOT / "configs" / "mappings" / "eduscol_multilevel_subjects.yml"
DOCUMENT_TYPES_PATH = ENGINE_ROOT / "configs" / "mappings" / "eduscol_multilevel_document_types.yml"

PDF_MIRROR = Path(os.environ.get("NEXUS_MULTILEVEL_PDF_MIRROR", ""))
PII_PATH = Path(os.environ.get("NEXUS_MULTILEVEL_PII_EVIDENCE_PATH", ""))
E5_PATH = Path(os.environ.get("RAG_EMBEDDING_MODEL_CACHE_DIR", ""))
RERANKER_PATH = Path(os.environ.get("RAG_RERANKER_MODEL_CACHE_DIR", ""))
RERANKER_INVENTORY_SHA256 = "bdcedc4d7cfe647b9aaa5a7546822dfee7826ebb3c64472bf89eae7592e08fe1"
if not os.environ.get("NEXUS_REQUIRE_DOCKER", "").strip() or not all(
    os.environ.get(name, "").strip()
    for name in (
        "NEXUS_MULTILEVEL_PDF_MIRROR",
        "NEXUS_MULTILEVEL_PII_EVIDENCE_PATH",
        "RAG_EMBEDDING_MODEL_CACHE_DIR",
        "RAG_EMBEDDING_MODEL_INVENTORY_SHA256",
        "RAG_RERANKER_MODEL_CACHE_DIR",
        "RAG_RERANKER_MODEL_INVENTORY_SHA256",
    )
):
    pytest.skip("multilevel real ingestion not requested", allow_module_level=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def control_pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("multilevel-real")


@pytest.fixture(scope="module")
def product_pg() -> Iterator[dict[str, str]]:
    """PostgreSQL+pgvector produit propre, distinct du plan de contrôle."""
    port = free_port()
    container = f"nexus-multilevel-product-{uuid.uuid4().hex[:10]}"
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
        admin_dsn = (
            f"host=127.0.0.1 port={port} dbname={PG_DB} "
            f"user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
        )
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
            assert result.returncode == 0, f"{name}: {result.stderr}"
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
                    (version, name, _sha256(migrations / name)),
                )
        publisher_password = secrets.token_urlsafe(32)
        retrieval_password = secrets.token_urlsafe(32)
        review_password = secrets.token_urlsafe(32)
        provision = subprocess.run(
            [str(ENGINE_ROOT / "infra" / "postgres" / "provision_runtime_roles.sh")],
            env={
                **admin_env,
                "POSTGRES_USER": PG_SUPERUSER,
                "POSTGRES_DB": PG_DB,
                "PGVECTOR_RETRIEVAL_USER": "multilevel_retrieval",
                "PGVECTOR_RETRIEVAL_PASSWORD": retrieval_password,
                "PGVECTOR_REVIEW_USER": "multilevel_review",
                "PGVECTOR_REVIEW_PASSWORD": review_password,
                "PGVECTOR_PUBLISHER_USER": "multilevel_publisher",
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
                f"user=multilevel_publisher password={publisher_password}"
            ),
            "retrieval_dsn": (
                f"host=127.0.0.1 port={port} dbname={PG_DB} "
                f"user=multilevel_retrieval password={retrieval_password}"
            ),
            "review_dsn": (
                f"host=127.0.0.1 port={port} dbname={PG_DB} "
                f"user=multilevel_review password={review_password}"
            ),
        }
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)


def _build_runtime_authorities() -> dict[str, Any]:
    assert _sha256(RELEASE_PATH) == RELEASE_SHA256
    assert _sha256(INVENTORY_PATH) == INVENTORY_SHA256
    assert _sha256(CURRENTNESS_PATH) == CURRENTNESS_SHA256
    assert _sha256(PII_PATH) == PII_SHA256
    assert _sha256(RIGHTS_PATH) == RIGHTS_SHA256
    assert _sha256(PROGRAMME_PATH) == PROGRAMME_SHA256
    assert _sha256(PROFILE_MANIFEST_PATH) == PROFILE_MANIFEST_SHA256
    assert os.environ["RAG_EMBEDDING_MODEL_INVENTORY_SHA256"] == E5_INVENTORY_SHA256

    profiles = load_profile_registry(PROFILES_DIR)
    profile_manifest = verify_staging_profile_manifest(profiles, PROFILE_MANIFEST_PATH)
    inventory = load_multilevel_candidate_inventory(
        INVENTORY_PATH, expected_sha256=INVENTORY_SHA256
    )
    currentness = load_multilevel_currentness(
        CURRENTNESS_PATH,
        expected_sha256=CURRENTNESS_SHA256,
        candidate_inventory=inventory,
    )
    mapping = load_multilevel_mapping(
        levels_path=LEVELS_PATH,
        expected_levels_sha256=LEVELS_SHA256,
        subjects_path=SUBJECTS_PATH,
        expected_subjects_sha256=SUBJECTS_SHA256,
        document_types_path=DOCUMENT_TYPES_PATH,
        expected_document_types_sha256=DOCUMENT_TYPES_SHA256,
    )
    programme = load_programme_index_registry(
        registry_path=PROGRAMME_PATH,
        expected_registry_sha256=PROGRAMME_SHA256,
        repository_root=REPOSITORY_ROOT,
    )
    eligibility = load_multilevel_release_eligibility(RELEASE_PATH, expected_sha256=RELEASE_SHA256)
    resolver = MultilevelVerifiedPedagogicalPlacementResolver.from_authorities(
        candidate_inventory=inventory,
        currentness=currentness,
        mapping=mapping,
        profiles=profiles,
        profile_manifest=profile_manifest,
        environment="rehearsal",
        programme_registry=programme,
        collection_config=load_collection_config(),
        release_eligibility=eligibility,
    )
    expectation = load_release_expectation(RELEASE_PATH, RELEASE_SHA256)
    pii = VerifiedPIIEvidenceRegistry.load(
        PII_PATH,
        expected_evidence_sha256=PII_SHA256,
        expected_corpus_manifest_sha256=CORPUS_MANIFEST_SHA256,
    )
    rights = VerifiedRightsEvidenceRegistry.load(
        RIGHTS_PATH,
        expected_registry_sha256=RIGHTS_SHA256,
        expected_corpus_manifest_sha256=CORPUS_MANIFEST_SHA256,
    )
    assert len(profiles) == TARGET_COLLECTIONS
    assert len(expectation.collections) == TARGET_COLLECTIONS
    assert len(expectation.artifacts) == EXPECTED_ARTIFACTS
    return {
        "profiles": profiles,
        "profile_manifest": profile_manifest,
        "resolver": resolver,
        "expectation": expectation,
        "pii": pii,
        "rights": rights,
    }


def _authorization_document(
    *,
    profile: Any,
    manifest_digest: str,
    authorization_id: str,
    allowed_content_sha256: list[str],
) -> ScopeAuthorizationArtifactV2:
    return ScopeAuthorizationArtifactV2.model_validate(
        {
            "protocol_version": "LOT41A-V2",
            "authorization_id": authorization_id,
            "decision": "AUTHORIZE_INGESTION_SCOPE",
            "scope": profile.scope.model_dump(mode="json"),
            "manifest_digest": manifest_digest,
            "profile_id": profile.scope.collection,
            "profile_version": profile.profile_version,
            "profile_fingerprint": profile_fingerprint(profile),
            "allowed_domains": sorted(profile.allowed_domains),
            "rights_categories": [Rights.officiel_public.value],
            "exclusions": [],
            "allowed_content_sha256": sorted(allowed_content_sha256),
            "pii_absence_attested": True,
            "pii_absence_evidence": f"multilevel PII sha256={PII_SHA256}; all listed SHA CLEARED",
            "valid_from": "2026-08-12T00:00:00Z",
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
        {
            **scope,
            "audience": sorted(scope["audience"]),
            "profile_version": profile.profile_version,
        },
    ).fetchone()
    assert row is not None
    return uuid.UUID(str(row[0]))


def _parse_proposal(output: str) -> tuple[str, bytes]:
    lines = output.splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines) if line.startswith("REVIEW_ARTIFACT_PATH "))
    return lines[index].split(" ", 1)[1].strip(), "".join(lines[index + 2 :]).encode()


def _reject_duplicate_pdf_extraction(_raw: bytes) -> str:
    raise AssertionError("PDF text must come only from extract_pdf_pages")


@dataclass(frozen=True)
class SearchCase:
    query: str
    expected_artifact_sha256: str
    expected_concepts_any: tuple[str, ...]


SEARCH_CASES: Mapping[str, tuple[SearchCase, ...]] = {
    "entree_premiere_maths_v2": (
        SearchCase(
            "Comment le programme aborde-t-il les vecteurs et la géométrie repérée en seconde ?",
            "05c5403d45bfc3631fa13b5c334822de09bcd68d850d0611044045cddba270de",
            ("vecteur", "geometrie"),
        ),
        SearchCase(
            "Quelles capacités sont attendues sur les fonctions en classe de seconde ?",
            "05c5403d45bfc3631fa13b5c334822de09bcd68d850d0611044045cddba270de",
            ("fonction",),
        ),
        SearchCase(
            "Comment les probabilités et statistiques sont-elles enseignées en seconde ?",
            "05c5403d45bfc3631fa13b5c334822de09bcd68d850d0611044045cddba270de",
            ("probabil", "statisti"),
        ),
    ),
    "entree_premiere_francais_v2": (
        SearchCase(
            "Quel est le programme de français en classe de seconde générale et technologique ?",
            "b54b6422d0eb2fb906e6ad6c79a2e95e6cae00e3fa113da5f7499eee4cc53ae7",
            ("programme",),
        ),
        SearchCase(
            "Comment enseigner explicitement la compréhension de l'écrit en seconde ?",
            "c4e3cc6fb201f4dabc78fa47206c1b498b3ed46496cf05165a74e0ecd8856fb1",
            ("comprehension",),
        ),
        SearchCase(
            "Quelles démarches permettent d'enseigner explicitement la compréhension de textes en seconde ?",
            "c4e3cc6fb201f4dabc78fa47206c1b498b3ed46496cf05165a74e0ecd8856fb1",
            ("comprehension",),
        ),
    ),
    "entree_troisieme_maths_v2": (
        SearchCase(
            "Quels sont les attendus de fin d'année en mathématiques en quatrième ?",
            "d0edabd6a21d6345d36d32c5506ddcf225e819ddca25d27c1ecc3f97b87a8966",
            ("attendus",),
        ),
        SearchCase(
            "Que doit savoir faire un élève de quatrième en calcul littéral ?",
            "d0edabd6a21d6345d36d32c5506ddcf225e819ddca25d27c1ecc3f97b87a8966",
            ("calcul litteral",),
        ),
        SearchCase(
            "Quels sont les attendus de fin d'année pour calculer avec des nombres rationnels en quatrième ?",
            "d0edabd6a21d6345d36d32c5506ddcf225e819ddca25d27c1ecc3f97b87a8966",
            ("nombres",),
        ),
    ),
    "entree_troisieme_francais_v2": (
        SearchCase(
            "Quels sont les attendus de fin d'année en français en quatrième ?",
            "73c001b93cf2151924da5245c4d740b56a5194c17e29c37cda2e1c0593711fae",
            ("attendus",),
        ),
        SearchCase(
            "Quels attendus de fin d'année concernent l'expression orale en quatrième ?",
            "73c001b93cf2151924da5245c4d740b56a5194c17e29c37cda2e1c0593711fae",
            ("oral",),
        ),
        SearchCase(
            "Comment un élève de quatrième doit-il justifier son interprétation d'un texte ?",
            "73c001b93cf2151924da5245c4d740b56a5194c17e29c37cda2e1c0593711fae",
            ("interpret",),
        ),
    ),
    "entree_terminale_maths_v2": (
        SearchCase(
            "Quel est le programme 2026 de spécialité mathématiques en première générale ?",
            "5303df0fcf6335f06d00c969a61dcd82cc3fdfd105271ae5c2ef580ff49b6c08",
            ("programme",),
        ),
        SearchCase(
            "Comment le programme de première aborde-t-il l'algèbre et l'analyse ?",
            "5303df0fcf6335f06d00c969a61dcd82cc3fdfd105271ae5c2ef580ff49b6c08",
            ("analyse", "algebre"),
        ),
        SearchCase(
            "Quelle place occupent les probabilités conditionnelles et les variables aléatoires en première ?",
            "5303df0fcf6335f06d00c969a61dcd82cc3fdfd105271ae5c2ef580ff49b6c08",
            ("probabil",),
        ),
    ),
    "entree_terminale_nsi_v2": (
        SearchCase(
            "Quel est le programme de spécialité NSI en première générale ?",
            "7ca9a32e1823be6c1120cb0417324c3cb01688d1d194c7614a88ea851ccc60b0",
            ("programme",),
        ),
        SearchCase(
            "Quelles notions de programmation et d'algorithmique sont étudiées en NSI première ?",
            "7ca9a32e1823be6c1120cb0417324c3cb01688d1d194c7614a88ea851ccc60b0",
            ("algorithm",),
        ),
        SearchCase(
            "Quels apprentissages concernent le Web et les interactions entre l'homme et la machine en première NSI ?",
            "7ca9a32e1823be6c1120cb0417324c3cb01688d1d194c7614a88ea851ccc60b0",
            ("web", "interaction"),
        ),
    ),
    "eaf_premiere_francais_v2": (
        SearchCase(
            "Quel est le programme de français en première générale et technologique ?",
            "b88b5c685ec05d44b0c22d64f491443759fc0f544fe9ad33e626fb6cc29bf65a",
            ("programme",),
        ),
        # Requalifiée le 2026-09-05 contre la release régénérée. La formulation
        # précédente (« Quelles compétences prépare-t-on pour les épreuves
        # anticipées de français ? ») n'est plus servie : mesurée sur les 38
        # chunks de l'artefact, la meilleure logit du reranker vaut -1.251,
        # très en dessous du plancher gouverné de 1.90. Le contenu, lui, est
        # bien là — page 9, « l'orientation générale du travail en classe de
        # première est liée à la préparation des élèves aux épreuves anticipées
        # de français » — et cette question-ci l'atteint (logit 2.032). Le
        # plancher n'a pas bougé ; c'est la question qui a été remesurée.
        SearchCase(
            "Quels exercices d'écrit et d'oral prépare-t-on en première en vue "
            "des épreuves anticipées de français ?",
            "b88b5c685ec05d44b0c22d64f491443759fc0f544fe9ad33e626fb6cc29bf65a",
            ("epreuves anticipees",),
        ),
        # Requalifiée le 2026-09-05, même cause : sous la partition régénérée,
        # la formulation précédente (« Comment le programme de première
        # organise-t-il lecture, écriture et étude de la langue ? ») place en
        # tête un chunk dont l'extrait de 200 caractères, centré sur les
        # termes de la question, ne montre pas « langue ». L'extrait est la
        # citation rendue à l'élève : un extrait qui n'expose pas la notion
        # demandée n'étaye pas la réponse. Cette question-ci la met en tête
        # et dans l'extrait.
        SearchCase(
            "Comment l'étude de la langue est-elle conduite en classe de première ?",
            "b88b5c685ec05d44b0c22d64f491443759fc0f544fe9ad33e626fb6cc29bf65a",
            ("langue",),
        ),
    ),
    "terminale_maths_v2": (
        SearchCase(
            "Quel est le programme de spécialité mathématiques en terminale générale ?",
            "eb8369e7c1611e90f51491fecc5a7c2081a9c57f9c7fbb08d0414677b56ce16f",
            ("programme",),
        ),
        SearchCase(
            "Comment étudie-t-on les suites, les limites et la dérivation en terminale ?",
            "eb8369e7c1611e90f51491fecc5a7c2081a9c57f9c7fbb08d0414677b56ce16f",
            ("suite", "limite"),
        ),
        SearchCase(
            "Comment le programme de terminale traite-t-il probabilités et géométrie ?",
            "eb8369e7c1611e90f51491fecc5a7c2081a9c57f9c7fbb08d0414677b56ce16f",
            ("probabil", "geometr"),
        ),
    ),
    "terminale_nsi_v2": (
        SearchCase(
            "Quel est le programme de spécialité NSI en terminale générale ?",
            "10ce34666edd722a3d8d86642a9f1ac205c7a9d128d6142a17effcba2fb85e69",
            ("programme",),
        ),
        SearchCase(
            "Quelles structures de données et bases de données sont étudiées en NSI terminale ?",
            "10ce34666edd722a3d8d86642a9f1ac205c7a9d128d6142a17effcba2fb85e69",
            ("base", "donnees"),
        ),
        SearchCase(
            "Comment le programme aborde-t-il la récursivité et les algorithmes diviser pour régner ?",
            "10ce34666edd722a3d8d86642a9f1ac205c7a9d128d6142a17effcba2fb85e69",
            ("diviser pour regner",),
        ),
    ),
    "terminale_physique_chimie_v2": (
        SearchCase(
            "Quel est le programme de spécialité physique-chimie en terminale générale ?",
            "c07f8b2db9d22a6c2b9ab8386cf7ba323bc2c56abacb3f560dd97d02b383de18",
            ("programme",),
        ),
        SearchCase(
            "Comment prévoir le sens d'évolution spontanée d'un système chimique ?",
            "c07f8b2db9d22a6c2b9ab8386cf7ba323bc2c56abacb3f560dd97d02b383de18",
            ("evolution", "systeme chimique"),
        ),
        SearchCase(
            "Quelles notions de mécanique, d'ondes et de mesures sont étudiées en physique-chimie terminale ?",
            "c07f8b2db9d22a6c2b9ab8386cf7ba323bc2c56abacb3f560dd97d02b383de18",
            ("mecanique", "ondes"),
        ),
    ),
}
FR_SECONDE_SECOND_ARTIFACT_SHA = "c4e3cc6fb201f4dabc78fa47206c1b498b3ed46496cf05165a74e0ecd8856fb1"


def _urlsafe_json(value: dict[str, object]) -> str:
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _identity_token(
    scope_id: str,
    *,
    secret: str,
    issuer: str,
    audience: str,
    identity_issuer: str,
    identity_audience: str,
) -> str:
    artifact = load_retrieval_scope_artifact(scope_id)
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    target = artifact.target_identity
    evidence = artifact.evidence_subject
    issued_at = int(time.time())
    expires_at = issued_at + 600
    jti = f"multilevel-{uuid.uuid4().hex}"
    payload: dict[str, object] = {
        "protocol_version": "1",
        "iss": issuer,
        "aud": audience,
        "sub": "psn_multilevel_search_acceptance",
        "jti": jti,
        "iat": issued_at,
        "exp": expires_at,
        "identity": {
            "iss": identity_issuer,
            "aud": identity_audience,
            "sub": "psn_multilevel_search_acceptance",
            "jti": jti,
            "exp": expires_at,
            "tenant": target.tenant,
            "niveau": target.niveau.value,
            "role": "teacher",
            "school_year": evidence.school_year,
            "pedagogical_profile": {
                "voie": target.voie.value,
                "matieres": [target.matiere],
                "statut_enseignement": target.statut_enseignement.value,
                "candidat": target.candidates[0].value,
                "audience": target.audience,
            },
        },
        "scope_id": artifact.scope_id,
        "scope_digest": artifact.sha256_digest(),
        "allowed_collections": [evidence.collection],
    }
    InternalIdentityEnvelope.model_validate(payload)
    header = _urlsafe_json({"alg": "HS256", "typ": "JWT"})
    body = _urlsafe_json(payload)
    signing_input = f"{header}.{body}"
    signature = hmac.new(secret.encode(), signing_input.encode("ascii"), hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{signing_input}.{encoded}"


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
            "k": 8,
            "hybrid": True,
            "rerank": True,
            "include_citations": True,
        },
    }


def _normalized_search_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        "".join(
            character for character in decomposed if not unicodedata.combining(character)
        ).split()
    )


def _run_real_http_search_acceptance(product_pg: Mapping[str, str]) -> None:
    assert os.environ["RAG_RERANKER_MODEL_INVENTORY_SHA256"] == (RERANKER_INVENTORY_SHA256)
    assert len(SEARCH_CASES) == TARGET_COLLECTIONS
    assert all(len(cases) == 3 for cases in SEARCH_CASES.values())
    expectation = load_release_expectation(RELEASE_PATH, RELEASE_SHA256)
    expected_artifact_by_sha = {
        artifact.content_sha256: artifact for artifact in expectation.artifacts
    }
    expected_chunk_by_id: dict[str, tuple[Any, Mapping[str, Any]]] = {}
    for artifact in expectation.artifacts:
        for chunk in artifact.chunks:
            chunk_id = str(chunk["chunk_id"])
            assert chunk_id not in expected_chunk_by_id
            expected_chunk_by_id[chunk_id] = (artifact, chunk)

    bff_token = secrets.token_urlsafe(48)
    identity_secret = secrets.token_urlsafe(48)
    token_issuer = "multilevel-http-bff"
    token_audience = "multilevel-rag-engine"
    identity_issuer = "multilevel-nexus-sso"
    identity_audience = "multilevel-nexus-cockpit"
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    release_registry = json.dumps(
        [{"path": str(RELEASE_PATH), "sha256": RELEASE_SHA256}],
        separators=(",", ":"),
    )
    child_env = dict(os.environ)
    child_env.pop("RAG_RELEASE_MANIFEST_PATH", None)
    child_env.pop("RAG_RELEASE_MANIFEST_SHA256", None)
    child_env.pop("RAG_RELEASE_MANIFESTS_JSON", None)
    child_env.update(
        {
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
            "RAG_COLLECTIONS_CONFIG": str(
                ENGINE_ROOT / "configs" / "staging" / "rag_collections_multilevel.yml"
            ),
            "RAG_RELEASE_MANIFESTS_JSON": release_registry,
            "RAG_EMBEDDING_MODEL_CACHE_DIR": str(E5_PATH),
            "RAG_EMBEDDING_MODEL_INVENTORY_SHA256": E5_INVENTORY_SHA256,
            "RAG_RERANKER_MODEL_CACHE_DIR": str(RERANKER_PATH),
            "RAG_RERANKER_MODEL_INVENTORY_SHA256": RERANKER_INVENTORY_SHA256,
            "EMBED_MODEL": CANONICAL_EMBED_MODEL,
            "EMBED_DIM": "1024",
            "CUDA_VISIBLE_DEVICES": "",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
    )
    process_log = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
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
        stderr=process_log,
        text=True,
    )
    stderr = ""
    try:
        deadline = time.monotonic() + 300
        with httpx.Client(base_url=base_url, timeout=120.0) as client:
            while True:
                if process.poll() is not None:
                    pytest.fail("uvicorn exited before multilevel readiness")
                try:
                    health = client.get("/health")
                    if health.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() >= deadline:
                    pytest.fail("uvicorn multilevel readiness deadline exceeded")
                time.sleep(0.25)

            passed = 0
            discovered: set[str] = set()
            collections_seen: set[str] = set()
            headers_by_scope: dict[str, dict[str, str]] = {}
            for scope_id, cases in SEARCH_CASES.items():
                artifact = load_retrieval_scope_artifact(scope_id)
                assert isinstance(artifact, RetrievalScopeArtifactV2)
                expected_collection = artifact.evidence_subject.collection
                token = _identity_token(
                    scope_id,
                    secret=identity_secret,
                    issuer=token_issuer,
                    audience=token_audience,
                    identity_issuer=identity_issuer,
                    identity_audience=identity_audience,
                )
                headers = {
                    "Authorization": f"Bearer {bff_token}",
                    "X-Nexus-Identity": token,
                }
                headers_by_scope[scope_id] = headers
                picker = client.get("/collections/v2", headers=headers)
                assert picker.status_code == 200, (scope_id, picker.text)
                assert [item["name"] for item in picker.json()["collections"]] == [
                    expected_collection
                ]
                readiness = client.get("/collections/readiness", headers=headers)
                assert readiness.status_code == 200, (scope_id, readiness.text)
                ready_rows = readiness.json()["collections"]
                assert len(ready_rows) == 1
                assert ready_rows[0]["name"] == expected_collection
                assert ready_rows[0]["ready"] is True
                collections_seen.add(expected_collection)
                for case in cases:
                    response = client.post(
                        "/search/v2",
                        headers=headers,
                        json=_search_payload(scope_id, case.query),
                    )
                    assert response.status_code == 200, (scope_id, response.text)
                    parsed = RetrievalResponse.model_validate(response.json())
                    assert parsed.results, (scope_id, case.query)
                    for result in parsed.results:
                        expected_artifact, expected_chunk = expected_chunk_by_id[result.chunk_id]
                        metadata = result.metadata
                        citation = result.citation
                        assert metadata.get("collection") == expected_collection
                        assert expected_artifact.collection == expected_collection
                        assert metadata.get("content_sha256") == expected_artifact.content_sha256
                        assert metadata.get("artifact_id") == expected_artifact.content_sha256
                        assert result.doc_id == expected_artifact.content_sha256
                        assert metadata.get("review_status") == "reviewed"
                        assert (
                            metadata.get("placement_source_path") == expected_artifact.source_path
                        )
                        assert citation is not None
                        assert citation.page == expected_chunk["page_start"]
                        assert citation.source_uri == expected_artifact.source_url
                        assert citation.rights == Rights.officiel_public.value
                    returned = {str(result.metadata["content_sha256"]) for result in parsed.results}
                    assert case.expected_artifact_sha256 in returned
                    top_excerpt = _normalized_search_text(parsed.results[0].excerpt)
                    assert any(
                        _normalized_search_text(concept) in top_excerpt
                        for concept in case.expected_concepts_any
                    ), (scope_id, case.query, parsed.results[0].metadata.get("rerank_score"))
                    discovered.add(case.expected_artifact_sha256)
                    passed += 1
            assert len(collections_seen) == TARGET_COLLECTIONS
            assert passed == TARGET_COLLECTIONS * 3

            cross_scope = client.post(
                "/search/v2",
                headers=headers_by_scope["entree_premiere_maths_v2"],
                json=_search_payload(
                    "entree_premiere_francais_v2",
                    SEARCH_CASES["entree_premiere_francais_v2"][0].query,
                ),
            )
            assert cross_scope.status_code == 403

            fr_scope = "entree_premiere_francais_v2"
            fr_token = _identity_token(
                fr_scope,
                secret=identity_secret,
                issuer=token_issuer,
                audience=token_audience,
                identity_issuer=identity_issuer,
                identity_audience=identity_audience,
            )
            probe = client.post(
                "/search/v2",
                headers={
                    "Authorization": f"Bearer {bff_token}",
                    "X-Nexus-Identity": fr_token,
                },
                json=_search_payload(
                    fr_scope,
                    "Comment enseigner explicitement la compréhension de l'écrit ou des écrits en seconde ?",
                ),
            )
            assert probe.status_code == 200, probe.text
            probe_results = RetrievalResponse.model_validate(probe.json()).results
            probe_by_sha = {str(result.metadata.get("content_sha256")) for result in probe_results}
            assert FR_SECONDE_SECOND_ARTIFACT_SHA in probe_by_sha
            for result in probe_results:
                expected_artifact, expected_chunk = expected_chunk_by_id[result.chunk_id]
                citation = result.citation
                assert expected_artifact.collection == "rag_nexus_francais_seconde_tc"
                assert result.metadata.get("collection") == expected_artifact.collection
                assert result.metadata.get("placement_source_path") == expected_artifact.source_path
                assert citation is not None
                assert citation.page == expected_chunk["page_start"]
                assert citation.source_uri == expected_artifact.source_url
                assert citation.rights == Rights.officiel_public.value
            discovered.add(FR_SECONDE_SECOND_ARTIFACT_SHA)
            assert discovered == set(expected_artifact_by_sha)
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=15)
        process_log.flush()
        process_log.seek(0)
        stderr = process_log.read()
        process_log.close()
        if process.returncode not in (0, -15):
            sanitized = "\n".join(stderr.splitlines()[-50:])[:10_000]
            sanitized = sanitized.replace(bff_token, "<redacted>").replace(
                identity_secret, "<redacted>"
            )
            pytest.fail(f"uvicorn multilevel acceptance failed:\n{sanitized}")


def test_multilevel_real_governed_batch_ingestion_and_idempotence(
    control_pg: dict[str, str],
    product_pg: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    request: pytest.FixtureRequest,
) -> None:
    authorities = _build_runtime_authorities()
    profiles = authorities["profiles"]
    expectation = authorities["expectation"]
    manifest_digest = authorities["profile_manifest"].manifest_sha256

    raw_by_url: dict[str, bytes] = {}
    by_collection: dict[str, list[Any]] = defaultdict(list)
    for artifact in expectation.artifacts:
        pdf_path = PDF_MIRROR / artifact.source_path
        raw = pdf_path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == artifact.content_sha256
        raw_by_url[artifact.source_url] = raw
        by_collection[artifact.collection].append(artifact)
    assert len(raw_by_url) == EXPECTED_ARTIFACTS

    storage = tmp_path / "artifacts"

    def fetch(url: str, *, on_destination: Any = None, **_kwargs: Any) -> httpx.Response:
        if on_destination is not None:
            on_destination(url)
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=raw_by_url[url],
            request=httpx.Request("GET", url),
        )

    deps_a = WorkerDeps(
        owner="multilevel-worker-a",
        profile_registry=profiles,
        artifact_store=make_filesystem_artifact_store(storage),
        artifact_reader=make_filesystem_artifact_reader(storage),
        validate_destination=lambda url: url,
        safe_fetch=fetch,
        manifest_digest=manifest_digest,
        pii_evidence_registry=authorities["pii"],
        rights_evidence_registry=authorities["rights"],
        placement_resolver=authorities["resolver"],
    )
    assert deps_a.verify_scope_authorization.__module__.endswith("scope_authority")

    github = LocalGitHub()
    token_path = tmp_path / "github-token"
    token_path.write_text(VALID_TOKEN, encoding="utf-8")
    auth_meta: dict[str, tuple[str, int, str]] = {}
    pub_meta: dict[str, tuple[int, str, str]] = {}
    for index, collection in enumerate(sorted(by_collection), start=1):
        authorization_id = f"multilevel-{index:02d}-scope-v1"
        auth_head = hashlib.sha1(f"auth:{collection}".encode()).hexdigest()
        auth_pr = 9700 + index
        github.add_approved_pr(
            number=auth_pr,
            head_sha=auth_head,
            base_sha="9" * 40,
            review_id=97000 + index,
        )
        profile = profiles[(collection, "multilevel-v1")]
        document = _authorization_document(
            profile=profile,
            manifest_digest=manifest_digest,
            authorization_id=authorization_id,
            allowed_content_sha256=[item.content_sha256 for item in by_collection[collection]],
        )
        github.put_blob(
            path=canonical_authorization_path(authorization_id),
            ref=auth_head,
            content=document.canonical_bytes(),
        )
        auth_meta[collection] = (authorization_id, auth_pr, auth_head)

    for index, artifact in enumerate(expectation.artifacts, start=1):
        pub_head = hashlib.sha1(f"pub:{artifact.content_sha256}".encode()).hexdigest()
        pub_pr = 9800 + index
        review_id = f"multilevel-{index:02d}-publication-v1"
        github.add_approved_pr(
            number=pub_pr,
            head_sha=pub_head,
            base_sha="9" * 40,
            review_id=98000 + index,
            submitted_at="2026-08-12T19:30:00Z",
        )
        pub_meta[artifact.content_sha256] = (pub_pr, pub_head, review_id)

    monkeypatch.setenv("PG_INGESTION_CONTROL_AUTHORITY_DSN", authority_dsn(control_pg))
    monkeypatch.setenv("PG_INGESTION_CONTROL_ATTESTOR_DSN", attestor_dsn(control_pg))
    monkeypatch.delenv("PG_INGESTION_CONTROL_DSN", raising=False)
    monkeypatch.setenv("NEXUS_GITHUB_TOKEN_FILE", str(token_path))
    monkeypatch.delenv("NEXUS_GITHUB_TOKEN", raising=False)

    with local_github_server(github) as base_url:
        monkeypatch.setenv("NEXUS_GITHUB_API_BASE", base_url)
        for collection, (authorization_id, auth_pr, auth_head) in auth_meta.items():
            assert (
                authorize_scope_main(
                    [
                        "record-authorization",
                        "--authorization-id",
                        authorization_id,
                        "--repository",
                        REPOSITORY,
                        "--pull-request",
                        str(auth_pr),
                        "--expected-head",
                        auth_head,
                    ]
                )
                == 0
            ), collection

        with psycopg.connect(app_dsn(control_pg)) as conn:
            run_by_collection = {
                collection: _make_run(conn, profiles[(collection, "multilevel-v1")])
                for collection in sorted(by_collection)
            }
            for artifact in expectation.artifacts:
                profile = profiles[(artifact.collection, "multilevel-v1")]
                authorization_id = auth_meta[artifact.collection][0]
                create_job(
                    conn,
                    run_id=run_by_collection[artifact.collection],
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
                        "scope_authorization_id": authorization_id,
                    },
                )
            conn.commit()
            for _ in range(EXPECTED_PLACEMENTS):
                outcome = run_worker_iteration(conn, deps=deps_a)
                assert outcome.status == "succeeded", outcome.error
                conn.commit()
            assert conn.execute(
                "SELECT COUNT(*) FROM ingestion_control.resources "
                "WHERE resource_state = 'NEEDS_REVIEW'"
            ).fetchone() == (EXPECTED_PLACEMENTS,)
            rows = conn.execute(
                """
                SELECT r.resource_id, a.artifact_id, a.sha256,
                       r.run_id, r.state_version, r.collection
                FROM ingestion_control.resources r
                JOIN ingestion_control.artifacts a USING (resource_id)
                ORDER BY a.artifact_id
                """
            ).fetchall()
        assert len(rows) == EXPECTED_PLACEMENTS

        attested: list[dict[str, Any]] = []
        for (
            resource_id,
            artifact_id,
            content_sha256,
            run_id,
            state_version,
            collection,
        ) in rows:
            authorization_id = auth_meta[collection][0]
            pub_pr, pub_head, review_id = pub_meta[content_sha256]
            capsys.readouterr()
            assert (
                attest_main(
                    [
                        "propose-review",
                        "--resource-id",
                        str(resource_id),
                        "--artifact-id",
                        str(artifact_id),
                        "--scope-authorization-id",
                        authorization_id,
                        "--review-id",
                        review_id,
                    ]
                )
                == 0
            )
            proposal_path, proposal_bytes = _parse_proposal(capsys.readouterr().out)
            github.put_blob(path=proposal_path, ref=pub_head, content=proposal_bytes)
            assert (
                attest_main(
                    [
                        "record-attestation",
                        "--resource-id",
                        str(resource_id),
                        "--artifact-id",
                        str(artifact_id),
                        "--scope-authorization-id",
                        authorization_id,
                        "--review-id",
                        review_id,
                        "--repository",
                        REPOSITORY,
                        "--pull-request",
                        str(pub_pr),
                        "--expected-head",
                        pub_head,
                    ]
                )
                == 0
            )
            with psycopg.connect(superuser_dsn(control_pg)) as check:
                attestation = check.execute(
                    "SELECT attestation_id FROM ingestion_control.publication_attestations "
                    "WHERE resource_id = %s AND invalidated_at IS NULL",
                    (resource_id,),
                ).fetchone()
            assert attestation is not None
            attested.append(
                {
                    "resource_id": resource_id,
                    "artifact_id": artifact_id,
                    "content_sha256": content_sha256,
                    "run_id": run_id,
                    "expected_state_version": state_version,
                    "publication_attestation_id": attestation[0],
                }
            )

    publication_authority = ExitStack()
    request.addfinalizer(publication_authority.close)
    publication_base_url = publication_authority.enter_context(local_github_server(github))
    monkeypatch.setenv("NEXUS_GITHUB_API_BASE", publication_base_url)

    provider = VerifiedE5EmbeddingProvider.from_artifact(
        artifact_root=E5_PATH,
        inventory_sha256=E5_INVENTORY_SHA256,
        pg_dsn=product_pg["admin_dsn"],
    )
    deps_b = PublicationResumeDeps(
        owner="multilevel-worker-b",
        product_dsn=product_pg["publisher_dsn"],
        artifact_reader=deps_a.artifact_reader,
        extract_text=_reject_duplicate_pdf_extraction,
        embedding_provider=provider,
        pii_evidence_registry=authorities["pii"],
        rights_evidence_registry=authorities["rights"],
        manifest_digest=manifest_digest,
        placement_resolver=authorities["resolver"],
    )
    publication_jobs: list[uuid.UUID] = []
    with psycopg.connect(app_dsn(control_pg)) as conn:
        for item in attested:
            publication_jobs.append(
                create_job(
                    conn,
                    run_id=item["run_id"],
                    resource_id=item["resource_id"],
                    job_type="publication_resume",
                    payload={
                        "resource_id": str(item["resource_id"]),
                        "run_id": str(item["run_id"]),
                        "expected_state_version": item["expected_state_version"],
                        "publication_attestation_id": str(item["publication_attestation_id"]),
                    },
                )
            )
        conn.commit()
        for _ in publication_jobs:
            outcome = run_publication_resume_iteration(conn, deps=deps_b, build_placements=None)
            assert outcome.status == "succeeded", outcome.error
            assert outcome.embedded is True
            conn.commit()
        assert conn.execute(
            "SELECT COUNT(*) FROM ingestion_control.resources "
            "WHERE resource_state = 'RETRIEVAL_ELIGIBLE'"
        ).fetchone() == (EXPECTED_PLACEMENTS,)

    with psycopg.connect(product_pg["admin_dsn"]) as conn:
        report = validate_release_readiness(RELEASE_PATH, RELEASE_SHA256, conn)
        assert report.ready, report.blockers
        before = conn.execute(
            "SELECT (SELECT COUNT(*) FROM rag_artifacts), "
            "(SELECT COUNT(*) FROM rag_artifact_placements), "
            "(SELECT COUNT(*) FROM rag_chunks), "
            "(SELECT COUNT(*) FROM rag_chunks WHERE vector IS NOT NULL)"
        ).fetchone()
        assert before == (
            EXPECTED_ARTIFACTS,
            EXPECTED_PLACEMENTS,
            EXPECTED_CHUNKS,
            EXPECTED_CHUNKS,
        )
        assert conn.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE model <> %s OR vector_dims(vector) <> 1024",
            (CANONICAL_EMBED_MODEL,),
        ).fetchone() == (0,)

    with psycopg.connect(app_dsn(control_pg)) as conn:
        assert (
            conn.execute(
                "UPDATE ingestion_control.jobs SET status = 'queued', "
                "next_attempt_at = now(), updated_at = now() "
                "WHERE job_id = ANY(%s) AND status = 'succeeded'",
                (publication_jobs,),
            ).rowcount
            == EXPECTED_PLACEMENTS
        )
        conn.commit()
        for _ in publication_jobs:
            replay = run_publication_resume_iteration(conn, deps=deps_b, build_placements=None)
            assert replay.status == "succeeded", replay.error
            assert replay.embedded is False
            conn.commit()

    with psycopg.connect(product_pg["admin_dsn"]) as conn:
        after = conn.execute(
            "SELECT (SELECT COUNT(*) FROM rag_artifacts), "
            "(SELECT COUNT(*) FROM rag_artifact_placements), "
            "(SELECT COUNT(*) FROM rag_chunks), "
            "(SELECT COUNT(*) FROM rag_chunks WHERE vector IS NOT NULL)"
        ).fetchone()
        assert after == before
        assert conn.execute(
            "SELECT COUNT(*) FROM (SELECT artifact_id FROM rag_artifacts "
            "GROUP BY artifact_id HAVING COUNT(*) > 1) duplicate"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT COUNT(*) FROM (SELECT placement_id FROM rag_artifact_placements "
            "GROUP BY placement_id HAVING COUNT(*) > 1) duplicate"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT COUNT(*) FROM (SELECT chunk_id FROM rag_chunks "
            "GROUP BY chunk_id HAVING COUNT(*) > 1) duplicate"
        ).fetchone() == (0,)

    _run_real_http_search_acceptance(product_pg)
