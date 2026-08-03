"""Sonde bornée des artefacts modèles déjà prouvés au démarrage."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from src.ingestor import model_artifact as model_artifact_module
from src.ingestor.model_artifact import (
    attest_verified_model_artifact,
    model_artifact_attestation_ready,
    verify_model_artifact,
)


def _write_artifact(root: Path) -> str:
    root.mkdir()
    files = {
        "manifest.json": json.dumps({"model_id": "nexus/test"}) + "\n",
        "model.safetensors": "poids déterministes\n",
    }
    for relative, content in files.items():
        (root / relative).write_text(content, encoding="utf-8")
    inventory = "".join(
        f"{hashlib.sha256(content.encode()).hexdigest()}  {relative}\n"
        for relative, content in sorted(files.items())
    )
    (root / "SHA256SUMS").write_text(inventory, encoding="utf-8")
    return hashlib.sha256(inventory.encode()).hexdigest()


def _verified_attestation(root: Path):
    inventory_sha256 = _write_artifact(root)
    verified_root = verify_model_artifact(
        root,
        expected_inventory_sha256=inventory_sha256,
        expected_manifest={"model_id": "nexus/test"},
        require_model_weights=True,
    )
    return (
        attest_verified_model_artifact(
            verified_root,
            expected_inventory_sha256=inventory_sha256,
        ),
        inventory_sha256,
    )


def test_bounded_attestation_accepts_the_unchanged_verified_artifact(
    tmp_path: Path,
) -> None:
    attestation, inventory_sha256 = _verified_attestation(tmp_path / "model")

    assert model_artifact_attestation_ready(
        attestation,
        expected_inventory_sha256=inventory_sha256,
    )


def test_public_probe_reads_no_artifact_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    attestation, inventory_sha256 = _verified_attestation(tmp_path / "model")

    def reject_content_read(
        _path: Path,
        *_args: object,
        **_kwargs: object,
    ) -> None:
        raise AssertionError("la sonde publique ne doit ouvrir aucun fichier modèle")

    monkeypatch.setattr(Path, "open", reject_content_read)

    assert model_artifact_attestation_ready(
        attestation,
        expected_inventory_sha256=inventory_sha256,
    )


def test_bounded_attestation_rejects_a_weight_replacement(tmp_path: Path) -> None:
    root = tmp_path / "model"
    attestation, inventory_sha256 = _verified_attestation(root)
    (root / "model.safetensors").write_bytes(b"poids remplaces et plus longs")

    assert not model_artifact_attestation_ready(
        attestation,
        expected_inventory_sha256=inventory_sha256,
    )


def test_bounded_attestation_rejects_an_added_file(tmp_path: Path) -> None:
    root = tmp_path / "model"
    attestation, inventory_sha256 = _verified_attestation(root)
    (root / "unexpected.bin").write_bytes(b"unexpected")

    assert not model_artifact_attestation_ready(
        attestation,
        expected_inventory_sha256=inventory_sha256,
    )


def test_bounded_attestation_enumerates_paths_even_if_root_metadata_is_stable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "model"
    attestation, inventory_sha256 = _verified_attestation(root)
    attested_root = attestation.entries[0]
    original_entry_state = model_artifact_module._entry_state
    (root / "unexpected.bin").write_bytes(b"unexpected")

    def stable_root_state(path: Path, relative_path: str):
        if relative_path == ".":
            return attested_root
        return original_entry_state(path, relative_path)

    monkeypatch.setattr(model_artifact_module, "_entry_state", stable_root_state)

    assert not model_artifact_attestation_ready(
        attestation,
        expected_inventory_sha256=inventory_sha256,
    )


def test_bounded_attestation_rejects_same_size_content_with_restored_mtime(
    tmp_path: Path,
) -> None:
    root = tmp_path / "model"
    attestation, inventory_sha256 = _verified_attestation(root)
    weights = root / "model.safetensors"
    before = weights.stat()
    weights.write_bytes(b"x" * before.st_size)
    os.utime(weights, ns=(before.st_atime_ns, before.st_mtime_ns))

    assert not model_artifact_attestation_ready(
        attestation,
        expected_inventory_sha256=inventory_sha256,
    )


def test_bounded_attestation_rejects_a_changed_external_anchor(tmp_path: Path) -> None:
    attestation, _inventory_sha256 = _verified_attestation(tmp_path / "model")

    assert not model_artifact_attestation_ready(
        attestation,
        expected_inventory_sha256="0" * 64,
    )
