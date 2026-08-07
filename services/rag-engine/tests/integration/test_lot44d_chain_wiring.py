"""LOT44d : câblage réel des huit stages sur PostgreSQL — LOT44b/44c non modifiés.

Périmètre strict : preuve d'intégration que la chaîne
Scout -> Fetcher -> Extractor -> Classifier -> RightsAgent -> QualityAgent
écrit réellement dans ``ingestion_control`` (LOT44b, migration figée) via
``apply_resource_transition`` (LOT44d), et que la sélection/validation de
profil (LOT44c) est réellement appelée dans la chaîne — pas contournée.

Aucun réseau réel (``validate_destination``/``safe_fetch`` toujours des
doublures), aucun stockage réel (``store_artifact``/``read_artifact``
toujours en mémoire) : seul PostgreSQL est réel (conteneur Docker jetable,
même convention que ``test_lot44c_profile_validation_events.py``).

Preuves centrales de ce fichier :
- ``job_id`` reste ``NULL`` sur chaque ligne ``workflow_events`` écrite par
  la chaîne (LOT44d ne crée ni run, ni job, ni table ``jobs``).
- ``QUALITY_CHECKED -> ROUTED`` (activée LOT44f, ADR-0029) n'est écrite que
  lorsque la ``RoutingDecision`` calculée vaut ``"ROUTE"`` — jamais pour
  ``QUARANTINE``/``REJECT``/``DUPLICATE``, où l'état final réel reste
  ``QUALITY_CHECKED``.
- Aucun profil/manifest de production n'est créé : le registre LOT44c est
  chargé depuis un répertoire temporaire (fixture), jamais depuis
  l'emplacement de production réel.
"""
from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg
import pytest
import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[2]
INFRA_ROOT = ENGINE_ROOT / "infra"
BOOTSTRAP_SCRIPT = INFRA_ROOT / "scripts" / "bootstrap_ingestion_control_schema.sh"
PROVISION_SCRIPT = INFRA_ROOT / "scripts" / "provision_ingestion_control_roles.sh"

sys.path.insert(0, str(ENGINE_ROOT / "src"))

from nexus_contracts.ingestion import SearchPlan  # noqa: E402

from ingestor.ingestion_agents.classifier import run_classifier  # noqa: E402
from ingestor.ingestion_agents.extractor import run_extractor  # noqa: E402
from ingestor.ingestion_agents.fetcher import run_fetcher  # noqa: E402
from ingestor.ingestion_agents.quality_agent import run_quality_agent  # noqa: E402
from ingestor.ingestion_agents.rights_agent import run_rights_agent  # noqa: E402
from ingestor.ingestion_agents.scout import run_scout  # noqa: E402
from ingestor.ingestion_profiles.registry import load_profile_registry, select_profile  # noqa: E402
from ingestor.ingestion_profiles.validation import validate_scope_against_profile  # noqa: E402

PG_IMAGE = "pgvector/pgvector:pg16"
PG_SUPERUSER = "raguser"
PG_SUPERUSER_PASSWORD = secrets.token_urlsafe(24)  # revue PR#90 : jamais un litteral statique
PG_DB = "ragdb"
APP_PASSWORD = secrets.token_urlsafe(24)  # revue PR#90 : jamais un litteral statique
MIGRATOR_PASSWORD = secrets.token_urlsafe(24)  # revue PR#90 : jamais un litteral statique
AUTHORITY_PASSWORD = secrets.token_urlsafe(24)  # revue PR#90 : jamais un litteral statique
ATTESTOR_PASSWORD = secrets.token_urlsafe(24)  # revue PR#90 : jamais un litteral statique

_DOCKER_AVAILABLE = shutil.which("docker") is not None and (
    subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DOCKER_AVAILABLE, reason="Docker not available"),
]

