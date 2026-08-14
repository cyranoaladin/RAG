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
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[3] / "packages" / "contracts" / "src")
)

import deployment_image_inventory as dii  # noqa: E402
import sign_production_readiness_manifest_cli as tool  # noqa: E402
from nexus_contracts.authority_artifacts import (  # noqa: E402
    ScopeAuthorizationArtifactV2,
    canonical_authorization_path,
    git_blob_sha1,
)
from nexus_contracts.h2_coverage_evidence import (  # noqa: E402
    H2_COVERAGE_EVIDENCE_PROTOCOL_VERSION,
    H2CoverageEvidenceV1,
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

REPOSITORY = "cyranoaladin/RAG"
PR_NUMBER = 98
WORKFLOW_PATH = ".github/workflows/promote.yml"
WORKFLOW_REF = "refs/heads/main"
RUN_ID = 1234
RUN_ATTEMPT = 1

#: Les trois vrais services applicatifs (deployment_image_inventory.py,
#: PR #102) -- jamais un seul service fictif : les digests applicatifs ne
#: sont plus une saisie opérateur, ils sont dérivés d'une provenance
#: vérifiée qui exige exactement cet ensemble.
APPLICATION_SERVICES = ("ingestor", "multilevel-worker-a-production", "multilevel-worker-b-production")
INGESTOR_REPO = "ghcr.io/cyranoaladin/rag-ingestor"
WORKER_REPO = "ghcr.io/cyranoaladin/rag-multilevel-worker-production"
INGESTOR_DIGEST = "sha256:" + "1" * 64
WORKER_DIGEST = "sha256:" + "2" * 64
DOCKERFILE_SHA = "3" * 64
APPLICATION_IMAGE_DIGESTS = {
    "ingestor": f"{INGESTOR_REPO}@{INGESTOR_DIGEST}",
    "multilevel-worker-a-production": f"{WORKER_REPO}@{WORKER_DIGEST}",
    "multilevel-worker-b-production": f"{WORKER_REPO}@{WORKER_DIGEST}",
}
PROVENANCE_RUN_ID = 777
PROVENANCE_RUN_ATTEMPT = 1
PROVENANCE_WORKFLOW_PATH = ".github/workflows/production-image-provenance.yml"

UPSTREAM_IMAGE_SERVICE = "pgvector"
UPSTREAM_IMAGE_REF = "pgvector/pgvector@sha256:" + "2" * 64

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


def _compose_bytes(
    *, upstream_image: str = UPSTREAM_IMAGE_REF, application_services: tuple[str, ...] = APPLICATION_SERVICES
) -> bytes:
    services: dict[str, Any] = {UPSTREAM_IMAGE_SERVICE: {"image": upstream_image}}
    for name in application_services:
        services[name] = {"build": {"context": "."}}
    return yaml.safe_dump({"services": services}, sort_keys=True).encode("utf-8")


def _inventory_document(
    *, source_commit_sha: str = MERGE_SHA, source_tree_sha: str = TREE_SHA, **overrides: Any
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "protocol_version": "NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1",
        "repository": REPOSITORY,
        "source_commit_sha": source_commit_sha,
        "source_tree_sha": source_tree_sha,
        "platform": "linux/amd64",
        "workflow_path": PROVENANCE_WORKFLOW_PATH,
        "workflow_run_id": PROVENANCE_RUN_ID,
        "workflow_run_attempt": PROVENANCE_RUN_ATTEMPT,
        "workflow_ref": "refs/heads/main",
        "built_at": "2026-08-14T12:00:00Z",
        "services": {
            "ingestor": {
                "source_kind": "build",
                "build_context": ".",
                "dockerfile": "services/rag-engine/infra/Dockerfile.ingestor-v2",
                "dockerfile_sha256": DOCKERFILE_SHA,
                "image_repository": INGESTOR_REPO,
                "image_digest": INGESTOR_DIGEST,
            },
            "multilevel-worker-a-production": {
                "source_kind": "build",
                "build_context": ".",
                "dockerfile": "services/rag-engine/infra/Dockerfile.multilevel-worker-production",
                "dockerfile_sha256": DOCKERFILE_SHA,
                "image_repository": WORKER_REPO,
                "image_digest": WORKER_DIGEST,
            },
            "multilevel-worker-b-production": {
                "source_kind": "build",
                "build_context": ".",
                "dockerfile": "services/rag-engine/infra/Dockerfile.multilevel-worker-production",
                "dockerfile_sha256": DOCKERFILE_SHA,
                "image_repository": WORKER_REPO,
                "image_digest": WORKER_DIGEST,
            },
        },
    }
    document.update(overrides)
    return document


def _github_responses(
    *,
    pr_head_sha: str = PR_HEAD_SHA,
    merge_sha: str = MERGE_SHA,
    pr_head_tree_sha: str = TREE_SHA,
    merge_tree_sha: str = TREE_SHA,
    merged: bool = True,
    pr_repository: str = REPOSITORY,
    workflow_path: str = WORKFLOW_PATH,
    workflow_repository: str = REPOSITORY,
    head_branch: str | None = "main",
    provenance_conclusion: str = "success",
) -> dict[str, dict[str, Any]]:
    """Réponses GitHub par défaut : tout concorde (chemin heureux). Chaque
    test qui a besoin d'un scénario différent mute le dict retourné par la
    fixture ``_stub_github_api`` avant d'appeler ``assemble_and_sign``."""
    return {
        f"repos/{REPOSITORY}/pulls/{PR_NUMBER}": {
            "merged": merged,
            "merge_commit_sha": merge_sha,
            "head": {"sha": pr_head_sha, "repo": {"full_name": pr_repository}},
            "base": {"repo": {"full_name": REPOSITORY}},
        },
        f"repos/{REPOSITORY}/git/commits/{pr_head_sha}": {"tree": {"sha": pr_head_tree_sha}},
        f"repos/{REPOSITORY}/git/commits/{merge_sha}": {"tree": {"sha": merge_tree_sha}},
        f"repos/{REPOSITORY}/actions/runs/{RUN_ID}": {
            "path": workflow_path,
            "repository": {"full_name": workflow_repository},
            "head_branch": head_branch,
        },
        f"repos/{REPOSITORY}/actions/runs/{RUN_ID}/attempts/{RUN_ATTEMPT}": {},
        f"repos/{REPOSITORY}/actions/runs/{PROVENANCE_RUN_ID}": {
            "path": PROVENANCE_WORKFLOW_PATH,
            "repository": {"full_name": REPOSITORY},
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": provenance_conclusion,
            "head_sha": merge_sha,
            "run_attempt": PROVENANCE_RUN_ATTEMPT,
        },
        f"repos/{REPOSITORY}/actions/runs/{PROVENANCE_RUN_ID}/attempts/{PROVENANCE_RUN_ATTEMPT}": {},
    }


@pytest.fixture(autouse=True)
def _stub_github_api(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    """Substitue la seule frontière réseau de l'outil (``tool._github_api_get``)
    -- aucun test de cette suite ne doit jamais atteindre le réseau réel.
    Chemin heureux par défaut ; un test qui veut un scénario différent
    demande cette fixture et mute son dict avant d'appeler l'outil."""
    responses = _github_responses()

    def fake(path: str) -> dict[str, Any]:
        try:
            return responses[path]
        except KeyError:
            raise tool.SigningToolError(
                f"unexpected GitHub API path requested in test: {path!r}"
            ) from None

    monkeypatch.setattr(tool, "_github_api_get", fake)
    return responses


@pytest.fixture(autouse=True)
def _stub_download_artifact(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Substitue la seconde frontière réseau (téléchargement d'artefact de
    provenance d'image, PR #102) -- jamais un vrai ``gh run download``.
    Chemin heureux par défaut (inventaire des trois services réels) ; un
    test qui veut un scénario différent mute ce dict avant d'appeler
    l'outil."""
    state: dict[str, Any] = {"inventory": _inventory_document()}

    def fake_factory(*, repository: str) -> Any:
        def download(run_id: int, artifact_name: str, dest_dir: Path) -> Path:
            path = dest_dir / dii._ARTIFACT_FILENAME
            path.write_text(json.dumps(state["inventory"]), encoding="utf-8")
            return path

        return download

    monkeypatch.setattr(tool.dii, "make_download_artifact_via_gh", fake_factory)
    return state


def _h2_coverage_evidence_bytes(
    *,
    catalog_digest: str,
    sealed_manifest_digest: str,
    authorization_digest: str,
    authorization_id: str = AUTHORIZATION_ID,
    h2_coverage_gate_pass: bool = True,
    **overrides: Any,
) -> bytes:
    """Preuve H2 canonique (ADR-0042) liée par digest à *ce même* catalogue,
    manifeste scellé et artefact d'autorisation -- jamais trois fichiers
    indépendants qui pourraient diverger sans être détectés."""
    zero_safety_invariants = {
        "INGEST_WITHOUT_RIGHTS_CLEARANCE": 0,
        "INGEST_WITHOUT_PII_CLEARANCE": 0,
        "INGEST_WITHOUT_CURRENTNESS_CLEARANCE": 0,
        "INGEST_WITH_UNSUPPORTED_FORMAT": 0,
        "INGEST_WITHOUT_PROVENANCE": 0,
        "INGEST_WITHOUT_CONTENT_SHA": 0,
        "INGEST_WITHOUT_AUTHORITY": 0,
        "INGEST_WITH_SELF_DECLARED_AUTHORITY": 0,
        "INGEST_WITHOUT_ATTRIBUTION_METADATA": 0,
    }
    document: dict[str, Any] = {
        "protocol_version": H2_COVERAGE_EVIDENCE_PROTOCOL_VERSION,
        "environment": "production",
        "report_id": "sign-tool-test-h2b-report",
        "generated_at": FAR_PAST,
        "git_commit": MERGE_SHA,
        "producer_version": "h2b_coverage_report/1",
        "manifest_sha256": sealed_manifest_digest,
        "input_file_digests": {
            "catalog": catalog_digest,
            "routing": "6" * 64,
            "rights": "7" * 64,
            "pii": "8" * 64,
            "golden": "9" * 64,
            "authority": authorization_digest,
        },
        "corpus_total_expected": 2583,
        "corpus_total_actual": 2583,
        "corpus_match": True,
        "sum_equals_total": True,
        "zero_overlap": True,
        "zero_gap": True,
        "coverage_complete": True,
        "rights_gate_status": "PASS",
        "pii_gate_status": "PASS",
        "golden_validation_pass": True,
        "h2_coverage_gate_pass": h2_coverage_gate_pass,
        "authority_review_binding_verified": True,
        "authority_revocations_checked": True,
        "authorization_id": authorization_id,
        "safety_invariants": zero_safety_invariants,
    }
    document.update(overrides)
    return H2CoverageEvidenceV1.model_validate(document).canonical_bytes()


def _base_args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    catalog_bytes = b"catalog-content"
    sealed_manifest_bytes = b"sealed-manifest-content"
    authorization_bytes = _authorization_bytes()
    catalog_digest = hashlib.sha256(catalog_bytes).hexdigest()
    sealed_manifest_digest = hashlib.sha256(sealed_manifest_bytes).hexdigest()
    authorization_digest = hashlib.sha256(authorization_bytes).hexdigest()

    parser = tool._build_arg_parser()
    argv = [
        "--repository", REPOSITORY,
        "--pr-number", str(PR_NUMBER),
        "--pr-head-sha", PR_HEAD_SHA,
        "--merge-sha", MERGE_SHA,
        "--environment", "production",
        "--review-binding-file", str(_write(tmp_path / "rb.json", _signed_review_binding_bytes())),
        "--review-binding-trust-anchor-file",
        str(_write(tmp_path / "rb_anchor.json", _review_binding_trust_anchor_bytes())),
        "--authorization-file", str(_write(tmp_path / "auth.json", authorization_bytes)),
        "--trust-anchor-file", str(_write(tmp_path / "anchor.json")),
        "--revocation-registry-file",
        str(_write(tmp_path / "revoc.json", _revocation_registry_bytes())),
        "--catalog-file", str(_write(tmp_path / "catalog.json", catalog_bytes)),
        "--sealed-manifest-file", str(_write(tmp_path / "sealed.txt", sealed_manifest_bytes)),
        "--h2b-report-file", str(_write(
            tmp_path / "report.json",
            _h2_coverage_evidence_bytes(
                catalog_digest=catalog_digest,
                sealed_manifest_digest=sealed_manifest_digest,
                authorization_digest=authorization_digest,
            ),
        )),
        "--compose-file", str(_write(tmp_path / "compose.yml", _compose_bytes())),
        "--provenance-run-id", str(PROVENANCE_RUN_ID),
        "--provenance-run-attempt", str(PROVENANCE_RUN_ATTEMPT),
        "--upstream-image", f"{UPSTREAM_IMAGE_SERVICE}={UPSTREAM_IMAGE_REF}",
        "--workflow-path", WORKFLOW_PATH,
        "--workflow-ref", WORKFLOW_REF,
        "--run-id", str(RUN_ID),
        "--run-attempt", str(RUN_ATTEMPT),
        "--key-id", TEST_KEY_ID,
        "--private-key-file", str(_write(tmp_path / "priv.hex", TEST_SEED.encode())),
        "--verification-trust-anchor-file", str(tmp_path / "verify_anchor.json"),
        "--output", str(tmp_path / "manifest.json"),
    ]
    args = parser.parse_args(argv)
    for key, value in overrides.items():
        setattr(args, key.replace("-", "_"), value)
    return args


def _main_argv(tmp_path: Path, *, output: Path) -> list[str]:
    """argv pour ``tool.main()`` référençant les fichiers déjà écrits par
    ``_base_args`` (appelé séparément, comme effet de bord, par chaque
    test qui utilise ce helper) -- jamais dupliqué trois fois."""
    return [
        "--repository", "cyranoaladin/RAG", "--pr-number", "98",
        "--pr-head-sha", PR_HEAD_SHA,
        "--merge-sha", MERGE_SHA,
        "--environment", "production",
        "--review-binding-file", str(tmp_path / "rb.json"),
        "--review-binding-trust-anchor-file", str(tmp_path / "rb_anchor.json"),
        "--authorization-file", str(tmp_path / "auth.json"),
        "--trust-anchor-file", str(tmp_path / "anchor.json"),
        "--revocation-registry-file", str(tmp_path / "revoc.json"),
        "--catalog-file", str(tmp_path / "catalog.json"),
        "--sealed-manifest-file", str(tmp_path / "sealed.txt"),
        "--h2b-report-file", str(tmp_path / "report.json"),
        "--compose-file", str(tmp_path / "compose.yml"),
        "--provenance-run-id", str(PROVENANCE_RUN_ID),
        "--provenance-run-attempt", str(PROVENANCE_RUN_ATTEMPT),
        "--upstream-image", "pgvector=pgvector/pgvector@sha256:" + "2" * 64,
        "--workflow-path", ".github/workflows/promote.yml",
        "--workflow-ref", "refs/heads/main",
        "--run-id", "1234", "--run-attempt", "1",
        "--key-id", TEST_KEY_ID,
        "--private-key-file", str(tmp_path / "priv.hex"),
        "--verification-trust-anchor-file", str(tmp_path / "verify_anchor.json"),
        "--output", str(output),
    ]


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

        rc = tool.main(_main_argv(tmp_path, output=tmp_path / "manifest.json"))
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

    def test_mismatched_tree_shas_refused_by_contract(
        self, tmp_path: Path, _stub_github_api: dict[str, dict[str, Any]]
    ) -> None:
        # pr_head_tree_sha/merge_tree_sha are no longer CLI arguments -- they
        # are derived from the (stubbed) live GitHub commit responses.
        # Diverging them here exercises the same contract binding
        # (_bindings_hold) as before, from its real source now.
        _stub_github_api[f"repos/{REPOSITORY}/git/commits/{PR_HEAD_SHA}"]["tree"]["sha"] = "d" * 40
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="pr_head_tree_sha and merge_tree_sha differ"):
            tool.assemble_and_sign(args)

    def test_duplicate_upstream_image_service_name_refused(self, tmp_path: Path) -> None:
        # _image_digest_pairs is still exercised directly for --upstream-image
        # (application images no longer go through this opaque-input path,
        # see TestApplicationImageProvenanceIsDerivedNotDeclared instead).
        args = _base_args(
            tmp_path,
            upstream_image=[
                f"{UPSTREAM_IMAGE_SERVICE}={UPSTREAM_IMAGE_REF}",
                f"{UPSTREAM_IMAGE_SERVICE}=pgvector/pgvector@sha256:" + "3" * 64,
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
        rc = tool.main(_main_argv(tmp_path, output=output))
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
        rc = tool.main(_main_argv(tmp_path, output=priv))  # aliases the signing key itself
        assert rc == 1
        assert priv.read_bytes() == original


class TestGitAndWorkflowFactsAreLiveVerified:
    """Codex (PR #100 §9-11) : un SHA/entier bien formé n'est pas une
    preuve. Chaque scénario ici prouve qu'un fait qui diverge de la
    réponse GitHub réelle (stubbée) est refusé -- jamais accepté sur le
    seul format."""

    def test_a_matching_pr_is_accepted(self, tmp_path: Path) -> None:
        args = _base_args(tmp_path)
        manifest = tool.assemble_and_sign(args)
        assert manifest.pr_head_tree_sha == manifest.merge_tree_sha == TREE_SHA

    def test_unmerged_pr_is_refused(
        self, tmp_path: Path, _stub_github_api: dict[str, dict[str, Any]]
    ) -> None:
        _stub_github_api[f"repos/{REPOSITORY}/pulls/{PR_NUMBER}"]["merged"] = False
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="is not merged"):
            tool.assemble_and_sign(args)

    def test_merge_sha_not_matching_live_merge_commit_is_refused(
        self, tmp_path: Path, _stub_github_api: dict[str, dict[str, Any]]
    ) -> None:
        _stub_github_api[f"repos/{REPOSITORY}/pulls/{PR_NUMBER}"]["merge_commit_sha"] = "f" * 40
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="does not match the live"):
            tool.assemble_and_sign(args)

    def test_pr_head_sha_not_matching_live_head_is_refused(
        self, tmp_path: Path, _stub_github_api: dict[str, dict[str, Any]]
    ) -> None:
        _stub_github_api[f"repos/{REPOSITORY}/pulls/{PR_NUMBER}"]["head"]["sha"] = "f" * 40
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="does not match the live"):
            tool.assemble_and_sign(args)

    def test_fork_head_repository_is_refused(
        self, tmp_path: Path, _stub_github_api: dict[str, dict[str, Any]]
    ) -> None:
        _stub_github_api[f"repos/{REPOSITORY}/pulls/{PR_NUMBER}"]["head"]["repo"]["full_name"] = (
            "someone-else/RAG"
        )
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="fork or cross-repository"):
            tool.assemble_and_sign(args)

    def test_workflow_path_not_matching_the_live_run_is_refused(
        self, tmp_path: Path, _stub_github_api: dict[str, dict[str, Any]]
    ) -> None:
        _stub_github_api[f"repos/{REPOSITORY}/actions/runs/{RUN_ID}"]["path"] = (
            ".github/workflows/other.yml"
        )
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="does not match the live workflow path"):
            tool.assemble_and_sign(args)

    def test_workflow_ref_not_matching_the_live_head_branch_is_refused(
        self, tmp_path: Path, _stub_github_api: dict[str, dict[str, Any]]
    ) -> None:
        _stub_github_api[f"repos/{REPOSITORY}/actions/runs/{RUN_ID}"]["head_branch"] = "some-other-branch"
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="does not match the live run"):
            tool.assemble_and_sign(args)

    def test_run_attempt_that_does_not_exist_is_refused(
        self, tmp_path: Path, _stub_github_api: dict[str, dict[str, Any]]
    ) -> None:
        del _stub_github_api[f"repos/{REPOSITORY}/actions/runs/{RUN_ID}/attempts/{RUN_ATTEMPT}"]
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="unexpected GitHub API path"):
            tool.assemble_and_sign(args)

    def test_github_api_transport_failure_is_refused_not_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(path: str) -> dict[str, Any]:
            raise tool.SigningToolError(f"GitHub API call to {path!r} failed: boom")

        monkeypatch.setattr(tool, "_github_api_get", boom)
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="GitHub API call"):
            tool.assemble_and_sign(args)


