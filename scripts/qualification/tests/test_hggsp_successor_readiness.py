"""La readiness HGGSP lie ses deux images et son périmètre signé."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/go_live/hggsp_successor_readiness.py"


def _module():
    spec = importlib.util.spec_from_file_location("hggsp_successor_readiness", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _anchor(seed: str) -> bytes:
    public = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed)).public_key()
    key = public.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    return json.dumps({"protocol_version": "NEXUS-STAGING-READINESS-V1", "keys": [{
        "key_id": "nexus-rehearsal-readiness-20260920-01", "algorithm": "ed25519",
        "public_key": key, "environment": "rehearsal"
    }]}).encode()


def test_bundle_roundtrip_and_v4_rejected() -> None:
    module = _module()
    seed = "01" * 32  # fixture locale ; jamais un secret opérateur
    now = datetime(2026, 9, 28, tzinfo=UTC)
    v1, binding = module.sign_bundle(seed=seed, key_id=module.KEY_ID, issued_at=now)
    verified = module.verify_bundle(v1, binding, trust_anchor_raw=_anchor(seed), now=now)
    assert verified["release_id"] == module.RELEASE_ID
    assert verified["worker_image"] == module.WORKER_IMAGE
    assert verified["retrieval_image"] == module.RETRIEVAL_IMAGE
    assert verified["database"] == "ragdb_profile_gate_v4"
    assert verified["collections"] == list(module.COLLECTIONS)
    assert verified["source_commit"] == "a9e3701965503d2862a248c46fd7e7e175058c8f"
    assert verified["worker_image"] == (
        "ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:"
        "2228650e2245ea2fdc45d442a78363fd362781c2f80e2270618eedca0abf9bcf"
    )
    assert verified["retrieval_image"] == (
        "ghcr.io/cyranoaladin/rag-ingestor@sha256:"
        "11aa98d58ebcd10ee09543d4791f63b67542b764ab0484f004cccc8d43e86caf"
    )

    wrong = json.loads(v1)
    wrong["manifest"]["allowed_release_id"] = "production-profile-gate-2026-2027-v4"
    with pytest.raises(module.ReadinessRefuse):
        module.verify_bundle(json.dumps(wrong).encode(), binding, trust_anchor_raw=_anchor(seed), now=now)


@pytest.mark.parametrize("field,value", [
    ("worker_image", "ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:" + "0" * 64),
    ("retrieval_image", "ghcr.io/cyranoaladin/rag-ingestor@sha256:" + "0" * 64),
    ("database", "ragdb"),
    ("collections", ["rag_nexus_hggsp_premiere_specialite"]),
    ("mixed_registry_sha256", "0" * 64),
    ("manifest_sha256", "0" * 64),
    ("source_commit", "26062eb1a1d7e8645a9a213fbf3de42ba88383fa"),
    ("release_id", "production-profile-gate-2026-2027-v4"),
])
def test_wrong_signed_binding_fact_rejected(field: str, value: object) -> None:
    module = _module()
    seed = "01" * 32
    now = datetime(2026, 9, 28, tzinfo=UTC)
    v1, binding = module.sign_bundle(seed=seed, key_id=module.KEY_ID, issued_at=now)
    payload = json.loads(binding)
    payload["binding"][field] = value
    with pytest.raises(module.ReadinessRefuse):
        module.verify_bundle(v1, json.dumps(payload).encode(), trust_anchor_raw=_anchor(seed), now=now)


def test_cli_denies_unapproved_head_before_reading_seed_or_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un fichier actif sur main ne remplace pas la revue fusionnée au HEAD."""
    module = _module()
    auth_raw = (ROOT / module.AUTH_PATH).read_bytes()
    monkeypatch.setattr(
        module.subprocess, "run",
        lambda *_a, **_kw: subprocess.CompletedProcess([], 0, stdout=auth_raw),
    )
    checker = module._authorization_checker(ROOT)
    monkeypatch.setattr(module, "_authorization_checker", lambda _root: checker)
    calls: list[tuple[Path, str, dict]] = []

    def deny(root: Path, operation: str, target: dict) -> list[str]:
        calls.append((root, operation, target))
        return ["approbation au HEAD exact absente"]

    monkeypatch.setattr(
        checker, "verifier_operation_hggsp", deny,
    )
    seed = tmp_path / "seed"
    seed.write_text("01" * 32)
    seed.chmod(0o600)
    output = tmp_path / "bundle"
    original_read_text = Path.read_text

    def read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path == seed:
            pytest.fail("la graine a été lue avant la revue de l'activation")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    assert module.main(["sign", "--private-key-file", str(seed), "--output-dir", str(output)]) == 1
    assert not output.exists()
    assert calls == [(
        ROOT, "successor_readiness_sign",
        checker.OPERATIONS_HGGSP["successor_readiness_sign"]["cible"],
    )]


def test_cli_denies_branch_only_authorization_before_reading_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    seed = tmp_path / "seed"
    seed.write_text("01" * 32)
    seed.chmod(0o600)
    monkeypatch.setattr(
        module.subprocess, "run",
        lambda *_a, **_kw: subprocess.CompletedProcess([], 128, stdout=b""),
    )
    original_read_text = Path.read_text

    def read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path == seed:
            pytest.fail("la graine a été lue malgré l'absence de l'autorisation dans main")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    assert module.main([
        "sign", "--private-key-file", str(seed),
        "--output-dir", str(tmp_path / "bundle"),
    ]) == 1
    assert not (tmp_path / "bundle").exists()
