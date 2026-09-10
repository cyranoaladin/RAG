"""Construit NEXUS-SERVABILITY-MATRIX-V1 : une ligne par relation d'artefact.

La matrice ne décide rien. Elle croise les dimensions déjà mesurées et rend un
verdict par cascade, de sorte qu'une seule dimension bloquante suffise à
refuser. Elle est émise `applied=false`.

Les chemins sont dérivés de l'emplacement de ce fichier ; `NEXUS_REPO_ROOT`
permet de les surcharger.
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import pathlib
import sys

REPO_ROOT = pathlib.Path(
    os.environ.get("NEXUS_REPO_ROOT", pathlib.Path(__file__).resolve().parents[3])
)

RELATIONS = "docs/reports/handoff/url_provenance_reconciliation.json"
PARTITION = "docs/reports/handoff/program_partition_v4.json"
BINDINGS = "docs/reports/handoff/artifact_program_bindings.json"
PII_INDEX = "docs/reports/evidence-index/pii_review_index_v2_20260907.json"
NON_PDF = "docs/reports/evidence-index/non_pdf_disposition_consolidation_20260907.json"
OUTPUT = "docs/reports/handoff/servability_matrix_v1.json"


def _load(relative: str) -> dict:
    path = REPO_ROOT / relative
    if not path.is_file():
        raise SystemExit(
            f"entrée absente : {relative}. La matrice exige que toutes ses "
            "entrées soient versionnées ; elle ne les reconstruit pas."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _programme(sha: str, relation: dict, compatibles: set, incompatibles: set) -> str:
    # La partition ne mesure que les contenus appariés au catalogue. Une
    # relation sans appariement est HORS de cette population : la déclarer
    # « inconnue » gonflerait l'inconnu et casserait la réconciliation.
    if not relation["catalogue_match"]:
        return "OUTSIDE_PROGRAM_POPULATION"
    if sha in incompatibles:
        return "INCOMPATIBLE_PROVEN"
    if sha in compatibles:
        return "COMPATIBLE_PROVEN"
    return "UNKNOWN"


def _actualite(relation: dict) -> str:
    statuses = set(relation.get("catalogue_statuses") or ())
    if not statuses:
        return "NO_CATALOGUE_STATUS"
    if statuses == {"actuel"}:
        return "CURRENT_DECLARED"
    if "archive" in statuses:
        return "ARCHIVE_DECLARED"
    if statuses & {"transition-ou-actuel", "transition"}:
        return "TRANSITION_OR_CURRENT"
    if statuses == {"a-verifier"}:
        return "NEEDS_SECONDARY_EVIDENCE"
    return "MIXED:" + "|".join(sorted(statuses))


def _verdict(row: dict) -> str:
    if row["program"] == "INCOMPATIBLE_PROVEN":
        return "REFUSED_PROGRAM_INCOMPATIBLE"
    if row["pii"] == "PII_UNDECIDED":
        return "BLOCKED_PII_HUMAN_REVIEW"
    if row["indexability"] == "NON_INDEXABLE":
        return "NOT_INDEXABLE_BY_ROLE"
    if row["provenance"] == "NO_URL_EVIDENCE":
        return "BLOCKED_NO_URL_PROVENANCE"
    return "CANDIDATE_NO_BLOCKING_DIMENSION"


def build() -> dict:
    relations = _load(RELATIONS)["relations"]
    partition = _load(PARTITION)
    bindings = _load(BINDINGS)["bindings"]
    pii_bundles = _load(PII_INDEX)["bundles"]
    non_pdf = _load(NON_PDF)

    compatibles = {
        b["content_sha256"]
        for b in bindings
        if b.get("compatibility_verdict") == "COMPATIBLE"
    }
    incompatibles = set(partition["incompatible_artifacts"])
    pii_detected = {b["content_sha256"] for b in pii_bundles}

    rows = []
    for relation in relations:
        sha = relation["content_sha256"]
        row = {
            "content_sha256": sha,
            "provenance": relation["disposition"],
            "program": _programme(sha, relation, compatibles, incompatibles),
            "currentness": _actualite(relation),
            "pii": "PII_UNDECIDED" if sha in pii_detected else "PII_CLEARED_OR_NOT_SCANNED",
            "indexability": relation["serving_relevance"],
            "source_role": relation["source_role"],
        }
        row["verdict"] = _verdict(row)
        rows.append(row)
    rows.sort(key=lambda r: r["content_sha256"])

    def histogram(key: str) -> dict:
        counter = collections.Counter(row[key] for row in rows)
        return dict(sorted(counter.items(), key=lambda kv: -kv[1]))

    by_program = histogram("program")
    reconciliation = {
        "MATRIX_UNKNOWN": by_program.get("UNKNOWN", 0),
        "PARTITION_UNKNOWN": partition["PROGRAM_COMPATIBILITY_UNKNOWN"],
        "MATRIX_COMPATIBLE": by_program.get("COMPATIBLE_PROVEN", 0),
        "PARTITION_COMPATIBLE": partition["PROGRAM_COMPATIBILITY_PROVEN"],
        "MATRIX_INCOMPATIBLE": by_program.get("INCOMPATIBLE_PROVEN", 0),
        "PARTITION_INCOMPATIBLE": partition["PROGRAM_INCOMPATIBILITY_PROVEN"],
        "PARTITION_POPULATION": partition["PROGRAM_POPULATION_TOTAL"],
    }
    reconciliation["MATRIX_IN_PARTITION_POPULATION"] = (
        reconciliation["MATRIX_UNKNOWN"]
        + reconciliation["MATRIX_COMPATIBLE"]
        + reconciliation["MATRIX_INCOMPATIBLE"]
    )
    reconciliation["RECONCILES"] = (
        reconciliation["MATRIX_UNKNOWN"] == reconciliation["PARTITION_UNKNOWN"]
        and reconciliation["MATRIX_COMPATIBLE"] == reconciliation["PARTITION_COMPATIBLE"]
        and reconciliation["MATRIX_INCOMPATIBLE"] == reconciliation["PARTITION_INCOMPATIBLE"]
        and reconciliation["MATRIX_IN_PARTITION_POPULATION"]
        == reconciliation["PARTITION_POPULATION"]
    )

    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "kind": "NEXUS-SERVABILITY-MATRIX-V1",
        "applied": False,
        "SERVABILITY_ROWS_TOTAL": len(rows),
        "SERVABILITY_ROWS_DISTINCT_CONTENTS": len({r["content_sha256"] for r in rows}),
        "SERVABILITY_UNACCOUNTED": 0,
        "MATRIX_SHA256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "inputs": {
            "relations": RELATIONS,
            "program": PARTITION,
            "program_bindings": BINDINGS,
            "pii": PII_INDEX,
            "non_pdf": NON_PDF,
        },
        "PROGRAM_RECONCILIATION": reconciliation,
        "by_provenance": histogram("provenance"),
        "by_program": by_program,
        "by_currentness": histogram("currentness"),
        "by_pii": histogram("pii"),
        "by_indexability": histogram("indexability"),
        "by_source_role": histogram("source_role"),
        "by_verdict": histogram("verdict"),
        "non_pdf_by_disposition": non_pdf["NON_PDF_BY_DISPOSITION"],
        "rows": rows,
    }


def main() -> int:
    matrix = build()
    if not matrix["PROGRAM_RECONCILIATION"]["RECONCILES"]:
        print("REFUS : la matrice ne se réconcilie pas avec la partition programme.")
        print(json.dumps(matrix["PROGRAM_RECONCILIATION"], indent=1))
        return 1
    (REPO_ROOT / OUTPUT).write_text(
        json.dumps(matrix, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    for key in ("SERVABILITY_ROWS_TOTAL", "SERVABILITY_UNACCOUNTED", "MATRIX_SHA256"):
        print(f"{key}={matrix[key]}")
    for key, value in matrix["by_verdict"].items():
        print(f"  {key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
