from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from rag_pedago.paths import RAG_LOCAL_ROOT, REPO_ROOT

ROOT = REPO_ROOT
RAG_LOCAL = RAG_LOCAL_ROOT
PROTOCOL = ROOT / "docs/HUMAN_UNLOCK_PROTOCOL.md"
TEMPLATE = ROOT / "docs/templates/human_unlock/human_unlock.template.json"
FIXTURE_DIR = ROOT / "data/fixtures/pilot_math_terminale/human_unlock"
VALID_UNLOCK = FIXTURE_DIR / "human_unlock.valid.json"
INVALID_FIXTURES = [
    FIXTURE_DIR / "human_unlock.invalid_placeholder.json",
    FIXTURE_DIR / "human_unlock.invalid_rejected.json",
    FIXTURE_DIR / "human_unlock.invalid_too_many_items.json",
    FIXTURE_DIR / "human_unlock.invalid_allows_parsing.json",
    FIXTURE_DIR / "human_unlock.invalid_wrong_zone.json",
    FIXTURE_DIR / "human_unlock.invalid_secret_marker.json",
]
PERMANENT_LEDGER = ROOT / "data/ledger/rag_pedago.sqlite"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _issue_codes(issues: list[dict]) -> set[str]:
    return {str(issue["code"]) for issue in issues}


def _ledger_marker() -> tuple[bool, int | None]:
    if not PERMANENT_LEDGER.exists():
        return False, None
    return True, PERMANENT_LEDGER.stat().st_mtime_ns


def _assert_ledger_unchanged(marker: tuple[bool, int | None]) -> None:
    existed, mtime = marker
    assert PERMANENT_LEDGER.exists() is existed
    if existed:
        assert PERMANENT_LEDGER.stat().st_mtime_ns == mtime


def test_protocol_template_and_valid_fixture_exist() -> None:
    assert PROTOCOL.is_file()
    assert TEMPLATE.is_file()
    assert VALID_UNLOCK.is_file()


def test_valid_fixture_is_approved_for_metadata_only_next_step() -> None:
    from rag_pedago.imports.human_unlock_guard import build_human_unlock_report

    report = build_human_unlock_report(VALID_UNLOCK)

    assert report["status"] == "approved_for_metadata_only_next_step"
    assert report["issue_count"] == 0
    assert report["decision"] == "approved"
    assert report["scope"] == "real_minimal_metadata_only_draft"
    assert report["max_items"] == 2
    assert report["reviewer_present"] is True
    assert report["reviewed_at_present"] is True


def test_cli_accepts_valid_fixture_and_rejects_invalid_fixtures(capsys: pytest.CaptureFixture[str]) -> None:
    from rag_pedago.imports.human_unlock_guard import main

    assert main([str(VALID_UNLOCK)]) == 0
    assert "status: approved_for_metadata_only_next_step" in capsys.readouterr().out

    for fixture in INVALID_FIXTURES:
        assert main([str(fixture)]) == 1
        assert "status: blocked" in capsys.readouterr().out


def test_validator_refuses_placeholders_rejection_limits_and_parsing() -> None:
    from rag_pedago.imports.human_unlock_guard import validate_human_unlock

    valid = _load_json(VALID_UNLOCK)

    assert "placeholder_unfilled" in _issue_codes(
        validate_human_unlock(valid | {"reviewer_name": "A_REMPLIR"})
    )
    assert "decision_not_approved" in _issue_codes(
        validate_human_unlock(valid | {"decision": "rejected"})
    )
    assert "too_many_items" in _issue_codes(validate_human_unlock(valid | {"max_items": 3}))
    assert "unsafe_permission_enabled" in _issue_codes(
        validate_human_unlock(valid | {"no_parsing_allowed": False})
    )


