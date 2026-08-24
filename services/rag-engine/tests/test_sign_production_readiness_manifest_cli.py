"""Tests — outil de signature du manifeste de production readiness.

Clé de test triviale et déterministe : sans rapport avec les clés de
production (production-readiness PR #97, review-binding PR #99).
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

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
from nexus_contracts.authorization_set import (  # noqa: E402
    AuthorizationSetMemberV1,
    AuthorizationSetV1,
    ReleaseScopePlacementEntryV1,
    ReleaseScopePlacementV1,
    VerifiedProfileFactV1,
    canonical_review_binding_path,
    content_set_digest,
    scope_digest,
)
from nexus_contracts.h2_coverage_evidence import (  # noqa: E402
    H2_COVERAGE_EVIDENCE_PROTOCOL_VERSION,
    H2CoverageEvidenceV1,
    H2CoverageEvidenceV2,
)
from nexus_contracts.ingestion import (  # noqa: E402
    CollectionProfile,
    collection_profile_fingerprint,
)
from nexus_contracts.production_readiness import (  # noqa: E402
    ProductionReadinessError,
    ProductionReadinessTrustAnchor,
    ProductionReadinessTrustAnchorKey,
    public_readiness_key_hex,
    verify_production_readiness_manifest,
    verify_production_readiness_manifest_v2,
)
from nexus_contracts.profile_manifest import validate_production_profile_manifest  # noqa: E402
from nexus_contracts.release_evidence import (  # noqa: E402
    H2EvidenceBundleV2,
    PromotionEvidenceV2,
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
V2_NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


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


def _resolved_compose_document(
    *,
    upstream_image: str | None = UPSTREAM_IMAGE_REF,
    upstream_service: str = UPSTREAM_IMAGE_SERVICE,
    application_images: dict[str, str] | None = None,
    extra_services: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose déjà RÉSOLU (sortie de ``docker compose ... config --format
    json``, Section 11) -- jamais un YAML source brut. Par défaut, les
    trois services applicatifs y sont déjà pleinement résolus (plus de
    ``build:``, image épinglée EXACTEMENT égale à ``APPLICATION_IMAGE_
    DIGESTS``, la même provenance vérifiée que le reste de la suite) --
    reflète la release overlay réelle (``docker-compose.production-
    release.yml``'s ``!reset null`` + ``image: ${...}``), jamais l'ancien
    état ``build:``-only d'un fichier source unique."""
    app_images = application_images if application_images is not None else dict(APPLICATION_IMAGE_DIGESTS)
    services: dict[str, Any] = {name: {"image": ref} for name, ref in app_images.items()}
    if upstream_image is not None:
        services[upstream_service] = {"image": upstream_image}
    if extra_services:
        services.update(extra_services)
    return {"services": services}


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
    run_status: str = "completed",
    run_conclusion: str = "success",
    run_head_sha: str = MERGE_SHA,
    run_attempt_value: int = RUN_ATTEMPT,
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
        f"repos/{REPOSITORY}/git/ref/heads/main": {"object": {"sha": merge_sha}},
        f"repos/{REPOSITORY}/actions/runs/{RUN_ID}": {
            "path": workflow_path,
            "repository": {"full_name": workflow_repository},
            "head_branch": head_branch,
            "status": run_status,
            "conclusion": run_conclusion,
            "head_sha": run_head_sha,
            "run_attempt": run_attempt_value,
        },
        f"repos/{REPOSITORY}/actions/runs/{RUN_ID}/attempts/{RUN_ATTEMPT}": {},
        f"repos/{REPOSITORY}/actions/runs/{RUN_ID}/artifacts?per_page=100": {
            "total_count": 1,
            "artifacts": [
                {
                    "id": 9001,
                    "name": f"promotion-evidence-{merge_sha}-release-v2-test",
                    "expired": False,
                }
            ],
        },
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


