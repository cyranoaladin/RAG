"""LOT41A public : A réel est préparé, aucune review n'est présumée."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from nexus_contracts.authority_artifacts import (
    ScopeAuthorizationArtifactV2,
    git_blob_sha1,
)
from nexus_contracts.authorization_set import (
    canonical_review_binding_path,
    scope_digest,
)
from nexus_contracts.review_binding import (
    ScopeAuthorizationReviewBindingV1,
    TrustAnchor,
    expected_challenge_digest,
    parse_trust_anchor,
    public_key_hex,
    sign_review_binding,
)
from nexus_release_chain.public_lot41a_adapter import (
    PublicLot41AError,
    build_public_lot41a_set,
)
from nexus_release_chain.public_successor_activation import (
    derive_public_release_scope_placement,
    verify_content_anchor,
)

ROOT = Path(__file__).resolve().parents[3]
RELEASE = (
    ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027"
    / "profile_gate_student_public_successor_v1/release-fcc84331e7700042"
)
ANCHOR = (
    ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261010.json"
)
ANCHOR_SHA = "159e6e25fa493325304f8c790dd67113b4c6ced72a2fa696a60799a9fe7255a0"
NOW = datetime(2026, 10, 10, 16, tzinfo=UTC)
TEST_SEED = "11" * 32


def _test_material(
    *,
    rights_categories: tuple[str, ...] = ("public_allowed",),
    pii_evidence: str | None = None,
    allowed_domains: tuple[str, ...] = ("eduscol.education.gouv.fr",),
) -> tuple[tuple[str, ...], dict[str, bytes], TrustAnchor]:
    """Onze signatures de fixture ; aucune review GitHub réelle n'est revendiquée."""
    content = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    projection = derive_public_release_scope_placement(RELEASE, content)
    pii_sha = json.loads(ANCHOR.read_bytes())["preparation_sidecars"][
        "public_pii_registry.json"
    ]
    by_scope: dict[str, list[str]] = {}
    first_entry = {}
    for entry in projection.placements:
        digest = scope_digest(entry.scope)
        by_scope.setdefault(digest, []).append(entry.content_sha256)
        first_entry[digest] = entry
    files: dict[str, bytes] = {}
    ids: list[str] = []
    for position, (digest, values) in enumerate(sorted(by_scope.items())):
        entry = first_entry[digest]
        authorization_id = f"lot41a-public-test-{position:02d}"
        ids.append(authorization_id)
        authorization = ScopeAuthorizationArtifactV2.model_validate(
            {
                "protocol_version": "LOT41A-V2",
                "authorization_id": authorization_id,
                "decision": "AUTHORIZE_INGESTION_SCOPE",
                "scope": entry.scope,
                "manifest_digest": projection.profile_manifest_digest,
                "profile_id": entry.profile_id,
                "profile_version": entry.profile_version,
                "profile_fingerprint": entry.profile_fingerprint,
                "allowed_domains": allowed_domains,
                "rights_categories": rights_categories,
                "exclusions": [],
                "pii_absence_attested": True,
                "pii_absence_evidence": pii_evidence
                or ("profile_gate/public_pii_registry.json@sha256:" + pii_sha),
                "valid_from": datetime(2026, 10, 10, 15, tzinfo=UTC),
                "valid_until": datetime(2026, 10, 11, 13, tzinfo=UTC),
                "allowed_content_sha256": sorted(set(values)),
            }
        )
        raw = authorization.canonical_bytes()
        files[authorization.canonical_path()] = raw
        binding = ScopeAuthorizationReviewBindingV1.model_validate(
            {
                "protocol_version": "NEXUS-REVIEW-BINDING-V1",
                "repository": "cyranoaladin/RAG",
                "pull_request": 777,
                "base_ref": "main",
                "base_sha": "a" * 40,
                "head_sha": "b" * 40,
                "authorization_artifact_path": authorization.canonical_path(),
                "authorization_artifact_sha256": sha256(raw).hexdigest(),
                "authorization_artifact_git_blob_sha1": git_blob_sha1(raw),
                "authorization_id": authorization_id,
                "authorization_decision": "AUTHORIZE_INGESTION_SCOPE",
                # Une seule review de PR couvre les onze fichiers au même HEAD ;
                # chaque binding reste signé pour son artefact individuel.
                "review_id": 900,
                "reviewer_login": "abenrhouma",
                "reviewer_permission": "admin",
                "author_login": "cyranoaladin",
                "submitted_at": datetime(2026, 10, 10, 15, 10, tzinfo=UTC),
                "challenge_protocol": "NEXUS-TRUSTED-REVIEW-V1",
                "challenge_digest": expected_challenge_digest(
                    repository="cyranoaladin/RAG",
                    pull_request=777,
                    base_ref="main",
                    base_sha="a" * 40,
                    head_sha="b" * 40,
                    author="cyranoaladin",
                    reviewer="abenrhouma",
                ),
                "verified_at": datetime(2026, 10, 10, 15, 20, tzinfo=UTC),
                "verifier_version": "fixture-v1",
                "expires_at": datetime(2026, 10, 11, 13, tzinfo=UTC),
            }
        )
        files[canonical_review_binding_path(authorization_id)] = sign_review_binding(
            binding,
            private_key_hex=TEST_SEED,
            key_id="nexus-test-key",
        ).canonical_bytes()
    anchor = TrustAnchor.model_validate(
        {
            "protocol_version": "NEXUS-REVIEW-BINDING-V1",
            "keys": [
                {
                    "key_id": "nexus-test-key",
                    "algorithm": "ed25519",
                    "public_key": public_key_hex(TEST_SEED),
                    "environment": "test",
                }
            ],
        }
    )
    return tuple(ids), files, anchor


