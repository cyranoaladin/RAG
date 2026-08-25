"""Comparaison pure et fail-closed des captures de parité A/B."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from enum import StrEnum
from itertools import zip_longest
from pathlib import Path
from typing import Any

from nexus_contracts.document import Rights

_SHA256 = re.compile(r"[0-9a-f]{64}")
_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:#-]{0,127}")
_SENSITIVE_IDENTIFIER = re.compile(
    r"(?:api[_-]?key|bearer|password|secret|token|://|@)", re.IGNORECASE
)
_MAX_WITNESS_BYTES = 1024 * 1024
_PROTOCOL = "NEXUS-ENGINE-PARITY-V1"
_SCOPE_KEYS = frozenset(
    {"collection", "matiere", "niveau", "voie", "statut_enseignement"}
)
_WITNESS_KEYS = frozenset(
    {
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
)
_CAPTURE_KEYS = frozenset(
    {
        "protocol_version",
        "fixture_marker",
        "evidence_status",
        "capture_id",
        "engine",
        "witness_sha256",
        "queries",
    }
)


class EngineParityError(ValueError):
    """Une entrée de parité ne respecte pas le contrat fermé."""


class ParityVerdict(StrEnum):
    """Verdicts fermés du comparateur hors runtime."""

    FAIL_CLOSED = "FAIL_CLOSED"
    METRICS_ONLY_THRESHOLDS_UNAPPROVED = "METRICS_ONLY_THRESHOLDS_UNAPPROVED"


class ParityReasonCode(StrEnum):
    """Invariants à tolérance zéro, distincts des métriques."""

    COLLECTION_SCOPE_MISMATCH = "COLLECTION_SCOPE_MISMATCH"
    NIVEAU_SCOPE_MISMATCH = "NIVEAU_SCOPE_MISMATCH"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    CITATION_INCOMPLETE = "CITATION_INCOMPLETE"
    CITATION_MISMATCH = "CITATION_MISMATCH"
    RIGHTS_UNKNOWN = "RIGHTS_UNKNOWN"
    NOT_REVIEWED = "NOT_REVIEWED"
    OUT_OF_COLLECTION_RESULT = "OUT_OF_COLLECTION_RESULT"


@dataclass(frozen=True)
class PassageUnit:
    """Identité portable d'un passage, indépendante du moteur."""

    source_sha256: str
    canonical_span_id: str
    content_hash: str

    @classmethod
    def from_mapping(cls, value: Any) -> PassageUnit:
        if not isinstance(value, dict) or set(value) != {
            "source_sha256",
            "canonical_span_id",
            "content_hash",
        }:
            raise EngineParityError("passage unit schema is invalid")
        source_sha256 = value.get("source_sha256")
        canonical_span_id = value.get("canonical_span_id")
        content_hash = value.get("content_hash")
        if not isinstance(source_sha256, str) or _SHA256.fullmatch(source_sha256) is None:
            raise EngineParityError("passage source digest is invalid")
        if not isinstance(content_hash, str) or _SHA256.fullmatch(content_hash) is None:
            raise EngineParityError("passage content digest is invalid")
        canonical_span_id = _opaque(
            canonical_span_id, field="canonical span id"
        )
        return cls(
            source_sha256=source_sha256,
            canonical_span_id=canonical_span_id,
            content_hash=content_hash,
        )


@dataclass(frozen=True)
class _Scope:
    collection: str
    matiere: str
    niveau: str
    voie: str
    statut_enseignement: str

    @classmethod
    def from_mapping(cls, value: Any) -> _Scope:
        document = _exact_mapping(value, expected=_SCOPE_KEYS, field="scope")
        values: dict[str, str] = {}
        for field in _SCOPE_KEYS:
            candidate = document.get(field)
            if (
                not isinstance(candidate, str)
                or not candidate
                or len(candidate) > 128
            ):
                raise EngineParityError("scope value is invalid")
            values[field] = candidate
        return cls(**values)


