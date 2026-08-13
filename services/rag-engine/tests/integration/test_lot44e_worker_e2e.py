"""LOT44e : E2E réel — job -> worker -> huit stages -> événements PostgreSQL.

Périmètre strict : ``run_worker_iteration`` (ingestion_worker.runner) sur
PostgreSQL réel, à partir d'un job créé exactement comme ``/ingest/v2``
serait censé le faire (même forme de payload). Réseau et téléchargement
toujours des doublures (``validate_destination``/``safe_fetch`` injectés,
jamais la vraie garde SSRF) ; stockage réel sur disque temporaire
(``tmp_path``, filesystem local, pas de simulation).

Preuves centrales :
- la chaîne complète progresse jusqu'à ``ROUTED`` pour un scénario "propre"
  (LOT44f, ADR-0029 — droits connus, pas de PII/doublon, qualité au-dessus
  du seuil du profil) ;
- **tous** les événements ``workflow_events`` de l'exécution portent le
  **même** ``job_id`` ;
- le retry/backoff fonctionne réellement (échec de téléchargement ->
  ``record_job_retry`` -> nouvelle tentative réussie) ;
- aucun profil de production n'est utilisé : le registre est chargé depuis
  un répertoire temporaire.
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
from pathlib import Path

import httpx
import psycopg
import pytest
import yaml
from nexus_contracts.ingestion import CollectionProfile

ENGINE_ROOT = Path(__file__).resolve().parents[2]
INFRA_ROOT = ENGINE_ROOT / "infra"
BOOTSTRAP_SCRIPT = INFRA_ROOT / "scripts" / "bootstrap_ingestion_control_schema.sh"
PROVISION_SCRIPT = INFRA_ROOT / "scripts" / "provision_ingestion_control_roles.sh"

sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests"))

from _authorization_stub import (  # noqa: E402
    STUB_AUTHORIZATION_ID,
    verified_authorization,
)

from ingestor.ingestion_control.jobs import create_job  # noqa: E402
from ingestor.ingestion_control.scope_authority import (  # noqa: E402
    ScopeAuthorizationDeniedError,
)
from ingestor.ingestion_control.sealed_evidence import (  # noqa: E402
    VerifiedPIIEvidenceRegistry,
    VerifiedRightsEvidenceRegistry,
)
from ingestor.ingestion_profiles.registry import (  # noqa: E402
    load_profile_registry,
    profile_fingerprint,
    select_profile,
)
from ingestor.ingestion_worker.runner import WorkerDeps, run_worker_iteration  # noqa: E402
from ingestor.ingestion_worker.storage import (  # noqa: E402
    make_filesystem_artifact_reader,
    make_filesystem_artifact_store,
)
from ingestor.ssrf_guard import SSRFValidationError  # noqa: E402

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


def _job_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "scope": VALID_SCOPE,
        "dedup_key": "e" * 64,
        "source_url": "https://eduscol.education.fr/nsi/algo",
        "canonical_url": "https://eduscol.education.fr/nsi/algo",
        "domain": "eduscol.education.fr",
        "proposed_type_doc": "cours",
        "profile_version": "v1",
        # Item C : un job nomme TOUJOURS son autorisation, explicitement.
        "scope_authorization_id": STUB_AUTHORIZATION_ID,
        "license": "CC-BY-SA",
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
            capture_output=True, check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise TimeoutError(f"Postgres not ready on port {port} after {timeout_s}s")


@pytest.fixture(scope="module")
def pg_container() -> Iterator[dict[str, str]]:
    container_name = f"nexus-lot44e-worker-e2e-{uuid.uuid4().hex[:10]}"
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
        check=True, capture_output=True,
    )
    try:
        _wait_pg_isready(port)
        env = os.environ.copy()
        env.update({
            "PGHOST": "127.0.0.1", "PGPORT": str(port), "PGUSER": PG_SUPERUSER,
            "PGPASSWORD": PG_SUPERUSER_PASSWORD, "PGDATABASE": PG_DB,
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
            "TRUNCATE ingestion_control.jobs, ingestion_control.workflow_events, "
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


def _write_profile(profiles_dir: Path) -> None:
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "nsi.yml").write_text(yaml.safe_dump(_profile_payload()), encoding="utf-8")


#: Digest de manifest arbitraire mais FIXE de ces suites : le worker le
#: porte, l'autorisation stub le déclare, et le point de contrôle pre_fetch
#: les compare pour de vrai (item D).
STUB_MANIFEST_DIGEST = "7" * 64

_STUB_PROFILE = CollectionProfile.model_validate(_profile_payload())


def _stub_registry():
    """Registre équivalent à celui que le worker charge — construit depuis
    le MÊME ``_profile_payload()``, donc de même empreinte."""
    return {
        (_STUB_PROFILE.scope.collection, _STUB_PROFILE.profile_version): _STUB_PROFILE
    }


def _always_authorized(conn, *, authorization_id, scope=None, now=None):
    """Stub LOT41A (ADR-0032) : ce fichier teste la chaîne d'ingestion, jamais
    la frontière GitHub d'autorisation de scope elle-même — reconstruire une
    PR/review/blob GitHub réels ici serait hors périmètre, et c'est couvert
    par les suites dédiées (``test_lot41a_scope_authority.py``, …).

    L'autorisation rendue reste **cohérente avec le job** (mêmes domaines,
    mêmes droits, même profil, même manifest) : les points de contrôle
    d'enforcement (item D) s'exécutent donc réellement ici, et un job hors
    périmètre y échouerait comme en production. Le stub refuse d'ailleurs un
    ``authorization_id`` qu'il ne connaît pas, exactement comme la
    vérification réelle."""
    if authorization_id != STUB_AUTHORIZATION_ID:
        raise ScopeAuthorizationDeniedError(
            f"no scope_authorizations row with authorization_id={authorization_id!r}"
        )
    profile = select_profile(
        _stub_registry(), collection=VALID_SCOPE["collection"], profile_version="v1"
    )
    return verified_authorization(
        scope=scope if scope is not None else VALID_SCOPE,
        manifest_digest=STUB_MANIFEST_DIGEST,
        profile_id=profile.scope.collection,
        profile_version=profile.profile_version,
        profile_fingerprint=profile_fingerprint(profile),
    )
    return verified_authorization(
        scope=scope if scope is not None else VALID_SCOPE,
        manifest_digest=STUB_MANIFEST_DIGEST,
        profile_id=profile.scope.collection,
        profile_version=profile.profile_version,
        profile_fingerprint=profile_fingerprint(profile),
    )


#: SHA-256 des octets réellement stockés par Fetcher pour les doublures de
#: ce fichier. C'est ce digest que le worker interroge — pas celui de la
#: réponse HTTP brute, qui peut différer après normalisation.
#:
#: La preuve couvre ces contenus et eux seuls : un test qui changerait son
#: contenu sans étendre la preuve doit échouer, pas passer par défaut.
_FETCHED_CONTENT_SHAS = (
    "27610d4b542a4405553c0bd54bf1fb927ee2d2d7b047e38ddc85a081a358a00d",
    "5fb448b94317a73402a717828c1fe4272ce161941b08b3534738718a13b9f26f",
)


def _sealed_evidence(
    tmp_path: Path,
) -> tuple[VerifiedPIIEvidenceRegistry, VerifiedRightsEvidenceRegistry]:
    """Preuves scellées synthétiques mais cryptographiquement cohérentes.

    Le worker en exige sur toute voie publiable. Elles sont construites
    ici plutôt que dans le code de production : rendre le worker tolérant
    pour satisfaire un test annulerait précisément ce qui a été fermé.

    La zone de droits est le préfixe d'URL du domaine autorisé, ce test
    travaillant sur une URL de doublure et non sur un chemin du manifeste
    scellé.
    """
    import hashlib as _hashlib
    import json as _json

    evidence_dir = tmp_path / "sealed-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    pii_path = evidence_dir / "pii.json"
    pii_path.write_text(
        _json.dumps({
            "evidence_kind": "REAL_CORPUS_PII_SCAN",
            "corpus_manifest_sha256": STUB_MANIFEST_DIGEST,
            "remote_access_mode": "READ_ONLY",
            "remote_write_operations": 0,
            "raw_pii_in_output": False,
            "raw_pii_in_logs": False,
            "results": [
                {"content_sha256": sha, "status": "CLEARED",
                 "pii_detected": False, "pages_scanned": 1,
                 "characters_scanned": 46}
                for sha in _FETCHED_CONTENT_SHAS
            ],
        }),
        encoding="utf-8",
    )
    rights_path = evidence_dir / "rights.yml"
    rights_path.write_text(
        "registry_id: lot44e_test_registry\n"
        "human_rights_decisions:\n"
        "  eduscol:\n"
        f"    scope_manifest_sha256: \"{STUB_MANIFEST_DIGEST}\"\n"
        "    scope_zone: https://eduscol.education.fr/\n"
        "    approved_for_production_rag: true\n"
        "source_evidence:\n"
        "  eduscol:\n"
        "    zone: https://eduscol.education.fr/\n"
        "    recommended_rights_category: officiel_public\n",
        encoding="utf-8",
    )
    return (
        VerifiedPIIEvidenceRegistry.load(
            pii_path,
            expected_evidence_sha256=_hashlib.sha256(
                pii_path.read_bytes()
            ).hexdigest(),
            expected_corpus_manifest_sha256=STUB_MANIFEST_DIGEST,
        ),
        VerifiedRightsEvidenceRegistry.load(
            rights_path,
            expected_registry_sha256=_hashlib.sha256(
                rights_path.read_bytes()
            ).hexdigest(),
            expected_corpus_manifest_sha256=STUB_MANIFEST_DIGEST,
        ),
    )


def _worker_deps(tmp_path: Path, *, safe_fetch, owner: str = "worker-e2e") -> WorkerDeps:
    profiles_dir = tmp_path / "profiles"
    _write_profile(profiles_dir)
    pii_registry, rights_registry = _sealed_evidence(tmp_path)
    return WorkerDeps(
        owner=owner,
        profile_registry=load_profile_registry(profiles_dir),
        artifact_store=make_filesystem_artifact_store(tmp_path / "artifacts"),
        artifact_reader=make_filesystem_artifact_reader(tmp_path / "artifacts"),
        validate_destination=lambda url: url,
        safe_fetch=safe_fetch,
        verify_scope_authorization=_always_authorized,
        manifest_digest=STUB_MANIFEST_DIGEST,
        pii_evidence_registry=pii_registry,
        rights_evidence_registry=rights_registry,
    )


def _fake_safe_fetch_success(url: str, *, max_bytes: int, **kwargs: object) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/html"},
        content=b"<p>Cours d'algorithmique pour la terminale.</p>",
        request=httpx.Request("GET", url),
    )


def _fake_safe_fetch_high_quality(url: str, *, max_bytes: int, **kwargs: object) -> httpx.Response:
    """Contenu suffisamment long pour dépasser min_extraction_quality (0.1,
    seuil du profil de test) — le contenu minimal de
    ``_fake_safe_fetch_success`` (quelques mots) reste volontairement sous
    ce seuil, donc n'atteint jamais ROUTE (cf. LOT44f, ADR-0029) : les
    autres tests de ce fichier n'ont pas besoin d'atteindre ROUTED, celui-ci
    si."""
    return httpx.Response(
        200,
        headers={"content-type": "text/html"},
        content=(
            b"<p>Ce cours d'algorithmique aborde la recursivite, les structures "
            b"de donnees, les boucles, les fonctions et plusieurs algorithmes "
            b"de tri classiques pour le programme de terminale.</p>"
        ),
        request=httpx.Request("GET", url),
    )


class TestWorkerE2E:
    def test_full_chain_reaches_quality_checked_with_consistent_job_id(
        self, tmp_path: Path, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        """Remédiation revue PR#90 (Cubic P1 + Codex P1) : ce test attendait
        auparavant ``ROUTED`` — désormais structurellement inatteignable
        tant qu'aucun classifieur réel ne vérifie niveau/voie/programme
        (``classify_conformity_core`` les renvoie à ``False`` = "non
        vérifié", et ``QualityAgent`` les traite comme des motifs de rejet
        explicites). Changement intentionnel et documenté, pas une
        régression : le scénario "propre" s'arrête maintenant à
        ``QUALITY_CHECKED``, avec les trois motifs `_not_verified` dans
        ``rejection_reasons`` — la chaîne complète (Scout..QualityAgent)
        reste néanmoins exercée de bout en bout, job_id compris."""
        run_id = _insert_run(app_conn)
        job_id = create_job(
            app_conn, run_id=run_id, job_type="resource_pipeline", payload=_job_payload()
        )
        app_conn.commit()

        deps = _worker_deps(tmp_path, safe_fetch=_fake_safe_fetch_high_quality)
        outcome = run_worker_iteration(app_conn, deps=deps)

        assert outcome.worked is True
        assert outcome.status == "succeeded"
        assert outcome.job_id == job_id
        assert outcome.error is None

        with app_conn.cursor() as cur:
            cur.execute("SELECT status FROM ingestion_control.jobs WHERE job_id = %s", (job_id,))
            (status,) = cur.fetchone()
        assert status == "succeeded"

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT resource_state FROM ingestion_control.resources WHERE run_id = %s",
                (run_id,),
            )
            (resource_state,) = cur.fetchone()
        assert resource_state == "QUALITY_CHECKED"

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT job_id, event_type, to_state, payload FROM ingestion_control.workflow_events "
                "WHERE run_id = %s ORDER BY occurred_at",
                (run_id,),
            )
            rows = cur.fetchall()

        assert len(rows) >= 6, (
            "attendu au moins 6 transitions (Scout..QualityAgent, Fetcher=2)"
        )
        job_ids_seen = {row[0] for row in rows}
        assert job_ids_seen == {job_id}, "tous les événements doivent porter le même job_id"

        # Depuis LOT42 (item E), le verdict du gate est journalisé après la
        # dernière transition — il n'a pas de to_state (ce n'est pas une
        # transition d'état). Les assertions ci-dessous portent donc sur les
        # transitions, filtrées explicitement, jamais sur « le dernier
        # événement » qui n'en est plus une.
        transitions = [row for row in rows if row[1] == "transition"]
        to_states = [row[2] for row in transitions]
        assert to_states[-1] == "QUALITY_CHECKED"

        gate_events = [row for row in rows if row[1] == "PUBLICATION_GATE_EVALUATED"]
        assert len(gate_events) == 1, "le verdict du gate est toujours journalisé, positif ou non"
        assert gate_events[0][3]["gate_passed"] is False, (
            "ce contenu court ne franchit pas le seuil de qualité — le gate "
            "négatif doit laisser une trace durable, pas rien du tout"
        )

        quality_checked_payload = transitions[-1][3]
        rejection_reasons = quality_checked_payload["rejection_reasons"]
        assert "niveau_conformity_not_verified" in rejection_reasons
        assert "voie_conformity_not_verified" in rejection_reasons
        assert "programme_conformity_not_verified" in rejection_reasons

    def test_profile_modified_on_disk_after_startup_does_not_affect_running_worker(
        self, tmp_path: Path, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        """Remédiation revue PR#90 (Codex + Cubic) : le worker garde en
        mémoire le ``ProfileRegistry`` exact vérifié au démarrage
        (``WorkerDeps.profile_registry``) — une modification du fichier de
        profil sur l'hôte après ce démarrage (le montage lecture seule ne
        protège que le conteneur) ne doit **jamais** être prise en compte
        pendant la durée de vie de ce worker, même si un job est traité
        après la modification. Preuve : désactiver le profil sur disque
        (``enabled: False``) après avoir construit ``WorkerDeps`` ne bloque
        pas le traitement — un rechargement depuis le disque aurait levé
        ``ProfileDisabledError``."""
        run_id = _insert_run(app_conn)
        job_id = create_job(
            app_conn, run_id=run_id, job_type="resource_pipeline", payload=_job_payload()
        )
        app_conn.commit()

        profiles_dir = tmp_path / "profiles"
        _write_profile(profiles_dir)
        deps = WorkerDeps(
            owner="worker-e2e",
            profile_registry=load_profile_registry(profiles_dir),
            artifact_store=make_filesystem_artifact_store(tmp_path / "artifacts"),
            artifact_reader=make_filesystem_artifact_reader(tmp_path / "artifacts"),
            validate_destination=lambda url: url,
            safe_fetch=_fake_safe_fetch_high_quality,
            verify_scope_authorization=_always_authorized,
            manifest_digest=STUB_MANIFEST_DIGEST,
            pii_evidence_registry=_sealed_evidence(tmp_path)[0],
            rights_evidence_registry=_sealed_evidence(tmp_path)[1],
        )

        # Modification post-démarrage : le profil approuvé devient désactivé
        # sur le disque — un rechargement le rendrait immédiatement
        # inutilisable (ProfileDisabledError dans select_profile).
        (profiles_dir / "nsi.yml").write_text(
            yaml.safe_dump(_profile_payload(enabled=False)), encoding="utf-8"
        )

        outcome = run_worker_iteration(app_conn, deps=deps)

        assert outcome.worked is True
        assert outcome.status == "succeeded"
        assert outcome.error is None
        with app_conn.cursor() as cur:
            cur.execute("SELECT status FROM ingestion_control.jobs WHERE job_id = %s", (job_id,))
            (status,) = cur.fetchone()
        assert status == "succeeded"

    def test_no_job_available_returns_worked_false(
        self, tmp_path: Path, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        deps = _worker_deps(tmp_path, safe_fetch=_fake_safe_fetch_success)
        outcome = run_worker_iteration(app_conn, deps=deps)
        assert outcome.worked is False
        assert outcome.job_id is None

    def test_blocked_url_causes_retry_not_a_crash(
        self, tmp_path: Path, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(app_conn)
        job_id = create_job(
            app_conn, run_id=run_id, job_type="resource_pipeline", payload=_job_payload()
        )
        app_conn.commit()

        def blocking_validate_destination(url: str) -> str:
            raise SSRFValidationError(f"blocked: {url}")

        profiles_dir = tmp_path / "profiles"
        _write_profile(profiles_dir)
        deps = WorkerDeps(
            owner="worker-e2e",
            profile_registry=load_profile_registry(profiles_dir),
            artifact_store=make_filesystem_artifact_store(tmp_path / "artifacts"),
            artifact_reader=make_filesystem_artifact_reader(tmp_path / "artifacts"),
            validate_destination=blocking_validate_destination,
            safe_fetch=_fake_safe_fetch_success,
            verify_scope_authorization=_always_authorized,
            manifest_digest=STUB_MANIFEST_DIGEST,
            pii_evidence_registry=_sealed_evidence(tmp_path)[0],
            rights_evidence_registry=_sealed_evidence(tmp_path)[1],
        )

        outcome = run_worker_iteration(app_conn, deps=deps)

        assert outcome.worked is True
        assert outcome.status == "retried"
        assert outcome.job_id == job_id
        assert "blocked" in (outcome.error or "")

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT status, attempt_count, lease_token FROM ingestion_control.jobs "
                "WHERE job_id = %s",
                (job_id,),
            )
            status, attempt_count, lease_token = cur.fetchone()
        assert status == "queued"
        assert attempt_count == 1
        assert lease_token is None

    def test_retry_then_success_on_second_iteration(
        self, tmp_path: Path, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        """Retry/backoff réel : première itération échoue (téléchargement
        qui lève), seconde itération (après recalage manuel de
        next_attempt_at, pour ne pas dépendre du délai réel) réussit."""
        run_id = _insert_run(app_conn)
        job_id = create_job(
            app_conn, run_id=run_id, job_type="resource_pipeline", payload=_job_payload()
        )
        app_conn.commit()

        def failing_safe_fetch(url: str, *, max_bytes: int, **kwargs: object) -> httpx.Response:
            raise RuntimeError("transient network failure")

        profiles_dir = tmp_path / "profiles"
        _write_profile(profiles_dir)
        failing_deps = WorkerDeps(
            owner="worker-e2e", profile_registry=load_profile_registry(profiles_dir),
            artifact_store=make_filesystem_artifact_store(tmp_path / "artifacts"),
            artifact_reader=make_filesystem_artifact_reader(tmp_path / "artifacts"),
            validate_destination=lambda url: url,
            safe_fetch=failing_safe_fetch,
            verify_scope_authorization=_always_authorized,
            manifest_digest=STUB_MANIFEST_DIGEST,
            pii_evidence_registry=_sealed_evidence(tmp_path)[0],
            rights_evidence_registry=_sealed_evidence(tmp_path)[1],
        )

        first_outcome = run_worker_iteration(app_conn, deps=failing_deps)
        assert first_outcome.status == "retried"

        with app_conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_control.jobs SET next_attempt_at = now() WHERE job_id = %s",
                (job_id,),
            )
        app_conn.commit()

        succeeding_deps = _worker_deps(tmp_path, safe_fetch=_fake_safe_fetch_success)
        second_outcome = run_worker_iteration(app_conn, deps=succeeding_deps)

        assert second_outcome.status == "succeeded"
        assert second_outcome.job_id == job_id

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT status, attempt_count FROM ingestion_control.jobs WHERE job_id = %s",
                (job_id,),
            )
            status, attempt_count = cur.fetchone()
        assert status == "succeeded"
        assert attempt_count == 1
