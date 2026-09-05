#!/usr/bin/env python3
"""Produire le schéma OpenAPI de l'API externe DEPUIS l'application elle-même.

Le schéma publié n'est jamais écrit à la main : il est dérivé des modèles
Pydantic déjà utilisés par le runtime (`nexus_contracts.RetrievalRequest` /
`RetrievalResponse` et les modèles de route). Un YAML rédigé séparément
finirait par dériver du code sans que rien ne le signale — et un contrat qui
ment est pire que pas de contrat.

Usage :

    PYTHONPATH=src python scripts/generate_openapi.py            # écrit
    PYTHONPATH=src python scripts/generate_openapi.py --check    # compare

Le mode ``--check`` est celui qu'exerce le test de dérive ; il ne modifie
rien et sort en erreur si le fichier publié n'est plus celui que le runtime
produirait.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

#: Racine du service dérivée de l'emplacement de ce fichier — jamais un
#: chemin absolu de poste de travail.
ENGINE_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ENGINE_ROOT / "src"
OPENAPI_PATH = ENGINE_ROOT / "openapi" / "rag-engine-external-api.json"


def build_openapi_document() -> dict:
    """Rendre le schéma que FastAPI dérive des modèles montés."""
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from ingestor import api_v2

    document = api_v2.app.openapi()
    if not isinstance(document, dict):  # pragma: no cover - contrat FastAPI
        raise RuntimeError("FastAPI did not return an OpenAPI document")
    return document


def serialize(document: dict) -> str:
    """Forme canonique : clés triées, indentation fixe, saut de ligne final.

    Sans elle, deux exécutions équivalentes produiraient des octets
    différents et la comparaison de dérive serait bruyante donc ignorée.
    """
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="comparer sans écrire ; sortie non nulle en cas de dérive",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OPENAPI_PATH,
        help="fichier de schéma publié",
    )
    arguments = parser.parse_args()

    rendered = serialize(build_openapi_document())
    output: Path = arguments.output

    if arguments.check:
        if not output.is_file():
            print(f"OPENAPI_SCHEMA_MISSING={output}", file=sys.stderr)
            return 1
        if output.read_text(encoding="utf-8") != rendered:
            print("OPENAPI_SCHEMA_DRIFT=1", file=sys.stderr)
            return 1
        print("OPENAPI_SCHEMA_DRIFT=0")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(f"OPENAPI_SCHEMA_WRITTEN={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
