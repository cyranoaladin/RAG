"""Real PostgreSQL proof for the cross-schema Resource Registry export."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pg_authority import (  # noqa: E402
    PG_SUPERUSER,
    PG_SUPERUSER_PASSWORD,
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)

from ingestor.resource_registry_bootstrap import (  # noqa: E402
    BootstrapInventoryError,
    export_resource_registry_bootstrap_inventory,
)

pytestmark = [pytest.mark.integration, requires_docker]

PRODUCT_MIGRATIONS = (
    "001_rag_chunks_v2_schema.sql",
    "002_hybrid_retrieval.sql",
    "003_profile_filtering.sql",
    "004_artifact_placements.sql",
)
RESOURCE_ID = UUID("11111111-1111-4111-8111-111111111111")
VERSION_ID = UUID("22222222-2222-4222-8222-222222222222")
RUN_ID = UUID("33333333-3333-4333-8333-333333333333")
SHA_A = "a" * 64
SHA_B = "b" * 64
SOURCE_URI = "https://eduscol.education.fr/programme.pdf"
GENERATED_AT = datetime(2026, 8, 30, 12, tzinfo=UTC)


def _apply_product_migrations(pg: dict[str, str]) -> None:
    directory = ENGINE_ROOT / "infra" / "postgres" / "migrations"
    for name in PRODUCT_MIGRATIONS:
        result = subprocess.run(
            [
                "psql",
                "-X",
                "-q",
                "-v",
                "ON_ERROR_STOP=1",
                "-h",
                pg["host"],
                "-p",
                pg["port"],
                "-U",
                PG_SUPERUSER,
                "-d",
                pg["dbname"],
                "-f",
                str(directory / name),
            ],
            env={"PGPASSWORD": PG_SUPERUSER_PASSWORD, "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{name}: {result.stderr}"


@pytest.fixture(scope="module")
def pg() -> Iterator[dict[str, str]]:
    for instance in start_ingestion_control_postgres("resource-bootstrap"):
        _apply_product_migrations(instance)
        yield instance


@pytest.fixture(autouse=True)
def _clean(pg: dict[str, str]) -> Iterator[None]:
    with psycopg.connect(superuser_dsn(pg)) as connection, connection.cursor() as cursor:
        cursor.execute(
            "TRUNCATE TABLE public.rag_chunks, public.rag_artifact_placements, "
            "public.rag_artifacts"
        )
        for table in (
            "artifact_attributions",
            "artifacts",
            "resource_candidates",
            "jobs",
            "resources",
            "ingestion_runs",
        ):
            cursor.execute(f"DELETE FROM ingestion_control.{table}")  # noqa: S608
        connection.commit()
    yield


def _scope() -> dict[str, object]:
    return {
        "tenant": "nexus",
        "collection": "terminale_maths",
        "niveau": "terminale",
        "voie": "generale",
        "matiere": "mathematiques",
        "candidat": "scolarise",
        "audience": ["aefe"],
        "visibility": "internal",
        "school_year": "2026-2027",
        "programme_version": "fr-national-2026",
    }


def _artifact_payload() -> dict[str, object]:
    return {
        "artifact_id": str(VERSION_ID),
        "resource_id": str(RESOURCE_ID),
        "run_id": str(RUN_ID),
        "scope": _scope(),
        "sha256": SHA_A,
        "size_bytes": 42,
        "mime_declared": "application/pdf",
        "mime_detected": "application/pdf",
        "original_url": SOURCE_URI,
        "final_url": SOURCE_URI,
        "collected_at": "2026-08-30T10:00:00Z",
        "domain": "eduscol.education.fr",
        "publisher": "Ministère de l'Éducation nationale",
        "title": "Programme officiel de mathématiques",
        "license": "Licence Ouverte 2.0",
        "rights_status": "officiel_public",
        "pages_count": 10,
        "version": "2026",
        "extracted_text_ref": "/governed/private/extracted.txt",
    }


def _seed(connection: psycopg.Connection) -> None:
    scope = _scope()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO ingestion_control.ingestion_runs (
                run_id, tenant, collection, niveau, voie, matiere, candidat,
                audience, visibility, school_year, programme_version,
                profile_version, trigger, status
            ) VALUES (
                %(run_id)s, %(tenant)s, %(collection)s, %(niveau)s, %(voie)s,
                %(matiere)s, %(candidat)s, %(audience)s, %(visibility)s,
                %(school_year)s, %(programme_version)s, 'v1', 'manual', 'succeeded'
            )
            """,
            {"run_id": RUN_ID, **scope},
        )
        cursor.execute(
            """
            INSERT INTO ingestion_control.resources (
                resource_id, run_id, dedup_key, tenant, collection, niveau, voie,
                matiere, candidat, audience, visibility, school_year,
                programme_version, resource_state
            ) VALUES (
                %(resource_id)s, %(run_id)s, %(dedup_key)s, %(tenant)s,
                %(collection)s, %(niveau)s, %(voie)s, %(matiere)s, %(candidat)s,
                %(audience)s, %(visibility)s, %(school_year)s,
                %(programme_version)s, 'RETRIEVAL_ELIGIBLE'
            )
            """,
            {"resource_id": RESOURCE_ID, "run_id": RUN_ID, "dedup_key": SHA_B, **scope},
        )
        cursor.execute(
            """
            INSERT INTO ingestion_control.artifacts (
                artifact_id, resource_id, run_id, sha256, size_bytes,
                mime_declared, mime_detected, original_url, final_url, payload
            ) VALUES (
                %s, %s, %s, %s, 42, 'application/pdf', 'application/pdf',
                %s, %s, %s::jsonb
            )
            """,
            (
                VERSION_ID,
                RESOURCE_ID,
                RUN_ID,
                SHA_A,
                SOURCE_URI,
                SOURCE_URI,
                json.dumps(_artifact_payload()),
            ),
        )
        cursor.execute(
            """
            INSERT INTO ingestion_control.artifact_attributions (
                ingestion_artifact_id, resource_id, source_label, official,
                source_kind, type_doc, recorded_by_run_id, recorded_by_actor
            ) VALUES (%s, %s, %s, true, %s, %s, %s, 'fixture')
            """,
            (
                VERSION_ID,
                RESOURCE_ID,
                "Programme officiel de mathématiques",
                "eduscol.education.fr",
                "programme_officiel",
                RUN_ID,
            ),
        )
        cursor.execute(
            """
            INSERT INTO public.rag_artifacts (
                artifact_id, content_sha256, source_label, source_uri, rights,
                official, source_kind, type_doc, ingestion_artifact_id
            ) VALUES (%s, %s, %s, %s, %s, true, %s, %s, %s)
            """,
            (
                SHA_A,
                SHA_A,
                "Programme officiel de mathématiques",
                SOURCE_URI,
                "officiel_public",
                "eduscol.education.fr",
                "programme_officiel",
                VERSION_ID,
            ),
        )
        cursor.execute(
            """
            INSERT INTO public.rag_artifact_placements (
                placement_id, artifact_id, collection, tenant, niveau, voie,
                audience, matiere, statut_enseignement, candidat, visibility,
                school_year, programme_version, currentness, placement_status,
                review_status, source_scope, source_placement_id, source_path,
                source_uri, authorization_id, publication_attestation_id
            ) VALUES (
                %s, %s, 'terminale_maths', 'nexus', 'terminale', 'generale',
                ARRAY['aefe'], 'mathematiques', 'specialite', 'scolarise',
                'internal', '2026-2027', 'fr-national-2026', 'current', 'active',
                'reviewed', 'fixture-scope', 'fixture-placement',
                '/governed/private/programme.pdf', %s, 'fixture-auth',
                '44444444-4444-4444-8444-444444444444'
            )
            """,
            ("c" * 64, SHA_A, SOURCE_URI),
        )
        cursor.execute(
            """
            INSERT INTO public.rag_chunks (
                chunk_id, doc_id, chunk_sha256, collection, niveau, voie,
                audience, matiere, statut_enseignement, source_label, source_uri,
                rights, type_doc, official, text, chunk_index, page_start, page_end,
                review_status, source_kind, tenant, candidat, visibility,
                school_year, programme_version, artifact_id
            ) VALUES (
                'chunk-001', %s, %s, 'terminale_maths', 'terminale', 'generale',
                ARRAY['aefe'], 'mathematiques', 'specialite', %s, %s,
                'officiel_public', 'programme_officiel', true,
                'SENSITIVE CHUNK TEXT NOT FOR EXPORT', 0, 2, 4, 'reviewed',
                'eduscol.education.fr', 'nexus', 'scolarise', 'internal',
                '2026-2027', 'fr-national-2026', %s
            )
            """,
            (SHA_A, SHA_B, "Programme officiel de mathématiques", SOURCE_URI, SHA_A),
        )
    connection.commit()


