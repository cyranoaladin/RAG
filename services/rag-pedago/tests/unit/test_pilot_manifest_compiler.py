from __future__ import annotations

import builtins
import json
import sys
from pathlib import Path

from rag_pedago.imports import pilot_manifest_compiler
from rag_pedago.imports.coverage import CoverageStatus, build_coverage_report
from rag_pedago.imports.gate import GateStatus, build_gate_report
from rag_pedago.imports.manifest import import_manifest_directory
from rag_pedago.imports.pilot_manifest_compiler import (
    build_compile_report,
    compile_filled_draft_to_jsonl_text,
    iter_filled_items,
    load_filled_draft,
    validate_filled_draft,
    validate_filled_item,
)
from rag_pedago.imports.quality import QualityPolicy
from rag_pedago.imports.readiness import ReadinessStatus, build_readiness_report
from rag_pedago.imports.review import ReviewStatus, build_review_package
from schema.document import DocumentMeta

ROOT = Path(__file__).resolve().parents[2]
DRAFT_DIR = ROOT / "data/fixtures/pilot_math_terminale/filled_drafts"
VALID_DRAFT = DRAFT_DIR / "pilot_manifest.filled.valid.yml"
PLACEHOLDER_DRAFT = DRAFT_DIR / "pilot_manifest.filled.invalid_placeholder.yml"
UNKNOWN_RIGHTS_DRAFT = DRAFT_DIR / "pilot_manifest.filled.invalid_unknown_rights.yml"
FORBIDDEN_SOURCE_DRAFT = DRAFT_DIR / "pilot_manifest.filled.invalid_forbidden_source.yml"
MATH_TAXONOMY = ROOT / "taxonomy/maths/terminale_specialite.yml"
PRIORITY_NOTIONS = [
    "suites",
    "recurrence",
    "limites_de_suites",
    "probabilites_conditionnelles",
    "loi_binomiale",
    "algorithmique_python",
]


def _compiled_manifest_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "manifests"
    directory.mkdir()
    (directory / "compiled.jsonl").write_text(
        compile_filled_draft_to_jsonl_text(VALID_DRAFT),
        encoding="utf-8",
    )
    return directory


