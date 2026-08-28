"""Sonde bornée des artefacts modèles déjà prouvés au démarrage."""

from __future__ import annotations

import hashlib
import json
import os
import time
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


def _write_modular_artifact(
    root: Path, *, include_pooling: bool, seal_pooling: bool = True
) -> str:
    """Artefact déclarant Transformer + Pooling + Normalize dans `modules.json`."""
    root.mkdir()
    modules = [
        {"idx": 0, "name": "0", "path": "", "type": "sentence_transformers.models.Transformer"},
        {"idx": 1, "name": "1", "path": "1_Pooling", "type": "sentence_transformers.models.Pooling"},
        {"idx": 2, "name": "2", "path": "2_Normalize", "type": "sentence_transformers.models.Normalize"},
    ]
    files = {
        "manifest.json": json.dumps({"model_id": "nexus/test"}) + "\n",
        "model.safetensors": "poids déterministes\n",
        "modules.json": json.dumps(modules) + "\n",
    }
    if include_pooling:
        (root / "1_Pooling").mkdir()
        files["1_Pooling/config.json"] = (
            json.dumps({"pooling_mode_mean_tokens": True}) + "\n"
        )
    for relative, content in files.items():
        (root / relative).write_text(content, encoding="utf-8")

    sealed = dict(files)
    if include_pooling and not seal_pooling:
        del sealed["1_Pooling/config.json"]
    inventory = "".join(
        f"{hashlib.sha256(content.encode()).hexdigest()}  {relative}\n"
        for relative, content in sorted(sealed.items())
    )
    (root / "SHA256SUMS").write_text(inventory, encoding="utf-8")
    return hashlib.sha256(inventory.encode()).hexdigest()


def test_verification_rejects_a_module_declared_but_absent(tmp_path: Path) -> None:
    """Un artefact amputé d'un module déclaré doit être refusé, pas accepté.

    `SHA256SUMS` scelle une liste de fichiers et garantit que chacun est intact.
    Il ne vérifie pas que cette liste couvre ce que `modules.json` déclare. Le
    27/08/2026, un artefact embedding sans `1_Pooling/` a été jugé **conforme**
    par l'attestation : chaque fichier scellé était intact, et l'artefact était
    incapable de se charger — `sentence_transformers` retombait sur un
    téléchargement distant qui échouait au démarrage du runtime.
    """
    root = tmp_path / "artefact"
    inventory_sha256 = _write_modular_artifact(root, include_pooling=False)

    with pytest.raises(model_artifact_module.ModelArtifactError) as failure:
        verify_model_artifact(
            root,
            expected_inventory_sha256=inventory_sha256,
            expected_manifest={"model_id": "nexus/test"},
            require_model_weights=True,
        )

    assert "MODEL_ARTIFACT_INCOMPLETE" in str(failure.value)
    assert "1_Pooling/config.json" in str(failure.value)


def test_verification_accepts_a_complete_modular_artifact(tmp_path: Path) -> None:
    """Aucun faux positif : un artefact complet reste accepté.

    `2_Normalize/` est absent ici comme dans les snapshots amont légitimes :
    `Normalize.load()` ne lit aucun fichier (vérifié au source de
    `sentence-transformers` 3.0.1) et doit rester exempté.
    """
    root = tmp_path / "artefact"
    inventory_sha256 = _write_modular_artifact(root, include_pooling=True)

    verified = verify_model_artifact(
        root,
        expected_inventory_sha256=inventory_sha256,
        expected_manifest={"model_id": "nexus/test"},
        require_model_weights=True,
    )

    assert verified == root.resolve()


def test_verification_rejects_a_module_present_but_unsealed(tmp_path: Path) -> None:
    """Présent sur le disque ne suffit pas : le module doit être scellé.

    Un fichier hors sceau peut être remplacé sans que l'empreinte d'inventaire
    bouge — c'est-à-dire exactement le trou que l'attestation existe pour
    fermer.
    """
    root = tmp_path / "artefact"
    inventory_sha256 = _write_modular_artifact(
        root, include_pooling=True, seal_pooling=False
    )

    with pytest.raises(model_artifact_module.ModelArtifactError) as failure:
        verify_model_artifact(
            root,
            expected_inventory_sha256=inventory_sha256,
            expected_manifest={"model_id": "nexus/test"},
            require_model_weights=True,
        )

    assert "MODEL_ARTIFACT" in str(failure.value)


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
    deadline = time.monotonic() + 2.0
    while True:
        weights.write_bytes(b"x" * before.st_size)
        os.utime(weights, ns=(before.st_atime_ns, before.st_mtime_ns))
        if weights.stat().st_ctime_ns != before.st_ctime_ns:
            break
        if time.monotonic() >= deadline:
            pytest.fail("filesystem ctime did not advance after a bounded mutation")
        time.sleep(0.01)

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
