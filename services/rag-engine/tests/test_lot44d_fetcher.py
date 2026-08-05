"""LOT44d : Fetcher — téléchargement et persistance déterministes d'ArtifactRecord.

Périmètre strict : aucun réseau réel (``safe_fetch`` toujours une doublure),
aucun stockage réel (``store_artifact`` toujours une doublure), aucun
PostgreSQL réel (``apply_resource_transition`` monkeypatché).
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest
from nexus_contracts.document import Rights
from nexus_contracts.ingestion import ResourceCandidate
from nexus_contracts.resource_state import ResourceState

from ingestor.ingestion_agents import fetcher as fetcher_module
from ingestor.ingestion_agents.fetcher import build_artifact_core, run_fetcher
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


def _candidate(**overrides: object) -> ResourceCandidate:
    payload: dict[str, object] = {
        "candidate_id": uuid4(),
        "resource_id": uuid4(),
        "run_id": uuid4(),
        "scope": SCOPE,
        "discovered_at": datetime(2026, 8, 4, tzinfo=UTC),
        "source_url": "https://eduscol.education.fr/nsi/algo",
        "canonical_url": "https://eduscol.education.fr/nsi/algo",
        "domain": "eduscol.education.fr",
        "proposed_type_doc": "cours",
        "dedup_key": "a" * 64,
    }
    payload.update(overrides)
    return ResourceCandidate.model_validate(payload)


class TestBuildArtifactCore:
    def test_rights_status_is_always_unknown_at_fetch_time(self) -> None:
        artifact = build_artifact_core(
            candidate=_candidate(),
            artifact_id=uuid4(),
            sha256="b" * 64,
            size_bytes=1024,
            mime_declared="text/html",
            mime_detected="text/html",
            final_url="https://eduscol.education.fr/nsi/algo",
            collected_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
        assert artifact.rights_status == Rights.unknown

    def test_domain_and_original_url_come_from_candidate(self) -> None:
        candidate = _candidate()
        artifact = build_artifact_core(
            candidate=candidate,
            artifact_id=uuid4(),
            sha256="b" * 64,
            size_bytes=1024,
            mime_declared="text/html",
            mime_detected="text/html",
            final_url="https://eduscol.education.fr/nsi/algo",
            collected_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
        assert artifact.domain == candidate.domain
        assert artifact.original_url == candidate.source_url


class TestRunFetcherWiring:
    def test_two_distinct_transitions_are_applied_in_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        candidate = _candidate()
        artifact_id = uuid4()

        fake_response = httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"<html>algorithmique</html>",
            request=httpx.Request("GET", candidate.source_url),
        )
        fake_safe_fetch = MagicMock(return_value=fake_response)

        fetched_result = TransitionResult(
            resource_id=candidate.resource_id,
            from_state=ResourceState.CANDIDATE,
            to_state=ResourceState.FETCHED,
            state_version=2,
        )
        stored_result = TransitionResult(
            resource_id=candidate.resource_id,
            from_state=ResourceState.FETCHED,
            to_state=ResourceState.STORED,
            state_version=3,
        )
        mock_apply = MagicMock(side_effect=[fetched_result, stored_result])
        monkeypatch.setattr(fetcher_module, "apply_resource_transition", mock_apply)

        store_calls: list[bytes] = []

        def fake_store_artifact(*, artifact_id: object, content: bytes) -> str:
            store_calls.append(content)
            return f"mem://{artifact_id}"

        artifact, fetched, stored = run_fetcher(
            conn=MagicMock(),
            candidate=candidate,
            artifact_id=artifact_id,
            collected_at=datetime(2026, 8, 4, tzinfo=UTC),
            expected_version=1,
            actor="fetcher-test",
            max_bytes=1_000_000,
            store_artifact=fake_store_artifact,
            safe_fetch=fake_safe_fetch,
        )

        assert fetched is fetched_result
        assert stored is stored_result
        assert mock_apply.call_count == 2
        first_call_kwargs = mock_apply.call_args_list[0].kwargs
        second_call_kwargs = mock_apply.call_args_list[1].kwargs
        assert first_call_kwargs["expected_state"] == ResourceState.CANDIDATE
        assert first_call_kwargs["new_state"] == ResourceState.FETCHED
        assert second_call_kwargs["expected_state"] == ResourceState.FETCHED
        assert second_call_kwargs["new_state"] == ResourceState.STORED
        assert second_call_kwargs["expected_version"] == fetched_result.state_version
        assert store_calls == [b"<html>algorithmique</html>"]
        assert artifact.extracted_text_ref == f"mem://{artifact_id}"
        assert artifact.sha256 == __import__("hashlib").sha256(b"<html>algorithmique</html>").hexdigest()

    def test_store_artifact_is_called_only_after_fetched_transition(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        candidate = _candidate()
        call_order: list[str] = []

        fake_response = httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"contenu",
            request=httpx.Request("GET", candidate.source_url),
        )

        def recording_apply(*args: object, **kwargs: object) -> TransitionResult:
            call_order.append("transition")
            state = kwargs["new_state"]
            return TransitionResult(
                resource_id=candidate.resource_id,
                from_state=kwargs["expected_state"],
                to_state=state,
                state_version=kwargs["expected_version"] + 1,
            )

        def recording_store(*, artifact_id: object, content: bytes) -> str:
            call_order.append("store")
            return "mem://x"

        monkeypatch.setattr(fetcher_module, "apply_resource_transition", recording_apply)

        run_fetcher(
            conn=MagicMock(),
            candidate=candidate,
            artifact_id=uuid4(),
            collected_at=datetime(2026, 8, 4, tzinfo=UTC),
            expected_version=1,
            actor="fetcher-test",
            max_bytes=1_000_000,
            store_artifact=recording_store,
            safe_fetch=lambda url, **kwargs: fake_response,
        )

        assert call_order == ["transition", "store", "transition"]

    def test_job_id_is_forwarded_to_both_transitions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        candidate = _candidate()
        job_id = uuid4()
        seen_job_ids: list[object] = []

        fake_response = httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"contenu",
            request=httpx.Request("GET", candidate.source_url),
        )

        def recording_apply(*args: object, **kwargs: object) -> TransitionResult:
            seen_job_ids.append(kwargs["job_id"])
            return TransitionResult(
                resource_id=candidate.resource_id,
                from_state=kwargs["expected_state"],
                to_state=kwargs["new_state"],
                state_version=kwargs["expected_version"] + 1,
            )

        monkeypatch.setattr(fetcher_module, "apply_resource_transition", recording_apply)

        run_fetcher(
            conn=MagicMock(),
            candidate=candidate,
            artifact_id=uuid4(),
            collected_at=datetime(2026, 8, 4, tzinfo=UTC),
            expected_version=1,
            actor="fetcher-test",
            max_bytes=1_000_000,
            store_artifact=lambda *, artifact_id, content: "mem://x",
            safe_fetch=lambda url, **kwargs: fake_response,
            job_id=job_id,
        )

        assert seen_job_ids == [job_id, job_id]
