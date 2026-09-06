#!/usr/bin/env python3
"""Produire — ou vérifier — le registre de dispositions de fraîcheur.

Le registre est DÉRIVÉ de deux autorités déjà scellées : l'évidence de
fraîcheur (quels artefacts sont gouvernés) et le registre d'URL sources (ce
que chaque provenance a rendu). Rien n'y est saisi à la main : une disposition
écrite par un opérateur serait un avis, pas une mesure.

Usage :

    python scripts/build_currentness_disposition.py           # écrit
    python scripts/build_currentness_disposition.py --check    # compare
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

PEDAGO_ROOT = Path(__file__).resolve().parents[1]
if str(PEDAGO_ROOT) not in sys.path:
    sys.path.insert(0, str(PEDAGO_ROOT))

from rag_pedago.governance.currentness_disposition import (  # noqa: E402
    DispositionError,
    construire_registre,
    verifier_registre,
)

EVIDENCE_PATH = (
    PEDAGO_ROOT / "configs" / "prerentree_2026_2027" / "multilevel_currentness_evidence.yml"
)
URL_REGISTRY_PATH = (
    PEDAGO_ROOT
    / "data"
    / "releases"
    / "prerentree_2026_2027"
    / "multilevel"
    / "url_source_registry.json"
)
LEDGER_PATH = (
    PEDAGO_ROOT
    / "data"
    / "releases"
    / "prerentree_2026_2027"
    / "multilevel"
    / "currentness_disposition.json"
)


def build() -> dict:
    evidence = yaml.safe_load(EVIDENCE_PATH.read_text(encoding="utf-8"))
    registry = json.loads(URL_REGISTRY_PATH.read_text(encoding="utf-8"))
    ledger = construire_registre(
        artefacts=evidence["artifacts"], entrees_url=registry["entrees"]
    )
    verifier_registre(ledger)
    return ledger


def serialize(ledger: dict) -> bytes:
    return (
        json.dumps(ledger, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=LEDGER_PATH)
    arguments = parser.parse_args(argv)

    try:
        rendered = serialize(build())
    except (DispositionError, KeyError, OSError) as exc:
        print(f"currentness disposition error: {exc}", file=sys.stderr)
        return 2

    output: Path = arguments.output
    if arguments.check:
        if not output.is_file():
            print(f"CURRENTNESS_LEDGER_MISSING={output}", file=sys.stderr)
            return 1
        if output.read_bytes() != rendered:
            print("CURRENTNESS_LEDGER_DRIFT=1", file=sys.stderr)
            return 1
        print("CURRENTNESS_LEDGER_DRIFT=0")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(rendered)
    ledger = json.loads(rendered)
    print(f"CURRENTNESS_LEDGER_WRITTEN={output}")
    for name, value in sorted(ledger["comptes"].items()):
        print(f"{name}={value}")
    print(f"CURRENTNESS_ACCOUNTED={ledger['CURRENTNESS_ACCOUNTED']}")
    print(f"CURRENTNESS_UNACCOUNTED={ledger['CURRENTNESS_UNACCOUNTED']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
