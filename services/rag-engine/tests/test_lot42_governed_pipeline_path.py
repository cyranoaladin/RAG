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
        expected_attestation_id=verified.attestation_id,
    )

    assert [event[0] for event in events] == ["verify", "reviewed", "anchor"]
    assert events[0][1]["require_content_bound_authority"] is True
    assert events[0][1]["expected_attestation_id"] == verified.attestation_id
    assert "require_content_bound_authority" not in events[2][1]
    assert events[2][1]["expected_attestation_id"] == verified.attestation_id
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


def test_attestation_named_by_job_is_checked_before_review_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _path()
    expected_attestation_id = uuid4()

    def verify(_conn: object, **kwargs: object) -> object:
        assert kwargs["expected_attestation_id"] == expected_attestation_id
        raise RuntimeError("expected attestation does not match active attestation")

    monkeypatch.setattr(path, "verify_publication_attestation", verify)
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

    with pytest.raises(RuntimeError, match="expected attestation"):
        path.promote_reviewed_publication(
            _connection(),
            resource_id=uuid4(),
            run_id=uuid4(),
            expected_version=10,
            actor="publication-resume",
            current_content_sha256="a" * 64,
            current_profile_fingerprint="b" * 64,
            current_manifest_digest="c" * 64,
            expected_attestation_id=expected_attestation_id,
        )


def test_path_exposes_no_public_writer() -> None:
    """Aucune surface HTTP ne peut publier : la publication n'est jamais
    déclenchable depuis l'extérieur."""
    source = inspect.getsource(_path())

    assert "FastAPI" not in source
    assert "APIRouter" not in source


def test_the_worker_stages_for_review_but_never_publishes() -> None:
    """Ce que le worker a le droit de faire, et ce qu'il n'a pas le droit
    de faire.

    Le worker atteint désormais ``NEEDS_REVIEW`` lui-même : s'arrêter à
    ``ROUTED`` obligeait un appelant extérieur à porter les deux pas
    suivants, donc à prouver l'appelant plutôt que le pipeline.

    Mais il ne franchit pas la revue. ``promote_reviewed_publication`` et
    ``publish_governed_artifact`` restent hors de son code : un worker qui
    publierait sans attestation LOT42 supprimerait la frontière humaine
    que toute la chaîne existe pour tenir."""
    runner = inspect.getsource(
        importlib.import_module("ingestor.ingestion_worker.runner")
    )

    assert "stage_publication_for_review" in runner
    assert "promote_reviewed_publication" not in runner
    assert "publish_governed_artifact" not in runner
    assert "attempt_retrieval_eligible_transition" not in runner