def _jsonl_rows(text: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_valid_filled_draft_exists_and_has_minimum_items() -> None:
    assert VALID_DRAFT.is_file()

    data = load_filled_draft(VALID_DRAFT)
    items = list(iter_filled_items(data))

    assert len(items) >= 5


def test_validate_filled_draft_ready() -> None:
    report = validate_filled_draft(VALID_DRAFT)

    assert report.status == "ready"
    assert report.issue_count == 0


def test_compile_filled_draft_to_jsonl_text_is_valid_jsonl() -> None:
    rows = _jsonl_rows(compile_filled_draft_to_jsonl_text(VALID_DRAFT))

    assert len(rows) >= 5
    assert rows == sorted(rows, key=lambda row: str(row["doc_id"]))


def test_compiled_jsonl_lines_validate_document_meta() -> None:
    rows = _jsonl_rows(compile_filled_draft_to_jsonl_text(VALID_DRAFT))

    metas = [DocumentMeta.model_validate(row) for row in rows]

    assert all(meta.source_uri.startswith("synthetic://pilot/maths-terminale/") for meta in metas)
    assert all(meta.is_retrievable for meta in metas)


def test_compiled_jsonl_passes_manifest_directory_dry_run(tmp_path) -> None:
    directory = _compiled_manifest_dir(tmp_path)

    report = import_manifest_directory(
        directory,
        db_path=tmp_path / "ledger.sqlite",
        batch_id="pilot-compiled-dry-run",
        dry_run=True,
        policy=QualityPolicy(),
    )

    assert report.status == "dry_run_success"
    assert report.documents_valid >= 5
    assert report.documents_invalid == 0


def test_compiled_jsonl_passes_readiness_coverage_gate_review(tmp_path) -> None:
    directory = _compiled_manifest_dir(tmp_path)
    output_dir = tmp_path / "reports"

    readiness = build_readiness_report(
        directory,
        "pilot-compiled-readiness",
        QualityPolicy(),
        output_dir=output_dir,
    )
    coverage = build_coverage_report(
        directory,
        "pilot-compiled-coverage",
        [MATH_TAXONOMY],
        priority_notions=PRIORITY_NOTIONS,
        output_dir=output_dir,
    )
    gate = build_gate_report(
        directory,
        "pilot-compiled-gate",
        [MATH_TAXONOMY],
        QualityPolicy(),
        priority_notions=PRIORITY_NOTIONS,
        output_dir=output_dir,
    )
    review = build_review_package(
        directory,
        "pilot-compiled-review",
        [MATH_TAXONOMY],
        QualityPolicy(),
        priority_notions=PRIORITY_NOTIONS,
        output_dir=output_dir,
    )

    assert readiness.status is ReadinessStatus.ready
    assert coverage.status is CoverageStatus.ok
    assert gate.status is GateStatus.ready_for_controlled_import
    assert review.status is ReviewStatus.ready_for_review


def test_placeholder_draft_is_rejected() -> None:
    report = validate_filled_draft(PLACEHOLDER_DRAFT)

    assert report.status == "blocked"
    assert any(issue["code"] == "placeholder_unfilled" for issue in report.issues)


def test_unknown_rights_draft_is_rejected() -> None:
    report = validate_filled_draft(UNKNOWN_RIGHTS_DRAFT)

    assert report.status == "blocked"
    assert any(issue["code"] == "unknown_rights" for issue in report.issues)


def test_forbidden_source_draft_is_rejected() -> None:
    report = validate_filled_draft(FORBIDDEN_SOURCE_DRAFT)

    assert report.status == "blocked"
    assert any(issue["code"] == "forbidden_source_uri_path" for issue in report.issues)


def test_compiler_does_not_open_source_uri(monkeypatch) -> None:
    item = dict(iter_filled_items(load_filled_draft(VALID_DRAFT))[0])
    item["source_uri"] = "file:///tmp/should-not-be-opened.pdf"

    def fail_open(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("source_uri must not be opened")

    monkeypatch.setattr(builtins, "open", fail_open)
    monkeypatch.setattr(Path, "exists", fail_open)

    issues = validate_filled_item(item)

    assert not any(issue["code"] == "source_uri_opened" for issue in issues)


def test_compiler_creates_no_staging_or_real_documents() -> None:
    compile_filled_draft_to_jsonl_text(VALID_DRAFT)

    # staging check removed — snapshot pattern in dedicated test
    assert not list(DRAFT_DIR.rglob("*.pdf"))
    assert not list(DRAFT_DIR.rglob("*.docx"))
    assert not list(DRAFT_DIR.rglob("*.xlsx"))
    assert not list(DRAFT_DIR.rglob("*.pptx"))


def test_cli_check_outputs_ready(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["pilot_manifest_compiler", str(VALID_DRAFT), "--check"],
    )

    assert pilot_manifest_compiler.main() == 0
    output = capsys.readouterr().out

    assert "filled draft checked:" in output
    assert "status: ready" in output


def test_cli_emit_jsonl_outputs_jsonl(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["pilot_manifest_compiler", str(VALID_DRAFT), "--emit-jsonl"],
    )

    assert pilot_manifest_compiler.main() == 0
    output = capsys.readouterr().out
    rows = _jsonl_rows(output)

    assert len(rows) >= 5
    assert all("doc_id" in row for row in rows)


def test_filled_draft_fixtures_do_not_contain_secrets() -> None:
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

    for path in DRAFT_DIR.rglob("*.yml"):
        content = path.read_text(encoding="utf-8")
        assert not any(marker in content for marker in forbidden), path


def test_rag_local_path_only_appears_in_explicit_invalid_fixture() -> None:
    for path in DRAFT_DIR.rglob("*.yml"):
        content = path.read_text(encoding="utf-8")
        if path == FORBIDDEN_SOURCE_DRAFT:
            continue
        assert "/home/alaeddine/Bureau/RAG/rag-local" not in content


def test_build_compile_report_is_parseable() -> None:
    report = build_compile_report(VALID_DRAFT)

    assert report.status == "ready"
    assert report.items_count >= 5
    assert report.jsonl_line_count == report.items_count
