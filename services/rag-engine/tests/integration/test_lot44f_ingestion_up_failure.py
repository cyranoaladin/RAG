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
import re
import secrets
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
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


def _required_compose_variables() -> list[str]:
    """Les variables `${VAR:?…}` que la fusion des deux Compose EXIGE.

    Elles étaient énumérées à la main. Le jour où un fichier Compose en a
    gagné une — `PGVECTOR_PUBLISHER_PASSWORD` — la liste a silencieusement
    divergé, et les trois tests de ce fichier ont commencé à échouer sur une
    erreur d'interpolation qui n'avait rien à voir avec ce qu'ils mesurent.
    Quatre autres manquaient déjà.

    Les lire dans les fichiers rend la dérive impossible : le banc suit le
    Compose, au lieu de prétendre le connaître."""
    pattern = re.compile(r"\$\{([A-Z_][A-Z0-9_]*):\?")
    required: set[str] = set()
    for compose in (COMPOSE_V2, COMPOSE_INGESTION):
        required |= set(pattern.findall(compose.read_text(encoding="utf-8")))
    return sorted(required)


def _make_dummy_env_file(
    path: Path, *, pgvector_port: int, colliding_roles: bool, host_dir: Path
) -> None:
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
    #
    # Les variables qui exigent une FORME précise sont nommées ici ; toutes
    # les autres reçoivent un mot de passe factice conforme.
    host_dir.mkdir(parents=True, exist_ok=True)
    # Chaque clé n'est écrite QU'UNE FOIS. Une première version laissait la
    # boucle attribuer un jeton aléatoire aux deux SHA d'inventaire, puis le
    # bloc final les réécrivait à zéro : le fichier portait des clés en double
    # et la bonne valeur ne survivait que par la règle « dernier gagne » de
    # Compose. Un jour où cette règle change, ou si le bloc final disparaît,
    # l'inventaire de modèles recevrait une valeur non hexadécimale sans que
    # rien ne le signale.
    shaped: dict[str, str] = {
        "INGESTION_CONTROL_MIGRATOR_ROLE": migrator_role,
        "INGESTION_CONTROL_APP_ROLE": app_role,
        "RAG_EMBEDDING_MODEL_INVENTORY_SHA256": "0" * 64,
        "RAG_RERANKER_MODEL_INVENTORY_SHA256": "0" * 64,
        "PGVECTOR_PORT": str(pgvector_port),
        "PG_INGESTION_CONTROL_DSN": (
            "postgresql://ingestion_control_app_test:dummy@pgvector:5432/ragdb"
        ),
        "PG_RAG_DSN": "postgresql://dummy:dummy@pgvector:5432/ragdb",
        "PG_REVIEW_DSN": "postgresql://dummy:dummy@pgvector:5432/ragdb",
        "NEXUS_INTERNAL_TOKEN_AUDIENCE": f"test-audience-{uuid.uuid4().hex[:8]}",
        "NEXUS_INTERNAL_TOKEN_ISSUER": f"test-issuer-{uuid.uuid4().hex[:8]}",
        "NEXUS_SSO_AUDIENCE": f"test-sso-audience-{uuid.uuid4().hex[:8]}",
        "NEXUS_SSO_ISSUER": f"test-sso-issuer-{uuid.uuid4().hex[:8]}",
    }
    for name in _required_compose_variables():
        if name in shaped:
            continue
        shaped[name] = (
            str(host_dir) if name.endswith(("_HOST_DIR", "_CACHE_DIR"))
            else secrets.token_urlsafe(24)
        )
    lines = [f"{name}={value}" for name, value in sorted(shaped.items())]
    assert len({line.split("=", 1)[0] for line in lines}) == len(lines), (
        "le fichier d'environnement porte une clé en double"
    )
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
        env_file,
        pgvector_port=int(isolated_project["port"]),
        colliding_roles=colliding_roles,
        host_dir=env_file.parent / "host",
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


@dataclass(frozen=True)
class _ServiceState:
    """État d'un service tel que Compose le rapporte.

    `state` vaut `running`/`exited` et ne dit RIEN de la santé : une assertion
    « state != healthy » est donc toujours vraie, et ne vérifie rien. La santé
    vit dans son propre champ."""

    state: str
    health: str
    exit_code: str


