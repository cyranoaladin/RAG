"""Ré-export de la règle de liaison de déploiement — AUCUNE logique ici.

La règle elle-même vit dans :attr:`nexus_release_chain.release_readiness`,
le module que le runtime de lecture embarque octet pour octet. Ce module
n'existe que pour la nommer là où on la cherche.

Il a d'abord porté sa propre implémentation. C'était une deuxième écriture de
la même règle : le qualificateur C1 l'appelait, le service en gardait une
troisième, et rien ne prouvait qu'elles disaient la même chose. Une règle de
configuration écrite deux fois est une règle qui divergera — et celle-ci
décide de ce qui est servi.
"""

from __future__ import annotations

from nexus_release_chain.release_readiness import (
    REGISTRY_PATH_ENV,
    REGISTRY_SHA256_ENV,
    DeploymentBindingError,
    configured_release_registry,
)

__all__ = [
    "REGISTRY_PATH_ENV",
    "REGISTRY_SHA256_ENV",
    "DeploymentBindingError",
    "configured_release_registry",
]
