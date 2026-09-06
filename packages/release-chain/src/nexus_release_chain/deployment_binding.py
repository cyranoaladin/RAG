"""Comment un DÉPLOIEMENT désigne le registre de releases qu'il sert.

Le chemin hôte est un **locator de transport** : il change d'une machine à
l'autre, et un staging comme une production peuvent monter des répertoires
différents. L'**autorité sémantique**, elle, est le couple identité + empreinte
du registre : deux stacks servent la même lignée si et seulement si elles
servent les mêmes octets.

Ce module existe parce que cette règle vivait dans un seul consommateur. Le
qualificateur C1 la réimplémentait, et l'a d'abord réimplémentée FAUX —
acceptant un chemin sans empreinte que le runtime refuse. Une règle de
configuration écrite deux fois est une règle qui divergera : elle est donc
énoncée ici, une seule fois, pour tous ceux qui la lisent.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

__all__ = [
    "REGISTRY_PATH_ENV",
    "REGISTRY_SHA256_ENV",
    "DeploymentBindingError",
    "configured_release_registry",
]

#: Les deux variables par lesquelles un déploiement s'exprime. Elles vont par
#: paire : un chemin sans empreinte laisserait le fichier observé devenir sa
#: propre autorité.
REGISTRY_PATH_ENV = "RAG_RELEASE_REGISTRY_PATH"
REGISTRY_SHA256_ENV = "RAG_RELEASE_REGISTRY_SHA256"


class DeploymentBindingError(ValueError):
    """La configuration de déploiement ne désigne pas une lignée — refus."""


def configured_release_registry(
    environ: Mapping[str, str] | None = None,
) -> tuple[Path, str] | None:
    """Le registre que le déploiement sert, ou ``None`` s'il n'en désigne aucun.

    Trois cas, et trois seulement :

    * les deux absents — aucun déploiement ne parle, l'appelant retombe sur sa
      politique par défaut ;
    * les deux présents — la lignée est explicitement épinglée, chemin ET
      octets ;
    * un seul présent — **refus**. Un chemin sans empreinte transformerait le
      fichier observé en sa propre autorité ; une empreinte sans chemin ne
      désigne rien.
    """
    source = os.environ if environ is None else environ
    chemin = source.get(REGISTRY_PATH_ENV)
    empreinte = source.get(REGISTRY_SHA256_ENV)
    if chemin is None and empreinte is None:
        return None
    if not chemin or not empreinte:
        raise DeploymentBindingError(
            "release registry configuration incomplete: "
            f"{REGISTRY_PATH_ENV}={chemin!r} {REGISTRY_SHA256_ENV}={empreinte!r}"
        )
    return Path(chemin), empreinte
