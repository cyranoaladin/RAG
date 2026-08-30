from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from nexus_contracts import (
    RetrievalNeed,
    RetrievalRequest,
    ServableCorpusManifestPayload,
    StudentProfile,
    seal_servable_corpus_manifest,
)

from ingestor.retrieval_scope_v2 import RetrievalScopeError
from ingestor.retrieval_v2_endpoint import (
    SearchV2Hit,
    _canonical_retrieval_request_sha256,
    _require_manifest_bound_corpus,
    _to_manifest_bound_retrieval_result,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
RESOURCE_ID = "11111111-1111-4111-8111-111111111111"
RESOURCE_VERSION_ID = "22222222-2222-4222-8222-222222222222"


def _manifest():
    return seal_servable_corpus_manifest(
        ServableCorpusManifestPayload.model_validate(
            {
                "protocol_version": "1",
                "manifest_version": "aria-servable-corpus-v1",
                "resource_registry_version": "aria-resource-registry-v1",
                "resource_registry_sha256": SHA_B,
                "producer_repository": "cyranoaladin/RAG",
                "producer_commit": SHA_A[:40],
                "generated_at": "2026-08-30T12:00:00Z",
                "corpora": [
                    {
                        "corpus_id": "aria-maths-terminale",
                        "corpus_version_id": "2026-08-30.1",
                        "academic_year": "2026-2027",
                        "curriculum_version": "fr-national-2026",
                        "physical_collection": "rag_nexus_maths_terminale_gen_specialite",
                        "scope_id": "scope-maths-terminale-v1",
                        "scope_sha256": SHA_A,
                        "resources": [
                            {
                                "resource_id": RESOURCE_ID,
                                "resource_version_id": RESOURCE_VERSION_ID,
                                "content_sha256": SHA_A,
                                "chunks": [
                                    {
                                        "chunk_id": "chunk-001",
                                        "locator": {
                                            "chunk_index": 0,
                                            "page_start": 2,
                                            "page_end": 4,
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )
    )


def _payload() -> RetrievalRequest:
    manifest = _manifest()
    return RetrievalRequest(
        student_profile=StudentProfile.model_validate(
            {
                "niveau": "terminale",
                "voie": "generale",
                "matieres": ["mathematiques"],
                "statut_enseignement": "specialite",
                "candidat": "scolarise",
                "school_year": "2026-2027",
                "zone": "aefe",
            }
        ),
        need=RetrievalNeed(intent="context", query="Suites et limites"),
        manifest_sha256=manifest.manifest_sha256,
        corpus_id="aria-maths-terminale",
        corpus_version_id="2026-08-30.1",
    )


class _Repository:
    def resolve_corpus(self, **kwargs):
        manifest = _manifest()
        assert kwargs == {
            "manifest_sha256": manifest.manifest_sha256,
            "corpus_id": "aria-maths-terminale",
            "corpus_version_id": "2026-08-30.1",
        }
        return manifest.corpora[0]


def _verified(payload: RetrievalRequest, **overrides: object):
    envelope = {
        "manifest_sha256": payload.manifest_sha256,
        "request_sha256": _canonical_retrieval_request_sha256(payload),
        "allowed_collections": ["rag_nexus_maths_terminale_gen_specialite"],
    }
    envelope.update(overrides)
    return SimpleNamespace(envelope=SimpleNamespace(**envelope))


def _hit(**overrides: object) -> SearchV2Hit:
    values: dict[str, object] = {
        "chunk_id": "chunk-001",
        "doc_id": SHA_A,
        "source_label": "Programme officiel",
        "source_uri": "https://eduscol.education.fr/programme.pdf",
        "rights": "officiel_public",
        "type_doc": "programme_officiel",
        "review_status": "reviewed",
        "artifact_id": SHA_A,
        "content_sha256": SHA_A,
        "placement_id": "c" * 64,
        "placement_source_scope": "release-scope",
        "placement_source_id": "source-id",
        "placement_source_path": "governed/source.pdf",
        "page": 2,
        "preview": "Extrait vérifié",
        "dense_score": 0.8,
        "lexical_score": 0.7,
        "rrf_score": 0.1,
        "rerank_score": 2.2,
        "mmr_score": 0.6,
        "score_final": 0.9,
    }
    values.update(overrides)
    return SearchV2Hit.model_validate(values)


def test_manifest_bound_request_requires_signed_request_digest_and_collection() -> None:
    payload = _payload()
    corpus = _require_manifest_bound_corpus(payload, _verified(payload), _Repository())
    assert corpus.physical_collection == "rag_nexus_maths_terminale_gen_specialite"

    for overrides in (
        {"request_sha256": SHA_B},
        {"manifest_sha256": SHA_B},
        {"allowed_collections": ["rag_nexus_nsi_terminale_specialite"]},
    ):
        with pytest.raises(RetrievalScopeError, match="forbidden"):
            _require_manifest_bound_corpus(payload, _verified(payload, **overrides), _Repository())


def test_manifest_bound_result_uses_only_verified_resource_version_and_locator() -> None:
    manifest = _manifest()
    result = _to_manifest_bound_retrieval_result(
        _hit(),
        manifest.corpora[0],
        manifest_sha256=manifest.manifest_sha256,
        include_citation=True,
    )

    assert str(result.resource_id) == RESOURCE_ID
    assert str(result.resource_version_id) == RESOURCE_VERSION_ID
    assert result.content_sha256 == SHA_A
    assert result.locator.model_dump(exclude_none=True) == {
        "chunk_index": 0,
        "page_start": 2,
        "page_end": 4,
    }
    assert result.corpus_id == "aria-maths-terminale"
    assert result.corpus_version_id == "2026-08-30.1"
    assert result.manifest_sha256 == manifest.manifest_sha256
    assert result.citation is not None


@pytest.mark.parametrize(
    "overrides",
    [
        {"chunk_id": "unknown-chunk"},
        {"artifact_id": SHA_B, "content_sha256": SHA_B, "doc_id": SHA_B},
    ],
)
def test_manifest_bound_result_rejects_unknown_or_mismatched_hit(
    overrides: dict[str, str]
) -> None:
    manifest = _manifest()
    with pytest.raises(HTTPException) as caught:
        _to_manifest_bound_retrieval_result(
            _hit(**overrides),
            manifest.corpora[0],
            manifest_sha256=manifest.manifest_sha256,
            include_citation=True,
        )
    assert caught.value.status_code == 503
    assert caught.value.detail == "retrieval evidence unavailable"


def test_search_v2_manifest_mode_uses_resolved_collection_and_returns_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor import retrieval_v2_endpoint as endpoint

    payload = _payload()
    verified = _verified(payload)
    calls: dict[str, object] = {}
    monkeypatch.setattr(endpoint, "_require_retrieval_identity", lambda *_args, **_kwargs: verified)
    monkeypatch.setattr(endpoint, "_servable_corpus_repository", lambda: _Repository())
    monkeypatch.setattr(endpoint, "load_collection_config", lambda: {})
    monkeypatch.setattr(endpoint, "_check_retrievable", lambda collection, *_args: calls.setdefault("checked", collection))
    monkeypatch.setattr(
        endpoint,
        "build_server_retrieval_scope",
        lambda _verified, *, collection, collection_config: SimpleNamespace(
            filter_digest=SHA_A,
            collection=collection,
        ),
    )
    monkeypatch.setattr(endpoint, "_require_retrieval_profile_match", lambda *_args: None)

    def adapt(_payload, *, collection, collection_config):
        calls["adapted"] = collection
        return SimpleNamespace(
            query="Suites et limites",
            nexus_collection=collection,
            top_k=8,
            include_citations=True,
            warnings=(),
        )

    monkeypatch.setattr(endpoint, "adapt_retrieval_request", adapt)
    monkeypatch.setattr(
        endpoint,
        "_retrieve_endpoint_hits",
        lambda query, collection, top_k, scope: [
            _hit()
        ],
    )

    response = endpoint.search_v2(payload, SimpleNamespace())

    assert calls == {
        "checked": "rag_nexus_maths_terminale_gen_specialite",
        "adapted": "rag_nexus_maths_terminale_gen_specialite",
    }
    assert len(response.results) == 1
    assert str(response.results[0].resource_version_id) == RESOURCE_VERSION_ID
