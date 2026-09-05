"""Journal d'accès au retrieval — une ligne structurée par requête.

Ce que l'exploitation doit pouvoir reconstituer sans ouvrir la base :
qui a demandé quoi, sous quelle autorisation, combien de candidats ont été
examinés, combien ont été rendus, en combien de temps, et quel canal a
défailli le cas échéant.

**Ce qui n'est jamais journalisé.** La requête brute d'un élève est du
contenu utilisateur : elle peut nommer une personne, une difficulté
scolaire, une situation familiale. Elle ne quitte donc jamais le processus.
Ce module n'expose d'elle que son empreinte SHA-256 et sa longueur — de
quoi corréler deux requêtes identiques et détecter une anomalie de taille,
jamais de quoi les relire. Même règle pour le jeton porteur : seul son
`client_id` déclaré et son empreinte courte circulent.

Le jeu de filtres appliqués est, lui, journalisé en clair : `collection`,
`notions`, empreinte de scope. Ce sont des dimensions de catalogue
pédagogique publiques, pas des données personnelles, et sans elles un « 0
résultat » serait indiagnosticable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

#: Nom du logger dédié — séparé des logs applicatifs pour qu'un exploitant
#: puisse router ce flux vers sa collecte sans embarquer le reste.
ACCESS_LOGGER_NAME = "nexus.retrieval.access"

#: En-tête de corrélation déjà utilisé par le plan d'ingestion
#: (`audit_logger`, `admin_api`) : une seule convention pour tout le
#: service.
REQUEST_ID_HEADER = "X-Request-ID"

#: Un identifiant de corrélation vient du client : il est donc borné et
#: restreint à un alphabet sûr avant d'entrer dans un log. Une valeur
#: refusée n'échoue pas la requête — elle est remplacée par un identifiant
#: généré, car perdre la corrélation vaut mieux que perdre la requête.
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def resolve_request_id(headers: Mapping[str, str] | None) -> str:
    """Reprendre l'identifiant du client s'il est sain, sinon en générer un."""
    if headers is not None:
        candidate = headers.get(REQUEST_ID_HEADER) or headers.get(
            REQUEST_ID_HEADER.lower()
        )
        if isinstance(candidate, str) and _REQUEST_ID_PATTERN.fullmatch(candidate.strip()):
            return candidate.strip()
    return uuid.uuid4().hex


def query_fingerprint(query: str) -> str:
    """Empreinte irréversible de la requête — jamais la requête elle-même."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RetrievalAccessRecord:
    """Une ligne de journal. Immuable : ce qui est constaté ne se réécrit pas."""

    request_id: str
    endpoint: str
    client_id: str
    granted_scopes: tuple[str, ...]
    status_code: int
    latency_ms: float
    filters: Mapping[str, Any] = field(default_factory=dict)
    channels: Mapping[str, Any] = field(default_factory=dict)
    query_sha256: str | None = None
    query_length: int | None = None

    def as_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event": "retrieval_access",
            "request_id": self.request_id,
            "endpoint": self.endpoint,
            "client_id": self.client_id,
            "granted_scopes": list(self.granted_scopes),
            "status_code": self.status_code,
            "latency_ms": round(self.latency_ms, 3),
            "filters": dict(self.filters),
        }
        payload.update(dict(self.channels))
        if self.query_sha256 is not None:
            payload["query_sha256"] = self.query_sha256
        if self.query_length is not None:
            payload["query_length"] = self.query_length
        return payload

    def as_json(self) -> str:
        return json.dumps(self.as_mapping(), ensure_ascii=False, sort_keys=True)


def log_retrieval_access(
    record: RetrievalAccessRecord,
    *,
    logger: logging.Logger | None = None,
) -> None:
    """Émettre la ligne, sans jamais faire échouer la requête servie.

    Un journal qui casse la réponse transforme un incident d'observabilité
    en incident de service : la défaillance est absorbée ici.
    """
    target = logger if logger is not None else logging.getLogger(ACCESS_LOGGER_NAME)
    try:
        target.info(record.as_json())
    except Exception:  # pragma: no cover - défense en profondeur
        pass


__all__ = [
    "ACCESS_LOGGER_NAME",
    "REQUEST_ID_HEADER",
    "RetrievalAccessRecord",
    "log_retrieval_access",
    "query_fingerprint",
    "resolve_request_id",
]
