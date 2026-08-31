from __future__ import annotations

import importlib
import inspect
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

metrics = importlib.import_module("metrics")
run_eval = importlib.import_module("run_eval")

BASELINE_CONFIG = {
    "rerank_candidates": 50,
    "rerank_score_threshold": 1.9,
    "top_k": 20,
    "retrieval_mode": "nominal",
}
SUITE_FINGERPRINT = "a" * 64


def _eval_result(
    *,
    ndcg_at_10: float = 0.7,
    filter_leak_rate: float = 0.0,
    citation_completeness: float = 1.0,
) -> object:
    result = run_eval.EvalResult(
        config=dict(BASELINE_CONFIG),
        golden_count=1,
        suite_fingerprint=SUITE_FINGERPRINT,
        recall_at_5=0.0,
        recall_at_10=0.0,
        recall_at_20=0.0,
        ndcg_at_10=ndcg_at_10,
        mrr=0.0,
        filter_leak_rate=filter_leak_rate,
        citation_completeness=citation_completeness,
        empty_answer_rate=0.0,
        latency_ms_p50=0.0,
        latency_ms_p95=0.0,
    )
    return result


def test_ndcg_preserves_the_rank_of_relevant_results() -> None:
    score = metrics.ndcg_at_k(
        ["irrelevant", "relevant"],
        {"relevant": 3},
        k=10,
    )

    assert score == pytest.approx(1 / math.log2(3))


def test_ndcg_credits_a_repeated_chunk_only_at_its_first_rank() -> None:
    score = metrics.ndcg_at_k(
        ["relevant", "relevant"],
        {"relevant": 3},
        k=10,
    )

    assert score == pytest.approx(1.0)


def test_ndcg_does_not_compress_ranks_after_a_repeated_chunk() -> None:
    score = metrics.ndcg_at_k(
        ["primary", "primary", "secondary"],
        {"primary": 3, "secondary": 1},
        k=10,
    )
    expected = metrics._dcg([3, 0, 1]) / metrics._dcg([3, 1])

    assert score == pytest.approx(expected)


def test_binary_metrics_ignore_nonpositive_and_nonfinite_grades() -> None:
    judgments = {
        "zero": 0,
        "negative": -1,
        "not-a-number": math.nan,
        "infinite": math.inf,
    }

    assert metrics.recall_at_k(list(judgments), judgments, k=10) == 0.0
    assert metrics.mrr(list(judgments), judgments) == 0.0


def test_load_golden_queries_normalizes_a_yaml_suite(tmp_path: Path) -> None:
    golden_path = tmp_path / "suite.yml"
    golden_path.write_text(
        """
- id: nsi-001
  query: Qu'est-ce qu'un arbre binaire ?
  intent: definition
  collection: rag_nexus_nsi_terminale_specialite
  niveau: terminale
  relevant_chunk_ids: [chunk-1]
  must_not_return: [chunk-hors-niveau]
""".lstrip(),
        encoding="utf-8",
    )

    queries = run_eval.load_golden_queries(tmp_path, [])

    assert len(queries) == 1
    assert queries[0].query_id == "nsi-001"
    assert queries[0].graded_relevance == {"chunk-1": 1.0}
    assert queries[0].must_not_return == ["chunk-hors-niveau"]


def test_suite_fingerprint_is_canonical_and_covers_judgments() -> None:
    first = run_eval.GoldenQuery(
        query_id="nsi-001",
        query="Définir une pile",
        intent="definition",
        collection="rag_nexus_nsi_premiere_specialite",
        niveau="premiere",
        relevant_chunk_ids=["chunk-1", "chunk-2"],
        graded_relevance={"chunk-1": 3.0, "chunk-2": 1.0},
        must_not_return=["chunk-x"],
    )
    second = run_eval.GoldenQuery(
        query_id="nsi-002",
        query="Parcourir un arbre",
        intent="methode",
        collection="rag_nexus_nsi_terminale_specialite",
        niveau="terminale",
        relevant_chunk_ids=["chunk-3"],
        graded_relevance={"chunk-3": 2.0},
        must_not_return=[],
    )
    changed_judgment = run_eval.GoldenQuery(
        **{**vars(first), "graded_relevance": {"chunk-1": 2.0, "chunk-2": 1.0}}
    )

    fingerprint = run_eval._fingerprint_golden_suite([first, second])

    assert fingerprint == run_eval._fingerprint_golden_suite([second, first])
    assert fingerprint != run_eval._fingerprint_golden_suite(
        [changed_judgment, second]
    )


