"""Journal d'accès au retrieval — une ligne structurée par requête, servie ou non.

Ce que l'exploitation doit pouvoir reconstituer sans ouvrir la base : qui a
demandé quoi, sous quelle autorisation, combien de candidats ont été examinés,
combien ont été rendus, en combien de temps, et quelle étape a défailli le cas
échéant. **Y compris quand la requête échoue** : un journal qui ne consigne que
les succès ne dit rien des incidents, c'est-à-dire de la seule chose qu'on lui
demande en incident.

**Ce qui n'est jamais journalisé en clair.**

La requête d'un élève est du contenu utilisateur : elle peut nommer une
personne, une difficulté scolaire, une situation familiale. Elle ne quitte
jamais le processus. Son empreinte non plus n'est pas un SHA-256 nu : un
condensé sans clé se retourne par dictionnaire, et « corréler » deviendrait
« retrouver ». L'empreinte est un HMAC-SHA256 sous un secret propre au
déploiement (``RAG_ACCESS_LOG_HMAC_SECRET``) : deux requêtes identiques se
corrèlent, une devinette ne se vérifie pas. Sans secret configuré, il n'y a
pas d'empreinte du tout — jamais de repli sur un condensé nu.

Les `notions` sont, elles aussi, du texte libre fourni par l'appelant :
aucune taxonomie fermée ne les contraint. Elles sont donc comptées et
empreintes sous la même clé, jamais recopiées. Les dimensions de catalogue
fermées — `collection`, empreinte de scope, identifiants de corpus — restent
en clair : elles sont publiques, et sans elles un « 0 résultat » serait
indiagnosticable.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import unicodedata
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

#: Nom du logger dédié — séparé des logs applicatifs pour qu'un exploitant
#: puisse router ce flux vers sa collecte sans embarquer le reste.
ACCESS_LOGGER_NAME = "nexus.retrieval.access"

#: En-tête de corrélation déjà utilisé par le plan d'ingestion
#: (`audit_logger`, `admin_api`) : une seule convention pour tout le service.
REQUEST_ID_HEADER = "X-Request-ID"

#: Secret dédié à l'empreinte du journal. Dédié : il ne partage rien avec les
#: credentials d'appel, pour qu'une rotation de l'un n'oblige pas l'autre et
#: qu'une fuite de l'un ne livre pas l'autre.
ACCESS_LOG_HMAC_SECRET_ENV = "RAG_ACCESS_LOG_HMAC_SECRET"

#: Un identifiant de corrélation vient du client : il est donc borné et
#: restreint à un alphabet sûr avant d'entrer dans un log. Une valeur refusée
#: n'échoue pas la requête — elle est remplacée par un identifiant généré, car
#: perdre la corrélation vaut mieux que perdre la requête.
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

#: Dimensions de catalogue publiques, journalisables en clair. Toute autre clé
#: de filtre est du texte d'appelant tant que rien ne prouve le contraire :
#: elle est empreinte, jamais recopiée.
CLOSED_FILTER_DIMENSIONS = frozenset(
    {
        "collection",
        "scope_digest",
        "manifest_sha256",
        "corpus_id",
        "corpus_version_id",
    }
)

_FINGERPRINT_PREFIX_LENGTH = 16


def resolve_request_id(headers: Mapping[str, str] | None) -> str:
    """Reprendre l'identifiant du client s'il est sain, sinon en générer un."""
    if headers is not None:
        candidate = headers.get(REQUEST_ID_HEADER) or headers.get(
            REQUEST_ID_HEADER.lower()
        )
        if isinstance(candidate, str) and _REQUEST_ID_PATTERN.fullmatch(candidate.strip()):
            return candidate.strip()
    return uuid.uuid4().hex


def load_access_log_secret() -> bytes | None:
    """Le secret d'empreinte, ou ``None`` s'il n'est pas configuré.

    Absence de secret ⇒ absence d'empreinte. Le journal perd une corrélation ;
    il ne gagne pas un condensé attaquable.
    """
    raw = (os.getenv(ACCESS_LOG_HMAC_SECRET_ENV) or "").strip()
    return raw.encode("utf-8") if raw else None


def _normalize(text: str) -> str:
    """Forme comparable : NFKC, casefold, espaces réduits."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(folded.split())


