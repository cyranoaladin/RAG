"""Manifest de profils de production (LOT44c).

Un manifest est une déclaration explicite, versionnée dans le dépôt, de
l'ensemble EXACT des identités ``(collection, profile_version)`` attendues
en production, avec l'empreinte de contenu attendue pour chacune — distinct
du simple glob de fichiers qu'effectue ``load_profile_registry`` (qui
accepte silencieusement tout fichier présent dans le répertoire de profils,
sans jamais vérifier qu'il s'agit bien de l'ensemble *voulu*, ni que son
contenu n'a pas dérivé).

Aucun profil de production n'est livré par LOT44c (décision de gouvernance,
hors périmètre infra — cf. rapport de lot). Ce module livre le mécanisme de
contrôle complet : sans manifest réel ni profils réels, tout appel à
``verify_profile_manifest`` échoue explicitement (fichier absent) — jamais
une approximation, jamais un fallback, jamais un profil par défaut.

Format de manifest attendu (YAML) :

    manifest_version: "1"
    provenance: "<origine libre, ex. pipeline de gouvernance>"
    generated_at: "<horodatage ISO 8601 libre, ex. 2026-08-04T00:00:00Z>"
    profiles:
      - collection: <CollectionName>
        profile_version: <str>
        fingerprint: <sha256 hex, 64 caractères>
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

from .registry import (
    ProfileKey,
    ProfileRegistry,
    ProfileRegistryError,
    profile_fingerprint,
)

#: Seule valeur de ``manifest_version`` actuellement supportée — un
#: manifest annonçant une autre valeur est rejeté explicitement plutôt que
#: d'être interprété de façon optimiste (fail-closed sur le format
#: lui-même, pas seulement sur son contenu).
SUPPORTED_MANIFEST_VERSION = "1"

_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ProfileManifestError(ProfileRegistryError):
    """Le manifest est absent, vide, malformé, ambigu, ou incohérent avec
    le registre chargé — toujours un échec explicite."""


@dataclass(frozen=True)
class ManifestVerification:
    """Preuve qu'un registre correspond exactement à un manifest déclaré,
    empreinte par empreinte — pas seulement identité par identité."""

    manifest_fingerprint: str
    declared_count: int
    manifest_version: str
    provenance: str
    generated_at: str


def _read_manifest_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ProfileManifestError(f"Production profile manifest not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProfileManifestError(f"Invalid YAML in manifest {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProfileManifestError(f"Invalid YAML mapping in manifest {path.name}")
    return cast(dict[str, Any], data)


def manifest_fingerprint(manifest_data: Mapping[str, Any]) -> str:
    """Empreinte SHA-256 déterministe du contenu complet du manifest —
    sérialisation canonique, indépendante de l'ordre des clés YAML."""
    canonical = json.dumps(manifest_data, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _require_non_empty_str(data: Mapping[str, Any], field: str, manifest_name: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ProfileManifestError(
            f"Manifest {manifest_name} is missing required field {field!r}"
        )
    return value


def verify_profile_manifest(
    registry: ProfileRegistry,
    manifest_path: Path,
) -> ManifestVerification:
    """Vérifie qu'un registre déjà chargé correspond EXACTEMENT à un
    manifest de production — aucun profil manquant, aucun profil
    surnuméraire, aucune ambiguïté, **aucune empreinte incorrecte**.

    Échec explicite (``ProfileManifestError``) si :
    - le fichier manifest est absent ;
    - le YAML est invalide ou n'est pas une correspondance ;
    - ``manifest_version`` est absent ou différent de
      ``SUPPORTED_MANIFEST_VERSION`` (format non reconnu, jamais interprété
      de façon optimiste) ;
    - ``provenance``/``generated_at`` sont absents ou vides (traçabilité
      obligatoire — un manifest anonyme ou non daté est refusé) ;
    - la clé ``profiles`` est absente ou vide (manifest vide) ;
    - une entrée est incomplète (``collection``, ``profile_version`` ou
      ``fingerprint`` manquant ou vide) ;
    - ``fingerprint`` ne respecte pas le format attendu (64 caractères
      hexadécimaux) ;
    - deux entrées déclarent la même identité (ambiguïté interne) ;
    - une identité déclarée est absente du registre chargé (profil
      manquant) ;
    - le registre chargé contient une identité absente du manifest (profil
      surnuméraire, dérive de configuration non déclarée) ;
    - **l'empreinte déclarée dans le manifest ne correspond pas à
      l'empreinte réelle du profil chargé** (dérive de contenu non
      déclarée — le manifest fige la version ET le contenu exact attendus,
      pas seulement l'identité).

    Aucun profil par défaut, aucun fallback, aucune sélection "latest" :
    la correspondance exigée est une égalité d'ensembles stricte entre les
    identités déclarées et celles réellement chargées, plus une égalité
    stricte d'empreinte pour chacune.
    """
    data = _read_manifest_yaml(manifest_path)

    manifest_version = _require_non_empty_str(data, "manifest_version", manifest_path.name)
    if manifest_version != SUPPORTED_MANIFEST_VERSION:
        raise ProfileManifestError(
            f"Manifest {manifest_path.name} declares manifest_version={manifest_version!r}, "
            f"only {SUPPORTED_MANIFEST_VERSION!r} is supported"
        )
    provenance = _require_non_empty_str(data, "provenance", manifest_path.name)
    generated_at = _require_non_empty_str(data, "generated_at", manifest_path.name)

    entries = data.get("profiles")
    if not isinstance(entries, list) or not entries:
        raise ProfileManifestError(
            f"Manifest {manifest_path.name} declares zero profiles — "
            "an empty manifest can never be valid for production"
        )

    declared: dict[ProfileKey, str] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ProfileManifestError(f"Manifest entry #{index} is not a mapping")
        collection = entry.get("collection")
        profile_version = entry.get("profile_version")
        declared_fingerprint = entry.get("fingerprint")
        if not isinstance(collection, str) or not collection:
            raise ProfileManifestError(f"Manifest entry #{index} is missing 'collection'")
        if not isinstance(profile_version, str) or not profile_version:
            raise ProfileManifestError(f"Manifest entry #{index} is missing 'profile_version'")
        if not isinstance(declared_fingerprint, str) or not _FINGERPRINT_PATTERN.match(
            declared_fingerprint
        ):
            raise ProfileManifestError(
                f"Manifest entry #{index} (collection={collection!r}, "
                f"profile_version={profile_version!r}) has a missing or malformed "
                "'fingerprint' — expected 64 lowercase hexadecimal characters"
            )
        key: ProfileKey = (collection, profile_version)
        if key in declared:
            raise ProfileManifestError(
                f"Manifest declares collection={collection!r} "
                f"profile_version={profile_version!r} more than once — ambiguous manifest"
            )
        declared[key] = declared_fingerprint

    declared_keys = set(declared.keys())
    loaded = set(registry.keys())
    missing = declared_keys - loaded
    if missing:
        raise ProfileManifestError(
            f"Manifest declares profiles not present in the loaded registry: {sorted(missing)}"
        )
    unexpected = loaded - declared_keys
    if unexpected:
        raise ProfileManifestError(
            f"Registry contains profiles not declared in the manifest: {sorted(unexpected)}"
        )

    for key, expected_fingerprint in declared.items():
        actual_fingerprint = profile_fingerprint(registry[key])
        if actual_fingerprint != expected_fingerprint:
            raise ProfileManifestError(
                f"Fingerprint mismatch for collection={key[0]!r} profile_version={key[1]!r}: "
                f"manifest declares {expected_fingerprint}, loaded profile is "
                f"{actual_fingerprint} — profile content drifted from what the manifest expects"
            )

    return ManifestVerification(
        manifest_fingerprint=manifest_fingerprint(data),
        declared_count=len(declared),
        manifest_version=manifest_version,
        provenance=provenance,
        generated_at=generated_at,
    )


__all__ = [
    "SUPPORTED_MANIFEST_VERSION",
    "ManifestVerification",
    "ProfileManifestError",
    "manifest_fingerprint",
    "verify_profile_manifest",
]
