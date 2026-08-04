"""LOT44d/44e : application de transition — is_valid_resource_transition puis cas_transition.

Périmètre strict : preuve unitaire que la transition structurellement
invalide est rejetée avant tout accès base (aucun appel à ``conn``), et que
``job_id`` (paramètre ajouté par LOT44e) est transmis tel quel — jamais
généré, jamais deviné, et absent par défaut (compatibilité LOT44d). Le cas
nominal (écriture CAS réelle) est couvert par le test d'intégration
Postgres réel (``tests/integration/test_lot44d_chain_wiring.py`` et
``tests/integration/test_lot44e_worker_e2e.py``), pas ici.
"""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from nexus_contracts.resource_state import ResourceState

from ingestor.ingestion_agents import transitions as transitions_module
from ingestor.ingestion_agents.transitions import (
    InvalidTransitionError,
    apply_resource_transition,
)


class _ConnectionMustNotBeUsed:
    """Double qui échoue bruyamment si la moindre méthode est appelée."""

    def __getattr__(self, name: str) -> object:  # pragma: no cover - jamais atteint si le test passe
        raise AssertionError(f"conn.{name} was accessed but should not have been")


class TestStructuralRejectionBeforeDatabaseAccess:
    def test_invalid_transition_raises_before_touching_connection(self) -> None:
        with pytest.raises(InvalidTransitionError):
            apply_resource_transition(
                _ConnectionMustNotBeUsed(),
                resource_id=__import__("uuid").uuid4(),
                expected_state=ResourceState.CANDIDATE,
                expected_version=1,
                new_state=ResourceState.STAGED,
                actor="test-actor",
                run_id=__import__("uuid").uuid4(),
            )

    def test_skip_in_normal_sequence_is_rejected(self) -> None:
        with pytest.raises(InvalidTransitionError):
            apply_resource_transition(
                _ConnectionMustNotBeUsed(),
                resource_id=__import__("uuid").uuid4(),
                expected_state=ResourceState.DISCOVERED,
                expected_version=1,
                new_state=ResourceState.FETCHED,
                actor="test-actor",
                run_id=__import__("uuid").uuid4(),
            )


class TestJobIdPropagation:
    def test_job_id_is_an_optional_parameter_defaulting_to_none(self) -> None:
        signature = inspect.signature(apply_resource_transition)
        assert "job_id" in signature.parameters
        assert signature.parameters["job_id"].default is None

    def test_job_id_omitted_forwards_none_to_cas_transition(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_cas_transition = MagicMock(return_value="sentinel")
        monkeypatch.setattr(transitions_module, "cas_transition", mock_cas_transition)

        apply_resource_transition(
            MagicMock(),
            resource_id=uuid4(),
            expected_state=ResourceState.DISCOVERED,
            expected_version=0,
            new_state=ResourceState.CANDIDATE,
            actor="test-actor",
            run_id=uuid4(),
        )

        assert mock_cas_transition.call_args.kwargs["job_id"] is None

    def test_job_id_supplied_is_forwarded_unchanged_never_fabricated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_cas_transition = MagicMock(return_value="sentinel")
        monkeypatch.setattr(transitions_module, "cas_transition", mock_cas_transition)
        explicit_job_id = uuid4()

        apply_resource_transition(
            MagicMock(),
            resource_id=uuid4(),
            expected_state=ResourceState.DISCOVERED,
            expected_version=0,
            new_state=ResourceState.CANDIDATE,
            actor="test-actor",
            run_id=uuid4(),
            job_id=explicit_job_id,
        )

        assert mock_cas_transition.call_args.kwargs["job_id"] == explicit_job_id