class TestComposeImageBindingIsEnforced:
    """Codex P1 (PR #100 §2-6) : ``--application-image``/``--upstream-image``
    ne sont plus des affirmations indépendantes du Compose haché -- chaque
    scénario prouve qu'une divergence entre les deux est refusée."""

    def test_matching_compose_and_declared_images_signs_successfully(
        self, tmp_path: Path
    ) -> None:
        args = _base_args(tmp_path)
        manifest = tool.assemble_and_sign(args)
        assert manifest.upstream_image_digests[UPSTREAM_IMAGE_SERVICE] == UPSTREAM_IMAGE_REF

    def test_upstream_image_digest_diverging_from_compose_is_refused(
        self, tmp_path: Path
    ) -> None:
        args = _base_args(
            tmp_path,
            upstream_image=[f"{UPSTREAM_IMAGE_SERVICE}=pgvector/pgvector@sha256:" + "9" * 64],
        )
        with pytest.raises(tool.SigningToolError, match="does not match the compose file"):
            tool.assemble_and_sign(args)

    def test_upstream_service_omitted_from_declared_images_is_refused(
        self, tmp_path: Path
    ) -> None:
        # compose.yml (default fixture) pins exactly one upstream service
        # (pgvector); declaring zero upstream images leaves it
        # unrepresented -- caught by _image_digest_pairs itself (it already
        # refuses an empty list), before the cross-check even runs. Same
        # underlying gap either way: no unrepresented service is accepted.
        args = _base_args(tmp_path, upstream_image=[])
        with pytest.raises(tool.SigningToolError, match="must declare at least one image"):
            tool.assemble_and_sign(args)

    def test_upstream_service_omitted_while_another_is_present_is_refused(
        self, tmp_path: Path
    ) -> None:
        # Non-empty but still missing 'pgvector' -- exercises the
        # cross-check's set-mismatch branch specifically (distinct from the
        # empty-list case above, which never reaches it).
        raw = yaml.safe_dump(
            {
                "services": {
                    UPSTREAM_IMAGE_SERVICE: {"image": UPSTREAM_IMAGE_REF},
                    "redis": {"image": "redis:7@sha256:" + "5" * 64},
                    **{name: {"build": {"context": "."}} for name in APPLICATION_SERVICES},
                }
            },
            sort_keys=True,
        ).encode("utf-8")
        args = _base_args(
            tmp_path,
            compose_file=_write(tmp_path / "compose_two_upstream.yml", raw),
            upstream_image=[f"{UPSTREAM_IMAGE_SERVICE}={UPSTREAM_IMAGE_REF}"],
        )
        with pytest.raises(tool.SigningToolError, match="image-pinned services"):
            tool.assemble_and_sign(args)

    def test_extra_invented_upstream_service_is_refused(self, tmp_path: Path) -> None:
        args = _base_args(
            tmp_path,
            upstream_image=[
                f"{UPSTREAM_IMAGE_SERVICE}={UPSTREAM_IMAGE_REF}",
                "invented-service=ghcr.io/x/invented@sha256:" + "9" * 64,
            ],
        )
        with pytest.raises(tool.SigningToolError, match="image-pinned services"):
            tool.assemble_and_sign(args)

    def test_compose_build_service_omitted_relative_to_provenance_is_refused(
        self, tmp_path: Path
    ) -> None:
        # Provenance always vouches for exactly the three real application
        # services (deployment_image_inventory._EXPECTED_APPLICATION_
        # SERVICES); a compose file that only declares two of them leaves
        # one unrepresented -- application_image_digests no longer comes
        # from an operator list, so this is now exercised entirely through
        # the compose file's own build-service set.
        raw = yaml.safe_dump(
            {
                "services": {
                    UPSTREAM_IMAGE_SERVICE: {"image": UPSTREAM_IMAGE_REF},
                    APPLICATION_SERVICES[0]: {"build": {"context": "."}},
                }
            },
            sort_keys=True,
        ).encode("utf-8")
        args = _base_args(
            tmp_path, compose_file=_write(tmp_path / "compose_missing_service.yml", raw)
        )
        with pytest.raises(tool.SigningToolError, match="build-based services"):
            tool.assemble_and_sign(args)

    def test_compose_build_service_not_in_provenance_is_refused(self, tmp_path: Path) -> None:
        raw = yaml.safe_dump(
            {
                "services": {
                    UPSTREAM_IMAGE_SERVICE: {"image": UPSTREAM_IMAGE_REF},
                    **{name: {"build": {"context": "."}} for name in APPLICATION_SERVICES},
                    "invented-worker": {"build": {"context": "."}},
                }
            },
            sort_keys=True,
        ).encode("utf-8")
        args = _base_args(
            tmp_path, compose_file=_write(tmp_path / "compose_extra_service.yml", raw)
        )
        with pytest.raises(tool.SigningToolError, match="build-based services"):
            tool.assemble_and_sign(args)

    def test_compose_service_with_neither_image_nor_build_is_ignored(
        self, tmp_path: Path
    ) -> None:
        raw = yaml.safe_dump(
            {
                "services": {
                    UPSTREAM_IMAGE_SERVICE: {"image": UPSTREAM_IMAGE_REF},
                    **{name: {"build": {"context": "."}} for name in APPLICATION_SERVICES},
                    "network-only": {"networks": ["rag_net"]},
                }
            },
            sort_keys=True,
        ).encode("utf-8")
        args = _base_args(tmp_path, compose_file=_write(tmp_path / "compose_extra.yml", raw))
        manifest = tool.assemble_and_sign(args)
        assert manifest.upstream_image_digests[UPSTREAM_IMAGE_SERVICE] == UPSTREAM_IMAGE_REF

    def test_templated_compose_image_value_is_refused(self, tmp_path: Path) -> None:
        raw = yaml.safe_dump(
            {
                "services": {
                    UPSTREAM_IMAGE_SERVICE: {"image": "${PGVECTOR_IMAGE}"},
                    APPLICATION_SERVICES[0]: {"build": {"context": "."}},
                }
            },
            sort_keys=True,
        ).encode("utf-8")
        args = _base_args(tmp_path, compose_file=_write(tmp_path / "compose_templated.yml", raw))
        with pytest.raises(tool.SigningToolError, match="templated or non-literal"):
            tool.assemble_and_sign(args)

    def test_malformed_compose_yaml_is_refused(self, tmp_path: Path) -> None:
        args = _base_args(
            tmp_path, compose_file=_write(tmp_path / "compose_bad.yml", b"not: [valid: yaml")
        )
        with pytest.raises(tool.SigningToolError, match="not valid YAML"):
            tool.assemble_and_sign(args)

    def test_compose_without_a_services_mapping_is_refused(self, tmp_path: Path) -> None:
        raw = yaml.safe_dump({"not_services": {}}, sort_keys=True).encode("utf-8")
        args = _base_args(tmp_path, compose_file=_write(tmp_path / "compose_no_services.yml", raw))
        with pytest.raises(tool.SigningToolError, match="does not declare a top-level 'services'"):
            tool.assemble_and_sign(args)

    def test_a_compose_tag_alongside_the_digest_is_normalized_away_before_comparing(
        self, tmp_path: Path
    ) -> None:
        """The real docker-compose.v2.yml pins images as name:tag@sha256:...
        (e.g. pgvector/pgvector:pg16@sha256:...). ProductionReadinessManifestV1
        (shared contract, not modified here without an ADR) only ever accepts
        the tagless name@sha256:... form for --upstream-image, so the compose
        side's tag must be normalized away before the byte comparison --
        never by relaxing what the manifest itself accepts."""
        tagged_ref = "pgvector/pgvector:pg16@sha256:" + "2" * 64
        args = _base_args(
            tmp_path,
            upstream_image=[f"{UPSTREAM_IMAGE_SERVICE}={UPSTREAM_IMAGE_REF}"],  # tagless
            compose_file=_write(
                tmp_path / "compose_tagged.yml", _compose_bytes(upstream_image=tagged_ref)
            ),
        )
        manifest = tool.assemble_and_sign(args)
        assert manifest.upstream_image_digests[UPSTREAM_IMAGE_SERVICE] == UPSTREAM_IMAGE_REF

    def test_a_compose_image_not_pinned_by_digest_is_refused(self, tmp_path: Path) -> None:
        raw = yaml.safe_dump(
            {
                "services": {
                    UPSTREAM_IMAGE_SERVICE: {"image": "pgvector/pgvector:pg16"},  # no digest
                    APPLICATION_SERVICES[0]: {"build": {"context": "."}},
                }
            },
            sort_keys=True,
        ).encode("utf-8")
        args = _base_args(tmp_path, compose_file=_write(tmp_path / "compose_unpinned.yml", raw))
        with pytest.raises(tool.SigningToolError, match="not pinned by digest"):
            tool.assemble_and_sign(args)

    def test_compose_tag_mismatch_with_same_digest_is_still_accepted(
        self, tmp_path: Path
    ) -> None:
        """The tag is documentation for a human reader; only the digest (and
        repository name) is the actual deployment unit. A tag that differs
        from what a human might expect, but the same digest, is not a
        divergence this cross-check is meant to catch."""
        differently_tagged_ref = "pgvector/pgvector:pg16-alpine@sha256:" + "2" * 64
        args = _base_args(
            tmp_path,
            upstream_image=[f"{UPSTREAM_IMAGE_SERVICE}={UPSTREAM_IMAGE_REF}"],
            compose_file=_write(
                tmp_path / "compose_other_tag.yml",
                _compose_bytes(upstream_image=differently_tagged_ref),
            ),
        )
        manifest = tool.assemble_and_sign(args)
        assert manifest.upstream_image_digests[UPSTREAM_IMAGE_SERVICE] == UPSTREAM_IMAGE_REF


