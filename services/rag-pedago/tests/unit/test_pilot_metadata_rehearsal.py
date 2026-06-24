from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from rag_pedago.paths import RAG_LOCAL_ROOT, REPO_ROOT
from schema.document import DocumentMeta

ROOT = REPO_ROOT
RAG_LOCAL = RAG_LOCAL_ROOT
VALID_DRAFT = (
    ROOT
    / "data/fixtures/pilot_math_terminale/filled_drafts/pilot_manifest.filled.valid.yml"
)
UNKNOWN_RIGHTS_DRAFT = (
    ROOT
    / "data/fixtures/pilot_math_terminale/filled_drafts/"
    "pilot_manifest.filled.invalid_unknown_rights.yml"
)
FORBIDDEN_SOURCE_DRAFT = (
    ROOT
    / "data/fixtures/pilot_math_terminale/filled_drafts/"
    "pilot_manifest.filled.invalid_forbidden_source.yml"
)
PERMANENT_LEDGER = ROOT / "data/ledger/rag_pedago.sqlite"


def _permanent_ledger_marker() -> tuple[bool, int | None]:
    if not PERMANENT_LEDGER.exists():
        return False, None
    return True, PERMANENT_LEDGER.stat().st_mtime_ns


def _assert_permanent_ledger_unchanged(marker: tuple[bool, int | None]) -> None:
    existed, mtime = marker
    assert PERMANENT_LEDGER.exists() is existed
    if existed:
        assert PERMANENT_LEDGER.stat().st_mtime_ns == mtime


def _assert_no_real_documents(path: Path) -> None:
    real_document_suffixes = {".pdf", ".docx", ".pptx", ".xlsx"}
    assert not [
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file() and candidate.suffix.lower() in real_document_suffixes
    ]


def test_filled_synthetic_draft_exists() -> None:
    assert VALID_DRAFT.exists()


def test_rehearsal_runs_full_metadata_only_chain(tmp_path: Path) -> None:
    from rag_pedago.imports.pilot_metadata_rehearsal import run_metadata_rehearsal

    marker = _permanent_ledger_marker()
    summary = run_metadata_rehearsal(
        VALID_DRAFT,
        tmp_path / "workspace",
        batch_id="pilot-rehearsal-test",
    )

    assert summary.compile_status == "ready"
    assert summary.dry_run_status == "dry_run_success"
    assert summary.readiness_status == "ready"
    assert summary.coverage_status == "coverage_ok"
    assert summary.gate_status == "ready_for_controlled_import"
    assert summary.review_status == "ready_for_review"
    assert summary.decision_status == "approved"
    assert summary.controlled_import_status == "imported"
    assert summary.ledger_audit_status == "recorded"
    assert summary.ledger_db_path.is_relative_to(tmp_path)
    assert summary.review_decision_path is not None
    assert "synthetic=true" in summary.review_notes
    _assert_permanent_ledger_unchanged(marker)
    assert not (ROOT / "data/staging").exists()
    _assert_no_real_documents(tmp_path)

    with sqlite3.connect(summary.ledger_db_path) as conn:
        attempt_count = conn.execute("SELECT COUNT(*) FROM controlled_import_attempts").fetchone()[0]
        verification_count = conn.execute(
            "SELECT COUNT(*) FROM controlled_import_verifications"
        ).fetchone()[0]
        document_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    assert attempt_count == 1
    assert verification_count >= 10
    assert document_count >= 5


def test_rehearsal_steps_compile_and_validate_jsonl_in_tmp_path(tmp_path: Path) -> None:
    from rag_pedago.imports.pilot_metadata_rehearsal import (
        build_rehearsal_workspace,
        compile_draft_to_workspace_manifest,
    )

    workspace = build_rehearsal_workspace(tmp_path / "workspace")
    manifest_path = compile_draft_to_workspace_manifest(VALID_DRAFT, workspace)

    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) >= 5
    assert all(DocumentMeta.model_validate(row) for row in rows)
    assert all(str(row["source_uri"]).startswith("synthetic://") for row in rows)
    assert manifest_path.is_relative_to(tmp_path)


def test_rehearsal_refuses_forbidden_and_secret_output_dirs(tmp_path: Path) -> None:
    from rag_pedago.imports.pilot_metadata_rehearsal import build_rehearsal_workspace

    with pytest.raises(ValueError, match="forbidden output_dir"):
        build_rehearsal_workspace(Path("/srv/nexusreussite/rag-ui/rehearsal"))
    with pytest.raises(ValueError, match="forbidden output_dir"):
        build_rehearsal_workspace(RAG_LOCAL_ROOT / "rehearsal")
    with pytest.raises(ValueError, match="sensitive output_dir"):
        build_rehearsal_workspace(tmp_path / "creds-rehearsal")


def test_rehearsal_rejects_invalid_drafts(tmp_path: Path) -> None:
    from rag_pedago.imports.pilot_metadata_rehearsal import run_metadata_rehearsal

    with pytest.raises(ValueError, match="filled draft is not ready"):
        run_metadata_rehearsal(UNKNOWN_RIGHTS_DRAFT, tmp_path / "unknown-rights")
    with pytest.raises(ValueError, match="filled draft is not ready"):
        run_metadata_rehearsal(FORBIDDEN_SOURCE_DRAFT, tmp_path / "forbidden-source")


def test_rehearsal_cli_tmp_mode_outputs_summary(capsys: pytest.CaptureFixture[str]) -> None:
    from rag_pedago.imports.pilot_metadata_rehearsal import main

    status = main([str(VALID_DRAFT), "--tmp", "--batch-id", "pilot-rehearsal-cli"])

    captured = capsys.readouterr()
    assert status == 0
    assert "rehearsal summary:" in captured.out
    assert "gate_status: ready_for_controlled_import" in captured.out
    assert "controlled_import_status: imported" in captured.out


def test_rehearsal_fixture_files_contain_no_secrets() -> None:
    fixture_dir = ROOT / "data/fixtures/pilot_math_terminale"
    join = "".join
    forbidden_markers = [
        join(("OPENAI", "_API_KEY")),
        join(("QDRANT", "_URL")),
        join(("POSTGRES", "_URL")),
        "gdrive-sa.json",
        "BEGIN PRIVATE KEY",
        ".pem",
        ".key",
    ]
    for path in fixture_dir.rglob("*"):
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        assert not any(marker in content for marker in forbidden_markers), path


def test_rehearsal_does_not_create_paths_in_forbidden_repositories() -> None:
    if RAG_LOCAL.exists():
        assert not (RAG_LOCAL / "rag_pedago/imports/pilot_metadata_rehearsal.py").exists()
        assert not (RAG_LOCAL / "tests/unit/test_pilot_metadata_rehearsal.py").exists()
        assert not (RAG_LOCAL / "data/fixtures/pilot_math_terminale/rehearsal").exists()
    assert not Path("/srv/nexusreussite/rag-ui/rag_pedago/imports/pilot_metadata_rehearsal.py").exists()
