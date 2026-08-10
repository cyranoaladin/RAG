"""Publisher interne H2-C : un artefact, un jeu de chunks, N placements.

Ce module n'est monté dans aucune API. Chaque placement est lié à sa propre
attestation LOT42 revérifiée en direct et à une ressource déjà
``RETRIEVAL_ELIGIBLE``. Les trois relations produit sont écrites dans une
seule transaction PostgreSQL, avec une identité artefact égale au SHA-256 du
contenu et sans chemin de mise à jour permissif.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import psycopg
from nexus_contracts.embedding_utils import format_passage
from nexus_contracts.ingestion import ResourceScope
from nexus_contracts.resource_state import ResourceState

try:
    from .embedding_contract import CANONICAL_EMBED_MODEL
    from .ingest_v2 import _is_artifact
    from .ingestion_control.publication_attestation import (
        VerifiedAttestation,
        verify_publication_attestation,
    )
    from .ingestion_control.scope_authority import scope_key
    from .pedagogical_chunker import RawChunk, _flatten_section, parse_sections
    from .retrieval_hybrid_v2 import EMBED_DIMENSION
except (ImportError, ValueError):
    from embedding_contract import CANONICAL_EMBED_MODEL  # type: ignore[no-redef]
    from ingest_v2 import _is_artifact  # type: ignore[no-redef]
    from ingestion_control.publication_attestation import (  # type: ignore[no-redef]
        VerifiedAttestation,
        verify_publication_attestation,
    )
    from ingestion_control.scope_authority import scope_key  # type: ignore[no-redef]
    from pedagogical_chunker import (  # type: ignore[no-redef]
        RawChunk,
        _flatten_section,
        parse_sections,
    )
    from retrieval_hybrid_v2 import EMBED_DIMENSION  # type: ignore[no-redef]

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
ExtractText = Callable[[bytes], str]
EmbedChunks = Callable[[Sequence[str]], Sequence[Sequence[float]]]


class GovernedPublicationError(RuntimeError):
    """La publication ne satisfait pas la chaîne gouvernée complète."""


def _nonblank(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonblank")
    return value


@dataclass(frozen=True)
class GovernedArtifact:
    content: bytes
    content_sha256: str
    source_label: str
    source_uri: str
    rights: str
    official: bool
    source_kind: str
    type_doc: str

    def __post_init__(self) -> None:
        if not isinstance(self.content, bytes) or not self.content:
            raise ValueError("content must be non-empty bytes")
        actual = hashlib.sha256(self.content).hexdigest()
        if self.content_sha256 != actual or _SHA256.fullmatch(actual) is None:
            raise ValueError("content SHA-256 does not match canonical bytes")
        for field in (
            "source_label",
            "source_uri",
            "rights",
            "source_kind",
            "type_doc",
        ):
            _nonblank(getattr(self, field), field=field)
        if not isinstance(self.official, bool):
            raise ValueError("official must be boolean")

    @property
    def artifact_id(self) -> str:
        return self.content_sha256


@dataclass(frozen=True)
class EligiblePlacement:
    resource_id: UUID
    scope: ResourceScope
    statut_enseignement: str
    domain: str
    source_scope: str
    source_placement_id: str
    source_path: str
    source_uri: str
    current_profile_fingerprint: str
    current_manifest_digest: str
    currentness: Literal["current"] = "current"

    def __post_init__(self) -> None:
        if not isinstance(self.resource_id, UUID):
            raise ValueError("resource_id must be UUID")
        if not isinstance(self.scope, ResourceScope):
            raise ValueError("scope must be canonical ResourceScope")
        for field in (
            "statut_enseignement",
            "domain",
            "source_scope",
            "source_placement_id",
            "source_path",
            "source_uri",
        ):
            _nonblank(getattr(self, field), field=field)
        for field in ("current_profile_fingerprint", "current_manifest_digest"):
            if _SHA256.fullmatch(getattr(self, field)) is None:
                raise ValueError(f"{field} must be SHA-256")
        if self.currentness != "current":
            raise ValueError("only current placements are publishable")


@dataclass(frozen=True)
class GovernedPublicationResult:
    artifact_id: str
    artifact_created: bool
    placement_rows: int
    chunk_rows: int
    embedded: bool


@dataclass(frozen=True)
class _VerifiedPlacement:
    placement: EligiblePlacement
    attestation: VerifiedAttestation


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _canonical_audience(scope: ResourceScope) -> list[str]:
    return sorted(_enum_value(value) for value in scope.audience)


def canonical_placement_id(artifact_id: str, placement: EligiblePlacement) -> str:
    """Identité stable du tuple pédagogique, indépendante de l'autorité."""
    if _SHA256.fullmatch(artifact_id) is None:
        raise ValueError("artifact_id must be SHA-256")
    scope = placement.scope
    document = {
        "artifact_id": artifact_id,
        "audience": _canonical_audience(scope),
        "candidat": _enum_value(scope.candidat),
        "collection": str(scope.collection),
        "matiere": str(scope.matiere),
        "niveau": _enum_value(scope.niveau),
        "programme_version": str(scope.programme_version),
        "school_year": str(scope.school_year),
        "statut_enseignement": placement.statut_enseignement,
        "tenant": str(scope.tenant),
        "visibility": str(scope.visibility),
        "voie": _enum_value(scope.voie),
    }
    canonical = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _resource_is_retrieval_eligible(
    control_conn: psycopg.Connection,
    *,
    resource_id: UUID,
) -> bool:
    with control_conn.cursor() as cursor:
        cursor.execute(
            "SELECT resource_state FROM ingestion_control.resources "
            "WHERE resource_id = %s",
            (resource_id,),
        )
        row = cursor.fetchone()
    return row == (ResourceState.RETRIEVAL_ELIGIBLE.value,)


