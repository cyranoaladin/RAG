"""ADR-0064 ne peut autoriser que le périmètre élève public proposé.

Ce test ne vaut ni approbation humaine ni émission d'un scope actif.
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import replace
from pathlib import Path
import sys

import pytest
import yaml
from nexus_contracts import InternalIdentityEnvelope, RetrievalScopeArtifactV3
from nexus_contracts.hggsp_successor_scopes import load_retrieval_scope_artifact
import nexus_contracts.hggsp_successor_scopes as scope_module

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import build_retrieval_scope_artifacts as emitter  # noqa: E402

EXPECTED_PREDECESSORS = {
    "rag_nexus_dgemc_terminale_option": "prod_dgemc_terminale_option_v3",
    "rag_nexus_hggsp_premiere_specialite": "prod_hggsp_premiere_specialite_v3",
    "rag_nexus_hggsp_terminale_specialite": "prod_hggsp_terminale_specialite_v3",
    "rag_nexus_hlp_premiere_specialite": "prod_hlp_premiere_specialite_v3",
    "rag_nexus_hlp_terminale_specialite": "prod_hlp_terminale_specialite_v2",
    "rag_nexus_nsi_premiere_specialite": "prod_nsi_premiere_specialite_v3",
    "rag_nexus_nsi_terminale_specialite": "prod_nsi_terminale_specialite_v3",
    "rag_nexus_ses_premiere_specialite": "prod_ses_premiere_specialite_v3",
    "rag_nexus_ses_terminale_specialite": "prod_ses_terminale_specialite_v3",
    "rag_nexus_svt_premiere_specialite": "prod_svt_premiere_specialite_v3",
    "rag_nexus_svt_terminale_specialite": "prod_svt_terminale_specialite_v3",
}


def test_adr_0064_allowlist_is_exactly_the_reviewed_eleven() -> None:
    assert dict(emitter.STUDENT_PUBLIC_PREDECESSORS) == EXPECTED_PREDECESSORS


def test_public_successor_emission_uses_role_bound_v3() -> None:
    subject = emitter.SubjectFacts(
        collection="rag_nexus_dgemc_terminale_option", sha256="a" * 64,
        dimensions={},
    )
    artifact = emitter._build_artifact_from_registry(
        "student_public_dgemc_terminale_option_v1", _proposal(), subject,
        "2026-2027",
    )
    assert isinstance(artifact, RetrievalScopeArtifactV3)
    assert artifact.source_sha256 == subject.sha256
    assert artifact.target_policy.roles == ["student"]
    assert artifact.target_policy.audiences == ["libre"]
    assert artifact.target_policy.candidates == ["libre"]
    assert artifact.evidence_subject.rights == ["public_allowed"]
    emitted = emitter.EmittedScope(
        scope_id=artifact.scope_id, collection=subject.collection,
        policy_source_scope_id="NEXUS_HUMAN_DECISION_ADR_0064",
        resource_name=emitter.resource_name_for(artifact.scope_id),
        artifact=artifact, canonical_bytes=emitter._artifact_bytes(artifact),
    )
    index = json.loads(emitter.registry_index_bytes(
        emitter.EmissionResult(emitted=(emitted,), reused=())
    ))
    assert index["entries"][0]["artifact_version"] == "3"


def test_public_successor_v3_refuses_teacher_identity() -> None:
    artifact = emitter._build_artifact_from_registry(
        "student_public_dgemc_terminale_option_v1", _proposal(),
        emitter.SubjectFacts("rag_nexus_dgemc_terminale_option", "a" * 64, {}),
        "2026-2027",
    )
    assert isinstance(artifact, RetrievalScopeArtifactV3)
    identity = {
        "aud": "nexus-rag-engine", "exp": 1_785_320_400,
        "iss": "nexus-cockpit", "jti": "teacher-test-jti",
        "tenant": "libre_terminale", "niveau": "terminale",
        "role": "teacher", "school_year": "2026-2027",
        "sub": "psn_1234567890abcdef",
        "pedagogical_profile": {
            "voie": "generale", "matieres": ["dgemc"],
            "statut_enseignement": "option", "candidat": "libre",
            "audience": "libre",
        },
    }
    envelope = InternalIdentityEnvelope.model_validate({
        "protocol_version": "1", "iss": "nexus-cockpit", "aud": "nexus-rag-engine",
        "sub": identity["sub"], "jti": identity["jti"],
        "iat": 1_785_320_370, "exp": 1_785_320_400,
        "identity": identity, "scope_id": artifact.scope_id,
        "scope_digest": artifact.sha256_digest(),
        "request_sha256": "b" * 64, "manifest_sha256": "c" * 64,
        "allowed_collections": [artifact.evidence_subject.collection],
    })
    with pytest.raises(ValueError, match="role"):
        artifact.validate_envelope(envelope)


def test_packaged_scope_reader_accepts_pinned_v3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = emitter._build_artifact_from_registry(
        "student_public_dgemc_terminale_option_v1", _proposal(),
        emitter.SubjectFacts("rag_nexus_dgemc_terminale_option", "a" * 64, {}),
        "2026-2027",
    )
    assert isinstance(artifact, RetrievalScopeArtifactV3)
    (tmp_path / "scope.json").write_bytes(emitter._artifact_bytes(artifact))
    monkeypatch.setattr(scope_module, "files", lambda _: tmp_path)
    monkeypatch.setattr(scope_module, "_STUDENT_PUBLIC_RESOURCES", {
        artifact.scope_id: ("scope.json", artifact.sha256_digest()),
    })
    monkeypatch.setattr(scope_module, "_load_historical_registry", lambda: {})
    monkeypatch.setattr(scope_module, "_HGGSP_SUCCESSOR_RESOURCES", {})
    assert scope_module.load_retrieval_scope_artifact(artifact.scope_id) == artifact
    assert scope_module.load_retrieval_scope_registry()[artifact.scope_id] == artifact


def test_candidate_successor_cannot_emit_student_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[3]
    candidate = root / (
        "services/rag-pedago/data/releases/prerentree_2026_2027/"
        "profile_gate_student_public_successor_v1/release-fcc84331e7700042/"
        "profile_gate/production-profile-gate.release.json"
    )
    registry = emitter.PolicyRegistry(
        entries={"rag_nexus_dgemc_terminale_option": _proposal()},
        visibility_restriction_order=("public", "internal", "restricted", "private"),
        school_year="2026-2027", programme_authority_path="unused",
        programme_authority_sha256="a" * 64,
        release_manifest_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(emitter, "load_policy_registry", lambda *_: registry)
    monkeypatch.setattr(emitter, "load_successor_authority", lambda *_: {})
    output = tmp_path / "scopes"
    with pytest.raises(emitter.ScopeEmissionError, match="final public successor"):
        emitter.emit_from_policy_registry(
            subject_release=candidate,
            subject_release_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
            policy_registry=tmp_path / "unused-policy",
            policy_registry_sha256="a" * 64,
            successor_authority=tmp_path / "unused-names",
            successor_authority_sha256="b" * 64,
            artifacts_dir=output, repo_root=root,
        )
    assert not output.exists()


def test_adr_0053_cannot_emit_v2_under_student_public_ids_on_real_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[3]
    candidate = root / (
        "services/rag-pedago/data/releases/prerentree_2026_2027/"
        "profile_gate_student_public_successor_v1/release-fcc84331e7700042/"
        "profile_gate/production-profile-gate.release.json"
    )
    manifest = json.loads(candidate.read_bytes())
    refs = {row["collection"]: row["sha256"] for row in manifest["subjects"]}
    proposal = yaml.safe_load((root / (
        "governance/student_public_rights/"
        "public_successor_scope_proposal_20261010.yml"
    )).read_text())
    entries = {}
    named = {}
    for row in proposal["bindings"]:
        target = row["target_policy"]
        collection = row["collection"]
        named[collection] = row["proposed_scope_id"]
        entries[collection] = emitter.PolicyRegistryEntry(
            collection=collection, decision_status="GOVERNED_BY_HUMAN_DECISION",
            authority_source="NEXUS_HUMAN_DECISION_ADR_0053",
            policy_source_scope_id=None, subject_manifest_sha256=refs[collection],
            tenant=target["tenant"], niveau=target["niveau"], voie=target["voie"],
            matiere=target["matiere"],
            statut_enseignement=target["statut_enseignement"], candidat="libre",
            audiences=tuple(row["evidence_audiences"]), rights=tuple(row["rights"]),
            policy_visibility="public", evidence_visibility="public",
            programme_version=row["programme_version"], target_audience="libre",
            target_candidates=("libre",),
        )
    programme = (
        "services/rag-pedago/data/releases/prerentree_2026_2027/"
        "profile_gate_v4/release-024f8625ebfeb7ce/profile_gate/programme_registry.json"
    )
    registry = emitter.PolicyRegistry(
        entries=entries,
        visibility_restriction_order=("public", "internal", "restricted", "private"),
        school_year="2026-2027", programme_authority_path=programme,
        programme_authority_sha256=hashlib.sha256((root / programme).read_bytes()).hexdigest(),
        release_manifest_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(emitter, "load_policy_registry", lambda *_: registry)
    monkeypatch.setattr(emitter, "load_successor_authority", lambda *_: named)
    output = tmp_path / "scopes"
    with pytest.raises(emitter.ScopeEmissionError, match="student_public"):
        emitter.emit_from_policy_registry(
            subject_release=candidate,
            subject_release_sha256=registry.release_manifest_sha256,
            policy_registry=tmp_path / "unused-policy", policy_registry_sha256="a" * 64,
            successor_authority=tmp_path / "unused-names",
            successor_authority_sha256="b" * 64,
            artifacts_dir=output, repo_root=root,
        )
    assert not output.exists()


def _proposal(**overrides: object) -> emitter.PolicyRegistryEntry:
    entry = emitter.PolicyRegistryEntry(
        collection="rag_nexus_dgemc_terminale_option",
        decision_status="GOVERNED_BY_HUMAN_DECISION",
        authority_source="NEXUS_HUMAN_DECISION_ADR_0064",
        policy_source_scope_id=None,
        subject_manifest_sha256="a" * 64,
        tenant="libre_terminale",
        niveau="terminale",
        voie="generale",
        matiere="dgemc",
        statut_enseignement="option",
        candidat="libre",
        audiences=("libre", "aefe"),
        rights=("public_allowed",),
        policy_visibility="public",
        evidence_visibility="public",
        programme_version="BOEN_special_8_2019-07-25_MENE1921266A_MENE2208320A",
        target_audience="libre",
        target_candidates=("libre",),
    )
    return replace(entry, **overrides)


@pytest.mark.parametrize(
    "collection,predecessor_id",
    sorted(EXPECTED_PREDECESSORS.items()),
)
def test_adr_0064_is_limited_to_the_eleven_existing_policies(
    collection: str, predecessor_id: str
) -> None:
    source = load_retrieval_scope_artifact(predecessor_id)
    evidence = source.evidence_subject
    target = source.target_identity
    entry = _proposal(
        collection=collection,
        tenant=target.tenant,
        niveau=target.niveau,
        voie=target.voie,
        matiere=target.matiere,
        statut_enseignement=target.statut_enseignement,
        candidat=evidence.candidat.value,
        audiences=("libre", "aefe"),
        programme_version=evidence.programme_version,
    )
    emitter._require_human_decision_is_declared_as_such(entry)


@pytest.mark.parametrize(
    "field,value",
    [
        ("collection", "rag_nexus_anglais_terminale"),
        ("rights", ("usage_interne",)),
        ("rights", ("officiel_public",)),
        ("rights", ("officiel_public", "nexus_proprietaire")),
        ("policy_visibility", "internal"),
        ("evidence_visibility", "internal"),
        ("target_audience", "aefe"),
        ("target_candidates", ("scolaire",)),
        ("candidat", "scolaire"),
        ("audiences", ("aefe",)),
        ("policy_source_scope_id", "prod_dgemc_terminale_option_v3"),
    ],
)
def test_adr_0064_refuses_wider_or_disguised_policy(field: str, value: object) -> None:
    with pytest.raises(emitter.ScopeEmissionError):
        emitter._require_human_decision_is_declared_as_such(_proposal(**{field: value}))


@pytest.mark.parametrize(
    "scope_id",
    (
        "prod_hggsp_premiere_specialite_v3",
        "prod_hggsp_terminale_specialite_v3",
    ),
)
def test_hggsp_successor_id_cannot_be_reissued_with_other_bytes(scope_id: str) -> None:
    pinned = load_retrieval_scope_artifact(scope_id)
    changed = pinned.model_copy(update={"source_sha256": "f" * 64})
    with pytest.raises(emitter.ScopeEmissionError, match="collision de scope_id"):
        emitter._require_registry_reuse_is_a_strict_reproduction(scope_id, changed)


@pytest.mark.parametrize(
    "scope_id",
    (
        "prod_hggsp_premiere_specialite_v3",
        "prod_hggsp_terminale_specialite_v3",
    ),
)
def test_hggsp_successor_subject_is_found_by_existing_match(scope_id: str) -> None:
    pinned = load_retrieval_scope_artifact(scope_id)
    assert emitter.exact_existing_matches(
        str(pinned.evidence_subject.collection), pinned.source_sha256
    ) == (scope_id,)
