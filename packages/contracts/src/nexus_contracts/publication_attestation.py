"""Contrat LOT42 — chaîne d'attestations de publication (ADR-0033).

Comme pour ``scope_authorization`` (LOT41A), ce module définit la
**forme** d'une chaîne d'attestations, jamais sa validité. La validité
est toujours recalculée en direct par
``ingestor.ingestion_control.publication_attestation.verify_publication_
attestation`` (``rag-engine``) — jamais un booléen figé stocké ici.

Aucune fonction de ce module ne peut construire une attestation dont la
revue humaine finale n'a pas été indépendamment vérifiée par la même
frontière GitHub qu'ADR-0025/LOT41V (``HumanReviewEvidence`` réutilise
exactement ``GitHubApprovalEvidence`` de ``scope_authorization`` — jamais
une seconde frontière parallèle inventée).
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StrictStr

from nexus_contracts.document import Rights, StrictBaseModel
from nexus_contracts.identity import CollectionName
from nexus_contracts.scope_authorization import GitHubApprovalEvidence

#: Version du protocole — permet une évolution future du contrat sans
#: ambiguïté rétroactive sur les attestations déjà construites (ADR-0033 § 2).
PROTOCOL_VERSION: Literal["LOT42-V1"] = "LOT42-V1"

HumanReviewEvidence = GitHubApprovalEvidence
"""Alias explicite plutôt qu'une sous-classe : la revue humaine finale de
publication est structurellement identique à une évidence d'approbation
LOT41A — même frontière, même revérification live, jamais une seconde
notion de "review" parallèle (ADR-0033 § 3)."""


class RightsAttestation(StrictBaseModel):
    rights_status: Rights
    assessed_at: AwareDatetime


class QualityAttestation(StrictBaseModel):
    passed: bool
    score: float = Field(ge=0, le=1)
    assessed_at: AwareDatetime


class GateAttestation(StrictBaseModel):
    passed: bool
    gate_name: StrictStr = Field(min_length=1)
    evaluated_at: AwareDatetime


class PublicationAttestation(StrictBaseModel):
    """Chaîne d'attestations complète pour une ressource — ADR-0033 § 2.

    Construite incrémentalement par le worker (les quatre premières
    attestations déterministes) puis complétée par
    ``attest_publication_cli.py`` (la revue humaine finale, seule étape
    non déterministe de la chaîne) — jamais assemblée en une seule fois à
    partir de données non revérifiées."""

    resource_id: UUID
    artifact_id: UUID
    content_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_url: StrictStr = Field(min_length=1)
    collection: CollectionName
    scope_authorization_id: StrictStr = Field(min_length=1, max_length=128)
    profile_id: StrictStr = Field(min_length=1)
    profile_version: StrictStr = Field(min_length=1)
    profile_fingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_digest: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    rights: RightsAttestation
    quality: QualityAttestation
    gate: GateAttestation
    human_review: HumanReviewEvidence
    protocol_version: Literal["LOT42-V1"] = PROTOCOL_VERSION
    created_at: AwareDatetime


def is_invalidated_by_content_change(
    attestation: PublicationAttestation, *, current_sha256: str
) -> bool:
    """Pure — comparaison de digest, jamais un accès disque/réseau ici
    (l'appelant fournit ``current_sha256`` déjà relu)."""
    return attestation.content_sha256 != current_sha256


def is_invalidated_by_profile_drift(
    attestation: PublicationAttestation, *, current_profile_fingerprint: str
) -> bool:
    return attestation.profile_fingerprint != current_profile_fingerprint


def is_invalidated_by_manifest_drift(
    attestation: PublicationAttestation, *, current_manifest_digest: str
) -> bool:
    return attestation.manifest_digest != current_manifest_digest


__all__ = [
    "PROTOCOL_VERSION",
    "GateAttestation",
    "HumanReviewEvidence",
    "PublicationAttestation",
    "QualityAttestation",
    "RightsAttestation",
    "is_invalidated_by_content_change",
    "is_invalidated_by_manifest_drift",
    "is_invalidated_by_profile_drift",
]
