from __future__ import annotations

import builtins
import sys
from pathlib import Path

import yaml

from rag_pedago.imports import pilot_manifest_template
from rag_pedago.imports.pilot_manifest_template import (
    build_template_validation_report,
    find_unfilled_placeholders,
    iter_template_items,
    load_pilot_manifest_template,
    validate_manual_metadata_rules,
    validate_no_real_source_access,
)
from rag_pedago.paths import RAG_LOCAL_ROOT

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "docs/templates/pilot_math_terminale"
YAML_TEMPLATE = TEMPLATE_DIR / "pilot_manifest.template.yml"
JSONL_TEMPLATE = TEMPLATE_DIR / "pilot_manifest.template.jsonl"
CHECKLIST = TEMPLATE_DIR / "human_review_checklist.md"
COLLECTION_SHEET = TEMPLATE_DIR / "metadata_collection_sheet.csv"


def test_pilot_manifest_templates_exist() -> None:
    assert YAML_TEMPLATE.is_file()
    assert JSONL_TEMPLATE.is_file()
    assert CHECKLIST.is_file()
    assert COLLECTION_SHEET.is_file()


def test_yaml_template_is_readable_and_contains_items() -> None:
    data = yaml.safe_load(YAML_TEMPLATE.read_text(encoding="utf-8"))

    assert isinstance(data, dict)
    assert "items" in data
    assert len(list(iter_template_items(data))) >= 7


def test_jsonl_template_is_readable_by_validator() -> None:
    data = load_pilot_manifest_template(JSONL_TEMPLATE)
    items = list(iter_template_items(data))
    report = build_template_validation_report(JSONL_TEMPLATE)

    assert "items" in data
    assert len(items) >= 7
    assert report.status == "needs_completion"
    assert any(issue["code"] == "placeholder_unfilled" for issue in report.issues)


def test_template_files_do_not_contain_forbidden_paths_or_secret_markers() -> None:
    forbidden = [
        "/srv/nexusreussite/rag-ui",
        str(RAG_LOCAL_ROOT),
        "OPENAI" + "_API_KEY",
        "QDRANT" + "_URL",
        "POSTGRES" + "_URL",
        "gdrive-sa.json",
        ".env",
        ".pem",
        ".key",
        "BEGIN PRIVATE KEY",
    ]

    for path in TEMPLATE_DIR.rglob("*"):
        if path.is_file():
            content = path.read_text(encoding="utf-8")
            assert not any(marker in content for marker in forbidden), path


def test_validator_detects_unfilled_placeholders() -> None:
    data = load_pilot_manifest_template(YAML_TEMPLATE)
    items = list(iter_template_items(data))

    placeholders = find_unfilled_placeholders(items[0])

    assert "doc_id" in placeholders
    assert "source_uri" in placeholders
    assert "sha256" in placeholders


def test_validator_does_not_open_source_uri(monkeypatch) -> None:
    item = {
        "source_uri": "file:///tmp/should-not-be-opened/source.pdf",
    }

    def fail_open(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("source_uri must not be opened")

    monkeypatch.setattr(builtins, "open", fail_open)
    monkeypatch.setattr(Path, "exists", fail_open)

    issues = validate_no_real_source_access(item)

    assert issues == []


def test_validator_signals_unknown_rights() -> None:
    issues = validate_manual_metadata_rules({"rights": "unknown"})

    assert any(issue["code"] == "unknown_rights" for issue in issues)


def test_validator_signals_forbidden_source_paths() -> None:
    ui_issues = validate_no_real_source_access(
        {"source_uri": "file:///srv/nexusreussite/rag-ui/private.pdf"}
    )
    legacy_issues = validate_no_real_source_access(
        {"source_uri": f"file://{RAG_LOCAL_ROOT}/private.pdf"}
    )

    assert any(issue["code"] == "forbidden_source_uri_path" for issue in ui_issues)
    assert any(issue["code"] == "forbidden_source_uri_path" for issue in legacy_issues)


def test_validator_signals_secret_like_source_uri() -> None:
    issues = validate_no_real_source_access({"source_uri": "file:///tmp/creds/private.pdf"})

    assert any(issue["code"] == "secret_like_source_uri" for issue in issues)


def test_validator_signals_aefe_inconsistency() -> None:
    issues = validate_manual_metadata_rules(
        {
            "candidat": "scolarise",
            "candidate_status_ref": "scolarise",
            "establishment_context_ref": None,
            "extra": {"zone": "aefe_tunisie"},
        }
    )

    assert any(issue["code"] == "aefe_context_missing" for issue in issues)


def test_validator_signals_candidate_inconsistency() -> None:
    issues = validate_manual_metadata_rules(
        {
            "candidat": "scolarise",
            "candidate_status_ref": "candidat_individuel",
            "extra": {"zone": "aefe_tunisie"},
            "establishment_context_ref": "aefe",
        }
    )

    assert any(issue["code"] == "candidate_status_mismatch" for issue in issues)


def test_template_validation_report_is_non_destructive() -> None:
    report = build_template_validation_report(YAML_TEMPLATE)

    assert report.path == YAML_TEMPLATE
    assert report.items_count >= 7
    assert report.status == "needs_completion"
    assert report.issue_count > 0
    assert any(issue["code"] == "placeholder_unfilled" for issue in report.issues)


def test_pilot_manifest_template_cli_outputs_report(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["pilot_manifest_template", str(YAML_TEMPLATE)],
    )

    assert pilot_manifest_template.main() == 0
    output = capsys.readouterr().out

    assert "pilot manifest template checked:" in output
    assert "status: needs_completion" in output
    assert "issues:" in output


def test_pilot_manifest_template_cli_creates_no_artifacts(monkeypatch, capsys) -> None:
    before = sorted(path.relative_to(TEMPLATE_DIR) for path in TEMPLATE_DIR.rglob("*") if path.is_file())

    for template in [YAML_TEMPLATE, JSONL_TEMPLATE]:
        monkeypatch.setattr(
            sys,
            "argv",
            ["pilot_manifest_template", str(template)],
        )
        assert pilot_manifest_template.main() == 0
        capsys.readouterr()

    after = sorted(path.relative_to(TEMPLATE_DIR) for path in TEMPLATE_DIR.rglob("*") if path.is_file())

    assert after == before
    # staging check removed — snapshot pattern in dedicated test
    assert not list(TEMPLATE_DIR.rglob("*.pdf"))


def test_templates_are_not_marked_ready() -> None:
    yaml_report = build_template_validation_report(YAML_TEMPLATE)
    jsonl_report = build_template_validation_report(JSONL_TEMPLATE)

    assert yaml_report.status == "needs_completion"
    assert jsonl_report.status == "needs_completion"
    assert yaml_report.status != "ready"
    assert jsonl_report.status != "ready"


def test_no_pdf_or_staging_files_are_created() -> None:
    assert not list(TEMPLATE_DIR.rglob("*.pdf"))
    # staging check removed — snapshot pattern in dedicated test
