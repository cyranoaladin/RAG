"""Projection des faits d'une release scellée — SEALED-RELEASE-PROJECTION-V1.

Chaque fait porte son ORIGINE. Rien n'est comblé par une valeur de
convenance : ce qui n'est ni établi ni dérivable est déclaré ``NON_ETABLI``,
figure dans ``unresolved_conditions`` et **empêche** la porte de publication
d'être franchie.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg

from ingestor.ingestion_control.sealed_evidence import (
    PII_CLEARED,
    PII_DETECTED_REVIEWED_ACCEPTED,
    PIIClearance,
    SealedEvidenceError,
)
from ingestor.multilevel_evidence import (
    PRODUCT_CURRENTNESS_BY_DISPOSITION,
    MultilevelCurrentnessArtifact,
)

PROJECTION_VERSION = "SEALED-RELEASE-PROJECTION-V1"
QUALITY_PREDICATE_VERSION = "BATCH-TECHNICAL-QUALITY-V1"
GATE_NAME = "sealed_release_publication_gate"

FAIT_HISTORIQUE = "FAIT_HISTORIQUE"
DERIVATION = "DERIVATION"
EVALUATION = "EVALUATION"
NON_ETABLI = "NON_ETABLI"

#: Ce que la porte admet, et rien d'autre (ADR-0059). Un instantané officiel
#: est publiable sans jamais devenir `current` ; une détection PII admise
#: après revue humaine reste une détection.
ACTUALITES_PUBLIABLES = frozenset(PRODUCT_CURRENTNESS_BY_DISPOSITION.values())
PII_PUBLIABLES = frozenset({PII_CLEARED, PII_DETECTED_REVIEWED_ACCEPTED})


class SealedReleaseProjectionError(RuntimeError):
    """Refus explicite — jamais un contournement."""


@dataclass(frozen=True)
class DimensionProjetee:
    """Un fait, sa valeur et d'où il vient."""

    valeur: Any
    origine: str
    source: str
    digest: str = "0" * 64

    def est_etablie(self) -> bool:
        return self.origine != NON_ETABLI


@dataclass
class ProjectionRow:
    resource_id: UUID
    artifact_id: UUID
    content_sha256: str
    collection: str
    scope_authorization_id: str
    droits: DimensionProjetee
    qualite: DimensionProjetee
    actualite: DimensionProjetee
    pii: DimensionProjetee
    gate_evaluator: str
    gate_evaluated_at: datetime
    unresolved: list[str] = field(default_factory=list)

    @property
    def gate_passed(self) -> bool:
        """La porte n'est franchie que si TOUTE condition obligatoire est
        établie **et** positive.

        Une condition négative bloque autant qu'une condition inconnue :
        l'absence de ``NON_ETABLI`` ne signifie pas que tout est satisfait.
        """
        if self.unresolved:
            return False
        return (
            self.droits.valeur not in (None, "", "unknown")
            and self.qualite.valeur is True
            and self.actualite.origine == DERIVATION
            and self.actualite.valeur in ACTUALITES_PUBLIABLES
            and self.pii.origine == DERIVATION
            and self.pii.valeur in PII_PUBLIABLES
        )


def _conditions_non_resolues(ligne: ProjectionRow) -> list[str]:
    """Les dimensions inconnues **et** les dimensions négatives.

    Les deux bloquent. Seules les inconnues sont listées ici, car le schéma
    exige qu'une dimension ``NON_ETABLI`` y figure ; une dimension établie
    mais négative est bloquée par ``gate_passed``.
    """
    manquantes = []
    for nom, dimension in (
        ("rights", ligne.droits), ("quality", ligne.qualite),
        ("currentness", ligne.actualite), ("pii", ligne.pii),
    ):
        if not dimension.est_etablie():
            manquantes.append(nom)
    return sorted(manquantes)