def test_validator_refuses_wrong_zone_secret_and_unsafe_permissions() -> None:
    from rag_pedago.imports.human_unlock_guard import validate_human_unlock

    valid = _load_json(VALID_UNLOCK)

    assert "wrong_allowed_context" in _issue_codes(
        validate_human_unlock(valid | {"allowed_zone": "hors_aefe"})
    )
    assert "forbidden_marker" in _issue_codes(
        validate_human_unlock(valid | {"human_notes": "contains secret marker"})
    )
    for field in [
        "no_qdrant_allowed",
        "no_scraping_allowed",
        "no_embedding_allowed",
        "no_permanent_ledger_write_allowed",
    ]:
        assert "unsafe_permission_enabled" in _issue_codes(
            validate_human_unlock(valid | {field: False})
        )


def test_validator_refuses_incoherent_pedagogical_context() -> None:
    from rag_pedago.imports.human_unlock_guard import validate_human_unlock

    valid = _load_json(VALID_UNLOCK)

    for field, value in [
        ("allowed_candidate_status", "candidat_individuel"),
        ("allowed_subject", "nsi"),
        ("allowed_level", "premiere"),
        ("allowed_track", "technologique"),
        ("allowed_teaching", "option"),
    ]:
        assert "wrong_allowed_context" in _issue_codes(
            validate_human_unlock(valid | {field: value})
        )


def test_validator_does_not_write_files_or_create_staging_or_touch_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rag_pedago.imports.human_unlock_guard import build_human_unlock_report

    marker = _ledger_marker()

    def fail_write(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("human unlock guard must not write files")

    monkeypatch.setattr(Path, "write_text", fail_write)
    monkeypatch.setattr(Path, "write_bytes", fail_write)

    report = build_human_unlock_report(VALID_UNLOCK)

    assert report["status"] == "approved_for_metadata_only_next_step"
    assert not (ROOT / "data/staging").exists()
    _assert_ledger_unchanged(marker)


def test_validator_does_not_read_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    from rag_pedago.imports.human_unlock_guard import build_human_unlock_report

    original_open = builtins.open

    def fail_pdf_open(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if str(path).lower().endswith(".pdf"):
            raise AssertionError("PDF must not be opened")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fail_pdf_open)

    assert build_human_unlock_report(VALID_UNLOCK)["issue_count"] == 0


def test_module_contains_no_forbidden_integrations() -> None:
    module_path = ROOT / "rag_pedago/imports/human_unlock_guard.py"
    text = module_path.read_text(encoding="utf-8")

    forbidden = [
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


def test_fixtures_and_template_contain_no_real_documents() -> None:
    for directory in [FIXTURE_DIR, TEMPLATE.parent]:
        assert not list(directory.rglob("*.pdf"))
        assert not list(directory.rglob("*.docx"))
        assert not list(directory.rglob("*.pptx"))
        assert not list(directory.rglob("*.xlsx"))


def test_rag_local_contains_no_lot_15g_artifacts() -> None:
    if RAG_LOCAL.exists():
        assert not (RAG_LOCAL / "rag_pedago/imports/human_unlock_guard.py").exists()
        assert not (RAG_LOCAL / "tests/unit/test_human_unlock_guard.py").exists()
        assert not (RAG_LOCAL / "data/fixtures/pilot_math_terminale/human_unlock").exists()
        assert not (RAG_LOCAL / "docs/HUMAN_UNLOCK_PROTOCOL.md").exists()


def test_report_contains_required_summary_fields() -> None:
    from rag_pedago.imports.human_unlock_guard import build_human_unlock_report

    report = build_human_unlock_report(VALID_UNLOCK)

    assert {"status", "issue_count", "decision", "scope", "max_items"} <= set(report)


def test_template_is_blocked_because_of_placeholders() -> None:
    from rag_pedago.imports.human_unlock_guard import build_human_unlock_report

    report = build_human_unlock_report(TEMPLATE)

    assert report["status"] == "blocked"
    assert any(issue["code"] == "placeholder_unfilled" for issue in report["issues"])
