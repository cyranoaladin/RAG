"""Contrat de l'outil de matérialisation d'artefact modèle runtime.

L'artefact runtime est une **matérialisation** de la release scellée, jamais une
source. Ces tests pincent la seule propriété qui compte : le répertoire produit
porte exactement l'empreinte d'inventaire scellée par la release, sans qu'aucun
ajustement soit nécessaire ni possible.

Contexte : deux producteurs écrivaient chacun leur `manifest.json` — dix clés
côté `prepare-embedding-model-artifact.sh`, trois côté release — d'où deux
empreintes irréconciliables pour les mêmes poids. Servir une release scellée avec
un artefact du premier est structurellement impossible (dette n°19).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL = REPO_ROOT / "scripts" / "e2e" / "materialize-release-model-artifact.py"


def _tool():
    spec = importlib.util.spec_from_file_location("materialize_tool", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release_and_snapshot(tmp_path: Path) -> tuple[Path, Path, str]:
    """Construire une release scellée minimale et son snapshot d'origine."""
    snapshot = tmp_path / "snapshot"
    (snapshot / "1_Pooling").mkdir(parents=True)
    (snapshot / "model.safetensors").write_bytes(b"poids")
    (snapshot / "modules.json").write_text(
        json.dumps(
            [
                {"idx": 0, "path": "", "type": "sentence_transformers.models.Transformer"},
                {"idx": 1, "path": "1_Pooling", "type": "sentence_transformers.models.Pooling"},
            ]
        ),
        encoding="utf-8",
    )
    (snapshot / "1_Pooling" / "config.json").write_text('{"m":true}', encoding="utf-8")

    # Le manifeste de la release : trois clés, sérialisation canonique.
    manifest = json.dumps(
        {"canonical_dim": 1024, "model_id": "nexus/test", "revision": "abc"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    release = tmp_path / "release-models"
    release.mkdir()
    (release / "manifest.json").write_bytes(manifest)

    rows = [f"{hashlib.sha256(manifest).hexdigest()}  manifest.json"]
    for relative in ("1_Pooling/config.json", "model.safetensors", "modules.json"):
        payload = (snapshot / relative).read_bytes()
        rows.append(f"{hashlib.sha256(payload).hexdigest()}  {relative}")
    inventory = ("\n".join(rows) + "\n").encode()
    (release / "SHA256SUMS").write_bytes(inventory)

    return release, snapshot, hashlib.sha256(inventory).hexdigest()


def test_materialized_artifact_carries_the_sealed_inventory(tmp_path: Path) -> None:
    """L'empreinte produite est celle de la release, sans ajustement."""
    release, snapshot, sealed = _release_and_snapshot(tmp_path)
    output = tmp_path / "artefact"

    produced = _tool().materialize(
        release_models_dir=release, snapshot=snapshot, output=output
    )

    assert produced == sealed
    assert (output / "SHA256SUMS").read_bytes() == (release / "SHA256SUMS").read_bytes()
    assert (output / "manifest.json").read_bytes() == (
        release / "manifest.json"
    ).read_bytes(), "le manifeste doit venir de la release, jamais du snapshot"
    assert (output / "1_Pooling" / "config.json").is_file()


def test_materialization_never_regenerates_the_seal(tmp_path: Path) -> None:
    """Un `manifest.json` présent dans le snapshot ne doit pas l'emporter.

    C'est exactement le point où les deux producteurs divergent : si l'outil
    recopiait le manifeste du snapshot — celui du script d'apprêtage, à dix
    clés — l'empreinte cesserait de correspondre à la release.
    """
    release, snapshot, sealed = _release_and_snapshot(tmp_path)
    (snapshot / "manifest.json").write_text(
        json.dumps({"revision_requested": "abc", "file_count": 3}), encoding="utf-8"
    )
    output = tmp_path / "artefact"

    produced = _tool().materialize(
        release_models_dir=release, snapshot=snapshot, output=output
    )

    assert produced == sealed
    assert json.loads((output / "manifest.json").read_text()) == {
        "canonical_dim": 1024,
        "model_id": "nexus/test",
        "revision": "abc",
    }


def test_materialization_refuses_a_snapshot_missing_a_sealed_file(
    tmp_path: Path,
) -> None:
    """Un snapshot amputé doit échouer, jamais produire un artefact partiel."""
    release, snapshot, _ = _release_and_snapshot(tmp_path)
    (snapshot / "1_Pooling" / "config.json").unlink()

    with pytest.raises(SystemExit) as failure:
        _tool().materialize(
            release_models_dir=release, snapshot=snapshot, output=tmp_path / "artefact"
        )

    assert "MATERIALIZE_SNAPSHOT_INCOMPLETE" in str(failure.value)
    assert "1_Pooling/config.json" in str(failure.value)


def test_materialization_refuses_content_drift(tmp_path: Path) -> None:
    """Un poids divergent doit être détecté, pas recopié en silence."""
    release, snapshot, _ = _release_and_snapshot(tmp_path)
    (snapshot / "model.safetensors").write_bytes(b"autres poids")

    with pytest.raises(SystemExit) as failure:
        _tool().materialize(
            release_models_dir=release, snapshot=snapshot, output=tmp_path / "artefact"
        )

    assert "MATERIALIZE_CONTENT_MISMATCH" in str(failure.value)


def test_materialization_never_overwrites_an_existing_artifact(
    tmp_path: Path,
) -> None:
    """Écraser un artefact rendrait le retour arrière impossible."""
    release, snapshot, _ = _release_and_snapshot(tmp_path)
    output = tmp_path / "artefact"
    output.mkdir()

    with pytest.raises(SystemExit) as failure:
        _tool().materialize(
            release_models_dir=release, snapshot=snapshot, output=output
        )

    assert "MATERIALIZE_OUTPUT_EXISTS" in str(failure.value)


def test_materialization_refuses_a_path_escaping_the_artifact(tmp_path: Path) -> None:
    """Un chemin d'inventaire hors du répertoire est refusé.

    L'inventaire est une donnée : un `../` y suffirait à écrire hors de la cible.
    """
    release, snapshot, _ = _release_and_snapshot(tmp_path)
    (release / "SHA256SUMS").write_bytes(b"%s  ../evasion\n" % (b"0" * 64))

    with pytest.raises(SystemExit) as failure:
        _tool().materialize(
            release_models_dir=release, snapshot=snapshot, output=tmp_path / "artefact"
        )

    assert "MATERIALIZE_INVENTORY_UNSAFE_PATH" in str(failure.value)