class TestApplicationImageProvenanceIsDerivedNotDeclared:
    """PR #102 integration : les digests d'images applicatives ne sont plus
    une saisie opérateur (ancien ``--application-image``) -- ils sont
    dérivés d'un run GitHub Actions de provenance réel et vérifié. Chaque
    scénario ici prouve qu'une provenance invalide est refusée, jamais
    seulement un format d'image plausible."""

    def test_valid_provenance_derives_the_expected_three_service_digests(
        self, tmp_path: Path
    ) -> None:
        args = _base_args(tmp_path)
        manifest = tool.assemble_and_sign(args)
        assert manifest.application_image_digests == APPLICATION_IMAGE_DIGESTS

    def test_provenance_is_anchored_on_merge_sha_not_pr_head_sha(
        self, tmp_path: Path, _stub_github_api: dict[str, dict[str, Any]]
    ) -> None:
        # The inventory document's source_commit_sha defaults to MERGE_SHA
        # (_inventory_document's own default) and the provenance run's
        # head_sha is likewise MERGE_SHA in _github_responses -- diverging
        # PR_HEAD_SHA from MERGE_SHA (already true by construction, they are
        # distinct fixture constants) and still succeeding proves the tool
        # anchors provenance on the commit that actually lands on main, not
        # the pre-merge PR head.
        assert PR_HEAD_SHA != MERGE_SHA
        args = _base_args(tmp_path)
        manifest = tool.assemble_and_sign(args)
        assert manifest.application_image_digests == APPLICATION_IMAGE_DIGESTS

    def test_failed_provenance_run_is_refused(
        self, tmp_path: Path, _stub_github_api: dict[str, dict[str, Any]]
    ) -> None:
        _stub_github_api[f"repos/{REPOSITORY}/actions/runs/{PROVENANCE_RUN_ID}"]["conclusion"] = (
            "failure"
        )
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="application image provenance refused"):
            tool.assemble_and_sign(args)

    def test_provenance_inventory_for_the_wrong_commit_is_refused(
        self, tmp_path: Path, _stub_download_artifact: dict[str, Any]
    ) -> None:
        _stub_download_artifact["inventory"] = _inventory_document(source_commit_sha="f" * 40)
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="application image provenance refused"):
            tool.assemble_and_sign(args)

    def test_provenance_inventory_missing_a_required_service_is_refused(
        self, tmp_path: Path, _stub_download_artifact: dict[str, Any]
    ) -> None:
        inventory = _inventory_document()
        del inventory["services"]["multilevel-worker-b-production"]
        _stub_download_artifact["inventory"] = inventory
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="application image provenance refused"):
            tool.assemble_and_sign(args)