def _verify_placements(
    control_conn: psycopg.Connection,
    *,
    artifact: GovernedArtifact,
    placements: Sequence[EligiblePlacement],
) -> tuple[_VerifiedPlacement, ...]:
    if not placements:
        raise GovernedPublicationError("at least one eligible placement is required")
    verified: list[_VerifiedPlacement] = []
    placement_ids: set[str] = set()
    for placement in placements:
        placement_id = canonical_placement_id(artifact.artifact_id, placement)
        if placement_id in placement_ids:
            raise GovernedPublicationError("duplicate canonical placement")
        placement_ids.add(placement_id)
        attestation = verify_publication_attestation(
            control_conn,
            resource_id=placement.resource_id,
            current_content_sha256=artifact.content_sha256,
            current_profile_fingerprint=placement.current_profile_fingerprint,
            current_manifest_digest=placement.current_manifest_digest,
            require_content_bound_authority=True,
        )
        if not isinstance(attestation, VerifiedAttestation):
            raise GovernedPublicationError("LOT42 verifier returned an invalid object")
        facts = attestation.facts
        if (
            attestation.resource_id != placement.resource_id
            or attestation.content_sha256 != artifact.content_sha256
            or facts.content_sha256 != artifact.content_sha256
            or facts.collection != str(placement.scope.collection)
            or facts.canonical_url != placement.source_uri
            or facts.rights_status.value != artifact.rights
            or scope_key(attestation.authorization.scope) != scope_key(placement.scope)
        ):
            raise GovernedPublicationError("verified LOT42 facts do not match publication")
        if not _resource_is_retrieval_eligible(
            control_conn, resource_id=placement.resource_id
        ):
            raise GovernedPublicationError("resource is not RETRIEVAL_ELIGIBLE")
        verified.append(_VerifiedPlacement(placement, attestation))
    return tuple(verified)


def _chunk_text(extracted_text: str) -> tuple[str, ...]:
    if not isinstance(extracted_text, str) or not extracted_text.strip():
        raise GovernedPublicationError("extraction produced no substantive text")
    sections = parse_sections(extracted_text)
    raw_chunks: list[RawChunk] = []
    for section in sections:
        raw_chunks.extend(_flatten_section(section))
    if not raw_chunks:
        raw_chunks = [
            RawChunk(text=extracted_text, section_path=[], section_title="")
        ]
    chunks = tuple(
        chunk.text.replace("\x00", "").strip()
        for chunk in raw_chunks
        if not _is_artifact(chunk.text.replace("\x00", ""))
    )
    if not chunks or any(not chunk for chunk in chunks):
        raise GovernedPublicationError("chunking produced no substantive text")
    return chunks


def _vectors(
    chunks: Sequence[str],
    embed_chunks: EmbedChunks,
) -> tuple[tuple[float, ...], ...]:
    passages = [format_passage(chunk) for chunk in chunks]
    encoded = embed_chunks(passages)
    if len(encoded) != len(chunks):
        raise GovernedPublicationError("embedding cardinality mismatch")
    vectors: list[tuple[float, ...]] = []
    for vector in encoded:
        normalized = tuple(float(component) for component in vector)
        if (
            len(normalized) != EMBED_DIMENSION
            or any(not math.isfinite(component) for component in normalized)
            or math.hypot(*normalized) == 0.0
        ):
            raise GovernedPublicationError("invalid governed embedding")
        vectors.append(normalized)
    return tuple(vectors)


