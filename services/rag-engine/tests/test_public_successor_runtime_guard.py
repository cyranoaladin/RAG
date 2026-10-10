"""A candidat ne devient servable qu'avec C et une readiness V2 signée."""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import HTTPException
from nexus_contracts import RetrievalScopeArtifactV3
from nexus_contracts.production_readiness import (
    ProductionReadinessManifestV2,
    sign_production_readiness_manifest_v2,
)

from src.ingestor import retrieval_v2_endpoint as endpoint

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import deploy_verified_release_cli as deploy  # noqa: E402

COLLECTION = "rag_nexus_maths_premiere_gen_specialite"
MANIFEST_SHA = "6" * 64
ANCHOR_SHA = "a" * 64
ENVELOPE_SHA = "b" * 64
REGISTRY_SHA = "c" * 64
SCOPE_AUTHORITY_SHA = "d" * 64
SUBJECT_SHA = "e" * 64
RELEASE_ID = "student-public-successor-test"
SEED = "11" * 32
KEY_ID = "nexus-readiness-test-1"


@dataclass(frozen=True)
class _VerifiedC:
    release_id: str = RELEASE_ID
    content_anchor_sha256: str = ANCHOR_SHA
    content_manifest_sha256: str = MANIFEST_SHA
    authority_envelope_sha256: str = ENVELOPE_SHA
    release_registry_sha256: str = REGISTRY_SHA
    scope_authority_sha256: str = SCOPE_AUTHORITY_SHA
    subject_sha256_by_collection: tuple[tuple[str, str], ...] = ((COLLECTION, SUBJECT_SHA),)
    counts: tuple[int, int, int, int] = (1, 1, 1, 1)
    expires_at_utc: str = "2026-10-11T00:00:00Z"


def _registry(*, subject_sha: str = SUBJECT_SHA) -> SimpleNamespace:
    expectation = SimpleNamespace(
        release_kind="MULTILEVEL_AGGREGATE_RELEASE_V2",
        release_id=RELEASE_ID,
        release_mode="candidate",
        promotion_status="NOT_PROMOTABLE",
        activation_status="NO_PRODUCTION_ACTIVATION",
        review_status="PRE_REVIEW",
        collections=(COLLECTION,),
        subject_manifest_sha256_by_collection=((COLLECTION, subject_sha),),
    )
    binding = SimpleNamespace(expectation=expectation, expected_sha256=MANIFEST_SHA)
    return SimpleNamespace(
        manifests=(binding,), collections=(COLLECTION,),
        manifest_for_collection=lambda collection: binding if collection == COLLECTION else None,
    )


def _scope(*, subject_sha: str = SUBJECT_SHA, rights: str = "public_allowed") -> RetrievalScopeArtifactV3:
    return RetrievalScopeArtifactV3.model_validate(
        {
            "artifact_version": "3",
            "scope_id": "student_public_maths_premiere",
            "status": "eligible_for_promotion",
            "source_sha256": subject_sha,
            "target_policy": {
                "tenant": "nexus", "niveau": "premiere", "voie": "generale",
                "matiere": "maths", "statut_enseignement": "specialite",
                "audiences": ["libre"], "candidates": ["scolarise"],
                "roles": ["student"],
            },
            "evidence_subject": {
                "collection": COLLECTION, "tenant": "nexus", "niveau": "premiere",
                "voie": "generale", "matiere": "maths",
                "statut_enseignement": "specialite", "candidat": "scolarise",
                "audiences": ["libre"], "visibility": "public",
                "rights": [rights], "school_year": "2026-2027",
                "programme_version": "fr-national-2026",
            },
        }
    )


def _signed_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    fixture = (
        Path(__file__).resolve().parents[3]
        / "packages/contracts/tests/fixtures/legacy_v2/production_readiness_manifest_v2.json"
    )
    document = json.loads(fixture.read_bytes())
    document.update(
        public_successor_content_manifest_digest=MANIFEST_SHA,
        public_successor_content_anchor_digest=ANCHOR_SHA,
        public_successor_authority_envelope_digest=ENVELOPE_SHA,
    )
    manifest = ProductionReadinessManifestV2.model_validate(document)
    signed = sign_production_readiness_manifest_v2(
        manifest, private_key_hex=SEED, key_id=KEY_ID
    )
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    readiness_path = bundle / "readiness-manifest.json"
    readiness_path.write_bytes(signed.canonical_bytes())
    readiness_path.chmod(0o600)
    public_key = (
        Ed25519PrivateKey.from_private_bytes(bytes.fromhex(SEED))
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
        .hex()
    )
    anchor = tmp_path / "trust-anchor.json"
    anchor.write_text(json.dumps({
        "protocol_version": "NEXUS-PRODUCTION-READINESS-V1",
        "keys": [{"key_id": KEY_ID, "algorithm": "ed25519",
                  "public_key": public_key, "environment": "production"}],
    }), encoding="utf-8")
    anchor.chmod(0o600)
    monkeypatch.setattr(endpoint, "_PUBLIC_READINESS_ANCHOR", anchor, raising=False)
    monkeypatch.setenv("NEXUS_PUBLIC_SUCCESSOR_BUNDLE_ROOT", str(bundle))
    monkeypatch.setenv("NEXUS_READINESS_MANIFEST_PATH", str(readiness_path))
    monkeypatch.setenv("NEXUS_RELEASE_SHA", "a" * 40)
    monkeypatch.setenv("NEXUS_PUBLIC_SCOPE_AUTHORITY_SHA256", SCOPE_AUTHORITY_SHA)
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_SHA256", REGISTRY_SHA)
    return readiness_path, anchor


