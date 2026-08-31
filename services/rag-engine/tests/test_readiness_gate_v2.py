from __future__ import annotations

import dataclasses
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "scripts"))
sys.path.insert(0, str(ENGINE_ROOT / "tests"))

import sign_production_readiness_manifest_cli as signer  # noqa: E402
from nexus_contracts.production_readiness import (  # noqa: E402
    PRODUCTION_READINESS_V2_PROTOCOL_VERSION,
    public_readiness_key_hex,
    sign_production_readiness_manifest_v2,
)
from test_sign_production_readiness_manifest_cli import (  # noqa: E402
    PR_HEAD_SHA,
    PR_NUMBER,
    TEST_KEY_ID,
    TEST_SEED,
    V2_NOW,
    _v2_material,
)

from ingestor.ingestion_profiles import readiness_gate as gate  # noqa: E402


@pytest.fixture(autouse=True)
def _pin_v2_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    class FixtureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return V2_NOW

    monkeypatch.setenv(
        gate.EXPECTED_PROTOCOL_ENV, "NEXUS-PRODUCTION-READINESS-V2"
    )
    monkeypatch.setattr(gate, "datetime", FixtureClock)


def _anchor() -> bytes:
    return json.dumps(
        {
            "protocol_version": "NEXUS-PRODUCTION-READINESS-V1",
            "keys": [
                {
                    "key_id": TEST_KEY_ID,
                    "algorithm": "ed25519",
                    "public_key": public_readiness_key_hex(TEST_SEED),
                    "environment": "production",
                }
            ],
        }
    ).encode()


def _signed(material: signer.V2ReleaseMaterial) -> bytes:
    return _sign_manifest(_manifest(material))


def _manifest(material: signer.V2ReleaseMaterial):
    manifest = signer.assemble_and_sign_v2(
        material,
        repository="cyranoaladin/RAG",
        pr_number=PR_NUMBER,
        pr_head_sha=PR_HEAD_SHA,
        pr_head_tree_sha=material.merge_tree_sha,
        application_image_digests={
            "ingestion-worker": "ghcr.io/o/rag-ingestion-worker@sha256:" + "1" * 64
        },
        upstream_image_digests={
            "pgvector": "pgvector/pgvector@sha256:" + "3" * 64
        },
        compose_digest="8" * 64,
        key_id=TEST_KEY_ID,
        workflow_ref="refs/heads/main",
    )
    assert manifest.protocol_version == PRODUCTION_READINESS_V2_PROTOCOL_VERSION
    return manifest


def _sign_manifest(manifest) -> bytes:
    return sign_production_readiness_manifest_v2(
        manifest, private_key_hex=TEST_SEED, key_id=TEST_KEY_ID
    ).canonical_bytes()