def _service_states(isolated_project: dict[str, str]) -> dict[str, _ServiceState]:
    """État et code de sortie de chaque service, après `up`.

    **Pourquoi le code retour de `docker compose up --wait` ne suffit pas.**
    `migrator-ingestion-control` est un conteneur ONE-SHOT : il fait son
    travail et sort. Selon la version de Compose, `--wait` traite cette sortie
    comme une condition d'échec du service attendu et rend un code non nul —
    y compris quand le migrateur a parfaitement réussi (mesuré sur le runner
    CI : « container … exited (0) » et pourtant `up` rend 1, là où le même
    montage rend 0 en local).

    Un contrôle positif qui repose sur ce code retour mesure donc la version
    de Compose, pas le déploiement. Pire : son pendant négatif ne distinguerait
    plus rien, les deux cas rendant 1.

    Le signal opposable est l'état RÉEL des services."""
    inspect = subprocess.run(
        [
            "docker", "compose", "-p", isolated_project["project"],
            "-f", str(COMPOSE_V2), "-f", str(COMPOSE_INGESTION),
            "--env-file", isolated_project["env_file"],
            "ps", "-a", "--format", "{{.Service}}|{{.State}}|{{.Health}}|{{.ExitCode}}",
        ],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    states: dict[str, _ServiceState] = {}
    for line in inspect.stdout.splitlines():
        parts = line.split("|")
        if len(parts) == 4:
            states[parts[0]] = _ServiceState(
                state=parts[1], health=parts[2], exit_code=parts[3]
            )
    return states


def _terminal_migrator_exit_code(
    isolated_project: dict[str, str], *, timeout_s: float = 120.0
) -> str:
    """Attend que le migrateur ait FINI, puis rend son code de sortie.

    `docker compose up --wait` peut rendre la main avant qu'un conteneur
    one-shot ait terminé : une lecture immédiate attrape alors `running` et
    un code de sortie `0` provisoire. Mesuré — un contrôle positif saboté
    (collision de rôles injectée) passait quand même, parce qu'il lisait
    l'état trop tôt. Un test qui dépend d'une course ne prouve rien de
    stable.

    L'attente est bornée : au-delà, l'absence d'état terminal est elle-même
    un échec nommé."""
    deadline = time.monotonic() + timeout_s
    last: _ServiceState | None = None
    while time.monotonic() < deadline:
        states = _service_states(isolated_project)
        last = states.get("migrator-ingestion-control")
        if last is not None and last.state == "exited":
            return last.exit_code
        time.sleep(1.0)
    raise AssertionError(
        f"migrator-ingestion-control n'a pas atteint d'état terminal en {timeout_s}s "
        f"(dernier état observé : {last})"
    )


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

    def test_distinct_roles_let_the_migrator_succeed(
        self, isolated_project: dict[str, str]
    ) -> None:
        """Contrôle positif : sans la collision délibérée, le migrateur réussit.

        Le nom promettait aussi « up returns zero ». Ce n'est plus ce qui est
        vérifié — et ce ne pouvait pas l'être : le code retour de
        `docker compose up --wait` dépend de la façon dont la version installée
        traite la sortie d'un conteneur one-shot. Un nom qui décrit autre chose
        que l'assertion égare quiconque cherche la cause d'un échec.

        La même commande
        (limitée à ``migrator-ingestion-control`` — ``ingestion-worker``
        exige en plus un manifest LOT44c approuvé pour devenir healthy,
        une préoccupation orthogonale à ce correctif, déjà couverte par
        les suites de câblage du gate LOT44c) doit réussir — prouve que le
        test d'échec ci-dessus teste bien la collision de rôles, pas un
        défaut environnemental plus large de ce montage de test."""
        result = _run_v2_ingestion_up(
            isolated_project, colliding_roles=False, services=("migrator-ingestion-control",)
        )

        # Symétrique de son pendant négatif : c'est le code de sortie du
        # MIGRATEUR qui distingue les deux cas, pas celui de Compose.
        exit_code = _terminal_migrator_exit_code(isolated_project)
        assert exit_code == "0", (
            "sans collision de rôles, le migrateur doit réussir ; il est sorti "
            f"en {exit_code}\nstdout={result.stdout}\nstderr={result.stderr}"
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
        # Le code retour seul ne suffit pas : sur un Compose qui rend déjà 1
        # pour la sortie du conteneur one-shot, l'assertion ci-dessus serait
        # satisfaite quel que soit l'état du worker — donc creuse. Ce qui doit
        # être vrai, c'est que le worker n'est PAS devenu healthy alors que le
        # migrateur dont il dépend a réussi.
        assert _terminal_migrator_exit_code(isolated_project) == "0", (
            "le migrateur devait réussir dans ce cas"
        )
        states = _service_states(isolated_project)
        worker = states.get("ingestion-worker")
        assert worker is not None, f"ingestion-worker absent des services : {states}"
        # `state` vaut `running`/`exited` : « state != healthy » aurait été
        # toujours vrai, donc creux. C'est le champ SANTÉ qu'il faut lire.
        assert worker.health != "healthy", (
            f"ingestion-worker ne devait jamais devenir healthy ici : {states}"
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
