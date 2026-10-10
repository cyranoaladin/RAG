"""Une politique proposée ne devient pas un scope actif par sa seule présence."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/go_live"))
AUTHORITY_PATH = ROOT / "governance/student_public_rights/public_scope_policy_authority_v1.yml"
RELEASE = (ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027"
           / "profile_gate_student_public_v1/release-eb39f6cd0423e184/profile_gate")


def _verifier():
    return importlib.import_module("check_public_scope_policy_authority")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pack() -> dict:
    aggregate_raw = (RELEASE / "production-profile-gate.release.json").read_bytes()
    aggregate = json.loads(aggregate_raw)
    return {
        "authority": yaml.safe_load(AUTHORITY_PATH.read_bytes()),
        "aggregate_raw": aggregate_raw,
        "profiles_raw": (RELEASE / "public_profiles.json").read_bytes(),
        "rights_raw": (RELEASE / "public_rights_registry.json").read_bytes(),
        "artifacts_raw": (RELEASE / "artifacts.release.json").read_bytes(),
        "candidate_manifest_raw": (ROOT / "docs/reports/go_live/student_rights_evidence"
                                   / "public_derivative_candidate_manifest_20261010.json").read_bytes(),
        "rights_authority_raw": (ROOT / "governance/student_public_rights/authorities"
                                 / "eduscol_etalab_2_0_sitewide_20261010.yml").read_bytes(),
        "adr_raw": (ROOT / "docs/adr"
                    / "ADR-0064-acces-etudiant-public-gouverne-des-onze-collections.md").read_bytes(),
        "subjects_raw": {row["collection"]: (RELEASE / row["path"]).read_bytes()
                         for row in aggregate["subjects"]},
    }


def test_candidate_authority_is_pending_for_exactly_eleven_public_collections() -> None:
    assert _verifier().check_public_scope_policy_authority(**_pack()) == 11


@pytest.mark.parametrize("mutate", [
    lambda p: p["authority"]["student_visibility"].append("internal"),
    lambda p: p["authority"]["bindings"][0].update({"policy_visibility": "internal"}),
    lambda p: p["authority"]["bindings"][0].update({"evidence_visibility": "internal"}),
    lambda p: p["authority"]["bindings"][0].update({"scope_id": "forged_active_scope"}),
    lambda p: p["authority"]["bindings"][0].update({"final_subject_sha256": "a" * 64}),
    lambda p: p["authority"]["bindings"][0].update({"candidate_profile_fingerprint": "a" * 64}),
    lambda p: p["authority"]["bindings"][0].update({"rights_basis": "officiel_public"}),
    lambda p: p["authority"].update({"rights_authority_sha256": "0" * 64}),
    lambda p: p["authority"].update({"status": "ACTIVE"}),
    lambda p: p["authority"]["bindings"][0]["target_policy"].update({"roles": ["student", "admin"]}),
])
def test_pending_authority_refuses_activation_or_rights_drift(mutate) -> None:
    pack = copy.deepcopy(_pack())
    mutate(pack)
    with pytest.raises(_verifier().PublicScopePolicyError):
        _verifier().check_public_scope_policy_authority(**pack)


def test_missing_rights_and_pdf_material_are_not_authorized() -> None:
    pack = _pack()
    registry = json.loads(pack["rights_raw"])
    registry["entries"].pop()
    pack["rights_raw"] = json.dumps(registry).encode()
    with pytest.raises(_verifier().PublicScopePolicyError):
        _verifier().check_public_scope_policy_authority(**pack)

    pack = _pack()
    artifacts = json.loads(pack["artifacts_raw"])
    artifacts["artifacts"][0]["media_type"] = "application/pdf"
    pack["artifacts_raw"] = json.dumps(artifacts).encode()
    with pytest.raises(_verifier().PublicScopePolicyError):
        _verifier().check_public_scope_policy_authority(**pack)


def test_resealed_zone_label_cannot_replace_derivative_rights() -> None:
    pack = _pack()
    rights = json.loads(pack["rights_raw"])
    rights["entries"][0]["rights_basis"] = "officiel_public"
    pack["rights_raw"] = json.dumps(rights).encode()
    aggregate = json.loads(pack["aggregate_raw"])
    aggregate["authorities"]["public_rights_registry_sha256"] = _sha(pack["rights_raw"])
    pack["aggregate_raw"] = json.dumps(aggregate).encode()
    pack["authority"]["candidate_rights_registry_sha256"] = _sha(pack["rights_raw"])
    pack["authority"]["candidate_release_manifest_sha256"] = _sha(pack["aggregate_raw"])
    with pytest.raises(_verifier().PublicScopePolicyError):
        _verifier().check_public_scope_policy_authority(**pack)


def test_resealed_pdf_manifest_cannot_be_a_text_scope() -> None:
    pack = _pack()
    manifest = json.loads(pack["candidate_manifest_raw"])
    manifest["entries"][0]["media_type"] = "application/pdf"
    pack["candidate_manifest_raw"] = json.dumps(manifest).encode()
    aggregate = json.loads(pack["aggregate_raw"])
    aggregate["authorities"]["candidate_manifest_sha256"] = _sha(pack["candidate_manifest_raw"])
    pack["aggregate_raw"] = json.dumps(aggregate).encode()
    pack["authority"]["candidate_derivative_manifest_sha256"] = _sha(pack["candidate_manifest_raw"])
    pack["authority"]["candidate_release_manifest_sha256"] = _sha(pack["aggregate_raw"])
    with pytest.raises(_verifier().PublicScopePolicyError):
        _verifier().check_public_scope_policy_authority(**pack)
