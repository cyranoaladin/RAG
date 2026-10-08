"""La qualification signée borne le claim et le reaper du Worker B."""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

import ingestor.ingestion_worker.multilevel_publication_resume_cli as cli
import ingestor.ingestion_worker.publication_resume as publication
from ingestor.embedding_provider import CallableEmbeddingProvider
from ingestor.ingestion_worker.publication_resume import (
    PublicationResumeDeps,
    PublicationResumeError,
    PublicationResumeOutcome,
)

MANIFEST = "5" * 64

class Connection:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def test_release_bound_iteration_passes_release_and_collection_before_claim(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(publication, "claim_job", lambda _conn, **kwargs: calls.append(kwargs) or None)
    deps = SimpleNamespace(owner="hggsp", claim_collections=("premiere", "terminale"),
                           claim_release_id="v5-hggsp", claim_release_manifest_sha256=MANIFEST)
    outcome = publication.run_publication_resume_iteration(Connection(), deps=deps)
    assert outcome.worked is False
    assert calls == [{"owner": "hggsp", "job_types": ("publication_resume",),
                      "collections": ("premiere", "terminale"), "release_id": "v5-hggsp",
                      "release_manifest_sha256": MANIFEST}]


def test_unqualified_iteration_keeps_previous_claim_signature(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(publication, "claim_job", lambda _conn, **kwargs: calls.append(kwargs) or None)
    deps = SimpleNamespace(owner="legacy", claim_collections=None, claim_release_id=None,
                           claim_release_manifest_sha256=None)
    publication.run_publication_resume_iteration(Connection(), deps=deps)
    assert calls == [{"owner": "legacy", "job_types": ("publication_resume",),
                      "collections": None}]


def test_worker_loop_reaps_only_qualified_release_and_keeps_exit_75(monkeypatch) -> None:
    reaps = []
    monkeypatch.setattr(cli, "reap_expired_job_leases", lambda _conn, **kwargs: reaps.append(kwargs) or [])
    args = argparse.Namespace(min_job_interval_s=0.0, max_consecutive_rate_limits=1,
                              rate_limit_max_wait_s=900.0, heartbeat_file=None,
                              max_idle_polls=5, once=False, poll_interval_s=0.0)
    outcome = PublicationResumeOutcome(worked=True, job_id=None, status="rate_limited",
                                       error="GitHub", retry_after_s=60.0)
    conn = Connection()
    code = cli._run_worker_loop(
        conn, deps=SimpleNamespace(claim_release_id="v5-hggsp",
                                   claim_release_manifest_sha256=MANIFEST,
                                   claim_collections=("premiere", "terminale")), args=args,
        max_iterations=2, iterate=lambda _conn, *, deps: outcome,
        sleep=lambda _seconds: None,
    )
    assert code == 75
    assert reaps == [{"release_id": "v5-hggsp", "release_manifest_sha256": MANIFEST,
                      "collections": ("premiere", "terminale")}]
    assert conn.commits == 1


def test_unqualified_worker_loop_keeps_previous_reaper_signature(monkeypatch) -> None:
    reaps = []
    monkeypatch.setattr(cli, "reap_expired_job_leases", lambda _conn, **kwargs: reaps.append(kwargs) or [])
    args = argparse.Namespace(min_job_interval_s=0.0, max_consecutive_rate_limits=3,
                              rate_limit_max_wait_s=900.0, heartbeat_file=None,
                              max_idle_polls=1, once=False, poll_interval_s=0.0)
    idle = PublicationResumeOutcome(worked=False, job_id=None, status=None, error=None)
    code = cli._run_worker_loop(
        Connection(), deps=SimpleNamespace(claim_release_id=None,
                                           claim_release_manifest_sha256=None), args=args,
        max_iterations=1, iterate=lambda _conn, *, deps: idle,
    )
    assert code == 0
    assert reaps == [{}]


def test_qualified_worker_requires_positive_collection_allowlist() -> None:
    qualification = SimpleNamespace(release_id="v5-hggsp")
    with pytest.raises(cli.RuntimeAuthorityStartupError):
        cli._require_qualified_claim_scope(qualification, None)
    assert cli._require_qualified_claim_scope(qualification, ("premiere", "terminale")) == (
        "premiere", "terminale"
    )
    assert cli._require_qualified_claim_scope(None, None) is None


def test_startup_log_names_claim_scope_and_release_id() -> None:
    source = (Path(cli.__file__)).read_text(encoding="utf-8")
    assert 'f"claim_scope={\',\'.join(claim_collections)} "' in source
    assert 'f"claim_release_id={qualification.release_id} "' in source


@pytest.mark.parametrize("release,manifest", [("v5-hggsp", None), (None, MANIFEST)])
def test_publication_deps_reject_partial_release_binding(
    release: str | None, manifest: str | None,
) -> None:
    with pytest.raises(PublicationResumeError, match="release qualification"):
        PublicationResumeDeps(
            owner="hggsp", product_dsn="postgresql://unused",
            artifact_reader=lambda **_kwargs: b"", extract_text=lambda _content: "",
            embedding_provider=CallableEmbeddingProvider(encoder=lambda _chunks: ()),
            claim_release_id=release, claim_release_manifest_sha256=manifest,
        )
