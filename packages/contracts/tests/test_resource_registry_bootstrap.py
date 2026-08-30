from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from nexus_contracts import (
    BootstrapChunk,
    BootstrapResourceVersion,
    ResourceRegistryBootstrapPayload,
    seal_resource_registry_bootstrap,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
RESOURCE_ID = UUID("11111111-1111-4111-8111-111111111111")
VERSION_ID = UUID("22222222-2222-4222-8222-222222222222")


def _payload() -> ResourceRegistryBootstrapPayload:
    return ResourceRegistryBootstrapPayload(
        protocol_version="1",
        producer_repository="cyranoaladin/RAG",
        producer_commit=SHA_A[:40],
        package_version="0.15.0",
        source_snapshot_sha256=SHA_B,
        generated_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
        resources=[
            BootstrapResourceVersion(
                resource_id=RESOURCE_ID,
                resource_version_id=VERSION_ID,
                content_sha256=SHA_A,
                rag_artifact_id=SHA_A,
                size_bytes=42,
                mime_type="application/pdf",
                source_label="Programme officiel de mathématiques",
                source_uri="https://eduscol.education.fr/programme.pdf",
                rights="officiel_public",
                official=True,
                source_kind="eduscol",
                type_doc="programme_officiel",
                placements=[
                    {
                        "tenant": "nexus",
                        "collection": "terminale_maths",
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
                chunks=[
                    BootstrapChunk(
                        chunk_id="chunk-001",
                        locator={"page": 1},
                    )
                ],
            )
        ],
    )


def test_bootstrap_preserves_ingestion_identity_mapping() -> None:
    inventory = seal_resource_registry_bootstrap(_payload())
    item = inventory.resources[0]

    assert item.resource_id == RESOURCE_ID
    assert item.resource_version_id == VERSION_ID
    assert item.content_sha256 == SHA_A
    assert item.rag_artifact_id == item.content_sha256
    assert inventory.inventory_sha256 == inventory.compute_sha256()


def test_bootstrap_rejects_rag_artifact_not_equal_to_content_hash() -> None:
    data = _payload().model_dump(mode="python")
    data["resources"][0]["rag_artifact_id"] = SHA_B
    with pytest.raises(ValidationError, match="rag_artifact_id"):
        ResourceRegistryBootstrapPayload.model_validate(data)


def test_bootstrap_rejects_duplicate_resource_version_or_orphan_chunk() -> None:
    data = _payload().model_dump(mode="python")
    data["resources"].append(dict(data["resources"][0]))
    with pytest.raises(ValidationError, match="resource_version_id"):
        ResourceRegistryBootstrapPayload.model_validate(data)

    data = _payload().model_dump(mode="python")
    data["resources"][0]["chunks"] = []
    with pytest.raises(ValidationError, match="chunks"):
        ResourceRegistryBootstrapPayload.model_validate(data)


def test_bootstrap_contract_rejects_unknown_fields() -> None:
    data = _payload().model_dump(mode="python")
    data["resources"][0]["collection"] = "invented_mapping"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ResourceRegistryBootstrapPayload.model_validate(data)


def test_bootstrap_locator_preserves_exact_page_range() -> None:
    data = _payload().model_dump(mode="python")
    data["resources"][0]["chunks"][0]["locator"] = {
        "chunk_index": 0,
        "page_start": 2,
        "page_end": 4,
    }
    inventory = ResourceRegistryBootstrapPayload.model_validate(data)
    locator = inventory.resources[0].chunks[0].locator
    assert (locator.chunk_index, locator.page_start, locator.page_end) == (0, 2, 4)

    data["resources"][0]["chunks"][0]["locator"] = {"page_start": 2}
    with pytest.raises(ValidationError, match="page_start and page_end"):
        ResourceRegistryBootstrapPayload.model_validate(data)


@pytest.mark.parametrize(
    "field",
    [
        "mime_type",
        "source_label",
        "source_uri",
        "rights",
        "source_kind",
        "type_doc",
    ],
)
def test_bootstrap_requires_auditable_provenance(field: str) -> None:
    data = _payload().model_dump(mode="python")
    data["resources"][0][field] = ""
    with pytest.raises(ValidationError, match=field):
        ResourceRegistryBootstrapPayload.model_validate(data)
