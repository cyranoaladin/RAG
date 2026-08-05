"""Création best-effort d'un job à l'entrée ``/ingest/v2`` (LOT44e, LOT44f).

Best-effort et non bloquant (choix explicitement validé) : toute erreur ici
est loggée en structuré et **jamais propagée** — l'ingestion réelle
existante (``ingest_v2.py::ingest_document``) continue sans interruption.
Ce module ne prétend jamais qu'une exécution est suivie par un job si la
création a échoué : retourne ``None``, jamais un identifiant fabriqué.

Scope : ``ResourceScope`` (LOT44a, dix dimensions) est construit à partir
des champs réellement fournis par la requête ``/ingest/v2``
(``collection``, ``niveau``, ``voie``, ``matiere``, ``audience``) et des
**mêmes** valeurs par défaut de déploiement déjà utilisées par le pipeline
v2 existant (``ingest_v2._get_default_scope()`` : ``NEXUS_DEFAULT_TENANT``,
``NEXUS_DEFAULT_CANDIDAT``, ``NEXUS_DEFAULT_VISIBILITY``,
``NEXUS_DEFAULT_SCHOOL_YEAR``, ``NEXUS_DEFAULT_PROGRAMME_VERSION``) —
jamais une valeur inventée pour ce pont, jamais un profil par défaut.

Réserve documentée (ADR-0028) : le vocabulaire libre de ``niveau``/``voie``
côté v2 (ex. ``voie="gen"``) ne correspond pas toujours aux valeurs
strictement énumérées de ``nexus_contracts.document.Niveau``/``Voie`` — la
construction du scope échoue alors explicitement (capturée, loggée,
aucun job créé) plutôt que d'être devinée.

Résolution de ``profile_version`` (LOT44f, ADR-0029, ferme partiellement la
dette ADR-0028) : ce pont tente de résoudre un profil LOT44c **réel** avant
de retomber sur le repère legacy. La résolution n'a lieu que si le
registre contient **exactement un** profil actif pour cette ``collection``
et que le scope construit valide contre lui (``validate_scope_against_
profile``, statut ``passed``) — jamais une inférence ambiguë : zéro ou
plusieurs profils candidats retombent sur le mode legacy explicite. Cette
tentative est elle-même best-effort (registre absent, profils LOT44c non
provisionnés, etc. → mode legacy, jamais une exception qui bloque
l'ingestion réelle). Tant qu'aucun profil réel n'est déclaré pour une
collection donnée (état actuel du dépôt, aucun fichier sous
``configs/ingestion_profiles/``), le mode legacy reste le seul chemin
emprunté — documenté, pas masqué.
"""
from __future__ import annotations

import logging
from uuid import UUID

import psycopg
from nexus_contracts.ingestion import ResourceScope

try:
    from ingestor.ingestion_control.db import get_ingestion_control_dsn
    from ingestor.ingestion_control.jobs import create_job, find_active_job_by_dedup_key
    from ingestor.ingestion_control.provisioning import create_ingestion_run
    from ingestor.ingestion_governance_gate import resolve_profiles_dir
    from ingestor.ingestion_profiles.registry import (
        ProfileRegistryError,
        load_profile_registry,
    )
    from ingestor.ingestion_profiles.validation import validate_scope_against_profile
except (ImportError, ValueError):
    # Image Docker aplatie (LOT44f, ADR-0029) : "ingestor" n'existe pas comme
    # paquet — ces sous-paquets sont importables directement au premier
    # niveau. Même discipline que api.py.
    from ingestion_control.db import get_ingestion_control_dsn
    from ingestion_control.jobs import create_job, find_active_job_by_dedup_key
    from ingestion_control.provisioning import create_ingestion_run
    from ingestion_governance_gate import resolve_profiles_dir
    from ingestion_profiles.registry import (
        ProfileRegistryError,
        load_profile_registry,
    )
    from ingestion_profiles.validation import validate_scope_against_profile

logger = logging.getLogger(__name__)

#: Repère explicite de mode legacy : jamais un profil réel. Utilisé quand
#: aucune résolution non ambiguë n'a pu avoir lieu (cf. docstring module).
#: Fait toujours échouer select_profile (LOT44c) côté worker — jamais un
#: profil fabriqué qui laisserait croire qu'une validation a eu lieu.
UNSPECIFIED_PROFILE_VERSION = "unspecified_legacy_ingest_v2"

_CONNECT_TIMEOUT_S = 2


