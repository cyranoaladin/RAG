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


#: The exact sealed chunk authority for the single chunk ``_seed`` inserts:
#: chunk-001, index 0, chunk_sha256=SHA_B, pages 2-4, owned by SHA_A.
SEALED_CHUNK_BINDING = (SHA_A, "chunk-001", 0, SHA_B, 2, 4)


def _export(
    pg: dict[str, str],
    *,
    artifact_bindings: frozenset[tuple[str, str]] | None = None,
    chunk_bindings: frozenset[tuple[str, str, int, str, int, int]] | None = None,
):
    with psycopg.connect(superuser_dsn(pg)) as connection:
        return export_resource_registry_bootstrap_inventory(
            connection,
            producer_repository="cyranoaladin/RAG",
            producer_commit=SHA_B[:40],
            generated_at=GENERATED_AT,
            package_version="0.15.0",
            release_collections=frozenset({"terminale_maths"}),
            release_artifact_bindings=artifact_bindings
            or frozenset({("terminale_maths", SHA_A)}),
            release_chunk_bindings=chunk_bindings or frozenset({SEALED_CHUNK_BINDING}),
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
            # A real, authoritative placement for SHA_B too -- otherwise the
            # observed_bindings guard (scoped by real placements, not by
            # rag_artifacts rows alone) refuses this fixture before ever
            # reaching the identity-collision check this test targets.
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
                    'reviewed', 'fixture-scope', 'fixture-placement-dup',
                    '/governed/private/programme.pdf', %s, 'fixture-auth',
                    '66666666-6666-4666-8666-666666666666'
                )
                """,
                ("f" * 64, SHA_B, SOURCE_URI),
            )
        connection.commit()

    with pytest.raises(BootstrapInventoryError, match="multiple RAG artifacts"):
        _export(
            pg,
            artifact_bindings=frozenset(
                {("terminale_maths", SHA_A), ("terminale_maths", SHA_B)}
            ),
        )


SECOND_PLACEMENT_ID = "e" * 64
SECOND_COLLECTION = "terminale_nsi"


def _seed_second_placement(connection: psycopg.Connection) -> None:
    """The same physical artifact/chunk seeded by ``_seed`` is also placed in
    a second, legitimately different collection -- the real shape of a
    première/terminale common-trunk resource shared across subjects."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO public.rag_artifact_placements (
                placement_id, artifact_id, collection, tenant, niveau, voie,
                audience, matiere, statut_enseignement, candidat, visibility,
                school_year, programme_version, currentness, placement_status,
                review_status, source_scope, source_placement_id, source_path,
                source_uri, authorization_id, publication_attestation_id
            ) VALUES (
                %s, %s, %s, 'nexus', 'terminale', 'generale',
                ARRAY['aefe'], 'mathematiques', 'specialite', 'scolarise',
                'internal', '2026-2027', 'fr-national-2026', 'current', 'active',
                'reviewed', 'fixture-scope', 'fixture-placement-2',
                '/governed/private/programme.pdf', %s, 'fixture-auth',
                '55555555-5555-4555-8555-555555555555'
            )
            """,
            (SECOND_PLACEMENT_ID, SHA_A, SECOND_COLLECTION, SOURCE_URI),
        )
    connection.commit()


def test_real_snapshot_reaches_a_shared_artifact_in_its_second_placement(
    pg: dict[str, str],
) -> None:
    with psycopg.connect(superuser_dsn(pg)) as connection:
        _seed(connection)
        _seed_second_placement(connection)

    with psycopg.connect(superuser_dsn(pg)) as connection:
        inventory = export_resource_registry_bootstrap_inventory(
            connection,
            producer_repository="cyranoaladin/RAG",
            producer_commit=SHA_B[:40],
            generated_at=GENERATED_AT,
            package_version="0.15.0",
            release_collections=frozenset({"terminale_maths", SECOND_COLLECTION}),
            release_artifact_bindings=frozenset(
                {("terminale_maths", SHA_A), (SECOND_COLLECTION, SHA_A)}
            ),
            release_chunk_bindings=frozenset({SEALED_CHUNK_BINDING}),
        )

    assert len(inventory.resources) == 1
    item = inventory.resources[0]
    assert len(item.chunks) == 1
    assert len(item.placements) == 2
    assert {p.collection for p in item.placements} == {"terminale_maths", SECOND_COLLECTION}


def test_missing_release_placement_binding_fails_closed(pg: dict[str, str]) -> None:
    """The second placement physically exists but the release registry never
    promoted it -- the exact bindings guard must still refuse a subset."""
    with psycopg.connect(superuser_dsn(pg)) as connection:
        _seed(connection)
        _seed_second_placement(connection)

    with pytest.raises(BootstrapInventoryError, match="exact promoted release"):
        _export(pg, artifact_bindings=frozenset({("terminale_maths", SHA_A)}))


def test_unknown_extra_release_placement_binding_fails_closed(pg: dict[str, str]) -> None:
    """The release registry claims a placement that does not physically
    exist -- the exact bindings guard must refuse a superset too."""
    with psycopg.connect(superuser_dsn(pg)) as connection:
        _seed(connection)

    with pytest.raises(BootstrapInventoryError, match="exact promoted release"):
        with psycopg.connect(superuser_dsn(pg)) as connection:
            export_resource_registry_bootstrap_inventory(
                connection,
                producer_repository="cyranoaladin/RAG",
                producer_commit=SHA_B[:40],
                generated_at=GENERATED_AT,
                package_version="0.15.0",
                release_collections=frozenset({"terminale_maths", SECOND_COLLECTION}),
                release_artifact_bindings=frozenset(
                    {("terminale_maths", SHA_A), (SECOND_COLLECTION, SHA_A)}
                ),
                release_chunk_bindings=frozenset({SEALED_CHUNK_BINDING}),
            )


# ---------------------------------------------------------------------------
# R1A -- same-(artifact, collection) semantic-placement hole.
#
# ``observed_bindings`` is a set of exactly (collection, content_sha256)
# pairs: it can only ever prove or refuse WHICH collections a given artifact
# reaches, never what a placement inside an already-authorized collection
# actually asserts about candidat/audience/visibility/etc. A second placement
# row sharing the anchor's own (collection, sha256) contributes no new
# element to that set -- it is structurally invisible to the guard, whatever
# it says on every dimension the guard does not look at.
# ---------------------------------------------------------------------------

CONFLICTING_PLACEMENT_ID = "d" * 64


def _seed_conflicting_same_collection_placement(
    connection: psycopg.Connection, *, candidat: str
) -> None:
    """A second, DIFFERENT placement row for the SAME artifact in the SAME
    collection as the one seeded by ``_seed`` -- differing only in
    ``candidat`` (an authorization-relevant dimension). Every dimension the
    ``observed_bindings`` guard actually compares (collection, sha256) is
    identical to the legitimate placement, so this row is designed to be
    invisible to it."""
    with connection.cursor() as cursor:
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
                ARRAY['aefe'], 'mathematiques', 'specialite', %s,
                'internal', '2026-2027', 'fr-national-2026', 'current', 'active',
                'reviewed', 'fixture-scope', 'fixture-placement-conflict',
                '/governed/private/programme.pdf', %s, 'fixture-auth',
                '77777777-7777-4777-8777-777777777777'
            )
            """,
            (CONFLICTING_PLACEMENT_ID, SHA_A, candidat, SOURCE_URI),
        )
    connection.commit()


