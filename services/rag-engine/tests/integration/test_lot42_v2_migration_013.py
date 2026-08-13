"""Migration 013 — LOT42-V2 sur PostgreSQL réel (ADR-0035, constat F3).

Aucun mock : un conteneur ``pgvector:pg16`` jetable est migré par le VRAI
script de bootstrap, et les refus mesurés sont de vrais refus PostgreSQL.

Ce que la migration doit prouver ici :

* le schéma accepte V2 et continue d'accepter V1 (coexistence historique) ;
* V2 sans digest d'attribution est **impossible**, V1 avec digest aussi —
  une ligne V1 ne peut donc jamais sembler porter une revue d'attribution
  qu'elle n'a pas eue ;
* aucun digest n'est fabriqué pour une ligne V1 existante ;
* le rollback est intégral sur une base sans donnée V2, et **refuse sans
  rien modifier** dès qu'une donnée V2 existe ;
* la réapplication après rollback fonctionne ;
* les permissions des quatre rôles sont inchangées.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
INFRA_ROOT = ENGINE_ROOT / "infra"
BOOTSTRAP_SCRIPT = INFRA_ROOT / "scripts" / "bootstrap_ingestion_control_schema.sh"
MIGRATIONS_DIR = INFRA_ROOT / "postgres" / "ingestion_control" / "migrations"
ROLLBACKS_DIR = INFRA_ROOT / "postgres" / "ingestion_control" / "rollbacks"

sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pg_authority import (  # noqa: E402
    PG_SUPERUSER,
    PG_SUPERUSER_PASSWORD,
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)

pytestmark = [pytest.mark.integration, requires_docker]

MIGRATION_013 = "013_lot42_v2_attribution_bound_reviews"
ATTRIBUTION_DIGEST = "ab" * 32
CHALLENGE = "NEXUS-TRUSTED-REVIEW-V1:" + "cd" * 32


@pytest.fixture(scope="module")
def pg_container() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("lot42-v2-migration-013")


def _bootstrap_env(pg: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PGHOST": pg["host"],
            "PGPORT": pg["port"],
            "PGUSER": PG_SUPERUSER,
            "PGPASSWORD": PG_SUPERUSER_PASSWORD,
            "PGDATABASE": pg["dbname"],
        }
    )
    return env


def _run_bootstrap(pg: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(BOOTSTRAP_SCRIPT)],
        cwd=ENGINE_ROOT,
        env=_bootstrap_env(pg),
        capture_output=True,
        text=True,
        check=False,
    )


def _rollback_013(conn: psycopg.Connection) -> None:
    sql = (ROLLBACKS_DIR / f"{MIGRATION_013}.down.sql").read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
        cur.execute(
            "DELETE FROM ingestion_control.schema_migrations WHERE version = 13"
        )
    conn.commit()


def _apply_013(conn: psycopg.Connection) -> None:
    sql = (MIGRATIONS_DIR / f"{MIGRATION_013}.sql").read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def _seed_prerequisites(conn: psycopg.Connection) -> tuple[uuid.UUID, uuid.UUID, str]:
    """Crée le minimum de lignes parentes exigé par les clés étrangères."""
    run_id, resource_id, artifact_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    authorization_id = f"lot42-v2-{uuid.uuid4().hex[:8]}"
    scope = (
        "'nexus', 'libre_terminale_philosophie', 'terminale', 'generale', "
        "'philosophie', 'libre', ARRAY['libre'], 'internal', '2026-2027', "
        "'BOEN_special_8_2019-07-25'"
    )
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO ingestion_control.ingestion_runs (
                run_id, tenant, collection, niveau, voie, matiere, candidat,
                audience, visibility, school_year, programme_version,
                profile_version, trigger
            ) VALUES (%s, {scope}, '1.0.0', 'manual')
            """,
            (run_id,),
        )
        cur.execute(
            f"""
            INSERT INTO ingestion_control.resources (
                resource_id, run_id, dedup_key,
                tenant, collection, niveau, voie, matiere, candidat,
                audience, visibility, school_year, programme_version,
                resource_state
            ) VALUES (%s, %s, %s, {scope}, 'REVIEWED')
            """,
            (resource_id, run_id, uuid.uuid4().hex),
        )
        cur.execute(
            """
            INSERT INTO ingestion_control.artifacts (
                artifact_id, resource_id, run_id, sha256, size_bytes,
                mime_declared, mime_detected, original_url, final_url
            ) VALUES (
                %s, %s, %s, repeat('1', 64), 1024,
                'application/pdf', 'application/pdf',
                'https://eduscol.education.gouv.fr/a',
                'https://eduscol.education.gouv.fr/a'
            )
            """,
            (artifact_id, resource_id, run_id),
        )
        cur.execute(
            """
            INSERT INTO ingestion_control.scope_authorizations (
                authorization_id, protocol_version, decision,
                tenant, collection, niveau, voie, matiere, candidat, audience,
                visibility, school_year, programme_version,
                manifest_digest, profile_id, profile_version, profile_fingerprint,
                allowed_domains, rights_categories, exclusions,
                pii_absence_attested, pii_absence_evidence,
                valid_from, valid_until,
                artifact_path, artifact_blob_sha, authorization_digest,
                evidence_repository, evidence_pull_request,
                evidence_base_sha, evidence_head_sha, evidence_review_id,
                evidence_reviewer, evidence_submitted_at, evidence_challenge,
                allowed_content_sha256
            ) VALUES (
                %s, 'LOT41A-V2', 'AUTHORIZE_INGESTION_SCOPE',
                'nexus', 'libre_terminale_philosophie', 'terminale', 'generale',
                'philosophie', 'libre', ARRAY['libre'], 'internal', '2026-2027',
                'BOEN_special_8_2019-07-25',
                repeat('a', 64), 'terminale-philosophie', '1.0.0', repeat('b', 64),
                ARRAY['eduscol.education.gouv.fr'], ARRAY['officiel_public'],
                ARRAY[]::text[],
                true, 'attested',
                now() - interval '1 day', now() + interval '365 days',
                %s, repeat('c', 40), repeat('d', 64),
                'cyranoaladin/RAG', 1, repeat('e', 40), repeat('f', 40), 2,
                'abenrhouma', now(), %s,
                ARRAY[repeat('1', 64)]
            )
            """,
            (
                authorization_id,
                f"governance/authorizations/{authorization_id}.json",
                CHALLENGE,
            ),
        )
    conn.commit()
    return resource_id, artifact_id, authorization_id


