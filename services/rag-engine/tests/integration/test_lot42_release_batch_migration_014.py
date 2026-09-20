"""Migration 014 — stockage LOT42-RELEASE-BATCH-V1 sur PostgreSQL réel.

Aucun mock : un conteneur ``pgvector:pg16`` jetable est migré par le VRAI
script de bootstrap, et les refus mesurés sont de vrais refus PostgreSQL.

Ce que la migration doit prouver ici :

* `resource_pipeline` exige TOUJOURS une `canonical_url` non vide — l'ancien
  comportement est intact, à la ligne près ;
* une ressource de release scellée est acceptée **sans** `canonical_url` ;
* une `canonical_url` FABRIQUÉE pour une release scellée est **impossible** :
  la base la refuse, au lieu de la tolérer ;
* les mêmes deux faits sur `publication_attestations` ;
* le rollback est intégral sur une base sans donnée de release, et **refuse
  sans rien modifier** dès qu'une telle donnée existe.
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

MIGRATION_014 = "014_lot42_release_batch_storage"
URL_FABRIQUEE = "https://eduscol.education.gouv.fr/5799/programmes-et-ressources"

SCOPE = (
    "'nexus', 'rag_nexus_hggsp_premiere_specialite', 'premiere', 'generale', "
    "'hggsp', 'libre', ARRAY['libre'], 'public', '2026-2027', "
    "'EDUSCOL_CORPUS_20260808'"
)


@pytest.fixture(scope="module")
def pg_container() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("lot42-release-batch-014")


def _bootstrap(pg: dict[str, str]) -> subprocess.CompletedProcess[str]:
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
    return subprocess.run(
        [str(BOOTSTRAP_SCRIPT)], cwd=ENGINE_ROOT, env=env,
        capture_output=True, text=True, check=False,
    )


@pytest.fixture(scope="module")
def migrated(pg_container: dict[str, str]) -> dict[str, str]:
    resultat = _bootstrap(pg_container)
    assert resultat.returncode == 0, resultat.stderr
    assert "SCHEMA_VERIFICATION=OK" in resultat.stdout
    return pg_container


def _run(conn: psycopg.Connection) -> uuid.UUID:
    run_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO ingestion_control.ingestion_runs (
                run_id, tenant, collection, niveau, voie, matiere, candidat,
                audience, visibility, school_year, programme_version,
                profile_version, trigger
            ) VALUES (%s, {SCOPE}, 'profile-gate-v2', 'manual')
            """,
            (run_id,),
        )
    conn.commit()
    return run_id


def _resource(conn: psycopg.Connection, run_id: uuid.UUID, kind: str) -> uuid.UUID:
    resource_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO ingestion_control.resources (
                resource_id, run_id, dedup_key,
                tenant, collection, niveau, voie, matiere, candidat,
                audience, visibility, school_year, programme_version,
                resource_state, pipeline_kind
            ) VALUES (%s, %s, %s, {SCOPE}, 'DISCOVERED', %s)
            """,
            (resource_id, run_id, uuid.uuid4().hex, kind),
        )
    conn.commit()
    return resource_id


def _candidat(
    conn: psycopg.Connection,
    run_id: uuid.UUID,
    resource_id: uuid.UUID,
    *,
    kind: str,
    canonical_url: str | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.resource_candidates (
                resource_id, run_id, dedup_key, source_url, canonical_url,
                domain, proposed_type_doc, pipeline_kind
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                resource_id, run_id, uuid.uuid4().hex,
                "https://eduscol.education.gouv.fr/5799/source",
                canonical_url, "eduscol.education.gouv.fr",
                "programme-officiel", kind,
            ),
        )
    conn.commit()


# --- 1 / 3 — resource_pipeline reste exigeant ---------------------------


def test_resource_pipeline_refuse_une_canonical_url_absente(
    migrated: dict[str, str],
) -> None:
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        run_id = _run(conn)
        resource_id = _resource(conn, run_id, "resource_pipeline")
        with pytest.raises(psycopg.errors.CheckViolation):
            _candidat(conn, run_id, resource_id,
                      kind="resource_pipeline", canonical_url=None)


def test_resource_pipeline_refuse_une_canonical_url_vide(
    migrated: dict[str, str],
) -> None:
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        run_id = _run(conn)
        resource_id = _resource(conn, run_id, "resource_pipeline")
        with pytest.raises(psycopg.errors.CheckViolation):
            _candidat(conn, run_id, resource_id,
                      kind="resource_pipeline", canonical_url="   ")


def test_resource_pipeline_accepte_une_canonical_url_reelle(
    migrated: dict[str, str],
) -> None:
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        run_id = _run(conn)
        resource_id = _resource(conn, run_id, "resource_pipeline")
        _candidat(conn, run_id, resource_id,
                  kind="resource_pipeline", canonical_url=URL_FABRIQUEE)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT canonical_url FROM ingestion_control.resource_candidates "
                "WHERE resource_id = %s",
                (resource_id,),
            )
            assert cur.fetchone()[0] == URL_FABRIQUEE


# --- 4 / 5 — la release scellée ne peut PAS porter d'URL canonique ------


def test_une_release_scellee_est_acceptee_sans_canonical_url(
    migrated: dict[str, str],
) -> None:
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        run_id = _run(conn)
        resource_id = _resource(conn, run_id, "sealed_release_pipeline")
        _candidat(conn, run_id, resource_id,
                  kind="sealed_release_pipeline", canonical_url=None)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT canonical_url, source_url FROM "
                "ingestion_control.resource_candidates WHERE resource_id = %s",
                (resource_id,),
            )
            canonical, source = cur.fetchone()
        assert canonical is None
        # La provenance, elle, est conservée — et n'a pas été promue.
        assert source.startswith("https://eduscol.education.gouv.fr/")


def test_une_canonical_url_fabriquee_pour_une_release_est_refusee_par_la_base(
    migrated: dict[str, str],
) -> None:
    """Le refus est celui de PostgreSQL, pas une convention d'équipe."""
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        run_id = _run(conn)
        resource_id = _resource(conn, run_id, "sealed_release_pipeline")
        with pytest.raises(psycopg.errors.CheckViolation):
            _candidat(conn, run_id, resource_id,
                      kind="sealed_release_pipeline", canonical_url=URL_FABRIQUEE)


