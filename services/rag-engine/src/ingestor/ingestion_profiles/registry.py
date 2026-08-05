"""Registre déclaratif des profils de collection (LOT44c).

Réutilise ``CollectionProfile`` (LOT44a, ``nexus_contracts.ingestion``) sans
aucune modification. Chaque profil est un fichier YAML déclaratif, mirroir
du motif déjà en place pour ``rag_collections.yml``
(``ingestor.collection_config``) : résolution de chemin par variable
d'environnement, chargement explicite, aucune supposition implicite.

Un profil n'est jamais persisté en base : c'est une déclaration statique,
versionnée dans le dépôt (LOT44b a délibérément laissé ``profile_version``
comme colonne texte libre, sans table ``collection_profiles`` ni FK — cf.
ADR-0024, ADR-0025). Ce module ne crée donc aucune migration.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import yaml
from nexus_contracts.ingestion import CollectionProfile
from pydantic import ValidationError

PROFILES_DIR_ENV = "RAG_ENGINE_INGESTION_PROFILES_DIR"
PROFILES_DIRNAME = "ingestion_profiles"

#: Contrainte LOT44c, plus stricte que le contrat gelé CollectionProfile
#: (``profile_version: str = Field(min_length=1)``, qui accepte toute
#: chaîne non vide, y compris des espaces). L'identité d'un profil dans ce
#: lot étant ``(collection, profile_version)`` — jamais un UUID —, sa
#: stabilité dépend directement de la forme de cette chaîne : ce motif
#: rejette les espaces, sauts de ligne et caractères de contrôle, borne la
#: longueur, sans modifier le contrat LOT44a lui-même (vérification
#: additionnelle, appliquée uniquement au chargement du registre).
PROFILE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

ProfileKey = tuple[str, str]
ProfileRegistry = dict[ProfileKey, CollectionProfile]


class ProfileRegistryError(ValueError):
    """Base des erreurs de registre de profils — jamais levée directement."""


class ProfileRegistryLoadError(ProfileRegistryError):
    """Le registre ne peut pas être chargé : YAML invalide, profil
    structurellement invalide, ou doublon ``(collection, profile_version)``
    entre deux fichiers — rejeté explicitement, jamais "le dernier gagne"."""


class ProfileUnknownError(ProfileRegistryError):
    """Aucun profil enregistré pour ``(collection, profile_version)``."""


class ProfileDisabledError(ProfileRegistryError):
    """Le profil existe mais ``enabled`` est ``False`` — rejet explicite,
    distinct d'un profil inconnu."""


