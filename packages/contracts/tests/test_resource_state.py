"""Tests de la machine d'état des ressources du moteur d'ingestion (LOT44a).

PUBLISHED est explicitement absent de cette machine d'état : la publication
produit est hors périmètre de LOT44a et l'auto-publication n'est pas
implémentée. Toute mention future de « PUBLISHED » appartiendra à un
sous-système de publication distinct, jamais à ce module.
"""
from __future__ import annotations

import pytest

from nexus_contracts.resource_state import (
    NORMAL_SEQUENCE,
    ResourceState,
    is_valid_resource_transition,
)


def test_resource_state_enumerates_exactly_the_expected_twenty_values() -> None:
    expected = {
        "DISCOVERED", "CANDIDATE", "FETCHED", "STORED", "EXTRACTED",
        "CLASSIFIED", "RIGHTS_CHECKED", "QUALITY_CHECKED", "ROUTED", "STAGED",
        "NEEDS_REVIEW", "REVIEWED", "RETRIEVAL_ELIGIBLE",
        "FAILED", "DEAD_LETTER", "CANCELLED", "REJECTED", "QUARANTINED",
        "DUPLICATE", "SUPERSEDED",
    }
    assert {member.value for member in ResourceState} == expected


def test_published_is_not_a_member_of_resource_state() -> None:
    """PUBLISHED n'existe pas dans ce moteur — appartient à un futur
    sous-système de publication produit, hors périmètre LOT44a."""
    assert "PUBLISHED" not in {member.value for member in ResourceState}
    with pytest.raises(ValueError):
        ResourceState("PUBLISHED")


def test_candidate_and_staged_are_distinct_non_adjacent_states() -> None:
    assert ResourceState.CANDIDATE != ResourceState.STAGED
    candidate_index = NORMAL_SEQUENCE.index(ResourceState.CANDIDATE)
    staged_index = NORMAL_SEQUENCE.index(ResourceState.STAGED)
    assert staged_index - candidate_index > 1, (
        "au moins un état intermédiaire doit séparer CANDIDATE de STAGED"
    )


def test_candidate_to_staged_direct_transition_is_forbidden() -> None:
    """Aucun raccourci CANDIDATE -> STAGED ne doit être représentable."""
    assert is_valid_resource_transition(
        ResourceState.CANDIDATE, ResourceState.STAGED
    ) is False


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        (a, b)
        for a, b in zip(NORMAL_SEQUENCE, NORMAL_SEQUENCE[1:])
    ],
)
def test_normal_sequence_single_step_transitions_are_valid(
    from_state: ResourceState, to_state: ResourceState
) -> None:
    assert is_valid_resource_transition(from_state, to_state) is True


def test_normal_sequence_cannot_be_skipped_forward() -> None:
    for skip in (2, 3, 4):
        for index in range(len(NORMAL_SEQUENCE) - skip):
            from_state = NORMAL_SEQUENCE[index]
            to_state = NORMAL_SEQUENCE[index + skip]
            assert is_valid_resource_transition(from_state, to_state) is False, (
                f"{from_state} -> {to_state} devrait être interdit (saut de {skip})"
            )


def test_normal_sequence_cannot_go_backward() -> None:
    for index in range(1, len(NORMAL_SEQUENCE)):
        from_state = NORMAL_SEQUENCE[index]
        to_state = NORMAL_SEQUENCE[index - 1]
        assert is_valid_resource_transition(from_state, to_state) is False


@pytest.mark.parametrize(
    "from_state",
    [state for state in NORMAL_SEQUENCE if state != ResourceState.RETRIEVAL_ELIGIBLE],
)
@pytest.mark.parametrize(
    "to_state",
    [ResourceState.FAILED, ResourceState.REJECTED, ResourceState.QUARANTINED, ResourceState.CANCELLED],
)
def test_active_states_can_always_fail_reject_quarantine_or_cancel(
    from_state: ResourceState, to_state: ResourceState
) -> None:
    assert is_valid_resource_transition(from_state, to_state) is True