def test_same_collection_placement_with_different_candidat_fails_closed(
    pg: dict[str, str],
) -> None:
    """GREEN (was RED): the (collection, sha256) binding-set guard alone
    cannot detect a spurious same-collection placement asserting a
    DIFFERENT ``candidat`` than the one legitimately promoted for that
    collection -- ``_validate_placements``'s per-collection semantic
    consistency check now closes exactly that gap. The release registry
    only ever authorized ``scolarise`` for ``terminale_maths``; a second,
    conflicting ``libre`` placement in that same collection must refuse the
    export outright rather than silently ship both."""
    with psycopg.connect(superuser_dsn(pg)) as connection:
        _seed(connection)  # candidat="scolarise", the only ever-promoted value
        _seed_conflicting_same_collection_placement(connection, candidat="libre")

    with pytest.raises(BootstrapInventoryError, match="conflicting semantic placements"):
        _export(pg)


def test_same_collection_placement_with_different_visibility_fails_closed(
    pg: dict[str, str],
) -> None:
    """Same proof, second independent dimension: visibility."""
    with psycopg.connect(superuser_dsn(pg)) as connection_scope:
        _seed(connection_scope)
        with connection_scope.cursor() as cursor:
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
                    'public', '2026-2027', 'fr-national-2026', 'current', 'active',
                    'reviewed', 'fixture-scope', 'fixture-placement-conflict-vis',
                    '/governed/private/programme.pdf', %s, 'fixture-auth',
                    '88888888-8888-4888-8888-888888888888'
                )
                """,
                ("9" * 64, SHA_A, SOURCE_URI),
            )
        connection_scope.commit()

    with pytest.raises(BootstrapInventoryError, match="conflicting semantic placements"):
        _export(pg)


# Note: a THIRD case -- two placement rows sharing one collection with an
# otherwise IDENTICAL semantic tuple -- is not exercised here because
# ``rag_artifact_placements_canonical_scope_unique`` (migration 004) already
# makes that state unreachable at the schema level: it is a table-wide
# UNIQUE constraint on exactly
# (artifact_id, collection, tenant, niveau, voie, audience, matiere,
# statut_enseignement, candidat, visibility, school_year, programme_version).
# The new check above only ever has work to do because that constraint's key
# is the full semantic tuple, not (collection, sha256) alone -- it does not
# by itself prevent two DIFFERENT semantic tuples from sharing a collection.


# ---------------------------------------------------------------------------
# R1G -- exact chunk-release binding.
#
# ``observed_bindings`` (above) is keyed by (collection, content_sha256): it
# proves WHICH artifacts are reachable, never WHICH individual chunk rows the
# DB actually holds for them. These cases prove the new chunk-set guard in
# ``export_resource_registry_bootstrap_inventory`` closes that gap for real
# PostgreSQL rows -- the R1 pré-GO forensic reproduced all three of extra/
# missing/swapped chunk acceptance against the pre-R1G exporter (cases A, B,
# C below). Case D (wrong ``chunk_sha256``, same id and locator) and case E
# (wrong locator) prove the guard checks every dimension of the canonical
# tuple, not merely presence/absence of a chunk_id. Case F proves a chunk
# reattributed to the wrong sealed artifact is refused. Cases G (legitimate
# multi-placement dedup) and H (exact sealed set) are already exercised above
# by ``test_real_snapshot_reaches_a_shared_artifact_in_its_second_placement``
# and ``test_real_snapshot_is_deterministic_exact_and_non_mutating``, both of
# which now go through the same chunk-set guard via ``_export``'s default.
# ---------------------------------------------------------------------------


def _insert_chunk(
    connection: psycopg.Connection,
    *,
    chunk_id: str,
    chunk_sha256: str,
    chunk_index: int,
    page_start: int,
    page_end: int,
    artifact_id: str = SHA_A,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO public.rag_chunks (
                chunk_id, doc_id, chunk_sha256, collection, niveau, voie,
                audience, matiere, statut_enseignement, source_label, source_uri,
                rights, type_doc, official, text, chunk_index, page_start, page_end,
                review_status, source_kind, tenant, candidat, visibility,
                school_year, programme_version, artifact_id
            ) VALUES (
                %s, %s, %s, 'terminale_maths', 'terminale', 'generale',
                ARRAY['aefe'], 'mathematiques', 'specialite', %s, %s,
                'officiel_public', 'programme_officiel', true,
                'SENSITIVE CHUNK TEXT NOT FOR EXPORT', %s, %s, %s, 'reviewed',
                'eduscol.education.fr', 'nexus', 'scolarise', 'internal',
                '2026-2027', 'fr-national-2026', %s
            )
            """,
            (
                chunk_id,
                artifact_id,
                chunk_sha256,
                "Programme officiel de mathématiques",
                SOURCE_URI,
                chunk_index,
                page_start,
                page_end,
                artifact_id,
            ),
        )
    connection.commit()


