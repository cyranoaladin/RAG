"""Isolation des autorités d'opérateur (remédiation GATE H1, item **K**).

PostgreSQL réel, rôles réels provisionnés par le vrai script. Ce fichier ne
relit pas des ``GRANT`` : il **tente les écritures interdites** et exige un
``InsufficientPrivilege`` de PostgreSQL lui-même. Une convention applicative
qui « n'écrit jamais là » ne prouve rien ; un privilège absent, si.

Couvre aussi la surface d'exécution : le service worker de longue durée ne
doit porter **aucun** secret d'autorité ou d'attestation, et deux services
ponctuels isolés doivent exister pour ces deux rôles.
"""
from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pg_authority import (  # noqa: E402
    app_dsn,
    attestor_dsn,
    authority_dsn,
    requires_docker,
    start_ingestion_control_postgres,
)

pytestmark = [pytest.mark.integration, requires_docker]

COMPOSE_FILE = ENGINE_ROOT / "infra" / "docker-compose.ingestion.yml"
DOCKERFILE = ENGINE_ROOT / "infra" / "Dockerfile.ingestion-worker"

#: Secrets qui ne doivent JAMAIS apparaître dans la définition du worker de
#: longue durée — ni comme mot de passe, ni comme DSN les portant.
FORBIDDEN_IN_WORKER = (
    "INGESTION_CONTROL_AUTHORITY_PASSWORD",
    "INGESTION_CONTROL_ATTESTOR_PASSWORD",
    "PG_INGESTION_CONTROL_AUTHORITY_DSN",
    "PG_INGESTION_CONTROL_ATTESTOR_DSN",
)


@pytest.fixture(scope="module")
def pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("lot41a-roles")


def denied(dsn: str, statement: str, params: tuple[Any, ...] = ()) -> str:
    """Exécute une instruction censée être refusée et rend le SQLSTATE.

    Toute autre issue — succès, ou échec pour une raison différente d'un
    privilège manquant — fait échouer le test : « ça n'a pas marché » n'est
    pas la même chose que « c'est interdit »."""
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(statement, params)
            except psycopg.errors.InsufficientPrivilege as exc:
                conn.rollback()
                return str(exc.sqlstate)
            except psycopg.Error as exc:  # pragma: no cover - diagnostic explicite
                conn.rollback()
                raise AssertionError(
                    f"statement failed, but NOT for a missing privilege: "
                    f"{type(exc).__name__} sqlstate={exc.sqlstate} — {exc}"
                ) from exc
        conn.rollback()
    raise AssertionError(f"statement was ALLOWED but must be denied: {statement}")


