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

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, StrictStr, model_validator

from nexus_contracts.document import StrictBaseModel
from nexus_contracts.identity import CollectionName
from nexus_contracts.ingestion import ResourceScope

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


# ---------------------------------------------------------------------------
# Artefact d'autorité (remédiation revue GATE H1, item B)
# ---------------------------------------------------------------------------
#
# La première version de LOT41A prouvait deux choses séparément : (1) qu'une
# PR/head donnée était APPROVED, et (2) qu'un fichier local arbitraire
# (``--scope-file``) décrivait un scope. Elle ne prouvait JAMAIS que le
# relecteur humain avait approuvé *ces octets-là* — un opérateur pouvait
# présenter n'importe quel fichier local avec une PR approuvée sans rapport.
#
# L'artefact ci-dessous supprime cette faille : l'autorisation complète est
# un fichier canonique **versionné dans le HEAD exact qui reçoit la review**
# (``governance/authorizations/<authorization_id>.json``). Le lien prouvé
# devient : HEAD revu -> blob relu depuis ce HEAD -> digest canonique -> ligne
# PostgreSQL. Aucun fichier local ne peut s'y substituer.

#: Chemin canonique, dérivé de l'identifiant — jamais un chemin libre choisi
#: par l'opérateur (qui pourrait pointer vers un artefact sans rapport).
AUTHORIZATION_ARTIFACT_DIR = "governance/authorizations"

LOT41A_ARTIFACT_PROTOCOL_VERSION = "LOT41A-ARTIFACT-V1"


def authorization_artifact_path(authorization_id: str) -> str:
    """Chemin canonique de l'artefact — déterministe, jamais fourni librement."""
    return f"{AUTHORIZATION_ARTIFACT_DIR}/{authorization_id}.json"


class ScopeAuthorizationArtifact(StrictBaseModel):
    """Autorisation complète telle qu'elle existe **dans le dépôt**, au HEAD
    exact revu par l'humain.

    ``extra="forbid"`` (via ``StrictBaseModel``) est ici une garantie de
    sécurité, pas une commodité : un champ inconnu ajouté à l'artefact
    revu échoue la validation au lieu d'être silencieusement ignoré."""

    protocol_version: Literal["LOT41A-ARTIFACT-V1"]
    authorization_id: StrictStr = Field(min_length=1, max_length=128)
    decision: Literal["AUTHORIZE_INGESTION_SCOPE"]
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

    @model_validator(mode="after")
    def _validity_window_is_coherent(self) -> ScopeAuthorizationArtifact:
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be strictly after valid_from")
        return self

    @model_validator(mode="after")
    def _no_wildcard_domain(self) -> ScopeAuthorizationArtifact:
        for domain in self.allowed_domains:
            if domain.strip() in ("*", "") or domain.strip().startswith("*."):
                raise ValueError(
                    f"allowed_domains must never contain a wildcard, got {domain!r}"
                )
        return self

    @model_validator(mode="after")
    def _pii_attestation_requires_evidence(self) -> ScopeAuthorizationArtifact:
        if not self.pii_absence_attested:
            raise ValueError(
                "pii_absence_attested must be true — an authorization artifact can "
                "never be constructed for a scope where PII absence is not attested"
            )
        return self

    @model_validator(mode="after")
    def _collection_matches_scope(self) -> ScopeAuthorizationArtifact:
        if self.collection != self.scope.collection:
            raise ValueError(
                f"collection {self.collection!r} must equal scope.collection "
                f"{self.scope.collection!r} — never two divergent sources of truth"
            )
        return self


def canonical_authorization_bytes(artifact: ScopeAuthorizationArtifact) -> bytes:
    """Sérialisation canonique déterministe — même discipline que
    ``ingestion_profiles.events.canonical_json_bytes`` :

    - ``sort_keys=True`` : indépendant de l'ordre des clés du fichier source ;
    - ``ensure_ascii=True`` : indépendant de l'encodage/locale ;
    - ``separators=(",", ":")`` : aucune marge de formatage ;
    - ``allow_nan=False`` : aucune valeur non représentable en JSON strict.

    Deux fichiers sémantiquement identiques mais formatés différemment
    produisent donc le MÊME digest — le digest lie le **contenu autorisé**,
    jamais un formatage accidentel."""
    payload = artifact.model_dump(mode="json")
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def authorization_digest(artifact: ScopeAuthorizationArtifact) -> str:
    """SHA-256 de la sérialisation canonique — l'identité cryptographique de
    l'autorisation, calculée identiquement depuis le blob GitHub relu et
    depuis la ligne PostgreSQL stockée."""
    return hashlib.sha256(canonical_authorization_bytes(artifact)).hexdigest()


REVOCATION_ARTIFACT_DIR = "governance/revocations"
LOT41A_REVOCATION_PROTOCOL_VERSION = "LOT41A-REVOCATION-V1"


def revocation_artifact_path(authorization_id: str) -> str:
    return f"{REVOCATION_ARTIFACT_DIR}/{authorization_id}.json"


class ScopeRevocationArtifact(StrictBaseModel):
    """Révocation telle qu'elle existe dans le HEAD exact revu — même
    principe de liaison au contenu que l'octroi (item B) : ni
    ``authorization_id`` ni le motif ne sont des arguments libres du CLI,
    ils font partie des octets effectivement approuvés."""

    protocol_version: Literal["LOT41A-REVOCATION-V1"]
    authorization_id: StrictStr = Field(min_length=1, max_length=128)
    revocation_reason: StrictStr = Field(min_length=1)


def canonical_revocation_bytes(artifact: ScopeRevocationArtifact) -> bytes:
    payload = artifact.model_dump(mode="json")
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def revocation_digest(artifact: ScopeRevocationArtifact) -> str:
    return hashlib.sha256(canonical_revocation_bytes(artifact)).hexdigest()


__all__ = [
    "AUTHORIZATION_ARTIFACT_DIR",
    "AUTHORIZE_INGESTION_SCOPE_DECISION",
    "LOT41A_ARTIFACT_PROTOCOL_VERSION",
    "LOT41A_REVOCATION_PROTOCOL_VERSION",
    "REVOCATION_ARTIFACT_DIR",
    "GitHubApprovalEvidence",
    "ScopeAuthorization",
    "ScopeAuthorizationArtifact",
    "ScopeAuthorizationRevocation",
    "ScopeRevocationArtifact",
    "authorization_artifact_path",
    "authorization_digest",
    "canonical_authorization_bytes",
    "canonical_revocation_bytes",
    "is_expired",
    "revocation_artifact_path",
    "revocation_digest",
]