@pytest.mark.parametrize(
    ("yaml_payload", "expected_error"),
    [
        ("metadata: seulement\n", "clé queries attendue"),
        (
            """
- id: nsi-001
  query: Question
  intent: definition
  collection: collection_inconnue
  niveau: sixieme
  relevant_chunk_ids: [chunk-1]
  must_not_return: []
""",
            "niveau invalide",
        ),
        (
            """
- id: nsi-001
  query: Question
  intent: inconnu
  collection: rag_nexus_nsi_terminale_specialite
  niveau: premiere
  relevant_chunk_ids: [chunk-1]
  must_not_return: []
""",
            "intent invalide",
        ),
        (
            """
- id: nsi-001
  query: Question
  intent: definition
  collection: rag_nexus_nsi_terminale_specialite
  niveau: terminale
  relevant_chunk_ids: []
  graded_relevance: {}
  must_not_return: []
""",
            "jugement pertinent",
        ),
        (
            """
- id: nsi-001
  query: Question
  intent: definition
  collection: rag_nexus_nsi_terminale_specialite
  niveau: terminale
  relevant_chunk_ids: [chunk-1]
""",
            "must_not_return est requis",
        ),
        (
            """
- id: nsi-001
  query: Question
  intent: definition
  collection: rag_nexus_nsi_terminale_specialite
  niveau: terminale
  relevant_chunk_ids: [chunk-1]
  graded_relevance: {chunk-1: .nan}
  must_not_return: []
""",
            "grade doit être fini et positif ou nul",
        ),
        (
            """
- id: nsi-001
  query: Question
  intent: definition
  collection: rag_nexus_nsi_terminale_specialite
  niveau: terminale
  relevant_chunk_ids: [chunk-1]
  graded_relevance: {chunk-1: true}
  must_not_return: []
""",
            "grade doit être numérique",
        ),
    ],
)
def test_load_golden_queries_rejects_non_substantive_or_invalid_suites(
    tmp_path: Path,
    yaml_payload: str,
    expected_error: str,
) -> None:
    (tmp_path / "suite.yml").write_text(
        yaml_payload.lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=expected_error):
        run_eval.load_golden_queries(tmp_path, [])


def test_compare_baseline_rejects_an_ndcg_regression(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "config": BASELINE_CONFIG,
                "suite": {
                    "query_count": 1,
                    "top_k": 20,
                    "suite_fingerprint": SUITE_FINGERPRINT,
                },
                "metrics": {"ndcg_at_10": 0.8},
            }
        ),
        encoding="utf-8",
    )

    reasons = run_eval._compare_baseline(
        _eval_result(),
        baseline_path,
        drop_tolerance=0.02,
    )

    assert reasons == ["nDCG@10 en régression: 0.7000 < 0.8000 * (1 - 0.02)"]


@pytest.mark.parametrize(
    ("offline_fallback", "expected_mode"),
    [(False, "nominal"), (True, "offline_lexical")],
)
def test_evaluate_serializes_the_retrieval_mode(
    offline_fallback: bool,
    expected_mode: str,
) -> None:
    retrieval_module = SimpleNamespace(
        RERANK_CANDIDATES=50,
        RERANK_SCORE_THRESHOLD=1.9,
    )

    result = run_eval.evaluate_golden_set(
        [],
        top_k=20,
        retrieval_module=retrieval_module,
        offline_fallback=offline_fallback,
    )

    assert result.config["retrieval_mode"] == expected_mode


def test_real_endpoint_reports_only_the_canonical_lot40_configuration() -> None:
    retrieval_module = run_eval._load_module()
    before = (
        retrieval_module.RERANK_CANDIDATES,
        retrieval_module.RERANK_SCORE_THRESHOLD,
    )

    result = run_eval.evaluate_golden_set(
        [],
        top_k=20,
        retrieval_module=retrieval_module,
    )

    assert result.config == {
        "rerank_candidates": 50,
        "rerank_score_threshold": 1.9,
        "top_k": 20,
        "retrieval_mode": "nominal",
    }
    assert (
        retrieval_module.RERANK_CANDIDATES,
        retrieval_module.RERANK_SCORE_THRESHOLD,
    ) == before


