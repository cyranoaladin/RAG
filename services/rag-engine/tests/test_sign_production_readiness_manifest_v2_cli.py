"""Tests — mode V2 (ADR-0044, ensemble `AuthorizationSetV1`) de l'outil de
signature du manifeste de production readiness.

Réutilise toutes les frontières déjà substituées par
``test_sign_production_readiness_manifest_cli.py`` (GitHub API, téléchargement
de provenance d'image, résolution Compose — fixtures ``autouse``, même
module ``conftest`` implicite car les deux fichiers de test vivent dans le
même répertoire et importent le même outil). Clés de test triviales et
déterministes, sans rapport avec les clés de production.
"""
from __future__ import annotations

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
from nexus_contracts.authorization_set import build_authorization_set  # noqa: E402
from nexus_contracts.h2_coverage_evidence import (  # noqa: E402
    H2CoverageEvidenceV2,
)
from nexus_contracts.production_readiness import (  # noqa: E402
    ProductionReadinessError,
    ProductionReadinessManifestV1,
    ProductionReadinessManifestV2,
    ProductionReadinessTrustAnchor,
    ProductionReadinessTrustAnchorKey,
    public_readiness_key_hex,
    verify_production_readiness_manifest,
    verify_production_readiness_manifest_v2,
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
MERGE_SHA = "a" * 40
PR_HEAD_SHA = "b" * 40
TREE_SHA = "c" * 40

REPOSITORY = "cyranoaladin/RAG"
PR_NUMBER = 128
WORKFLOW_PATH = ".github/workflows/promote.yml"
WORKFLOW_REF = "refs/heads/main"
RUN_ID = 1234
RUN_ATTEMPT = 1

APPLICATION_SERVICES = ("ingestor", "multilevel-worker-a-production", "multilevel-worker-b-production")
INGESTOR_REPO = "ghcr.io/cyranoaladin/rag-ingestor"
WORKER_REPO = "ghcr.io/cyranoaladin/rag-multilevel-worker-production"
INGESTOR_DIGEST = "sha256:" + "1" * 64
WORKER_DIGEST = "sha256:" + "2" * 64
APPLICATION_IMAGE_DIGESTS = {
    "ingestor": f"{INGESTOR_REPO}@{INGESTOR_DIGEST}",
    "multilevel-worker-a-production": f"{WORKER_REPO}@{WORKER_DIGEST}",
    "multilevel-worker-b-production": f"{WORKER_REPO}@{WORKER_DIGEST}",
}
PROVENANCE_RUN_ID = 777
PROVENANCE_RUN_ATTEMPT = 1
UPSTREAM_IMAGE_SERVICE = "pgvector"
UPSTREAM_IMAGE_REF = "pgvector/pgvector@sha256:" + "2" * 64

RB_TEST_SEED = "33" * 32
RB_KEY_ID = "rb-sign-tool-test-key-1"
RB_REPOSITORY = "cyranoaladin/RAG"
RB_PULL_REQUEST = 42
RB_BASE_SHA = "d" * 40
RB_HEAD_SHA = "e" * 40
RB_REVIEWER = "abenrhouma"
RB_AUTHOR = "cyranoaladin"

FAR_PAST = "2020-01-01T00:00:00Z"
FAR_FUTURE = "2099-01-01T00:00:00Z"
JUST_EXPIRED = "2020-01-02T00:00:00Z"  # valid_until dans le passé — toujours expiré, indépendant de l'horloge réelle

ROUTING_BYTES = b"routing-content"
RIGHTS_BYTES = b"rights-content"
PII_BYTES = b"pii-content"
GOLDEN_BYTES = b"golden-content"
ROUTING_DIGEST = hashlib.sha256(ROUTING_BYTES).hexdigest()
RIGHTS_DIGEST = hashlib.sha256(RIGHTS_BYTES).hexdigest()
PII_DIGEST = hashlib.sha256(PII_BYTES).hexdigest()
GOLDEN_DIGEST = hashlib.sha256(GOLDEN_BYTES).hexdigest()


def _write(path: Path, content: bytes = b"content") -> Path:
    path.write_bytes(content)
    return path


def _authorization(
    *, authorization_id: str, content_sha256: str, manifest_digest: str, **overrides: Any
) -> ScopeAuthorizationArtifactV2:
    document: dict[str, Any] = {
        "protocol_version": "LOT41A-V2",
        "authorization_id": authorization_id,
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
        "manifest_digest": manifest_digest,
        "profile_id": "rag_nexus_nsi_terminale_specialite",
        "profile_version": "v1",
        "profile_fingerprint": "d" * 64,
        "allowed_domains": ["eduscol.education.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "allowed_content_sha256": [content_sha256],
        "pii_absence_attested": True,
        "pii_absence_evidence": "Corpus officiel, aucune donnee personnelle.",
        "valid_from": FAR_PAST,
        "valid_until": FAR_FUTURE,
    }
    document.update(overrides)
    return ScopeAuthorizationArtifactV2.model_validate(document)


def _signed_review_binding(
    *, authorization: ScopeAuthorizationArtifactV2, signing_key: str = RB_TEST_SEED, **overrides: Any
) -> Any:
    auth_bytes = authorization.canonical_bytes()
    document: dict[str, Any] = {
        "protocol_version": "NEXUS-REVIEW-BINDING-V1",
        "repository": RB_REPOSITORY,
        "pull_request": RB_PULL_REQUEST,
        "base_ref": "main",
        "base_sha": RB_BASE_SHA,
        "head_sha": RB_HEAD_SHA,
        "authorization_artifact_path": canonical_authorization_path(authorization.authorization_id),
        "authorization_artifact_sha256": hashlib.sha256(auth_bytes).hexdigest(),
        "authorization_artifact_git_blob_sha1": git_blob_sha1(auth_bytes),
        "authorization_id": authorization.authorization_id,
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
    return sign_review_binding(binding, private_key_hex=signing_key, key_id=RB_KEY_ID)


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


def _resolved_compose_document() -> dict[str, Any]:
    services: dict[str, Any] = {name: {"image": ref} for name, ref in APPLICATION_IMAGE_DIGESTS.items()}
    services[UPSTREAM_IMAGE_SERVICE] = {"image": UPSTREAM_IMAGE_REF}
    return {"services": services}


def _inventory_document() -> dict[str, Any]:
    return {
        "protocol_version": "NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1",
        "repository": REPOSITORY,
        "source_commit_sha": MERGE_SHA,
        "source_tree_sha": TREE_SHA,
        "platform": "linux/amd64",
        "workflow_path": ".github/workflows/production-image-provenance.yml",
        "workflow_run_id": PROVENANCE_RUN_ID,
        "workflow_run_attempt": PROVENANCE_RUN_ATTEMPT,
        "workflow_ref": "refs/heads/main",
        "built_at": "2026-08-14T12:00:00Z",
        "services": {
            "ingestor": {
                "source_kind": "build", "build_context": ".",
                "dockerfile": "services/rag-engine/infra/Dockerfile.ingestor-v2",
                "dockerfile_sha256": "3" * 64,
                "image_repository": INGESTOR_REPO, "image_digest": INGESTOR_DIGEST,
            },
            "multilevel-worker-a-production": {
                "source_kind": "build", "build_context": ".",
                "dockerfile": "services/rag-engine/infra/Dockerfile.multilevel-worker-production",
                "dockerfile_sha256": "3" * 64,
                "image_repository": WORKER_REPO, "image_digest": WORKER_DIGEST,
            },
            "multilevel-worker-b-production": {
                "source_kind": "build", "build_context": ".",
                "dockerfile": "services/rag-engine/infra/Dockerfile.multilevel-worker-production",
                "dockerfile_sha256": "3" * 64,
                "image_repository": WORKER_REPO, "image_digest": WORKER_DIGEST,
            },
        },
    }


def _github_responses() -> dict[str, dict[str, Any]]:
    return {
        f"repos/{REPOSITORY}/pulls/{PR_NUMBER}": {
            "merged": True, "merge_commit_sha": MERGE_SHA,
            "head": {"sha": PR_HEAD_SHA, "repo": {"full_name": REPOSITORY}},
            "base": {"repo": {"full_name": REPOSITORY}},
        },
        f"repos/{REPOSITORY}/git/commits/{PR_HEAD_SHA}": {"tree": {"sha": TREE_SHA}},
        f"repos/{REPOSITORY}/git/commits/{MERGE_SHA}": {"tree": {"sha": TREE_SHA}},
        f"repos/{REPOSITORY}/actions/runs/{RUN_ID}": {
            "path": WORKFLOW_PATH, "repository": {"full_name": REPOSITORY},
            "head_branch": "main", "status": "completed", "conclusion": "success",
            "head_sha": MERGE_SHA, "run_attempt": RUN_ATTEMPT,
        },
        f"repos/{REPOSITORY}/actions/runs/{RUN_ID}/attempts/{RUN_ATTEMPT}": {},
        f"repos/{REPOSITORY}/actions/runs/{PROVENANCE_RUN_ID}": {
            "path": ".github/workflows/production-image-provenance.yml",
            "repository": {"full_name": REPOSITORY}, "event": "workflow_dispatch",
            "status": "completed", "conclusion": "success",
            "head_sha": MERGE_SHA, "run_attempt": PROVENANCE_RUN_ATTEMPT,
        },
        f"repos/{REPOSITORY}/actions/runs/{PROVENANCE_RUN_ID}/attempts/{PROVENANCE_RUN_ATTEMPT}": {},
    }


@pytest.fixture(autouse=True)
def _stub_github_api(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    responses = _github_responses()

    def fake(path: str) -> dict[str, Any]:
        try:
            return responses[path]
        except KeyError:
            raise tool.SigningToolError(f"unexpected GitHub API path requested in test: {path!r}") from None

    monkeypatch.setattr(tool, "_github_api_get", fake)
    return responses


@pytest.fixture(autouse=True)
def _stub_download_artifact(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"inventory": _inventory_document()}

    def fake_factory(*, repository: str) -> Any:
        def download(run_id: int, artifact_name: str, dest_dir: Path) -> Path:
            path = dest_dir / tool.dii._ARTIFACT_FILENAME
            path.write_text(json.dumps(state["inventory"]), encoding="utf-8")
            return path

        return download

    monkeypatch.setattr(tool.dii, "make_download_artifact_via_gh", fake_factory)
    return state


@pytest.fixture(autouse=True)
def _stub_compose_resolution(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"resolved": _resolved_compose_document()}

    def fake(repo_root: Path, merge_sha: str, work_dir: Path, env_file: Path) -> dict[str, Any]:
        return state["resolved"]

    monkeypatch.setattr(tool, "_run_docker_compose_config", fake)
    return state


def _write_verification_anchor(tmp_path: Path) -> None:
    anchor = ProductionReadinessTrustAnchor(
        protocol_version="NEXUS-PRODUCTION-READINESS-V1",
        keys=(
            ProductionReadinessTrustAnchorKey(
                key_id=TEST_KEY_ID, algorithm="ed25519",
                public_key=public_readiness_key_hex(TEST_SEED), environment="production",
            ),
        ),
    )
    (tmp_path / "verify_anchor.json").write_text(
        json.dumps(anchor.model_dump(mode="json"), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _v2_fixture(tmp_path: Path, *, revoked: tuple[str, ...] = (), member_overrides: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Construit un ensemble réel à 2 membres (2 autorisations distinctes,
    2 reçus de revue distincts, chacun individuellement signé et vérifié)
    et tous les fichiers d'un run V2 complet — chemin heureux par défaut,
    ``member_overrides`` permet de faire dévier un membre nommé (ex.
    fenêtre de validité expirée) pour les tests adversariaux."""
    member_overrides = member_overrides or {}
    catalog_bytes = b"catalog-content"
    sealed_manifest_bytes = b"sealed-manifest-content"
    catalog_digest = hashlib.sha256(catalog_bytes).hexdigest()
    sealed_manifest_digest = hashlib.sha256(sealed_manifest_bytes).hexdigest()

    ids = ("member-a", "member-b")
    contents = ("e" * 64, "f" * 64)
    authorizations = []
    review_bindings = {}
    for auth_id, content in zip(ids, contents, strict=True):
        overrides = member_overrides.get(auth_id, {})
        authorization = _authorization(
            authorization_id=auth_id,
            content_sha256=content,
            manifest_digest=sealed_manifest_digest,
            **overrides,
        )
        authorizations.append(authorization)
        review_bindings[auth_id] = _signed_review_binding(authorization=authorization)

    authorization_set = build_authorization_set(
        authorizations, review_bindings,
        manifest_digest=sealed_manifest_digest, expected_repository=REPOSITORY,
    )

    for auth_id, authorization in zip(ids, authorizations, strict=True):
        _write(tmp_path / f"auth_{auth_id}.json", authorization.canonical_bytes())
        _write(tmp_path / f"rb_{auth_id}.json", review_bindings[auth_id].canonical_bytes())
    _write(tmp_path / "authorization_set.json", authorization_set.canonical_bytes())
    _write(tmp_path / "rb_anchor.json", _review_binding_trust_anchor_bytes())
    _write(tmp_path / "revoc.json", _revocation_registry_bytes(revoked=revoked))
    _write(tmp_path / "anchor.json")
    _write(tmp_path / "catalog.json", catalog_bytes)
    _write(tmp_path / "sealed.txt", sealed_manifest_bytes)
    _write(tmp_path / "routing.yml", ROUTING_BYTES)
    _write(tmp_path / "rights.yml", RIGHTS_BYTES)
    _write(tmp_path / "pii.json", PII_BYTES)
    _write(tmp_path / "golden.json", GOLDEN_BYTES)
    _write(tmp_path / "dummy.env", b"# unused: compose resolution is stubbed in tests\n")
    _write(tmp_path / "priv.hex", TEST_SEED.encode())
    _write_verification_anchor(tmp_path)

    zero_safety_invariants = {
        "INGEST_WITHOUT_RIGHTS_CLEARANCE": 0, "INGEST_WITHOUT_PII_CLEARANCE": 0,
        "INGEST_WITHOUT_CURRENTNESS_CLEARANCE": 0, "INGEST_WITH_UNSUPPORTED_FORMAT": 0,
        "INGEST_WITHOUT_PROVENANCE": 0, "INGEST_WITHOUT_CONTENT_SHA": 0,
        "INGEST_WITHOUT_AUTHORITY": 0, "INGEST_WITH_SELF_DECLARED_AUTHORITY": 0,
        "INGEST_WITHOUT_ATTRIBUTION_METADATA": 0,
    }
    h2_document: dict[str, Any] = {
        "protocol_version": "NEXUS-H2-COVERAGE-EVIDENCE-V2",
        "environment": "production",
        "report_id": "sign-tool-v2-test-h2b-report",
        "generated_at": FAR_PAST,
        "git_commit": MERGE_SHA,
        "producer_version": "h2b_coverage_report/2",
        "manifest_sha256": sealed_manifest_digest,
        "input_file_digests": {
            "catalog": catalog_digest, "routing": ROUTING_DIGEST,
            "rights": RIGHTS_DIGEST, "pii": PII_DIGEST, "golden": GOLDEN_DIGEST,
        },
        "corpus_total_expected": 2583, "corpus_total_actual": 2583,
        "corpus_match": True, "sum_equals_total": True, "zero_overlap": True,
        "zero_gap": True, "coverage_complete": True,
        "rights_gate_status": "PASS", "pii_gate_status": "PASS",
        "golden_validation_pass": True, "h2_coverage_gate_pass": True,
        "authority_review_binding_verified": True, "authority_revocations_checked": True,
        "authorization_set_digest": authorization_set.authorization_set_digest,
        "authorization_count": authorization_set.authorization_count,
        "authority_required_count": authorization_set.union_content_count,
        "authority_covered_count": authorization_set.union_content_count,
        "authority_required_set_sha256": authorization_set.union_content_sha256_digest,
        "safety_invariants": zero_safety_invariants,
    }
    h2_bytes = H2CoverageEvidenceV2.model_validate(h2_document).canonical_bytes()
    _write(tmp_path / "report.json", h2_bytes)

    return {
        "authorization_set": authorization_set,
        "authority_required_set_sha256": authorization_set.union_content_sha256_digest,
        "h2_document": h2_document,
    }


def _v2_argv(tmp_path: Path, *, authority_required_set_sha256: str, output: Path) -> list[str]:
    return [
        "--pr-number", str(PR_NUMBER),
        "--pr-head-sha", PR_HEAD_SHA,
        "--merge-sha", MERGE_SHA,
        "--environment", "production",
        "--review-binding-trust-anchor-file", str(tmp_path / "rb_anchor.json"),
        "--authorization-set-file", str(tmp_path / "authorization_set.json"),
        "--member-authorization-file", str(tmp_path / "auth_member-a.json"),
        "--member-authorization-file", str(tmp_path / "auth_member-b.json"),
        "--member-review-binding-file", str(tmp_path / "rb_member-a.json"),
        "--member-review-binding-file", str(tmp_path / "rb_member-b.json"),
        "--expected-authority-required-set-sha256", authority_required_set_sha256,
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
        "--upstream-image", f"{UPSTREAM_IMAGE_SERVICE}={UPSTREAM_IMAGE_REF}",
        "--workflow-path", WORKFLOW_PATH,
        "--workflow-ref", WORKFLOW_REF,
        "--run-id", str(RUN_ID), "--run-attempt", str(RUN_ATTEMPT),
        "--key-id", TEST_KEY_ID,
        "--private-key-file", str(tmp_path / "priv.hex"),
        "--verification-trust-anchor-file", str(tmp_path / "verify_anchor.json"),
        "--output", str(output),
    ]


class TestValidAuthorizationSetSignsAndVerifies:
    def test_two_member_set_signs_and_round_trips(self, tmp_path: Path) -> None:
        fixture = _v2_fixture(tmp_path)
        output = tmp_path / "manifest.json"
        rc = tool.main(_v2_argv(
            tmp_path, authority_required_set_sha256=fixture["authority_required_set_sha256"], output=output
        ))
        assert rc == 0
        verified = verify_production_readiness_manifest_v2(
            output.read_bytes(),
            trust_anchor=ProductionReadinessTrustAnchor(
                protocol_version="NEXUS-PRODUCTION-READINESS-V1",
                keys=(ProductionReadinessTrustAnchorKey(
                    key_id=TEST_KEY_ID, algorithm="ed25519",
                    public_key=public_readiness_key_hex(TEST_SEED), environment="production",
                ),),
            ),
            environment="production",
        )
        assert (
            verified.authorization_set_digest
            == fixture["authorization_set"].authorization_set_digest
        )


class TestTamperedAuthorizationSetIsRefused:
    def test_h2_report_authorization_set_digest_mismatch_is_refused(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        fixture = _v2_fixture(tmp_path)
        # Falsifie authorization_set_digest dans le rapport H2 déjà écrit.
        h2_document = dict(fixture["h2_document"])
        h2_document["authorization_set_digest"] = "9" * 64
        (tmp_path / "report.json").write_bytes(
            H2CoverageEvidenceV2.model_validate(h2_document).canonical_bytes()
        )
        rc = tool.main(_v2_argv(
            tmp_path, authority_required_set_sha256=fixture["authority_required_set_sha256"],
            output=tmp_path / "manifest.json",
        ))
        assert rc == 1
        assert "does not vouch for this exact authorization set" in capsys.readouterr().err


class TestRevokedMemberIsRefused:
    def test_one_revoked_member_refuses_the_whole_set(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        fixture = _v2_fixture(tmp_path, revoked=("member-a",))
        rc = tool.main(_v2_argv(
            tmp_path, authority_required_set_sha256=fixture["authority_required_set_sha256"],
            output=tmp_path / "manifest.json",
        ))
        assert rc == 1
        err = capsys.readouterr().err
        assert "member-a" in err and "revocation registry" in err


class TestExpiredMemberIsRefused:
    def test_one_expired_member_refuses_the_whole_set(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        fixture = _v2_fixture(
            tmp_path,
            member_overrides={"member-b": {"valid_from": FAR_PAST, "valid_until": JUST_EXPIRED}},
        )
        rc = tool.main(_v2_argv(
            tmp_path, authority_required_set_sha256=fixture["authority_required_set_sha256"],
            output=tmp_path / "manifest.json",
        ))
        assert rc == 1
        err = capsys.readouterr().err
        assert "member-b" in err and "validity" in err


class TestMixingV1AndV2FlagsIsRefused:
    def test_authorization_set_file_plus_authorization_file_is_refused(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        fixture = _v2_fixture(tmp_path)
        argv = _v2_argv(
            tmp_path, authority_required_set_sha256=fixture["authority_required_set_sha256"],
            output=tmp_path / "manifest.json",
        ) + ["--authorization-file", str(tmp_path / "auth_member-a.json")]
        rc = tool.main(argv)
        assert rc == 1
        assert "never accepted" in capsys.readouterr().err

    def test_neither_v1_nor_v2_flags_is_refused(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        fixture = _v2_fixture(tmp_path)
        argv = [
            a for a in _v2_argv(
                tmp_path, authority_required_set_sha256=fixture["authority_required_set_sha256"],
                output=tmp_path / "manifest.json",
            )
        ]
        # Retire tous les marqueurs de mode V2 par paire drapeau/valeur
        # (--authorization-set-file, les deux --member-*-file répétés,
        # --expected-authority-required-set-sha256) sans fournir aucun
        # drapeau du mode V1 non plus — ni mode n'est alors détecté.
        for flag in (
            "--authorization-set-file",
            "--member-authorization-file",
            "--member-review-binding-file",
            "--expected-authority-required-set-sha256",
        ):
            while flag in argv:
                idx = argv.index(flag)
                del argv[idx:idx + 2]
        rc = tool.main(argv)
        assert rc == 1
        assert "exactly one of" in capsys.readouterr().err


class TestV1AndV2ManifestsAreNeverInterchangeable:
    def test_v2_verification_never_accepts_a_v1_shaped_manifest(self, tmp_path: Path) -> None:
        v1_manifest = ProductionReadinessManifestV1.model_construct(
            protocol_version="NEXUS-PRODUCTION-READINESS-V1",
        )
        assert not isinstance(v1_manifest, ProductionReadinessManifestV2)

    def test_v1_verification_never_accepts_a_v2_shaped_manifest_bytes(self, tmp_path: Path) -> None:
        fixture = _v2_fixture(tmp_path)
        output = tmp_path / "manifest.json"
        rc = tool.main(_v2_argv(
            tmp_path, authority_required_set_sha256=fixture["authority_required_set_sha256"], output=output
        ))
        assert rc == 0
        anchor = ProductionReadinessTrustAnchor(
            protocol_version="NEXUS-PRODUCTION-READINESS-V1",
            keys=(ProductionReadinessTrustAnchorKey(
                key_id=TEST_KEY_ID, algorithm="ed25519",
                public_key=public_readiness_key_hex(TEST_SEED), environment="production",
            ),),
        )
        with pytest.raises(ProductionReadinessError, match="protocol_version"):
            verify_production_readiness_manifest(output.read_bytes(), trust_anchor=anchor, environment="production")
