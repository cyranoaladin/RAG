"""Re-export from nexus-contracts (source of truth)."""

from nexus_contracts.retrieval import *  # noqa: F401,F403
from nexus_contracts.retrieval import (
    Citation,
    RetrievalNeed,
    RetrievalOptions,
    RetrievalRequest,
    RetrievalResponse,
    RetrievalResult,
)

__all__ = [
    "Citation",
    "RetrievalNeed",
    "RetrievalOptions",
    "RetrievalRequest",
    "RetrievalResponse",
    "RetrievalResult",
]
