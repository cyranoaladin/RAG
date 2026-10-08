"""Les deux r4 du successeur sont dérivées, sans renommer les r4 V4."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "hggsp_successor_r4", ROOT / "scripts/go_live/build_hggsp_successor_r4_authorizations.py"
)
assert SPEC and SPEC.loader
r4 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r4)


def test_two_successor_r4_are_canonical_and_distinct_from_v4() -> None:
    ids = r4.verifier_fichiers(ROOT)
    assert ids == [
        "lot41a-staging-v5-hggsp-premiere-specialite-r4",
        "lot41a-staging-v5-hggsp-terminale-specialite-r4",
    ]
    assert all("staging-v4" not in value for value in ids)
    documents = r4.construire(ROOT)
    assert set(documents) == set(ids)
    assert {document["scope"]["collection"] for document in documents.values()} == set(r4.COLLECTIONS)
    assert len({content for document in documents.values()
                for content in document["allowed_content_sha256"]}) == 52


def test_wrong_manifest_or_registry_binding_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r4, "MANIFEST_SHA256", "0" * 64)
    with pytest.raises(r4.ScopeRefuse, match="manifeste"):
        r4.construire(ROOT)
    monkeypatch.setattr(r4, "MANIFEST_SHA256", "8286388002071e31a4d80d357feb19d802292c862055e6749d9371fc15441daf")
    monkeypatch.setattr(r4, "MIXED_REGISTRY_SHA256", "0" * 64)
    with pytest.raises(r4.ScopeRefuse, match="registre mixte"):
        r4.construire(ROOT)


def test_v4_scope_id_is_not_an_installed_successor_scope() -> None:
    sys.path.insert(0, str(ROOT / "packages/contracts/src"))
    try:
        from nexus_contracts import load_retrieval_scope_registry

        registry = load_retrieval_scope_registry()
    finally:
        sys.path.pop(0)
    bindings = r4.registre_scopes(ROOT)["bindings"]
    assert len(bindings) == 2
    for binding in bindings:
        assert binding["scope_id"] in registry
        assert binding["predecessor_scope_id"] in registry
        assert binding["scope_id"] != binding["predecessor_scope_id"]