def test_extra_chunk_on_sealed_artifact_fails_closed(pg: dict[str, str]) -> None:
    """R1G case A: the release seals exactly chunk-001; the DB additionally
    holds a second, well-formed chunk on the same sealed artifact. The
    pre-R1G exporter accepted this silently -- the new chunk-set guard must
    refuse it before the bootstrap is built."""
    with psycopg.connect(superuser_dsn(pg)) as connection:
        _seed(connection)
        _insert_chunk(
            connection,
            chunk_id="chunk-002",
            chunk_sha256="c" * 64,
            chunk_index=1,
            page_start=5,
            page_end=6,
        )

    with pytest.raises(BootstrapInventoryError, match="exact sealed release chunk"):
        _export(pg)


def test_missing_sealed_chunk_fails_closed(pg: dict[str, str]) -> None:
    """R1G case B: the release seals two chunks for SHA_A but the DB only
    ever held one -- a chunk silently disappeared between sealing and
    export."""
    with psycopg.connect(superuser_dsn(pg)) as connection:
        _seed(connection)

    missing_binding = (SHA_A, "chunk-002", 1, "c" * 64, 5, 6)
    with pytest.raises(BootstrapInventoryError, match="exact sealed release chunk"):
        _export(pg, chunk_bindings=frozenset({SEALED_CHUNK_BINDING, missing_binding}))


