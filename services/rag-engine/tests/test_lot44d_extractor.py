"""LOT44d : Extractor — décodage déterministe de contenu brut en texte.

Périmètre strict : cœur pur testé sans E/S ; ``run_extractor`` testé avec
une doublure de ``read_artifact`` et ``apply_resource_transition``
monkeypatché — aucun PostgreSQL réel, aucun stockage réel.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from nexus_contracts.ingestion import ArtifactRecord
from nexus_contracts.resource_state import ResourceState

from ingestor.ingestion_agents import extractor as extractor_module
from ingestor.ingestion_agents.extractor import (
    UnsupportedMimeTypeError,
    extract_text_core,
    run_extractor,
)
from ingestor.ingestion_agents.transitions import TransitionResult

SCOPE = {
    "tenant": "libre_terminale",
    "collection": "rag_nexus_nsi_terminale_specialite",
    "niveau": "terminale",
    "voie": "generale",
    "matiere": "nsi",
    "candidat": "libre",
    "audience": ["libre", "tous"],
    "visibility": "internal",
    "school_year": "2026-2027",
    "programme_version": "BOEN_special_8_2019-07-25",
}


def _artifact(**overrides: object) -> ArtifactRecord:
    payload: dict[str, object] = {
        "artifact_id": uuid4(),
        "resource_id": uuid4(),
        "run_id": uuid4(),
        "scope": SCOPE,
        "sha256": "a" * 64,
        "size_bytes": 100,
        "mime_declared": "text/html",
        "mime_detected": "text/html",
        "original_url": "https://eduscol.education.fr/nsi/algo",
        "final_url": "https://eduscol.education.fr/nsi/algo",
        "collected_at": datetime(2026, 8, 4, tzinfo=UTC),
        "domain": "eduscol.education.fr",
        "rights_status": "unknown",
        "extracted_text_ref": "mem://artifact-1",
    }
    payload.update(overrides)
    return ArtifactRecord.model_validate(payload)


class TestExtractTextCore:
    def test_html_tags_are_stripped(self) -> None:
        text = extract_text_core(
            artifact=_artifact(mime_detected="text/html"),
            raw_bytes=b"<html><body><p>algorithmique</p></body></html>",
        )
        assert text == "algorithmique"

    def test_plain_text_is_decoded_as_is(self) -> None:
        text = extract_text_core(
            artifact=_artifact(mime_detected="text/plain"),
            raw_bytes=b"algorithmique et structures",
        )
        assert text == "algorithmique et structures"

    def test_latin1_fallback_when_utf8_decoding_fails(self) -> None:
        raw = "café".encode("latin-1")
        text = extract_text_core(artifact=_artifact(mime_detected="text/plain"), raw_bytes=raw)
        assert text == "café"

    def test_unsupported_mime_type_is_rejected(self) -> None:
        with pytest.raises(UnsupportedMimeTypeError):
            extract_text_core(
                artifact=_artifact(mime_detected="application/pdf"),
                raw_bytes=b"%PDF-1.4",
            )

    def test_deterministic_for_identical_input(self) -> None:
        artifact = _artifact(mime_detected="text/html")
        raw = b"<p>algorithmique</p>"
        assert extract_text_core(artifact=artifact, raw_bytes=raw) == extract_text_core(
            artifact=artifact, raw_bytes=raw
        )


class TestRunExtractorWiring:
    def test_reads_stored_content_then_transitions_stored_to_extracted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        artifact = _artifact(mime_detected="text/plain", extracted_text_ref="mem://artifact-1")
        fake_transition = TransitionResult(
            resource_id=artifact.resource_id,
            from_state=ResourceState.STORED,
            to_state=ResourceState.EXTRACTED,
            state_version=4,
        )
        mock_apply = MagicMock(return_value=fake_transition)
        monkeypatch.setattr(extractor_module, "apply_resource_transition", mock_apply)

        read_calls: list[str] = []

        def fake_read_artifact(*, extracted_text_ref: str) -> bytes:
            read_calls.append(extracted_text_ref)
            return b"algorithmique"

        text, transition = run_extractor(
            conn=MagicMock(),
            artifact=artifact,
            expected_version=3,
            actor="extractor-test",
            read_artifact=fake_read_artifact,
        )

        assert read_calls == ["mem://artifact-1"]
        assert text == "algorithmique"
        assert transition is fake_transition
        kwargs = mock_apply.call_args.kwargs
        assert kwargs["expected_state"] == ResourceState.STORED
        assert kwargs["new_state"] == ResourceState.EXTRACTED

    def test_job_id_is_forwarded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        artifact = _artifact(mime_detected="text/plain", extracted_text_ref="mem://artifact-1")
        fake_transition = TransitionResult(
            resource_id=artifact.resource_id, from_state=ResourceState.STORED,
            to_state=ResourceState.EXTRACTED, state_version=4,
        )
        mock_apply = MagicMock(return_value=fake_transition)
        monkeypatch.setattr(extractor_module, "apply_resource_transition", mock_apply)
        job_id = uuid4()

        run_extractor(
            conn=MagicMock(),
            artifact=artifact,
            expected_version=3,
            actor="extractor-test",
            read_artifact=lambda *, extracted_text_ref: b"algorithmique",
            job_id=job_id,
        )

        assert mock_apply.call_args.kwargs["job_id"] == job_id

    def test_missing_extracted_text_ref_raises_before_reading(self) -> None:
        artifact = _artifact(extracted_text_ref=None)

        def must_not_be_called(*, extracted_text_ref: str) -> bytes:
            raise AssertionError("read_artifact must not be called without extracted_text_ref")

        with pytest.raises(ValueError):
            run_extractor(
                conn=MagicMock(),
                artifact=artifact,
                expected_version=3,
                actor="extractor-test",
                read_artifact=must_not_be_called,
            )