@dataclass(frozen=True)
class _ExpectedQuery:
    query_id: str
    k: int
    scope: _Scope
    expected_units: tuple[PassageUnit, ...]


@dataclass(frozen=True)
class _CapturedResult:
    rank: int
    unit: PassageUnit
    scope: _Scope
    citation: dict[str, str]
    rights: str
    review_status: str


@dataclass(frozen=True)
class _CapturedQuery:
    query_id: str
    results: tuple[_CapturedResult, ...]


@dataclass(frozen=True)
class EngineParityMetrics:
    engine: str
    mean_recall_at_k: float
    mean_reciprocal_rank: float
    coverage: float


@dataclass(frozen=True)
class EngineParityReport:
    verdict: ParityVerdict
    reason_codes: tuple[ParityReasonCode, ...]
    input_digests: tuple[str, str, str]
    metrics: tuple[EngineParityMetrics, ...]
    passage_divergence_count: int
    divergence_by_query: tuple[tuple[str, int], ...]
    synthetic_evidence: bool

    def digest(self) -> str:
        raw = json.dumps(
            asdict(self),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class _Witness:
    digest: str
    max_capture_bytes: int
    queries: tuple[_ExpectedQuery, ...]
    out_query_id: str
    out_unit: PassageUnit


def _exact_mapping(
    value: Any, *, expected: frozenset[str], field: str
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or not all(isinstance(key, str) for key in value)
        or frozenset(value) != expected
    ):
        raise EngineParityError(f"{field} schema is invalid")
    return value


def _opaque(value: Any, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or _OPAQUE_ID.fullmatch(value) is None
        or _SENSITIVE_IDENTIFIER.search(value) is not None
    ):
        raise EngineParityError(f"{field} is invalid")
    return value


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise EngineParityError("JSON document contains a duplicate key")
        document[key] = value
    return document


def _read_json(path: Path, *, max_bytes: int) -> tuple[dict[str, Any], str]:
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise EngineParityError("file size limit is invalid")
    descriptor = -1
    try:
        flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise EngineParityError("parity input is unavailable")
        if metadata.st_size > max_bytes:
            raise EngineParityError("parity input is too large")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            raw = stream.read(max_bytes + 1)
    except EngineParityError:
        raise
    except OSError:
        raise EngineParityError("parity input is unavailable") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(raw) > max_bytes:
        raise EngineParityError("parity input is too large")
    invalid = False
    try:
        document = json.loads(raw, object_pairs_hook=_unique_pairs)
    except EngineParityError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError):
        invalid = True
        document = None
    if invalid:
        raise EngineParityError("parity input is invalid")
    if not isinstance(document, dict):
        raise EngineParityError("parity input schema is invalid")
    return document, hashlib.sha256(raw).hexdigest()