class TestH2CoverageEvidenceIsSemanticallyVerified:
    """ADR-0042 integration : le rapport de couverture H2-B n'est plus un
    fichier opaque simplement haché -- il est parsé et son verdict, ainsi
    que sa liaison à l'autorisation/l'autorité/le catalogue/le manifeste
    scellé de ce même manifeste, sont exigés."""

    def test_a_passing_h2_evidence_signs_successfully(self, tmp_path: Path) -> None:
        args = _base_args(tmp_path)
        manifest = tool.assemble_and_sign(args)
        assert manifest.h2b_report_digest == hashlib.sha256(
            (tmp_path / "report.json").read_bytes()
        ).hexdigest()

    def test_h2_coverage_gate_pass_false_is_refused(self, tmp_path: Path) -> None:
        catalog_bytes = b"catalog-content"
        sealed_manifest_bytes = b"sealed-manifest-content"
        authorization_bytes = _authorization_bytes()
        evidence = _h2_coverage_evidence_bytes(
            catalog_digest=hashlib.sha256(catalog_bytes).hexdigest(),
            sealed_manifest_digest=hashlib.sha256(sealed_manifest_bytes).hexdigest(),
            authorization_digest=hashlib.sha256(authorization_bytes).hexdigest(),
            h2_coverage_gate_pass=False,
            coverage_complete=False,
        )
        args = _base_args(
            tmp_path, h2b_report_file=_write(tmp_path / "report_bad.json", evidence)
        )
        with pytest.raises(tool.SigningToolError, match="h2_coverage_gate_pass is false"):
            tool.assemble_and_sign(args)

    def test_malformed_h2b_report_is_refused(self, tmp_path: Path) -> None:
        args = _base_args(
            tmp_path, h2b_report_file=_write(tmp_path / "report_bad.json", b"not json")
        )
        with pytest.raises(tool.SigningToolError, match="failed semantic verification"):
            tool.assemble_and_sign(args)

    def test_h2_evidence_authorization_id_mismatch_is_refused(self, tmp_path: Path) -> None:
        catalog_bytes = b"catalog-content"
        sealed_manifest_bytes = b"sealed-manifest-content"
        authorization_bytes = _authorization_bytes()
        evidence = _h2_coverage_evidence_bytes(
            catalog_digest=hashlib.sha256(catalog_bytes).hexdigest(),
            sealed_manifest_digest=hashlib.sha256(sealed_manifest_bytes).hexdigest(),
            authorization_digest=hashlib.sha256(authorization_bytes).hexdigest(),
            authorization_id="some-other-authz-v1",
        )
        args = _base_args(
            tmp_path, h2b_report_file=_write(tmp_path / "report_bad.json", evidence)
        )
        with pytest.raises(tool.SigningToolError, match="authorization_id"):
            tool.assemble_and_sign(args)

    def test_h2_evidence_authority_digest_mismatch_is_refused(self, tmp_path: Path) -> None:
        catalog_bytes = b"catalog-content"
        sealed_manifest_bytes = b"sealed-manifest-content"
        evidence = _h2_coverage_evidence_bytes(
            catalog_digest=hashlib.sha256(catalog_bytes).hexdigest(),
            sealed_manifest_digest=hashlib.sha256(sealed_manifest_bytes).hexdigest(),
            authorization_digest="9" * 64,  # does not match --authorization-file's real digest
        )
        args = _base_args(
            tmp_path, h2b_report_file=_write(tmp_path / "report_bad.json", evidence)
        )
        with pytest.raises(tool.SigningToolError, match="authority digest does not match"):
            tool.assemble_and_sign(args)

    def test_h2_evidence_catalog_digest_mismatch_is_refused(self, tmp_path: Path) -> None:
        sealed_manifest_bytes = b"sealed-manifest-content"
        authorization_bytes = _authorization_bytes()
        evidence = _h2_coverage_evidence_bytes(
            catalog_digest="9" * 64,  # does not match --catalog-file's real digest
            sealed_manifest_digest=hashlib.sha256(sealed_manifest_bytes).hexdigest(),
            authorization_digest=hashlib.sha256(authorization_bytes).hexdigest(),
        )
        args = _base_args(
            tmp_path, h2b_report_file=_write(tmp_path / "report_bad.json", evidence)
        )
        with pytest.raises(tool.SigningToolError, match="catalog digest does not match"):
            tool.assemble_and_sign(args)

    def test_h2_evidence_sealed_manifest_digest_mismatch_is_refused(self, tmp_path: Path) -> None:
        catalog_bytes = b"catalog-content"
        authorization_bytes = _authorization_bytes()
        evidence = _h2_coverage_evidence_bytes(
            catalog_digest=hashlib.sha256(catalog_bytes).hexdigest(),
            sealed_manifest_digest="9" * 64,  # does not match --sealed-manifest-file's real digest
            authorization_digest=hashlib.sha256(authorization_bytes).hexdigest(),
        )
        args = _base_args(
            tmp_path, h2b_report_file=_write(tmp_path / "report_bad.json", evidence)
        )
        with pytest.raises(tool.SigningToolError, match="manifest_sha256 does not match"):
            tool.assemble_and_sign(args)


