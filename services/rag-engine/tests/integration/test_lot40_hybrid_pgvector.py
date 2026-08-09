"""Preuves LOT40 sur une base PostgreSQL/pgvector ephemere reelle."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nexus_contracts import Candidat, Niveau, Rights, Voie, load_pilot_retrieval_scope
from nexus_contracts.ingestion import ResourceScope
from psycopg import sql
from psycopg.conninfo import make_conninfo

from ingestor import api_v2 as runtime_api
from ingestor import governed_publisher_v2 as publisher
from ingestor import retrieval_v2_endpoint as endpoint
from ingestor import review_v2_endpoint as review_endpoint
from ingestor.identity_v2 import load_identity_verifier_config, verify_identity_token
from ingestor.ingestion_control.publication_attestation import VerifiedAttestation
from ingestor.ingestion_control.publication_evidence import PublicationFacts
from ingestor.ingestion_control.scope_authority import VerifiedAuthorization
from ingestor.pg_pool import PoolSettings, close_pool, pool_connection
from ingestor.readiness_db import postgres_database_authorities_share_instance
from ingestor.retrieval_hybrid_v2 import (
    EMBED_DIMENSION,
    RetrievalPipelineError,
    retrieve_hybrid,
)
from ingestor.retrieval_pg_v2 import (
    _DENSE_ANN_POOL_LIMIT,
    _DENSE_ANN_PROBE_LIMIT,
    _DENSE_SQL,
    _LEXICAL_SQL,
    PgCandidateStore,
)
from ingestor.retrieval_readiness_v2 import retrieval_database_ready
from ingestor.retrieval_scope_v2 import ServerRetrievalScope
from ingestor.review_readiness_v2 import review_database_ready
from ingestor.schema_readiness_v2 import schema_head_004_ready

pytestmark = pytest.mark.integration

APP_DSN = os.environ.get("LOT40_PG_DSN", "").strip()
ADMIN_DSN = os.environ.get("LOT40_PG_ADMIN_DSN", "").strip()
REVIEW_DSN = os.environ.get("LOT41_PG_REVIEW_DSN", "").strip()
PUBLISHER_DSN = os.environ.get("LOT42_PG_PUBLISHER_DSN", "").strip()
if not APP_DSN or not ADMIN_DSN or not REVIEW_DSN or not PUBLISHER_DSN:
    pytest.skip(
        "DSN applicatif, admin, review et publisher requis par le runner ephemere",
        allow_module_level=True,
    )

SERVICE_ROOT = Path(__file__).resolve().parents[2]
TARGET_COLLECTION = "lot40_target"
TIE_COLLECTION = "lot40_ties"
OVERFLOW_TIE_COLLECTION = "lot40_ties_overflow"
SMALL_COLLECTION = "lot40_small"
MATRIX_COLLECTIONS = {
    "maths": "rag_nexus_maths_terminale_gen_specialite",
    "nsi": "rag_nexus_nsi_terminale_specialite",
}
MATRIX_CANDIDATES = ("individuel", "libre", "cned_libre")
TARGET_SCALE = 45000
QUERY = "algorithme graphe"
QUERY_VECTOR = (1.0,) + (0.0,) * (EMBED_DIMENSION - 1)
QUERY_VECTOR_TEXT = "[" + ",".join(str(value) for value in QUERY_VECTOR) + "]"
TENANT = "libre_terminale"
VOIE = "generale"
STATUT_ENSEIGNEMENT = "specialite"
CANDIDAT = "individuel"
AUDIENCE = ["tous"]
VISIBILITY = "internal"
SCHOOL_YEAR = "2026-2027"
PROGRAMME_VERSION = "BOEN_special_8_2019-07-25"
INTERNAL_TOKEN_SECRET = "lot41-integration-internal-secret-32-bytes"
INTERNAL_TOKEN_ISSUER = "lot41-integration-cockpit"
INTERNAL_TOKEN_AUDIENCE = "lot41-integration-engine"
SSO_ISSUER = "lot41-integration-sso"
SSO_AUDIENCE = "lot41-integration-cockpit-audience"

ROLLBACK_004 = (
    SERVICE_ROOT
    / "infra"
    / "postgres"
    / "rollbacks"
    / "004_artifact_placements.down.sql"
)
MIGRATIONS = SERVICE_ROOT / "infra" / "postgres" / "migrations"


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _signed_identity_token(
    *,
    candidat: str = CANDIDAT,
    matieres: tuple[str, ...] = ("maths", "nsi"),
) -> str:
    artifact = load_pilot_retrieval_scope()
    now = int(time.time())
    identity = {
        "aud": SSO_AUDIENCE,
        "exp": now + 600,
        "iss": SSO_ISSUER,
        "jti": "lot41-e2e-jti",
        "tenant": TENANT,
        "niveau": "terminale",
        "role": "admin",
        "school_year": SCHOOL_YEAR,
        "sub": "psn_lot41integration0001",
        "pedagogical_profile": {
            "voie": VOIE,
            "matieres": list(matieres),
            "statut_enseignement": STATUT_ENSEIGNEMENT,
            "candidat": candidat,
            "audience": "libre",
        },
    }
    payload = {
        "protocol_version": "1",
        "iss": INTERNAL_TOKEN_ISSUER,
        "aud": INTERNAL_TOKEN_AUDIENCE,
        "sub": identity["sub"],
        "jti": identity["jti"],
        "iat": now,
        "exp": now + 300,
        "identity": identity,
        "scope_id": artifact.scope_id,
        "scope_digest": artifact.sha256_digest(),
        "allowed_collections": [subject.collection for subject in artifact.subjects],
    }
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url(json.dumps(payload).encode())
    signed = f"{header}.{body}"
    signature = hmac.new(
        INTERNAL_TOKEN_SECRET.encode(),
        signed.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signed}.{_b64url(signature)}"


def _scope(
    collection: str,
    *,
    candidat: str = CANDIDAT,
    matiere: str = "nsi",
) -> ServerRetrievalScope:
    return ServerRetrievalScope(
        tenant=TENANT,
        niveau="terminale",
        voie=VOIE,
        matiere=matiere,
        statut_enseignement=STATUT_ENSEIGNEMENT,
        candidat=candidat,
        audiences=("libre", "tous"),
        rights=(Rights.usage_interne,),
        visibilities=(VISIBILITY,),
        school_year=SCHOOL_YEAR,
        collection=collection,
        programme_version=PROGRAMME_VERSION,
        scope_id="lot41_integration_scope",
        scope_digest="a" * 64,
        source_sha256="b" * 64,
    )


def _governed_placement(
    *, collection: str, source_suffix: str
) -> publisher.EligiblePlacement:
    return publisher.EligiblePlacement(
        resource_id=uuid4(),
        scope=ResourceScope(
            tenant=TENANT,
            collection=collection,
            niveau=Niveau.terminale,
            voie=Voie.generale,
            matiere="nsi",
            candidat=Candidat.individuel,
            audience=["tous"],
            visibility=VISIBILITY,
            school_year=SCHOOL_YEAR,
            programme_version=PROGRAMME_VERSION,
        ),
        statut_enseignement=STATUT_ENSEIGNEMENT,
        domain="lycee",
        source_scope=f"01_EDUSCOL_OFFICIEL/terminale/nsi/{source_suffix}",
        source_placement_id=f"eduscol:governed:{source_suffix}",
        source_path=f"01_EDUSCOL_OFFICIEL/nsi/{source_suffix}.pdf",
        source_uri=f"https://eduscol.education.gouv.fr/{source_suffix}",
        current_profile_fingerprint="c" * 64,
        current_manifest_digest="d" * 64,
    )


def _verified_publication(
    artifact: publisher.GovernedArtifact,
    placement: publisher.EligiblePlacement,
) -> VerifiedAttestation:
    now = datetime.now(UTC)
    authorization = VerifiedAuthorization(
        authorization_id=f"AUTH-H2C-{placement.resource_id.hex}",
        scope=placement.scope,
        manifest_digest=placement.current_manifest_digest,
        profile_id="h2-initial-governed-profile",
        profile_version="1.0.0",
        profile_fingerprint=placement.current_profile_fingerprint,
        allowed_domains=("eduscol.education.fr",),
        rights_categories=(Rights.usage_interne.value,),
        exclusions=(),
        pii_absence_attested=True,
        valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(hours=1),
        artifact_path=(
            "governance/authorizations/"
            f"AUTH-H2C-{placement.resource_id.hex}.json"
        ),
        artifact_blob_sha="e" * 40,
        authorization_digest="f" * 64,
        evidence_repository="cyranoaladin/RAG",
        evidence_pull_request=999_041,
        evidence_base_sha="1" * 40,
        evidence_head_sha="2" * 40,
        evidence_review_id=999_042,
        evidence_reviewer="staging-human-reviewer",
        evidence_challenge="LOT41V:" + "3" * 64,
        verified_at=now,
        protocol_version="LOT41A-V2",
        allowed_content_sha256=(artifact.content_sha256,),
    )
    facts = PublicationFacts(
        resource_id=placement.resource_id,
        artifact_id=uuid4(),
        collection=str(placement.scope.collection),
        canonical_url=placement.source_uri,
        content_sha256=artifact.content_sha256,
        content_event_id=uuid4(),
        content_scope_authorization_id=authorization.authorization_id,
        content_scope_authorization_digest=authorization.authorization_digest,
        content_scope_authorization_protocol_version=authorization.protocol_version,
        rights_status=Rights.usage_interne,
        rights_assessed_at=now,
        rights_event_id=uuid4(),
        quality_passed=True,
        quality_report_digest="4" * 64,
        quality_assessed_at=now,
        quality_event_id=uuid4(),
        gate_passed=True,
        gate_name="h2_governed_publication",
        gate_evaluated_at=now,
        gate_event_id=uuid4(),
    )
    return VerifiedAttestation(
        attestation_id=uuid4(),
        resource_id=placement.resource_id,
        artifact_id=facts.artifact_id,
        content_sha256=artifact.content_sha256,
        scope_authorization_id=authorization.authorization_id,
        profile_fingerprint=placement.current_profile_fingerprint,
        manifest_digest=placement.current_manifest_digest,
        review_id=f"LOT42-H2C-{placement.resource_id.hex}",
        attestation_digest="5" * 64,
        authorization=authorization,
        facts=facts,
    )


def _retrieval_request_payload(
    *,
    matiere: str = "nsi",
    query: str = QUERY,
    k: int = 5,
) -> dict[str, object]:
    return {
        "student_profile": {
            "niveau": "terminale",
            "voie": VOIE,
            "matieres": [matiere],
            "statut_enseignement": STATUT_ENSEIGNEMENT,
            "candidat": CANDIDAT,
            "school_year": SCHOOL_YEAR,
            "zone": "libre",
        },
        "need": {"intent": "context", "query": query},
        "retrieval": {
            "k": k,
            "hybrid": True,
            "rerank": True,
            "include_citations": True,
        },
    }


def test_rollback_004_rechecks_after_a_concurrent_writer_commits() -> None:
    """La garde de données doit observer une écriture arrivée pendant le rollback.

    La base dédiée permet de rejouer le vrai SQL destructif dans une
    transaction finalement rollbackée, sans perturber les autres preuves du
    runner. Le writer garde un RowExclusive non committé ; le rollback doit
    demander ACCESS EXCLUSIVE *avant* sa garde, attendre, puis refuser après
    le commit du writer. Sans ce verrou initial, la garde passe sur un
    snapshot vide et le DROP réussit après le commit concurrent.
    """
    database = f"h2_rollback_{uuid4().hex}"
    database_dsn = make_conninfo(ADMIN_DSN, dbname=database)
    rollback_sql = ROLLBACK_004.read_text(encoding="utf-8")
    writer: psycopg.Connection[Any] | None = None
    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        with psycopg.connect(database_dsn, autocommit=True) as setup:
            for version in range(1, 5):
                migration = next(MIGRATIONS.glob(f"{version:03d}_*.sql"))
                setup.execute(migration.read_text(encoding="utf-8"))

        writer = psycopg.connect(database_dsn)
        writer.execute(
            """
            INSERT INTO public.rag_artifacts (
                artifact_id, content_sha256, source_label, source_uri,
                rights, official, source_kind, type_doc, ingestion_artifact_id
            ) VALUES (%s, %s, 'rollback concurrency', 'urn:h2:rollback',
                      'internal', true, 'test', 'test', %s)
            """,
            ("a" * 64, "a" * 64, uuid4()),
        )

        outcome: dict[str, object] = {}
        rollback_started = threading.Event()

        def execute_rollback() -> None:
            with psycopg.connect(database_dsn) as connection:
                try:
                    rollback_started.set()
                    connection.execute(rollback_sql)
                    outcome["completed"] = True
                except BaseException as error:  # résultat inspecté par le thread principal
                    outcome["error"] = error
                finally:
                    connection.rollback()

        rollback_thread = threading.Thread(target=execute_rollback, daemon=True)
        rollback_thread.start()
        assert rollback_started.wait(timeout=5)

        queued = False
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with psycopg.connect(database_dsn, autocommit=True) as observer:
                row = observer.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_locks
                        WHERE relation = 'public.rag_artifacts'::regclass
                          AND mode = 'AccessExclusiveLock'
                          AND NOT granted
                    )
                    """
                ).fetchone()
            if row == (True,):
                queued = True
                break
            time.sleep(0.05)
        assert queued, "rollback never queued ACCESS EXCLUSIVE on rag_artifacts"

        writer.commit()
        rollback_thread.join(timeout=10)
        assert not rollback_thread.is_alive()
        error = outcome.get("error")
        assert isinstance(error, psycopg.errors.RaiseException)
        assert "ROLLBACK_004_DATA_PRESENT" in str(error)
        assert "completed" not in outcome

        with psycopg.connect(database_dsn, autocommit=True) as observer:
            assert observer.execute(
                "SELECT COUNT(*) FROM public.rag_artifacts WHERE artifact_id = %s",
                ("a" * 64,),
            ).fetchone() == (1,)
            observer.execute(
                "DELETE FROM public.rag_artifacts WHERE artifact_id = %s",
                ("a" * 64,),
            )
        print("ROLLBACK_004_CONCURRENT_WRITER_REFUSED=PASS")
    finally:
        if writer is not None:
            writer.close()
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database,),
            )
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database)))


