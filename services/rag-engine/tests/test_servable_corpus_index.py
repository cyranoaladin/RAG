from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
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
                        "retrieval_scope": {
                            "artifact_version": "3",
                            "scope_id": "aria_maths_terminale_v1",
                            "status": "eligible_for_promotion",
                            "source_sha256": SHA_B,
                            "target_policy": {
                                "tenant": "nexus", "niveau": "terminale",
                                "voie": "generale", "matiere": "mathematiques",
                                "statut_enseignement": "specialite",
                                "audiences": ["aefe", "libre"],
                                "candidates": ["scolarise", "aefe", "libre"],
                                "roles": ["student"],
                            },
                            "evidence_subject": {
                                "collection": "rag_nexus_maths_terminale_gen_specialite",
                                "tenant": "nexus", "niveau": "terminale",
                                "voie": "generale", "matiere": "mathematiques",
                                "statut_enseignement": "specialite",
                                "candidat": "scolarise", "audiences": ["aefe", "tous"],
                                "visibility": "public", "rights": ["officiel_public"],
                                "school_year": "2026-2027",
                                "programme_version": "fr-national-2026",
                            },
                        },
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


def test_index_preserves_n_minus_one_with_its_immutable_registry_binding(
    tmp_path: Path,
) -> None:
    active = _manifest(version="2026-08-30.2", registry_sha=SHA_A)
    previous = _manifest(version="2026-08-30.1", registry_sha=SHA_B)
    index = build_servable_corpus_index(
        active_manifest=active,
        previous_manifest=previous,
        previous_retire_at=NOW + timedelta(days=7),
        generated_at=NOW,
        producer_repository="cyranoaladin/RAG",
        producer_commit=SHA_A[:40],
    )

    publish_servable_corpus_bundle(tmp_path, index=index, manifests=[active, previous])
    repository = FilesystemServableCorpusRepository(
        directory=tmp_path,
        expected_index_sha256=index.index_sha256,
        now=lambda: NOW,
    )

    assert index.resource_registry_sha256 == active.resource_registry_sha256
    assert (
        repository.manifest(previous.manifest_sha256).resource_registry_sha256
        == previous.resource_registry_sha256
    )


def test_index_rejects_invalid_retirement() -> None:
    active = _manifest(version="2026-08-30.2")
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


def test_publication_writes_byte_identical_legacy_and_nexus_runtime_manifest_names(
    tmp_path: Path,
) -> None:
    _index, active, previous = _publish(tmp_path)

    for manifest in (active, previous):
        legacy = tmp_path / "manifests" / f"{manifest.manifest_sha256}.json"
        nexus_runtime = (
            tmp_path / "manifests" / f"{manifest.manifest_sha256}.aria-rag-manifest"
        )
        assert legacy.is_file()
        assert nexus_runtime.is_file()
        assert nexus_runtime.read_bytes() == legacy.read_bytes()


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

    active_path.write_bytes(
        tmp_path.joinpath(
            "manifests", f"{active.manifest_sha256}.aria-rag-manifest"
        ).read_bytes()
    )
    runtime_path = (
        tmp_path / "manifests" / f"{active.manifest_sha256}.aria-rag-manifest"
    )
    runtime_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ServableCorpusRepositoryError, match="immutable"):
        publish_servable_corpus_bundle(
            tmp_path,
            index=index,
            manifests=[active, previous],
        )


def test_private_http_router_exposes_only_index_and_digest_addressed_manifest() -> None:
    from ingestor.servable_corpus_api import router

    paths = {(route.path, tuple(sorted(route.methods or set()))) for route in router.routes}
    assert paths == {
        ("/corpora/servable/v1", ("GET",)),
        ("/corpora/servable/v1/{manifest_sha256}", ("GET",)),
    }


def _servable_client() -> TestClient:
    from ingestor.servable_corpus_api import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_private_http_surface_requires_bff_and_fails_closed_without_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "servable-corpus-bff-token-at-least-32-bytes"
    monkeypatch.setenv("RAG_BFF_SERVICE_TOKEN", token)
    monkeypatch.delenv("RAG_SERVABLE_CORPUS_DIRECTORY", raising=False)
    monkeypatch.delenv("RAG_SERVABLE_CORPUS_INDEX_SHA256", raising=False)

    unauthenticated = _servable_client().get("/corpora/servable/v1")
    unavailable = _servable_client().get(
        "/corpora/servable/v1",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert unauthenticated.status_code == 401
    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": "servable corpus unavailable"}


def test_private_http_surface_serves_only_pinned_digest_addressed_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "servable-corpus-bff-token-at-least-32-bytes"
    index, active, _previous = _publish(tmp_path)
    monkeypatch.setenv("RAG_BFF_SERVICE_TOKEN", token)
    monkeypatch.setenv("RAG_SERVABLE_CORPUS_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("RAG_SERVABLE_CORPUS_INDEX_SHA256", index.index_sha256)
    headers = {"Authorization": f"Bearer {token}"}

    client = _servable_client()
    index_response = client.get("/corpora/servable/v1", headers=headers)
    manifest_response = client.get(
        f"/corpora/servable/v1/{active.manifest_sha256}",
        headers=headers,
    )
    unknown_response = client.get(
        f"/corpora/servable/v1/{'f' * 64}",
        headers=headers,
    )

    assert index_response.status_code == 200
    assert index_response.json()["index_sha256"] == index.index_sha256
    assert manifest_response.status_code == 200
    assert manifest_response.json()["manifest_sha256"] == active.manifest_sha256
    assert unknown_response.status_code == 404
    assert unknown_response.json() == {"detail": "manifest unavailable"}
