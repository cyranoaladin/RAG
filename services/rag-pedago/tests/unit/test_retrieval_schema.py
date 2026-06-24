from __future__ import annotations

from schema.document import Candidat, Niveau, StatutEnseignement, TypeDoc, Voie
from schema.retrieval import RetrievalRequest


def test_retrieval_request_with_profile_filters_passes() -> None:
    request = RetrievalRequest.model_validate(
        {
            "student_profile": {
                "niveau": Niveau.terminale,
                "voie": Voie.generale,
                "matieres": ["mathematiques"],
                "statut_enseignement": StatutEnseignement.specialite,
                "candidat": Candidat.scolarise,
                "school_year": "2026-2027",
                "zone": "aefe_tunisie",
            },
            "need": {
                "intent": "remediation",
                "query": "Je veux réviser les suites récurrentes.",
                "notions": ["suites", "recurrence"],
                "desired_doc_types": [TypeDoc.fiche_methode, TypeDoc.exercice_corrige],
                "difficulty_max": 3,
            },
            "retrieval": {
                "k": 8,
                "hybrid": True,
                "rerank": True,
                "include_citations": True,
            },
        }
    )

    filters = request.to_payload_filters()

    assert filters["niveau"] == "terminale"
    assert filters["matiere"] == "mathematiques"
    assert filters["statut_enseignement"] == "specialite"
    assert filters["candidat"] == "scolarise"

