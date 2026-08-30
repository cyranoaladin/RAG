from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from nexus_contracts import (
    BootstrapChunk,
    BootstrapResourceVersion,
    ResourceRegistryBootstrapPayload,
    seal_resource_registry_bootstrap,
)

from ingestor import resource_registry_bootstrap_cli

SHA_A = "a" * 64
SHA_B = "b" * 64


def _inventory():
    return seal_resource_registry_bootstrap(
        ResourceRegistryBootstrapPayload.model_validate(
            {
                "protocol_version": "1",
                "producer_repository": "cyranoaladin/RAG",
                "producer_commit": SHA_A[:40],
                "package_version": "0.15.0",
                "source_snapshot_sha256": SHA_B,
                "generated_at": datetime(2026, 8, 30, 12, tzinfo=UTC),
                "resources": [
                    BootstrapResourceVersion(
                        resource_id="11111111-1111-4111-8111-111111111111",
                        resource_version_id="22222222-2222-4222-8222-222222222222",
                        content_sha256=SHA_A,
                        rag_artifact_id=SHA_A,
                        size_bytes=42,
                        mime_type="application/pdf",
                        source_label="Programme officiel",
                        source_uri="https://eduscol.education.fr/programme.pdf",
                        rights="officiel_public",
                        official=True,
                        source_kind="eduscol.education.fr",
                        type_doc="programme_officiel",
                        chunks=[
                            BootstrapChunk(
                                chunk_id="chunk-001",
                                locator={"chunk_index": 0, "page": 1},
                            )
                        ],
                    )
                ],
            }
        )
    )


class _ConnectionContext:
    def __enter__(self):
        return object()

    def __exit__(self, *_args: object) -> None:
        return None


class _ReleaseRegistry:
    collections = ("terminale_maths",)


def test_cli_writes_canonical_inventory_without_disclosing_dsn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "inventory.json"
    secret_dsn = "postgresql://operator:super-secret@example.invalid/rag"
    inventory = _inventory()
    monkeypatch.setenv("NEXUS_RESOURCE_EXPORT_DSN", secret_dsn)
    monkeypatch.setattr(
        resource_registry_bootstrap_cli.psycopg,
        "connect",
        lambda dsn: _ConnectionContext() if dsn == secret_dsn else None,
    )
    monkeypatch.setattr(
        resource_registry_bootstrap_cli,
        "export_resource_registry_bootstrap_inventory",
        lambda *_args, **_kwargs: inventory,
    )
    monkeypatch.setattr(
        resource_registry_bootstrap_cli.metadata,
        "version",
        lambda package: "0.15.0" if package == "nexus-contracts" else "",
    )
    monkeypatch.setattr(
        resource_registry_bootstrap_cli,
        "load_release_registry_file",
        lambda path, digest: _ReleaseRegistry()
        if path == tmp_path / "release-registry.json" and digest == SHA_B
        else None,
    )

    result = resource_registry_bootstrap_cli.main(
        [
            "--producer-commit",
            SHA_A[:40],
            "--generated-at",
            "2026-08-30T12:00:00Z",
            "--output",
            str(output),
            "--release-registry-path",
            str(tmp_path / "release-registry.json"),
            "--release-registry-sha256",
            SHA_B,
        ]
    )

    assert result == 0
    assert output.read_bytes().endswith(b"\n")
    assert inventory.inventory_sha256.encode() in output.read_bytes()
    captured = capsys.readouterr()
    assert inventory.inventory_sha256 in captured.out
    assert secret_dsn not in captured.out + captured.err
    assert "super-secret" not in captured.out + captured.err


def test_cli_fails_closed_without_explicit_operator_dsn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("NEXUS_RESOURCE_EXPORT_DSN", raising=False)
    with pytest.raises(SystemExit, match="NEXUS_RESOURCE_EXPORT_DSN"):
        resource_registry_bootstrap_cli.main(
            [
                "--producer-commit",
                SHA_A[:40],
                "--generated-at",
                "2026-08-30T12:00:00Z",
                "--output",
                str(tmp_path / "inventory.json"),
                "--release-registry-path",
                str(tmp_path / "release-registry.json"),
                "--release-registry-sha256",
                SHA_B,
            ]
        )


def test_cli_requires_pinned_release_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NEXUS_RESOURCE_EXPORT_DSN", "postgresql://fixture")
    with pytest.raises(SystemExit):
        resource_registry_bootstrap_cli.main(
            [
                "--producer-commit",
                SHA_A[:40],
                "--generated-at",
                "2026-08-30T12:00:00Z",
                "--output",
                str(tmp_path / "inventory.json"),
            ]
        )
