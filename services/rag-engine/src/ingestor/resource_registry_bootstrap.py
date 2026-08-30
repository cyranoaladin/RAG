"""Read-only export of governed RAG identities for the Nexus Resource Registry."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import psycopg
from nexus_contracts import (
    ArtifactRecord,
    BootstrapChunk,
    BootstrapResourceVersion,
    ResourceRegistryBootstrap,
    ResourceRegistryBootstrapPayload,
    Rights,
    TypeDoc,
    seal_resource_registry_bootstrap,
)
from nexus_contracts.document import StrictBaseModel
from psycopg.rows import dict_row
from pydantic import Field, ValidationError


class BootstrapInventoryError(RuntimeError):
    """The governed source cannot be represented without guessing."""


class _PlacementRow(StrictBaseModel):
    collection: str = Field(min_length=1)
    tenant: str = Field(min_length=1)
    niveau: str = Field(min_length=1)
    voie: str = Field(min_length=1)
    matiere: str = Field(min_length=1)
    statut_enseignement: str = Field(min_length=1)
    candidat: str = Field(min_length=1)
    audience: list[str] = Field(min_length=1)
    visibility: str = Field(min_length=1)
    school_year: str = Field(min_length=1)
    programme_version: str = Field(min_length=1)
    currentness: Literal["current", "archive", "review_required"]
    placement_status: Literal["active", "disabled"]
    review_status: Literal["needs_review", "reviewed"]
    source_uri: str = Field(min_length=1)


class _ChunkRow(StrictBaseModel):
    chunk_id: str = Field(min_length=1)
    artifact_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    doc_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_index: int = Field(ge=0)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    source_uri: str = Field(min_length=1)
    rights: Rights
    source_label: str = Field(min_length=1)
    official: bool
    source_kind: str = Field(min_length=1)
    type_doc: TypeDoc
    review_status: Literal["needs_review", "reviewed"]
    collection: str = Field(min_length=1)
    tenant: str = Field(min_length=1)
    niveau: str = Field(min_length=1)
    voie: str = Field(min_length=1)
    matiere: str = Field(min_length=1)
    statut_enseignement: str = Field(min_length=1)
    candidat: str = Field(min_length=1)
    audience: list[str] = Field(min_length=1)
    visibility: str = Field(min_length=1)
    school_year: str = Field(min_length=1)
    programme_version: str = Field(min_length=1)


class _BootstrapSourceRow(StrictBaseModel):
    resource_id: UUID
    resource_version_id: UUID
    run_id: UUID
    run_status: str = Field(min_length=1)
    resource_state: str = Field(min_length=1)
    tenant: str = Field(min_length=1)
    collection: str = Field(min_length=1)
    niveau: str = Field(min_length=1)
    voie: str = Field(min_length=1)
    matiere: str = Field(min_length=1)
    candidat: str = Field(min_length=1)
    audience: list[str] = Field(min_length=1)
    visibility: str = Field(min_length=1)
    school_year: str = Field(min_length=1)
    programme_version: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    mime_detected: str = Field(min_length=1)
    artifact_payload: dict[str, Any]
    rag_artifact_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    rag_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rag_source_label: str = Field(min_length=1)
    rag_source_uri: str = Field(min_length=1)
    rag_rights: Rights
    rag_official: bool
    rag_source_kind: str = Field(min_length=1)
    rag_type_doc: TypeDoc
    attribution_resource_id: UUID
    attribution_source_label: str = Field(min_length=1)
    attribution_official: bool
    attribution_source_kind: str = Field(min_length=1)
    attribution_type_doc: TypeDoc
    placements: list[_PlacementRow]
    chunks: list[_ChunkRow]


EXPORT_SQL = """
SELECT
    r.resource_id,
    a.artifact_id AS resource_version_id,
    a.run_id,
    ir.status AS run_status,
    r.resource_state,
    r.tenant,
    r.collection,
    r.niveau,
    r.voie,
    r.matiere,
    r.candidat,
    r.audience,
    r.visibility,
    r.school_year,
    r.programme_version,
    a.sha256 AS content_sha256,
    a.size_bytes,
    a.mime_detected,
    a.payload AS artifact_payload,
    ra.artifact_id AS rag_artifact_id,
    ra.content_sha256 AS rag_content_sha256,
    ra.source_label AS rag_source_label,
    ra.source_uri AS rag_source_uri,
    ra.rights AS rag_rights,
    ra.official AS rag_official,
    ra.source_kind AS rag_source_kind,
    ra.type_doc AS rag_type_doc,
    aa.resource_id AS attribution_resource_id,
    aa.source_label AS attribution_source_label,
    aa.official AS attribution_official,
    aa.source_kind AS attribution_source_kind,
    aa.type_doc AS attribution_type_doc,
    placements.items AS placements,
    chunks.items AS chunks
