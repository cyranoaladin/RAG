"""Les deux scopes HGGSP successeurs sont packagés et distincts de V4."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path

import yaml
import pytest

from nexus_contracts import load_retrieval_scope_registry
from nexus_contracts import hggsp_successor_scopes, scope as historical_scope


ROOT = Path(__file__).resolve().parents[3]
AUTHORITY = ROOT / "packages/contracts/authorities/production-profile-scope-successors-hggsp-v5.yml"
MIXED = ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json"
RELEASE = ROOT / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_hggsp_v5/release-b34b11e678bf9559/profile_gate/production-profile-gate.release.json"
)
V4 = {
    "prod_hggsp_premiere_specialite_v2": "dd68b2c6770bf42061e74d3e0844c25ddd582a297e2c775cc4b2e7a622f8fd26",
    "prod_hggsp_terminale_specialite_v2": "6101644987d86a5410bc01f5efaee2f10c69686d2ff415c1650f4fcec8896791",
}
SUCCESSOR = {
    "rag_nexus_hggsp_premiere_specialite": "prod_hggsp_premiere_specialite_v3",
    "rag_nexus_hggsp_terminale_specialite": "prod_hggsp_terminale_specialite_v3",
}
V4_RETAINED_BYTES = {
    "prod_dgemc_terminale_option_v3": "bd24b45ac2d50d8f3426c6785555a1eb5e001bdab007b74afe48956f887735c4",
    "prod_hlp_premiere_specialite_v3": "8e69811130c8c447cb0484c1117b4f0d0e14447eda50cd3e026e243064624e7d",
    "prod_hlp_terminale_specialite_v2": "8a7e64fdf33eb9c85c6e45bc5df83248789a971a0cd0517d461921a07665de2e",
    "prod_nsi_premiere_specialite_v3": "5309a2cd9581f0c0cdee9c76c3f11f6a755a39f739767a99d3c6140443f6815e",
    "prod_nsi_terminale_specialite_v3": "021a4d044362bb8dc25c3fa6fa9b98d222cc6674768195ca41ee75e51537387c",
    "prod_ses_premiere_specialite_v3": "d3d3e6585983b5d7de7d4ca69c5d5b839446b388c19bdb72788eaad826861bdc",
    "prod_ses_terminale_specialite_v3": "d5ced8f451d36156f583442e84a6f9a9ee4bf74b725812c2f5723cf768f5c783",
    "prod_svt_premiere_specialite_v3": "946059ade73dde210ed1b596b832d0757ea2711921275e6c6c998a8045c9b6be",
    "prod_svt_terminale_specialite_v3": "9b1fed323f9ee29504056b4dceebe7a50f34af7d474872185d498d003170512a",
}


def _builder():
    script = ROOT / "packages/contracts/scripts/build_hggsp_successor_scope_artifacts.py"
    spec = importlib.util.spec_from_file_location("hggsp_scope_builder", script)
    assert spec and spec.loader
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    return builder


def test_successor_subjects_and_mixed_owner_are_exact() -> None:
    authority = yaml.safe_load(AUTHORITY.read_text())
    release = json.loads(RELEASE.read_text())
    mixed = json.loads(MIXED.read_text())
    assert authority["release_id"] == release["release_id"] == "production-profile-gate-2026-2027-v5-hggsp"
    assert authority["release_manifest_sha256"] == hashlib.sha256(RELEASE.read_bytes()).hexdigest() == (
        "8286388002071e31a4d80d357feb19d802292c862055e6749d9371fc15441daf"
    )
    assert authority["mixed_registry_sha256"] == hashlib.sha256(MIXED.read_bytes()).hexdigest() == (
        "59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6"
    )
    owner = next(r for r in mixed["releases"] if r["release_id"] == release["release_id"])
    assert set(owner["collections"]) == set(SUCCESSOR)
    assert {entry["collection"]: entry["scope_id"] for entry in authority["bindings"]} == SUCCESSOR
    subject_sha = {entry["collection"]: entry["sha256"] for entry in release["subjects"]}
    assert {entry["collection"]: entry["subject_sha256"] for entry in authority["bindings"]} == subject_sha


def test_new_scopes_resolve_and_v4_hggsp_bytes_stay_pinned() -> None:
    registry = load_retrieval_scope_registry()
    assert len(registry) == 65
    for collection, new_id in SUCCESSOR.items():
        new = registry[new_id]
        old_id = new_id.removesuffix("_v3") + "_v2"
        old = registry[old_id]
        assert old.sha256_digest() == V4[old_id]
        assert new.scope_id == new_id
        assert new.evidence_subject.collection == collection
        assert new.source_sha256 != old.source_sha256
        assert new.evidence_subject == old.evidence_subject
        assert new.target_identity == old.target_identity


def test_historical_registry_remains_attested_and_successor_is_disjoint() -> None:
    source = ROOT / "packages/contracts/src/nexus_contracts/scope.py"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        "831e021070dbb681bd8363898ce5a80fa1fe2ef043f733c9ba3d73f4295162ad"
    )
    historical = historical_scope.load_retrieval_scope_registry()
    combined = load_retrieval_scope_registry()
    assert len(historical) == 63
    assert set(combined) == set(historical) | set(SUCCESSOR.values())
    assert set(historical).isdisjoint(SUCCESSOR.values())
    for scope_id, artifact in historical.items():
        assert combined[scope_id] == artifact


def test_successor_extension_refuses_historical_id_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        hggsp_successor_scopes,
        "_HGGSP_SUCCESSOR_RESOURCES",
        {"prod_hggsp_premiere_specialite_v2": ("unused.json", "0" * 64)},
    )
    with pytest.raises(ValueError, match="collides"):
        hggsp_successor_scopes.load_retrieval_scope_registry()
    with pytest.raises(ValueError, match="collides"):
        hggsp_successor_scopes.load_retrieval_scope_artifact(
            "prod_hggsp_premiere_specialite_v2"
        )


def test_successor_extension_refuses_bad_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        hggsp_successor_scopes,
        "_HGGSP_SUCCESSOR_RESOURCES",
        {
            "prod_hggsp_premiere_specialite_v3": (
                "artifacts/retrieval-scope-prod-hggsp-premiere-specialite-v3.json",
                "0" * 64,
            )
        },
    )
    with pytest.raises(ValueError, match="digest mismatch"):
        hggsp_successor_scopes.load_retrieval_scope_artifact(
            "prod_hggsp_premiere_specialite_v3"
        )


def test_canonical_derivation_reproduces_every_packaged_byte() -> None:
    builder = _builder()
    authority, artifacts = builder.derive(ROOT)
    assert authority == AUTHORITY.read_bytes()
    assert set(artifacts) == set(SUCCESSOR.values())
    for scope_id, raw in artifacts.items():
        filename = f"retrieval-scope-{scope_id.replace('_', '-')}.json"
        packaged = ROOT / "packages/contracts/src/nexus_contracts/artifacts" / filename
        assert raw == packaged.read_bytes()


@pytest.mark.parametrize("field", [
    "decision_status", "tenant", "niveau", "voie", "matiere",
    "statut_enseignement", "candidat", "audiences", "rights",
    "policy_visibility", "evidence_visibility", "programme_version",
    "authority_source", "policy_source_scope_id", "target_audience",
    "target_candidates", "programme_taxonomy_sha256",
])
def test_successor_policy_cannot_mutate_governed_v4_dimension(field: str) -> None:
    builder = _builder()
    old = {field: "approved"}
    new = {field: "widened"}
    with pytest.raises(builder.ScopeDerivationRefused, match="politique V4 divergente"):
        builder.validate_inherited_policy(new, old)


def test_all_nine_retained_v4_scope_artifact_bytes_are_unchanged() -> None:
    v4 = yaml.safe_load((ROOT / "packages/contracts/authorities/production-profile-scope-successors-v4.yml").read_text())
    retained = {entry["scope_id"] for entry in v4["bindings"] if "hggsp" not in entry["collection"]}
    assert retained == set(V4_RETAINED_BYTES)
    for scope_id, digest in V4_RETAINED_BYTES.items():
        path = ROOT / "packages/contracts/src/nexus_contracts/artifacts" / f"retrieval-scope-{scope_id.replace('_', '-')}.json"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_v4_hggsp_naming_authority_cannot_be_successor_authority() -> None:
    builder = _builder()
    v4 = yaml.safe_load((ROOT / "packages/contracts/authorities/production-profile-scope-successors-v4.yml").read_text())
    with pytest.raises(builder.ScopeDerivationRefused, match="non liée au successeur"):
        builder.validate_successor_authority(v4)


def test_canonical_derivation_rejects_mutated_policy_even_with_new_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = _builder()
    (tmp_path / "services").symlink_to(ROOT / "services", target_is_directory=True)
    (tmp_path / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
    governance = tmp_path / "docs/governance"
    governance.mkdir(parents=True)
    (governance / "retrieval_scope_policy_registry_v4.yml").symlink_to(
        ROOT / "docs/governance/retrieval_scope_policy_registry_v4.yml"
    )
    policy = yaml.safe_load((ROOT / builder.POLICY_PATH).read_text())
    policy["collections"][0]["audiences"] = ["tous"]
    mutated = governance / "retrieval_scope_policy_registry_hggsp_v5.yml"
    mutated.write_text(yaml.safe_dump(policy, sort_keys=False))
    monkeypatch.setattr(builder, "POLICY_SHA256", hashlib.sha256(mutated.read_bytes()).hexdigest())
    with pytest.raises(builder.ScopeDerivationRefused, match="audiences"):
        builder.derive(tmp_path)


def test_v5_naming_authority_cannot_emit_v4_scopes(tmp_path: Path) -> None:
    _builder()
    emitter = importlib.import_module("build_retrieval_scope_artifacts")
    v4_release = ROOT / (
        "services/rag-pedago/data/releases/prerentree_2026_2027/"
        "profile_gate_v4/release-024f8625ebfeb7ce/profile_gate/"
        "production-profile-gate.release.json"
    )
    v4_policy = ROOT / "docs/governance/retrieval_scope_policy_registry_v4.yml"
    with pytest.raises(emitter.ScopeEmissionError, match="aucun identifiant"):
        emitter.emit_from_policy_registry(
            subject_release=v4_release,
            subject_release_sha256=hashlib.sha256(v4_release.read_bytes()).hexdigest(),
            policy_registry=v4_policy,
            policy_registry_sha256=hashlib.sha256(v4_policy.read_bytes()).hexdigest(),
            successor_authority=AUTHORITY,
            successor_authority_sha256=hashlib.sha256(AUTHORITY.read_bytes()).hexdigest(),
            artifacts_dir=tmp_path,
            repo_root=ROOT,
        )
