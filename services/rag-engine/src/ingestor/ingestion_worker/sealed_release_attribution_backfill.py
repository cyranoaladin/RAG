"""Rattrapage de l'attribution durable d'une release scellée déjà ingérée.

**Ce que ce module résout.** Les quatre faits d'attribution — ``source_label``,
``official``, ``source_kind``, ``type_doc`` — ont un foyer durable unique
depuis la migration 012, et la publication les y lit. Une release scellée
ingérée **avant** que son point d'entrée ne les écrive n'en porte aucun : ses
artefacts existent, ses attestations peuvent exister, et la publication
refuse — à raison, puisque rien de gouverné ne dit quel type documentaire
serait publié.

Réingérer n'est pas la réponse : les ressources, les runs et les événements
historiques acquis sont l'identité de cette release, et les remplacer ferait
perdre ce que la revue a couvert. Ce module **n'écrit que les attributions
manquantes**, dérivées des autorités de la release elle-même.

**D'où viennent les quatre faits.** Du catalogue d'artefacts de la release —
le fichier que le manifeste nomme, dont il déclare l'empreinte, et dont cette
empreinte (``artifacts_release_sha256``) est portée par l'artefact de revue
approuvé. Le type documentaire y est confronté au périmètre du profil
approuvé, et l'hôte de provenance à ses domaines autorisés, exactement comme
pour un type proposé par le chemin unitaire.

**Ce que ce module n'écrit jamais.** Aucune ressource, aucun candidat, aucun
artefact, aucun événement, aucune attestation, aucune ligne produit. Une
attribution déjà présente et identique est un no-op ; une attribution
présente et **divergente** est un refus, jamais un écrasement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import psycopg

from ingestor.ingestion_control.artifact_attribution import (
    ArtifactAttributionError,
    derive_sealed_release_artifact_attribution,
    load_artifact_attribution,
    persist_artifact_attribution,
)
from ingestor.ingestion_control.provisioning import SEALED_RELEASE_PIPELINE
from ingestor.ingestion_profiles.registry import ProfileRegistry

from .sealed_release_ingestion import SealedReleaseFacts


class AttributionBackfillError(RuntimeError):
    """Le rattrapage ne peut pas établir ce qu'il écrirait — refus."""


@dataclass
class AttributionBackfillReport:
    """Le compte rendu — mesuré ligne à ligne, jamais déduit de la release."""

    release_id: str
    examined: int = 0
    written: int = 0
    already_present: int = 0
    missing_rows: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "pipeline_kind": SEALED_RELEASE_PIPELINE,
            "examined": self.examined,
            "written": self.written,
            "already_present": self.already_present,
            "missing_rows": list(self.missing_rows),
        }


def _lignes_de_la_release(
    conn: psycopg.Connection, *, release_id: str
) -> dict[tuple[str, str], tuple[UUID, UUID]]:
    """Les artefacts scellés de CETTE release, indexés par (collection, sha).

    La sélection est celle du plan de contrôle — ``pipeline_kind`` durable et
    identité de release portée par le payload — jamais une liste fournie par
    l'appelant.
    """
    lignes = conn.execute(
        "SELECT r.collection, a.sha256, a.artifact_id, a.run_id"
        "  FROM ingestion_control.resources r"
        "  JOIN ingestion_control.artifacts a USING (resource_id)"
        " WHERE r.pipeline_kind = %s"
        "   AND a.payload->>'release_id' = %s",
        (SEALED_RELEASE_PIPELINE, release_id),
    ).fetchall()
    indexees: dict[tuple[str, str], tuple[UUID, UUID]] = {}
    for collection, sha256, artifact_id, run_id in lignes:
        cle = (str(collection), str(sha256))
        if cle in indexees:
            raise AttributionBackfillError(
                f"release {release_id!r} carries two sealed artifacts for "
                f"{cle} — which one the attribution describes cannot be decided"
            )
        indexees[cle] = (artifact_id, run_id)
    return indexees


def backfill_sealed_release_attributions(
    conn: psycopg.Connection,
    *,
    facts: SealedReleaseFacts,
    profile_registry: ProfileRegistry,
    owner: str,
) -> AttributionBackfillReport:
    """Établit les attributions manquantes des artefacts déjà ingérés.

    Ne committe pas : la transaction appartient à l'appelant, comme pour
    toutes les primitives ``ingestion_control``.
    """
    rapport = AttributionBackfillReport(release_id=facts.release_id)
    lignes = _lignes_de_la_release(conn, release_id=facts.release_id)

    for placement in facts.placements:
        rapport.examined += 1
        cle = (placement.collection, placement.artifact_id)
        trouvee = lignes.get(cle)
        if trouvee is None:
            # Un placement de la release qui n'a pas de ligne ingérée n'est
            # pas rattrapable ici : c'est une ingestion qui manque, pas une
            # attribution. Le dire, ne pas l'inventer.
            rapport.missing_rows.append(f"{placement.collection}/{placement.artifact_id}")
            continue
        artifact_id, run_id = trouvee

        profil = profile_registry[
            (placement.collection, facts.profile_versions[placement.collection])
        ]
        attribution = derive_sealed_release_artifact_attribution(
            ingestion_artifact_id=artifact_id,
            catalog_entry={
                "type_doc": placement.type_doc,
                "source_url": placement.provenance_url,
            },
            profile=profil,
        )
        try:
            existante, _digest = load_artifact_attribution(
                conn, ingestion_artifact_id=artifact_id
            )
        except ArtifactAttributionError:
            existante = None
        if existante is not None:
            if existante != attribution:
                raise AttributionBackfillError(
                    f"artifact {artifact_id} already carries an attribution that "
                    f"differs from the one this release establishes — refusing "
                    f"rather than overwriting (stored={existante!r})"
                )
            rapport.already_present += 1
            continue

        persist_artifact_attribution(
            conn, attribution=attribution, run_id=run_id, actor=owner
        )
        rapport.written += 1

    return rapport


__all__ = [
    "AttributionBackfillError",
    "AttributionBackfillReport",
    "backfill_sealed_release_attributions",
]
