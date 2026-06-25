#!/usr/bin/env python3
"""Validate all taxonomy YAML files against TaxonomySpec."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from schema.taxonomy import TaxonomySpec

TAXONOMY_DIR = Path(__file__).resolve().parents[1] / "taxonomy"
SKIP_DIRS = {"common", "exams", "proposals"}


def validate_all() -> int:
    errors = 0
    validated = 0
    warnings = 0
    total_notions = 0
    total_subnotions = 0

    for yml_file in sorted(TAXONOMY_DIR.rglob("*.yml")):
        rel = yml_file.relative_to(TAXONOMY_DIR)
        if rel.parts[0] in SKIP_DIRS:
            continue

        try:
            raw = yml_file.read_text(encoding="utf-8")
            data = yaml.safe_load(raw)
            spec = TaxonomySpec.model_validate(data)

            # Count notions vs subnotions
            n_notions = 0
            n_subnotions = 0
            for theme in spec.themes:
                for notion in theme.notions:
                    n_notions += 1
                    n_subnotions += len(notion.subnotions)
            total_notions += n_notions
            total_subnotions += n_subnotions

            # Check programme_version format
            pv = spec.programme_version
            pv_ok = bool(re.match(r"^(BOEN|BO)_", pv))
            pv_flag = "" if pv_ok else " [!programme_version format]"

            # Check for PREMIER JET marker
            is_draft = "PREMIER JET" in raw
            draft_flag = " [PREMIER JET]" if is_draft else ""
            if is_draft:
                warnings += 1

            print(
                f"  OK  {rel} — {spec.matiere}/{spec.niveau.value}"
                f" ({n_notions} notions, {n_subnotions} subnotions)"
                f"{draft_flag}{pv_flag}"
            )
            validated += 1

        except Exception as e:
            print(f"  FAIL  {rel} — {e}")
            errors += 1

    print(f"\n{validated} validated, {errors} errors, {warnings} drafts (PREMIER JET)")
    print(f"Total: {total_notions} notions, {total_subnotions} subnotions")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(validate_all())
