"""Le successeur préparatoire #313 ne peut émettre aucun scope étudiant."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/go_live"))

from check_public_scope_policy_authority import (
    SUCCESSOR_DIR,
    PublicScopePolicyError,
    check_public_successor_scope_proposal,
)

PROPOSAL = (
    ROOT / "governance/student_public_rights/public_successor_scope_proposal_20261010.yml"
)


def _proposal() -> dict:
    return yaml.safe_load(PROPOSAL.read_text(encoding="utf-8"))


def test_prepared_successor_binds_eleven_unissued_student_scopes() -> None:
    proposal = _proposal()
    assert check_public_successor_scope_proposal(ROOT, proposal) == 11
    assert all(row["status"] == "NOT_ISSUED" for row in proposal["bindings"])
    assert proposal["scope_issuance_authorized"] is False


def test_successor_proposal_requires_exact_rights_authority_bytes(tmp_path: Path) -> None:
    release = tmp_path / SUCCESSOR_DIR
    release.parent.mkdir(parents=True)
    release.symlink_to(ROOT / SUCCESSOR_DIR, target_is_directory=True)
    relative = Path(
        "governance/student_public_rights/authorities/"
        "eduscol_etalab_2_0_sitewide_20261010.yml"
    )
    authority = tmp_path / relative
    authority.parent.mkdir(parents=True)
    authority.write_bytes((ROOT / relative).read_bytes() + b"\n# altered\n")
    with pytest.raises(PublicScopePolicyError, match="RIGHTS"):
        check_public_successor_scope_proposal(tmp_path, _proposal())


@pytest.mark.parametrize("sabotage", [
    "old_candidate", "bad_manifest", "bad_preparation_index", "missing_scope",
    "internal", "teacher", "second_subject", "wrong_subject", "wrong_profile",
    "wrong_scope_id", "issued", "faked_review", "publication_enabled",
    "pdf_download_enabled", "answer_generation_enabled", "bad_rights_authority",
])
def test_successor_proposal_refuses_drift_or_premature_activation(sabotage: str) -> None:
    proposal = copy.deepcopy(_proposal())
    row = proposal["bindings"][0]
    if sabotage == "old_candidate":
        proposal["successor_release_id"] = "student-public-20261010-v1-eb39f6cd0423e184"
    elif sabotage == "bad_manifest":
        proposal["successor_release_manifest_sha256"] = "0" * 64
    elif sabotage == "bad_preparation_index":
        proposal["preparation_index_sha256"] = "0" * 64
    elif sabotage == "missing_scope":
        proposal["bindings"].pop()
    elif sabotage == "internal":
        row["visibility"] = "internal"
    elif sabotage == "teacher":
        row["target_policy"]["roles"] = ["student", "teacher"]
    elif sabotage == "second_subject":
        row["target_policy"]["matiere"] = ["dgemc", "nsi"]
    elif sabotage == "wrong_subject":
        row["prepared_subject_sha256"] = "0" * 64
    elif sabotage == "wrong_profile":
        row["profile_fingerprint"] = "0" * 64
    elif sabotage == "wrong_scope_id":
        row["proposed_scope_id"] = "student_public_hggsp_premiere_specialite_v1"
    elif sabotage == "issued":
        row["status"] = "ISSUED"
    elif sabotage == "faked_review":
        proposal["exact_head_review_receipt"] = "a" * 64
    elif sabotage == "publication_enabled":
        proposal["publication_authorized"] = True
    elif sabotage == "pdf_download_enabled":
        proposal["full_pdf_redistribution_allowed"] = True
    elif sabotage == "answer_generation_enabled":
        proposal["answer_generation_allowed"] = True
    elif sabotage == "bad_rights_authority":
        proposal["rights_authority_sha256"] = "0" * 64
    with pytest.raises(PublicScopePolicyError):
        check_public_successor_scope_proposal(ROOT, proposal)
