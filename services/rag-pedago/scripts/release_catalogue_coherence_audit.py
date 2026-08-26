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
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CATALOGUE = REPOSITORY_ROOT / "services/rag-engine/configs/rag_collections.yml"
PROFILES = REPOSITORY_ROOT / "services/rag-engine/configs/ingestion_profiles"
RELEASES = REPOSITORY_ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027"
GO_LIVE_SCOPE = REPOSITORY_ROOT / "services/rag-pedago/configs/go_live_scope.yml"
ADR_ACTIVATION_SOURCES = (
    "docs/adr/ADR-0039-activation-wave0-apres-release-readiness.md",
    "docs/adr/ADR-0041-activation-multi-niveaux-apres-readiness.md",
    "docs/adr/ADR-0040-extension-multi-niveaux-prioritaire.md",
    "services/rag-engine/configs/h2_initial_placement_policy.yml",
)
SCOPE_CLASSES = (
    "pilot_vertical",
    "complete_coverage_target",
    "out_of_v1",
    "architecture_target",
    "infrastructure",
)

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


# ═══════════════════════════════════════════════════════════════════════
# Algèbre des ensembles et matrice de périmètre GO-LIVE
# ═══════════════════════════════════════════════════════════════════════


def _catalogue() -> dict[str, Any]:
    return _load_yaml(CATALOGUE)["collections"]


def _current_release() -> dict[str, Any]:
    registry = json.loads((RELEASES / "release-registry.json").read_text("utf-8"))
    return registry["releases"][0]


def activation_authorized() -> dict[str, list[str]]:
    """Collections nommées par une autorité d'activation versionnée.

    Instancier une collection sans qu'aucune ADR ne la nomme reste possible —
    c'est le cas des deux collections NSI, antérieures au régime
    ADR-0039/ADR-0041 — mais cela doit être visible, pas implicite.
    """
    named: dict[str, list[str]] = {}
    for relative in ADR_ACTIVATION_SOURCES:
        text = (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
        for collection in sorted(set(re.findall(r"rag_nexus_[a-z0-9_]+", text))):
            named.setdefault(collection, []).append(Path(relative).name)
    return named


def collection_sets() -> dict[str, Any]:
    """Les cinq ensembles canoniques et leurs différences, calculés — jamais cités."""
    catalogue = _catalogue()
    release = _current_release()

    catalogue_ids = set(catalogue)
    quarantine = {
        name for name, entry in catalogue.items() if entry.get("domain") == "quarantine"
    }
    instanciee_raw = {
        name for name, entry in catalogue.items() if entry.get("instanciee") is True
    }
    # `rag_nexus_quarantine` est instanciée mais non retrievable par design :
    # la compter comme servable fausserait chaque différence ci-dessous.
    instanciee = instanciee_raw - quarantine
    current_release = set(release["collections"])
    authorized = set(activation_authorized())

    return {
        "CATALOGUE": sorted(catalogue_ids),
        "INSTANCIEE_RAW": sorted(instanciee_raw),
        "INSTANCIEE": sorted(instanciee),
        "QUARANTINE": sorted(quarantine),
        "ACTIVATION_AUTHORIZED": sorted(authorized),
        "CURRENT_RELEASE": sorted(current_release),
        "FIRST_RELEASE_CANDIDATE": sorted(current_release & instanciee),
        "CURRENT_RELEASE_INTERSECT_INSTANCIEE": sorted(current_release & instanciee),
        "CURRENT_RELEASE_MINUS_INSTANCIEE": sorted(current_release - instanciee),
        "INSTANCIEE_MINUS_CURRENT_RELEASE": sorted(instanciee - current_release),
        "INSTANCIEE_WITHOUT_NAMED_AUTHORITY": sorted(instanciee - authorized),
        "AUTHORIZED_NOT_INSTANCIEE": sorted(authorized - instanciee),
    }


def go_live_scope_matrix() -> list[dict[str, Any]]:
    """Une ligne par collection du catalogue, classée par une source nommée."""
    declaration = _load_yaml(GO_LIVE_SCOPE)
    catalogue = _catalogue()
    release = set(_current_release()["collections"])
    authorized = activation_authorized()
    instanciee = {
        name for name, entry in catalogue.items() if entry.get("instanciee") is True
    }

    scope_of: dict[str, str] = {}
    for scope_class in SCOPE_CLASSES:
        block = declaration[scope_class]
        for collection in block["collections"]:
            if collection in scope_of:
                raise ValueError(
                    f"{collection} is classified twice: {scope_of[collection]} "
                    f"and {scope_class}"
                )
            scope_of[collection] = scope_class

    unclassified = set(catalogue) - set(scope_of)
    if unclassified:
        raise ValueError(f"unclassified catalogue collections: {sorted(unclassified)}")
    unknown = set(scope_of) - set(catalogue)
    if unknown:
        raise ValueError(f"scope names collections absent from catalogue: {sorted(unknown)}")

    first_release = release & instanciee
    rows: list[dict[str, Any]] = []
    for collection in sorted(catalogue):
        scope_class = scope_of[collection]
        rows.append(
            {
                "collection": collection,
                "exists_in_catalogue": True,
                "product_scope": scope_class,
                "activation_authorized": authorized.get(collection, []),
                "instanciee": catalogue[collection].get("instanciee") is True,
                "first_release_required": collection in first_release,
                "final_go_live_required": scope_class == "pilot_vertical",
                "governing_source": declaration[scope_class]["source"],
                "reason": declaration["sources"][declaration[scope_class]["source"]].strip(),
            }
        )
    return rows


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

    sets = collection_sets()
    matrix = go_live_scope_matrix()
    print()
    print("SET_ALGEBRA")
    for name in (
        "CATALOGUE",
        "INSTANCIEE",
        "ACTIVATION_AUTHORIZED",
        "CURRENT_RELEASE",
        "FIRST_RELEASE_CANDIDATE",
        "CURRENT_RELEASE_INTERSECT_INSTANCIEE",
        "CURRENT_RELEASE_MINUS_INSTANCIEE",
        "INSTANCIEE_MINUS_CURRENT_RELEASE",
        "INSTANCIEE_WITHOUT_NAMED_AUTHORITY",
    ):
        print(f"  {name:38s} = {len(sets[name])}")
    required = [row["collection"] for row in matrix if row["final_go_live_required"]]
    print(f"  {'FINAL_GO_LIVE_REQUIRED':38s} = {len(required)} {required}")

    if arguments.json:
        arguments.json.write_text(
            json.dumps(
                {
                    "protocol_version": "NEXUS-RELEASE-CATALOGUE-COHERENCE-V1",
                    "collections": [asdict(row) for row in rows],
                    "summary": summary,
                    "sets": sets,
                    "go_live_scope_matrix": matrix,
                },
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    # Le verdict ne dépend jamais de `--check` : un rapport qui afficherait
    # `PASS` sous une table de sept incohérences serait pire que muet.
    # `--check` ne décide que du code de sortie.
    if summary["incoherent_collections"]:
        print(
            f"\nRELEASE_CATALOGUE_COHERENCE=FAIL "
            f"({summary['incoherent_collections']} collections)",
            file=sys.stderr,
        )
        return 1 if arguments.check else 0
    print("\nRELEASE_CATALOGUE_COHERENCE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
