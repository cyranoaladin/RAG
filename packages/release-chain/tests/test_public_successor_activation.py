"""A ne devient jamais une autorité publique par la seule présence de ses octets."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from nexus_contracts.authority_artifacts import (
    ReleaseBatchExpectedCounts,
    ReleaseBatchPlacementEvidence,
    ReleaseBatchPublicationReviewArtifact,
)
from nexus_contracts.authorization_set import (
    AuthorizationSetMemberV1,
    AuthorizationSetV2,
    content_set_digest,
    scope_digest,
)
from nexus_release_chain.public_successor_activation import (
    PublicSuccessorActivationError,
    derive_public_release_scope_placement,
    verify_content_anchor,
    verify_content_authority_bindings,
    verify_content_currentness,
    verify_public_lot41a_authorization_set,
    verify_public_authorization_revocations,
    verify_public_scope_registry,
    verify_public_successor_activation,
    verify_public_transfer_offline,
    verify_public_transfer_placement_population,
    verify_publication_batch_review,
    verify_reviewed_public_scope_policy,
)

ROOT = Path(__file__).resolve().parents[3]
RELEASE = (
    ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027"
    / "profile_gate_student_public_successor_v1"
    / "release-fcc84331e7700042"
)
ANCHOR = (
    ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261010.json"
)
ANCHOR_SHA = "159e6e25fa493325304f8c790dd67113b4c6ced72a2fa696a60799a9fe7255a0"


def test_real_content_anchor_is_replayed_without_activation() -> None:
    observed = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    assert observed.content_manifest_sha256 == (
        "b79246ff356b919aeb3dcb7f640a1a554e338899128a7c5acdcfaa9b7bcb1c78"
    )
    assert observed.release_registry_sha256 == (
        "3f34f56c18e514ba4b0e92698f4b9a15deaa425818a0513ab51d48877ea24028"
    )
    assert len(observed.subject_sha256_by_collection) == 11
    assert observed.expected_counts == {
        "subjects": 11,
        "unique_artifacts": 253,
        "placements": 377,
        "unique_chunks": 3975,
    }
    assert observed.activation_allowed is False


def test_public_lot41a_projection_covers_all_a_placements() -> None:
    content = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    projection = derive_public_release_scope_placement(RELEASE, content)
    assert projection.profile_manifest_digest == "f165782c0404762e7869c1f7b2d17edc8d62087b124442f29ebe4243644f0d9b"
    assert len(projection.placements) == 377
    assert len({entry.content_sha256 for entry in projection.placements}) == 253
    assert len({scope_digest(entry.scope) for entry in projection.placements}) == 11


@pytest.mark.parametrize("mutation", ["duplicate", "wrong_pdf", "wrong_release"])
def test_currentness_registry_must_cover_exact_a_artifact_identities(
    tmp_path: Path, mutation: str,
) -> None:
    content = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    copied = tmp_path / "release"
    shutil.copytree(RELEASE, copied)
    registry_path = copied / "profile_gate/public_currentness_registry.json"
    registry = json.loads(registry_path.read_bytes())
    if mutation == "duplicate":
        registry["entries"][1] = dict(registry["entries"][0])
    elif mutation == "wrong_pdf":
        registry["entries"][0]["source_pdf_sha256"] = "f" * 64
    else:
        registry["release_id"] = "other-release"
    registry_path.write_bytes((json.dumps(registry, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    changed = replace(content, currentness_registry_sha256=hashlib.sha256(registry_path.read_bytes()).hexdigest())
    with pytest.raises(PublicSuccessorActivationError, match="currentness"):
        verify_content_currentness(copied, changed, datetime(2026, 10, 10, 21, tzinfo=UTC))


def test_public_lot41a_refuses_equal_count_wrong_content_binding() -> None:
    content = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    projection = derive_public_release_scope_placement(RELEASE, content)
    by_scope = {}
    for entry in projection.placements:
        by_scope.setdefault(scope_digest(entry.scope), (entry.scope, set()))[1].add(entry.content_sha256)
    members = []
    for n, (digest, (scope, values)) in enumerate(sorted(by_scope.items())):
        contents = tuple(sorted(values))
        members.append(AuthorizationSetMemberV1.model_validate({
            "authorization_id": f"lot41a-{n:02d}",
            "authorization_digest": hashlib.sha256(f"auth:{n}".encode()).hexdigest(),
            "review_binding_digest": hashlib.sha256(f"review:{n}".encode()).hexdigest(),
            "scope": scope,
            "scope_digest": digest,
            "allowed_content_sha256": contents,
            "allowed_content_count": len(contents),
            "allowed_content_set_sha256": content_set_digest(contents),
            "valid_from": datetime(2026, 10, 10, tzinfo=UTC),
            "valid_until": datetime(2026, 10, 11, tzinfo=UTC),
        }))
    valid = AuthorizationSetV2.build(
        members=members,
        corpus_manifest_sha256=content.content_manifest_sha256,
        profile_manifest_digest=projection.profile_manifest_digest,
        release_scope_placement_digest=projection.digest(),
    )
    assert verify_public_lot41a_authorization_set(
        valid.canonical_bytes(), RELEASE, content,
        datetime(2026, 10, 10, 21, tzinfo=UTC),
    ).authorization_binding_count == 377
    first = members[0]
    replaced = tuple(sorted((*first.allowed_content_sha256[1:], "f" * 64)))
    wrong_member = first.model_copy(update={
        "allowed_content_sha256": replaced,
        "allowed_content_set_sha256": content_set_digest(replaced),
    })
    wrong_binding = AuthorizationSetV2.build(
        members=[wrong_member, *members[1:]],
        corpus_manifest_sha256=content.content_manifest_sha256,
        profile_manifest_digest=projection.profile_manifest_digest,
        release_scope_placement_digest=projection.digest(),
    )
    with pytest.raises(PublicSuccessorActivationError, match="LOT41A binding"):
        verify_public_lot41a_authorization_set(
            wrong_binding.canonical_bytes(), RELEASE, content,
            datetime(2026, 10, 10, 21, tzinfo=UTC),
        )
    changed = valid.model_copy(update={"corpus_manifest_sha256": "f" * 64})
    with pytest.raises(PublicSuccessorActivationError, match="LOT41A"):
        verify_public_lot41a_authorization_set(
            changed.canonical_bytes(), RELEASE, content,
            datetime(2026, 10, 10, 21, tzinfo=UTC),
        )


def test_public_revocation_registry_refuses_revoked_lot41a_authorization() -> None:
    assert verify_public_authorization_revocations(
        b'{"protocol_version":"NEXUS-AUTHORIZATION-REVOCATIONS-V1",'
        b'"revoked_authorization_ids":[]}',
        authorization_ids=("lot41a-00", "lot41a-01"),
    ) == frozenset()
    with pytest.raises(PublicSuccessorActivationError, match="LOT41A.*revoked"):
        verify_public_authorization_revocations(
            b'{"protocol_version":"NEXUS-AUTHORIZATION-REVOCATIONS-V1",'
            b'"revoked_authorization_ids":["lot41a-00"]}',
            authorization_ids=("lot41a-00", "lot41a-01"),
        )
    with pytest.raises(PublicSuccessorActivationError, match="revocation"):
        verify_public_authorization_revocations(
            b'{"protocol_version":"UNKNOWN","revoked_authorization_ids":[]}',
            authorization_ids=("lot41a-00",),
        )


def _compact(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _transfer_offline_fixture() -> tuple[bytes, bytes, bytes, bytes, str]:
    plan = json.loads((ROOT / "docs/reports/go_live/student_public_successor_v2_transfer_plan_20261010.json").read_bytes())
    plan_raw = _compact(plan)
    receipt = {
        "kind": "NEXUS_STUDENT_PUBLIC_TEXT_OBSERVED_TRANSFER_V1",
        "status": "OBSERVED_NOT_PUBLICATION_AUTHORITY",
        "release_id": plan["release_id"],
        "transfer_manifest_sha256": hashlib.sha256(plan_raw).hexdigest(),
        "target_identity": "staging-qualified-test",
        "target_identity_status": "CLAIMED_UNQUALIFIED",
        "observed_host": "staging-test",
        "destination_realpath": "/isolated/staging-test",
        "observed_at_utc": "2026-10-10T20:00:00Z",
        "file_count": plan["file_count"],
        "derivative_receipt_count": plan["derivative_receipt_count"],
        "total_bytes": 506,
        "files": [{"file": row["file"], "sha256_observed": row["sha256_expected"], "size_bytes": 1}
                  for row in plan["files"]],
        "derivative_receipts": [{"file": row["file"], "sha256_observed": row["sha256_expected"],
                                 "size_bytes": 1} for row in plan["derivative_receipts"]],
    }
    receipt_raw = _compact(receipt)
    content = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    pin = {
        "kind": "NEXUS_STAGING_QUALIFIED_TARGET_PIN_V1",
        "content_anchor_sha256": content.content_anchor_sha256,
        "release_id": content.release_id,
        "target_identity": receipt["target_identity"],
        "hostname": receipt["observed_host"],
        "host_machine_id_sha256": "a" * 64,
        "postgres_system_identifier": "1234567890",
        "database_name": "rag_staging",
        "destination_realpath": receipt["destination_realpath"],
        "pinned_at_utc": "2026-10-10T19:00:00Z",
        "expires_at_utc": "2026-10-11T12:00:00Z",
    }
    pin_raw = _compact(pin)
    pin_sha = hashlib.sha256(pin_raw).hexdigest()
    attestation = {
        "kind": "NEXUS_STUDENT_PUBLIC_QUALIFIED_TRANSFER_TARGET_ATTESTATION_V2",
        "status": "QUALIFIED_OBSERVED_NOT_PUBLICATION_AUTHORITY",
        "content_anchor_sha256": content.content_anchor_sha256,
        "release_id": content.release_id,
        "transfer_manifest_sha256": hashlib.sha256(plan_raw).hexdigest(),
        "observed_v1_receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
        "target_pin_sha256": pin_sha,
        "target_identity": pin["target_identity"],
        "hostname": pin["hostname"],
        "host_machine_id_sha256": pin["host_machine_id_sha256"],
        "postgres_system_identifier": pin["postgres_system_identifier"],
        "database_name": pin["database_name"],
        "destination_realpath": pin["destination_realpath"],
        "observed_at_utc": "2026-10-10T20:30:00Z",
        "expires_at_utc": pin["expires_at_utc"],
        "file_count": receipt["file_count"],
        "derivative_receipt_count": receipt["derivative_receipt_count"],
        "total_bytes": receipt["total_bytes"],
    }
    return plan_raw, receipt_raw, pin_raw, _compact(attestation), pin_sha


def test_public_transfer_offline_links_v2_to_exact_a_and_v1() -> None:
    content = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    plan, receipt, pin, attestation, pin_sha = _transfer_offline_fixture()
    now = datetime(2026, 10, 10, 21, tzinfo=UTC)
    assert verify_public_transfer_offline(
        plan, receipt, pin, attestation, RELEASE, content,
        expected_target_pin_sha256=pin_sha, now_utc=now,
    ) == hashlib.sha256(plan).hexdigest()
    changed = json.loads(attestation)
    changed["target_pin_sha256"] = "f" * 64
    with pytest.raises(PublicSuccessorActivationError, match="transfer"):
        verify_public_transfer_offline(
            plan, receipt, pin, _compact(changed), RELEASE, content,
            expected_target_pin_sha256=pin_sha, now_utc=now,
        )


def test_public_transfer_pairs_must_match_all_377_subject_placements() -> None:
    content = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    inventory = json.loads((RELEASE / "profile_gate/candidate_inventory.json").read_bytes())
    verify_public_transfer_placement_population(inventory, RELEASE, content)
    inventory["collections"][0]["candidates"][0]["placements"][0][
        "source_placement_id"
    ] = "f" * 64
    with pytest.raises(PublicSuccessorActivationError, match="transfer.*placement"):
        verify_public_transfer_placement_population(inventory, RELEASE, content)


@pytest.mark.parametrize("mutation", ["v1_unqualified", "expired_pin", "missing_v1_row"])
def test_public_transfer_offline_refuses_invalid_evidence(mutation: str) -> None:
    content = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    plan, receipt, pin, attestation, pin_sha = _transfer_offline_fixture()
    if mutation == "v1_unqualified":
        row = json.loads(receipt)
        row["target_identity_status"] = "QUALIFIED"
        receipt = _compact(row)
    elif mutation == "expired_pin":
        row = json.loads(pin)
        row["expires_at_utc"] = "2026-10-10T20:45:00Z"
        pin = _compact(row)
        pin_sha = hashlib.sha256(pin).hexdigest()
    else:
        row = json.loads(receipt)
        row["files"].pop()
        receipt = _compact(row)
    with pytest.raises(PublicSuccessorActivationError, match="transfer"):
        verify_public_transfer_offline(
            plan, receipt, pin, attestation, RELEASE, content,
            expected_target_pin_sha256=pin_sha,
            now_utc=datetime(2026, 10, 10, 21, tzinfo=UTC),
        )


def test_public_transfer_offline_refuses_resealed_wrong_content_same_count() -> None:
    content = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    plan_raw, receipt_raw, pin, attestation_raw, pin_sha = _transfer_offline_fixture()
    plan, receipt, attestation = map(json.loads, (plan_raw, receipt_raw, attestation_raw))
    old = plan["files"][0]
    forged = "f" * 64
    old_file = old["file"]
    old["file"] = f"{forged}.txt"
    old["sha256_expected"] = forged
    plan["files"].sort(key=lambda row: row["sha256_expected"])
    plan_raw = _compact(plan)
    for row in receipt["files"]:
        if row["file"] == old_file:
            row["file"] = f"{forged}.txt"
            row["sha256_observed"] = forged
    receipt["transfer_manifest_sha256"] = hashlib.sha256(plan_raw).hexdigest()
    receipt_raw = _compact(receipt)
    attestation["transfer_manifest_sha256"] = hashlib.sha256(plan_raw).hexdigest()
    attestation["observed_v1_receipt_sha256"] = hashlib.sha256(receipt_raw).hexdigest()
    with pytest.raises(PublicSuccessorActivationError, match="transfer plan"):
        verify_public_transfer_offline(
            plan_raw, receipt_raw, pin, _compact(attestation), RELEASE, content,
            expected_target_pin_sha256=pin_sha,
            now_utc=datetime(2026, 10, 10, 21, tzinfo=UTC),
        )


def test_content_currentness_expires_at_the_sealed_limit() -> None:
    content = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    expiry = verify_content_currentness(
        RELEASE, content, datetime(2026, 10, 10, 21, tzinfo=UTC),
    )
    assert expiry.isoformat() == "2026-10-11T13:39:22.520000+00:00"
    with pytest.raises(PublicSuccessorActivationError, match="currentness expired"):
        verify_content_currentness(RELEASE, content, expiry)


def test_c_content_authorities_must_restate_exact_a_bindings() -> None:
    content = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    index = json.loads((RELEASE / "preparation-index.json").read_bytes())
    manifest = json.loads((RELEASE / "profile_gate/production-profile-gate.release.json").read_bytes())
    anchor = json.loads(ANCHOR.read_bytes())
    authorities = {
        "source_candidate_release_manifest_sha256": index["source_candidate_manifest_sha256"],
        "source_preparation_release_manifest_sha256": content.content_manifest_sha256,
        "source_preparation_index_sha256": content.preparation_index_sha256,
        "candidate_inventory_sha256": content.candidate_inventory_sha256,
        "inclusion_attestation_sha256": anchor["preparation_sidecars"]["inclusion_attestation.json"],
        "derivative_pii_evidence_sha256": index["pii_adjudication_report_sha256"],
        "derivative_currentness_evidence_sha256": index["source_currentness_attestation_sha256"],
        "public_profile_manifest_sha256": anchor["preparation_sidecars"]["public_profiles.json"],
        "public_rights_registry_sha256": anchor["preparation_sidecars"]["public_rights_registry.json"],
        "public_pii_registry_sha256": anchor["preparation_sidecars"]["public_pii_registry.json"],
        "rights_authority_sha256": manifest["authorities"]["rights_authority_sha256"],
        "delegated_evidence_pack_sha256": manifest["authorities"]["delegated_evidence_pack_sha256"],
        "pr300_final_authority_receipt_sha256": manifest["authorities"]["pr300_final_authority_receipt_sha256"],
    }
    verify_content_authority_bindings(RELEASE, content, authorities)
    for field in authorities:
        changed = {**authorities, field: "f" * 64}
        with pytest.raises(PublicSuccessorActivationError, match=field):
            verify_content_authority_bindings(RELEASE, content, changed)


def _lot42_review() -> ReleaseBatchPublicationReviewArtifact:
    content = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    artifacts = json.loads((RELEASE / "profile_gate/artifacts.release.json").read_bytes())["artifacts"]
    source_url_count = len({item["source_url"] for item in artifacts})
    return ReleaseBatchPublicationReviewArtifact(
        protocol_version="LOT42-RELEASE-BATCH-V1",
        review_id="lot42-public-successor-test",
        decision="AUTHORIZE_SEALED_RELEASE_PUBLICATION",
        release_id=content.release_id,
        release_manifest_sha256=content.content_manifest_sha256,
        artifacts_release_sha256=content.artifact_registry_sha256,
        candidate_inventory_sha256=content.candidate_inventory_sha256,
        artifact_transfer_manifest_sha256="a" * 64,
        expected_counts=ReleaseBatchExpectedCounts(**content.expected_counts),
        collections=tuple(sorted(content.subject_sha256_by_collection)),
        placement_evidence=ReleaseBatchPlacementEvidence(
            currentness="official_snapshot", placement_status="active", review_status="reviewed",
        ),
        scope_authorization_ids=tuple(f"lot41a-{n:02d}" for n in range(11)),
        provenance_source_url_count=source_url_count,
        provenance_note="Provenance du corpus textuel public testé.",
        valid_from=datetime(2026, 10, 10, 20, tzinfo=UTC),
        valid_until=datetime(2026, 10, 11, 12, tzinfo=UTC),
    )


def test_lot42_public_review_is_bound_to_a_and_transfer() -> None:
    content = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    review = _lot42_review()
    now = datetime(2026, 10, 10, 21, tzinfo=UTC)
    assert verify_publication_batch_review(
        review.canonical_bytes(), content, RELEASE, "a" * 64,
        review.scope_authorization_ids, now,
    ).digest() == review.digest()
    with pytest.raises(PublicSuccessorActivationError, match="LOT42.*transfer"):
        verify_publication_batch_review(
            review.canonical_bytes(), content, RELEASE, "b" * 64,
            review.scope_authorization_ids, now,
        )
    with pytest.raises(PublicSuccessorActivationError, match="LOT42.*expired"):
        verify_publication_batch_review(
            review.canonical_bytes(), content, RELEASE, "a" * 64,
            review.scope_authorization_ids, review.valid_until,
        )
    wrong_source_count = review.model_copy(update={"provenance_source_url_count": 1})
    with pytest.raises(PublicSuccessorActivationError, match="LOT42.*provenance"):
        verify_publication_batch_review(
            wrong_source_count.canonical_bytes(), content, RELEASE, "a" * 64,
            review.scope_authorization_ids, now,
        )


@pytest.mark.parametrize(
    "relative",
    [
        "release-registry.json",
        "profile_gate/public_profiles.json",
        "profile_gate/public_rights_registry.json",
        "profile_gate/public_pii_registry.json",
        "profile_gate/public_currentness_registry.json",
        "profile_gate/inclusion_attestation.json",
        "profile_gate/subjects/rag_nexus_svt_premiere_specialite.release.json",
        "profile_gate/profiles/rag_nexus_svt_premiere_specialite.yml",
    ],
)
def test_missing_referenced_content_is_refused(tmp_path: Path, relative: str) -> None:
    copied = tmp_path / "release"
    shutil.copytree(RELEASE, copied)
    (copied / relative).unlink()
    with pytest.raises(PublicSuccessorActivationError):
        verify_content_anchor(ANCHOR, ANCHOR_SHA, copied)


def test_content_anchor_without_final_envelope_cannot_activate(tmp_path: Path) -> None:
    (tmp_path / "release").symlink_to(RELEASE, target_is_directory=True)
    (tmp_path / "content-anchor.json").write_bytes(ANCHOR.read_bytes())
    with pytest.raises(PublicSuccessorActivationError, match="authority envelope"):
        verify_public_successor_activation(
            tmp_path,
            expected_content_anchor_sha256=ANCHOR_SHA,
            expected_authority_envelope_sha256="f" * 64,
            expected_release_id="student-public-successor-20261010-fcc84331e7700042",
            expected_registry_sha256="3f34f56c18e514ba4b0e92698f4b9a15deaa425818a0513ab51d48877ea24028",
            expected_scope_authority_sha256="e" * 64,
            expected_target_pin_sha256="d" * 64,
        )


def test_internal_symlink_is_refused_even_with_identical_bytes(tmp_path: Path) -> None:
    copied = tmp_path / "release"
    shutil.copytree(RELEASE, copied)
    path = copied / "profile_gate/public_profiles.json"
    target = copied / "profile_gate/public_profiles-original.json"
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(PublicSuccessorActivationError, match="symlink"):
        verify_content_anchor(ANCHOR, ANCHOR_SHA, copied)


def _scope_fixture(tmp_path: Path) -> tuple[Path, str, object]:
    from nexus_contracts.scope import RetrievalScopeArtifactV3

    content = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    collection = "rag_nexus_hggsp_premiere_specialite"
    old = json.loads((ROOT / "packages/contracts/src/nexus_contracts/artifacts"
                      / "retrieval-scope-prod-hggsp-premiere-specialite-v3.json").read_text())
    target = old.pop("target_identity")
    old["artifact_version"] = "3"
    old["source_sha256"] = content.subject_sha256_by_collection[collection]
    old["target_policy"] = {
        **{key: value for key, value in target.items() if key not in ("audience", "candidates")},
        "audiences": [target["audience"]],
        "candidates": target["candidates"],
        "roles": ["student"],
    }
    old["evidence_subject"]["visibility"] = "public"
    old["evidence_subject"]["rights"] = ["public_allowed"]
    scope = RetrievalScopeArtifactV3.model_validate(old)
    scope_path = tmp_path / "scopes" / "hggsp.json"
    scope_path.parent.mkdir(parents=True)
    scope_path.write_bytes(scope.canonical_bytes())
    registry = {
        "kind": "NEXUS_STUDENT_PUBLIC_SCOPE_REGISTRY_V1",
        "status": "SCOPES_ISSUED_NOT_PUBLICATION_AUTHORITY",
        "activation_allowed": False,
        "content_anchor_sha256": ANCHOR_SHA,
        "content_manifest_sha256": content.content_manifest_sha256,
        "policy_registry_sha256": "a" * 64,
        "successor_authority_sha256": "b" * 64,
        "scopes": [{
            "collection": collection, "scope_id": scope.scope_id,
            "resource": "scopes/hggsp.json", "sha256": scope.sha256_digest(),
            "source_sha256": scope.source_sha256, "artifact_version": "3",
        }],
    }
    raw = (json.dumps(registry, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
    path = tmp_path / "scope-registry.json"
    path.write_bytes(raw)
    one_subject = replace(content, subject_sha256_by_collection={
        collection: content.subject_sha256_by_collection[collection],
    })
    return path, hashlib.sha256(raw).hexdigest(), one_subject


def test_scope_registry_binds_student_public_v3_to_a(tmp_path: Path) -> None:
    path, digest, content = _scope_fixture(tmp_path)
    scopes = verify_public_scope_registry(path, digest, content, RELEASE)
    assert len(scopes) == 1
    assert scopes[0].target_policy.roles == ["student"]


def _reviewed_scope_policy_fixture(tmp_path: Path):
    path, _, content = _scope_fixture(tmp_path)
    from nexus_contracts.scope import RetrievalScopeArtifactV3
    original = json.loads((tmp_path / "scopes/hggsp.json").read_bytes())
    original["scope_id"] = "student_public_hggsp_premiere_specialite_v1"
    original["evidence_subject"]["audiences"] = ["libre", "aefe"]
    scope = RetrievalScopeArtifactV3.model_validate(original)
    scope_doc = json.loads(scope.canonical_bytes())
    scope_path = tmp_path / f"scopes/{scope.scope_id}.json"
    scope_path.write_bytes(scope.canonical_bytes())
    (tmp_path / "scopes/hggsp.json").unlink()
    collection = scope_doc["evidence_subject"]["collection"]
    evidence = scope_doc["evidence_subject"]
    target = scope_doc["target_policy"]
    row = {
        "collection": collection,
        "decision_status": "GOVERNED_BY_HUMAN_DECISION",
        "authority_source": "NEXUS_HUMAN_DECISION_ADR_0064",
        "policy_source_scope_id": None,
        "subject_manifest_sha256": content.subject_sha256_by_collection[collection],
        **{key: evidence[key] for key in (
            "tenant", "niveau", "voie", "matiere", "statut_enseignement",
            "candidat", "audiences", "rights", "programme_version",
        )},
        "policy_visibility": "public",
        "evidence_visibility": "public",
        "target_audience": target["audiences"][0],
        "target_candidates": target["candidates"],
    }
    policy = {
        "registry_kind": "NEXUS_RETRIEVAL_SCOPE_POLICY_REGISTRY_V1",
        "release_id": content.release_id,
        "release_manifest_sha256": content.content_manifest_sha256,
        "school_year": evidence["school_year"],
        "collections": [row],
    }
    names = {"authority_id": "PRODUCTION_PROFILE_SCOPE_SUCCESSORS_V1",
             "release_id": content.release_id, "bindings": [
        {"collection": collection, "scope_id": scope.scope_id},
    ]}
    import yaml
    policy_raw = yaml.safe_dump(policy, sort_keys=True).encode()
    names_raw = yaml.safe_dump(names, sort_keys=True).encode()
    registry = json.loads(path.read_bytes())
    registry["policy_registry_sha256"] = hashlib.sha256(policy_raw).hexdigest()
    registry["successor_authority_sha256"] = hashlib.sha256(names_raw).hexdigest()
    registry["scopes"][0].update(
        scope_id=scope.scope_id, resource=f"scopes/{scope.scope_id}.json",
        sha256=scope.sha256_digest(),
    )
    path.write_bytes((json.dumps(registry, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode())
    registry_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = {
        "kind": "PR294_STUDENT_PUBLIC_SCOPE_REVIEW_RECEIPT_V1",
        "status": "REVIEWED_SCOPES_NOT_PUBLICATION_AUTHORITY",
        "activation_allowed": False,
        "repository": "cyranoaladin/RAG", "pull_request": 294,
        "reviewer": "abenrhouma",
        "base_sha": "1" * 40, "head_sha": "2" * 40,
        "head_tree_sha": "3" * 40, "merge_commit_sha": "4" * 40,
        "review_id": 1, "workflow_run_id": 1,
        "trusted_status_context": "trusted-human-review/head-pinned",
        "challenge": "NEXUS-TRUSTED-REVIEW-V1:" + "5" * 64,
        "content_anchor_sha256": content.content_anchor_sha256,
        "content_manifest_sha256": content.content_manifest_sha256,
        "policy_registry_sha256": hashlib.sha256(policy_raw).hexdigest(),
        "successor_authority_sha256": hashlib.sha256(names_raw).hexdigest(),
        "public_scope_authority_sha256": registry_sha,
        "scope_sha256_by_id": {scope.scope_id: scope.sha256_digest()},
    }
    receipt_raw = (json.dumps(receipt, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()
    return path, registry_sha, content, policy_raw, names_raw, receipt_raw


def test_reviewed_scope_policy_reconstructs_exact_v3(tmp_path: Path) -> None:
    path, sha, content, policy, names, receipt = _reviewed_scope_policy_fixture(tmp_path)
    scopes = verify_public_scope_registry(path, sha, content, RELEASE)
    observed = verify_reviewed_public_scope_policy(
        path, sha, content, scopes, policy_raw=policy, names_raw=names,
        receipt_raw=receipt, expected_receipt_sha256=hashlib.sha256(receipt).hexdigest(),
    )
    assert observed == {scopes[0].scope_id: scopes[0].sha256_digest()}


def test_reviewed_scope_policy_refuses_resealed_audience_expansion(tmp_path: Path) -> None:
    path, _sha, content, policy, names, receipt = _reviewed_scope_policy_fixture(tmp_path)
    registry = json.loads(path.read_bytes())
    scope_path = tmp_path / registry["scopes"][0]["resource"]
    scope_doc = json.loads(scope_path.read_bytes())
    scope_doc["target_policy"]["audiences"] = ["libre", "aefe"]
    from nexus_contracts.scope import RetrievalScopeArtifactV3
    widened = RetrievalScopeArtifactV3.model_validate(scope_doc)
    scope_path.write_bytes(widened.canonical_bytes())
    registry["scopes"][0]["sha256"] = widened.sha256_digest()
    path.write_bytes((json.dumps(registry, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode())
    widened_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt_doc = json.loads(receipt)
    receipt_doc["public_scope_authority_sha256"] = widened_sha
    receipt_doc["scope_sha256_by_id"] = {widened.scope_id: widened.sha256_digest()}
    resealed_receipt = (json.dumps(receipt_doc, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
    scopes = verify_public_scope_registry(path, widened_sha, content, RELEASE)
    with pytest.raises(PublicSuccessorActivationError, match="reviewed policy"):
        verify_reviewed_public_scope_policy(
            path, widened_sha, content, scopes, policy_raw=policy, names_raw=names,
            receipt_raw=resealed_receipt,
            expected_receipt_sha256=hashlib.sha256(resealed_receipt).hexdigest(),
        )


def test_reviewed_scope_policy_refuses_changed_evidence_audience(tmp_path: Path) -> None:
    path, _sha, content, policy, names, receipt = _reviewed_scope_policy_fixture(tmp_path)
    import yaml
    policy_doc = yaml.safe_load(policy)
    policy_doc["collections"][0]["audiences"] = ["libre", "tous"]
    changed_policy = yaml.safe_dump(policy_doc, sort_keys=True).encode()
    registry = json.loads(path.read_bytes())
    registry["policy_registry_sha256"] = hashlib.sha256(changed_policy).hexdigest()
    row = registry["scopes"][0]
    scope_path = tmp_path / row["resource"]
    scope_doc = json.loads(scope_path.read_bytes())
    scope_doc["evidence_subject"]["audiences"] = ["libre", "tous"]
    from nexus_contracts.scope import RetrievalScopeArtifactV3
    changed_scope = RetrievalScopeArtifactV3.model_validate(scope_doc)
    scope_path.write_bytes(changed_scope.canonical_bytes())
    row["sha256"] = changed_scope.sha256_digest()
    path.write_bytes((json.dumps(registry, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode())
    changed_registry_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt_doc = json.loads(receipt)
    receipt_doc["policy_registry_sha256"] = hashlib.sha256(changed_policy).hexdigest()
    receipt_doc["public_scope_authority_sha256"] = changed_registry_sha
    receipt_doc["scope_sha256_by_id"] = {changed_scope.scope_id: changed_scope.sha256_digest()}
    changed_receipt = (json.dumps(receipt_doc, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
    scopes = verify_public_scope_registry(path, changed_registry_sha, content, RELEASE)
    with pytest.raises(PublicSuccessorActivationError, match="reviewed policy"):
        verify_reviewed_public_scope_policy(
            path, changed_registry_sha, content, scopes, policy_raw=changed_policy,
            names_raw=names, receipt_raw=changed_receipt,
            expected_receipt_sha256=hashlib.sha256(changed_receipt).hexdigest(),
        )


@pytest.mark.parametrize("change", ["source", "role", "visibility", "rights"])
def test_scope_registry_refuses_wrong_scope_semantics(tmp_path: Path, change: str) -> None:
    path, digest, content = _scope_fixture(tmp_path)
    scope_path = tmp_path / "scopes/hggsp.json"
    scope = json.loads(scope_path.read_bytes())
    if change == "source":
        scope["source_sha256"] = "f" * 64
    elif change == "role":
        scope["target_policy"]["roles"] = ["teacher"]
    elif change == "visibility":
        scope["evidence_subject"]["visibility"] = "internal"
    else:
        scope["evidence_subject"]["rights"] = ["officiel_public"]
    scope_path.write_bytes(json.dumps(scope, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode())
    with pytest.raises(PublicSuccessorActivationError):
        verify_public_scope_registry(path, digest, content, RELEASE)
