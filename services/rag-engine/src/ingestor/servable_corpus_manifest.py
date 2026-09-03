"""Build the RAG-owned servable corpus manifest from canonical resource identities."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from nexus_contracts import (
    CorpusChunkBinding,
    CorpusResourceVersion,
    ResourceRegistryBootstrap,
    ResourceRegistrySnapshot,
    RetrievalScopeArtifactV3,
    ServableCorpus,
    ServableCorpusManifest,
    ServableCorpusManifestPayload,
    seal_servable_corpus_manifest,
)
from nexus_contracts.document import StrictBaseModel
from nexus_contracts.identity import CollectionName, SchoolYear
from nexus_contracts.servable_corpus_manifest import BoundedVersion
from pydantic import ValidationError


class ServableCorpusBuildError(ValueError):
    """The governed inputs cannot produce an unambiguous servable corpus."""


class CorpusBuildSpec(StrictBaseModel):
    """RAG-owned corpus identity to physical collection binding.

    It deliberately contains no Nexus course key. Nexus consumes ``corpus_id``;
    only this manifest resolves it to a physical retrieval collection.
    """

    corpus_id: BoundedVersion
    corpus_version_id: BoundedVersion
    academic_year: SchoolYear
    curriculum_version: BoundedVersion
    physical_collection: CollectionName
    retrieval_scope: RetrievalScopeArtifactV3


def _resources_for_spec(
    resource_inventory: ResourceRegistryBootstrap,
    resource_registry: ResourceRegistrySnapshot,
    spec: CorpusBuildSpec,
) -> list[CorpusResourceVersion]:
    resources: list[CorpusResourceVersion] = []
    known_collection = False
    chunk_ids: set[str] = set()
    registered = {
        (item.resource_id, item.resource_version_id, item.content_sha256)
        for item in resource_registry.resources
    }
    for item in resource_inventory.resources:
        collection_placements = [
            placement
            for placement in item.placements
            if placement.collection == spec.physical_collection
        ]
        if not collection_placements:
            continue
        known_collection = True
        if (item.resource_id, item.resource_version_id, item.content_sha256) not in registered:
            raise ServableCorpusBuildError(
                f"resource version is absent from Nexus Resource Registry: {item.resource_version_id}"
            )
        if any(
            placement.school_year != spec.academic_year
            or placement.programme_version != spec.curriculum_version
            for placement in collection_placements
        ):
            raise ServableCorpusBuildError(
                f"collection scope differs for {spec.corpus_id}"
            )
        chunks = [
            CorpusChunkBinding(chunk_id=chunk.chunk_id, locator=chunk.locator)
            for chunk in sorted(item.chunks, key=lambda value: value.chunk_id)
        ]
        duplicates = chunk_ids.intersection(chunk.chunk_id for chunk in chunks)
        if duplicates:
            raise ServableCorpusBuildError(
                f"chunk identity is ambiguous in corpus {spec.corpus_id}"
            )
        chunk_ids.update(chunk.chunk_id for chunk in chunks)
        resources.append(
            CorpusResourceVersion(
                resource_id=item.resource_id,
                resource_version_id=item.resource_version_id,
                content_sha256=item.content_sha256,
                chunks=chunks,
            )
        )
    if not known_collection or not resources:
        raise ServableCorpusBuildError(
            f"physical collection has no canonical resources: {spec.physical_collection}"
        )
    return sorted(resources, key=lambda value: str(value.resource_version_id))


def build_servable_corpus_manifest(
    *,
    resource_inventory: ResourceRegistryBootstrap,
    resource_registry: ResourceRegistrySnapshot,
    manifest_version: str,
    producer_repository: str,
    producer_commit: str,
    generated_at: datetime,
    corpus_specs: Iterable[CorpusBuildSpec],
) -> ServableCorpusManifest:
    """Seal deterministic corpus bindings without minting document identities."""

    if (
        resource_registry.bootstrap_inventory_sha256
        != resource_inventory.inventory_sha256
    ):
        raise ServableCorpusBuildError(
            "Nexus Resource Registry does not bind this bootstrap inventory"
        )

    specs = sorted(
        corpus_specs,
        key=lambda value: (value.corpus_id, value.corpus_version_id),
    )
    if not specs:
        raise ServableCorpusBuildError("corpus build specification is empty")
    identities = [(item.corpus_id, item.corpus_version_id) for item in specs]
    if len(identities) != len(set(identities)) or len({item.corpus_id for item in specs}) != len(specs):
        raise ServableCorpusBuildError("corpus identity is duplicated")

    try:
        corpora = [
            ServableCorpus(
                **spec.model_dump(mode="python"),
                resources=_resources_for_spec(
                    resource_inventory,
                    resource_registry,
                    spec,
                ),
            )
            for spec in specs
        ]
        payload = ServableCorpusManifestPayload(
            protocol_version="1",
            manifest_version=manifest_version,
            resource_registry_version=resource_registry.registry_version,
            resource_registry_sha256=resource_registry.registry_sha256,
            producer_repository=producer_repository,
            producer_commit=producer_commit,
            generated_at=generated_at,
            corpora=corpora,
        )
    except ValidationError as exc:
        raise ServableCorpusBuildError(f"servable corpus manifest is invalid: {exc}") from exc
    return seal_servable_corpus_manifest(payload)


__all__ = [
    "CorpusBuildSpec",
    "ServableCorpusBuildError",
    "build_servable_corpus_manifest",
]