def query_fingerprint(query: str, *, secret: bytes | None) -> str | None:
    """Empreinte clefée et irréversible de la requête, ou rien.

    Le secret est un paramètre obligatoire — pas une valeur par défaut lue en
    douce : un appelant qui n'a pas de secret doit le dire, et obtenir
    ``None``, plutôt que de retomber sur une empreinte nue sans le savoir.
    """
    if secret is None:
        return None
    return hmac.new(secret, _normalize(query).encode("utf-8"), hashlib.sha256).hexdigest()


def _fingerprint_values(
    values: Iterable[str], *, secret: bytes | None
) -> list[str] | None:
    if secret is None:
        return None
    return sorted(
        hmac.new(secret, _normalize(value).encode("utf-8"), hashlib.sha256)
        .hexdigest()[:_FINGERPRINT_PREFIX_LENGTH]
        for value in values
    )


def sanitize_filters(
    filters: Mapping[str, Any], *, secret: bytes | None
) -> dict[str, Any]:
    """Ne laisser passer en clair que les dimensions de catalogue fermées.

    Tout le reste est du texte d'appelant : il est compté, éventuellement
    empreint sous la clé du journal, jamais recopié.
    """
    sanitized: dict[str, Any] = {}
    for key, value in filters.items():
        if key in CLOSED_FILTER_DIMENSIONS:
            sanitized[key] = value
            continue
        if isinstance(value, str):
            values: Sequence[str] = (value,)
        elif isinstance(value, Sequence) and all(
            isinstance(item, str) for item in value
        ):
            values = tuple(value)
        else:
            sanitized[f"{key}_present"] = value is not None
            continue
        sanitized[f"{key}_count"] = len(values)
        fingerprints = _fingerprint_values(values, secret=secret)
        if fingerprints is not None:
            sanitized[f"{key}_fingerprints"] = fingerprints
    return sanitized


def _frozen(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    """Instantané immuable : ce qui est constaté ne se réécrit pas.

    ``frozen=True`` gèle les attributs, pas les dictionnaires qu'ils
    désignent : sans cette copie, l'appelant pouvait réécrire un
    enregistrement d'audit après sa construction, et même après son émission.
    """
    return MappingProxyType(dict(mapping))


@dataclass(frozen=True)
class RetrievalAccessRecord:
    """Une ligne de journal. Immuable, contenu compris."""

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
    outcome: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "filters", _frozen(self.filters))
        object.__setattr__(self, "channels", _frozen(self.channels))
        object.__setattr__(self, "granted_scopes", tuple(self.granted_scopes))

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
        if self.outcome is not None:
            payload["outcome"] = self.outcome
        return payload

    def as_json(self) -> str:
        return json.dumps(self.as_mapping(), ensure_ascii=False, sort_keys=True)


def log_retrieval_access(
    record: RetrievalAccessRecord,
    *,
    logger: logging.Logger | None = None,
) -> None:
    """Émettre la ligne, sans jamais faire échouer la requête servie.

    Un journal qui casse la réponse transforme un incident d'observabilité en
    incident de service : la défaillance est absorbée ici.
    """
    target = logger if logger is not None else logging.getLogger(ACCESS_LOGGER_NAME)
    try:
        target.info(record.as_json())
    except Exception:  # pragma: no cover - défense en profondeur
        pass


__all__ = [
    "ACCESS_LOGGER_NAME",
    "ACCESS_LOG_HMAC_SECRET_ENV",
    "CLOSED_FILTER_DIMENSIONS",
    "REQUEST_ID_HEADER",
    "RetrievalAccessRecord",
    "load_access_log_secret",
    "log_retrieval_access",
    "query_fingerprint",
    "resolve_request_id",
    "sanitize_filters",
]
