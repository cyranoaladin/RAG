"""LOT44f (remédiation revue PR#90, passe 2, item H) : ``make
v2-ingestion-up`` ne doit jamais annoncer un succès prématuré — PostgreSQL
et Docker réels.

Périmètre strict : la commande réellement exécutée par la cible Make
(``docker compose ... up -d --build --wait migrator-ingestion-control
ingestion-worker``) — jamais ``make`` lui-même en sous-processus (le
fichier ``infra/.env`` réel du dépôt n'est jamais lu ni modifié par ce
test ; un fichier d'environnement isolé, jetable, est construit ici avec
des valeurs factices syntaxiquement valides pour chaque variable exigée
par les DEUX fichiers Compose fusionnés — y compris celles de services
sans rapport comme ``ingestor``, que Compose interpole systématiquement
avant toute résolution de dépendances, même quand ces services ne sont pas
demandés).

Échec de migration délibéré : ``INGESTION_CONTROL_APP_ROLE`` réglé à la
même valeur que ``INGESTION_CONTROL_MIGRATOR_ROLE`` — rejeté explicitement
par ``provision_ingestion_control_roles.sh`` (revue PR#90, item C) avant
toute écriture, faisant échouer ``migrator-ingestion-control`` (exit != 0)
de façon déterministe, sans dépendre d'une corruption de fichier SQL.
"""
from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ENGINE_ROOT.parents[1]
INFRA_ROOT = ENGINE_ROOT / "infra"
COMPOSE_V2 = INFRA_ROOT / "docker-compose.v2.yml"
COMPOSE_INGESTION = INFRA_ROOT / "docker-compose.ingestion.yml"

_DOCKER_AVAILABLE = shutil.which("docker") is not None and (
    subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DOCKER_AVAILABLE, reason="Docker not available"),
]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _make_dummy_env_file(path: Path, *, pgvector_port: int, colliding_roles: bool) -> None:
    """Valeurs factices, syntaxiquement valides, pour CHAQUE variable
    ``:?`` exigée par la fusion des deux fichiers Compose — y compris les
    variables du service ``ingestor`` (sans rapport avec ce test), que
    Compose interpole pour l'intégralité du fichier avant toute résolution
    de service demandé (vérifié empiriquement : ``up --dry-run
    migrator-ingestion-control ingestion-worker`` échoue quand même sur des
    variables ``ingestor`` manquantes)."""
    migrator_role = "ingestion_control_migrator_test"
    app_role = migrator_role if colliding_roles else "ingestion_control_app_test"
    # provision_runtime_roles.sh exige >= 32 caractères pour tout mot de
    # passe runtime (vérifié empiriquement : "mot de passe runtime trop
    # court (32 caracteres minimum)") — token_urlsafe(24) produit 32
    # caractères, même convention que le reste de la suite d'intégration.
    lines = [
        f"PGVECTOR_PASSWORD={secrets.token_urlsafe(24)}",
        f"PGVECTOR_RETRIEVAL_PASSWORD={secrets.token_urlsafe(24)}",
        f"PGVECTOR_REVIEW_PASSWORD={secrets.token_urlsafe(24)}",
        f"INGESTION_CONTROL_MIGRATOR_PASSWORD={secrets.token_urlsafe(24)}",
        f"INGESTION_CONTROL_APP_PASSWORD={secrets.token_urlsafe(24)}",
        f"INGESTION_CONTROL_AUTHORITY_PASSWORD={secrets.token_urlsafe(24)}",
        f"INGESTION_CONTROL_ATTESTOR_PASSWORD={secrets.token_urlsafe(24)}",
        f"INGESTION_CONTROL_MIGRATOR_ROLE={migrator_role}",
        f"INGESTION_CONTROL_APP_ROLE={app_role}",
        "PG_INGESTION_CONTROL_DSN=postgresql://ingestion_control_app_test:dummy@pgvector:5432/ragdb",
        "PG_RAG_DSN=postgresql://dummy:dummy@pgvector:5432/ragdb",
        "PG_REVIEW_DSN=postgresql://dummy:dummy@pgvector:5432/ragdb",
        f"NEXUS_INTERNAL_TOKEN_AUDIENCE=test-audience-{uuid.uuid4().hex[:8]}",
        f"NEXUS_INTERNAL_TOKEN_ISSUER=test-issuer-{uuid.uuid4().hex[:8]}",
        f"NEXUS_INTERNAL_TOKEN_SECRET={secrets.token_urlsafe(24)}",
        f"NEXUS_SSO_AUDIENCE=test-sso-audience-{uuid.uuid4().hex[:8]}",
        f"NEXUS_SSO_ISSUER=test-sso-issuer-{uuid.uuid4().hex[:8]}",
        f"RAG_BFF_SERVICE_TOKEN={secrets.token_urlsafe(24)}",
        "RAG_EMBEDDING_MODEL_INVENTORY_SHA256=" + "0" * 64,
        "RAG_RERANKER_MODEL_INVENTORY_SHA256=" + "0" * 64,
        f"PGVECTOR_PORT={pgvector_port}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def isolated_project(tmp_path: Path) -> Iterator[dict[str, str]]:
    project_name = f"nexus-lot44f-ingup-{uuid.uuid4().hex[:10]}"
    env_file = tmp_path / "test.env"
    port = _free_port()
    yield {"project": project_name, "env_file": str(env_file), "port": str(port)}
    subprocess.run(
        [
            "docker", "compose", "-p", project_name,
            "-f", str(COMPOSE_V2), "-f", str(COMPOSE_INGESTION),
            "--env-file", str(env_file),
            "down", "-v", "--remove-orphans",
        ],
        cwd=REPO_ROOT, capture_output=True, check=False,
    )


def _run_v2_ingestion_up(
    isolated_project: dict[str, str], *, colliding_roles: bool, services: tuple[str, ...]
) -> subprocess.CompletedProcess[str]:
    env_file = Path(isolated_project["env_file"])
    _make_dummy_env_file(
        env_file, pgvector_port=int(isolated_project["port"]), colliding_roles=colliding_roles
    )
    env = os.environ.copy()
    # Réplique exactement COMPOSE_V2_INGESTION + la cible v2-ingestion-up
    # du Makefile (infra/../Makefile:148,162-166), jamais infra/.env réel.
    cmd = [
        "docker", "compose", "-p", isolated_project["project"],
        "-f", str(COMPOSE_V2), "-f", str(COMPOSE_INGESTION),
        "--env-file", str(env_file),
        "up", "-d", "--build", "--wait",
        *services,
    ]
    return subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False)


