"""Construit NEXUS-SERVABILITY-MATRIX-V1 : une ligne par relation d'artefact.

La matrice ne décide rien. Elle croise les dimensions déjà mesurées et délègue
la composition au gate de servabilité, de sorte qu'une seule dimension
bloquante suffise à refuser, et que chaque refus nomme l'autorité qui l'a
prononcé.

Un défaut a rendu cette délégation nécessaire. La matrice calculait une colonne
`currentness` que son verdict ne consultait jamais : quarante contenus déclarés
archivés par la source ressortaient candidats servables, dont trois figuraient
déjà dans la release promue. Une dimension calculée mais non consommée est pire
qu'une dimension absente — elle donne l'apparence d'un contrôle.

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

SERVICE_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from nexus_contracts import parse_pii_review_decision_set  # noqa: E402

from rag_pedago.governance.currentness_disposition import (  # noqa: E402
    NOT_CURRENT_DECLARED_BY_SOURCE,
    cas_depuis_ligne_de_matrice,
    charger_politique,
    disposition_actualite,
)
from rag_pedago.governance.servability_gate import (  # noqa: E402
    AUTORITE_ACTUALITE,
    AUTORITE_PII,
    AUTORITE_PROGRAMME,
    AUTORITE_PROVENANCE,
    AUTORITE_ROLE,
    composer,
)

#: Un refus par autorité. Le verdict nomme QUI refuse, pas seulement QUE l on
#: refuse : sans cela, corriger la cause supposerait de deviner la dimension.
VERDICT_PAR_AUTORITE = {
    AUTORITE_PII: "BLOCKED_PII_HUMAN_REVIEW",
    AUTORITE_PROGRAMME: "REFUSED_PROGRAM_INCOMPATIBLE",
    AUTORITE_ROLE: "NOT_INDEXABLE_BY_ROLE",
    AUTORITE_PROVENANCE: "BLOCKED_NO_URL_PROVENANCE",
}

VERDICT_CANDIDAT = "CANDIDATE_NO_BLOCKING_DIMENSION"
VERDICT_ARCHIVE = "BLOCKED_NOT_CURRENT_BY_SOURCE"
VERDICT_ACTUALITE_INCONNUE = "BLOCKED_CURRENTNESS_UNKNOWN"

REPO_ROOT = pathlib.Path(
    os.environ.get("NEXUS_REPO_ROOT", pathlib.Path(__file__).resolve().parents[3])
)

RELATIONS = "docs/reports/handoff/url_provenance_reconciliation.json"
PARTITION = "docs/reports/handoff/program_partition_v4.json"
BINDINGS = "docs/reports/handoff/artifact_program_bindings.json"
PII_INDEX = "docs/reports/evidence-index/pii_review_index_v2_20260907.json"
PII_DECISIONS = "governance/pii-review-decisions/pii-review-2026-09-17-final.json"
PII_DECISIONS_SOURCE_PR = 219
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


def _verdict(row: dict, politique: dict) -> str:
    """Delegue la composition au gate. La matrice ne compose plus elle-meme."""
    actualite = disposition_actualite(cas_depuis_ligne_de_matrice(row), politique)
    row["currentness_disposition"] = actualite
    pii_gate_val = (
        "PII_UNDECIDED"
        if row["pii"] == "PII_UNDECIDED"
        else (
            "REJECTED"
            if row["pii"]
            in (
                "EXCLUDE_FROM_SERVABLE_SET",
                "PII_REDACTION_REQUIRED",
                "REJECTED",
            )
            else "PASS"
        )
    )
    verdict, autorite = composer(
        {
            "pii_gate": pii_gate_val,
            "program": "INCOMPATIBLE" if row["program"] == "INCOMPATIBLE_PROVEN" else row["program"],
            "indexable": row["indexability"] != "NON_INDEXABLE",
            "url_provenance": row["provenance"] != "NO_URL_EVIDENCE",
        },
        actualite,
    )
    if autorite is None:
        return VERDICT_CANDIDAT
    if autorite == AUTORITE_ACTUALITE:
        return (
            VERDICT_ARCHIVE
            if actualite == NOT_CURRENT_DECLARED_BY_SOURCE
            else VERDICT_ACTUALITE_INCONNUE
        )
    return VERDICT_PAR_AUTORITE[autorite]


def build() -> dict:
    # La politique d actualite est chargee ICI : si elle n est pas appliquee,
    # la matrice refuse de se construire plutot que d ignorer l actualite.
    politique = charger_politique()
    relations = _load(RELATIONS)["relations"]
    partition = _load(PARTITION)
    bindings = _load(BINDINGS)["bindings"]
    pii_bundles = _load(PII_INDEX)["bundles"]
    non_pdf = _load(NON_PDF)

    decisions: dict[str, str] = {}
    pii_decision_info = None
    pii_decision_path = REPO_ROOT / PII_DECISIONS
    if pii_decision_path.is_file():
        raw_decisions = pii_decision_path.read_bytes()
        dec_set = parse_pii_review_decision_set(raw_decisions)
        decisions = {d.content_sha256: d.decision for d in dec_set.decisions}
        first_d = dec_set.decisions[0] if dec_set.decisions else None
        pii_decision_info = {
            "path": PII_DECISIONS,
            "sha256": hashlib.sha256(raw_decisions).hexdigest(),
            "decision_set_id": dec_set.decision_set_id,
            "decisions_count": len(dec_set.decisions),
            "reviewer_login": first_d.reviewer_login if first_d else None,
            "decided_at": first_d.decided_at.isoformat() if first_d else None,
            "source_pr": PII_DECISIONS_SOURCE_PR,
        }

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
        if sha in pii_detected:
            if decisions.get(sha) == "APPROVED":
                pii_status = "PII_CLEARED"
            elif decisions.get(sha) == "REJECTED":
                pii_status = "REJECTED"
            else:
                pii_status = "PII_UNDECIDED"
        else:
            pii_status = "PII_CLEARED_OR_NOT_SCANNED"

        row = {
            "content_sha256": sha,
            "provenance": relation["disposition"],
            "program": _programme(sha, relation, compatibles, incompatibles),
            "currentness": _actualite(relation),
            "pii": pii_status,
            "indexability": relation["serving_relevance"],
            "source_role": relation["source_role"],
        }
        row["verdict"] = _verdict(row, politique)
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
            "pii_decisions": pii_decision_info,
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
