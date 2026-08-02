"""Preuves LOT40 sur une base PostgreSQL/pgvector ephemere reelle."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nexus_contracts import Rights, load_pilot_retrieval_scope

from ingestor import retrieval_v2_endpoint as endpoint
from ingestor import review_v2_endpoint as review_endpoint
from ingestor.identity_v2 import load_identity_verifier_config, verify_identity_token
from ingestor.pg_pool import close_pool
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
from ingestor.schema_readiness_v2 import schema_head_003_ready

pytestmark = pytest.mark.integration

APP_DSN = os.environ.get("LOT40_PG_DSN", "").strip()
ADMIN_DSN = os.environ.get("LOT40_PG_ADMIN_DSN", "").strip()
REVIEW_DSN = os.environ.get("LOT41_PG_REVIEW_DSN", "").strip()
if not APP_DSN or not ADMIN_DSN or not REVIEW_DSN:
    pytest.skip(
        "DSN applicatif, admin et review requis par le runner ephemere",
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


def _scope_sql_params(collection: str) -> tuple[object, ...]:
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
            cursor.execute("TRUNCATE TABLE rag_chunks")
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
        connection.execute("TRUNCATE TABLE rag_chunks")


@contextmanager
def _app_store_connection() -> Iterator[psycopg.Connection[Any]]:
    """Connexion applicative brute; seul le store active pgvector et strict_order."""

    with psycopg.connect(APP_DSN) as connection:
        yield connection


@contextmanager
def _empirical_plan_store_connection() -> Iterator[psycopg.Connection[Any]]:
    """Connexion de preuve réglée pour comparer la fixture distincte à l'oracle."""

    with psycopg.connect(APP_DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL hnsw.ef_search = 40")
            cursor.execute("SET LOCAL hnsw.max_scan_tuples = 100000")
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
        *_scope_sql_params(collection),
        _DENSE_ANN_PROBE_LIMIT,
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
    print("APP_ROLE_NON_SUPERUSER_SELECT_ONLY=PASS")


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
    assert review_database_ready(REVIEW_DSN) is True
    print("REVIEW_ROLE_COLUMN_LEVEL_UPDATE_ONLY=PASS")


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


def test_schema_registry_and_real_migration_objects_are_exact() -> None:
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
    }
    with psycopg.connect(ADMIN_DSN) as connection:
        rows = connection.execute(
            "SELECT version, file_name, sha256 FROM rag_schema_migrations ORDER BY version"
        ).fetchall()
        assert rows == [(version, *expected[version]) for version in (1, 2, 3)]
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
    assert schema_head_003_ready(APP_DSN) is True
    print("MIGRATION_OBJECTS_REAL_DB=PASS")


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

    empirical_store = PgCandidateStore(
        _empirical_plan_store_connection,
        _scope(TARGET_COLLECTION),
    )
    actual = empirical_store.dense(
        query_vector=QUERY_VECTOR,
        collection=TARGET_COLLECTION,
        limit=50,
    )
    with psycopg.connect(APP_DSN) as connection:
        connection.execute("SET LOCAL enable_indexscan = off")
        connection.execute("SET LOCAL enable_bitmapscan = off")
        expected_rows = connection.execute(
            _DENSE_ORACLE_SQL,
            (*_scope_sql_params(TARGET_COLLECTION), QUERY_VECTOR_TEXT),
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
        limited = empirical_store.dense(
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
    print("HNSW_DISTINCT_FIXTURE_EMPIRICAL_ORACLE_PREFIX=PASS")
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
            else:
                ordinal = int(text.rsplit(" ", 1)[1])
                scores.append(2.50 - ordinal / 1000)
        return scores


class EmptyReranker:
    def predict(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]:
        return [0.0] * len(pairs)


class PilotFixtureReranker:
    def predict(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]:
        assert all(query == QUERY for query, _text in pairs)
        return [2.60] * len(pairs)


def test_real_store_and_core_prove_union_scores_page_dedup_and_dimension_failure() -> None:
    store = PgCandidateStore(_app_store_connection, _scope(TARGET_COLLECTION))
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
    monkeypatch.setattr(endpoint, "load_collection_config", lambda: {})
    monkeypatch.setattr(endpoint, "_check_retrievable", lambda *args, **kwargs: {})
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
        json={"q": QUERY, "collection": TARGET_COLLECTION, "k": 5},
    )
    assert failed.status_code == 503
    assert failed.json() == {"detail": "retrieval unavailable"}
    assert APP_DSN not in failed.text

    monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", real_retrieve)
    response = client.post(
        "/search/v2",
        json={"q": QUERY, "collection": TARGET_COLLECTION, "k": 5},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["returned"] == 5
    assert [hit["chunk_id"] for hit in payload["hits"][:2]] == [
        "target-dense-only",
        "target-lexical-only",
    ]
    assert payload["hits"][0]["page"] is None
    assert payload["hits"][1]["page"] == 7
    assert all(hit["review_status"] == "reviewed" for hit in payload["hits"])
    assert all(hit["source_label"] and hit["source_uri"] and hit["rights"] for hit in payload["hits"])
    assert all(
        key in payload["hits"][0]
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
            "q": QUERY,
            "collection": MATRIX_COLLECTIONS["nsi"],
            "k": 5,
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
            "q": QUERY,
            "collection": MATRIX_COLLECTIONS["nsi"],
            "k": 5,
        },
    )

    assert response.status_code == 200, response.text
    assert [hit["chunk_id"] for hit in response.json()["hits"]] == [
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
    assert populated.json()["retrieval_hits"][0]["chunk_id"] == "target-dense-only"

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