def _scope_sql_params(collection: str) -> tuple[object, ...]:
    scope = _scope(collection)
    legacy = (
        scope.collection,
        scope.tenant,
        scope.niveau,
        scope.voie,
        scope.matiere,
        scope.statut_enseignement,
        [scope.candidat, "both"],
        list(scope.audiences),
        [right.value for right in scope.rights],
        list(scope.visibilities),
        scope.school_year,
        scope.programme_version,
    )
    placement = (
        scope.collection,
        scope.tenant,
        scope.niveau,
        scope.voie,
        scope.matiere,
        scope.statut_enseignement,
        [scope.candidat, "both"],
        list(scope.audiences),
        list(scope.visibilities),
        scope.school_year,
        scope.programme_version,
    )
    return (*placement, *legacy, [right.value for right in scope.rights])


def _legacy_scope_sql_params(collection: str) -> tuple[object, ...]:
    scope = _scope(collection)
    return (
        scope.collection,
        scope.tenant,
        scope.niveau,
        scope.voie,
        scope.matiere,
        scope.statut_enseignement,
        [scope.candidat, "both"],
        list(scope.audiences),
        [right.value for right in scope.rights],
        list(scope.visibilities),
        scope.school_year,
        scope.programme_version,
    )


def _placement_scope_sql_params(collection: str) -> tuple[object, ...]:
    scope = _scope(collection)
    return (
        scope.collection,
        scope.tenant,
        scope.niveau,
        scope.voie,
        scope.matiere,
        scope.statut_enseignement,
        [scope.candidat, "both"],
        list(scope.audiences),
        list(scope.visibilities),
        scope.school_year,
        scope.programme_version,
    )


def _dense_filter_sql_params(collection: str) -> tuple[object, ...]:
    scope = _scope(collection)
    placement = _placement_scope_sql_params(collection)
    rights = [right.value for right in scope.rights]
    return (*_legacy_scope_sql_params(collection), *placement, rights)


_DENSE_ORACLE_SQL = """
    SELECT chunk_id
    FROM rag_chunks
    WHERE collection = %s
      AND tenant = %s
      AND niveau = %s
      AND voie IS NOT DISTINCT FROM %s
      AND matiere = %s
      AND statut_enseignement = %s
      AND candidat = ANY(%s::text[])
      AND audience && %s::text[]
      AND rights = ANY(%s::text[])
      AND visibility = ANY(%s::text[])
      AND school_year = %s
      AND programme_version = %s
      AND review_status = 'reviewed'
      AND text IS NOT NULL AND btrim(text) <> '' AND vector IS NOT NULL
      AND btrim(source_label) <> '' AND btrim(source_uri) <> ''
      AND btrim(rights) <> ''
    ORDER BY vector <=> %s::vector ASC, chunk_id ASC
    LIMIT 50
"""

def _vector(first: float, second: float = 0.0) -> str:
    values = (first, second) + (0.0,) * (EMBED_DIMENSION - 2)
    return "[" + ",".join(f"{value:.12g}" for value in values) + "]"


def _unit_vector(angle: float) -> str:
    return _vector(math.cos(angle), math.sin(angle))


def _row(
    chunk_id: str,
    *,
    collection: str,
    vector: str,
    text: str,
    review_status: str = "reviewed",
    doc_id: str | None = None,
    source_label: str = "Preuve LOT40",
    source_uri: str = "https://example.invalid/lot40",
    rights: str = "usage_interne",
    page_start: int | None = 1,
    tenant: str = TENANT,
    niveau: str = "terminale",
    voie: str = VOIE,
    matiere: str = "nsi",
    statut_enseignement: str = STATUT_ENSEIGNEMENT,
    candidat: str = "both",
    audience: list[str] | None = None,
    visibility: str = VISIBILITY,
    school_year: str = SCHOOL_YEAR,
    programme_version: str = PROGRAMME_VERSION,
) -> tuple[object, ...]:
    return (
        chunk_id,
        doc_id or f"doc-{chunk_id}",
        hashlib.sha256(chunk_id.encode()).hexdigest(),
        vector,
        collection,
        niveau,
        voie,
        matiere,
        statut_enseignement,
        candidat,
        audience or AUDIENCE,
        tenant,
        visibility,
        school_year,
        programme_version,
        source_label,
        source_uri,
        rights,
        "cours",
        text,
        0,
        page_start,
        page_start,
        review_status,
    )


def _seed_rows() -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for index in range(80):
        rows.append(
            _row(
                f"target-{index:03d}",
                collection=TARGET_COLLECTION,
                vector=_unit_vector(0.002 + index * 0.002),
                text=f"algorithme graphe preuve pedagogique ordinal {index:03d}",
                doc_id="doc-shared" if index in {0, 1} else None,
                page_start=0 if index == 0 else index + 1,
            )
        )
    rows.extend(
        [
            _row(
                "target-dense-only",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="contenu vectoriel distinct sans terme de recherche",
                page_start=0,
            ),
            _row(
                "target-lexical-only",
                collection=TARGET_COLLECTION,
                vector=_vector(-1.0),
                text="algorithme graphe algorithme graphe algorithme graphe",
                page_start=7,
            ),
        ]
    )
    rows.extend(
        [
            _row(
                "scope-canary-tenant",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe canari tenant",
                tenant="aefe_terminale",
            ),
            _row(
                "scope-canary-niveau",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe canari niveau",
                niveau="premiere",
            ),
            _row(
                "scope-canary-voie",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe canari voie",
                voie="technologique",
            ),
            _row(
                "scope-canary-matiere",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe canari matiere",
                matiere="mathematiques",
            ),
            _row(
                "scope-canary-statut",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe canari statut",
                statut_enseignement="option",
            ),
            _row(
                "scope-canary-candidat",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe canari candidat",
                candidat="scolarise",
            ),
            _row(
                "scope-canary-audience",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe canari audience",
                audience=["aefe"],
            ),
            _row(
                "scope-canary-rights",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe canari droits",
                rights=Rights.officiel_public.value,
            ),
            _row(
                "scope-canary-visibility",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe canari visibilite",
                visibility="public",
            ),
            _row(
                "scope-canary-school-year",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe canari annee",
                school_year="2025-2026",
            ),
            _row(
                "scope-canary-programme",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe canari programme",
                programme_version="version-invalide-pour-le-scope",
            ),
            _row(
                "review-idor-outside",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe cible IDOR hors tenant",
                review_status="needs_review",
                tenant="aefe_terminale",
            ),
        ]
    )

    for index in range(120):
        rows.append(
            _row(
                f"outside-{index:03d}",
                collection="lot40_outside",
                vector=_unit_vector(index * 0.000001),
                text="algorithme graphe hors collection",
            )
        )
    for index in range(80):
        rows.append(
            _row(
                f"pending-{index:03d}",
                collection=TARGET_COLLECTION,
                vector=_unit_vector(index * 0.000001),
                text="algorithme graphe non revu",
                review_status="needs_review",
            )
        )
    rows.extend(
        [
            _row(
                "incomplete-label",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe",
                source_label=" ",
            ),
            _row(
                "incomplete-uri",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe",
                source_uri=" ",
            ),
            _row(
                "incomplete-rights",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe",
                rights=" ",
            ),
        ]
    )
    for index in range(52):
        rows.append(
            _row(
                f"tie-{index:03d}",
                collection=TIE_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe egalite complete",
            )
        )
    for index in range(_DENSE_ANN_PROBE_LIMIT + 4):
        rows.append(
            _row(
                f"overflow-tie-{index:03d}",
                collection=OVERFLOW_TIE_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe egalite au dela du pool ann",
            )
        )
    for index in range(3):
        rows.append(
            _row(
                f"small-{index:03d}",
                collection=SMALL_COLLECTION,
                vector=_unit_vector(index * 0.01),
                text="algorithme graphe petit corpus",
            )
        )
    for matiere, collection in MATRIX_COLLECTIONS.items():
        for candidat in MATRIX_CANDIDATES:
            rows.append(
                _row(
                    f"matrix-{matiere}-{candidat}",
                    collection=collection,
                    vector=_vector(1.0),
                    text="algorithme graphe matrice scope pedagogique",
                    matiere=matiere,
                    candidat=candidat,
                )
            )
    return rows


