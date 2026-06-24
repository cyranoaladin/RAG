from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from schema.official_reference import (
    CandidateStatusReference,
    ExamReference,
    OfficialSource,
    SchoolLevelReference,
    SubjectReference,
)


def test_official_source_accepts_verified_institutional_source() -> None:
    source = OfficialSource(
        source_id="education_bac_general",
        title="Le baccalauréat général",
        url="https://www.education.gouv.fr/reussir-au-lycee/le-baccalaureat-general-10457",
        authority_level="official_verified",
        verification_status="verified",
        last_verified_at=datetime(2026, 6, 14, tzinfo=UTC),
        applies_to=["bac_general", "terminale_generale"],
    )

    assert source.authority_level == "official_verified"
    assert source.verification_status == "verified"


def test_official_source_rejects_unknown_status_as_official_verified() -> None:
    with pytest.raises(ValidationError):
        OfficialSource(
            source_id="bad_source",
            title="Bad source",
            url="https://example.invalid",
            authority_level="official_verified",
            verification_status="unknown",
            last_verified_at=datetime(2026, 6, 14, tzinfo=UTC),
            applies_to=["bac_general"],
        )


def test_official_reference_models_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SchoolLevelReference(
            level_id="terminale_generale",
            label="Terminale générale",
            school_year="2026-2027",
            common_subjects=["philosophie"],
            official_sources=["education_bac_general"],
            unexpected=True,
        )


def test_exam_reference_accepts_bac_weights() -> None:
    exam = ExamReference(
        exam_id="bac_general",
        label="Baccalauréat général",
        level_id="terminale_generale",
        candidate_types=["scolarise", "individuel"],
        exam_parts=["controle_continu", "epreuves_terminales"],
        is_terminal=True,
        control_continu_weight=40,
        terminal_weight=60,
        official_sources=["education_bac_general"],
    )

    assert exam.control_continu_weight == 40
    assert exam.terminal_weight == 60


def test_candidate_status_reference_accepts_free_candidate_warning() -> None:
    status = CandidateStatusReference(
        status_id="candidat_individuel",
        label="Candidat individuel",
        applies_to_levels=["premiere_generale", "terminale_generale"],
        control_continu_mode="evaluations_ponctuelles",
        exam_mode="epreuves_terminales",
        warnings=["carte d'examen obligatoire"],
        official_sources=["eduscol_candidats_individuels_bac"],
    )

    assert "carte d'examen obligatoire" in status.warnings


def test_subject_reference_accepts_option_rules() -> None:
    subject = SubjectReference(
        subject_id="maths_expertes",
        label="Mathématiques expertes",
        level_id="terminale_generale",
        is_option=True,
        weekly_hours=3,
        requires_subjects=["mathematiques"],
        official_sources=["education_maths_reforme_lycee"],
    )

    assert subject.requires_subjects == ["mathematiques"]
