"""Attestation du rôle runtime PostgreSQL du worker (LOT44f, remédiation
revue PR#90, item I — revue incrémentale).

Avant ce module, ``ingestion_worker/cli.py`` ouvrait la connexion PostgreSQL
(``PG_INGESTION_CONTROL_DSN``) et démarrait sa boucle sans jamais vérifier
QUI cette connexion était réellement — un DSN mal configuré (ex. pointant
par erreur vers le superutilisateur du conteneur ``pgvector``, ou vers le
rôle de migration plutôt que le rôle applicatif) aurait laissé le worker
tourner avec des privilèges très supérieurs à ceux strictement nécessaires
à sa boucle de traitement — silencieusement, jamais détecté avant qu'un
incident ne le révèle.

``attest_runtime_role`` vérifie, dans l'ordre, **avant** que le worker ne
fasse quoi que ce soit d'autre avec cette connexion :

1. ``current_user`` correspond exactement au rôle attendu (``expected_role``,
   fourni séparément du DSN — jamais dérivé du DSN lui-même, pour détecter
   un DSN qui se connecterait silencieusement à un rôle différent de celui
   annoncé par la configuration).
2. Le rôle n'est ni superutilisateur, ni ``CREATEDB``, ni ``CREATEROLE``, ni
   ``REPLICATION``, ni ``BYPASSRLS`` — mêmes attributs de moindre privilège
   que ceux imposés par ``provision_ingestion_control_roles.sh`` (item C),
   revérifiés ici côté runtime pour détecter une dérive de configuration
   entre le provisioning et l'exécution.
3. Le rôle ne possède PAS le schéma ``ingestion_control`` (propriété
   réservée au rôle de migration, jamais au rôle applicatif — cf.
   ``ALTER SCHEMA ... OWNER TO`` dans le script de provisioning).
4. Le rôle ne porte aucun privilège excessif sur
   ``ingestion_control.workflow_events`` : ``SELECT``/``INSERT`` attendus,
   ``UPDATE``/``DELETE``/``TRUNCATE`` doivent être absents (protection
   append-only réelle, item C/ADR-0026 décision 5 — revérifiée ici côté
   runtime, pas seulement au provisioning).
5. Le rôle n'est membre d'aucun autre rôle (``pg_auth_members``) — aucune
   voie de ``SET ROLE`` vers une autorité supérieure (même invariant que
   celui appliqué côté provisioning, item D).

Toute violation lève ``WorkerAttestationError`` — l'appelant (``cli.py``)
doit refuser de démarrer, jamais dégrader silencieusement en poursuivant
avec des privilèges non vérifiés.
"""
from __future__ import annotations

from dataclasses import dataclass

import psycopg


class WorkerAttestationError(RuntimeError):
    """Le rôle PostgreSQL réellement utilisé par cette connexion ne
    correspond pas à la politique de moindre privilège attendue — le
    worker doit refuser de démarrer, jamais poursuivre avec des privilèges
    non vérifiés."""


@dataclass(frozen=True)
class RoleAttestation:
    current_user: str
    is_superuser: bool
    can_create_db: bool
    can_create_role: bool
    can_replicate: bool
    can_bypass_rls: bool
    owns_ingestion_control_schema: bool
    has_excessive_workflow_events_grant: bool
    member_of_other_roles: bool