def _parse_witness(path: Path) -> _Witness:
    document, digest = _read_json(path, max_bytes=_MAX_WITNESS_BYTES)
    _exact_mapping(document, expected=_WITNESS_KEYS, field="witness")
    if (
        document.get("protocol_version") != _PROTOCOL
        or document.get("fixture_marker") != "SYNTHETIC_TEST_ONLY"
        or document.get("evidence_status") != "NOT_REAL_PARITY_EVIDENCE"
        or document.get("thresholds_status") != "UNAPPROVED"
    ):
        raise EngineParityError("witness identity is invalid")
    _opaque(document.get("witness_id"), field="witness id")
    limits = _exact_mapping(
        document.get("limits"),
        expected=frozenset({"max_capture_bytes", "max_k"}),
        field="witness limits",
    )
    max_capture_bytes = limits.get("max_capture_bytes")
    max_k = limits.get("max_k")
    if (
        not isinstance(max_capture_bytes, int)
        or isinstance(max_capture_bytes, bool)
        or not 1 <= max_capture_bytes <= _MAX_WITNESS_BYTES
        or not isinstance(max_k, int)
        or isinstance(max_k, bool)
        or not 1 <= max_k <= 50
    ):
        raise EngineParityError("witness limits are invalid")
    raw_allowlist = document.get("query_allowlist")
    raw_queries = document.get("queries")
    if not isinstance(raw_allowlist, list) or not isinstance(raw_queries, list):
        raise EngineParityError("witness query set is invalid")
    if (
        not raw_queries
        or not all(isinstance(item, str) for item in raw_allowlist)
        or len(raw_allowlist) != len(set(raw_allowlist))
    ):
        raise EngineParityError("witness query set is invalid")
    queries: list[_ExpectedQuery] = []
    for raw_query in raw_queries:
        query = _exact_mapping(
            raw_query,
            expected=frozenset(
                {"query_id", "query", "k", "expected_scope", "expected_units"}
            ),
            field="witness query",
        )
        query_id = _opaque(query.get("query_id"), field="query id")
        query_text = query.get("query")
        k = query.get("k")
        raw_units = query.get("expected_units")
        if (
            not isinstance(query_text, str)
            or not 1 <= len(query_text) <= 200
            or not isinstance(k, int)
            or isinstance(k, bool)
            or not 1 <= k <= max_k
            or not isinstance(raw_units, list)
            or not raw_units
            or len(raw_units) > k
        ):
            raise EngineParityError("witness query is invalid")
        units = tuple(PassageUnit.from_mapping(item) for item in raw_units)
        if len(units) != len(set(units)):
            raise EngineParityError("witness query repeats a passage")
        queries.append(
            _ExpectedQuery(
                query_id=query_id,
                k=k,
                scope=_Scope.from_mapping(query.get("expected_scope")),
                expected_units=units,
            )
        )
    query_ids = tuple(item.query_id for item in queries)
    if raw_allowlist != list(query_ids):
        raise EngineParityError("witness allowlist is inconsistent")
    outside = _exact_mapping(
        document.get("out_of_collection_witness"),
        expected=frozenset({"query_id", "expected_disposition", "scope", "unit"}),
        field="out-of-collection witness",
    )
    out_query_id = _opaque(outside.get("query_id"), field="outside query id")
    if (
        out_query_id not in query_ids
        or outside.get("expected_disposition") != "OUT_OF_COLLECTION"
    ):
        raise EngineParityError("out-of-collection witness is invalid")
    out_scope = _Scope.from_mapping(outside.get("scope"))
    target_scope = next(item.scope for item in queries if item.query_id == out_query_id)
    if out_scope.collection == target_scope.collection:
        raise EngineParityError("out-of-collection scope is invalid")
    return _Witness(
        digest=digest,
        max_capture_bytes=max_capture_bytes,
        queries=tuple(queries),
        out_query_id=out_query_id,
        out_unit=PassageUnit.from_mapping(outside.get("unit")),
    )


def _parse_result(value: Any) -> _CapturedResult:
    document = _exact_mapping(
        value,
        expected=frozenset(
            {"rank", "unit", "scope", "citation", "rights", "review_status"}
        ),
        field="captured result",
    )
    rank = document.get("rank")
    if not isinstance(rank, int) or isinstance(rank, bool) or rank <= 0:
        raise EngineParityError("captured rank is invalid")
    citation_value = document.get("citation")
    if not isinstance(citation_value, dict) or not all(
        isinstance(key, str) for key in citation_value
    ):
        raise EngineParityError("citation schema is invalid")
    citation_keys = frozenset(citation_value)
    expected_citation_keys = frozenset(
        {"source_id", "source_sha256", "canonical_span_id"}
    )
    if citation_keys - expected_citation_keys:
        raise EngineParityError("citation schema is invalid")
    citation = {
        key: value
        for key, value in citation_value.items()
        if isinstance(value, str)
    }
    for field in ("source_id", "canonical_span_id"):
        if field in citation:
            _opaque(citation[field], field=f"citation {field}")
    rights = document.get("rights")
    review_status = document.get("review_status")
    if not isinstance(rights, str) or not isinstance(review_status, str):
        raise EngineParityError("governance metadata is invalid")
    return _CapturedResult(
        rank=rank,
        unit=PassageUnit.from_mapping(document.get("unit")),
        scope=_Scope.from_mapping(document.get("scope")),
        citation=citation,
        rights=rights,
        review_status=review_status,
    )


