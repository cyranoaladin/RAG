"""Adaptateur plan de contrôle vers le producteur partagé de placement."""

from nexus_contracts.release_scope_placement import (
    ProducedReleaseScopePlacement,
    ReleaseScopePlacementGitInputs,
    ReleaseScopePlacementProducerError,
    ReleaseScopePlacementProvenance,
    produce_release_scope_placement_from_git,
)
from nexus_contracts.release_scope_placement import (
    _compose_release_scope_placement as _compose_release_scope_placement,
)
from nexus_contracts.release_scope_placement import (
    _GitTreeReader as _GitTreeReader,
)
from nexus_contracts.release_scope_placement import (
    _parse_git_tree_entry as _parse_git_tree_entry,
)

__all__ = [
    "ProducedReleaseScopePlacement",
    "ReleaseScopePlacementGitInputs",
    "ReleaseScopePlacementProducerError",
    "ReleaseScopePlacementProvenance",
    "produce_release_scope_placement_from_git",
]
