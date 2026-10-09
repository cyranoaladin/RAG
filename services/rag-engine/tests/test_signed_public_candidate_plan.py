"""Le wrapper signé qualifie un candidat public sans autoriser de mutation."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import deploy_verified_release_cli as dep  # noqa: E402
import deployment_image_inventory as dii  # noqa: E402
import public_blue_green_preflight as public  # noqa: E402
import sign_production_readiness_manifest_cli as sign_cli  # noqa: E402
from nexus_contracts.production_readiness import public_readiness_key_hex  # noqa: E402

from tests.test_deploy_verified_release_cli import (
    _run_document,  # noqa: E402
    _trust_anchor_bytes,  # noqa: E402
)
from tests.test_deployment_image_inventory import _public_inventory  # noqa: E402
from tests.test_public_blue_green_preflight import (  # noqa: E402
    COCKPIT_IMAGE,
    IMAGE,
    SHA,
    _cockpit_fixture,
    _fixture,
)
from tests.test_sign_production_readiness_manifest_cli import (  # noqa: E402
    APPLICATION_IMAGE_DIGESTS,
    PR_HEAD_SHA,
    PR_NUMBER,
    TEST_KEY_ID,
    TEST_SEED,
    TREE_SHA,
    WORKFLOW_REF,
    _v2_material,
)


def _inventory(material: dep.signer.V2ReleaseMaterial, *, application_claim: str = IMAGE) -> dict:
    images = {**APPLICATION_IMAGE_DIGESTS, "ingestor": application_claim, "cockpit": COCKPIT_IMAGE}
    return {
        "protocol_version": dii._PUBLIC_PROTOCOL_VERSION,
        "repository": "cyranoaladin/RAG",
        "source_commit_sha": material.merge_sha,
        "source_tree_sha": material.merge_tree_sha,
        "workflow_run_id": 777,
        "workflow_run_attempt": 1,
        "services": {
            name: {"image_repository": ref.split("@")[0], "image_digest": ref.split("@")[1]}
            for name, ref in images.items()
        },
    }


def _signed_public(
    config: dict, *, application_claim: str = IMAGE, upstream_claim: str | None = None,
    legacy: bool = False,
) -> tuple[bytes, bytes, dep.signer.V2ReleaseMaterial]:
    material = _v2_material()
    inventory = _inventory(material, application_claim=application_claim)
    digest = hashlib.sha256(public.vri.canonical_resolved_compose_bytes(config)).hexdigest()
    upstream = {
        name: config["services"][name]["image"]
        for name in ("pgvector", "prometheus", "session-redis")
        if name in config["services"]
    }
    if upstream_claim is not None:
        upstream["pgvector"] = upstream_claim
    manifest = dep.signer.assemble_and_sign_v2(
        material,
        repository="cyranoaladin/RAG",
        pr_number=PR_NUMBER,
        pr_head_sha=PR_HEAD_SHA,
        pr_head_tree_sha=TREE_SHA,
        application_image_digests=(
            {"ingestor": application_claim} if legacy else
            {name: f"{item['image_repository']}@{item['image_digest']}"
             for name, item in inventory["services"].items()}
        ),
        upstream_image_digests=upstream,
        compose_digest=digest,
        key_id=TEST_KEY_ID,
        workflow_ref=WORKFLOW_REF,
        public_candidate_inventory_digest=(
            None if legacy else dii.public_candidate_inventory_digest(inventory)
        ),
    )
    signed = dep.signer.sign_production_readiness_manifest_v2(
        manifest, private_key_hex=TEST_SEED, key_id=TEST_KEY_ID
    ).canonical_bytes()
    anchor = json.loads(_trust_anchor_bytes(key_id=TEST_KEY_ID))
    anchor["keys"][0]["public_key"] = public_readiness_key_hex(TEST_SEED)
    return signed, json.dumps(anchor).encode(), material


def _plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mutation: str = "",
    verify_calls: list[None] | None = None,
    legacy: bool = False,
) -> dict:
    config, root, secrets, repo = (
        _fixture(tmp_path) if legacy else _cockpit_fixture(tmp_path)
    )
    application_claim = IMAGE
    upstream_claim = None
    if mutation == "application_claim":
        application_claim = "ghcr.io/cyranoaladin/rag-ingestor@sha256:" + "0" * 64
    elif mutation == "upstream_claim":
        upstream_claim = "postgres@sha256:" + "0" * 64
    signed, anchor, material = _signed_public(
        config, application_claim=application_claim, upstream_claim=upstream_claim,
        legacy=legacy,
    )
    promotion = dep.signer.verify_v2_release_material(material).promotion
    if verify_calls is not None:
        original_verify = dep.signer.verify_v2_release_material

        def count_verify(material: dep.signer.V2ReleaseMaterial) -> dep.signer.VerifiedV2ReleaseMaterial:
            verify_calls.append(None)
            return original_verify(material)

        monkeypatch.setattr(dep.signer, "verify_v2_release_material", count_verify)
    monkeypatch.setattr(
        dii, "fetch_and_verify_public_candidate_image_provenance_document",
        lambda **kwargs: _inventory(material),
    )
    if mutation == "compose":
        config["services"]["ingestor"]["ports"][0]["published"] = "18102"
    elif mutation == "network":
        config["services"]["pgvector"]["networks"]["bff_net"] = None
    elif mutation == "image":
        config["services"]["ingestor"]["image"] = "ghcr.io/cyranoaladin/rag-ingestor@sha256:" + "0" * 64
    elif mutation == "material":
        (root / "postgres/init.sql").write_text("changed", encoding="utf-8")
    elif mutation == "signature":
        signed = signed.replace(b"production", b"staging")
    return dep.plan_signed_public_candidate(
        resolved_compose=config,
        source_sha=SHA,
        source_tree_sha=material.merge_tree_sha,
        color="blue",
        material_root=root,
        secrets_root=secrets,
        repo_root=repo,
        provenance_run_id=promotion.image_provenance_run_id,
        provenance_run_attempt=promotion.image_provenance_run_attempt,
        github_api_get=lambda path: {},
        download_artifact=lambda run, name, where: where,
        work_dir=tmp_path / "work",
        readiness_manifest_raw=signed,
        trust_anchor_raw=anchor,
        release_material=material,
    )


def test_signed_public_candidate_is_only_a_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    verify_calls: list[None] = []
    result = _plan(tmp_path, monkeypatch, verify_calls=verify_calls)
    assert len(verify_calls) == 1
    assert result["signed_readiness_valid"] is True
    assert result["project"] == "nexus-rag-blue"
    assert result["mutation_allowed"] is False
    assert result["production_ready"] is False
    assert result["go_live_ready"] is False
    assert "public_edge_ingest_denial_unverified" in result["missing_cutover_preconditions"]


def test_legacy_v2_readiness_is_not_public_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(dep.DeploymentWrapperError, match="public candidate inventory"):
        _plan(tmp_path, monkeypatch, legacy=True)


@pytest.mark.parametrize("mutation", ["compose", "network", "image", "material", "signature"])
def test_plan_refuses_unsigned_or_divergent_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    with pytest.raises((dep.DeploymentWrapperError, public.PublicCandidateError)):
        _plan(tmp_path, monkeypatch, mutation=mutation)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("application_claim", "public candidate inventory differs from signed readiness"),
        ("upstream_claim", "public candidate upstream images differ from signed readiness"),
    ],
)
def test_plan_refuses_validly_signed_but_wrong_image_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str, message: str
) -> None:
    with pytest.raises(dep.DeploymentWrapperError, match=message):
        _plan(tmp_path, monkeypatch, mutation=mutation)


def _signed_public_bundle(
    tmp_path: Path, *, legacy: bool = False, artifact_mutation: str | None = None
) -> tuple[Path, bytes, dict]:
    config, _root, _secrets, _repo = _cockpit_fixture(tmp_path)
    material = _v2_material()
    inventory = _public_inventory(
        source_commit_sha=material.merge_sha,
        source_tree_sha=material.merge_tree_sha,
        workflow_run_id=777,
        workflow_run_attempt=1,
    )
    inventory["services"]["ingestor"]["image_digest"] = IMAGE.split("@")[1]
    inventory["services"]["cockpit"]["image_digest"] = COCKPIT_IMAGE.split("@")[1]
    manifest = dep.signer.assemble_and_sign_v2(
        material,
        repository="cyranoaladin/RAG",
        pr_number=PR_NUMBER,
        pr_head_sha=PR_HEAD_SHA,
        pr_head_tree_sha=TREE_SHA,
        application_image_digests={
            name: f"{item['image_repository']}@{item['image_digest']}"
            for name, item in inventory["services"].items()
        } if not legacy else {"ingestor": IMAGE},
        upstream_image_digests={
            name: config["services"][name]["image"]
            for name in ("pgvector", "prometheus", "session-redis")
        },
        compose_digest=hashlib.sha256(public.vri.canonical_resolved_compose_bytes(config)).hexdigest(),
        key_id=TEST_KEY_ID,
        workflow_ref=WORKFLOW_REF,
        public_candidate_inventory_digest=(
            None if legacy else dii.public_candidate_inventory_digest(inventory)
        ),
    )
    signed = dep.signer.sign_production_readiness_manifest_v2(
        manifest, private_key_hex=TEST_SEED, key_id=TEST_KEY_ID
    ).canonical_bytes()
    readiness = tmp_path / "readiness.json"
    readiness.write_bytes(signed)
    anchor = json.loads(_trust_anchor_bytes(key_id=TEST_KEY_ID))
    anchor["keys"][0]["public_key"] = public_readiness_key_hex(TEST_SEED)
    anchor_raw = json.dumps(anchor).encode()
    anchor_file = tmp_path / "anchor.json"
    anchor_file.write_bytes(anchor_raw)
    env_file = tmp_path / "public.env"
    env_file.write_bytes(b"COMPOSE_PROJECT_NAME=nexus-rag-blue\n")
    calls: list[tuple[str, ...]] = []

    def download(_run: int, _name: str, where: Path) -> Path:
        path = where / dii._PUBLIC_ARTIFACT_FILENAME
        artifact = json.loads(json.dumps(inventory))
        if artifact_mutation == "wrong_run":
            artifact["workflow_run_attempt"] = 2
        elif artifact_mutation == "wrong_cockpit_digest":
            artifact["services"]["cockpit"]["image_digest"] = "sha256:" + "0" * 64
        elif artifact_mutation == "missing_cockpit":
            artifact["services"].pop("cockpit")
        path.write_bytes(dii.public_candidate_inventory_bytes(artifact))
        return path

    def resolve(_repo: Path, _sha: str, files: tuple[str, ...], _work: Path, _env: Path) -> dict:
        calls.append(files)
        return config

    bundle = tmp_path / "bundle"
    dep.materialize_verified_bundle(
        merge_sha=material.merge_sha,
        merge_tree_sha=material.merge_tree_sha,
        provenance_run_id=777,
        provenance_run_attempt=1,
        repo_root=tmp_path,
        env_file=env_file,
        readiness_manifest_file=readiness,
        trust_anchor_file=anchor_file,
        environment="production",
        github_api_get=lambda _path: _run_document(),
        download_artifact=download,
        run_docker_compose_config=resolve,
        work_dir=tmp_path / "work",
        bundle_dir=bundle,
        git_show_bytes=lambda _repo, _sha, path: path.encode(),
        readiness_protocol="NEXUS-PRODUCTION-READINESS-V2",
        v2_release_material=material,
        public_candidate=True,
    )
    assert calls == [public.vri._PUBLIC_CANDIDATE_COMPOSE_FILES]
    return bundle, anchor_raw, config


def test_public_bundle_is_signed_plan_only_with_two_runtime_images(tmp_path: Path) -> None:
    bundle, anchor, config = _signed_public_bundle(tmp_path)
    document = json.loads((bundle / dep._BUNDLE_MANIFEST_NAME).read_bytes())
    assert document["public_candidate"] is True
    assert document["compose_files"] == list(public.vri._PUBLIC_CANDIDATE_COMPOSE_FILES)
    assert set(document["verified_images"]) == {"ingestor", "cockpit"}
    assert set(json.loads((bundle / dep._IMAGE_PROVENANCE_BUNDLE_NAME).read_bytes())["services"]) == {
        "ingestor", "cockpit", "multilevel-worker-a-production", "multilevel-worker-b-production"
    }
    seen: list[tuple[str, ...]] = []

    def resolve(_bundle: Path, _env: Path, files: tuple[str, ...]) -> dict:
        seen.append(files)
        return config

    plan = dep.deploy_from_bundle(
        bundle_dir=bundle, merge_sha=SHA, execute=False,
        trusted_readiness_anchor_raw=anchor, run_bundle_compose_config=resolve,
    )
    assert seen == [public.vri._PUBLIC_CANDIDATE_COMPOSE_FILES]
    assert all("docker-compose.public-blue-green.yml" in command for command in plan)
    assert all("docker-compose.production-release.yml" not in command for command in plan)
    with pytest.raises(dep.DeploymentWrapperError, match="plan-only"):
        dep.deploy_from_bundle(
            bundle_dir=bundle, merge_sha=SHA, execute=True,
            trusted_readiness_anchor_raw=anchor, run_bundle_compose_config=resolve,
        )


def test_public_bundle_refuses_legacy_v2_before_materialization(tmp_path: Path) -> None:
    with pytest.raises(dep.DeploymentWrapperError, match="public candidate inventory"):
        _signed_public_bundle(tmp_path, legacy=True)
    assert not (tmp_path / "bundle").exists()


@pytest.mark.parametrize("artifact_mutation", ["wrong_run", "wrong_cockpit_digest", "missing_cockpit"])
def test_public_bundle_refuses_changed_provenance_before_materialization(
    tmp_path: Path, artifact_mutation: str
) -> None:
    with pytest.raises(public.vri.ReleaseVerificationError):
        _signed_public_bundle(tmp_path, artifact_mutation=artifact_mutation)
    assert not (tmp_path / "bundle").exists()


def test_signer_public_mode_resolves_exact_public_compose_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, ...]] = []

    def resolve(_repo: Path, _sha: str, files: tuple[str, ...], _work: Path, _env: Path) -> dict:
        calls.append(files)
        return {"services": {}}

    monkeypatch.setattr(sign_cli.vri, "run_docker_compose_config_via_subprocess", resolve)
    sign_cli._run_docker_compose_config(tmp_path, SHA, tmp_path, tmp_path, public_candidate=True)
    sign_cli._run_docker_compose_config(tmp_path, SHA, tmp_path, tmp_path)
    assert calls == [
        public.vri._PUBLIC_CANDIDATE_COMPOSE_FILES,
        public.vri._CANONICAL_COMPOSE_FILES,
    ]


def test_public_bundle_rechecks_effective_compose_and_bundle_mode(tmp_path: Path) -> None:
    bundle, anchor, config = _signed_public_bundle(tmp_path)
    mutated = json.loads(json.dumps(config))
    mutated["services"]["cockpit"]["image"] = COCKPIT_IMAGE.replace("e" * 64, "0" * 64)
    with pytest.raises(dep.DeploymentWrapperError, match="effective compose differs"):
        dep.deploy_from_bundle(
            bundle_dir=bundle, merge_sha=SHA, execute=False,
            trusted_readiness_anchor_raw=anchor,
            run_bundle_compose_config=lambda *_: mutated,
        )
    path = bundle / dep._BUNDLE_MANIFEST_NAME
    document = json.loads(path.read_bytes())
    document.pop("bundle_digest")
    document["compose_files"] = list(public.vri._CANONICAL_COMPOSE_FILES)
    document["bundle_digest"] = hashlib.sha256(dep._canonical_json_bytes(document)).hexdigest()
    path.write_bytes(dep._canonical_json_bytes(document))
    with pytest.raises(dep.DeploymentWrapperError, match="Compose files differ"):
        dep.deploy_from_bundle(
            bundle_dir=bundle, merge_sha=SHA, execute=False,
            trusted_readiness_anchor_raw=anchor,
            run_bundle_compose_config=lambda *_: config,
        )