def _parse_capture(
    path: Path, *, expected_engine: str, witness: _Witness
) -> tuple[tuple[_CapturedQuery, ...], str]:
    document, digest = _read_json(path, max_bytes=witness.max_capture_bytes)
    _exact_mapping(document, expected=_CAPTURE_KEYS, field="capture")
    if (
        document.get("protocol_version") != _PROTOCOL
        or document.get("fixture_marker") != "SYNTHETIC_TEST_ONLY"
        or document.get("evidence_status") != "NOT_REAL_PARITY_EVIDENCE"
        or document.get("engine") != expected_engine
        or document.get("witness_sha256") != witness.digest
    ):
        raise EngineParityError("capture identity is invalid")
    _opaque(document.get("capture_id"), field="capture id")
    raw_queries = document.get("queries")
    if (
        not isinstance(raw_queries, list)
        or len(raw_queries) != len(witness.queries)
    ):
        raise EngineParityError("capture query set is invalid")
    expected_ids = tuple(item.query_id for item in witness.queries)
    captured: list[_CapturedQuery] = []
    for raw_query, expected_query in zip(raw_queries, witness.queries, strict=False):
        query = _exact_mapping(
            raw_query,
            expected=frozenset({"query_id", "ordered_results"}),
            field="captured query",
        )
        query_id = _opaque(query.get("query_id"), field="captured query id")
        raw_results = query.get("ordered_results")
        if not isinstance(raw_results, list) or len(raw_results) > expected_query.k:
            raise EngineParityError("captured result set is invalid")
        results = tuple(_parse_result(item) for item in raw_results)
        if tuple(item.rank for item in results) != tuple(range(1, len(results) + 1)):
            raise EngineParityError("captured result order is invalid")
        if len({item.unit for item in results}) != len(results):
            raise EngineParityError("captured result repeats a passage")
        captured.append(_CapturedQuery(query_id=query_id, results=results))
    if tuple(item.query_id for item in captured) != expected_ids:
        raise EngineParityError("capture query set is inconsistent")
    return tuple(captured), digest


def _safety_reasons(
    witness: _Witness, captures: tuple[tuple[_CapturedQuery, ...], ...]
) -> tuple[ParityReasonCode, ...]:
    reasons: set[ParityReasonCode] = set()
    expected = {item.query_id: item for item in witness.queries}
    for capture in captures:
        for query in capture:
            expected_query = expected[query.query_id]
            for result in query.results:
                if result.scope.collection != expected_query.scope.collection:
                    reasons.add(ParityReasonCode.COLLECTION_SCOPE_MISMATCH)
                if result.scope.niveau != expected_query.scope.niveau:
                    reasons.add(ParityReasonCode.NIVEAU_SCOPE_MISMATCH)
                if (
                    result.scope.matiere != expected_query.scope.matiere
                    or result.scope.voie != expected_query.scope.voie
                    or result.scope.statut_enseignement
                    != expected_query.scope.statut_enseignement
                ):
                    reasons.add(ParityReasonCode.SCOPE_MISMATCH)
                required_citation = {
                    "source_id",
                    "source_sha256",
                    "canonical_span_id",
                }
                if set(result.citation) != required_citation:
                    reasons.add(ParityReasonCode.CITATION_INCOMPLETE)
                elif (
                    result.citation["source_sha256"] != result.unit.source_sha256
                    or result.citation["canonical_span_id"]
                    != result.unit.canonical_span_id
                    or _OPAQUE_ID.fullmatch(result.citation["source_id"]) is None
                ):
                    reasons.add(ParityReasonCode.CITATION_MISMATCH)
                try:
                    rights = Rights(result.rights)
                except ValueError:
                    rights = Rights.unknown
                if rights is Rights.unknown:
                    reasons.add(ParityReasonCode.RIGHTS_UNKNOWN)
                if result.review_status != "reviewed":
                    reasons.add(ParityReasonCode.NOT_REVIEWED)
                if (
                    query.query_id == witness.out_query_id
                    and result.unit == witness.out_unit
                ):
                    reasons.add(ParityReasonCode.OUT_OF_COLLECTION_RESULT)
    return tuple(sorted(reasons, key=lambda item: item.value))