def test_same_count_swapped_chunk_id_fails_closed(pg: dict[str, str]) -> None:
    """R1G case C: cardinality is preserved (one chunk expected, one chunk
    found) but the DB's actual chunk_id was substituted for a different,
    otherwise well-formed one -- an equal-count set substitution the old
    (collection, content_sha256)-keyed guard could never see."""
    with psycopg.connect(superuser_dsn(pg)) as connection:
        _seed(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE public.rag_chunks SET chunk_id = 'chunk-swapped' "
                "WHERE chunk_id = 'chunk-001'"
            )
        connection.commit()

    with pytest.raises(BootstrapInventoryError, match="exact sealed release chunk"):
        _export(pg)


def test_wrong_chunk_sha256_blocked_before_bootstrap_publication(pg: dict[str, str]) -> None:
    """R1G case D: same chunk_id, same locator, but the DB's real content
    digest for that chunk diverges from the sealed release's. Must fail on
    the exporter side, before any bootstrap is published -- chunk_sha256
    never reaches the BootstrapChunk contract for a downstream check to
    catch this instead."""
    with psycopg.connect(superuser_dsn(pg)) as connection:
        _seed(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE public.rag_chunks SET chunk_sha256 = %s WHERE chunk_id = 'chunk-001'",
                ("f" * 64,),
            )
        connection.commit()

    with pytest.raises(BootstrapInventoryError, match="exact sealed release chunk"):
        _export(pg)


def test_wrong_chunk_locator_fails_closed(pg: dict[str, str]) -> None:
    """R1G case E: same chunk_id and chunk_sha256, but the DB's page range
    diverges from the sealed release's declared locator."""
    with psycopg.connect(superuser_dsn(pg)) as connection:
        _seed(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE public.rag_chunks SET page_start = 9, page_end = 10 "
                "WHERE chunk_id = 'chunk-001'"
            )
        connection.commit()

    with pytest.raises(BootstrapInventoryError, match="exact sealed release chunk"):
        _export(pg)


SECOND_ARTIFACT_SHA = "c" * 64
SECOND_ARTIFACT_VERSION_ID = UUID("55555555-5555-4555-8555-555555555555")
SECOND_RESOURCE_ID = UUID("66666666-6666-4666-8666-666666666666")


