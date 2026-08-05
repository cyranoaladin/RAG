"""Câblage du gate de démarrage LOT44c dans les processus réellement
déployés (LOT44f, ADR-0029).

``ingestion_profiles.startup_gate.enforce_production_manifest_gate`` est un
mécanisme complet (registre + manifest + empreinte, échec fermé) livré par
LOT44c mais délibérément non câblé — son propre module le documente comme
"portée non couverte par ce lot" (cf. ``ingestion_profiles/startup_gate.py``,
en-tête), pour ne pas modifier un fichier d'un lot antérieur sans mandat
explicite. Ce module fournit ce câblage sans modifier aucun fichier
``ingestion_profiles/*.py`` (ADR-0026 reste fermé, non rouvert).

Règle retenue (ADR-0029) : le gate ne bloque un démarrage que pour un
processus qui déclare réellement l'intention de faire de l'ingestion
gouvernée.

- ``api.py`` sert aussi le retrieval en lecture seule
  (``pedago_interface_contract.yml`` : ``server_start_allowed: true``,
  indépendant de ``real_documents_allowed``) — le bloquer
  inconditionnellement casserait un déploiement retrieval-only légitime.
  Le signal retenu n'est pas un nouveau flag arbitraire : c'est
  ``PG_INGESTION_CONTROL_DSN``, la variable qui déclenche déjà, depuis
  LOT44e, la tentative best-effort de création de job
  (``ingestion_worker/ingest_v2_bridge.py``). Un déploiement qui configure
  cette variable déclare son intention d'utiliser le plan de contrôle ; le
  gate devient alors bloquant pour ``api.py``.
- ``ingestion_worker.cli`` n'a aucune raison d'exister sans plan de
  contrôle : le gate y est inconditionnel (câblé directement dans
  ``cli.py``, pas via ce module).
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from ingestor.ingestion_control.db import get_ingestion_control_dsn
    from ingestor.ingestion_profiles.registry import PROFILES_DIR_ENV, PROFILES_DIRNAME
    from ingestor.ingestion_profiles.startup_gate import (
        StartupGateResult,
        enforce_production_manifest_gate,
    )
except (ImportError, ValueError):
    # Image Docker aplatie (LOT44f, ADR-0029) : "ingestor" n'existe pas comme
    # paquet — ingestion_control/ingestion_profiles sont importables
    # directement au premier niveau. Même discipline que api.py.
    from ingestion_control.db import get_ingestion_control_dsn
    from ingestion_profiles.registry import (
        PROFILES_DIR_ENV,
        PROFILES_DIRNAME,
    )
    from ingestion_profiles.startup_gate import (
        StartupGateResult,
        enforce_production_manifest_gate,
    )

INGESTION_MANIFEST_PATH_ENV = "RAG_ENGINE_INGESTION_MANIFEST_PATH"


class IngestionGovernanceConfigError(RuntimeError):
    """Le plan de contrôle est activé (DSN présent) mais la configuration du
    gate est incomplète — jamais un démarrage silencieux avec un chemin de
    manifest implicite."""


def ingestion_control_plane_enabled() -> bool:
    """``True`` si ``PG_INGESTION_CONTROL_DSN`` est configuré — même
    fonction que ``ingest_v2_bridge`` utilise pour décider de tenter la
    création best-effort d'un job, réutilisée ici plutôt que de relire la
    variable d'environnement sous un autre nom."""
    try:
        get_ingestion_control_dsn()
    except RuntimeError:
        return False
    return True


def resolve_profiles_dir() -> Path:
    """Même résolution que ``ingestion_profiles.registry`` (variable
    d'environnement puis répertoire par défaut) — dupliquée ici en 3 lignes
    plutôt que d'importer un symbole privé (``_resolve_profiles_dir``) à
    travers une frontière de module."""
    env_dir = os.getenv(PROFILES_DIR_ENV)
    if env_dir:
        return Path(env_dir).expanduser()
    engine_root = Path(__file__).resolve().parents[2]
    return Path(engine_root / "configs" / PROFILES_DIRNAME)


def enforce_governance_gate_from_environment() -> StartupGateResult:
    """Exécute le gate LOT44c à partir de la configuration d'environnement
    (``api.py`` uniquement — le worker CLI configure ses chemins par
    arguments explicites, pas par variables d'environnement, cf.
    ``ingestion_worker/cli.py``).

    Échec explicite (exception non interceptée) si le manifest est absent,
    invalide, ou si son chemin n'est pas configuré — jamais de valeur de
    repli, jamais de chemin par défaut deviné pour le manifest lui-même."""
    manifest_path_str = os.getenv(INGESTION_MANIFEST_PATH_ENV, "").strip()
    if not manifest_path_str:
        raise IngestionGovernanceConfigError(
            "PG_INGESTION_CONTROL_DSN is set (ingestion control plane "
            f"enabled) but {INGESTION_MANIFEST_PATH_ENV} is not — refusing "
            "to start with an implicit manifest path."
        )
    return enforce_production_manifest_gate(
        resolve_profiles_dir(), Path(manifest_path_str).expanduser()
    )


__all__ = [
    "INGESTION_MANIFEST_PATH_ENV",
    "IngestionGovernanceConfigError",
    "enforce_governance_gate_from_environment",
    "ingestion_control_plane_enabled",
    "resolve_profiles_dir",
]
