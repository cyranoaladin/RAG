"""A merged LOT42 review is usable only through the exact, live C binding."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from _local_github import VALID_TOKEN, LocalGitHub, local_github_server
from nexus_release_chain.public_successor_activation import PublicSuccessorActivationVerdict

from ingestor.ingestion_control import publication_attestation as attestation
from ingestor.ingestion_control.github_authority import (
    _load_trusted_review_module,
    activate_job_github_read_cache,
    fetch_blob_at_ref,
    force_live_github_reads,
    job_github_read_cache,
)

SHA = "a" * 64
BASE = "b" * 40
HEAD = "c" * 40
TREE = "d" * 40
CHALLENGE = _load_trusted_review_module().build_challenge({
    "protocol": "NEXUS-TRUSTED-REVIEW-V1", "repository": "cyranoaladin/RAG",
    "pull_request": 338, "base_ref": "main", "base_sha": BASE,
    "head_sha": HEAD, "author": "cyranoaladin", "reviewer": "abenrhouma",
})
BINDING = (BASE, HEAD, TREE, 5489094640, CHALLENGE, "abenrhouma")


class Refused(RuntimeError):
    pass


class Invalidator:
    def fail(self, reason: str) -> Refused:
        return Refused(reason)

    def require_equal(self, field: str, stored: Any, current: Any) -> None:
        if stored != current:
            raise Refused(f"{field} drift")


def _verdict() -> PublicSuccessorActivationVerdict:
    return PublicSuccessorActivationVerdict(
        release_id="public-release", content_anchor_sha256=SHA,
        content_manifest_sha256=SHA, authority_envelope_sha256=SHA,
        artifact_registry_sha256=SHA, release_registry_sha256=SHA,
        scope_authority_sha256=SHA, subject_sha256_by_collection={},
        scope_sha256_by_id={}, counts={},
        expires_at_utc=datetime.now(UTC) + timedelta(hours=1),
        verified_at_utc=datetime.now(UTC),
        publication_batch_review_id="lot42-public-release",
        publication_batch_review_digest=SHA,
        publication_batch_review_binding=BINDING,
    )


def _row() -> dict[str, Any]:
    return {
        "release_id": "public-release",
        "review_id": "lot42-public-release",
        "attestation_digest": SHA,
        "release_batch_review_digest": SHA,
        "human_review_repository": "cyranoaladin/RAG",
        "human_review_pull_request": 338,
        "human_review_base_sha": BASE,
        "human_review_head_sha": HEAD,
        "human_review_review_id": BINDING[3],
        "human_review_reviewer": BINDING[5],
        "human_review_challenge": BINDING[4],
        "human_review_submitted_at": datetime(2026, 8, 8, 10, tzinfo=UTC),
    }


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    state = LocalGitHub()
    state.add_approved_pr(number=338, head_sha=HEAD, base_sha=BASE,
                          review_id=BINDING[3])
    state.close_pr(338)
    state.pulls[338].update(
        merged=True, merged_at="2026-10-12T10:00:00Z",
        merge_commit_sha="e" * 40,
    )
    # GitHub's base branch moves after the merge. C still binds the base
    # from the exact-head approval, not today's main SHA.
    state.pulls[338]["base"]["sha"] = "f" * 40
    with local_github_server(state) as url:
        monkeypatch.setenv("NEXUS_GITHUB_API_BASE", url)
        monkeypatch.setenv("NEXUS_GITHUB_TOKEN", VALID_TOKEN)
        yield state


def test_merged_batch_review_accepts_only_live_exact_c_binding(
    github: LocalGitHub,
) -> None:
    result = attestation._verify_human_review(
        _row(), Invalidator(), batch_authority=_verdict(),
    )
    assert result.approved and result.head_sha == HEAD
    assert result.review_id == BINDING[3]


def test_merged_review_accepts_api_version_omitted_merge_commit_sha(
    github: LocalGitHub,
) -> None:
    # GitHub REST 2026-03-10 currently returns null for this field on PR338,
    # while the signed historical C receipt carries the exact merge SHA.
    github.pulls[338]["merge_commit_sha"] = None
    result = attestation._verify_human_review(
        _row(), Invalidator(), batch_authority=_verdict(),
    )
    assert result.approved and result.head_pinned_status == "success"


def test_newest_head_pinned_failure_cannot_be_masked_by_older_success(
    github: LocalGitHub,
) -> None:
    github.head_pinned_statuses = [
        {"context": "trusted-human-review/head-pinned", "state": "failure",
         "created_at": "2026-10-12T11:00:00Z", "id": 2},
        {"context": "trusted-human-review/head-pinned", "state": "success",
         "created_at": "2026-10-12T09:53:25Z", "id": 1},
    ]
    with pytest.raises(Refused, match="merged_review_differs_from_c"):
        attestation._verify_human_review(
            _row(), Invalidator(), batch_authority=_verdict(),
        )


def test_ambiguous_head_pinned_chronology_refuses(github: LocalGitHub) -> None:
    github.head_pinned_statuses = [
        {"context": "trusted-human-review/head-pinned", "state": "failure",
         "created_at": "2026-10-12T11:00:00Z", "id": 2},
        {"context": "trusted-human-review/head-pinned", "state": "success",
         "created_at": "2026-10-12T11:00:00Z", "id": 2},
    ]
    with pytest.raises(Refused, match="merged_review_differs_from_c"):
        attestation._verify_human_review(
            _row(), Invalidator(), batch_authority=_verdict(),
        )


def test_job_cache_reuses_only_intermediate_reads_and_final_review_is_live(
    github: LocalGitHub,
) -> None:
    with job_github_read_cache():
        attestation._verify_human_review(
            _row(), Invalidator(), batch_authority=_verdict(),
        )
        initial_gets = len(github.request_log)
        assert initial_gets == 5
        activate_job_github_read_cache()
        github.dismiss_reviews(338)
        # Intermediate DB/authority checkpoints can reuse the just-verified
        # external snapshot, but the last product-transaction check cannot.
        attestation._verify_human_review(
            _row(), Invalidator(), batch_authority=_verdict(),
        )
        assert len(github.request_log) == initial_gets
        force_live_github_reads()
        with pytest.raises(Refused, match="no longer approved"):
            attestation._verify_human_review(
                _row(), Invalidator(), batch_authority=_verdict(),
            )
        assert len(github.request_log) >= initial_gets + 5


def test_job_cache_is_discarded_between_jobs(github: LocalGitHub) -> None:
    with job_github_read_cache():
        attestation._verify_human_review(
            _row(), Invalidator(), batch_authority=_verdict(),
        )
    github.dismiss_reviews(338)
    with job_github_read_cache():
        with pytest.raises(Refused, match="no longer approved"):
            attestation._verify_human_review(
                _row(), Invalidator(), batch_authority=_verdict(),
            )


def test_job_cache_does_not_survive_an_exception(github: LocalGitHub) -> None:
    with pytest.raises(RuntimeError, match="interrupted"):
        with job_github_read_cache():
            attestation._verify_human_review(
                _row(), Invalidator(), batch_authority=_verdict(),
            )
            activate_job_github_read_cache()
            raise RuntimeError("interrupted")
    github.dismiss_reviews(338)
    with pytest.raises(Refused, match="no longer approved"):
        attestation._verify_human_review(
            _row(), Invalidator(), batch_authority=_verdict(),
        )


def test_job_cache_key_includes_exact_blob_ref_and_path(github: LocalGitHub) -> None:
    github.put_blob(path="proof/one.json", ref=HEAD, content=b"one")
    github.put_blob(path="proof/two.json", ref=HEAD, content=b"two")
    other_head = "8" * 40
    github.put_blob(path="proof/one.json", ref=other_head, content=b"new")
    with job_github_read_cache():
        assert fetch_blob_at_ref(
            repository="cyranoaladin/RAG", path="proof/one.json", ref=HEAD,
        ).content == b"one"
        activate_job_github_read_cache()
        assert fetch_blob_at_ref(
            repository="cyranoaladin/RAG", path="proof/one.json", ref=HEAD,
        ).content == b"one"
        assert len(github.request_log) == 1
        assert fetch_blob_at_ref(
            repository="cyranoaladin/RAG", path="proof/two.json", ref=HEAD,
        ).content == b"two"
        assert fetch_blob_at_ref(
            repository="cyranoaladin/RAG", path="proof/one.json", ref=other_head,
        ).content == b"new"
        assert len(github.request_log) == 3


def test_final_http_403_refuses_after_cached_intermediate_review(
    github: LocalGitHub,
) -> None:
    with job_github_read_cache():
        attestation._verify_human_review(
            _row(), Invalidator(), batch_authority=_verdict(),
        )
        activate_job_github_read_cache()
        github.force_status = 403
        attestation._verify_human_review(
            _row(), Invalidator(), batch_authority=_verdict(),
        )
        force_live_github_reads()
        with pytest.raises(Refused, match="transport failure"):
            attestation._verify_human_review(
                _row(), Invalidator(), batch_authority=_verdict(),
            )


def test_without_public_job_context_all_checks_remain_live(github: LocalGitHub) -> None:
    attestation._verify_human_review(
        _row(), Invalidator(), batch_authority=_verdict(),
    )
    first = len(github.request_log)
    assert first == 5
    attestation._verify_human_review(
        _row(), Invalidator(), batch_authority=_verdict(),
    )
    assert len(github.request_log) == 2 * first


@pytest.mark.parametrize("change", [
    "missing_c", "expired_c", "head", "base", "review_id", "challenge",
    "reviewer", "digest", "release", "revoked_reviewer",
])
def test_merged_batch_review_refuses_missing_stale_or_mismatched_c(
    github: LocalGitHub, change: str,
) -> None:
    row = _row()
    verdict = _verdict()
    if change == "missing_c":
        verdict = None
    elif change == "expired_c":
        verdict = replace(verdict, expires_at_utc=datetime.now(UTC) - timedelta(seconds=1))
    elif change == "digest":
        row["release_batch_review_digest"] = "f" * 64
    elif change == "release":
        row["release_id"] = "other-release"
    elif change == "revoked_reviewer":
        github.permissions["abenrhouma"] = {"permission": "read", "role_name": "read"}
    elif change in {"head", "base", "review_id", "challenge", "reviewer"}:
        row["human_review_" + change + ("_sha" if change in {"head", "base"} else "")] = "wrong"
    with pytest.raises(Refused):
        attestation._verify_human_review(row, Invalidator(), batch_authority=verdict)


def test_closed_review_without_historical_c_keeps_original_refusal(
    github: LocalGitHub,
) -> None:
    with pytest.raises(Refused, match="pull_request_not_open"):
        attestation._verify_human_review(_row(), Invalidator())


@pytest.mark.parametrize("change", [
    "dismissed", "review_absent", "unmerged", "head", "status",
    "status_absent", "transport", "c_before_merge", "merge_non_utc", "c_non_utc",
])
def test_merged_review_live_sabotage_fails_closed(
    github: LocalGitHub, change: str,
) -> None:
    verdict = _verdict()
    if change == "dismissed":
        github.dismiss_reviews(338)
    elif change == "review_absent":
        github.reviews[338] = []
    elif change == "unmerged":
        github.pulls[338]["merged"] = False
    elif change == "head":
        github.move_head(338, "9" * 40)
    elif change == "status":
        github.fail_head_pinned()
    elif change == "status_absent":
        github.head_pinned_state = ""
    elif change == "transport":
        github.force_status = 403
    elif change == "c_before_merge":
        verdict = replace(verdict, verified_at_utc=datetime(2026, 10, 12, 9, tzinfo=UTC))
    elif change == "merge_non_utc":
        github.pulls[338]["merged_at"] = "2026-10-12T11:00:00+01:00"
    elif change == "c_non_utc":
        verdict = replace(verdict, verified_at_utc=datetime.fromisoformat(
            "2026-10-12T22:00:00+02:00",
        ))
    with pytest.raises(Refused):
        attestation._verify_human_review(_row(), Invalidator(), batch_authority=verdict)
