"""Le wrapper signé qualifie un candidat public sans autoriser de mutation."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import deploy_verified_release_cli as dep  # noqa: E402
import public_blue_green_preflight as public  # noqa: E402
from nexus_contracts.production_readiness import public_readiness_key_hex  # noqa: E402

from tests.test_deploy_verified_release_cli import _trust_anchor_bytes  # noqa: E402
from tests.test_public_blue_green_preflight import IMAGE, SHA, _fixture  # noqa: E402
from tests.test_sign_production_readiness_manifest_cli import (  # noqa: E402
    PR_HEAD_SHA,
    PR_NUMBER,
    TEST_KEY_ID,
    TEST_SEED,
    TREE_SHA,
    WORKFLOW_REF,
    _v2_material,
)


def _signed_public(
    config: dict, *, application_claim: str = IMAGE, upstream_claim: str | None = None
) -> tuple[bytes, bytes, dep.signer.V2ReleaseMaterial]:
    material = _v2_material()
    digest = hashlib.sha256(public.vri.canonical_resolved_compose_bytes(config)).hexdigest()
    upstream = {
        name: config["services"][name]["image"]
        for name in ("pgvector", "prometheus")
    }
    if upstream_claim is not None:
        upstream["pgvector"] = upstream_claim
    manifest = dep.signer.assemble_and_sign_v2(
        material,
        repository="cyranoaladin/RAG",
        pr_number=PR_NUMBER,
        pr_head_sha=PR_HEAD_SHA,
        pr_head_tree_sha=TREE_SHA,
        application_image_digests={"ingestor": application_claim},
        upstream_image_digests=upstream,
        compose_digest=digest,
        key_id=TEST_KEY_ID,
        workflow_ref=WORKFLOW_REF,
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
) -> dict:
    config, root, secrets, repo = _fixture(tmp_path)
    application_claim = IMAGE
    upstream_claim = None
    if mutation == "application_claim":
        application_claim = "ghcr.io/cyranoaladin/rag-ingestor@sha256:" + "0" * 64
    elif mutation == "upstream_claim":
        upstream_claim = "postgres@sha256:" + "0" * 64
    signed, anchor, material = _signed_public(
        config, application_claim=application_claim, upstream_claim=upstream_claim
    )
    promotion = dep.signer.verify_v2_release_material(material).promotion
    if verify_calls is not None:
        original_verify = dep.signer.verify_v2_release_material

        def count_verify(material: dep.signer.V2ReleaseMaterial) -> dep.signer.VerifiedV2ReleaseMaterial:
            verify_calls.append(None)
            return original_verify(material)

        monkeypatch.setattr(dep.signer, "verify_v2_release_material", count_verify)
    monkeypatch.setattr(
        public.dii,
        "verify_application_image_provenance",
        lambda **kwargs: {"ingestor": IMAGE},
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


@pytest.mark.parametrize("mutation", ["compose", "network", "image", "material", "signature"])
def test_plan_refuses_unsigned_or_divergent_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    with pytest.raises((dep.DeploymentWrapperError, public.PublicCandidateError)):
        _plan(tmp_path, monkeypatch, mutation=mutation)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("application_claim", "public candidate API image differs from signed readiness"),
        ("upstream_claim", "public candidate upstream images differ from signed readiness"),
    ],
)
def test_plan_refuses_validly_signed_but_wrong_image_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str, message: str
) -> None:
    with pytest.raises(dep.DeploymentWrapperError, match=message):
        _plan(tmp_path, monkeypatch, mutation=mutation)
