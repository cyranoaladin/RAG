"""Contrat statique des fixtures synthétiques de parité A/B."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

from src.ingestor.engine_parity import (
    EngineParityError,
    ParityReasonCode,
    ParityVerdict,
    PassageUnit,
    compare_engine_parity,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
WITNESS_PATH = FIXTURES / "engine_parity_witness_v1.json"
CAPTURE_PATHS = (
    FIXTURES / "engine_parity_a_v1.json",
    FIXTURES / "engine_parity_b_v1.json",
)
SYNTHETIC_MARKER = "SYNTHETIC_TEST_ONLY"
NON_EVIDENCE_STATUS = "NOT_REAL_PARITY_EVIDENCE"
SHA256 = re.compile(r"[0-9a-f]{64}")
OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:#-]{0,127}")
SENSITIVE_VALUE = re.compile(
    r"(?:\bapi[_-]?key\b|bearer|password|secret|token|://|@)", re.IGNORECASE
)
QUERY_ALLOWLIST = ["q-nsi-premiere-pile", "q-nsi-terminale-complexite"]
EXPECTED_SCOPES = {
    "q-nsi-premiere-pile": {
        "collection": "rag_nexus_nsi_premiere_specialite",
        "matiere": "nsi",
        "niveau": "premiere",
        "voie": "gen",
        "statut_enseignement": "specialite",
    },
    "q-nsi-terminale-complexite": {
        "collection": "rag_nexus_nsi_terminale_specialite",
        "matiere": "nsi",
        "niveau": "terminale",
        "voie": "gen",
        "statut_enseignement": "specialite",
    },
}
SCOPE_KEYS = {
    "collection",
    "matiere",
    "niveau",
    "voie",
    "statut_enseignement",
}
UNIT_KEYS = {"source_sha256", "canonical_span_id", "content_hash"}
FORBIDDEN_KEYS = {
    "answer",
    "api_key",
    "content",
    "document",
    "embedding",
    "embeddings",
    "password",
    "secret",
    "text",
    "token",
}
WITNESS_KEYS = {
    "protocol_version",
    "fixture_marker",
    "evidence_status",
    "witness_id",
    "thresholds_status",
    "limits",
    "query_allowlist",
    "queries",
    "out_of_collection_witness",
}
CAPTURE_KEYS = {
    "protocol_version",
    "fixture_marker",
    "evidence_status",
    "capture_id",
    "engine",
    "witness_sha256",
    "queries",
}
QUERY_KEYS = {"query_id", "query", "k", "expected_scope", "expected_units"}
CAPTURE_QUERY_KEYS = {"query_id", "ordered_results"}
RESULT_KEYS = {"rank", "unit", "scope", "citation", "rights", "review_status"}
CITATION_KEYS = {"canonical_span_id", "source_id", "source_sha256"}
OUTSIDE_KEYS = {"query_id", "expected_disposition", "scope", "unit"}


def _load(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _walk(value: Any):
    yield value
    if isinstance(value, dict):
        for nested in value.values():
            yield from _walk(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk(nested)


def _assert_unit(unit: Any) -> None:
    assert isinstance(unit, dict)
    assert set(unit) == UNIT_KEYS
    assert SHA256.fullmatch(unit["source_sha256"])
    assert SHA256.fullmatch(unit["content_hash"])
    assert OPAQUE_ID.fullmatch(unit["canonical_span_id"])


def test_parity_fixtures_are_explicitly_synthetic_and_bound_to_witness() -> None:
    witness = _load(WITNESS_PATH)
    captures = [_load(path) for path in CAPTURE_PATHS]
    witness_sha256 = hashlib.sha256(WITNESS_PATH.read_bytes()).hexdigest()

    assert set(witness) == WITNESS_KEYS
    assert OPAQUE_ID.fullmatch(witness["witness_id"])
    assert witness["thresholds_status"] == "UNAPPROVED"
    for document in [witness, *captures]:
        assert document["fixture_marker"] == SYNTHETIC_MARKER
        assert document["evidence_status"] == NON_EVIDENCE_STATUS
        assert document["protocol_version"] == "NEXUS-ENGINE-PARITY-V1"
    assert {capture["engine"] for capture in captures} == {"A", "B"}
    assert all(set(capture) == CAPTURE_KEYS for capture in captures)
    assert all(OPAQUE_ID.fullmatch(capture["capture_id"]) for capture in captures)
    assert all(
        capture["witness_sha256"] == witness_sha256 for capture in captures
    )
    assert captures[0]["queries"] == captures[1]["queries"]
    assert all(path.stat().st_size <= witness["limits"]["max_capture_bytes"] for path in CAPTURE_PATHS)


def test_witness_closes_query_allowlist_scope_and_canonical_units() -> None:
    witness = _load(WITNESS_PATH)
    queries = witness["queries"]
    allowlist = witness["query_allowlist"]

    assert allowlist == QUERY_ALLOWLIST
    assert allowlist == [query["query_id"] for query in queries]
    assert len(allowlist) == len(set(allowlist))
    assert witness["limits"] == {
        "max_capture_bytes": 65536,
        "max_k": 3,
    }
    for query in queries:
        assert set(query) == QUERY_KEYS
        assert OPAQUE_ID.fullmatch(query["query_id"])
        assert isinstance(query["query"], str) and 0 < len(query["query"]) <= 200
        assert set(query["expected_scope"]) == SCOPE_KEYS
        assert query["expected_scope"] == EXPECTED_SCOPES[query["query_id"]]
        assert type(query["k"]) is int
        assert 0 < query["k"] <= witness["limits"]["max_k"]
        assert query["expected_units"]
        assert len(query["expected_units"]) == query["k"]
        assert query["expected_scope"]["matiere"] == "nsi"
        assert query["expected_scope"]["voie"] == "gen"
        assert query["expected_scope"]["statut_enseignement"] == "specialite"
        assert query["expected_scope"]["niveau"] in {"premiere", "terminale"}
        for unit in query["expected_units"]:
            _assert_unit(unit)

    outside = witness["out_of_collection_witness"]
    assert set(outside) == OUTSIDE_KEYS
    assert set(outside["scope"]) == SCOPE_KEYS
    _assert_unit(outside["unit"])
    assert outside["query_id"] in allowlist
    target = next(query for query in queries if query["query_id"] == outside["query_id"])
    assert outside["scope"]["collection"] != target["expected_scope"]["collection"]
    assert outside["scope"] == EXPECTED_SCOPES["q-nsi-terminale-complexite"]
    assert outside["expected_disposition"] == "OUT_OF_COLLECTION"
    for capture in [_load(path) for path in CAPTURE_PATHS]:
        captured_query = next(
            item for item in capture["queries"] if item["query_id"] == outside["query_id"]
        )
        assert outside["unit"] not in [
            result["unit"] for result in captured_query["ordered_results"]
        ]


@pytest.mark.parametrize("capture_path", CAPTURE_PATHS)
def test_capture_results_are_ordered_cited_reviewed_and_in_scope(
    capture_path: Path,
) -> None:
    witness = _load(WITNESS_PATH)
    capture = _load(capture_path)
    queries = {query["query_id"]: query for query in witness["queries"]}
    captured_queries = capture["queries"]

    assert [item["query_id"] for item in captured_queries] == witness[
        "query_allowlist"
    ]
    for captured_query in captured_queries:
        assert set(captured_query) == CAPTURE_QUERY_KEYS
        query = queries[captured_query["query_id"]]
        results = captured_query["ordered_results"]
        assert results
        assert [result["rank"] for result in results] == list(
            range(1, len(results) + 1)
        )
        assert all(type(result["rank"]) is int for result in results)
        assert len(results) == query["k"]
        assert [result["unit"] for result in results] == query["expected_units"]
        for result in results:
            assert set(result) == RESULT_KEYS
            _assert_unit(result["unit"])
            assert set(result["scope"]) == SCOPE_KEYS
            assert result["scope"] == query["expected_scope"]
            assert set(result["citation"]) == CITATION_KEYS
            assert OPAQUE_ID.fullmatch(result["citation"]["source_id"])
            assert result["citation"]["source_sha256"] == result["unit"][
                "source_sha256"
            ]
            assert result["citation"]["canonical_span_id"] == result["unit"][
                "canonical_span_id"
            ]
            assert result["rights"] in {"officiel_public", "usage_interne"}
            assert result["review_status"] == "reviewed"


def test_parity_fixtures_contain_no_long_or_sensitive_content() -> None:
    documents = [_load(WITNESS_PATH), *(_load(path) for path in CAPTURE_PATHS)]

    for document in documents:
        for value in _walk(document):
            if isinstance(value, dict):
                assert not FORBIDDEN_KEYS & set(value)
            elif isinstance(value, str):
                assert len(value) <= 200
                assert SENSITIVE_VALUE.search(value) is None


def test_passage_unit_requires_all_three_canonical_components() -> None:
    valid = {
        "source_sha256": "a" * 64,
        "canonical_span_id": "span-001",
        "content_hash": "b" * 64,
    }

    assert PassageUnit.from_mapping(valid) == PassageUnit(
        source_sha256="a" * 64,
        canonical_span_id="span-001",
        content_hash="b" * 64,
    )
    for field in tuple(valid):
        invalid = dict(valid)
        del invalid[field]
        with pytest.raises(EngineParityError):
            PassageUnit.from_mapping(invalid)


def _write_json(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(
        json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    return path


def _capture(engine: str) -> dict[str, Any]:
    path = CAPTURE_PATHS[0] if engine == "A" else CAPTURE_PATHS[1]
    return _load(path)


def _metrics(report, engine: str):
    return next(item for item in report.metrics if item.engine == engine)


def test_nominal_parity_is_metrics_only_without_approved_thresholds() -> None:
    first = compare_engine_parity(WITNESS_PATH, *CAPTURE_PATHS)
    second = compare_engine_parity(WITNESS_PATH, *CAPTURE_PATHS)

    assert first == second
    assert first.verdict is ParityVerdict.METRICS_ONLY_THRESHOLDS_UNAPPROVED
    assert first.reason_codes == ()
    assert first.passage_divergence_count == 0
    assert first.divergence_by_query == (
        ("q-nsi-premiere-pile", 0),
        ("q-nsi-terminale-complexite", 0),
    )
    assert all(
        (item.mean_recall_at_k, item.mean_reciprocal_rank, item.coverage) == (
            1.0,
            1.0,
            1.0,
        )
        for item in first.metrics
    )
    assert all(len(digest) == 64 for digest in first.input_digests)
    assert len(first.digest()) == 64


def test_parity_refuses_wrong_witness_binding_and_query_sets(tmp_path: Path) -> None:
    bad_digest = _capture("A")
    bad_digest["witness_sha256"] = "0" * 64
    with pytest.raises(EngineParityError):
        compare_engine_parity(
            WITNESS_PATH,
            _write_json(tmp_path / "bad-digest.json", bad_digest),
            CAPTURE_PATHS[1],
        )

    for name, mutate in (
        ("missing", lambda queries: queries.pop()),
        (
            "extra",
            lambda queries: queries.append(
                {"query_id": "q-extra", "ordered_results": []}
            ),
        ),
    ):
        capture = _capture("A")
        mutate(capture["queries"])
        with pytest.raises(EngineParityError):
            compare_engine_parity(
                WITNESS_PATH,
                _write_json(tmp_path / f"{name}.json", capture),
                CAPTURE_PATHS[1],
            )


def test_parity_refuses_non_string_allowlist_without_raw_type_error(
    tmp_path: Path,
) -> None:
    witness = _load(WITNESS_PATH)
    witness["query_allowlist"] = [{}]

    with pytest.raises(EngineParityError):
        compare_engine_parity(
            _write_json(tmp_path / "bad-allowlist.json", witness),
            *CAPTURE_PATHS,
        )


@pytest.mark.parametrize("k", (0, 4, True))
def test_parity_refuses_invalid_k_bounds(tmp_path: Path, k: Any) -> None:
    witness = _load(WITNESS_PATH)
    witness["queries"][0]["k"] = k

    with pytest.raises(EngineParityError):
        compare_engine_parity(
            _write_json(tmp_path / "bad-k.json", witness),
            *CAPTURE_PATHS,
        )


def test_parity_refuses_capture_over_declared_size_limit(tmp_path: Path) -> None:
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(
        CAPTURE_PATHS[0].read_bytes() + b" " * 65_536
    )

    with pytest.raises(EngineParityError):
        compare_engine_parity(WITNESS_PATH, oversized, CAPTURE_PATHS[1])


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    (
        (
            lambda result: result["scope"].update(collection="rag_divers"),
            ParityReasonCode.COLLECTION_SCOPE_MISMATCH,
        ),
        (
            lambda result: result["scope"].update(niveau="terminale"),
            ParityReasonCode.NIVEAU_SCOPE_MISMATCH,
        ),
        (
            lambda result: result["citation"].pop("source_id"),
            ParityReasonCode.CITATION_INCOMPLETE,
        ),
        (
            lambda result: result.update(rights="unknown"),
            ParityReasonCode.RIGHTS_UNKNOWN,
        ),
        (
            lambda result: result.update(review_status="pending"),
            ParityReasonCode.NOT_REVIEWED,
        ),
    ),
)
def test_parity_safety_invariants_fail_closed(
    tmp_path: Path, mutation, expected_reason: ParityReasonCode
) -> None:
    capture = _capture("B")
    mutation(capture["queries"][0]["ordered_results"][0])

    report = compare_engine_parity(
        WITNESS_PATH,
        CAPTURE_PATHS[0],
        _write_json(tmp_path / "unsafe.json", capture),
    )

    assert report.verdict is ParityVerdict.FAIL_CLOSED
    assert expected_reason in report.reason_codes


def test_parity_uses_canonical_rights_categories(tmp_path: Path) -> None:
    capture = _capture("B")
    capture["queries"][0]["ordered_results"][0]["rights"] = "public_allowed"

    report = compare_engine_parity(
        WITNESS_PATH,
        CAPTURE_PATHS[0],
        _write_json(tmp_path / "canonical-rights.json", capture),
    )

    assert ParityReasonCode.RIGHTS_UNKNOWN not in report.reason_codes


def test_out_of_collection_witness_is_zero_tolerance(tmp_path: Path) -> None:
    witness = _load(WITNESS_PATH)
    outside = witness["out_of_collection_witness"]
    capture = _capture("B")
    result = capture["queries"][0]["ordered_results"][1]
    result["unit"] = outside["unit"]
    result["citation"]["source_sha256"] = outside["unit"]["source_sha256"]
    result["citation"]["canonical_span_id"] = outside["unit"][
        "canonical_span_id"
    ]

    report = compare_engine_parity(
        WITNESS_PATH,
        CAPTURE_PATHS[0],
        _write_json(tmp_path / "outside.json", capture),
    )

    assert report.verdict is ParityVerdict.FAIL_CLOSED
    assert ParityReasonCode.OUT_OF_COLLECTION_RESULT in report.reason_codes


def test_parity_calculates_recall_rank_coverage_and_passage_divergence(
    tmp_path: Path,
) -> None:
    capture = _capture("B")
    capture["queries"][1]["ordered_results"] = []

    report = compare_engine_parity(
        WITNESS_PATH,
        CAPTURE_PATHS[0],
        _write_json(tmp_path / "partial.json", capture),
    )
    metrics = _metrics(report, "B")

    assert report.verdict is ParityVerdict.METRICS_ONLY_THRESHOLDS_UNAPPROVED
    assert metrics.mean_recall_at_k == pytest.approx(0.5)
    assert metrics.mean_reciprocal_rank == pytest.approx(0.5)
    assert metrics.coverage == pytest.approx(2 / 3)
    assert report.passage_divergence_count == 1
    assert report.divergence_by_query[-1] == ("q-nsi-terminale-complexite", 1)


def test_parity_metrics_detect_rank_order_inversion(tmp_path: Path) -> None:
    capture = _capture("B")
    results = capture["queries"][0]["ordered_results"]
    results.reverse()
    for rank, result in enumerate(results, start=1):
        result["rank"] = rank

    report = compare_engine_parity(
        WITNESS_PATH,
        CAPTURE_PATHS[0],
        _write_json(tmp_path / "reordered.json", capture),
    )

    assert _metrics(report, "B").mean_reciprocal_rank == pytest.approx(0.75)
    assert report.passage_divergence_count == 2
    assert report.divergence_by_query[0] == ("q-nsi-premiere-pile", 2)


@pytest.mark.parametrize(
    ("document_name", "path"),
    (
        ("witness", ("witness_id",)),
        ("capture", ("capture_id",)),
        (
            "capture",
            ("queries", 0, "ordered_results", 0, "citation", "source_id"),
        ),
    ),
)
def test_parity_rejects_sensitive_identifiers(
    tmp_path: Path, document_name: str, path: tuple[Any, ...]
) -> None:
    document = _load(WITNESS_PATH) if document_name == "witness" else _capture("B")
    target: Any = document
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = "operator-token-secret"
    mutated = _write_json(tmp_path / f"sensitive-{document_name}.json", document)

    with pytest.raises(EngineParityError):
        compare_engine_parity(
            mutated if document_name == "witness" else WITNESS_PATH,
            CAPTURE_PATHS[0],
            mutated if document_name == "capture" else CAPTURE_PATHS[1],
        )


def test_unmappable_result_is_refused_without_echoing_payload(tmp_path: Path) -> None:
    canary = "CANARY-UNMAPPABLE-RESULT"
    capture = _capture("B")
    capture["queries"][0]["ordered_results"][0]["unit"].pop("content_hash")
    capture["queries"][0]["ordered_results"][0]["unexpected"] = canary

    with pytest.raises(EngineParityError) as caught:
        compare_engine_parity(
            WITNESS_PATH,
            CAPTURE_PATHS[0],
            _write_json(tmp_path / "unmappable.json", capture),
        )

    assert canary not in str(caught.value)
