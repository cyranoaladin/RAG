from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from rag_pedago.imports.coverage import CoverageStatus, build_coverage_report
from rag_pedago.imports.gate import GateStatus, build_gate_report
from rag_pedago.imports.manifest import import_manifest_directory
from rag_pedago.imports.quality import QualityPolicy
from rag_pedago.imports.readiness import ReadinessStatus, build_readiness_report
from rag_pedago.imports.review import ReviewStatus, build_review_package
from schema.document import DocumentMeta


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = ROOT / "data/fixtures/pilot_math_terminale"
MANIFEST_DIR = FIXTURE_ROOT / "manifests"
VALID_MANIFEST = MANIFEST_DIR / "pilot_math_terminale_specialite.valid.jsonl"
MISSING_RIGHTS_MANIFEST = (
    MANIFEST_DIR / "pilot_math_terminale_specialite.invalid_missing_rights.jsonl"
)
UNKNOWN_RIGHTS_MANIFEST = (
    MANIFEST_DIR / "pilot_math_terminale_specialite.invalid_unknown_rights.jsonl"
)
MATH_TAXONOMY = ROOT / "taxonomy/maths/terminale_specialite.yml"
PRIORITY_NOTIONS = [
    "suites",
    "recurrence",
    "limites_de_suites",
    "probabilites_conditionnelles",
    "loi_binomiale",
    "algorithmique_python",
]
FORBIDDEN_TEXT = [
    "/srv/nexusreussite/rag-ui",
    "/home/alaeddine/Bureau/RAG/rag-local",
    "OPENAI" + "_API_KEY",
    "QDRANT" + "_URL",
    "POSTGRES" + "_URL",
]


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _single_manifest_dir(tmp_path: Path, source: Path) -> Path:
    directory = tmp_path / "manifests"
    directory.mkdir()
    (directory / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return directory


def test_valid_pilot_manifest_exists_and_has_minimum_documents() -> None:
    assert VALID_MANIFEST.is_file()

    rows = _read_jsonl(VALID_MANIFEST)

    assert len(rows) >= 5


def test_valid_pilot_manifest_lines_validate_as_document_meta() -> None:
    metas = [DocumentMeta.model_validate(row) for row in _read_jsonl(VALID_MANIFEST)]

    assert all(meta.source_uri.startswith("synthetic://pilot/maths-terminale/") for meta in metas)
    assert all(meta.niveau and meta.niveau.value == "terminale" for meta in metas)
    assert all(meta.matiere == "mathematiques" for meta in metas)
    assert all(meta.candidat and meta.candidat.value == "scolarise" for meta in metas)


def test_valid_pilot_manifest_does_not_require_real_source_files(tmp_path) -> None:
    directory = _single_manifest_dir(tmp_path, VALID_MANIFEST)

    report = import_manifest_directory(
        directory,
        db_path=tmp_path / "ledger.sqlite",
        batch_id="pilot-math-source-uri-dry-run",
        dry_run=True,
        policy=QualityPolicy(),
    )

    assert report.documents_valid >= 5
    assert all(meta.source_uri.startswith("synthetic://") for meta in report.valid_metas)
    assert not any(Path(meta.source_uri).exists() for meta in report.valid_metas)


def test_valid_pilot_manifest_covers_priority_notions() -> None:
    metas = [DocumentMeta.model_validate(row) for row in _read_jsonl(VALID_MANIFEST)]
    declared = {notion for meta in metas for notion in meta.notions}

    assert set(PRIORITY_NOTIONS).issubset(declared)


def test_missing_rights_manifest_fails_document_validation() -> None:
    row = _read_jsonl(MISSING_RIGHTS_MANIFEST)[0]

    with pytest.raises(ValidationError):
        DocumentMeta.model_validate(row)


def test_unknown_rights_manifest_is_valid_but_not_retrievable(tmp_path) -> None:
    row = _read_jsonl(UNKNOWN_RIGHTS_MANIFEST)[0]
    meta = DocumentMeta.model_validate(row)

    assert meta.rights.value == "unknown"
    assert meta.is_retrievable is False

    directory = _single_manifest_dir(tmp_path, UNKNOWN_RIGHTS_MANIFEST)
    report = import_manifest_directory(
        directory,
        db_path=tmp_path / "ledger.sqlite",
        batch_id="pilot-math-unknown-rights",
        dry_run=True,
        policy=QualityPolicy(),
    )

    assert report.documents_valid == 1
    assert report.documents_not_retrievable == 1


def test_pilot_fixtures_do_not_reference_forbidden_paths_or_secrets() -> None:
    for path in [VALID_MANIFEST, MISSING_RIGHTS_MANIFEST, UNKNOWN_RIGHTS_MANIFEST]:
        content = path.read_text(encoding="utf-8")
        assert not any(forbidden in content for forbidden in FORBIDDEN_TEXT)


def test_pilot_manifest_chain_reaches_review_package(tmp_path) -> None:
    directory = _single_manifest_dir(tmp_path, VALID_MANIFEST)
    output_dir = tmp_path / "reports"

    readiness = build_readiness_report(
        directory,
        "pilot-math-readiness",
        QualityPolicy(),
        output_dir=output_dir,
    )
    coverage = build_coverage_report(
        directory,
        "pilot-math-coverage",
        [MATH_TAXONOMY],
        priority_notions=PRIORITY_NOTIONS,
        output_dir=output_dir,
    )
    gate = build_gate_report(
        directory,
        "pilot-math-gate",
        [MATH_TAXONOMY],
        QualityPolicy(),
        priority_notions=PRIORITY_NOTIONS,
        output_dir=output_dir,
    )
    review = build_review_package(
        directory,
        "pilot-math-review",
        [MATH_TAXONOMY],
        QualityPolicy(),
        priority_notions=PRIORITY_NOTIONS,
        output_dir=output_dir,
    )

    assert readiness.status is ReadinessStatus.ready
    assert coverage.status is CoverageStatus.ok
    assert gate.status is GateStatus.ready_for_controlled_import
    assert review.status is ReviewStatus.ready_for_review
