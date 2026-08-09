"""Chemin LOT42 interne, répétable, jamais activé par le runner vivant."""

from __future__ import annotations

import importlib
import inspect
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from nexus_contracts.resource_state import ResourceState

from ingestor.ingestion_control.transitions import TransitionResult


def _path() -> Any:
    return importlib.import_module(
        "ingestor.ingestion_control.governed_publication_path"
    )


def _connection() -> SimpleNamespace:
    return SimpleNamespace(transaction=lambda: nullcontext())


def test_stage_path_is_exactly_routed_staged_needs_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _path()
    resource_id, run_id, job_id = uuid4(), uuid4(), uuid4()
    calls: list[dict[str, object]] = []

    def transition(_conn: object, **kwargs: object) -> TransitionResult:
        calls.append(kwargs)
        expected = kwargs["expected_state"]
        target = kwargs["new_state"]
        version = kwargs["expected_version"]
        assert isinstance(expected, ResourceState)
        assert isinstance(target, ResourceState)
        assert isinstance(version, int)
        return TransitionResult(
            resource_id=resource_id,
            from_state=expected,
            to_state=target,
            state_version=version + 1,
        )

    monkeypatch.setattr(path, "cas_transition", transition)

    result = path.stage_publication_for_review(
        _connection(),
        resource_id=resource_id,
        run_id=run_id,
        expected_version=8,
        actor="h2-rehearsal",
        job_id=job_id,
    )

    assert [(call["expected_state"], call["new_state"]) for call in calls] == [
        (ResourceState.ROUTED, ResourceState.STAGED),
        (ResourceState.STAGED, ResourceState.NEEDS_REVIEW),
    ]
    assert [call["expected_version"] for call in calls] == [8, 9]
    assert all(call["run_id"] == run_id for call in calls)
    assert all(call["job_id"] == job_id for call in calls)
    assert result.needs_review.state_version == 10


def test_review_path_verifies_then_uses_the_unique_lot42_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _path()
    resource_id, run_id, job_id = uuid4(), uuid4(), uuid4()
    events: list[tuple[str, dict[str, object]]] = []
    verified = SimpleNamespace(
        attestation_id=uuid4(),
        review_id="LOT42-H2-REVIEW",
        attestation_digest="d" * 64,
    )

    def verify(_conn: object, **kwargs: object) -> object:
        events.append(("verify", kwargs))
        return verified

    def transition(_conn: object, **kwargs: object) -> TransitionResult:
        events.append(("reviewed", kwargs))
        assert kwargs["expected_state"] is ResourceState.NEEDS_REVIEW
        assert kwargs["new_state"] is ResourceState.REVIEWED
        return TransitionResult(
            resource_id=resource_id,
            from_state=ResourceState.NEEDS_REVIEW,
            to_state=ResourceState.REVIEWED,
            state_version=11,
        )

    def anchor(_conn: object, **kwargs: object) -> TransitionResult:
        events.append(("anchor", kwargs))
        assert kwargs["expected_version"] == 11
        return TransitionResult(
            resource_id=resource_id,
            from_state=ResourceState.REVIEWED,
            to_state=ResourceState.RETRIEVAL_ELIGIBLE,
            state_version=12,
        )

    monkeypatch.setattr(path, "verify_publication_attestation", verify)
    monkeypatch.setattr(path, "cas_transition", transition)
    monkeypatch.setattr(path, "attempt_retrieval_eligible_transition", anchor)

    result = path.promote_reviewed_publication(
        _connection(),
        resource_id=resource_id,
        run_id=run_id,
        expected_version=10,
        actor="h2-rehearsal",
        current_content_sha256="a" * 64,
        current_profile_fingerprint="b" * 64,
        current_manifest_digest="c" * 64,
        job_id=job_id,
    )

    assert [event[0] for event in events] == ["verify", "reviewed", "anchor"]
    assert events[0][1]["require_content_bound_authority"] is True
    assert "require_content_bound_authority" not in events[2][1]
    assert result.attestation is verified
    assert result.reviewed.state_version == 11
    assert result.retrieval_eligible.state_version == 12


def test_failed_review_verification_never_changes_resource_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _path()
    monkeypatch.setattr(
        path,
        "verify_publication_attestation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("review denied")),
    )
    monkeypatch.setattr(
        path,
        "cas_transition",
        lambda *_args, **_kwargs: pytest.fail("state transition must not run"),
    )
    monkeypatch.setattr(
        path,
        "attempt_retrieval_eligible_transition",
        lambda *_args, **_kwargs: pytest.fail("LOT42 anchor must not run"),
    )

    with pytest.raises(RuntimeError, match="review denied"):
        path.promote_reviewed_publication(
            _connection(),
            resource_id=uuid4(),
            run_id=uuid4(),
            expected_version=10,
            actor="h2-rehearsal",
            current_content_sha256="a" * 64,
            current_profile_fingerprint="b" * 64,
            current_manifest_digest="c" * 64,
        )


def test_path_is_dormant_and_exposes_no_public_or_worker_writer() -> None:
    path = _path()
    source = inspect.getsource(path)
    runner = inspect.getsource(
        importlib.import_module("ingestor.ingestion_worker.runner")
    )

    assert "FastAPI" not in source
    assert "APIRouter" not in source
    assert "governed_publication_path" not in runner
    assert "publish_governed_artifact" not in runner
