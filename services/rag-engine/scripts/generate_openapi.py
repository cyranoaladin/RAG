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


#: Les trois credentials du contrat externe, décrits pour un générateur de
#: client. Ils ne peuvent PAS être dérivés de `app.openapi()` : l'application
#: les exige dans un middleware, pas dans des dépendances FastAPI. Sans cette
#: déclaration, le schéma publié annonce des routes ouvertes que le runtime
#: refuse — un contrat qui ment.
SECURITY_SCHEMES: dict[str, dict] = {
    "bffServiceToken": {
        "type": "http",
        "scheme": "bearer",
        "description": (
            "Credential machine de la façade autorisée "
            "(`Authorization: Bearer <RAG_BFF_SERVICE_TOKEN>`). Il établit "
            "d'où vient l'appel, jamais ce que l'appelant a le droit de faire."
        ),
    },
    "ragApiKey": {
        "type": "apiKey",
        "in": "header",
        "name": "X-RAG-API-Key",
        "description": (
            "Clé porteuse du client, portée par le registre de clients du "
            "déploiement. Elle établit ce que CE client a le droit de faire. "
            "Aucun repli sur `Authorization` : les deux sont exigés."
        ),
    },
    "nexusSignedIdentity": {
        "type": "apiKey",
        "in": "header",
        "name": "X-Nexus-Identity",
        "description": (
            "Jeton d'identité signé émis par le SSO. Il transporte la portée "
            "de retrieval (tenant, niveau, matière, droits) que ni le "
            "credential machine ni la clé de client ne portent."
        ),
    },
}


def _security_requirement(route: str) -> list[dict[str, list[str]]] | None:
    """Les credentials exigés par cette route, lus des tables du runtime.

    Un seul objet dans la liste signifie « tous ceux-ci », pas « l'un d'eux » :
    c'est bien une conjonction, comme le middleware l'applique.
    """
    from ingestor.api_scopes import (
        required_scope_for_route,
        route_requires_signed_identity,
    )

    scope = required_scope_for_route(route)
    if scope is None:
        return None
    requirement: dict[str, list[str]] = {
        "bffServiceToken": [],
        "ragApiKey": [scope.value],
    }
    if route_requires_signed_identity(route):
        requirement["nexusSignedIdentity"] = []
    return [requirement]


def build_openapi_document() -> dict:
    """Rendre le schéma que FastAPI dérive des modèles montés, auth comprise."""
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from ingestor import api_v2

    document = api_v2.app.openapi()
    if not isinstance(document, dict):  # pragma: no cover - contrat FastAPI
        raise RuntimeError("FastAPI did not return an OpenAPI document")

    components = document.setdefault("components", {})
    components["securitySchemes"] = SECURITY_SCHEMES

    for route, operations in document.get("paths", {}).items():
        requirement = _security_requirement(route)
        if requirement is None:
            continue
        for operation in operations.values():
            if isinstance(operation, dict):
                operation["security"] = requirement
    return document


#: **Environnement d'émission.** Le schéma est rendu par Pydantic, et deux
#: versions de Pydantic rendent le même modèle avec des différences de forme
#: (2.13 écrit `additionalProperties: true` là où 2.9 l'omet — même sémantique
#: JSON Schema, la valeur par défaut étant `true`). Le service épingle 2.9.2
#: dans `requirements.lock` ; l'image v2 épingle 2.13.4 dans
#: `src/ingestor/requirements.runtime-v2.txt`, aligné sur `packages/contracts`.
#: L'artefact publié est donc celui du lock de service, qui est aussi celui que
#: la CI compare. La divergence est de rendu, pas de contrat ; l'aligner exige
#: de régénérer le lock du service, hors périmètre de ce lot.


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

    # Comparaison et écriture en octets UTF-8, jamais en texte : une lecture
    # en mode texte normalise les fins de ligne, et un fichier publié en CRLF
    # passerait pour identique alors que ses octets diffèrent —
    # `OPENAPI_SCHEMA_DRIFT=0` ne prouverait plus l'artefact octet-identique
    # qu'il promet.
    encoded = rendered.encode("utf-8")
    if arguments.check:
        if not output.is_file():
            print(f"OPENAPI_SCHEMA_MISSING={output}", file=sys.stderr)
            return 1
        if output.read_bytes() != encoded:
            print("OPENAPI_SCHEMA_DRIFT=1", file=sys.stderr)
            return 1
        print("OPENAPI_SCHEMA_DRIFT=0")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encoded)
    print(f"OPENAPI_SCHEMA_WRITTEN={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