class TestWorkerRoleCannotWriteAuthorityTables:
    """Le worker lit les autorisations pour les vérifier lui-même — il ne
    peut jamais s'en écrire une."""

    def test_insert_scope_authorization_is_denied(self, pg: dict[str, str]) -> None:
        assert denied(
            app_dsn(pg),
            "INSERT INTO ingestion_control.scope_authorizations (authorization_id) VALUES ('x')",
        ) == "42501"

    def test_update_scope_authorization_is_denied(self, pg: dict[str, str]) -> None:
        assert denied(
            app_dsn(pg),
            "UPDATE ingestion_control.scope_authorizations SET valid_until = now()",
        ) == "42501"

    def test_delete_scope_authorization_is_denied(self, pg: dict[str, str]) -> None:
        assert denied(
            app_dsn(pg), "DELETE FROM ingestion_control.scope_authorizations"
        ) == "42501"

    def test_insert_publication_attestation_is_denied(self, pg: dict[str, str]) -> None:
        assert denied(
            app_dsn(pg),
            "INSERT INTO ingestion_control.publication_attestations (resource_id) "
            "VALUES (%s)",
            (uuid.uuid4(),),
        ) == "42501"

    def test_update_publication_attestation_is_denied(self, pg: dict[str, str]) -> None:
        assert denied(
            app_dsn(pg),
            "UPDATE ingestion_control.publication_attestations SET invalidated_at = now()",
        ) == "42501"

    def test_reading_authority_tables_is_allowed(self, pg: dict[str, str]) -> None:
        """La lecture EST nécessaire : le worker exécute lui-même la
        vérification live. Sans elle, l'isolation serait obtenue au prix du
        mécanisme qu'elle protège."""
        with psycopg.connect(app_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM ingestion_control.scope_authorizations")
            cur.execute("SELECT count(*) FROM ingestion_control.publication_attestations")


class TestAuthorityRoleIsConfinedToItsTable:
    def test_cannot_write_publication_attestations(self, pg: dict[str, str]) -> None:
        assert denied(
            authority_dsn(pg),
            "INSERT INTO ingestion_control.publication_attestations (resource_id) VALUES (%s)",
            (uuid.uuid4(),),
        ) == "42501"

    @pytest.mark.parametrize(
        "statement",
        [
            "INSERT INTO ingestion_control.resources (resource_id) VALUES (gen_random_uuid())",
            "INSERT INTO ingestion_control.jobs (job_id) VALUES (gen_random_uuid())",
            "INSERT INTO ingestion_control.workflow_events (event_type) VALUES ('x')",
            "SELECT count(*) FROM ingestion_control.resources",
            "SELECT count(*) FROM ingestion_control.workflow_events",
        ],
    )
    def test_cannot_touch_pipeline_tables(self, pg: dict[str, str], statement: str) -> None:
        assert denied(authority_dsn(pg), statement) == "42501"

    def test_cannot_delete_its_own_table(self, pg: dict[str, str]) -> None:
        """Une autorisation s'ajoute et se révoque, elle ne s'efface jamais —
        l'historique d'autorité est append-only de fait."""
        assert denied(
            authority_dsn(pg), "DELETE FROM ingestion_control.scope_authorizations"
        ) == "42501"

    def test_cannot_update_a_decision_column(self, pg: dict[str, str]) -> None:
        """Seules les colonnes de révocation sont modifiables : le GRANT est
        au niveau colonne, jamais au niveau table."""
        assert denied(
            authority_dsn(pg),
            "UPDATE ingestion_control.scope_authorizations SET allowed_domains = ARRAY['x']",
        ) == "42501"


class TestAttestorRoleIsConfinedToItsTable:
    def test_cannot_write_scope_authorizations(self, pg: dict[str, str]) -> None:
        assert denied(
            attestor_dsn(pg),
            "INSERT INTO ingestion_control.scope_authorizations (authorization_id) VALUES ('x')",
        ) == "42501"

    def test_cannot_revoke_a_scope_authorization(self, pg: dict[str, str]) -> None:
        assert denied(
            attestor_dsn(pg),
            "UPDATE ingestion_control.scope_authorizations SET revoked_at = now()",
        ) == "42501"

    @pytest.mark.parametrize(
        "statement",
        [
            "INSERT INTO ingestion_control.workflow_events (event_type) VALUES ('x')",
            "UPDATE ingestion_control.workflow_events SET actor = 'x'",
            "DELETE FROM ingestion_control.workflow_events",
            "UPDATE ingestion_control.resources SET resource_state = 'FAILED'",
            "UPDATE ingestion_control.artifacts SET sha256 = 'x'",
        ],
    )
    def test_cannot_write_pipeline_tables(self, pg: dict[str, str], statement: str) -> None:
        assert denied(attestor_dsn(pg), statement) == "42501"

    def test_can_read_the_durable_evidence_it_needs(self, pg: dict[str, str]) -> None:
        """Lecture indispensable (item E) : sans elle, le conteneur
        d'attestation devrait AUSSI porter le DSN du worker — exactement le
        cumul de credentials que l'item K interdit."""
        with psycopg.connect(attestor_dsn(pg)) as conn, conn.cursor() as cur:
            for table in ("workflow_events", "resources", "artifacts", "resource_candidates"):
                cur.execute(f"SELECT count(*) FROM ingestion_control.{table}")  # noqa: S608

    def test_cannot_update_an_attested_decision_column(self, pg: dict[str, str]) -> None:
        assert denied(
            attestor_dsn(pg),
            "UPDATE ingestion_control.publication_attestations SET content_sha256 = 'x'",
        ) == "42501"

    def test_cannot_delete_its_own_table(self, pg: dict[str, str]) -> None:
        assert denied(
            attestor_dsn(pg), "DELETE FROM ingestion_control.publication_attestations"
        ) == "42501"


class TestNoRoleCanEscalate:
    @pytest.mark.parametrize(
        "role", ["ingestion_control_authority", "ingestion_control_attestor", "raguser"]
    )
    def test_app_role_cannot_set_role(self, pg: dict[str, str], role: str) -> None:
        """``SET ROLE`` n'est permis que vers un rôle dont on est membre. Le
        provisioning révoque toute appartenance héritée — testé ici, jamais
        supposé."""
        assert denied(app_dsn(pg), f'SET ROLE "{role}"') == "42501"

    @pytest.mark.parametrize(
        "role", ["ingestion_control_app", "ingestion_control_attestor", "raguser"]
    )
    def test_authority_role_cannot_set_role(self, pg: dict[str, str], role: str) -> None:
        assert denied(authority_dsn(pg), f'SET ROLE "{role}"') == "42501"

    @pytest.mark.parametrize(
        "role", ["ingestion_control_app", "ingestion_control_authority", "raguser"]
    )
    def test_attestor_role_cannot_set_role(self, pg: dict[str, str], role: str) -> None:
        assert denied(attestor_dsn(pg), f'SET ROLE "{role}"') == "42501"

    @pytest.mark.parametrize("dsn_name", ["app", "authority", "attestor"])
    def test_no_role_can_write_the_public_schema(
        self, pg: dict[str, str], dsn_name: str
    ) -> None:
        dsn = {"app": app_dsn, "authority": authority_dsn, "attestor": attestor_dsn}[dsn_name](pg)
        assert denied(dsn, "CREATE TABLE public.escalation (x int)") == "42501"


class TestRuntimeSurfaceIsIsolated:
    """L'isolation des privilèges ne vaut que si les secrets ne se retrouvent
    pas tous dans le même conteneur. Ces assertions portent sur la
    définition Compose réellement déployée."""

    @staticmethod
    def _compose() -> dict[str, Any]:
        document: dict[str, Any] = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
        return document

    def test_the_long_lived_worker_holds_no_authority_secret(self) -> None:
        worker = self._compose()["services"]["ingestion-worker"]
        rendered = yaml.safe_dump(worker)
        for forbidden in FORBIDDEN_IN_WORKER:
            assert forbidden not in rendered, (
                f"{forbidden} must never reach the long-lived worker container"
            )

    def test_two_isolated_one_shot_operators_exist(self) -> None:
        services = self._compose()["services"]
        assert "scope-authority-operator" in services
        assert "publication-attestor-operator" in services

    @pytest.mark.parametrize(
        ("service", "own_secret", "foreign_secret"),
        [
            (
                "scope-authority-operator",
                "PG_INGESTION_CONTROL_AUTHORITY_DSN",
                "PG_INGESTION_CONTROL_ATTESTOR_DSN",
            ),
            (
                "publication-attestor-operator",
                "PG_INGESTION_CONTROL_ATTESTOR_DSN",
                "PG_INGESTION_CONTROL_AUTHORITY_DSN",
            ),
        ],
    )
    def test_each_operator_holds_exactly_one_role_credential(
        self, service: str, own_secret: str, foreign_secret: str
    ) -> None:
        definition = self._compose()["services"][service]
        environment = definition["environment"]
        assert own_secret in environment
        assert foreign_secret not in environment
        assert "PG_INGESTION_CONTROL_DSN" not in environment, (
            "an operator container must never also carry the worker credential"
        )

    @pytest.mark.parametrize(
        "service", ["scope-authority-operator", "publication-attestor-operator"]
    )
    def test_each_operator_is_a_hardened_one_shot(self, service: str) -> None:
        definition = self._compose()["services"][service]
        assert definition.get("restart") == "no", "an operator task never restarts"
        assert "ports" not in definition, "an operator task exposes no port"
        assert definition.get("read_only") is True
        assert "no-new-privileges:true" in definition.get("security_opt", [])
        assert definition.get("profiles") == ["operator"], (
            "an operator task must never start with a plain `up`"
        )

    def test_the_image_builds_no_secret_in(self) -> None:
        """Aucun ``ARG``/``ENV`` porteur de credential dans l'image : le
        jeton GitHub est monté à l'exécution, jamais construit dedans."""
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        for token in ("NEXUS_GITHUB_TOKEN=", "PASSWORD", "_DSN=", "ghp_", "github_pat_"):
            assert token not in dockerfile, f"{token!r} must never appear in the image build"
