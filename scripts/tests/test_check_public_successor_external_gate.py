"""Le diagnostic externe ne transforme jamais un SHA déclaré en autorité."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/go_live"))

from check_public_successor_external_gate import (
    AUTHORITY_FIELDS,
    ExternalGateError,
    _verify_preparation_semantics,
    _verify_private_replay_bindings,
    inspect_release,
)

PREPARATION = next((ROOT / "services/rag-pedago/data/releases").glob(
    "*/profile_gate_student_public_successor_v1/"
    "release-b1dda0c8503aa474/profile_gate"
))


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _final_fixture(tmp_path: Path) -> tuple[Path, str]:
    release = tmp_path / "profile_gate"
    shutil.copytree(PREPARATION, release)
    source = release / "source_preparation"
    source.mkdir()
    for name in ("production-profile-gate.release.json", "candidate_inventory.json"):
        shutil.copy2(PREPARATION / name, source / name)
    shutil.copy2(PREPARATION.parent / "preparation-index.json", source / "preparation-index.json")

    final_id = "student-public-successor-test-final"
    manifest_path = release / "production-profile-gate.release.json"
    manifest = json.loads(manifest_path.read_bytes())
    source_manifest_sha = _sha(source / manifest_path.name)
    authorities = {field: "a" * 64 for field in AUTHORITY_FIELDS}
    authorities.update(
        source_candidate_release_manifest_sha256=json.loads(
            (source / "preparation-index.json").read_bytes()
        )["source_candidate_manifest_sha256"],
        source_preparation_release_manifest_sha256=source_manifest_sha,
        source_preparation_index_sha256=_sha(source / "preparation-index.json"),
    )
    registry_path = release / "artifacts.release.json"
    registry = json.loads(registry_path.read_bytes())
    registry["release_id"] = final_id
    registry_path.write_bytes(_canonical(registry))
    manifest["artifact_registry"]["sha256"] = _sha(registry_path)

    inventory_path = release / "candidate_inventory.json"
    inventory = json.loads(inventory_path.read_bytes())
    inventory["release_id"] = final_id
    inventory["artifact_registry_sha256"] = _sha(registry_path)
    inventory_path.write_bytes(_canonical(inventory))
    authorities["candidate_inventory_sha256"] = _sha(inventory_path)

    for ref in manifest["subjects"]:
        path = release / ref["path"]
        subject = json.loads(path.read_bytes())
        subject["release_id"] = f"{final_id}-{ref['collection']}"
        subject["authorities"] = authorities
        subject["artifact_registry"]["sha256"] = _sha(registry_path)
        subject["profile"]["manifest_digest"] = authorities["public_profile_manifest_sha256"]
        path.write_bytes(_canonical(subject))
        ref["sha256"] = _sha(path)
    manifest.update(
        release_id=final_id,
        release_mode="public_successor",
        promotion_status="PROMOTABLE",
        review_status="REVIEWED",
        activation_status="PRODUCTION_ACTIVATION_ALLOWED",
        authorities=authorities,
    )
    manifest_path.write_bytes(_canonical(manifest))
    return manifest_path, _sha(manifest_path)


def _reseal_authorities(path: Path, authorities: dict[str, str]) -> str:
    manifest = json.loads(path.read_bytes())
    manifest["authorities"] = authorities
    for ref in manifest["subjects"]:
        subject_path = path.parent / ref["path"]
        subject = json.loads(subject_path.read_bytes())
        subject["authorities"] = authorities
        subject["profile"]["manifest_digest"] = authorities["public_profile_manifest_sha256"]
        subject_path.write_bytes(_canonical(subject))
        ref["sha256"] = _sha(subject_path)
    path.write_bytes(_canonical(manifest))
    return _sha(path)


def _reseal_inclusion(path: Path, attestation: dict) -> tuple[str, Path]:
    inclusion_path = path.parent / "inclusion_attestation.json"
    inclusion_path.write_bytes(_canonical(attestation))
    inclusion_sha = _sha(inclusion_path)
    index_path = path.parent / "source_preparation/preparation-index.json"
    index = json.loads(index_path.read_bytes())
    index["inclusion_attestation_sha256"] = inclusion_sha
    index["verified_authorities"]["inclusion_attestation_sha256"] = inclusion_sha
    index_path.write_bytes(_canonical(index))
    authorities = json.loads(path.read_bytes())["authorities"]
    authorities["inclusion_attestation_sha256"] = inclusion_sha
    authorities["source_preparation_index_sha256"] = _sha(index_path)
    return _reseal_authorities(path, authorities), inclusion_path


def test_preparatory_candidate_cannot_be_promoted(tmp_path: Path) -> None:
    path = PREPARATION / "production-profile-gate.release.json"
    with pytest.raises(ExternalGateError, match="public_successor"):
        inspect_release(path, _sha(path), {})


def test_all_21_declarations_and_preparation_chain_still_block_activation(tmp_path: Path) -> None:
    path, sha = _final_fixture(tmp_path)
    result = inspect_release(path, sha, {})
    assert result["preparation_chain_verified"] is True
    assert result["authority_count"] == 21
    assert result["release_counts"] == {
        "subjects": 11, "unique_artifacts": 253, "placements": 377, "unique_chunks": 3975,
    }
    assert result["PUBLIC_SUCCESSOR_EXTERNAL_GATE_PASS"] is False
    assert "exact_head_scope_review_receipt_sha256" in result["unverified_authorities"]
    assert "observed_transfer_receipt_sha256" in result["unverified_authorities"]
    assert set(result["semantic_unverified_authorities"]) == AUTHORITY_FIELDS


def test_transfer_receipt_cannot_be_credited_without_reobserving_destination(
    tmp_path: Path,
) -> None:
    path, _ = _final_fixture(tmp_path)
    plan = tmp_path / "transfer-plan.json"
    receipt = tmp_path / "transfer-receipt.json"
    plan.write_bytes(b"{}\n")
    receipt.write_bytes(b"{}\n")
    authorities = json.loads(path.read_bytes())["authorities"]
    authorities["artifact_transfer_manifest_sha256"] = _sha(plan)
    authorities["observed_transfer_receipt_sha256"] = _sha(receipt)
    sha = _reseal_authorities(path, authorities)

    with pytest.raises(ExternalGateError, match="observed transfer requires destination"):
        inspect_release(path, sha, {
            "artifact_transfer_manifest_sha256": plan,
            "observed_transfer_receipt_sha256": receipt,
        })


def test_partial_transfer_evidence_is_refused(tmp_path: Path) -> None:
    path, _ = _final_fixture(tmp_path)
    plan = tmp_path / "transfer-plan.json"
    plan.write_bytes(b"{}\n")
    authorities = json.loads(path.read_bytes())["authorities"]
    authorities["artifact_transfer_manifest_sha256"] = _sha(plan)
    sha = _reseal_authorities(path, authorities)
    with pytest.raises(ExternalGateError, match="transfer evidence must be paired"):
        inspect_release(path, sha, {"artifact_transfer_manifest_sha256": plan})


def test_cli_forwards_destination_to_transfer_verifier(tmp_path: Path) -> None:
    path, _ = _final_fixture(tmp_path)
    manifest = json.loads(path.read_bytes())
    plan = tmp_path / "transfer-plan.json"
    receipt = tmp_path / "transfer-receipt.json"
    plan.write_bytes(_canonical({
        "release_id": manifest["release_id"],
        "inventory_sha256": manifest["authorities"]["candidate_inventory_sha256"],
        "file_count": 0,
        "placement_count": 0,
        "files": [],
    }))
    receipt.write_bytes(b"{}\n")
    authorities = manifest["authorities"]
    authorities["artifact_transfer_manifest_sha256"] = _sha(plan)
    authorities["observed_transfer_receipt_sha256"] = _sha(receipt)
    sha = _reseal_authorities(path, authorities)
    evidence_map = tmp_path / "evidence-map.json"
    evidence_map.write_bytes(_canonical({
        "artifact_transfer_manifest_sha256": str(plan),
        "observed_transfer_receipt_sha256": str(receipt),
    }))

    result = subprocess.run([
        sys.executable, str(ROOT / "scripts/go_live/check_public_successor_external_gate.py"),
        "--release-manifest", str(path),
        "--expected-manifest-sha256", sha,
        "--evidence-map", str(evidence_map),
        "--transfer-destination-root", str(tmp_path / "destination"),
        "--transfer-target-identity", "qualified-staging",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "transfer population differs" in json.loads(result.stdout)["error"]


def test_transfer_plan_must_match_final_inventory_even_when_resigned(
    tmp_path: Path,
) -> None:
    path, _ = _final_fixture(tmp_path)
    manifest = json.loads(path.read_bytes())
    plan = tmp_path / "transfer-plan.json"
    receipt = tmp_path / "transfer-receipt.json"
    plan.write_bytes(_canonical({
        "kind": "NEXUS_STUDENT_PUBLIC_TEXT_TRANSFER_MANIFEST_V1",
        "status": "PLANNED_NOT_TRANSFERRED",
        "release_id": manifest["release_id"],
        "inventory_sha256": "f" * 64,
        "file_count": 0,
        "placement_count": 0,
        "files": [],
    }))
    receipt.write_bytes(b"{}\n")
    authorities = manifest["authorities"]
    authorities["artifact_transfer_manifest_sha256"] = _sha(plan)
    authorities["observed_transfer_receipt_sha256"] = _sha(receipt)
    sha = _reseal_authorities(path, authorities)

    with pytest.raises(ExternalGateError, match="transfer inventory differs"):
        inspect_release(path, sha, {
            "artifact_transfer_manifest_sha256": plan,
            "observed_transfer_receipt_sha256": receipt,
        }, transfer_destination_root=tmp_path / "destination",
            transfer_target_identity="qualified-staging")


def test_transfer_plan_cannot_omit_final_artifacts_even_when_resigned(
    tmp_path: Path,
) -> None:
    path, _ = _final_fixture(tmp_path)
    manifest = json.loads(path.read_bytes())
    plan = tmp_path / "transfer-plan.json"
    receipt = tmp_path / "transfer-receipt.json"
    plan.write_bytes(_canonical({
        "kind": "NEXUS_STUDENT_PUBLIC_TEXT_TRANSFER_MANIFEST_V1",
        "status": "PLANNED_NOT_TRANSFERRED",
        "release_id": manifest["release_id"],
        "inventory_sha256": manifest["authorities"]["candidate_inventory_sha256"],
        "file_count": 0,
        "placement_count": 0,
        "files": [],
    }))
    receipt.write_bytes(b"{}\n")
    authorities = manifest["authorities"]
    authorities["artifact_transfer_manifest_sha256"] = _sha(plan)
    authorities["observed_transfer_receipt_sha256"] = _sha(receipt)
    sha = _reseal_authorities(path, authorities)

    with pytest.raises(ExternalGateError, match="transfer population differs"):
        inspect_release(path, sha, {
            "artifact_transfer_manifest_sha256": plan,
            "observed_transfer_receipt_sha256": receipt,
        }, transfer_destination_root=tmp_path / "destination",
            transfer_target_identity="qualified-staging")


def test_transfer_receipt_rehashes_destination_instead_of_trusting_its_sha(
    tmp_path: Path,
) -> None:
    from public_text_transfer import canonical as transfer_canonical

    path, _ = _final_fixture(tmp_path)
    manifest = json.loads(path.read_bytes())
    inventory = json.loads((path.parent / "candidate_inventory.json").read_bytes())
    candidates = {
        row["content_sha256"]: row
        for collection in inventory["collections"]
        for row in collection["candidates"]
    }
    files = [
        {"file": f"{sha}.txt", "media_type": "text/plain; charset=utf-8",
         "sha256_expected": sha}
        for sha in sorted(candidates)
    ]
    receipt_shas = sorted({row["derivative_receipt_sha256"] for row in candidates.values()})
    derivative_receipts = [
        {"file": f"derivative_receipts/{sha}.json", "sha256_expected": sha}
        for sha in receipt_shas
    ]
    plan_raw = transfer_canonical({
        "kind": "NEXUS_STUDENT_PUBLIC_TEXT_TRANSFER_MANIFEST_V1",
        "status": "PLANNED_NOT_TRANSFERRED",
        "release_id": manifest["release_id"],
        "inventory_sha256": manifest["authorities"]["candidate_inventory_sha256"],
        "allowlist_sha256": "a" * 64,
        "file_count": len(files),
        "derivative_receipt_count": len(derivative_receipts),
        "placement_count": manifest["expected_counts"]["placements"],
        "files": files,
        "derivative_receipts": derivative_receipts,
    })
    destination = tmp_path / "destination"
    destination.mkdir()
    receipt_raw = transfer_canonical({
        "kind": "NEXUS_STUDENT_PUBLIC_TEXT_OBSERVED_TRANSFER_V1",
        "status": "OBSERVED_NOT_PUBLICATION_AUTHORITY",
        "release_id": manifest["release_id"],
        "transfer_manifest_sha256": hashlib.sha256(plan_raw).hexdigest(),
        "target_identity": "qualified-staging",
        "target_identity_status": "CLAIMED_UNQUALIFIED",
        "observed_host": socket.gethostname(),
        "destination_realpath": str(destination.resolve()),
        "observed_at_utc": "2026-10-10T17:00:00Z",
        "file_count": len(files),
        "derivative_receipt_count": len(derivative_receipts),
        "total_bytes": 0,
        "files": [{"file": row["file"], "sha256_observed": row["sha256_expected"],
                   "size_bytes": 0} for row in files],
        "derivative_receipts": [
            {"file": row["file"], "sha256_observed": row["sha256_expected"],
             "size_bytes": 0} for row in derivative_receipts
        ],
    })
    plan = tmp_path / "transfer-plan.json"
    receipt = tmp_path / "transfer-receipt.json"
    plan.write_bytes(plan_raw)
    receipt.write_bytes(receipt_raw)
    authorities = manifest["authorities"]
    authorities["artifact_transfer_manifest_sha256"] = _sha(plan)
    authorities["observed_transfer_receipt_sha256"] = _sha(receipt)
    sha = _reseal_authorities(path, authorities)

    with pytest.raises(ExternalGateError, match="observed transfer differs"):
        inspect_release(path, sha, {
            "artifact_transfer_manifest_sha256": plan,
            "observed_transfer_receipt_sha256": receipt,
        }, transfer_destination_root=destination,
            transfer_target_identity="qualified-staging")


def test_inclusion_decisions_bind_exact_final_population_but_not_promotion(
    tmp_path: Path,
) -> None:
    path, _ = _final_fixture(tmp_path)
    attestation = json.loads((path.parent / "inclusion_attestation.json").read_bytes())
    sha, inclusion_path = _reseal_inclusion(path, attestation)
    result = inspect_release(path, sha, {"inclusion_attestation_sha256": inclusion_path})
    assert result["preparation_inclusion_population_verified"] is True
    assert result["PUBLIC_SUCCESSOR_EXTERNAL_GATE_PASS"] is False
    assert "inclusion_attestation_sha256" in result["semantic_unverified_authorities"]


def test_resealed_inclusion_wrong_source_pdf_is_rejected(tmp_path: Path) -> None:
    path, _ = _final_fixture(tmp_path)
    attestation = json.loads((path.parent / "inclusion_attestation.json").read_bytes())
    attestation["decisions"][0]["source_pdf_sha256"] = "d" * 64
    attestation["evidence_pack_sha256"] = hashlib.sha256(
        _canonical(attestation["decisions"])
    ).hexdigest()
    sha, inclusion_path = _reseal_inclusion(path, attestation)
    with pytest.raises(ExternalGateError, match="inclusion source PDF differs"):
        inspect_release(path, sha, {"inclusion_attestation_sha256": inclusion_path})


def test_resealed_inclusion_exclusion_cannot_leave_artifact_public(tmp_path: Path) -> None:
    path, _ = _final_fixture(tmp_path)
    attestation = json.loads((path.parent / "inclusion_attestation.json").read_bytes())
    attestation["decisions"][0]["disposition"] = "EXCLUDE"
    attestation["evidence_pack_sha256"] = hashlib.sha256(
        _canonical(attestation["decisions"])
    ).hexdigest()
    sha, inclusion_path = _reseal_inclusion(path, attestation)
    with pytest.raises(ExternalGateError, match="included derivative population differs"):
        inspect_release(path, sha, {"inclusion_attestation_sha256": inclusion_path})


def test_resealed_inclusion_evidence_digest_is_rejected(tmp_path: Path) -> None:
    path, _ = _final_fixture(tmp_path)
    attestation = json.loads((path.parent / "inclusion_attestation.json").read_bytes())
    attestation["decisions"][0]["evidence_sha256"] = "e" * 64
    attestation["evidence_pack_sha256"] = hashlib.sha256(
        _canonical(attestation["decisions"])
    ).hexdigest()
    sha, inclusion_path = _reseal_inclusion(path, attestation)
    with pytest.raises(ExternalGateError, match="inclusion evidence digest differs"):
        inspect_release(path, sha, {"inclusion_attestation_sha256": inclusion_path})


def test_resealed_inclusion_missing_rights_authority_is_rejected(tmp_path: Path) -> None:
    path, _ = _final_fixture(tmp_path)
    attestation = json.loads((path.parent / "inclusion_attestation.json").read_bytes())
    attestation["rights_authority_sha256"] = None
    _, inclusion_path = _reseal_inclusion(path, attestation)
    index_path = path.parent / "source_preparation/preparation-index.json"
    index = json.loads(index_path.read_bytes())
    index["verified_authorities"]["rights_authority_sha256"] = None
    index_path.write_bytes(_canonical(index))
    authorities = json.loads(path.read_bytes())["authorities"]
    authorities["source_preparation_index_sha256"] = _sha(index_path)
    sha = _reseal_authorities(path, authorities)
    with pytest.raises(ExternalGateError, match="inclusion preparation authority differs"):
        inspect_release(path, sha, {"inclusion_attestation_sha256": inclusion_path})


def test_resealed_index_cannot_disagree_with_its_inclusion_authority(tmp_path: Path) -> None:
    path, _ = _final_fixture(tmp_path)
    attestation = json.loads((path.parent / "inclusion_attestation.json").read_bytes())
    _, inclusion_path = _reseal_inclusion(path, attestation)
    index_path = path.parent / "source_preparation/preparation-index.json"
    index = json.loads(index_path.read_bytes())
    index["verified_authorities"]["inclusion_attestation_sha256"] = "f" * 64
    index_path.write_bytes(_canonical(index))
    authorities = json.loads(path.read_bytes())["authorities"]
    authorities["source_preparation_index_sha256"] = _sha(index_path)
    sha = _reseal_authorities(path, authorities)
    with pytest.raises(ExternalGateError, match="inclusion preparation index digest differs"):
        inspect_release(path, sha, {"inclusion_attestation_sha256": inclusion_path})


def test_private_replay_requires_exact_inclusion_evidence(tmp_path: Path) -> None:
    path, sha = _final_fixture(tmp_path)
    with pytest.raises(ExternalGateError, match="private replay requires inclusion evidence"):
        inspect_release(
            path, sha, {}, private_cas_root=tmp_path / "private-cas", repository_root=ROOT,
        )


def test_private_replay_bindings_refuse_candidate_or_replay_substitution(
    tmp_path: Path,
) -> None:
    path, _ = _final_fixture(tmp_path)
    attestation = json.loads((path.parent / "inclusion_attestation.json").read_bytes())
    _, inclusion_path = _reseal_inclusion(path, attestation)
    manifest = json.loads(path.read_bytes())
    index = json.loads((path.parent / "source_preparation/preparation-index.json").read_bytes())
    source = {"inputs": {
        "release_sha256": manifest["authorities"]["source_candidate_release_manifest_sha256"],
        "candidate_manifest_sha256": index["verified_authorities"]["candidate_manifest_sha256"],
        "artifact_registry_sha256": index["artifact_registry_sha256"],
        "release": {"expected_counts": manifest["expected_counts"]},
    }}
    pr300 = {
        "PR300_AUTHORITY_APPROVAL_PASS": True,
        "CANDIDATE_MANIFEST_SHA256": source["inputs"]["candidate_manifest_sha256"],
    }
    pr312 = {
        "PR312_AUTHORITY_APPROVAL_PASS": True,
        "AGGREGATE_SHA256": source["inputs"]["release_sha256"],
        "ARTIFACTS_SHA256": source["inputs"]["artifact_registry_sha256"],
        "EXPECTED_COUNTS": manifest["expected_counts"],
    }
    assert _sha(inclusion_path) == manifest["authorities"]["inclusion_attestation_sha256"]
    _verify_private_replay_bindings(
        source, attestation, attestation, pr300, pr312, manifest, index,
    )
    forged_source = json.loads(json.dumps(source))
    forged_source["inputs"]["release_sha256"] = "f" * 64
    with pytest.raises(ExternalGateError, match="private candidate authority differs"):
        _verify_private_replay_bindings(
            forged_source, attestation, attestation, pr300, pr312, manifest, index,
        )
    forged_replay = dict(attestation)
    forged_replay["decision_count"] = 0
    with pytest.raises(ExternalGateError, match="private inclusion replay differs"):
        _verify_private_replay_bindings(
            source, forged_replay, attestation, pr300, pr312, manifest, index,
        )


def test_preparation_registries_and_profiles_match_replayed_population() -> None:
    from build_student_public_successor_release import load_sources

    source = load_sources(ROOT)
    replay = json.loads((PREPARATION / "inclusion_attestation.json").read_bytes())
    index = json.loads((PREPARATION.parent / "preparation-index.json").read_bytes())
    _verify_preparation_semantics(source, replay, index, PREPARATION)


@pytest.mark.parametrize("field", ["version", "fingerprint"])
def test_v2_preparation_rejects_resealed_subject_profile_substitution(
    field: str, tmp_path: Path,
) -> None:
    from build_student_public_successor_release import build_documents, load_sources

    source = load_sources(ROOT)
    replay = json.loads((PREPARATION / "inclusion_attestation.json").read_bytes())
    documents = build_documents(source, inclusion=replay)
    for relative, raw in documents.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    index_path = next(tmp_path / relative for relative in documents
                      if relative.name == "preparation-index.json")
    index = json.loads(index_path.read_bytes())
    prepared = index_path.parent / "profile_gate"
    manifest_path = prepared / "production-profile-gate.release.json"
    manifest = json.loads(manifest_path.read_bytes())
    subject_ref = manifest["subjects"][0]
    subject_path = prepared / subject_ref["path"]
    subject = json.loads(subject_path.read_bytes())
    subject["profile"][field] = "student-public-v1" if field == "version" else "a" * 64
    subject_path.write_bytes(_canonical(subject))
    subject_ref["sha256"] = _sha(subject_path)
    manifest_path.write_bytes(_canonical(manifest))
    index["release_manifest_sha256"] = _sha(manifest_path)

    with pytest.raises(ExternalGateError, match="preparation profile binding differs"):
        _verify_preparation_semantics(source, replay, index, prepared)


@pytest.mark.parametrize("mutation", [
    "rights_citation", "rights_status", "pii_proof", "currentness_row",
    "duplicate_rights", "profile_fingerprint", "profile_index_digest", "profile_scope",
])
def test_preparation_semantics_reject_resealed_but_false_claims(
    mutation: str, tmp_path: Path,
) -> None:
    from build_student_public_successor_release import load_sources

    source = copy.deepcopy(load_sources(ROOT))
    replay = json.loads((PREPARATION / "inclusion_attestation.json").read_bytes())
    index = json.loads((PREPARATION.parent / "preparation-index.json").read_bytes())
    prepared = tmp_path / "profile_gate"
    shutil.copytree(PREPARATION, prepared)
    if mutation == "rights_citation":
        source["sidecars"]["public_rights_registry.json"]["entries"][0]["citation_sha256"] = "f" * 64
    elif mutation == "rights_status":
        source["sidecars"]["public_rights_registry.json"]["authorized_use"] = "full_pdf"
    elif mutation == "pii_proof":
        source["sidecars"]["public_pii_registry.json"]["entries"][0]["pii_evidence_sha256"] = "f" * 64
    elif mutation == "currentness_row":
        path = prepared / "public_currentness_registry.json"
        value = json.loads(path.read_bytes())
        value["entries"][0]["revocation_status"] = "UNKNOWN"
        path.write_bytes(_canonical(value))
        index["verified_authorities"]["public_currentness_registry_sha256"] = _sha(path)
    elif mutation == "duplicate_rights":
        entries = source["sidecars"]["public_rights_registry.json"]["entries"]
        entries[1] = entries[0]
    elif mutation == "profile_fingerprint":
        source["sidecars"]["public_profiles.json"]["entries"][0]["profile_fingerprint"] = "f" * 64
    elif mutation == "profile_index_digest":
        index["complete_profiles"][0]["sha256"] = "f" * 64
    elif mutation == "profile_scope":
        collection = next(iter(source["profiles"]))
        raw = source["profiles"][collection].replace(
            b"visibility: public", b"visibility: internal",
        )
        source["profiles"][collection] = raw
        source["profile_refs"][collection]["sha256"] = hashlib.sha256(raw).hexdigest()
        (prepared / "profiles" / f"{collection}.yml").write_bytes(raw)
        for ref in index["complete_profiles"]:
            if ref["collection"] == collection:
                ref["sha256"] = hashlib.sha256(raw).hexdigest()
                break
    with pytest.raises(ExternalGateError, match="preparation (registry|profile)"):
        _verify_preparation_semantics(source, replay, index, prepared)


def test_tampered_preparation_index_is_rejected(tmp_path: Path) -> None:
    path, sha = _final_fixture(tmp_path)
    index = path.parent / "source_preparation/preparation-index.json"
    index.write_bytes(index.read_bytes() + b" ")
    with pytest.raises(ExternalGateError, match="source_preparation_index_sha256"):
        inspect_release(path, sha, {})


def test_provided_authority_bytes_must_match_declared_digest(tmp_path: Path) -> None:
    path, sha = _final_fixture(tmp_path)
    forged = tmp_path / "forged.json"
    forged.write_text("{}\n")
    with pytest.raises(ExternalGateError, match="exact_head_scope_review_receipt_sha256"):
        inspect_release(path, sha, {"exact_head_scope_review_receipt_sha256": forged})


def test_unexpected_evidence_mapping_is_rejected(tmp_path: Path) -> None:
    path, sha = _final_fixture(tmp_path)
    with pytest.raises(ExternalGateError, match="unknown authority"):
        inspect_release(path, sha, {"not_an_authority": tmp_path / "anything"})


def test_final_inventory_cannot_omit_a_registry_artifact_even_when_resealed(
    tmp_path: Path,
) -> None:
    path, _ = _final_fixture(tmp_path)
    inventory_path = path.parent / "candidate_inventory.json"
    inventory = json.loads(inventory_path.read_bytes())
    inventory["collections"][0]["candidates"].pop()
    inventory_path.write_bytes(_canonical(inventory))
    authorities = json.loads(path.read_bytes())["authorities"]
    authorities["candidate_inventory_sha256"] = _sha(inventory_path)
    sha = _reseal_authorities(path, authorities)
    with pytest.raises(ExternalGateError, match="inventory placement population differs"):
        inspect_release(path, sha, {})


def test_final_inventory_cannot_duplicate_a_candidate_even_when_resealed(
    tmp_path: Path,
) -> None:
    path, _ = _final_fixture(tmp_path)
    inventory_path = path.parent / "candidate_inventory.json"
    inventory = json.loads(inventory_path.read_bytes())
    candidates = inventory["collections"][0]["candidates"]
    candidates.append(candidates[0])
    inventory_path.write_bytes(_canonical(inventory))
    authorities = json.loads(path.read_bytes())["authorities"]
    authorities["candidate_inventory_sha256"] = _sha(inventory_path)
    sha = _reseal_authorities(path, authorities)
    with pytest.raises(ExternalGateError, match="duplicate derivative"):
        inspect_release(path, sha, {})


def test_renamed_source_and_final_collection_must_match_canonical_subjects(
    tmp_path: Path,
) -> None:
    path, _ = _final_fixture(tmp_path)
    source_root = path.parent / "source_preparation"
    source_inventory_path = source_root / "candidate_inventory.json"
    final_inventory_path = path.parent / "candidate_inventory.json"
    for inventory_path in (source_inventory_path, final_inventory_path):
        inventory = json.loads(inventory_path.read_bytes())
        inventory["collections"][0]["collection"] = "rag_nexus_forged_collection"
        inventory_path.write_bytes(_canonical(inventory))
    index_path = source_root / "preparation-index.json"
    index = json.loads(index_path.read_bytes())
    index["candidate_inventory_sha256"] = _sha(source_inventory_path)
    index_path.write_bytes(_canonical(index))
    authorities = json.loads(path.read_bytes())["authorities"]
    authorities["source_preparation_index_sha256"] = _sha(index_path)
    authorities["candidate_inventory_sha256"] = _sha(final_inventory_path)
    sha = _reseal_authorities(path, authorities)
    with pytest.raises(ExternalGateError, match="canonical subjects"):
        inspect_release(path, sha, {})


def test_source_only_derivative_is_reported_as_unreconciled_not_verified(
    tmp_path: Path,
) -> None:
    path, _ = _final_fixture(tmp_path)
    source_root = path.parent / "source_preparation"
    source_inventory_path = source_root / "candidate_inventory.json"
    source_inventory = json.loads(source_inventory_path.read_bytes())
    collection = source_inventory["collections"][0]["collection"]
    added = dict(source_inventory["collections"][0]["candidates"][0])
    added["content_sha256"] = "c" * 64
    added["placements"] = [dict(added["placements"][0])]
    added["placements"][0]["source_placement_id"] = "d" * 64
    source_inventory["collections"][0]["candidates"].append(added)
    source_inventory_path.write_bytes(_canonical(source_inventory))
    index_path = source_root / "preparation-index.json"
    index = json.loads(index_path.read_bytes())
    index["candidate_inventory_sha256"] = _sha(source_inventory_path)
    index_path.write_bytes(_canonical(index))
    authorities = json.loads(path.read_bytes())["authorities"]
    authorities["source_preparation_index_sha256"] = _sha(index_path)
    sha = _reseal_authorities(path, authorities)

    result = inspect_release(path, sha, {})
    assert result["preparation_subset_lineage_verified"] is True
    assert result["preparation_chain_verified"] is False
    assert result["unreconciled_preparation_exclusions"] == {collection: ["c" * 64]}
    assert result["PUBLIC_SUCCESSOR_EXTERNAL_GATE_PASS"] is False


def test_all_21_authority_bytes_still_cannot_claim_semantic_pass(tmp_path: Path) -> None:
    path, _ = _final_fixture(tmp_path)
    evidence = tmp_path / "untyped-evidence.json"
    evidence.write_text("{}\n")
    authorities = json.loads(path.read_bytes())["authorities"]
    mapped_fields = AUTHORITY_FIELDS - {
        "source_preparation_release_manifest_sha256",
        "source_preparation_index_sha256",
        "candidate_inventory_sha256",
        "inclusion_attestation_sha256",
    }
    for field in mapped_fields:
        authorities[field] = _sha(evidence)
    index_path = path.parent / "source_preparation/preparation-index.json"
    index = json.loads(index_path.read_bytes())
    index["source_candidate_manifest_sha256"] = _sha(evidence)
    index_path.write_bytes(_canonical(index))
    authorities["source_preparation_index_sha256"] = _sha(index_path)
    inclusion_path = path.parent / "inclusion_attestation.json"
    authorities["inclusion_attestation_sha256"] = _sha(inclusion_path)
    sha = _reseal_authorities(path, authorities)
    evidence_map = {field: evidence for field in mapped_fields}
    evidence_map["inclusion_attestation_sha256"] = inclusion_path
    with pytest.raises(ExternalGateError, match="observed transfer requires destination"):
        inspect_release(path, sha, evidence_map)


@pytest.mark.parametrize("assert_ready", [False, True])
def test_cli_exit_is_nonzero_while_semantic_gate_is_unavailable(
    tmp_path: Path, assert_ready: bool,
) -> None:
    path, sha = _final_fixture(tmp_path)
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/go_live/check_public_successor_external_gate.py"),
         "--release-manifest", str(path), "--expected-manifest-sha256", sha,
         *(["--assert-ready"] if assert_ready else [])],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 1
    assert json.loads(completed.stdout)["PUBLIC_SUCCESSOR_EXTERNAL_GATE_PASS"] is False
