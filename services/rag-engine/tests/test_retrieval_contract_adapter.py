from __future__ import annotations

import pytest
from nexus_contracts.document import Candidat, Niveau, StatutEnseignement, TypeDoc, Voie
from nexus_contracts.retrieval import RetrievalNeed, RetrievalOptions, RetrievalRequest
from nexus_contracts.student_profile import StatusDetail, StudentProfile

from src.ingestor.retrieval_contract_adapter import (
    adapt_legacy_search_payload,
    adapt_retrieval_request,
    build_citation_payload,
)


def test_legacy_search_collection_is_mapped_to_nexus_domain() -> None:
    adapted = adapt_legacy_search_payload(
        {
            "q": "smart contract",
            "k": 7,
            "collection": "rag_web3",
            "filters": {"categorie": "Solana"},
        }
    )

    assert adapted.query == "smart contract"
    assert adapted.top_k == 7
    assert adapted.nexus_collection == "rag_nexus_web3"
    assert adapted.physical_collection == "rag_web3"
    assert adapted.domain == "web3"
    assert adapted.filters["domain"] == "web3"
    assert adapted.filters["categorie"] == "Solana"


def test_legacy_search_rejects_unknown_collection_override() -> None:
    with pytest.raises(ValueError, match="collection"):
        adapt_legacy_search_payload({"q": "test", "collection": "anything"})


def test_retrieval_request_is_adapted_without_client_collection_override() -> None:
    profile = StudentProfile(
        status_detail=StatusDetail.aefe,
        niveau=Niveau.premiere,
        voie=Voie.generale,
        matieres=["Mathématiques"],
        statut_enseignement=StatutEnseignement.specialite,
        candidat=Candidat.scolarise,
        school_year="2026-2027",
        zone="aefe_tunis",
    )
    request = RetrievalRequest(
        student_profile=profile,
        need=RetrievalNeed(
            intent="revision",
            query="limites de suites",
            notions=["suites"],
            desired_doc_types=[TypeDoc.cours],
        ),
        retrieval=RetrievalOptions(k=5, include_citations=True),
    )

    adapted = adapt_retrieval_request(request)

    assert adapted.query == "limites de suites"
    assert adapted.top_k == 5
    assert adapted.nexus_collection == "rag_nexus_education"
    assert adapted.physical_collection == "rag_nexus_education"
    assert adapted.filters["niveau"] == "premiere"
    assert adapted.filters["audience"] == "aefe"
    assert adapted.filters["type_doc"] == "cours"


def test_citation_payload_uses_required_contract_fields() -> None:
    citation = build_citation_payload(
        {
            "source_label": "BO specialite mathematiques",
            "source_uri": "https://example.test/bo",
            "rights": "officiel_public",
            "page": 3,
        }
    )

    assert citation == {
        "source_label": "BO specialite mathematiques",
        "source_uri": "https://example.test/bo",
        "rights": "officiel_public",
        "page": 3,
    }
