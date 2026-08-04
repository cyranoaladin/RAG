"""LOT44d : application de transition — is_valid_resource_transition puis cas_transition.

Périmètre strict : preuve unitaire que la transition structurellement
invalide est rejetée avant tout accès base (aucun appel à ``conn``), et que
``job_id`` n'est jamais un paramètre exposé. Le cas nominal (écriture CAS
réelle) est couvert par le test d'intégration Postgres réel
(``tests/integration/test_lot44d_chain_wiring.py``), pas ici.
"""
from __future__ import annotations

import inspect

import pytest
from nexus_contracts.resource_state import ResourceState

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


class TestJobIdIsNeverAParameter:
    def test_apply_resource_transition_signature_has_no_job_id_parameter(self) -> None:
        signature = inspect.signature(apply_resource_transition)
        assert "job_id" not in signature.parameters