@pytest.fixture(scope="module", autouse=True)
def seeded_database() -> Iterator[None]:
    rows = _seed_rows()
    with psycopg.connect(ADMIN_DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "TRUNCATE TABLE rag_chunks, rag_artifact_placements, rag_artifacts"
            )
            cursor.executemany(
                """
                INSERT INTO rag_chunks (
                    chunk_id, doc_id, chunk_sha256, vector, collection, niveau,
                    voie, matiere, statut_enseignement, candidat, audience,
                    tenant, visibility, school_year, programme_version,
                    source_label, source_uri, rights, type_doc, text, chunk_index,
                    page_start, page_end, review_status
                ) VALUES (
                    %s, %s, %s, %s::vector, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                rows,
            )
            cursor.execute(
                """
                INSERT INTO rag_chunks (
                    chunk_id, doc_id, chunk_sha256, vector, collection, niveau,
                    voie, matiere, statut_enseignement, candidat, audience,
                    tenant, visibility, school_year, programme_version,
                    source_label, source_uri, rights, type_doc, text, chunk_index,
                    page_start, page_end, review_status
                )
                SELECT
                    prefix || '-' || lpad(series::text, 6, '0'),
                    'doc-' || prefix || '-' || series,
                    md5(prefix || series::text) || md5('b' || prefix || series::text),
                    ((ARRAY[cos(base_angle + series * angle_step),
                            sin(base_angle + series * angle_step)]::real[]
                      || array_fill(0::real, ARRAY[1022])))::vector,
                    collection, 'terminale', 'generale', 'nsi', 'specialite',
                    'both', ARRAY['tous']::text[], 'libre_terminale', 'internal',
                    '2026-2027', 'BOEN_special_8_2019-07-25', 'Preuve LOT40',
                    'https://example.invalid/lot40', 'usage_interne', 'cours',
                    'algorithme graphe preuve pedagogique de charge',
                    0, 1, 1, review_status
                FROM (
                    VALUES
                      ('target-bulk', 'lot40_target', 'reviewed', 0.4::float8,
                       0.00001::float8, 80, %s - 1),
                      ('outside-bulk', 'lot40_outside', 'reviewed', 0.0::float8,
                       0.000001::float8, 120, (%s * 15 / 100) - 1),
                      ('pending-bulk', 'lot40_target', 'needs_review', 0.0::float8,
                       0.000001::float8, 80, (%s * 10 / 100) - 1)
                ) AS fixture(
                    prefix, collection, review_status, base_angle, angle_step,
                    first_series, last_series
                )
                CROSS JOIN LATERAL generate_series(first_series, last_series) AS generated(series)
                """,
                (TARGET_SCALE, TARGET_SCALE, TARGET_SCALE),
            )
            cursor.execute("ANALYZE rag_chunks")
    yield
    with psycopg.connect(ADMIN_DSN) as connection:
        connection.execute(
            "TRUNCATE TABLE rag_chunks, rag_artifact_placements, rag_artifacts"
        )


@contextmanager
def _app_store_connection() -> Iterator[psycopg.Connection[Any]]:
    """Connexion applicative brute; seul le store active pgvector et strict_order."""

    with psycopg.connect(APP_DSN) as connection:
        yield connection


@contextmanager
def _exact_store_connection() -> Iterator[psycopg.Connection[Any]]:
    """Connexion séquentielle réservée à l'oracle dense exact."""

    with psycopg.connect(APP_DSN) as connection:
        with connection.cursor() as cursor:
            # Une égalité de préfixe est une propriété d'oracle exact, pas une
            # garantie d'un index HNSW approximatif. Les propriétés HNSW sont
            # prouvées séparément par leurs plans et leurs bornes ci-dessous.
            cursor.execute("SET LOCAL enable_indexscan = off")
            cursor.execute("SET LOCAL enable_bitmapscan = off")
        yield connection


@contextmanager
def _underfill_store_connection() -> Iterator[psycopg.Connection[Any]]:
    """Connexion réglée exclusivement pour provoquer un underfill HNSW borné."""

    with psycopg.connect(APP_DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL hnsw.ef_search = 1")
            cursor.execute("SET LOCAL hnsw.max_scan_tuples = 1")
        yield connection


def _plan_lines(
    connection: psycopg.Connection[Any],
    sql: str,
    params: Sequence[object],
) -> str:
    with connection.cursor() as cursor:
        cursor.execute("EXPLAIN (ANALYZE, COSTS OFF, SUMMARY OFF) " + sql, params)
        return "\n".join(str(row[0]) for row in cursor.fetchall())


def _plan_json(
    connection: psycopg.Connection[Any],
    sql: str,
    params: Sequence[object],
) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params)
        payload = cursor.fetchone()[0]
    assert isinstance(payload, list) and len(payload) == 1
    assert isinstance(payload[0], dict)
    return payload[0]


def _plan_nodes(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield node
    for child in node.get("Plans", []):
        assert isinstance(child, dict)
        yield from _plan_nodes(child)


def _assert_bounded_hnsw_json_plan(plan_payload: dict[str, Any]) -> None:
    nodes = list(_plan_nodes(plan_payload["Plan"]))
    rag_scans = [node for node in nodes if node.get("Relation Name") == "rag_chunks"]
    assert len(rag_scans) == 1, rag_scans
    assert rag_scans[0].get("Node Type") == "Index Scan", rag_scans[0]
    assert rag_scans[0].get("Index Name") == "idx_rag_chunks_vector", rag_scans[0]
    cte_nodes = [
        node
        for node in nodes
        if str(node.get("Subplan Name", "")).endswith("hnsw_candidates")
    ]
    assert len(cte_nodes) == 1, cte_nodes
    assert int(cte_nodes[0]["Actual Rows"]) <= _DENSE_ANN_PROBE_LIMIT
    sort_nodes = [node for node in nodes if node.get("Node Type") == "Sort"]
    assert sort_nodes
    assert max(int(node["Actual Rows"]) for node in sort_nodes) <= _DENSE_ANN_PROBE_LIMIT
    assert any(any(str(key).endswith("Blocks") for key in node) for node in nodes)


def _assert_gin_plan(connection: psycopg.Connection[Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL enable_seqscan = off")
    plan = _plan_lines(
        connection,
        _LEXICAL_SQL,
        (QUERY, *_scope_sql_params(TARGET_COLLECTION), 50),
    )
    if "idx_rag_chunks_text_tsv" not in plan:
        raise AssertionError(plan)


def _assert_ids(actual: Sequence[str], expected: Sequence[str]) -> None:
    if list(actual) != list(expected):
        raise AssertionError(f"ordre inattendu: {list(actual)!r}")


def _dense_params(collection: str) -> tuple[object, ...]:
    return (
        QUERY_VECTOR_TEXT,
        *_dense_filter_sql_params(collection),
        _DENSE_ANN_PROBE_LIMIT,
        *_placement_scope_sql_params(collection),
        _DENSE_ANN_POOL_LIMIT,
        _DENSE_ANN_PROBE_LIMIT,
        50,
    )


def test_application_role_is_non_superuser_and_select_only() -> None:
    with psycopg.connect(APP_DSN, autocommit=True) as connection:
        role = connection.execute(
            """
            SELECT current_user, rolsuper, rolcreatedb, rolcreaterole,
                   rolreplication, rolbypassrls
            FROM pg_roles
            WHERE rolname = current_user
            """
        ).fetchone()
        assert role == ("lot40_app", False, False, False, False, False)
        privileges = connection.execute(
            """
            SELECT
              has_database_privilege(current_user, current_database(), 'CONNECT'),
              has_database_privilege(current_user, current_database(), 'CREATE'),
              has_database_privilege(current_user, current_database(), 'TEMP'),
              has_schema_privilege(current_user, 'public', 'USAGE'),
              has_schema_privilege(current_user, 'public', 'CREATE'),
              has_table_privilege(current_user, 'public.rag_chunks', 'SELECT'),
              has_table_privilege(current_user, 'public.rag_chunks', 'INSERT'),
              has_table_privilege(current_user, 'public.rag_chunks', 'UPDATE'),
              has_table_privilege(current_user, 'public.rag_chunks', 'DELETE'),
              has_table_privilege(current_user, 'public.rag_chunks', 'TRUNCATE'),
              has_table_privilege(current_user, 'public.rag_chunks', 'REFERENCES'),
              has_table_privilege(current_user, 'public.rag_chunks', 'TRIGGER'),
              pg_has_role(current_user, tableowner, 'USAGE')
            FROM pg_tables
            WHERE schemaname = 'public' AND tablename = 'rag_chunks'
            """
        ).fetchone()
        assert privileges == (
            True,
            False,
            False,
            True,
            False,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
        )
        governed_privileges = connection.execute(
            """
            SELECT
              has_table_privilege(
                  current_user, 'public.rag_artifacts', 'SELECT'
              ),
              has_table_privilege(
                  current_user, 'public.rag_artifacts', 'INSERT'
              ),
              has_table_privilege(
                  current_user, 'public.rag_artifacts', 'UPDATE'
              ),
              has_table_privilege(
                  current_user, 'public.rag_artifact_placements', 'SELECT'
              ),
              has_table_privilege(
                  current_user, 'public.rag_artifact_placements', 'INSERT'
              ),
              has_table_privilege(
                  current_user, 'public.rag_artifact_placements', 'UPDATE'
              )
            """
        ).fetchone()
        assert governed_privileges == (True, False, False, True, False, False)
    print("APP_ROLE_NON_SUPERUSER_SELECT_ONLY=PASS")


def test_runtime_roles_share_the_same_live_database_instance() -> None:
    assert postgres_database_authorities_share_instance(APP_DSN, REVIEW_DSN) is True
    print("RUNTIME_AUTHORITIES_SHARED_LIVE_INSTANCE=PASS")


def test_review_role_can_only_select_and_update_review_status() -> None:
    with psycopg.connect(REVIEW_DSN, autocommit=True) as connection:
        role = connection.execute(
            """
            SELECT current_user, rolsuper, rolcreatedb, rolcreaterole,
                   rolreplication, rolbypassrls
            FROM pg_roles
            WHERE rolname = current_user
            """
        ).fetchone()
        assert role == ("lot41_review", False, False, False, False, False)
        privileges = connection.execute(
            """
            SELECT
              has_table_privilege(current_user, 'public.rag_chunks', 'SELECT'),
              has_table_privilege(current_user, 'public.rag_chunks', 'INSERT'),
              has_table_privilege(current_user, 'public.rag_chunks', 'DELETE'),
              has_table_privilege(current_user, 'public.rag_chunks', 'TRUNCATE'),
              has_column_privilege(
                  current_user, 'public.rag_chunks', 'review_status', 'UPDATE'
              ),
              has_column_privilege(
                  current_user, 'public.rag_chunks', 'text', 'UPDATE'
              ),
              pg_has_role(current_user, tableowner, 'USAGE')
            FROM pg_tables
            WHERE schemaname = 'public' AND tablename = 'rag_chunks'
            """
        ).fetchone()
        assert privileges == (True, False, False, False, True, False, False)
        governed_writes = connection.execute(
            """
            SELECT
              has_table_privilege(
                  current_user, 'public.rag_artifacts', 'INSERT'
              ),
              has_table_privilege(
                  current_user, 'public.rag_artifact_placements', 'INSERT'
              ),
              has_table_privilege(
                  current_user, 'public.rag_artifacts', 'UPDATE'
              ),
              has_table_privilege(
                  current_user, 'public.rag_artifact_placements', 'UPDATE'
              )
            """
        ).fetchone()
        assert governed_writes == (False, False, False, False)
    assert review_database_ready(REVIEW_DSN) is True
    print("REVIEW_ROLE_COLUMN_LEVEL_UPDATE_ONLY=PASS")


def test_publisher_role_is_insert_only_on_product_relations() -> None:
    with psycopg.connect(PUBLISHER_DSN, autocommit=True) as connection:
        role = connection.execute(
            """
            SELECT current_user, rolsuper, rolcreatedb, rolcreaterole,
                   rolreplication, rolbypassrls
            FROM pg_roles
            WHERE rolname = current_user
            """
        ).fetchone()
        assert role == ("lot42_publisher", False, False, False, False, False)
        privileges = connection.execute(
            """
            SELECT
              has_table_privilege(current_user, 'public.rag_chunks', 'SELECT'),
              has_table_privilege(current_user, 'public.rag_chunks', 'INSERT'),
              has_table_privilege(current_user, 'public.rag_chunks', 'UPDATE'),
              has_table_privilege(current_user, 'public.rag_chunks', 'DELETE'),
              has_table_privilege(
                  current_user, 'public.rag_artifacts', 'SELECT'
              ),
              has_table_privilege(
                  current_user, 'public.rag_artifacts', 'INSERT'
              ),
              has_table_privilege(
                  current_user, 'public.rag_artifacts', 'UPDATE'
              ),
              has_table_privilege(
                  current_user, 'public.rag_artifact_placements', 'SELECT'
              ),
              has_table_privilege(
                  current_user, 'public.rag_artifact_placements', 'INSERT'
              ),
              has_table_privilege(
                  current_user, 'public.rag_artifact_placements', 'UPDATE'
              ),
              has_table_privilege(
                  current_user, 'public.rag_schema_migrations', 'SELECT'
              ),
              has_table_privilege(current_user, 'public.rag_api_keys', 'SELECT')
            """
        ).fetchone()
        assert privileges == (
            True,
            True,
            False,
            False,
            True,
            True,
            False,
            True,
            True,
            False,
            False,
            False,
        )
    print("PUBLISHER_ROLE_INSERT_ONLY_PRODUCT_RELATIONS=PASS")


def test_governed_publisher_is_atomic_idempotent_and_multi_placement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = (
        b"Titre: Graphes et algorithmes\n\n"
        b"Cette ressource pedagogique explique les parcours de graphes, "
        b"leurs invariants et leur usage dans un programme de terminale."
    )
    artifact = publisher.GovernedArtifact(
        content=content,
        content_sha256=hashlib.sha256(content).hexdigest(),
        source_label="Ressource officielle multi-placement",
        source_uri="https://eduscol.education.fr/governed-multi-placement.pdf",
        rights=Rights.usage_interne.value,
        official=True,
        source_kind="eduscol",
        type_doc="ressource_officielle",
    )
    placement_a = _governed_placement(
        collection="lot42_governed_scope_a",
        source_suffix="scope-a",
    )
    placement_b = _governed_placement(
        collection="lot42_governed_scope_b",
        source_suffix="scope-b",
    )

    changed_content = content + b" Revision substantielle."
    changed_artifact = publisher.GovernedArtifact(
        content=changed_content,
        content_sha256=hashlib.sha256(changed_content).hexdigest(),
        source_label=artifact.source_label,
        source_uri=artifact.source_uri,
        rights=artifact.rights,
        official=artifact.official,
        source_kind=artifact.source_kind,
        type_doc=artifact.type_doc,
    )
    changed_placement = _governed_placement(
        collection="lot42_governed_changed",
        source_suffix="changed",
    )
    failed_content = b"contenu dont l'extraction echoue sans ecriture partielle"
    failed_artifact = publisher.GovernedArtifact(
        content=failed_content,
        content_sha256=hashlib.sha256(failed_content).hexdigest(),
        source_label=artifact.source_label,
        source_uri=artifact.source_uri,
        rights=artifact.rights,
        official=artifact.official,
        source_kind=artifact.source_kind,
        type_doc=artifact.type_doc,
    )
    failed_placement = _governed_placement(
        collection="lot42_governed_failed",
        source_suffix="failed",
    )

    bindings = {
        placement_a.resource_id: (artifact, placement_a),
        placement_b.resource_id: (artifact, placement_b),
        changed_placement.resource_id: (changed_artifact, changed_placement),
        failed_placement.resource_id: (failed_artifact, failed_placement),
    }
    attestations = {
        resource_id: _verified_publication(bound_artifact, placement)
        for resource_id, (bound_artifact, placement) in bindings.items()
    }

    def verified_attestation(
        _connection: psycopg.Connection[Any],
        *,
        resource_id: UUID,
        current_content_sha256: str,
        current_profile_fingerprint: str,
        current_manifest_digest: str,
        require_content_bound_authority: bool = False,
    ) -> VerifiedAttestation:
        assert require_content_bound_authority is True
        bound_artifact, placement = bindings[resource_id]
        assert current_content_sha256 == bound_artifact.content_sha256
        assert current_profile_fingerprint == placement.current_profile_fingerprint
        assert current_manifest_digest == placement.current_manifest_digest
        return attestations[resource_id]

    monkeypatch.setattr(publisher, "verify_publication_attestation", verified_attestation)
    monkeypatch.setattr(
        publisher,
        "_resource_is_retrieval_eligible",
        lambda _connection, *, resource_id: resource_id in bindings,
    )

    calls = {"extract": 0, "embed": 0}

    def extract_text(value: bytes) -> str:
        calls["extract"] += 1
        return value.decode("utf-8")

    def embed_chunks(passages: Sequence[str]) -> list[tuple[float, ...]]:
        calls["embed"] += 1
        return [QUERY_VECTOR for _ in passages]

    with psycopg.connect(PUBLISHER_DSN) as product_connection:
        created = publisher.publish_governed_artifact(
            product_connection,
            product_connection,
            artifact,
            (placement_a,),
            extract_text,
            embed_chunks,
        )
        retried = publisher.publish_governed_artifact(
            product_connection,
            product_connection,
            artifact,
            (placement_a,),
            extract_text,
            embed_chunks,
        )
        extended = publisher.publish_governed_artifact(
            product_connection,
            product_connection,
            artifact,
            (placement_a, placement_b),
            extract_text,
            embed_chunks,
        )
        changed = publisher.publish_governed_artifact(
            product_connection,
            product_connection,
            changed_artifact,
            (changed_placement,),
            extract_text,
            embed_chunks,
        )

        def extraction_failure(_value: bytes) -> str:
            raise RuntimeError("synthetic extraction failure")

        with pytest.raises(RuntimeError, match="synthetic extraction failure"):
            publisher.publish_governed_artifact(
                product_connection,
                product_connection,
                failed_artifact,
                (failed_placement,),
                extraction_failure,
                embed_chunks,
            )

    assert created.artifact_created is True
    assert created.placement_rows == 1
    assert created.chunk_rows > 0
    assert created.embedded is True
    assert retried == publisher.GovernedPublicationResult(
        artifact_id=artifact.artifact_id,
        artifact_created=False,
        placement_rows=1,
        chunk_rows=created.chunk_rows,
        embedded=False,
    )
    assert extended.placement_rows == 2
    assert extended.chunk_rows == created.chunk_rows
    assert extended.embedded is False
    assert changed.artifact_id != artifact.artifact_id
    assert changed.artifact_created is True
    assert changed.embedded is True
    assert calls == {"extract": 2, "embed": 2}

    with psycopg.connect(ADMIN_DSN) as admin_connection:
        counts = admin_connection.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM rag_artifacts WHERE artifact_id = %s),
              (SELECT COUNT(*) FROM rag_artifact_placements WHERE artifact_id = %s),
              (SELECT COUNT(*) FROM rag_chunks WHERE artifact_id = %s),
              (SELECT COUNT(*) FROM rag_artifacts WHERE artifact_id = %s),
              (SELECT COUNT(*) FROM rag_artifact_placements WHERE artifact_id = %s),
              (SELECT COUNT(*) FROM rag_chunks WHERE artifact_id = %s)
            """,
            (
                artifact.artifact_id,
                artifact.artifact_id,
                artifact.artifact_id,
                failed_artifact.artifact_id,
                failed_artifact.artifact_id,
                failed_artifact.artifact_id,
            ),
        ).fetchone()
    assert counts == (1, 2, created.chunk_rows, 0, 0, 0)

    candidates_by_collection = {
        collection: PgCandidateStore(
            _app_store_connection,
            _scope(collection),
        ).dense(
            query_vector=QUERY_VECTOR,
            collection=collection,
            limit=10,
        )
        for collection in (
            str(placement_a.scope.collection),
            str(placement_b.scope.collection),
            "lot42_governed_wrong_scope",
        )
    }
    scope_a = candidates_by_collection[str(placement_a.scope.collection)]
    scope_b = candidates_by_collection[str(placement_b.scope.collection)]
    wrong_scope = candidates_by_collection["lot42_governed_wrong_scope"]
    expected_placement_ids = {
        str(placement_a.scope.collection): publisher.canonical_placement_id(
            artifact.artifact_id, placement_a
        ),
        str(placement_b.scope.collection): publisher.canonical_placement_id(
            artifact.artifact_id, placement_b
        ),
    }
    for collection, candidates in (
        (str(placement_a.scope.collection), scope_a),
        (str(placement_b.scope.collection), scope_b),
    ):
        assert len(candidates) == created.chunk_rows
        assert len({candidate.chunk_id for candidate in candidates}) == len(candidates)
        assert all(candidate.doc_id == artifact.artifact_id for candidate in candidates)
        assert all(candidate.artifact_id == artifact.artifact_id for candidate in candidates)
        assert all(
            candidate.content_sha256 == artifact.content_sha256
            for candidate in candidates
        )
        assert all(
            candidate.placement_id == expected_placement_ids[collection]
            for candidate in candidates
        )
        assert all(candidate.placement_source_path for candidate in candidates)
    assert wrong_scope == []
    print("GOVERNED_PUBLISHER_ATOMIC_IDEMPOTENT=PASS")
    print("MULTI_PLACEMENT_RETRIEVAL_NO_DUPLICATE_CHUNKS=PASS")


def test_retrieval_role_is_exactly_read_only() -> None:
    assert retrieval_database_ready(APP_DSN) is True
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        connection.execute(
            "GRANT UPDATE (source_label) ON TABLE rag_chunks TO lot40_app"
        )
    try:
        assert retrieval_database_ready(APP_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                "REVOKE UPDATE (source_label) ON TABLE rag_chunks FROM lot40_app"
            )
    assert retrieval_database_ready(APP_DSN) is True
    print("RETRIEVAL_ROLE_WRITE_PRIVILEGE_REJECTED=PASS")


def test_runtime_roles_reject_privileges_on_auxiliary_relations() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        connection.execute("GRANT SELECT ON TABLE rag_api_keys TO lot40_app")
        connection.execute("GRANT SELECT ON TABLE rag_eval_runs TO lot41_review")
    try:
        assert retrieval_database_ready(APP_DSN) is False
        assert review_database_ready(REVIEW_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute("REVOKE SELECT ON TABLE rag_api_keys FROM lot40_app")
            connection.execute(
                "REVOKE SELECT ON TABLE rag_eval_runs FROM lot41_review"
            )
    assert retrieval_database_ready(APP_DSN) is True
    assert review_database_ready(REVIEW_DSN) is True
    print("RUNTIME_ROLE_AUXILIARY_RELATION_PRIVILEGE_REJECTED=PASS")


def test_runtime_roles_reject_executable_security_definer_routines() -> None:
    routine = "public.lot41u_unexpected_security_definer()"
    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(f"DROP FUNCTION IF EXISTS {routine}")
            connection.execute(
                """
                CREATE FUNCTION public.lot41u_unexpected_security_definer()
                RETURNS bigint
                LANGUAGE sql
                SECURITY DEFINER
                SET search_path = pg_catalog
                AS 'SELECT 1::bigint'
                """
            )
        assert retrieval_database_ready(APP_DSN) is False
        assert review_database_ready(REVIEW_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(f"DROP FUNCTION IF EXISTS {routine}")
    assert retrieval_database_ready(APP_DSN) is True
    assert review_database_ready(REVIEW_DSN) is True
    print("RUNTIME_SECURITY_DEFINER_EXECUTE_REJECTED=PASS")


def test_runtime_roles_reject_non_builtin_security_definer_in_pg_catalog() -> None:
    routine = "pg_catalog.lot41u_unexpected_catalog_security_definer()"
    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(f"DROP FUNCTION IF EXISTS {routine}")
            connection.execute(
                """
                CREATE FUNCTION pg_catalog.lot41u_unexpected_catalog_security_definer()
                RETURNS bigint
                LANGUAGE sql
                SECURITY DEFINER
                SET search_path = pg_catalog
                AS 'SELECT 1::bigint'
                """
            )
        assert retrieval_database_ready(APP_DSN) is False
        assert review_database_ready(REVIEW_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(f"DROP FUNCTION IF EXISTS {routine}")
    assert retrieval_database_ready(APP_DSN) is True
    assert review_database_ready(REVIEW_DSN) is True
    print("RUNTIME_PG_CATALOG_SECURITY_DEFINER_REJECTED=PASS")


def test_runtime_roles_reject_executable_window_security_definer() -> None:
    routine = "public.lot41u_unexpected_window_security_definer()"
    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(f"DROP FUNCTION IF EXISTS {routine}")
            connection.execute(
                """
                CREATE FUNCTION public.lot41u_unexpected_window_security_definer()
                RETURNS bigint
                AS 'window_row_number'
                LANGUAGE internal
                WINDOW
                STABLE
                STRICT
                SECURITY DEFINER
                """
            )
        assert retrieval_database_ready(APP_DSN) is False
        assert review_database_ready(REVIEW_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(f"DROP FUNCTION IF EXISTS {routine}")
    assert retrieval_database_ready(APP_DSN) is True
    assert review_database_ready(REVIEW_DSN) is True
    print("RUNTIME_WINDOW_SECURITY_DEFINER_REJECTED=PASS")


def test_runtime_schema_predicate_is_independent_of_string_mode() -> None:
    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                "ALTER ROLE lot40_app SET standard_conforming_strings TO off"
            )
            connection.execute(
                "ALTER ROLE lot41_review SET standard_conforming_strings TO off"
            )
        assert retrieval_database_ready(APP_DSN) is True
        assert review_database_ready(REVIEW_DSN) is True
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                "ALTER ROLE lot40_app RESET standard_conforming_strings"
            )
            connection.execute(
                "ALTER ROLE lot41_review RESET standard_conforming_strings"
            )
    assert retrieval_database_ready(APP_DSN) is True
    assert review_database_ready(REVIEW_DSN) is True
    print("RUNTIME_SCHEMA_ESCAPE_STABLE=PASS")


def test_runtime_roles_reject_create_or_ownership_on_every_user_schema() -> None:
    owned_schema = "lot41u_retrieval_owned"
    granted_schema = "lot41u_review_create"
    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(f"DROP SCHEMA IF EXISTS {owned_schema} CASCADE")
            connection.execute(f"DROP SCHEMA IF EXISTS {granted_schema} CASCADE")
            connection.execute(
                f"CREATE SCHEMA {owned_schema} AUTHORIZATION lot40_app"
            )
            connection.execute(f"CREATE SCHEMA {granted_schema}")
            connection.execute(
                f"GRANT CREATE ON SCHEMA {granted_schema} TO lot41_review"
            )
        assert retrieval_database_ready(APP_DSN) is False
        assert review_database_ready(REVIEW_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(f"DROP SCHEMA IF EXISTS {owned_schema} CASCADE")
            connection.execute(f"DROP SCHEMA IF EXISTS {granted_schema} CASCADE")
    assert retrieval_database_ready(APP_DSN) is True
    assert review_database_ready(REVIEW_DSN) is True
    print("RUNTIME_USER_SCHEMA_CREATE_REJECTED=PASS")


def test_runtime_roles_reject_large_object_ownership_and_privileges() -> None:
    retrieval_object: int | None = None
    review_object: int | None = None
    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            retrieval_row = connection.execute("SELECT lo_create(0)").fetchone()
            review_row = connection.execute("SELECT lo_create(0)").fetchone()
            assert retrieval_row is not None and review_row is not None
            retrieval_object = int(retrieval_row[0])
            review_object = int(review_row[0])
            connection.execute(
                f"GRANT SELECT ON LARGE OBJECT {retrieval_object} TO lot40_app"
            )
            connection.execute(
                f"ALTER LARGE OBJECT {review_object} OWNER TO lot41_review"
            )
        assert retrieval_database_ready(APP_DSN) is False
        assert review_database_ready(REVIEW_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            if retrieval_object is not None:
                connection.execute("SELECT lo_unlink(%s)", (retrieval_object,))
            if review_object is not None:
                connection.execute("SELECT lo_unlink(%s)", (review_object,))
    assert retrieval_database_ready(APP_DSN) is True
    assert review_database_ready(REVIEW_DSN) is True
    print("RUNTIME_LARGE_OBJECT_PRIVILEGES_REJECTED=PASS")


@pytest.mark.parametrize(
    ("role", "dsn", "ready"),
    (
        ("lot40_app", APP_DSN, retrieval_database_ready),
        ("lot41_review", REVIEW_DSN, review_database_ready),
    ),
)
def test_runtime_roles_require_large_object_acl_enforcement(
    role: str,
    dsn: str,
    ready: Callable[[str], bool],
) -> None:
    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                sql.SQL("ALTER ROLE {} SET lo_compat_privileges = on").format(
                    sql.Identifier(role)
                )
            )
        assert ready(dsn) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                sql.SQL("ALTER ROLE {} RESET lo_compat_privileges").format(
                    sql.Identifier(role)
                )
            )
    assert ready(dsn) is True

    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                sql.SQL(
                    "GRANT SET ON PARAMETER lo_compat_privileges TO {}"
                ).format(sql.Identifier(role))
            )
        assert ready(dsn) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                sql.SQL(
                    "REVOKE SET ON PARAMETER lo_compat_privileges FROM {}"
                ).format(sql.Identifier(role))
            )
    assert ready(dsn) is True
    print(f"RUNTIME_LARGE_OBJECT_ACL_ENFORCEMENT_{role.upper()}=PASS")


def test_retrieval_pool_enforces_server_side_execution_timeouts() -> None:
    settings = PoolSettings(
        dsn=APP_DSN,
        min_size=1,
        max_size=1,
        timeout_s=5.0,
        statement_timeout_ms=100,
        lock_timeout_ms=50,
    )
    close_pool()
    try:
        with pytest.raises(psycopg.errors.QueryCanceled):
            with pool_connection(settings) as connection:
                connection.execute("SELECT pg_sleep(0.25)")

        with psycopg.connect(ADMIN_DSN) as locker:
            locker.execute("LOCK TABLE rag_chunks IN ACCESS EXCLUSIVE MODE")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                with pool_connection(settings) as connection:
                    connection.execute("SELECT 1 FROM rag_chunks LIMIT 1")
    finally:
        close_pool()
    print("RETRIEVAL_POOL_SERVER_TIMEOUTS=PASS")


def test_review_connections_enforce_server_side_execution_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PG_CONNECT_TIMEOUT_S", "3")
    monkeypatch.setenv("PG_STATEMENT_TIMEOUT_MS", "100")
    monkeypatch.setenv("PG_LOCK_TIMEOUT_MS", "50")

    with pytest.raises(psycopg.errors.QueryCanceled):
        with review_endpoint._connect_review_database(REVIEW_DSN) as connection:
            connection.execute("SELECT pg_sleep(0.25)")

    with psycopg.connect(ADMIN_DSN) as locker:
        locker.execute("LOCK TABLE rag_chunks IN ACCESS EXCLUSIVE MODE")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            with review_endpoint._connect_review_database(REVIEW_DSN) as connection:
                connection.execute("SELECT 1 FROM rag_chunks LIMIT 1")
    print("REVIEW_CONNECTION_SERVER_TIMEOUTS=PASS")


def test_review_readiness_rejects_update_on_any_other_column() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        connection.execute(
            "GRANT UPDATE (source_label) ON TABLE rag_chunks TO lot41_review"
        )
    try:
        assert review_database_ready(REVIEW_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                "REVOKE UPDATE (source_label) ON TABLE rag_chunks FROM lot41_review"
            )
    assert review_database_ready(REVIEW_DSN) is True
    print("REVIEW_ROLE_OTHER_COLUMN_UPDATE_REJECTED=PASS")


def test_review_readiness_rejects_column_level_insert() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        connection.execute(
            "GRANT INSERT (source_label) ON TABLE rag_chunks TO lot41_review"
        )
    try:
        assert review_database_ready(REVIEW_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                "REVOKE INSERT (source_label) ON TABLE rag_chunks FROM lot41_review"
            )
    assert review_database_ready(REVIEW_DSN) is True
    print("REVIEW_ROLE_COLUMN_LEVEL_INSERT_REJECTED=PASS")


def test_review_readiness_rejects_trigger_privilege() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        connection.execute("GRANT TRIGGER ON TABLE rag_chunks TO lot41_review")
    try:
        assert review_database_ready(REVIEW_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute("REVOKE TRIGGER ON TABLE rag_chunks FROM lot41_review")
    assert review_database_ready(REVIEW_DSN) is True
    print("REVIEW_ROLE_TRIGGER_PRIVILEGE_REJECTED=PASS")


def test_review_readiness_rejects_column_level_references() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        connection.execute(
            "GRANT REFERENCES (source_label) ON TABLE rag_chunks TO lot41_review"
        )
    try:
        assert review_database_ready(REVIEW_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                "REVOKE REFERENCES (source_label) ON TABLE rag_chunks FROM lot41_review"
            )
    assert review_database_ready(REVIEW_DSN) is True
    print("REVIEW_ROLE_COLUMN_LEVEL_REFERENCES_REJECTED=PASS")


def test_review_readiness_rejects_migration_registry_insert() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        connection.execute(
            "GRANT INSERT ON TABLE rag_schema_migrations TO lot41_review"
        )
    try:
        assert review_database_ready(REVIEW_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                "REVOKE INSERT ON TABLE rag_schema_migrations FROM lot41_review"
            )
    assert review_database_ready(REVIEW_DSN) is True
    print("REVIEW_ROLE_MIGRATION_REGISTRY_INSERT_REJECTED=PASS")


def test_runtime_roles_reject_every_set_role_membership_path() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        connection.execute(
            "CREATE ROLE lot41_set_role_writer "
            "NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOINHERIT NOREPLICATION NOBYPASSRLS"
        )
        connection.execute(
            "GRANT UPDATE (source_label) ON TABLE rag_chunks "
            "TO lot41_set_role_writer"
        )
        connection.execute("GRANT lot41_set_role_writer TO lot40_app")
        connection.execute("GRANT lot41_set_role_writer TO lot41_review")
    try:
        assert retrieval_database_ready(APP_DSN) is False
        assert review_database_ready(REVIEW_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute("REVOKE lot41_set_role_writer FROM lot40_app")
            connection.execute("REVOKE lot41_set_role_writer FROM lot41_review")
            connection.execute(
                "REVOKE UPDATE (source_label) ON TABLE rag_chunks "
                "FROM lot41_set_role_writer"
            )
            connection.execute("DROP ROLE lot41_set_role_writer")
    assert retrieval_database_ready(APP_DSN) is True
    assert review_database_ready(REVIEW_DSN) is True
    print("RUNTIME_SET_ROLE_MEMBERSHIP_REJECTED=PASS")


def test_schema_registry_fingerprints_and_real_migration_objects_are_exact() -> None:
    expected = {
        1: (
            "001_rag_chunks_v2_schema.sql",
            hashlib.sha256(
                (SERVICE_ROOT / "infra/postgres/migrations/001_rag_chunks_v2_schema.sql")
                .read_bytes()
            ).hexdigest(),
        ),
        2: (
            "002_hybrid_retrieval.sql",
            hashlib.sha256(
                (SERVICE_ROOT / "infra/postgres/migrations/002_hybrid_retrieval.sql")
                .read_bytes()
            ).hexdigest(),
        ),
        3: (
            "003_profile_filtering.sql",
            hashlib.sha256(
                (SERVICE_ROOT / "infra/postgres/migrations/003_profile_filtering.sql")
                .read_bytes()
            ).hexdigest(),
        ),
        4: (
            "004_artifact_placements.sql",
            hashlib.sha256(
                (SERVICE_ROOT / "infra/postgres/migrations/004_artifact_placements.sql")
                .read_bytes()
            ).hexdigest(),
        ),
    }
    with psycopg.connect(ADMIN_DSN) as connection:
        rows = connection.execute(
            "SELECT version, file_name, sha256 FROM rag_schema_migrations ORDER BY version"
        ).fetchall()
        assert rows == [(version, *expected[version]) for version in (1, 2, 3, 4)]
        objects = connection.execute(
            """
            SELECT
              to_regclass('public.idx_rag_chunks_vector')::text,
              to_regclass('public.idx_rag_chunks_text_tsv')::text,
              to_regclass('public.idx_rag_chunks_profile_reviewed')::text,
              (SELECT is_generated FROM information_schema.columns
               WHERE table_schema='public' AND table_name='rag_chunks'
                 AND column_name='text_tsv')
            """
        ).fetchone()
        assert objects == (
            "idx_rag_chunks_vector",
            "idx_rag_chunks_text_tsv",
            "idx_rag_chunks_profile_reviewed",
            "ALWAYS",
        )
    assert schema_head_004_ready(APP_DSN) is True
    print("SCHEMA_FINGERPRINTS_REAL_DB=PASS")


def test_schema_readiness_rejects_missing_lexical_index() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        connection.execute("DROP INDEX idx_rag_chunks_text_tsv")
    try:
        assert schema_head_004_ready(APP_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                "CREATE INDEX idx_rag_chunks_text_tsv "
                "ON rag_chunks USING gin (text_tsv)"
            )
    assert schema_head_004_ready(APP_DSN) is True
    print("SCHEMA_BASE_INDEX_DRIFT_REJECTED=PASS")


def test_schema_readiness_rejects_default_and_extra_index_drift() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        connection.execute(
            "ALTER TABLE rag_chunks ALTER COLUMN voie SET DEFAULT 'drifted'"
        )
    try:
        assert schema_head_004_ready(APP_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                "ALTER TABLE rag_chunks ALTER COLUMN voie SET DEFAULT 'generale'"
            )
    assert schema_head_004_ready(APP_DSN) is True

    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        connection.execute(
            "CREATE INDEX idx_rag_chunks_unexpected ON rag_chunks (doc_id)"
        )
    try:
        assert schema_head_004_ready(APP_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute("DROP INDEX idx_rag_chunks_unexpected")
    assert schema_head_004_ready(APP_DSN) is True
    print("SCHEMA_DEFAULT_AND_EXTRA_INDEX_DRIFT_REJECTED=PASS")


def test_schema_readiness_rejects_an_invalid_extra_index() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        connection.execute(
            "CREATE INDEX idx_rag_chunks_invalid_extra ON rag_chunks (doc_id)"
        )
        connection.execute(
            "UPDATE pg_index SET indisvalid = false "
            "WHERE indexrelid = 'idx_rag_chunks_invalid_extra'::regclass"
        )
    try:
        assert schema_head_004_ready(APP_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute("DROP INDEX idx_rag_chunks_invalid_extra")
    assert schema_head_004_ready(APP_DSN) is True
    print("SCHEMA_INVALID_EXTRA_INDEX_DRIFT_REJECTED=PASS")


def test_schema_readiness_rejects_row_security_drift() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        connection.execute("ALTER TABLE rag_chunks ENABLE ROW LEVEL SECURITY")
    try:
        assert schema_head_004_ready(APP_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute("ALTER TABLE rag_chunks DISABLE ROW LEVEL SECURITY")
    assert schema_head_004_ready(APP_DSN) is True
    print("SCHEMA_ROW_SECURITY_DRIFT_REJECTED=PASS")


def test_schema_readiness_rejects_unlogged_rag_chunks() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        connection.execute("ALTER TABLE rag_chunks SET UNLOGGED")
    try:
        assert schema_head_004_ready(APP_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute("ALTER TABLE rag_chunks SET LOGGED")
    assert schema_head_004_ready(APP_DSN) is True
    print("SCHEMA_PERMANENT_STORAGE_DRIFT_REJECTED=PASS")


def test_schema_readiness_rejects_non_internal_trigger_drift() -> None:
    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                "DROP TRIGGER IF EXISTS lot41u_unexpected_trigger ON rag_chunks"
            )
            connection.execute(
                "DROP FUNCTION IF EXISTS lot41u_unexpected_trigger()"
            )
            connection.execute(
                """
                CREATE FUNCTION lot41u_unexpected_trigger()
                RETURNS trigger
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    RETURN NEW;
                END;
                $$
                """
            )
            connection.execute(
                """
                CREATE TRIGGER lot41u_unexpected_trigger
                BEFORE UPDATE ON rag_chunks
                FOR EACH ROW
                EXECUTE FUNCTION lot41u_unexpected_trigger()
                """
            )
        assert schema_head_004_ready(APP_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                "DROP TRIGGER IF EXISTS lot41u_unexpected_trigger ON rag_chunks"
            )
            connection.execute(
                "DROP FUNCTION IF EXISTS lot41u_unexpected_trigger()"
            )
    assert schema_head_004_ready(APP_DSN) is True
    print("SCHEMA_TRIGGER_DRIFT_REJECTED=PASS")


def test_runtime_blocks_review_update_while_trigger_drift_is_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_token = "lot41u-runtime-bff-service-token-32-bytes"
    target = "doc-pending-000"
    monkeypatch.setenv("RAG_BFF_SERVICE_TOKEN", service_token)
    monkeypatch.setenv("PG_RAG_DSN", APP_DSN)
    monkeypatch.setenv("PG_REVIEW_DSN", REVIEW_DSN)
    monkeypatch.setattr(
        review_endpoint,
        "_require_review_identity",
        lambda *_args, **_kwargs: SimpleNamespace(scope_digest="a" * 64),
    )
    monkeypatch.setattr(
        review_endpoint,
        "_load_review_scopes",
        lambda *_args, **_kwargs: (_scope(TARGET_COLLECTION),),
    )
    monkeypatch.setattr(review_endpoint, "_get_pg_dsn", lambda: REVIEW_DSN)
    runtime_api._reset_database_readiness_cache()
    response = None
    observed_status = None
    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                "DROP TRIGGER IF EXISTS lot41u_runtime_gate_trigger ON rag_chunks"
            )
            connection.execute(
                "DROP FUNCTION IF EXISTS lot41u_runtime_gate_trigger()"
            )
            connection.execute(
                """
                CREATE FUNCTION lot41u_runtime_gate_trigger()
                RETURNS trigger
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    RETURN NEW;
                END;
                $$
                """
            )
            connection.execute(
                """
                CREATE TRIGGER lot41u_runtime_gate_trigger
                BEFORE UPDATE ON rag_chunks
                FOR EACH ROW
                EXECUTE FUNCTION lot41u_runtime_gate_trigger()
                """
            )

        response = TestClient(runtime_api.app).post(
            "/review/v2/decide",
            headers={"Authorization": f"Bearer {service_token}"},
            json={
                "target_type": "doc",
                "target_id": target,
                "decision": "reviewed",
                "tenant": TENANT,
            },
        )
        with psycopg.connect(ADMIN_DSN) as connection:
            observed_status = connection.execute(
                "SELECT review_status FROM rag_chunks WHERE chunk_id = %s",
                ("pending-000",),
            ).fetchone()[0]
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                "UPDATE rag_chunks SET review_status = 'needs_review' "
                "WHERE chunk_id = 'pending-000'"
            )
            connection.execute(
                "DROP TRIGGER IF EXISTS lot41u_runtime_gate_trigger ON rag_chunks"
            )
            connection.execute(
                "DROP FUNCTION IF EXISTS lot41u_runtime_gate_trigger()"
            )
        runtime_api._reset_database_readiness_cache()

    assert response is not None
    assert response.status_code == 503
    assert response.json() == {"detail": "service unavailable"}
    assert observed_status == "needs_review"
    assert schema_head_004_ready(APP_DSN) is True
    print("RUNTIME_REVIEW_TRIGGER_DRIFT_BLOCKED=PASS")


def test_schema_readiness_rejects_rewrite_rule_drift() -> None:
    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                "DROP RULE IF EXISTS lot41u_unexpected_rule ON rag_chunks"
            )
            connection.execute(
                "CREATE RULE lot41u_unexpected_rule AS "
                "ON UPDATE TO rag_chunks DO INSTEAD NOTHING"
            )
        assert schema_head_004_ready(APP_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                "DROP RULE IF EXISTS lot41u_unexpected_rule ON rag_chunks"
            )
    assert schema_head_004_ready(APP_DSN) is True
    print("SCHEMA_REWRITE_RULE_DRIFT_REJECTED=PASS")


def test_schema_readiness_rejects_inheritance_hierarchy_drift() -> None:
    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute("DROP TABLE IF EXISTS lot41u_rag_chunks_child")
            connection.execute(
                "CREATE TABLE lot41u_rag_chunks_child () INHERITS (rag_chunks)"
            )
        assert schema_head_004_ready(APP_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute("DROP TABLE IF EXISTS lot41u_rag_chunks_child")
    assert schema_head_004_ready(APP_DSN) is True
    print("SCHEMA_INHERITANCE_HIERARCHY_DRIFT_REJECTED=PASS")


def test_schema_readiness_rejects_unexpected_foreign_key_constraint() -> None:
    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                "ALTER TABLE rag_chunks "
                "DROP CONSTRAINT IF EXISTS lot41u_unexpected_fk"
            )
            connection.execute("DROP TABLE IF EXISTS lot41u_fk_target")
            connection.execute(
                "CREATE TABLE lot41u_fk_target (source_label text PRIMARY KEY)"
            )
            connection.execute(
                "ALTER TABLE rag_chunks "
                "ADD CONSTRAINT lot41u_unexpected_fk "
                "FOREIGN KEY (source_label) "
                "REFERENCES lot41u_fk_target(source_label) NOT VALID"
            )
        assert schema_head_004_ready(APP_DSN) is False
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(
                "ALTER TABLE rag_chunks "
                "DROP CONSTRAINT IF EXISTS lot41u_unexpected_fk"
            )
            connection.execute("DROP TABLE IF EXISTS lot41u_fk_target")
    assert schema_head_004_ready(APP_DSN) is True
    print("SCHEMA_ALL_CONSTRAINT_TYPES_DRIFT_REJECTED=PASS")


def test_equal_score_rank_50_is_deterministic_in_both_channels() -> None:
    store = PgCandidateStore(_app_store_connection, _scope(TIE_COLLECTION))
    dense = store.dense(
        query_vector=QUERY_VECTOR,
        collection=TIE_COLLECTION,
        limit=50,
    )
    lexical = store.lexical(raw_query=QUERY, collection=TIE_COLLECTION, limit=50)
    expected = [f"tie-{index:03d}" for index in range(50)]
    _assert_ids([item.chunk_id for item in dense], expected)
    _assert_ids([item.chunk_id for item in lexical], expected)
    with pytest.raises(AssertionError):
        _assert_ids([item.chunk_id for item in dense], list(reversed(expected)))
    assert dense[-1].chunk_id == "tie-049"
    assert lexical[-1].chunk_id == "tie-049"
    with pytest.raises(RetrievalPipelineError, match="dense channel query failed"):
        PgCandidateStore(
            _app_store_connection,
            _scope(OVERFLOW_TIE_COLLECTION),
        ).dense(
            query_vector=QUERY_VECTOR,
            collection=OVERFLOW_TIE_COLLECTION,
            limit=50,
        )
    print("RANK_50_DETERMINISTIC=PASS")
    print("HNSW_TIE_SENTINEL_OVERFLOW_FAIL_CLOSED=PASS")


@pytest.mark.parametrize("matiere", sorted(MATRIX_COLLECTIONS))
@pytest.mark.parametrize("candidat", MATRIX_CANDIDATES)
def test_candidate_by_subject_scope_matrix_is_real(
    matiere: str,
    candidat: str,
) -> None:
    collection = MATRIX_COLLECTIONS[matiere]
    scope = _scope(collection, candidat=candidat, matiere=matiere)
    store = PgCandidateStore(_app_store_connection, scope)
    expected = f"matrix-{matiere}-{candidat}"

    dense = store.dense(
        query_vector=QUERY_VECTOR,
        collection=collection,
        limit=5,
    )
    lexical = store.lexical(
        raw_query=QUERY,
        collection=collection,
        limit=5,
    )

    _assert_ids([candidate.chunk_id for candidate in dense], [expected])
    _assert_ids([candidate.chunk_id for candidate in lexical], [expected])
    print(f"SCOPE_MATRIX_{matiere.upper()}_{candidat.upper()}=PASS")


def test_real_gin_and_hnsw_plans_filters_top_50_and_local_scope() -> None:
    with psycopg.connect(APP_DSN, autocommit=True) as connection:
        assert connection.execute(
            "SELECT current_setting('hnsw.iterative_scan', true)"
        ).fetchone()[0] is None
        assert connection.execute(
            "SELECT %s::vector IS NOT NULL", (QUERY_VECTOR_TEXT,)
        ).fetchone()[0]
        initial_scan_mode = connection.execute("SHOW hnsw.iterative_scan").fetchone()[0]
        with connection.transaction():
            connection.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
            assert connection.execute("SHOW hnsw.iterative_scan").fetchone()[0] == (
                "strict_order"
            )
        assert connection.execute("SHOW hnsw.iterative_scan").fetchone()[0] == (
            initial_scan_mode
        )

        with connection.transaction():
            connection.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
            connection.execute("SET LOCAL hnsw.ef_search = 40")
            connection.execute("SET LOCAL hnsw.max_scan_tuples = 100000")
            hnsw_plan = _plan_json(
                connection,
                _DENSE_SQL,
                _dense_params(TARGET_COLLECTION),
            )
            _assert_bounded_hnsw_json_plan(hnsw_plan)

        with connection.transaction():
            connection.execute("SET LOCAL enable_seqscan = off")
            connection.execute("SET LOCAL enable_bitmapscan = off")
            connection.execute("SET LOCAL enable_sort = off")
            connection.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
            connection.execute("SET LOCAL hnsw.ef_search = 40")
            connection.execute("SET LOCAL hnsw.max_scan_tuples = 100000")
            structural_plan = _plan_json(
                connection,
                _DENSE_SQL,
                _dense_params(TARGET_COLLECTION),
            )
            _assert_bounded_hnsw_json_plan(structural_plan)

        with connection.transaction():
            _assert_gin_plan(connection)

    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin_connection:
        admin_connection.execute("DROP INDEX idx_rag_chunks_text_tsv")
    try:
        with psycopg.connect(APP_DSN) as app_connection:
            with pytest.raises(AssertionError):
                _assert_gin_plan(app_connection)
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin_connection:
            admin_connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rag_chunks_text_tsv
                    ON rag_chunks USING gin (text_tsv)
                """
            )
    with psycopg.connect(APP_DSN) as app_connection:
        _assert_gin_plan(app_connection)

    app_store = PgCandidateStore(_app_store_connection, _scope(TARGET_COLLECTION))
    app_actual = app_store.dense(
        query_vector=QUERY_VECTOR,
        collection=TARGET_COLLECTION,
        limit=50,
    )
    assert 0 < len(app_actual) <= 50
    assert len({item.chunk_id for item in app_actual}) == len(app_actual)
    assert [item.dense_score for item in app_actual] == sorted(
        (item.dense_score for item in app_actual),
        reverse=True,
    )
    assert all(item.review_status == "reviewed" for item in app_actual)
    assert not any(
        item.chunk_id.startswith(
            ("outside-", "pending-", "incomplete-", "scope-canary-")
        )
        for item in app_actual
    )

    exact_store = PgCandidateStore(
        _exact_store_connection,
        _scope(TARGET_COLLECTION),
    )
    actual = exact_store.dense(
        query_vector=QUERY_VECTOR,
        collection=TARGET_COLLECTION,
        limit=50,
    )
    with psycopg.connect(APP_DSN) as connection:
        connection.execute("SET LOCAL enable_indexscan = off")
        connection.execute("SET LOCAL enable_bitmapscan = off")
        expected_rows = connection.execute(
            _DENSE_ORACLE_SQL,
            (*_legacy_scope_sql_params(TARGET_COLLECTION), QUERY_VECTOR_TEXT),
        ).fetchall()
    expected_ids = [str(row[0]) for row in expected_rows]
    assert 0 < len(actual) <= 50
    _assert_ids([item.chunk_id for item in actual], expected_ids[: len(actual)])
    assert all(item.review_status == "reviewed" for item in actual)
    assert not any(
        item.chunk_id.startswith(
            ("outside-", "pending-", "incomplete-", "scope-canary-")
        )
        for item in actual
    )

    assert PgCandidateStore(
        _app_store_connection,
        _scope("lot40_empty"),
    ).dense(
        query_vector=QUERY_VECTOR,
        collection="lot40_empty",
        limit=50,
    ) == []
    small = PgCandidateStore(
        _app_store_connection,
        _scope(SMALL_COLLECTION),
    ).dense(
        query_vector=QUERY_VECTOR,
        collection=SMALL_COLLECTION,
        limit=50,
    )
    _assert_ids(
        [item.chunk_id for item in small],
        [f"small-{index:03d}" for index in range(3)],
    )
    for variable_limit in (1, 17, 50):
        limited = exact_store.dense(
            query_vector=QUERY_VECTOR,
            collection=TARGET_COLLECTION,
            limit=variable_limit,
        )
        _assert_ids(
            [item.chunk_id for item in limited],
            expected_ids[: len(limited)],
        )
        assert 0 < len(limited) <= variable_limit

    with psycopg.connect(APP_DSN, autocommit=True) as connection:
        assert connection.execute(
            "SELECT %s::vector IS NOT NULL", (QUERY_VECTOR_TEXT,)
        ).fetchone()[0]
        with connection.transaction():
            connection.execute("SET LOCAL enable_seqscan = off")
            connection.execute("SET LOCAL enable_bitmapscan = off")
            connection.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
            connection.execute("SET LOCAL hnsw.ef_search = 1")
            connection.execute("SET LOCAL hnsw.max_scan_tuples = 1")
            underfill_plan = _plan_json(
                connection,
                _DENSE_SQL,
                _dense_params(TARGET_COLLECTION),
            )
            _assert_bounded_hnsw_json_plan(underfill_plan)
    underfill_store = PgCandidateStore(
        _underfill_store_connection,
        _scope(TARGET_COLLECTION),
    )
    underfill_actual = underfill_store.dense(
        query_vector=QUERY_VECTOR,
        collection=TARGET_COLLECTION,
        limit=50,
    )
    underfill_again = underfill_store.dense(
        query_vector=QUERY_VECTOR,
        collection=TARGET_COLLECTION,
        limit=50,
    )
    assert len(underfill_actual) <= 50
    _assert_ids(
        [item.chunk_id for item in underfill_actual],
        [item.chunk_id for item in underfill_again],
    )
    assert len({item.chunk_id for item in underfill_actual}) == len(underfill_actual)
    assert all(item.review_status == "reviewed" for item in underfill_actual)
    assert not any(
        item.chunk_id.startswith(
            ("outside-", "pending-", "incomplete-", "scope-canary-")
        )
        for item in underfill_actual
    )
    assert [item.dense_score for item in underfill_actual] == sorted(
        (item.dense_score for item in underfill_actual),
        reverse=True,
    )
    execution_ms = float(hnsw_plan["Execution Time"])
    assert execution_ms >= 0.0
    print("GIN_PLAN=PASS")
    print("HNSW_STRICT_FILTERED_BOUNDED=PASS")
    print(f"HNSW_BOUNDED_JSON_PLAN_MS={execution_ms:.3f}")
    print("HNSW_NATURAL_AND_STRUCTURAL_BOUNDED_PLAN=PASS")
    print("APP_STORE_DEFAULT_HNSW_SETTINGS=PASS")
    print("DENSE_EXACT_ORACLE_PREFIX=PASS")
    print("HNSW_UNDERFILL_BOUNDED_NO_GLOBAL_SCAN=PASS")


class DeterministicEmbedder:
    def encode(self, text: str, *, normalize_embeddings: bool) -> Sequence[float]:
        assert text == f"query: {QUERY}"
        assert normalize_embeddings is True
        return QUERY_VECTOR


class DeterministicReranker:
    def predict(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]:
        scores: list[float] = []
        for query, text in pairs:
            assert query == QUERY
            if "distinct sans terme" in text:
                scores.append(2.60)
            elif text.count("algorithme graphe") == 3:
                scores.append(2.55)
            elif text == "algorithme graphe preuve pedagogique de charge":
                scores.append(0.0)
            else:
                ordinal = int(text.rsplit(" ", 1)[1])
                scores.append(2.50 - ordinal / 1000)
        return scores


def test_deterministic_reranker_accepts_ann_load_candidates() -> None:
    assert DeterministicReranker().predict(
        [(QUERY, "algorithme graphe preuve pedagogique de charge")]
    ) == [0.0]


class EmptyReranker:
    def predict(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]:
        return [0.0] * len(pairs)


class PilotFixtureReranker:
    def predict(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]:
        assert all(query == QUERY for query, _text in pairs)
        return [2.60] * len(pairs)


def test_exact_store_and_core_prove_union_scores_page_dedup_and_dimension_failure() -> None:
    # Les canaris dense/lexical prouvent ici la fusion contre l'oracle exact.
    # Le chemin HNSW runtime reste approximatif par contrat et ses propriétés
    # de plan, de scope, de bornes et d'underfill sont prouvées séparément.
    store = PgCandidateStore(_exact_store_connection, _scope(TARGET_COLLECTION))
    hits = retrieve_hybrid(
        QUERY,
        TARGET_COLLECTION,
        5,
        store=store,
        embedder=DeterministicEmbedder(),
        reranker=DeterministicReranker(),
    )
    assert [hit.candidate.chunk_id for hit in hits[:2]] == [
        "target-dense-only",
        "target-lexical-only",
    ]
    assert hits[0].dense_rank == 1
    assert hits[0].lexical_rank is None
    assert hits[1].dense_rank is None
    assert hits[1].lexical_rank == 1
    assert hits[0].candidate.page_start is None
    assert hits[1].candidate.page_start == 7
    assert hits[0].rrf_score == pytest.approx(0.7 / 61)
    assert hits[0].rerank_score == 2.60
    expected_first_mmr = 0.7 / (1.0 + math.exp(-2.60))
    assert hits[0].mmr_score == pytest.approx(expected_first_mmr)
    assert hits[0].score_final == pytest.approx((expected_first_mmr + 0.3) / 1.3)
    assert len({hit.candidate.doc_id for hit in hits}) == len(hits)
    assert all(hit.candidate.review_status == "reviewed" for hit in hits)
    assert not any(
        hit.candidate.chunk_id.startswith(("incomplete-", "scope-canary-"))
        for hit in hits
    )

    sql_calls = 0

    @contextmanager
    def counted_connection() -> Iterator[psycopg.Connection[Any]]:
        nonlocal sql_calls
        sql_calls += 1
        with psycopg.connect(APP_DSN) as connection:
            yield connection

    class WrongDimensionEmbedder:
        def encode(self, text: str, *, normalize_embeddings: bool) -> Sequence[float]:
            return (1.0, 0.0)

    with pytest.raises(RetrievalPipelineError):
        retrieve_hybrid(
            QUERY,
            TARGET_COLLECTION,
            5,
            store=PgCandidateStore(counted_connection, _scope(TARGET_COLLECTION)),
            embedder=WrongDimensionEmbedder(),
            reranker=DeterministicReranker(),
        )
    assert sql_calls == 0
    print("HYBRID_REAL_DB=PASS")


def _test_app(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        endpoint,
        "_require_retrieval_identity",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        endpoint,
        "load_collection_config",
        lambda: {
            "collections": {
                TARGET_COLLECTION: {
                    "domain": "education",
                    "instanciee": True,
                },
            },
            "domains": {"education": {"retrievable": True}},
        },
    )
    monkeypatch.setattr(endpoint, "_check_retrievable", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        endpoint,
        "_collection_for_retrieval_request",
        lambda *_args, **_kwargs: TARGET_COLLECTION,
    )
    monkeypatch.setattr(
        endpoint,
        "_require_retrieval_profile_match",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        endpoint,
        "build_server_retrieval_scope",
        lambda _identity, *, collection, collection_config: _scope(collection),
    )
    app = FastAPI()
    app.include_router(endpoint.router)
    return TestClient(app)


def test_http_search_fails_closed_then_uses_real_hybrid_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PG_RAG_DSN", APP_DSN)
    monkeypatch.setenv("PG_POOL_MIN_SIZE", "1")
    monkeypatch.setenv("PG_POOL_MAX_SIZE", "2")
    monkeypatch.setenv("PG_POOL_TIMEOUT_S", "5")
    monkeypatch.setattr(endpoint, "_get_embed_model", lambda: DeterministicEmbedder())
    monkeypatch.setattr(endpoint, "_get_reranker", lambda: DeterministicReranker())
    close_pool()
    client = _test_app(monkeypatch)
    real_retrieve = endpoint._retrieve_hybrid_hits

    def fail_with_private_context(*args: object, **kwargs: object) -> list[object]:
        raise RetrievalPipelineError(f"private database context: {APP_DSN}")

    monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", fail_with_private_context)
    failed = client.post(
        "/search/v2",
        json=_retrieval_request_payload(),
    )
    assert failed.status_code == 503
    assert failed.json() == {"detail": "retrieval unavailable"}
    assert APP_DSN not in failed.text

    monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", real_retrieve)
    response = client.post(
        "/search/v2",
        json=_retrieval_request_payload(),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["results"]) == 5
    results_by_id = {hit["chunk_id"]: hit for hit in payload["results"]}
    assert "target-lexical-only" in results_by_id
    assert results_by_id["target-lexical-only"]["citation"]["page"] == 7
    assert payload["results"][0]["chunk_id"] in {
        "target-dense-only",
        "target-lexical-only",
    }
    if "target-dense-only" in results_by_id:
        assert results_by_id["target-dense-only"]["citation"]["page"] is None
    assert all(
        hit["metadata"]["review_status"] == "reviewed"
        for hit in payload["results"]
    )
    assert all(
        hit["citation"]["source_label"]
        and hit["citation"]["source_uri"]
        and hit["citation"]["rights"]
        for hit in payload["results"]
    )
    assert all(
        key in payload["results"][0]["metadata"]
        for key in (
            "dense_score",
            "lexical_score",
            "rrf_score",
            "rerank_score",
            "mmr_score",
            "score_final",
        )
    )
    client.close()
    close_pool()
    print("HTTP_SEARCH_V2=PASS")


def test_signed_identity_to_http_scope_and_real_database_is_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_token = "lot41-integration-bff-service-token-32-bytes"
    monkeypatch.setenv("RAG_BFF_SERVICE_TOKEN", service_token)
    monkeypatch.setenv("NEXUS_INTERNAL_TOKEN_SECRET", INTERNAL_TOKEN_SECRET)
    monkeypatch.setenv("NEXUS_INTERNAL_TOKEN_ISSUER", INTERNAL_TOKEN_ISSUER)
    monkeypatch.setenv("NEXUS_INTERNAL_TOKEN_AUDIENCE", INTERNAL_TOKEN_AUDIENCE)
    monkeypatch.setenv("NEXUS_SSO_ISSUER", SSO_ISSUER)
    monkeypatch.setenv("NEXUS_SSO_AUDIENCE", SSO_AUDIENCE)
    monkeypatch.setenv("PG_RAG_DSN", APP_DSN)
    monkeypatch.setenv("PG_POOL_MIN_SIZE", "1")
    monkeypatch.setenv("PG_POOL_MAX_SIZE", "2")
    monkeypatch.setenv("PG_POOL_TIMEOUT_S", "5")
    for variable in (
        "RAG_ADMIN_TOKEN",
        "RAG_REVIEWER_TOKEN",
        "REVIEWER_API_TOKEN",
        "RAG_TEACHER_TOKEN",
        "RAG_INGEST_AGENT_TOKEN",
        "INGESTOR_API_TOKEN",
        "INGEST_AUTH_TOKEN",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("RAG_STUDENT_TOKEN", "distinct-human-student-token")
    monkeypatch.setattr(endpoint, "_get_embed_model", lambda: DeterministicEmbedder())
    monkeypatch.setattr(endpoint, "_get_reranker", lambda: PilotFixtureReranker())
    close_pool()
    app = FastAPI()
    app.include_router(endpoint.router)
    client = TestClient(app)
    real_endpoint_hits = endpoint._retrieve_endpoint_hits
    retrieval_calls: list[str] = []

    def counted_endpoint_hits(
        query: str,
        collection: str,
        k: int,
        scope: ServerRetrievalScope,
    ) -> list[endpoint.SearchV2Hit]:
        retrieval_calls.append(collection)
        return real_endpoint_hits(query, collection, k, scope)

    monkeypatch.setattr(endpoint, "_retrieve_endpoint_hits", counted_endpoint_hits)
    identity_token = _signed_identity_token()
    nsi_only_identity_token = _signed_identity_token(matieres=("nsi",))
    maths_only_identity_token = _signed_identity_token(matieres=("maths",))
    verified = verify_identity_token(
        identity_token,
        config=load_identity_verifier_config(),
    )
    collection_config = endpoint.load_collection_config()
    scope = endpoint.build_server_retrieval_scope(
        verified,
        collection=MATRIX_COLLECTIONS["nsi"],
        collection_config=collection_config,
    )
    direct_hits = retrieve_hybrid(
        QUERY,
        MATRIX_COLLECTIONS["nsi"],
        5,
        store=PgCandidateStore(_app_store_connection, scope),
        embedder=DeterministicEmbedder(),
        reranker=PilotFixtureReranker(),
    )
    assert [hit.candidate.chunk_id for hit in direct_hits] == [
        "matrix-nsi-individuel",
    ]

    cross_subject_response = client.post(
        "/search/v2",
        headers={
            "Authorization": f"Bearer {service_token}",
            "X-Nexus-Identity": maths_only_identity_token,
        },
        json={
            **_retrieval_request_payload(matiere="nsi"),
        },
    )
    assert cross_subject_response.status_code == 403
    assert cross_subject_response.json() == {"detail": "Forbidden"}
    assert retrieval_calls == []

    response = client.post(
        "/search/v2",
        headers={
            "Authorization": f"Bearer {service_token}",
            "X-Nexus-Identity": nsi_only_identity_token,
        },
        json={
            **_retrieval_request_payload(matiere="nsi"),
        },
    )

    assert response.status_code == 200, response.text
    assert [hit["chunk_id"] for hit in response.json()["results"]] == [
        "matrix-nsi-individuel",
    ]
    assert retrieval_calls == [MATRIX_COLLECTIONS["nsi"]]
    nsi_readiness = client.get(
        "/collections/readiness",
        headers={
            "Authorization": f"Bearer {service_token}",
            "X-Nexus-Identity": nsi_only_identity_token,
        },
    )
    assert nsi_readiness.status_code == 200, nsi_readiness.text
    assert [
        item["name"] for item in nsi_readiness.json()["collections"]
    ] == [MATRIX_COLLECTIONS["nsi"]]
    print("MONO_SUBJECT_HTTP_SCOPE=PASS")
    readiness = client.get(
        "/collections/readiness",
        headers={
            "Authorization": f"Bearer {service_token}",
            "X-Nexus-Identity": identity_token,
        },
    )
    assert readiness.status_code == 200, readiness.text
    readiness_payload = readiness.json()
    assert readiness_payload["launch_ready"] is False
    assert readiness_payload["release_evidence_verified"] is False
    assert readiness_payload["total_collections"] == 2
    assert {
        item["name"]: item["reviewed_chunks"]
        for item in readiness_payload["collections"]
    } == {
        MATRIX_COLLECTIONS["maths"]: 1,
        MATRIX_COLLECTIONS["nsi"]: 1,
    }
    client.close()
    close_pool()
    print("SIGNED_IDENTITY_HTTP_REAL_DB=PASS")


def test_http_chat_is_locked_with_zero_or_real_hits_and_never_calls_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PG_RAG_DSN", APP_DSN)
    monkeypatch.setenv("OPENROUTER_API_KEY", "lot40-fake-key-never-used")
    active_reranker: dict[str, object] = {"value": EmptyReranker()}
    monkeypatch.setattr(endpoint, "_get_embed_model", lambda: DeterministicEmbedder())
    monkeypatch.setattr(endpoint, "_get_reranker", lambda: active_reranker["value"])
    network_calls = 0

    def network_must_not_run(*args: object, **kwargs: object) -> None:
        nonlocal network_calls
        network_calls += 1
        raise AssertionError("network generation forbidden in LOT40")

    monkeypatch.setattr(endpoint, "_openrouter_answer", network_must_not_run, raising=False)
    close_pool()
    client = _test_app(monkeypatch)
    profile = {
        "niveau": "terminale",
        "voie": "generale",
        "matieres": ["nsi"],
        "statut_enseignement": "specialite",
        "candidat": "individuel",
        "school_year": "2026-2027",
        "zone": "libre",
    }
    base_request = {
        "student_profile": profile,
        "query": QUERY,
        "collections": [TARGET_COLLECTION],
        "top_k": 3,
        "include_retrieval": True,
    }

    empty = client.post("/chat", json=base_request)
    assert empty.status_code == 200, empty.text
    assert empty.json()["refusal_reason"] == "answer_generation_locked"
    assert empty.json()["grounded"] is False
    assert empty.json()["citations"] == []
    assert empty.json()["retrieval_hits"] == []

    active_reranker["value"] = DeterministicReranker()
    populated = client.post("/chat", json=base_request)
    assert populated.status_code == 200, populated.text
    assert populated.json()["refusal_reason"] == "answer_generation_locked"
    assert populated.json()["grounded"] is False
    assert populated.json()["citations"] == []
    assert len(populated.json()["retrieval_hits"]) == 3
    retrieval_ids = {
        hit["chunk_id"] for hit in populated.json()["retrieval_hits"]
    }
    assert "target-lexical-only" in retrieval_ids
    assert populated.json()["retrieval_hits"][0]["chunk_id"] in {
        "target-dense-only",
        "target-lexical-only",
    }

    hidden_request = dict(base_request, include_retrieval=False)
    hidden = client.post("/chat", json=hidden_request)
    assert hidden.status_code == 200
    assert hidden.json()["refusal_reason"] == "answer_generation_locked"
    assert hidden.json()["retrieval_hits"] == []
    assert hidden.json()["citations"] == []
    assert network_calls == 0
    client.close()
    close_pool()
    print("HTTP_CHAT_LOCKED=PASS")


def test_review_idor_promotion_revocation_and_no_reactivation_are_real(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified = SimpleNamespace(scope_digest="a" * 64)
    monkeypatch.setattr(
        review_endpoint,
        "_require_review_identity",
        lambda *_args, **_kwargs: verified,
    )
    monkeypatch.setattr(
        review_endpoint,
        "_load_review_scopes",
        lambda *_args, **_kwargs: (_scope(TARGET_COLLECTION),),
    )
    monkeypatch.setattr(review_endpoint, "_get_pg_dsn", lambda: REVIEW_DSN)
    app = FastAPI()
    app.include_router(review_endpoint.router)
    client = TestClient(app)

    idor_target = "doc-review-idor-outside"
    idor = client.post(
        "/review/v2/decide",
        json={
            "target_type": "doc",
            "target_id": idor_target,
            "decision": "reviewed",
            "tenant": TENANT,
        },
    )
    assert idor.status_code == 404
    assert idor.json() == {"detail": "review target unavailable"}
    assert idor_target not in idor.text
    with psycopg.connect(ADMIN_DSN) as connection:
        assert connection.execute(
            "SELECT review_status FROM rag_chunks WHERE chunk_id = %s",
            ("review-idor-outside",),
        ).fetchone()[0] == "needs_review"

    target = "doc-pending-000"
    promoted = client.post(
        "/review/v2/decide",
        json={
            "target_type": "doc",
            "target_id": target,
            "decision": "reviewed",
            "tenant": TENANT,
        },
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["chunks_affected"] == 1
    assert promoted.json()["max_stale_other_workers_s"] == 0

    revoked = client.post(
        "/review/v2/decide",
        json={
            "target_type": "doc",
            "target_id": target,
            "decision": "quarantined",
            "tenant": TENANT,
        },
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["chunks_affected"] == 1

    reactivation = client.post(
        "/review/v2/decide",
        json={
            "target_type": "doc",
            "target_id": target,
            "decision": "reviewed",
            "tenant": TENANT,
        },
    )
    assert reactivation.status_code == 404
    assert reactivation.json() == {"detail": "review target unavailable"}
    with psycopg.connect(ADMIN_DSN) as connection:
        assert connection.execute(
            "SELECT review_status FROM rag_chunks WHERE chunk_id = %s",
            ("pending-000",),
        ).fetchone()[0] == "quarantined"

    client.close()
    print("REVIEW_SCOPED_IDOR_AND_REVOCATION=PASS")
