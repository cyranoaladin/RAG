from __future__ import annotations

import importlib
import sys

import pytest

try:
    from fastapi.testclient import TestClient
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("fastapi is required") from exc


def _load_api(monkeypatch: pytest.MonkeyPatch):
    mod = "src.ingestor.api"
    for m in list(sys.modules):
        if m.startswith("src.ingestor"):
            sys.modules.pop(m)
    monkeypatch.setenv("INGESTOR_API_TOKEN", "tok")
    return importlib.import_module(mod)


def test_rag_query_success(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api(monkeypatch)

    class FakeCollection:
        def query(self, *, query_embeddings=None, n_results=6, where=None):  # noqa: ARG002
            return {
                "ids": [["id1", "id2"]],
                "documents": [["doc1", "doc2"]],
                "metadatas": [[{"source": "s1", "domain": "math"}, {"source": "s2"}]],
                "distances": [[0.1, 0.2]],
            }

    class FakeClient:
        def get_or_create_collection(self, *_, **__):
            return FakeCollection()

    class Emb:
        def __init__(self, *a, **k):  # noqa: ARG002
            pass

        def embed_query(self, q):  # noqa: ARG002
            return [0.0, 1.0, 2.0]

    monkeypatch.setattr(api, "get_chroma_client", lambda: FakeClient())
    monkeypatch.setattr(api, "TimedOllamaEmbeddings", Emb)

    client = TestClient(api.app)
    r = client.post(
        "/rag/query",
        json={
            "query": "hello",
            "top_k": 2,
            "collection": api.COLLECTION_NAME,
            "filters": {"domain": "math", "tags": ["x"], "metadata": {"foo": "bar"}},
        },
        headers={"Authorization": "Bearer tok"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("k") == 2
    assert len(body.get("hits", [])) == 2
    assert body["hits"][0]["metadata"]["source"] == "s1"


def test_rag_query_embedding_404(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api(monkeypatch)

    class FakeCollection:
        def query(self, **_):
            pytest.fail("should not query when embedding fails")

    class FakeClient:
        def get_or_create_collection(self, *_, **__):
            return FakeCollection()

    class BadEmb:
        def __init__(self, *a, **k):  # noqa: ARG002
            pass

        def embed_query(self, q):  # noqa: ARG002
            raise ValueError("HTTP code: 404 not found")

    monkeypatch.setattr(api, "get_chroma_client", lambda: FakeClient())
    monkeypatch.setattr(api, "TimedOllamaEmbeddings", BadEmb)

    client = TestClient(api.app)
    r = client.post(
        "/rag/query",
        json={"query": "x"},
        headers={"Authorization": "Bearer tok"},
    )
    assert r.status_code == 503


@pytest.mark.parametrize("collection", ["anything", "rag_divers"])
def test_rag_query_rejects_forbidden_collection_before_chroma(
    monkeypatch: pytest.MonkeyPatch, collection: str
) -> None:
    api = _load_api(monkeypatch)

    def fail_if_called():
        pytest.fail("Chroma must not be called before collection validation")

    monkeypatch.setattr(api, "get_chroma_client", fail_if_called)

    client = TestClient(api.app)
    r = client.post(
        "/rag/query",
        json={"query": "hello", "collection": collection},
        headers={"Authorization": "Bearer tok"},
    )

    assert r.status_code == 400


def test_rag_query_accepts_legacy_web3_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api(monkeypatch)
    requested_collections: list[str] = []

    class FakeCollection:
        def query(self, *, query_embeddings=None, n_results=6, where=None):  # noqa: ARG002
            return {
                "ids": [["id-web3"]],
                "documents": [["doc-web3"]],
                "metadatas": [[{"source": "s-web3", "domain": "web3"}]],
                "distances": [[0.1]],
            }

    class FakeClient:
        def get_or_create_collection(self, name: str, *_, **__):
            requested_collections.append(name)
            return FakeCollection()

    class Emb:
        def __init__(self, *a, **k):  # noqa: ARG002
            pass

        def embed_query(self, q):  # noqa: ARG002
            return [0.0, 1.0, 2.0]

    monkeypatch.setattr(api, "get_chroma_client", lambda: FakeClient())
    monkeypatch.setattr(api, "TimedOllamaEmbeddings", Emb)

    client = TestClient(api.app)
    r = client.post(
        "/rag/query",
        json={"query": "web3", "collection": "rag_web3"},
        headers={"Authorization": "Bearer tok"},
    )

    assert r.status_code == 200
    assert r.json()["collection"] == "rag_web3"
    assert requested_collections == ["rag_web3"]