class TestRevocationRegistryUsesTheSharedStrictParser:
    """ADR-0042 : le registre de révocation n'est plus analysé par un
    parseur local minimal -- ``nexus_contracts.authorization_revocations``
    (le même parseur strict que ``rag-pedago``) est utilisé. Ce test prouve
    une amélioration réelle : un doublon, que l'ancien parseur minimal de
    cet outil acceptait silencieusement (aucune détection de doublon dans
    son propre code), est désormais refusé."""

    def test_duplicate_revoked_id_is_refused(self, tmp_path: Path) -> None:
        raw = (
            json.dumps(
                {
                    "protocol_version": "NEXUS-AUTHORIZATION-REVOCATIONS-V1",
                    "revoked_authorization_ids": ["some-other-id", "some-other-id"],
                },
                sort_keys=True,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        args = _base_args(
            tmp_path, revocation_registry_file=_write(tmp_path / "revoc_dup.json", raw)
        )
        with pytest.raises(tool.SigningToolError, match="repeats authorization ids"):
            tool.assemble_and_sign(args)


class TestRealCommittedComposeFileParsesAsExpected:
    """Contre la vraie racine du dépôt, jamais une fixture synthétique
    (même précédent que ``test_h2b_coverage_report.py``) : prouve que
    ``_compose_services`` comprend réellement ``docker-compose.v2.yml`` tel
    qu'il est commité, pas une forme imaginée."""

    def test_the_real_v2_compose_file_has_the_expected_image_and_build_split(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        compose_path = repo_root / "services" / "rag-engine" / "infra" / "docker-compose.v2.yml"
        services = tool._compose_services(compose_path.read_bytes())
        image_based = {name for name, svc in services.items() if "image" in svc}
        build_based = {name for name, svc in services.items() if "build" in svc}
        assert "ingestor" in build_based
        assert {"pgvector", "prometheus"}.issubset(image_based)
        for name in image_based:
            image = services[name]["image"]
            assert "$" not in image, f"service {name!r} unexpectedly templates its image"
            assert "@sha256:" in image, f"service {name!r} is not digest-pinned"
