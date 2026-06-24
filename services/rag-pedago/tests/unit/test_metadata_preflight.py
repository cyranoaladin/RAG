from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from rag_pedago.paths import RAG_LOCAL_ROOT, REPO_ROOT

ROOT = REPO_ROOT
RAG_LOCAL = RAG_LOCAL_ROOT
PROTOCOL = ROOT / "docs/METADATA_PREFLIGHT_PROTOCOL.md"
MODULE = ROOT / "rag_pedago/imports/metadata_preflight.py"
FIXTURE_ROOT = ROOT / "data/fixtures/pilot_math_terminale"
TEMPLATE_ROOT = ROOT / "docs/templates"
PERMANENT_LEDGER = ROOT / "data/ledger/rag_pedago.sqlite"


def _ledger_marker() -> tuple[bool, int | None]:
    if not PERMANENT_LEDGER.exists():
        return False, None
    return True, PERMANENT_LEDGER.stat().st_mtime_ns


def _assert_ledger_unchanged(marker: tuple[bool, int | None]) -> None:
    existed, mtime = marker
    assert PERMANENT_LEDGER.exists() is existed
    if existed:
        assert PERMANENT_LEDGER.stat().st_mtime_ns == mtime


def test_protocol_and_module_exist() -> None:
    assert PROTOCOL.is_file()
    assert MODULE.is_file()


def test_metadata_preflight_returns_ready_status() -> None:
    from rag_pedago.imports.metadata_preflight import build_metadata_preflight_report

    report = build_metadata_preflight_report()

    assert report["status"] == "metadata_preflight_ready"
    assert report["issue_count"] == 0


def test_metadata_preflight_cli_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    from rag_pedago.imports.metadata_preflight import main

    assert main([]) == 0
    assert "status: metadata_preflight_ready" in capsys.readouterr().out


def test_report_contains_expected_statuses_and_limits() -> None:
    from rag_pedago.imports.metadata_preflight import build_metadata_preflight_report

    report = build_metadata_preflight_report()

    assert {
        "status",
        "issue_count",
        "checks",
        "template_status",
        "compile_status",
        "rehearsal_status",
        "real_draft_guard_status",
        "human_unlock_status",
        "unlock_gate_status",
        "data_staging_absent",
        "permanent_ledger_unchanged",
        "real_documents_absent",
    } <= set(report)
    assert report["template_status"] == "needs_completion"
    assert report["compile_status"] == "ready"
    assert report["rehearsal_status"] == "rehearsal_ok"
    assert report["real_draft_guard_status"] == "ready_for_human_locked_metadata_validation"
    assert report["human_unlock_status"] == "approved_for_metadata_only_next_step"
    assert report["unlock_gate_status"] == "approved_for_real_metadata_draft_preparation"
    assert report["data_staging_absent"] is True
    assert report["permanent_ledger_unchanged"] is True
    assert report["real_documents_absent"] is True
    assert report["limitations"]["pedagogical_content_validated"] is False
    assert report["limitations"]["ingestion_authorized"] is False


def test_each_subcheck_reports_expected_status() -> None:
    from rag_pedago.imports import metadata_preflight

    assert metadata_preflight.run_template_check()["status"] == "needs_completion"
    assert metadata_preflight.run_compile_check()["status"] == "ready"
    assert metadata_preflight.run_rehearsal_check()["status"] == "rehearsal_ok"
    assert (
        metadata_preflight.run_real_draft_guard_check()["status"]
        == "ready_for_human_locked_metadata_validation"
    )
    assert (
        metadata_preflight.run_human_unlock_check()["status"]
        == "approved_for_metadata_only_next_step"
    )
    assert (
        metadata_preflight.run_unlock_gate_check()["status"]
        == "approved_for_real_metadata_draft_preparation"
    )


def test_preflight_creates_no_staging_real_documents_or_ledger_change() -> None:
    from rag_pedago.imports.metadata_preflight import build_metadata_preflight_report

    marker = _ledger_marker()

    report = build_metadata_preflight_report()

    assert report["status"] == "metadata_preflight_ready"
    assert not (ROOT / "data/staging").exists()
    assert not [
        candidate
        for directory in (FIXTURE_ROOT, TEMPLATE_ROOT)
        for candidate in directory.rglob("*")
        if candidate.is_file() and candidate.suffix.lower() in {".pdf", ".docx", ".pptx", ".xlsx"}
    ]
    _assert_ledger_unchanged(marker)


def test_preflight_does_not_open_source_uri_or_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    from rag_pedago.imports.metadata_preflight import build_metadata_preflight_report

    original_open = builtins.open

    def fail_pdf_open(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if str(path).lower().endswith(".pdf"):
            raise AssertionError("PDF must not be opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fail_pdf_open)

    report = build_metadata_preflight_report()

    assert report["status"] == "metadata_preflight_ready"


def test_module_contains_no_forbidden_integrations() -> None:
    text = MODULE.read_text(encoding="utf-8")
    forbidden = [
        "requests",
        "httpx",
        "urllib",
        "socket",
        "subprocess",
        "qdrant",
        "psycopg",
        "docker",
        "open(",
        "read_bytes",
        "write_bytes",
        "Path(.*source_uri",
    ]
    assert not any(token in text for token in forbidden)


def test_rag_local_contains_no_lot_15i_artifacts() -> None:
    if RAG_LOCAL.exists():
        assert not (RAG_LOCAL / "rag_pedago/imports/metadata_preflight.py").exists()
        assert not (RAG_LOCAL / "tests/unit/test_metadata_preflight.py").exists()
        assert not (RAG_LOCAL / "docs/METADATA_PREFLIGHT_PROTOCOL.md").exists()


def test_blocked_subcheck_blocks_report(monkeypatch: pytest.MonkeyPatch) -> None:
    from rag_pedago.imports import metadata_preflight

    def blocked_check() -> dict:
        return {
            "name": "human_unlock",
            "status": "blocked",
            "expected_status": "approved_for_metadata_only_next_step",
            "ok": False,
            "issues": [{"code": "forced_failure", "field": "test", "message": "forced"}],
        }

    monkeypatch.setattr(metadata_preflight, "run_human_unlock_check", blocked_check)

    report = metadata_preflight.build_metadata_preflight_report()

    assert report["status"] == "blocked"
    assert report["issue_count"] > 0


def test_cli_returns_one_when_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    from rag_pedago.imports import metadata_preflight

    monkeypatch.setattr(
        metadata_preflight,
        "build_metadata_preflight_report",
        lambda: {"status": "blocked", "issue_count": 1, "issues": []},
    )

    assert metadata_preflight.main([]) == 1