def _lock_artifact(cursor: Any, artifact_id: str) -> None:
    """Sérialiser les publications du même contenu sans droit UPDATE."""
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (artifact_id,),
    )


def _artifact_row(cursor: Any, artifact_id: str) -> tuple[object, ...] | None:
    cursor.execute(
        """
        SELECT content_sha256, rights, official, source_kind, type_doc
        FROM public.rag_artifacts
        WHERE artifact_id = %s
        """,
        (artifact_id,),
    )
    row = cursor.fetchone()
    return None if row is None else tuple(row)


def _insert_placement(
    cursor: Any,
    *,
    artifact_id: str,
    verified: _VerifiedPlacement,
) -> None:
    placement = verified.placement
    attestation = verified.attestation
    scope = placement.scope
    placement_id = canonical_placement_id(artifact_id, placement)
    values = (
        placement_id,
        artifact_id,
        str(scope.collection),
        str(scope.tenant),
        _enum_value(scope.niveau),
        _enum_value(scope.voie),
        _canonical_audience(scope),
        str(scope.matiere),
        placement.statut_enseignement,
        _enum_value(scope.candidat),
        str(scope.visibility),
        str(scope.school_year),
        str(scope.programme_version),
        placement.currentness,
        "active",
        "reviewed",
        placement.source_scope,
        placement.source_placement_id,
        placement.source_path,
        placement.source_uri,
        attestation.scope_authorization_id,
        attestation.attestation_id,
    )
    cursor.execute(
        """
        INSERT INTO public.rag_artifact_placements (
            placement_id, artifact_id, collection, tenant, niveau, voie,
            audience, matiere, statut_enseignement, candidat, visibility,
            school_year, programme_version, currentness, placement_status,
            review_status, source_scope, source_placement_id, source_path,
            source_uri, authorization_id, publication_attestation_id
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (placement_id) DO NOTHING
        """,
        values,
    )
    cursor.execute(
        """
        SELECT placement_id, artifact_id, collection, tenant, niveau, voie,
               audience, matiere, statut_enseignement, candidat, visibility,
               school_year, programme_version, currentness, placement_status,
               review_status, source_scope, source_placement_id, source_path,
               source_uri, authorization_id, publication_attestation_id
        FROM public.rag_artifact_placements
        WHERE placement_id = %s
        """,
        (placement_id,),
    )
    if cursor.fetchone() != values:
        raise GovernedPublicationError("existing placement differs from verified input")


def _insert_chunks(
    cursor: Any,
    *,
    artifact: GovernedArtifact,
    placement: EligiblePlacement,
    chunks: Sequence[str],
    vectors: Sequence[Sequence[float]],
) -> None:
    scope = placement.scope
    for index, (text, vector) in enumerate(zip(chunks, vectors, strict=True)):
        chunk_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        chunk_id = hashlib.sha256(
            f"{artifact.artifact_id}:{index}:{chunk_sha}".encode()
        ).hexdigest()
        vector_text = "[" + ",".join(str(component) for component in vector) + "]"
        cursor.execute(
            """
            INSERT INTO public.rag_chunks (
                chunk_id, doc_id, chunk_sha256, vector,
                collection, niveau, voie, audience, matiere,
                statut_enseignement, domain, source_label, source_uri,
                rights, type_doc, official, text, chunk_index,
                review_status, model, source_kind, tenant, candidat,
                visibility, school_year, programme_version, artifact_id
            ) VALUES (
                %s, %s, %s, %s::vector,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            """,
            (
                chunk_id,
                artifact.artifact_id,
                chunk_sha,
                vector_text,
                str(scope.collection),
                _enum_value(scope.niveau),
                _enum_value(scope.voie),
                _canonical_audience(scope),
                str(scope.matiere),
                placement.statut_enseignement,
                placement.domain,
                artifact.source_label,
                artifact.source_uri,
                artifact.rights,
                artifact.type_doc,
                artifact.official,
                text,
                index,
                "reviewed",
                CANONICAL_EMBED_MODEL,
                artifact.source_kind,
                str(scope.tenant),
                _enum_value(scope.candidat),
                str(scope.visibility),
                str(scope.school_year),
                str(scope.programme_version),
                artifact.artifact_id,
            ),
        )


