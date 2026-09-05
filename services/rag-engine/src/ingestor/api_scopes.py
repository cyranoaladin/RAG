"""Portées d'API porteuses — lecture et écriture ne partagent pas de clé.

Les rôles historiques (`security_v2.SecurityRole`) décrivent *qui* appelle :
un élève, un enseignant, un agent d'ingestion. Ils ne décrivent pas *ce que
la clé a le droit de faire*. Un même acteur peut légitimement détenir une
clé de lecture et pas de clé d'écriture ; c'est ce que ce module rend
exprimable.

Quatre portées, volontairement disjointes — aucune n'en implique une autre :

``rag:search``       interroger le retrieval gouverné ;
``rag:read-source``  lire une source servable (manifeste, corpus) ;
``rag:ingest``       soumettre du contenu à la chaîne d'ingestion ;
``rag:admin``        agir sur la revue et l'exploitation.

Que ``rag:search`` n'implique pas ``rag:read-source`` est délibéré : rendre
un extrait cité n'est pas rendre le document source.

**Aucun secret ne vit dans le dépôt.** La configuration ne transporte que
l'empreinte SHA-256 du jeton, jamais le jeton : même publiée par erreur,
elle n'ouvre rien. Une entrée qui porterait une valeur en clair est refusée
plutôt qu'acceptée — sans ce refus, la facilité finirait par produire un
secret commité.

La configuration vient de l'environnement (``RAG_API_CLIENTS``) ou d'un
magasin monté (``RAG_API_CLIENTS_FILE``), jamais des deux à la fois : deux
sources concurrentes rendraient indécidable celle qui gouverne.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from fastapi import HTTPException, Request

if __package__:
    from .security_v2 import extract_token
else:  # Image Docker aplatie sous /app.
    from security_v2 import extract_token  # type: ignore[no-redef]


class ApiScope(str, Enum):
    """Les quatre portées. Toute autre valeur est une erreur de configuration."""

    SEARCH = "rag:search"
    READ_SOURCE = "rag:read-source"
    INGEST = "rag:ingest"
    ADMIN = "rag:admin"


#: Registre inline — la forme habituelle en conteneur.
API_CLIENTS_ENV = "RAG_API_CLIENTS"

#: Registre monté depuis un magasin de secrets (Docker/Kubernetes secret).
API_CLIENTS_FILE_ENV = "RAG_API_CLIENTS_FILE"

#: En-tête dédié à la clé porteuse externe. Il existe parce que
#: ``Authorization`` transporte déjà, sur l'application v2, le credential
#: machine du BFF : deux secrets différents ne peuvent pas partager un
#: en-tête sans que l'un masque l'autre. Là où aucun credential de service
#: n'occupe ``Authorization`` (chaîne d'ingestion), le repli sur le porteur
#: standard s'applique.
API_KEY_HEADER = "X-RAG-API-Key"

#: Identifiants de client : lisibles dans un journal, bornés, sans espace.
_CLIENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

#: Taille maximale du registre monté : une lecture de fichier ne doit pas
#: pouvoir consommer la mémoire du processus.
_MAX_REGISTRY_BYTES = 256 * 1024


class ApiScopeConfigurationError(ValueError):
    """Registre de clients absent ou irrecevable — refusé, jamais deviné."""


@dataclass(frozen=True)
class ApiClient:
    """Un appelant authentifié, réduit à ce qui peut être journalisé."""

    client_id: str
    token_sha256: str
    scopes: frozenset[ApiScope]

    def allows(self, scope: ApiScope) -> bool:
        return scope in self.scopes


def _read_registry_document() -> str:
    inline = (os.getenv(API_CLIENTS_ENV) or "").strip()
    path_value = (os.getenv(API_CLIENTS_FILE_ENV) or "").strip()
    if inline and path_value:
        raise ApiScopeConfigurationError(
            "both API client sources are configured; exactly one must govern"
        )
    if inline:
        return inline
    if not path_value:
        raise ApiScopeConfigurationError("no API client registry configured")
    path = Path(path_value)
    try:
        if path.stat().st_size > _MAX_REGISTRY_BYTES:
            raise ApiScopeConfigurationError("API client registry is too large")
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ApiScopeConfigurationError("API client registry is unreadable") from exc


def _parse_client(entry: object) -> ApiClient:
    if not isinstance(entry, dict):
        raise ApiScopeConfigurationError("API client entry must be an object")
    unknown = set(entry) - {"client_id", "token_sha256", "scopes"}
    if unknown:
        # `token` en fait partie : refusé nommément, pour que l'erreur dise
        # au lecteur pourquoi un jeton en clair n'a pas sa place ici.
        raise ApiScopeConfigurationError(
            "API client entry carries unsupported fields "
            f"({', '.join(sorted(unknown))}); a plaintext token is never accepted"
        )
    client_id = entry.get("client_id")
    token_sha256 = entry.get("token_sha256")
    scopes = entry.get("scopes")
    if not isinstance(client_id, str) or not _CLIENT_ID_PATTERN.fullmatch(client_id):
        raise ApiScopeConfigurationError("API client identifier is invalid")
    if not isinstance(token_sha256, str) or not _SHA256_PATTERN.fullmatch(token_sha256):
        raise ApiScopeConfigurationError(
            "API client must declare token_sha256, a lowercase SHA-256 digest"
        )
    if not isinstance(scopes, list) or not scopes:
        raise ApiScopeConfigurationError("API client must declare at least one scope")
    parsed: set[ApiScope] = set()
    for scope in scopes:
        try:
            parsed.add(ApiScope(scope))
        except ValueError as exc:
            raise ApiScopeConfigurationError(f"unknown API scope: {scope!r}") from exc
    return ApiClient(
        client_id=client_id,
        token_sha256=token_sha256,
        scopes=frozenset(parsed),
    )


def load_api_clients() -> tuple[ApiClient, ...]:
    """Relire le registre à chaque appel — jamais un cache process-local.

    Une clé révoquée doit cesser d'ouvrir dès que la configuration change ;
    un cache ferait survivre l'autorisation à sa révocation.
    """
    document = _read_registry_document()
    try:
        parsed = json.loads(document)
    except json.JSONDecodeError as exc:
        raise ApiScopeConfigurationError("API client registry is not valid JSON") from exc
    if not isinstance(parsed, list) or not parsed:
        raise ApiScopeConfigurationError("API client registry must be a non-empty list")
    clients = tuple(_parse_client(entry) for entry in parsed)
    identifiers = [client.client_id for client in clients]
    if len(set(identifiers)) != len(identifiers):
        raise ApiScopeConfigurationError("API client identifiers must be unique")
    digests = [client.token_sha256 for client in clients]
    if len(set(digests)) != len(digests):
        # Deux identités derrière une même clé rendraient tout le journal
        # d'accès ambigu : impossible de dire qui a appelé.
        raise ApiScopeConfigurationError("API client credentials must be unique")
    return clients


#: Portée exigée par chaque route métier exposée. Table unique et explicite :
#: une route absente d'ici n'a pas de porte, ce qu'un test rend visible.
_ROUTE_SCOPES: dict[str, ApiScope] = {
    "/search/v2": ApiScope.SEARCH,
    "/taxonomy/v2": ApiScope.SEARCH,
    "/collections/v2": ApiScope.SEARCH,
    "/catalogue/v2": ApiScope.SEARCH,
    "/collections/readiness": ApiScope.SEARCH,
    "/chat": ApiScope.SEARCH,
    "/corpora/servable/v1": ApiScope.READ_SOURCE,
    "/corpora/servable/v1/{manifest_sha256}": ApiScope.READ_SOURCE,
    "/review/v2/queue": ApiScope.ADMIN,
    "/review/v2/decide": ApiScope.ADMIN,
    "/ingest/v2/upload-files": ApiScope.INGEST,
    "/ingest/v2/urls": ApiScope.INGEST,
    "/ingest/v2/drive": ApiScope.INGEST,
}


def required_scope_for_route(route: str) -> ApiScope | None:
    """Portée exigée, ou ``None`` si la route n'est pas gouvernée ici."""
    return _ROUTE_SCOPES.get(route)


