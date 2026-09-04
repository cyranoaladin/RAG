"""Un instantané de modèle incomplet ne doit pas pouvoir être scellé (§4).

Le 27/08/2026, un artefact embedding a été scellé sans `1_Pooling/` : conforme
à son empreinte, et incapable de se charger — `sentence_transformers` lit
`modules.json`, n'y trouve pas le module de pooling en local, et retombe sur un
téléchargement distant qui échoue hors ligne. Le seul garde-fou existant
(« model inventory has no weights ») protégeait les poids, pas la structure.

La règle tenue ici est celle que `modules.json` énonce lui-même : chaque module
déclaré avec un chemin doit exister dans l'instantané — sauf les types de
modules qui, par construction, ne portent aucun fichier. `Normalize` est le
seul aujourd'hui ; un type inconnu et absent fait échouer, ce qui est le bon
sens d'un garde-fou.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

PRODUCER = Path(__file__).resolve().parents[1] / "scripts" / "build_production_profile_release.py"

MODULES = [
    {"idx": 0, "name": "0", "path": "", "type": "sentence_transformers.models.Transformer"},
    {"idx": 1, "name": "1", "path": "1_Pooling", "type": "sentence_transformers.models.Pooling"},
    {"idx": 2, "name": "2", "path": "2_Normalize", "type": "sentence_transformers.models.Normalize"},
]


def _module() -> Any:
    from conftest import load_producer

    return load_producer()


def _snapshot(tmp_path: Path, *, with_pooling: bool, modules: list[dict[str, Any]] | None = None) -> Path:
    root = tmp_path / "snapshot"
    root.mkdir()
    (root / "model.safetensors").write_bytes(b"poids-factices")
    (root / "config.json").write_text("{}", encoding="utf-8")
    (root / "modules.json").write_text(
        json.dumps(MODULES if modules is None else modules), encoding="utf-8"
    )
    if with_pooling:
        (root / "1_Pooling").mkdir()
        (root / "1_Pooling" / "config.json").write_text("{}", encoding="utf-8")
    return root


class TestSnapshotCompleteness:
    def test_a_complete_snapshot_is_sealed(self, tmp_path: Path) -> None:
        builder = _module()
        _manifest, inventory = builder._model_inventory(
            snapshot=_snapshot(tmp_path, with_pooling=True),
            manifest={"model_id": "test/model", "revision": "abc"},
        )
        assert b"1_Pooling/config.json" in inventory

    def test_a_snapshot_missing_a_declared_module_is_refused(self, tmp_path: Path) -> None:
        """L'artefact amputé du 27/08 : conforme à son empreinte, non chargeable."""
        builder = _module()
        with pytest.raises(ValueError, match="1_Pooling"):
            builder._model_inventory(
                snapshot=_snapshot(tmp_path, with_pooling=False),
                manifest={"model_id": "test/model", "revision": "abc"},
            )

    def test_a_parameterless_module_needs_no_directory(self, tmp_path: Path) -> None:
        """`2_Normalize` ne porte aucun fichier, même dans l'artefact complet.

        Exiger son répertoire refuserait l'instantané qui SERT aujourd'hui."""
        builder = _module()
        builder._model_inventory(
            snapshot=_snapshot(tmp_path, with_pooling=True),
            manifest={"model_id": "test/model", "revision": "abc"},
        )

    def test_an_unknown_module_type_that_is_absent_is_refused(self, tmp_path: Path) -> None:
        """Un garde-fou qui ne connaît pas un type échoue du côté fermé."""
        builder = _module()
        modules = [*MODULES, {"idx": 3, "name": "3", "path": "3_Dense",
                              "type": "sentence_transformers.models.Dense"}]
        with pytest.raises(ValueError, match="3_Dense"):
            builder._model_inventory(
                snapshot=_snapshot(tmp_path, with_pooling=True, modules=modules),
                manifest={"model_id": "test/model", "revision": "abc"},
            )

    def test_a_snapshot_without_modules_json_is_still_sealed(self, tmp_path: Path) -> None:
        """Le reranker n'est pas un sentence-transformer et n'en a pas."""
        builder = _module()
        root = tmp_path / "reranker"
        root.mkdir()
        (root / "model.safetensors").write_bytes(b"poids")
        (root / "config.json").write_text("{}", encoding="utf-8")
        builder._model_inventory(snapshot=root, manifest={"model_id": "x", "revision": "y"})


class TestTheRealSnapshotsAreJudgedCorrectly:
    """La mesure sur les instantanés réellement présents sur la machine."""

    ROOT = Path("/home/alaeddine/rag-model-artifacts")

    @pytest.mark.skipif(
        not (Path("/home/alaeddine/rag-model-artifacts")).is_dir(),
        reason="artefacts de modèle absents de cette machine",
    )
    def test_the_amputated_snapshot_is_refused_and_the_complete_one_accepted(self) -> None:
        builder = _module()
        complete = self.ROOT / "e5-large-prerentree-2026-2027-20260828-materialise"
        amputated = self.ROOT / "e5-large-prerentree-2026-2027"
        manifest = {"model_id": "intfloat/multilingual-e5-large", "revision": "3d7cfbda"}
        if amputated.is_dir():
            with pytest.raises(ValueError, match="1_Pooling"):
                builder._model_inventory(snapshot=amputated, manifest=manifest)
        if complete.is_dir():
            _m, inventory = builder._model_inventory(snapshot=complete, manifest=manifest)
            assert b"1_Pooling/config.json" in inventory