def publish_governed_artifact(
    control_conn: psycopg.Connection,
    product_conn: psycopg.Connection,
    artifact: GovernedArtifact,
    placements: Sequence[EligiblePlacement],
    extract_text: ExtractText,
    embed_chunks: EmbedChunks,
) -> GovernedPublicationResult:
    """Revérifier LOT42 puis publier une fois, sans writer HTTP ou bypass."""
    if not isinstance(artifact, GovernedArtifact):
        raise TypeError("artifact must be GovernedArtifact")
    verified = _verify_placements(
        control_conn,
        artifact=artifact,
        placements=placements,
    )
    ordered = tuple(
        sorted(
            verified,
            key=lambda item: canonical_placement_id(
                artifact.artifact_id, item.placement
            ),
        )
    )
    embedded = False
    with product_conn.transaction():
        # Revérification live dans la transaction d'écriture : une révocation
        # ou une dérive détectée après le préflight ne laisse aucune ligne
        # produit partiellement publiée.
        ordered = tuple(
            sorted(
                _verify_placements(
                    control_conn,
                    artifact=artifact,
                    placements=tuple(item.placement for item in ordered),
                ),
                key=lambda item: canonical_placement_id(
                    artifact.artifact_id, item.placement
                ),
            )
        )
        with product_conn.cursor() as cursor:
            _lock_artifact(cursor, artifact.artifact_id)
            existing = _artifact_row(cursor, artifact.artifact_id)
            artifact_created = existing is None
            if existing is None:
                first_attestation = ordered[0].attestation
                cursor.execute(
                    """
                    INSERT INTO public.rag_artifacts (
                        artifact_id, content_sha256, source_label, source_uri,
                        rights, official, source_kind, type_doc,
                        ingestion_artifact_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        artifact.artifact_id,
                        artifact.content_sha256,
                        artifact.source_label,
                        artifact.source_uri,
                        artifact.rights,
                        artifact.official,
                        artifact.source_kind,
                        artifact.type_doc,
                        first_attestation.artifact_id,
                    ),
                )
            elif existing != (
                artifact.content_sha256,
                artifact.rights,
                artifact.official,
                artifact.source_kind,
                artifact.type_doc,
            ):
                raise GovernedPublicationError(
                    "existing artifact differs from content-bound publication"
                )

            for item in ordered:
                _insert_placement(
                    cursor,
                    artifact_id=artifact.artifact_id,
                    verified=item,
                )

            if artifact_created:
                extracted = extract_text(artifact.content)
                chunks = _chunk_text(extracted)
                vectors = _vectors(chunks, embed_chunks)
                _insert_chunks(
                    cursor,
                    artifact=artifact,
                    placement=ordered[0].placement,
                    chunks=chunks,
                    vectors=vectors,
                )
                embedded = True
            else:
                cursor.execute(
                    "SELECT COUNT(*) FROM public.rag_chunks WHERE artifact_id = %s",
                    (artifact.artifact_id,),
                )
                row = cursor.fetchone()
                if row is None or not isinstance(row[0], int) or row[0] <= 0:
                    raise GovernedPublicationError(
                        "existing artifact has no atomic chunk set"
                    )

            # La vérification précédente protège toute entrée dans le writer.
            # Celle-ci ferme la fenêtre extraction/embedding : aucune autorité
            # ou attestation révoquée entre-temps ne peut être validée.
            final_verified = _verify_placements(
                control_conn,
                artifact=artifact,
                placements=placements,
            )
            initial_bindings = {
                (
                    item.placement.resource_id,
                    item.attestation.attestation_id,
                    item.attestation.attestation_digest,
                    item.attestation.authorization.authorization_digest,
                )
                for item in verified
            }
            final_bindings = {
                (
                    item.placement.resource_id,
                    item.attestation.attestation_id,
                    item.attestation.attestation_digest,
                    item.attestation.authorization.authorization_digest,
                )
                for item in final_verified
            }
            if final_bindings != initial_bindings:
                raise GovernedPublicationError(
                    "LOT42 authority changed during atomic publication"
                )

            cursor.execute(
                "SELECT COUNT(*) FROM public.rag_artifact_placements "
                "WHERE artifact_id = %s",
                (artifact.artifact_id,),
            )
            placement_count_row = cursor.fetchone()
            cursor.execute(
                "SELECT COUNT(*) FROM public.rag_chunks WHERE artifact_id = %s",
                (artifact.artifact_id,),
            )
            chunk_count_row = cursor.fetchone()
            if placement_count_row is None or chunk_count_row is None:
                raise GovernedPublicationError("publication counts unavailable")

    return GovernedPublicationResult(
        artifact_id=artifact.artifact_id,
        artifact_created=artifact_created,
        placement_rows=int(placement_count_row[0]),
        chunk_rows=int(chunk_count_row[0]),
        embedded=embedded,
    )


__all__ = [
    "EligiblePlacement",
    "GovernedArtifact",
    "GovernedPublicationError",
    "GovernedPublicationResult",
    "canonical_placement_id",
    "publish_governed_artifact",
]
