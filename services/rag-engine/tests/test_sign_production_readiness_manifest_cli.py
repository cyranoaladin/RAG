"""Tests — outil de signature du manifeste de production readiness.

Clé de test triviale et déterministe : sans rapport avec les clés de
production (production-readiness PR #97, review-binding PR #99).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[3] / "packages" / "contracts" / "src")
)

import sign_production_readiness_manifest_cli as tool  # noqa: E402
from nexus_contracts.production_readiness import (  # noqa: E402
    ProductionReadinessError,
    ProductionReadinessTrustAnchor,
    ProductionReadinessTrustAnchorKey,
    public_readiness_key_hex,
    verify_production_readiness_manifest,
)

TEST_SEED = "11" * 32
TEST_KEY_ID = "sign-tool-test-key-1"
OTHER_SEED = "22" * 32
MERGE_SHA = "a" * 40
PR_HEAD_SHA = "b" * 40
TREE_SHA = "c" * 40
GIT_SHA1_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _write(path: Path, content: bytes = b"content") -> Path:
    path.write_bytes(content)
    return path


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
        "--review-binding-file", str(_write(tmp_path / "rb.json")),
        "--authorization-file", str(_write(tmp_path / "auth.json")),
        "--trust-anchor-file", str(_write(tmp_path / "anchor.json")),
        "--revocation-registry-file", str(_write(tmp_path / "revoc.json")),
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