def _fetch_attestation(conn: psycopg.Connection, *, expected_role: str) -> RoleAttestation:
    with conn.cursor() as cur:
        cur.execute("SELECT current_user")
        current_user_row = cur.fetchone()
        if current_user_row is None:  # pragma: no cover - SELECT current_user renvoie toujours une ligne
            raise WorkerAttestationError("SELECT current_user produced no row")
        (current_user,) = current_user_row

        cur.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
            "FROM pg_roles WHERE rolname = %s",
            (current_user,),
        )
        row = cur.fetchone()
        if row is None:
            raise WorkerAttestationError(
                f"current_user={current_user!r} not found in pg_roles — cannot attest"
            )
        is_superuser, can_create_db, can_create_role, can_replicate, can_bypass_rls = row

        cur.execute(
            "SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'ingestion_control'"
        )
        owner_row = cur.fetchone()
        owns_schema = owner_row is not None and owner_row[0] == current_user

        cur.execute(
            "SELECT has_table_privilege(%s, 'ingestion_control.workflow_events', 'UPDATE') "
            "OR has_table_privilege(%s, 'ingestion_control.workflow_events', 'DELETE') "
            "OR has_table_privilege(%s, 'ingestion_control.workflow_events', 'TRUNCATE')",
            (current_user, current_user, current_user),
        )
        excessive_grant_row = cur.fetchone()
        if excessive_grant_row is None:  # pragma: no cover - has_table_privilege renvoie toujours une ligne
            raise WorkerAttestationError("has_table_privilege query produced no row")
        (has_excessive_grant,) = excessive_grant_row

        cur.execute(
            "SELECT count(*) FROM pg_auth_members m "
            "WHERE m.member = (SELECT oid FROM pg_roles WHERE rolname = %s)",
            (current_user,),
        )
        membership_row = cur.fetchone()
        if membership_row is None:  # pragma: no cover - SELECT count(*) renvoie toujours une ligne
            raise WorkerAttestationError("membership count query produced no row")
        (membership_count,) = membership_row

    return RoleAttestation(
        current_user=current_user,
        is_superuser=is_superuser,
        can_create_db=can_create_db,
        can_create_role=can_create_role,
        can_replicate=can_replicate,
        can_bypass_rls=can_bypass_rls,
        owns_ingestion_control_schema=owns_schema,
        has_excessive_workflow_events_grant=has_excessive_grant,
        member_of_other_roles=membership_count > 0,
    )


def attest_runtime_role(conn: psycopg.Connection, *, expected_role: str) -> RoleAttestation:
    """Vérifie la politique de moindre privilège du rôle réellement utilisé
    par ``conn``. Lève ``WorkerAttestationError`` (jamais silencieux) à la
    première violation détectée — l'appelant doit refuser de démarrer."""
    attestation = _fetch_attestation(conn, expected_role=expected_role)

    if attestation.current_user != expected_role:
        raise WorkerAttestationError(
            f"current_user={attestation.current_user!r} does not match expected "
            f"runtime role {expected_role!r} — refusing to start with an unverified identity"
        )
    if attestation.is_superuser:
        raise WorkerAttestationError(
            f"role {attestation.current_user!r} is SUPERUSER — worker must never run "
            "with superuser privileges"
        )
    if attestation.can_create_db:
        raise WorkerAttestationError(
            f"role {attestation.current_user!r} has CREATEDB — excessive privilege for a worker"
        )
    if attestation.can_create_role:
        raise WorkerAttestationError(
            f"role {attestation.current_user!r} has CREATEROLE — excessive privilege for a worker"
        )
    if attestation.can_replicate:
        raise WorkerAttestationError(
            f"role {attestation.current_user!r} has REPLICATION — excessive privilege for a worker"
        )
    if attestation.can_bypass_rls:
        raise WorkerAttestationError(
            f"role {attestation.current_user!r} has BYPASSRLS — excessive privilege for a worker"
        )
    if attestation.owns_ingestion_control_schema:
        raise WorkerAttestationError(
            f"role {attestation.current_user!r} owns schema ingestion_control — schema "
            "ownership is reserved for the migration role, never the runtime role"
        )
    if attestation.has_excessive_workflow_events_grant:
        raise WorkerAttestationError(
            f"role {attestation.current_user!r} has UPDATE/DELETE/TRUNCATE on "
            "ingestion_control.workflow_events — violates the append-only invariant"
        )
    if attestation.member_of_other_roles:
        raise WorkerAttestationError(
            f"role {attestation.current_user!r} is a member of another role — a SET ROLE "
            "escalation path exists and must never be left in place"
        )

    return attestation


__all__ = ["RoleAttestation", "WorkerAttestationError", "attest_runtime_role"]