def _metrics(
    engine: str,
    witness: _Witness,
    capture: tuple[_CapturedQuery, ...],
) -> EngineParityMetrics:
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    found = 0
    expected_count = 0
    for expected_query, captured_query in zip(witness.queries, capture, strict=True):
        expected = set(expected_query.expected_units)
        actual = tuple(item.unit for item in captured_query.results)
        matches = sum(item in expected for item in actual)
        recalls.append(matches / len(expected))
        primary_expected = expected_query.expected_units[0]
        primary_ranks = [
            index
            for index, item in enumerate(actual, start=1)
            if item == primary_expected
        ]
        reciprocal_ranks.append(1 / primary_ranks[0] if primary_ranks else 0.0)
        found += len(expected & set(actual))
        expected_count += len(expected)
    return EngineParityMetrics(
        engine=engine,
        mean_recall_at_k=sum(recalls) / len(recalls),
        mean_reciprocal_rank=sum(reciprocal_ranks) / len(reciprocal_ranks),
        coverage=found / expected_count,
    )


def _compare_engine_parity(
    witness_path: Path, engine_a_path: Path, engine_b_path: Path
) -> EngineParityReport:
    witness = _parse_witness(witness_path)
    capture_a, digest_a = _parse_capture(
        engine_a_path, expected_engine="A", witness=witness
    )
    capture_b, digest_b = _parse_capture(
        engine_b_path, expected_engine="B", witness=witness
    )
    reasons = _safety_reasons(witness, (capture_a, capture_b))
    divergence_by_query = tuple(
        (
            expected_query.query_id,
            sum(
                unit_a != unit_b
                for unit_a, unit_b in zip_longest(
                    (item.unit for item in query_a.results),
                    (item.unit for item in query_b.results),
                )
            ),
        )
        for expected_query, query_a, query_b in zip(
            witness.queries, capture_a, capture_b, strict=True
        )
    )
    return EngineParityReport(
        verdict=(
            ParityVerdict.FAIL_CLOSED
            if reasons
            else ParityVerdict.METRICS_ONLY_THRESHOLDS_UNAPPROVED
        ),
        reason_codes=reasons,
        input_digests=(witness.digest, digest_a, digest_b),
        metrics=(
            _metrics("A", witness, capture_a),
            _metrics("B", witness, capture_b),
        ),
        passage_divergence_count=sum(count for _, count in divergence_by_query),
        divergence_by_query=divergence_by_query,
        synthetic_evidence=True,
    )


def compare_engine_parity(
    witness_path: Path, engine_a_path: Path, engine_b_path: Path
) -> EngineParityReport:
    """Comparer trois fichiers locaux sans conserver leur contenu dans l'exception."""

    sanitized_error: str | None = None
    try:
        return _compare_engine_parity(witness_path, engine_a_path, engine_b_path)
    except EngineParityError as caught:
        sanitized_error = str(caught)
    if sanitized_error is None:  # pragma: no cover
        raise EngineParityError("parity comparison failed")
    raise EngineParityError(sanitized_error)