FROM ingestion_control.resources AS r
JOIN ingestion_control.ingestion_runs AS ir
  ON ir.run_id = r.run_id
 AND ir.tenant = r.tenant
 AND ir.collection = r.collection
 AND ir.niveau = r.niveau
 AND ir.voie = r.voie
 AND ir.matiere = r.matiere
 AND ir.candidat = r.candidat
 AND ir.audience = r.audience
 AND ir.visibility = r.visibility
 AND ir.school_year = r.school_year
 AND ir.programme_version = r.programme_version
JOIN ingestion_control.artifacts AS a
  ON a.resource_id = r.resource_id
 AND a.run_id = r.run_id
JOIN public.rag_artifacts AS ra
  ON ra.ingestion_artifact_id = a.artifact_id
JOIN ingestion_control.artifact_attributions AS aa
  ON aa.ingestion_artifact_id = a.artifact_id
 AND aa.resource_id = r.resource_id
JOIN LATERAL (
    SELECT COALESCE(
        jsonb_agg(
            jsonb_build_object(
                'collection', p.collection,
                'tenant', p.tenant,
                'niveau', p.niveau,
                'voie', p.voie,
                'matiere', p.matiere,
                'statut_enseignement', p.statut_enseignement,
                'candidat', p.candidat,
                'audience', p.audience,
                'visibility', p.visibility,
                'school_year', p.school_year,
                'programme_version', p.programme_version,
                'currentness', p.currentness,
                'placement_status', p.placement_status,
                'review_status', p.review_status,
                'source_uri', p.source_uri
            ) ORDER BY p.collection, p.placement_id
        ),
        '[]'::jsonb
    ) AS items
    FROM public.rag_artifact_placements AS p
    WHERE p.artifact_id = ra.artifact_id
      AND p.currentness = 'current'
      AND p.placement_status = 'active'
      AND p.review_status = 'reviewed'
) AS placements ON TRUE
JOIN LATERAL (
    SELECT COALESCE(
        jsonb_agg(
            jsonb_build_object(
                'chunk_id', c.chunk_id,
                'artifact_id', c.artifact_id,
                'doc_id', c.doc_id,
                'chunk_index', c.chunk_index,
                'page_start', c.page_start,
                'page_end', c.page_end,
                'source_uri', c.source_uri,
                'rights', c.rights,
                'source_label', c.source_label,
                'official', c.official,
                'source_kind', c.source_kind,
                'type_doc', c.type_doc,
                'review_status', c.review_status,
                'collection', c.collection,
                'tenant', c.tenant,
                'niveau', c.niveau,
                'voie', c.voie,
                'matiere', c.matiere,
                'statut_enseignement', c.statut_enseignement,
                'candidat', c.candidat,
                'audience', c.audience,
                'visibility', c.visibility,
                'school_year', c.school_year,
                'programme_version', c.programme_version
            ) ORDER BY c.chunk_index, c.chunk_id
        ),
        '[]'::jsonb
    ) AS items
    FROM public.rag_chunks AS c
    WHERE c.artifact_id = ra.artifact_id
) AS chunks ON TRUE
WHERE r.resource_state = 'RETRIEVAL_ELIGIBLE'
  AND ir.status = 'succeeded'
  AND r.collection = ANY(%(release_collections)s)
