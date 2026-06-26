from __future__ import annotations

from pathlib import Path

import rag_pedago.project_doctor as project_doctor
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


def test_project_doctor_tolerates_git_tracked_file_deleted_between_scan_and_read(
    tmp_path,
    monkeypatch,
) -> None:
    for relative in project_doctor.REQUIRED_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(
        "\n".join(project_doctor.REQUIRED_GITIGNORE_PATTERNS) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(project_doctor, "_tracked_files", lambda root: [Path("vanishing.py")])

    result = run_project_doctor(tmp_path)

    assert result.ok is True
    assert not any("vanishing.py" in error for error in result.errors)
