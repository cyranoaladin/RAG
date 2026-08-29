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
    RetrievalScopeArtifact,
    RetrievalScopeArtifactV2,
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

#: `student` a longtemps été le seul rôle sans `internal`, et les 18 collections
#: servies portent toutes `visibility: internal` — aucun profil élève ne pouvait
#: donc interroger le corpus. Le défaut n'apparaît qu'au premier tir sous le rôle
#: auquel le produit est destiné : les tests d'intégration passaient parce qu'ils
#: utilisent des rôles privilégiés.
#:
#: `internal` n'est PAS défini comme « exclu des utilisateurs finaux », vérifié :
#: le contrat n'attache aucune sémantique à `Literal["public", "internal",
#: "restricted", "private"]` ; là où « revue seulement » est visé, un autre
#: terme explicite est employé (`internal_review_only`,
#: `source_admission_policy.yml`) ; et la décision de droits sur
#: `01_EDUSCOL_OFFICIEL/` autorise nommément « le retrieval, la citation et
#: l'ingestion de production » (`rights_evidence_registry.yml`).
#:
#: `internal` désigne donc l'appartenance au corpus Nexus, par opposition au web
#: public — pas une exclusion des élèves. Les collections restent internes ; la
#: politique de rôle dit que les élèves les lisent. Alternative écartée : passer
#: les collections en `public` aurait exigé de ré-émettre les 18 manifests-sujets
#: scellés, donc 18 scopes `_v3` et la cascade entière — disproportionné pour une
#: correspondance rôle/visibilité.
#:
#: Décision opérateur du 28/08/2026. Voir
#: `docs/reports/analyse_dette_28_visibilite_eleve.md`.
_ROLE_VISIBILITIES: dict[str, tuple[str, ...]] = {
    "student": ("public", "internal"),
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
    if isinstance(artifact, RetrievalScopeArtifactV2):
        return (artifact.evidence_subject.collection,)
    matieres = set(envelope.identity.pedagogical_profile.matieres)
    effective = tuple(
        subject.collection for subject in artifact.subjects if subject.matiere in matieres
    )
    if not effective:
        raise RetrievalScopeError("retrieval scope forbidden")
    return effective


def validate_pilot_scope_catalogue_alignment(
    artifact: RetrievalScopeArtifact,
    collection_config: Mapping[str, Any],
) -> None:
    """Lier chaque matière signée à sa définition catalogue autoritative."""
    _validate_scope_catalogue_alignment(
        artifact,
        collection_config,
        require_instantiated=True,
    )


def validate_scope_registry_catalogue_alignment(
    artifacts: Mapping[str, RetrievalScopeArtifact],
    collection_config: Mapping[str, Any],
) -> None:
    """Valider tout le registre contre les collections déclarées, sans les activer."""
    if not artifacts or any(key != artifact.scope_id for key, artifact in artifacts.items()):
        raise RetrievalScopeError("retrieval scope forbidden")
    for artifact in artifacts.values():
        _validate_scope_catalogue_alignment(
            artifact,
            collection_config,
            require_instantiated=False,
        )


def _validate_scope_catalogue_alignment(
    artifact: RetrievalScopeArtifact,
    collection_config: Mapping[str, Any],
    *,
    require_instantiated: bool,
) -> None:
    """Comparer un artefact aux dimensions déclarées du catalogue monté."""
    domains = collection_config.get("domains")
    if not isinstance(domains, Mapping):
        raise RetrievalScopeError("retrieval scope forbidden")

    if isinstance(artifact, RetrievalScopeArtifactV2):
        evidence_subjects = (artifact.evidence_subject,)
    else:
        evidence_subjects = artifact.subjects
    for subject in evidence_subjects:
        try:
            resolver = (
                resolve_collection_v2 if require_instantiated else resolve_declared_collection_v2
            )
            definition = resolver(subject.collection, collection_config)
        except CollectionConfigError as exc:
            raise RetrievalScopeError("retrieval scope forbidden") from exc

        domain = definition.get("domain")
        domain_definition = domains.get(domain) if isinstance(domain, str) else None
        if (
            not isinstance(domain_definition, Mapping)
            or domain_definition.get("retrievable") is not True
        ):
            raise RetrievalScopeError("retrieval scope forbidden")

        if isinstance(artifact, RetrievalScopeArtifactV2):
            expected_dimensions = {
                "matiere": subject.matiere,
                "niveau": subject.niveau.value,
                "voie": subject.voie.value,
                "statut": subject.statut_enseignement.value,
            }
        else:
            expected_identity = artifact.identity
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

    if isinstance(artifact, RetrievalScopeArtifactV2):
        subject = (
            artifact.evidence_subject
            if artifact.evidence_subject.collection == collection
            else None
        )
    else:
        subject = next(
            (candidate for candidate in artifact.subjects if candidate.collection == collection),
            None,
        )
    if subject is None:
        raise RetrievalScopeError("retrieval scope forbidden")

    identity = envelope.identity
    profile = identity.pedagogical_profile
    if isinstance(artifact, RetrievalScopeArtifactV2):
        evidence = artifact.evidence_subject
        dimensions = {
            "niveau": evidence.niveau.value,
            "voie": evidence.voie.value,
            "matiere": evidence.matiere,
            "statut": evidence.statut_enseignement.value,
        }
        tenant = evidence.tenant
        niveau = evidence.niveau.value
        voie = evidence.voie.value
        matiere = evidence.matiere
        statut_enseignement = evidence.statut_enseignement.value
        candidat = evidence.candidat.value
        audiences = tuple(evidence.audiences)
        school_year = evidence.school_year
        programme_version = evidence.programme_version
        allowed_rights = set(allowed_rights_for_role(identity.role))
        rights = tuple(right for right in evidence.rights if right in allowed_rights)
        role_visibilities = allowed_visibilities_for_role(identity.role)
        visibilities = (evidence.visibility,) if evidence.visibility in role_visibilities else ()
        if not rights or not visibilities:
            raise RetrievalScopeError("retrieval scope forbidden")
    else:
        dimensions = {
            "niveau": identity.niveau.value,
            "voie": profile.voie.value,
            "matiere": subject.matiere,
            "statut": profile.statut_enseignement.value,
        }
        if subject.matiere not in profile.matieres:
            raise RetrievalScopeError("retrieval scope forbidden")
        tenant = identity.tenant
        niveau = identity.niveau.value
        voie = profile.voie.value
        matiere = subject.matiere
        statut_enseignement = profile.statut_enseignement.value
        candidat = profile.candidat.value
        audiences = tuple(dict.fromkeys((profile.audience, "tous")))
        school_year = identity.school_year
        programme_version = subject.programme_version
        rights = allowed_rights_for_role(identity.role)
        visibilities = allowed_visibilities_for_role(identity.role)
    if any(definition.get(key) != expected for key, expected in dimensions.items()):
        raise RetrievalScopeError("retrieval scope forbidden")

    return ServerRetrievalScope(
        tenant=tenant,
        niveau=niveau,
        voie=voie,
        matiere=matiere,
        statut_enseignement=statut_enseignement,
        candidat=candidat,
        audiences=audiences,
        rights=rights,
        visibilities=visibilities,
        school_year=school_year,
        collection=collection,
        programme_version=programme_version,
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
    "validate_scope_registry_catalogue_alignment",
]
