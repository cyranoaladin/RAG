"""Registre de révocation gouverné — exigé en production, fail-closed."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor.ingestion_control.revocation_registry import (  # noqa: E402
    RevocationRegistryError,
    load_revocation_registry,
    load_shared_authorization_revocations,
    require_revocation_registry_matches_manifest,
)


def _write_registry(path: Path, payload: object) -> str:
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_loads_an_empty_revocation_registry(tmp_path: Path) -> None:
    path = tmp_path / "revocation-registry.json"
    digest = _write_registry(path, {"registry_version": "1", "revoked": []})

    registry = load_revocation_registry(path, expected_sha256=digest)

    assert registry.revoked_authorization_ids == frozenset()
    assert registry.revoked_publication_attestation_ids == frozenset()
    assert registry.is_revoked(authorization_id="LOT41A-V2:anything") is False


def test_loads_revoked_authorization_and_attestation_ids(tmp_path: Path) -> None:
    path = tmp_path / "revocation-registry.json"
    digest = _write_registry(
        path,
        {
            "registry_version": "1",
            "revoked": [
                {"kind": "authorization", "id": "LOT41A-V2:revoked-1"},
                {
                    "kind": "publication_attestation",
                    "id": "11111111-1111-1111-1111-111111111111",
                },
            ],
        },
    )

    registry = load_revocation_registry(path, expected_sha256=digest)

    assert registry.is_revoked(authorization_id="LOT41A-V2:revoked-1") is True
    assert registry.is_revoked(authorization_id="LOT41A-V2:not-revoked") is False
    assert (
        registry.is_revoked(
            publication_attestation_id="11111111-1111-1111-1111-111111111111"
        )
        is True
    )


def test_refuses_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RevocationRegistryError, match="unavailable"):
        load_revocation_registry(tmp_path / "missing.json", expected_sha256="0" * 64)


def test_refuses_digest_drift(tmp_path: Path) -> None:
    path = tmp_path / "revocation-registry.json"
    _write_registry(path, {"registry_version": "1", "revoked": []})

    with pytest.raises(RevocationRegistryError, match="digest differs"):
        load_revocation_registry(path, expected_sha256="0" * 64)


def test_refuses_malformed_expected_digest(tmp_path: Path) -> None:
    path = tmp_path / "revocation-registry.json"
    _write_registry(path, {"registry_version": "1", "revoked": []})

    with pytest.raises(RevocationRegistryError, match="lowercase 64-hex"):
        load_revocation_registry(path, expected_sha256="not-a-digest")


def test_refuses_unsupported_registry_version(tmp_path: Path) -> None:
    path = tmp_path / "revocation-registry.json"
    digest = _write_registry(path, {"registry_version": "999", "revoked": []})

    with pytest.raises(RevocationRegistryError, match="version is unsupported"):
        load_revocation_registry(path, expected_sha256=digest)


def test_refuses_malformed_entry(tmp_path: Path) -> None:
    path = tmp_path / "revocation-registry.json"
    digest = _write_registry(
        path,
        {"registry_version": "1", "revoked": [{"kind": "authorization"}]},
    )

    with pytest.raises(RevocationRegistryError, match="malformed"):
        load_revocation_registry(path, expected_sha256=digest)


def test_refuses_unsupported_kind(tmp_path: Path) -> None:
    path = tmp_path / "revocation-registry.json"
    digest = _write_registry(
        path,
        {
            "registry_version": "1",
            "revoked": [{"kind": "something_else", "id": "x"}],
        },
    )

    with pytest.raises(RevocationRegistryError, match="kind is unsupported"):
        load_revocation_registry(path, expected_sha256=digest)


def test_require_matches_manifest_accepts_identical_digest(tmp_path: Path) -> None:
    path = tmp_path / "revocation-registry.json"
    digest = _write_registry(path, {"registry_version": "1", "revoked": []})
    registry = load_revocation_registry(path, expected_sha256=digest)

    require_revocation_registry_matches_manifest(
        registry, manifest_revocation_registry_digest=digest
    )


def test_require_matches_manifest_refuses_drift(tmp_path: Path) -> None:
    path = tmp_path / "revocation-registry.json"
    digest = _write_registry(path, {"registry_version": "1", "revoked": []})
    registry = load_revocation_registry(path, expected_sha256=digest)

    with pytest.raises(RevocationRegistryError, match="does not match"):
        require_revocation_registry_matches_manifest(
            registry, manifest_revocation_registry_digest="9" * 64
        )


def test_v2_loads_only_the_shared_authorization_revocation_schema(tmp_path: Path) -> None:
    path = tmp_path / "revocations.json"
    digest = _write_registry(
        path,
        {
            "protocol_version": "NEXUS-AUTHORIZATION-REVOCATIONS-V1",
            "revoked_authorization_ids": ["auth-b", "auth-a"],
        },
    )

    registry = load_shared_authorization_revocations(path, expected_sha256=digest)

    assert registry.revoked_authorization_ids == frozenset({"auth-a", "auth-b"})
    assert registry.revoked_publication_attestation_ids == frozenset()


def test_v2_refuses_the_legacy_runtime_revocation_schema(tmp_path: Path) -> None:
    path = tmp_path / "legacy.json"
    digest = _write_registry(path, {"registry_version": "1", "revoked": []})

    with pytest.raises(RevocationRegistryError, match="REVOCATION_REGISTRY_INVALID"):
        load_shared_authorization_revocations(path, expected_sha256=digest)


def test_legacy_loader_refuses_the_shared_v2_schema(tmp_path: Path) -> None:
    path = tmp_path / "shared.json"
    digest = _write_registry(
        path,
        {
            "protocol_version": "NEXUS-AUTHORIZATION-REVOCATIONS-V1",
            "revoked_authorization_ids": [],
        },
    )

    with pytest.raises(RevocationRegistryError, match="version is unsupported"):
        load_revocation_registry(path, expected_sha256=digest)
