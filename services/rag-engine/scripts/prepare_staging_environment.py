#!/usr/bin/env python3
"""Préparer le matériel de secret d'un staging, sans rien déployer.

Ce que ce producteur fait, et pourquoi il existe séparément du déploiement :

Un staging externe a besoin de secrets qui n'existent nulle part encore — un
credential machine pour la façade, une clé porteuse par client, un secret
d'empreinte pour le journal d'accès, des mots de passe PostgreSQL. Les
fabriquer à la main, c'est produire des valeurs faibles, en oublier, ou pire :
en coller une dans le dépôt. Ce script les fabrique, écrit le registre de
clients que le runtime attend, et rend un fichier d'environnement complet.

**Ce qu'il refuse de faire.**

- *Écrire quoi que ce soit dans le dépôt.* La destination est vérifiée : un
  chemin sous la racine du dépôt est refusé, pas ignoré. Un secret committé ne
  se rattrape pas par une rotation, il se rattrape par une réécriture
  d'historique.
- *Inventer ce qui n'est pas un secret.* Les empreintes d'inventaire de
  modèles, celle du registre de releases, celle de l'index de corpus servables
  et les répertoires hôtes sont des **faits** du déploiement : le script les
  exige de l'opérateur et échoue s'ils manquent. Générer une valeur plausible
  pour une empreinte reviendrait à fabriquer une preuve.
- *Déclarer deux autorités de registre.* Le Compose canonique fixe déjà
  ``RAG_API_CLIENTS_FILE`` ; le fichier rendu laisse donc ``RAG_API_CLIENTS``
  vide. Deux sources feraient échouer le démarrage, ce qui est le comportement
  voulu du runtime mais un défaut de ce producteur.

**Ce qu'il rend.**

    <destination>/api-clients.json    registre : uniquement des empreintes
    <destination>/staging.env         environnement du Compose (mode 0600)
    <destination>/credentials.env     jetons EN CLAIR à distribuer (0600)

Les jetons en clair ne sont écrits que dans `credentials.env`, et jamais
imprimés : un secret qui passe par la sortie standard finit dans un journal de
terminal, un historique de shell ou une capture de CI.

La liste des variables à rendre est **lue du Compose**, jamais recopiée : le
jour où le Compose en exige une de plus, ce script échoue au lieu de produire
un environnement incomplet.

Usage :

    python scripts/prepare_staging_environment.py \\
        --destination ~/nexus-staging-secrets \\
        --pgvector-host pgvector --pgvector-database ragdb \\
        --embedding-artifact-dir /srv/nexus/models/e5-large \\
        --embedding-inventory-sha256 <64 hex> \\
        --reranker-artifact-dir /srv/nexus/models/reranker \\
        --reranker-inventory-sha256 <64 hex> \\
        --release-registry-sha256 <64 hex> \\
        --servable-corpus-dir /srv/nexus/servable-corpus \\
        --servable-corpus-index-sha256 <64 hex> \\
        --sso-issuer https://sso.staging.example/ \\
        --sso-audience nexus-cockpit-staging
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ENGINE_ROOT.parents[1]
COMPOSE_V2 = ENGINE_ROOT / "infra" / "docker-compose.v2.yml"

#: Chemin du registre DANS le conteneur — fixé par le Compose canonique, donc
#: relu de lui plutôt que recopié.
_REGISTRY_ENV = "RAG_API_CLIENTS_FILE"

#: Longueur des secrets générés. 32 octets d'entropie : au-delà, on n'achète
#: rien ; en deçà, `provision_runtime_roles.sh` refuse les mots de passe.
_SECRET_BYTES = 32

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REQUIRED_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*):\?")


class StagingPreparationError(RuntimeError):
    """La préparation ne peut pas produire un environnement honnête."""


@dataclass(frozen=True)
class StagingClient:
    """Un appelant du staging, sa portée, et la clé qu'on vient de lui faire."""

    client_id: str
    scopes: tuple[str, ...]
    token: str

    @property
    def token_sha256(self) -> str:
        return hashlib.sha256(self.token.encode("utf-8")).hexdigest()

    def registry_entry(self) -> dict[str, object]:
        return {
            "client_id": self.client_id,
            "token_sha256": self.token_sha256,
            "scopes": list(self.scopes),
        }


#: Les trois appelants qu'un staging doit servir, et rien de plus. Chacun a la
#: portée minimale de son rôle : le Cockpit et l'agent externe cherchent, ils
#: n'administrent pas ; la console d'exploitation administre, elle ne se
#: substitue pas au Cockpit dans le journal d'accès.
STAGING_CLIENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cockpit-staging", ("rag:search",)),
    ("agent-externe-staging", ("rag:search",)),
    ("ops-staging", ("rag:admin",)),
)


def required_compose_variables() -> tuple[str, ...]:
    """Les `${VAR:?…}` que le Compose v2 exige, lues du fichier."""
    text = COMPOSE_V2.read_text(encoding="utf-8")
    return tuple(sorted(set(_REQUIRED_PATTERN.findall(text))))