def _seed_second_artifact_with_own_chunk(connection: psycopg.Connection) -> None:
    """A genuinely distinct sealed resource/artifact/placement/chunk, in the
    same collection as ``_seed``'s SHA_A, used to prove a chunk reattributed
    to the WRONG real sealed artifact is refused -- not merely a chunk that
    vanished or was invented from nothing. Its own resource_id (not
    ``RESOURCE_ID``): ``ingestion_control.resources`` scopes one physical
    ingestion, and reusing the first resource's row here would conflate two
    unrelated documents under one dedup identity."""
    scope = _scope()
    with connection.cursor() as cursor:
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
            {
                "resource_id": SECOND_RESOURCE_ID,
                "run_id": RUN_ID,
                "dedup_key": SECOND_ARTIFACT_SHA,
                **scope,
            },
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
                SECOND_ARTIFACT_VERSION_ID,
                SECOND_RESOURCE_ID,
                RUN_ID,
                SECOND_ARTIFACT_SHA,
                SOURCE_URI,
                SOURCE_URI,
                json.dumps(
                    {
                        **_artifact_payload(),
                        "artifact_id": str(SECOND_ARTIFACT_VERSION_ID),
                        "resource_id": str(SECOND_RESOURCE_ID),
                        "sha256": SECOND_ARTIFACT_SHA,
                    }
                ),
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
                SECOND_ARTIFACT_VERSION_ID,
                SECOND_RESOURCE_ID,
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
                SECOND_ARTIFACT_SHA,
                SECOND_ARTIFACT_SHA,
                "Programme officiel de mathématiques",
                SOURCE_URI,
                "officiel_public",
                "eduscol.education.fr",
                "programme_officiel",
                SECOND_ARTIFACT_VERSION_ID,
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
                'reviewed', 'fixture-scope', 'fixture-placement-second-artifact',
                '/governed/private/programme.pdf', %s, 'fixture-auth',
                'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
            )
            """,
            ("b" * 63 + "1", SECOND_ARTIFACT_SHA, SOURCE_URI),
        )
    connection.commit()
    _insert_chunk(
        connection,
        chunk_id="chunk-second",
        chunk_sha256="d" * 64,
        # index 1, not 0: SHA_A already owns a chunk at index 0 (chunk-001)
        # and idx_rag_chunks_artifact_chunk_index_unique forbids two chunks
        # sharing (artifact_id, chunk_index) -- the reattribution below must
        # not collide with it.
        chunk_index=1,
        page_start=1,
        page_end=1,
        artifact_id=SECOND_ARTIFACT_SHA,
    )


def test_chunk_wrong_artifact_fails_closed(pg: dict[str, str]) -> None:
    """R1G case F: two real sealed artifacts, each with its own real chunk --
    then the DB's ``chunk-second`` row is reattributed from its true owner
    (SECOND_ARTIFACT_SHA) to SHA_A. The sealed release still declares
    ``chunk-second`` under SECOND_ARTIFACT_SHA: the guard must see this both
    as an unsealed chunk appearing under SHA_A and as SECOND_ARTIFACT_SHA's
    own sealed chunk going missing."""
    with psycopg.connect(superuser_dsn(pg)) as connection:
        _seed(connection)
        _seed_second_artifact_with_own_chunk(connection)
        with connection.cursor() as cursor:
            # ``rag_chunks_governed_identity_check`` (migration 004) requires
            # doc_id = artifact_id for every governed chunk -- a real
            # misattribution moves both together, it can never move only one.
            cursor.execute(
                "UPDATE public.rag_chunks SET artifact_id = %s, doc_id = %s "
                "WHERE chunk_id = 'chunk-second'",
                (SHA_A, SHA_A),
            )
        connection.commit()

    second_artifact_binding = (SECOND_ARTIFACT_SHA, "chunk-second", 1, "d" * 64, 1, 1)
    with pytest.raises(BootstrapInventoryError, match="exact sealed release chunk"):
        _export(
            pg,
            artifact_bindings=frozenset(
                {("terminale_maths", SHA_A), ("terminale_maths", SECOND_ARTIFACT_SHA)}
            ),
            chunk_bindings=frozenset({SEALED_CHUNK_BINDING, second_artifact_binding}),
        )
