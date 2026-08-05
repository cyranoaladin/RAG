"""Dépendances injectables communes aux stages LOT44d.

Périmètre strict : deux points d'E/S réseau partagés (validation de
destination, téléchargement borné), déclarés ici comme types et valeurs par
défaut réelles — jamais appelés en dur depuis un cœur de stage. Chaque
cœur de stage (``*_core``) reste une fonction pure ; seule la couche
d'exécution (``run_*``) reçoit ces dépendances, avec la vraie implémentation
en valeur par défaut et une doublure injectable pour les tests (cf.
ADR-0029, contrainte « cœur déterministe sans E/S implicite »).

Planner, Scout et Fetcher sont les trois stages qui manipulent une URL
externe (LOT44d, consigne explicite) : ils passent exclusivement par
``ssrf_guard.validate_destination``/``ssrf_guard.safe_fetch`` — jamais un
``httpx``/``requests`` direct sur une URL non fiable.
"""
from __future__ import annotations

from typing import Protocol
from uuid import UUID

import httpx

try:
    from ingestor import ssrf_guard
except (ImportError, ValueError):
    # Image Docker aplatie (LOT44f, ADR-0029) : "ingestor" n'existe pas comme
    # paquet — ssrf_guard est importable directement au premier niveau,
    # sibling de api.py. Même discipline que api.py.
    import ssrf_guard


class DestinationValidator(Protocol):
    """Signature de ``ssrf_guard.validate_destination`` — pas de réseau caché
    au-delà de ce qu'elle effectue elle-même (résolution DNS incluse)."""

    def __call__(self, url: str) -> str: ...


class SafeFetcher(Protocol):
    """Signature de ``ssrf_guard.safe_fetch``."""

    def __call__(
        self,
        url: str,
        *,
        max_bytes: int,
        max_redirects: int = ...,
        timeout: httpx.Timeout = ...,
        transport: httpx.BaseTransport | None = ...,
    ) -> httpx.Response: ...


class ArtifactStore(Protocol):
    """Persiste un contenu binaire et retourne une référence stable (chemin,
    URI, clé d'objet — au choix de l'appelant).

    Aucune implémentation réelle n'est fournie par LOT44d : ce dépôt ne
    contient aucun client de stockage (S3, filesystem partagé, etc.)
    réutilisable, et en créer un serait une infrastructure de production
    hors périmètre de ce lot. Ce protocole documente uniquement le point
    d'injection attendu par ``Fetcher`` — un appelant réel (LOT44e ou
    ultérieur) doit fournir une implémentation explicite ; aucun défaut
    silencieux n'existe pour ce paramètre.
    """

    def __call__(self, *, artifact_id: UUID, content: bytes) -> str: ...


class ArtifactReader(Protocol):
    """Relit un contenu binaire déjà persisté par ``ArtifactStore``, à
    partir de la référence qu'il a retournée.

    Comme ``ArtifactStore``, aucune implémentation réelle n'est fournie par
    LOT44d — point d'injection obligatoire pour ``Extractor``, sans défaut
    silencieux.
    """

    def __call__(self, *, extracted_text_ref: str) -> bytes: ...


#: Implémentations réelles par défaut — un stage appelé sans surcharge
#: explicite passe réellement par la garde SSRF de production (LOT43, D-7),
#: jamais par une approximation locale.
default_validate_destination: DestinationValidator = ssrf_guard.validate_destination
default_safe_fetch: SafeFetcher = ssrf_guard.safe_fetch


__all__ = [
    "ArtifactReader",
    "ArtifactStore",
    "DestinationValidator",
    "SafeFetcher",
    "default_safe_fetch",
    "default_validate_destination",
]