def test_duplicate_only_reachable_once_an_artifact_has_been_fetched() -> None:
    assert is_valid_resource_transition(ResourceState.DISCOVERED, ResourceState.DUPLICATE) is False
    assert is_valid_resource_transition(ResourceState.CANDIDATE, ResourceState.DUPLICATE) is False
    assert is_valid_resource_transition(ResourceState.FETCHED, ResourceState.DUPLICATE) is True
    assert is_valid_resource_transition(ResourceState.ROUTED, ResourceState.DUPLICATE) is True


def test_superseded_only_reachable_from_staged_onward() -> None:
    assert is_valid_resource_transition(ResourceState.CLASSIFIED, ResourceState.SUPERSEDED) is False
    assert is_valid_resource_transition(ResourceState.STAGED, ResourceState.SUPERSEDED) is True
    assert is_valid_resource_transition(ResourceState.REVIEWED, ResourceState.SUPERSEDED) is True
    assert is_valid_resource_transition(ResourceState.RETRIEVAL_ELIGIBLE, ResourceState.SUPERSEDED) is True


def test_reviewed_and_retrieval_eligible_are_not_synonymous() -> None:
    """REVIEWED signifie uniquement review_status='reviewed' côté rag-engine.
    RETRIEVAL_ELIGIBLE est une vérification déterministe distincte, jamais
    décidée par un humain ni confondue avec REVIEWED."""
    assert ResourceState.REVIEWED != ResourceState.RETRIEVAL_ELIGIBLE
    assert is_valid_resource_transition(ResourceState.REVIEWED, ResourceState.RETRIEVAL_ELIGIBLE) is True
    # REVIEWED ne peut pas revenir en arrière vers NEEDS_REVIEW ni sauter ailleurs
    assert is_valid_resource_transition(ResourceState.REVIEWED, ResourceState.NEEDS_REVIEW) is False
    assert is_valid_resource_transition(ResourceState.NEEDS_REVIEW, ResourceState.RETRIEVAL_ELIGIBLE) is False


def test_retrieval_eligible_has_no_outgoing_transition_except_superseded() -> None:
    for state in ResourceState:
        if state in (ResourceState.RETRIEVAL_ELIGIBLE, ResourceState.SUPERSEDED):
            continue
        assert is_valid_resource_transition(ResourceState.RETRIEVAL_ELIGIBLE, state) is False


@pytest.mark.parametrize(
    "state",
    [
        ResourceState.REJECTED,
        ResourceState.QUARANTINED,
        ResourceState.DUPLICATE,
        ResourceState.SUPERSEDED,
        ResourceState.DEAD_LETTER,
        ResourceState.CANCELLED,
    ],
)
def test_exception_states_have_no_outgoing_transition(state: ResourceState) -> None:
    for target in ResourceState:
        assert is_valid_resource_transition(state, target) is False


def test_failed_can_only_reach_dead_letter_or_cancelled() -> None:
    assert is_valid_resource_transition(ResourceState.FAILED, ResourceState.DEAD_LETTER) is True
    assert is_valid_resource_transition(ResourceState.FAILED, ResourceState.CANCELLED) is True
    assert is_valid_resource_transition(ResourceState.FAILED, ResourceState.DISCOVERED) is False
    assert is_valid_resource_transition(ResourceState.FAILED, ResourceState.STAGED) is False


def test_no_transition_targets_a_nonexistent_published_state() -> None:
    """Preuve directe qu'aucune paire (from, to) de la table de transitions
    ne référence un état PUBLISHED, sous quelque forme que ce soit."""
    for from_state in ResourceState:
        for to_state in ResourceState:
            if is_valid_resource_transition(from_state, to_state):
                assert to_state.value != "PUBLISHED"


def test_discovered_is_a_valid_initial_state_with_no_incoming_transition() -> None:
    for from_state in ResourceState:
        if from_state is ResourceState.DISCOVERED:
            continue
        assert is_valid_resource_transition(from_state, ResourceState.DISCOVERED) is False
