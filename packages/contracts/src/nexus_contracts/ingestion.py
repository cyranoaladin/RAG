"""Contrats canoniques du moteur d'ingestion agentique (LOT44a).

Périmètre strict : modèles de données uniquement (aucune migration, aucun
worker, aucun agent, aucun endpoint, aucun comportement d'ingestion — cf.
docs/reports/lot_43_rag_engine_p1_hardening.md et les décisions LOT44a
validées en amont).

Invariants portés par ce module :
- ``ResourceScope`` est obligatoire et fail-closed sur chaque modèle qui le
  porte : aucun champ n'a de valeur par défaut, une instanciation
  incomplète échoue à la construction plutôt que de deviner une valeur.
- Les identifiants d'exécution (``run_id``, ``*_id``) sont des UUID. Les
  hash déterministes (``dedup_key``, ``sha256``) sont réservés à la
  déduplication, l'idempotence et le rattachement contrôlé de versions —
  jamais utilisés comme identifiant primaire.
- ``PublicationPolicy.auto_publish`` est verrouillé au type ``Literal[False]``
  : l'auto-publication n'est pas seulement désactivée par défaut, elle est
  structurellement irreprésentable comme activée en LOT44a.
- Aucun de ces modèles ne référence un état ou un champ de publication —
  cf. ``nexus_contracts.resource_state`` pour la machine d'état complète.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from nexus_contracts.chunk import Audience
from nexus_contracts.document import Candidat, Niveau, Rights, StrictBaseModel, TypeDoc, Voie
from nexus_contracts.identity import BoundedSlug, CollectionName, SchoolYear, Sha256Digest
from nexus_contracts.scope import ProgrammeVersion

Visibility = Literal["public", "internal", "restricted", "private"]


class ResourceScope(StrictBaseModel):
    """Scope gouverné complet — obligatoire et fail-closed.

    Reprend exactement les dix dimensions de scope déjà gouvernées côté
    rag-engine (colonnes ``rag_chunks`` introduites en LOT41,
    ``services/rag-engine/infra/postgres/migrations/003_profile_filtering.sql``).
    Aucun champ n'a de valeur par défaut : un scope incomplet ne peut pas
    être construit, jamais deviné silencieusement.
    """

    tenant: BoundedSlug
    collection: CollectionName
    niveau: Niveau
    voie: Voie
    matiere: BoundedSlug
    candidat: Candidat
    audience: list[Audience] = Field(min_length=1)
    visibility: Visibility
    school_year: SchoolYear
    programme_version: ProgrammeVersion

    @field_validator("audience")
    @classmethod
    def validate_audience_no_duplicates(cls, values: list[Audience]) -> list[Audience]:
        if len(values) != len(set(values)):
            raise ValueError("audience cannot contain duplicates")
        return values

    @field_validator("school_year")
    @classmethod
    def validate_school_year_is_consecutive(cls, value: str) -> str:
        start, end = (int(part) for part in value.split("-"))
        if end != start + 1:
            raise ValueError("school_year must use the form YYYY-YYYY+1")
        return value


class PublicationPolicy(StrictBaseModel):
    """Politique de publication d'une collection — verrouillée en LOT44a.

    ``auto_publish`` est typé ``Literal[False]`` : ce n'est pas une valeur
    par défaut contournable, c'est une garantie structurelle que
    l'auto-publication ne peut pas être activée par ce contrat tant que le
    sous-système de publication n'existe pas.
    """

    mode: Literal["human_review"] = "human_review"
    auto_publish: Literal[False] = False


class CollectionProfile(StrictBaseModel):
    """Profil déclaratif complet d'une collection gouvernée."""

    profile_version: str = Field(min_length=1)
    enabled: bool
    scope: ResourceScope

    title: str = Field(min_length=1)
    language: str = "fr"
    owner: str = Field(min_length=1)

    expected_topics: list[str] = Field(min_length=1)
    expected_resource_types: list[TypeDoc] = Field(min_length=1)
    excluded_topics: list[str] = Field(default_factory=list)

    allowed_domains: list[str] = Field(min_length=1)
    seed_urls: list[str] = Field(default_factory=list)
    source_authority: Literal["official", "authorized", "unknown"]

    search_cadence: Literal["daily", "weekly", "monthly", "manual"]
    max_queries_per_run: int = Field(gt=0)
    max_documents_per_run: int = Field(gt=0)

    max_chunk_size: int = Field(gt=0)
    chunk_overlap: int = Field(ge=0)

    min_source_confidence: float = Field(ge=0, le=1)
    min_scope_confidence: float = Field(ge=0, le=1)
    min_extraction_quality: float = Field(ge=0, le=1)
    reject_unknown_rights: bool = True
    reject_ambiguous_routing: bool = True

    publication: PublicationPolicy = Field(default_factory=PublicationPolicy)

    @field_validator("expected_topics")
    @classmethod
    def validate_expected_topics_are_non_blank(cls, values: list[str]) -> list[str]:
        """Remédiation revue PR#90 (Cubic P1) : ``expected_topics: [""]``
        (ou une entrée uniquement faite d'espaces) ferait accepter
        n'importe quel document comme conforme à la matière — le
        classifier (``classify_conformity_core``) considère une chaîne
        vide comme présente dans tout texte non vide. ``min_length=1`` sur
        la liste ne protège pas contre une chaîne vide *à l'intérieur* de
        la liste."""
        for topic in values:
            if not topic.strip():
                raise ValueError("expected_topics entries must not be blank")
        return values

    @model_validator(mode="after")
    def validate_chunk_overlap_smaller_than_chunk_size(self) -> "CollectionProfile":
        if self.chunk_overlap >= self.max_chunk_size:
            raise ValueError("chunk_overlap must be strictly smaller than max_chunk_size")
        return self


