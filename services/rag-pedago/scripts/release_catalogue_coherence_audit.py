#!/usr/bin/env python3
"""Réconcilier le registre de release et le catalogue de collections (P0-L1A).

Depuis que `validate_configured_release_database()` conditionne le démarrage du
moteur, ces deux sources ne peuvent plus diverger sans conséquence :

* le registre impose au moteur, avant tout trafic, de trouver en base les
  artefacts, placements et chunks de **chaque** collection qu'il nomme ;
* le catalogue décide, par `instanciee`, quelles collections peuvent être
  servies — `resolve_collection_v2` refuse fail-closed toutes les autres.

Une collection nommée par le registre mais non instanciée est donc
auto-contradictoire : sa publication est exigée pour démarrer, et son
interrogation est refusée ensuite. Ce n'est pas une dette cosmétique, c'est du
travail d'ingestion gouvernée dont le résultat ne sera jamais interrogeable.

Usage :
    release_catalogue_coherence_audit.py [--json SORTIE] [--check]

`--check` sort en code 1 dès qu'une collection est incohérente : c'est la forme
utilisable comme garde-fou.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CATALOGUE = REPOSITORY_ROOT / "services/rag-engine/configs/rag_collections.yml"
PROFILES = REPOSITORY_ROOT / "services/rag-engine/configs/ingestion_profiles"
RELEASES = REPOSITORY_ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027"

VERDICT_COHERENT = "COHERENT"
VERDICT_INCOHERENT = "P0_RELEASE_NAMES_A_NON_INSTANCIATED_COLLECTION"
VERDICT_NO_PROFILE = "P0_RELEASE_NAMES_A_COLLECTION_WITHOUT_ENABLED_PROFILE"
VERDICT_ABSENT = "P0_RELEASE_NAMES_A_COLLECTION_ABSENT_FROM_THE_CATALOGUE"


@dataclass(frozen=True)
class CollectionCoherence:
    collection: str
    in_catalogue: bool
    instanciee: bool | None
    in_release_registry: bool
    expected_artifacts: int
    expected_placements: int
    expected_chunks: int
    ingestion_profile: str | None
    ingestible_by_current_policy: bool
    verdict: str


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _production_profiles() -> dict[str, list[tuple[str, bool]]]:
    """Profils production uniquement : `staging/` est explicitement hors release."""
    profiles: dict[str, list[tuple[str, bool]]] = {}
    for path in sorted(PROFILES.glob("*.yml")):
        document = _load_yaml(path) or {}
        collection = (document.get("scope") or {}).get("collection")
        if collection:
            profiles.setdefault(str(collection), []).append(
                (path.name, bool(document.get("enabled")))
            )
    return profiles


def audit() -> tuple[list[CollectionCoherence], dict[str, Any]]:
    catalogue = _load_yaml(CATALOGUE)["collections"]
    registry = json.loads((RELEASES / "release-registry.json").read_text("utf-8"))
    release = registry["releases"][0]
    manifest = json.loads((RELEASES / release["manifest_path"]).read_text("utf-8"))
    profiles = _production_profiles()

    rows: list[CollectionCoherence] = []
    for subject in manifest["subjects"]:
        collection = subject["collection"]
        counts = json.loads(
            (RELEASES / "profile_gate" / subject["path"]).read_text("utf-8")
        )["expected_counts"]
        entry = catalogue.get(collection)
        instanciee = None if entry is None else entry.get("instanciee")
        candidates = profiles.get(collection, [])
        enabled = len(candidates) == 1 and candidates[0][1]

        if entry is None:
            verdict = VERDICT_ABSENT
        elif instanciee is not True:
            verdict = VERDICT_INCOHERENT
        elif not enabled:
            verdict = VERDICT_NO_PROFILE
        else:
            verdict = VERDICT_COHERENT

        rows.append(
            CollectionCoherence(
                collection=collection,
                in_catalogue=entry is not None,
                instanciee=instanciee,
                in_release_registry=collection in release["collections"],
                expected_artifacts=counts["artifacts"],
                expected_placements=counts["placements"],
                expected_chunks=counts["chunks"],
                ingestion_profile=candidates[0][0] if candidates else None,
                ingestible_by_current_policy=verdict == VERDICT_COHERENT,
                verdict=verdict,
            )
        )

    rows.sort(key=lambda row: row.collection)
    incoherent = [row for row in rows if row.verdict != VERDICT_COHERENT]
    summary = {
        "release_id": release["release_id"],
        "school_year": registry["school_year"],
        "registry_collections": len(release["collections"]),
        "manifest_subjects": len(manifest["subjects"]),
        "manifest_expected_counts": manifest["expected_counts"],
        "coherent_collections": len(rows) - len(incoherent),
        "incoherent_collections": len(incoherent),
        "incoherent_collection_ids": [row.collection for row in incoherent],
        "declared_totals": {
            "artifacts": sum(row.expected_artifacts for row in rows),
            "placements": sum(row.expected_placements for row in rows),
            "chunks": sum(row.expected_chunks for row in rows),
        },
        "coherent_totals": {
            "artifacts": sum(
                row.expected_artifacts for row in rows if row not in incoherent
            ),
            "placements": sum(
                row.expected_placements for row in rows if row not in incoherent
            ),
            "chunks": sum(row.expected_chunks for row in rows if row not in incoherent),
        },
        "unservable_work_if_kept": {
            "artifacts": sum(row.expected_artifacts for row in incoherent),
            "placements": sum(row.expected_placements for row in incoherent),
            "chunks": sum(row.expected_chunks for row in incoherent),
        },
    }
    return rows, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="écrire la preuve machine ici")
    parser.add_argument(
        "--check",
        action="store_true",
        help="sortir en 1 si une collection de release est incohérente",
    )
    arguments = parser.parse_args(argv)

    rows, summary = audit()

    widths = (44, 8, 11, 8, 5, 5, 6, 48, 12)
    header = (
        "collection",
        "in_cat",
        "instanciee",
        "in_reg",
        "art",
        "plc",
        "chk",
        "ingestion_profile",
        "ingestible",
    )
    print("".join(str(cell).ljust(width) for cell, width in zip(header, widths, strict=True)))
    print("-" * sum(widths))
    for row in rows:
        cells = (
            row.collection,
            "yes" if row.in_catalogue else "NO",
            str(row.instanciee),
            "yes" if row.in_release_registry else "NO",
            row.expected_artifacts,
            row.expected_placements,
            row.expected_chunks,
            row.ingestion_profile or "ABSENT",
            "yes" if row.ingestible_by_current_policy else "no",
        )
        print("".join(str(cell).ljust(width) for cell, width in zip(cells, widths, strict=True)))
        if row.verdict != VERDICT_COHERENT:
            print(f"{'':44s}^-- {row.verdict}")

    print()
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))

    if arguments.json:
        arguments.json.write_text(
            json.dumps(
                {
                    "protocol_version": "NEXUS-RELEASE-CATALOGUE-COHERENCE-V1",
                    "collections": [asdict(row) for row in rows],
                    "summary": summary,
                },
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    if arguments.check and summary["incoherent_collections"]:
        print(
            f"\nRELEASE_CATALOGUE_COHERENCE=FAIL "
            f"({summary['incoherent_collections']} collections)",
            file=sys.stderr,
        )
        return 1
    print("\nRELEASE_CATALOGUE_COHERENCE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
