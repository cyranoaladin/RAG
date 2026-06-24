from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from schema.document import DocumentMeta
from schema.official_reference import (
    CandidateStatusReference,
    EstablishmentContextReference,
    ExamReference,
    OfficialClaim,
    OfficialSource,
    SchoolLevelReference,
    SubjectReference,
)


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "data/reference"


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def source_map() -> dict[str, OfficialSource]:
    payload = load_yaml(REFERENCE / "official_sources.yml")
    sources = [OfficialSource.model_validate(item) for item in payload["official_sources"]]
    return {source.source_id: source for source in sources}


def level_map() -> dict[str, SchoolLevelReference]:
    levels = [SchoolLevelReference.model_validate(load_yaml(path)) for path in (REFERENCE / "levels").glob("*.yml")]
    return {level.level_id: level for level in levels}


def exam_map() -> dict[str, ExamReference]:
    exams = [ExamReference.model_validate(load_yaml(path)) for path in (REFERENCE / "exams").glob("*.yml")]
    return {exam.exam_id: exam for exam in exams}


def candidate_status_map() -> dict[str, CandidateStatusReference]:
    payload = load_yaml(REFERENCE / "candidate_statuses.yml")
    statuses = [CandidateStatusReference.model_validate(item) for item in payload["candidate_statuses"]]
    return {status.status_id: status for status in statuses}


def establishment_context_map() -> dict[str, EstablishmentContextReference]:
    payload = load_yaml(REFERENCE / "establishment_contexts.yml")
    contexts = [
        EstablishmentContextReference.model_validate(item)
        for item in payload["establishment_contexts"]
    ]
    return {context.context_id: context for context in contexts}


def subject_map() -> dict[str, SubjectReference]:
    subjects: dict[str, SubjectReference] = {}
    for filename, key in [
        ("subjects/common_subjects.yml", "common_subjects"),
        ("specialties.yml", "specialties"),
        ("options.yml", "options"),
    ]:
        payload = load_yaml(REFERENCE / filename)
        for item in payload[key]:
            subject = SubjectReference.model_validate(item)
            subjects[subject.subject_id] = subject
    return subjects


def claim_map() -> dict[str, OfficialClaim]:
    payload = load_yaml(REFERENCE / "official_claims.yml")
    claims = [OfficialClaim.model_validate(item) for item in payload["official_claims"]]
    return {claim.claim_id: claim for claim in claims}


def all_reference_objects() -> list[Any]:
    return [
        *source_map().values(),
        *level_map().values(),
        *exam_map().values(),
        *candidate_status_map().values(),
        *establishment_context_map().values(),
        *subject_map().values(),
        *claim_map().values(),
    ]


def test_all_official_sources_referenced_exist() -> None:
    sources = source_map()

    for item in all_reference_objects():
        if hasattr(item, "official_sources"):
            for source_id in item.official_sources:
                assert source_id in sources
        if isinstance(item, OfficialClaim):
            assert item.source_id in sources


def test_all_exam_refs_in_levels_exist() -> None:
    exams = exam_map()

    for level in level_map().values():
        for exam_ref in level.exam_refs:
            assert exam_ref in exams


def test_all_subject_level_ids_exist() -> None:
    levels = level_map()

    for subject in subject_map().values():
        assert subject.level_id in levels


def test_subject_constraints_point_to_known_subjects_or_specialties() -> None:
    subjects = subject_map()

    for subject in subjects.values():
        for required in subject.requires_subjects:
            assert required in subjects
        for excluded in subject.excludes_terminal_specialties:
            assert excluded in subjects
            assert subjects[excluded].is_specialty is True


def test_exam_candidate_types_are_statuses_not_establishment_contexts() -> None:
    statuses = candidate_status_map()
    contexts = establishment_context_map()

    for exam in exam_map().values():
        for candidate_type in exam.candidate_types:
            assert candidate_type in statuses
            assert candidate_type not in contexts
    assert "aefe" in contexts
    assert "aefe" in statuses
    assert statuses["aefe"].deprecated is True
    assert "establishment context" in " ".join(statuses["aefe"].warnings)


def test_no_pending_source_can_be_official_verified() -> None:
    for source in source_map().values():
        assert not (
            source.verification_status == "pending"
            and source.authority_level == "official_verified"
        )


