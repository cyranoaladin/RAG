"""Topologie Compose de production pour Worker A / Worker B multi-niveaux
(LOT H2-B remédiation, finding P1-workers). Versionnée seulement — ce
fichier ne démarre jamais rien, il vérifie la structure déclarée."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ENGINE_ROOT / "infra" / "docker-compose.production-workers.yml"
DOCKERFILE_PATH = ENGINE_ROOT / "infra" / "Dockerfile.multilevel-worker-production"

SERVICES = ("multilevel-worker-a-production", "multilevel-worker-b-production")


def _load_compose() -> dict:
    data = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _environment_variables(environment: object) -> dict[str, str]:
    if isinstance(environment, dict):
        return {str(key): str(value) for key, value in environment.items()}
    raise AssertionError(f"unsupported environment format: {type(environment)!r}")


def test_compose_file_and_dockerfile_exist() -> None:
    assert COMPOSE_PATH.is_file()
    assert DOCKERFILE_PATH.is_file()


def test_only_the_two_production_workers_are_declared() -> None:
    compose = _load_compose()
    assert set(compose["services"]) == set(SERVICES)


@pytest.mark.parametrize("service", SERVICES)
def test_no_service_publishes_a_port(service: str) -> None:
    """ADR-0024/ADR-0031 : ni Worker A ni Worker B ne sont, ni ne doivent
    jamais être, exposés — aucun `ports:` sur aucun des deux, en
    production comme en rehearsal."""
    compose = _load_compose()
    assert "ports" not in compose["services"][service]


@pytest.mark.parametrize("service", SERVICES)
def test_each_worker_uses_the_production_dockerfile(service: str) -> None:
    compose = _load_compose()
    build = compose["services"][service]["build"]
    assert build["dockerfile"] == "services/rag-engine/infra/Dockerfile.multilevel-worker-production"


@pytest.mark.parametrize("service", SERVICES)
def test_each_worker_is_hardened(service: str) -> None:
    compose = _load_compose()
    service_def = compose["services"][service]
    assert service_def["restart"] == "unless-stopped"
    assert service_def["read_only"] is True
    assert "no-new-privileges:true" in service_def["security_opt"]
    assert service_def["tmpfs"] == ["/tmp"]


@pytest.mark.parametrize("service", SERVICES)
def test_each_worker_declares_production_environment(service: str) -> None:
    compose = _load_compose()
    configured = _environment_variables(compose["services"][service]["environment"])
    assert configured["NEXUS_ENVIRONMENT"] == "production"
    assert configured["NEXUS_READINESS_MANIFEST_PATH"] == "/app/production/readiness-manifest.json"
    assert "${NEXUS_RELEASE_SHA:?" in configured["NEXUS_RELEASE_SHA"]


@pytest.mark.parametrize("service", SERVICES)
def test_each_worker_mounts_the_governed_trust_anchor_path_read_only(service: str) -> None:
    """The mount target is fixed by readiness_gate.GOVERNED_TRUST_ANCHOR_PATH
    — no override. The default host source is a file that does not carry a
    real anchor (PRODUCTION_TRUST_ANCHOR_PROVISIONED=false): this mission
    provisions no real anchor, and the worker must refuse to start without
    one, never fall back to rehearsal or a degraded production."""
    compose = _load_compose()
    volumes = compose["services"][service]["volumes"]
    anchor_mounts = [
        v
        for v in volumes
        if isinstance(v, str)
        and v.endswith(":/app/governance/trust-anchors/production-readiness-v1.json:ro")
    ]
    assert len(anchor_mounts) == 1


@pytest.mark.parametrize("service", SERVICES)
def test_each_worker_mounts_the_release_registry_and_revocation_registry(service: str) -> None:
    compose = _load_compose()
    volumes = compose["services"][service]["volumes"]
    assert any(v.endswith(":/app/production/release:ro") for v in volumes if isinstance(v, str))
    assert any(
        ":/app/production/revocation-registry.json:ro" in v
        for v in volumes
        if isinstance(v, str)
    )
    command = compose["services"][service]["command"]
    assert "--release-registry-path=/app/production/release/release-registry.json" in command
    assert any(entry.startswith("--release-registry-sha256=") for entry in command)
    assert "--revocation-registry-path=/app/production/revocation-registry.json" in command
    assert any(entry.startswith("--revocation-registry-sha256=") for entry in command)


@pytest.mark.parametrize("service", SERVICES)
def test_each_worker_runs_long_lived_not_once(service: str) -> None:
    """Production workers never pass ``--once`` — that flag is for the
    bounded rehearsal/test invocations, never the long-running service."""
    compose = _load_compose()
    command = compose["services"][service]["command"]
    assert "--once" not in command


@pytest.mark.parametrize("service", SERVICES)
def test_each_worker_declares_a_heartbeat_healthcheck(service: str) -> None:
    compose = _load_compose()
    service_def = compose["services"][service]
    command = service_def["command"]
    heartbeat_flags = [entry for entry in command if entry.startswith("--heartbeat-file=")]
    assert len(heartbeat_flags) == 1
    heartbeat_path = heartbeat_flags[0].split("=", 1)[1]
    assert heartbeat_path in " ".join(service_def["healthcheck"]["test"])


def test_worker_a_uses_the_ingestion_control_dsn_only() -> None:
    compose = _load_compose()
    configured = _environment_variables(
        compose["services"]["multilevel-worker-a-production"]["environment"]
    )
    assert "${PG_INGESTION_CONTROL_DSN:?" in configured["PG_INGESTION_CONTROL_DSN"]
    assert "PG_RAG_DSN" not in configured


def test_worker_b_declares_two_distinct_dsns_and_no_superuser_fallback() -> None:
    """Worker B is the only one that publishes into the product database —
    it needs both DSNs, and _enforce_production_evidence (multilevel_
    publication_resume_cli.py) already refuses at startup if they collide
    or if the product role attests as anything but the declared role."""
    compose = _load_compose()
    configured = _environment_variables(
        compose["services"]["multilevel-worker-b-production"]["environment"]
    )
    assert "${PG_INGESTION_CONTROL_DSN:?" in configured["PG_INGESTION_CONTROL_DSN"]
    assert "${PG_RAG_DSN:?" in configured["PG_RAG_DSN"]
    assert configured["PG_INGESTION_CONTROL_DSN"] != configured["PG_RAG_DSN"]

    command = compose["services"]["multilevel-worker-b-production"]["command"]
    assert any(entry.startswith("--expected-product-role=") for entry in command)
    assert configured["HF_HUB_OFFLINE"] == "1"
    assert configured["TRANSFORMERS_OFFLINE"] == "1"


def test_worker_b_mounts_the_embedding_artifact_read_only_and_never_downloads() -> None:
    compose = _load_compose()
    volumes = compose["services"]["multilevel-worker-b-production"]["volumes"]
    embedding_mounts = [
        v for v in volumes if isinstance(v, str) and v.endswith(":/app/models/e5:ro")
    ]
    assert len(embedding_mounts) == 1


def test_worker_a_never_mounts_the_embedding_artifact() -> None:
    """Only Worker B loads the embedding model — mounting it into Worker A
    would be an unused, unaudited surface."""
    compose = _load_compose()
    volumes = compose["services"]["multilevel-worker-a-production"]["volumes"]
    assert not any(
        isinstance(v, str) and "/app/models/e5" in v for v in volumes
    )


def test_no_secret_literal_in_compose_file() -> None:
    """Every credential-shaped variable is `${...:?...}` — interpolated at
    up-time from the environment, never a literal value in this file."""
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    for forbidden in ("PASSWORD=", "SECRET=", "TOKEN=\"", "_DSN=\"postgresql://"):
        assert forbidden not in text


def test_dockerfile_preserves_repository_depth_for_the_governed_root() -> None:
    """readiness_gate._GOVERNED_REPOSITORY_ROOT derives from the on-disk
    depth of readiness_gate.py (5 levels under the repo root). Flattening
    the copy to /app/ingestor/... (Dockerfile.ingestion-worker's layout)
    would make the governed root unresolvable in this image — this asserts
    the production Dockerfile keeps the real depth instead."""
    text = DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert (
        "COPY services/rag-engine/src/ingestor/ingestion_profiles/ "
        "/app/services/rag-engine/src/ingestor/ingestion_profiles/"
    ) in text
    assert "mkdir -p /app/docs/adr" in text
    assert "ENV PYTHONPATH=/app/services/rag-engine/src" in text


class TestTheComposeCommandsCarryEveryRequiredCliArgument:
    """Un argument rendu obligatoire doit atteindre les commandes réelles.

    `--repository-root` est devenu requis sans que les commandes Compose des
    deux workers Wave 0 le reçoivent : la pile d'ingestion échouait donc à
    `argparse`, AVANT tout contrôle d'autorité. Le défaut est passé au travers
    des tests parce qu'aucun ne confrontait le parseur aux commandes qui le
    lancent réellement.

    Ce test le fait : pour chaque service dont la commande invoque un
    entrypoint worker, tout argument que le parseur déclare `required` doit
    être présent. Il n'a pas d'opinion sur la VALEUR — seulement sur le fait
    que la commande de production ne peut pas être structurellement invalide.
    """

    _ENTRYPOINTS = {
        "ingestor.ingestion_worker.cli": "ingestor.ingestion_worker.cli",
        "ingestor.ingestion_worker.publication_resume_cli": (
            "ingestor.ingestion_worker.publication_resume_cli"
        ),
    }

    def _required_options(self, module_name: str) -> set[str]:
        import importlib

        module = importlib.import_module(module_name)
        parser = module._build_arg_parser()
        return {
            option
            for action in parser._actions
            if getattr(action, "required", False)
            for option in action.option_strings
        }

    def test_every_required_option_appears_in_the_compose_command(self) -> None:
        import yaml

        compose = yaml.safe_load(
            (ENGINE_ROOT / "infra/docker-compose.ingestion.yml").read_text(
                encoding="utf-8"
            )
        )
        checked = 0
        for name, service in (compose.get("services") or {}).items():
            command = service.get("command") or []
            entrypoint = next(
                (module for module in self._ENTRYPOINTS if module in command), None
            )
            if entrypoint is None:
                continue
            supplied = {
                str(item).split("=", 1)[0]
                for item in command
                if str(item).startswith("--")
            }
            missing = sorted(self._required_options(entrypoint) - supplied)
            assert not missing, (
                f"le service Compose {name!r} lance {entrypoint} sans "
                f"{missing} : la pile échouerait à argparse, avant tout "
                "contrôle d'autorité"
            )
            checked += 1
        assert checked >= 2, (
            f"seuls {checked} services worker ont été confrontés au parseur"
        )