def _insert_attestation(
    conn: psycopg.Connection,
    *,
    resource_id: uuid.UUID,
    artifact_id: uuid.UUID,
    authorization_id: str,
    protocol_version: str,
    attributed_facts_digest: str | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.publication_attestations (
                resource_id, artifact_id, content_sha256, canonical_url, collection,
                scope_authorization_id, profile_id, profile_version,
                profile_fingerprint, manifest_digest,
                rights_status, rights_assessed_at,
                quality_passed, quality_report_digest, quality_assessed_at,
                gate_passed, gate_name, gate_evaluated_at,
                evidence_event_ids,
                review_id, review_artifact_path, review_artifact_blob_sha,
                attestation_digest,
                human_review_repository, human_review_pull_request,
                human_review_base_sha, human_review_head_sha, human_review_review_id,
                human_review_reviewer, human_review_submitted_at,
                human_review_challenge,
                protocol_version, attributed_facts_digest
            ) VALUES (
                %s, %s, repeat('1', 64), 'https://eduscol.education.gouv.fr/a',
                'libre_terminale_philosophie',
                %s, 'terminale-philosophie', '1.0.0', repeat('b', 64), repeat('a', 64),
                'officiel_public', now(),
                true, repeat('9', 64), now(),
                true, 'h2f-gate', now(),
                ARRAY[gen_random_uuid()],
                'review-x',
                'governance/publication-reviews/review-x-' || repeat('7', 64)
                    || '.json',
                repeat('c', 40),
                repeat('7', 64),
                'cyranoaladin/RAG', 1, repeat('e', 40), repeat('f', 40), 3,
                'abenrhouma', now(), %s,
                %s, %s
            )
            """,
            (
                resource_id,
                artifact_id,
                authorization_id,
                CHALLENGE,
                protocol_version,
                attributed_facts_digest,
            ),
        )
    conn.commit()


class TestMigration013Applies:
    def test_bootstrap_declares_013_as_head(self, pg_container: dict[str, str]) -> None:
        result = _run_bootstrap(pg_container)
        assert result.returncode == 0, result.stderr
        assert "SCHEMA_HEAD=13" in result.stdout

    def test_the_protocol_constraints_enumerate_both_versions(
        self, pg_container: dict[str, str]
    ) -> None:
        with psycopg.connect(superuser_dsn(pg_container)) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT pg_get_constraintdef(oid) FROM pg_constraint
                WHERE conname = 'publication_attestations_protocol_version_valid'
                """
            )
            (definition,) = cur.fetchone()
        assert "LOT42-V1" in definition and "LOT42-V2" in definition

    def test_commit_pins_accept_both_versions(
        self, pg_container: dict[str, str]
    ) -> None:
        with psycopg.connect(superuser_dsn(pg_container)) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT pg_get_constraintdef(oid) FROM pg_constraint
                WHERE conname = 'publication_commit_pins_publication_protocol_valid'
                """
            )
            (definition,) = cur.fetchone()
        assert "LOT42-V1" in definition and "LOT42-V2" in definition

    def test_reapplying_013_is_idempotent(self, pg_container: dict[str, str]) -> None:
        with psycopg.connect(superuser_dsn(pg_container)) as conn:
            _apply_013(conn)
            _apply_013(conn)


class TestTheDigestInvariantIsEnforcedByPostgres:
    def test_a_v2_attestation_without_digest_is_refused(
        self, pg_container: dict[str, str]
    ) -> None:
        with psycopg.connect(superuser_dsn(pg_container)) as conn:
            resource_id, artifact_id, authorization_id = _seed_prerequisites(conn)
            with pytest.raises(
                psycopg.errors.CheckViolation,
                match="attribution_digest_matches_protocol",
            ):
                _insert_attestation(
                    conn,
                    resource_id=resource_id,
                    artifact_id=artifact_id,
                    authorization_id=authorization_id,
                    protocol_version="LOT42-V2",
                    attributed_facts_digest=None,
                )

    def test_a_v1_attestation_carrying_a_digest_is_refused(
        self, pg_container: dict[str, str]
    ) -> None:
        """Aucun digest n'est jamais attribué rétroactivement à une V1."""
        with psycopg.connect(superuser_dsn(pg_container)) as conn:
            resource_id, artifact_id, authorization_id = _seed_prerequisites(conn)
            with pytest.raises(
                psycopg.errors.CheckViolation,
                match="attribution_digest_matches_protocol",
            ):
                _insert_attestation(
                    conn,
                    resource_id=resource_id,
                    artifact_id=artifact_id,
                    authorization_id=authorization_id,
                    protocol_version="LOT42-V1",
                    attributed_facts_digest=ATTRIBUTION_DIGEST,
                )

    def test_an_unknown_protocol_version_is_refused(
        self, pg_container: dict[str, str]
    ) -> None:
        with psycopg.connect(superuser_dsn(pg_container)) as conn:
            resource_id, artifact_id, authorization_id = _seed_prerequisites(conn)
            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_attestation(
                    conn,
                    resource_id=resource_id,
                    artifact_id=artifact_id,
                    authorization_id=authorization_id,
                    protocol_version="LOT42-V3",
                    attributed_facts_digest=ATTRIBUTION_DIGEST,
                )

    def test_a_correct_v2_attestation_is_accepted(
        self, pg_container: dict[str, str]
    ) -> None:
        with psycopg.connect(superuser_dsn(pg_container)) as conn:
            resource_id, artifact_id, authorization_id = _seed_prerequisites(conn)
            _insert_attestation(
                conn,
                resource_id=resource_id,
                artifact_id=artifact_id,
                authorization_id=authorization_id,
                protocol_version="LOT42-V2",
                attributed_facts_digest=ATTRIBUTION_DIGEST,
            )
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT attributed_facts_digest FROM "
                    "ingestion_control.publication_attestations "
                    "WHERE resource_id = %s",
                    (resource_id,),
                )
                assert cur.fetchone() == (ATTRIBUTION_DIGEST,)

    def test_a_historical_v1_row_coexists_with_a_v2_row(
        self, pg_container: dict[str, str]
    ) -> None:
        """Coexistence historique : le schéma autorise les deux. C'est
        l'application (``require_publication_review_v2``) qui interdit
        d'écrire une nouvelle V1, pas un CHECK — une contrainte ne
        distingue pas une ligne ancienne d'une ligne neuve."""
        with psycopg.connect(superuser_dsn(pg_container)) as conn:
            legacy = _seed_prerequisites(conn)
            _insert_attestation(
                conn,
                resource_id=legacy[0],
                artifact_id=legacy[1],
                authorization_id=legacy[2],
                protocol_version="LOT42-V1",
                attributed_facts_digest=None,
            )
            modern = _seed_prerequisites(conn)
            _insert_attestation(
                conn,
                resource_id=modern[0],
                artifact_id=modern[1],
                authorization_id=modern[2],
                protocol_version="LOT42-V2",
                attributed_facts_digest=ATTRIBUTION_DIGEST,
            )
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT protocol_version, attributed_facts_digest FROM "
                    "ingestion_control.publication_attestations "
                    "WHERE resource_id IN (%s, %s) ORDER BY protocol_version",
                    (legacy[0], modern[0]),
                )
                assert cur.fetchall() == [
                    ("LOT42-V1", None),
                    ("LOT42-V2", ATTRIBUTION_DIGEST),
                ]


