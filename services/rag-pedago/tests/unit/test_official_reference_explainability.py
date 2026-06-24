from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rag_pedago.imports.controlled_import import controlled_import_manifest_directory
from rag_pedago.imports.gate import GateStatus, build_gate_report
from rag_pedago.imports.manifest import import_manifest_directory
from rag_pedago.imports.quality import QualityPolicy, evaluate_manifest_directory_quality
from rag_pedago.imports.readiness import build_readiness_report
from rag_pedago.reference.loader import load_official_reference_index
from rag_pedago.reference.resolver import OfficialReferenceResolver
from schema.document import DocumentMeta


ROOT = Path(__file__).resolve().parents[2]
TAXONOMIES = [
    ROOT / "taxonomy/maths/terminale_specialite.yml",
    ROOT / "taxonomy/nsi/terminale.yml",
]
BATCH_MISMATCH = ROOT / "data/fixtures/manifests/batch_official_mismatch"
BATCH_OFFICIAL_PROFILES = ROOT / "data/fixtures/manifests/batch_official_profiles_clean"


def meta(
    doc_id: str,
    *,
    official_exam_ref: str = "grand_oral",
    candidate_status_ref: str = "scolarise",
) -> DocumentMeta:
    return DocumentMeta.model_validate(
        {
            "doc_id": doc_id,
            "source_uri": f"fixture://explainability/{doc_id}",
            "source_type": "upload",
            "sha256": "1" * 64,
            "discovered_at": datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc).isoformat(),
            "rights": "officiel_public",
            "visibility": "public",
            "niveau": "terminale",
            "matiere": "mathematiques",
            "type_doc": "annale",
            "epreuve": "grand_oral",
            "programme_version": "fixture-programme",
            "notions": ["suites"],
            "official_level_ref": "terminale_generale",
            "official_subject_ref": "mathematiques",
            "official_exam_ref": official_exam_ref,
            "candidate_status_ref": candidate_status_ref,
        }
    )


def resolver() -> OfficialReferenceResolver:
    return OfficialReferenceResolver(load_official_reference_index(ROOT / "data/reference"))


def quality_for_batch(tmp_path: Path, directory: Path = BATCH_MISMATCH):
    report = import_manifest_directory(directory, tmp_path / "ledger.sqlite", dry_run=True)
    return evaluate_manifest_directory_quality(report, QualityPolicy())


def test_source_explanation_for_bac_general_to_grand_oral_contains_path() -> None:
    explanation = resolver().explain_source_compatibility("education_bac_general", meta("grand-oral"))

    assert explanation.compatible is True
    assert explanation.matched_ref == "grand_oral"
    assert explanation.path == ["bac_general", "grand_oral"]
    assert "bac_general -> grand_oral" in explanation.reason


def test_source_explanation_for_dnb_to_grand_oral_is_incompatible() -> None:
    explanation = resolver().explain_source_compatibility("education_dnb", meta("grand-oral"))

    assert explanation.compatible is False
    assert explanation.matched_ref is None
    assert explanation.path == []
    assert "no compatible path" in explanation.reason


def test_claim_explanation_for_bac_to_specialite_contains_path() -> None:
    explanation = resolver().explain_claim_compatibility(
        "bac_general_40_60",
        meta("specialite", official_exam_ref="bac_specialite_ecrit"),
    )

    assert explanation.compatible is True
    assert explanation.path == ["bac_general", "bac_specialite_ecrit"]


def test_claim_explanation_for_dnb_individual_to_scolarise_is_incompatible() -> None:
    explanation = resolver().explain_claim_compatibility(
        "candidat_individuel_exam_card_required",
        meta("scolarise", candidate_status_ref="scolarise"),
    )

    assert explanation.compatible is False
    assert "scolarise" in explanation.document_refs


def test_quality_issue_contains_source_compatibility_explanation(tmp_path) -> None:
    quality = quality_for_batch(tmp_path)
    issue = next(issue for issue in quality.issues if issue.code == "official_source_applies_to_mismatch")

    assert issue.compatibility_explanation is not None
    assert issue.compatibility_explanation.ref_id == "education_dnb"
    assert issue.compatibility_explanation.compatible is False


def test_quality_issue_contains_claim_compatibility_explanation(tmp_path) -> None:
    quality = quality_for_batch(tmp_path)
    issue = next(issue for issue in quality.issues if issue.code == "official_claim_applies_to_mismatch")

    assert issue.compatibility_explanation is not None
    assert issue.compatibility_explanation.ref_id == "candidat_individuel_exam_card_required"
    assert "scolarise" in issue.compatibility_explanation.document_refs


def test_readiness_report_contains_official_reference_compatibility_section(tmp_path) -> None:
    report = build_readiness_report(
        BATCH_MISMATCH,
        "mismatch-readiness",
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    markdown = report.markdown_path.read_text(encoding="utf-8")
    assert "## Official reference compatibility" in markdown
    assert "education_dnb" in markdown
    assert "no compatible path" in markdown


def test_gate_json_contains_compatibility_explanations(tmp_path) -> None:
    report = build_gate_report(
        BATCH_MISMATCH,
        "mismatch-gate",
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )
    payload = json.loads(report.json_path.read_text(encoding="utf-8"))

    assert report.status is GateStatus.blocked
    issues = payload["issues"]["blocking"]
    explanations = [issue["compatibility_explanation"] for issue in issues if issue.get("compatibility_explanation")]
    assert any(explanation["ref_id"] == "education_dnb" for explanation in explanations)


def test_controlled_import_blocked_report_contains_compatibility_explanations(tmp_path) -> None:
    report = controlled_import_manifest_directory(
        BATCH_MISMATCH,
        db_path=tmp_path / "ledger.sqlite",
        batch_id="mismatch-controlled",
        taxonomy_paths=TAXONOMIES,
        policy=QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    markdown = report.markdown_path.read_text(encoding="utf-8")
    payload = json.loads(report.json_path.read_text(encoding="utf-8"))
    assert "## Official reference compatibility" in markdown
    assert "education_dnb" in markdown
    assert payload["official_reference_compatibility"]


def test_clean_official_profiles_has_no_mismatch_explanations(tmp_path) -> None:
    quality = quality_for_batch(tmp_path, BATCH_OFFICIAL_PROFILES)

    assert not [
        issue
        for issue in quality.issues
        if issue.code
        in {"official_source_applies_to_mismatch", "official_claim_applies_to_mismatch"}
    ]