def _install_verifier(monkeypatch: pytest.MonkeyPatch, verdict: _VerifiedC) -> list[dict]:
    calls: list[dict] = []
    module = ModuleType("nexus_release_chain.public_successor_activation")
    module.PublicSuccessorActivationVerdict = _VerifiedC  # type: ignore[attr-defined]

    def verify(_root: Path, **kwargs: object) -> _VerifiedC:
        calls.append(kwargs)
        return verdict

    module.verify_public_successor_activation = verify  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return calls


@pytest.mark.parametrize("environment", ["production", "rehearsal"])
def test_candidate_is_refused_without_signed_c(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("NEXUS_ENVIRONMENT", environment)
    monkeypatch.delenv("NEXUS_PUBLIC_SUCCESSOR_BUNDLE_ROOT", raising=False)
    with pytest.raises(RuntimeError, match="public successor"):
        endpoint._validate_unpromoted_release_guard(_registry())


def test_signed_readiness_and_exact_c_can_authorize_a_without_rewriting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _signed_readiness(tmp_path, monkeypatch)
    monkeypatch.setenv("NEXUS_ENVIRONMENT", "production")
    calls = _install_verifier(monkeypatch, _VerifiedC())
    endpoint._validate_unpromoted_release_guard(_registry())
    assert len(calls) == 1
    assert calls[0]["expected_content_anchor_sha256"] == ANCHOR_SHA
    assert calls[0]["expected_authority_envelope_sha256"] == ENVELOPE_SHA
    assert calls[0]["expected_registry_sha256"] == REGISTRY_SHA
    assert calls[0]["expected_scope_authority_sha256"] == SCOPE_AUTHORITY_SHA


@pytest.mark.parametrize("tamper", ["manifest", "registry", "subject", "scope"])
def test_signed_c_cannot_authorize_different_content_or_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    _signed_readiness(tmp_path, monkeypatch)
    monkeypatch.setenv("NEXUS_ENVIRONMENT", "production")
    changes = {
        "manifest": {"content_manifest_sha256": "0" * 64},
        "registry": {"release_registry_sha256": "0" * 64},
        "subject": {"subject_sha256_by_collection": ((COLLECTION, "0" * 64),)},
        "scope": {"scope_authority_sha256": "0" * 64},
    }
    verdict = _VerifiedC(**{**_VerifiedC().__dict__, **changes[tamper]})
    _install_verifier(monkeypatch, verdict)
    with pytest.raises(RuntimeError, match="public successor"):
        endpoint._validate_unpromoted_release_guard(_registry())


def test_v3_scope_requires_release_and_exact_public_policy(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(endpoint, "_configured_release_registry", lambda: None)
    cfg = {"collections": {COLLECTION: {"instanciee": True}}}
    with pytest.raises(RuntimeError, match="release manifest"):
        endpoint.validate_release_startup_configuration(
            {"student_public_maths_premiere": _scope()}, cfg
        )


@pytest.mark.parametrize(
    ("scope", "reason"),
    [
        (_scope(rights="officiel_public"), "public successor scope policy"),
        (_scope(subject_sha="0" * 64), "scope source SHA"),
    ],
)
def test_candidate_v3_scope_must_match_exact_subject_and_public_rights(
    monkeypatch: pytest.MonkeyPatch, scope: RetrievalScopeArtifactV3, reason: str
) -> None:
    monkeypatch.setattr(endpoint, "_configured_release_registry", _registry)
    monkeypatch.setattr(endpoint, "_validate_unpromoted_release_guard", lambda _: None)
    cfg = {"collections": {COLLECTION: {"instanciee": True}}}
    with pytest.raises(RuntimeError, match=reason):
        endpoint.validate_release_startup_configuration({scope.scope_id: scope}, cfg)


def test_candidate_v3_scope_positive_requires_validated_release(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(endpoint, "_configured_release_registry", _registry)
    monkeypatch.setattr(endpoint, "_validate_unpromoted_release_guard", lambda _: None)
    cfg = {"collections": {COLLECTION: {"instanciee": True}}}
    endpoint.validate_release_startup_configuration(
        {"student_public_maths_premiere": _scope()}, cfg
    )


def test_candidate_v3_search_gate_refuses_missing_release_evidence(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = _scope()
    verified = SimpleNamespace(artifact=scope)
    monkeypatch.setattr(endpoint, "_v2_evidence_collections", lambda: frozenset({COLLECTION}))
    monkeypatch.setattr(endpoint, "_release_evidence_for_v2_artifact", lambda _: False)
    with pytest.raises(HTTPException) as refusal:
        endpoint._require_release_ready_if_governed(
            COLLECTION,
            {"collections": {COLLECTION: {"instanciee": True}}},
            verified=verified,
        )
    assert refusal.value.status_code == 503


def _wrapper_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, bytes, bytes, dict]:
    readiness_path, anchor_path = _signed_readiness(tmp_path, monkeypatch)
    material_root = tmp_path / "material"
    release_root = material_root / "release"
    release_root.mkdir(parents=True)
    shutil.copyfile(readiness_path, release_root / "readiness-manifest.json")
    (release_root / "readiness-manifest.json").chmod(0o600)
    environment = {
        "NEXUS_PUBLIC_SUCCESSOR_BUNDLE_ROOT": "/app/release",
        "NEXUS_READINESS_MANIFEST_PATH": "/app/release/readiness-manifest.json",
        "NEXUS_RELEASE_SHA": "a" * 40,
        "RAG_RELEASE_REGISTRY_PATH": "/app/release/release/release-registry.json",
        "RAG_RELEASE_REGISTRY_SHA256": REGISTRY_SHA,
        "NEXUS_PUBLIC_SCOPE_AUTHORITY_SHA256": SCOPE_AUTHORITY_SHA,
    }
    return (
        material_root,
        readiness_path.read_bytes(),
        anchor_path.read_bytes(),
        {"services": {"ingestor": {"environment": environment}}},
    )


def test_blue_green_wrapper_requires_signed_a_c_before_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    material_root, signed_raw, anchor_raw, compose = _wrapper_inputs(tmp_path, monkeypatch)
    calls = _install_verifier(monkeypatch, _VerifiedC())
    monkeypatch.setattr(deploy, "load_release_registry_file", lambda *_: _registry(), raising=False)
    deploy.require_public_successor_bundle_for_deploy(
        material_root=material_root,
        resolved_compose=compose,
        readiness_manifest_raw=signed_raw,
        trusted_readiness_anchor_raw=anchor_raw,
        merge_sha="a" * 40,
    )
    assert len(calls) == 1
    assert calls[0]["expected_content_anchor_sha256"] == ANCHOR_SHA


@pytest.mark.parametrize("tamper", ["material_readiness", "scope", "subject"])
def test_blue_green_wrapper_refuses_tampering_before_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    material_root, signed_raw, anchor_raw, compose = _wrapper_inputs(tmp_path, monkeypatch)
    verdict = _VerifiedC()
    if tamper == "material_readiness":
        (material_root / "release/readiness-manifest.json").write_bytes(b"substituted")
    elif tamper == "scope":
        compose["services"]["ingestor"]["environment"]["NEXUS_PUBLIC_SCOPE_AUTHORITY_SHA256"] = "0" * 64
    else:
        verdict = _VerifiedC(**{
            **verdict.__dict__,
            "subject_sha256_by_collection": ((COLLECTION, "0" * 64),),
        })
    _install_verifier(monkeypatch, verdict)
    monkeypatch.setattr(deploy, "load_release_registry_file", lambda *_: _registry(), raising=False)
    with pytest.raises(deploy.DeploymentWrapperError, match="public successor"):
        deploy.require_public_successor_bundle_for_deploy(
            material_root=material_root,
            resolved_compose=compose,
            readiness_manifest_raw=signed_raw,
            trusted_readiness_anchor_raw=anchor_raw,
            merge_sha="a" * 40,
        )


def test_docker_wrapper_refuses_old_public_plan_without_c_before_mutation(
    tmp_path: Path
) -> None:
    from tests.test_public_atomic_deploy import _inputs

    _, _, _, options = _inputs(tmp_path)
    options["run_subprocess"] = lambda *_: pytest.fail("Docker mutation called before C")
    with pytest.raises(deploy.DeploymentWrapperError, match="public successor"):
        deploy.deploy_from_bundle(**options)
