from __future__ import annotations

from schema.document import Candidat, Niveau
from schema.exam_profile import ExamProfile, ModalitePonctuelle


def test_candidat_libre_terminale_without_two_specialities_warns() -> None:
    profile = ExamProfile.model_validate(
        {
            "niveau": Niveau.terminale,
            "session": 2026,
            "school_year": "2025-2026",
            "candidat": Candidat.individuel,
            "zone": "aefe_tunisie",
            "modalite_ponctuelles": ModalitePonctuelle.unknown,
            "specialites_terminale": ["mathematiques"],
        }
    )

    assert "terminale_generale_less_than_two_eds" in profile.warning_codes
    assert "candidat_libre_modalite_ponctuelle_unknown" in profile.warning_codes


def test_premiere_generale_without_three_specialities_warns() -> None:
    profile = ExamProfile.model_validate(
        {
            "niveau": Niveau.premiere,
            "session": 2026,
            "school_year": "2025-2026",
            "candidat": Candidat.scolarise,
            "zone": "metropole",
            "specialites_premiere": ["mathematiques", "nsi"],
        }
    )

    assert "premiere_generale_less_than_three_eds" in profile.warning_codes


def test_maths_options_incoherences_warn_strongly() -> None:
    profile = ExamProfile.model_validate(
        {
            "niveau": Niveau.terminale,
            "session": 2026,
            "school_year": "2025-2026",
            "candidat": Candidat.scolarise,
            "zone": "metropole",
            "specialites_terminale": ["nsi", "physique_chimie"],
            "options": ["maths_expertes", "maths_complementaires"],
        }
    )

    assert "maths_expertes_without_maths_specialite" in profile.warning_codes
    assert "maths_complementaires_with_maths_specialite_kept" not in profile.warning_codes

