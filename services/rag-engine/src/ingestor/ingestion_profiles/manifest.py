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
        approved_by: <identité humaine nommée, ex. "abenrhouma">
        approved_at: <horodatage ISO 8601, ex. "2026-08-05T00:00:00Z">

Couche d'autorité minimale (LOT44f, réconciliation, ADR-0031) : chaque
entrée doit porter ``approved_by``/``approved_at`` — une identité humaine
nommée et un horodatage, tous deux non vides. Ceci n'est **pas** une
implémentation de LOT41A ("autorisation de scope") ni de LOT42
("attestations quality→gate→review") : ces deux lots n'ont, à ce jour,
aucune définition, aucun contrat, aucune implémentation partielle ailleurs
dans ce dépôt (recherche explicite documentée dans ADR-0031) — inventer une
autorité complète pour les remplacer serait exactement l'erreur à éviter.
Ce module livre seulement le strict nécessaire pour qu'aucune entrée de
manifest ne puisse jamais être acceptée sans une trace d'approbation
humaine explicite et attribuable — le gate le plus étroit qui rend
``enforce_production_manifest_gate`` réellement fail-closed sur l'absence
d'autorité, pas seulement sur l'absence de fichier. Tant qu'aucun manifest
réel, approuvé par une autorité humaine nommée, n'existe, ce gate continue
d'échouer explicitement — comportement inchangé pour le cas actuel réel
(aucun manifest de production n'existe dans ce dépôt).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
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
class ProfileAuthority:
    """Autorité humaine explicite ayant approuvé UNE entrée de manifest
    (LOT44f, couche d'autorité minimale — cf. docstring de ce module).
    Jamais devinée : lue telle quelle depuis le manifest."""

    approved_by: str
    approved_at: str


@dataclass(frozen=True)
class ManifestVerification:
    """Preuve qu'un registre correspond exactement à un manifest déclaré,
    empreinte par empreinte — pas seulement identité par identité."""

    manifest_fingerprint: str
    declared_count: int
    manifest_version: str
    provenance: str
    generated_at: str
    authorities: Mapping[ProfileKey, ProfileAuthority]


class _DuplicateKeyRejectingLoader(yaml.SafeLoader):
    """``yaml.SafeLoader`` qui refuse toute clé dupliquée dans n'importe
    quel mapping du document (y compris les entrées de ``profiles``).

    Remédiation revue PR#90 (Cubic P2) : ``yaml.safe_load`` standard
    accepte silencieusement des clés YAML dupliquées — la valeur retenue
    est la dernière, celle *écartée* n'apparaît jamais dans
    ``manifest_fingerprint`` (calculé sur le dict Python déjà dédupliqué).
    Un manifest ambigu (deux valeurs déclarées pour la même clé) pouvait
    donc être audité/approuvé sur un contenu différent de celui
    réellement appliqué par le gate — cassant la garantie de provenance
    que ``manifest_fingerprint`` est censée porter."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            # Remédiation revue PR#90 (Cubic P2, revue incrémentale) : une
            # clé YAML non-hachable (ex. ``? [a, b]: value``, une séquence
            # ou un mapping utilisé comme clé) faisait auparavant échouer
            # ``key in seen`` avec un ``TypeError`` brut, jamais capturé par
            # ``except yaml.YAMLError`` dans ``_read_manifest_yaml`` — un
            # manifest malformé de cette façon plantait avec une erreur bas
            # niveau confuse au lieu d'un ``ProfileManifestError`` maîtrisé.
            # Rejeté ici explicitement, dans la même hiérarchie
            # ``yaml.YAMLError`` que le reste des erreurs de ce chargeur.
            try:
                already_seen = key in seen
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(
                    None, None, f"unhashable mapping key {key!r}: {exc}", node.start_mark
                ) from exc
            if already_seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"found duplicate key {key!r}", node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)

    def compose_node(self, parent: yaml.Node | None, index: Any) -> yaml.Node | None:
        # Remédiation revue PR#90 (Cubic P2, revue incrémentale) : politique
        # explicite pour les ancres/alias/clés de fusion YAML (``&ancre``,
        # ``*alias``, ``<<: *ancre``) — rejetés inconditionnellement, jamais
        # tolérés silencieusement. Un manifest de production est une
        # déclaration d'approbation nominative par entrée (cf. docstring de
        # ce module) : chaque entrée doit être écrite littéralement et
        # rester auditable par simple lecture humaine du fichier, jamais
        # reconstituée indirectement via une référence à un autre nœud du
        # document — une clé de fusion en particulier pourrait faire
        # hériter silencieusement une entrée de champs déclarés ailleurs
        # dans le fichier, rendant le contenu réellement approuvé moins
        # évident qu'une lecture superficielle du fichier ne le suggère.
        # PyYAML ne porte pas l'ancre sur l'objet ``Node`` composé lui-même
        # (contrairement à une intuition naturelle) — elle n'existe que sur
        # l'événement source (``event.anchor``), inspecté ici via
        # ``peek_event()`` (sans le consommer) avant toute composition,
        # pour les deux formes possibles : un nœud portant une déclaration
        # d'ancre, et une référence d'alias (``AliasEvent``) elle-même.
        event = self.peek_event()
        anchor = getattr(event, "anchor", None)
        if anchor is not None:
            kind = "alias" if isinstance(event, yaml.events.AliasEvent) else "anchor"
            raise yaml.constructor.ConstructorError(
                None, None,
                f"YAML {kind} {anchor!r} is not permitted in a production "
                "profile manifest — every entry must be written explicitly and "
                "literally, never referenced indirectly via an anchor/alias or "
                "a merge key (<<)",
                event.start_mark,
            )
        return super().compose_node(parent, index)


def _read_manifest_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ProfileManifestError(f"Production profile manifest not found: {path}")
    try:
        data = yaml.load(  # noqa: S506 - loader restreint (safe + rejet des doublons), jamais yaml.load nu
            path.read_text(encoding="utf-8"), Loader=_DuplicateKeyRejectingLoader
        )
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
    - une entrée est incomplète (``collection``, ``profile_version``,
      ``fingerprint``, ``approved_by`` ou ``approved_at`` manquant ou
      vide) ;
    - ``fingerprint`` ne respecte pas le format attendu (64 caractères
      hexadécimaux) ;
    - ``approved_at`` n'est pas un horodatage ISO 8601 valide (couche
      d'autorité minimale, LOT44f — cf. docstring de ce module) ;
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
    authorities: dict[ProfileKey, ProfileAuthority] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ProfileManifestError(f"Manifest entry #{index} is not a mapping")
        collection = entry.get("collection")
        profile_version = entry.get("profile_version")
        declared_fingerprint = entry.get("fingerprint")
        approved_by = entry.get("approved_by")
        approved_at = entry.get("approved_at")
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
        # Couche d'autorité minimale (LOT44f, ADR-0031) : une entrée sans
        # approbateur nommé ou sans horodatage d'approbation valide est
        # rejetée exactement comme une entrée sans fingerprint — l'autorité
        # n'est pas une métadonnée optionnelle, c'est une condition
        # d'acceptation au même titre que le contenu.
        if not isinstance(approved_by, str) or not approved_by.strip():
            raise ProfileManifestError(
                f"Manifest entry #{index} (collection={collection!r}, "
                f"profile_version={profile_version!r}) has a missing or empty "
                "'approved_by' — no manifest entry may be accepted without a "
                "named human authority"
            )
        if not isinstance(approved_at, str) or not approved_at.strip():
            raise ProfileManifestError(
                f"Manifest entry #{index} (collection={collection!r}, "
                f"profile_version={profile_version!r}) has a missing or empty "
                "'approved_at'"
            )
        try:
            datetime.fromisoformat(approved_at)
        except ValueError as exc:
            raise ProfileManifestError(
                f"Manifest entry #{index} (collection={collection!r}, "
                f"profile_version={profile_version!r}) has an invalid ISO 8601 "
                f"'approved_at': {approved_at!r} ({exc})"
            ) from exc
        key: ProfileKey = (collection, profile_version)
        if key in declared:
            raise ProfileManifestError(
                f"Manifest declares collection={collection!r} "
                f"profile_version={profile_version!r} more than once — ambiguous manifest"
            )
        declared[key] = declared_fingerprint
        authorities[key] = ProfileAuthority(approved_by=approved_by, approved_at=approved_at)

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
        authorities=authorities,
    )


__all__ = [
    "SUPPORTED_MANIFEST_VERSION",
    "ManifestVerification",
    "ProfileAuthority",
    "ProfileManifestError",
    "manifest_fingerprint",
    "verify_profile_manifest",
]
