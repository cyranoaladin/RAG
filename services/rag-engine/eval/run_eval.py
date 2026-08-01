#!/usr/bin/env python3
# ruff: noqa: E402, I001
"""Harnais d'évaluation du retrieval (LOT 39).

Ce script charge des requêtes dorées au format YAML, évalue le pipeline v2 via
`ingestor.retrieval_v2_endpoint._retrieve_reviewed_hits`, calcule des métriques,
et applique un gate CI. L'option de sweep est réservée et refusée jusqu’au LOT43.

Objectif LOT 39 :
- produire des métriques de qualité sans modifier le chemin de retrieval ;
- conserver une comparaison contre une baseline versionnée ;
- empêcher la régression de nDCG@10 au-delà d'un seuil relatif ;
- exiger un taux de leak 0 et des citations complètes (1.0).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

EVAL_DIR = Path(__file__).resolve().parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

ENGINE_ROOT = EVAL_DIR.parent
SRC_ROOT = ENGINE_ROOT / "src"
CONTRACTS_ROOT = ENGINE_ROOT.parent.parent / "packages" / "contracts" / "src"
for _root in (SRC_ROOT, CONTRACTS_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from ingestor.retrieval_hybrid_v2 import CHANNEL_LIMIT, RERANK_THRESHOLD

from metrics import (
    citation_completeness,
    empty_answer_rate,
    mrr,
    ndcg_at_k,
    percentile,
    recall_at_k,
)


ALLOWED_INTENTS = {"definition", "methode", "exercice", "annale", "correction"}
COLLECTION_BY_NIVEAU = {
    "premiere": "rag_nexus_nsi_premiere_specialite",
    "terminale": "rag_nexus_nsi_terminale_specialite",
}
GOLDEN_EXTS = (".yml", ".yaml")
MIN_EVAL_DEPTH = 20
OFFLINE_FALLBACK_SENTENCE_LIMIT = 4


@dataclass
class GoldenQuery:
    query_id: str
    query: str
    intent: str
    collection: str
    niveau: str
    relevant_chunk_ids: list[str]
    graded_relevance: dict[str, float]
    must_not_return: list[str]


@dataclass
class EvalResult:
    config: dict[str, Any]
    golden_count: int
    suite_fingerprint: str
    recall_at_5: float
    recall_at_10: float
    recall_at_20: float
    ndcg_at_10: float
    mrr: float
    filter_leak_rate: float
    citation_completeness: float
    empty_answer_rate: float
    latency_ms_p50: float
    latency_ms_p95: float


@dataclass
class _FallbackHit:
    chunk_id: str
    doc_id: str
    source_label: str
    source_uri: str
    rights: str
    type_doc: str


def _load_module() -> Any:
    return importlib.import_module("ingestor.retrieval_v2_endpoint")


def _require_canonical_retrieval_config(retrieval_module: Any) -> None:
    candidates = getattr(retrieval_module, "RERANK_CANDIDATES", None)
    threshold = getattr(retrieval_module, "RERANK_SCORE_THRESHOLD", None)
    if candidates != CHANNEL_LIMIT or threshold != RERANK_THRESHOLD:
        raise ValueError(
            "Configuration retrieval non canonique: seuls candidates=50 et "
            "threshold=1.90 sont autorisés avant LOT43."
        )


def _safe_float(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("Un grade doit être numérique, pas booléen.")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Valeur numérique invalide: {value!r}") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError("Un grade doit être fini et positif ou nul.")
    return parsed


def _normalize_chunks(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [str(k).strip() for k in value if str(k).strip()]
    if not isinstance(value, list):
        raise ValueError("relevant_chunk_ids doit être une liste ou une map.")
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_graded(value: Any) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("graded_relevance doit être un mapping {chunk_id: score}.")
    out: dict[str, float] = {}
    for chunk_id, score in value.items():
        chunk = str(chunk_id).strip()
        if not chunk:
            continue
        out[chunk] = _safe_float(score)
    return out


def _as_golden_query(payload: dict[str, Any]) -> GoldenQuery:
    query_id = payload.get("id")
    query = payload.get("query")
    intent = payload.get("intent")
    collection = payload.get("collection")
    niveau = payload.get("niveau")
    if not all(isinstance(value, str) and value.strip() for value in (query_id, query, intent, collection, niveau)):
        raise ValueError("Champs requis manquants: id, query, intent, collection, niveau.")
    if intent not in ALLOWED_INTENTS:
        raise ValueError(f"intent invalide: {intent!r} (attendu {sorted(ALLOWED_INTENTS)}).")
    if niveau not in COLLECTION_BY_NIVEAU:
        raise ValueError(f"niveau invalide: {niveau!r}.")
    expected_collection = COLLECTION_BY_NIVEAU[niveau]
    if collection != expected_collection:
        raise ValueError(
            f"collection incohérente pour {niveau!r}: {collection!r} "
            f"(attendu {expected_collection!r})."
        )

    relevant_chunk_ids = _normalize_chunks(payload.get("relevant_chunk_ids", payload.get("relevant_chunk")))
    if not relevant_chunk_ids:
        raise ValueError("Chaque requête doit contenir au moins un jugement pertinent.")
    graded_relevance = _normalize_graded(payload.get("graded_relevance", {}))
    if not graded_relevance and relevant_chunk_ids:
        graded_relevance = {chunk_id: 1.0 for chunk_id in relevant_chunk_ids}
    positive_graded_ids = {
        chunk_id for chunk_id, grade in graded_relevance.items() if grade > 0
    }
    if set(relevant_chunk_ids) != positive_graded_ids:
        raise ValueError(
            "relevant_chunk_ids doit correspondre aux grades strictement positifs."
        )

    if "must_not_return" not in payload:
        raise ValueError("must_not_return est requis pour chaque requête.")
    must_not_payload = payload["must_not_return"]
    if not isinstance(must_not_payload, list):
        raise ValueError("must_not_return doit être une liste.")
    must_not_return = _normalize_chunks(must_not_payload)
    if set(relevant_chunk_ids).intersection(must_not_return):
        raise ValueError("Un chunk pertinent ne peut pas figurer dans must_not_return.")
    return GoldenQuery(
        query_id=str(query_id).strip(),
        query=str(query).strip(),
        intent=str(intent).strip(),
        collection=str(collection).strip(),
        niveau=str(niveau).strip(),
        relevant_chunk_ids=relevant_chunk_ids,
        graded_relevance=graded_relevance,
        must_not_return=must_not_return,
    )


def _load_yaml_queries(path: Path) -> list[GoldenQuery]:
    content = path.read_text(encoding="utf-8")
    payload = yaml.safe_load(content)
    if payload is None:
        raise ValueError(f"Fichier golden vide: {path}")
    if isinstance(payload, dict):
        if "queries" in payload:
            payload_items = payload["queries"]
        elif "golden_queries" in payload:
            payload_items = payload["golden_queries"]
        else:
            raise ValueError(
                f"Format YAML invalide (clé queries attendue) dans {path}"
            )
    elif isinstance(payload, list):
        payload_items = payload
    else:
        raise ValueError(f"Format YAML invalide dans {path}")
    if not isinstance(payload_items, list):
        raise ValueError(f"Format YAML invalide (liste attendue) dans {path}")
    if not payload_items:
        raise ValueError(f"Fichier golden sans requête: {path}")

    queries: list[GoldenQuery] = []
    for item in payload_items:
        if not isinstance(item, dict):
            raise ValueError(f"Entrée invalide dans {path}: {item!r}")
        queries.append(_as_golden_query(item))
    return queries


def load_golden_queries(golden_dir: Path, explicit: list[Path]) -> list[GoldenQuery]:
    if explicit:
        paths = explicit
    else:
        paths = sorted(
            p for ext in GOLDEN_EXTS for p in golden_dir.glob(f"*{ext}")
        )
    if not paths:
        raise FileNotFoundError(f"Aucune requête dorée trouvée dans {golden_dir}")

    queries: list[GoldenQuery] = []
    for path in paths:
        queries.extend(_load_yaml_queries(path))

    ids = {q.query_id for q in queries}
    if len(ids) != len(queries):
        raise ValueError("IDs de requêtes dorées dupliqués.")
    return queries


def _fingerprint_golden_suite(queries: list[GoldenQuery]) -> str:
    canonical_queries = [
        {
            "id": item.query_id,
            "query": item.query,
            "intent": item.intent,
            "collection": item.collection,
            "niveau": item.niveau,
            "relevant_chunk_ids": sorted(set(item.relevant_chunk_ids)),
            "graded_relevance": dict(sorted(item.graded_relevance.items())),
            "must_not_return": sorted(set(item.must_not_return)),
        }
        for item in sorted(queries, key=lambda query: query.query_id)
    ]
    serialized = json.dumps(
        canonical_queries,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _chunk_metadata(hit: Any) -> dict[str, str]:
    return {
        "chunk_id": str(getattr(hit, "chunk_id", "") or ""),
        "doc_id": str(getattr(hit, "doc_id", "") or ""),
        "source_label": str(getattr(hit, "source_label", "") or ""),
        "source_uri": str(getattr(hit, "source_uri", "") or ""),
        "rights": str(getattr(hit, "rights", "") or ""),
    }


def _tokenize_query(query: str) -> list[str]:
    # Normalise la ponctuation pour conserver des termes exploitables par l'index FTS.
    # Le tiret est retiré (sinon il peut entrer dans le token et casser le parse).
    cleaned = query.lower().replace("-", " ")
    cleaned = re.sub(r"[^A-Za-zÀ-ÿ0-9_\\s]", " ", cleaned)
    return [word for word in cleaned.split() if len(word) >= 3]


def _build_fallback_queries(query: str) -> tuple[list[str], str, str, str]:
    terms = _tokenize_query(query)
    if not terms:
        terms = ["nsi"]

    # 1) Recherche très permissive (OR)
    or_query = " | ".join(terms[:OFFLINE_FALLBACK_SENTENCE_LIMIT])
    # 2) Recherche plus stricte (AND)
    and_query = " & ".join(terms[:OFFLINE_FALLBACK_SENTENCE_LIMIT])
    # 3) Phrase de secours (2-4 termes)
    phrase_terms = terms[: min(OFFLINE_FALLBACK_SENTENCE_LIMIT, 4)]
    phrase_query = " ".join(phrase_terms)

    return terms, or_query, and_query, phrase_query


def _run_offline_query(
    dsn: str,
    collection: str,
    fts_query: str,
    tsquery_strategy: str,
    limit: int,
) -> list[tuple[Any, ...]]:
    if not fts_query:
        return []

    sql = f"""
        SELECT chunk_id, doc_id, source_label, source_uri, rights, type_doc,
               ts_rank_cd(tsv, {tsquery_strategy}(%s, %s)) AS lexical_score
        FROM rag_chunks
        WHERE collection = %s
          AND review_status = 'reviewed'
          AND tsv @@ {tsquery_strategy}(%s, %s)
        ORDER BY lexical_score DESC, chunk_id ASC
        LIMIT %s
    """

    with importlib.import_module("psycopg").connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, ("french", fts_query, collection, "french", fts_query, limit))
            return cast(list[tuple[Any, ...]], cur.fetchall())


def _run_offline_text_fallback(
    dsn: str,
    collection: str,
    terms: list[str],
    limit: int,
) -> list[tuple[Any, ...]]:
    if not terms:
        return []

    selected = [f"%{term.lower()}%" for term in terms[:OFFLINE_FALLBACK_SENTENCE_LIMIT]]
    clauses = ["lower(coalesce(text, '')) LIKE %s" for _ in selected]

    if not clauses:
        return []

    sql = f"""
        SELECT chunk_id, doc_id, source_label, source_uri, rights, type_doc,
               0.0 AS lexical_score
        FROM rag_chunks
        WHERE collection = %s
          AND review_status = 'reviewed'
          AND ({" OR ".join(clauses)})
        ORDER BY chunk_id ASC
        LIMIT %s
    """

    with importlib.import_module("psycopg").connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (collection, *selected, limit))
            return cast(list[tuple[Any, ...]], cur.fetchall())


def _retrieve_reviewed_hits_offline(
    query: str,
    collection: str,
    top_k: int,
    retrieval_module: Any,
) -> list[_FallbackHit]:
    _require_canonical_retrieval_config(retrieval_module)
    dsn = retrieval_module._get_pg_dsn()
    terms, or_query, and_query, phrase_query = _build_fallback_queries(query)
    limit = min(top_k, CHANNEL_LIMIT)

    rows: list[tuple[Any, ...]] = []
    rows.extend(_run_offline_query(dsn, collection, or_query, "to_tsquery", limit))
    if not rows:
        rows.extend(_run_offline_query(dsn, collection, and_query, "to_tsquery", limit))
    if not rows and phrase_query:
        rows.extend(_run_offline_query(dsn, collection, phrase_query, "plainto_tsquery", limit))
    if not rows:
        rows.extend(_run_offline_text_fallback(dsn, collection, terms[:OFFLINE_FALLBACK_SENTENCE_LIMIT], limit))

    # Les requêtes FTS peuvent contenir des doublons ; déduplication stable.
    deduped_rows: list[tuple[Any, ...]] = []
    seen: set[str] = set()
    for row in rows:
        if len(row) < 6:
            continue
        chunk_id = str(row[0])
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        deduped_rows.append(row)

    rows = deduped_rows

    return [
        _FallbackHit(
            chunk_id=str(row[0]),
            doc_id=str(row[1]),
            source_label=str(row[2] or ""),
            source_uri=str(row[3] or ""),
            rights=str(row[4] or ""),
            type_doc=str(row[5] or ""),
        )
        for row in rows[:limit]
    ]


def _mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def evaluate_golden_set(
    queries: list[GoldenQuery],
    *,
    top_k: int,
    retrieval_module: Any,
    offline_fallback: bool = False,
) -> EvalResult:
    if top_k < MIN_EVAL_DEPTH:
        raise ValueError(f"top_k doit être >= {MIN_EVAL_DEPTH} pour publier Recall@20.")
    _require_canonical_retrieval_config(retrieval_module)

    recall5_values: list[float] = []
    recall10_values: list[float] = []
    recall20_values: list[float] = []
    ndcg_values: list[float] = []
    mrr_values: list[float] = []
    citation_values: list[float] = []
    per_query_leak_items: list[int] = []
    result_counts: list[int] = []
    latencies_ms: list[float] = []

    for item in queries:
        start = time.perf_counter()
        if offline_fallback:
            hits = _retrieve_reviewed_hits_offline(
                item.query,
                item.collection,
                top_k,
                retrieval_module,
            )
        else:
            hits = retrieval_module._retrieve_reviewed_hits(item.query, item.collection, top_k)
        latency_ms = (time.perf_counter() - start) * 1000.0
        latencies_ms.append(latency_ms)

        result_ids = [str(hit.chunk_id) for hit in hits]
        result_counts.append(len(result_ids))
        metadata = {str(hit.chunk_id): _chunk_metadata(hit) for hit in hits}
        relevant = dict(item.graded_relevance)
        if not relevant and item.relevant_chunk_ids:
            relevant = {chunk_id: 1.0 for chunk_id in item.relevant_chunk_ids}

        recall5_values.append(recall_at_k(result_ids, relevant, k=5))
        recall10_values.append(recall_at_k(result_ids, relevant, k=10))
        recall20_values.append(recall_at_k(result_ids, relevant, k=20))
        ndcg_values.append(ndcg_at_k(result_ids, relevant, k=10))
        mrr_values.append(mrr(result_ids, relevant))
        citation_values.append(citation_completeness(result_ids, metadata))

        leak = sum(1 for value in result_ids if value in set(item.must_not_return))
        per_query_leak_items.append(leak)

    recall_at_5 = _mean(recall5_values)
    recall_at_10 = _mean(recall10_values)
    recall_at_20 = _mean(recall20_values)
    ndcg_at_10 = _mean(ndcg_values)
    mean_mrr = _mean(mrr_values)
    total_retrieved = sum(result_counts)
    leak_rate = (sum(per_query_leak_items) / total_retrieved) if total_retrieved else 0.0
    citation_ratio = _mean(citation_values)
    empty_rate = empty_answer_rate(result_counts)
    latency_p50 = percentile(latencies_ms, 0.5)
    latency_p95 = percentile(latencies_ms, 0.95)

    return EvalResult(
        config={
            "rerank_candidates": CHANNEL_LIMIT,
            "rerank_score_threshold": RERANK_THRESHOLD,
            "top_k": top_k,
            "retrieval_mode": "offline_lexical" if offline_fallback else "nominal",
        },
        golden_count=len(queries),
        suite_fingerprint=_fingerprint_golden_suite(queries),
        recall_at_5=recall_at_5,
        recall_at_10=recall_at_10,
        recall_at_20=recall_at_20,
        ndcg_at_10=ndcg_at_10,
        mrr=mean_mrr,
        filter_leak_rate=leak_rate,
        citation_completeness=citation_ratio,
        empty_answer_rate=empty_rate,
        latency_ms_p50=latency_p50,
        latency_ms_p95=latency_p95,
    )


def run_sweep(
    queries: list[GoldenQuery],
    *,
    retrieval_module: Any,
    top_k: int,
    offline_fallback: bool = False,
) -> list[EvalResult]:
    del queries, retrieval_module, top_k, offline_fallback
    raise ValueError("Le sweep de calibration est désactivé jusqu'au LOT43.")


def _validate_eval_result(result: EvalResult) -> None:
    candidates = result.config.get("rerank_candidates")
    if candidates != CHANNEL_LIMIT:
        raise ValueError(
            f"rerank_candidates doit rester canonique ({CHANNEL_LIMIT}) avant LOT43."
        )

    threshold = result.config.get("rerank_score_threshold")
    if threshold != RERANK_THRESHOLD:
        raise ValueError(
            "rerank_score_threshold doit rester canonique "
            f"({RERANK_THRESHOLD:.2f}) avant LOT43."
        )

    top_k = result.config.get("top_k")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < MIN_EVAL_DEPTH:
        raise ValueError(f"top_k doit être un entier >= {MIN_EVAL_DEPTH}.")

    if result.config.get("retrieval_mode") not in {"nominal", "offline_lexical"}:
        raise ValueError("retrieval_mode doit être nominal ou offline_lexical.")
    if result.golden_count <= 0:
        raise ValueError("golden_count doit être strictement positif.")
    if re.fullmatch(r"[0-9a-f]{64}", result.suite_fingerprint) is None:
        raise ValueError("suite_fingerprint doit être une empreinte SHA-256 canonique.")

    bounded_metrics = {
        "recall_at_5": result.recall_at_5,
        "recall_at_10": result.recall_at_10,
        "recall_at_20": result.recall_at_20,
        "ndcg_at_10": result.ndcg_at_10,
        "mrr": result.mrr,
        "filter_leak_rate": result.filter_leak_rate,
        "citation_completeness": result.citation_completeness,
        "empty_answer_rate": result.empty_answer_rate,
    }
    for metric_name, value in bounded_metrics.items():
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{metric_name} doit être un nombre fini entre 0 et 1.")

    latency_metrics = {
        "latency_ms_p50": result.latency_ms_p50,
        "latency_ms_p95": result.latency_ms_p95,
    }
    for metric_name, value in latency_metrics.items():
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{metric_name} doit être un nombre fini positif ou nul.")


def _absolute_gate_reasons(result: EvalResult) -> list[str]:
    _validate_eval_result(result)
    reasons: list[str] = []
    if result.ndcg_at_10 <= 0:
        reasons.append("nDCG@10 courant non exploitable.")
    if result.filter_leak_rate > 0.0:
        reasons.append(f"filter_leak_rate non nul: {result.filter_leak_rate:.4f}")
    if result.citation_completeness < 1.0:
        reasons.append(
            f"citation_completeness < 1: {result.citation_completeness:.4f}"
        )
    return reasons


def _compare_baseline(current: EvalResult, baseline_path: Path, drop_tolerance: float) -> list[str]:
    _validate_eval_result(current)
    if not math.isfinite(drop_tolerance) or not 0 <= drop_tolerance < 1:
        raise ValueError("La tolérance nDCG doit être un nombre fini entre 0 inclus et 1 exclu.")
    if not baseline_path.exists():
        raise FileNotFoundError(
            "Baseline absente. Utiliser --write-baseline pour produire la référence LOT 39."
        )
    raw = json.loads(baseline_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("La baseline doit être un objet JSON.")
    if raw.get("version") != "1.0.0":
        raise ValueError("Version de baseline absente ou incompatible.")

    baseline_config = raw.get("config")
    if not isinstance(baseline_config, dict) or baseline_config != current.config:
        raise ValueError("La configuration de baseline ne correspond pas à l'évaluation courante.")

    baseline_suite = raw.get("suite")
    if not isinstance(baseline_suite, dict):
        raise ValueError("La baseline doit identifier sa suite.")
    if baseline_suite.get("query_count") != current.golden_count:
        raise ValueError("Le query_count de baseline ne correspond pas à la suite courante.")
    if baseline_suite.get("top_k") != current.config.get("top_k"):
        raise ValueError("Le top_k de baseline ne correspond pas à la suite courante.")
    if baseline_suite.get("suite_fingerprint") != current.suite_fingerprint:
        raise ValueError("L'empreinte de suite ne correspond pas à la baseline.")

    baseline_metrics = raw.get("metrics", {})
    if not isinstance(baseline_metrics, dict):
        raise ValueError("Les métriques de baseline doivent former un objet JSON.")
    for metric_name, value in baseline_metrics.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(float(value))
        ):
            raise ValueError(
                f"La métrique de baseline {metric_name!r} doit être un nombre fini."
            )
    reason = _absolute_gate_reasons(current)

    baseline_ndcg = float(baseline_metrics.get("ndcg_at_10", 0.0))
    if baseline_ndcg <= 0:
        reason.append("La baseline n'a pas de nDCG@10 exploitable.")
    elif current.ndcg_at_10 < baseline_ndcg * (1.0 - drop_tolerance):
        reason.append(
            f"nDCG@10 en régression: {current.ndcg_at_10:.4f} < {baseline_ndcg:.4f} * (1 - {drop_tolerance:.2f})"
        )

    return reason


def _to_json(result: EvalResult, *, queries_count: int) -> dict[str, Any]:
    return {
        "config": result.config,
        "metrics": {
            "recall_at_5": result.recall_at_5,
            "recall_at_10": result.recall_at_10,
            "recall_at_20": result.recall_at_20,
            "ndcg_at_10": result.ndcg_at_10,
            "mrr": result.mrr,
            "filter_leak_rate": result.filter_leak_rate,
            "citation_completeness": result.citation_completeness,
            "empty_answer_rate": result.empty_answer_rate,
            "latency_ms_p50": result.latency_ms_p50,
            "latency_ms_p95": result.latency_ms_p95,
        },
        "queries": queries_count,
        "suite_fingerprint": result.suite_fingerprint,
    }


def _serialize_sweep(rows: list[EvalResult]) -> list[dict[str, Any]]:
    return [
        {
            "rerank_candidates": row.config["rerank_candidates"],
            "rerank_score_threshold": row.config["rerank_score_threshold"],
            "recall_at_10": row.recall_at_10,
            "ndcg_at_10": row.ndcg_at_10,
            "empty_answer_rate": row.empty_answer_rate,
            "latency_ms_p95": row.latency_ms_p95,
        }
        for row in rows
    ]


def _print_sweep(rows: list[EvalResult]) -> None:
    print("\nCalibration sweep")
    print("candidates | threshold | nDCG@10 | Recall@10 | empty_answer_rate | p95_latency_ms")
    print("----------|-----------|---------|-----------|------------------|----------------")
    for row in rows:
        print(
            f"{int(row.config['rerank_candidates']):9d} | "
            f"{row.config['rerank_score_threshold']:9.2f} | "
            f"{row.ndcg_at_10:7.4f} | "
            f"{row.recall_at_10:9.4f} | "
            f"{row.empty_answer_rate:16.4f} | "
            f"{row.latency_ms_p95:15.2f}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Évaluer le retrieval v2 sur des requêtes dorées YAML."
    )
    parser.add_argument(
        "--golden-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "golden",
        help="Répertoire des fichiers golden (.yml/.yaml).",
    )
    parser.add_argument(
        "--golden-file",
        type=Path,
        action="append",
        default=[],
        help="Fichiers golden explicites (peut être répété).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=20,
        help="Nombre de résultats conservés par requête.",
    )
    parser.add_argument(
        "--rerank-candidates",
        type=int,
        default=CHANNEL_LIMIT,
        help=f"Valeur figée à {CHANNEL_LIMIT} jusqu'au LOT43.",
    )
    parser.add_argument(
        "--rerank-score-threshold",
        type=float,
        default=RERANK_THRESHOLD,
        help=f"Valeur figée à {RERANK_THRESHOLD:.2f} jusqu'au LOT43.",
    )
    parser.add_argument(
        "--baseline-path",
        type=Path,
        default=Path(__file__).resolve().parent
        / "baselines"
        / "lot_39_baseline_v1.0.0.json",
        help="Chemin de la baseline versionnée.",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Écrire une nouvelle baseline à partir de l'évaluation courante.",
    )
    parser.add_argument(
        "--ndcg-drop-tolerance",
        type=float,
        default=0.02,
        help="Tolérance de baisse relative pour nDCG@10.",
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Option réservée au LOT43 et refusée jusqu’au LOT43.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Écrire le résultat complet (JSON) vers ce fichier.",
    )
    parser.add_argument(
        "--offline-fallback",
        action="store_true",
        help=(
            "Évaluer sans dépendance HF (recherche lexicale dans rag_chunks). "
            "Utilisé uniquement si le modèle embedding n'est pas disponible."
        ),
    )
    parser.add_argument(
        "--pg-rag-dsn",
        type=str,
        default=None,
        help="DSN pgvector (sinon PG_RAG_DSN / DATABASE_URL_SYNC).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.top_k < MIN_EVAL_DEPTH:
        raise SystemExit(f"--top-k doit être >= {MIN_EVAL_DEPTH} pour publier Recall@20")
    if args.rerank_candidates is not None and args.rerank_candidates <= 0:
        raise SystemExit("--rerank-candidates doit être strictement positif")
    if (
        args.rerank_candidates is not None
        and args.rerank_candidates != CHANNEL_LIMIT
    ):
        raise SystemExit(
            f"--rerank-candidates doit rester canonique ({CHANNEL_LIMIT}) avant LOT43"
        )
    if args.rerank_score_threshold is not None and not math.isfinite(
        args.rerank_score_threshold
    ):
        raise SystemExit("--rerank-score-threshold doit être un nombre fini")
    if (
        args.rerank_score_threshold is not None
        and args.rerank_score_threshold != RERANK_THRESHOLD
    ):
        raise SystemExit(
            "--rerank-score-threshold doit rester canonique "
            f"({RERANK_THRESHOLD:.2f}) avant LOT43"
        )
    if getattr(args, "sweep", False) and getattr(args, "offline_fallback", False):
        raise SystemExit("--sweep est incompatible avec --offline-fallback")
    if getattr(args, "sweep", False):
        raise SystemExit("--sweep est désactivé jusqu'au LOT43")

    if args.pg_rag_dsn:
        os.environ["PG_RAG_DSN"] = args.pg_rag_dsn
    else:
        os.environ.setdefault("PG_RAG_DSN", os.environ.get("DATABASE_URL_SYNC", ""))

    retrieval_module = _load_module()
    try:
        _require_canonical_retrieval_config(retrieval_module)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None

    if not os.environ.get("PG_RAG_DSN") and not os.environ.get("DATABASE_URL_SYNC"):
        raise SystemExit(
            "PG_RAG_DSN manquant : définir PG_RAG_DSN ou DATABASE_URL_SYNC."
        )

    golden_queries = load_golden_queries(
        args.golden_dir.resolve(),
        [path.resolve() for path in args.golden_file],
    )
    if not golden_queries:
        raise SystemExit("Aucune requête dorée.")

    sweep_rows: list[EvalResult] = []

    result = evaluate_golden_set(
        golden_queries,
        top_k=args.top_k,
        retrieval_module=retrieval_module,
        offline_fallback=args.offline_fallback,
    )

    payload: dict[str, Any] = {
        "suite": {
            "query_count": result.golden_count,
            "top_k": args.top_k,
            "suite_fingerprint": result.suite_fingerprint,
        },
        "config": result.config,
        "metrics": {
            "recall_at_5": result.recall_at_5,
            "recall_at_10": result.recall_at_10,
            "recall_at_20": result.recall_at_20,
            "ndcg_at_10": result.ndcg_at_10,
            "mrr": result.mrr,
            "filter_leak_rate": result.filter_leak_rate,
            "citation_completeness": result.citation_completeness,
            "empty_answer_rate": result.empty_answer_rate,
            "latency_ms_p50": result.latency_ms_p50,
            "latency_ms_p95": result.latency_ms_p95,
        },
    }
    if sweep_rows:
        payload["calibration_sweep"] = _serialize_sweep(sweep_rows)

    if args.write_baseline:
        reasons = _absolute_gate_reasons(result)
    else:
        reasons = _compare_baseline(result, args.baseline_path, args.ndcg_drop_tolerance)

    print(json.dumps(payload["metrics"], ensure_ascii=False, indent=2, allow_nan=False))
    if reasons:
        for item in reasons:
            print(f"FAIL: {item}", file=sys.stderr)
        return 1

    if args.write_baseline:
        args.baseline_path.parent.mkdir(parents=True, exist_ok=True)
        args.baseline_path.write_text(
            json.dumps(
                {
                    "version": "1.0.0",
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "collection": "nsi",
                    "config": result.config,
                    "metrics": payload["metrics"],
                    "suite": payload["suite"],
                },
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )

    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )

    if args.write_baseline:
        print(f"Baseline écrite : {args.baseline_path}")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
