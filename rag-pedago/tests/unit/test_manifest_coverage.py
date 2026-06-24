from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import pytest

from rag_pedago.imports.coverage import CoverageStatus, build_coverage_report
from rag_pedago.imports.coverage_report import main
from schema.document import Candidat, Niveau, SourceType, TypeDoc


@pytest.fixture(autouse=True)
def chdir_tmp_path(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)


def payload(
    doc_id: str,
    *,
    matiere: str = "mathematiques",
    niveau: str = Niveau.terminale.value,
    type_doc: str = TypeDoc.cours.value,
    candidat: str = Candidat.scolarise.value,
    notions: list[str] | None = None,
    sha: str = "a",
    source_uri: str | None = None,
) -> dict[str, object]:
    return {
        "doc_id": doc_id,
        "source_uri": source_uri or f"fixture://{doc_id}",
        "source_type": SourceType.upload.value,
        "sha256": sha * 64,
        "discovered_at": datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc).isoformat(),
        "rights": "officiel_public",
        "visibility": "public",
        "niveau": niveau,
        "matiere": matiere,
        "type_doc": type_doc,
        "candidat": candidat,
        "programme_version": "fixture-programme",
        "notions": notions or [],
    }


def write_jsonl(path, lines: list[dict[str, object] | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write((line if isinstance(line, str) else json.dumps(line)) + "\n")


def write_taxonomy(path, *, taxonomy_id: str, matiere: str, notions: list[str]) -> None:
    notions_yaml = "\n".join(f"      - id: {notion}\n        label: {notion}" for notion in notions)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""id: {taxonomy_id}
matiere: {matiere}
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


def test_coverage_ok_for_known_notions(tmp_path) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    write_jsonl(directory / "a.jsonl", [payload("doc-1", notions=["suites", "recurrence"])])
    write_taxonomy(taxonomy, taxonomy_id="maths_fixture", matiere="mathematiques", notions=["suites", "recurrence"])

    report = build_coverage_report(
        directory,
        "ok",
        [taxonomy],
        priority_notions=["suites", "recurrence"],
    )

    assert report.status is CoverageStatus.ok
    assert report.notions_unknown == []


def test_coverage_partial_for_unknown_notions(tmp_path) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    write_jsonl(directory / "a.jsonl", [payload("doc-1", notions=["notion_inconnue"])])
    write_taxonomy(taxonomy, taxonomy_id="maths_fixture", matiere="mathematiques", notions=["suites"])

    report = build_coverage_report(directory, "unknown", [taxonomy])

    assert report.status is CoverageStatus.partial
    assert report.notions_unknown == ["notion_inconnue"]


def test_coverage_partial_for_missing_priority_notions(tmp_path) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    write_jsonl(directory / "a.jsonl", [payload("doc-1", notions=["suites"])])
    write_taxonomy(taxonomy, taxonomy_id="maths_fixture", matiere="mathematiques", notions=["suites", "recurrence"])

    report = build_coverage_report(directory, "missing-priority", [taxonomy], priority_notions=["recurrence"])

    assert report.status is CoverageStatus.partial
    assert report.missing_priority_notions == ["recurrence"]


def test_coverage_insufficient_without_valid_documents(tmp_path) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    write_jsonl(directory / "a.jsonl", [{"doc_id": "invalid"}])
    write_taxonomy(taxonomy, taxonomy_id="maths_fixture", matiere="mathematiques", notions=["suites"])

    report = build_coverage_report(directory, "insufficient", [taxonomy])

    assert report.status is CoverageStatus.insufficient
    assert report.documents_valid == 0


def test_coverage_counts_by_matiere_niveau_type_doc(tmp_path) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    write_jsonl(
        directory / "a.jsonl",
        [
            payload("maths", notions=["suites"], type_doc=TypeDoc.cours.value),
            payload("nsi", matiere="nsi", notions=["sql"], type_doc=TypeDoc.exercice.value, sha="b"),
        ],
    )
    write_taxonomy(taxonomy, taxonomy_id="fixture", matiere="mathematiques", notions=["suites", "sql"])

    report = build_coverage_report(directory, "counts", [taxonomy])

    assert report.by_matiere == {"mathematiques": 1, "nsi": 1}
    assert report.by_niveau == {"terminale": 2}
    assert report.by_type_doc == {"cours": 1, "exercice": 1}
    assert report.by_candidat == {"scolarise": 2}


def test_coverage_writes_markdown_and_json(tmp_path) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    output_dir = tmp_path / "reports"
    write_jsonl(directory / "a.jsonl", [payload("doc-1", notions=["unknown"])])
    write_taxonomy(taxonomy, taxonomy_id="maths_fixture", matiere="mathematiques", notions=["suites"])

    report = build_coverage_report(directory, "files", [taxonomy], output_dir=output_dir)

    assert report.markdown_path.is_file()
    assert report.json_path.is_file()
    data = json.loads(report.json_path.read_text(encoding="utf-8"))
    assert data["status"] == "coverage_partial"
    assert data["notions_unknown"] == ["unknown"]


def test_coverage_does_not_create_ledger(tmp_path) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    write_jsonl(
        directory / "a.jsonl",
        [
            payload(
                "doc-1",
                notions=["suites"],
                source_uri="file:///tmp/should-not-be-read/secret.pdf",
            )
        ],
    )
    write_taxonomy(taxonomy, taxonomy_id="maths_fixture", matiere="mathematiques", notions=["suites"])

    build_coverage_report(directory, "no-ledger", [taxonomy])

    assert not (tmp_path / "data/ledger/rag_pedago.sqlite").exists()


def test_coverage_cli_outputs_summary(tmp_path, monkeypatch, capsys) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    output_dir = tmp_path / "reports"
    write_jsonl(directory / "a.jsonl", [payload("doc-1", notions=["suites"])])
    write_taxonomy(taxonomy, taxonomy_id="maths_fixture", matiere="mathematiques", notions=["suites"])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "coverage_report",
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

    assert "coverage report generated:" in output
    assert "batch_id: cli" in output
    assert "status: coverage_ok" in output


def test_coverage_uses_multiple_taxonomies(tmp_path) -> None:
    directory = tmp_path / "manifests"
    maths_taxonomy = tmp_path / "maths.yml"
    nsi_taxonomy = tmp_path / "nsi.yml"
    write_jsonl(
        directory / "a.jsonl",
        [
            payload("maths", notions=["suites"]),
            payload("nsi", matiere="nsi", notions=["sql"], sha="b"),
        ],
    )
    write_taxonomy(maths_taxonomy, taxonomy_id="maths_fixture", matiere="mathematiques", notions=["suites"])
    write_taxonomy(nsi_taxonomy, taxonomy_id="nsi_fixture", matiere="nsi", notions=["sql"])

    report = build_coverage_report(directory, "multi", [maths_taxonomy, nsi_taxonomy])

    assert report.taxonomy_ids_used == ["maths_fixture", "nsi_fixture"]
    assert report.notions_known == ["sql", "suites"]


def test_coverage_report_contains_guarantees(tmp_path) -> None:
    directory = tmp_path / "manifests"
    taxonomy = tmp_path / "taxonomy.yml"
    write_jsonl(directory / "a.jsonl", [payload("doc-1", notions=["suites"])])
    write_taxonomy(taxonomy, taxonomy_id="maths_fixture", matiere="mathematiques", notions=["suites"])

    report = build_coverage_report(directory, "guarantees", [taxonomy])
    content = report.markdown_path.read_text(encoding="utf-8")

    assert "No source_uri was opened." in content
    assert "No network call was made." in content
    assert "No document ingestion was performed." in content
