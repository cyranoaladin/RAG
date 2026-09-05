"""Portées d'API porteuses — `rag:search` n'est pas `rag:ingest`.

Une clé de lecture qui pourrait écrire n'est pas une clé de lecture. Ces
épreuves scellent la séparation, et le fait qu'aucune clé ne vive dans le
dépôt : la configuration ne transporte que des empreintes SHA-256, jamais un
jeton utilisable.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor.api_scopes import (  # noqa: E402
    API_CLIENTS_ENV,
    API_CLIENTS_FILE_ENV,
    ApiScope,
    ApiScopeConfigurationError,
    load_api_clients,
    require_api_scope,
    required_scope_for_route,
)

SEARCH_TOKEN = "jeton-de-recherche-de-test-0123456789"
INGEST_TOKEN = "jeton-d-ingestion-de-test-0123456789"
ADMIN_TOKEN = "jeton-d-administration-de-test-0123456789"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


REGISTRY = [
    {
        "client_id": "cockpit-lecture",
        "token_sha256": _digest(SEARCH_TOKEN),
        "scopes": ["rag:search", "rag:read-source"],
    },
    {
        "client_id": "worker-ingestion",
        "token_sha256": _digest(INGEST_TOKEN),
        "scopes": ["rag:ingest"],
    },
    {
        "client_id": "console-admin",
        "token_sha256": _digest(ADMIN_TOKEN),
        "scopes": ["rag:admin"],
    },
]


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(API_CLIENTS_FILE_ENV, raising=False)
    monkeypatch.setenv(API_CLIENTS_ENV, json.dumps(REGISTRY))


def _request(token: str | None, *, path: str = "/search/v2") -> Request:
    headers = []
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": headers,
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 5555),
        }
    )


class TestChargementDuRegistre:
    def test_aucun_registre_configure_ferme_le_service(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail-closed : pas de configuration, pas de trafic — jamais un repli."""
        monkeypatch.delenv(API_CLIENTS_ENV, raising=False)
        monkeypatch.delenv(API_CLIENTS_FILE_ENV, raising=False)

        with pytest.raises(ApiScopeConfigurationError):
            load_api_clients()

        with pytest.raises(HTTPException) as excinfo:
            require_api_scope(
                _request(SEARCH_TOKEN), required=ApiScope.SEARCH, endpoint="/search/v2"
            )
        assert excinfo.value.status_code == 503

    def test_un_jeton_en_clair_dans_la_configuration_est_refuse(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La configuration ne transporte que des empreintes.

        Accepter un jeton en clair rendrait possible — donc un jour
        inévitable — de le committer."""
        monkeypatch.delenv(API_CLIENTS_FILE_ENV, raising=False)
        monkeypatch.setenv(
            API_CLIENTS_ENV,
            json.dumps(
                [
                    {
                        "client_id": "naif",
                        "token": SEARCH_TOKEN,
                        "scopes": ["rag:search"],
                    }
                ]
            ),
        )
        with pytest.raises(ApiScopeConfigurationError):
            load_api_clients()

    def test_les_cles_viennent_d_un_magasin_monte(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Un secret monté (fichier) est une source légitime, le dépôt non."""
        monkeypatch.delenv(API_CLIENTS_ENV, raising=False)
        store = tmp_path / "clients.json"
        store.write_text(json.dumps(REGISTRY), encoding="utf-8")
        monkeypatch.setenv(API_CLIENTS_FILE_ENV, str(store))

        clients = load_api_clients()

        assert {client.client_id for client in clients} == {
            "cockpit-lecture",
            "worker-ingestion",
            "console-admin",
        }

    def test_deux_sources_simultanees_sont_refusees(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Deux vérités concurrentes : impossible de dire laquelle gouverne."""
        store = tmp_path / "clients.json"
        store.write_text(json.dumps(REGISTRY), encoding="utf-8")
        monkeypatch.setenv(API_CLIENTS_ENV, json.dumps(REGISTRY))
        monkeypatch.setenv(API_CLIENTS_FILE_ENV, str(store))

        with pytest.raises(ApiScopeConfigurationError):
            load_api_clients()

    def test_une_portee_inconnue_est_refusee(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(API_CLIENTS_FILE_ENV, raising=False)
        monkeypatch.setenv(
            API_CLIENTS_ENV,
            json.dumps(
                [
                    {
                        "client_id": "trop-gourmand",
                        "token_sha256": _digest(SEARCH_TOKEN),
                        "scopes": ["rag:search", "rag:tout"],
                    }
                ]
            ),
        )
        with pytest.raises(ApiScopeConfigurationError):
            load_api_clients()

    def test_deux_clients_ne_peuvent_pas_partager_une_empreinte(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un même jeton portant deux identités rendrait le journal faux."""
        monkeypatch.delenv(API_CLIENTS_FILE_ENV, raising=False)
        monkeypatch.setenv(
            API_CLIENTS_ENV,
            json.dumps(
                [
                    {
                        "client_id": "a",
                        "token_sha256": _digest(SEARCH_TOKEN),
                        "scopes": ["rag:search"],
                    },
                    {
                        "client_id": "b",
                        "token_sha256": _digest(SEARCH_TOKEN),
                        "scopes": ["rag:ingest"],
                    },
                ]
            ),
        )
        with pytest.raises(ApiScopeConfigurationError):
            load_api_clients()


class TestPorteeExigee:
    def test_jeton_absent_est_401(self, registry: None) -> None:
        with pytest.raises(HTTPException) as excinfo:
            require_api_scope(_request(None), required=ApiScope.SEARCH, endpoint="/search/v2")
        assert excinfo.value.status_code == 401

    def test_jeton_inconnu_est_401(self, registry: None) -> None:
        with pytest.raises(HTTPException) as excinfo:
            require_api_scope(
                _request("jeton-jamais-declare"),
                required=ApiScope.SEARCH,
                endpoint="/search/v2",
            )
        assert excinfo.value.status_code == 401

    def test_la_cle_de_recherche_cherche(self, registry: None) -> None:
        client = require_api_scope(
            _request(SEARCH_TOKEN), required=ApiScope.SEARCH, endpoint="/search/v2"
        )
        assert client.client_id == "cockpit-lecture"
        assert ApiScope.SEARCH in client.scopes

    def test_la_cle_de_recherche_lit_une_source(self, registry: None) -> None:
        client = require_api_scope(
            _request(SEARCH_TOKEN),
            required=ApiScope.READ_SOURCE,
            endpoint="/corpora/servable/v1",
        )
        assert client.client_id == "cockpit-lecture"

    def test_la_cle_de_recherche_n_administre_pas(self, registry: None) -> None:
        with pytest.raises(HTTPException) as excinfo:
            require_api_scope(
                _request(SEARCH_TOKEN),
                required=ApiScope.ADMIN,
                endpoint="/review/v2/decide",
            )
        assert excinfo.value.status_code == 403

    def test_la_cle_d_ingestion_ne_cherche_pas(self, registry: None) -> None:
        """La séparation joue dans les deux sens, sinon ce n'est pas une séparation."""
        with pytest.raises(HTTPException) as excinfo:
            require_api_scope(
                _request(INGEST_TOKEN), required=ApiScope.SEARCH, endpoint="/search/v2"
            )
        assert excinfo.value.status_code == 403

    def test_lecture_de_source_n_est_pas_incluse_dans_recherche(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`rag:read-source` est une portée distincte, jamais impliquée par
        `rag:search` : servir un extrait n'autorise pas à servir la source."""
        monkeypatch.delenv(API_CLIENTS_FILE_ENV, raising=False)
        monkeypatch.setenv(
            API_CLIENTS_ENV,
            json.dumps(
                [
                    {
                        "client_id": "recherche-seule",
                        "token_sha256": _digest(SEARCH_TOKEN),
                        "scopes": ["rag:search"],
                    }
                ]
            ),
        )
        with pytest.raises(HTTPException) as excinfo:
            require_api_scope(
                _request(SEARCH_TOKEN),
                required=ApiScope.READ_SOURCE,
                endpoint="/corpora/servable/v1",
            )
        assert excinfo.value.status_code == 403


class TestSeparationDeLIngestion:
    def test_une_cle_rag_search_ne_peut_pas_ingerer(
        self, registry: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L'épreuve bloquante, sur la VRAIE porte d'ingestion livrée.

        Le jeton est par ailleurs un jeton d'agent d'ingestion valide au sens
        des rôles historiques : seule la portée manque. Sans cela, le refus
        pourrait venir du contrôle de rôle et ne prouverait rien sur les
        portées."""
        from ingestor import ingest_v2_endpoint

        monkeypatch.setenv("RAG_INGEST_AGENT_TOKEN", SEARCH_TOKEN)
        monkeypatch.delenv("INGESTOR_IP_ALLOWLIST", raising=False)

        with pytest.raises(HTTPException) as excinfo:
            ingest_v2_endpoint._enforce_security(
                _request(SEARCH_TOKEN, path="/ingest/v2/urls")
            )

        assert excinfo.value.status_code == 403

    def test_la_cle_rag_ingest_ingere(
        self, registry: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Contrôle positif : sans lui, un refus systématique passerait."""
        from ingestor import ingest_v2_endpoint

        monkeypatch.setenv("RAG_INGEST_AGENT_TOKEN", INGEST_TOKEN)
        monkeypatch.delenv("INGESTOR_IP_ALLOWLIST", raising=False)

        token = ingest_v2_endpoint._enforce_security(
            _request(INGEST_TOKEN, path="/ingest/v2/urls")
        )

        assert token == INGEST_TOKEN


class TestTableDesRoutes:
    def test_chaque_route_metier_exige_une_portee(self) -> None:
        """Une route sans portée déclarée serait une route sans porte."""
        for route in (
            "/search/v2",
            "/taxonomy/v2",
            "/collections/v2",
            "/catalogue/v2",
            "/collections/readiness",
            "/chat",
            "/corpora/servable/v1",
            "/corpora/servable/v1/{manifest_sha256}",
            "/review/v2/queue",
            "/review/v2/decide",
        ):
            assert required_scope_for_route(route) is not None, route

    def test_le_retrieval_exige_rag_search(self) -> None:
        assert required_scope_for_route("/search/v2") is ApiScope.SEARCH
        assert required_scope_for_route("/taxonomy/v2") is ApiScope.SEARCH

    def test_la_source_servable_exige_rag_read_source(self) -> None:
        assert required_scope_for_route("/corpora/servable/v1") is ApiScope.READ_SOURCE

    def test_la_revue_exige_rag_admin(self) -> None:
        assert required_scope_for_route("/review/v2/decide") is ApiScope.ADMIN

    def test_une_route_inconnue_n_a_pas_de_portee(self) -> None:
        assert required_scope_for_route("/inconnue") is None


class TestAucunSecretDansLeDepot:
    def test_le_module_ne_porte_aucune_valeur_de_jeton(self) -> None:
        """Le code lit une configuration ; il n'en embarque jamais une."""
        source = (
            Path(__file__).resolve().parents[1] / "src" / "ingestor" / "api_scopes.py"
        ).read_text(encoding="utf-8")
        assert "token_sha256\": \"" not in source
        assert not any(
            len(word) == 64 and all(char in "0123456789abcdef" for char in word)
            for word in source.replace('"', " ").replace("'", " ").split()
        )
