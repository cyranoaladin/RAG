from __future__ import annotations

from pathlib import Path

import yaml

from schema.official_reference import (
    CandidateStatusReference,
    ExamReference,
    OfficialSource,
    SchoolLevelReference,
    SubjectReference,
)

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "data/reference"


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def official_sources() -> dict[str, OfficialSource]:
    payload = load_yaml(REFERENCE / "official_sources.yml")
    sources = [OfficialSource.model_validate(item) for item in payload["official_sources"]]
    return {source.source_id: source for source in sources}


def levels() -> dict[str, SchoolLevelReference]:
    result = {}
    for path in (REFERENCE / "levels").glob("*.yml"):
        level = SchoolLevelReference.model_validate(load_yaml(path))
        result[level.level_id] = level
    return result


def exams() -> dict[str, ExamReference]:
    result = {}
    for path in (REFERENCE / "exams").glob("*.yml"):
        exam = ExamReference.model_validate(load_yaml(path))
        result[exam.exam_id] = exam
    return result


def candidate_statuses() -> dict[str, CandidateStatusReference]:
    payload = load_yaml(REFERENCE / "candidate_statuses.yml")
    statuses = [CandidateStatusReference.model_validate(item) for item in payload["candidate_statuses"]]
    return {status.status_id: status for status in statuses}


def subject_lists() -> dict[str, SubjectReference]:
    subjects: dict[str, SubjectReference] = {}
    for filename, key in [("specialties.yml", "specialties"), ("options.yml", "options")]:
        payload = load_yaml(REFERENCE / filename)
        for item in payload[key]:
            subject = SubjectReference.model_validate(item)
            subjects[subject.subject_id] = subject
    return subjects


def test_all_reference_yaml_validates_against_models() -> None:
    assert official_sources()
    assert levels()
    assert exams()
    assert candidate_statuses()
    assert subject_lists()


def test_troisieme_references_dnb() -> None:
    troisieme = levels()["troisieme_generale"]

    assert "dnb" in troisieme.exam_refs


def test_dnb_contains_school_and_individual_candidates() -> None:
    dnb = exams()["dnb"]

    assert "scolarise" in dnb.candidate_types
    assert "candidat_individuel" in dnb.candidate_types


def test_dnb_individual_candidate_contains_specific_foreign_language_exam() -> None:
    dnb = exams()["dnb"]

    assert "langue_vivante_etrangere_candidats_individuels" in dnb.exam_parts
    assert dnb.coefficients["langue_vivante_etrangere_candidats_individuels"] == 2


def test_seconde_contains_common_subjects_and_options() -> None:
    seconde = levels()["seconde_generale_technologique"]

    assert "francais" in seconde.common_subjects
    assert "snt" in seconde.common_subjects
    assert seconde.optional_subjects


def test_premiere_contains_three_specialties_rule() -> None:
    premiere = levels()["premiere_generale"]

    assert premiere.expected_specialties_count == 3


def test_premiere_contains_eaf_and_eam() -> None:
    premiere = levels()["premiere_generale"]

    assert "eaf" in premiere.exam_refs
    assert "anticipee_maths" in premiere.exam_refs


def test_terminale_contains_two_specialties_rule() -> None:
    terminale = levels()["terminale_generale"]

    assert terminale.expected_specialties_count == 2


def test_terminale_contains_philosophy_and_grand_oral() -> None:
    terminale = levels()["terminale_generale"]

    assert "philosophie" in terminale.common_subjects
    assert "grand_oral" in terminale.exam_refs


def test_maths_expertes_requires_maths_specialty() -> None:
    maths_expertes = subject_lists()["maths_expertes"]

    assert maths_expertes.is_option is True
    assert "mathematiques" in maths_expertes.requires_subjects


def test_maths_complementaires_requires_maths_not_conserved() -> None:
    maths_complementaires = subject_lists()["maths_complementaires"]

    assert maths_complementaires.is_option is True
    assert "mathematiques" in maths_complementaires.excludes_terminal_specialties


def test_bac_general_contains_40_60_weights() -> None:
    bac = exams()["bac_general"]

    assert bac.control_continu_weight == 40
    assert bac.terminal_weight == 60


def test_free_candidate_has_exam_card_warning() -> None:
    candidat = candidate_statuses()["candidat_individuel"]

    assert "carte d'examen obligatoire" in candidat.warnings


def test_unknown_verification_status_cannot_be_official_verified() -> None:
    for source in official_sources().values():
        assert not (
            source.verification_status == "unknown"
            and source.authority_level == "official_verified"
        )
