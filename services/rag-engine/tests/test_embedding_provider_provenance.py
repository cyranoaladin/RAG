from __future__ import annotations

import hashlib
import math
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import ingestor.embedding_provider as provider_module
from ingestor.embedding_contract import CANONICAL_EMBED_MODEL
from ingestor.embedding_provider import (
    DEBUG_EMBED_MODEL,
    CallableEmbeddingProvider,
    EmbeddingProviderError,
    VerifiedE5EmbeddingProvider,
    coerce_embedding_provider,
)
from ingestor.governed_publisher_v2 import GovernedArtifact, _insert_chunks
from ingestor.publication_chunking import PublicationChunk


def _vectors(passages: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for index, _passage in enumerate(passages, start=1):
        vector = [0.0] * 1024
        vector[index % 1024] = 1.0
        vectors.append(vector)
    return vectors


def test_bare_callable_is_labeled_debug_not_canonical() -> None:
    provider = coerce_embedding_provider(_vectors)

    assert provider.model_id == DEBUG_EMBED_MODEL
    assert provider.dimension == 1024
    assert provider.verified_artifact is None
    assert provider.inventory_sha256 is None


def test_unverified_callable_cannot_claim_canonical_model() -> None:
    with pytest.raises(EmbeddingProviderError, match="canonical model requires"):
        CallableEmbeddingProvider(
            encoder=_vectors,
            model_id=CANONICAL_EMBED_MODEL,
            dimension=1024,
        )


def test_structural_provider_cannot_claim_canonical_model() -> None:
    class ForgedCanonicalProvider:
        model_id = CANONICAL_EMBED_MODEL
        dimension = 1024
        max_sequence_length = 512
        verified_artifact = Path("/unverified")
        inventory_sha256 = "a" * 64

        def passage_token_count(self, _text: str) -> int:
            return 1

        def encode(self, passages: list[str]) -> list[list[float]]:
            return _vectors(passages)

    with pytest.raises(EmbeddingProviderError, match="canonical model requires"):
        coerce_embedding_provider(ForgedCanonicalProvider())


def test_forged_verified_provider_subclass_cannot_claim_canonical_model() -> None:
    class ForgedVerifiedProvider(VerifiedE5EmbeddingProvider):
        def __init__(self) -> None:
            self.verified_artifact = Path("/unverified")
            self.inventory_sha256 = "a" * 64
            self.max_sequence_length = 512

        def encode(self, passages: list[str]) -> list[list[float]]:
            return _vectors(passages)

    with pytest.raises(EmbeddingProviderError, match="canonical model requires"):
        coerce_embedding_provider(ForgedVerifiedProvider())


@pytest.mark.parametrize(
    "bad_vector",
    (
        [0.0] * 1024,
        [math.nan] + [0.0] * 1023,
        [1.0] * 4,
    ),
)
def test_debug_provider_rejects_invalid_vectors(bad_vector: list[float]) -> None:
    provider = CallableEmbeddingProvider(
        encoder=lambda _passages: [bad_vector],
        model_id=DEBUG_EMBED_MODEL,
        dimension=1024,
    )

    with pytest.raises(EmbeddingProviderError):
        provider.encode(["passage: test"])


def test_debug_provider_rejects_wrong_cardinality() -> None:
    provider = CallableEmbeddingProvider(
        encoder=lambda _passages: [],
        model_id=DEBUG_EMBED_MODEL,
        dimension=1024,
    )

    with pytest.raises(EmbeddingProviderError, match="cardinality"):
        provider.encode(["passage: test"])


def test_chunk_insert_persists_pages_and_actual_provider_model() -> None:
    content = b"publication page-aware"
    artifact = GovernedArtifact(
        content=content,
        content_sha256=hashlib.sha256(content).hexdigest(),
        source_label="Eduscol",
        source_uri="https://eduscol.education.gouv.fr/document.pdf",
        rights="officiel_public",
        official=True,
        source_kind="eduscol",
        type_doc="ressource_officielle",
        mime_detected="application/pdf",
    )
    scope = SimpleNamespace(
        collection="rag_nexus_maths_troisieme_tc",
        niveau="troisieme",
        voie="college",
        audience=("tous",),
        matiere="maths",
        tenant="libre_troisieme",
        candidat="libre",
        visibility="internal",
        school_year="2026-2027",
        programme_version="BOEN_special_11_2018-07-26_aj_2020",
    )
    placement = SimpleNamespace(
        resource_id=uuid4(),
        scope=scope,
        statut_enseignement="tronc_commun",
        domain="mathematiques",
    )
    chunk = PublicationChunk("Un passage borné.", 3, 3)
    vector = [0.0] * 1024
    vector[0] = 1.0

    class Cursor:
        query = ""
        params: tuple[object, ...] = ()

        def execute(self, query: str, params: tuple[object, ...]) -> None:
            self.query = query
            self.params = params

    cursor = Cursor()
    _insert_chunks(
        cursor,
        artifact=artifact,
        placement=placement,
        chunks=(chunk,),
        vectors=(vector,),
        model_id=DEBUG_EMBED_MODEL,
    )

    assert "page_start, page_end" in cursor.query
    assert cursor.params[18:22] == (3, 3, "reviewed", DEBUG_EMBED_MODEL)


def test_verified_e5_provider_is_built_only_after_contract_checks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "e5"
    root.mkdir()
    calls: list[object] = []

    class Tokenizer:
        model_max_length = 512

        def __call__(self, text: str, **kwargs: object) -> dict[str, list[int]]:
            assert kwargs == {"add_special_tokens": True, "truncation": False}
            return {"input_ids": list(range(len(text.split()) + 2))}

    class Model:
        max_seq_length = 512
        tokenizer = Tokenizer()

        def encode(self, passages: list[str], **kwargs: object) -> list[list[float]]:
            calls.append((tuple(passages), kwargs))
            return _vectors(passages)

    monkeypatch.setattr(
        provider_module,
        "verify_embedding_artifact",
        lambda path, *, expected_inventory_sha256: (
            calls.append((path, expected_inventory_sha256)) or path
        ),
    )
    monkeypatch.setattr(
        provider_module,
        "load_embedding_model",
        lambda *, verified_artifact_root: (
            calls.append(verified_artifact_root) or Model()
        ),
    )
    monkeypatch.setattr(
        provider_module,
        "validate_runtime_embedding_contract",
        lambda model, pg_dsn: calls.append((model, pg_dsn)),
    )

    provider = VerifiedE5EmbeddingProvider.from_artifact(
        artifact_root=root,
        inventory_sha256="a" * 64,
        pg_dsn="postgresql://acceptance",
    )

    assert provider.model_id == CANONICAL_EMBED_MODEL
    assert provider.dimension == 1024
    assert provider.max_sequence_length == 512
    assert provider.verified_artifact == root
    assert provider.inventory_sha256 == "a" * 64
    assert provider.passage_token_count("contenu français") == 5
    assert len(provider.encode(["passage: contenu"])) == 1
    assert calls[0] == (root, "a" * 64)


def test_verified_e5_provider_rejects_tokenizer_truncation_risk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "e5"
    root.mkdir()

    class Tokenizer:
        model_max_length = 512

    class Model:
        max_seq_length = 1024
        tokenizer = Tokenizer()

    monkeypatch.setattr(provider_module, "verify_embedding_artifact", lambda *a, **k: root)
    monkeypatch.setattr(provider_module, "load_embedding_model", lambda **k: Model())
    monkeypatch.setattr(
        provider_module, "validate_runtime_embedding_contract", lambda *a, **k: None
    )

    with pytest.raises(EmbeddingProviderError, match="sequence length"):
        VerifiedE5EmbeddingProvider.from_artifact(
            artifact_root=root,
            inventory_sha256="a" * 64,
            pg_dsn="postgresql://acceptance",
        )


def test_verified_e5_provider_rejects_oversized_passage_before_model_encode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "e5"
    root.mkdir()
    model_encode_calls: list[object] = []

    class Tokenizer:
        model_max_length = 512

        def __call__(self, text: str, **kwargs: object) -> dict[str, list[int]]:
            assert kwargs == {"add_special_tokens": True, "truncation": False}
            token_count = 513 if text == "passage: oversized" else 4
            return {"input_ids": list(range(token_count))}

    class Model:
        max_seq_length = 512
        tokenizer = Tokenizer()

        def encode(self, passages: list[str], **kwargs: object) -> list[list[float]]:
            model_encode_calls.append((passages, kwargs))
            return _vectors(passages)

    monkeypatch.setattr(provider_module, "verify_embedding_artifact", lambda *a, **k: root)
    monkeypatch.setattr(provider_module, "load_embedding_model", lambda **k: Model())
    monkeypatch.setattr(
        provider_module, "validate_runtime_embedding_contract", lambda *a, **k: None
    )
    provider = VerifiedE5EmbeddingProvider.from_artifact(
        artifact_root=root,
        inventory_sha256="a" * 64,
        pg_dsn="postgresql://acceptance",
    )

    with pytest.raises(EmbeddingProviderError, match="exceeds model sequence length"):
        provider.encode(["passage: oversized"])

    assert model_encode_calls == []