@pytest.fixture(autouse=True)
def _stub_compose_resolution(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Substitue la troisième frontière process (résolution Compose,
    Section 11) -- jamais un vrai ``docker``/``git show`` dans ces tests
    unitaires (même convention que ``_stub_github_api``/``_stub_download_
    artifact`` ci-dessus). Chemin heureux par défaut (les trois services
    applicatifs pleinement résolus, épinglés à ``APPLICATION_IMAGE_
    DIGESTS``, plus l'upstream ``pgvector``) ; un test qui veut un
    scénario différent mute ``state["resolved"]`` avant d'appeler l'outil.
    ``state["calls"]`` enregistre chaque invocation pour les tests de
    câblage (repo_root/merge_sha/env_file transmis tels quels)."""
    state: dict[str, Any] = {
        "resolved": _resolved_compose_document(),
        "calls": [],
        "error": None,
    }

    def fake(repo_root: Path, merge_sha: str, work_dir: Path, env_file: Path) -> dict[str, Any]:
        state["calls"].append(
            {"repo_root": repo_root, "merge_sha": merge_sha, "work_dir": work_dir, "env_file": env_file}
        )
        if state["error"] is not None:
            raise state["error"]
        return state["resolved"]

    monkeypatch.setattr(tool, "_run_docker_compose_config", fake)
    return state


ROUTING_BYTES = b"routing-content"
RIGHTS_BYTES = b"rights-content"
PII_BYTES = b"pii-content"
GOLDEN_BYTES = b"golden-content"
ROUTING_DIGEST = hashlib.sha256(ROUTING_BYTES).hexdigest()
RIGHTS_DIGEST = hashlib.sha256(RIGHTS_BYTES).hexdigest()
PII_DIGEST = hashlib.sha256(PII_BYTES).hexdigest()
GOLDEN_DIGEST = hashlib.sha256(GOLDEN_BYTES).hexdigest()


def _h2_coverage_evidence_bytes(
    *,
    catalog_digest: str,
    sealed_manifest_digest: str,
    authorization_digest: str,
    routing_digest: str = ROUTING_DIGEST,
    rights_digest: str = RIGHTS_DIGEST,
    pii_digest: str = PII_DIGEST,
    golden_digest: str = GOLDEN_DIGEST,
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
            "routing": routing_digest,
            "rights": rights_digest,
            "pii": pii_digest,
            "golden": golden_digest,
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
        "--routing-file", str(_write(tmp_path / "routing.yml", ROUTING_BYTES)),
        "--rights-file", str(_write(tmp_path / "rights.yml", RIGHTS_BYTES)),
        "--pii-file", str(_write(tmp_path / "pii.json", PII_BYTES)),
        "--golden-file", str(_write(tmp_path / "golden.json", GOLDEN_BYTES)),
        "--env-file", str(_write(tmp_path / "dummy.env", b"# unused: compose resolution is stubbed in tests\n")),
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
        "--pr-number", "98",
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
        "--routing-file", str(tmp_path / "routing.yml"),
        "--rights-file", str(tmp_path / "rights.yml"),
        "--pii-file", str(tmp_path / "pii.json"),
        "--golden-file", str(tmp_path / "golden.json"),
        "--env-file", str(tmp_path / "dummy.env"),
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


class TestRepositoryIsNeverOperatorControlled:
    """Codex, PR #100 (même classe de défaut que PR #105) : le dépôt qui
    ancre PR/run/workflow/provenance d'image n'est plus un argument
    opérateur."""

    def test_no_repository_cli_flag_exists(self) -> None:
        help_text = tool._build_arg_parser().format_help()
        assert "--repository" not in help_text

    def test_trusted_repository_constant_is_the_real_repo(self) -> None:
        assert tool._TRUSTED_REPOSITORY == "cyranoaladin/RAG"


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

    def test_output_hardlinked_to_the_private_key_file_is_refused(self, tmp_path: Path) -> None:
        # Codex, PR #100: Path.resolve() never detects a hard link -- two
        # distinct directory entries pointing to the same inode, neither
        # of which is a symlink for resolve() to follow. Both paths
        # resolve to themselves, identical only by content/inode, which
        # only os.path.samefile()/st_ino catches.
        priv = tmp_path / "priv.hex"
        args = _base_args(tmp_path)
        hardlink = tmp_path / "priv_hardlink.hex"
        os.link(priv, hardlink)
        args.output = hardlink
        original = priv.read_bytes()
        with pytest.raises(tool.SigningToolError, match="hard link.*private-key-file"):
            tool._reject_output_aliasing_an_input(args)
        assert priv.read_bytes() == original

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
        with pytest.raises(tool.SigningToolError, match="is not the canonical promotion workflow"):
            tool.assemble_and_sign(args)

    def test_workflow_path_omitted_still_verifies_against_canonical_constant(
        self, tmp_path: Path, _stub_github_api: dict[str, dict[str, Any]]
    ) -> None:
        """``--workflow-path`` is optional -- verification against the
        canonical constant happens regardless of whether an operator
        supplies this now-redundant assertion."""
        args = _base_args(tmp_path, **{"workflow_path": None})
        manifest = tool.assemble_and_sign(args)
        assert manifest.workflow_path == tool._CANONICAL_PROMOTION_WORKFLOW_PATH

    def test_workflow_path_mismatching_the_canonical_constant_is_refused_before_any_live_check(
        self, tmp_path: Path, _stub_github_api: dict[str, dict[str, Any]]
    ) -> None:
        """An operator-supplied ``--workflow-path`` that disagrees with
        the canonical constant is refused immediately -- it is never the
        authority, only a redundant assertion checked against it."""
        args = _base_args(tmp_path, **{"workflow_path": ".github/workflows/some-other.yml"})
        with pytest.raises(tool.SigningToolError, match="does not match the canonical promotion workflow"):
            tool.assemble_and_sign(args)

    def test_manifest_workflow_path_is_always_the_canonical_constant(
        self, tmp_path: Path, _stub_github_api: dict[str, dict[str, Any]]
    ) -> None:
        args = _base_args(tmp_path)
        manifest = tool.assemble_and_sign(args)
        assert manifest.workflow_path == ".github/workflows/promote.yml"
        assert manifest.workflow_path == tool._CANONICAL_PROMOTION_WORKFLOW_PATH

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

    def test_failed_promotion_run_is_refused(
        self, tmp_path: Path, _stub_github_api: dict[str, dict[str, Any]]
    ) -> None:
        _stub_github_api[f"repos/{REPOSITORY}/actions/runs/{RUN_ID}"]["conclusion"] = "failure"
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="successfully completed"):
            tool.assemble_and_sign(args)

    def test_in_progress_promotion_run_is_refused(
        self, tmp_path: Path, _stub_github_api: dict[str, dict[str, Any]]
    ) -> None:
        _stub_github_api[f"repos/{REPOSITORY}/actions/runs/{RUN_ID}"]["status"] = "in_progress"
        _stub_github_api[f"repos/{REPOSITORY}/actions/runs/{RUN_ID}"]["conclusion"] = None
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="successfully completed"):
            tool.assemble_and_sign(args)

    def test_promotion_run_built_a_different_commit_is_refused(
        self, tmp_path: Path, _stub_github_api: dict[str, dict[str, Any]]
    ) -> None:
        _stub_github_api[f"repos/{REPOSITORY}/actions/runs/{RUN_ID}"]["head_sha"] = "f" * 40
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="not the commit being signed"):
            tool.assemble_and_sign(args)

    def test_promotion_run_current_attempt_diverging_from_declared_is_refused(
        self, tmp_path: Path, _stub_github_api: dict[str, dict[str, Any]]
    ) -> None:
        # The run was re-run since --run-attempt was recorded: its current
        # attempt (on the general run endpoint) no longer matches, even
        # though the /attempts/<n> sub-endpoint for the stale attempt
        # still exists and would otherwise pass unnoticed (Codex, same bug
        # class as PR #102).
        _stub_github_api[f"repos/{REPOSITORY}/actions/runs/{RUN_ID}"]["run_attempt"] = 2
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="was re-run since this attempt"):
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
    """Codex P1 (PR #100 §2-6, étendu Section 11) : ``--upstream-image``/
    les digests applicatifs dérivés de la provenance ne sont plus des
    affirmations indépendantes du Compose RÉSOLU -- chaque scénario prouve
    qu'une divergence entre les deux est refusée. Le Compose lui-même
    n'est plus un fichier source unique haché : c'est la sortie déjà
    résolue (``docker compose ... config --format json``) que
    ``_stub_compose_resolution`` fait passer par ``tool._run_docker_
    compose_config``, jamais un vrai ``docker``/``git`` dans cette suite."""

    def test_matching_compose_and_declared_images_signs_successfully(
        self, tmp_path: Path
    ) -> None:
        args = _base_args(tmp_path)
        manifest = tool.assemble_and_sign(args)
        assert manifest.upstream_image_digests[UPSTREAM_IMAGE_SERVICE] == UPSTREAM_IMAGE_REF
        assert manifest.application_image_digests == APPLICATION_IMAGE_DIGESTS

    def test_upstream_image_digest_diverging_from_compose_is_refused(
        self, tmp_path: Path
    ) -> None:
        args = _base_args(
            tmp_path,
            upstream_image=[f"{UPSTREAM_IMAGE_SERVICE}=pgvector/pgvector@sha256:" + "9" * 64],
        )
        with pytest.raises(tool.SigningToolError, match="does not match the resolved compose"):
            tool.assemble_and_sign(args)

    def test_upstream_service_omitted_from_declared_images_is_refused(
        self, tmp_path: Path
    ) -> None:
        # The default resolved compose pins exactly one upstream service
        # (pgvector); declaring zero upstream images leaves it
        # unrepresented -- caught by _image_digest_pairs itself (it already
        # refuses an empty list), before the cross-check even runs. Same
        # underlying gap either way: no unrepresented service is accepted.
        args = _base_args(tmp_path, upstream_image=[])
        with pytest.raises(tool.SigningToolError, match="must declare at least one image"):
            tool.assemble_and_sign(args)

    def test_upstream_service_omitted_while_another_is_present_is_refused(
        self, tmp_path: Path, _stub_compose_resolution: dict[str, Any]
    ) -> None:
        # Non-empty but still missing 'pgvector' -- exercises the
        # cross-check's set-mismatch branch specifically (distinct from the
        # empty-list case above, which never reaches it).
        _stub_compose_resolution["resolved"] = _resolved_compose_document(
            extra_services={"redis": {"image": "redis@sha256:" + "5" * 64}}
        )
        args = _base_args(tmp_path, upstream_image=[f"{UPSTREAM_IMAGE_SERVICE}={UPSTREAM_IMAGE_REF}"])
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

    def test_compose_application_service_missing_is_refused(
        self, tmp_path: Path, _stub_compose_resolution: dict[str, Any]
    ) -> None:
        # dii.require_resolved_compose_images_are_pinned itself refuses a
        # resolved compose that omits one of the three known application
        # services -- proven wired here, not re-derived (dii has its own
        # suite for the primitive itself).
        partial = dict(APPLICATION_IMAGE_DIGESTS)
        del partial[APPLICATION_SERVICES[0]]
        _stub_compose_resolution["resolved"] = _resolved_compose_document(application_images=partial)
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="missing expected service"):
            tool.assemble_and_sign(args)

    def test_compose_application_service_still_has_build_key_is_refused(
        self, tmp_path: Path, _stub_compose_resolution: dict[str, Any]
    ) -> None:
        # The release overlay's `!reset null` failing to take effect (wrong
        # compose files combined, or wrong order) leaves a 'build' key on a
        # resolved application service -- dii.require_resolved_compose_
        # images_are_pinned refuses this; proven wired here.
        resolved = _resolved_compose_document()
        resolved["services"][APPLICATION_SERVICES[0]] = {"build": {"context": "."}}
        _stub_compose_resolution["resolved"] = resolved
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="still resolves with a 'build' key"):
            tool.assemble_and_sign(args)

    def test_compose_application_image_diverging_from_provenance_is_refused(
        self, tmp_path: Path, _stub_compose_resolution: dict[str, Any]
    ) -> None:
        # NEW in Section 11 (previously this file only compared service
        # NAMES between compose and provenance, never the image digest
        # itself -- same class of gap already closed for
        # verify_release_image_provenance_cli.py, PR #105 round 2). A
        # correctly-formed, digest-pinned image that simply isn't the one
        # the verified provenance run actually produced must be refused.
        diverged = dict(APPLICATION_IMAGE_DIGESTS)
        diverged[APPLICATION_SERVICES[0]] = f"{INGESTOR_REPO}@sha256:" + "9" * 64
        _stub_compose_resolution["resolved"] = _resolved_compose_document(application_images=diverged)
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="do not match verified provenance"):
            tool.assemble_and_sign(args)

    def test_unexpected_build_based_service_outside_application_set_is_refused(
        self, tmp_path: Path, _stub_compose_resolution: dict[str, Any]
    ) -> None:
        _stub_compose_resolution["resolved"] = _resolved_compose_document(
            extra_services={"invented-worker": {"build": {"context": "."}}}
        )
        args = _base_args(tmp_path)
        with pytest.raises(
            tool.SigningToolError,
            match="still resolves with a 'build' key and is not one of the known application services",
        ):
            tool.assemble_and_sign(args)

    def test_compose_service_with_neither_image_nor_build_is_ignored(
        self, tmp_path: Path, _stub_compose_resolution: dict[str, Any]
    ) -> None:
        _stub_compose_resolution["resolved"] = _resolved_compose_document(
            extra_services={"network-only": {"networks": ["rag_net"]}}
        )
        args = _base_args(tmp_path)
        manifest = tool.assemble_and_sign(args)
        assert manifest.upstream_image_digests[UPSTREAM_IMAGE_SERVICE] == UPSTREAM_IMAGE_REF

    def test_resolved_compose_without_a_services_mapping_is_refused(
        self, tmp_path: Path, _stub_compose_resolution: dict[str, Any]
    ) -> None:
        _stub_compose_resolution["resolved"] = {"not_services": {}}
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="has no 'services' mapping"):
            tool.assemble_and_sign(args)

    def test_an_upstream_image_not_pinned_by_digest_is_refused(
        self, tmp_path: Path, _stub_compose_resolution: dict[str, Any]
    ) -> None:
        # A fully resolved Compose is not supposed to leave an unpinned
        # image behind, but this tool never assumes that -- it is refused
        # explicitly rather than silently trusted.
        _stub_compose_resolution["resolved"] = _resolved_compose_document(
            upstream_image="pgvector/pgvector:pg16"  # no digest
        )
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="not pinned by digest"):
            tool.assemble_and_sign(args)

    def test_compose_digest_reflects_the_resolved_compose_content(
        self, tmp_path: Path, _stub_compose_resolution: dict[str, Any]
    ) -> None:
        # compose_digest (Section 11) is a digest of the resolved config,
        # not of a raw source file -- changing the resolved content (here,
        # an extra ignored service) must change the signed digest.
        args_a = _base_args(tmp_path)
        manifest_a = tool.assemble_and_sign(args_a)

        _stub_compose_resolution["resolved"] = _resolved_compose_document(
            extra_services={"network-only": {"networks": ["rag_net"]}}
        )
        args_b = _base_args(tmp_path)
        manifest_b = tool.assemble_and_sign(args_b)
        assert manifest_a.compose_digest != manifest_b.compose_digest

    def test_compose_resolution_is_invoked_with_the_signed_merge_sha(
        self, tmp_path: Path, _stub_compose_resolution: dict[str, Any]
    ) -> None:
        # The three canonical Compose files must be read from the exact
        # commit being signed (merge_sha) -- never from a possibly-
        # diverged working tree, never from the PR head before merge.
        args = _base_args(tmp_path)
        tool.assemble_and_sign(args)
        assert len(_stub_compose_resolution["calls"]) == 1
        call = _stub_compose_resolution["calls"][0]
        assert call["merge_sha"] == MERGE_SHA
        assert call["env_file"] == args.env_file
        assert call["repo_root"] == args.repo_root

    def test_compose_resolution_failure_is_surfaced_as_signing_tool_error(
        self, tmp_path: Path, _stub_compose_resolution: dict[str, Any]
    ) -> None:
        _stub_compose_resolution["error"] = tool.SigningToolError(
            "compose resolution refused: env file not found (simulated)"
        )
        args = _base_args(tmp_path)
        with pytest.raises(tool.SigningToolError, match="env file not found"):
            tool.assemble_and_sign(args)


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

    @pytest.mark.parametrize(
        "evidence_kwarg,cli_arg,expected_key",
        [
            ("routing_digest", "routing_file", "routing"),
            ("rights_digest", "rights_file", "rights"),
            ("pii_digest", "pii_file", "pii"),
            ("golden_digest", "golden_file", "golden"),
        ],
    )
    def test_h2_evidence_routing_rights_pii_golden_digest_mismatch_is_refused(
        self, tmp_path: Path, evidence_kwarg: str, cli_arg: str, expected_key: str
    ) -> None:
        # Codex, PR #100 §10: catalog/authority were confronted to real
        # files, but routing/rights/pii/golden could carry an arbitrary
        # digest -- an H2 report structurally valid but unbound to any
        # real evidence for these four inputs would still pass. Each
        # parametrized case proves one of the four is now refused.
        catalog_bytes = b"catalog-content"
        sealed_manifest_bytes = b"sealed-manifest-content"
        authorization_bytes = _authorization_bytes()
        evidence = _h2_coverage_evidence_bytes(
            catalog_digest=hashlib.sha256(catalog_bytes).hexdigest(),
            sealed_manifest_digest=hashlib.sha256(sealed_manifest_bytes).hexdigest(),
            authorization_digest=hashlib.sha256(authorization_bytes).hexdigest(),
            **{evidence_kwarg: "9" * 64},
        )
        args = _base_args(
            tmp_path, h2b_report_file=_write(tmp_path / "report_bad.json", evidence)
        )
        with pytest.raises(tool.SigningToolError, match=f"{expected_key} digest does not match"):
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

    def test_h2_evidence_git_commit_not_matching_merge_sha_is_refused(
        self, tmp_path: Path
    ) -> None:
        catalog_bytes = b"catalog-content"
        sealed_manifest_bytes = b"sealed-manifest-content"
        authorization_bytes = _authorization_bytes()
        evidence = _h2_coverage_evidence_bytes(
            catalog_digest=hashlib.sha256(catalog_bytes).hexdigest(),
            sealed_manifest_digest=hashlib.sha256(sealed_manifest_bytes).hexdigest(),
            authorization_digest=hashlib.sha256(authorization_bytes).hexdigest(),
            git_commit="f" * 40,  # does not match --merge-sha
        )
        args = _base_args(
            tmp_path, h2b_report_file=_write(tmp_path / "report_bad.json", evidence)
        )
        with pytest.raises(tool.SigningToolError, match="git_commit .* does not match"):
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


class TestMultiAuthorizationReadinessV2Surface:
    def test_v2_verification_boundary_is_explicit(self) -> None:
        """Le nouveau chemin ne peut pas retomber sur l'assembleur V1."""
        assert callable(tool.verify_v2_release_material)
        assert callable(tool.assemble_and_sign_v2)

    def test_signer_never_imports_another_service(self) -> None:
        source = Path(tool.__file__).read_text(encoding="utf-8")
        assert "rag_pedago" not in source
        assert "services/rag-pedago" not in source

    def test_rag_engine_production_code_has_no_cross_service_python_import(self) -> None:
        service_root = Path(__file__).resolve().parents[1]
        violations: list[str] = []
        for source_path in sorted(
            path
            for directory in ("backend", "scripts", "src")
            for path in (service_root / directory).rglob("*.py")
        ):
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules = (
                    [node.module]
                    if isinstance(node, ast.ImportFrom)
                    else [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else []
                )
                if any(
                    module == "rag_pedago" or module.startswith("rag_pedago.")
                    for module in modules
                    if module is not None
                ):
                    violations.append(f"{source_path.relative_to(service_root)}:{node.lineno}")
        assert violations == []

    def test_v2_cli_exposes_only_set_based_authority_flags(self) -> None:
        parser = tool._build_v2_arg_parser()
        help_text = parser.format_help()
        flags = {flag for action in parser._actions for flag in action.option_strings}
        assert "--authorization-set-file" in help_text
        assert "--governed-root" in help_text
        assert "--authorization-file" not in flags
        assert "--review-binding-file" not in flags
        assert "--json-output" in help_text

    def test_v2_signing_requires_the_exact_promotion_artifact_from_the_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        material = _v2_material()
        downloaded = material.promotion_evidence_raw + b" "

        def fake_download(run_id: int, artifact_name: str, dest_dir: Path) -> Path:
            assert run_id == RUN_ID
            assert artifact_name == f"promotion-evidence-{MERGE_SHA}-release-v2-test"
            return _write(dest_dir / "promotion-evidence.json", downloaded)

        monkeypatch.setattr(tool, "_download_promotion_artifact_via_gh", fake_download)
        args = argparse.Namespace(run_id=RUN_ID, run_attempt=RUN_ATTEMPT)

        with pytest.raises(tool.SigningToolError, match="exact promotion evidence artifact"):
            tool._verify_promotion_artifact_matches_run(args, material)

    def test_v2_signing_accepts_only_one_current_exact_named_artifact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        material = _v2_material()
        calls: list[tuple[int, str]] = []

        def fake_download(run_id: int, artifact_name: str, dest_dir: Path) -> Path:
            calls.append((run_id, artifact_name))
            return _write(
                dest_dir / "promotion-evidence.json",
                material.promotion_evidence_raw,
            )

        monkeypatch.setattr(tool, "_download_promotion_artifact_via_gh", fake_download)
        args = argparse.Namespace(run_id=RUN_ID, run_attempt=RUN_ATTEMPT)

        tool._verify_promotion_artifact_matches_run(args, material)

        assert calls == [
            (RUN_ID, f"promotion-evidence-{MERGE_SHA}-release-v2-test")
        ]

    def test_v2_signing_refuses_when_main_advanced_after_promotion(
        self, _stub_github_api: dict[str, dict[str, Any]]
    ) -> None:
        endpoint = f"repos/{REPOSITORY}/git/ref/heads/main"
        _stub_github_api[endpoint]["object"]["sha"] = "f" * 40

        with pytest.raises(tool.SigningToolError, match="main HEAD"):
            tool._require_live_main_head(MERGE_SHA)

    def test_v2_main_rechecks_main_immediately_before_private_key_use(self) -> None:
        source = Path(tool.__file__).read_text(encoding="utf-8")
        main_v2 = source[source.index("def _main_v2(") : source.index("def main(", source.index("def _main_v2("))]
        recheck = main_v2.index("_require_live_main_head(merge_sha)")
        key_read = main_v2.index("args.private_key_file")
        assert recheck < key_read

    @pytest.mark.parametrize(
        ("artifact_mutation", "message"),
        [
            (lambda artifacts: [], "exactly one"),
            (lambda artifacts: artifacts + [dict(artifacts[0], id=9002)], "exactly one"),
            (lambda artifacts: [dict(artifacts[0], expired=True)], "expired"),
        ],
    )
    def test_v2_signing_refuses_missing_duplicate_or_expired_promotion_artifact(
        self,
        artifact_mutation: Any,
        message: str,
        _stub_github_api: dict[str, dict[str, Any]],
    ) -> None:
        material = _v2_material()
        endpoint = f"repos/{REPOSITORY}/actions/runs/{RUN_ID}/artifacts?per_page=100"
        response = _stub_github_api[endpoint]
        artifacts = artifact_mutation(response["artifacts"])
        response["artifacts"] = artifacts
        response["total_count"] = len(artifacts)

        with pytest.raises(tool.SigningToolError, match=message):
            tool._verify_promotion_artifact_matches_run(
                argparse.Namespace(run_id=RUN_ID, run_attempt=RUN_ATTEMPT),
                material,
            )

    @staticmethod
    def _v2_alias_args(tmp_path: Path, *, output: Path) -> argparse.Namespace:
        material = _v2_material()
        repository = tmp_path / "repository"
        governed = repository / "governed"
        for relative, raw in material.release_files.items():
            (governed / relative).parent.mkdir(parents=True, exist_ok=True)
            _write(governed / relative, raw)
        authorization_set = _write(
            tmp_path / "authorization-set.json", material.authorization_set_raw
        )
        return argparse.Namespace(
            output=output,
            governed_root=governed,
            repo_root=repository,
            authorization_set_file=authorization_set,
            trust_anchor_file=_write(tmp_path / "readiness-anchor.json", b"anchor"),
            revocation_registry_file=_write(
                tmp_path / "revocations.json", material.revocation_registry_raw
            ),
        )

    def test_v2_output_inside_governed_root_is_refused(self, tmp_path: Path) -> None:
        args = self._v2_alias_args(
            tmp_path, output=tmp_path / "repository" / "governed" / "out.json"
        )
        with pytest.raises(tool.SigningToolError, match="governed root"):
            tool._reject_v2_output_aliasing_an_input(args)

    def test_v2_output_inside_repository_input_directory_is_refused(
        self, tmp_path: Path
    ) -> None:
        args = self._v2_alias_args(
            tmp_path, output=tmp_path / "repository" / "readiness.json"
        )
        with pytest.raises(tool.SigningToolError, match="repo-root"):
            tool._reject_v2_output_aliasing_an_input(args)

    def test_v2_output_hardlink_to_dynamic_member_is_refused(self, tmp_path: Path) -> None:
        args = self._v2_alias_args(tmp_path, output=tmp_path / "outside.json")
        material = _v2_material()
        member = args.governed_root / next(iter(material.release_files))
        args.output.hardlink_to(member)
        with pytest.raises(tool.SigningToolError, match="member"):
            tool._reject_v2_output_aliasing_an_input(args)

    @pytest.mark.parametrize(
        "target",
        [
            "authorization_member",
            "review_binding_member",
            "authorization_set_file",
            "trust_anchor_file",
            "revocation_registry_file",
        ],
    )
    def test_v2_output_equal_to_every_sensitive_input_is_refused(
        self, tmp_path: Path, target: str
    ) -> None:
        args = self._v2_alias_args(tmp_path, output=tmp_path / "outside.json")
        material = _v2_material()
        if target == "authorization_member":
            args.output = args.governed_root / next(
                path for path in material.release_files if "/authorizations/" in path
            )
        elif target == "review_binding_member":
            args.output = args.governed_root / next(
                path for path in material.release_files if "/review-bindings/" in path
            )
        else:
            args.output = getattr(args, target)
        with pytest.raises(tool.SigningToolError, match="output"):
            tool._reject_v2_output_aliasing_an_input(args)

    def test_v2_output_symlink_alias_is_refused(self, tmp_path: Path) -> None:
        args = self._v2_alias_args(tmp_path, output=tmp_path / "outside.json")
        args.output.symlink_to(args.authorization_set_file)
        with pytest.raises(tool.SigningToolError, match="symlink"):
            tool._reject_v2_output_aliasing_an_input(args)


def _v2_material() -> tool.V2ReleaseMaterial:
    profile_source_document = {
        "profile_version": "v1",
        "enabled": True,
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
        "title": "Profil NSI terminale",
        "owner": "tests",
        "expected_topics": ["notion"],
        "expected_resource_types": ["cours"],
        "allowed_domains": ["eduscol.education.fr"],
        "source_authority": "official",
        "search_cadence": "weekly",
        "max_queries_per_run": 1,
        "max_documents_per_run": 1,
        "max_chunk_size": 800,
        "chunk_overlap": 100,
        "min_source_confidence": 0.7,
        "min_scope_confidence": 0.7,
        "min_extraction_quality": 0.7,
    }
    profile_fingerprint = collection_profile_fingerprint(
        CollectionProfile.model_validate(profile_source_document)
    )
    profile_manifest_raw = f'''manifest_version: "1"
provenance: "test"
generated_at: "2026-08-23T08:00:00+00:00"
profiles:
  - collection: rag_nexus_nsi_terminale_specialite
    profile_version: v1
    fingerprint: {profile_fingerprint}
    approved_by: abenrhouma
    approved_at: "2026-08-23T08:00:00+00:00"
'''.encode()
    profile_digest = validate_production_profile_manifest(
        profile_manifest_raw,
        profile_fingerprints={
            ("rag_nexus_nsi_terminale_specialite", "v1"): profile_fingerprint
        },
        source="profiles-manifest.yml",
    ).manifest_fingerprint
    authorization_raw = _authorization_bytes(
        manifest_digest=profile_digest,
        profile_fingerprint=profile_fingerprint,
    )
    authorization = tool.parse_scope_authorization_artifact(authorization_raw)
    binding_raw = _signed_review_binding_bytes(
        authorization_bytes=authorization_raw,
        submitted_at=V2_NOW - timedelta(hours=4),
        verified_at=V2_NOW - timedelta(hours=3),
        expires_at=V2_NOW + timedelta(days=7),
    )
    member = AuthorizationSetMemberV1.model_validate(
        {
            "authorization_id": authorization.authorization_id,
            "authorization_digest": sha256(authorization_raw).hexdigest(),
            "review_binding_digest": sha256(binding_raw).hexdigest(),
            "scope": authorization.scope,
            "scope_digest": scope_digest(authorization.scope),
            "allowed_content_sha256": authorization.allowed_content_sha256,
            "allowed_content_count": 1,
            "allowed_content_set_sha256": content_set_digest(
                authorization.allowed_content_sha256
            ),
            "valid_from": authorization.valid_from,
            "valid_until": authorization.valid_until,
        }
    )
    profile = VerifiedProfileFactV1(
        profile_id=authorization.profile_id,
        profile_version=authorization.profile_version,
        profile_fingerprint=authorization.profile_fingerprint,
        scope=authorization.scope,
    )
    placement = ReleaseScopePlacementV1.build(
        placements=(
            ReleaseScopePlacementEntryV1(
                content_sha256=authorization.allowed_content_sha256[0],
                profile_id=authorization.profile_id,
                profile_version=authorization.profile_version,
                profile_fingerprint=authorization.profile_fingerprint,
                scope=authorization.scope,
            ),
        ),
        profile_manifest_digest=profile_digest,
    )
    sealed_manifest_raw = b"sealed-corpus-manifest\n"
    authorization_set = AuthorizationSetV1.build(
        members=(member,),
        corpus_manifest_sha256=sha256(sealed_manifest_raw).hexdigest(),
        profile_manifest_digest=profile_digest,
        release_scope_placement_digest=placement.digest(),
        authority_required_content_sha256=authorization.allowed_content_sha256,
    )
    trust_anchor_raw = _review_binding_trust_anchor_bytes()
    revocations_raw = _revocation_registry_bytes()
    catalog_raw = b"catalog-v2\n"
    trusted_reviewers_raw = (
        json.dumps(
            {"repository": REPOSITORY, "reviewers": [RB_REVIEWER]},
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode()
    evidence_files = {
        "catalog": catalog_raw,
        "routing": b"routing-v2\n",
        "rights": b"rights-v2\n",
        "pii": b"pii-v2\n",
        "golden": b"golden-v2\n",
        "currentness_verification": b"currentness-v2\n",
        "authorization_set": authorization_set.canonical_bytes(),
        "authority_revocations": revocations_raw,
        "review_binding_trust_anchor": trust_anchor_raw,
        "release_scope_placement": placement.canonical_bytes(),
        "trusted_reviewers": trusted_reviewers_raw,
    }
    input_digests = {name: sha256(raw).hexdigest() for name, raw in evidence_files.items()}
    release_scope_git_paths = {
        "profile_proposal_matrix_path": "governance/profile-matrix.json",
        "accepted_placements_path": "governance/placements.json",
        "release_registry_path": "governance/release-registry.json",
        "expected_contents_path": "governance/expected-contents.txt",
        "verified_profiles_path": "governance/verified-profiles.json",
        "profile_manifest_path": "governance/profile-manifest.yml",
    }
    profile_source_path = "profiles/nsi.yml"

    def canonical_fixture(document: Any) -> bytes:
        return (json.dumps(document, sort_keys=True, indent=2) + "\n").encode()

    scope_document = authorization.scope.model_dump(mode="json")
    release_scope_source_blobs = {
        release_scope_git_paths["profile_proposal_matrix_path"]: canonical_fixture(
            [
                {
                    "partition_id": "P01",
                    "partition_kind": "EXACT_VERSIONED_RELEASE_PROFILE",
                    "content_count": 1,
                    "content_sha256": list(authorization.allowed_content_sha256),
                    "profile_decision_required": False,
                    "evidence_sources": [profile_source_path],
                    "dimensions": {
                        name: {
                            "value": value,
                            "grounded": True,
                            "source_of_truth": profile_source_path,
                        }
                        for name, value in scope_document.items()
                    },
                }
            ]
        ),
        release_scope_git_paths["accepted_placements_path"]: canonical_fixture(
            [
                {
                    "content_sha256": authorization.allowed_content_sha256[0],
                    "release_id": "release-v2-test",
                    "collection": authorization.profile_id,
                    "profile_version": authorization.profile_version,
                }
            ]
        ),
        release_scope_git_paths["release_registry_path"]: canonical_fixture(
            {
                "registry_version": "1",
                "school_year": authorization.scope.school_year,
                "releases": [
                    {
                        "release_id": "release-v2-test",
                        "collections": [authorization.profile_id],
                    }
                ],
            }
        ),
        release_scope_git_paths["expected_contents_path"]: (
            f"{authorization.allowed_content_sha256[0]}\n".encode()
        ),
        release_scope_git_paths["verified_profiles_path"]: canonical_fixture(
            {
                "profile_manifest_digest": profile_digest,
                "profiles": [
                    {**profile.model_dump(mode="json"), "source_path": profile_source_path}
                ],
            }
        ),
        release_scope_git_paths["profile_manifest_path"]: profile_manifest_raw,
        profile_source_path: canonical_fixture(profile_source_document),
    }
    release_scope_source_digests = {
        path: sha256(raw).hexdigest()
        for path, raw in release_scope_source_blobs.items()
    }
    safety = {
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
    coverage = H2CoverageEvidenceV2(
        protocol_version="NEXUS-H2-COVERAGE-EVIDENCE-V2",
        environment="production",
        report_id="v2-readiness-test",
        generated_at=V2_NOW - timedelta(hours=1),
        git_commit=MERGE_SHA,
        producer_version="h2b/2",
        corpus_manifest_sha256=authorization_set.corpus_manifest_sha256,
        profile_manifest_digest=profile_digest,
        authorization_set_digest=authorization_set.digest(),
        authorization_count=1,
        authorization_set_verified_at=V2_NOW - timedelta(hours=2),
        earliest_review_submitted_at=V2_NOW - timedelta(hours=4),
        earliest_review_binding_verified_at=V2_NOW - timedelta(hours=3),
        earliest_review_binding_expires_at=V2_NOW + timedelta(days=7),
        authorizations_effective_valid_until=authorization_set.authorizations_effective_valid_until,
        release_scope_source_tree_sha=TREE_SHA,
        release_scope_placement_digest=placement.digest(),
        release_scope_source_blob_digests=release_scope_source_digests,
        input_file_digests=input_digests,
        corpus_total_expected=1,
        corpus_total_actual=1,
        corpus_match=True,
        sum_equals_total=True,
        zero_overlap=True,
        zero_gap=True,
        coverage_complete=True,
        rights_gate_status="PASS",
        pii_gate_status="PASS",
        golden_validation_pass=True,
        h2_coverage_gate_pass=True,
        authority_review_bindings_verified=True,
        authority_revocations_checked=True,
        authority_required_count=1,
        authority_covered_count=1,
        authority_required_set_sha256=authorization_set.authority_required_set_sha256,
        authorization_overlap_count=0,
        authorization_gap_count=0,
        authorization_extra_count=0,
        safety_invariants=safety,
    )
    bundle = H2EvidenceBundleV2(
        protocol_version="NEXUS-H2-EVIDENCE-V2",
        repository=REPOSITORY,
        pull_request_number=PR_NUMBER,
        pr_head_sha=PR_HEAD_SHA,
        pr_head_tree_sha=TREE_SHA,
        merge_sha=MERGE_SHA,
        merge_tree_sha=TREE_SHA,
        campaign_id="release-v2-test",
        campaign_digest="1" * 64,
        source_oci_digest="sha256:" + "2" * 64,
        source_archive_sha256="3" * 64,
        source_tree_digest="4" * 64,
        corpus_manifest_sha256=authorization_set.corpus_manifest_sha256,
        catalog_sha256=sha256(catalog_raw).hexdigest(),
        review_view_sha256="5" * 64,
        profile_manifest_digest=profile_digest,
        authorization_set_digest=authorization_set.digest(),
        authorization_count=1,
        authority_required_count=1,
        authority_required_set_sha256=authorization_set.authority_required_set_sha256,
        release_scope_source_tree_sha=TREE_SHA,
        release_scope_placement_digest=placement.digest(),
        release_scope_source_blob_digests=release_scope_source_digests,
        revocation_registry_sha256=sha256(revocations_raw).hexdigest(),
        review_binding_trust_anchor_sha256=sha256(trust_anchor_raw).hexdigest(),
        trusted_reviewers_sha256=sha256(trusted_reviewers_raw).hexdigest(),
        input_file_digests=input_digests,
        authorization_set_verified_at=coverage.authorization_set_verified_at,
        earliest_review_submitted_at=coverage.earliest_review_submitted_at,
        earliest_review_binding_verified_at=coverage.earliest_review_binding_verified_at,
        earliest_review_binding_expires_at=coverage.earliest_review_binding_expires_at,
        authorizations_effective_valid_from=authorization_set.authorizations_effective_valid_from,
        authorizations_effective_valid_until=authorization_set.authorizations_effective_valid_until,
        h2_coverage_generated_at=coverage.generated_at,
        h2_coverage_evidence_sha256=sha256(coverage.canonical_bytes()).hexdigest(),
        h2_coverage_gate_pass=True,
        authority_revocations_checked=True,
        authority_review_bindings_verified=True,
        coverage_complete=True,
        authority_covered_count=1,
        authorization_overlap_count=0,
        authorization_gap_count=0,
        authorization_extra_count=0,
        environment="production",
        workflow_path=".github/workflows/_produce-h2-evidence.yml",
        run_id="123",
        run_attempt=1,
    )
    promotion = PromotionEvidenceV2.model_validate(
        PromotionEvidenceV2.fields_from_h2_bundle(
            bundle,
            image_provenance_run_id=PROVENANCE_RUN_ID,
            image_provenance_run_attempt=PROVENANCE_RUN_ATTEMPT,
            promotion_workflow_path=WORKFLOW_PATH,
            promotion_run_id=RUN_ID,
            promotion_run_attempt=RUN_ATTEMPT,
            promotion_workflow_ref=WORKFLOW_REF,
        )
    )
    return tool.V2ReleaseMaterial(
        authorization_set_raw=authorization_set.canonical_bytes(),
        release_files={
            authorization.canonical_path(): authorization_raw,
            canonical_review_binding_path(authorization.authorization_id): binding_raw,
        },
        review_binding_trust_anchor_raw=trust_anchor_raw,
        trusted_reviewers_raw=trusted_reviewers_raw,
        revocation_registry_raw=revocations_raw,
        release_scope_placement_raw=placement.canonical_bytes(),
        release_scope_source_blobs=release_scope_source_blobs,
        verified_profiles=(profile,),
        profile_manifest_raw=profile_manifest_raw,
        authority_required_content_sha256=authorization.allowed_content_sha256,
        h2_coverage_raw=coverage.canonical_bytes(),
        h2_evidence_bundle_raw=bundle.canonical_bytes(),
        promotion_evidence_raw=promotion.canonical_bytes(),
        evidence_files=evidence_files,
        sealed_manifest_raw=sealed_manifest_raw,
        now=V2_NOW,
        merge_sha=MERGE_SHA,
        merge_tree_sha=TREE_SHA,
        release_scope_git_paths=release_scope_git_paths,
    )


class TestMultiAuthorizationReadinessV2Verification:
    def test_exact_release_material_is_verified_by_one_global_boundary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        material = _v2_material()
        original = tool.rv2.verify_authorization_set
        calls = 0

        def counted(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(tool.rv2, "verify_authorization_set", counted)
        verified = tool.verify_v2_release_material(material)
        assert calls == 1
        assert verified.authorization_set.digest() == verified.h2_bundle.authorization_set_digest

    @pytest.mark.parametrize(
        ("field", "replacement", "message"),
        [
            ("authorization_set_raw", b"{}\n", "authorization set"),
            ("release_scope_placement_raw", b"{}\n", "placement"),
            ("sealed_manifest_raw", b"other\n", "corpus manifest"),
            ("revocation_registry_raw", _revocation_registry_bytes(revoked=(AUTHORIZATION_ID,)), "revoked"),
        ],
    )
    def test_substituted_or_revoked_material_is_refused(
        self, field: str, replacement: bytes, message: str
    ) -> None:
        material = _v2_material()
        changed = tool.dataclasses.replace(material, **{field: replacement})
        with pytest.raises(tool.SigningToolError, match=message):
            tool.verify_v2_release_material(changed)

    def test_v2_readiness_is_signed_and_never_parses_as_v1(self) -> None:
        material = _v2_material()
        manifest = tool.assemble_and_sign_v2(
            material,
            repository=REPOSITORY,
            pr_number=PR_NUMBER,
            pr_head_sha=PR_HEAD_SHA,
            pr_head_tree_sha=TREE_SHA,
            application_image_digests=APPLICATION_IMAGE_DIGESTS,
            upstream_image_digests={UPSTREAM_IMAGE_SERVICE: UPSTREAM_IMAGE_REF},
            compose_digest="8" * 64,
            key_id=TEST_KEY_ID,
            workflow_ref=WORKFLOW_REF,
        )
        signed = tool.sign_production_readiness_manifest_v2(
            manifest, private_key_hex=TEST_SEED, key_id=TEST_KEY_ID
        )
        anchor = ProductionReadinessTrustAnchor(
            protocol_version="NEXUS-PRODUCTION-READINESS-V1",
            keys=(
                ProductionReadinessTrustAnchorKey(
                    key_id=TEST_KEY_ID,
                    algorithm="ed25519",
                    public_key=public_readiness_key_hex(TEST_SEED),
                    environment="production",
                ),
            ),
        )
        assert verify_production_readiness_manifest_v2(
            signed.canonical_bytes(), trust_anchor=anchor
        ).authorization_set_digest == sha256(material.authorization_set_raw).hexdigest()
        with pytest.raises(ProductionReadinessError, match="V1"):
            verify_production_readiness_manifest(signed.canonical_bytes(), trust_anchor=anchor)

    def test_v2_inputs_are_opened_without_following_symlinks(self, tmp_path: Path) -> None:
        target = _write(tmp_path / "real.json", b"secret")
        link = tmp_path / "link.json"
        link.symlink_to(target)
        with pytest.raises(tool.SigningToolError, match="symlink"):
            tool._read_bytes_no_follow(link, label="authorization_set")

    def test_signed_output_is_atomic_private_and_does_not_follow_symlinks(
        self, tmp_path: Path
    ) -> None:
        output = tmp_path / "readiness.json"
        tool._atomic_private_write(output, b"signed\n")
        assert output.read_bytes() == b"signed\n"
        assert output.stat().st_mode & 0o777 == 0o600
        victim = _write(tmp_path / "victim", b"unchanged")
        alias = tmp_path / "alias"
        alias.symlink_to(victim)
        with pytest.raises(tool.SigningToolError, match="symlink"):
            tool._atomic_private_write(alias, b"overwrite")
        assert victim.read_bytes() == b"unchanged"

    def test_missing_and_extra_member_files_are_refused(self) -> None:
        material = _v2_material()
        missing = dict(material.release_files)
        missing.pop(next(iter(missing)))
        with pytest.raises(tool.SigningToolError, match="missing release material"):
            tool.verify_v2_release_material(
                tool.dataclasses.replace(material, release_files=missing)
            )
        extra = dict(material.release_files)
        extra["governance/authorizations/extra.json"] = b"{}\n"
        with pytest.raises(tool.SigningToolError, match="extra release material"):
            tool.verify_v2_release_material(
                tool.dataclasses.replace(material, release_files=extra)
            )

    def test_bad_member_and_review_binding_digests_are_refused(self) -> None:
        material = _v2_material()
        files = dict(material.release_files)
        authorization_path = next(path for path in files if "/authorizations/" in path)
        files[authorization_path] += b" "
        with pytest.raises(tool.SigningToolError, match="authorization_digest"):
            tool.verify_v2_release_material(
                tool.dataclasses.replace(material, release_files=files)
            )

    def test_release_scope_exact_tree_source_substitution_is_refused(self) -> None:
        material = _v2_material()
        profile_source = next(
            path for path in material.release_scope_source_blobs if path.startswith("profiles/")
        )
        with pytest.raises(tool.SigningToolError, match="exact-tree"):
            tool.verify_v2_release_material(
                tool.dataclasses.replace(
                    material,
                    release_scope_source_blobs={
                        **material.release_scope_source_blobs,
                        profile_source: b"opaque-invalid-profile-bytes\n",
                    },
                )
            )

    def test_forged_verified_profile_fact_is_refused_by_exact_tree_producer(self) -> None:
        material = _v2_material()
        forged = material.verified_profiles[0].model_copy(
            update={"profile_fingerprint": "f" * 64}
        )
        with pytest.raises(tool.SigningToolError, match="profile facts"):
            tool.verify_v2_release_material(
                tool.dataclasses.replace(material, verified_profiles=(forged,))
            )

    def test_profile_source_mismatch_is_refused_by_shared_producer(self) -> None:
        material = _v2_material()
        profile_source = next(
            path for path in material.release_scope_source_blobs if path.startswith("profiles/")
        )
        document = json.loads(material.release_scope_source_blobs[profile_source])
        document["scope"]["matiere"] = "francais"
        blobs = dict(material.release_scope_source_blobs)
        blobs[profile_source] = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode()
        with pytest.raises(tool.SigningToolError, match="PROFILE_SOURCE_MISMATCH"):
            tool.verify_v2_release_material(
                tool.dataclasses.replace(material, release_scope_source_blobs=blobs)
            )

    def test_private_key_material_is_never_echoed_in_a_signing_error(self) -> None:
        material = _v2_material()
        manifest = tool.assemble_and_sign_v2(
            material,
            repository=REPOSITORY,
            pr_number=PR_NUMBER,
            pr_head_sha=PR_HEAD_SHA,
            pr_head_tree_sha=TREE_SHA,
            application_image_digests=APPLICATION_IMAGE_DIGESTS,
            upstream_image_digests={UPSTREAM_IMAGE_SERVICE: UPSTREAM_IMAGE_REF},
            compose_digest="8" * 64,
            key_id=TEST_KEY_ID,
            workflow_ref=WORKFLOW_REF,
        )
        private_material = "TOP-SECRET-NOT-A-KEY"
        with pytest.raises(ProductionReadinessError) as error:
            tool.sign_production_readiness_manifest_v2(
                manifest,
                private_key_hex=private_material,
                key_id=TEST_KEY_ID,
            )
        assert private_material not in str(error.value)

        files = dict(material.release_files)
        binding_path = next(path for path in files if "/review-bindings/" in path)
        files[binding_path] += b" "
        with pytest.raises(tool.SigningToolError, match="review_binding_digest"):
            tool.verify_v2_release_material(
                tool.dataclasses.replace(material, release_files=files)
            )

    def test_half_open_authorization_and_binding_expiry_are_refused(self) -> None:
        material = _v2_material()
        authorization = tool.parse_scope_authorization_artifact(
            next(raw for path, raw in material.release_files.items() if "/authorizations/" in path)
        )
        with pytest.raises(tool.SigningToolError, match="expired"):
            tool.verify_v2_release_material(
                tool.dataclasses.replace(material, now=authorization.valid_until)
            )

        coverage = tool.parse_h2_coverage_evidence_v2(material.h2_coverage_raw)
        with pytest.raises(tool.SigningToolError, match="expired"):
            tool.verify_v2_release_material(
                tool.dataclasses.replace(
                    material,
                    now=coverage.earliest_review_binding_expires_at,
                )
            )

    @pytest.mark.parametrize(
        ("field", "message"),
        [
            ("h2_coverage_raw", "H2"),
            ("h2_evidence_bundle_raw", "H2"),
            ("promotion_evidence_raw", "promotion"),
        ],
    )
    def test_substituted_h2_or_promotion_document_is_refused(
        self, field: str, message: str
    ) -> None:
        material = _v2_material()
        with pytest.raises(tool.SigningToolError, match=message):
            tool.verify_v2_release_material(
                tool.dataclasses.replace(material, **{field: b"{}\n"})
            )

    def test_repromoted_h2_bundle_with_changed_routing_digest_is_refused(self) -> None:
        material = _v2_material()
        bundle = tool.parse_h2_evidence_bundle_v2(material.h2_evidence_bundle_raw)
        changed_inputs = dict(bundle.input_file_digests)
        changed_inputs["routing"] = "f" * 64
        changed_bundle = bundle.model_copy(update={"input_file_digests": changed_inputs})
        promotion = tool.PromotionEvidenceV2.model_validate(
            tool.PromotionEvidenceV2.fields_from_h2_bundle(
                changed_bundle,
                image_provenance_run_id=PROVENANCE_RUN_ID,
                image_provenance_run_attempt=PROVENANCE_RUN_ATTEMPT,
                promotion_workflow_path=WORKFLOW_PATH,
                promotion_run_id=RUN_ID,
                promotion_run_attempt=RUN_ATTEMPT,
                promotion_workflow_ref=WORKFLOW_REF,
            )
        )
        with pytest.raises(tool.SigningToolError, match="input_file_digests"):
            tool.verify_v2_release_material(
                tool.dataclasses.replace(
                    material,
                    h2_evidence_bundle_raw=changed_bundle.canonical_bytes(),
                    promotion_evidence_raw=promotion.canonical_bytes(),
                )
            )


# Section 11 : plus de ``_compose_services`` local à prouver contre les
# vrais fichiers Compose commités -- la résolution elle-même délègue
# entièrement à ``verify_release_image_provenance_cli.run_docker_compose_
# config_via_subprocess`` (PR #105), déjà exercée contre un vrai
# ``docker compose`` et un vrai ``git show`` par
# ``TestRunDockerComposeConfigViaSubprocess`` dans
# ``test_verify_release_image_provenance_cli.py`` (skip si Docker est
# absent). Redériver cette même preuve ici pour une fonction que ce
# fichier ne fait qu'appeler, sans logique propre, serait une pure
# duplication (AGENTS.md, DRY) -- l'ancienne classe
# ``TestRealCommittedComposeFileParsesAsExpected`` est supprimée plutôt
# que réécrite.