ORDER BY a.artifact_id
"""

_RESOURCE_SCOPE_FIELDS = (
    "tenant",
    "collection",
    "niveau",
    "voie",
    "matiere",
    "candidat",
    "audience",
    "visibility",
    "school_year",
    "programme_version",
)


def _scope_tuple(value: object) -> tuple[object, ...]:
    if isinstance(value, _BootstrapSourceRow | _PlacementRow | _ChunkRow):
        return tuple(getattr(value, field) for field in _RESOURCE_SCOPE_FIELDS)
    if isinstance(value, Mapping):
        return tuple(value.get(field) for field in _RESOURCE_SCOPE_FIELDS)
    raise BootstrapInventoryError("scope value is not representable")


def _validate_artifact(row: _BootstrapSourceRow) -> ArtifactRecord:
    try:
        artifact = ArtifactRecord.model_validate(row.artifact_payload)
    except ValidationError as exc:
        raise BootstrapInventoryError(f"artifact payload is invalid: {exc}") from exc

    typed = (
        artifact.artifact_id == row.resource_version_id
        and artifact.resource_id == row.resource_id
        and artifact.run_id == row.run_id
        and artifact.sha256 == row.content_sha256
        and artifact.size_bytes == row.size_bytes
        and artifact.mime_detected == row.mime_detected
        and artifact.final_url == row.rag_source_uri
        and artifact.rights_status == row.rag_rights
    )
    if not typed:
        raise BootstrapInventoryError(
            f"artifact payload differs from typed columns for {row.resource_version_id}"
        )
    if row.run_status != "succeeded" or row.resource_state != "RETRIEVAL_ELIGIBLE":
        raise BootstrapInventoryError(
            f"run or resource is not retrieval-eligible for {row.resource_version_id}"
        )
    if _scope_tuple(artifact.scope.model_dump(mode="json")) != _scope_tuple(row):
        raise BootstrapInventoryError(
            f"artifact scope differs for {row.resource_version_id}"
        )
    return artifact


def _validate_identity(row: _BootstrapSourceRow) -> None:
    if not (
        row.rag_artifact_id
        == row.rag_content_sha256
        == row.content_sha256
    ):
        raise BootstrapInventoryError(
            f"RAG artifact content hash differs for {row.resource_version_id}"
        )
    attribution = (
        row.attribution_resource_id == row.resource_id
        and row.attribution_source_label == row.rag_source_label
        and row.attribution_official == row.rag_official
        and row.attribution_source_kind == row.rag_source_kind
        and row.attribution_type_doc == row.rag_type_doc
    )
    if not attribution:
        raise BootstrapInventoryError(
            f"artifact attribution differs for {row.resource_version_id}"
        )


def _validate_placements(row: _BootstrapSourceRow) -> None:
    if not row.placements:
        raise BootstrapInventoryError(
            f"placements are missing for {row.resource_version_id}"
        )
    for placement in row.placements:
        if (
            placement.currentness != "current"
            or placement.placement_status != "active"
            or placement.review_status != "reviewed"
            or placement.source_uri != row.rag_source_uri
            or _scope_tuple(placement) != _scope_tuple(row)
        ):
                raise BootstrapInventoryError(
                    f"placement state, source, or scope differs for "
                f"{row.resource_version_id}"
            )


def _validated_chunks(row: _BootstrapSourceRow) -> list[BootstrapChunk]:
    if not row.chunks:
        raise BootstrapInventoryError(f"chunks are missing for {row.resource_version_id}")
    chunk_ids: set[str] = set()
    chunk_indexes: set[int] = set()
    result: list[BootstrapChunk] = []
    for chunk in sorted(row.chunks, key=lambda item: (item.chunk_index, item.chunk_id)):
        if chunk.chunk_id in chunk_ids or chunk.chunk_index in chunk_indexes:
            raise BootstrapInventoryError(
                f"chunk identity is duplicated for {row.resource_version_id}"
            )
        chunk_ids.add(chunk.chunk_id)
        chunk_indexes.add(chunk.chunk_index)
        if not (
            chunk.artifact_id == row.rag_artifact_id
            and chunk.doc_id == row.rag_artifact_id
            and chunk.source_uri == row.rag_source_uri
            and chunk.rights == row.rag_rights
            and chunk.source_label == row.rag_source_label
            and chunk.official == row.rag_official
            and chunk.source_kind == row.rag_source_kind
            and chunk.type_doc == row.rag_type_doc
            and chunk.review_status == "reviewed"
            and _scope_tuple(chunk) == _scope_tuple(row)
        ):
            raise BootstrapInventoryError(
                f"chunk metadata or scope differs for "
                f"{row.resource_version_id}/{chunk.chunk_id}"
            )
        if (chunk.page_start is None) != (chunk.page_end is None):
            raise BootstrapInventoryError(
                f"chunk page locator is incomplete for {row.resource_version_id}/"
                f"{chunk.chunk_id}"
            )
        locator: dict[str, int] = {"chunk_index": chunk.chunk_index}
        if chunk.page_start is not None and chunk.page_end is not None:
            locator.update(page_start=chunk.page_start, page_end=chunk.page_end)
        result.append(BootstrapChunk(chunk_id=chunk.chunk_id, locator=locator))
    return result


def _safe_snapshot_row(
    row: _BootstrapSourceRow, resource: BootstrapResourceVersion
) -> dict[str, object]:
    return {
        "resource": resource.model_dump(mode="json"),
        "placements": [
            placement.model_dump(mode="json")
            for placement in sorted(
                row.placements,
                key=lambda item: (item.collection, item.source_uri),
            )
        ],
    }


def build_resource_registry_bootstrap_inventory(
    rows: Iterable[Mapping[str, object]],
    *,
    producer_repository: str,
    producer_commit: str,
    generated_at: datetime,
    package_version: str,
) -> ResourceRegistryBootstrap:
    """Validate and seal a deterministic inventory without source content or paths."""

    validated: list[_BootstrapSourceRow] = []
    for raw in rows:
        try:
            validated.append(_BootstrapSourceRow.model_validate(raw))
        except ValidationError as exc:
            raise BootstrapInventoryError(f"bootstrap source row is invalid: {exc}") from exc
    if not validated:
        raise BootstrapInventoryError("bootstrap source contains no governed resources")
    version_ids = [row.resource_version_id for row in validated]
    if len(version_ids) != len(set(version_ids)):
        raise BootstrapInventoryError(
            "multiple RAG artifacts link to one ingestion resource version"
        )

    resources: list[BootstrapResourceVersion] = []
    snapshot: list[dict[str, object]] = []
    for row in sorted(validated, key=lambda item: str(item.resource_version_id)):
        _validate_artifact(row)
        _validate_identity(row)
        _validate_placements(row)
        chunks = _validated_chunks(row)
        resource = BootstrapResourceVersion(
            resource_id=row.resource_id,
            resource_version_id=row.resource_version_id,
            content_sha256=row.content_sha256,
            rag_artifact_id=row.rag_artifact_id,
            size_bytes=row.size_bytes,
            mime_type=row.mime_detected,
            source_label=row.rag_source_label,
            source_uri=row.rag_source_uri,
            rights=row.rag_rights,
            official=row.rag_official,
            source_kind=row.rag_source_kind,
            type_doc=row.rag_type_doc,
            chunks=chunks,
        )
        resources.append(resource)
        snapshot.append(_safe_snapshot_row(row, resource))

    snapshot_bytes = json.dumps(
        snapshot,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    try:
        payload = ResourceRegistryBootstrapPayload(
            protocol_version="1",
            producer_repository=producer_repository,
            producer_commit=producer_commit,
            package_version=package_version,
            source_snapshot_sha256=hashlib.sha256(snapshot_bytes).hexdigest(),
            generated_at=generated_at,
            resources=resources,
        )
    except ValidationError as exc:
        raise BootstrapInventoryError(f"bootstrap inventory is invalid: {exc}") from exc
    return seal_resource_registry_bootstrap(payload)


def export_resource_registry_bootstrap_inventory(
    connection: psycopg.Connection[Any],
    *,
    producer_repository: str,
    producer_commit: str,
    generated_at: datetime,
    package_version: str,
    release_collections: frozenset[str],
) -> ResourceRegistryBootstrap:
    """Read both schemas through one repeatable, read-only PostgreSQL snapshot."""

    if not release_collections or any(not item.strip() for item in release_collections):
        raise BootstrapInventoryError("release registry collections are required")
    with connection.transaction():
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY, DEFERRABLE"
            )
            cursor.execute(
                EXPORT_SQL,
                {"release_collections": sorted(release_collections)},
            )
            rows = cursor.fetchall()
    return build_resource_registry_bootstrap_inventory(
        rows,
        producer_repository=producer_repository,
        producer_commit=producer_commit,
        generated_at=generated_at,
        package_version=package_version,
    )


__all__ = [
    "BootstrapInventoryError",
    "EXPORT_SQL",
    "build_resource_registry_bootstrap_inventory",
    "export_resource_registry_bootstrap_inventory",
]
