from __future__ import annotations

import stat
from pathlib import Path

import pytest

from ingestor import r1_evidence_verifier_cli
from ingestor.r1_evidence_verifier import R1EvidenceReport

PASSING_REPORT = R1EvidenceReport(ready=True, gates={"BOOTSTRAP_RESOURCE_ROWS": 1})


def _common_args(tmp_path: Path, out: Path) -> list[str]:
    return [
        "--bootstrap",
        str(tmp_path / "bootstrap.json"),
        "--release-registry-path",
        str(tmp_path / "release-registry.json"),
        "--release-registry-sha256",
        "a" * 64,
        "--profile-root",
        str(tmp_path / "profiles"),
        "--profile-manifest-path",
        str(tmp_path / "manifest.yml"),
        "--out",
        str(out),
    ]


def test_cli_writes_report_with_private_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out = tmp_path / "report.json"
    monkeypatch.setattr(
        r1_evidence_verifier_cli, "verify_r1_evidence", lambda **_kwargs: PASSING_REPORT
    )

    result = r1_evidence_verifier_cli.main(_common_args(tmp_path, out))

    assert result == 0
    assert out.exists()
    assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_cli_refuses_existing_report_before_running_verification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An evidence report belongs to the audit event of its own run: a
    subsequent invocation must never silently overwrite it, and must fail
    before spending time re-running the (potentially large) verification."""
    out = tmp_path / "report.json"
    out.write_bytes(b"already published")

    def _verify_must_never_be_called(**_kwargs: object) -> R1EvidenceReport:
        raise AssertionError("verify_r1_evidence must never run when --out already exists")

    monkeypatch.setattr(r1_evidence_verifier_cli, "verify_r1_evidence", _verify_must_never_be_called)

    result = r1_evidence_verifier_cli.main(_common_args(tmp_path, out))

    assert result == 2
    assert out.read_bytes() == b"already published"


def test_cli_refuses_a_directory_as_report_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out = tmp_path / "report.json"
    out.mkdir()

    def _verify_must_never_be_called(**_kwargs: object) -> R1EvidenceReport:
        raise AssertionError("verify_r1_evidence must never run when --out is a directory")

    monkeypatch.setattr(r1_evidence_verifier_cli, "verify_r1_evidence", _verify_must_never_be_called)

    result = r1_evidence_verifier_cli.main(_common_args(tmp_path, out))

    assert result == 2


def test_cli_stdout_only_mode_still_works_without_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        r1_evidence_verifier_cli, "verify_r1_evidence", lambda **_kwargs: PASSING_REPORT
    )
    args = _common_args(tmp_path, tmp_path / "unused.json")[:-2]  # drop --out and its value

    result = r1_evidence_verifier_cli.main(args)

    assert result == 0
    captured = capsys.readouterr()
    assert "BOOTSTRAP_RESOURCE_ROWS=1" in captured.out
