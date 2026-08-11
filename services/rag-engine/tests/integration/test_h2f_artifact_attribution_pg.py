"""H2-F (défaut 6) — l'attribution durable, prouvée sur PostgreSQL réel.

**Aucun mock ne remplace la base ici.** Un conteneur ``pgvector:pg16``
jetable est migré par les VRAIS scripts de bootstrap et de provisionnement
de rôles, puis le schéma produit est appliqué depuis les VRAIES migrations
``infra/postgres/migrations``. Les quatre rôles portent leurs privilèges de
production exacts : les refus mesurés ici sont de vrais refus PostgreSQL,
pas des assertions applicatives.

**Le writer est mesuré à son site d'appel de production.** Le chemin testé
est ``run_worker_iteration`` — la boucle que le worker exécute — et non une
reconstitution du pipeline. Deux pièces seulement sont substituées :
``classify_conformity_core`` et ``assess_rights_core``, les deux cœurs que
le dépôt documente explicitement comme des placeholders qui rendent
aujourd'hui ``ROUTED`` inatteignable (cf.
``TestLivePipelineCannotYetPublish`` dans
``test_lot42_publication_attestation.py``, qui mesure ce fait plutôt que de
le contourner). Tout ce qui se trouve entre eux — Scout, Fetcher,
Extractor, QualityAgent, la transition ``ROUTED``, l'événement de gate et
l'appel au writer — est le code de production non modifié.

Chaîne complète couverte, de bout en bout :

    création de l'artefact d'ingestion
      -> finalisation gouvernée des quatre faits (gate de routage)
      -> writer ``persist_artifact_attribution`` (rôle application)
      -> lecture par le rôle attestor
      -> proposition, revue humaine, attestation LOT42
      -> promotion ``REVIEWED -> RETRIEVAL_ELIGIBLE``
      -> publication produit gouvernée
"""
from __future__ import annotations

import dataclasses
import hashlib
import math
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _authorization_stub import (  # noqa: E402
    STUB_AUTHORIZATION_ID,
    stub_verifier,
    verified_authorization,
)
from _local_github import (  # noqa: E402
    REPOSITORY,
    VALID_TOKEN,
    LocalGitHub,
    local_github_server,
)
from _pg_authority import (  # noqa: E402
    PG_SUPERUSER,
    PG_SUPERUSER_PASSWORD,
    app_dsn,
    attestor_dsn,
    authority_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)
from nexus_contracts.authority_artifacts import (  # noqa: E402
    ScopeAuthorizationArtifactV2,
    canonical_authorization_path,
)
from nexus_contracts.document import Rights  # noqa: E402
from nexus_contracts.ingestion import (  # noqa: E402
    CollectionProfile,
    ResourceCandidate,
    ResourceScope,
)
from nexus_contracts.resource_state import ResourceState  # noqa: E402

from ingestor.governed_publisher_v2 import (  # noqa: E402
    EligiblePlacement,
    GovernedArtifact,
    GovernedPublicationError,
    publish_governed_artifact,
)
from ingestor.ingestion_agents import classifier as classifier_module  # noqa: E402
from ingestor.ingestion_agents import rights_agent as rights_module  # noqa: E402
from ingestor.ingestion_agents.classifier import ConformityResult  # noqa: E402
from ingestor.ingestion_control.artifact_attribution import (  # noqa: E402
    ArtifactAttribution,
    ArtifactAttributionError,
    attribution_digest,
    derive_artifact_attribution,
    load_artifact_attribution,
    persist_artifact_attribution,
)
from ingestor.ingestion_control.governed_publication_path import (  # noqa: E402
    promote_reviewed_publication,
    stage_publication_for_review,
)
from ingestor.ingestion_control.jobs import create_job  # noqa: E402
from ingestor.ingestion_control.provisioning import get_resource_state  # noqa: E402
from ingestor.ingestion_control.publication_attestation import (  # noqa: E402
    PublicationAttestationInvalidError,
    verify_publication_attestation,
)
from ingestor.ingestion_control.publication_evidence import (  # noqa: E402
    PublicationEvidenceMissingError,
    collect_publication_facts,
)
from ingestor.ingestion_profiles.registry import profile_fingerprint  # noqa: E402
from ingestor.ingestion_worker.attest_publication_cli import (  # noqa: E402
    main as attest_main,
)
from ingestor.ingestion_worker.authorize_scope_cli import (  # noqa: E402
    main as authorize_scope_main,
)
from ingestor.ingestion_worker.runner import WorkerDeps, run_worker_iteration  # noqa: E402
from ingestor.ingestion_worker.storage import (  # noqa: E402
    make_filesystem_artifact_reader,
    make_filesystem_artifact_store,
)
from ingestor.retrieval_hybrid_v2 import EMBED_DIMENSION  # noqa: E402

pytestmark = [pytest.mark.integration, requires_docker]

MANIFEST_DIGEST = "a" * 64
AUTH_PR, AUTH_HEAD, AUTH_BASE, AUTH_REVIEW = 5242, "b" * 40, "a" * 40, 977
PUB_PR, PUB_HEAD, PUB_REVIEW = 5300, "c" * 40, 988
REVIEW_ID = "pub-h2f-attribution-001"

DOMAIN = "eduscol.education.fr"
CANONICAL_URL = f"https://{DOMAIN}/nsi/algorithmique"

