"""C ne compose un verdict A2 qu'après des constats live liés aux 26 preuves."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from nexus_contracts.authorization_set import VerifiedAuthorizationSetV1
from nexus_contracts.production_readiness import ProductionReadinessManifestV2
from nexus_release_chain import public_successor_activation as c

NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)
SHA = "a" * 64


def _case():
    ids = tuple(f"lot41a-student-public-collection-{n}-v2" for n in range(11))
    members = tuple(SimpleNamespace(
        authorization_id=ident, authorization_digest=f"{n:064x}",
        review_binding_digest=f"{n + 11:064x}",
        scope=SimpleNamespace(collection=f"collection-{n}"),
    ) for n, ident in enumerate(ids))
    authorization_set = SimpleNamespace(
        members=members,
        authorizations_effective_valid_from=NOW - timedelta(days=1),
        authorizations_effective_valid_until=NOW + timedelta(days=3),
    )
    authorization_raw = b"set"
    authorization_sha = hashlib.sha256(authorization_raw).hexdigest()
    verified = VerifiedAuthorizationSetV1(
        authorization_set_bytes=authorization_raw, authorization_set_digest=authorization_sha,
        authorization_ids=ids, content_authorization_ids=(),
        scope_authorization_ids=(),
        authorizations_effective_valid_from=NOW - timedelta(days=1),
        authorizations_effective_valid_until=NOW + timedelta(days=3),
        earliest_review_submitted_at=NOW - timedelta(hours=2),
        earliest_review_binding_verified_at=NOW - timedelta(hours=1),
        earliest_review_binding_expires_at=NOW + timedelta(days=2),
        verified_at=NOW - timedelta(minutes=1),
    )
    counts = {"subjects": 11, "unique_artifacts": 253,
              "placements": 377, "unique_chunks": 3975}
    content = SimpleNamespace(
        release_id="public-test", content_anchor_sha256="b" * 64,
        content_manifest_sha256="c" * 64,
        artifact_registry_sha256="d" * 64,
        release_registry_sha256="e" * 64,
        subject_sha256_by_collection={f"collection-{n}": SHA for n in range(11)},
        expected_counts=counts,
    )
    authorities = {name: SHA for name in c._PUBLIC_SUCCESSOR_A2_AUTHORITY_FIELDS}
    authorities["authorization_set_sha256"] = authorization_sha
    scope_sha256_by_id = {f"scope-{n}": SHA for n in range(11)}
    batch = SimpleNamespace(
        review_id="lot42-test", valid_until=NOW + timedelta(days=2),
        digest=lambda: authorities["publication_batch_review_receipt_sha256"],
    )
    reviews = tuple(sorted((
        member.scope.collection, member.authorization_id,
        member.authorization_digest, member.review_binding_digest,
    ) for member in members))
    live = c.VerifiedPublicSuccessorLiveEvidence(
        authority_sha256_by_field=authorities,
        content_anchor_sha256=content.content_anchor_sha256,
        authority_envelope_sha256="f" * 64,
        target_pin_sha256="1" * 64,
        release_id=content.release_id,
        content_manifest_sha256=content.content_manifest_sha256,
        counts=counts,
        scope_sha256_by_id=scope_sha256_by_id,
        verified_authorization_set=verified,
        authorization_review_evidence_by_id=reviews,
        publication_batch_review_id=batch.review_id,
        publication_batch_review_digest=authorities["publication_batch_review_receipt_sha256"],
        publication_batch_review_binding=("1" * 40, "2" * 40, "3" * 40, 1,
            "NEXUS-TRUSTED-REVIEW-V1:" + "4" * 64, "abenrhouma"),
        verified_at_utc=NOW - timedelta(seconds=5),
        revocations_checked_at_utc=NOW - timedelta(seconds=10),
        source_pulse_replayed_at_utc=NOW - timedelta(seconds=20),
        active_authorization_ids=ids,
        lot42_attestation_count=377,
        revoked_authorization_ids=(),
        revoked_review_ids=(),
        target_pin_expires_at_utc=NOW + timedelta(hours=8),
        expires_at_utc=NOW + timedelta(hours=4),
    )
    kwargs = {
        "content": content, "authority_envelope_sha256": "f" * 64,
        "authorities": authorities, "scope_sha256_by_id": scope_sha256_by_id,
        "authorization_set": authorization_set, "batch_review": batch,
        "expected_target_pin_sha256": "1" * 64,
        "a2_expires_at_utc": NOW + timedelta(days=6),
        "pin_expires_at_utc": NOW + timedelta(hours=8),
        "now_utc": NOW,
    }
    return live, kwargs


def test_c_live_evidence_bounds_expiry_without_a1() -> None:
    live, kwargs = _case()
    verdict = c._finalize_a2_live_evidence(live=live, **kwargs)
    assert verdict.expires_at_utc == NOW + timedelta(hours=4)
    assert verdict.authorization_review_evidence_by_id == live.authorization_review_evidence_by_id
    assert verdict.publication_batch_review_binding == live.publication_batch_review_binding


def test_c_live_evidence_refuses_absent_supplier_result() -> None:
    _, kwargs = _case()
    with pytest.raises(c.PublicSuccessorActivationError, match="trusted live C replay absent"):
        c._finalize_a2_live_evidence(live=None, **kwargs)  # type: ignore[arg-type]


def test_c_live_replay_clock_is_read_after_supplier(monkeypatch: pytest.MonkeyPatch) -> None:
    completed_at = NOW + timedelta(seconds=30)

    class Clock:
        @staticmethod
        def now(tz: object) -> datetime:
            assert tz is UTC
            return completed_at

    monkeypatch.setattr(c, "datetime", Clock)
    assert c._post_replay_utc_now(NOW) == completed_at
    assert c._post_replay_utc_now(completed_at + timedelta(seconds=1)) == (
        completed_at + timedelta(seconds=1)
    )


def _signed_readiness(live: c.VerifiedPublicSuccessorLiveEvidence) -> ProductionReadinessManifestV2:
    fixture = (
        Path(__file__).resolve().parents[2]
        / "contracts/tests/fixtures/legacy_v2/production_readiness_manifest_v2.json"
    )
    fields = json.loads(fixture.read_bytes())
    fields.update(
        issued_at=NOW - timedelta(minutes=1),
        sealed_manifest_digest=live.content_manifest_sha256,
        public_successor_content_manifest_digest=live.content_manifest_sha256,
        public_successor_content_anchor_digest=live.content_anchor_sha256,
        public_successor_authority_envelope_digest=live.authority_envelope_sha256,
        public_successor_target_pin_digest=live.target_pin_sha256,
        public_successor_c_expires_at_utc=live.expires_at_utc,
        public_successor_c_verified_at_utc=NOW - timedelta(seconds=30),
        public_successor_lot42_review_binding=live.publication_batch_review_binding,
    )
    return ProductionReadinessManifestV2.model_validate(fields)


def test_signed_c_runtime_uses_exact_signed_binding_and_expiry() -> None:
    live, kwargs = _case()
    readiness = _signed_readiness(live)
    verdict = c._finalize_a2_signed_readiness(
        readiness=readiness,
        content=kwargs["content"],
        authority_envelope_sha256=kwargs["authority_envelope_sha256"],
        authorities=kwargs["authorities"],
        scope_sha256_by_id=kwargs["scope_sha256_by_id"],
        authorization_set=kwargs["authorization_set"],
        batch_review=kwargs["batch_review"],
        expected_target_pin_sha256=kwargs["expected_target_pin_sha256"],
        a2_expires_at_utc=kwargs["a2_expires_at_utc"],
        pin_expires_at_utc=kwargs["pin_expires_at_utc"],
        now_utc=kwargs["now_utc"],
    )
    assert verdict.expires_at_utc == live.expires_at_utc
    assert verdict.publication_batch_review_binding == live.publication_batch_review_binding


@pytest.mark.parametrize("mutation", [
    "expired", "a", "c", "pin", "lot42", "overlong", "future_replay",
])
def test_signed_c_runtime_refuses_missing_or_divergent_authority(mutation: str) -> None:
    live, kwargs = _case()
    readiness = _signed_readiness(live)
    if mutation == "expired":
        kwargs["now_utc"] = live.expires_at_utc
    elif mutation == "a":
        kwargs["content"] = SimpleNamespace(**{
            **vars(kwargs["content"]), "content_anchor_sha256": "0" * 64,
        })
    elif mutation == "c":
        kwargs["authority_envelope_sha256"] = "0" * 64
    elif mutation == "pin":
        kwargs["expected_target_pin_sha256"] = "0" * 64
    elif mutation == "lot42":
        kwargs["authorities"] = {
            **kwargs["authorities"], "publication_batch_review_receipt_sha256": "0" * 64,
        }
    elif mutation == "future_replay":
        readiness = readiness.model_copy(update={
            "public_successor_c_verified_at_utc": NOW + timedelta(seconds=1),
        })
    else:
        readiness = readiness.model_copy(update={
            "public_successor_c_expires_at_utc": NOW + timedelta(days=7),
        })
    with pytest.raises(c.PublicSuccessorActivationError):
        c._finalize_a2_signed_readiness(
            readiness=readiness,
            content=kwargs["content"],
            authority_envelope_sha256=kwargs["authority_envelope_sha256"],
            authorities=kwargs["authorities"],
            scope_sha256_by_id=kwargs["scope_sha256_by_id"],
            authorization_set=kwargs["authorization_set"],
            batch_review=kwargs["batch_review"],
            expected_target_pin_sha256=kwargs["expected_target_pin_sha256"],
            a2_expires_at_utc=kwargs["a2_expires_at_utc"],
            pin_expires_at_utc=kwargs["pin_expires_at_utc"],
            now_utc=kwargs["now_utc"],
        )


@pytest.mark.parametrize("mutation", [
    "missing_authority", "unknown_authority", "stale_revocations",
    "lot42_substitution", "missing_authorization", "pin_substitution",
    "revoked_authorization", "lot42_count", "stale_source_replay",
    "missing_db_authorization", "lot42_reviewer",
])
def test_c_live_evidence_refuses_omission_substitution_and_staleness(
    mutation: str,
) -> None:
    live, kwargs = _case()
    if mutation == "missing_authority":
        changed = dict(live.authority_sha256_by_field)
        changed.pop("temporal_c_attestation_sha256")
        live = replace(live, authority_sha256_by_field=changed)
    elif mutation == "unknown_authority":
        changed = dict(live.authority_sha256_by_field)
        changed["unknown"] = SHA
        live = replace(live, authority_sha256_by_field=changed)
    elif mutation == "stale_revocations":
        live = replace(live, revocations_checked_at_utc=NOW - timedelta(hours=1))
    elif mutation == "lot42_substitution":
        live = replace(live, publication_batch_review_digest="0" * 64)
    elif mutation == "missing_authorization":
        live = replace(live, authorization_review_evidence_by_id=(
            live.authorization_review_evidence_by_id[:-1]
        ))
    elif mutation == "pin_substitution":
        live = replace(live, target_pin_sha256="0" * 64)
    elif mutation == "revoked_authorization":
        live = replace(live, revoked_authorization_ids=(
            live.active_authorization_ids[0],
        ))
    elif mutation == "lot42_count":
        live = replace(live, lot42_attestation_count=376)
    elif mutation == "missing_db_authorization":
        live = replace(live, active_authorization_ids=live.active_authorization_ids[:-1])
    elif mutation == "lot42_reviewer":
        live = replace(live, publication_batch_review_binding=(
            *live.publication_batch_review_binding[:5], "other-reviewer",
        ))
    else:
        live = replace(live, source_pulse_replayed_at_utc=NOW - timedelta(hours=1))
    with pytest.raises(c.PublicSuccessorActivationError):
        c._finalize_a2_live_evidence(live=live, **kwargs)
