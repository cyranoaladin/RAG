from __future__ import annotations

from pathlib import Path

from rag_pedago.project_doctor import run_project_doctor

ROOT = Path(__file__).resolve().parents[2]


def test_project_doctor_returns_ok_on_current_repository() -> None:
    result = run_project_doctor(ROOT)

    assert result.ok is True
    assert result.errors == []


def test_project_doctor_detects_missing_required_file(tmp_path) -> None:
    (tmp_path / ".gitignore").write_text("data/ledger/**\n", encoding="utf-8")

    result = run_project_doctor(tmp_path)

    assert result.ok is False
    assert any("missing required file: README.md" in error for error in result.errors)
