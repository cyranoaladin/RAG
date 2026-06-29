from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from nexus_contracts.retrieval import RetrievalRequest

from .collection_config import CollectionConfigError, resolve_collection

EXAM_DOC_TYPES = {
    "annale",
    "sujet_zero",
    "corrige",
    "bareme",
    "grille_evaluation",
    "grille_grand_oral",
    "bac_blanc",
    "brevet_blanc",
}
OFFICIAL_DOC_TYPES = {"programme_officiel", "ressource_officielle", "referentiel"}


@dataclass(frozen=True)
class AdaptedRetrieval:
    query: str
    top_k: int
    filters: dict[str, Any]
    nexus_collection: str
    physical_collection: str
    domain: str
    include_citations: bool
    warnings: tuple[str, ...] = ()


def _coerce_top_k(value: Any, default: int = 6) -> int:
    try:
        return max(1, min(int(value), 50))
    except (TypeError, ValueError):
        return default


def _normalized_query(payload: Mapping[str, Any]) -> str:
    query = payload.get("q") or payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query is required")
    return query.strip()


def _safe_filters(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items() if item not in (None, "", "Tous")}


def adapt_legacy_search_payload(payload: Mapping[str, Any]) -> AdaptedRetrieval:
    """Convert the historical `/search` payload into Nexus routing semantics."""
    query = _normalized_query(payload)
    top_k = _coerce_top_k(payload.get("k", payload.get("top_k", 6)))
    collection = payload.get("collection")
    section = payload.get("section")

    try:
        resolution = resolve_collection(
            section=str(section) if section else None,
            collection=str(collection) if collection else None,
            allow_non_retrievable=False,
        )
    except CollectionConfigError as exc:
        raise ValueError(str(exc)) from exc

    filters = _safe_filters(payload.get("filters"))
    requested_domain = filters.get("domain")
    if requested_domain and requested_domain != resolution.domain:
        raise ValueError("domain filter does not match resolved collection")
    filters["domain"] = resolution.domain
    filters["nexus_collection"] = resolution.nexus_collection

    warnings: list[str] = []
    if resolution.used_legacy:
        warnings.append(
            f"legacy_collection_mapped:{resolution.physical_collection}->{resolution.nexus_collection}"
        )

    return AdaptedRetrieval(
        query=query,
        top_k=top_k,
        filters=filters,
        nexus_collection=resolution.nexus_collection,
        physical_collection=resolution.physical_collection,
        domain=resolution.domain,
        include_citations=bool(payload.get("include_citations", True)),
        warnings=tuple(warnings),
    )


def _collection_for_contract(request: RetrievalRequest) -> str:
    doc_types = {doc_type.value for doc_type in request.need.desired_doc_types}
    if doc_types & OFFICIAL_DOC_TYPES:
        return "rag_nexus_official"
    if doc_types & EXAM_DOC_TYPES:
        return "rag_nexus_exams"
    return "rag_nexus_education"


def adapt_retrieval_request(request: RetrievalRequest) -> AdaptedRetrieval:
    """Convert the shared Nexus contract into server-side retrieval routing."""
    nexus_collection = _collection_for_contract(request)
    resolution = resolve_collection(collection=nexus_collection, allow_non_retrievable=False)
    filters: dict[str, Any] = dict(request.to_payload_filters())
    filters["domain"] = resolution.domain
    filters["nexus_collection"] = resolution.nexus_collection
    if request.need.notions:
        filters["notions"] = list(request.need.notions)
    if request.need.desired_doc_types:
        doc_types = [doc_type.value for doc_type in request.need.desired_doc_types]
        filters["type_doc"] = doc_types[0] if len(doc_types) == 1 else doc_types
    if request.need.difficulty_max is not None:
        filters["difficulty_max"] = request.need.difficulty_max

    return AdaptedRetrieval(
        query=request.need.query,
        top_k=request.retrieval.k,
        filters=filters,
        nexus_collection=resolution.nexus_collection,
        physical_collection=resolution.physical_collection,
        domain=resolution.domain,
        include_citations=request.retrieval.include_citations,
    )


def build_citation_payload(metadata: Mapping[str, Any]) -> dict[str, Any] | None:
    """Build the citation subset required by `nexus_contracts.retrieval.Citation`."""
    required = ("source_label", "source_uri", "rights")
    if not all(metadata.get(key) for key in required):
        return None
    citation: dict[str, Any] = {key: str(metadata[key]) for key in required}
    page = metadata.get("page")
    if isinstance(page, int):
        citation["page"] = page
    elif isinstance(page, str) and page.strip().isdigit():
        citation["page"] = int(page.strip())
    return citation