def test_complete_synthetic_reviews_produce_exact_v2_set() -> None:
    ids, files, trust_anchor = _test_material()
    result = build_public_lot41a_set(
        anchor_path=ANCHOR,
        anchor_sha256=ANCHOR_SHA,
        release_root=RELEASE,
        authorization_ids=ids,
        release_files=files,
        trust_anchor=trust_anchor,
        environment="test",
        now_utc=NOW,
        accepted_reviewers=("abenrhouma",),
        revocation_registry_raw=(
            ROOT / "governance/trust-anchors/authorization-revocations-v1.json"
        ).read_bytes(),
    )
    assert result.authorization_count == 11
    assert result.unique_content_count == 253
    assert result.authorization_binding_count == 377


def test_actual_a_requires_all_eleven_reviewed_authorizations() -> None:
    with pytest.raises(PublicLot41AError, match="11.*authorization"):
        build_public_lot41a_set(
            anchor_path=ANCHOR,
            anchor_sha256=ANCHOR_SHA,
            release_root=RELEASE,
            authorization_ids=(),
            release_files={},
            trust_anchor=parse_trust_anchor(
                (ROOT / "governance/trust-anchors/review-binding-v1.json").read_bytes()
            ),
            environment="production",
            now_utc=datetime(2026, 10, 11, 6, tzinfo=UTC),
            accepted_reviewers=("abenrhouma",),
            revocation_registry_raw=(
                ROOT / "governance/trust-anchors/authorization-revocations-v1.json"
            ).read_bytes(),
        )


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"rights_categories": ("usage_interne",)}, "rights"),
        ({"pii_evidence": "unrelated-pii-proof"}, "rights"),
        ({"allowed_domains": ("example.org",)}, "rights"),
    ],
)
def test_reviewed_artifact_must_prove_public_derivatives(
    override: dict,
    expected: str,
) -> None:
    ids, files, trust_anchor = _test_material(**override)
    with pytest.raises(PublicLot41AError, match=expected):
        build_public_lot41a_set(
            anchor_path=ANCHOR,
            anchor_sha256=ANCHOR_SHA,
            release_root=RELEASE,
            authorization_ids=ids,
            release_files=files,
            trust_anchor=trust_anchor,
            environment="test",
            now_utc=NOW,
            accepted_reviewers=("abenrhouma",),
            revocation_registry_raw=(
                ROOT / "governance/trust-anchors/authorization-revocations-v1.json"
            ).read_bytes(),
        )


def test_missing_signed_review_material_is_rejected() -> None:
    ids, files, trust_anchor = _test_material()
    files.pop(canonical_review_binding_path(ids[0]))
    with pytest.raises(PublicLot41AError, match="material incomplete"):
        build_public_lot41a_set(
            anchor_path=ANCHOR,
            anchor_sha256=ANCHOR_SHA,
            release_root=RELEASE,
            authorization_ids=ids,
            release_files=files,
            trust_anchor=trust_anchor,
            environment="test",
            now_utc=NOW,
            accepted_reviewers=("abenrhouma",),
            revocation_registry_raw=(
                ROOT / "governance/trust-anchors/authorization-revocations-v1.json"
            ).read_bytes(),
        )


def test_revoked_authorization_is_refused() -> None:
    ids, files, trust_anchor = _test_material()
    revocations = json.dumps(
        {
            "protocol_version": "NEXUS-AUTHORIZATION-REVOCATIONS-V1",
            "revoked_authorization_ids": [ids[0]],
        }
    ).encode()
    with pytest.raises(ValueError, match="revok|revoc"):
        build_public_lot41a_set(
            anchor_path=ANCHOR,
            anchor_sha256=ANCHOR_SHA,
            release_root=RELEASE,
            authorization_ids=ids,
            release_files=files,
            trust_anchor=trust_anchor,
            environment="test",
            now_utc=NOW,
            accepted_reviewers=("abenrhouma",),
            revocation_registry_raw=revocations,
        )


def test_expired_content_anchor_cannot_produce_authority() -> None:
    ids, files, trust_anchor = _test_material()
    with pytest.raises(ValueError, match="expir|currentness"):
        build_public_lot41a_set(
            anchor_path=ANCHOR,
            anchor_sha256=ANCHOR_SHA,
            release_root=RELEASE,
            authorization_ids=ids,
            release_files=files,
            trust_anchor=trust_anchor,
            environment="test",
            now_utc=datetime(2026, 10, 12, tzinfo=UTC),
            accepted_reviewers=("abenrhouma",),
            revocation_registry_raw=(
                ROOT / "governance/trust-anchors/authorization-revocations-v1.json"
            ).read_bytes(),
        )


def test_cli_refuses_to_emit_without_reviewed_material(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/go_live/produce_public_lot41a_v2.py"),
            "--anchor-path",
            str(ANCHOR),
            "--anchor-sha256",
            ANCHOR_SHA,
            "--release-root",
            str(RELEASE),
            "--material-root",
            str(tmp_path),
            *[
                argument
                for index in range(11)
                for argument in (
                    "--authorization-id",
                    f"lot41a-public-{index:02d}",
                )
            ],
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert result.stdout == b""
    assert b"missing" in result.stderr.lower()


def test_cli_refuses_symlinked_material_root(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/go_live/produce_public_lot41a_v2.py"),
            "--anchor-path",
            str(ANCHOR),
            "--anchor-sha256",
            ANCHOR_SHA,
            "--release-root",
            str(RELEASE),
            "--material-root",
            str(alias),
            "--authorization-id",
            "lot41a-public-00",
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert result.stdout == b""
    assert b"symlink" in result.stderr.lower()
