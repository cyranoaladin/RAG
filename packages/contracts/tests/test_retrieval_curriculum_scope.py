from __future__ import annotations

from uuid import UUID

import pytest
from nexus_contracts import (
    Candidat,
    Niveau,
    RetrievalCurriculumScope,
    RetrievalNeed,
    RetrievalRequest,
    RetrievalResult,
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


def test_manifest_binding_is_optional_for_legacy_and_atomic_when_present() -> None:
    legacy = RetrievalRequest(
        student_profile=_student_profile(),
        need=RetrievalNeed(intent="revision", query="Revoir les fonctions"),
    )
    assert legacy.manifest_sha256 is None

    with pytest.raises(ValidationError, match="provided together"):
        RetrievalRequest(
            student_profile=_student_profile(),
            need=RetrievalNeed(intent="revision", query="Revoir les fonctions"),
            manifest_sha256="a" * 64,
        )

    canonical = RetrievalRequest(
        student_profile=_student_profile(),
        need=RetrievalNeed(intent="revision", query="Revoir les fonctions"),
        corpus_id="aria-maths-seconde",
        corpus_version_id="2026-08-30.1",
        manifest_sha256="a" * 64,
    )
    assert canonical.corpus_id == "aria-maths-seconde"

    for incomplete in (
        {"corpus_id": "aria-maths-seconde", "corpus_version_id": "2026-08-30.1"},
        {"corpus_id": "aria-maths-seconde", "manifest_sha256": "a" * 64},
        {"corpus_version_id": "2026-08-30.1", "manifest_sha256": "a" * 64},
    ):
        with pytest.raises(ValidationError, match="provided together"):
            RetrievalRequest(
                student_profile=_student_profile(),
                need=RetrievalNeed(intent="revision", query="Revoir les fonctions"),
                **incomplete,
            )


def test_retrieval_result_canonical_identity_is_complete_or_absent() -> None:
    base = {
        "chunk_id": "chunk-001",
        "doc_id": "legacy-doc",
        "score": 0.9,
        "excerpt": "Contenu de preuve",
    }
    assert RetrievalResult(**base).resource_version_id is None

    identity = {
        "resource_id": UUID("11111111-1111-4111-8111-111111111111"),
        "resource_version_id": UUID("22222222-2222-4222-8222-222222222222"),
        "content_sha256": "a" * 64,
        "locator": {"page": 1},
        "corpus_id": "aria-maths-terminale",
        "corpus_version_id": "2026-08-30.1",
        "manifest_sha256": "b" * 64,
    }
    result = RetrievalResult(**base, **identity)
    assert result.resource_version_id == identity["resource_version_id"]

    del identity["manifest_sha256"]
    with pytest.raises(ValidationError, match="provided together"):
        RetrievalResult(**base, **identity)


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
