"""Sélection d'import compatible, sans masquer la cause réelle.

**Le défaut que ce module ferme.** Le dépôt s'exécute sous deux formes :
en paquet (``from . import x``) et en scripts à plat (``import x``), avec
``src/ingestor`` sur le ``PYTHONPATH``. Les modules portaient donc des
replis de la forme ::

    try:
        from . import retrieval_v2_endpoint
    except Exception:
        importlib.import_module("retrieval_v2_endpoint")

Ce ``except`` ne distingue pas deux situations qui n'ont rien à voir :

*le module cible est introuvable* — le repli a un sens ;
*le module a été trouvé, mais son exécution a échoué* — une dépendance
transitive manque, une configuration est invalide — et le repli n'a aucun
sens, puisqu'il réessaie le même code par un autre chemin.

Dans le second cas, le repli échoue à son tour et c'est **son** erreur
qui remonte. Une dépendance manquante au fond de la chaîne ressort alors
en ``ModuleNotFoundError: No module named 'retrieval_v2_endpoint'`` — un
message qui désigne un module parfaitement présent. Le diagnostic part
alors dans la mauvaise direction, et la vraie erreur n'apparaît nulle
part.

``except (ImportError, ValueError)`` aggrave le cas : une ``ValueError``
levée à l'import — une configuration refusée, une borne invalide — n'est
jamais une raison de changer de chemin d'import. Elle est convertie en
« module manquant », ce qui efface l'information la plus utile.

**La règle.** On ne se replie que si l'exception est un
``ModuleNotFoundError`` dont ``exc.name`` désigne *exactement* le module
qu'on cherchait à importer. Tout le reste remonte intact, avec sa trace
d'origine.
"""
from __future__ import annotations

import importlib
from collections.abc import Sequence
from types import ModuleType

__all__ = ["import_first_available", "is_missing_module", "legacy_candidates"]


def is_missing_module(exc: BaseException, *names: str) -> bool:
    """Le module lui-même est-il absent, ou son exécution a-t-elle échoué ?

    C'est la seule question qui autorise un repli. ``exc.name`` porte le
    nom du module que l'import n'a pas trouvé.

    Un **paquet parent** absent compte comme la cible absente : importer
    ``ingestor.foo`` quand ``ingestor`` n'existe pas lève
    ``ModuleNotFoundError(name='ingestor')``. C'est bien « cette
    disposition n'existe pas ici », et l'autre disposition doit être
    tentée. En revanche ``deep_dep``, qui n'est le préfixe d'aucune cible,
    est une dépendance transitive : la cible existe, son exécution a
    échoué, et réessayer ailleurs rejouerait le même échec.
    """
    if isinstance(exc, ImportError) and not isinstance(exc, ModuleNotFoundError):
        # Runtime aplati (image Docker) : ``src/ingestor`` est directement
        # sur le ``sys.path``, les modules n'ont pas de paquet parent et
        # ``from .x import y`` lève « attempted relative import with no
        # known parent package ». C'est bien « cette disposition n'existe
        # pas ici », et c'est la seule ``ImportError`` non-``ModuleNotFound``
        # qui autorise un repli — un ``cannot import name`` signale au
        # contraire un module présent mais incomplet.
        return exc.name is None and "relative import" in str(exc)
    if not isinstance(exc, ModuleNotFoundError):
        return False
    missing = exc.name
    if not missing:
        return False
    return any(
        missing == name or name.startswith(f"{missing}.") for name in names
    )


def legacy_candidates(name: str, *, package: str | None) -> list[str]:
    """Noms complets à tenter, du plus canonique au plus historique.

    L'ordre n'est pas cosmétique : la forme paquet doit gagner quand elle
    est disponible, sinon un même module pourrait être chargé sous deux
    identités et porter deux états globaux distincts.
    """
    candidates: list[str] = []
    if package:
        candidates.append(f"{package}.{name}")
    for prefix in ("src.ingestor", "ingestor"):
        qualified = f"{prefix}.{name}"
        if qualified not in candidates:
            candidates.append(qualified)
    if name not in candidates:
        candidates.append(name)
    return candidates


def import_first_available(
    name: str, *, package: str | None = None, candidates: Sequence[str] | None = None
) -> ModuleType:
    """Importe ``name`` sous sa première forme disponible.

    Se replie uniquement quand la forme tentée est elle-même absente. Une
    dépendance transitive manquante, une configuration refusée ou toute
    autre erreur d'exécution remonte telle quelle : c'est elle qu'il faut
    lire, pas un message de repli.
    """
    attempts = list(candidates) if candidates is not None else legacy_candidates(
        name, package=package
    )
    if not attempts:
        raise ValueError("at least one candidate module name is required")

    last: ModuleNotFoundError | None = None
    for qualified in attempts:
        try:
            return importlib.import_module(qualified)
        except ModuleNotFoundError as exc:
            if not is_missing_module(exc, qualified):
                # Le module existe : c'est l'une de ses dépendances qui
                # manque. Réessayer ailleurs rejouerait le même échec en
                # le renommant.
                raise
            last = exc

    assert last is not None  # noqa: S101 - la boucle a nécessairement échoué
    raise ModuleNotFoundError(
        f"none of {attempts} could be imported; the module is genuinely absent "
        "under every supported layout",
        name=attempts[-1],
    ) from last
