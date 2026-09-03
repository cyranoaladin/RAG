from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from nexus_contracts import (
    ResourceRegistrySnapshotPayload,
    seal_resource_registry_snapshot,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def _payload(*, resources: list[dict[str, str]] | None = None) -> ResourceRegistrySnapshotPayload:
    return ResourceRegistrySnapshotPayload.model_validate(
        {
            "protocol_version": "1",
            "registry_version": "aria-resource-registry-v1",
            "producer_repository": "cyranoaladin/nexus-project_v0",
            "producer_commit": SHA_A[:40],
            "generated_at": datetime(2026, 8, 30, 12, tzinfo=UTC),
            "bootstrap_inventory_sha256": SHA_B,
            "resources": resources
            or [
                {
                    "resource_id": "11111111-1111-4111-8111-111111111111",
                    "resource_version_id": "22222222-2222-4222-8222-222222222222",
                    "content_sha256": SHA_A,
                }
            ],
        }
    )


def test_snapshot_is_nexus_owned_digest_sealed_and_strict() -> None:
    snapshot = seal_resource_registry_snapshot(_payload())

    assert snapshot.registry_sha256 == snapshot.compute_sha256()
    assert snapshot.producer_repository == "cyranoaladin/nexus-project_v0"
    assert snapshot.bootstrap_inventory_sha256 == SHA_B

    with pytest.raises(ValidationError):
        ResourceRegistrySnapshotPayload.model_validate(
            {**_payload().model_dump(mode="json"), "unknown": True}
        )


def test_snapshot_requires_canonical_unique_resource_version_order() -> None:
    first = {
        "resource_id": "11111111-1111-4111-8111-111111111111",
        "resource_version_id": "22222222-2222-4222-8222-222222222222",
        "content_sha256": SHA_A,
    }
    second = {
        "resource_id": "33333333-3333-4333-8333-333333333333",
        "resource_version_id": "44444444-4444-4444-8444-444444444444",
        "content_sha256": SHA_B,
    }

    seal_resource_registry_snapshot(_payload(resources=[first, second]))
    with pytest.raises(ValidationError, match="canonical"):
        _payload(resources=[second, first])
    with pytest.raises(ValidationError, match="unique"):
        _payload(resources=[first, first])


def test_snapshot_refuses_non_nexus_producer_and_digest_tamper() -> None:
    document = _payload().model_dump(mode="json")
    with pytest.raises(ValidationError):
        ResourceRegistrySnapshotPayload.model_validate(
            {**document, "producer_repository": "cyranoaladin/RAG"}
        )

    snapshot = seal_resource_registry_snapshot(_payload())
    with pytest.raises(ValidationError, match="registry_sha256"):
        snapshot.model_validate({**snapshot.model_dump(mode="json"), "registry_sha256": SHA_B})
