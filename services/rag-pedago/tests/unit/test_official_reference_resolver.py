from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rag_pedago.reference.loader import load_official_reference_index
from rag_pedago.reference.resolver import OfficialReferenceResolver
from schema.document import DocumentMeta

ROOT = Path(__file__).resolve().parents[2]


def meta(
    doc_id: str,
    *,
    official_level_ref: str = "terminale_generale",
    official_subject_ref: str = "mathematiques",
    official_exam_ref: str | None = "grand_oral",
    candidate_status_ref: str = "scolarise",
    establishment_context_ref: str | None = None,
) -> DocumentMeta:
    payload: dict[str, object] = {
        "doc_id": doc_id,
        "source_uri": f"fixture://resolver/{doc_id}",
        "source_type": "upload",
        "sha256": "1" * 64,
        "discovered_at": datetime(2026, 6, 14, 12, 0, tzinfo=UTC).isoformat(),
        "rights": "officiel_public",
        "visibility": "public",
        "niveau": "terminale",
        "matiere": "mathematiques",
        "type_doc": "annale",
        "epreuve": "grand_oral",
        "programme_version": "fixture-programme",
        "notions": ["suites"],
        "official_level_ref": official_level_ref,
        "official_subject_ref": official_subject_ref,
        "candidate_status_ref": candidate_status_ref,
    }
    if official_exam_ref is not None:
        payload["official_exam_ref"] = official_exam_ref
    if establishment_context_ref is not None:
        payload["establishment_context_ref"] = establishment_context_ref
    return DocumentMeta.model_validate(payload)


def resolver() -> OfficialReferenceResolver:
    return OfficialReferenceResolver(load_official_reference_index(ROOT / "data/reference"))


def test_bac_general_source_applies_to_grand_oral() -> None:
    assert resolver().source_applies_to_document("education_bac_general", meta("grand-oral"))


def test_bac_general_source_applies_to_bac_specialite() -> None:
    document = meta("specialite", official_exam_ref="bac_specialite_ecrit")

    assert resolver().source_applies_to_document("education_bac_general", document)


def test_dnb_source_does_not_apply_to_bac_document() -> None:
    assert not resolver().source_applies_to_document("education_dnb", meta("bac-doc"))


def test_dnb_aggregate_applies_to_dnb_individual() -> None:
    document = meta(
        "dnb-individual",
        official_level_ref="troisieme_generale",
        official_subject_ref="langues_vivantes",
        official_exam_ref="dnb_candidat_individuel",
        candidate_status_ref="candidat_individuel",
    )

    assert resolver().source_applies_to_document("education_dnb", document)


def test_premiere_level_applies_to_eaf() -> None:
    document = meta(
        "eaf",
        official_level_ref="premiere_generale",
        official_subject_ref="francais",
        official_exam_ref="eaf",
    )

    assert resolver().source_applies_to_document("education_voie_generale", document)


def test_terminale_level_applies_to_grand_oral() -> None:
    assert "terminale_generale" in resolver().ancestors_for_ref("grand_oral")


def test_claim_candidate_individual_does_not_apply_to_scolarise() -> None:
    assert not resolver().claim_applies_to_document("candidat_individuel_exam_card_required", meta("scolarise"))


def test_aefe_context_does_not_equal_candidate_status() -> None:
    document = meta("aefe", establishment_context_ref="aefe", candidate_status_ref="scolarise")

    assert "aefe" in resolver().refs_for_document(document)
    assert "scolarise" in resolver().refs_for_document(document)
    assert not resolver().claim_applies_to_document("candidat_individuel_exam_card_required", document)


def test_source_compatibility_explanation_contains_path() -> None:
    explanation = resolver().explain_source_compatibility("education_bac_general", meta("grand-oral"))

    assert explanation.compatible is True
    assert explanation.path == ["bac_general", "grand_oral"]


def test_claim_compatibility_explanation_contains_document_refs() -> None:
    explanation = resolver().explain_claim_compatibility("dnb_individual_foreign_language", meta("grand-oral"))

    assert explanation.compatible is False
    assert "grand_oral" in explanation.document_refs
    assert "scolarise" in explanation.document_refs