def resolve_api_client(token: str) -> ApiClient | None:
    """Retrouver le client par empreinte, en comparaison à temps constant."""
    if not token:
        return None
    presented = hashlib.sha256(token.encode("utf-8")).hexdigest()
    matched: ApiClient | None = None
    for client in load_api_clients():
        # Aucune sortie anticipée : la durée de la boucle ne doit pas
        # dépendre de la position du client dans le registre.
        if hmac.compare_digest(presented, client.token_sha256):
            matched = client
    return matched


def extract_api_key(request: Request) -> str:
    """Lire la clé porteuse : en-tête dédié d'abord, porteur standard ensuite."""
    headers = request.headers
    dedicated = headers.get(API_KEY_HEADER) or headers.get(API_KEY_HEADER.lower())
    if isinstance(dedicated, str) and dedicated.strip():
        return dedicated.strip()
    return extract_token(request)


def require_api_scope(
    request: Request,
    *,
    required: ApiScope,
    endpoint: str,
) -> ApiClient:
    """Exiger une portée sur une requête entrante. Fail-closed de bout en bout."""
    try:
        load_api_clients()
    except ApiScopeConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"{endpoint}: API scope configuration invalid",
        ) from exc

    token = extract_api_key(request)
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    client = resolve_api_client(token)
    if client is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not client.allows(required):
        raise HTTPException(status_code=403, detail="Forbidden")
    return client


__all__ = [
    "API_CLIENTS_ENV",
    "API_CLIENTS_FILE_ENV",
    "API_KEY_HEADER",
    "ApiClient",
    "extract_api_key",
    "ApiScope",
    "ApiScopeConfigurationError",
    "load_api_clients",
    "required_scope_for_route",
    "require_api_scope",
    "resolve_api_client",
]