class SearchPlan(StrictBaseModel):
    """Plan de recherche généré pour une collection, justifié requête par requête."""

    search_plan_id: UUID
    run_id: UUID
    scope: ResourceScope

    generated_at: datetime
    profile_version: str = Field(min_length=1)

    gap_targets: list[str] = Field(default_factory=list)
    queries: list[str] = Field(min_length=1)
    allowed_domains: list[str] = Field(min_length=1)
    required_resource_types: list[TypeDoc] = Field(default_factory=list)
    required_topics: list[str] = Field(default_factory=list)
    excluded_topics: list[str] = Field(default_factory=list)
    max_results: int = Field(gt=0)
    reason: str = Field(min_length=1)


class ResourceCandidate(StrictBaseModel):
    """Candidat de ressource découvert, toujours rattaché à une ressource.

    ``resource_id`` est obligatoire : LOT44a crée la ressource provisoire de
    façon atomique dès l'acceptation du candidat (même transaction), donc
    aucun ``ResourceCandidate`` ne peut exister sans ressource rattachée.
    Ce modèle ne porte volontairement pas de champ de statut propre — son
    état est entièrement représenté par ``resource_state`` (rattaché via
    ``resource_id``), pour préserver un gate d'état unique.
    """

    candidate_id: UUID
    resource_id: UUID
    run_id: UUID
    scope: ResourceScope

    discovered_at: datetime
    source_url: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    proposed_type_doc: TypeDoc
    title: str | None = None
    publisher: str | None = None
    language: str = "fr"
    relevance_evidence: list[str] = Field(default_factory=list)

    dedup_key: Sha256Digest


class ArtifactRecord(StrictBaseModel):
    """Artefact téléchargé et son empreinte — ancre de déduplication/version."""

    artifact_id: UUID
    resource_id: UUID
    run_id: UUID
    scope: ResourceScope

    sha256: Sha256Digest
    size_bytes: int = Field(ge=0)
    mime_declared: str = Field(min_length=1)
    mime_detected: str = Field(min_length=1)
    original_url: str = Field(min_length=1)
    final_url: str = Field(min_length=1)
    collected_at: datetime
    domain: str = Field(min_length=1)
    publisher: str | None = None
    title: str | None = None
    license: str | None = None
    rights_status: Rights
    pages_count: int | None = Field(default=None, ge=0)
    version: str | None = None
    extracted_text_ref: str | None = None