def container_registry_path() -> str:
    """Le chemin du registre dans le conteneur, relu du Compose."""
    for line in COMPOSE_V2.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{_REGISTRY_ENV}:"):
            value = stripped.split(":", 1)[1].strip()
            if value:
                return value
    raise StagingPreparationError(
        f"{_REGISTRY_ENV} est absent du Compose canonique"
    )


def _generated_secret() -> str:
    return secrets.token_urlsafe(_SECRET_BYTES)


def _require_sha256(value: str, label: str) -> str:
    if _SHA256.fullmatch(value) is None:
        raise StagingPreparationError(
            f"{label} doit être un SHA-256 minuscule de 64 caractères — "
            "cette empreinte est un fait du déploiement, jamais une valeur "
            "à inventer"
        )
    return value


def _require_absolute(value: str, label: str) -> str:
    path = Path(value)
    if not path.is_absolute():
        raise StagingPreparationError(f"{label} doit être un chemin absolu")
    return str(path)


def _refuse_repository_destination(destination: Path) -> Path:
    """Refuser toute destination sous le dépôt — un secret n'y entre pas."""
    resolved = destination.expanduser().resolve()
    root = REPOSITORY_ROOT.resolve()
    if resolved == root or root in resolved.parents:
        raise StagingPreparationError(
            f"destination interdite : {resolved} est sous le dépôt {root}. "
            "Un secret écrit dans un arbre de travail finit committé ; le "
            "rattraper exige une réécriture d'historique, pas une rotation."
        )
    return resolved


def build_clients() -> tuple[StagingClient, ...]:
    """Fabriquer une clé par appelant, toutes distinctes."""
    clients = tuple(
        StagingClient(client_id=client_id, scopes=scopes, token=_generated_secret())
        for client_id, scopes in STAGING_CLIENTS
    )
    digests = {client.token_sha256 for client in clients}
    if len(digests) != len(clients):
        raise StagingPreparationError("deux clients partagent une clé")
    return clients


def render_registry(clients: tuple[StagingClient, ...]) -> str:
    """Le registre que le runtime lira — empreintes seules, jamais un jeton."""
    document = [client.registry_entry() for client in clients]
    rendered = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    for client in clients:
        if client.token in rendered:
            raise StagingPreparationError(
                "un jeton en clair est entré dans le registre"
            )
    return rendered


def build_environment(
    arguments: argparse.Namespace,
    clients: tuple[StagingClient, ...],
    *,
    registry_host_file: Path,
) -> dict[str, str]:
    """Rendre chaque variable exigée par le Compose — aucune devinée."""
    bff_service_token = _generated_secret()
    pg_password = _generated_secret()
    values: dict[str, str] = {
        # Secrets fabriqués ici.
        "RAG_BFF_SERVICE_TOKEN": bff_service_token,
        "RAG_ACCESS_LOG_HMAC_SECRET": _generated_secret(),
        "NEXUS_INTERNAL_TOKEN_SECRET": _generated_secret(),
        "PGVECTOR_PASSWORD": pg_password,
        "PGVECTOR_RETRIEVAL_PASSWORD": _generated_secret(),
        "PGVECTOR_REVIEW_PASSWORD": _generated_secret(),
        "PGVECTOR_PUBLISHER_PASSWORD": _generated_secret(),
        # Faits du déploiement, exigés de l'opérateur.
        "RAG_API_CLIENTS_HOST_FILE": str(registry_host_file),
        "RAG_EMBEDDING_MODEL_ARTIFACT_HOST_DIR": _require_absolute(
            arguments.embedding_artifact_dir, "--embedding-artifact-dir"
        ),
        "RAG_EMBEDDING_MODEL_INVENTORY_SHA256": _require_sha256(
            arguments.embedding_inventory_sha256, "--embedding-inventory-sha256"
        ),
        "RAG_RERANKER_MODEL_ARTIFACT_HOST_DIR": _require_absolute(
            arguments.reranker_artifact_dir, "--reranker-artifact-dir"
        ),
        "RAG_RERANKER_MODEL_INVENTORY_SHA256": _require_sha256(
            arguments.reranker_inventory_sha256, "--reranker-inventory-sha256"
        ),
        "RAG_RELEASE_REGISTRY_SHA256": _require_sha256(
            arguments.release_registry_sha256, "--release-registry-sha256"
        ),
        "RAG_SERVABLE_CORPUS_HOST_DIR": _require_absolute(
            arguments.servable_corpus_dir, "--servable-corpus-dir"
        ),
        "RAG_SERVABLE_CORPUS_INDEX_SHA256": _require_sha256(
            arguments.servable_corpus_index_sha256, "--servable-corpus-index-sha256"
        ),
        "NEXUS_SSO_ISSUER": arguments.sso_issuer,
        "NEXUS_SSO_AUDIENCE": arguments.sso_audience,
        "NEXUS_INTERNAL_TOKEN_ISSUER": arguments.internal_token_issuer,
        "NEXUS_INTERNAL_TOKEN_AUDIENCE": arguments.internal_token_audience,
    }
    # Les DSN sont DÉRIVÉS des mots de passe fabriqués juste au-dessus. Les
    # ressaisir ouvrirait la possibilité qu'un rôle porte, dans son DSN, un
    # mot de passe qui n'est pas le sien.
    for name, role, password_name in (
        ("PG_RAG_DSN", arguments.retrieval_role, "PGVECTOR_RETRIEVAL_PASSWORD"),
        ("PG_REVIEW_DSN", arguments.review_role, "PGVECTOR_REVIEW_PASSWORD"),
    ):
        values[name] = (
            f"postgresql://{role}:{values[password_name]}"
            f"@{arguments.pgvector_host}:5432/{arguments.pgvector_database}"
        )

    missing = set(required_compose_variables()) - set(values)
    if missing:
        raise StagingPreparationError(
            "le Compose exige des variables que ce producteur ne rend pas : "
            f"{sorted(missing)} — l'ajouter ici plutôt que livrer un "
            "environnement incomplet"
        )
    unknown = set(values) - set(required_compose_variables())
    if unknown:
        raise StagingPreparationError(
            f"variables rendues sans être exigées : {sorted(unknown)}"
        )
    # Le Compose fixe lui-même RAG_API_CLIENTS_FILE : laisser RAG_API_CLIENTS
    # vide, faute de quoi deux sources gouverneraient et le service refuserait
    # de démarrer.
    values["RAG_API_CLIENTS"] = ""
    return values