def _resolve_governed_profile_version(*, collection: str, scope: ResourceScope) -> str | None:
    """Retourne un ``profile_version`` réel si — et seulement si — le
    registre LOT44c contient exactement un profil actif pour cette
    ``collection`` et que le scope y valide (statut ``passed``). Toute
    autre situation (registre absent/vide, zéro ou plusieurs candidats,
    validation non passante, erreur de chargement) retourne ``None`` sans
    jamais lever — c'est un enrichissement best-effort, pas une exigence."""
    try:
        registry = load_profile_registry(resolve_profiles_dir())
    except ProfileRegistryError:
        return None

    candidates = sorted(
        {
            profile_version
            for (reg_collection, profile_version), profile in registry.items()
            if reg_collection == collection and profile.enabled
        }
    )
    if len(candidates) != 1:
        return None
    profile_version: str = candidates[0]

    result = validate_scope_against_profile(
        raw_scope=scope.model_dump(mode="json"),
        registry=registry,
        collection=collection,
        profile_version=profile_version,
    )
    if result.status != "passed":
        return None
    return profile_version


def best_effort_create_ingest_job(
    *,
    collection: str,
    source_label: str,
    source_uri: str,
    rights: str,
    type_doc: str,
    matiere: str,
    niveau: str,
    voie: str,
    audience: list[str],
    default_tenant: str,
    default_candidat: str,
    default_visibility: str,
    default_school_year: str,
    default_programme_version: str,
    dedup_key: str,
) -> UUID | None:
    """Tente de créer un run + une resource + un job de suivi pour cette
    requête ``/ingest/v2`` — retourne ``None`` sans jamais lever si quoi
    que ce soit échoue (scope invalide, PostgreSQL injoignable, etc.), en
    loggant systématiquement l'échec (structuré, ``extra=``) pour qu'il
    reste observable sans bloquer l'appelant.

    Idempotent (LOT44f) : si un job non terminal porte déjà ce
    ``dedup_key``, son ``job_id`` est retourné directement, aucun nouveau
    run/job n'est créé — évite les doublons lors d'une nouvelle tentative
    applicative (retry HTTP, double clic)."""
    try:
        scope = ResourceScope(
            tenant=default_tenant,
            collection=collection,
            niveau=niveau,
            voie=voie,
            matiere=matiere,
            candidat=default_candidat,
            audience=audience,
            visibility=default_visibility,
            school_year=default_school_year,
            programme_version=default_programme_version,
        )
    except Exception:
        logger.warning(
            "ingest_v2_job_creation_failed_invalid_scope",
            extra={
                "collection": collection, "niveau": niveau, "voie": voie,
                "matiere": matiere, "source_uri": source_uri,
            },
            exc_info=True,
        )
        return None

    profile_version = _resolve_governed_profile_version(collection=collection, scope=scope)
    governed = profile_version is not None
    if profile_version is None:
        profile_version = UNSPECIFIED_PROFILE_VERSION

    try:
        with psycopg.connect(get_ingestion_control_dsn(), connect_timeout=_CONNECT_TIMEOUT_S) as conn:
            existing_job_id: UUID | None = find_active_job_by_dedup_key(conn, dedup_key=dedup_key)
            if existing_job_id is not None:
                return existing_job_id

            run_id = create_ingestion_run(
                conn, scope=scope, profile_version=profile_version, trigger="manual"
            )
            # resource_id volontairement absent : aucune ressource n'existe
            # encore à cet instant — c'est le worker (run_worker_iteration)
            # qui la créera lors du traitement effectif du job, jamais
            # deux fois (cf. runner.py::_process_claimed_job).
            job_id: UUID = create_job(
                conn,
                run_id=run_id,
                job_type="ingest_v2_upload",
                payload={
                    "scope": scope.model_dump(mode="json"),
                    "dedup_key": dedup_key,
                    "source_url": source_uri,
                    "canonical_url": source_uri,
                    "domain": source_label,
                    "proposed_type_doc": type_doc,
                    "profile_version": profile_version,
                    "rights": rights,
                    "governed": governed,
                },
            )
            conn.commit()
        return job_id
    except Exception:
        logger.warning(
            "ingest_v2_job_creation_failed",
            extra={"collection": collection, "source_uri": source_uri},
            exc_info=True,
        )
        return None


__all__ = ["UNSPECIFIED_PROFILE_VERSION", "best_effort_create_ingest_job"]