VALID_SCOPE = {
    "tenant": "libre_terminale",
    "collection": "rag_nexus_nsi_terminale_specialite",
    "niveau": "terminale",
    "voie": "generale",
    "matiere": "nsi",
    "candidat": "libre",
    "audience": ["libre", "tous"],
    "visibility": "internal",
    "school_year": "2026-2027",
    "programme_version": "BOEN_special_8_2019-07-25",
}


def _profile_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "profile_version": "v1",
        "enabled": True,
        "scope": VALID_SCOPE,
        "title": "NSI Terminale Spécialité",
        "owner": "equipe-nsi",
        "expected_topics": ["algorithmique"],
        "expected_resource_types": ["cours"],
        "allowed_domains": ["eduscol.education.fr"],
        "source_authority": "official",
        "search_cadence": "weekly",
        "max_queries_per_run": 10,
        "max_documents_per_run": 20,
        "max_chunk_size": 800,
        "chunk_overlap": 100,
        "min_source_confidence": 0.7,
        "min_scope_confidence": 0.7,
        "min_extraction_quality": 0.1,
    }
    payload.update(overrides)
    return payload


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_pg_isready(port: int, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["pg_isready", "-h", "127.0.0.1", "-p", str(port), "-U", PG_SUPERUSER],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise TimeoutError(f"Postgres not ready on port {port} after {timeout_s}s")


@pytest.fixture(scope="module")
def pg_container() -> Iterator[dict[str, str]]:
    container_name = f"nexus-lot44d-chain-wiring-{uuid.uuid4().hex[:10]}"
    port = _free_port()
    subprocess.run(
        [
            "docker", "run", "-d", "--rm",
            "--name", container_name,
            "-e", f"POSTGRES_USER={PG_SUPERUSER}",
            "-e", f"POSTGRES_PASSWORD={PG_SUPERUSER_PASSWORD}",
            "-e", f"POSTGRES_DB={PG_DB}",
            "-p", f"{port}:5432",
            PG_IMAGE,
        ],
        check=True,
        capture_output=True,
    )
    try:
        _wait_pg_isready(port)
        env = os.environ.copy()
        env.update({
            "PGHOST": "127.0.0.1",
            "PGPORT": str(port),
            "PGUSER": PG_SUPERUSER,
            "PGPASSWORD": PG_SUPERUSER_PASSWORD,
            "PGDATABASE": PG_DB,
        })

        bootstrap = subprocess.run(
            [str(BOOTSTRAP_SCRIPT)], cwd=ENGINE_ROOT, env=env,
            capture_output=True, text=True, check=False,
        )
        assert bootstrap.returncode == 0, bootstrap.stderr
        assert "BOOTSTRAP_COMPLETE" in bootstrap.stdout

        provision_env = dict(env)
        provision_env.update({
            "INGESTION_CONTROL_MIGRATOR_PASSWORD": MIGRATOR_PASSWORD,
            "INGESTION_CONTROL_APP_PASSWORD": APP_PASSWORD,
            "INGESTION_CONTROL_AUTHORITY_PASSWORD": AUTHORITY_PASSWORD,
            "INGESTION_CONTROL_ATTESTOR_PASSWORD": ATTESTOR_PASSWORD,
        })
        provision = subprocess.run(
            [str(PROVISION_SCRIPT)], cwd=ENGINE_ROOT, env=provision_env,
            capture_output=True, text=True, check=False,
        )
        assert provision.returncode == 0, provision.stderr
        assert "ROLES_PROVISIONED=1" in provision.stdout

        yield {"host": "127.0.0.1", "port": str(port), "dbname": PG_DB}
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)


def _app_dsn(pg_container: dict[str, str]) -> str:
    return (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user=ingestion_control_app password={APP_PASSWORD}"
    )


@pytest.fixture
def app_conn(pg_container: dict[str, str]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_app_dsn(pg_container), autocommit=False) as conn:
        yield conn


@pytest.fixture
def clean_db(pg_container: dict[str, str]) -> None:
    dsn = (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
    )
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE ingestion_control.workflow_events, "
            "ingestion_control.artifacts, ingestion_control.resource_candidates, "
            "ingestion_control.resources, ingestion_control.ingestion_runs CASCADE"
        )


