from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rag_pedago.imports.controlled_import import (
    ControlledImportStatus,
    controlled_import_manifest_directory,
)
from rag_pedago.imports.gate import GateStatus, build_gate_report
from rag_pedago.imports.manifest import import_manifest_directory
from rag_pedago.imports.quality import QualityPolicy, Severity, evaluate_manifest_directory_quality
from rag_pedago.reference.loader import load_official_reference_index
from schema.document import SourceType, TypeDoc


ROOT = Path(__file__).resolve().parents[2]
BATCH_CLEAN = ROOT / "data/fixtures/manifests/batch_clean_001"
TAXONOMIES = [
    ROOT / "taxonomy/maths/terminale_specialite.yml",
    ROOT / "taxonomy/nsi/terminale.yml",
]


def payload(
    doc_id: str,
    *,
    type_doc: str = TypeDoc.programme_officiel.value,
    sha: str = "a",
    official_level_ref: str | None = "terminale_generale",
    official_subject_ref: str | None = "mathematiques",
    official_exam_ref: str | None = None,
    candidate_status_ref: str | None = None,
    official_source_refs: list[str] | None = None,
    official_claim_refs: list[str] | None = None,
    establishment_context_ref: str | None = None,
) -> dict[str, object]:
    data: dict[str, object] = {
        "doc_id": doc_id,
        "source_uri": f"fixture://official-quality/{doc_id}",
        "source_type": SourceType.upload.value,
        "sha256": sha * 64,
        "discovered_at": datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc).isoformat(),
        "rights": "officiel_public",
        "visibility": "public",
        "niveau": "terminale",
        "matiere": "mathematiques",
        "type_doc": type_doc,
        "epreuve": "bac_specialite_ecrit",
        "programme_version": "fixture-programme",
        "notions": ["suites"],
    }
    optional = {
        "official_level_ref": official_level_ref,
        "official_subject_ref": official_subject_ref,
        "official_exam_ref": official_exam_ref,
        "candidate_status_ref": candidate_status_ref,
        "official_source_refs": official_source_refs,
        "official_claim_refs": official_claim_refs,
        "establishment_context_ref": establishment_context_ref,
    }
    for key, value in optional.items():
        if value is not None:
            data[key] = value
    return data


def write_jsonl(path: Path, lines: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line) + "\n")


def quality_for(tmp_path, doc: dict[str, object], policy: QualityPolicy | None = None):
    directory = tmp_path / "manifests"
    write_jsonl(directory / "a.jsonl", [doc])
    directory_report = import_manifest_directory(directory, tmp_path / "ledger.sqlite", dry_run=True)
    return evaluate_manifest_directory_quality(directory_report, policy or QualityPolicy())


def test_official_reference_index_loads_reference_data() -> None:
    index = load_official_reference_index(ROOT / "data/reference")

    assert index.has_level("terminale_generale")
    assert index.has_subject("mathematiques")
    assert index.has_exam("bac_specialite_ecrit")
    assert index.has_candidate_status("candidat_individuel")
    assert index.has_claim("bac_general_40_60")
    assert index.source_is_verified("education_bac_general")


def test_official_programme_missing_official_refs_warns_or_blocks(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "missing-official-refs",
            official_level_ref=None,
            official_subject_ref=None,
            official_source_refs=None,
            official_claim_refs=None,
        ),
    )

    codes = {issue.code for issue in quality.issues}
    assert "missing_official_level_ref" in codes
    assert "missing_official_subject_ref" in codes
    assert "official_doc_without_verified_source" in codes
    assert quality.status == "quality_blocked"


def test_exam_document_missing_official_exam_ref_blocks_in_strict(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "exam-missing-ref",
            type_doc=TypeDoc.annale.value,
            official_exam_ref=None,
            candidate_status_ref="scolarise",
            official_claim_refs=["bac_general_40_60"],
        ),
        QualityPolicy(require_official_refs_for_exam_docs=True),
    )

    assert any(issue.code == "missing_official_exam_ref" for issue in quality.issues)
    assert quality.status == "quality_blocked"


def test_unknown_official_level_ref_blocks(tmp_path) -> None:
    quality = quality_for(tmp_path, payload("unknown-level", official_level_ref="missing_level"))

    assert any(issue.code == "unknown_official_level_ref" for issue in quality.issues)
    assert quality.status == "quality_blocked"


def test_unknown_official_exam_ref_blocks(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "unknown-exam",
            type_doc=TypeDoc.annale.value,
            official_exam_ref="missing_exam",
            candidate_status_ref="scolarise",
            official_claim_refs=["bac_general_40_60"],
        ),
    )

    assert any(issue.code == "unknown_official_exam_ref" for issue in quality.issues)
    assert quality.status == "quality_blocked"


def test_deprecated_aefe_candidate_status_warns_by_default(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "aefe-deprecated",
            type_doc=TypeDoc.annale.value,
            official_exam_ref="bac_specialite_ecrit",
            candidate_status_ref="aefe",
            official_claim_refs=["bac_general_40_60"],
        ),
    )

    issue = next(issue for issue in quality.issues if issue.code == "deprecated_candidate_status_ref")
    assert issue.severity is Severity.warning


