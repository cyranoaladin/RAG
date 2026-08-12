from __future__ import annotations

import pytest
from nexus_contracts import (
    Candidat,
    Niveau,
    RetrievalCurriculumScope,
    RetrievalNeed,
    RetrievalRequest,
    StatutEnseignement,
    StudentProfile,
    Voie,
)
from pydantic import ValidationError


def _student_profile() -> StudentProfile:
    return StudentProfile(
        niveau=Niveau.seconde,
        voie=Voie.generale,
        matieres=["maths"],
        statut_enseignement=StatutEnseignement.tronc_commun,
        candidat=Candidat.libre,
        school_year="2026-2027",
        zone="libre",
    )


def test_curriculum_scope_separates_student_target_from_evidence_filters() -> None:
    request = RetrievalRequest(
        student_profile=_student_profile(),
        curriculum_scope=RetrievalCurriculumScope(
            niveau=Niveau.troisieme,
            voie=Voie.college,
            matiere="maths",
            statut_enseignement=StatutEnseignement.tronc_commun,
        ),
        need=RetrievalNeed(intent="remediation", query="Revoir les fonctions"),
    )

    assert request.student_profile.niveau is Niveau.seconde
    assert request.to_payload_filters() == {
        "niveau": "troisieme",
        "voie": "college",
        "matiere": "maths",
        "statut_enseignement": "tronc_commun",
        "candidat": "libre",
        "audience": "libre",
    }


def test_legacy_request_without_curriculum_scope_keeps_v1_filters() -> None:
    request = RetrievalRequest(
        student_profile=_student_profile(),
        need=RetrievalNeed(intent="revision", query="Revoir les fonctions"),
    )

    assert request.curriculum_scope is None
    assert request.to_payload_filters()["niveau"] == "seconde"
    assert request.to_payload_filters()["voie"] == "generale"


def test_curriculum_scope_is_closed_and_requires_a_non_blank_subject() -> None:
    with pytest.raises(ValidationError):
        RetrievalCurriculumScope.model_validate(
            {
                "niveau": "troisieme",
                "voie": "college",
                "matiere": "maths",
                "statut_enseignement": "tronc_commun",
                "collection": "rag_nexus_maths_troisieme_tc",
            }
        )

    with pytest.raises(ValidationError):
        RetrievalCurriculumScope(
            niveau=Niveau.troisieme,
            voie=Voie.college,
            matiere="   ",
            statut_enseignement=StatutEnseignement.tronc_commun,
        )