def _digest_projection(ligne: ProjectionRow, *, release_id: str) -> str:
    """Identité du CONTENU projeté — deux projections identiques ont le même
    digest, et un rejeu strictement identique est donc reconnaissable."""
    document = {
        "projection_version": PROJECTION_VERSION,
        "release_id": release_id,
        "resource_id": str(ligne.resource_id),
        "artifact_id": str(ligne.artifact_id),
        "content_sha256": ligne.content_sha256,
        "collection": ligne.collection,
        "scope_authorization_id": ligne.scope_authorization_id,
        "rights": [ligne.droits.valeur, ligne.droits.origine, ligne.droits.source],
        "quality": [ligne.qualite.valeur, ligne.qualite.origine,
                    ligne.qualite.digest],
        "currentness": [ligne.actualite.valeur, ligne.actualite.origine],
        "pii": [ligne.pii.valeur, ligne.pii.origine, ligne.pii.digest],
        "unresolved": ligne.unresolved,
        "gate_passed": ligne.gate_passed,
    }
    return hashlib.sha256(
        json.dumps(document, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def persist_projection(
    conn: psycopg.Connection,
    *,
    facts: Any,
    lignes: list[ProjectionRow],
) -> tuple[int, int]:
    """Écrit la projection. Rend ``(ecrites, deja_presentes)``.

    Un rejeu **strictement identique** est reconnu sans duplication : la
    ligne existante porte le même digest. Une même identité portant un
    contenu différent lève un conflit — jamais un écrasement, la table
    étant append-only.
    """
    ecrites = deja = 0
    for ligne in lignes:
        ligne.unresolved = _conditions_non_resolues(ligne)
        digest = _digest_projection(ligne, release_id=facts.release_id)
        existante = conn.execute(
            "SELECT projection_digest FROM ingestion_control.sealed_release_projections"
            " WHERE release_id = %s AND resource_id = %s AND artifact_id = %s"
            "   AND projection_version = %s",
            (facts.release_id, ligne.resource_id, ligne.artifact_id,
             PROJECTION_VERSION),
        ).fetchone()
        if existante is not None:
            if existante[0] != digest:
                raise SealedReleaseProjectionError(
                    f"projection {PROJECTION_VERSION} already exists for resource "
                    f"{ligne.resource_id} with digest {existante[0][:16]}…, but "
                    f"the new one is {digest[:16]}… — this is a conflict, and "
                    "the recorded past is never overwritten. A correction is a "
                    "new projection version."
                )
            deja += 1
            continue
        conn.execute(
            """
            INSERT INTO ingestion_control.sealed_release_projections (
                projection_id, projection_version, release_id,
                release_manifest_sha256, artifacts_release_sha256,
                candidate_inventory_sha256, artifact_transfer_manifest_sha256,
                resource_id, artifact_id, content_sha256, collection,
                scope_authorization_id,
                rights_status, rights_decision_id, rights_registry_sha256,
                rights_origin,
                quality_passed, quality_report_digest, quality_predicate_version,
                quality_origin,
                currentness, currentness_origin,
                pii_status, pii_evidence_sha256, pii_origin,
                gate_passed, gate_name, gate_evaluator, gate_evaluated_at,
                unresolved_conditions, projection_digest
            ) VALUES (
                %(projection_id)s, %(projection_version)s, %(release_id)s,
                %(release_manifest_sha256)s, %(artifacts_release_sha256)s,
                %(candidate_inventory_sha256)s, %(artifact_transfer_manifest_sha256)s,
                %(resource_id)s, %(artifact_id)s, %(content_sha256)s, %(collection)s,
                %(scope_authorization_id)s,
                %(rights_status)s, %(rights_decision_id)s, %(rights_registry_sha256)s,
                %(rights_origin)s,
                %(quality_passed)s, %(quality_report_digest)s,
                %(quality_predicate_version)s, %(quality_origin)s,
                %(currentness)s, %(currentness_origin)s,
                %(pii_status)s, %(pii_evidence_sha256)s, %(pii_origin)s,
                %(gate_passed)s, %(gate_name)s, %(gate_evaluator)s,
                %(gate_evaluated_at)s,
                %(unresolved_conditions)s, %(projection_digest)s
            )
            """,
            {
                "projection_id": uuid4(),
                "projection_version": PROJECTION_VERSION,
                "release_id": facts.release_id,
                "release_manifest_sha256": facts.release_manifest_sha256,
                "artifacts_release_sha256": facts.artifacts_release_sha256,
                "candidate_inventory_sha256": facts.candidate_inventory_sha256,
                "artifact_transfer_manifest_sha256":
                    facts.artifact_transfer_manifest_sha256,
                "resource_id": ligne.resource_id,
                "artifact_id": ligne.artifact_id,
                "content_sha256": ligne.content_sha256,
                "collection": ligne.collection,
                "scope_authorization_id": ligne.scope_authorization_id,
                "rights_status": str(ligne.droits.valeur),
                "rights_decision_id": ligne.droits.source,
                "rights_registry_sha256": ligne.droits.digest,
                "rights_origin": ligne.droits.origine,
                "quality_passed": bool(ligne.qualite.valeur),
                "quality_report_digest": ligne.qualite.digest,
                "quality_predicate_version": QUALITY_PREDICATE_VERSION,
                "quality_origin": ligne.qualite.origine,
                "currentness": str(ligne.actualite.valeur),
                "currentness_origin": ligne.actualite.origine,
                "pii_status": str(ligne.pii.valeur),
                "pii_evidence_sha256": ligne.pii.digest,
                "pii_origin": ligne.pii.origine,
                "gate_passed": ligne.gate_passed,
                "gate_name": GATE_NAME,
                "gate_evaluator": ligne.gate_evaluator,
                # La date REELLE de cette evaluation. Jamais antidatee, jamais
                # presentee comme une transition historique retrouvee.
                "gate_evaluated_at": ligne.gate_evaluated_at,
                "unresolved_conditions": ligne.unresolved,
                "projection_digest": digest,
            },
        )
        ecrites += 1
    return ecrites, deja


def load_applicable_projection(
    conn: psycopg.Connection,
    *,
    release_id: str,
    resource_id: UUID,
    artifact_id: UUID,
    projection_version: str = PROJECTION_VERSION,
) -> Mapping[str, Any]:
    """Relit LA projection nommée — jamais « la plus récente ».

    Une nouvelle version append-only ne doit pas remplacer silencieusement
    celle que la revue a couverte : la version est donc un paramètre, pas
    une déduction.
    """
    ligne = conn.execute(
        "SELECT rights_status, rights_decision_id, rights_registry_sha256,"
        "       rights_origin, quality_passed, quality_report_digest,"
        "       quality_origin, currentness, currentness_origin, pii_status,"
        "       pii_evidence_sha256, pii_origin, gate_passed, gate_name,"
        "       gate_evaluated_at, unresolved_conditions, projection_digest,"
        "       collection, scope_authorization_id, content_sha256"
        "  FROM ingestion_control.sealed_release_projections"
        " WHERE release_id = %s AND resource_id = %s AND artifact_id = %s"
        "   AND projection_version = %s",
        (release_id, resource_id, artifact_id, projection_version),
    ).fetchone()
    if ligne is None:
        raise SealedReleaseProjectionError(
            f"no {projection_version} projection for resource {resource_id} in "
            f"release {release_id!r} — the facts it would carry are not "
            "established, and nothing may be published from them"
        )
    colonnes = (
        "rights_status", "rights_decision_id", "rights_registry_sha256",
        "rights_origin", "quality_passed", "quality_report_digest",
        "quality_origin", "currentness", "currentness_origin", "pii_status",
        "pii_evidence_sha256", "pii_origin", "gate_passed", "gate_name",
        "gate_evaluated_at", "unresolved_conditions", "projection_digest",
        "collection", "scope_authorization_id", "content_sha256",
    )
    return dict(zip(colonnes, ligne, strict=True))


def require_projection_authorises(projection: Mapping[str, Any], *, resource_id: UUID) -> None:
    """Une projection consultable n'autorise rien par elle-même."""
    if projection["unresolved_conditions"]:
        raise SealedReleaseProjectionError(
            f"resource {resource_id} carries unresolved condition(s) "
            f"{projection['unresolved_conditions']!r} — the projection is "
            "readable, the publication is not authorised"
        )
    if not projection["gate_passed"]:
        raise SealedReleaseProjectionError(
            f"resource {resource_id}: the publication gate was evaluated and "
            "did NOT pass — a negative condition blocks as much as an unknown one"
        )


def now_utc() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "DERIVATION",
    "DimensionProjetee",
    "EVALUATION",
    "FAIT_HISTORIQUE",
    "GATE_NAME",
    "NON_ETABLI",
    "PROJECTION_VERSION",
    "QUALITY_PREDICATE_VERSION",
    "ProjectionRow",
    "SealedReleaseProjectionError",
    "load_applicable_projection",
    "now_utc",
    "persist_projection",
    "require_projection_authorises",
]


# ---------------------------------------------------------------------------
# Dérivation depuis les autorités scellées
# ---------------------------------------------------------------------------


def _digest_qualite(entree: Mapping[str, Any], conditions: Mapping[str, bool]) -> str:
    """Empreinte du rapport de qualité TECHNIQUE réellement évalué.

    Ce n'est pas un score : c'est l'empreinte des conditions mesurées et de
    leur résultat, pour que le rapport soit relisable et comparable.
    """
    document = {
        "predicate_version": QUALITY_PREDICATE_VERSION,
        "content_sha256": entree.get("content_sha256"),
        "page_count": entree.get("page_count"),
        "chunk_id_set_digest": entree.get("chunk_id_set_digest"),
        "chunk_sha256_set_digest": entree.get("chunk_sha256_set_digest"),
        "conditions": dict(sorted(conditions.items())),
    }
    return hashlib.sha256(
        json.dumps(document, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def derive_quality(entree: Mapping[str, Any]) -> DimensionProjetee:
    """Le prédicat de qualité technique du batch, sur ce que le pré-vol MESURE.

    Lisibilité, pertinence documentaire, couverture thématique et exactitude
    des citations ne sont **pas** établies ici : elles relèvent des recettes.
    Aucun score n'est inventé pour les remplir.
    """
    chunks = entree.get("chunks") or []
    pages = entree.get("page_count")
    ignorees = set(entree.get("ignored_empty_pages") or [])
    conditions = {
        "extraction_reussie": bool(pages) and bool(chunks),
        "aucun_chunk_vide": all(
            (c.get("character_count") or 0) > 0 for c in chunks
        ),
        "pagination_coherente": all(
            1 <= c.get("page_start", 0) <= c.get("page_end", 0) <= (pages or 0)
            for c in chunks
        ),
        "couverture_des_pages": (
            {n for c in chunks
             for n in range(c.get("page_start", 1), c.get("page_end", 0) + 1)}
            | ignorees
        ) >= set(range(1, (pages or 0) + 1)),
    }
    digest = _digest_qualite(entree, conditions)
    if all(conditions.values()):
        return DimensionProjetee(
            valeur=True, origine=DERIVATION,
            source=f"preflight_evidence/{QUALITY_PREDICATE_VERSION}", digest=digest,
        )
    echouees = sorted(nom for nom, tenue in conditions.items() if not tenue)
    return DimensionProjetee(
        valeur=False, origine=EVALUATION,
        source=f"preflight_evidence:{','.join(echouees)}", digest=digest,
    )


def derive_currentness(
    actualite: MultilevelCurrentnessArtifact | None, *, evidence_sha256: str
) -> DimensionProjetee:
    """L'actualité vient de sa propre autorité, jamais du succès d'une autre.

    Elle reçoit la disposition que le chargeur canonique a VÉRIFIÉE
    (``load_multilevel_currentness``), jamais une déclaration brute : une
    ligne qui se dirait « CURRENT » sans passer ce chargeur ne dirait rien.
    Un instantané officiel se projette ``official_snapshot`` et jamais
    ``current`` (ADR-0059).
    """
    if actualite is None:
        return DimensionProjetee(
            valeur="unknown", origine=NON_ETABLI,
            source="currentness_evidence: aucune entree pour ce contenu",
            digest=evidence_sha256,
        )
    produit = actualite.product_currentness
    if produit is not None:
        return DimensionProjetee(
            valeur=produit, origine=DERIVATION,
            source=f"currentness_evidence:{actualite.disposition}",
            digest=evidence_sha256,
        )
    return DimensionProjetee(
        valeur=actualite.decision, origine=EVALUATION,
        source=f"currentness_evidence:{actualite.disposition}",
        digest=evidence_sha256,
    )


def derive_pii(
    clairance: PIIClearance | SealedEvidenceError | None, *, evidence_sha256: str
) -> DimensionProjetee:
    """La PII est une dimension distincte des droits.

    Elle reçoit la clairance que ``VerifiedPIIEvidenceRegistry`` a rendue —
    ensemble de décisions, reçu et ancre vérifiés — ou le refus qu'il a
    opposé. Une admission après revue reste ``DETECTED_REVIEWED_ACCEPTED`` :
    elle n'efface jamais la détection (ADR-0047). Elle ne produit jamais un
    ``rights_status``.
    """
    if clairance is None:
        return DimensionProjetee(
            valeur="unknown", origine=NON_ETABLI,
            source="pii_evidence: aucune entree pour ce contenu",
            digest=evidence_sha256,
        )
    if isinstance(clairance, SealedEvidenceError):
        return DimensionProjetee(
            valeur="REFUSED", origine=EVALUATION,
            source=f"pii_evidence: {clairance}"[:500],
            digest=evidence_sha256,
        )
    if clairance.status == PII_CLEARED:
        return DimensionProjetee(
            valeur=PII_CLEARED, origine=DERIVATION,
            source="pii_evidence/REAL_CORPUS_PII_SCAN", digest=evidence_sha256,
        )
    if clairance.is_reviewed_accepted and clairance.decision_set_id:
        return DimensionProjetee(
            valeur=PII_DETECTED_REVIEWED_ACCEPTED, origine=DERIVATION,
            source=f"pii_review_decisions/{clairance.decision_set_id}",
            digest=evidence_sha256,
        )
    return DimensionProjetee(
        valeur=clairance.status, origine=EVALUATION,
        source=f"pii_evidence: status={clairance.status!r}",
        digest=evidence_sha256,
    )
