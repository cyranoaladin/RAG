"""Ré-export de la règle de liaison de déploiement — AUCUNE logique ici.

La règle elle-même vit dans :attr:`nexus_release_chain.release_readiness`,
le module que le runtime de lecture embarque octet pour octet. Ce module
n'existe que pour la nommer là où on la cherche.

Il a d'abord porté sa propre implémentation. C'était une deuxième écriture de
la même règle : le qualificateur C1 l'appelait, le service en gardait une
troisième, et rien ne prouvait qu'elles disaient la même chose. Une règle de
configuration écrite deux fois est une règle qui divergera — et celle-ci
décide de ce qui est servi.

La règle couvre les TROIS mécanismes que le runtime reconnaît — registre
canonique, liste explicite de manifests, couple historique d'un manifest
unique — et leur exclusion mutuelle. N'en ré-exporter qu'un tiers laissait le
qualificateur retomber sur son défaut là où le service sert autre chose.
"""

from __future__ import annotations

from nexus_release_chain.release_readiness import (
    MANIFEST_PATH_ENV,
    MANIFEST_SHA256_ENV,
    MANIFESTS_JSON_ENV,
    REGISTRY_PATH_ENV,
    REGISTRY_SHA256_ENV,
    RELEASE_AUTHORITY_LEGACY_MANIFEST,
    RELEASE_AUTHORITY_MANIFEST_LIST,
    RELEASE_AUTHORITY_REGISTRY_FILE,
    DeploymentBindingError,
    ReleaseAuthoritySelection,
    configured_release_manifest,
    configured_release_registry,
    load_selected_release_registry,
    parse_release_manifest_list,
    select_release_authority,
)

__all__ = [
    "MANIFEST_PATH_ENV",
    "MANIFEST_SHA256_ENV",
    "MANIFESTS_JSON_ENV",
    "REGISTRY_PATH_ENV",
    "REGISTRY_SHA256_ENV",
    "RELEASE_AUTHORITY_LEGACY_MANIFEST",
    "RELEASE_AUTHORITY_MANIFEST_LIST",
    "RELEASE_AUTHORITY_REGISTRY_FILE",
    "DeploymentBindingError",
    "ReleaseAuthoritySelection",
    "configured_release_manifest",
    "configured_release_registry",
    "load_selected_release_registry",
    "parse_release_manifest_list",
    "select_release_authority",
]
