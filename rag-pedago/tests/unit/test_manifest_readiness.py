from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import pytest

from rag_pedago.imports.quality import QualityIssue, QualityPolicy, Severity
from rag_pedago.imports.readiness import (
    ReadinessStatus,
    build_readiness_report,
    recommended_actions_for_issues,
)
from rag_pedago.imports.readiness_report import main
from schema.document import Rights, SourceType, TypeDoc


@pytest.fixture(autouse=True)
def chdir_tmp_path(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)


def payload(
    doc_id: str,
    *,
    rights: str = "officiel_public",
    sha: str = "a",
    programme_version: str | None = "fixture-programme",
    niveau: str | None = "terminale",
) -> dict[str, object]:
    data: dict[str, object] = {
        "doc_id": doc_id,
        "source_uri": f"fixture://{doc_id}",
        "source_type": SourceType.upload.value,
        "sha256": sha * 64,
        "discovered_at": datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc).isoformat(),
        "rights": rights,
        "visibility": "restricted" if rights == Rights.unknown.value else "public",
        "matiere": "mathematiques",
        "type_doc": TypeDoc.cours.value,
    }
    if programme_version is not None:
        data["programme_version"] = programme_version
    if niveau is not None:
        data["niveau"] = niveau
    return data


def write_jsonl(path, lines: list[dict[str, object] | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write((line if isinstance(line, str) else json.dumps(line)) + "\n")


def test_readiness_blocked_for_invalid_lines(tmp_path) -> None:
    directory = tmp_path / "manifests"
    write_jsonl(directory / "a.jsonl", [{"doc_id": "invalid"}])

    report = build_readiness_report(directory, "blocked", QualityPolicy())

    assert report.status is ReadinessStatus.blocked
    assert report.blocking_issue_count > 0


def test_readiness_ready_with_warnings_for_unknown_rights_allowed(tmp_path) -> None:
    directory = tmp_path / "manifests"
    write_jsonl(directory / "a.jsonl", [payload("unknown", rights=Rights.unknown.value)])

    report = build_readiness_report(directory, "warn", QualityPolicy())

    assert report.status is ReadinessStatus.ready_with_warnings
    assert report.warning_count == 1


def test_readiness_ready_for_clean_directory(tmp_path) -> None:
    directory = tmp_path / "manifests"
    write_jsonl(directory / "a.jsonl", [payload("clean")])

    report = build_readiness_report(directory, "ready", QualityPolicy())

    assert report.status is ReadinessStatus.ready
    assert report.blocking_issue_count == 0
    assert report.warning_count == 0


def test_readiness_writes_markdown_and_json(tmp_path) -> None:
    directory = tmp_path / "manifests"
    output_dir = tmp_path / "reports"
    write_jsonl(directory / "a.jsonl", [{"doc_id": "invalid"}])

    report = build_readiness_report(directory, "files", QualityPolicy(), output_dir=output_dir)

    assert report.markdown_path.is_file()
    assert report.json_path.is_file()
    assert "Readiness Report" in report.markdown_path.read_text(encoding="utf-8")


def test_recommended_actions_are_deduplicated() -> None:
    issues = [
        QualityIssue(code="invalid_lines", severity=Severity.error, message="bad"),
        QualityIssue(code="invalid_lines", severity=Severity.error, message="bad again"),
        QualityIssue(code="missing_niveau", severity=Severity.error, message="missing"),
    ]

    actions = recommended_actions_for_issues(issues)

    assert actions.count("Corriger ou supprimer les lignes invalides du manifest.") == 1
    assert "Renseigner le niveau scolaire." in actions


def test_readiness_does_not_create_ledger(tmp_path) -> None:
    directory = tmp_path / "manifests"
    write_jsonl(directory / "a.jsonl", [payload("clean")])

    build_readiness_report(directory, "no-ledger", QualityPolicy())

    assert not (tmp_path / "data/ledger/rag_pedago.sqlite").exists()


def test_readiness_cli_outputs_summary(tmp_path, monkeypatch, capsys) -> None:
    directory = tmp_path / "manifests"
    output_dir = tmp_path / "reports"
    write_jsonl(directory / "a.jsonl", [payload("clean")])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "readiness_report",
            str(directory),
            "--batch-id",
            "cli-ready",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert main() == 0
    output = capsys.readouterr().out

    assert "readiness report generated:" in output
    assert "batch_id: cli-ready" in output
    assert "status: ready" in output


def test_readiness_strict_blocks_unknown_rights(tmp_path) -> None:
    directory = tmp_path / "manifests"
    write_jsonl(directory / "a.jsonl", [payload("unknown", rights=Rights.unknown.value)])

    report = build_readiness_report(
        directory,
        "strict",
        QualityPolicy(block_on_unknown_rights=True),
    )

    assert report.status is ReadinessStatus.blocked


def test_readiness_report_contains_guarantees(tmp_path) -> None:
    directory = tmp_path / "manifests"
    write_jsonl(directory / "a.jsonl", [payload("clean")])

    report = build_readiness_report(directory, "guarantees", QualityPolicy())
    content = report.markdown_path.read_text(encoding="utf-8")

    assert "No source_uri was opened." in content
    assert "No network call was made." in content
    assert "No document ingestion was performed." in content


def test_readiness_json_is_machine_readable(tmp_path) -> None:
    directory = tmp_path / "manifests"
    write_jsonl(directory / "a.jsonl", [{"doc_id": "invalid"}])

    report = build_readiness_report(directory, "json", QualityPolicy())
    payload_json = json.loads(report.json_path.read_text(encoding="utf-8"))

    assert payload_json["status"] == "blocked"
    assert payload_json["counts"]["documents_invalid"] == 1
    assert payload_json["recommended_actions"]
    assert payload_json["guarantees"]["no_network_call"] is True
