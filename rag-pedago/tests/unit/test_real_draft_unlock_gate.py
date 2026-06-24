from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from rag_pedago.paths import RAG_LOCAL_ROOT, REPO_ROOT

ROOT = REPO_ROOT
RAG_LOCAL = RAG_LOCAL_ROOT
PROTOCOL = ROOT / "docs/REAL_DRAFT_UNLOCK_GATE_PROTOCOL.md"
FIXTURE_DIR = ROOT / "data/fixtures/pilot_math_terminale/real_draft_unlock_gate"
VALID_UNLOCK = FIXTURE_DIR / "unlock.valid.json"
VALID_DRAFT = FIXTURE_DIR / "draft.valid.jsonl"
INVALID_UNLOCK = FIXTURE_DIR / "unlock.invalid_rejected.json"
INVALID_DRAFTS = {
    "subject": FIXTURE_DIR / "draft.invalid_wrong_subject.jsonl",
    "level": FIXTURE_DIR / "draft.invalid_wrong_level.jsonl",
    "zone": FIXTURE_DIR / "draft.invalid_wrong_zone.jsonl",
    "too_many": FIXTURE_DIR / "draft.invalid_too_many_items.jsonl",
    "review": FIXTURE_DIR / "draft.invalid_missing_human_review.jsonl",
    "rights": FIXTURE_DIR / "draft.invalid_unknown_rights.jsonl",
}
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


def _issue_codes(report: dict) -> set[str]:
    return {str(issue["code"]) for issue in report["issues"]}


def test_protocol_and_fixtures_exist() -> None:
    assert PROTOCOL.is_file()
    assert VALID_UNLOCK.is_file()
    assert VALID_DRAFT.is_file()
    assert INVALID_UNLOCK.is_file()
    for fixture in INVALID_DRAFTS.values():
        assert fixture.is_file()


def test_gate_accepts_valid_unlock_and_valid_draft() -> None:
    from rag_pedago.imports.real_draft_unlock_gate import build_unlock_gate_report

    report = build_unlock_gate_report(VALID_UNLOCK, VALID_DRAFT)

    assert report["status"] == "approved_for_real_metadata_draft_preparation"
    assert report["issue_count"] == 0
    assert report["item_count"] == 2
    assert report["unlock_status"] == "approved_for_metadata_only_next_step"
    assert report["draft_status"] == "ready_for_human_locked_metadata_validation"
    assert report["max_items"] == 2


def test_cli_accepts_valid_pair_and_rejects_invalid_pairs(capsys: pytest.CaptureFixture[str]) -> None:
    from rag_pedago.imports.real_draft_unlock_gate import main

    assert main([str(VALID_UNLOCK), str(VALID_DRAFT)]) == 0
    assert "status: approved_for_real_metadata_draft_preparation" in capsys.readouterr().out

    assert main([str(INVALID_UNLOCK), str(VALID_DRAFT)]) == 1
    assert "status: blocked" in capsys.readouterr().out

    for fixture in INVALID_DRAFTS.values():
        assert main([str(VALID_UNLOCK), str(fixture)]) == 1
        assert "status: blocked" in capsys.readouterr().out


def test_gate_reports_expected_issue_codes_for_scope_mismatches() -> None:
    from rag_pedago.imports.real_draft_unlock_gate import build_unlock_gate_report

    assert "item_subject_out_of_scope" in _issue_codes(
        build_unlock_gate_report(VALID_UNLOCK, INVALID_DRAFTS["subject"])
    )
    assert "item_level_out_of_scope" in _issue_codes(
        build_unlock_gate_report(VALID_UNLOCK, INVALID_DRAFTS["level"])
    )
    assert "item_zone_out_of_scope" in _issue_codes(
        build_unlock_gate_report(VALID_UNLOCK, INVALID_DRAFTS["zone"])
    )
    assert "item_count_exceeds_unlock" in _issue_codes(
        build_unlock_gate_report(VALID_UNLOCK, INVALID_DRAFTS["too_many"])
    )
    assert "draft_guard_blocked" in _issue_codes(
        build_unlock_gate_report(VALID_UNLOCK, INVALID_DRAFTS["review"])
    )
    assert "draft_guard_blocked" in _issue_codes(
        build_unlock_gate_report(VALID_UNLOCK, INVALID_DRAFTS["rights"])
    )


