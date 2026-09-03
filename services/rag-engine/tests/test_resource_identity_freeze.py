from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from nexus_contracts import (
    ResourceRegistrySnapshot,
    ResourceRegistrySnapshotPayload,
    seal_resource_registry_snapshot,
)
from nexus_contracts.ingestion import ResourceScope

from ingestor.ingestion_control.provisioning import create_resource
from ingestor.resource_identity_freeze import (
    RESOURCE_REGISTRY_ISSUANCE_REQUIRED,
    ResourceIdentityFreeze,
    ResourceIdentityFreezeError,
    load_optional_pinned_resource_identity_freeze,
)

SHA_A = "a" * 64


def _snapshot() -> ResourceRegistrySnapshot:
    return seal_resource_registry_snapshot(
        ResourceRegistrySnapshotPayload.model_validate(
            {
                "protocol_version": "1",
                "registry_version": "aria-resource-registry-v1",
                "producer_repository": "cyranoaladin/nexus-project_v0",
                "producer_commit": SHA_A[:40],
                "generated_at": datetime(2026, 8, 30, 12, tzinfo=UTC),
                "bootstrap_inventory_sha256": SHA_A,
                "resources": [
                    {
                        "resource_id": "11111111-1111-4111-8111-111111111111",
                        "resource_version_id": "22222222-2222-4222-8222-222222222222",
                        "content_sha256": SHA_A,
                    }
                ],
            }
        )
    )


def _freeze() -> ResourceIdentityFreeze:
    return ResourceIdentityFreeze(_snapshot())


def test_registered_resource_and_version_are_reused_without_minting() -> None:
    freeze = _freeze()
    resource_id = freeze.require_resource_id(
        "11111111-1111-4111-8111-111111111111"
    )
    version_id = freeze.require_resource_version_id(
        resource_id=resource_id,
        resource_version_id="22222222-2222-4222-8222-222222222222",
        content_sha256=SHA_A,
    )

    assert resource_id == UUID("11111111-1111-4111-8111-111111111111")
    assert version_id == UUID("22222222-2222-4222-8222-222222222222")
    assert freeze.require_declared_resource_version_id(
        resource_id=resource_id,
        resource_version_id=version_id,
    ) == version_id


@pytest.mark.parametrize(
    ("resource_id", "version_id", "content_sha256"),
    [
        (None, None, SHA_A),
        ("33333333-3333-4333-8333-333333333333", None, SHA_A),
        (
            "11111111-1111-4111-8111-111111111111",
            "44444444-4444-4444-8444-444444444444",
            SHA_A,
        ),
        (
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
            "b" * 64,
        ),
    ],
)
def test_missing_or_unregistered_identity_fails_with_stable_code(
    resource_id: str | None,
    version_id: str | None,
    content_sha256: str,
) -> None:
    freeze = _freeze()
    with pytest.raises(ResourceIdentityFreezeError) as caught:
        resolved_resource_id = freeze.require_resource_id(resource_id)
        freeze.require_resource_version_id(
            resource_id=resolved_resource_id,
            resource_version_id=version_id,
            content_sha256=content_sha256,
        )
    assert str(caught.value) == RESOURCE_REGISTRY_ISSUANCE_REQUIRED


def test_provisioning_refuses_to_mint_when_registry_issuance_is_required() -> None:
    connection = MagicMock()
    scope = ResourceScope.model_validate(
        {
            "tenant": "nexus",
            "collection": "rag_nexus_maths_terminale_gen_specialite",
            "niveau": "terminale",
            "voie": "generale",
            "matiere": "mathematiques",
            "candidat": "scolarise",
            "audience": ["aefe"],
            "visibility": "internal",
            "school_year": "2026-2027",
            "programme_version": "fr-national-2026",
        }
    )

    with pytest.raises(ResourceIdentityFreezeError) as caught:
        create_resource(
            connection,
            run_id=UUID("55555555-5555-4555-8555-555555555555"),
            dedup_key="governed-resource",
            scope=scope,
            resource_registry_issuance_required=True,
        )

    assert str(caught.value) == RESOURCE_REGISTRY_ISSUANCE_REQUIRED
    connection.cursor.assert_not_called()


def _write_snapshot(path: Path) -> str:
    raw = _snapshot().model_dump_json().encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def test_snapshot_cutover_is_optional_only_when_both_inputs_are_absent(
    tmp_path: Path,
) -> None:
    assert load_optional_pinned_resource_identity_freeze(None, None) is None

    snapshot_path = tmp_path / "resource-registry.json"
    digest = _write_snapshot(snapshot_path)
    freeze = load_optional_pinned_resource_identity_freeze(snapshot_path, digest)

    assert freeze is not None
    assert freeze.require_resource_id(
        "11111111-1111-4111-8111-111111111111"
    ) == UUID("11111111-1111-4111-8111-111111111111")


@pytest.mark.parametrize(
    ("path_present", "digest_present"),
    [(True, False), (False, True)],
)
def test_snapshot_cutover_refuses_partial_configuration(
    tmp_path: Path,
    path_present: bool,
    digest_present: bool,
) -> None:
    path = tmp_path / "resource-registry.json"
    digest = _write_snapshot(path)

    with pytest.raises(ResourceIdentityFreezeError, match="atomic"):
        load_optional_pinned_resource_identity_freeze(
            path if path_present else None,
            digest if digest_present else None,
        )


def test_snapshot_cutover_refuses_file_digest_drift(tmp_path: Path) -> None:
    path = tmp_path / "resource-registry.json"
    _write_snapshot(path)

    with pytest.raises(ResourceIdentityFreezeError, match="digest"):
        load_optional_pinned_resource_identity_freeze(path, "b" * 64)