def test_pending_local_source_is_not_sole_source_for_definitive_rule() -> None:
    sources = source_map()

    for item in all_reference_objects():
        if not hasattr(item, "official_sources"):
            continue
        item_sources = [sources[source_id] for source_id in item.official_sources]
        if item_sources and all(source.verification_status == "pending" for source in item_sources):
            assert getattr(item, "verification_status", "pending") == "pending"
            warnings = " ".join(getattr(item, "warnings", []))
            assert "à vérifier manuellement" in warnings


def test_manifest_official_refs_point_to_existing_ids() -> None:
    payload = {
        "doc_id": "official-ref-doc",
        "source_uri": "fixture://official/ref",
        "source_type": "upload",
        "sha256": "a" * 64,
        "discovered_at": "2026-06-14T12:00:00+00:00",
        "rights": "officiel_public",
        "visibility": "public",
        "niveau": "terminale",
        "matiere": "mathematiques",
        "type_doc": "programme_officiel",
        "official_level_ref": "terminale_generale",
        "official_exam_ref": "bac_specialite_ecrit",
        "official_subject_ref": "mathematiques",
        "candidate_status_ref": "scolarise",
    }
    meta = DocumentMeta.model_validate(payload)

    assert meta.official_level_ref in level_map()
    assert meta.official_exam_ref in exam_map()
    assert meta.official_subject_ref in subject_map()
    assert meta.candidate_status_ref in candidate_status_map()


def test_exam_refs_are_split_for_premiere_terminale_and_dnb() -> None:
    levels = level_map()
    exams = exam_map()

    assert {"eaf", "anticipee_maths"} <= set(levels["premiere_generale"].exam_refs)
    assert {
        "bac_specialite_ecrit",
        "philosophie",
        "grand_oral",
        "controle_continu_bac",
    } <= set(levels["terminale_generale"].exam_refs)
    assert {"dnb_scolaire", "dnb_candidat_individuel"} <= set(levels["troisieme_generale"].exam_refs)
    for exam_id in levels["premiere_generale"].exam_refs + levels["terminale_generale"].exam_refs:
        assert exam_id in exams


def test_dnb_individual_variant_has_lve_and_no_oral() -> None:
    dnb_individual = exam_map()["dnb_candidat_individuel"]

    assert "langue_vivante_etrangere_candidats_individuels" in dnb_individual.exam_parts
    assert "oral" not in dnb_individual.exam_parts


def test_grand_oral_is_linked_to_specialties() -> None:
    grand_oral = exam_map()["grand_oral"]

    assert "enseignements_de_specialite" in grand_oral.related_subject_refs


def test_each_official_claim_source_exists_and_verified_claim_has_verified_source() -> None:
    sources = source_map()

    for claim in claim_map().values():
        source = sources[claim.source_id]
        if claim.verification_status == "verified":
            assert source.verification_status == "verified"


def test_regulatory_fields_have_official_claims() -> None:
    fields = {field for claim in claim_map().values() for field in claim.fields_supported}

    assert "bac_general.control_continu_weight" in fields
    assert "bac_general.terminal_weight" in fields
    assert "premiere_generale.expected_specialties_count" in fields
    assert "terminale_generale.expected_specialties_count" in fields
    assert "dnb_candidat_individuel.exam_parts" in fields
    assert "candidate_status.carte_examen" in fields


def test_pending_claim_cannot_be_unique_support_for_definitive_rule() -> None:
    claims_by_field: dict[str, list[OfficialClaim]] = {}
    for claim in claim_map().values():
        for field in claim.fields_supported:
            claims_by_field.setdefault(field, []).append(claim)

    for field, claims in claims_by_field.items():
        if all(claim.verification_status == "pending" for claim in claims):
            assert not field.startswith(("bac_general.", "dnb_", "premiere_", "terminale_"))


def test_common_subjects_listed_in_levels_have_subject_reference() -> None:
    subjects = subject_map()

    for level in level_map().values():
        for subject_id in level.common_subjects:
            assert subject_id in subjects


def test_unverified_weekly_hours_are_not_forced() -> None:
    for subject in subject_map().values():
        if subject.verification_status == "pending":
            assert subject.weekly_hours is None


def test_option_and_specialty_constraints_are_detectable() -> None:
    subjects = subject_map()

    maths_expertes = subjects["maths_expertes"]
    maths_complementaires = subjects["maths_complementaires"]
    dgemc = subjects["dgemc"]

    assert "mathematiques" in maths_expertes.requires_subjects
    assert "mathematiques" in maths_complementaires.excludes_terminal_specialties
    assert dgemc.level_id == "terminale_generale"
    assert "terminale_generale" in dgemc.allowed_level_ids
