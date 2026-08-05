"""Création best-effort d'un job à l'entrée ``/ingest/v2`` (LOT44e).

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
aucun job créé) plutôt que d'être devinée. De même, aucun
``profile_version`` LOT44c réel n'existe pour le chemin ``/ingest/v2`` :
la valeur portée dans le payload du job est un repère explicite qui fera
toujours échouer ``select_profile`` (``ProfileUnknownError``) tant qu'une
convention réelle n'est pas établie — jamais un profil fabriqué qui
laisserait croire qu'une validation LOT44c a eu lieu.
"""
from __future__ import annotations

import logging
from uuid import UUID

import psycopg
from nexus_contracts.ingestion import ResourceScope

try:
    from ingestor.ingestion_control.db import get_ingestion_control_dsn
    from ingestor.ingestion_control.jobs import create_job
    from ingestor.ingestion_control.provisioning import create_ingestion_run
except (ImportError, ValueError):
    # Image Docker aplatie (LOT44f, ADR-0029) : "ingestor" n'existe pas comme
    # paquet — ingestion_control est importable directement au premier
    # niveau. Même discipline que api.py. Notons que ce module est déjà
    # importé de façon défensive (try/except) par son unique appelant
    # (ingest_v2_endpoint.py::_best_effort_track_job) — cette correction
    # rend l'import lui-même robuste plutôt que de dépendre uniquement de
    # ce filet de sécurité applicatif.
    from ingestion_control.db import get_ingestion_control_dsn
    from ingestion_control.jobs import create_job
    from ingestion_control.provisioning import create_ingestion_run

logger = logging.getLogger(__name__)

#: Jamais un profil réel : ce repère fait toujours échouer select_profile
#: (LOT44c) tant qu'aucune convention profile_version n'existe pour le
#: chemin /ingest/v2 — documente l'absence, ne la masque jamais.
UNSPECIFIED_PROFILE_VERSION = "unspecified_legacy_ingest_v2"

_CONNECT_TIMEOUT_S = 2


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
    reste observable sans bloquer l'appelant."""
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

    try:
        with psycopg.connect(get_ingestion_control_dsn(), connect_timeout=_CONNECT_TIMEOUT_S) as conn:
            run_id = create_ingestion_run(
                conn, scope=scope, profile_version=UNSPECIFIED_PROFILE_VERSION, trigger="manual"
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
                    "profile_version": UNSPECIFIED_PROFILE_VERSION,
                    "rights": rights,
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
