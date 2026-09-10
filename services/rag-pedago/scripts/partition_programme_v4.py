#!/usr/bin/env python3
"""Partition de la population programme, prouvée par ÉGALITÉ D'ENSEMBLE.

Un compte qui tombe juste ne prouve rien : trois sous-ensembles peuvent
totaliser 2451 en se chevauchant et en manquant des éléments à la fois. La
preuve exigée ici est ensembliste — union exacte, intersections vides — et
chaque sous-ensemble est scellé par une empreinte rejouable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import psycopg

ZONE_PROGRAMME = "01_EDUSCOL_OFFICIEL"


def empreinte_ensemble(valeurs: set[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(valeurs)) + "\n").encode("utf-8")).hexdigest()


def main() -> int:
    parseur = argparse.ArgumentParser()
    parseur.add_argument("--liaisons", type=Path, required=True)
    parseur.add_argument("--resolution", type=Path, required=True)
    parseur.add_argument("--sortie", type=Path, required=True)
    parseur.add_argument("--dsn", default=os.environ.get("DRIVE_STAGING_DSN"))
    arguments = parseur.parse_args()

    with psycopg.connect(arguments.dsn) as connexion:
        population = {
            r[0] for r in connexion.execute(
                "select artifact_id from drive_staging.artifacts where zone = %s",
                (ZONE_PROGRAMME,)).fetchall()
        }

    liaisons = json.loads(arguments.liaisons.read_text(encoding="utf-8"))
    compatibles = {b["content_sha256"] for b in liaisons["bindings"]}

    resolution = json.loads(arguments.resolution.read_text(encoding="utf-8"))
    incompatibles = {
        sha for sha, verdict in resolution["artifact_verdicts"].items()
        if verdict == "INCOMPATIBLE"
    }

    # Un artefact hors population ne peut pas entrer dans sa partition : ce
    # serait compter une preuve sur un objet que le dénominateur ne contient
    # pas.
    hors_population = sorted((compatibles | incompatibles) - population)
    if hors_population:
        raise SystemExit(f"REFUS : hors population — {hors_population}")
    chevauchement = sorted(compatibles & incompatibles)
    if chevauchement:
        raise SystemExit(f"REFUS : à la fois compatible et incompatible — {chevauchement}")

    inconnus = population - compatibles - incompatibles
    union = compatibles | incompatibles | inconnus
    rapport = {
        "kind": "NEXUS-PROGRAM-PARTITION-V4",
        "supersedes": "NEXUS-PROGRAM-PARTITION-V3",
        "applied": False,
        "PROGRAM_POPULATION_TOTAL": len(population),
        "PROGRAM_POPULATION_SHA_SET_SHA256": empreinte_ensemble(population),
        "PROGRAM_COMPATIBILITY_PROVEN": len(compatibles),
        "PROGRAM_INCOMPATIBILITY_PROVEN": len(incompatibles),
        "PROGRAM_COMPATIBILITY_UNKNOWN": len(inconnus),
        "PROGRAM_COMPATIBLE_SHA_SET_SHA256": empreinte_ensemble(compatibles),
        "PROGRAM_INCOMPATIBLE_SHA_SET_SHA256": empreinte_ensemble(incompatibles),
        "PROGRAM_UNKNOWN_SHA_SET_SHA256": empreinte_ensemble(inconnus),
        "PROGRAM_PARTITION_UNION_COUNT": len(union),
        "PROGRAM_PARTITION_UNION_SHA256": empreinte_ensemble(union),
        "PROGRAM_PARTITION_INTERSECTION_COUNT": len(
            (compatibles & incompatibles) | (compatibles & inconnus) | (incompatibles & inconnus)),
        "PROGRAM_PARTITION_UNACCOUNTED": len(population - union),
        "PROGRAM_PARTITION_SET_EQUALITY": union == population,
        "incompatible_artifacts": sorted(incompatibles),
        "incompatibility_evidence": {
            sha: {
                "cited_reference": r["normalized_reference"],
                "scope_level": r["attributed_scope_level"],
                "matiere": r["matiere"],
                "authority_current_references": r["authority_current_references"],
                "authority_evidence_status": r["authority_evidence_status"],
                "attribution_basis": r["attribution_basis"],
            }
            for sha in sorted(incompatibles)
            for r in resolution["resolutions"] if r["content_sha256"] == sha
        },
    }
    if not rapport["PROGRAM_PARTITION_SET_EQUALITY"]:
        raise SystemExit("REFUS : l'union des trois parts n'est pas la population")

    arguments.sortie.write_text(
        json.dumps(rapport, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    for cle in ("PROGRAM_COMPATIBILITY_PROVEN", "PROGRAM_INCOMPATIBILITY_PROVEN",
                "PROGRAM_COMPATIBILITY_UNKNOWN", "PROGRAM_PARTITION_UNION_COUNT",
                "PROGRAM_PARTITION_INTERSECTION_COUNT", "PROGRAM_PARTITION_UNACCOUNTED",
                "PROGRAM_PARTITION_SET_EQUALITY"):
        print(f"{cle} = {rapport[cle]}")
    print(f"somme = {rapport['PROGRAM_COMPATIBILITY_PROVEN']}"
          f" + {rapport['PROGRAM_INCOMPATIBILITY_PROVEN']}"
          f" + {rapport['PROGRAM_COMPATIBILITY_UNKNOWN']}"
          f" = {sum((rapport['PROGRAM_COMPATIBILITY_PROVEN'], rapport['PROGRAM_INCOMPATIBILITY_PROVEN'], rapport['PROGRAM_COMPATIBILITY_UNKNOWN']))}")
    print(f"POPULATION_SHA = {rapport['PROGRAM_POPULATION_SHA_SET_SHA256']}")
    print(f"UNION_SHA      = {rapport['PROGRAM_PARTITION_UNION_SHA256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