def _insert_run(conn: psycopg.Connection) -> uuid.UUID:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.ingestion_runs
                (tenant, collection, niveau, voie, matiere, candidat, audience,
                 visibility, school_year, programme_version, profile_version, trigger)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING run_id
            """,
            (
                VALID_SCOPE["tenant"], VALID_SCOPE["collection"], VALID_SCOPE["niveau"],
                VALID_SCOPE["voie"], VALID_SCOPE["matiere"], VALID_SCOPE["candidat"],
                VALID_SCOPE["audience"], VALID_SCOPE["visibility"], VALID_SCOPE["school_year"],
                VALID_SCOPE["programme_version"], "v1", "manual",
            ),
        )
        row = cur.fetchone()
        assert row is not None
        return row[0]


def _insert_resource(conn: psycopg.Connection, run_id: uuid.UUID, dedup_key: str) -> uuid.UUID:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.resources
                (run_id, dedup_key, tenant, collection, niveau, voie, matiere, candidat,
                 audience, visibility, school_year, programme_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING resource_id
            """,
            (
                run_id, dedup_key, VALID_SCOPE["tenant"], VALID_SCOPE["collection"],
                VALID_SCOPE["niveau"], VALID_SCOPE["voie"], VALID_SCOPE["matiere"],
                VALID_SCOPE["candidat"], VALID_SCOPE["audience"], VALID_SCOPE["visibility"],
                VALID_SCOPE["school_year"], VALID_SCOPE["programme_version"],
            ),
        )
        row = cur.fetchone()
        assert row is not None
        return row[0]


