from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from nexus_contracts import (
    ServableCorpusIndex,
    ServableCorpusManifest,
    ServableCorpusManifestPayload,
    seal_servable_corpus_manifest,
)

from ingestor.servable_corpus_index import (
    FilesystemServableCorpusRepository,
    ServableCorpusRepositoryError,
    build_servable_corpus_index,
    publish_servable_corpus_bundle,
)

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64


def _manifest(*, version: str, registry_sha: str = SHA_A) -> ServableCorpusManifest:
    return seal_servable_corpus_manifest(
        ServableCorpusManifestPayload.model_validate(
            {
                "protocol_version": "1",
                "manifest_version": version,
                "resource_registry_version": "aria-resource-registry-v1",
                "resource_registry_sha256": registry_sha,
                "producer_repository": "cyranoaladin/RAG",
                "producer_commit": SHA_B[:40],
                "generated_at": NOW,
                "corpora": [
                    {
                        "corpus_id": "aria-maths-terminale",
                        "corpus_version_id": version,
                        "academic_year": "2026-2027",
                        "curriculum_version": "fr-national-2026",
                        "physical_collection": "rag_nexus_maths_terminale_gen_specialite",
                        "scope_id": "scope-maths-terminale-v1",
                        "scope_sha256": SHA_B,
                        "resources": [
                            {
                                "resource_id": "11111111-1111-4111-8111-111111111111",
                                "resource_version_id": "22222222-2222-4222-8222-222222222222",
                                "content_sha256": SHA_A,
                                "chunks": [
                                    {"chunk_id": "chunk-001", "locator": {"page": 1}}
                                ],
                            }
                        ],
                    }
                ],
            }
        )
    )


def test_index_supports_active_and_unretired_n_minus_one_only() -> None:
    active = _manifest(version="2026-08-30.2")
    previous = _manifest(version="2026-08-30.1")
    index = build_servable_corpus_index(
        active_manifest=active,
        previous_manifest=previous,
        previous_retire_at=NOW + timedelta(days=7),
        generated_at=NOW,
        producer_repository="cyranoaladin/RAG",
        producer_commit=SHA_A[:40],
    )

    assert index.active_manifest_sha256 == active.manifest_sha256
    assert len(index.supported_manifests) == 2
    assert index.index_sha256 == index.compute_sha256()


def test_index_rejects_registry_drift_or_invalid_retirement() -> None:
    active = _manifest(version="2026-08-30.2")
    with pytest.raises(ServableCorpusRepositoryError, match="registry"):
        build_servable_corpus_index(
            active_manifest=active,
            previous_manifest=_manifest(version="2026-08-30.1", registry_sha=SHA_B),
            previous_retire_at=NOW + timedelta(days=7),
            generated_at=NOW,
            producer_repository="cyranoaladin/RAG",
            producer_commit=SHA_A[:40],
        )
    with pytest.raises(ServableCorpusRepositoryError, match="retire"):
        build_servable_corpus_index(
            active_manifest=active,
            previous_manifest=_manifest(version="2026-08-30.1"),
            previous_retire_at=NOW,
            generated_at=NOW,
            producer_repository="cyranoaladin/RAG",
            producer_commit=SHA_A[:40],
        )


def _publish(directory: Path) -> tuple[ServableCorpusIndex, ServableCorpusManifest, ServableCorpusManifest]:
    active = _manifest(version="2026-08-30.2")
    previous = _manifest(version="2026-08-30.1")
    index = build_servable_corpus_index(
        active_manifest=active,
        previous_manifest=previous,
        previous_retire_at=NOW + timedelta(days=7),
        generated_at=NOW,
        producer_repository="cyranoaladin/RAG",
        producer_commit=SHA_A[:40],
    )
    publish_servable_corpus_bundle(directory, index=index, manifests=[active, previous])
    return index, active, previous


def test_repository_resolves_digest_corpus_version_and_retirement(tmp_path: Path) -> None:
    index, active, previous = _publish(tmp_path)
    repository = FilesystemServableCorpusRepository(
        directory=tmp_path,
        expected_index_sha256=index.index_sha256,
        now=lambda: NOW,
    )

    assert repository.index() == index
    assert repository.manifest(active.manifest_sha256) == active
    resolved = repository.resolve_corpus(
        manifest_sha256=previous.manifest_sha256,
        corpus_id="aria-maths-terminale",
        corpus_version_id="2026-08-30.1",
    )
    assert resolved.physical_collection == "rag_nexus_maths_terminale_gen_specialite"

    retired = FilesystemServableCorpusRepository(
        directory=tmp_path,
        expected_index_sha256=index.index_sha256,
        now=lambda: NOW + timedelta(days=8),
    )
    with pytest.raises(ServableCorpusRepositoryError, match="retired"):
        retired.manifest(previous.manifest_sha256)


def test_repository_refuses_unknown_n_minus_two_tamper_and_overwrite(tmp_path: Path) -> None:
    index, active, previous = _publish(tmp_path)
    repository = FilesystemServableCorpusRepository(
        directory=tmp_path,
        expected_index_sha256=index.index_sha256,
        now=lambda: NOW,
    )
    with pytest.raises(ServableCorpusRepositoryError, match="supported"):
        repository.manifest("f" * 64)

    active_path = tmp_path / "manifests" / f"{active.manifest_sha256}.json"
    active_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ServableCorpusRepositoryError, match="manifest"):
        repository.manifest(active.manifest_sha256)

    with pytest.raises(ServableCorpusRepositoryError, match="immutable"):
        publish_servable_corpus_bundle(
            tmp_path,
            index=index,
            manifests=[active, previous],
        )
