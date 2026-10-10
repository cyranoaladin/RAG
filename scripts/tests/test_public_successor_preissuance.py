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
        datetime.now(UTC),
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
            datetime.now(UTC) + timedelta(days=3),
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
            datetime.now(UTC),
        )
    path, cas = _fixture(tmp_path / "fresh")
    (cas / "index.json").write_bytes(b"{\"changed\":true}\n")
    with pytest.raises(PreissuanceError, match="CAS"):
        verify_preissuance_authority(
            ANCHOR, _sha(ANCHOR), _sha(MANIFEST), path, _sha(path), ROOT, cas,
            datetime.now(UTC),
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
            datetime.now(UTC),
        )