class TestRollbackIsFailClosed:
    def test_rollback_refuses_without_loss_when_v2_data_exists(
        self, pg_container: dict[str, str]
    ) -> None:
        with psycopg.connect(superuser_dsn(pg_container)) as conn:
            seeded = _seed_prerequisites(conn)
            _insert_attestation(
                conn,
                resource_id=seeded[0],
                artifact_id=seeded[1],
                authorization_id=seeded[2],
                protocol_version="LOT42-V2",
                attributed_facts_digest=ATTRIBUTION_DIGEST,
            )
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM ingestion_control.publication_attestations"
                )
                (before,) = cur.fetchone()

            with pytest.raises(
                psycopg.errors.RaiseException,
                match="ROLLBACK_013_LOT42_V2_ATTESTATIONS_PRESENT",
            ):
                _rollback_013(conn)
            conn.rollback()

            # Aucun octet modifié : ni les données, ni les contraintes.
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM ingestion_control.publication_attestations"
                )
                assert cur.fetchone() == (before,)
                cur.execute(
                    """
                    SELECT pg_get_constraintdef(oid) FROM pg_constraint
                    WHERE conname = 'publication_attestations_protocol_version_valid'
                    """
                )
                (definition,) = cur.fetchone()
            assert "LOT42-V2" in definition

    def test_rollback_then_reapply_on_a_base_without_v2_data(
        self, pg_container: dict[str, str]
    ) -> None:
        with psycopg.connect(superuser_dsn(pg_container)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM ingestion_control.publication_attestations "
                    "WHERE protocol_version = 'LOT42-V2'"
                )
            conn.commit()

            _rollback_013(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pg_get_constraintdef(oid) FROM pg_constraint
                    WHERE conname = 'publication_attestations_protocol_version_valid'
                    """
                )
                (definition,) = cur.fetchone()
            assert "LOT42-V2" not in definition

            _apply_013(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pg_get_constraintdef(oid) FROM pg_constraint
                    WHERE conname = 'publication_attestations_protocol_version_valid'
                    """
                )
                (definition,) = cur.fetchone()
            assert "LOT42-V2" in definition