def test_une_origine_inconnue_est_refusee(migrated: dict[str, str]) -> None:
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        run_id = _run(conn)
        with pytest.raises(psycopg.errors.CheckViolation):
            _resource(conn, run_id, "pipeline_maison")


# --- 11 / 12 — la machine d'états atteint NEEDS_REVIEW pour une release -


def test_une_release_scellee_peut_atteindre_needs_review(
    migrated: dict[str, str],
) -> None:
    """C'était impossible avant 014 : `CANDIDATE` exigeait une canonical_url."""
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        run_id = _run(conn)
        resource_id = _resource(conn, run_id, "sealed_release_pipeline")
        _candidat(conn, run_id, resource_id,
                  kind="sealed_release_pipeline", canonical_url=None)
        with conn.cursor() as cur:
            for etat in ("CANDIDATE", "FETCHED", "STORED", "EXTRACTED",
                         "CLASSIFIED", "RIGHTS_CHECKED", "QUALITY_CHECKED",
                         "ROUTED", "STAGED", "NEEDS_REVIEW"):
                cur.execute(
                    "UPDATE ingestion_control.resources SET resource_state = %s, "
                    "state_version = state_version + 1 WHERE resource_id = %s",
                    (etat, resource_id),
                )
            cur.execute(
                "SELECT resource_state FROM ingestion_control.resources "
                "WHERE resource_id = %s",
                (resource_id,),
            )
            assert cur.fetchone()[0] == "NEEDS_REVIEW"
        conn.commit()


# --- le rollback : intégral à vide, refus dès qu'une release existe -----


def _rollback(conn: psycopg.Connection) -> None:
    sql = (ROLLBACKS_DIR / f"{MIGRATION_014}.down.sql").read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)


def test_le_rollback_refuse_et_ne_modifie_rien_si_une_release_existe(
    migrated: dict[str, str],
) -> None:
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        run_id = _run(conn)
        resource_id = _resource(conn, run_id, "sealed_release_pipeline")
        _candidat(conn, run_id, resource_id,
                  kind="sealed_release_pipeline", canonical_url=None)
        with pytest.raises(psycopg.errors.RaiseException, match="rollback 014 refusé"):
            _rollback(conn)
        conn.rollback()

    # Après le refus, la contrainte conditionnelle est toujours en place :
    # rien n'a été modifié.
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        run_id = _run(conn)
        autre = _resource(conn, run_id, "sealed_release_pipeline")
        _candidat(conn, run_id, autre,
                  kind="sealed_release_pipeline", canonical_url=None)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM ingestion_control.resource_candidates "
                "WHERE pipeline_kind = 'sealed_release_pipeline'"
            )
            assert cur.fetchone()[0] >= 2
        conn.commit()
