"""Tests for query agents — context_only, filtering by API, governance gate.

Tests with mocked API responses (unit tests).
Real execution proofs are in the lot report.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _mock_api_response(
    niveau: str = "terminale",
    audience: str = "libre",
    chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a mock API response."""
    if chunks is None:
        chunks = [
            {
                "chunk_id": f"{niveau}_mathematiques_derivation#0",
                "doc_id": f"{niveau}_mathematiques_derivation",
                "niveau": niveau,
                "matiere": "mathematiques",
                "notions": ["derivation"],
                "similarity": 0.875,
                "preview": "La dérivée d'une fonction...",
            }
        ]
    return {
        "results": chunks,
        "profile_niveau": niveau,
        "profile_audience": audience,
        "count": len(chunks),
    }


class TestQueryOrchestratorContextOnly:
    """Verify the orchestrator produces context_only output."""

    @patch("query_agents.query_subject_agent.requests.post")
    def test_returns_context_only_mode(self, mock_post) -> None:
        from query_agents.query_orchestrator import query_orchestrator

        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: _mock_api_response(),
        )
        mock_post.return_value.raise_for_status = MagicMock()

        result = query_orchestrator(
            question="dérivée",
            niveau="terminale",
            audience="libre",
            matiere="mathematiques",
            profile_secret="test-secret",
        )

        assert result["mode"] == "context_only"
        assert result["answer_generation_allowed"] is False
        assert "passages" in result
        assert len(result["passages"]) > 0
        assert result["count"] > 0

    @patch("query_agents.query_subject_agent.requests.post")
    def test_no_prose_in_output(self, mock_post) -> None:
        """The output must contain passages+metadata, never generated text."""
        from query_agents.query_orchestrator import query_orchestrator

        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: _mock_api_response(),
        )
        mock_post.return_value.raise_for_status = MagicMock()

        result = query_orchestrator(
            question="dérivée",
            niveau="terminale",
            audience="libre",
            matiere="mathematiques",
            profile_secret="test-secret",
        )

        # Output is structured context, not prose
        for passage in result["passages"]:
            assert "chunk_id" in passage
            assert "doc_id" in passage
            assert "matiere" in passage
            assert "notions" in passage
            assert "similarity" in passage
            assert "text" in passage
        # No "answer" or "response" key
        assert "answer" not in result
        assert "response" not in result
        assert "generated_text" not in result


class TestQueryOrchestratorGovernance:
    """Verify answer_generation_allowed gate is enforced."""

    def test_answer_generation_blocked_in_contract(self) -> None:
        """The real contract has answer_generation_allowed=false."""
        contract = yaml.safe_load(
            (ROOT / "configs/pedago_interface_contract.yml").read_text()
        )
        assert contract["answer_generation_allowed"] is False

    def test_answer_without_source_blocked(self) -> None:
        """citation_policy.answer_without_source_allowed is false."""
        contract = yaml.safe_load(
            (ROOT / "configs/pedago_interface_contract.yml").read_text()
        )
        assert contract["citation_policy"]["answer_without_source_allowed"] is False

    @patch("query_agents.query_subject_agent.requests.post")
    def test_blocked_reason_in_output(self, mock_post) -> None:
        from query_agents.query_orchestrator import query_orchestrator

        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: _mock_api_response(),
        )
        mock_post.return_value.raise_for_status = MagicMock()

        result = query_orchestrator(
            question="test",
            niveau="terminale",
            audience="libre",
            matiere="mathematiques",
            profile_secret="test-secret",
        )

        assert result["answer_generation_blocked_reason"] is not None
        assert "false" in result["answer_generation_blocked_reason"]


class TestQuerySubjectAgent:
    """Verify the subject agent assembles context correctly."""

    @patch("query_agents.query_subject_agent.requests.post")
    def test_assemble_context_structure(self, mock_post) -> None:
        from query_agents.query_subject_agent import query_subject

        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: _mock_api_response(),
        )
        mock_post.return_value.raise_for_status = MagicMock()

        result = query_subject(
            matiere="mathematiques",
            question="dérivée",
            token="fake-token",
        )

        assert result["mode"] == "context_only"
        assert result["matiere"] == "mathematiques"
        assert result["question"] == "dérivée"
        assert len(result["passages"]) == 1
        assert result["passages"][0]["matiere"] == "mathematiques"

    @patch("query_agents.query_subject_agent.requests.post")
    def test_api_called_with_bearer_token(self, mock_post) -> None:
        """The agent passes the token through in Authorization header."""
        from query_agents.query_subject_agent import query_subject

        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: _mock_api_response(),
        )
        mock_post.return_value.raise_for_status = MagicMock()

        query_subject(
            matiere="mathematiques",
            question="test",
            token="my-signed-token",
        )

        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers["Authorization"] == "Bearer my-signed-token"


class TestQueryLevelAgent:
    """Verify the level agent routes correctly."""

    @patch("query_agents.query_subject_agent.requests.post")
    def test_routes_to_subject(self, mock_post) -> None:
        from query_agents.query_level_agent import query_level

        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: _mock_api_response(niveau="premiere"),
        )
        mock_post.return_value.raise_for_status = MagicMock()

        result = query_level(
            niveau="premiere",
            matiere="mathematiques",
            question="dérivée",
            token="fake-token",
        )

        assert result["routed_niveau"] == "premiere"
        assert result["mode"] == "context_only"


class TestFilteringByApi:
    """Verify filtering is imposed by the API, not reimplemented in agents."""

    @patch("query_agents.query_subject_agent.requests.post")
    def test_premiere_gets_only_premiere_chunks(self, mock_post) -> None:
        from query_agents.query_orchestrator import query_orchestrator

        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: _mock_api_response(niveau="premiere", chunks=[
                {
                    "chunk_id": "premiere_maths#0",
                    "doc_id": "premiere_maths",
                    "niveau": "premiere",
                    "matiere": "mathematiques",
                    "notions": ["derivation"],
                    "similarity": 0.85,
                    "preview": "Première...",
                }
            ]),
        )
        mock_post.return_value.raise_for_status = MagicMock()

        result = query_orchestrator(
            question="dérivée",
            niveau="premiere",
            audience="libre",
            matiere="mathematiques",
            profile_secret="test-secret",
        )

        for passage in result["passages"]:
            assert passage["niveau"] == "premiere", (
                f"Got non-premiere chunk: {passage}"
            )

    @patch("query_agents.query_subject_agent.requests.post")
    def test_agent_does_not_reimplement_filtering(self, mock_post) -> None:
        """Agent doesn't filter — it passes API results through.
        If the API returns terminale chunks (bug), agent would too.
        Filtering responsibility is the API's, not the agent's."""
        from query_agents.query_subject_agent import assemble_context

        api_response = _mock_api_response(niveau="terminale")
        context = assemble_context(api_response)
        # All API results pass through — no agent-side filtering
        assert len(context["passages"]) == len(api_response["results"])


class TestNoSecretError:
    """Verify graceful handling when PROFILE_SECRET is missing."""

    def test_orchestrator_returns_error_without_secret(self) -> None:
        from query_agents.query_orchestrator import query_orchestrator

        result = query_orchestrator(
            question="test",
            niveau="terminale",
            audience="libre",
            matiere="mathematiques",
            profile_secret="",
        )
        assert result["mode"] == "error"
        assert "PROFILE_SECRET" in result["error"]
