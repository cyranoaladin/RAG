"""Extension fermée des scopes HGGSP V5 au registre historique attesté.

``scope.py`` reste octet-identique à la provenance multilevel publiée. Les
deux scopes du successeur sont chargés ici, avec leurs digests canoniques,
sans altérer cette autorité historique.
"""

from __future__ import annotations

from importlib.resources import files
from types import MappingProxyType
from typing import Mapping

from nexus_contracts.scope import (
    RetrievalScopeArtifact,
    RetrievalScopeArtifactV2,
    _RETRIEVAL_SCOPE_RESOURCES,
    load_retrieval_scope_artifact as _load_historical_artifact,
    load_retrieval_scope_registry as _load_historical_registry,
)

_HGGSP_SUCCESSOR_RESOURCES: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "prod_hggsp_premiere_specialite_v3": (
            "artifacts/retrieval-scope-prod-hggsp-premiere-specialite-v3.json",
            "ceab3ef201fa12d5a33edf3ffc2a1fb86bfd09428b4e5139923dc3e9e60e1bbf",
        ),
        "prod_hggsp_terminale_specialite_v3": (
            "artifacts/retrieval-scope-prod-hggsp-terminale-specialite-v3.json",
            "1406aa3ffc45c25c346e1ff8353b7ee77db9496dfbad8ae8865c74fa63a94215",
        ),
    }
)


def load_retrieval_scope_artifact(scope_id: str) -> RetrievalScopeArtifact:
    """Charger un scope historique ou V5 explicitement nommé et vérifié."""
    successor = _HGGSP_SUCCESSOR_RESOURCES.get(scope_id)
    if successor is None:
        return _load_historical_artifact(scope_id)
    if scope_id in _RETRIEVAL_SCOPE_RESOURCES:
        raise ValueError("HGGSP successor scope collides with historical scope")
    resource_name, expected_digest = successor
    resource = files("nexus_contracts").joinpath(resource_name)
    artifact = RetrievalScopeArtifactV2.model_validate_json(resource.read_bytes())
    if artifact.scope_id != scope_id or artifact.sha256_digest() != expected_digest:
        raise ValueError("retrieval scope artifact digest mismatch")
    return artifact


def load_retrieval_scope_registry() -> Mapping[str, RetrievalScopeArtifact]:
    """Retourner le registre public fermé historique + deux scopes V5."""
    historical = _load_historical_registry()
    if set(historical) & set(_HGGSP_SUCCESSOR_RESOURCES):
        raise ValueError("HGGSP successor scope collides with historical scope")
    return MappingProxyType(
        {
            **historical,
            **{
                scope_id: load_retrieval_scope_artifact(scope_id)
                for scope_id in _HGGSP_SUCCESSOR_RESOURCES
            },
        }
    )


__all__ = ["load_retrieval_scope_artifact", "load_retrieval_scope_registry"]