class TestV2IngestionUpFailsClosed:
    def test_colliding_roles_make_migrator_fail_and_up_returns_nonzero(
        self, isolated_project: dict[str, str]
    ) -> None:
        """Revue incrémentale PR#90 (Cubic P1, item H) : preuve directe que
        la commande réellement exécutée par ``make v2-ingestion-up``
        (désormais avec ``--wait``, cf. Makefile) retourne un code non-nul
        quand ``migrator-ingestion-control`` échoue — jamais un succès
        rapporté à tort comme avant ce correctif (``up -d`` seul, sans
        ``--wait``, retournait 0 dès que les conteneurs étaient *créés*,
        indépendamment de leur issue réelle)."""
        result = _run_v2_ingestion_up(
            isolated_project, colliding_roles=True,
            services=("migrator-ingestion-control", "ingestion-worker"),
        )

        assert result.returncode != 0, (
            f"expected non-zero exit when migrator-ingestion-control fails, got 0\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        # Le message d'échec du wait doit référencer le service en échec.
        assert "migrator-ingestion-control" in (result.stdout + result.stderr)

        inspect = subprocess.run(
            [
                "docker", "compose", "-p", isolated_project["project"],
                "-f", str(COMPOSE_V2), "-f", str(COMPOSE_INGESTION),
                "--env-file", isolated_project["env_file"],
                "ps", "-a", "--format", "{{.Service}} {{.ExitCode}}",
            ],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False,
        )
        assert "migrator-ingestion-control" in inspect.stdout
        for line in inspect.stdout.splitlines():
            if line.startswith("migrator-ingestion-control"):
                assert not line.endswith(" 0"), f"migrator-ingestion-control unexpectedly exited 0: {line}"

    def test_distinct_roles_let_migrator_succeed_and_up_returns_zero(
        self, isolated_project: dict[str, str]
    ) -> None:
        """Contrôle positif : sans la collision délibérée, la même commande
        (limitée à ``migrator-ingestion-control`` — ``ingestion-worker``
        exige en plus un manifest LOT44c approuvé pour devenir healthy,
        une préoccupation orthogonale à ce correctif, déjà couverte par
        les suites de câblage du gate LOT44c) doit réussir — prouve que le
        test d'échec ci-dessus teste bien la collision de rôles, pas un
        défaut environnemental plus large de ce montage de test."""
        result = _run_v2_ingestion_up(
            isolated_project, colliding_roles=False, services=("migrator-ingestion-control",)
        )

        assert result.returncode == 0, (
            f"expected zero exit on a well-formed deployment, got {result.returncode}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_worker_never_healthy_is_caught_even_when_migrator_succeeds(
        self, isolated_project: dict[str, str]
    ) -> None:
        """Isole précisément le point aveugle que ``--wait`` corrige, par
        opposition au strict échec de ``migrator-ingestion-control``.

        Constaté empiriquement (expérimentation délibérée, retrait
        temporaire de ``--wait`` de la commande) : même AVANT ce correctif,
        ``docker compose up -d`` (Compose v5.4.0) retournait déjà un code
        non-nul quand ``migrator-ingestion-control`` échouait lui-même
        (``depends_on: condition: service_completed_successfully`` est
        appliqué par l'orchestration `up`, avec ou sans ``--wait``). En
        revanche, sans ``--wait``, ``up -d`` retournait 0 dès que
        ``ingestion-worker`` était *démarré* — sans jamais attendre ni
        vérifier son ``healthcheck`` (ici : gate LOT44c refusé, faute de
        manifest approuvé dans cet environnement de test jetable ; le
        worker reste donc durablement ``unhealthy``, jamais un
        planté immédiat que ``depends_on`` aurait pu détecter seul). C'est
        précisément ce point aveugle que ``--wait`` corrige : ce test
        prouve que la commande réelle de la cible Make détecte bien un
        worker jamais devenu healthy, même quand le migrator dont il
        dépend a lui-même parfaitement réussi."""
        result = _run_v2_ingestion_up(
            isolated_project, colliding_roles=False,
            services=("migrator-ingestion-control", "ingestion-worker"),
        )

        assert result.returncode != 0, (
            f"expected non-zero exit when ingestion-worker never becomes healthy, got 0\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "ingestion-worker" in (result.stdout + result.stderr)

        inspect = subprocess.run(
            [
                "docker", "compose", "-p", isolated_project["project"],
                "-f", str(COMPOSE_V2), "-f", str(COMPOSE_INGESTION),
                "--env-file", isolated_project["env_file"],
                "ps", "-a", "--format", "{{.Service}} {{.ExitCode}}",
            ],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False,
        )
        for line in inspect.stdout.splitlines():
            if line.startswith("migrator-ingestion-control"):
                assert line.endswith(" 0"), (
                    f"migrator-ingestion-control should have succeeded in this scenario: {line}"
                )
