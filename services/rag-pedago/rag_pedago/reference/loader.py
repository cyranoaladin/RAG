from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from rag_pedago.reference.index import OfficialReferenceIndex
from schema.official_reference import (
    CandidateStatusReference,
    EstablishmentContextReference,
    ExamReference,
    OfficialClaim,
    OfficialSource,
    SchoolLevelReference,
    SubjectReference,
)

ModelT = TypeVar("ModelT", bound=BaseModel)
ROOT = Path(__file__).resolve().parents[2]


def _load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_many(path: Path, key: str, model: type[ModelT], id_field: str) -> dict[str, ModelT]:
    payload = _load_yaml(path)
    items = [model.model_validate(item) for item in payload[key]]
    return {str(getattr(item, id_field)): item for item in items}


def _load_directory(path: Path, model: type[ModelT], id_field: str) -> dict[str, ModelT]:
    result: dict[str, ModelT] = {}
    for item_path in sorted(path.glob("*.yml")):
        item = model.model_validate(_load_yaml(item_path))
        result[str(getattr(item, id_field))] = item
    return result


def _merge_subjects(*groups: dict[str, SubjectReference]) -> dict[str, SubjectReference]:
    subjects: dict[str, SubjectReference] = {}
    for group in groups:
        for subject_id, subject in group.items():
            if subject_id not in subjects:
                subjects[subject_id] = subject
                continue
            existing = subjects[subject_id]
            allowed = sorted(
                {
                    *existing.allowed_level_ids,
                    *subject.allowed_level_ids,
                    existing.level_id,
                    subject.level_id,
                }
            )
            subjects[subject_id] = subject.model_copy(update={"allowed_level_ids": allowed})
    return subjects


def load_official_reference_index(reference_dir: Path = Path("data/reference")) -> OfficialReferenceIndex:
    if not reference_dir.exists() and not reference_dir.is_absolute():
        reference_dir = ROOT / reference_dir
    common_subjects = _load_many(
        reference_dir / "subjects" / "common_subjects.yml",
        "common_subjects",
        SubjectReference,
        "subject_id",
    )
    specialties = _load_many(
        reference_dir / "specialties.yml",
        "specialties",
        SubjectReference,
        "subject_id",
    )
    options = _load_many(
        reference_dir / "options.yml",
        "options",
        SubjectReference,
        "subject_id",
    )
    subjects = _merge_subjects(common_subjects, specialties, options)

    return OfficialReferenceIndex(
        sources=_load_many(
            reference_dir / "official_sources.yml",
            "official_sources",
            OfficialSource,
            "source_id",
        ),
        levels=_load_directory(reference_dir / "levels", SchoolLevelReference, "level_id"),
        subjects=subjects,
        exams=_load_directory(reference_dir / "exams", ExamReference, "exam_id"),
        candidate_statuses=_load_many(
            reference_dir / "candidate_statuses.yml",
            "candidate_statuses",
            CandidateStatusReference,
            "status_id",
        ),
        establishment_contexts=_load_many(
            reference_dir / "establishment_contexts.yml",
            "establishment_contexts",
            EstablishmentContextReference,
            "context_id",
        ),
        claims=_load_many(
            reference_dir / "official_claims.yml",
            "official_claims",
            OfficialClaim,
            "claim_id",
        ),
    )
