"""Qualification d'une release de production sur le staging (ADR-0060).

Le staging exécute ; la production sert. Qualifier une release sur le staging,
c'est y exercer ses **octets exacts** — contenus, profils, modèles, preuves —
sans que rien de ce qui se passe là ne devienne une permission de production.

Une qualification ne s'active **jamais** par un argument. Elle se déduit d'une
readiness de staging déjà VÉRIFIÉE (signature, ancre, expiration) qui nomme la
release exacte — identifiant et empreinte de manifeste — et l'image qui tourne.
Ce module est le seul endroit qui la construit : un appelant ne peut pas en
fabriquer une pour une release que la readiness ne nomme pas.

Ce qu'elle permet, et rien d'autre :

* consommer le manifeste de profils de PRODUCTION de cette release, par son
  empreinte canonique déclarée, au lieu d'un manifeste de staging ;
* vérifier la chaîne documentaire PII de cette release avec les clés publiques
  qui l'ont réellement signée — la clé privée ne quitte jamais son détenteur.

Elle n'est pas une readiness de production : l'environnement reste
``rehearsal``, et tout ce qui exige ``production`` continue de le refuser.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_JETON = object()


class ReleaseQualificationError(RuntimeError):
    """Refus : la readiness ne qualifie pas cette release, sur cette image."""


@dataclass(frozen=True)
class ReleaseBoundQualification:
    """Ce qu'une readiness de staging vérifiée qualifie — une release, une image."""

    release_id: str
    release_manifest_sha256: str
    readiness_manifest_sha256: str
    worker_image: str
    _jeton: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._jeton is not _JETON:
            raise ReleaseQualificationError(
                "a release qualification is derived from a verified staging "
                "readiness, never constructed by a caller"
            )


def qualify_release_from_staging_readiness(
    readiness: Any,
    *,
    release_manifest_path: Path,
    release_manifest_sha256: str,
    running_image: str,
) -> ReleaseBoundQualification:
    """Rend la qualification que ``readiness`` accorde à cette release, ou refuse.

    ``readiness`` est le résultat de ``enforce_staging_readiness_gate`` : sa
    signature, son ancre et sa fraîcheur sont déjà vérifiées. Ici, on exige
    qu'il nomme exactement la release chargée et l'image qui s'exécute."""
    if getattr(readiness, "environment", None) != "rehearsal":
        raise ReleaseQualificationError(
            "a release qualification exists only under a rehearsal staging readiness"
        )
    manifest = readiness.manifest
    raw = release_manifest_path.read_bytes()
    measured = hashlib.sha256(raw).hexdigest()
    if measured != release_manifest_sha256:
        raise ReleaseQualificationError(
            f"release manifest bytes hash to {measured}, not the expected "
            f"{release_manifest_sha256}"
        )
    if manifest.allowed_release_manifest_sha256 != release_manifest_sha256:
        raise ReleaseQualificationError(
            "staging readiness authorises release manifest "
            f"{manifest.allowed_release_manifest_sha256}, not {release_manifest_sha256}"
        )
    release_id = str(json.loads(raw.decode("utf-8")).get("release_id", ""))
    if manifest.allowed_release_id != release_id:
        raise ReleaseQualificationError(
            f"staging readiness authorises release {manifest.allowed_release_id!r}, "
            f"not {release_id!r}"
        )
    if manifest.worker_image != running_image:
        raise ReleaseQualificationError(
            f"staging readiness names worker image {manifest.worker_image!r}, "
            f"not the running {running_image!r}"
        )
    return ReleaseBoundQualification(
        release_id=release_id,
        release_manifest_sha256=release_manifest_sha256,
        readiness_manifest_sha256=str(readiness.manifest_sha256),
        worker_image=running_image,
        _jeton=_JETON,
    )


__all__ = [
    "ReleaseBoundQualification",
    "ReleaseQualificationError",
    "qualify_release_from_staging_readiness",
]
