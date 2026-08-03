"""Capacité bornée et deadline de bout en bout pour les inférences v2."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextvars import copy_context
from typing import Any, Final, TypeVar

try:
    from .pg_pool import remaining_request_budget_ms
except ImportError:
    from pg_pool import remaining_request_budget_ms  # type: ignore[no-redef]

_Result = TypeVar("_Result")

# Le runtime canonique dispose de deux CPU. Un seul créneau empêche les huit
# collections d'une requête chat, puis les requêtes concurrentes, de multiplier
# les inférences CPU. Le sémaphore interdit aussi la file non bornée interne de
# ThreadPoolExecutor : aucun travail n'est soumis sans créneau acquis.
INFERENCE_MAX_CONCURRENCY: Final = 1
_inference_executor = ThreadPoolExecutor(
    max_workers=INFERENCE_MAX_CONCURRENCY,
    thread_name_prefix="rag-v2-inference",
)
_inference_capacity = threading.BoundedSemaphore(INFERENCE_MAX_CONCURRENCY)


class InferenceRuntimeError(RuntimeError):
    """L'inférence ne peut pas finir dans la capacité et la deadline autorisées."""


def _remaining_timeout_s() -> float:
    try:
        return remaining_request_budget_ms() / 1_000.0
    except Exception:
        raise InferenceRuntimeError("inference unavailable") from None


def _release_capacity(_future: Future[Any]) -> None:
    _inference_capacity.release()


def run_bounded_inference(operation: Callable[[], _Result]) -> _Result:
    """Attendre un créneau sans jamais dépasser la deadline de requête."""
    try:
        capacity_wait_s = _remaining_timeout_s()
        if not _inference_capacity.acquire(timeout=capacity_wait_s):
            raise InferenceRuntimeError("inference unavailable")
    except InferenceRuntimeError:
        raise
    except Exception:
        raise InferenceRuntimeError("inference unavailable") from None

    try:
        # L'attente du sémaphore consomme le même budget que l'inférence :
        # une nouvelle lecture empêche de redonner une deadline complète au worker.
        timeout_s = _remaining_timeout_s()
        request_context = copy_context()
        future = _inference_executor.submit(request_context.run, operation)
    except Exception:
        _inference_capacity.release()
        raise InferenceRuntimeError("inference unavailable") from None

    future.add_done_callback(_release_capacity)
    try:
        return future.result(timeout=timeout_s)
    except FutureTimeout:
        # Une tâche déjà démarrée n'est pas interruptible en sûreté. Elle garde
        # donc son unique créneau jusqu'à sa fin ; les appels suivants échouent
        # sans alimenter la file de l'executor.
        future.cancel()
        raise InferenceRuntimeError("inference unavailable") from None
    except Exception:
        raise InferenceRuntimeError("inference unavailable") from None


class BoundedInferenceEmbedder:
    """Adapter l'encodeur canonique à la capacité runtime bornée."""

    def __init__(self, model: Any) -> None:
        self._model = model

    def encode(
        self,
        text: str,
        *,
        normalize_embeddings: bool,
    ) -> Iterable[float]:
        return run_bounded_inference(
            lambda: tuple(
                self._model.encode(
                    text,
                    normalize_embeddings=normalize_embeddings,
                )
            )
        )


class BoundedInferenceReranker:
    """Adapter le reranker canonique à la capacité runtime bornée."""

    def __init__(self, model: Any) -> None:
        self._model = model

    def predict(
        self,
        pairs: Sequence[tuple[str, str]],
    ) -> Iterable[float]:
        return run_bounded_inference(lambda: tuple(self._model.predict(pairs)))


__all__ = [
    "BoundedInferenceEmbedder",
    "BoundedInferenceReranker",
    "INFERENCE_MAX_CONCURRENCY",
    "InferenceRuntimeError",
    "run_bounded_inference",
]
