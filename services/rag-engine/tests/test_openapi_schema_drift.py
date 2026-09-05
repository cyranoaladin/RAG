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
    published = OPENAPI_PATH.read_text(encoding="utf-8")
    assert published == serialize(runtime_document), (
        "OPENAPI_SCHEMA_DRIFT=1 — le schéma publié ne correspond plus au "
        "runtime. Régénérer : PYTHONPATH=src python scripts/generate_openapi.py"
    )


def test_le_schema_couvre_exactement_la_surface_gouvernee(
    runtime_document: dict,
) -> None:
    """Un schéma vide serait stable et donc vert : on vérifie la substance."""
    from ingestor import api_v2

    documented = set(runtime_document["paths"])
    mounted = {
        route.path
        for route in api_v2.app.routes
        if route.path not in {"/docs", "/redoc", "/openapi.json"}
    }
    assert documented == mounted
    assert "/search/v2" in documented
    assert "/taxonomy/v2" in documented


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
