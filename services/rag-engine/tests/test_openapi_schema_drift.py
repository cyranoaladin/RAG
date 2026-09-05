"""Le schéma OpenAPI publié EST celui du runtime, ou la suite est rouge.

Un fichier de contrat rédigé à la main dérive : le code change, le document
reste, et les intégrateurs codent contre une promesse qui n'existe plus.
Ici, le document est dérivé des mêmes modèles Pydantic que les routes, et
cette épreuve refuse tout écart.

Elle ne teste pas seulement l'égalité d'octets : elle vérifie aussi que la
surface annoncée est bien la surface gouvernée, et que le contrat partagé
`RetrievalRequest`/`RetrievalResponse` y figure — un schéma identique mais
vide passerait autrement.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "scripts"))

from generate_openapi import (  # noqa: E402
    OPENAPI_PATH,
    build_openapi_document,
    serialize,
)


@pytest.fixture(scope="module")
def runtime_document() -> dict:
    return build_openapi_document()


def test_le_schema_publie_est_celui_du_runtime(runtime_document: dict) -> None:
    """`OPENAPI_SCHEMA_DRIFT=0` — sinon régénérer avec scripts/generate_openapi.py."""
    assert OPENAPI_PATH.is_file(), (
        "schéma OpenAPI absent : "
        "PYTHONPATH=src python scripts/generate_openapi.py"
    )
    # Octets, pas texte : une lecture en mode texte normalise les fins de
    # ligne, et un fichier publié en CRLF passerait pour identique.
    published = OPENAPI_PATH.read_bytes()
    assert published == serialize(runtime_document).encode("utf-8"), (
        "OPENAPI_SCHEMA_DRIFT=1 — le schéma publié ne correspond plus au "
        "runtime. Régénérer : PYTHONPATH=src python scripts/generate_openapi.py"
    )


def test_le_schema_couvre_exactement_la_surface_gouvernee(
    runtime_document: dict,
) -> None:
    """Un schéma vide serait stable et donc vert : on vérifie la substance."""
    from ingestor import api_v2

    documented = set(runtime_document["paths"])
    # Seules les routes que FastAPI documente réellement entrent dans la
    # comparaison. Une liste d'exclusions codée en dur oubliait
    # `/docs/oauth2-redirect`, monté en mode développement et jamais
    # documenté : la surface de contrat aurait divergé pour un composant
    # d'interface qui n'en fait pas partie.
    mounted = {
        route.path
        for route in api_v2.app.routes
        if getattr(route, "include_in_schema", False) and getattr(route, "methods", None)
    }
    assert documented == mounted
    assert "/search/v2" in documented
    assert "/taxonomy/v2" in documented


def test_le_schema_declare_les_credentials_que_le_runtime_exige(
    runtime_document: dict,
) -> None:
    """`app.openapi()` seul ne voit rien : l'auth vit dans un middleware.

    Sans déclaration explicite, le document annonce des routes ouvertes que
    le runtime refuse en 401 — un générateur de client produit alors du code
    qui ne peut pas appeler `/search/v2`.
    """
    from ingestor.api_scopes import required_scope_for_route, route_requires_signed_identity

    schemes = runtime_document["components"]["securitySchemes"]
    assert schemes["bffServiceToken"]["type"] == "http"
    assert schemes["bffServiceToken"]["scheme"] == "bearer"
    assert schemes["ragApiKey"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-RAG-API-Key",
        "description": schemes["ragApiKey"]["description"],
    }
    assert schemes["nexusSignedIdentity"]["name"] == "X-Nexus-Identity"

    gouvernees = 0
    for route, operations in runtime_document["paths"].items():
        scope = required_scope_for_route(route)
        for operation in operations.values():
            declared = operation.get("security")
            if scope is None:
                assert declared is None, route
                continue
            gouvernees += 1
            # Un seul objet : conjonction, pas alternative — c'est ce que le
            # middleware applique.
            assert isinstance(declared, list) and len(declared) == 1, route
            (requirement,) = declared
            assert requirement["bffServiceToken"] == []
            assert requirement["ragApiKey"] == [scope.value]
            assert ("nexusSignedIdentity" in requirement) is (
                route_requires_signed_identity(route)
            ), route
    assert gouvernees >= 8


def test_la_taxonomie_est_typee_et_non_un_objet_libre(runtime_document: dict) -> None:
    """Un `dict[str, Any]` publié n'apprend rien à un générateur de client."""
    taxonomy = runtime_document["paths"]["/taxonomy/v2"]["get"]
    reference = taxonomy["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert reference.endswith("/TaxonomyV2Response")

    schemas = runtime_document["components"]["schemas"]
    assert set(schemas["TaxonomyV2Response"]["properties"]) == {
        "version",
        "collections",
        "dimensions",
    }
    assert set(schemas["TaxonomyCollectionV2"]["properties"]) == {
        "collection",
        "matiere",
        "niveau",
        "voie",
        "statut_enseignement",
        "programme_version",
        "school_year",
    }
    assert set(schemas["TaxonomyDimensionsV2"]["properties"]) == {
        "matiere",
        "niveau",
        "voie",
        "statut_enseignement",
        "programme_version",
        "school_year",
    }


def test_le_schema_derive_du_contrat_partage(runtime_document: dict) -> None:
    """Les modèles annoncés sont ceux de `nexus-contracts`, pas des copies."""
    schemas = runtime_document["components"]["schemas"]
    assert "RetrievalRequest" in schemas
    assert "RetrievalResponse" in schemas

    search = runtime_document["paths"]["/search/v2"]["post"]
    body_ref = search["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert body_ref.endswith("/RetrievalRequest")
    response_ref = search["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert response_ref.endswith("/RetrievalResponse")

    # Le filtre pédagogique désormais servi doit être visible du contrat.
    assert "notions" in schemas["RetrievalNeed"]["properties"]
