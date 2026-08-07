"""Contrat LOT41A — autorisation de scope d'ingestion (ADR-0032).

Ce module définit la **forme** d'une autorisation de scope, jamais son
octroi. Aucune fonction de ce module ne déclare, ne construit ni ne valide
une autorisation comme réellement accordée — cette responsabilité relève
exclusivement de `ingestor.ingestion_control.scope_authority`
(``rag-engine``), qui revérifie systématiquement l'évidence GitHub
embarquée avant tout usage (ADR-0032 § 4). ``ScopeAuthorization`` n'est
qu'une structure de données transportant ce qu'une autorisation *prétend*
être — jamais une preuve de validité en elle-même.

Aucun champ de confiance figé (``approved``, ``valid``) n'existe ici,
délibérément : la validité n'est jamais un booléen stocké, toujours
recalculée en direct contre GitHub au moment de l'usage.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, StrictStr, model_validator

from nexus_contracts.document import StrictBaseModel
from nexus_contracts.ingestion import ResourceScope
from nexus_contracts.identity import CollectionName

#: Seule valeur acceptée — jamais un texte libre (ADR-0032 § 2).
AUTHORIZE_INGESTION_SCOPE_DECISION = "AUTHORIZE_INGESTION_SCOPE"


class GitHubApprovalEvidence(StrictBaseModel):
    """Évidence d'approbation humaine GitHub — mêmes champs que le readback
    du check ``Evaluate trusted human review`` (ADR-0025/LOT41V), jamais une
    structure parallèle inventée. Revérifiée en direct à chaque usage, pas
    seulement lue telle quelle."""

    repository: StrictStr = Field(min_length=1)
    pull_request: StrictInt = Field(gt=0)
    base_sha: StrictStr = Field(pattern=r"^[0-9a-f]{40}$")
    head_sha: StrictStr = Field(pattern=r"^[0-9a-f]{40}$")
    review_id: StrictInt = Field(gt=0)
    reviewer: StrictStr = Field(min_length=1)
    submitted_at: AwareDatetime
    challenge: StrictStr = Field(min_length=1, pattern=r"^NEXUS-TRUSTED-REVIEW-V1:[0-9a-f]{64}$")


class ScopeAuthorization(StrictBaseModel):
    """Autorisation de scope d'ingestion — structure complète, ADR-0032 § 2.

    Toujours construite par ``authorize_scope_cli.py`` après revérification
    live de ``evidence`` — jamais assemblée à la main à partir d'un fichier
    fourni par un opérateur sans cette revérification préalable."""

    authorization_id: StrictStr = Field(min_length=1, max_length=128)
    decision: StrictStr = Field(min_length=1)
    scope: ResourceScope
    collection: CollectionName
    manifest_digest: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    profile_id: StrictStr = Field(min_length=1)
    profile_version: StrictStr = Field(min_length=1)
    profile_fingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    allowed_domains: tuple[StrictStr, ...] = Field(min_length=1)
    rights_categories: tuple[StrictStr, ...] = Field(min_length=1)
    exclusions: tuple[StrictStr, ...] = Field(default=())
    pii_absence_attested: StrictBool
    pii_absence_evidence: StrictStr = Field(min_length=1)
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    evidence: GitHubApprovalEvidence

    @model_validator(mode="after")
    def _decision_is_fixed_literal(self) -> ScopeAuthorization:
        if self.decision != AUTHORIZE_INGESTION_SCOPE_DECISION:
            raise ValueError(
                f"decision must be exactly {AUTHORIZE_INGESTION_SCOPE_DECISION!r}, "
                f"got {self.decision!r} — never a free-form string"
            )
        return self

    @model_validator(mode="after")
    def _validity_window_is_coherent(self) -> ScopeAuthorization:
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be strictly after valid_from")
        return self

    @model_validator(mode="after")
    def _no_wildcard_domain(self) -> ScopeAuthorization:
        for domain in self.allowed_domains:
            if domain.strip() in ("*", "") or domain.strip().startswith("*."):
                raise ValueError(
                    f"allowed_domains must never contain a wildcard, got {domain!r}"
                )
        return self

    @model_validator(mode="after")
    def _pii_attestation_requires_evidence(self) -> ScopeAuthorization:
        if not self.pii_absence_attested:
            raise ValueError(
                "pii_absence_attested must be true — a scope authorization can never "
                "be constructed for a scope where PII absence is not attested"
            )
        return self


class ScopeAuthorizationRevocation(StrictBaseModel):
    """Révocation d'une autorisation — même frontière GitHub que l'octroi,
    jamais un simple UPDATE opérateur (ADR-0032 § 3)."""

    authorization_id: StrictStr = Field(min_length=1, max_length=128)
    revocation_reason: StrictStr = Field(min_length=1)
    revoked_at: AwareDatetime
    evidence: GitHubApprovalEvidence


def is_expired(authorization: ScopeAuthorization, *, now: datetime) -> bool:
    """Pure — jamais d'horloge système lue directement ici, ``now`` toujours
    fourni par l'appelant (même discipline que le reste de ce paquet)."""
    return now >= authorization.valid_until


__all__ = [
    "AUTHORIZE_INGESTION_SCOPE_DECISION",
    "GitHubApprovalEvidence",
    "ScopeAuthorization",
    "ScopeAuthorizationRevocation",
    "is_expired",
]
