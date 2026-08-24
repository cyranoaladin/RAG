"""Registre de révocation gouverné — exigé en production, jamais par défaut.

**Le défaut fermé ici.** Le manifeste de readiness de production signé
(``nexus_contracts.production_readiness.ProductionReadinessManifestV1``)
porte déjà un ``revocation_registry_digest`` : c'est l'empreinte que la
chaîne de promotion a approuvée. Mais rien, avant ce module, ne charge le
fichier correspondant ni ne vérifie qu'il correspond à ce digest — le
worker faisait confiance à la signature du manifeste sans jamais
consulter le contenu qu'elle nomme. L'absence de ce fichier n'est
**jamais** interprétée comme « rien n'est révoqué » : c'est un refus de
démarrage, au même titre qu'une preuve PII ou de droits absente."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from nexus_contracts.authorization_revocations import (
    parse_revoked_authorization_ids,
)

_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_SUPPORTED_VERSIONS = frozenset({"1"})
_ENTRY_FIELDS = frozenset({"kind", "id"})
_SUPPORTED_KINDS = frozenset({"authorization", "publication_attestation"})


class RevocationRegistryError(RuntimeError):
    """Le registre de révocation ne peut pas être établi — refus explicite."""


@dataclass(frozen=True)
class RevocationRegistry:
    sha256: str
    registry_version: str
    revoked_authorization_ids: frozenset[str]
    revoked_publication_attestation_ids: frozenset[str]

    def is_revoked(
        self,
        *,
        authorization_id: str | None = None,
        publication_attestation_id: str | None = None,
    ) -> bool:
        if authorization_id is not None and authorization_id in self.revoked_authorization_ids:
            return True
        if (
            publication_attestation_id is not None
            and publication_attestation_id in self.revoked_publication_attestation_ids
        ):
            return True
        return False


def load_revocation_registry(path: Path, *, expected_sha256: str) -> RevocationRegistry:
    """Charger le registre, vérifié par sa propre empreinte externe.

    Jamais de valeur de repli : chaque absence ou divergence est un refus."""
    if not isinstance(expected_sha256, str) or _SHA256.fullmatch(expected_sha256) is None:
        raise RevocationRegistryError(
            "expected revocation registry digest must be a lowercase 64-hex SHA-256"
        )
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise RevocationRegistryError(f"revocation registry unavailable at {path}") from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise RevocationRegistryError("revocation registry digest differs from the pinned expectation")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RevocationRegistryError("revocation registry is not valid JSON") from exc
    if not isinstance(document, Mapping):
        raise RevocationRegistryError("revocation registry must be an object")
    if document.get("registry_version") not in _SUPPORTED_VERSIONS:
        raise RevocationRegistryError("revocation registry version is unsupported")
    revoked = document.get("revoked")
    if not isinstance(revoked, list):
        raise RevocationRegistryError("revocation registry.revoked must be an array")

    authorization_ids: set[str] = set()
    attestation_ids: set[str] = set()
    for index, entry_raw in enumerate(revoked):
        field = f"revocation registry.revoked[{index}]"
        if not isinstance(entry_raw, Mapping) or set(entry_raw) != _ENTRY_FIELDS:
            raise RevocationRegistryError(f"{field} is malformed")
        kind = entry_raw.get("kind")
        identifier = entry_raw.get("id")
        if kind not in _SUPPORTED_KINDS:
            raise RevocationRegistryError(f"{field}.kind is unsupported")
        if not isinstance(identifier, str) or not identifier.strip():
            raise RevocationRegistryError(f"{field}.id must be nonblank")
        if kind == "authorization":
            authorization_ids.add(identifier)
        else:
            attestation_ids.add(identifier)

    return RevocationRegistry(
        sha256=actual,
        registry_version=str(document["registry_version"]),
        revoked_authorization_ids=frozenset(authorization_ids),
        revoked_publication_attestation_ids=frozenset(attestation_ids),
    )


def load_shared_authorization_revocations(
    path: Path, *, expected_sha256: str
) -> RevocationRegistry:
    """Charge exclusivement le registre partagé des releases V2.

    Le parseur historique reste dans :func:`load_revocation_registry`. Deux
    points d'entrée nommés rendent impossible un fallback silencieux entre
    des schémas qui n'ont ni les mêmes champs ni la même sémantique.
    """
    if not isinstance(expected_sha256, str) or _SHA256.fullmatch(expected_sha256) is None:
        raise RevocationRegistryError(
            "expected revocation registry digest must be a lowercase 64-hex SHA-256"
        )
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise RevocationRegistryError(f"revocation registry unavailable at {path}") from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise RevocationRegistryError(
            "revocation registry digest differs from the pinned expectation"
        )
    try:
        revoked = parse_revoked_authorization_ids(raw, origin=str(path))
    except ValueError as exc:
        raise RevocationRegistryError(str(exc)) from exc
    return RevocationRegistry(
        sha256=actual,
        registry_version="NEXUS-AUTHORIZATION-REVOCATIONS-V1",
        revoked_authorization_ids=frozenset(revoked),
        revoked_publication_attestation_ids=frozenset(),
    )


def require_revocation_registry_matches_manifest(
    registry: RevocationRegistry,
    *,
    manifest_revocation_registry_digest: str,
) -> None:
    """Lier le registre chargé au digest que le manifeste signé a approuvé.

    Un registre valide en soi, mais dont l'empreinte diffère de celle que
    la chaîne de promotion a signée, n'est pas *le* registre gouverné :
    c'est un fichier de plus qui prétend l'être."""
    if registry.sha256 != manifest_revocation_registry_digest:
        raise RevocationRegistryError(
            "revocation registry digest does not match the production readiness manifest"
        )


__all__ = [
    "RevocationRegistry",
    "RevocationRegistryError",
    "load_revocation_registry",
    "load_shared_authorization_revocations",
    "require_revocation_registry_matches_manifest",
]
