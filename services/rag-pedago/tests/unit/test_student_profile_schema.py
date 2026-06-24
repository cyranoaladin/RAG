from __future__ import annotations

from schema.document import Candidat, Niveau, StatutEnseignement, Voie
from schema.student_profile import StatusDetail, StudentProfile


def test_terminale_maths_specialite_scolarise_profile_passes() -> None:
    profile = StudentProfile.model_validate(
        {
            "niveau": Niveau.terminale,
            "voie": Voie.generale,
            "matieres": ["mathematiques"],
            "statut_enseignement": StatutEnseignement.specialite,
            "candidat": Candidat.scolarise,
            "school_year": "2026-2027",
            "zone": "aefe_tunisie",
        }
    )

    assert profile.primary_matiere == "mathematiques"


def test_candidat_individuel_profile_passes() -> None:
    profile = StudentProfile.model_validate(
        {
            "niveau": Niveau.terminale,
            "voie": Voie.generale,
            "matieres": ["nsi"],
            "statut_enseignement": StatutEnseignement.specialite,
            "candidat": Candidat.individuel,
            "school_year": "2026-2027",
            "zone": "metropole",
        }
    )

    assert profile.candidat is Candidat.individuel


def test_aefe_scolarise_profile_passes() -> None:
    profile = StudentProfile.model_validate(
        {
            "student_id": "student-001",
            "niveau": Niveau.terminale,
            "voie": Voie.generale,
            "matieres": ["mathematiques"],
            "statut_enseignement": StatutEnseignement.specialite,
            "candidat": Candidat.scolarise,
            "status_detail": StatusDetail.aefe,
            "school_year": "2026-2027",
            "zone": "aefe_tunisie",
            "establishment": "Lycee francais de Tunis",
            "specialites": ["mathematiques", "nsi"],
            "nexus_offer": "premium",
            "nexus_group_id": "term-maths-aefe-01",
            "teacher_confirmed": True,
            "school_calendar_zone": "centres_etrangers_groupe_1b",
        }
    )

    assert profile.status_detail is StatusDetail.aefe
    assert profile.warning_codes == []


def test_candidat_libre_extended_profile_passes() -> None:
    profile = StudentProfile.model_validate(
        {
            "niveau": Niveau.terminale,
            "voie": Voie.generale,
            "matieres": ["nsi"],
            "statut_enseignement": StatutEnseignement.specialite,
            "candidat": Candidat.individuel,
            "status_detail": StatusDetail.candidat_libre,
            "school_year": "2026-2027",
            "zone": "metropole",
            "objective": "preparer_bac",
            "needs": ["annales", "cours_autoportants"],
        }
    )

    assert profile.status_detail is StatusDetail.candidat_libre


def test_double_cursus_profile_passes() -> None:
    profile = StudentProfile.model_validate(
        {
            "niveau": Niveau.premiere,
            "voie": Voie.generale,
            "matieres": ["mathematiques", "francais"],
            "statut_enseignement": StatutEnseignement.specialite,
            "candidat": Candidat.scolarise,
            "status_detail": StatusDetail.double_cursus,
            "school_year": "2026-2027",
            "zone": "tunisie",
            "target_pathway": "bac_general",
        }
    )

    assert profile.status_detail is StatusDetail.double_cursus


def test_terminale_maths_specialite_with_maths_expertes_passes() -> None:
    profile = StudentProfile.model_validate(
        {
            "niveau": Niveau.terminale,
            "voie": Voie.generale,
            "matieres": ["mathematiques"],
            "statut_enseignement": StatutEnseignement.specialite,
            "candidat": Candidat.scolarise,
            "school_year": "2026-2027",
            "zone": "metropole",
            "specialites": ["mathematiques", "physique_chimie"],
            "options": ["maths_expertes"],
        }
    )

    assert profile.warning_codes == []


def test_incoherent_profile_produces_warning() -> None:
    profile = StudentProfile.model_validate(
        {
            "niveau": Niveau.terminale,
            "voie": Voie.generale,
            "matieres": ["nsi"],
            "statut_enseignement": StatutEnseignement.specialite,
            "candidat": Candidat.scolarise,
            "school_year": "2026-2027",
            "zone": "metropole",
            "specialites": ["nsi", "physique_chimie"],
            "options": ["maths_expertes"],
        }
    )

    assert "maths_expertes_without_maths_specialite" in profile.warning_codes