def profile_fingerprint(profile: CollectionProfile) -> str:
    """Empreinte SHA-256 déterministe du contenu complet d'un profil.

    Distincte de l'identité ``(collection, profile_version)`` : deux profils
    de même identité mais de contenu différent produisent des empreintes
    différentes. Sérialisation canonique — ``model_dump(mode="json")`` puis
    ``json.dumps(..., sort_keys=True)`` — stable indépendamment de l'ordre
    des clés dans le fichier YAML source (l'ordre des champs Pydantic est
    fixé par la déclaration du modèle, jamais par le fichier).

    Ne détecte PAS, à elle seule, la modification d'un profil déjà utilisé :
    cette fonction est pure et sans état, elle ne compare à aucun
    historique. La détection réelle d'une dérive nécessite qu'un appelant
    (LOT44c : ``ValidationResult.profile_fingerprint``, persistée via
    ``record_validation_result``) compare cette empreinte à celle d'un
    résultat précédent pour la même identité — mécanisme habilitant, pas
    encore un contrôle automatique (cf. ADR-0026, réserve documentée).
    """
    canonical = json.dumps(profile.model_dump(mode="json"), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _resolve_profiles_dir(directory: Path | None) -> Path:
    if directory is not None:
        return directory
    env_dir = os.getenv(PROFILES_DIR_ENV)
    if env_dir:
        return Path(env_dir).expanduser()
    # services/rag-engine/src/ingestor/ingestion_profiles/registry.py -> services/rag-engine/configs/ingestion_profiles
    engine_root = Path(__file__).resolve().parents[3]
    return engine_root / "configs" / PROFILES_DIRNAME


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProfileRegistryLoadError(f"Invalid YAML in {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProfileRegistryLoadError(f"Invalid YAML mapping in {path.name}")
    return cast(dict[str, Any], data)


def load_profile_registry(directory: Path | None = None) -> ProfileRegistry:
    """Charge tous les profils déclaratifs d'un répertoire.

    - Répertoire absent : registre vide (aucun profil n'est encore déclaré,
      ce n'est jamais une erreur — LOT44c ne livre aucun profil de
      production, cf. rapport de lot).
    - Ordre de lecture des fichiers : trié par chemin complet — jamais
      dépendant de l'ordre de retour du système de fichiers.
    - Un fichier YAML structurellement invalide (ne valide pas
      ``CollectionProfile``) fait échouer le chargement entier : un
      registre partiellement chargé n'est jamais retourné.
    - Deux fichiers déclarant la même clé ``(scope.collection,
      profile_version)`` font échouer le chargement entier — jamais "le
      dernier fichier lu gagne".
    """
    dir_path = _resolve_profiles_dir(directory)
    if not dir_path.is_dir():
        return {}

    paths = sorted({*dir_path.glob("*.yml"), *dir_path.glob("*.yaml")})
    registry: ProfileRegistry = {}
    for path in paths:
        data = _read_yaml(path)
        try:
            profile = CollectionProfile.model_validate(data)
        except ValidationError as exc:
            raise ProfileRegistryLoadError(
                f"Profile file {path.name} does not validate against CollectionProfile: {exc}"
            ) from exc

        if not PROFILE_VERSION_PATTERN.match(profile.profile_version):
            raise ProfileRegistryLoadError(
                f"Profile file {path.name}: profile_version {profile.profile_version!r} "
                f"does not match the required pattern {PROFILE_VERSION_PATTERN.pattern!r} "
                "(LOT44c registry constraint, stricter than the frozen CollectionProfile "
                "contract — identity stability requires a bounded, unambiguous version string)"
            )

        key: ProfileKey = (profile.scope.collection, profile.profile_version)
        if key in registry:
            raise ProfileRegistryLoadError(
                f"Duplicate profile registration for collection={key[0]!r} "
                f"profile_version={key[1]!r} (file {path.name} conflicts with an "
                "earlier file) — ambiguous registry, refusing to select silently"
            )
        registry[key] = profile

    return registry


def select_profile(
    registry: Mapping[ProfileKey, CollectionProfile],
    *,
    collection: str,
    profile_version: str,
) -> CollectionProfile:
    """Sélection explicite et déterministe : ``(collection, profile_version)``
    doivent être fournis tous les deux — aucune inférence de "dernière
    version" ou de "profil par défaut" n'est effectuée (aucune règle
    canonique de ce type n'existe dans les contrats LOT44a/ADR)."""
    key: ProfileKey = (collection, profile_version)
    profile = registry.get(key)
    if profile is None:
        raise ProfileUnknownError(
            f"No profile registered for collection={collection!r} "
            f"profile_version={profile_version!r}"
        )
    if not profile.enabled:
        raise ProfileDisabledError(
            f"Profile collection={collection!r} profile_version={profile_version!r} "
            "is registered but disabled (enabled=False)"
        )
    return profile


__all__ = [
    "PROFILE_VERSION_PATTERN",
    "ProfileDisabledError",
    "ProfileKey",
    "ProfileRegistry",
    "ProfileRegistryError",
    "ProfileRegistryLoadError",
    "ProfileUnknownError",
    "load_profile_registry",
    "profile_fingerprint",
    "select_profile",
]
