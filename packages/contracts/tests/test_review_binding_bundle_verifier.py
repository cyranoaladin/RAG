"""Tests du vérificateur de bundle de ReviewBindings réels et preuve des cas de rejet négatif."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from nexus_contracts.authority_artifacts import canonical_authorization_path, git_blob_sha1
from nexus_contracts.review_binding import (
    REVIEW_BINDING_PROTOCOL_VERSION,
    TRUSTED_REVIEW_PROTOCOL,
    ScopeAuthorizationReviewBindingV1,
    TrustAnchor,
    expected_challenge_digest,
    parse_trust_anchor,
    public_key_hex,
    sign_review_binding,
)

# Importer verify_bundle depuis le script de gestion
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from review_binding_bundle_manager import (
    CANONICAL_AUTHORIZATION_IDS,
    EXPECTED_COUNT,
    EXPECTED_HEAD_SHA,
    EXPECTED_KEY_ID,
    EXPECTED_PR_NUMBER,
    EXPECTED_REPOSITORY,
    verify_bundle,
)

TEST_SEED = "33" * 32
TEST_PUBLIC_KEY = public_key_hex(TEST_SEED)
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _build_test_trust_anchor(tmp_path: Path, key_id: str = EXPECTED_KEY_ID, public_key: str = TEST_PUBLIC_KEY) -> Path:
    anchor_doc = {
        "protocol_version": REVIEW_BINDING_PROTOCOL_VERSION,
        "keys": [
            {
                "algorithm": "ed25519",
                "environment": "production",
                "key_id": key_id,
                "public_key": public_key,
                "comment": "Test mock production anchor",
            }
        ],
    }
    p = tmp_path / "trust-anchor.json"
    p.write_text(json.dumps(anchor_doc), encoding="utf-8")
    return p


def _build_valid_fixture_bundle(tmp_path: Path, anchor_path: Path, seed: str = TEST_SEED, key_id: str = EXPECTED_KEY_ID, head_sha: str = EXPECTED_HEAD_SHA) -> Path:
    bundle_dir = tmp_path / "review-bindings"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    author = "mock-author"
    reviewer = "mock-reviewer"
    base_sha = "0" * 40

    challenge_dig = expected_challenge_digest(
        repository=EXPECTED_REPOSITORY,
        pull_request=EXPECTED_PR_NUMBER,
        base_ref="main",
        base_sha=base_sha,
        head_sha=head_sha,
        author=author,
        reviewer=reviewer,
    )

    # Récupérer les vrais octets des autorisations depuis Git
    import subprocess
    for aid in CANONICAL_AUTHORIZATION_IDS:
        rel_path = canonical_authorization_path(aid)
        auth_bytes = subprocess.check_output(["git", "show", f"origin/rag-pedago/production-authorizations-20260825:{rel_path}"])
        blob_sha1 = git_blob_sha1(auth_bytes)
        auth_sha256 = hashlib.sha256(auth_bytes).hexdigest()

        binding = ScopeAuthorizationReviewBindingV1(
            protocol_version=REVIEW_BINDING_PROTOCOL_VERSION,
            repository=EXPECTED_REPOSITORY,
            pull_request=EXPECTED_PR_NUMBER,
            base_ref="main",
            base_sha=base_sha,
            head_sha=head_sha,
            authorization_artifact_path=rel_path,
            authorization_artifact_sha256=auth_sha256,
            authorization_artifact_git_blob_sha1=blob_sha1,
            authorization_id=aid,
            authorization_decision="AUTHORIZE_INGESTION_SCOPE",
            author_login=author,
            reviewer_login=reviewer,
            reviewer_permission="admin",
            challenge_protocol=TRUSTED_REVIEW_PROTOCOL,
            challenge_digest=challenge_dig,
            review_id=123456,
            submitted_at=NOW,
            verified_at=NOW,
            expires_at=datetime(2026, 9, 27, 12, 0, tzinfo=UTC),
            verifier_version="nexus-review-binding-producer/1",
        )

        signed = sign_review_binding(binding, private_key_hex=seed, key_id=key_id)
        out_file = bundle_dir / f"{aid}.binding.json"
        out_file.write_bytes(signed.canonical_bytes())

    return bundle_dir


def test_bundle_verifier_passes_on_valid_bundle(tmp_path: Path) -> None:
    anchor_path = _build_test_trust_anchor(tmp_path)
    bundle_dir = _build_valid_fixture_bundle(tmp_path, anchor_path)

    res = verify_bundle(
        bundle_dir=bundle_dir,
        trust_anchor_path=anchor_path,
        now=NOW,
    )

    assert res["REVIEW_BINDING_BUNDLE_VERIFICATION"] == "PASS"
    assert res["EXPECTED_BINDINGS"] == 18
    assert res["FOUND_BINDINGS"] == 18
    assert res["MISSING"] == 0
    assert res["UNEXPECTED"] == 0
    assert res["DUPLICATES"] == 0
    assert res["SIGNATURE_VALID"] == 18
    assert res["CURRENT_KEY_ID_MATCH"] == 18
    assert res["CURRENT_TRUST_ANCHOR_MATCH"] == 18
    assert res["PR_NUMBER_MATCH"] == 18
    assert res["EXPECTED_HEAD_MATCH"] == 18
    assert res["CHALLENGE_VALID"] == 18
    assert res["AUTHORIZATION_BYTES_MATCH"] == 18
    assert res["AUTHORIZATION_SHA256_MATCH"] == 18
    assert res["errors"] == []


def test_bundle_verifier_rejects_old_trust_anchor(tmp_path: Path) -> None:
    # 1. Ancre tournée : le bundle a été signé avec TEST_SEED mais l'ancre active déclare une autre clé
    other_anchor_path = _build_test_trust_anchor(tmp_path, key_id=EXPECTED_KEY_ID, public_key=public_key_hex("44" * 32))
    bundle_dir = _build_valid_fixture_bundle(tmp_path, other_anchor_path)

    res = verify_bundle(
        bundle_dir=bundle_dir,
        trust_anchor_path=other_anchor_path,
        now=NOW,
    )
    assert res["REVIEW_BINDING_BUNDLE_VERIFICATION"] == "FAIL"
    assert res["SIGNATURE_VALID"] == 0
    assert any("not sealed by an approved signer" in e for e in res["errors"])


def test_bundle_verifier_rejects_stale_head(tmp_path: Path) -> None:
    # 2. stale HEAD binding
    anchor_path = _build_test_trust_anchor(tmp_path)
    bundle_dir = _build_valid_fixture_bundle(tmp_path, anchor_path, head_sha="c" * 40)

    res = verify_bundle(
        bundle_dir=bundle_dir,
        trust_anchor_path=anchor_path,
        expected_head=EXPECTED_HEAD_SHA,
        now=NOW,
    )
    assert res["REVIEW_BINDING_BUNDLE_VERIFICATION"] == "FAIL"
    assert res["EXPECTED_HEAD_MATCH"] == 0
    assert any("HEAD mismatch" in e for e in res["errors"])


def test_bundle_verifier_rejects_tampered_authorization_bytes(tmp_path: Path) -> None:
    # 3. tampered authorization bytes (simulation: le binding pointe sur un digest modifié)
    anchor_path = _build_test_trust_anchor(tmp_path)
    bundle_dir = _build_valid_fixture_bundle(tmp_path, anchor_path)

    # Modifier un fichier de binding pour qu'il altère le digest attendu
    target_aid = CANONICAL_AUTHORIZATION_IDS[0]
    bf = bundle_dir / f"{target_aid}.binding.json"
    doc = json.loads(bf.read_text(encoding="utf-8"))
    doc["binding"]["authorization_artifact_sha256"] = "f" * 64
    # Re-signer frauduleusement avec la clé
    from nexus_contracts.review_binding import ScopeAuthorizationReviewBindingV1
    b_obj = ScopeAuthorizationReviewBindingV1.model_validate(doc["binding"])
    re_signed = sign_review_binding(b_obj, private_key_hex=TEST_SEED, key_id=EXPECTED_KEY_ID)
    bf.write_bytes(re_signed.canonical_bytes())

    res = verify_bundle(
        bundle_dir=bundle_dir,
        trust_anchor_path=anchor_path,
        now=NOW,
    )
    assert res["REVIEW_BINDING_BUNDLE_VERIFICATION"] == "FAIL"
    assert res["AUTHORIZATION_SHA256_MATCH"] == 17
    assert any("different authorization bytes" in e for e in res["errors"])


def test_bundle_verifier_rejects_tampered_binding_file(tmp_path: Path) -> None:
    # 4. tampered binding (altération d'un octet dans le fichier json sans resigner)
    anchor_path = _build_test_trust_anchor(tmp_path)
    bundle_dir = _build_valid_fixture_bundle(tmp_path, anchor_path)

    target_aid = CANONICAL_AUTHORIZATION_IDS[0]
    bf = bundle_dir / f"{target_aid}.binding.json"
    raw = bf.read_bytes()
    # Remplacer un caractère
    raw_tampered = raw.replace(b"mock-reviewer", b"evil-reviewer")
    bf.write_bytes(raw_tampered)

    res = verify_bundle(
        bundle_dir=bundle_dir,
        trust_anchor_path=anchor_path,
        now=NOW,
    )
    assert res["REVIEW_BINDING_BUNDLE_VERIFICATION"] == "FAIL"
    assert any("binding_digest does not describe the receipt" in e or "not in canonical form" in e for e in res["errors"])


def test_bundle_verifier_rejects_missing_binding(tmp_path: Path) -> None:
    # 5. missing binding (17 au lieu de 18)
    anchor_path = _build_test_trust_anchor(tmp_path)
    bundle_dir = _build_valid_fixture_bundle(tmp_path, anchor_path)

    target_aid = CANONICAL_AUTHORIZATION_IDS[0]
    (bundle_dir / f"{target_aid}.binding.json").unlink()

    res = verify_bundle(
        bundle_dir=bundle_dir,
        trust_anchor_path=anchor_path,
        now=NOW,
    )
    assert res["REVIEW_BINDING_BUNDLE_VERIFICATION"] == "FAIL"
    assert res["MISSING"] == 1
    assert res["FOUND_BINDINGS"] == 17
    assert any("Bindings manquants" in e for e in res["errors"])


def test_bundle_verifier_rejects_unexpected_nineteenth_binding(tmp_path: Path) -> None:
    # 6. unexpected nineteenth binding (19 au lieu de 18)
    anchor_path = _build_test_trust_anchor(tmp_path)
    bundle_dir = _build_valid_fixture_bundle(tmp_path, anchor_path)

    extra_file = bundle_dir / "prerentree-2026-2027-rag_nexus_extra_invalid-v1.binding.json"
    # Copier un existant
    shutil.copy(bundle_dir / f"{CANONICAL_AUTHORIZATION_IDS[0]}.binding.json", extra_file)

    res = verify_bundle(
        bundle_dir=bundle_dir,
        trust_anchor_path=anchor_path,
        now=NOW,
    )
    assert res["REVIEW_BINDING_BUNDLE_VERIFICATION"] == "FAIL"
    assert res["UNEXPECTED"] == 1
    assert res["FOUND_BINDINGS"] == 19
    assert any("Bindings inattendus" in e for e in res["errors"])
