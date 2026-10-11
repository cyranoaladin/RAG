"""Les entrées d'émission B doivent être les onze décisions préparées, octet par octet."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/contracts/scripts"))
sys.path.insert(0, str(ROOT / "scripts/go_live"))

import emit_student_public_scopes as issuer
from build_retrieval_scope_artifacts import (
    StudentScopeEmissionEvidence,
    emit_from_policy_registry,
    load_policy_registry,
    load_successor_authority,
)
from nexus_contracts import RetrievalScopeArtifactV3

PROPOSAL = ROOT / (
    "governance/student_public_rights/public_successor_scope_proposal_20261010.yml"
)
POLICY = ROOT / (
    "governance/student_public_rights/student_public_successor_scope_policy_registry_v1.yml"
)
NAMES = ROOT / (
    "packages/contracts/authorities/student-public-successor-scope-names-v1.yml"
)
ANCHOR = ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261010.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_reviewed_emission_inputs_restate_all_eleven_prepared_subjects() -> None:
    proposal = yaml.safe_load(PROPOSAL.read_bytes())
    anchor = json.loads(ANCHOR.read_bytes())
    registry = load_policy_registry(POLICY, _sha(POLICY))
    named = load_successor_authority(NAMES, _sha(NAMES))
    expected = {row["collection"]: row for row in proposal["bindings"]}
    subjects = {row["collection"]: row["subject_sha256"]
                for row in anchor["subjects"]}
    assert proposal["scope_issuance_authorized"] is False
    assert all(row["status"] == "NOT_ISSUED" for row in expected.values())
    assert len(expected) == len(registry.entries) == len(named) == len(subjects) == 11
    assert set(expected) == set(registry.entries) == set(named) == set(subjects)
    assert registry.release_manifest_sha256 == anchor["content_manifest_sha256"]
    assert registry.school_year == "2026-2027"
    assert registry.programme_authority_sha256 == (
        "67c91d6b0840864bf4750ef236a0c2f8cfb11804022fcf0ee70cbfd58320ee97"
    )
    for collection, row in expected.items():
        entry = registry.entries[collection]
        target = row["target_policy"]
        assert named[collection] == row["proposed_scope_id"]
        assert entry.authority_source == "NEXUS_HUMAN_DECISION_ADR_0064"
        assert entry.decision_status == "GOVERNED_BY_HUMAN_DECISION"
        assert entry.policy_source_scope_id is None
        assert entry.subject_manifest_sha256 == subjects[collection]
        assert entry.subject_manifest_sha256 == row["prepared_subject_sha256"]
        assert entry.rights == tuple(row["rights"]) == ("public_allowed",)
        assert entry.audiences == tuple(row["evidence_audiences"]) == ("libre", "aefe")
        assert entry.policy_visibility == entry.evidence_visibility == "public"
        assert entry.programme_version == row["programme_version"]
        assert entry.target_audience == "libre"
        assert entry.target_candidates == ("libre",)
        for field in ("tenant", "niveau", "voie", "matiere", "statut_enseignement"):
            assert getattr(entry, field) == target[field]


def _synthetic_emission(tmp_path: Path):
    anchor = json.loads(ANCHOR.read_bytes())
    manifest = ROOT / (
        "services/rag-pedago/data/releases/prerentree_2026_2027/"
        "profile_gate_student_public_successor_v1/release-fcc84331e7700042/"
        "profile_gate/production-profile-gate.release.json"
    )
    evidence = StudentScopeEmissionEvidence(
        content_anchor_sha256=_sha(ANCHOR),
        content_manifest_sha256=_sha(manifest),
        subject_sha256_by_collection={
            row["collection"]: row["subject_sha256"] for row in anchor["subjects"]
        },
        expires_at_utc=datetime.now(UTC) + timedelta(hours=1),
        reviewed_policy_registry_sha256=_sha(POLICY),
        reviewed_successor_authority_sha256=_sha(NAMES),
        reviewed_head_sha="a" * 40,
    )
    output = tmp_path / "synthetic-scopes"
    result = emit_from_policy_registry(
        subject_release=manifest,
        subject_release_sha256=_sha(manifest),
        policy_registry=POLICY,
        policy_registry_sha256=_sha(POLICY),
        successor_authority=NAMES,
        successor_authority_sha256=_sha(NAMES),
        artifacts_dir=output,
        repo_root=ROOT,
        student_scope_evidence=evidence,
    )
    return result, evidence, output


def test_eleven_v3_scopes_can_be_rebuilt_only_with_synthetic_verified_inputs(
    tmp_path: Path,
) -> None:
    result, evidence, output = _synthetic_emission(tmp_path)
    assert len(result.emitted) == 11
    assert all(isinstance(item.artifact, RetrievalScopeArtifactV3)
               for item in result.emitted)
    assert {item.collection: item.artifact.source_sha256 for item in result.emitted} == (
        evidence.subject_sha256_by_collection
    )
    assert len(list(output.glob("*.json"))) == 11


def test_collective_registry_binds_eleven_v3_to_a_without_activation(
    tmp_path: Path,
) -> None:
    result, _evidence, _output = _synthetic_emission(tmp_path)
    registry = issuer.build_public_scope_registry(
        result, ANCHOR, _sha(ANCHOR),
        json.loads(ANCHOR.read_bytes())["content_manifest_sha256"],
        _sha(POLICY), _sha(NAMES),
    )
    assert registry["kind"] == "NEXUS_STUDENT_PUBLIC_SCOPE_REGISTRY_V1"
    assert registry["status"] == "SCOPES_ISSUED_NOT_PUBLICATION_AUTHORITY"
    assert registry["activation_allowed"] is False
    assert len(registry["scopes"]) == 11
    emitted = {item.collection: item for item in result.emitted}
    for row in registry["scopes"]:
        item = emitted[row["collection"]]
        assert row["resource"] == f"scopes/{item.scope_id}.json"
        assert row["sha256"] == hashlib.sha256(item.artifact.canonical_bytes()).hexdigest()
    assert {row["collection"]: row["source_sha256"] for row in registry["scopes"]} == {
        row["collection"]: row["subject_sha256"]
        for row in json.loads(ANCHOR.read_bytes())["subjects"]
    }


@pytest.mark.parametrize("sabotage", ["source", "collection"])
def test_collective_registry_refuses_wrong_a_subject_population(
    tmp_path: Path, sabotage: str,
) -> None:
    result, _evidence, _output = _synthetic_emission(tmp_path)
    original = result.emitted[0]
    if sabotage == "source":
        changed = replace(original, artifact=original.artifact.model_copy(
            update={"source_sha256": "f" * 64},
        ))
    else:
        changed = replace(original, collection="rag_nexus_extra")
    broken = replace(result, emitted=(changed, *result.emitted[1:]))
    with pytest.raises(issuer.StudentPublicScopeEmissionError):
        issuer.build_public_scope_registry(
            broken, ANCHOR, _sha(ANCHOR),
            json.loads(ANCHOR.read_bytes())["content_manifest_sha256"],
            _sha(POLICY), _sha(NAMES),
        )