def test_deprecated_aefe_candidate_status_blocks_in_strict(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "aefe-strict",
            type_doc=TypeDoc.annale.value,
            official_exam_ref="bac_specialite_ecrit",
            candidate_status_ref="aefe",
            official_claim_refs=["bac_general_40_60"],
        ),
        QualityPolicy(block_on_deprecated_candidate_status_ref=True),
    )

    assert any(
        issue.code == "deprecated_candidate_status_ref" and issue.severity is Severity.error
        for issue in quality.issues
    )
    assert quality.status == "quality_blocked"


def test_pending_claim_cannot_support_definitive_regulatory_doc(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "pending-claim",
            official_source_refs=["ift_examens_concours"],
            official_claim_refs=["tunisie_ift_local_documents_pending"],
        ),
    )

    assert any(issue.code == "pending_official_claim" for issue in quality.issues)
    assert quality.status == "quality_blocked"


def test_verified_claim_allows_regulatory_doc(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "verified-claim",
            official_source_refs=["education_bac_general"],
            official_claim_refs=["bac_general_40_60"],
        ),
    )

    assert quality.status == "quality_pass"


def test_bac_general_source_is_compatible_with_grand_oral(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "bac-source-grand-oral",
            type_doc=TypeDoc.grille_grand_oral.value,
            official_exam_ref="grand_oral",
            candidate_status_ref="scolarise",
            official_source_refs=["education_bac_general"],
            official_claim_refs=["grand_oral_terminal"],
        ),
    )

    assert not any(issue.code == "official_source_applies_to_mismatch" for issue in quality.issues)
    assert quality.status == "quality_pass"


def test_dnb_source_is_incompatible_with_bac_document(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "dnb-source-bac",
            type_doc=TypeDoc.annale.value,
            official_exam_ref="grand_oral",
            candidate_status_ref="scolarise",
            official_source_refs=["education_dnb"],
            official_claim_refs=["grand_oral_terminal"],
        ),
    )

    assert any(issue.code == "official_source_applies_to_mismatch" for issue in quality.issues)
    assert quality.status == "quality_blocked"


def test_dnb_claim_is_incompatible_with_grand_oral(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "dnb-claim-grand-oral",
            type_doc=TypeDoc.grille_grand_oral.value,
            official_exam_ref="grand_oral",
            candidate_status_ref="scolarise",
            official_source_refs=["education_bac_general"],
            official_claim_refs=["dnb_individual_foreign_language"],
        ),
    )

    assert any(issue.code == "official_claim_applies_to_mismatch" for issue in quality.issues)
    assert quality.status == "quality_blocked"


def test_bac_claim_is_compatible_with_bac_specialite_via_aggregate(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "bac-claim-specialite",
            type_doc=TypeDoc.annale.value,
            official_exam_ref="bac_specialite_ecrit",
            candidate_status_ref="scolarise",
            official_source_refs=["education_bac_general"],
            official_claim_refs=["bac_general_40_60"],
        ),
    )

    assert not any(issue.code == "official_claim_applies_to_mismatch" for issue in quality.issues)


def test_official_subject_level_mismatch_blocks(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "subject-mismatch",
            official_level_ref="premiere_generale",
            official_subject_ref="maths_expertes",
            official_source_refs=["education_bac_general"],
            official_claim_refs=["terminale_generale_two_specialties"],
        ),
    )

    assert any(issue.code == "official_subject_level_mismatch" for issue in quality.issues)
    assert quality.status == "quality_blocked"


def test_official_exam_level_mismatch_blocks(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "exam-mismatch",
            type_doc=TypeDoc.annale.value,
            official_level_ref="premiere_generale",
            official_exam_ref="bac_specialite_ecrit",
            candidate_status_ref="scolarise",
            official_claim_refs=["bac_general_40_60"],
        ),
    )

    assert any(issue.code == "official_exam_level_mismatch" for issue in quality.issues)
    assert quality.status == "quality_blocked"


def test_clean_batch_still_passes_gate_with_official_refs(tmp_path) -> None:
    report = build_gate_report(
        BATCH_CLEAN,
        "official-clean-gate",
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    assert report.status is GateStatus.ready_for_controlled_import


def test_controlled_import_clean_batch_still_imports(tmp_path) -> None:
    report = controlled_import_manifest_directory(
        BATCH_CLEAN,
        db_path=tmp_path / "ledger.sqlite",
        batch_id="official-clean-import",
        taxonomy_paths=TAXONOMIES,
        policy=QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    assert report.status is ControlledImportStatus.imported


def test_problem_official_refs_batch_is_blocked_by_gate(tmp_path) -> None:
    directory = tmp_path / "problem"
    write_jsonl(
        directory / "official_missing_refs.jsonl",
        [
            payload(
                "official-missing",
                type_doc=TypeDoc.programme_officiel.value,
                official_level_ref=None,
                official_subject_ref=None,
                official_source_refs=None,
                official_claim_refs=None,
            )
        ],
    )

    report = build_gate_report(
        directory,
        "official-problem",
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    assert report.status is GateStatus.blocked
