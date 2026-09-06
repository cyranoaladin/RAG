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
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

PEDAGO_ROOT = Path(__file__).resolve().parents[1]
if str(PEDAGO_ROOT) not in sys.path:
    sys.path.insert(0, str(PEDAGO_ROOT))

from rag_pedago.governance.currentness_disposition import (  # noqa: E402
    DispositionError,
    construire_registre,
    verifier_registre,
)
from rag_pedago.governance.url_source_registry import (  # noqa: E402
    RegistreUrlSourceError,
    charger_registre,
)
from rag_pedago.governance.url_source_registry import (  # noqa: E402
    verifier_registre as verifier_registre_url,
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
#: Nom du champ par lequel l'autorité des artefacts déclare une source
#: statique — le même que celui qu'exige la disposition elle-même.
MARQUEUR_SOURCE_STATIQUE = "non_url_static_source"

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

    # Le registre d'URL est une AUTORITÉ de cette dérivation, pas une simple
    # entrée : on le vérifie avant de s'appuyer dessus. Le contrôle de dérive
    # du grand livre attrape un grand livre PÉRIMÉ ; il n'attrape pas un
    # registre vide, tronqué ou édité, à partir duquel un grand livre tout
    # neuf — et faux — se régénère sans rien signaler.
    verifier_registre_url(charger_registre(URL_REGISTRY_PATH))

    registry = json.loads(URL_REGISTRY_PATH.read_text(encoding="utf-8"))
    _exiger_couverture(evidence["artifacts"], registry["entrees"])

    ledger = construire_registre(
        artefacts=evidence["artifacts"], entrees_url=registry["entrees"]
    )
    verifier_registre(ledger)
    return ledger


def _exiger_couverture(
    artefacts: Sequence[Mapping[str, Any]], entrees: Sequence[Mapping[str, Any]]
) -> None:
    """Refuser de dériver si le registre ne couvre pas le périmètre.

    Un artefact absent de toute ``artefacts_perimetre`` n'est pas « sans
    URL » : il est hors de portée du registre. Les deux situations donnent
    zéro entrée et sont indiscernables dans le résultat, mais la première
    est une réponse et la seconde une lacune. Seule l'autorité des artefacts
    peut déclarer une source statique, et elle le fait explicitement.
    """
    couverts: set[str] = set()
    for entree in entrees:
        couverts.update(str(sha) for sha in entree.get("artefacts_perimetre") or ())
    orphelins = sorted(
        str(artefact["content_sha256"])
        for artefact in artefacts
        if str(artefact["content_sha256"]) not in couverts
        and not artefact.get(MARQUEUR_SOURCE_STATIQUE)
    )
    if orphelins:
        raise DispositionError(
            f"{len(orphelins)} artefact(s) hors couverture du registre d'URL et "
            f"sans déclaration {MARQUEUR_SOURCE_STATIQUE} par leur autorité : "
            + ", ".join(sha[:12] + "…" for sha in orphelins[:5])
        )


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
    except (DispositionError, RegistreUrlSourceError, KeyError, OSError) as exc:
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
