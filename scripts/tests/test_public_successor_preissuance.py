"""Pré-émission : un checkpoint scellé ne remplace jamais le rejeu live."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))

from build_public_successor_content_anchor import canonical_bytes
from check_public_successor_preissuance import (  # type: ignore[import-not-found]
    PreissuanceError,
    build_preissuance_receipt,
    verify_preissuance_authority,
)

ROOT = Path(__file__).resolve().parents[2]
ANCHOR = ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261010.json"
MANIFEST = ROOT / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_student_public_successor_v1/release-fcc84331e7700042/"
    "profile_gate/production-profile-gate.release.json"
)
HISTORICAL_NOW = datetime(2026, 10, 10, 21, tzinfo=UTC)
A2_ANCHOR = ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261011.json"
A2_MANIFEST = ROOT / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_student_public_successor_v1/release-40b956c6f5ec0c60/"
    "profile_gate/production-profile-gate.release.json"
)
A2_AUTHORITY = ROOT / "docs/reports/go_live/student_public_successor_temporal_continuity_a2_20261011_v2.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    cas = tmp_path / "cas"
    cas.mkdir(parents=True)
    (cas / "index.json").write_bytes(b"{}\n")
    receipt = build_preissuance_receipt(
        ANCHOR, _sha(ANCHOR), MANIFEST, ROOT, cas,
    )
    path = tmp_path / "preissuance.json"
    path.write_bytes(canonical_bytes(receipt))
    return path, cas


def _a2_fixture(tmp_path: Path) -> tuple[Path, Path]:
    cas = tmp_path / "cas"
    cas.mkdir(parents=True)
    (cas / "index.json").write_bytes(b"{}\n")
    receipt = build_preissuance_receipt(
        A2_ANCHOR, _sha(A2_ANCHOR), A2_MANIFEST, ROOT, cas,
    )
    path = tmp_path / "preissuance-a2.json"
    path.write_bytes(canonical_bytes(receipt))
    return path, cas


def test_a2_replays_old_cas_at_sealed_instant_after_original_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, cas = _a2_fixture(tmp_path)
    import check_public_successor_preissuance as module

    historical = datetime(2026, 10, 11, 14, 5, 36, tzinfo=UTC)
    observed: list[datetime | None] = []

    def inspect(*_args: object, **kwargs: object) -> dict[str, bool]:
        candidate = kwargs.get("cas_as_of")
        assert candidate is None or isinstance(candidate, datetime)
        observed.append(candidate)
        return {
            "inclusion_population_verified": True,
            "private_cas_replay_verified": True,
            "source_currentness_window_open": False,
            "activation_allowed": False,
        }

    monkeypatch.setattr(module, "_require_cas_index_matches", lambda *_a: None)
    monkeypatch.setattr(module, "_historical_cas_as_of", lambda *_a: historical, raising=False)
    monkeypatch.setattr(module, "inspect_content_preparation", inspect)
    verdict = verify_preissuance_authority(
        A2_ANCHOR, _sha(A2_ANCHOR), _sha(A2_MANIFEST), path, _sha(path), ROOT,
        cas, datetime(2026, 10, 13, tzinfo=UTC),
        temporal_authority_raw=A2_AUTHORITY.read_bytes(),
    )
    assert verdict.preissuance_verified is True
    assert observed == [historical]


def test_a2_release_cannot_replay_expired_cas_without_a2(tmp_path: Path) -> None:
    path, cas = _a2_fixture(tmp_path)
    with pytest.raises(PreissuanceError, match="A2 temporal authority required"):
        verify_preissuance_authority(
            A2_ANCHOR, _sha(A2_ANCHOR), _sha(A2_MANIFEST), path, _sha(path),
            ROOT, cas, datetime(2026, 10, 13, tzinfo=UTC),
        )


def test_a2_historical_cas_uses_index_pinned_attestation_time(tmp_path: Path) -> None:
    import check_public_successor_preissuance as module

    cas = tmp_path / "cas"
    report_path = cas / "reports/source_currentness.json"
    report_path.parent.mkdir(parents=True)
    report_raw = canonical_bytes({"attested_at_utc": "2026-10-11T14:05:36Z"})
    report_path.write_bytes(report_raw)
    index_raw = canonical_bytes({"files": [{
        "path": "reports/source_currentness.json",
        "sha256": hashlib.sha256(report_raw).hexdigest(),
        "byte_count": len(report_raw),
    }]})
    (cas / "index.json").write_bytes(index_raw)
    assert module._historical_cas_as_of(
        cas, hashlib.sha256(index_raw).hexdigest(),
        datetime(2026, 10, 13, tzinfo=UTC),
        datetime(2026, 10, 12, 13, 58, 41, tzinfo=UTC),
    ) == datetime(2026, 10, 11, 14, 5, 36, tzinfo=UTC)


@pytest.mark.parametrize("timestamp", [
    "2026-10-13T01:00:00Z",  # après l'instant du rejeu
    "2026-10-12T14:00:00Z",  # après l'expiration du reçu original
    "2026-10-11T15:05:36+01:00",  # pas la forme UTC scellée
])
def test_a2_historical_cas_rejects_invalid_sealed_timestamp(
    tmp_path: Path, timestamp: str,
) -> None:
    import check_public_successor_preissuance as module

    cas = tmp_path / "cas"
    report_path = cas / "reports/source_currentness.json"
    report_path.parent.mkdir(parents=True)
    report_raw = canonical_bytes({"attested_at_utc": timestamp})
    report_path.write_bytes(report_raw)
    index_raw = canonical_bytes({"files": [{
        "path": "reports/source_currentness.json",
        "sha256": hashlib.sha256(report_raw).hexdigest(),
        "byte_count": len(report_raw),
    }]})
    (cas / "index.json").write_bytes(index_raw)
    with pytest.raises(PreissuanceError, match="historical CAS"):
        module._historical_cas_as_of(
            cas, hashlib.sha256(index_raw).hexdigest(),
            datetime(2026, 10, 13, tzinfo=UTC),
            datetime(2026, 10, 12, 13, 58, 41, tzinfo=UTC),
        )


def test_a2_historical_cas_rejects_report_bytes_changed_after_index(
    tmp_path: Path,
) -> None:
    import check_public_successor_preissuance as module

    cas = tmp_path / "cas"
    report_path = cas / "reports/source_currentness.json"
    report_path.parent.mkdir(parents=True)
    report_raw = canonical_bytes({"attested_at_utc": "2026-10-11T14:05:36Z"})
    report_path.write_bytes(report_raw)
    index_raw = canonical_bytes({"files": [{
        "path": "reports/source_currentness.json",
        "sha256": hashlib.sha256(report_raw).hexdigest(),
        "byte_count": len(report_raw),
    }]})
    (cas / "index.json").write_bytes(index_raw)
    report_path.write_bytes(report_raw.replace(b"14:05:36", b"14:05:37"))
    with pytest.raises(PreissuanceError, match="historical CAS"):
        module._historical_cas_as_of(
            cas, hashlib.sha256(index_raw).hexdigest(),
            datetime(2026, 10, 13, tzinfo=UTC),
            datetime(2026, 10, 12, 13, 58, 41, tzinfo=UTC),
        )


def test_preissuance_replays_live_and_returns_exact_subjects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, cas = _fixture(tmp_path)
    import check_public_successor_preissuance as module

    monkeypatch.setattr(module, "inspect_content_preparation", lambda *_a, **_k: {
        "inclusion_population_verified": True,
        "private_cas_replay_verified": True,
        "source_currentness_window_open": True,
        "activation_allowed": False,
    })
    monkeypatch.setattr(module, "_require_cas_index_matches", lambda *_a: None)
    verdict = verify_preissuance_authority(
        ANCHOR, _sha(ANCHOR), _sha(MANIFEST), path, _sha(path), ROOT, cas,
        HISTORICAL_NOW,
    )
    assert verdict.content_anchor_sha256 == _sha(ANCHOR)
    assert verdict.content_manifest_sha256 == _sha(MANIFEST)
    assert verdict.subject_sha256_by_collection == {
        row["collection"]: row["subject_sha256"]
        for row in json.loads(ANCHOR.read_bytes())["subjects"]
    }
    assert verdict.preissuance_verified is True
    assert verdict.publication_authorized is False


def test_preissuance_rejects_expiry_even_if_replay_claims_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, cas = _fixture(tmp_path)
    import check_public_successor_preissuance as module

    monkeypatch.setattr(module, "inspect_content_preparation", lambda *_a, **_k: {
        "inclusion_population_verified": True,
        "private_cas_replay_verified": True,
        "source_currentness_window_open": True,
        "activation_allowed": False,
    })
    monkeypatch.setattr(module, "_require_cas_index_matches", lambda *_a: None)
    with pytest.raises(PreissuanceError, match="expired"):
        verify_preissuance_authority(
            ANCHOR, _sha(ANCHOR), _sha(MANIFEST), path, _sha(path), ROOT, cas,
            HISTORICAL_NOW + timedelta(days=3),
        )


def test_preissuance_rejects_tampered_receipt_and_cas_index(tmp_path: Path) -> None:
    path, cas = _fixture(tmp_path)
    original = _sha(path)
    document = json.loads(path.read_bytes())
    document["subject_sha256_by_collection"][next(iter(
        document["subject_sha256_by_collection"]
    ))] = "a" * 64
    path.write_bytes(canonical_bytes(document))
    with pytest.raises(PreissuanceError):
        verify_preissuance_authority(
            ANCHOR, _sha(ANCHOR), _sha(MANIFEST), path, original, ROOT, cas,
            HISTORICAL_NOW,
        )
    path, cas = _fixture(tmp_path / "fresh")
    (cas / "index.json").write_bytes(b"{\"changed\":true}\n")
    with pytest.raises(PreissuanceError, match="CAS"):
        verify_preissuance_authority(
            ANCHOR, _sha(ANCHOR), _sha(MANIFEST), path, _sha(path), ROOT, cas,
            HISTORICAL_NOW,
        )


def test_preissuance_rejects_missing_live_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, cas = _fixture(tmp_path)
    import check_public_successor_preissuance as module

    monkeypatch.setattr(module, "inspect_content_preparation", lambda *_a, **_k: {
        "inclusion_population_verified": True,
        "private_cas_replay_verified": False,
        "source_currentness_window_open": True,
        "activation_allowed": False,
    })
    monkeypatch.setattr(module, "_require_cas_index_matches", lambda *_a: None)
    with pytest.raises(PreissuanceError, match="replay"):
        verify_preissuance_authority(
            ANCHOR, _sha(ANCHOR), _sha(MANIFEST), path, _sha(path), ROOT, cas,
            HISTORICAL_NOW,
        )
