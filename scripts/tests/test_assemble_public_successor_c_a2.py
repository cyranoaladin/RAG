"""Le bundle C A2 transporte des octets, jamais une activation auto-déclarée."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest
from nexus_release_chain.release_readiness import _PUBLIC_SUCCESSOR_A2_AUTHORITY_FIELDS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))
from assemble_public_successor_c_a2 import AssemblyRefused, assemble_a2_bundle, main

ROOT = Path(__file__).resolve().parents[2]
ANCHOR = ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261011.json"
RELEASE = ROOT / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_student_public_successor_v1/release-40b956c6f5ec0c60"
)
COMPANIONS = frozenset({
    "observed-transfer-v1.json", "target-pin.json", "scope-policy.yml", "scope-names.yml",
})


def _inputs(tmp_path: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    source = tmp_path / "source"
    source.mkdir()
    authorities = {}
    for field in _PUBLIC_SUCCESSOR_A2_AUTHORITY_FIELDS:
        path = source / field
        path.write_text(json.dumps({"field": field}) + "\n", encoding="utf-8")
        authorities[field] = path
    authorities["source_preparation_release_manifest_sha256"] = (
        RELEASE / "profile_gate/production-profile-gate.release.json"
    )
    authorities["source_preparation_index_sha256"] = RELEASE / "preparation-index.json"
    authorities["candidate_inventory_sha256"] = RELEASE / "profile_gate/candidate_inventory.json"
    companions = {}
    for name in COMPANIONS:
        path = source / name
        path.write_text(json.dumps({"name": name}) + "\n", encoding="utf-8")
        companions[name] = path
    return authorities, companions


def test_assembly_copies_exact_proof_bytes_and_never_claims_activation(tmp_path: Path) -> None:
    authorities, companions = _inputs(tmp_path)
    output = tmp_path / "bundle"
    result = assemble_a2_bundle(
        anchor_path=ANCHOR, release_root=RELEASE, evidence_paths=authorities,
        companion_paths=companions, output_root=output,
    )
    envelope_raw = (output / "authority-envelope.json").read_bytes()
    envelope = json.loads(envelope_raw)
    assert envelope_raw == (json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    assert envelope["kind"] == "NEXUS_PUBLIC_SUCCESSOR_AUTHORITY_ENVELOPE_A2_V1"
    assert envelope["activation_allowed"] is False
    assert envelope["semantic_verification_complete"] is False
    assert result["authority_envelope_sha256"] == hashlib.sha256(envelope_raw).hexdigest()
    assert result["authority_count"] == 26
    assert set(envelope["authorities"]) == _PUBLIC_SUCCESSOR_A2_AUTHORITY_FIELDS
    for field, source in authorities.items():
        copied = (output / "authorities" / f"{field}.bin").read_bytes()
        assert copied == source.read_bytes()
        assert envelope["authorities"][field] == hashlib.sha256(copied).hexdigest()
    for name, source in companions.items():
        assert (output / "authorities" / name).read_bytes() == source.read_bytes()
    assert (output / "content-anchor.json").read_bytes() == ANCHOR.read_bytes()
    assert (output / "release/preparation-index.json").read_bytes() == (
        RELEASE / "preparation-index.json"
    ).read_bytes()


def test_assembly_refuses_missing_proof_without_partial_bundle(tmp_path: Path) -> None:
    authorities, companions = _inputs(tmp_path)
    authorities.pop("temporal_c_attestation_sha256")
    output = tmp_path / "bundle"
    with pytest.raises(AssemblyRefused, match="26"):
        assemble_a2_bundle(
            anchor_path=ANCHOR, release_root=RELEASE, evidence_paths=authorities,
            companion_paths=companions, output_root=output,
        )
    assert not output.exists()


def test_assembly_refuses_symlink_or_replacement(tmp_path: Path) -> None:
    authorities, companions = _inputs(tmp_path)
    field = "temporal_c_attestation_sha256"
    original = authorities[field]
    link = tmp_path / "proof-link"
    link.symlink_to(original)
    authorities[field] = link
    output = tmp_path / "bundle"
    with pytest.raises(AssemblyRefused, match="symlink"):
        assemble_a2_bundle(
            anchor_path=ANCHOR, release_root=RELEASE, evidence_paths=authorities,
            companion_paths=companions, output_root=output,
        )
    assert not output.exists()
    authorities[field] = original
    output.mkdir()
    (output / "valuable.json").write_text("keep me")
    with pytest.raises(AssemblyRefused, match="exists"):
        assemble_a2_bundle(
            anchor_path=ANCHOR, release_root=RELEASE, evidence_paths=authorities,
            companion_paths=companions, output_root=output,
        )
    assert (output / "valuable.json").read_text() == "keep me"


def test_assembly_refuses_foreign_release_file(tmp_path: Path) -> None:
    authorities, companions = _inputs(tmp_path)
    release = tmp_path / "release"
    shutil.copytree(RELEASE, release)
    (release / "document.pdf").write_bytes(b"%PDF foreign")
    authorities["source_preparation_release_manifest_sha256"] = (
        release / "profile_gate/production-profile-gate.release.json"
    )
    authorities["source_preparation_index_sha256"] = release / "preparation-index.json"
    authorities["candidate_inventory_sha256"] = release / "profile_gate/candidate_inventory.json"
    with pytest.raises(AssemblyRefused, match="foreign"):
        assemble_a2_bundle(
            anchor_path=ANCHOR, release_root=release, evidence_paths=authorities,
            companion_paths=companions, output_root=tmp_path / "bundle",
        )


def test_assembly_refuses_output_nested_in_immutable_release(tmp_path: Path) -> None:
    authorities, companions = _inputs(tmp_path)
    release = tmp_path / "release"
    shutil.copytree(RELEASE, release)
    authorities["source_preparation_release_manifest_sha256"] = (
        release / "profile_gate/production-profile-gate.release.json"
    )
    authorities["source_preparation_index_sha256"] = release / "preparation-index.json"
    authorities["candidate_inventory_sha256"] = release / "profile_gate/candidate_inventory.json"
    with pytest.raises(AssemblyRefused, match="overlaps"):
        assemble_a2_bundle(
            anchor_path=ANCHOR, release_root=release, evidence_paths=authorities,
            companion_paths=companions, output_root=release / "C-bundle",
        )
    assert not (release / "C-bundle").exists()


def test_cli_rejects_duplicate_evidence_map_keys(tmp_path: Path) -> None:
    authorities, companions = _inputs(tmp_path)
    mapping = {
        "authorities": {key: str(value) for key, value in authorities.items()},
        "companions": {key: str(value) for key, value in companions.items()},
    }
    raw = json.dumps(mapping).replace('"authorities":', '"authorities": {}, "authorities":', 1)
    path = tmp_path / "evidence-map.json"
    path.write_text(raw, encoding="utf-8")
    output = tmp_path / "bundle"
    assert main([
        "--anchor", str(ANCHOR), "--release-root", str(RELEASE),
        "--evidence-map", str(path), "--output-root", str(output),
    ]) == 1
    assert not output.exists()