def _write(tmp_path: Path, name: str, raw: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(raw)
    path.chmod(0o444)
    return path


def _install_anchor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "root"
    for marker in gate._GOVERNED_ROOT_MARKERS:
        (root / marker).mkdir(parents=True, exist_ok=True)
    anchor = root / gate.GOVERNED_TRUST_ANCHOR_PATH
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_bytes(_anchor())
    monkeypatch.setattr(gate, "_GOVERNED_REPOSITORY_ROOT", root)


def _write_runtime_material_root(
    tmp_path: Path, material: signer.V2ReleaseMaterial
) -> Path:
    root = tmp_path / "v2-material"
    root.mkdir()
    fixed = {
        "evidence/review_binding_trust_anchor.bin": material.review_binding_trust_anchor_raw,
        "evidence/trusted_reviewers.bin": material.trusted_reviewers_raw,
        "authorization-revocations.json": material.revocation_registry_raw,
        "release-scope-placement.jsonl": material.release_scope_placement_raw,
        "profile-manifest.yml": material.profile_manifest_raw,
        "h2-coverage.json": material.h2_coverage_raw,
        "h2-evidence.json": material.h2_evidence_bundle_raw,
        "promotion-evidence.json": material.promotion_evidence_raw,
        "sealed-manifest.txt": material.sealed_manifest_raw,
        "authority-required.txt": (
            "\n".join(material.authority_required_content_sha256) + "\n"
        ).encode(),
        "verified-profiles.json": (
            json.dumps(
                {
                    "profile_manifest_digest": signer.parse_authorization_set(
                        material.authorization_set_raw
                    ).profile_manifest_digest,
                    "profiles": [
                        fact.model_dump(mode="json") for fact in material.verified_profiles
                    ],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode(),
        "bundle_manifest.json": json.dumps(
            {
                "v2_release_scope_git_paths": dict(
                    material.release_scope_git_paths
                )
            }
        ).encode(),
    }
    for relative, raw in {
        **fixed,
        **{
            f"release-material/{relative}": value
            for relative, value in material.release_files.items()
        },
        **{
            f"evidence/{name}.bin": value
            for name, value in material.evidence_files.items()
        },
        **{
            f"release-scope-sources/{name}": value
            for name, value in material.release_scope_source_blobs.items()
        },
    }.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return root


def test_v2_readiness_returns_one_exact_immutable_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    material = _v2_material()
    _install_anchor(monkeypatch, tmp_path)
    path = _write(tmp_path, "readiness.json", _signed(material))

    result = gate.enforce_readiness_gate(
        manifest_path=path,
        release_sha=material.merge_sha,
        v2_material=gate.RuntimeV2ReleaseMaterial.from_signing_material(material),
    )

    assert result.authorization_mapping is not None
    content = material.authority_required_content_sha256[0]
    assert result.authorization_mapping.authorization_id_for_content(content)
    assert result.manifest.authorization_set_digest == (
        result.authorization_mapping.authorization_set_digest
    )


def test_v2_production_path_loads_the_exact_set_and_release_material_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    material = _v2_material()
    _install_anchor(monkeypatch, tmp_path)
    readiness = _write(tmp_path, "readiness.json", _signed(material))
    authorization_set = _write(
        tmp_path, "authorization-set.json", material.authorization_set_raw
    )
    root = _write_runtime_material_root(tmp_path, material)
    monkeypatch.setenv(gate.AUTHORIZATION_SET_PATH_ENV, str(authorization_set))
    monkeypatch.setenv(gate.V2_MATERIAL_ROOT_ENV, str(root))

    result = gate.enforce_readiness_gate(
        manifest_path=readiness, release_sha=material.merge_sha
    )

    assert result.authorization_mapping is not None


def test_runtime_context_rereads_revocations_bindings_and_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    material = _v2_material()
    _install_anchor(monkeypatch, tmp_path)
    readiness = _write(tmp_path, "readiness.json", _signed(material))
    authorization_set = _write(
        tmp_path, "authorization-set.json", material.authorization_set_raw
    )
    root = _write_runtime_material_root(tmp_path, material)
    monkeypatch.setenv(gate.AUTHORIZATION_SET_PATH_ENV, str(authorization_set))
    monkeypatch.setenv(gate.V2_MATERIAL_ROOT_ENV, str(root))

    result = gate.enforce_readiness_gate(
        manifest_path=readiness, release_sha=material.merge_sha
    )
    assert result.authorization_context is not None
    assert result.authorization_context.reverify() == result.authorization_mapping

    original_readiness = readiness.read_bytes()
    changed_readiness = _manifest(material).model_copy(
        update={"workflow_ref": "refs/tags/changed-after-startup"}
    )
    readiness.chmod(0o600)
    readiness.write_bytes(_sign_manifest(changed_readiness))
    readiness.chmod(0o444)
    with pytest.raises(gate.ReadinessGateError, match="readiness bytes changed"):
        result.authorization_context.reverify()
    readiness.chmod(0o600)
    readiness.write_bytes(original_readiness)
    readiness.chmod(0o444)

    member = signer.parse_authorization_set(material.authorization_set_raw).members[0]
    binding = root / "release-material" / member.review_binding_path
    original_binding = binding.read_bytes()
    binding.write_bytes(b"{}\n")
    with pytest.raises(gate.ReadinessGateError, match="refused"):
        result.authorization_context.reverify()
    binding.write_bytes(original_binding)

    revoked = (
        json.dumps(
            {
                "protocol_version": "NEXUS-AUTHORIZATION-REVOCATIONS-V1",
                "revoked_authorization_ids": [member.authorization_id],
            },
            indent=2,
            sort_keys=True,
        ).encode()
        + b"\n"
    )
    (root / "authorization-revocations.json").write_bytes(revoked)
    (root / "evidence/authority_revocations.bin").write_bytes(revoked)
    with pytest.raises(gate.ReadinessGateError, match="revoked|digest|refused"):
        result.authorization_context.reverify()

    (root / "authorization-revocations.json").write_bytes(
        material.revocation_registry_raw
    )
    (root / "evidence/authority_revocations.bin").write_bytes(
        material.revocation_registry_raw
    )

    class ExpiredClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2030, 1, 1, tzinfo=UTC)

    monkeypatch.setattr(gate, "datetime", ExpiredClock)
    with pytest.raises(gate.ReadinessGateError, match="expired|refused"):
        result.authorization_context.reverify()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("workflow_path", ".github/workflows/production-image-provenance.yml"),
        ("workflow_ref", "refs/tags/substituted"),
        ("run_id", 7654321),
        ("run_attempt", 9),
        ("catalog_digest", "a" * 64),
        ("trust_anchor_digest", "b" * 64),
        ("sealed_manifest_digest", "c" * 64),
    ],
)
def test_v2_startup_refuses_each_substituted_signed_release_fact(
    field: str,
    value: str | int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = _v2_material()
    substituted = _manifest(material).model_copy(update={field: value})
    _install_anchor(monkeypatch, tmp_path)
    path = _write(tmp_path, "readiness.json", _sign_manifest(substituted))

    with pytest.raises(gate.ReadinessGateError, match="mismatch|refused"):
        gate.enforce_readiness_gate(
            manifest_path=path,
            release_sha=material.merge_sha,
            v2_material=gate.RuntimeV2ReleaseMaterial.from_signing_material(material),
        )


@pytest.mark.parametrize(
    ("field", "substitution"),
    [
        ("sealed_manifest_raw", b"substituted sealed manifest\n"),
        ("review_binding_trust_anchor_raw", b"{}\n"),
    ],
)
def test_v2_startup_refuses_substituted_exact_release_bytes(
    field: str,
    substitution: bytes,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = _v2_material()
    signed = _signed(material)
    runtime = gate.RuntimeV2ReleaseMaterial.from_signing_material(material)
    assert "sealed_manifest_raw" in runtime.__dataclass_fields__
    runtime = dataclasses.replace(runtime, **{field: substitution})
    _install_anchor(monkeypatch, tmp_path)
    path = _write(tmp_path, "readiness.json", signed)

    with pytest.raises(gate.ReadinessGateError, match="refused|digest|manifest"):
        gate.enforce_readiness_gate(
            manifest_path=path,
            release_sha=material.merge_sha,
            v2_material=runtime,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("revoked", "revoked"),
        ("expired", "expired"),
        ("changed_set", "authorization set"),
    ],
)
def test_v2_startup_refuses_invalid_live_authority_material(
    mutation: str,
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = _v2_material()
    signed = _signed(material)
    if mutation == "revoked":
        material = dataclasses.replace(
            material,
            revocation_registry_raw=json.dumps(
                {
                    "protocol_version": "NEXUS-AUTHORIZATION-REVOCATIONS-V1",
                    "revoked_authorization_ids": [
                        next(iter(signer.parse_authorization_set(material.authorization_set_raw).members)).authorization_id
                    ],
                },
                sort_keys=True,
                indent=2,
            ).encode()
            + b"\n",
        )
    elif mutation == "expired":
        material = dataclasses.replace(material, now=datetime(2030, 1, 1, tzinfo=UTC))
    else:
        material = dataclasses.replace(material, authorization_set_raw=b"{}\n")
    _install_anchor(monkeypatch, tmp_path)
    path = _write(tmp_path, "readiness.json", signed)

    with pytest.raises(gate.ReadinessGateError, match=message):
        gate.enforce_readiness_gate(
            manifest_path=path,
            release_sha=material.merge_sha,
            v2_material=gate.RuntimeV2ReleaseMaterial.from_signing_material(material),
        )


def test_v1_remains_explicitly_legacy_without_an_authorization_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_readiness_gate import _anchor_bytes, _install_governed_root, _write_manifest

    _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())
    monkeypatch.setenv(
        gate.EXPECTED_PROTOCOL_ENV, "NEXUS-PRODUCTION-READINESS-V1"
    )
    result = gate.enforce_readiness_gate(
        manifest_path=_write_manifest(tmp_path), release_sha="a" * 40
    )

    assert result.authorization_mapping is None


def test_valid_v1_is_refused_when_runtime_requires_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_readiness_gate import _anchor_bytes, _install_governed_root, _write_manifest

    _install_governed_root(monkeypatch, tmp_path, anchor=_anchor_bytes())

    with pytest.raises(gate.ReadinessGateError, match="differs from expected"):
        gate.enforce_readiness_gate(
            manifest_path=_write_manifest(tmp_path), release_sha="a" * 40
        )


@pytest.mark.parametrize("configured", [None, "unknown-protocol"])
def test_runtime_refuses_missing_or_unknown_expected_protocol(
    configured: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = _v2_material()
    _install_anchor(monkeypatch, tmp_path)
    path = _write(tmp_path, "readiness.json", _signed(material))
    if configured is None:
        monkeypatch.delenv(gate.EXPECTED_PROTOCOL_ENV, raising=False)
    else:
        monkeypatch.setenv(gate.EXPECTED_PROTOCOL_ENV, configured)

    with pytest.raises(gate.ReadinessGateError, match="explicitly pin V1 or V2"):
        gate.enforce_readiness_gate(
            manifest_path=path,
            release_sha=material.merge_sha,
            v2_material=gate.RuntimeV2ReleaseMaterial.from_signing_material(material),
        )
