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
from schema.document import SourceType, TypeDoc


ROOT = Path(__file__).resolve().parents[2]
BATCH_OFFICIAL_PROFILES = ROOT / "data/fixtures/manifests/batch_official_profiles_clean"
BATCH_CLEAN = ROOT / "data/fixtures/manifests/batch_clean_001"
BATCH_PROBLEM = ROOT / "data/fixtures/manifests/batch_001"
TAXONOMIES = [
    ROOT / "taxonomy/maths/terminale_specialite.yml",
    ROOT / "taxonomy/nsi/terminale.yml",
]


def payload(
    doc_id: str,
    *,
    type_doc: str = TypeDoc.programme_officiel.value,
    official_level_ref: str = "terminale_generale",
    official_subject_ref: str = "mathematiques",
    official_exam_ref: str | None = None,
    candidate_status_ref: str = "scolarise",
    establishment_context_ref: str | None = None,
    official_source_refs: list[str] | None = None,
    official_claim_refs: list[str] | None = None,
    sha: str = "a",
) -> dict[str, object]:
    data: dict[str, object] = {
        "doc_id": doc_id,
        "source_uri": f"fixture://official-profiles/{doc_id}",
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
        "official_level_ref": official_level_ref,
        "official_subject_ref": official_subject_ref,
        "candidate_status_ref": candidate_status_ref,
        "official_source_refs": official_source_refs or ["education_bac_general"],
        "official_claim_refs": official_claim_refs or ["terminale_generale_two_specialties"],
    }
    if official_exam_ref is not None:
        data["official_exam_ref"] = official_exam_ref
    if establishment_context_ref is not None:
        data["establishment_context_ref"] = establishment_context_ref
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


def test_official_profiles_clean_gate_ready(tmp_path) -> None:
    report = build_gate_report(
        BATCH_OFFICIAL_PROFILES,
        "profiles-clean-gate",
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    assert report.status is GateStatus.ready_for_controlled_import


def test_official_profiles_clean_controlled_import_imports(tmp_path) -> None:
    report = controlled_import_manifest_directory(
        BATCH_OFFICIAL_PROFILES,
        db_path=tmp_path / "ledger.sqlite",
        batch_id="profiles-clean-import",
        taxonomy_paths=TAXONOMIES,
        policy=QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    assert report.status is ControlledImportStatus.imported
    assert report.documents_not_retrievable == 0


def test_dnb_scolaire_manifest_passes_official_quality(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "dnb-scolaire",
            type_doc=TypeDoc.annale.value,
            official_level_ref="troisieme_generale",
            official_subject_ref="mathematiques",
            official_exam_ref="dnb_scolaire",
            candidate_status_ref="scolarise",
            official_source_refs=["education_dnb"],
            official_claim_refs=["dnb_scolaire_official_parts"],
        ),
    )

    assert quality.status == "quality_pass"


def test_dnb_individual_manifest_passes_official_quality(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "dnb-individual",
            type_doc=TypeDoc.annale.value,
            official_level_ref="troisieme_generale",
            official_subject_ref="langues_vivantes",
            official_exam_ref="dnb_candidat_individuel",
            candidate_status_ref="candidat_individuel",
            official_source_refs=["bo_dnb_2025"],
            official_claim_refs=["dnb_individual_foreign_language"],
        ),
    )

    assert quality.status == "quality_pass"


def test_premiere_eaf_manifest_passes(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "eaf",
            type_doc=TypeDoc.annale.value,
            official_level_ref="premiere_generale",
            official_subject_ref="francais",
            official_exam_ref="eaf",
            official_source_refs=["education_bac_general"],
            official_claim_refs=["eaf_written_oral"],
        ),
    )

    assert quality.status == "quality_pass"


def test_premiere_eam_manifest_passes(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "eam",
            type_doc=TypeDoc.annale.value,
            official_level_ref="premiere_generale",
            official_subject_ref="mathematiques",
            official_exam_ref="anticipee_maths",
            official_source_refs=["education_bac_questions"],
            official_claim_refs=["anticipee_maths_2027"],
        ),
    )

    assert quality.status == "quality_pass"


def test_terminale_grand_oral_manifest_passes(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "grand-oral",
            type_doc=TypeDoc.grille_grand_oral.value,
            official_exam_ref="grand_oral",
            official_source_refs=["education_bac_general"],
            official_claim_refs=["grand_oral_terminal"],
        ),
    )

    assert quality.status == "quality_pass"


def test_aefe_as_establishment_context_passes(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "aefe-context",
            official_source_refs=["education_bac_general"],
            official_claim_refs=["terminale_generale_two_specialties"],
            establishment_context_ref="aefe",
            candidate_status_ref="scolarise",
        ),
    )

    assert quality.status == "quality_pass"


def test_aefe_as_candidate_status_warns(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload("aefe-candidate", candidate_status_ref="aefe"),
    )

    issue = next(issue for issue in quality.issues if issue.code == "deprecated_candidate_status_ref")
    assert issue.severity is Severity.warning


def test_aefe_as_candidate_status_blocks_in_strict(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload("aefe-candidate-strict", candidate_status_ref="aefe"),
        QualityPolicy(block_on_deprecated_candidate_status_ref=True),
    )

    assert quality.status == "quality_blocked"


def test_unknown_establishment_context_blocks(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload("unknown-context", establishment_context_ref="unknown_context"),
    )

    assert any(issue.code == "unknown_establishment_context_ref" for issue in quality.issues)
    assert quality.status == "quality_blocked"


def test_claim_applies_to_mismatch_blocks(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "claim-mismatch",
            official_exam_ref="grand_oral",
            official_claim_refs=["dnb_individual_foreign_language"],
        ),
    )

    assert any(issue.code == "official_claim_applies_to_mismatch" for issue in quality.issues)
    assert quality.status == "quality_blocked"


def test_source_applies_to_mismatch_blocks(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "source-mismatch",
            official_source_refs=["education_dnb"],
            official_claim_refs=["terminale_generale_two_specialties"],
        ),
    )

    assert any(issue.code == "official_source_applies_to_mismatch" for issue in quality.issues)
    assert quality.status == "quality_blocked"


def test_pending_ift_claim_blocks_definitive_regulatory_doc(tmp_path) -> None:
    quality = quality_for(
        tmp_path,
        payload(
            "pending-ift",
            official_source_refs=["ift_examens_concours"],
            official_claim_refs=["tunisie_ift_local_documents_pending"],
        ),
    )

    assert any(issue.code == "pending_official_claim" for issue in quality.issues)
    assert quality.status == "quality_blocked"


def test_batch_clean_001_still_passes(tmp_path) -> None:
    report = build_gate_report(
        BATCH_CLEAN,
        "batch-clean-still-passes",
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    assert report.status is GateStatus.ready_for_controlled_import


def test_problem_batch_still_blocked(tmp_path) -> None:
    report = build_gate_report(
        BATCH_PROBLEM,
        "problem-still-blocked",
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    assert report.status is GateStatus.blocked
