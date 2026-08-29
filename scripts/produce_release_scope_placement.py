#!/usr/bin/env python3
"""Produire le placement de scope de release et sa provenance.

═══ POURQUOI CE CLI EXISTE ══════════════════════════════════════════════════

`nexus_contracts.produce_release_scope_placement_from_git` produit une projection
reproductible depuis un arbre Git nommé. Jusqu'au 28/08/2026, sa **seule**
invocation du dépôt vivait dans
`services/rag-pedago/tests/test_production_release_scope_placement.py` : le
document `docs/reports/release_scope_placement_20260825.jsonl` et sa provenance
existaient, sans qu'aucune procédure ne dise comment les régénérer.

Cette lacune s'est manifestée lors du rescellement de la release production : le
test de dérive `test_current_head_has_no_drift_in_any_producer_input_blob` a
correctement signalé qu'une entrée de producteur avait changé
(`release-registry.json`), et rien ne permettait de réémettre le document.

═══ ENVELOPPE MINCE — CONTRAINTE DE CONCEPTION ══════════════════════════════

Ce CLI **n'est pas un second producteur**. Il appelle
`produce_release_scope_placement_from_git` et sérialise son résultat ; il
n'ordonne rien, ne reformate rien, n'ajoute aucune clé de son cru.

Cette contrainte n'est pas cosmétique. Deux producteurs du même artefact qui
divergent d'un détail de sérialisation produisent deux empreintes
irréconciliables — c'est exactement le défaut qui a rendu inutilisable
l'artefact embedding du 27/08 (dette n°19), et ce serait le reproduire une
couche plus haut.

Le test `test_cli_output_is_byte_identical_to_the_committed_documents` le prouve
au sens fort : rejoué sur l'arbre enregistré, ce CLI reproduit **octet pour
octet** les documents déjà versionnés.

Les trois champs que la provenance porte en plus de la dataclass — `producer`,
`source_commit_sha`, `release_scope_placement_digest` — sont assemblés ici parce
que le format du fichier les contient. Leur valeur est intégralement dérivée du
résultat du producteur ou de Git : aucune n'est inventée.

═══ SÉQUENCEMENT — PIÈGE À CONNAÎTRE ════════════════════════════════════════

La provenance atteste « projeté depuis cet état du dépôt ». **Elle doit être
produite en dernier**, après que tout le reste du lot est figé : la produire puis
modifier un autre fichier d'entrée la périme à la naissance. Après toute édition
tardive, rejouer `test_current_head_has_no_drift_in_any_producer_input_blob`.

Cf. `docs/runbooks/release_reseal.md` §4ter.

═══ USAGE ═══════════════════════════════════════════════════════════════════

    python3 scripts/produce_release_scope_placement.py            # arbre courant
    python3 scripts/produce_release_scope_placement.py --check    # sans écrire
    python3 scripts/produce_release_scope_placement.py --source-tree-sha <sha>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "packages/contracts/src"))

from nexus_contracts import (  # noqa: E402
    produce_release_scope_placement_from_git,
)

PLACEMENT_PATH = REPOSITORY_ROOT / "docs/reports/release_scope_placement_20260825.jsonl"
PROVENANCE_PATH = (
    REPOSITORY_ROOT / "docs/reports/release_scope_placement_provenance_20260825.json"
)

#: Entrées du producteur. Ces chemins sont ceux de l'appel historique : les
#: modifier changerait la projection, donc l'identité du document.
PRODUCER_INPUTS = {
    "profile_proposal_matrix_path": (
        "docs/reports/final_production_profile_matrix_20260825.json"
    ),
    "accepted_placements_path": (
        "docs/reports/production_profile_accepted_placements_20260825.json"
    ),
    "release_registry_path": (
        "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json"
    ),
    "expected_contents_path": "docs/reports/final_production_eligible_set_20260825.txt",
    "verified_profiles_path": "docs/reports/verified_production_profiles_20260825.json",
    "profile_manifest_path": "services/rag-engine/configs/ingestion_manifest.yml",
}

PRODUCER_NAME = "nexus_contracts.produce_release_scope_placement_from_git"


def _git(*args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def render(*, source_commit_sha: str) -> tuple[bytes, bytes]:
    """Rendre les deux documents, sans rien écrire.

    Retourne `(placement, provenance)` sous leur forme sérialisée exacte.
    """
    source_tree_sha = _git("rev-parse", f"{source_commit_sha}^{{tree}}")
    produced = produce_release_scope_placement_from_git(
        repository_root=REPOSITORY_ROOT,
        source_tree_sha=source_tree_sha,
        **PRODUCER_INPUTS,
    )

    placement_bytes = produced.placement.canonical_bytes()
    provenance = {
        "producer": PRODUCER_NAME,
        "source_commit_sha": source_commit_sha,
        "source_tree_sha": produced.provenance.source_tree_sha,
        "release_scope_placement_digest": produced.placement.digest(),
        "input_blob_sha256": dict(produced.provenance.input_blob_sha256),
        "input_git_entries": dict(produced.provenance.input_git_entries),
    }
    provenance_bytes = (
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    return placement_bytes, provenance_bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-commit-sha",
        default=None,
        help="Commit dont l'arbre fait foi. Défaut : HEAD.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Comparer aux documents versionnés sans écrire.",
    )
    args = parser.parse_args(argv)

    source_commit_sha = args.source_commit_sha or _git("rev-parse", "HEAD")
    placement_bytes, provenance_bytes = render(source_commit_sha=source_commit_sha)

    if args.check:
        drift = [
            path.relative_to(REPOSITORY_ROOT).as_posix()
            for path, rendered in (
                (PLACEMENT_PATH, placement_bytes),
                (PROVENANCE_PATH, provenance_bytes),
            )
            if not path.is_file() or path.read_bytes() != rendered
        ]
        for relative in drift:
            print(f"DRIFT {relative}")
        print(f"RELEASE_SCOPE_PLACEMENT_DRIFT={len(drift)}")
        return 1 if drift else 0

    PLACEMENT_PATH.write_bytes(placement_bytes)
    PROVENANCE_PATH.write_bytes(provenance_bytes)
    print(f"RELEASE_SCOPE_PLACEMENT_SOURCE_COMMIT={source_commit_sha}")
    print(
        "RELEASE_SCOPE_PLACEMENT_DIGEST="
        f"{hashlib.sha256(placement_bytes).hexdigest()}"
    )
    print(f"RELEASE_SCOPE_PLACEMENT_PATH={PLACEMENT_PATH}")
    print(f"RELEASE_SCOPE_PLACEMENT_PROVENANCE_PATH={PROVENANCE_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