@pytest.mark.parametrize(
    ("attribute", "noncanonical"),
    [("RERANK_CANDIDATES", 25), ("RERANK_SCORE_THRESHOLD", 1.5)],
)
def test_real_endpoint_noncanonical_configuration_fails_before_queries(
    attribute: str,
    noncanonical: int | float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retrieval_module = run_eval._load_module()
    query = run_eval.GoldenQuery(
        query_id="nsi-001",
        query="Question qui ne doit jamais être exécutée",
        intent="definition",
        collection="rag_nexus_nsi_terminale_specialite",
        niveau="terminale",
        relevant_chunk_ids=["chunk-1"],
        graded_relevance={"chunk-1": 1.0},
        must_not_return=[],
    )
    monkeypatch.setattr(retrieval_module, attribute, noncanonical)
    retrieve = MagicMock(side_effect=AssertionError("query exécutée avant validation"))
    monkeypatch.setattr(retrieval_module, "_retrieve_reviewed_hits", retrieve)

    with pytest.raises(ValueError, match="LOT43|canonique"):
        run_eval.evaluate_golden_set(
            [query],
            top_k=20,
            retrieval_module=retrieval_module,
        )

    retrieve.assert_not_called()


def test_calibration_sweep_is_disabled_before_lot43_without_mutating_endpoint() -> None:
    retrieval_module = run_eval._load_module()
    before = (
        retrieval_module.RERANK_CANDIDATES,
        retrieval_module.RERANK_SCORE_THRESHOLD,
    )

    with pytest.raises(ValueError, match="LOT43"):
        run_eval.run_sweep(
            [object()],
            retrieval_module=retrieval_module,
            top_k=20,
        )

    assert (
        retrieval_module.RERANK_CANDIDATES,
        retrieval_module.RERANK_SCORE_THRESHOLD,
    ) == before
    source = inspect.getsource(run_eval.run_sweep) + inspect.getsource(run_eval.main)
    assert "retrieval_module.RERANK_CANDIDATES =" not in source
    assert "retrieval_module.RERANK_SCORE_THRESHOLD =" not in source


def test_module_and_cli_help_present_sweep_as_reserved_and_refused_until_lot43(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_eval.__doc__ is not None
    assert "refusée jusqu’au LOT43" in run_eval.__doc__
    assert "effectue un sweep de calibration optionnel" not in run_eval.__doc__
    monkeypatch.setattr(sys, "argv", ["run_eval.py", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        run_eval.parse_args()

    assert exc_info.value.code == 0
    help_output = capsys.readouterr().out
    sweep_help = help_output[help_output.index("--sweep"):]
    assert "réservée" in sweep_help
    assert "refusée jusqu’au LOT43" in sweep_help


def test_evaluate_requires_enough_depth_for_recall_at_20() -> None:
    retrieval_module = SimpleNamespace(
        RERANK_CANDIDATES=50,
        RERANK_SCORE_THRESHOLD=1.9,
    )

    with pytest.raises(ValueError, match="top_k doit être >= 20"):
        run_eval.evaluate_golden_set(
            [],
            top_k=19,
            retrieval_module=retrieval_module,
        )


@pytest.mark.parametrize(
    ("config_key", "invalid_value", "expected_error"),
    [
        ("rerank_candidates", 0, "rerank_candidates"),
        ("rerank_score_threshold", math.nan, "rerank_score_threshold"),
        ("top_k", 19, "top_k"),
        ("retrieval_mode", "inconnu", "retrieval_mode"),
    ],
)
def test_validate_eval_result_rejects_invalid_runtime_configuration(
    config_key: str,
    invalid_value: object,
    expected_error: str,
) -> None:
    result = _eval_result()
    result.config[config_key] = invalid_value

    with pytest.raises(ValueError, match=expected_error):
        run_eval._validate_eval_result(result)


def test_main_does_not_write_a_baseline_that_fails_absolute_invariants(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "baseline.json"
    json_output = tmp_path / "report.json"
    args = SimpleNamespace(
        top_k=20,
        pg_rag_dsn="postgresql://example.invalid/db",
        rerank_candidates=None,
        rerank_score_threshold=None,
        golden_dir=tmp_path,
        golden_file=[],
        sweep=False,
        offline_fallback=False,
        write_baseline=True,
        baseline_path=baseline_path,
        json_output=json_output,
        ndcg_drop_tolerance=0.02,
    )
    retrieval_module = SimpleNamespace(
        RERANK_CANDIDATES=50,
        RERANK_SCORE_THRESHOLD=1.9,
    )
    monkeypatch.setattr(run_eval, "parse_args", lambda: args)
    monkeypatch.setattr(run_eval, "_load_module", lambda: retrieval_module)
    monkeypatch.setattr(run_eval, "load_golden_queries", lambda *_args: [object()])
    monkeypatch.setattr(
        run_eval,
        "evaluate_golden_set",
        lambda *_args, **_kwargs: _eval_result(ndcg_at_10=0.0),
    )

    assert run_eval.main() == 1
    assert not baseline_path.exists()
    assert not json_output.exists()


@pytest.mark.parametrize(
    ("rerank_candidates", "rerank_score_threshold", "expected_error"),
    [
        (0, None, "rerank-candidates"),
        (25, None, "LOT43|canonique"),
        (None, math.nan, "rerank-score-threshold"),
        (None, 1.5, "LOT43|canonique"),
    ],
)
def test_main_rejects_invalid_cli_rerank_parameters_before_loading_runtime(
    monkeypatch: pytest.MonkeyPatch,
    rerank_candidates: int | None,
    rerank_score_threshold: float | None,
    expected_error: str,
) -> None:
    args = SimpleNamespace(
        top_k=20,
        pg_rag_dsn="postgresql://example.invalid/db",
        rerank_candidates=rerank_candidates,
        rerank_score_threshold=rerank_score_threshold,
    )
    monkeypatch.setattr(run_eval, "parse_args", lambda: args)
    monkeypatch.setattr(
        run_eval,
        "_load_module",
        lambda: pytest.fail("runtime chargé malgré des paramètres CLI invalides"),
    )

    with pytest.raises(SystemExit, match=expected_error):
        run_eval.main()


def test_main_rejects_a_misleading_offline_calibration_sweep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = SimpleNamespace(
        top_k=20,
        rerank_candidates=None,
        rerank_score_threshold=None,
        sweep=True,
        offline_fallback=True,
        pg_rag_dsn="postgresql://example.invalid/db",
    )
    monkeypatch.setattr(run_eval, "parse_args", lambda: args)
    monkeypatch.setattr(
        run_eval,
        "_load_module",
        lambda: pytest.fail("runtime chargé malgré une combinaison CLI invalide"),
    )

    with pytest.raises(SystemExit, match="--sweep.*--offline-fallback"):
        run_eval.main()


def test_offline_text_fallback_orders_rows_before_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchall.return_value = []
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value = cursor
    driver = SimpleNamespace(connect=lambda _dsn: connection)
    monkeypatch.setattr(run_eval.importlib, "import_module", lambda _name: driver)

    run_eval._run_offline_text_fallback(
        "postgresql://example.invalid/db",
        "rag_nexus_nsi_terminale_specialite",
        ["arbre"],
        limit=20,
    )

    sql = cursor.execute.call_args.args[0]
    assert "ORDER BY chunk_id" in sql
    assert sql.index("ORDER BY chunk_id") < sql.index("LIMIT %s")


def test_offline_fts_uses_chunk_id_as_a_stable_tie_breaker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchall.return_value = []
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value = cursor
    driver = SimpleNamespace(connect=lambda _dsn: connection)
    monkeypatch.setattr(run_eval.importlib, "import_module", lambda _name: driver)

    run_eval._run_offline_query(
        "postgresql://example.invalid/db",
        "rag_nexus_nsi_terminale_specialite",
        "arbre | binaire",
        "to_tsquery",
        limit=20,
    )

    sql = cursor.execute.call_args.args[0]
    assert "ORDER BY lexical_score DESC, chunk_id ASC" in sql


@pytest.mark.parametrize("drop_tolerance", [math.nan, -0.1, 1.0, 2.0])
def test_compare_baseline_rejects_an_invalid_tolerance(
    tmp_path: Path,
    drop_tolerance: float,
) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "config": BASELINE_CONFIG,
                "suite": {
                    "query_count": 1,
                    "top_k": 20,
                    "suite_fingerprint": SUITE_FINGERPRINT,
                },
                "metrics": {"ndcg_at_10": 0.8},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="tolérance"):
        run_eval._compare_baseline(
            _eval_result(),
            baseline_path,
            drop_tolerance=drop_tolerance,
        )


@pytest.mark.parametrize(
    ("baseline_override", "expected_error"),
    [
        ({"metrics": {"ndcg_at_10": math.nan}}, "nombre fini"),
        ({"suite": {"query_count": 2, "top_k": 20}}, "query_count"),
        (
            {"config": {**BASELINE_CONFIG, "retrieval_mode": "offline_lexical"}},
            "configuration",
        ),
        (
            {
                "suite": {
                    "query_count": 1,
                    "top_k": 20,
                    "suite_fingerprint": "b" * 64,
                }
            },
            "empreinte",
        ),
    ],
)
def test_compare_baseline_rejects_an_invalid_or_incompatible_reference(
    tmp_path: Path,
    baseline_override: dict[str, object],
    expected_error: str,
) -> None:
    baseline: dict[str, object] = {
        "version": "1.0.0",
        "config": dict(BASELINE_CONFIG),
        "suite": {
            "query_count": 1,
            "top_k": 20,
            "suite_fingerprint": SUITE_FINGERPRINT,
        },
        "metrics": {"ndcg_at_10": 0.8},
    }
    baseline.update(baseline_override)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    with pytest.raises(ValueError, match=expected_error):
        run_eval._compare_baseline(
            _eval_result(),
            baseline_path,
            drop_tolerance=0.02,
        )
