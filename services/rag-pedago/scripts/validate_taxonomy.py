#!/usr/bin/env python3
"""Validate all taxonomy YAML files against TaxonomySpec."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from schema.taxonomy import TaxonomySpec

TAXONOMY_DIRS = [
    Path(__file__).resolve().parents[1] / "taxonomy",
]


def validate_all() -> int:
    errors = 0
    validated = 0

    for taxonomy_dir in TAXONOMY_DIRS:
        for yml_file in sorted(taxonomy_dir.rglob("*.yml")):
            # Skip non-TaxonomySpec files (common/, exams/, proposals/)
            rel = yml_file.relative_to(taxonomy_dir)
            if rel.parts[0] in ("common", "exams", "proposals"):
                continue

            try:
                data = yaml.safe_load(yml_file.read_text(encoding="utf-8"))
                spec = TaxonomySpec.model_validate(data)
                notion_count = len(spec.known_notion_ids)
                print(f"  OK  {rel} — {spec.matiere}/{spec.niveau.value} ({notion_count} notions)")
                validated += 1
            except Exception as e:
                print(f"  FAIL  {rel} — {e}")
                errors += 1

    print(f"\n{validated} validated, {errors} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(validate_all())