VALID_SCOPE: dict[str, Any] = {
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

PROFILE = CollectionProfile.model_validate({
    "profile_version": "v1",
    "enabled": True,
    "scope": VALID_SCOPE,
    "title": "NSI Terminale Spécialité",
    "owner": "equipe-nsi",
    "expected_topics": ["algorithmique"],
    "expected_resource_types": ["cours"],
    "allowed_domains": [DOMAIN],
    "source_authority": "official",
    "search_cadence": "weekly",
    "max_queries_per_run": 10,
    "max_documents_per_run": 20,
    "max_chunk_size": 800,
    "chunk_overlap": 100,
    "min_source_confidence": 0.7,
    "min_scope_confidence": 0.7,
    "min_extraction_quality": 0.1,
})
REGISTRY = {(PROFILE.scope.collection, PROFILE.profile_version): PROFILE}
PROFILE_FINGERPRINT = profile_fingerprint(PROFILE)

RICH_CONTENT = (
    b"<p>Ce cours d'algorithmique aborde la recursivite, les structures de "
    b"donnees, les boucles, les fonctions et plusieurs algorithmes de tri "
    b"classiques du programme de terminale, avec exemples et exercices "
    b"corriges pour couvrir largement la notion.</p>"
)
RICH_CONTENT_SHA = hashlib.sha256(RICH_CONTENT).hexdigest()

#: Ce que la dérivation gouvernée doit produire pour ce candidat et ce
#: profil — écrit ici en toutes lettres pour qu'un changement silencieux de
#: la dérivation soit visible dans le diff de ce test.
EXPECTED_ATTRIBUTION = {
    "source_label": DOMAIN,
    "official": True,
    "source_kind": DOMAIN,
    "type_doc": "cours",
}

PRODUCT_MIGRATIONS = (
    "001_rag_chunks_v2_schema.sql",
    "002_hybrid_retrieval.sql",
    "003_profile_filtering.sql",
    "004_artifact_placements.sql",
)

CONFORMING = ConformityResult(
    niveau_conformity=True,
    voie_conformity=True,
    matiere_conformity=True,
    programme_conformity=True,
    matiere_evidence=("algorithmique",),
)


def authorization_document() -> dict[str, Any]:
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    return {
        "protocol_version": "LOT41A-V2",
        "authorization_id": STUB_AUTHORIZATION_ID,
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "scope": dict(VALID_SCOPE),
        "manifest_digest": MANIFEST_DIGEST,
        "profile_id": PROFILE.scope.collection,
        "profile_version": PROFILE.profile_version,
        "profile_fingerprint": PROFILE_FINGERPRINT,
        "allowed_domains": [DOMAIN],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "allowed_content_sha256": [RICH_CONTENT_SHA],
        "pii_absence_attested": True,
        "pii_absence_evidence": "Corpus officiel, aucune donnee personnelle.",
        "valid_from": (now - timedelta(days=1)).isoformat(),
        "valid_until": (now + timedelta(days=365)).isoformat(),
    }


# ---------------------------------------------------------------------------
# Socle : base jetable réelle, schéma de contrôle ET schéma produit
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg() -> Iterator[dict[str, str]]:
    for instance in start_ingestion_control_postgres("h2f-attribution"):
        _apply_product_migrations(instance)
        yield instance


def _apply_product_migrations(pg: dict[str, str]) -> None:
    """Applique les VRAIES migrations produit, dans l'ordre du manifeste.

    Le schéma produit est nécessaire au seul scénario de publication ; il
    est appliqué avec la connexion administrative, jamais avec l'un des
    quatre rôles gouvernés — aucun d'eux ne doit pouvoir créer d'objet dans
    ``public``."""
    directory = ENGINE_ROOT / "infra" / "postgres" / "migrations"
    for name in PRODUCT_MIGRATIONS:
        result = subprocess.run(
            [
                "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1",
                "-h", pg["host"], "-p", pg["port"], "-U", PG_SUPERUSER,
                "-d", pg["dbname"], "-f", str(directory / name),
            ],
            env={"PGPASSWORD": PG_SUPERUSER_PASSWORD, "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, f"{name}: {result.stderr}"


@pytest.fixture(autouse=True)
def _clean(pg: dict[str, str]) -> Iterator[None]:
    with psycopg.connect(superuser_dsn(pg)) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE TABLE public.rag_chunks, "
                "public.rag_artifact_placements, public.rag_artifacts"
            )
            for table in (
                "publication_commit_pins", "publication_attestations",
                "artifact_attributions", "scope_authorizations",
                "workflow_events", "artifacts", "resource_candidates",
                "jobs", "resources", "ingestion_runs",
            ):
                cur.execute(f"DELETE FROM ingestion_control.{table}")  # noqa: S608
        conn.commit()
    yield


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[LocalGitHub]:
    state = LocalGitHub()
    state.add_approved_pr(
        number=AUTH_PR, head_sha=AUTH_HEAD, base_sha=AUTH_BASE, review_id=AUTH_REVIEW,
    )
    state.add_approved_pr(
        number=PUB_PR, head_sha=PUB_HEAD, base_sha=AUTH_BASE, review_id=PUB_REVIEW,
        submitted_at="2026-08-09T10:00:00Z",
    )
    state.put_blob(
        path=canonical_authorization_path(STUB_AUTHORIZATION_ID),
        ref=AUTH_HEAD,
        content=ScopeAuthorizationArtifactV2.model_validate(
            authorization_document()
        ).canonical_bytes(),
    )
    token_file = tmp_path / "gh-token"
    token_file.write_text(VALID_TOKEN, encoding="utf-8")
    with local_github_server(state) as base_url:
        monkeypatch.setenv("NEXUS_GITHUB_API_BASE", base_url)
        monkeypatch.setenv("NEXUS_GITHUB_TOKEN_FILE", str(token_file))
        monkeypatch.delenv("NEXUS_GITHUB_TOKEN", raising=False)
        yield state


@pytest.fixture
def operator_env(pg: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_INGESTION_CONTROL_AUTHORITY_DSN", authority_dsn(pg))
    monkeypatch.setenv("PG_INGESTION_CONTROL_ATTESTOR_DSN", attestor_dsn(pg))
    monkeypatch.delenv("PG_INGESTION_CONTROL_DSN", raising=False)


# ---------------------------------------------------------------------------
# Le VRAI workflow de production, jusqu'au gate qui fige les quatre faits
# ---------------------------------------------------------------------------


def _make_run(conn: psycopg.Connection) -> uuid.UUID:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.ingestion_runs
                (tenant, collection, niveau, voie, matiere, candidat, audience,
                 visibility, school_year, programme_version, profile_version,
                 trigger, status)
            VALUES (%(tenant)s, %(collection)s, %(niveau)s, %(voie)s, %(matiere)s,
                    %(candidat)s, %(audience)s, %(visibility)s, %(school_year)s,
                    %(programme_version)s, 'v1', 'manual', 'planned')
            RETURNING run_id
            """,
            {**VALID_SCOPE, "audience": sorted(VALID_SCOPE["audience"])},
        )
        row = cur.fetchone()
    assert row is not None
    conn.commit()
    return row[0]


def _unblock_documented_placeholders(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise **exactement** les deux placeholders documentés.

    ``classify_conformity_core`` renvoie toujours « non vérifié » pour
    niveau/voie/programme et ``assess_rights_core`` toujours
    ``Rights.unknown`` faute de preuve de licence gouvernée : ce sont les
    deux seules raisons pour lesquelles le worker vivant n'atteint pas
    ``ROUTED``. Rien d'autre n'est substitué — surtout pas le writer, ni la
    transition, ni le gate."""
    monkeypatch.setattr(
        classifier_module, "classify_conformity_core",
        lambda **_kwargs: CONFORMING,
    )
    monkeypatch.setattr(
        rights_module, "assess_rights_core",
        lambda **_kwargs: Rights.officiel_public,
    )


def run_production_pipeline(
    pg: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Exécute ``run_worker_iteration`` — la boucle de production — et rend
    ``(resource_id, ingestion_artifact_id, run_id)``."""
    _unblock_documented_placeholders(monkeypatch)

    def fetch(url: str, *, max_bytes: int, **_kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=RICH_CONTENT,
            request=httpx.Request("GET", url),
        )

    # Le digest est celui de l'artefact d'autorité RÉELLEMENT commité et
    # revu : le Fetcher l'écrit dans l'événement FETCHED, et LOT42 le
    # reconfronte à l'autorisation relue en direct. Un digest factice
    # ferait échouer la chaîne pour une raison sans rapport avec ce lot.
    auth = dataclasses.replace(
        verified_authorization(
            scope=VALID_SCOPE,
            manifest_digest=MANIFEST_DIGEST,
            profile_id=PROFILE.scope.collection,
            profile_version=PROFILE.profile_version,
            profile_fingerprint=PROFILE_FINGERPRINT,
            rights_categories=("officiel_public",),
            protocol_version="LOT41A-V2",
            allowed_content_sha256=(RICH_CONTENT_SHA,),
        ),
        authorization_digest=ScopeAuthorizationArtifactV2.model_validate(
            authorization_document()
        ).digest(),
    )
    deps = WorkerDeps(
        owner="worker-h2f",
        profile_registry=REGISTRY,
        artifact_store=make_filesystem_artifact_store(tmp_path / "artifacts"),
        artifact_reader=make_filesystem_artifact_reader(tmp_path / "artifacts"),
        validate_destination=lambda url: url,
        safe_fetch=fetch,
        verify_scope_authorization=stub_verifier(auth),
        manifest_digest=MANIFEST_DIGEST,
    )
    with psycopg.connect(app_dsn(pg)) as conn:
        run_id = _make_run(conn)
        create_job(
            conn, run_id=run_id, job_type="resource_pipeline",
            payload={
                "scope": VALID_SCOPE,
                "dedup_key": "e" * 64,
                "source_url": CANONICAL_URL,
                "canonical_url": CANONICAL_URL,
                "domain": DOMAIN,
                "proposed_type_doc": "cours",
                "profile_version": "v1",
                "scope_authorization_id": STUB_AUTHORIZATION_ID,
            },
        )
        conn.commit()
        outcome = run_worker_iteration(conn, deps=deps)
        assert outcome.status == "succeeded", outcome.error
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT resource_id, resource_state FROM ingestion_control.resources"
            )
            resource_id, resource_state = cur.fetchone()
            cur.execute(
                "SELECT artifact_id FROM ingestion_control.artifacts "
                "WHERE resource_id = %s",
                (resource_id,),
            )
            (artifact_id,) = cur.fetchone()
    assert resource_state == ResourceState.ROUTED.value
    return resource_id, artifact_id, run_id


@pytest.fixture
def routed(
    pg: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    return run_production_pipeline(pg, tmp_path, monkeypatch)


# ---------------------------------------------------------------------------
# 2/3 — le writer est appelé par le workflow de production, sous le rôle app
# ---------------------------------------------------------------------------


class TestProductionWorkflowWritesTheAttribution:
    def test_the_worker_loop_persists_the_four_facts(
        self, pg: dict[str, str], routed: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        """Exigence 2 et 3 : ``run_worker_iteration`` — et non un montage de
        test — écrit la ligne, avec la connexion du rôle applicatif."""
        _resource_id, artifact_id, run_id = routed
        with psycopg.connect(app_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT source_label, official, source_kind, type_doc, "
                "recorded_by_run_id, recorded_by_actor, attribution_digest "
                "FROM ingestion_control.artifact_attributions "
                "WHERE ingestion_artifact_id = %s",
                (artifact_id,),
            )
            row = cur.fetchone()
        assert row is not None, "le workflow de production n'a rien écrit"
        assert row[:4] == (
            EXPECTED_ATTRIBUTION["source_label"],
            EXPECTED_ATTRIBUTION["official"],
            EXPECTED_ATTRIBUTION["source_kind"],
            EXPECTED_ATTRIBUTION["type_doc"],
        )
        assert row[4] == run_id
        assert row[5] == "worker-h2f"
        assert row[6] == attribution_digest(
            ingestion_artifact_id=artifact_id, **EXPECTED_ATTRIBUTION  # type: ignore[arg-type]
        )

    def test_the_attribution_shares_the_routed_transaction(
        self, pg: dict[str, str], routed: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        """L'écriture est dans la transaction canonique du gate : la
        ressource est ``ROUTED``, l'événement de gate est présent, et
        l'attribution existe — les trois ou aucun."""
        resource_id, artifact_id, _run_id = routed
        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT resource_state FROM ingestion_control.resources "
                "WHERE resource_id = %s",
                (resource_id,),
            )
            assert cur.fetchone() == (ResourceState.ROUTED.value,)
            cur.execute(
                "SELECT COUNT(*) FROM ingestion_control.workflow_events "
                "WHERE resource_id = %s AND event_type = 'PUBLICATION_GATE_EVALUATED' "
                "AND (payload->>'gate_passed')::boolean",
                (resource_id,),
            )
            assert cur.fetchone() == (1,)
            cur.execute(
                "SELECT COUNT(*) FROM ingestion_control.artifact_attributions "
                "WHERE ingestion_artifact_id = %s",
                (artifact_id,),
            )
            assert cur.fetchone() == (1,)

    def test_no_product_row_exists_before_publication(
        self, pg: dict[str, str], routed: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        """Exigence 1 : à ce stade, ``public.rag_artifacts`` est vide. Toute
        lecture d'attribution qui y serait faite échouerait — c'est
        exactement le défaut que ce lot corrige."""
        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM public.rag_artifacts")
            assert cur.fetchone() == (0,)


# ---------------------------------------------------------------------------
# 4/5/6 — rôles réels : l'attestor lit, n'écrit pas, et n'a pas besoin du produit
# ---------------------------------------------------------------------------


class TestRoleIsolation:
    def test_the_attestor_role_reads_the_attribution(
        self, pg: dict[str, str], routed: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        _resource_id, artifact_id, _run_id = routed
        with psycopg.connect(attestor_dsn(pg)) as conn:
            attribution, digest = load_artifact_attribution(
                conn, ingestion_artifact_id=artifact_id
            )
        assert attribution.source_kind == EXPECTED_ATTRIBUTION["source_kind"]
        assert digest == attribution.digest

    @pytest.mark.parametrize(
        "statement",
        (
            "INSERT INTO ingestion_control.artifact_attributions "
            "(ingestion_artifact_id, resource_id, source_label, official, "
            "source_kind, type_doc, recorded_by_run_id, recorded_by_actor) "
            "VALUES (%(artifact)s, %(resource)s, 'x', true, 'x', 'cours', "
            "%(run)s, 'attestor')",
            "UPDATE ingestion_control.artifact_attributions "
            "SET source_label = 'forged' WHERE ingestion_artifact_id = %(artifact)s",
            "DELETE FROM ingestion_control.artifact_attributions "
            "WHERE ingestion_artifact_id = %(artifact)s",
        ),
    )
    def test_the_attestor_role_can_never_write(
        self, pg: dict[str, str], routed: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
        statement: str,
    ) -> None:
        """Exigence 5 : un vrai ``InsufficientPrivilege``, mesuré sur les
        GRANT réellement provisionnés — jamais une garde applicative."""
        resource_id, artifact_id, run_id = routed
        with psycopg.connect(attestor_dsn(pg)) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(
                    statement,
                    {"artifact": artifact_id, "resource": resource_id, "run": run_id},
                )
            conn.rollback()

    def test_the_attestor_role_has_no_product_schema_access(
        self, pg: dict[str, str]
    ) -> None:
        """Exigence 6 : l'attestation n'a jamais besoin du schéma produit —
        et n'y a d'ailleurs aucun droit."""
        with psycopg.connect(attestor_dsn(pg)) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("SELECT COUNT(*) FROM public.rag_artifacts")
            conn.rollback()

    def test_the_generated_digest_column_is_writable_by_nobody(
        self, pg: dict[str, str], routed: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        _resource_id, artifact_id, _run_id = routed
        with psycopg.connect(app_dsn(pg)) as conn:
            with pytest.raises(psycopg.errors.Error):
                conn.execute(
                    "UPDATE ingestion_control.artifact_attributions "
                    "SET attribution_digest = %s WHERE ingestion_artifact_id = %s",
                    ("0" * 64, artifact_id),
                )
            conn.rollback()


# ---------------------------------------------------------------------------
# 7/8/9/10 — refus de contrat, mesurés contre la vraie base
# ---------------------------------------------------------------------------


class TestWriterRefusals:
    def test_an_unknown_ingestion_uuid_is_refused(self, pg: dict[str, str]) -> None:
        """Exigence 7."""
        with psycopg.connect(app_dsn(pg)) as conn:
            with pytest.raises(ArtifactAttributionError, match="does not exist"):
                persist_artifact_attribution(
                    conn,
                    attribution=ArtifactAttribution(
                        ingestion_artifact_id=uuid.uuid4(),
                        **EXPECTED_ATTRIBUTION,  # type: ignore[arg-type]
                    ),
                    run_id=uuid.uuid4(),
                    actor="worker-h2f",
                )
            conn.rollback()

    def test_the_published_artifact_id_is_refused_as_the_key(
        self, pg: dict[str, str], routed: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        """Exigence 8 : le ``artifact_id`` produit est le SHA-256 du
        contenu. Passé à la place de l'UUID d'ingestion, il est refusé
        avant même d'atteindre la base."""
        with psycopg.connect(app_dsn(pg)) as conn:
            with pytest.raises(ArtifactAttributionError, match="UUID"):
                persist_artifact_attribution(
                    conn,
                    attribution=ArtifactAttribution(
                        ingestion_artifact_id=RICH_CONTENT_SHA,  # type: ignore[arg-type]
                        **EXPECTED_ATTRIBUTION,  # type: ignore[arg-type]
                    ),
                    run_id=uuid.uuid4(),
                    actor="worker-h2f",
                )
            conn.rollback()
        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM ingestion_control.artifact_attributions"
            )
            # La seule ligne est celle du pipeline ; aucune ligne parasite.
            assert cur.fetchone() == (1,)

    @pytest.mark.parametrize(
        "column", ("source_label", "official", "source_kind", "type_doc")
    )
    def test_a_missing_field_is_refused_by_the_database_itself(
        self, pg: dict[str, str], routed: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
        column: str,
    ) -> None:
        """Exigence 9 : le refus est une contrainte ``NOT NULL``, pas une
        convention applicative — mesurée en écrivant directement en SQL."""
        resource_id, artifact_id, run_id = routed
        columns = {
            "ingestion_artifact_id": uuid.uuid4(),
            "resource_id": resource_id,
            "source_label": "Éduscol",
            "official": True,
            "source_kind": DOMAIN,
            "type_doc": "cours",
            "recorded_by_run_id": run_id,
            "recorded_by_actor": "direct-sql",
        }
        columns[column] = None
        del artifact_id  # la ligne testée est neuve : la clé du pipeline reste intacte
        names = ", ".join(columns)
        placeholders = ", ".join(f"%({name})s" for name in columns)
        with psycopg.connect(app_dsn(pg)) as conn:
            with pytest.raises(psycopg.errors.NotNullViolation):
                conn.execute(
                    f"INSERT INTO ingestion_control.artifact_attributions "  # noqa: S608
                    f"({names}) VALUES ({placeholders})",
                    columns,
                )
            conn.rollback()

    @pytest.mark.parametrize(
        "column", ("source_label", "source_kind", "type_doc")
    )
    @pytest.mark.parametrize("blank", ("", "   "))
    def test_a_blank_string_is_refused_by_the_database_itself(
        self, pg: dict[str, str], routed: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
        column: str, blank: str,
    ) -> None:
        """Exigence 10 : ``NOT NULL`` ne suffit pas — une chaîne vide est
        une valeur. Le ``CHECK`` de la migration 012 la refuse."""
        resource_id, _artifact_id, run_id = routed
        columns: dict[str, Any] = {
            "ingestion_artifact_id": uuid.uuid4(),
            "resource_id": resource_id,
            "source_label": "Éduscol",
            "official": True,
            "source_kind": DOMAIN,
            "type_doc": "cours",
            "recorded_by_run_id": run_id,
            "recorded_by_actor": "direct-sql",
        }
        columns[column] = blank
        names = ", ".join(columns)
        placeholders = ", ".join(f"%({name})s" for name in columns)
        with psycopg.connect(app_dsn(pg)) as conn:
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(
                    f"INSERT INTO ingestion_control.artifact_attributions "  # noqa: S608
                    f"({names}) VALUES ({placeholders})",
                    columns,
                )
            conn.rollback()


# ---------------------------------------------------------------------------
# 11/12/15 — idempotence, correction avant attestation, atomicité
# ---------------------------------------------------------------------------


def _attribution_of(pg: dict[str, str], artifact_id: uuid.UUID) -> tuple[Any, ...]:
    with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT source_label, official, source_kind, type_doc, "
            "attribution_digest, recorded_at "
            "FROM ingestion_control.artifact_attributions "
            "WHERE ingestion_artifact_id = %s",
            (artifact_id,),
        )
        row = cur.fetchone()
    assert row is not None
    return tuple(row)


class TestIdempotenceAndAtomicity:
    def test_rewriting_the_same_facts_is_a_no_op(
        self, pg: dict[str, str], routed: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        """Exigence 11 : même valeurs, même digest, même ligne — y compris
        ``recorded_at``, qui prouve qu'aucun UPDATE n'a eu lieu."""
        _resource_id, artifact_id, run_id = routed
        before = _attribution_of(pg, artifact_id)
        with psycopg.connect(app_dsn(pg)) as conn:
            digest = persist_artifact_attribution(
                conn,
                attribution=ArtifactAttribution(
                    ingestion_artifact_id=artifact_id,
                    **EXPECTED_ATTRIBUTION,  # type: ignore[arg-type]
                ),
                run_id=run_id,
                actor="worker-h2f",
            )
            conn.commit()
        assert digest == before[4]
        assert _attribution_of(pg, artifact_id) == before

    def test_a_correction_before_attestation_is_accepted(
        self, pg: dict[str, str], routed: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        """Exigence 12 : tant qu'aucune attestation ne nomme cet artefact,
        le pipeline peut corriger ce qu'il a écrit."""
        _resource_id, artifact_id, run_id = routed
        corrected = {**EXPECTED_ATTRIBUTION, "source_label": "Éduscol — NSI"}
        with psycopg.connect(app_dsn(pg)) as conn:
            digest = persist_artifact_attribution(
                conn,
                attribution=ArtifactAttribution(
                    ingestion_artifact_id=artifact_id,
                    **corrected,  # type: ignore[arg-type]
                ),
                run_id=run_id,
                actor="worker-h2f",
            )
            conn.commit()
        stored = _attribution_of(pg, artifact_id)
        assert stored[0] == "Éduscol — NSI"
        assert stored[4] == digest
        assert digest != attribution_digest(
            ingestion_artifact_id=artifact_id, **EXPECTED_ATTRIBUTION  # type: ignore[arg-type]
        )

    def test_a_rolled_back_transaction_leaves_no_partial_attribution(
        self, pg: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exigence 15 : l'écriture ne committe rien d'elle-même. Une
        transaction annulée après le writer ne laisse aucune ligne."""
        resource_id, artifact_id, run_id = run_production_pipeline(
            pg, tmp_path, monkeypatch
        )
        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM ingestion_control.artifact_attributions "
                "WHERE ingestion_artifact_id = %s",
                (artifact_id,),
            )
            conn.commit()
        del resource_id
        with psycopg.connect(app_dsn(pg)) as conn:
            persist_artifact_attribution(
                conn,
                attribution=ArtifactAttribution(
                    ingestion_artifact_id=artifact_id,
                    **EXPECTED_ATTRIBUTION,  # type: ignore[arg-type]
                ),
                run_id=run_id,
                actor="worker-h2f",
            )
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM ingestion_control.artifact_attributions "
                    "WHERE ingestion_artifact_id = %s",
                    (artifact_id,),
                )
                assert cur.fetchone() == (1,), "la ligne doit exister dans la transaction"
            conn.rollback()
        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM ingestion_control.artifact_attributions "
                "WHERE ingestion_artifact_id = %s",
                (artifact_id,),
            )
            assert cur.fetchone() == (0,)


# ---------------------------------------------------------------------------
# Chaîne d'attestation LOT42 réelle, puis 13/14/16/17
# ---------------------------------------------------------------------------


def record_authorization(github: LocalGitHub) -> None:
    assert authorize_scope_main([
        "record-authorization",
        "--authorization-id", STUB_AUTHORIZATION_ID,
        "--repository", REPOSITORY,
        "--pull-request", str(AUTH_PR),
        "--expected-head", AUTH_HEAD,
    ]) == 0


def propose(resource_id: uuid.UUID, artifact_id: uuid.UUID, capsys: Any) -> tuple[int, str, str]:
    capsys.readouterr()
    code = attest_main([
        "propose-review",
        "--resource-id", str(resource_id),
        "--artifact-id", str(artifact_id),
        "--scope-authorization-id", STUB_AUTHORIZATION_ID,
        "--review-id", REVIEW_ID,
    ])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def parse_proposal(output: str) -> tuple[str, bytes]:
    lines = output.splitlines(keepends=True)
    index = next(
        i for i, line in enumerate(lines) if line.startswith("REVIEW_ARTIFACT_PATH ")
    )
    path = lines[index].split(" ", 1)[1].strip()
    assert lines[index + 1].startswith("REVIEW_ARTIFACT_DIGEST ")
    return path, "".join(lines[index + 2:]).encode("utf-8")


def attest(resource_id: uuid.UUID, artifact_id: uuid.UUID) -> int:
    return attest_main([
        "record-attestation",
        "--resource-id", str(resource_id),
        "--artifact-id", str(artifact_id),
        "--scope-authorization-id", STUB_AUTHORIZATION_ID,
        "--review-id", REVIEW_ID,
        "--repository", REPOSITORY,
        "--pull-request", str(PUB_PR),
        "--expected-head", PUB_HEAD,
    ])


@pytest.fixture
def attested(
    pg: dict[str, str], routed: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    github: LocalGitHub, operator_env: None, capsys: Any,
) -> dict[str, Any]:
    resource_id, artifact_id, run_id = routed
    record_authorization(github)
    code, output, error = propose(resource_id, artifact_id, capsys)
    assert code == 0, error
    path, raw = parse_proposal(output)
    github.put_blob(path=path, ref=PUB_HEAD, content=raw)
    assert attest(resource_id, artifact_id) == 0
    return {
        "resource_id": resource_id, "artifact_id": artifact_id,
        "run_id": run_id, "path": path, "raw": raw,
    }


def _verify(pg: dict[str, str], attested: dict[str, Any]) -> Any:
    with psycopg.connect(superuser_dsn(pg)) as conn:
        return verify_publication_attestation(
            conn,
            resource_id=attested["resource_id"],
            current_content_sha256=RICH_CONTENT_SHA,
            current_profile_fingerprint=PROFILE_FINGERPRINT,
            current_manifest_digest=MANIFEST_DIGEST,
            require_content_bound_authority=True,
        )


class TestTheReviewedArtifactIsLot42V2:
    """ADR-0035 § 6 (constat F3) : ce que l'humain approuve désigne
    l'attribution exacte, et une V1 n'autorise plus rien."""

    def test_the_attestation_row_is_v2(
        self, pg: dict[str, str], attested: dict[str, Any]
    ) -> None:
        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT protocol_version FROM "
                "ingestion_control.publication_attestations WHERE resource_id = %s",
                (attested["resource_id"],),
            )
            assert cur.fetchone() == ("LOT42-V2",)

    def test_the_reviewed_artifact_bytes_carry_the_attribution_digest(
        self, pg: dict[str, str], attested: dict[str, Any]
    ) -> None:
        """Le digest n'est pas seulement en base : il est **dans les octets
        que l'humain a relus**, donc dans leur digest et dans leur chemin
        canonique."""
        from nexus_contracts.authority_artifacts import (
            parse_publication_review_artifact,
            require_publication_review_v2,
        )

        with psycopg.connect(attestor_dsn(pg)) as conn:
            facts = collect_publication_facts(
                conn,
                resource_id=attested["resource_id"],
                artifact_id=attested["artifact_id"],
            )
        reviewed = require_publication_review_v2(
            parse_publication_review_artifact(attested["raw"])
        )
        assert reviewed.attributed_facts_digest == facts.attribution_digest
        assert reviewed.attributed_facts_digest in reviewed.canonical_bytes().decode()
        assert reviewed.digest() in reviewed.canonical_path()

    def test_a_v1_attestation_can_never_publish(
        self, pg: dict[str, str], attested: dict[str, Any]
    ) -> None:
        """Coexistence historique côté schéma, refus côté runtime : la
        ligne est repassée en V1 (digest retiré, comme une vraie ligne
        historique) et la publication doit être refusée."""
        with psycopg.connect(superuser_dsn(pg)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT attributed_facts_digest FROM "
                    "ingestion_control.publication_attestations "
                    "WHERE resource_id = %s",
                    (attested["resource_id"],),
                )
                (digest,) = cur.fetchone()
            conn.execute(
                "UPDATE ingestion_control.publication_attestations "
                "SET protocol_version = 'LOT42-V1', attributed_facts_digest = NULL "
                "WHERE resource_id = %s",
                (attested["resource_id"],),
            )
            conn.commit()
            try:
                # G4 : la cause est épinglée. Sans ``match``, ce test
                # passerait aussi bien pour une fixture cassée que pour la
                # barrière visée. Le blob Git reste V2 ; c'est donc la
                # comparaison artefact revu <-> ligne attestée qui doit
                # refuser, en nommant le champ divergent.
                with pytest.raises(
                    PublicationAttestationInvalidError,
                    match=r"protocol_version drift",
                ):
                    _verify(pg, attested)
            finally:
                conn.execute(
                    "UPDATE ingestion_control.publication_attestations "
                    "SET protocol_version = 'LOT42-V2', "
                    "    attributed_facts_digest = %s "
                    "WHERE resource_id = %s",
                    (digest, attested["resource_id"]),
                )
                conn.commit()


class TestAttestationSealsTheAttribution:
    def test_the_reviewed_proposal_carries_the_persisted_attribution(
        self, pg: dict[str, str], attested: dict[str, Any]
    ) -> None:
        with psycopg.connect(attestor_dsn(pg)) as conn:
            facts = collect_publication_facts(
                conn,
                resource_id=attested["resource_id"],
                artifact_id=attested["artifact_id"],
            )
        assert facts.source_label == EXPECTED_ATTRIBUTION["source_label"]
        assert facts.official is EXPECTED_ATTRIBUTION["official"]
        assert facts.source_kind == EXPECTED_ATTRIBUTION["source_kind"]
        assert facts.type_doc == EXPECTED_ATTRIBUTION["type_doc"]
        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT attributed_facts_digest FROM "
                "ingestion_control.publication_attestations WHERE resource_id = %s",
                (attested["resource_id"],),
            )
            assert cur.fetchone() == (facts.attribution_digest,)

    def test_a_mutation_after_attestation_is_refused_by_the_database(
        self, pg: dict[str, str], attested: dict[str, Any]
    ) -> None:
        """Exigence 13 : le trigger de la migration 012, pas une garde
        Python — la tentative passe par le rôle applicatif, qui détient
        pourtant bien le privilège ``UPDATE``."""
        with psycopg.connect(app_dsn(pg)) as conn:
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="ATTRIBUTION_SEALED_BY_ATTESTATION",
            ):
                conn.execute(
                    "UPDATE ingestion_control.artifact_attributions "
                    "SET source_label = 'Éditeur privé' "
                    "WHERE ingestion_artifact_id = %s",
                    (attested["artifact_id"],),
                )
            conn.rollback()

        with psycopg.connect(app_dsn(pg)) as conn:
            with pytest.raises(psycopg.errors.RaiseException):
                persist_artifact_attribution(
                    conn,
                    attribution=ArtifactAttribution(
                        ingestion_artifact_id=attested["artifact_id"],
                        **{**EXPECTED_ATTRIBUTION, "official": False},  # type: ignore[arg-type]
                    ),
                    run_id=attested["run_id"],
                    actor="worker-h2f",
                )
            conn.rollback()

    def test_an_identical_rewrite_after_attestation_stays_idempotent(
        self, pg: dict[str, str], attested: dict[str, Any]
    ) -> None:
        with psycopg.connect(app_dsn(pg)) as conn:
            digest = persist_artifact_attribution(
                conn,
                attribution=ArtifactAttribution(
                    ingestion_artifact_id=attested["artifact_id"],
                    **EXPECTED_ATTRIBUTION,  # type: ignore[arg-type]
                ),
                run_id=attested["run_id"],
                actor="worker-h2f",
            )
            conn.commit()
        assert digest == _attribution_of(pg, attested["artifact_id"])[4]

    def test_a_deletion_after_attestation_is_refused(
        self, pg: dict[str, str], attested: dict[str, Any]
    ) -> None:
        with psycopg.connect(superuser_dsn(pg)) as conn:
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="ATTRIBUTION_SEALED_BY_ATTESTATION",
            ):
                conn.execute(
                    "DELETE FROM ingestion_control.artifact_attributions "
                    "WHERE ingestion_artifact_id = %s",
                    (attested["artifact_id"],),
                )
            conn.rollback()

    def test_a_diverging_attested_digest_blocks_the_publication(
        self, pg: dict[str, str], attested: dict[str, Any]
    ) -> None:
        """Exigence 14 : même si l'attribution et l'attestation étaient
        toutes deux modifiables (elles ne le sont pas), le publisher
        recompare le digest attesté aux faits relus et refuse."""
        with psycopg.connect(superuser_dsn(pg)) as conn:
            conn.execute(
                "UPDATE ingestion_control.publication_attestations "
                "SET attributed_facts_digest = %s WHERE resource_id = %s",
                ("0" * 64, attested["resource_id"]),
            )
            conn.commit()
        # ADR-0035 : le refus arrive désormais plus tôt qu'avant. La
        # comparaison artefact revu <-> ligne attestée
        # (``_require_row_matches_artifact``) voit la dérive avant la
        # comparaison ligne <-> faits relus. Les deux branches de
        # l'égalité à trois voies protègent le même invariant ; c'est la
        # première atteinte qui nomme l'écart.
        with pytest.raises(
            PublicationAttestationInvalidError, match="attributed_facts_digest"
        ):
            _verify(pg, attested)

    def test_a_v2_attestation_cannot_even_be_stripped_of_its_digest(
        self, pg: dict[str, str], attested: dict[str, Any]
    ) -> None:
        """ADR-0035 § 7 : l'invariant a migré du runtime vers le schéma.

        Retirer le digest d'une attestation V2 n'aboutit plus à une
        publication refusée à la relecture — l'écriture elle-même est
        impossible. Une attestation sans digest ne peut exister que sous
        l'étiquette V1, et une V1 ne publie rien
        (``test_a_v1_attestation_can_never_publish``)."""
        with psycopg.connect(superuser_dsn(pg)) as conn:
            with pytest.raises(
                psycopg.errors.CheckViolation,
                match="attribution_digest_matches_protocol",
            ):
                conn.execute(
                    "UPDATE ingestion_control.publication_attestations "
                    "SET attributed_facts_digest = NULL WHERE resource_id = %s",
                    (attested["resource_id"],),
                )


class TestMissingWriterFailsClosed:
    def test_without_the_attribution_no_proposal_is_possible(
        self, pg: dict[str, str], routed: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
        github: LocalGitHub, operator_env: None, capsys: Any,
    ) -> None:
        """Exigence 16 : le writer retiré, la chaîne s'arrête — jamais une
        attribution devinée, jamais une publication « par défaut »."""
        resource_id, artifact_id, _run_id = routed
        with psycopg.connect(superuser_dsn(pg)) as conn:
            conn.execute(
                "DELETE FROM ingestion_control.artifact_attributions "
                "WHERE ingestion_artifact_id = %s",
                (artifact_id,),
            )
            conn.commit()
        record_authorization(github)
        code, _output, error = propose(resource_id, artifact_id, capsys)
        assert code == 1
        assert "DURABLE_EVIDENCE_MISSING" in error
        assert "no control-plane attribution record" in error

        with psycopg.connect(attestor_dsn(pg)) as conn:
            with pytest.raises(
                PublicationEvidenceMissingError, match="no control-plane attribution"
            ):
                collect_publication_facts(
                    conn, resource_id=resource_id, artifact_id=artifact_id
                )


# ---------------------------------------------------------------------------
# 17 — chemin complet valide, jusqu'à la publication produit
# ---------------------------------------------------------------------------


def _fake_vector(text: str) -> tuple[float, ...]:
    """Vecteur déterministe non nul de la bonne dimension. L'embedding est
    un point d'injection du publisher (``embed_chunks``), pas un invariant
    de ce lot — le substituer ne masque aucune écriture gouvernée."""
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
    raw = [math.sin(seed + index) for index in range(EMBED_DIMENSION)]
    norm = math.sqrt(sum(value * value for value in raw))
    return tuple(value / norm for value in raw)


class TestFullChainReachesPublication:
    def _promote(self, pg: dict[str, str], attested: dict[str, Any]) -> None:
        with psycopg.connect(app_dsn(pg)) as conn:
            state = get_resource_state(conn, resource_id=attested["resource_id"])
            assert state is not None
            _current, version = state
            staged = stage_publication_for_review(
                conn,
                resource_id=attested["resource_id"],
                run_id=attested["run_id"],
                expected_version=version,
                actor="worker-h2f",
            )
            promote_reviewed_publication(
                conn,
                resource_id=attested["resource_id"],
                run_id=attested["run_id"],
                expected_version=staged.needs_review.state_version,
                actor="worker-h2f",
                current_content_sha256=RICH_CONTENT_SHA,
                current_profile_fingerprint=PROFILE_FINGERPRINT,
                current_manifest_digest=MANIFEST_DIGEST,
            )
            conn.commit()

    def _placement(self, attested: dict[str, Any]) -> EligiblePlacement:
        return EligiblePlacement(
            resource_id=attested["resource_id"],
            scope=ResourceScope.model_validate(VALID_SCOPE),
            statut_enseignement="specialite",
            domain="algorithmique",
            source_scope="h2f-attribution",
            source_placement_id="h2f-attribution-1",
            source_path="corpus/nsi/algorithmique.html",
            source_uri=CANONICAL_URL,
            current_profile_fingerprint=PROFILE_FINGERPRINT,
            current_manifest_digest=MANIFEST_DIGEST,
        )

    def _artifact(self, **overrides: Any) -> GovernedArtifact:
        values: dict[str, Any] = {
            "content": RICH_CONTENT,
            "content_sha256": RICH_CONTENT_SHA,
            "source_uri": CANONICAL_URL,
            "rights": Rights.officiel_public.value,
            **EXPECTED_ATTRIBUTION,
        }
        values.update(overrides)
        return GovernedArtifact(**values)

    def test_the_whole_chain_publishes_the_attributed_facts(
        self, pg: dict[str, str], attested: dict[str, Any]
    ) -> None:
        """Exigence 17 : la publication produit aboutit, et les quatre
        valeurs écrites dans ``public.rag_artifacts`` sont exactement
        celles que le plan de contrôle a persistées puis scellées."""
        self._promote(pg, attested)
        with (
            psycopg.connect(app_dsn(pg)) as control_conn,
            psycopg.connect(superuser_dsn(pg)) as product_conn,
        ):
            result = publish_governed_artifact(
                control_conn,
                product_conn,
                self._artifact(),
                (self._placement(attested),),
                lambda raw: raw.decode("utf-8"),
                lambda chunks: [_fake_vector(chunk) for chunk in chunks],
            )
        assert result.artifact_created is True
        assert result.placement_rows == 1
        assert result.chunk_rows >= 1

        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT source_label, official, source_kind, type_doc, "
                "ingestion_artifact_id FROM public.rag_artifacts "
                "WHERE artifact_id = %s",
                (RICH_CONTENT_SHA,),
            )
            row = cur.fetchone()
        assert row == (
            EXPECTED_ATTRIBUTION["source_label"],
            EXPECTED_ATTRIBUTION["official"],
            EXPECTED_ATTRIBUTION["source_kind"],
            EXPECTED_ATTRIBUTION["type_doc"],
            attested["artifact_id"],
        )

    @pytest.mark.parametrize(
        "override",
        (
            {"source_label": "Éditeur privé"},
            {"official": False},
            {"source_kind": "example.org"},
            {"type_doc": "annale"},
        ),
    )
    def test_publishing_an_unattested_attribution_is_refused(
        self, pg: dict[str, str], attested: dict[str, Any], override: dict[str, Any]
    ) -> None:
        """Le publisher ne peut pas choisir librement l'attribution qu'il
        écrit : elle doit être celle que l'attestation a scellée."""
        self._promote(pg, attested)
        with (
            psycopg.connect(app_dsn(pg)) as control_conn,
            psycopg.connect(superuser_dsn(pg)) as product_conn,
        ):
            with pytest.raises(
                GovernedPublicationError, match="do not match publication"
            ):
                publish_governed_artifact(
                    control_conn,
                    product_conn,
                    self._artifact(**override),
                    (self._placement(attested),),
                    lambda raw: raw.decode("utf-8"),
                    lambda chunks: [_fake_vector(chunk) for chunk in chunks],
                )
        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM public.rag_artifacts")
            assert cur.fetchone() == (0,)


def test_derivation_matches_what_the_production_pipeline_persisted(
    pg: dict[str, str], routed: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
) -> None:
    """Garde-fou anti-divergence : la dérivation pure et la ligne écrite par
    le worker doivent produire le MÊME digest. Sans cela, un test pourrait
    valider une dérivation qui n'est plus celle du chemin de production."""
    _resource_id, artifact_id, _run_id = routed
    with psycopg.connect(app_dsn(pg)) as conn:
        stored, digest = load_artifact_attribution(
            conn, ingestion_artifact_id=artifact_id
        )
    with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM ingestion_control.resource_candidates LIMIT 1"
        )
        (payload,) = cur.fetchone()
    derived = derive_artifact_attribution(
        ingestion_artifact_id=artifact_id,
        candidate=ResourceCandidate.model_validate(payload),
        profile=PROFILE,
    )
    assert derived == stored
    assert derived.digest == digest
