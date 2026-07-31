"""Métriques d'évaluation du retrieval.

Ce module reste isolé du chemin de retrieval : il ne contient que des fonctions
purement computationnelles pour le lot 39.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def _positive_finite_grade(value: object) -> float | None:
    try:
        grade = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(grade) or grade <= 0:
        return None
    return grade


def _as_set_ids(relevant: Sequence[str] | Mapping[str, int | float] | None) -> set[str]:
    """Retourne les IDs pertinents sans perdre d'information de présence."""
    if not relevant:
        return set()
    if isinstance(relevant, Mapping):
        return {
            str(item).strip()
            for item, grade in relevant.items()
            if str(item).strip() and _positive_finite_grade(grade) is not None
        }
    return {str(item).strip() for item in relevant if str(item).strip()}


def recall_at_k(
    result_ids: Sequence[str],
    relevant: Sequence[str] | Mapping[str, int | float],
    k: int,
) -> float:
    """Recall@k (supporte relevant map ou liste)."""
    if k <= 0:
        raise ValueError("k doit être >= 1")
    relevant_ids = _as_set_ids(relevant)
    if not relevant_ids:
        return 0.0
    hit_ids = set(result_ids[:k])
    return len(hit_ids & relevant_ids) / len(relevant_ids)


def _dcg(sorted_relevances: Sequence[float]) -> float:
    if not sorted_relevances:
        return 0.0
    return sum(
        (2 ** rel - 1) / math.log2(position + 1)
        for position, rel in enumerate(sorted_relevances, start=1)
    )


def ndcg_at_k(
    result_ids: Sequence[str],
    graded_relevance: Mapping[str, int | float],
    k: int,
) -> float:
    """nDCG@k avec pertinence graduée (grades >= 0)."""
    if k <= 0:
        raise ValueError("k doit être >= 1")
    if not graded_relevance:
        return 0.0

    result_scores: list[float] = []
    seen_result_ids: set[str] = set()
    for chunk_id in result_ids[:k]:
        if chunk_id in seen_result_ids:
            result_scores.append(0.0)
            continue
        seen_result_ids.add(chunk_id)
        score = graded_relevance.get(chunk_id, 0.0)
        result_scores.append(_positive_finite_grade(score) or 0.0)

    ideal_scores = sorted(
        (
            grade
            for value in graded_relevance.values()
            if (grade := _positive_finite_grade(value)) is not None
        ),
        reverse=True,
    )[:k]

    if not ideal_scores:
        return 0.0

    ideal_dcg = _dcg(ideal_scores)
    if ideal_dcg == 0:
        return 0.0
    return _dcg(result_scores) / ideal_dcg


def mrr(result_ids: Sequence[str], relevant: Sequence[str] | Mapping[str, int | float]) -> float:
    """MRR (Mean Reciprocal Rank) binaire sur la première réponse pertinente."""
    relevant_ids = _as_set_ids(relevant)
    if not relevant_ids:
        return 0.0
    for index, chunk_id in enumerate(result_ids, start=1):
        if chunk_id in relevant_ids:
            return 1.0 / index
    return 0.0


def citation_completeness(result_ids: Sequence[str], metadata_by_chunk: Mapping[str, Mapping[str, object]]) -> float:
    """Taux de complétude de citation parmi les résultats.

    Une citation est considérée complète si chunk_id, doc_id, source_label,
    source_uri et rights sont non vides.
    """
    if not result_ids:
        return 1.0
    complete = 0
    for chunk_id in result_ids:
        meta = metadata_by_chunk.get(chunk_id, {})
        fields = (
            chunk_id,
            str(meta.get("chunk_id", "") or ""),
            str(meta.get("doc_id", "") or ""),
            str(meta.get("source_label", "") or ""),
            str(meta.get("source_uri", "") or ""),
            str(meta.get("rights", "") or ""),
        )
        if all(field.strip() for field in fields):
            complete += 1
    return complete / len(result_ids)


def percentile(values: Sequence[float], q: float) -> float:
    """Percentile simple (méthode linear interpolation)."""
    if not 0 <= q <= 1:
        raise ValueError("q doit être entre 0 et 1")
    if not values:
        return 0.0
    ordered = sorted(values)
    index = q * (len(ordered) - 1)
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return ordered[int(index)]
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def empty_answer_rate(result_counts: Sequence[int]) -> float:
    if not result_counts:
        return 0.0
    empty = sum(1 for count in result_counts if count == 0)
    return empty / len(result_counts)