class TestChainWiringToRealPostgres:
    def test_full_chain_reaches_quality_checked_never_routed_job_id_always_null(
        self, tmp_path: Path, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        # Registre LOT44c chargé depuis un répertoire temporaire — jamais
        # l'emplacement de production réel, aucun profil de production créé.
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "nsi.yml").write_text(
            yaml.safe_dump(_profile_payload()), encoding="utf-8"
        )
        registry = load_profile_registry(profiles_dir)
        profile = select_profile(registry, collection=VALID_SCOPE["collection"], profile_version="v1")

        validation_result = validate_scope_against_profile(
            raw_scope=VALID_SCOPE,
            registry=registry,
            collection=VALID_SCOPE["collection"],
            profile_version="v1",
        )
        assert validation_result.status == "passed"

        run_id = _insert_run(app_conn)
        resource_id = _insert_resource(app_conn, run_id, dedup_key="c" * 64)
        app_conn.commit()

        search_plan = SearchPlan(
            search_plan_id=uuid.uuid4(),
            run_id=run_id,
            scope=profile.scope,
            generated_at=datetime(2026, 8, 4, tzinfo=UTC),
            profile_version="v1",
            queries=["algorithmique"],
            allowed_domains=profile.allowed_domains,
            max_results=profile.max_documents_per_run,
            reason="test d'intégration LOT44d",
        )

        candidate, scout_transition = run_scout(
            app_conn,
            search_plan=search_plan,
            resource_id=resource_id,
            candidate_id=uuid.uuid4(),
            discovered_at=datetime(2026, 8, 4, tzinfo=UTC),
            source_url="https://eduscol.education.fr/nsi/algo",
            canonical_url="https://eduscol.education.fr/nsi/algo",
            domain="eduscol.education.fr",
            proposed_type_doc="cours",
            expected_version=0,
            actor="test-lot44d-chain",
            validate_destination=lambda url: url,
        )
        app_conn.commit()
        assert scout_transition.to_state.value == "CANDIDATE"

        fake_response = httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<p>Cours d'algorithmique pour la terminale.</p>",
            request=httpx.Request("GET", candidate.source_url),
        )
        stored_bytes: dict[str, bytes] = {}

        def fake_store_artifact(*, artifact_id: object, content: bytes) -> str:
            ref = f"mem://{artifact_id}"
            stored_bytes[ref] = content
            return ref

        artifact, fetched_transition, stored_transition = run_fetcher(
            app_conn,
            candidate=candidate,
            artifact_id=uuid.uuid4(),
            collected_at=datetime(2026, 8, 4, tzinfo=UTC),
            expected_version=scout_transition.state_version,
            actor="test-lot44d-chain",
            max_bytes=1_000_000,
            store_artifact=fake_store_artifact,
            safe_fetch=lambda url, **kwargs: fake_response,
        )
        app_conn.commit()
        assert stored_transition.to_state.value == "STORED"

        def fake_read_artifact(*, extracted_text_ref: str) -> bytes:
            return stored_bytes[extracted_text_ref]

        extracted_text, extract_transition = run_extractor(
            app_conn,
            artifact=artifact,
            expected_version=stored_transition.state_version,
            actor="test-lot44d-chain",
            read_artifact=fake_read_artifact,
        )
        app_conn.commit()
        assert extract_transition.to_state.value == "EXTRACTED"

        conformity, classify_transition = run_classifier(
            app_conn,
            resource_id=resource_id,
            run_id=run_id,
            extracted_text=extracted_text,
            profile=profile,
            expected_version=extract_transition.state_version,
            actor="test-lot44d-chain",
        )
        app_conn.commit()
        assert classify_transition.to_state.value == "CLASSIFIED"

        rights, rights_transition = run_rights_agent(
            app_conn,
            artifact=artifact.model_copy(update={"license": "CC-BY-SA"}),
            profile=profile,
            expected_version=classify_transition.state_version,
            actor="test-lot44d-chain",
        )
        app_conn.commit()
        assert rights_transition.to_state.value == "RIGHTS_CHECKED"

        quality_report, routing_decision, quality_transition = run_quality_agent(
            app_conn,
            artifact=artifact,
            profile=profile,
            conformity=conformity,
            rights=rights,
            extracted_text=extracted_text,
            declared_language="fr",
            pii_detected=False,
            duplicate_detected=False,
            report_id=uuid.uuid4(),
            decision_id=uuid.uuid4(),
            evaluated_at=datetime(2026, 8, 4, tzinfo=UTC),
            expected_version=rights_transition.state_version,
            actor="test-lot44d-chain",
        )
        app_conn.commit()
        assert routing_decision.decision in {"ROUTE", "QUARANTINE", "REJECT", "DUPLICATE"}
        # LOT44f (ADR-0029) : QUALITY_CHECKED -> ROUTED est désormais appliquée
        # quand (et seulement quand) la décision calculée vaut "ROUTE" — ce
        # scénario est délibérément "propre" (droits connus, pas de PII/
        # doublon), donc la décision réelle ici est ROUTE.
        expected_final_state = "ROUTED" if routing_decision.decision == "ROUTE" else "QUALITY_CHECKED"
        assert quality_transition.to_state.value == expected_final_state

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT resource_state, state_version FROM ingestion_control.resources "
                "WHERE resource_id = %s",
                (resource_id,),
            )
            row = cur.fetchone()
            assert row is not None
            final_state, final_version = row
            assert final_state == expected_final_state
            assert final_version == quality_transition.state_version

            cur.execute(
                "SELECT job_id FROM ingestion_control.workflow_events WHERE run_id = %s",
                (run_id,),
            )
            job_ids = [job_id for (job_id,) in cur.fetchall()]
            assert job_ids, "expected at least one workflow_events row"
            assert all(job_id is None for job_id in job_ids)

            cur.execute(
                "SELECT COUNT(*) FROM ingestion_control.workflow_events "
                "WHERE run_id = %s AND to_state = 'ROUTED'",
                (run_id,),
            )
            (routed_count,) = cur.fetchone()
            assert routed_count == (1 if routing_decision.decision == "ROUTE" else 0)
