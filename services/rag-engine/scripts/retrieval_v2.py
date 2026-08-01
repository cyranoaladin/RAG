#!/usr/bin/env python3
"""CLI minimal du pipeline canonique de retrieval hybride v2 (LOT40).

Le script ne contient ni SQL ni variante locale du classement. Il applique le
gate de gouvernance, délègue au noyau partagé et n'affiche jamais le texte des
chunks ni la requête utilisateur.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ENGINE_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT.parent.parent / "packages" / "contracts" / "src"))

from ingestor.collection_config import (  # noqa: E402
    CollectionConfigError,
    load_collection_config,
    resolve_collection_v2,
)
from ingestor.embedding_contract import (  # noqa: E402
    EmbeddingContractError,
    load_embedding_model,
)
from ingestor.pg_pool import (  # noqa: E402
    PoolConfigurationError,
    PoolSettings,
    close_pool,
    pool_connection,
)
from ingestor.retrieval_hybrid_v2 import (  # noqa: E402
    CHANNEL_LIMIT,
    RERANK_MODEL,
    CandidateStore,
    Embedder,
    HybridHit,
    Reranker,
    RetrievalPipelineError,
    RetrieveFunction,
    retrieve_hybrid,
)
from ingestor.retrieval_pg_v2 import PgCandidateStore  # noqa: E402

StoreFactory = Callable[[PoolSettings], CandidateStore]
EmbedderFactory = Callable[[], Embedder]
RerankerFactory = Callable[[], Reranker]


class CollectionNotRetrievableError(ValueError):
    """Refus fail-closed d'une collection non autorisée au retrieval."""


class ModelLoadError(RuntimeError):
    """Échec contrôlé de chargement d'un artefact de modèle canonique."""


def _check_retrievable(collection: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """Vérifie explicitement le verrou ``retrievable`` de la collection."""
    definition: dict[str, Any] = resolve_collection_v2(collection, cfg)

    domain = definition.get("domain")
    if not isinstance(domain, str) or not domain:
        raise CollectionNotRetrievableError(
            f"Collection '{collection}' has no declared domain — cannot verify "
            "retrievable. Add 'domain: <name>' to the collection definition."
        )

    domains = cfg.get("domains")
    if not isinstance(domains, dict):
        raise CollectionNotRetrievableError(
            "Config 'domains' section absent or malformed — fail-closed. "
            f"Cannot verify retrievable for domain '{domain}'."
        )

    domain_cfg = domains.get(domain)
    if not isinstance(domain_cfg, dict):
        raise CollectionNotRetrievableError(
            f"Domain '{domain}' not found in config domains — fail-closed. "
            f"Collection '{collection}' cannot be served."
        )

    if domain_cfg.get("retrievable") is not True:
        raise CollectionNotRetrievableError(
            f"Collection '{collection}' is not retrievable (domain '{domain}', "
            f"retrievable:{domain_cfg.get('retrievable')}). Refused."
        )

    return definition


def _build_pg_store(settings: PoolSettings) -> CandidateStore:
    """Construit le store sans ouvrir de connexion avant la première requête."""
    return PgCandidateStore(lambda: pool_connection(settings))


def _load_canonical_embedder() -> Embedder:
    """Charge exclusivement l'artefact d'embedding canonique pré-provisionné."""
    return load_embedding_model()


def _load_canonical_reranker() -> Reranker:
    """Charge exclusivement le reranker canonique depuis le cache local."""
    try:
        from sentence_transformers import CrossEncoder

        return CrossEncoder(
            RERANK_MODEL,
            max_length=512,
            local_files_only=True,
        )
    except Exception:
        raise ModelLoadError("canonical reranker unavailable") from None


def _validate_request(query: object, collection: object, top_k: object) -> None:
    if not isinstance(query, str) or not query.strip():
        raise RetrievalPipelineError("invalid query")
    if not isinstance(collection, str) or not collection.strip():
        raise RetrievalPipelineError("invalid collection")
    if (
        isinstance(top_k, bool)
        or not isinstance(top_k, int)
        or not 1 <= top_k <= CHANNEL_LIMIT
    ):
        raise RetrievalPipelineError("invalid top_k")


def search(
    query: str,
    collection: str,
    top_k: int = 5,
    *,
    settings: PoolSettings,
    store_factory: StoreFactory = _build_pg_store,
    embedder_factory: EmbedderFactory = _load_canonical_embedder,
    reranker_factory: RerankerFactory = _load_canonical_reranker,
    retrieve_fn: RetrieveFunction = retrieve_hybrid,
) -> list[HybridHit]:
    """Applique le gate avant toute factory puis délègue au noyau hybride."""
    _validate_request(query, collection, top_k)
    config = load_collection_config()
    _check_retrievable(collection, config)

    store = store_factory(settings)
    embedder = embedder_factory()
    reranker = reranker_factory()
    hits: list[HybridHit] = retrieve_fn(
        query,
        collection,
        top_k,
        store=store,
        embedder=embedder,
        reranker=reranker,
    )
    return hits


def _top_k_argument(raw_value: str) -> int:
    try:
        value = int(raw_value)
    except ValueError:
        raise argparse.ArgumentTypeError("top-k must be an integer between 1 and 50") from None
    if not 1 <= value <= CHANNEL_LIMIT:
        raise argparse.ArgumentTypeError("top-k must be between 1 and 50")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Retrieval v2 hybride canonique")
    parser.add_argument("--query", required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--top-k", type=_top_k_argument, default=5)
    return parser


def _score(value: float | None) -> str:
    return "none" if value is None else f"{value:.6f}"


def _print_hits(hits: Sequence[HybridHit]) -> None:
    print(f"results={len(hits)}")
    for hit in hits:
        candidate = hit.candidate
        print(
            f"chunk_id={candidate.chunk_id} doc_id={candidate.doc_id} "
            f"dense={_score(candidate.dense_score)} "
            f"lexical={_score(candidate.lexical_score)} "
            f"rrf={hit.rrf_score:.6f} rerank={hit.rerank_score:.6f} "
            f"final={hit.score_final:.6f} mmr={hit.mmr_score:.6f}"
        )


_CONTROLLED_ERRORS = (
    CollectionConfigError,
    CollectionNotRetrievableError,
    EmbeddingContractError,
    ModelLoadError,
    PoolConfigurationError,
    RetrievalPipelineError,
)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    hits: list[HybridHit] | None = None
    failed = False

    try:
        settings = PoolSettings.from_env()
        hits = search(
            args.query,
            args.collection,
            args.top_k,
            settings=settings,
            store_factory=_build_pg_store,
            embedder_factory=_load_canonical_embedder,
            reranker_factory=_load_canonical_reranker,
            retrieve_fn=retrieve_hybrid,
        )
    except _CONTROLLED_ERRORS:
        failed = True
    finally:
        try:
            close_pool()
        except PoolConfigurationError:
            failed = True

    if failed or hits is None:
        print("Error: hybrid retrieval unavailable", file=sys.stderr)
        return 1

    _print_hits(hits)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
