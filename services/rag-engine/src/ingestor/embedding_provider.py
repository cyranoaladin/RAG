"""Providers d'embedding avec provenance explicite pour la publication."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from nexus_contracts.embedding_utils import format_passage

try:
    from .embedding_contract import (
        CANONICAL_EMBED_DIM,
        CANONICAL_EMBED_MODEL,
        load_embedding_model,
        validate_runtime_embedding_contract,
        verify_embedding_artifact,
    )
except ImportError:  # image Docker aplatie
    from embedding_contract import (  # type: ignore[no-redef]
        CANONICAL_EMBED_DIM,
        CANONICAL_EMBED_MODEL,
        load_embedding_model,
        validate_runtime_embedding_contract,
        verify_embedding_artifact,
    )

DEBUG_EMBED_MODEL = "debug/deterministic-1024"


class EmbeddingProviderError(RuntimeError):
    """Le provider ne prouve pas l'identité ou la validité de ses vecteurs."""


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Autorité unique de tokenisation, encodage et provenance."""

    model_id: str
    dimension: int
    max_sequence_length: int
    verified_artifact: Path | None
    inventory_sha256: str | None

    def passage_token_count(self, text: str) -> int: ...

    def encode(self, passages: Sequence[str]) -> Sequence[Sequence[float]]: ...


def _validated_vectors(
    encoded: Sequence[Sequence[float]],
    *,
    expected_cardinality: int,
    dimension: int,
) -> tuple[tuple[float, ...], ...]:
    vectors = tuple(tuple(float(value) for value in row) for row in encoded)
    if len(vectors) != expected_cardinality:
        raise EmbeddingProviderError("embedding cardinality mismatch")
    for vector in vectors:
        if len(vector) != dimension:
            raise EmbeddingProviderError("embedding dimension mismatch")
        if not all(math.isfinite(value) for value in vector):
            raise EmbeddingProviderError("embedding contains a non-finite value")
        if not any(value != 0.0 for value in vector):
            raise EmbeddingProviderError("embedding vector must be non-zero")
    return vectors


class CallableEmbeddingProvider:
    """Adaptateur de test explicite : un callable nu reste toujours debug."""

    def __init__(
        self,
        *,
        encoder: Callable[[Sequence[str]], Sequence[Sequence[float]]],
        model_id: str = DEBUG_EMBED_MODEL,
        dimension: int = 1024,
        max_sequence_length: int = 512,
        token_counter: Callable[[str], int] | None = None,
    ) -> None:
        if model_id == CANONICAL_EMBED_MODEL:
            raise EmbeddingProviderError(
                "canonical model requires a verified immutable artifact"
            )
        if not model_id.strip() or dimension <= 0 or max_sequence_length <= 0:
            raise EmbeddingProviderError("invalid debug embedding provider contract")
        self._encoder = encoder
        self._token_counter = token_counter
        self.model_id = model_id
        self.dimension = dimension
        self.max_sequence_length = max_sequence_length
        self.verified_artifact: Path | None = None
        self.inventory_sha256: str | None = None

    def passage_token_count(self, text: str) -> int:
        passage = format_passage(text)
        if self._token_counter is not None:
            count = int(self._token_counter(passage))
        else:
            # Compteur déterministe de test, conservateur sur le préfixe E5.
            count = len(passage.split()) + 2
        if count <= 0:
            raise EmbeddingProviderError("token counter returned an invalid count")
        return count

    def encode(self, passages: Sequence[str]) -> Sequence[Sequence[float]]:
        return _validated_vectors(
            self._encoder(passages),
            expected_cardinality=len(passages),
            dimension=self.dimension,
        )


class VerifiedE5EmbeddingProvider:
    """Provider canonique obtenu uniquement par les verifiers existants."""

    model_id = CANONICAL_EMBED_MODEL
    dimension = CANONICAL_EMBED_DIM

    def __init__(
        self,
        *,
        model: Any,
        verified_artifact: Path,
        inventory_sha256: str,
        max_sequence_length: int,
        _verified: object,
    ) -> None:
        if _verified is not _VERIFIED_PROVIDER_TOKEN:
            raise EmbeddingProviderError(
                "canonical model requires a verified immutable artifact"
            )
        self._model = model
        self.verified_artifact = verified_artifact
        self.inventory_sha256 = inventory_sha256
        self.max_sequence_length = max_sequence_length

    @classmethod
    def from_artifact(
        cls,
        *,
        artifact_root: Path,
        inventory_sha256: str,
        pg_dsn: str,
    ) -> VerifiedE5EmbeddingProvider:
        verified = verify_embedding_artifact(
            artifact_root,
            expected_inventory_sha256=inventory_sha256,
        )
        model = load_embedding_model(verified_artifact_root=verified)
        validate_runtime_embedding_contract(model, pg_dsn)
        tokenizer = getattr(model, "tokenizer", None)
        if tokenizer is None:
            raise EmbeddingProviderError(
                "canonical tokenizer sequence length is unavailable"
            )
        try:
            model_limit = int(model.max_seq_length)
            tokenizer_limit = int(tokenizer.model_max_length)
        except (TypeError, ValueError, AttributeError) as exc:
            raise EmbeddingProviderError(
                "canonical tokenizer sequence length is unavailable"
            ) from exc
        if (
            model_limit <= 0
            or tokenizer_limit <= 0
            or model_limit > tokenizer_limit
            or model_limit > 100_000
        ):
            raise EmbeddingProviderError(
                "canonical tokenizer sequence length is inconsistent"
            )
        return cls(
            model=model,
            verified_artifact=verified,
            inventory_sha256=inventory_sha256,
            max_sequence_length=model_limit,
            _verified=_VERIFIED_PROVIDER_TOKEN,
        )

    def passage_token_count(self, text: str) -> int:
        passage = format_passage(text)
        return self._formatted_passage_token_count(passage)

    def _formatted_passage_token_count(self, passage: str) -> int:
        try:
            encoded = self._model.tokenizer(
                passage,
                add_special_tokens=True,
                truncation=False,
            )
            count = len(encoded["input_ids"])
        except Exception as exc:
            raise EmbeddingProviderError("canonical tokenizer failed") from exc
        if count <= 0:
            raise EmbeddingProviderError("canonical tokenizer returned no tokens")
        return count

    def encode(self, passages: Sequence[str]) -> Sequence[Sequence[float]]:
        if any(
            self._formatted_passage_token_count(passage) > self.max_sequence_length
            for passage in passages
        ):
            raise EmbeddingProviderError(
                "embedding passage exceeds model sequence length"
            )
        try:
            encoded = self._model.encode(
                list(passages),
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except Exception as exc:
            raise EmbeddingProviderError("canonical embedding inference failed") from exc
        return _validated_vectors(
            encoded,
            expected_cardinality=len(passages),
            dimension=self.dimension,
        )


_VERIFIED_PROVIDER_TOKEN = object()


def coerce_embedding_provider(value: object) -> EmbeddingProvider:
    """Préserver les anciens tests sans attribuer un modèle canonique au callable."""
    if type(value) is VerifiedE5EmbeddingProvider:
        return value
    if isinstance(value, EmbeddingProvider):
        if value.model_id == CANONICAL_EMBED_MODEL:
            raise EmbeddingProviderError(
                "canonical model requires a verified immutable artifact"
            )
        return value
    if callable(value):
        return CallableEmbeddingProvider(encoder=value)
    raise EmbeddingProviderError("embedding provider is required")


__all__ = [
    "DEBUG_EMBED_MODEL",
    "CallableEmbeddingProvider",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "VerifiedE5EmbeddingProvider",
    "coerce_embedding_provider",
]
