from __future__ import annotations

import os
import stat
import threading
from pathlib import Path

import pytest

from ingestor.atomic_artifact import (
    AtomicArtifactError,
    assert_publishable,
    publish_atomic_no_clobber,
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_publish_creates_file_with_exact_bytes_and_private_mode(tmp_path: Path) -> None:
    target = tmp_path / "artifact.json"
    publish_atomic_no_clobber(target, b'{"hello":"world"}')

    assert target.read_bytes() == b'{"hello":"world"}'
    assert _mode(target) == 0o600


def test_publish_refuses_existing_target_and_leaves_it_untouched(tmp_path: Path) -> None:
    target = tmp_path / "artifact.json"
    target.write_bytes(b"original")

    with pytest.raises(AtomicArtifactError, match="already exists"):
        publish_atomic_no_clobber(target, b"attacker-controlled-overwrite")

    assert target.read_bytes() == b"original"


def test_publish_refuses_directory_target(tmp_path: Path) -> None:
    target = tmp_path / "artifact.json"
    target.mkdir()

    with pytest.raises(AtomicArtifactError, match="directory"):
        publish_atomic_no_clobber(target, b"data")


def test_publish_leaves_no_partial_file_when_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "artifact.json"

    def _boom(_fd: int, _data: bytes) -> int:
        raise OSError("simulated interruption")

    monkeypatch.setattr(os, "write", _boom)

    with pytest.raises(OSError, match="simulated interruption"):
        publish_atomic_no_clobber(target, b"payload")

    assert not target.exists()
    # No stray dotfiles left behind in the target directory either.
    assert list(tmp_path.iterdir()) == []


def test_two_concurrent_publications_exactly_one_succeeds(tmp_path: Path) -> None:
    target = tmp_path / "artifact.json"
    payload_a = b"A" * 4096
    payload_b = b"B" * 4096
    results: dict[str, object] = {}
    barrier = threading.Barrier(2)

    def _attempt(name: str, payload: bytes) -> None:
        barrier.wait()
        try:
            publish_atomic_no_clobber(target, payload)
            results[name] = "ok"
        except AtomicArtifactError:
            results[name] = "refused"

    threads = [
        threading.Thread(target=_attempt, args=("a", payload_a)),
        threading.Thread(target=_attempt, args=("b", payload_b)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    outcomes = sorted(results.values())
    assert outcomes == ["ok", "refused"], results
    final = target.read_bytes()
    assert final in (payload_a, payload_b)
    assert len(final) == 4096  # never a partial/mixed write


def test_assert_publishable_accepts_absent_path(tmp_path: Path) -> None:
    assert_publishable(tmp_path / "does-not-exist-yet.json")  # must not raise


def test_assert_publishable_refuses_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "artifact.json"
    target.write_bytes(b"x")
    with pytest.raises(AtomicArtifactError, match="already exists"):
        assert_publishable(target)


def test_assert_publishable_refuses_directory(tmp_path: Path) -> None:
    target = tmp_path / "artifact.json"
    target.mkdir()
    with pytest.raises(AtomicArtifactError, match="directory"):
        assert_publishable(target)
