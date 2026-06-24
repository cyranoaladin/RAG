from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from schema.document import (
    Candidat,
    ChunkMeta,
    DocumentMeta,
    Epreuve,
    Modality,
    Niveau,
    Rights,
    SourceType,
    StatutEnseignement,
    TypeDoc,
    Voie,
)


def valid_document_payload() -> dict[str, object]:
    return {
        "doc_id": "doc-maths-ts-001",
        "source_uri": "file:///data/raw/nexus/math-ts/suites.pdf",
        "source_type": SourceType.nexus,
        "sha256": "a" * 64,
        "discovered_at": datetime(2026, 6, 13, tzinfo=timezone.utc),
        "rights": Rights.nexus_proprietaire,
        "visibility": "internal",
        "niveau": Niveau.terminale,
        "voie": Voie.generale,
        "matiere": "mathematiques",
        "statut_enseignement": StatutEnseignement.specialite,
        "type_doc": TypeDoc.fiche_methode,
        "epreuve": Epreuve.bac_specialite_ecrit,
        "candidat": Candidat.scolarise,
        "session": 2026,
        "school_year_start": 2026,
        "school_year_end": 2027,
        "programme_version": "terminale-specialite-2020",
        "bo_reference": "BO special n4 du 29 avril 2010",
        "notions": ["suites", "recurrence"],
        "competences": ["raisonner", "calculer"],
        "difficulty": 3,
    }


def test_valid_document_meta_passes() -> None:
    meta = DocumentMeta.model_validate(valid_document_payload())

    assert meta.doc_id == "doc-maths-ts-001"
    assert meta.rights is Rights.nexus_proprietaire
    assert meta.notions == ["suites", "recurrence"]
    assert meta.is_retrievable is True


def test_document_without_rights_fails() -> None:
    payload = valid_document_payload()
    payload.pop("rights")

    with pytest.raises(ValidationError):
        DocumentMeta.model_validate(payload)


def test_document_with_invalid_difficulty_fails() -> None:
    payload = valid_document_payload()
    payload["difficulty"] = 7

    with pytest.raises(ValidationError):
        DocumentMeta.model_validate(payload)


def test_document_with_unknown_rights_is_not_retrievable() -> None:
    payload = valid_document_payload()
    payload["rights"] = Rights.unknown

    meta = DocumentMeta.model_validate(payload)

    assert meta.is_retrievable is False


def test_valid_chunk_meta_passes() -> None:
    chunk = ChunkMeta.model_validate(
        {
            "chunk_id": "chunk-001",
            "doc_id": "doc-maths-ts-001",
            "chunk_sha256": "b" * 64,
            "chunk_index": 0,
            "text": "Méthode pour étudier une suite définie par récurrence.",
            "page_start": 2,
            "page_end": 3,
            "chunk_type": Modality.text,
            "notions": ["suites", "recurrence"],
            "competences": ["raisonner"],
            "citation_label": "Suites, p. 2-3",
        }
    )

    assert chunk.doc_id == "doc-maths-ts-001"
    assert chunk.char_count == len(chunk.text or "")


def test_chunk_without_doc_id_fails() -> None:
    payload = {
        "chunk_id": "chunk-001",
        "chunk_sha256": "b" * 64,
        "chunk_index": 0,
        "text": "Un chunk sans document parent est invalide.",
        "chunk_type": Modality.text,
    }

    with pytest.raises(ValidationError):
        ChunkMeta.model_validate(payload)

