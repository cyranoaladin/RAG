"""La phase INGESTION accepte A2 sans prolonger l'actualité A1 expirée."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/rag-engine/scripts"))
sys.path.insert(0, str(ROOT / "scripts/go_live"))
sys.path.insert(0, str(ROOT / "services/rag-engine/src"))

import check_public_successor_preissuance as preissuance  # noqa: E402
import public_successor_signing_replay as publication_replay  # noqa: E402
import sign_staging_readiness_manifest_cli as signer  # noqa: E402
from nexus_release_chain.public_successor_activation import (  # noqa: E402
    PublicSuccessorActivationVerdict,
    verify_content_anchor,
)

from ingestor.ingestion_worker import sealed_release_ingestion_cli as worker_a  # noqa: E402
from ingestor.ingestion_worker.public_text_runtime_authority import (  # noqa: E402
    PublicTextRuntimeAuthorityError,
    load_public_text_runtime_authorities,
)

RELEASE = (
    ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027"
    / "profile_gate_student_public_successor_v1/release-40b956c6f5ec0c60"
)
ANCHOR = ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261011.json"
RECEIPT = ROOT / "docs/reports/go_live/student_public_successor_preissuance_checkpoint_20261011.json"
A2 = ROOT / "docs/reports/go_live/student_public_successor_temporal_continuity_a2_20261011_v2.json"
MANIFEST = RELEASE / "profile_gate/production-profile-gate.release.json"
WHEN_A1_EXPIRED = datetime(2026, 10, 13, 0, 0, tzinfo=UTC)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_preissuance_replays_identity_and_cas_but_uses_a2_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preissuance, "_require_cas_index_matches", lambda *_: None)
    monkeypatch.setattr(preissuance, "inspect_content_preparation", lambda *_a, **_k: {
        "inclusion_population_verified": True,
        "private_cas_replay_verified": True,
        "source_currentness_window_open": False,
        "activation_allowed": False,
    })
    verdict = preissuance.verify_preissuance_authority(
        ANCHOR, _sha(ANCHOR), _sha(MANIFEST), RECEIPT, _sha(RECEIPT),
        ROOT, tmp_path, WHEN_A1_EXPIRED, temporal_authority_raw=A2.read_bytes(),
    )
    assert verdict.expires_at_utc == datetime(2026, 10, 18, 21, 54, 37, 14823, tzinfo=UTC)
    with pytest.raises(preissuance.PreissuanceError, match="A2"):
        preissuance.verify_preissuance_authority(
            ANCHOR, _sha(ANCHOR), _sha(MANIFEST), RECEIPT, _sha(RECEIPT),
            ROOT, tmp_path, WHEN_A1_EXPIRED,
        )
    with pytest.raises(preissuance.PreissuanceError, match="A2"):
        preissuance.verify_preissuance_authority(
            ANCHOR, _sha(ANCHOR), _sha(MANIFEST), RECEIPT, _sha(RECEIPT),
            ROOT, tmp_path, datetime(2026, 10, 18, tzinfo=UTC),
            temporal_authority_raw=A2.read_bytes(),
        )


def test_signer_binds_phase_to_a2_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preissuance, "_require_cas_index_matches", lambda *_: None)
    monkeypatch.setattr(preissuance, "inspect_content_preparation", lambda *_a, **_k: {
        "inclusion_population_verified": True,
        "private_cas_replay_verified": True,
        "source_currentness_window_open": False,
        "activation_allowed": False,
    })
    args = SimpleNamespace(
        public_successor_content_anchor_path=ANCHOR,
        public_successor_preissuance_receipt_path=RECEIPT,
        public_successor_private_cas_root=tmp_path,
        public_successor_repository_root=ROOT,
        public_successor_temporal_authority_path=A2,
    )
    anchor_sha, phase_sha, expiry = signer._verify_public_successor_ingestion_replay(
        args, _sha(MANIFEST), WHEN_A1_EXPIRED,
    )
    assert anchor_sha == _sha(ANCHOR)
    assert phase_sha == _sha(A2)
    assert expiry > WHEN_A1_EXPIRED
    link = tmp_path / "a2-link.json"
    link.symlink_to(A2)
    args.public_successor_temporal_authority_path = link
    with pytest.raises(signer.SigningRefused, match="symlink"):
        signer._verify_public_successor_ingestion_replay(
            args, _sha(MANIFEST), WHEN_A1_EXPIRED,
        )


def test_worker_a_requires_exact_signed_a2_before_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Clock(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return WHEN_A1_EXPIRED

    monkeypatch.setattr(worker_a, "datetime", Clock)
    readiness = SimpleNamespace(manifest=SimpleNamespace(
        public_successor_phase="INGESTION",
        public_successor_content_anchor_digest=_sha(ANCHOR),
        public_successor_phase_authority_digest=_sha(A2),
        allowed_release_id="student-public-successor-20261010-40b956c6f5ec0c60",
        allowed_release_manifest_sha256=_sha(MANIFEST),
    ))
    content = worker_a._require_public_candidate_ingestion_authority(
        readiness, RELEASE / "profile_gate", ANCHOR, RECEIPT, _sha(RECEIPT), A2,
    )
    assert content.expected_counts["placements"] == 377
    with pytest.raises(worker_a.SealedReleaseIngestionError, match="A2"):
        worker_a._require_public_candidate_ingestion_authority(
            readiness, RELEASE / "profile_gate", ANCHOR, RECEIPT, _sha(RECEIPT),
        )
    readiness.manifest.public_successor_phase_authority_digest = "a" * 64
    with pytest.raises(worker_a.SealedReleaseIngestionError, match="phase authority"):
        worker_a._require_public_candidate_ingestion_authority(
            readiness, RELEASE / "profile_gate", ANCHOR, RECEIPT, _sha(RECEIPT), A2,
        )


def test_publication_replay_uses_a2_and_refuses_missing_or_changed_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preissuance, "_require_cas_index_matches", lambda *_: None)
    monkeypatch.setattr(preissuance, "inspect_content_preparation", lambda *_a, **_k: {
        "inclusion_population_verified": True,
        "private_cas_replay_verified": True,
        "source_currentness_window_open": False,
        "activation_allowed": False,
    })
    inputs = publication_replay.PublicationSigningInputs(
        bundle_root=tmp_path, repository_root=ROOT,
        content_anchor_path=ANCHOR, preissuance_receipt_path=RECEIPT,
        private_cas_root=tmp_path, target_root=tmp_path,
        target_pin_path=tmp_path / "pin.json",
        target_pin_receipt_path=tmp_path / "receipt.json",
        target_pin_pull_request=327,
        observed_v1_receipt_path=tmp_path / "observed.json",
        database_dsn="postgresql://unused",
        temporal_authority_path=A2,
    )
    expiry = publication_replay._replay_publication_preissuance(
        inputs, _sha(ANCHOR), _sha(MANIFEST), WHEN_A1_EXPIRED,
    )
    assert expiry == datetime(2026, 10, 18, 21, 54, 37, 14823, tzinfo=UTC)
    with pytest.raises(publication_replay.PublicationSigningReplayRefused, match="A2"):
        publication_replay._replay_publication_preissuance(
            SimpleNamespace(**{**vars(inputs), "temporal_authority_path": None}),
            _sha(ANCHOR), _sha(MANIFEST), WHEN_A1_EXPIRED,
        )
    tampered = tmp_path / "a2.json"
    tampered.write_bytes(A2.read_bytes() + b" ")
    with pytest.raises(publication_replay.PublicationSigningReplayRefused, match="A2"):
        publication_replay._replay_publication_preissuance(
            SimpleNamespace(**{**vars(inputs), "temporal_authority_path": tampered}),
            _sha(ANCHOR), _sha(MANIFEST), WHEN_A1_EXPIRED,
        )


def test_worker_b_a2_requires_c_envelope_binding_and_preserves_registry_checks(
    tmp_path: Path,
) -> None:
    content = verify_content_anchor(ANCHOR, _sha(ANCHOR), RELEASE)
    envelope = tmp_path / "authority-envelope.json"
    envelope.write_text(json.dumps({"authorities": {
        "temporal_a2_authority_sha256": _sha(A2),
    }}, sort_keys=True))
    activation = PublicSuccessorActivationVerdict(
        release_id=content.release_id,
        content_anchor_sha256=content.content_anchor_sha256,
        content_manifest_sha256=content.content_manifest_sha256,
        authority_envelope_sha256=_sha(envelope),
        artifact_registry_sha256=content.artifact_registry_sha256,
        release_registry_sha256=content.release_registry_sha256,
        scope_authority_sha256="b" * 64,
        subject_sha256_by_collection=content.subject_sha256_by_collection,
        scope_sha256_by_id={}, counts=content.expected_counts,
        expires_at_utc=datetime(2026, 10, 14, tzinfo=UTC),
    )
    transfer = ROOT / "docs/reports/go_live/student_public_successor_v2_transfer_plan_release40b_a2_20261012.json"
    kwargs = dict(
        release_root=RELEASE, content_anchor_path=ANCHOR,
        expected_content_anchor_sha256=_sha(ANCHOR), activation=activation,
        transfer_manifest_path=transfer,
        expected_transfer_manifest_sha256=_sha(transfer),
        now_utc=WHEN_A1_EXPIRED,
    )
    with pytest.raises(PublicTextRuntimeAuthorityError, match="A2"):
        load_public_text_runtime_authorities(**kwargs)
    authorities = load_public_text_runtime_authorities(
        **kwargs, authority_envelope_path=envelope, temporal_authority_path=A2,
    )
    assert authorities.rights_evidence_registry._expires_at_utc == activation.expires_at_utc
    envelope.write_text(json.dumps({"authorities": {
        "temporal_a2_authority_sha256": "a" * 64,
    }}, sort_keys=True))
    with pytest.raises(PublicTextRuntimeAuthorityError, match="envelope|A2"):
        load_public_text_runtime_authorities(
            **kwargs, authority_envelope_path=envelope, temporal_authority_path=A2,
        )
    envelope.write_text(json.dumps({"authorities": {
        "temporal_a2_authority_sha256": _sha(A2),
    }}, sort_keys=True))
    altered = tmp_path / "altered-a2.json"
    altered.write_bytes(A2.read_bytes() + b" ")
    with pytest.raises(PublicTextRuntimeAuthorityError, match="A2"):
        load_public_text_runtime_authorities(
            **{**kwargs, "activation": replace(activation, authority_envelope_sha256=_sha(envelope))},
            authority_envelope_path=envelope, temporal_authority_path=altered,
        )
    with pytest.raises(PublicTextRuntimeAuthorityError, match="C expiry exceeds A2"):
        load_public_text_runtime_authorities(
            **{**kwargs, "activation": replace(
                activation, authority_envelope_sha256=_sha(envelope),
                expires_at_utc=datetime(2026, 10, 19, tzinfo=UTC),
            )},
            authority_envelope_path=envelope, temporal_authority_path=A2,
        )
