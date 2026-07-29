"""Tests for nexus-contracts 0.2.0: ChunkMetadata, Audience, audience derivation."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from nexus_contracts import (
    Audience,
    ChatCitation,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    Candidat,
    ChunkMetadata,
    Niveau,
    RetrievalNeed,
    RetrievalOptions,
    RetrievalRequest,
    StatutEnseignement,
    StudentProfile,
    TypeDoc,
    Voie,
)
from nexus_contracts.student_profile import StatusDetail
from nexus_contracts import InternalIdentity, PedagogicalProfile


# --- ChunkMetadata ---


def _valid_chunk(**overrides) -> dict:
    base = {
        "tenant": "terminale",
        "niveau": Niveau.terminale,
        "voie": Voie.generale,
        "matiere": "mathematiques",
        "audience": [Audience.tous],
        "type_doc": TypeDoc.cours,
        "notions": ["suites", "limites"],
        "source_label": "Programme officiel Maths Tle",
        "source_uri": "https://eduscol.education.gouv.fr/maths-tle",
        "rights": "officiel_public",
        "official": True,
        "doc_id": "doc-001",
    }
    base.update(overrides)
    return base


def test_chunk_metadata_valid_complete():
    cm = ChunkMetadata(**_valid_chunk(difficulte=3, page=42, chapitre="Suites numériques"))
    assert cm.tenant == "terminale"
    assert cm.audience == [Audience.tous]
    assert cm.difficulte == 3
    assert cm.page == 42


def test_chunk_metadata_valid_minimal():
    cm = ChunkMetadata(**_valid_chunk())
    assert cm.difficulte is None
    assert cm.page is None
    assert cm.chapitre is None


def test_chunk_metadata_rejects_empty_audience():
    with pytest.raises(ValidationError, match="audience"):
        ChunkMetadata(**_valid_chunk(audience=[]))


def test_chunk_metadata_rejects_duplicate_audience():
    with pytest.raises(ValidationError, match="duplicates"):
        ChunkMetadata(**_valid_chunk(audience=[Audience.libre, Audience.libre]))


def test_chunk_metadata_rejects_unknown_type_doc():
    with pytest.raises(ValidationError):
        ChunkMetadata(**_valid_chunk(type_doc="inexistant"))


def test_chunk_metadata_rejects_empty_notion():
    with pytest.raises(ValidationError, match="empty"):
        ChunkMetadata(**_valid_chunk(notions=["suites", ""]))


def test_chunk_metadata_rejects_missing_required():
    data = _valid_chunk()
    del data["doc_id"]
    with pytest.raises(ValidationError):
        ChunkMetadata(**data)


def test_chunk_metadata_new_type_doc_values():
    cm = ChunkMetadata(**_valid_chunk(type_doc=TypeDoc.referentiel))
    assert cm.type_doc == TypeDoc.referentiel
    cm2 = ChunkMetadata(**_valid_chunk(type_doc=TypeDoc.modalite_examen))
    assert cm2.type_doc == TypeDoc.modalite_examen


# --- Audience derivation ---


def _profile(**overrides) -> StudentProfile:
    base = {
        "niveau": Niveau.terminale,
        "voie": Voie.generale,
        "matieres": ["mathematiques"],
        "statut_enseignement": StatutEnseignement.specialite,
        "candidat": Candidat.individuel,
        "school_year": "2025-2026",
        "zone": "france",
    }
    base.update(overrides)
    return StudentProfile(**base)


def test_audience_candidat_libre():
    p = _profile(candidat=Candidat.libre, status_detail=StatusDetail.candidat_libre)
    assert p.audience == "libre"


def test_audience_candidat_individuel():
    p = _profile(candidat=Candidat.individuel)
    assert p.audience == "libre"


def test_audience_cned_libre():
    p = _profile(candidat=Candidat.cned_libre, status_detail=StatusDetail.cned_libre)
    assert p.audience == "libre"


def test_audience_aefe():
    p = _profile(
        candidat=Candidat.aefe,
        status_detail=StatusDetail.aefe,
        zone="aefe_tunis",
    )
    assert p.audience == "aefe"


def test_audience_scolarise_default():
    p = _profile(candidat=Candidat.scolarise, status_detail=StatusDetail.unknown)
    assert p.audience == "aefe"


# --- to_payload_filters includes audience ---


def test_filters_include_audience():
    p = _profile(candidat=Candidat.libre, status_detail=StatusDetail.candidat_libre)
    req = RetrievalRequest(
        student_profile=p,
        need=RetrievalNeed(intent="revision", query="suites numériques"),
        retrieval=RetrievalOptions(),
    )
    filters = req.to_payload_filters()
    assert "audience" in filters
    assert filters["audience"] == "libre"


def test_filters_audience_aefe():
    p = _profile(
        candidat=Candidat.aefe,
        status_detail=StatusDetail.aefe,
        zone="aefe_tunis",
    )
    req = RetrievalRequest(
        student_profile=p,
        need=RetrievalNeed(intent="exercise", query="algèbre linéaire"),
        retrieval=RetrievalOptions(),
    )
    filters = req.to_payload_filters()
    assert filters["audience"] == "aefe"


# --- ChatRequest / ChatResponse ---


def test_chat_request_requires_non_empty_collections() -> None:
    profile = StudentProfile(
        niveau=Niveau.terminale,
        voie=Voie.generale,
        matieres=["maths"],
        statut_enseignement=StatutEnseignement.specialite,
        candidat=Candidat.individuel,
        school_year="2026-2027",
        zone="france",
    )

    with pytest.raises(ValueError):
        ChatRequest(
            student_profile=profile,
            query="définition de limite",
            collections=[],
        )


def test_chat_response_requires_valid_message_shape() -> None:
    msg = ChatMessage(role="user", content="Question courte")
    profile = StudentProfile(
        niveau=Niveau.terminale,
        voie=Voie.generale,
        matieres=["maths"],
        statut_enseignement=StatutEnseignement.specialite,
        candidat=Candidat.individuel,
        school_year="2026-2027",
        zone="france",
    )
    citation = ChatCitation(
        chunk_id="chunk-1",
        doc_id="doc-1",
        source_label="Eduscol",
        source_uri="https://eduscol.education.gouv.fr",
        rights="officiel_public",
        page=12,
    )

    response = ChatResponse(
        answer="Voici une définition.",
        citations=[citation],
        retrieval_hits=[],
    )
    assert response.warnings == []
    assert response.grounded

    request = ChatRequest(
        student_profile=profile,
        query="Décris cette notion.",
        collections=["rag_nexus_nsi_terminale_specialite"],
        history=[msg],
    )
    assert request.history == [msg]
    assert request.include_retrieval


def test_chat_response_rejects_uncited_grounded_answer() -> None:
    """A conversational answer may never claim grounding without a source."""
    with pytest.raises(ValidationError, match="citations"):
        ChatResponse(
            answer="Réponse prétendument sourcée.",
            grounded=True,
            citations=[],
            retrieval_hits=[],
        )


def test_chat_response_requires_reason_for_refusal() -> None:
    with pytest.raises(ValidationError, match="refusal_reason"):
        ChatResponse(
            answer="Je ne peux pas répondre de manière fiable.",
            grounded=False,
            citations=[],
            retrieval_hits=[],
        )


# --- Identity ---


def test_internal_identity_exported_and_validated() -> None:
    identity = InternalIdentity(
        aud="nexus-cockpit",
        exp=4102444800,
        iss="nexus-issuer",
        jti="jti-123",
        tenant="tenant-1",
        niveau=Niveau.terminale,
        role="student",
        sub="student-001",
        pedagogical_profile=PedagogicalProfile(
            voie=Voie.generale,
            matieres=["maths"],
            statut_enseignement=StatutEnseignement.specialite,
            candidat=Candidat.individuel,
            audience="libre",
        ),
    )
    assert identity.role == "student"


def test_identity_rejects_empty_matieres() -> None:
    with pytest.raises(ValueError):
        InternalIdentity(
            aud="nexus-cockpit",
            exp=4102444800,
            iss="nexus-issuer",
            jti="jti-123",
            tenant="tenant-1",
            niveau=Niveau.terminale,
            role="student",
            sub="student-001",
            pedagogical_profile=PedagogicalProfile(
                voie=Voie.generale,
                matieres=[],
                statut_enseignement=StatutEnseignement.specialite,
                candidat=Candidat.individuel,
                audience="libre",
            ),
        )
