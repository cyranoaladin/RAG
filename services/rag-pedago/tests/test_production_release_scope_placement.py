"""Projection production produite depuis un tree Git exact et toujours courante."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from typing import Any
import subprocess
from pathlib import Path

from nexus_contracts import (
    parse_release_scope_placement,
    produce_release_scope_placement_from_git,
)

ROOT = Path(__file__).resolve().parents[3]
PLACEMENT_PATH = ROOT / "docs/reports/release_scope_placement_20260825.jsonl"
PROVENANCE_PATH = (
    ROOT / "docs/reports/release_scope_placement_provenance_20260825.json"
)
EXPECTED_DIGEST = "b1a36aef251d05f0098bfe88d7eae45b36333452f1613741e15dc6a89de75315"
EXPECTED_SET_DIGEST = "fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0"
EXPECTED_PROFILE_MANIFEST = (
    "57d532ca0c80f0e70218e74902f1d47a4ca9f21d7e6bafa209f6f89426125b6c"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


#: Le CLI est le chemin unique de production. Les chemins d'entrée vivent dans
#: `PRODUCER_INPUTS` : les redéclarer ici créerait une seconde source de vérité,
#: et deux appels qui divergent d'une entrée produisent deux documents
#: différents sans que rien ne le signale.
def _cli() -> Any:
    spec = importlib.util.spec_from_file_location(
        "produce_release_scope_placement",
        ROOT / "scripts" / "produce_release_scope_placement.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _produce_from_provenance() -> tuple[object, dict[str, object]]:
    """Reproduire la projection par le CLI, jamais par un appel parallèle.

    Un producteur, un chemin. Le CLI n'est qu'une enveloppe autour de
    `produce_release_scope_placement_from_git` ; passer par lui garantit que ce
    que les tests éprouvent est exactement ce qu'un opérateur exécutera.
    """
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    produced = produce_release_scope_placement_from_git(
        repository_root=ROOT,
        source_tree_sha=provenance["source_tree_sha"],
        **_cli().PRODUCER_INPUTS,
    )
    return produced, provenance


def test_cli_output_is_byte_identical_to_the_committed_documents() -> None:
    """Le CLI ne doit pas être un second producteur.

    Deux producteurs du même artefact qui divergent d'un détail de sérialisation
    produisent deux empreintes irréconciliables — c'est le défaut qui a rendu
    inutilisable l'artefact embedding du 27/08/2026 (dette n°19). Rejoué sur
    l'arbre enregistré, le CLI doit reproduire les documents versionnés **octet
    pour octet** : c'est ce qui établit qu'il n'ajoute ni ordre, ni format, ni
    clé de son cru.
    """
    cli = _cli()
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))

    placement_bytes, provenance_bytes = cli.render(
        source_commit_sha=str(provenance["source_commit_sha"])
    )

    assert placement_bytes == PLACEMENT_PATH.read_bytes()
    assert provenance_bytes == PROVENANCE_PATH.read_bytes()


def test_production_release_scope_placement_is_exactly_26_of_26() -> None:
    placement = parse_release_scope_placement(PLACEMENT_PATH.read_bytes())
    contents = [row.content_sha256 for row in placement.placements]

    assert len(contents) == len(set(contents)) == 26
    assert hashlib.sha256(("\n".join(sorted(contents)) + "\n").encode()).hexdigest() == (
        EXPECTED_SET_DIGEST
    )
    assert placement.profile_manifest_digest == EXPECTED_PROFILE_MANIFEST
    assert placement.digest() == EXPECTED_DIGEST == _sha256(PLACEMENT_PATH)
    assert len({row.profile_id for row in placement.placements}) == 18


def test_production_projection_replays_from_its_exact_source_tree() -> None:
    produced, provenance = _produce_from_provenance()
    source_commit = str(provenance["source_commit_sha"])
    observed_tree = subprocess.run(
        ["git", "rev-parse", f"{source_commit}^{{tree}}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert observed_tree == provenance["source_tree_sha"]
    assert produced.placement.canonical_bytes() == PLACEMENT_PATH.read_bytes()
    assert produced.placement.digest() == provenance["release_scope_placement_digest"]
    assert dict(produced.provenance.input_blob_sha256) == provenance[
        "input_blob_sha256"
    ]
    assert dict(produced.provenance.input_git_entries) == provenance[
        "input_git_entries"
    ]


def test_current_head_has_no_drift_in_any_producer_input_blob() -> None:
    _produced, provenance = _produce_from_provenance()
    for relative, expected_sha256 in provenance["input_blob_sha256"].items():
        assert _sha256(ROOT / relative) == expected_sha256
