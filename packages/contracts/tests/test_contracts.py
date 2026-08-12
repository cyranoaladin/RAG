"""Tests for the public nexus-contracts models."""
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
    InternalIdentity,
    Niveau,
    PedagogicalProfile,
    RetrievalNeed,
    RetrievalOptions,
    RetrievalRequest,
    StatutEnseignement,
    StudentProfile,
    TypeDoc,
    Voie,
)
from nexus_contracts.student_profile import StatusDetail


# --- Niveaux canoniques ---


def test_niveau_quatrieme_is_contractual() -> None:
    assert Niveau.quatrieme.value == "quatrieme"
    assert Niveau("quatrieme") is Niveau.quatrieme
    with pytest.raises(ValueError):
        Niveau("4e")


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


def _valid_identity(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "aud": "nexus-cockpit",
        "exp": 4_102_444_800,
        "iss": "nexus-issuer",
        "jti": "jti-12345",
        "tenant": "libre_terminale",
        "niveau": Niveau.terminale,
        "role": "student",
        "school_year": "2026-2027",
        "sub": "psn_1234567890abcdef",
        "pedagogical_profile": {
            "voie": Voie.generale,
            "matieres": ["mathematiques", "nsi"],
            "statut_enseignement": StatutEnseignement.specialite,
            "candidat": Candidat.individuel,
            "audience": "libre",
        },
    }
    base.update(overrides)
    return base


def test_internal_identity_exported_and_validated() -> None:
    identity = InternalIdentity(**_valid_identity())
    assert identity.role == "student"
    assert identity.school_year == "2026-2027"
    assert identity.sub.startswith("psn_")


def test_identity_rejects_contract_0_3_without_school_year() -> None:
    data = _valid_identity()
    del data["school_year"]
    with pytest.raises(ValidationError, match="school_year"):
        InternalIdentity(**data)


@pytest.mark.parametrize("school_year", ["2026-2028", "26-27", "2026/2027"])
def test_identity_requires_contiguous_school_year(school_year: str) -> None:
    with pytest.raises(ValidationError, match="school_year"):
        InternalIdentity(**_valid_identity(school_year=school_year))


def test_identity_rejects_non_pseudonymized_subject() -> None:
    with pytest.raises(ValidationError, match="sub"):
        InternalIdentity(**_valid_identity(sub="eleve@example.org"))


@pytest.mark.parametrize(
    "exp",
    [True, "4102444800", 4_102_444_800.0, 0, 9_007_199_254_740_992],
)
def test_identity_requires_positive_js_safe_strict_integer_exp(exp: object) -> None:
    with pytest.raises(ValidationError, match="exp"):
        InternalIdentity(**_valid_identity(exp=exp))


def test_identity_accepts_largest_js_safe_integer_exp() -> None:
    identity = InternalIdentity(
        **_valid_identity(exp=9_007_199_254_740_991),
    )
    assert identity.exp == 9_007_199_254_740_991


@pytest.mark.parametrize("field", ["aud", "iss", "tenant"])
def test_identity_bounds_identifiers(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        InternalIdentity(**_valid_identity(**{field: "x" * 129}))


def test_identity_rejects_short_jti() -> None:
    with pytest.raises(ValidationError, match="jti"):
        InternalIdentity(**_valid_identity(jti="short"))


def test_identity_rejects_duplicate_matieres() -> None:
    profile = dict(_valid_identity()["pedagogical_profile"])
    profile["matieres"] = ["mathematiques", "mathematiques"]
    with pytest.raises(ValidationError, match="matieres"):
        InternalIdentity(**_valid_identity(pedagogical_profile=profile))


def test_identity_bounds_matieres() -> None:
    profile = dict(_valid_identity()["pedagogical_profile"])
    profile["matieres"] = [f"matiere_{index}" for index in range(17)]
    with pytest.raises(ValidationError, match="matieres"):
        InternalIdentity(**_valid_identity(pedagogical_profile=profile))


@pytest.mark.parametrize(
    ("target", "extra"),
    [
        ("identity", {"email": "eleve@example.org"}),
        ("profile", {"nom": "Élève Exemple"}),
    ],
)
def test_identity_forbids_pii_and_free_fields(
    target: str,
    extra: dict[str, object],
) -> None:
    data = _valid_identity()
    if target == "identity":
        data.update(extra)
    else:
        profile = dict(data["pedagogical_profile"])
        profile.update(extra)
        data["pedagogical_profile"] = profile
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        InternalIdentity(**data)


def test_identity_schema_exposes_closed_bounded_contract() -> None:
    schema = InternalIdentity.model_json_schema()
    assert schema["additionalProperties"] is False
    assert "school_year" in schema["required"]
    assert schema["properties"]["school_year"]["pattern"] == r"^\d{4}-\d{4}$"
    profile = PedagogicalProfile.model_json_schema()
    assert profile["additionalProperties"] is False
    assert set(profile["properties"]) == {
        "voie",
        "matieres",
        "statut_enseignement",
        "candidat",
        "audience",
    }
    assert profile["properties"]["matieres"]["maxItems"] == 16
    assert profile["properties"]["matieres"]["uniqueItems"] is True


@pytest.mark.parametrize(
    "role",
    ["student", "teacher", "admin", "ingest_agent", "reviewer"],
)
def test_identity_accepts_only_authorized_roles(role: str) -> None:
    assert InternalIdentity(**_valid_identity(role=role)).role == role


def test_identity_rejects_unknown_role() -> None:
    with pytest.raises(ValidationError, match="role"):
        InternalIdentity(**_valid_identity(role="super_admin"))


@pytest.mark.parametrize(
    "claim",
    ["sub", "aud", "iss", "exp", "jti", "tenant", "school_year"],
)
def test_identity_requires_security_and_scope_claims(claim: str) -> None:
    data = _valid_identity()
    del data[claim]
    with pytest.raises(ValidationError, match=claim):
        InternalIdentity(**data)


def test_identity_bounds_each_matiere_slug() -> None:
    profile = dict(_valid_identity()["pedagogical_profile"])
    profile["matieres"] = ["m" * 101]
    with pytest.raises(ValidationError, match="matieres"):
        InternalIdentity(**_valid_identity(pedagogical_profile=profile))


def test_identity_rejects_empty_matieres() -> None:
    with pytest.raises(ValueError):
        profile = dict(_valid_identity()["pedagogical_profile"])
        profile["matieres"] = []
        InternalIdentity(**_valid_identity(pedagogical_profile=profile))
