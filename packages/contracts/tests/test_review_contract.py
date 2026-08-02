from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from nexus_contracts import (
    ReviewDecisionPayload,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewQueueDocument,
    ReviewQueuePayload,
    ReviewQueueResponse,
)


def _queue_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "doc_id": "doc-1",
        "collection": "libre_terminale_maths",
        "source_label": "Programme de mathématiques",
        "source_uri": "https://example.invalid/programme.pdf",
        "rights": "officiel_public",
        "source_kind": "pdf",
        "type_doc": "programme_officiel",
        "chunk_count": 3,
        "first_indexed": datetime(2026, 8, 1, tzinfo=UTC),
        "last_indexed": None,
    }
    document.update(overrides)
    return document


def test_review_queue_payload_is_browser_safe_and_bounded() -> None:
    assert ReviewQueuePayload().model_dump() == {
        "collection": None,
        "limit": 50,
        "offset": 0,
    }
    assert ReviewQueuePayload(
        collection="libre_terminale_maths",
        limit=500,
        offset=2,
    ).collection == "libre_terminale_maths"

    for invalid in (
        {"limit": 0},
        {"limit": 501},
        {"limit": "50"},
        {"offset": -1},
        {"offset": "0"},
        {"collection": "Libre-Terminale"},
        {"tenant": "libre_terminale"},
    ):
        with pytest.raises(ValidationError):
            ReviewQueuePayload.model_validate(invalid)


def test_review_decision_payload_excludes_server_and_free_text_fields() -> None:
    payload = ReviewDecisionPayload(
        target_id="doc-1",
        decision="reviewed",
        collection="libre_terminale_maths",
    )
    assert payload.model_dump() == {
        "target_type": "doc",
        "target_id": "doc-1",
        "decision": "reviewed",
        "collection": "libre_terminale_maths",
    }

    for invalid in (
        {"target_id": "", "decision": "reviewed"},
        {"target_id": "x" * 257, "decision": "reviewed"},
        {"target_id": 1, "decision": "reviewed"},
        {"target_id": "doc-1", "target_type": "document", "decision": "reviewed"},
        {"target_id": "doc-1", "decision": "needs_review"},
        {"target_id": "doc-1", "decision": "reviewed", "tenant": "libre_terminale"},
        {"target_id": "doc-1", "decision": "reviewed", "reason": "texte libre"},
    ):
        with pytest.raises(ValidationError):
            ReviewDecisionPayload.model_validate(invalid)


def test_review_decision_request_requires_server_derived_tenant() -> None:
    with pytest.raises(ValidationError):
        ReviewDecisionRequest(target_id="chunk-1", decision="quarantined")

    request = ReviewDecisionRequest(
        target_type="chunk",
        target_id="chunk-1",
        decision="quarantined",
        collection="libre_terminale_nsi",
        tenant="libre_terminale",
    )
    assert request.tenant == "libre_terminale"

    with pytest.raises(ValidationError):
        ReviewDecisionRequest(
            target_id="doc-1",
            decision="reviewed",
            tenant="Libre-Terminale",
        )


def test_review_queue_response_validates_documents_and_returned_count() -> None:
    response = ReviewQueueResponse(
        total_pending_docs=1,
        returned=1,
        offset=0,
        documents=[_queue_document()],
    )
    assert isinstance(response.documents[0], ReviewQueueDocument)
    assert response.documents[0].chunk_count == 3

    invalid_responses = (
        {
            "total_pending_docs": 1,
            "returned": 0,
            "offset": 0,
            "documents": [_queue_document()],
        },
        {
            "total_pending_docs": "1",
            "returned": 1,
            "offset": 0,
            "documents": [_queue_document()],
        },
        {
            "total_pending_docs": 1,
            "returned": -1,
            "offset": 0,
            "documents": [],
        },
        {
            "total_pending_docs": 1,
            "returned": 1,
            "offset": 0,
            "documents": [_queue_document(chunk_count=0)],
        },
        {
            "total_pending_docs": 1,
            "returned": 1,
            "offset": 0,
            "documents": [_queue_document()],
            "extra": True,
        },
    )
    for invalid in invalid_responses:
        with pytest.raises(ValidationError):
            ReviewQueueResponse.model_validate(invalid)


def test_review_queue_document_bounds_provenance_fields() -> None:
    for invalid in (
        _queue_document(doc_id=""),
        _queue_document(doc_id="x" * 257),
        _queue_document(source_label="x" * 1025),
        _queue_document(source_uri="x" * 4097),
        _queue_document(rights="x" * 129),
        _queue_document(source_kind="x" * 129),
        _queue_document(type_doc="x" * 129),
    ):
        with pytest.raises(ValidationError):
            ReviewQueueDocument.model_validate(invalid)


def test_review_decision_response_is_closed_and_bounded() -> None:
    response = ReviewDecisionResponse(
        target_type="chunk",
        target_id="chunk-1",
        decision="quarantined",
        chunks_affected=1,
        cache_invalidated_this_worker=True,
        max_stale_other_workers_s=0,
    )
    assert response.max_stale_other_workers_s == 0

    valid = response.model_dump()
    for field, value in (
        ("target_type", "document"),
        ("target_id", 1),
        ("decision", "needs_review"),
        ("chunks_affected", 0),
        ("chunks_affected", "1"),
        ("cache_invalidated_this_worker", 0),
        ("cache_invalidated_this_worker", 1),
        ("cache_invalidated_this_worker", "false"),
        ("cache_invalidated_this_worker", "true"),
        ("max_stale_other_workers_s", False),
        ("max_stale_other_workers_s", 0.0),
        ("max_stale_other_workers_s", 1),
        ("extra", True),
    ):
        invalid = {**valid, field: value}
        with pytest.raises(ValidationError):
            ReviewDecisionResponse.model_validate(invalid)