def _export(pg: dict[str, str], *, artifact_hashes: frozenset[str] | None = None):
    with psycopg.connect(superuser_dsn(pg)) as connection:
        return export_resource_registry_bootstrap_inventory(
            connection,
            producer_repository="cyranoaladin/RAG",
            producer_commit=SHA_B[:40],
            generated_at=GENERATED_AT,
            package_version="0.15.0",
            release_collections=frozenset({"terminale_maths"}),
            release_artifact_sha256s=artifact_hashes or frozenset({SHA_A}),
        )


def test_real_snapshot_is_deterministic_exact_and_non_mutating(pg: dict[str, str]) -> None:
    with psycopg.connect(superuser_dsn(pg)) as connection:
        _seed(connection)

    first = _export(pg)
    second = _export(pg)

    assert first == second
    assert len(first.resources) == 1
    item = first.resources[0]
    assert item.resource_id == RESOURCE_ID
    assert item.resource_version_id == VERSION_ID
    assert item.content_sha256 == SHA_A
    assert item.chunks[0].locator.model_dump(exclude_none=True) == {
        "chunk_index": 0,
        "page_start": 2,
        "page_end": 4,
    }
    serialized = first.model_dump_json()
    assert "SENSITIVE CHUNK TEXT" not in serialized
    assert "/governed/private" not in serialized

    with psycopg.connect(superuser_dsn(pg)) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT (SELECT count(*) FROM ingestion_control.resources), "
            "(SELECT count(*) FROM public.rag_artifacts), "
            "(SELECT count(*) FROM public.rag_chunks)"
        )
        assert cursor.fetchone() == (1, 1, 1)


def test_duplicate_ingestion_artifact_link_fails_closed(pg: dict[str, str]) -> None:
    with psycopg.connect(superuser_dsn(pg)) as connection:
        _seed(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.rag_artifacts (
                    artifact_id, content_sha256, source_label, source_uri, rights,
                    official, source_kind, type_doc, ingestion_artifact_id
                ) VALUES (%s, %s, 'Duplicate', %s, 'officiel_public', true,
                          'eduscol.education.fr', 'programme_officiel', %s)
                """,
                (SHA_B, SHA_B, SOURCE_URI, VERSION_ID),
            )
        connection.commit()

    with pytest.raises(BootstrapInventoryError, match="multiple RAG artifacts"):
        _export(pg, artifact_hashes=frozenset({SHA_A, SHA_B}))
