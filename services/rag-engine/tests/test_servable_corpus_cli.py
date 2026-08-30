from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from nexus_contracts import (
    ResourceRegistryBootstrapPayload,
    ResourceRegistrySnapshotPayload,
    ServableCorpusIndex,
    ServableCorpusManifest,
    seal_resource_registry_bootstrap,
    seal_resource_registry_snapshot,
)
from nexus_contracts.canonical_json import canonical_model_bytes

from ingestor.servable_corpus_cli import ServableCorpusCliError, build_and_publish_bundle

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64


def _write(path: Path, content: bytes) -> str:
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _inputs(tmp_path: Path) -> tuple[Path, str, Path, str, Path, str]:
    inventory = seal_resource_registry_bootstrap(
        ResourceRegistryBootstrapPayload.model_validate(
            {
                "protocol_version": "1",
                "producer_repository": "cyranoaladin/RAG",
                "producer_commit": SHA_A[:40],
                "package_version": "0.15.0",
                "source_snapshot_sha256": SHA_B,
                "generated_at": NOW,
                "resources": [
                    {
                        "resource_id": "11111111-1111-4111-8111-111111111111",
                        "resource_version_id": "22222222-2222-4222-8222-222222222222",
                        "content_sha256": SHA_A,
                        "rag_artifact_id": SHA_A,
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
                        "chunks": [{"chunk_id": "chunk-001", "locator": {"page": 1}}],
                    }
                ],
            }
        )
    )
    registry = seal_resource_registry_snapshot(
        ResourceRegistrySnapshotPayload.model_validate(
            {
                "protocol_version": "1",
                "registry_version": "aria-resource-registry-v1",
                "producer_repository": "cyranoaladin/nexus-project_v0",
                "producer_commit": SHA_B[:40],
                "generated_at": NOW,
                "bootstrap_inventory_sha256": inventory.inventory_sha256,
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
    specs = (
        b'[{"academic_year":"2026-2027","corpus_id":"aria-maths-terminale",'
        b'"corpus_version_id":"2026-08-30.1","curriculum_version":"fr-national-2026",'
        b'"physical_collection":"rag_nexus_maths_terminale_gen_specialite",'
        b'"scope_id":"scope-maths-terminale-v1","scope_sha256":"'
        + SHA_B.encode()
        + b'"}]\n'
    )
    inventory_path = tmp_path / "inventory.json"
    registry_path = tmp_path / "registry.json"
    specs_path = tmp_path / "specs.json"
    return (
        inventory_path,
        _write(inventory_path, canonical_model_bytes(inventory) + b"\n"),
        registry_path,
        _write(registry_path, canonical_model_bytes(registry) + b"\n"),
        specs_path,
        _write(specs_path, specs),
    )


def test_cli_builder_publishes_digest_addressed_manifest_and_pinned_index(
    tmp_path: Path,
) -> None:
    inventory_path, inventory_file_sha, registry_path, registry_file_sha, specs_path, specs_sha = _inputs(tmp_path)
    output = tmp_path / "bundle"

    index, manifest = build_and_publish_bundle(
        resource_inventory_path=inventory_path,
        expected_resource_inventory_file_sha256=inventory_file_sha,
        resource_registry_path=registry_path,
        expected_resource_registry_file_sha256=registry_file_sha,
        corpus_specs_path=specs_path,
        expected_corpus_specs_file_sha256=specs_sha,
        manifest_version="aria-servable-corpus-2026-08-30.1",
        producer_commit=SHA_A[:40],
        generated_at=NOW,
        output_directory=output,
    )

    assert ServableCorpusIndex.model_validate_json(
        (output / "servable-corpus-index-v1.json").read_bytes()
    ) == index
    assert ServableCorpusManifest.model_validate_json(
        (output / "manifests" / f"{manifest.manifest_sha256}.json").read_bytes()
    ) == manifest
    assert index.resource_registry_sha256 == manifest.resource_registry_sha256


def test_cli_builder_refuses_any_unpinned_or_changed_input(tmp_path: Path) -> None:
    inventory_path, inventory_file_sha, registry_path, registry_file_sha, specs_path, specs_sha = _inputs(tmp_path)
    specs_path.write_bytes(specs_path.read_bytes() + b" ")

    with pytest.raises(ServableCorpusCliError, match="corpus specs file digest"):
        build_and_publish_bundle(
            resource_inventory_path=inventory_path,
            expected_resource_inventory_file_sha256=inventory_file_sha,
            resource_registry_path=registry_path,
            expected_resource_registry_file_sha256=registry_file_sha,
            corpus_specs_path=specs_path,
            expected_corpus_specs_file_sha256=specs_sha,
            manifest_version="aria-servable-corpus-2026-08-30.1",
            producer_commit=SHA_A[:40],
            generated_at=NOW,
            output_directory=tmp_path / "bundle",
        )
