"""La sonde du complément suit l'autorité du registre mixte scellé."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "staging_retrieval_probe", ROOT / "scripts/go_live/staging_retrieval_probe.py"
)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)

REGISTRY = ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json"
REGISTRY_SHA = "59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6"
HGGSP = {"rag_nexus_hggsp_premiere_specialite", "rag_nexus_hggsp_terminale_specialite"}


def test_mixed_authority_names_eleven_scopes_and_successor_ownership() -> None:
    scopes, programmes, owners = probe.mixed_authorities(ROOT, REGISTRY, REGISTRY_SHA)
    assert len(scopes) == len(programmes) == len(owners) == 11
    assert set(scopes) == set(programmes) == set(owners)
    assert {name for name, owner in owners.items() if owner.endswith("v5-hggsp")} == HGGSP
    assert all(scopes[name] != probe.scopes_emis(ROOT).get(name) for name in HGGSP)


def test_mixed_authority_refuses_registry_digest_drift() -> None:
    with pytest.raises(probe.SondeEchec, match="registre mixte"):
        probe.mixed_authorities(ROOT, REGISTRY, "0" * 64)


def test_mixed_authority_refuses_third_successor_collection(tmp_path: Path) -> None:
    import json

    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    data["releases"][1]["collections"].append("rag_nexus_svt_premiere_specialite")
    altered = tmp_path / "registry.json"
    altered.write_text(json.dumps(data), encoding="utf-8")
    import hashlib

    with pytest.raises(probe.SondeEchec, match="collections"):
        probe.mixed_authorities(ROOT, altered, hashlib.sha256(altered.read_bytes()).hexdigest())


def test_mixed_authority_refuses_scope_registry_for_other_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yaml

    authority = yaml.safe_load((ROOT / probe.SUCCESSEURS_HGGSP).read_text(encoding="utf-8"))
    authority["mixed_registry_sha256"] = "0" * 64
    altered = tmp_path / "scope-authority.yml"
    altered.write_text(yaml.safe_dump(authority), encoding="utf-8")
    monkeypatch.setattr(probe, "SUCCESSEURS_HGGSP", str(altered))
    with pytest.raises(probe.SondeEchec, match="autorité de scope successeur"):
        probe.mixed_authorities(ROOT, REGISTRY, REGISTRY_SHA)


def test_mixed_authority_refuses_cross_swapped_v4_hggsp_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yaml

    authority = yaml.safe_load((ROOT / probe.SUCCESSEURS_HGGSP).read_text(encoding="utf-8"))
    authority["bindings"][0]["scope_id"] = "prod_hggsp_terminale_specialite_v2"
    authority["bindings"][1]["scope_id"] = "prod_hggsp_premiere_specialite_v2"
    altered = tmp_path / "scope-authority.yml"
    altered.write_text(yaml.safe_dump(authority), encoding="utf-8")
    monkeypatch.setattr(probe, "SUCCESSEURS_HGGSP", str(altered))
    with pytest.raises(probe.SondeEchec, match="V4"):
        probe.mixed_authorities(ROOT, REGISTRY, REGISTRY_SHA)


def test_mixed_probe_refuses_subset_before_database_access() -> None:
    modules = {"load_collection_config": lambda _path: {}}
    with pytest.raises(probe.SondeEchec, match="onze scopes"):
        probe.sonder(
            ROOT, connexion=lambda: (_ for _ in ()).throw(AssertionError("DB accessed")),
            modules=modules, collections=["rag_nexus_hggsp_premiere_specialite"],
            mixed_registry=(REGISTRY, REGISTRY_SHA),
        )


def test_multi_placement_keeps_each_authorized_placement() -> None:
    from types import SimpleNamespace

    class Connection:
        def execute(self, sql: str, params: dict) -> object:
            assert "JOIN public.rag_artifact_placements AS placement" in sql
            assert "DISTINCT ON" not in sql
            assert params["collection"] == "rag_nexus_hggsp_premiere_specialite"

            class Cursor:
                @staticmethod
                def fetchall() -> list[tuple[str, str, str, str, str]]:
                    return [
                        ("chunk-1", "[1,2]", "un texte valable", "artifact-1", "placement-a"),
                        ("chunk-1", "[1,2]", "un texte valable", "artifact-1", "placement-b"),
                    ]

            return Cursor()

    scope = SimpleNamespace(
        collection="rag_nexus_hggsp_premiere_specialite", tenant="libre_premiere",
        niveau="premiere", voie="generale", matiere="hggsp",
        statut_enseignement="specialite", candidat="libre", audiences=("libre",),
        rights=(SimpleNamespace(value="officiel_public"),), visibilities=("internal",),
        school_year="2026-2027", programme_version="BOEN_special_1_2019-01-22",
    )
    chunks, allowed = probe.jeu_publie(Connection(), scope)
    assert chunks == {"chunk-1": ("[1,2]", "un texte valable")}
    assert allowed == {
        ("chunk-1", "artifact-1", "placement-a"),
        ("chunk-1", "artifact-1", "placement-b"),
    }
