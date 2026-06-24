from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import pytest

from rag_pedago.imports.gate import GateStatus, build_gate_report
from rag_pedago.imports.gate_report import main
from rag_pedago.imports.quality import QualityPolicy
from schema.document import Candidat, Niveau, Rights, SourceType, TypeDoc


@pytest.fixture(autouse=True)
def chdir_tmp_path(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)


def payload(
    doc_id: str,
    *,
    notions: list[str] | None = None,
    rights: str = Rights.officiel_public.value,
    sha: str = "a",
    programme_version: str | None = "fixture-programme",
    niveau: str | None = Niveau.terminale.value,
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
        "candidat": Candidat.scolarise.value,
        "notions": notions or [],
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


def write_taxonomy(path, notions: list[str]) -> None:
    notions_yaml = "\n".join(f"      - id: {notion}\n        label: {notion}" for notion in notions)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""id: maths_fixture
matiere: mathematiques
niveau: terminale
voie: generale
statut_enseignement: specialite
programme_version: fixture
themes:
  - id: main
    label: Main
    notions:
{notions_yaml}
competences:
  - raisonner
""",
        encoding="utf-8",
    )


def test_gate_blocked_when_readiness_blocked_even_if_coverage_ok(tmp_path) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    write_jsonl(directory / "a.jsonl", [payload("doc-1", notions=["suites"]), {"doc_id": "bad"}])
    write_taxonomy(taxonomy, ["suites"])

    report = build_gate_report(directory, "blocked-readiness", [taxonomy], QualityPolicy())

    assert report.status is GateStatus.blocked
    assert report.readiness_status == "blocked"
    assert report.coverage_status == "coverage_ok"


def test_gate_blocked_when_coverage_insufficient(tmp_path) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    write_jsonl(directory / "a.jsonl", [payload("doc-1", notions=[])])
    write_taxonomy(taxonomy, ["suites"])

    report = build_gate_report(directory, "blocked-coverage", [taxonomy], QualityPolicy())

    assert report.status is GateStatus.blocked
    assert report.coverage_status == "coverage_insufficient"


def test_gate_review_required_when_coverage_partial(tmp_path) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    write_jsonl(directory / "a.jsonl", [payload("doc-1", notions=["unknown"])])
    write_taxonomy(taxonomy, ["suites"])

    report = build_gate_report(directory, "partial-coverage", [taxonomy], QualityPolicy())

    assert report.status is GateStatus.review_required
    assert report.coverage_status == "coverage_partial"
    assert report.notions_unknown == ["unknown"]


def test_gate_review_required_when_readiness_has_warnings(tmp_path) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    write_jsonl(
        directory / "a.jsonl",
        [payload("doc-1", notions=["suites"], rights=Rights.unknown.value)],
    )
    write_taxonomy(taxonomy, ["suites"])

    report = build_gate_report(directory, "warning-readiness", [taxonomy], QualityPolicy())

    assert report.status is GateStatus.review_required
    assert report.readiness_status == "ready_with_warnings"
    assert report.warning_count == 1


def test_gate_ready_when_readiness_and_coverage_ok(tmp_path) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    write_jsonl(directory / "a.jsonl", [payload("doc-1", notions=["suites"])])
    write_taxonomy(taxonomy, ["suites"])

    report = build_gate_report(directory, "ready", [taxonomy], QualityPolicy())

    assert report.status is GateStatus.ready_for_controlled_import
    assert "Ready for controlled manifest import" in report.reasons


def test_gate_writes_markdown_and_json(tmp_path) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    output_dir = tmp_path / "reports"
    write_jsonl(directory / "a.jsonl", [payload("doc-1", notions=["unknown"])])
    write_taxonomy(taxonomy, ["suites"])

    report = build_gate_report(directory, "files", [taxonomy], QualityPolicy(), output_dir=output_dir)

    assert report.markdown_path.is_file()
    assert report.json_path.is_file()
    data = json.loads(report.json_path.read_text(encoding="utf-8"))
    assert data["status"] == "review_required"
    assert data["reasons"]
    assert data["guarantees"]["no_source_uri_opened"] is True


def test_gate_does_not_create_ledger(tmp_path) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    write_jsonl(directory / "a.jsonl", [payload("doc-1", notions=["suites"])])
    write_taxonomy(taxonomy, ["suites"])

    build_gate_report(directory, "no-ledger", [taxonomy], QualityPolicy())

    assert not (tmp_path / "data/ledger/rag_pedago.sqlite").exists()


def test_gate_cli_outputs_summary(tmp_path, monkeypatch, capsys) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    output_dir = tmp_path / "reports"
    write_jsonl(directory / "a.jsonl", [payload("doc-1", notions=["suites"])])
    write_taxonomy(taxonomy, ["suites"])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gate_report",
            str(directory),
            "--batch-id",
            "cli",
            "--taxonomy",
            str(taxonomy),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert main() == 0
    output = capsys.readouterr().out

    assert "gate report generated:" in output
    assert "batch_id: cli" in output
    assert "status: ready_for_controlled_import" in output


def test_gate_recommended_actions_are_deduplicated(tmp_path) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    write_jsonl(directory / "a.jsonl", [payload("doc-1", notions=["unknown"])])
    write_taxonomy(taxonomy, ["suites"])

    report = build_gate_report(
        directory,
        "dedupe",
        [taxonomy],
        QualityPolicy(),
        priority_notions=["suites", "suites"],
    )

    assert len(report.recommended_actions) == len(set(report.recommended_actions))


def test_gate_report_contains_guarantees(tmp_path) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    write_jsonl(directory / "a.jsonl", [payload("doc-1", notions=["suites"])])
    write_taxonomy(taxonomy, ["suites"])

    report = build_gate_report(directory, "guarantees", [taxonomy], QualityPolicy())
    content = report.markdown_path.read_text(encoding="utf-8")

    assert "No source_uri was opened." in content
    assert "No network call was made." in content
    assert "No document ingestion was performed." in content
