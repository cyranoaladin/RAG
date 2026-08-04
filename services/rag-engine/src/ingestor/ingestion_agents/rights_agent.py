"""RightsAgent — détermine les droits d'un artefact (LOT44d).

Porte la transition ``CLASSIFIED -> RIGHTS_CHECKED``.

Règle déterministe minimale, explicitement documentée comme telle : ce
cœur n'analyse pas le texte réel d'une licence (pas de parseur de clauses),
il dérive une décision de ``profile.source_authority`` (déjà déclaré par le
profil, LOT44a) et de la présence d'une licence sur l'artefact. Ce n'est pas
une vérification juridique réelle — un futur lot qui introduirait une
analyse de licence réelle devra remplacer ``assess_rights_core`` sans
changer sa signature.

``CollectionProfile.reject_unknown_rights`` (défaut ``True``, LOT44a) est
appliqué ici : un résultat ``Rights.unknown`` fait échouer explicitement ce
stage si le profil l'exige — jamais une acceptation silencieuse.
"""
from __future__ import annotations

import psycopg
from nexus_contracts.document import Rights
from nexus_contracts.ingestion import ArtifactRecord, CollectionProfile
from nexus_contracts.resource_state import ResourceState

from ingestor.ingestion_agents.transitions import TransitionResult, apply_resource_transition


class UnknownRightsRejectedError(ValueError):
    """Les droits sont indéterminés et ``profile.reject_unknown_rights`` est
    vrai — rejet explicite, jamais un ``Rights.unknown`` propagé en silence
    vers les stages suivants."""


def assess_rights_core(*, artifact: ArtifactRecord, profile: CollectionProfile) -> Rights:
    """Dérive une décision de droits déterministe — aucune E/S.

    Aucune licence déclarée : toujours ``Rights.unknown``, quelle que soit
    l'autorité de la source (l'absence de licence est un fait sur
    l'artefact, jamais compensé par la réputation de la source).
    """
    if not artifact.license:
        rights = Rights.unknown
    elif profile.source_authority == "official":
        rights = Rights.officiel_public
    elif profile.source_authority == "authorized":
        rights = Rights.public_allowed
    else:
        rights = Rights.unknown

    if rights == Rights.unknown and profile.reject_unknown_rights:
        raise UnknownRightsRejectedError(
            f"artifact {artifact.artifact_id} resolved to Rights.unknown and "
            "profile.reject_unknown_rights is True — explicit rejection"
        )

    return rights


def run_rights_agent(
    conn: psycopg.Connection,
    *,
    artifact: ArtifactRecord,
    profile: CollectionProfile,
    expected_version: int,
    actor: str,
) -> tuple[Rights, TransitionResult]:
    """Calcule les droits (échec explicite si rejetés) puis transitionne
    ``CLASSIFIED -> RIGHTS_CHECKED``."""
    rights = assess_rights_core(artifact=artifact, profile=profile)

    transition = apply_resource_transition(
        conn,
        resource_id=artifact.resource_id,
        expected_state=ResourceState.CLASSIFIED,
        expected_version=expected_version,
        new_state=ResourceState.RIGHTS_CHECKED,
        actor=actor,
        run_id=artifact.run_id,
        payload={"rights_status": rights.value},
    )

    return rights, transition


__all__ = ["UnknownRightsRejectedError", "assess_rights_core", "run_rights_agent"]