def test_gate_reuses_unlock_and_draft_guard_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    import rag_pedago.imports.real_draft_unlock_gate as gate

    calls = {"unlock": 0, "draft": 0}
    original_unlock = gate.build_human_unlock_report
    original_draft = gate.build_real_draft_guard_report

    def wrapped_unlock(path: Path) -> dict:
        calls["unlock"] += 1
        return original_unlock(path)

    def wrapped_draft(items: list[dict]) -> dict:
        calls["draft"] += 1
        return original_draft(items)

    monkeypatch.setattr(gate, "build_human_unlock_report", wrapped_unlock)
    monkeypatch.setattr(gate, "build_real_draft_guard_report", wrapped_draft)

    report = gate.build_unlock_gate_report(VALID_UNLOCK, VALID_DRAFT)

    assert report["status"] == "approved_for_real_metadata_draft_preparation"
    assert calls == {"unlock": 1, "draft": 1}


def test_gate_does_not_open_source_uri_calculate_hash_or_check_source_existence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rag_pedago.imports.real_draft_unlock_gate import build_unlock_gate_report

    def fail_exists(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("source existence must not be checked")

    original_open = builtins.open

    def fail_pdf_open(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if str(path).lower().endswith(".pdf"):
            raise AssertionError("PDF must not be opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", fail_exists)
    monkeypatch.setattr(builtins, "open", fail_pdf_open)

    report = build_unlock_gate_report(VALID_UNLOCK, VALID_DRAFT)

    assert report["status"] == "approved_for_real_metadata_draft_preparation"


def test_gate_writes_no_files_creates_no_staging_and_does_not_touch_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rag_pedago.imports.real_draft_unlock_gate import build_unlock_gate_report

    marker = _ledger_marker()

    def fail_write(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("gate must not write files")

    monkeypatch.setattr(Path, "write_text", fail_write)
    monkeypatch.setattr(Path, "write_bytes", fail_write)

    report = build_unlock_gate_report(VALID_UNLOCK, VALID_DRAFT)

    assert report["status"] == "approved_for_real_metadata_draft_preparation"
    assert not (ROOT / "data/staging").exists()
    _assert_ledger_unchanged(marker)


def test_module_contains_no_forbidden_integrations() -> None:
    module_path = ROOT / "rag_pedago/imports/real_draft_unlock_gate.py"
    text = module_path.read_text(encoding="utf-8")

    forbidden = [
        "hashlib",
        "requests",
        "httpx",
        "urllib",
        "socket",
        "subprocess",
        "qdrant",
        "psycopg",
        "docker",
        "read_bytes",
        "write_bytes",
    ]
    assert not any(token in text for token in forbidden)


def test_fixtures_contain_no_real_documents_or_plaintext_secrets() -> None:
    forbidden = [
        "OPENAI" + "_API_KEY",
        "QDRANT" + "_URL",
        "POSTGRES" + "_URL",
        "BEGIN PRIVATE KEY",
        "gdrive-sa.json",
        ".env",
        ".pem",
        ".key",
    ]

    assert not list(FIXTURE_DIR.rglob("*.pdf"))
    assert not list(FIXTURE_DIR.rglob("*.docx"))
    assert not list(FIXTURE_DIR.rglob("*.pptx"))
    assert not list(FIXTURE_DIR.rglob("*.xlsx"))
    for path in FIXTURE_DIR.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert not any(marker in text for marker in forbidden), path
            assert "file://" not in text


def test_rag_local_contains_no_lot_15h_artifacts() -> None:
    if RAG_LOCAL.exists():
        assert not (RAG_LOCAL / "rag_pedago/imports/real_draft_unlock_gate.py").exists()
        assert not (RAG_LOCAL / "tests/unit/test_real_draft_unlock_gate.py").exists()
        assert not (RAG_LOCAL / "data/fixtures/pilot_math_terminale/real_draft_unlock_gate").exists()
        assert not (RAG_LOCAL / "docs/REAL_DRAFT_UNLOCK_GATE_PROTOCOL.md").exists()


def test_report_contains_required_summary_fields() -> None:
    from rag_pedago.imports.real_draft_unlock_gate import build_unlock_gate_report

    report = build_unlock_gate_report(VALID_UNLOCK, VALID_DRAFT)

    assert {
        "status",
        "issue_count",
        "item_count",
        "unlock_status",
        "draft_status",
        "max_items",
    } <= set(report)
