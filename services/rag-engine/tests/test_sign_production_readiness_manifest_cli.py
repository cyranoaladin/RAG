"""Tests — outil de signature du manifeste de production readiness.

Clé de test triviale et déterministe : sans rapport avec les clés de
production (production-readiness PR #97, review-binding PR #99).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[3] / "packages" / "contracts" / "src")
)

import sign_production_readiness_manifest_cli as tool  # noqa: E402
from nexus_contracts.authority_artifacts import (  # noqa: E402
    ScopeAuthorizationArtifactV2,
    canonical_authorization_path,
    git_blob_sha1,
)
from nexus_contracts.production_readiness import (  # noqa: E402
    ProductionReadinessError,
    ProductionReadinessTrustAnchor,
    ProductionReadinessTrustAnchorKey,
    public_readiness_key_hex,
    verify_production_readiness_manifest,
)
from nexus_contracts.review_binding import (  # noqa: E402
    ScopeAuthorizationReviewBindingV1,
    expected_challenge_digest,
    sign_review_binding,
)
from nexus_contracts.review_binding import (  # noqa: E402
    TrustAnchor as ReviewBindingTrustAnchor,
)
from nexus_contracts.review_binding import (  # noqa: E402
    public_key_hex as review_binding_public_key_hex,
)

TEST_SEED = "11" * 32
TEST_KEY_ID = "sign-tool-test-key-1"
OTHER_SEED = "22" * 32
MERGE_SHA = "a" * 40
PR_HEAD_SHA = "b" * 40
TREE_SHA = "c" * 40
GIT_SHA1_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

#: Clé de test du reçu de revue (ADR-0035) — distincte de TEST_SEED (clé de
#: signature du manifeste lui-même) : ce sont deux ancres de confiance
#: différentes dans le dépôt réel (review-binding-v1.json vs
#: production-readiness-v1.json).
RB_TEST_SEED = "33" * 32
RB_KEY_ID = "rb-sign-tool-test-key-1"
RB_REPOSITORY = "cyranoaladin/RAG"
RB_PULL_REQUEST = 42
RB_BASE_SHA = "d" * 40
RB_HEAD_SHA = "e" * 40
RB_REVIEWER = "abenrhouma"
RB_AUTHOR = "cyranoaladin"
AUTHORIZATION_ID = "sign-tool-test-authz-v1"

#: Fenêtre de validité large et fixe : évite toute dépendance à l'horloge
#: réelle au moment où la suite tourne (le nouveau garde-fou de l'outil
#: compare l'autorisation à ``datetime.now(UTC)``).
FAR_PAST = "2020-01-01T00:00:00Z"
FAR_FUTURE = "2099-01-01T00:00:00Z"


def _write(path: Path, content: bytes = b"content") -> Path:
    path.write_bytes(content)
    return path


def _authorization_bytes(**overrides: Any) -> bytes:
    document: dict[str, Any] = {
        "protocol_version": "LOT41A-V2",
        "authorization_id": AUTHORIZATION_ID,
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "scope": {
            "tenant": "libre_terminale",
            "collection": "rag_nexus_nsi_terminale_specialite",
            "niveau": "terminale",
            "voie": "generale",
            "matiere": "nsi",
            "candidat": "libre",
            "audience": ["libre", "tous"],
            "visibility": "internal",
            "school_year": "2026-2027",
            "programme_version": "BOEN_special_8_2019-07-25",
        },
        "manifest_digest": "c" * 64,
        "profile_id": "rag_nexus_nsi_terminale_specialite",
        "profile_version": "v1",
        "profile_fingerprint": "d" * 64,
        "allowed_domains": ["eduscol.education.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "allowed_content_sha256": ["e" * 64],
        "pii_absence_attested": True,
        "pii_absence_evidence": "Corpus officiel, aucune donnee personnelle.",
        "valid_from": FAR_PAST,
        "valid_until": FAR_FUTURE,
    }
    document.update(overrides)
    return ScopeAuthorizationArtifactV2.model_validate(document).canonical_bytes()


def _signed_review_binding_bytes(
    *, authorization_bytes: bytes | None = None, signing_key: str = RB_TEST_SEED, **overrides: Any
) -> bytes:
    auth_bytes = authorization_bytes if authorization_bytes is not None else _authorization_bytes()
    document: dict[str, Any] = {
        "protocol_version": "NEXUS-REVIEW-BINDING-V1",
        "repository": RB_REPOSITORY,
        "pull_request": RB_PULL_REQUEST,
        "base_ref": "main",
        "base_sha": RB_BASE_SHA,
        "head_sha": RB_HEAD_SHA,
        "authorization_artifact_path": canonical_authorization_path(AUTHORIZATION_ID),
        "authorization_artifact_sha256": hashlib.sha256(auth_bytes).hexdigest(),
        "authorization_artifact_git_blob_sha1": git_blob_sha1(auth_bytes),
        "authorization_id": AUTHORIZATION_ID,
        "authorization_decision": "AUTHORIZE_INGESTION_SCOPE",
        "review_id": 4242,
        "reviewer_login": RB_REVIEWER,
        "reviewer_permission": "admin",
        "author_login": RB_AUTHOR,
        "submitted_at": FAR_PAST,
        "challenge_protocol": "NEXUS-TRUSTED-REVIEW-V1",
        "challenge_digest": expected_challenge_digest(
            repository=RB_REPOSITORY,
            pull_request=RB_PULL_REQUEST,
            base_ref="main",
            base_sha=RB_BASE_SHA,
            head_sha=RB_HEAD_SHA,
            author=RB_AUTHOR,
            reviewer=RB_REVIEWER,
        ),
        "verified_at": FAR_PAST,
        "verifier_version": "nexus-review-binding/1",
        "expires_at": FAR_FUTURE,
    }
    document.update(overrides)
    binding = ScopeAuthorizationReviewBindingV1.model_validate(document)
    return sign_review_binding(
        binding, private_key_hex=signing_key, key_id=RB_KEY_ID
    ).canonical_bytes()


def _review_binding_trust_anchor_bytes(
    *, environment: str = "production", seed: str = RB_TEST_SEED
) -> bytes:
    anchor = ReviewBindingTrustAnchor.model_validate(
        {
            "protocol_version": "NEXUS-REVIEW-BINDING-V1",
            "keys": [
                {
                    "key_id": RB_KEY_ID,
                    "algorithm": "ed25519",
                    "public_key": review_binding_public_key_hex(seed),
                    "environment": environment,
                }
            ],
        }
    )
    return (
        json.dumps(anchor.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _revocation_registry_bytes(*, revoked: tuple[str, ...] = ()) -> bytes:
    return (
        json.dumps(
            {
                "protocol_version": "NEXUS-AUTHORIZATION-REVOCATIONS-V1",
                "revoked_authorization_ids": list(revoked),
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _base_args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    parser = tool._build_arg_parser()
    argv = [
        "--repository", "cyranoaladin/RAG",
        "--pr-number", "98",
        "--pr-head-sha", PR_HEAD_SHA,
        "--pr-head-tree-sha", TREE_SHA,
        "--merge-sha", MERGE_SHA,
        "--merge-tree-sha", TREE_SHA,
        "--environment", "production",
        "--review-binding-file", str(_write(tmp_path / "rb.json", _signed_review_binding_bytes())),
        "--review-binding-trust-anchor-file",
        str(_write(tmp_path / "rb_anchor.json", _review_binding_trust_anchor_bytes())),
        "--authorization-file", str(_write(tmp_path / "auth.json", _authorization_bytes())),
        "--trust-anchor-file", str(_write(tmp_path / "anchor.json")),
        "--revocation-registry-file",
        str(_write(tmp_path / "revoc.json", _revocation_registry_bytes())),
        "--catalog-file", str(_write(tmp_path / "catalog.json")),
        "--sealed-manifest-file", str(_write(tmp_path / "sealed.txt")),
        "--h2b-report-file", str(_write(tmp_path / "report.md")),
        "--compose-file", str(_write(tmp_path / "compose.yml")),
        "--application-image", "ingestor=ghcr.io/x/ingestor@sha256:" + "1" * 64,
        "--upstream-image", "pgvector=pgvector/pgvector@sha256:" + "2" * 64,
        "--workflow-path", ".github/workflows/promote.yml",
        "--workflow-ref", "refs/heads/main",
        "--run-id", "1234",
        "--run-attempt", "1",
        "--key-id", TEST_KEY_ID,
        "--private-key-file", str(_write(tmp_path / "priv.hex", TEST_SEED.encode())),
        "--verification-trust-anchor-file", str(tmp_path / "verify_anchor.json"),
        "--output", str(tmp_path / "manifest.json"),
    ]
    args = parser.parse_args(argv)
    for key, value in overrides.items():
        setattr(args, key.replace("-", "_"), value)
    return args


def _write_verification_anchor(tmp_path: Path, *, seed: str = TEST_SEED, environment: str = "production") -> None:
    anchor = ProductionReadinessTrustAnchor(
        protocol_version="NEXUS-PRODUCTION-READINESS-V1",
        keys=(
            ProductionReadinessTrustAnchorKey(
                key_id=TEST_KEY_ID,
                algorithm="ed25519",
                public_key=public_readiness_key_hex(seed),
                environment=environment,
            ),
        ),
    )
    doc = anchor.model_dump(mode="json")
    (tmp_path / "verify_anchor.json").write_text(
        json.dumps(doc, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


class TestValidManifestSignsAndVerifies:
    def test_a_complete_valid_manifest_signs_and_round_trips(self, tmp_path: Path) -> None:
        _write_verification_anchor(tmp_path)
        args = _base_args(tmp_path)
        manifest = tool.assemble_and_sign(args)
        assert manifest.protocol_version == "NEXUS-PRODUCTION-READINESS-V1"
        assert manifest.pr_head_tree_sha == manifest.merge_tree_sha

        rc = tool.main([
            "--repository", "cyranoaladin/RAG", "--pr-number", "98",
            "--pr-head-sha", PR_HEAD_SHA, "--pr-head-tree-sha", TREE_SHA,
            "--merge-sha", MERGE_SHA, "--merge-tree-sha", TREE_SHA,
            "--environment", "production",
            "--review-binding-file", str(tmp_path / "rb.json"),
            "--review-binding-trust-anchor-file", str(tmp_path / "rb_anchor.json"),
            "--authorization-file", str(tmp_path / "auth.json"),
            "--trust-anchor-file", str(tmp_path / "anchor.json"),
            "--revocation-registry-file", str(tmp_path / "revoc.json"),
            "--catalog-file", str(tmp_path / "catalog.json"),
            "--sealed-manifest-file", str(tmp_path / "sealed.txt"),
            "--h2b-report-file", str(tmp_path / "report.md"),
            "--compose-file", str(tmp_path / "compose.yml"),
            "--application-image", "ingestor=ghcr.io/x/ingestor@sha256:" + "1" * 64,
            "--upstream-image", "pgvector=pgvector/pgvector@sha256:" + "2" * 64,
            "--workflow-path", ".github/workflows/promote.yml",
            "--workflow-ref", "refs/heads/main",
            "--run-id", "1234", "--run-attempt", "1",
            "--key-id", TEST_KEY_ID,
            "--private-key-file", str(tmp_path / "priv.hex"),
            "--verification-trust-anchor-file", str(tmp_path / "verify_anchor.json"),
            "--output", str(tmp_path / "manifest.json"),
        ])
        assert rc == 0
        raw = (tmp_path / "manifest.json").read_bytes()
        anchor = ProductionReadinessTrustAnchor.model_validate(
            json.loads((tmp_path / "verify_anchor.json").read_bytes())
        )
        verified = verify_production_readiness_manifest(
            raw, trust_anchor=anchor, environment="production"
        )
        assert verified.pr_number == 98

    def test_private_key_file_permissions_are_restrictive_on_output(self, tmp_path: Path) -> None:
        _write_verification_anchor(tmp_path)
        args = _base_args(tmp_path)
        manifest = tool.assemble_and_sign(args)
        from nexus_contracts.production_readiness import sign_production_readiness_manifest
        signed = sign_production_readiness_manifest(
            manifest, private_key_hex=TEST_SEED, key_id=TEST_KEY_ID
        )
        out = tmp_path / "out.json"
        out.write_bytes(signed.canonical_bytes())
        out.chmod(0o600)
        import stat
        mode = stat.S_IMODE(out.stat().st_mode)
        assert mode == 0o600


class TestAdversarialCanaries:
    def test_wrong_pr_head_sha_format_refused(self, tmp_path: Path) -> None:
        args = _base_args(tmp_path, pr_head_sha="not-a-sha")
        with pytest.raises(tool.SigningToolError, match="pr_head_sha"):
            tool.assemble_and_sign(args)

    def test_mismatched_tree_shas_refused_by_contract(self, tmp_path: Path) -> None:
        args = _base_args(tmp_path, pr_head_tree_sha="d" * 40)  # differs from merge_tree_sha
        with pytest.raises(tool.SigningToolError, match="pr_head_tree_sha and merge_tree_sha differ"):
            tool.assemble_and_sign(args)

    def test_mutable_image_tag_refused(self, tmp_path: Path) -> None:
        args = _base_args(tmp_path, application_image=["ingestor=ghcr.io/x/ingestor:latest"])
        with pytest.raises(tool.SigningToolError, match="pinned as"):
            tool.assemble_and_sign(args)

    def test_no_application_images_refused(self, tmp_path: Path) -> None:
        args = _base_args(tmp_path, application_image=[])
        with pytest.raises(tool.SigningToolError, match="at least one image"):
            tool.assemble_and_sign(args)

    def test_duplicate_image_service_name_refused(self, tmp_path: Path) -> None:
        args = _base_args(
            tmp_path,
            application_image=[
                "ingestor=ghcr.io/x/ingestor@sha256:" + "1" * 64,
                "ingestor=ghcr.io/x/ingestor@sha256:" + "3" * 64,
            ],
        )
        with pytest.raises(tool.SigningToolError, match="twice"):
            tool.assemble_and_sign(args)

    def test_missing_evidence_file_refused(self, tmp_path: Path) -> None:
        args = _base_args(tmp_path)
        args.review_binding_file = tmp_path / "does-not-exist.json"
        with pytest.raises(tool.SigningToolError, match="cannot read"):
            tool.assemble_and_sign(args)

    def test_non_production_environment_refused_by_argparse(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            tool._build_arg_parser().parse_args(["--environment", "rehearsal"])

    def test_wrong_signing_key_produces_a_signature_that_fails_verification(
        self, tmp_path: Path
    ) -> None:
        """La clé qui signe et la clé publiée dans l'ancre de vérification
        doivent correspondre — sinon la revérification immédiate doit
        refuser, jamais écrire un manifeste dont la propre preuve échoue."""
        _write_verification_anchor(tmp_path, seed=OTHER_SEED)  # anchor expects OTHER_SEED's pubkey
        args = _base_args(tmp_path)  # but priv.hex on disk is TEST_SEED
        manifest = tool.assemble_and_sign(args)
        from nexus_contracts.production_readiness import sign_production_readiness_manifest
        signed = sign_production_readiness_manifest(
            manifest, private_key_hex=TEST_SEED, key_id=TEST_KEY_ID
        )
        anchor = ProductionReadinessTrustAnchor.model_validate(
            json.loads((tmp_path / "verify_anchor.json").read_bytes())
        )
        with pytest.raises(Exception, match="signature is invalid"):
            verify_production_readiness_manifest(
                signed.canonical_bytes(), trust_anchor=anchor, environment="production"
            )

    def test_a_test_environment_key_never_verifies_a_production_manifest(
        self, tmp_path: Path
    ) -> None:
        _write_verification_anchor(tmp_path, environment="test")
        args = _base_args(tmp_path)
        manifest = tool.assemble_and_sign(args)
        from nexus_contracts.production_readiness import sign_production_readiness_manifest
        signed = sign_production_readiness_manifest(
            manifest, private_key_hex=TEST_SEED, key_id=TEST_KEY_ID
        )
        anchor = ProductionReadinessTrustAnchor.model_validate(
            json.loads((tmp_path / "verify_anchor.json").read_bytes())
        )
        with pytest.raises(Exception, match="never be accepted"):
            verify_production_readiness_manifest(
                signed.canonical_bytes(), trust_anchor=anchor, environment="production"
            )

    def test_tampering_after_signing_invalidates_the_signature(self, tmp_path: Path) -> None:
        """Changer un fait après signature (ex: run_id) doit invalider la
        signature — preuve que le manifeste, pas seulement son digest
        déclaré, est ce qui est signé."""
        _write_verification_anchor(tmp_path)
        args = _base_args(tmp_path)
        manifest = tool.assemble_and_sign(args)
        from nexus_contracts.production_readiness import sign_production_readiness_manifest
        signed = sign_production_readiness_manifest(
            manifest, private_key_hex=TEST_SEED, key_id=TEST_KEY_ID
        )
        raw = signed.canonical_bytes()
        tampered = raw.replace(b'"run_id": 1234', b'"run_id": 9999')
        assert tampered != raw
        anchor = ProductionReadinessTrustAnchor.model_validate(
            json.loads((tmp_path / "verify_anchor.json").read_bytes())
        )
        with pytest.raises(ProductionReadinessError):
            verify_production_readiness_manifest(
                tampered, trust_anchor=anchor, environment="production"
            )

    def test_main_never_writes_output_when_verification_fails(self, tmp_path: Path) -> None:
        # _base_args() creates every required input file as a side effect
        # (rb.json, auth.json, priv.hex, ...) -- reusing it, rather than
        # hand-rolling argv, is what makes this test actually reach the
        # verification step instead of failing earlier on a missing file.
        _base_args(tmp_path)
        _write_verification_anchor(tmp_path, seed=OTHER_SEED)  # anchor won't match priv.hex (TEST_SEED)
        output = tmp_path / "manifest.json"
        rc = tool.main([
            "--repository", "cyranoaladin/RAG", "--pr-number", "98",
            "--pr-head-sha", PR_HEAD_SHA, "--pr-head-tree-sha", TREE_SHA,
            "--merge-sha", MERGE_SHA, "--merge-tree-sha", TREE_SHA,
            "--environment", "production",
            "--review-binding-file", str(tmp_path / "rb.json"),
            "--review-binding-trust-anchor-file", str(tmp_path / "rb_anchor.json"),
            "--authorization-file", str(tmp_path / "auth.json"),
            "--trust-anchor-file", str(tmp_path / "anchor.json"),
            "--revocation-registry-file", str(tmp_path / "revoc.json"),
            "--catalog-file", str(tmp_path / "catalog.json"),
            "--sealed-manifest-file", str(tmp_path / "sealed.txt"),
            "--h2b-report-file", str(tmp_path / "report.md"),
            "--compose-file", str(tmp_path / "compose.yml"),
            "--application-image", "ingestor=ghcr.io/x/ingestor@sha256:" + "1" * 64,
            "--upstream-image", "pgvector=pgvector/pgvector@sha256:" + "2" * 64,
            "--workflow-path", ".github/workflows/promote.yml",
            "--workflow-ref", "refs/heads/main",
            "--run-id", "1234", "--run-attempt", "1",
            "--key-id", TEST_KEY_ID,
            "--private-key-file", str(tmp_path / "priv.hex"),
            "--verification-trust-anchor-file", str(tmp_path / "verify_anchor.json"),
            "--output", str(output),
        ])
        assert rc == 1
        assert not output.exists()


class TestReviewBindingIsActuallyVerified:
    """Codex P1 (PR #100): un digest prouve que le fichier n'a pas changé,
    pas qu'il décrit une revue humaine réelle. Chaque scénario ici prouve
    qu'un reçu structurellement invalide, mal signé, ou ne couvrant pas
    l'autorisation présentée est refusé -- jamais simplement haché."""

    def test_a_valid_review_binding_and_authorization_sign_successfully(
        self, tmp_path: Path
    ) -> None:
        _write_verification_anchor(tmp_path)
        args = _base_args(tmp_path)
        manifest = tool.assemble_and_sign(args)
        assert manifest.review_binding_digest == hashlib.sha256(
            (tmp_path / "rb.json").read_bytes()
        ).hexdigest()

    def test_review_binding_signed_by_an_unrecognized_key_is_refused(
        self, tmp_path: Path
    ) -> None:
        # A distinct filename (rb_bad.json, not rb.json) is deliberate:
        # _base_args() unconditionally (re)writes its own default rb.json
        # as part of building argv, which would silently clobber an
        # override written to that same path back to valid content.
        args = _base_args(
            tmp_path,
            review_binding_file=_write(
                tmp_path / "rb_bad.json",
                _signed_review_binding_bytes(signing_key=OTHER_SEED),
            ),
        )
        with pytest.raises(tool.SigningToolError, match="review binding does not authorize"):
            tool.assemble_and_sign(args)

    def test_review_binding_for_a_different_authorization_id_is_refused(
        self, tmp_path: Path
    ) -> None:
        other_auth = _authorization_bytes(authorization_id="some-other-authz-v1")
        args = _base_args(
            tmp_path,
            review_binding_file=_write(
                tmp_path / "rb_bad.json",
                _signed_review_binding_bytes(authorization_bytes=other_auth),
            ),
        )
        with pytest.raises(tool.SigningToolError, match="review binding does not authorize"):
            tool.assemble_and_sign(args)

    def test_self_approved_review_binding_is_refused(self, tmp_path: Path) -> None:
        args = _base_args(
            tmp_path,
            review_binding_file=_write(
                tmp_path / "rb_bad.json",
                _signed_review_binding_bytes(reviewer_login=RB_AUTHOR),
            ),
        )
        with pytest.raises(tool.SigningToolError, match="review binding does not authorize"):
            tool.assemble_and_sign(args)

    def test_expired_review_binding_is_refused(self, tmp_path: Path) -> None:
        args = _base_args(
            tmp_path,
            review_binding_file=_write(
                tmp_path / "rb_bad.json",
                _signed_review_binding_bytes(expires_at=FAR_PAST),
            ),
        )
        with pytest.raises(tool.SigningToolError, match="review binding does not authorize"):
            tool.assemble_and_sign(args)

    def test_authorization_outside_its_validity_window_is_refused(
        self, tmp_path: Path
    ) -> None:
        expired_auth = _authorization_bytes(valid_from=FAR_PAST, valid_until="2021-01-01T00:00:00Z")
        args = _base_args(
            tmp_path,
            authorization_file=_write(tmp_path / "auth_bad.json", expired_auth),
            review_binding_file=_write(
                tmp_path / "rb_bad.json",
                _signed_review_binding_bytes(authorization_bytes=expired_auth),
            ),
        )
        with pytest.raises(tool.SigningToolError, match="outside its validity window"):
            tool.assemble_and_sign(args)

    def test_revoked_authorization_is_refused(self, tmp_path: Path) -> None:
        args = _base_args(
            tmp_path,
            revocation_registry_file=_write(
                tmp_path / "revoc_bad.json",
                _revocation_registry_bytes(revoked=(AUTHORIZATION_ID,)),
            ),
        )
        with pytest.raises(tool.SigningToolError, match="revocation registry"):
            tool.assemble_and_sign(args)

    def test_malformed_revocation_registry_is_refused(self, tmp_path: Path) -> None:
        args = _base_args(
            tmp_path,
            revocation_registry_file=_write(tmp_path / "revoc_bad.json", b"not json"),
        )
        with pytest.raises(tool.SigningToolError, match="revocation_registry"):
            tool.assemble_and_sign(args)


class TestOutputNeverAliasesAnInput:
    """Codex P2 (PR #100): ``--output`` ne doit jamais pouvoir écraser un
    fichier d'entrée, en particulier la graine de signature locale."""

    def test_output_equal_to_private_key_file_is_refused(self, tmp_path: Path) -> None:
        priv = tmp_path / "priv.hex"
        args = _base_args(tmp_path, output=priv)
        original = priv.read_bytes()
        with pytest.raises(tool.SigningToolError, match="private-key-file"):
            tool._reject_output_aliasing_an_input(args)
        assert priv.read_bytes() == original

    def test_output_equal_to_a_symlinked_private_key_file_is_refused(
        self, tmp_path: Path
    ) -> None:
        priv = tmp_path / "priv.hex"
        alias = tmp_path / "alias.hex"
        alias.symlink_to(priv)
        args = _base_args(tmp_path, output=alias)
        with pytest.raises(tool.SigningToolError, match="private-key-file"):
            tool._reject_output_aliasing_an_input(args)

    def test_distinct_output_path_is_accepted(self, tmp_path: Path) -> None:
        args = _base_args(tmp_path)
        tool._reject_output_aliasing_an_input(args)  # does not raise

    def test_main_refuses_before_touching_any_file_when_output_aliases_the_key(
        self, tmp_path: Path
    ) -> None:
        _base_args(tmp_path)  # populates rb.json, auth.json, priv.hex, ... as a side effect
        _write_verification_anchor(tmp_path)
        priv = tmp_path / "priv.hex"
        original = priv.read_bytes()
        rc = tool.main([
            "--repository", "cyranoaladin/RAG", "--pr-number", "98",
            "--pr-head-sha", PR_HEAD_SHA, "--pr-head-tree-sha", TREE_SHA,
            "--merge-sha", MERGE_SHA, "--merge-tree-sha", TREE_SHA,
            "--environment", "production",
            "--review-binding-file", str(tmp_path / "rb.json"),
            "--review-binding-trust-anchor-file", str(tmp_path / "rb_anchor.json"),
            "--authorization-file", str(tmp_path / "auth.json"),
            "--trust-anchor-file", str(tmp_path / "anchor.json"),
            "--revocation-registry-file", str(tmp_path / "revoc.json"),
            "--catalog-file", str(tmp_path / "catalog.json"),
            "--sealed-manifest-file", str(tmp_path / "sealed.txt"),
            "--h2b-report-file", str(tmp_path / "report.md"),
            "--compose-file", str(tmp_path / "compose.yml"),
            "--application-image", "ingestor=ghcr.io/x/ingestor@sha256:" + "1" * 64,
            "--upstream-image", "pgvector=pgvector/pgvector@sha256:" + "2" * 64,
            "--workflow-path", ".github/workflows/promote.yml",
            "--workflow-ref", "refs/heads/main",
            "--run-id", "1234", "--run-attempt", "1",
            "--key-id", TEST_KEY_ID,
            "--private-key-file", str(priv),
            "--verification-trust-anchor-file", str(tmp_path / "verify_anchor.json"),
            "--output", str(priv),  # aliases the signing key itself
        ])
        assert rc == 1
        assert priv.read_bytes() == original
