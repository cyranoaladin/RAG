#!/usr/bin/env python3
"""Dérive un registre de contenus successeur, sans réécriture historique.

Pourquoi ce script existe. Un artefact historique ne doit pas changer de sens
sous le même nom sans trace (décision de gouvernance du 2026-09-02, §8). Le
registre `content_ledger_20260814.jsonl` reste donc à son état attesté ; toute
mesure nouvelle qui contredit une de ses lignes produit un SUCCESSEUR daté,
dérivé par exécution depuis (a) le registre source et (b) un fichier de
rectifications déclaratif, chacune adossée à une preuve nommée par empreinte.
La provenance (`<sortie>.provenance.json`) pinne les entrées, la sortie et le
registre supplanté (`supersedes`), comme `matrice_production_20260831` le fait
pour la matrice.

    python scripts/deriver_content_ledger.py \\
        --source docs/reports/evidence-index/content_ledger_20260814.jsonl \\
        --rectifications docs/reports/evidence-index/rectifications_ledger_20260902.json \\
        --sortie docs/reports/evidence-index/content_ledger_20260902.jsonl

Refus (fail-closed) : empreinte source ou preuve différente de la déclaration,
contenu inconnu, valeur `avant` non observée, code de motif retiré absent,
champ non rectifiable, rectification sans preuve.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_RECTIFICATIONS = "NEXUS-LEDGER-RECTIFICATIONS-V1"
SCHEMA_PROVENANCE = "NEXUS-DERIVED-LEDGER-PROVENANCE-V1"

#: Les seuls champs qu'une mesure nouvelle peut rectifier. L'identité du
#: contenu, ses placements et son routage ne sont pas des mesures PII.
CHAMPS_RECTIFIABLES = frozenset({"PII", "EXTRACTABILITY", "FINAL_DISPOSITION"})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _octets_canoniques(document: object) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _lire_registre(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        sha = row.get("content_sha256")
        if not isinstance(sha, str) or sha in seen:
            raise ValueError(f"ledger row without a unique content_sha256: {line[:80]}")
        seen.add(sha)
        rows.append(row)
    return rows


def _resolve(base_dir: Path, declared: str) -> Path:
    candidate = Path(declared)
    return candidate if candidate.is_absolute() else base_dir / candidate


def deriver(
    *,
    source: Path,
    rectifications: Path,
    sortie: Path,
    base_dir: Path,
) -> dict[str, object]:
    declaration = json.loads(rectifications.read_text(encoding="utf-8"))
    if declaration.get("schema_version") != SCHEMA_RECTIFICATIONS:
        raise ValueError("rectifications schema_version is not supported")
    declared_source = declaration["source_ledger"]
    if _resolve(base_dir, declared_source["path"]).resolve() != source.resolve():
        raise ValueError("source ledger path differs from the declaration")
    source_sha = _sha256(source)
    if declared_source["sha256"] != source_sha:
        raise ValueError("source ledger digest differs from the declaration")
    evidences: dict[str, dict[str, str]] = declaration.get("evidences", {})
    for name, evidence in evidences.items():
        path = _resolve(base_dir, evidence["path"])
        if not path.is_file():
            raise ValueError(f"evidence {name!r} is missing: {evidence['path']}")
        if _sha256(path) != evidence["sha256"]:
            raise ValueError(f"evidence digest differs from the declaration: {name!r}")

    rows = _lire_registre(source)
    by_sha = {str(row["content_sha256"]): row for row in rows}
    applied: list[str] = []
    for rectification in declaration.get("rectifications", []):
        sha = rectification["content_sha256"]
        row = by_sha.get(sha)
        if row is None:
            raise ValueError(f"rectification targets an unknown content: {sha}")
        if sha in applied:
            raise ValueError(f"content rectified twice: {sha}")
        named = rectification.get("evidences") or []
        if not named or any(name not in evidences for name in named):
            raise ValueError(f"rectification without a declared evidence: {sha}")
        for field, change in rectification.get("champs", {}).items():
            if field not in CHAMPS_RECTIFIABLES:
                raise ValueError(f"field {field!r} is not rectifiable")
            if row.get(field) != change["avant"]:
                raise ValueError(
                    f"declared 'avant' value for {field} is not observed on {sha}"
                )
            row[field] = change["apres"]
        codes = list(row.get("REASON_CODES", []))
        for code in rectification.get("reason_codes_retires", []):
            if code not in codes:
                raise ValueError(f"reason code to withdraw is absent on {sha}: {code}")
            codes.remove(code)
        for code in rectification.get("reason_codes_ajoutes", []):
            if code in codes:
                raise ValueError(f"reason code already present on {sha}: {code}")
            codes.append(code)
        row["REASON_CODES"] = sorted(codes)
        sources = list(row.get("EVIDENCE_SOURCES", []))
        for evidence_source in rectification.get("evidence_sources_ajoutes", []):
            if evidence_source not in sources:
                sources.append(evidence_source)
        row["EVIDENCE_SOURCES"] = sources
        applied.append(sha)

    sortie.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    provenance: dict[str, object] = {
        "schema_version": SCHEMA_PROVENANCE,
        "producteur": "services/rag-pedago/scripts/deriver_content_ledger.py",
        "derive_le": datetime.now(UTC).isoformat(),
        "supersedes": {"path": declared_source["path"], "sha256": source_sha},
        "entrees": {
            rectifications.name: _sha256(rectifications),
            **{evidence["path"]: evidence["sha256"] for evidence in evidences.values()},
        },
        "sortie": {sortie.name: _sha256(sortie)},
        "lignes_avant": len(rows),
        "lignes_apres": len(rows),
        "rectifications_appliquees": len(applied),
        "contenus_rectifies": sorted(applied),
    }
    (sortie.with_suffix("")).with_name(sortie.stem + ".provenance.json").write_bytes(
        _octets_canoniques(provenance)
    )
    return provenance


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--rectifications", type=Path, required=True)
    parser.add_argument("--sortie", type=Path, required=True)
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(__file__).resolve().parents[3],
        help="racine contre laquelle les chemins déclarés sont résolus (dépôt par défaut)",
    )
    args = parser.parse_args(argv)
    provenance = deriver(
        source=args.source,
        rectifications=args.rectifications,
        sortie=args.sortie,
        base_dir=args.base_dir,
    )
    print(json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