def render_env(values: dict[str, str]) -> str:
    return "\n".join(f"{name}={values[name]}" for name in sorted(values)) + "\n"


def render_credentials(
    clients: tuple[StagingClient, ...], environment: dict[str, str]
) -> str:
    """Les jetons EN CLAIR, à distribuer hors bande — jamais imprimés."""
    lines = [
        "# Jetons en clair du staging. À distribuer par un canal sûr, jamais",
        "# committés, jamais copiés dans un ticket.",
        "#",
        "# Le Cockpit staging attend exactement ces deux valeurs :",
        "#   RAG_ENGINE_INTERNAL_TOKEN = RAG_BFF_SERVICE_TOKEN",
        "#   RAG_ENGINE_API_KEY        = COCKPIT_STAGING_API_KEY",
        "#",
        "# L'agent externe attend :",
        "#   RAG_BFF_SERVICE_TOKEN, RAG_API_KEY, RAG_IDENTITY_TOKEN",
        f"RAG_BFF_SERVICE_TOKEN={environment['RAG_BFF_SERVICE_TOKEN']}",
    ]
    for client in clients:
        name = client.client_id.replace("-", "_").upper()
        lines.append(f"{name}_API_KEY={client.token}")
    return "\n".join(lines) + "\n"


def _write_private(path: Path, content: str) -> None:
    """Écrire en 0600 avant d'y mettre quoi que ce soit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = path.open("w", encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        descriptor.write(content)
    finally:
        descriptor.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--pgvector-host", default="pgvector")
    parser.add_argument("--pgvector-database", default="ragdb")
    parser.add_argument("--retrieval-role", default="rag_retrieval")
    parser.add_argument("--review-role", default="rag_review")
    parser.add_argument("--embedding-artifact-dir", required=True)
    parser.add_argument("--embedding-inventory-sha256", required=True)
    parser.add_argument("--reranker-artifact-dir", required=True)
    parser.add_argument("--reranker-inventory-sha256", required=True)
    parser.add_argument("--release-registry-sha256", required=True)
    parser.add_argument("--servable-corpus-dir", required=True)
    parser.add_argument("--servable-corpus-index-sha256", required=True)
    parser.add_argument("--sso-issuer", required=True)
    parser.add_argument("--sso-audience", required=True)
    parser.add_argument("--internal-token-issuer", default="nexus-cockpit-staging")
    parser.add_argument("--internal-token-audience", default="nexus-rag-engine-staging")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        destination = _refuse_repository_destination(arguments.destination)
        clients = build_clients()
        registry_path = destination / "api-clients.json"
        environment = build_environment(
            arguments, clients, registry_host_file=registry_path
        )
        registry = render_registry(clients)
        _write_private(registry_path, registry)
        _write_private(destination / "staging.env", render_env(environment))
        _write_private(
            destination / "credentials.env",
            render_credentials(clients, environment),
        )
    except StagingPreparationError as exc:
        print(f"staging preparation error: {exc}", file=sys.stderr)
        return 2

    # Ce qui est imprimé ne contient AUCUN secret : des chemins, des
    # identifiants de client et le chemin de montage attendu.
    print(f"STAGING_SECRETS_DIRECTORY={destination}")
    print(f"STAGING_API_CLIENT_REGISTRY={registry_path}")
    print(f"STAGING_REGISTRY_CONTAINER_PATH={container_registry_path()}")
    print(f"STAGING_API_CLIENTS={','.join(client.client_id for client in clients)}")
    print(f"STAGING_ENV_FILE={destination / 'staging.env'}")
    print(f"STAGING_CREDENTIALS_FILE={destination / 'credentials.env'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
