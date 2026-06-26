#!/usr/bin/env python3
"""Build correspondence artefacts from programme PDFs.

Checks pdf_allowed/parsing_allowed before parsing.
Produces JSON artefacts in data/programmes/correspondance/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scrapers.programme_parser import build_correspondence_report

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "configs" / "pedago_interface_contract.yml"
PROGRAMMES_DIR = ROOT / "data" / "staging" / "programmes"
OUTPUT_DIR = ROOT / "data" / "programmes" / "correspondance"
TAXONOMY_ROOT = ROOT / "taxonomy"


def _check_allowed() -> bool:
    """Gate: pdf_allowed AND parsing_allowed must be true."""
    if not CONTRACT.is_file():
        return False
    config = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        return False
    return config.get("pdf_allowed") is True and config.get("parsing_allowed") is True


def _find_taxonomy(matiere: str, niveau: str) -> Path | None:
    """Find the taxonomy file for a (matiere, niveau)."""
    from schema.taxonomy import TaxonomySpec

    for yml in sorted(TAXONOMY_ROOT.rglob("*.yml")):
        if yml.parent.name in ("common", "exams", "proposals"):
            continue
        try:
            data = yaml.safe_load(yml.read_text(encoding="utf-8"))
            spec = TaxonomySpec.model_validate(data)
            if spec.matiere == matiere and spec.niveau.value == niveau:
                return yml
        except Exception:
            continue
    return None


def main() -> int:
    if not _check_allowed():
        print("BLOCKED: pdf_allowed or parsing_allowed is false")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    produced = 0

    for pdf in sorted(PROGRAMMES_DIR.glob("*.pdf")):
        # Parse filename: {matiere}_{niveau}_{statut}.pdf
        parts = pdf.stem.split("_")
        if len(parts) < 2:
            continue
        matiere = parts[0]
        niveau = parts[1]

        taxo = _find_taxonomy(matiere, niveau)
        if not taxo:
            print(f"  SKIP {pdf.name}: no taxonomy for {matiere}/{niveau}")
            continue

        print(f"  Parsing {pdf.name} vs {taxo.name}...")
        report = build_correspondence_report(taxo, pdf)

        if report.get("extraction_status") == "failed":
            print(f"  FAILED: extraction failed for {pdf.name}")
            continue

        out = OUTPUT_DIR / f"{matiere}_{niveau}.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  OK: {out.name} ({report.get('found_exact', 0)} exact, "
              f"{report.get('found_partial', 0)} partial, {report.get('not_found', 0)} not_found)")
        produced += 1

    print(f"\n{produced} artefact(s) produced in {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
