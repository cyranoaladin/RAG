from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from nexus_contracts import (
    ResourceRegistryBootstrapPayload,
    ResourceRegistrySnapshotPayload,
    seal_resource_registry_bootstrap,
    seal_resource_registry_snapshot,
)

from ingestor.servable_corpus_manifest import (
    CorpusBuildSpec,
    ServableCorpusBuildError,
    build_servable_corpus_manifest,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
REGISTRY_SHA = "c" * 64
GENERATED_AT = datetime(2026, 8, 30, 12, tzinfo=UTC)


def _resource(
    *,
    resource_id: str = "11111111-1111-4111-8111-111111111111",
    resource_version_id: str = "22222222-2222-4222-8222-222222222222",
    content_sha256: str = SHA_A,
    chunk_id: str = "chunk-001",
) -> dict[str, object]:
    return {
        "resource_id": resource_id,
        "resource_version_id": resource_version_id,
        "content_sha256": content_sha256,
        "rag_artifact_id": content_sha256,
        "size_bytes": 42,
        "mime_type": "application/pdf",
        "source_label": "Programme officiel",
        "source_uri": "https://eduscol.education.fr/programme.pdf",
        "rights": "officiel_public",
        "official": True,
        "source_kind": "eduscol.education.fr",
        "type_doc": "programme_officiel",
        "placements": [
            {
                "tenant": "nexus",
                "collection": "rag_nexus_maths_terminale_gen_specialite",
                "niveau": "terminale",
                "voie": "generale",
                "matiere": "mathematiques",
                "statut_enseignement": "specialite",
                "candidat": "scolarise",
                "audience": ["aefe"],
                "visibility": "internal",
                "school_year": "2026-2027",
                "programme_version": "fr-national-2026",
            }
        ],
        "chunks": [{"chunk_id": chunk_id, "locator": {"chunk_index": 0, "page": 1}}],
    }


def _registry(*resources: dict[str, object]):
    return seal_resource_registry_bootstrap(
        ResourceRegistryBootstrapPayload.model_validate(
            {
                "protocol_version": "1",
                "producer_repository": "cyranoaladin/RAG",
                "producer_commit": SHA_B[:40],
                "package_version": "0.15.0",
                "source_snapshot_sha256": REGISTRY_SHA,
                "generated_at": GENERATED_AT,
                "resources": list(resources) or [_resource()],
            }
        )
    )


def _spec(**changes: object) -> CorpusBuildSpec:
    payload: dict[str, object] = {
        "corpus_id": "aria-maths-terminale",
        "corpus_version_id": "2026-08-30.1",
        "academic_year": "2026-2027",
        "curriculum_version": "fr-national-2026",
        "physical_collection": "rag_nexus_maths_terminale_gen_specialite",
        "scope_id": "scope-maths-terminale-v1",
        "scope_sha256": SHA_B,
    }
    payload.update(changes)
    return CorpusBuildSpec.model_validate(payload)


def _snapshot(registry, *, resources: list[dict[str, object]] | None = None):
    return seal_resource_registry_snapshot(
        ResourceRegistrySnapshotPayload.model_validate(
            {
                "protocol_version": "1",
                "registry_version": "aria-resource-registry-v1",
                "producer_repository": "cyranoaladin/nexus-project_v0",
                "producer_commit": SHA_A[:40],
                "generated_at": GENERATED_AT,
                "bootstrap_inventory_sha256": registry.inventory_sha256,
                "resources": resources
                or [
                    {
                        "resource_id": item.resource_id,
                        "resource_version_id": item.resource_version_id,
                        "content_sha256": item.content_sha256,
                    }
                    for item in registry.resources
                ],
            }
        )
    )


def _build(registry=None, specs=None, snapshot=None):
    registry = registry or _registry(_resource())
    return build_servable_corpus_manifest(
        resource_inventory=registry,
        resource_registry=snapshot or _snapshot(registry),
        manifest_version="aria-servable-corpus-2026-08-30.1",
        producer_repository="cyranoaladin/RAG",
        producer_commit=SHA_A[:40],
        generated_at=GENERATED_AT,
        corpus_specs=specs or [_spec()],
    )


def test_manifest_is_deterministic_and_preserves_canonical_resource_identity() -> None:
    manifest = _build()
    corpus = manifest.corpora[0]
    resource = corpus.resources[0]

    assert manifest.manifest_sha256 == manifest.compute_sha256()
    registry = _registry(_resource())
    assert manifest.resource_registry_sha256 == _snapshot(registry).registry_sha256
    assert corpus.corpus_id == "aria-maths-terminale"
    assert corpus.physical_collection == "rag_nexus_maths_terminale_gen_specialite"
    assert resource.resource_id == UUID("11111111-1111-4111-8111-111111111111")
    assert resource.resource_version_id == UUID("22222222-2222-4222-8222-222222222222")
    assert resource.content_sha256 == SHA_A
    assert resource.chunks[0].chunk_id == "chunk-001"


def test_registry_refuses_noncanonical_resource_order() -> None:
    first = _resource()
    second = _resource(
        resource_id="33333333-3333-4333-8333-333333333333",
        resource_version_id="44444444-4444-4444-8444-444444444444",
        content_sha256=SHA_B,
        chunk_id="chunk-002",
    )
    _build(_registry(first, second))
    with pytest.raises(ValueError, match="canonical"):
        _registry(second, first)


def test_manifest_rejects_duplicate_chunk_id_across_resource_versions() -> None:
    first = _resource()
    second = _resource(
        resource_id="33333333-3333-4333-8333-333333333333",
        resource_version_id="44444444-4444-4444-8444-444444444444",
        content_sha256=SHA_B,
        chunk_id="chunk-001",
    )
    with pytest.raises(ServableCorpusBuildError, match="chunk"):
        _build(_registry(first, second))


def test_manifest_rejects_unknown_empty_or_cross_scope_collection() -> None:
    with pytest.raises(ServableCorpusBuildError, match="collection"):
        _build(specs=[_spec(physical_collection="rag_nexus_nsi_terminale_specialite")])

    with pytest.raises(ServableCorpusBuildError, match="scope"):
        _build(specs=[_spec(academic_year="2025-2026")])


def test_manifest_rejects_duplicate_corpus_binding() -> None:
    with pytest.raises(ServableCorpusBuildError, match="corpus"):
        _build(specs=[_spec(), _spec()])


def test_manifest_rejects_registry_not_derived_from_exact_bootstrap() -> None:
    inventory = _registry(_resource())
    other_inventory = _registry(
        _resource(
            resource_id="33333333-3333-4333-8333-333333333333",
            resource_version_id="44444444-4444-4444-8444-444444444444",
            content_sha256=SHA_B,
            chunk_id="chunk-002",
        )
    )
    with pytest.raises(ServableCorpusBuildError, match="bootstrap"):
        _build(inventory, snapshot=_snapshot(other_inventory))


def test_manifest_rejects_resource_version_or_hash_absent_from_nexus_registry() -> None:
    inventory = _registry(_resource())
    wrong_bindings = [
        {
            "resource_id": "11111111-1111-4111-8111-111111111111",
            "resource_version_id": "22222222-2222-4222-8222-222222222222",
            "content_sha256": SHA_B,
        }
    ]
    with pytest.raises(ServableCorpusBuildError, match="Nexus Resource Registry"):
        _build(
            inventory,
            snapshot=_snapshot(inventory, resources=wrong_bindings),
        )
