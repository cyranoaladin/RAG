"""Dérivation fail-closed du scope serveur de retrieval."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from nexus_contracts import (
    RIGHTS_ALLOWED_CONTEXTS,
    AccessContext,
    PilotRetrievalScopeArtifact,
    Rights,
)

if __package__:
    from .collection_config import (
        CollectionConfigError,
        resolve_collection_v2,
        resolve_declared_collection_v2,
    )
    from .identity_v2 import VerifiedInternalIdentity
else:
    from collection_config import (  # type: ignore[no-redef]
        CollectionConfigError,
        resolve_collection_v2,
        resolve_declared_collection_v2,
    )
    from identity_v2 import VerifiedInternalIdentity  # type: ignore[no-redef]


class RetrievalScopeError(ValueError):
    """Identité ou collection hors de la projection moteur autorisée."""


@dataclass(frozen=True)
class ServerRetrievalScope:
    """Prédicats serveur immuables, sans identifiant personnel."""

    tenant: str
    niveau: str
    voie: str | None
    matiere: str
    statut_enseignement: str
    candidat: str
    audiences: tuple[str, ...]
    rights: tuple[Rights, ...]
    visibilities: tuple[str, ...]
    school_year: str
    collection: str
    programme_version: str
    scope_id: str
    scope_digest: str
    source_sha256: str
    review_status: Literal["reviewed"] = "reviewed"

    @property
    def filter_digest(self) -> str:
        """Partition stable du scope ne contenant ni sujet ni identifiant de jeton."""
        payload = {
            "tenant": self.tenant,
            "niveau": self.niveau,
            "voie": self.voie,
            "matiere": self.matiere,
            "statut_enseignement": self.statut_enseignement,
            "candidat": self.candidat,
            "audiences": self.audiences,
            "rights": tuple(right.value for right in self.rights),
            "visibilities": self.visibilities,
            "school_year": self.school_year,
            "collection": self.collection,
            "programme_version": self.programme_version,
            "scope_id": self.scope_id,
            "scope_digest": self.scope_digest,
            "source_sha256": self.source_sha256,
            "review_status": self.review_status,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


_ROLE_CONTEXTS: dict[str, tuple[AccessContext, ...]] = {
    "student": (AccessContext.public,),
    "teacher": (
        AccessContext.public,
        AccessContext.internal,
        AccessContext.teacher,
    ),
    "reviewer": (
        AccessContext.public,
        AccessContext.internal,
        AccessContext.teacher,
    ),
    "ingest_agent": (AccessContext.internal,),
    "admin": (AccessContext.admin,),
}

_ROLE_VISIBILITIES: dict[str, tuple[str, ...]] = {
    "student": ("public",),
    "teacher": ("public", "internal"),
    "reviewer": ("public", "internal", "restricted"),
    "ingest_agent": ("internal", "restricted"),
    "admin": ("public", "internal", "restricted", "private"),
}


def allowed_rights_for_role(role: str) -> tuple[Rights, ...]:
    """Dériver les droits sans inférer un contexte absent de l'identité."""
    try:
        contexts = _ROLE_CONTEXTS[role]
    except KeyError as exc:
        raise ValueError("unsupported retrieval role") from exc

    return tuple(
        right
        for right, allowed_contexts in RIGHTS_ALLOWED_CONTEXTS.items()
        if any(context in allowed_contexts for context in contexts)
    )


def allowed_visibilities_for_role(role: str) -> tuple[str, ...]:
    """Retourner l'allowlist de visibilité propre au rôle."""
    try:
        return _ROLE_VISIBILITIES[role]
    except KeyError as exc:
        raise ValueError("unsupported retrieval role") from exc


def effective_signed_collections(
    verified: VerifiedInternalIdentity,
) -> tuple[str, ...]:
    """Return artifact-ordered collections selected by signed subjects."""
    envelope = verified.envelope
    artifact = verified.artifact
    try:
        artifact.validate_envelope(envelope)
    except ValueError as exc:
        raise RetrievalScopeError("retrieval scope forbidden") from exc
    matieres = set(envelope.identity.pedagogical_profile.matieres)
    effective = tuple(
        subject.collection for subject in artifact.subjects if subject.matiere in matieres
    )
    if not effective:
        raise RetrievalScopeError("retrieval scope forbidden")
    return effective


