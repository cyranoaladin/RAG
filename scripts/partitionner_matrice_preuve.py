#!/usr/bin/env python3
"""Partitionner la matrice de preuve depuis les placements résolus.

Une partition par collection. Chaque dimension déclare sa `source_of_truth` :
le profil pour les dimensions de scope, le bandeau éditeur pour le niveau quand
il l'a établi, le placement résolu sinon. Rien n'est affirmé sans dire d'où
cela vient.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--placements", type=Path, required=True)
    parser.add_argument("--profils", type=Path, required=True)
    parser.add_argument("--sortie", type=Path, required=True)
    args = parser.parse_args(argv)

    profils = {}
    for chemin in sorted(args.profils.glob("*.yml")):
        donnees = yaml.safe_load(chemin.read_text(encoding="utf-8"))
        profils[donnees["scope"]["collection"]] = (donnees, chemin)

    placements = json.loads(args.placements.read_text(encoding="utf-8"))
    import re
    import unicodedata

    def slug(valeur: str) -> str:
        plat = unicodedata.normalize("NFKD", valeur).encode("ascii", "ignore").decode()
        return re.sub(r"[^a-z0-9]+", "_", plat.lower()).strip("_")

    par_collection: dict[str, list[dict]] = defaultdict(list)
    for placement in placements:
        if placement["statut"] != "PLACE":
            continue
        for niveau in placement["niveaux"]:
            for matiere in placement.get("matieres", []):
                for collection, (donnees, _) in profils.items():
                    scope = donnees["scope"]
                    if scope["niveau"] == niveau and scope["matiere"] == slug(matiere):
                        par_collection[collection].append(placement)
                        break

    matrice = []
    for index, (collection, contenus) in enumerate(sorted(par_collection.items()), 1):
        donnees, chemin = profils[collection]
        scope = donnees["scope"]
        origine = str(chemin.relative_to(Path.cwd())) if chemin.is_absolute() else str(chemin)
        autorites = {p.get("autorite") for p in contenus}
        matrice.append({
            "partition_id": f"C{index:03d}",
            "partition_kind": "EDUSCOL_CORPUS_PLACEMENT_V2",
            "content_count": str(len({p["sha256"] for p in contenus})),
            "content_sha256": sorted({p["sha256"] for p in contenus}),
            "profile_decision_required": "False",
            "evidence_sources": sorted(autorites),
            "observed_matiere_evidence": [scope["matiere"].upper()],
            "observed_niveau_evidence": [scope["niveau"]],
            "dimensions": {
                dimension: {"grounded": True, "source_of_truth": origine,
                            "value": scope[dimension]}
                for dimension in ("collection", "tenant", "niveau", "voie", "matiere",
                                  "candidat", "audience", "visibility", "school_year",
                                  "programme_version")
            },
        })

    args.sortie.write_text(json.dumps(matrice, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    total = len({s for m in matrice for s in m["content_sha256"]})
    print(f"  partitions écrites : {len(matrice)}")
    print(f"  documents couverts : {total}")
    print(f"  placements sans collection correspondante : "
          f"{len({p['sha256'] for p in placements if p['statut'] == 'PLACE'}) - total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
