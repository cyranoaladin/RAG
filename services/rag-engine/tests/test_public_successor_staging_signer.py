"""Le signer de répétition ne scelle pas INGESTION sur un simple checkpoint."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/rag-engine/scripts"))
sys.path.insert(0, str(ROOT / "scripts/go_live"))

import check_public_successor_preissuance as preissuance  # noqa: E402
import sign_staging_readiness_manifest_cli as signer  # noqa: E402

RELEASE = (
    ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027"
    / "profile_gate_student_public_successor_v1/release-fcc84331e7700042"
)
MANIFEST = RELEASE / "profile_gate/production-profile-gate.release.json"
ANCHOR = ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261010.json"
ANCHOR_SHA = hashlib.sha256(ANCHOR.read_bytes()).hexdigest()


def _inputs(tmp_path: Path) -> SimpleNamespace:
    private_cas = tmp_path / "cas"
    private_cas.mkdir()
    receipt = preissuance.build_preissuance_receipt(
        ANCHOR, ANCHOR_SHA, MANIFEST, ROOT, private_cas,
    )
    path = tmp_path / "preissuance.json"
    path.write_bytes((json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    return SimpleNamespace(
        public_successor_phase="INGESTION",
        public_successor_content_anchor_path=ANCHOR,
        public_successor_preissuance_receipt_path=path,
        public_successor_private_cas_root=private_cas,
        public_successor_repository_root=ROOT,
        release_manifest_file=MANIFEST,
    )


def test_signer_refuses_valid_receipt_when_private_cas_changes(tmp_path: Path) -> None:
    args = _inputs(tmp_path)
    (args.public_successor_private_cas_root / "index.json").write_text("{}")
    with pytest.raises(signer.SigningRefused, match="preissuance"):
        signer._verify_public_successor_ingestion_replay(
            args, hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
            datetime.now(UTC),
        )


def test_signer_refuses_valid_receipt_when_live_review_replay_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = _inputs(tmp_path)
    # Isoler la révocation de review : le CAS est déjà saboté par le test
    # précédent et n'a pas à être copié sur le runner CI.
    monkeypatch.setattr(preissuance, "_require_cas_index_matches", lambda *_: None)
    monkeypatch.setattr(
        preissuance, "inspect_content_preparation",
        lambda *_a, **_k: (_ for _ in ()).throw(preissuance.ContentAnchorError("review changed")),
    )
    with pytest.raises(signer.SigningRefused, match="preissuance"):
        signer._verify_public_successor_ingestion_replay(
            args, hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
            datetime.now(UTC),
        )
