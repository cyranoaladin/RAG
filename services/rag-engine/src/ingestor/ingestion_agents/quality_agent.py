"""QualityAgent — calcule QualityReport et RoutingDecision (LOT44d, étendu LOT44f).

Porte la transition persistée ``RIGHTS_CHECKED -> QUALITY_CHECKED``, et
depuis LOT44f (ADR-0029), une seconde transition ``QUALITY_CHECKED ->
ROUTED`` — **uniquement** quand la ``RoutingDecision`` calculée vaut
``"ROUTE"``. Cette transition était déjà valide dans
``nexus_contracts.resource_state`` (LOT44a) mais jamais appliquée (LOT44d,
ADR-0027, Décision 3) : "la décision est retournée comme une valeur pure à
l'appelant". LOT44f active exactement ce cas, sans rien changer d'autre —
les autres décisions (``QUARANTINE``/``REJECT``/``DUPLICATE``) restent
purement calculées, non appliquées, exactement comme avant (activer leurs
transitions d'échappement respectives resterait une extension distincte,
hors périmètre de cette passe).

Toutes les heuristiques de qualité ci-dessous (``extraction_quality``,
``readability``, ``structure_score``, ``topic_coverage``, ``relevance_score``,
``metadata_quality``) sont des placeholders volontairement simples et
déterministes — **pas** un système de mesure de qualité pédagogique validé.
Un futur lot devra les remplacer par un vrai modèle avant toute utilisation
en décision de production réelle.
"""
from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

import psycopg
from nexus_contracts.document import Rights
from nexus_contracts.ingestion import (
    ArtifactRecord,
    CollectionProfile,
    QualityReport,
    RoutingDecision,
)
from nexus_contracts.resource_state import ResourceState

from .classifier import ConformityResult
from .transitions import TransitionResult, apply_resource_transition

_SENTENCE_BOUNDARY_PATTERN = re.compile(r"[.!?]")

#: Nombre de mots au-delà duquel le placeholder ``extraction_quality``/
#: ``readability`` sature à 1.0 — seuil arbitraire, documenté comme tel.
_QUALITY_SATURATION_WORD_COUNT = 100

#: Champs de métadonnées optionnels comptés par le placeholder
#: ``metadata_quality`` — mesure la complétude réelle des métadonnées
#: déclarées, pas une simple présence générique.
_OPTIONAL_METADATA_FIELDS = ("title", "publisher", "license", "pages_count", "version")


def _bounded_ratio(count: int, saturation: int) -> float:
    if saturation <= 0:
        return 0.0
    return min(1.0, count / saturation)


def build_quality_report_core(
    *,
    artifact: ArtifactRecord,
    profile: CollectionProfile,
    conformity: ConformityResult,
    rights: Rights,
    extracted_text: str,
    declared_language: str,
    pii_detected: bool,
    duplicate_detected: bool,
    report_id: UUID,
    evaluated_at: datetime,
) -> QualityReport:
    """Construit un ``QualityReport`` déterministe — aucune E/S, aucun modèle
    externe. ``pii_detected``/``duplicate_detected`` sont des constats déjà
    établis par l'appelant (aucun détecteur réel n'est construit ici)."""
    word_count = len(extracted_text.split())
    extraction_quality = _bounded_ratio(word_count, _QUALITY_SATURATION_WORD_COUNT)
    readability = extraction_quality
    sentence_count = len(_SENTENCE_BOUNDARY_PATTERN.findall(extracted_text))
    structure_score = _bounded_ratio(sentence_count, 5)

    expected_topics = profile.expected_topics
    topic_coverage = (
        len(conformity.matiere_evidence) / len(expected_topics) if expected_topics else 0.0
    )
    relevance_score = topic_coverage

    present_metadata = sum(
        1 for field in _OPTIONAL_METADATA_FIELDS if getattr(artifact, field, None)
    )
    metadata_quality = _bounded_ratio(present_metadata, len(_OPTIONAL_METADATA_FIELDS))

    rejection_reasons: list[str] = []
    if extraction_quality < profile.min_extraction_quality:
        rejection_reasons.append("extraction_quality_below_threshold")
    if not conformity.matiere_conformity:
        rejection_reasons.append("matiere_conformity_failed")
    if rights == Rights.unknown:
        rejection_reasons.append("rights_unknown")
    if pii_detected:
        rejection_reasons.append("pii_detected")
    if duplicate_detected:
        rejection_reasons.append("duplicate_detected")

    return QualityReport(
        report_id=report_id,
        resource_id=artifact.resource_id,
        run_id=artifact.run_id,
        scope=artifact.scope,
        extraction_quality=extraction_quality,
        readability=readability,
        language_detected=declared_language,
        structure_score=structure_score,
        niveau_conformity=conformity.niveau_conformity,
        voie_conformity=conformity.voie_conformity,
        matiere_conformity=conformity.matiere_conformity,
        programme_conformity=conformity.programme_conformity,
        topic_coverage=topic_coverage,
        relevance_score=relevance_score,
        pii_detected=pii_detected,
        duplicate_detected=duplicate_detected,
        metadata_quality=metadata_quality,
        rights_status=rights,
        rejection_reasons=rejection_reasons,
        evaluated_at=evaluated_at,
    )