def validate_pilot_scope_catalogue_alignment(
    artifact: PilotRetrievalScopeArtifact,
    collection_config: Mapping[str, Any],
) -> None:
    """Lier chaque matière signée à sa définition catalogue autoritative."""
    domains = collection_config.get("domains")
    if not isinstance(domains, Mapping):
        raise RetrievalScopeError("retrieval scope forbidden")

    expected_identity = artifact.identity
    for subject in artifact.subjects:
        try:
            definition = resolve_collection_v2(
                subject.collection,
                collection_config,
            )
        except CollectionConfigError as exc:
            raise RetrievalScopeError("retrieval scope forbidden") from exc

        domain = definition.get("domain")
        domain_definition = domains.get(domain) if isinstance(domain, str) else None
        if (
            not isinstance(domain_definition, Mapping)
            or domain_definition.get("retrievable") is not True
        ):
            raise RetrievalScopeError("retrieval scope forbidden")

        expected_dimensions = {
            "matiere": subject.matiere,
            "niveau": expected_identity.niveau.value,
            "voie": expected_identity.voie.value,
            "statut": expected_identity.statut_enseignement.value,
        }
        if any(
            definition.get(dimension) != expected
            for dimension, expected in expected_dimensions.items()
        ):
            raise RetrievalScopeError("retrieval scope forbidden")


def _retrievable_definition(
    collection: str,
    collection_config: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        definition = resolve_collection_v2(collection, collection_config)
    except CollectionConfigError as exc:
        raise RetrievalScopeError("retrieval scope forbidden") from exc

    domain = definition.get("domain")
    domains = collection_config.get("domains")
    if not isinstance(domain, str) or not isinstance(domains, Mapping):
        raise RetrievalScopeError("retrieval scope forbidden")
    domain_definition = domains.get(domain)
    if (
        not isinstance(domain_definition, Mapping)
        or domain_definition.get("retrievable") is not True
    ):
        raise RetrievalScopeError("retrieval scope forbidden")
    return definition


def build_server_retrieval_scope(
    verified: VerifiedInternalIdentity,
    *,
    collection: str,
    collection_config: Mapping[str, Any],
) -> ServerRetrievalScope:
    """Autoriser une collection puis dériver tous les prédicats serveur."""
    definition = _retrievable_definition(collection, collection_config)
    return _build_server_scope(
        verified,
        collection=collection,
        definition=definition,
    )


def build_server_readiness_scope(
    verified: VerifiedInternalIdentity,
    *,
    collection: str,
    collection_config: Mapping[str, Any],
) -> ServerRetrievalScope:
    """Project a signed declared collection without making it retrievable."""
    try:
        definition = resolve_declared_collection_v2(collection, collection_config)
    except CollectionConfigError as exc:
        raise RetrievalScopeError("retrieval scope forbidden") from exc
    return _build_server_scope(
        verified,
        collection=collection,
        definition=definition,
    )


def _build_server_scope(
    verified: VerifiedInternalIdentity,
    *,
    collection: str,
    definition: Mapping[str, Any],
) -> ServerRetrievalScope:
    """Derive immutable predicates after the caller selected its gate."""
    envelope = verified.envelope
    artifact = verified.artifact
    if collection not in effective_signed_collections(verified):
        raise RetrievalScopeError("retrieval scope forbidden")

    subject = next(
        (candidate for candidate in artifact.subjects if candidate.collection == collection),
        None,
    )
    if subject is None:
        raise RetrievalScopeError("retrieval scope forbidden")

    identity = envelope.identity
    profile = identity.pedagogical_profile
    dimensions = {
        "niveau": identity.niveau.value,
        "voie": profile.voie.value,
        "matiere": subject.matiere,
        "statut": profile.statut_enseignement.value,
    }
    if any(definition.get(key) != expected for key, expected in dimensions.items()):
        raise RetrievalScopeError("retrieval scope forbidden")
    if subject.matiere not in profile.matieres:
        raise RetrievalScopeError("retrieval scope forbidden")

    audiences = tuple(dict.fromkeys((profile.audience, "tous")))
    return ServerRetrievalScope(
        tenant=identity.tenant,
        niveau=identity.niveau.value,
        voie=profile.voie.value,
        matiere=subject.matiere,
        statut_enseignement=profile.statut_enseignement.value,
        candidat=profile.candidat.value,
        audiences=audiences,
        rights=allowed_rights_for_role(identity.role),
        visibilities=allowed_visibilities_for_role(identity.role),
        school_year=identity.school_year,
        collection=collection,
        programme_version=subject.programme_version,
        scope_id=artifact.scope_id,
        scope_digest=artifact.sha256_digest(),
        source_sha256=artifact.source_sha256,
    )


__all__ = [
    "RetrievalScopeError",
    "ServerRetrievalScope",
    "allowed_rights_for_role",
    "allowed_visibilities_for_role",
    "build_server_readiness_scope",
    "build_server_retrieval_scope",
    "effective_signed_collections",
    "validate_pilot_scope_catalogue_alignment",
]