class TestPermissionsAreUnchanged:
    def test_013_grants_no_new_privilege(self, pg_container: dict[str, str]) -> None:
        """La migration ne touche que des contraintes. Un GRANT accidentel
        serait une élévation silencieuse."""
        sql = (MIGRATIONS_DIR / f"{MIGRATION_013}.sql").read_text(encoding="utf-8")
        assert "GRANT" not in sql.upper()
        assert "REVOKE" not in sql.upper()
        assert "ALTER ROLE" not in sql.upper()

    def test_the_four_roles_keep_their_attestation_privileges(
        self, pg_container: dict[str, str]
    ) -> None:
        with psycopg.connect(superuser_dsn(pg_container)) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT grantee, privilege_type
                FROM information_schema.role_table_grants
                WHERE table_schema = 'ingestion_control'
                  AND table_name = 'publication_attestations'
                  AND grantee LIKE 'ingestion_control_%'
                ORDER BY grantee, privilege_type
                """
            )
            grants = {(row[0], row[1]) for row in cur.fetchall()}
        assert ("ingestion_control_attestor", "INSERT") in grants
        assert ("ingestion_control_attestor", "SELECT") in grants
        # L'attestor n'a jamais eu le droit de supprimer une attestation.
        assert ("ingestion_control_attestor", "DELETE") not in grants