def decide_routing_core(
    *,
    quality_report: QualityReport,
    profile: CollectionProfile,
    decision_id: UUID,
    decided_at: datetime,
) -> RoutingDecision:
    """Calcule une ``RoutingDecision`` déterministe à partir d'un
    ``QualityReport`` déjà produit — aucune E/S, aucune écriture d'état.

    Règle de priorité, appliquée dans cet ordre : doublon > PII > tout autre
    motif de rejet > acceptation. Jamais de repli implicite : chaque branche
    porte sa propre justification dans ``rules_applied``.
    """
    if quality_report.duplicate_detected:
        decision = "DUPLICATE"
        rules_applied = ["duplicate_detected"]
    elif quality_report.pii_detected:
        decision = "QUARANTINE"
        rules_applied = ["pii_detected"]
    elif quality_report.rejection_reasons:
        decision = "REJECT"
        rules_applied = ["has_rejection_reasons"]
    else:
        decision = "ROUTE"
        rules_applied = ["passed_all_checks"]

    return RoutingDecision(
        decision_id=decision_id,
        resource_id=quality_report.resource_id,
        run_id=quality_report.run_id,
        scope=quality_report.scope,
        decision=decision,
        confidence=quality_report.relevance_score,
        rules_applied=rules_applied,
        evidence=list(quality_report.rejection_reasons),
        errors=[],
        profile_version=profile.profile_version,
        agent_identity="QualityAgent",
        decided_at=decided_at,
    )


def run_quality_agent(
    conn: psycopg.Connection,
    *,
    artifact: ArtifactRecord,
    profile: CollectionProfile,
    conformity: ConformityResult,
    rights: Rights,
    extracted_text: str,
    declared_language: str,
    pii_detected: bool,
    duplicate_detected: bool,
    report_id: UUID,
    decision_id: UUID,
    evaluated_at: datetime,
    expected_version: int,
    actor: str,
    job_id: UUID | None = None,
) -> tuple[QualityReport, RoutingDecision, TransitionResult]:
    """Calcule le rapport qualité, transitionne
    ``RIGHTS_CHECKED -> QUALITY_CHECKED``, calcule la décision de routage,
    puis — uniquement si ``decision == "ROUTE"`` (LOT44f, ADR-0029) —
    applique une seconde transition ``QUALITY_CHECKED -> ROUTED``. Le
    ``TransitionResult`` retourné est toujours le dernier appliqué : celui
    de ``QUALITY_CHECKED`` si la décision n'est pas ``ROUTE``, celui de
    ``ROUTED`` sinon."""
    quality_report = build_quality_report_core(
        artifact=artifact,
        profile=profile,
        conformity=conformity,
        rights=rights,
        extracted_text=extracted_text,
        declared_language=declared_language,
        pii_detected=pii_detected,
        duplicate_detected=duplicate_detected,
        report_id=report_id,
        evaluated_at=evaluated_at,
    )

    transition = apply_resource_transition(
        conn,
        resource_id=artifact.resource_id,
        expected_state=ResourceState.RIGHTS_CHECKED,
        expected_version=expected_version,
        new_state=ResourceState.QUALITY_CHECKED,
        actor=actor,
        run_id=artifact.run_id,
        job_id=job_id,
        payload={"report_id": str(report_id), "rejection_reasons": quality_report.rejection_reasons},
    )

    routing_decision = decide_routing_core(
        quality_report=quality_report,
        profile=profile,
        decision_id=decision_id,
        decided_at=evaluated_at,
    )

    if routing_decision.decision == "ROUTE":
        transition = apply_resource_transition(
            conn,
            resource_id=artifact.resource_id,
            expected_state=ResourceState.QUALITY_CHECKED,
            expected_version=transition.state_version,
            new_state=ResourceState.ROUTED,
            actor=actor,
            run_id=artifact.run_id,
            job_id=job_id,
            payload={"decision_id": str(decision_id), "rules_applied": routing_decision.rules_applied},
        )

    return quality_report, routing_decision, transition


__all__ = [
    "build_quality_report_core",
    "decide_routing_core",
    "run_quality_agent",
]