class RoutingDecision(StrictBaseModel):
    """Décision de routage — validée côté serveur, jamais devinée."""

    decision_id: UUID
    resource_id: UUID
    run_id: UUID
    scope: ResourceScope

    decision: Literal["ROUTE", "QUARANTINE", "REJECT", "DUPLICATE", "SUPERSEDED"]
    confidence: float = Field(ge=0, le=1)
    rules_applied: list[str] = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    profile_version: str = Field(min_length=1)
    agent_identity: str = Field(min_length=1)
    decided_at: datetime


class QualityReport(StrictBaseModel):
    """Rapport qualité borné [0, 1] par dimension."""

    report_id: UUID
    resource_id: UUID
    run_id: UUID
    scope: ResourceScope

    extraction_quality: float = Field(ge=0, le=1)
    readability: float = Field(ge=0, le=1)
    language_detected: str = Field(min_length=1)
    structure_score: float = Field(ge=0, le=1)
    niveau_conformity: bool
    voie_conformity: bool
    matiere_conformity: bool
    programme_conformity: bool
    topic_coverage: float = Field(ge=0, le=1)
    relevance_score: float = Field(ge=0, le=1)
    pii_detected: bool
    duplicate_detected: bool
    metadata_quality: float = Field(ge=0, le=1)
    rights_status: Rights
    rejection_reasons: list[str] = Field(default_factory=list)
    evaluated_at: datetime


class IngestionRun(StrictBaseModel):
    """Run d'ingestion — s'arrête à ``resources_retrieval_eligible``.

    Aucun compteur ``resources_published`` : la publication produit est hors
    périmètre de LOT44a (cf. ``nexus_contracts.resource_state``).
    """

    run_id: UUID
    scope: ResourceScope
    profile_version: str = Field(min_length=1)
    trigger: Literal["scheduled", "manual"]
    mode: Literal["auto_stage"] = "auto_stage"
    status: Literal["planned", "running", "succeeded", "failed", "partial", "cancelled"] = "planned"

    started_at: datetime | None = None
    finished_at: datetime | None = None

    jobs_total: int = Field(default=0, ge=0)
    resources_discovered: int = Field(default=0, ge=0)
    resources_fetched: int = Field(default=0, ge=0)
    resources_accepted: int = Field(default=0, ge=0)
    resources_rejected: int = Field(default=0, ge=0)
    resources_quarantined: int = Field(default=0, ge=0)
    resources_needs_review: int = Field(default=0, ge=0)
    resources_retrieval_eligible: int = Field(default=0, ge=0)

    errors: list[str] = Field(default_factory=list)
    code_version: str | None = None

    @model_validator(mode="after")
    def validate_finished_at_after_started_at(self) -> "IngestionRun":
        if (
            self.started_at is not None
            and self.finished_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValueError("finished_at cannot precede started_at")
        return self


class CoverageSnapshot(StrictBaseModel):
    """Instantané de couverture thématique d'une collection sur une période."""

    snapshot_id: UUID
    scope: ResourceScope

    period_start: datetime
    period_end: datetime

    expected_topics: list[str] = Field(min_length=1)
    covered_topics: list[str] = Field(default_factory=list)
    insufficient_topics: list[str] = Field(default_factory=list)
    resources_per_topic: dict[str, int] = Field(default_factory=dict)
    average_quality: float | None = Field(default=None, ge=0, le=1)
    stale_resources: int = Field(default=0, ge=0)
    gaps: list[str] = Field(default_factory=list)
    recommended_next_queries: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_period_end_after_period_start(self) -> "CoverageSnapshot":
        if self.period_end < self.period_start:
            raise ValueError("period_end cannot precede period_start")
        return self


__all__ = [
    "ArtifactRecord",
    "CollectionProfile",
    "CoverageSnapshot",
    "IngestionRun",
    "PublicationPolicy",
    "QualityReport",
    "ResourceCandidate",
    "ResourceScope",
    "RoutingDecision",
    "SearchPlan",
    "Visibility",
]
