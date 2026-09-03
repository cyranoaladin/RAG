#!/usr/bin/env python3
"""Dérive la matrice de production en retirant les exclusions déclarées.

Pourquoi ce script existe plutôt qu'une édition à la main : la matrice employée
par une production doit être **dérivable**, et sa dérivation doit enregistrer ses
entrées. Le 2026-08-31 nous avons établi que le garde `FINAL_SET_SHA256` du
producteur se désarme dès que `NEXUS_FINAL_MATRIX` est fourni — c'est-à-dire
exactement dans le cas dérivé. Rien n'enregistre donc quelle matrice a servi.
Ce script écrit cet enregistrement lui-même, à côté de sa sortie.

    python appliquer_exclusions_production.py \
        --matrice   docs/reports/evidence-index/matrice_preuve_v2_20260829.json \
        --exclusions docs/reports/evidence-index/exclusions_production_20260831.json \
        --sortie    docs/reports/evidence-index/matrice_production_20260831.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def _sha256(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def _octets_canoniques(donnee: object) -> bytes:
    return (
        json.dumps(donnee, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def appliquer(matrice: list[dict], exclusions: dict) -> tuple[list[dict], list[dict]]:
    """Rend (matrice dérivée, journal des retraits effectifs).

    Une exclusion qui ne retire rien est une erreur : elle désigne un couple qui
    n'existe pas, donc l'exclusion ou la matrice est fausse. On lève.
    """
    retraits: list[dict] = []
    par_contenu = {e["content_sha256"]: e for e in exclusions["exclusions"]}
    derivee: list[dict] = []
    for partition in matrice:
        collection = partition["dimensions"]["collection"]["value"]
        gardes: list[str] = []
        for content_sha256 in partition["content_sha256"]:
            exclusion = par_contenu.get(content_sha256)
            if exclusion is not None and collection in exclusion["placements_retires"]:
                retraits.append(
                    {
                        "content_sha256": content_sha256,
                        "collection": collection,
                        "partition_id": partition["partition_id"],
                        "motif_code": exclusion["motif_code"],
                    }
                )
                continue
            gardes.append(content_sha256)
        copie = dict(partition)
        copie["content_sha256"] = gardes
        copie["content_count"] = len(gardes)
        derivee.append(copie)

    attendus = sum(len(e["placements_retires"]) for e in exclusions["exclusions"])
    if len(retraits) != attendus:
        raise ValueError(
            f"exclusions déclarées : {attendus} couples ; retirés : {len(retraits)}. "
            "Une exclusion qui ne retire rien désigne un couple inexistant."
        )
    return derivee, retraits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrice", required=True, type=Path)
    parser.add_argument("--exclusions", required=True, type=Path)
    parser.add_argument("--sortie", required=True, type=Path)
    args = parser.parse_args(argv)

    matrice = json.loads(args.matrice.read_text(encoding="utf-8"))
    exclusions = json.loads(args.exclusions.read_text(encoding="utf-8"))
    derivee, retraits = appliquer(matrice, exclusions)

    args.sortie.write_bytes(_octets_canoniques(derivee))

    # La sortie enregistre ses entrées. Le producteur ne le fera pas : son garde
    # se tait dès qu'une matrice lui est fournie.
    provenance = {
        "schema_version": "NEXUS-DERIVED-MATRIX-PROVENANCE-V1",
        "derive_le": datetime.now(UTC).isoformat(),
        "producteur": "services/rag-pedago/scripts/appliquer_exclusions_production.py",
        "entrees": {
            str(args.matrice): _sha256(args.matrice),
            str(args.exclusions): _sha256(args.exclusions),
        },
        "sortie": {str(args.sortie): _sha256(args.sortie)},
        "couples_avant": sum(len(p["content_sha256"]) for p in matrice),
        "couples_apres": sum(len(p["content_sha256"]) for p in derivee),
        "retraits": retraits,
    }
    chemin_provenance = args.sortie.with_suffix(".provenance.json")
    chemin_provenance.write_bytes(_octets_canoniques(provenance))

    print(f"matrice dérivée   : {args.sortie}  ({_sha256(args.sortie)})")
    print(f"provenance        : {chemin_provenance}")
    print(f"couples retirés   : {len(retraits)}")
    for r in retraits:
        print(f"   - {r['content_sha256'][:12]}…  {r['collection']}  [{r['motif_code']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
