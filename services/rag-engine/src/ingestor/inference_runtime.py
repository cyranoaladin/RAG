"""Capacité bornée et deadline de bout en bout pour les inférences v2."""

from __future__ import annotations

import os
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


def _cuda_is_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _model_device(model: Any) -> str:
    device = getattr(model, "device", None)
    if device is None:
        device = getattr(getattr(model, "model", None), "device", None)
    return str(device) if device is not None else ""


def verify_required_inference_device(embedding_model: Any, reranker_model: Any) -> None:
    """Refuser au démarrage un profil CUDA qui serait servi sur CPU."""
    required = os.environ.get("RAG_REQUIRE_CUDA", "false").strip().lower()
    if required not in {"true", "false"}:
        raise InferenceRuntimeError("CUDA_REQUIREMENT_INVALID")
    if required == "false":
        return
    if not _cuda_is_available() or any(
        not _model_device(model).startswith("cuda:")
        for model in (embedding_model, reranker_model)
    ):
        raise InferenceRuntimeError("CUDA_INFERENCE_UNAVAILABLE")


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
    "verify_required_inference_device",
]
