"""Journalisation structurée du runtime v2 (P0-L6A).

Le runtime n'émettait aucune ligne applicative : impossible de répondre à
« qui a interrogé quoi, quand, avec quel résultat », ni de corréler un incident
à une requête. Ces tests fixent le contrat de la ligne de journal et, surtout,
ce qu'elle ne doit jamais contenir.
"""

from __future__ import annotations

import json
import logging
import re
import sys

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.ingestor import api_v2

REQUEST_ID_PATTERN = re.compile(r"\A[0-9a-f]{32}\Z")


def _emitted_records(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for record in caplog.records:
        if record.name != api_v2.REQUEST_LOGGER_NAME:
            continue
        payloads.append(json.loads(record.getMessage()))
    return payloads


@pytest.fixture
def observed_route(monkeypatch: pytest.MonkeyPatch):
    """Servir une route métier réelle sans base ni identité."""
    monkeypatch.setattr(api_v2, "require_bff_service", lambda *_a, **_k: None)
    monkeypatch.setattr(api_v2, "_database_runtime_ready", lambda: True)

    async def route(_request: Request) -> JSONResponse:
        return JSONResponse({"results": []})

    monkeypatch.setattr(api_v2, "run_in_threadpool", _immediate)
    return route


async def _immediate(function, *args, **kwargs):  # noqa: ANN001, ANN202
    return function(*args, **kwargs)


def test_business_request_emits_one_structured_line_with_a_request_id(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(api_v2, "require_bff_service", lambda *_a, **_k: None)
    monkeypatch.setattr(api_v2, "_database_runtime_ready", lambda: True)
    monkeypatch.setattr(api_v2, "run_in_threadpool", _immediate)

    with caplog.at_level(logging.INFO, logger=api_v2.REQUEST_LOGGER_NAME):
        response = TestClient(api_v2.app).post(
            "/search/v2",
            json={"query": "definition d'un arbre binaire"},
            headers={"Authorization": "Bearer irrelevant"},
        )

    records = _emitted_records(caplog)
    assert len(records) == 1, records
    entry = records[0]

    assert entry["event"] == "http_request"
    assert entry["path"] == "/search/v2"
    assert entry["method"] == "POST"
    assert entry["status"] == response.status_code
    assert isinstance(entry["duration_ms"], int | float)
    assert entry["duration_ms"] >= 0
    assert REQUEST_ID_PATTERN.match(str(entry["request_id"]))


def test_response_carries_back_the_correlation_identifier(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Sans en-tête retourné, l'appelant ne peut pas citer la requête en panne."""
    monkeypatch.setattr(api_v2, "require_bff_service", lambda *_a, **_k: None)
    monkeypatch.setattr(api_v2, "_database_runtime_ready", lambda: True)
    monkeypatch.setattr(api_v2, "run_in_threadpool", _immediate)

    with caplog.at_level(logging.INFO, logger=api_v2.REQUEST_LOGGER_NAME):
        response = TestClient(api_v2.app).post(
            "/search/v2",
            json={"query": "x"},
            headers={"Authorization": "Bearer irrelevant"},
        )

    logged = _emitted_records(caplog)[0]["request_id"]
    assert response.headers["x-request-id"] == logged


def test_request_log_never_carries_the_query_the_token_or_the_identity(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Le journal est une trace de corrélation, jamais un miroir du trafic."""
    secret_token = "lot41u-runtime-bff-service-token-32-bytes"
    student_question = "quelles annales de philosophie pour Amine Ben Salah"
    identity_envelope = "eyJhbGciOiJIUzI1NiJ9.secret-identity-envelope.signature"

    monkeypatch.setattr(api_v2, "require_bff_service", lambda *_a, **_k: None)
    monkeypatch.setattr(api_v2, "_database_runtime_ready", lambda: True)
    monkeypatch.setattr(api_v2, "run_in_threadpool", _immediate)

    with caplog.at_level(logging.INFO, logger=api_v2.REQUEST_LOGGER_NAME):
        TestClient(api_v2.app).post(
            "/search/v2",
            json={"query": student_question},
            headers={
                "Authorization": f"Bearer {secret_token}",
                "X-Nexus-Identity": identity_envelope,
            },
        )

    serialized = json.dumps(_emitted_records(caplog))
    assert student_question not in serialized
    assert secret_token not in serialized
    assert identity_envelope not in serialized
    assert "Authorization" not in serialized
    assert "authorization" not in serialized


def test_unknown_paths_are_logged_under_a_bounded_label(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """La cardinalité du journal suit celle des métriques : jamais l'URL brute."""
    monkeypatch.setattr(api_v2, "require_bff_service", lambda *_a, **_k: None)
    monkeypatch.setattr(api_v2, "_database_runtime_ready", lambda: True)

    with caplog.at_level(logging.INFO, logger=api_v2.REQUEST_LOGGER_NAME):
        TestClient(api_v2.app).get("/../../etc/passwd?leak=1")

    entry = _emitted_records(caplog)[0]
    assert entry["path"] == "unmatched"
    assert "passwd" not in json.dumps(entry)
    assert "leak" not in json.dumps(entry)


def test_a_client_supplied_correlation_identifier_is_adopted_when_safe(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Le BFF corrèle sa requête entrante et l'appel moteur sous un même id."""
    monkeypatch.setattr(api_v2, "require_bff_service", lambda *_a, **_k: None)
    monkeypatch.setattr(api_v2, "_database_runtime_ready", lambda: True)
    monkeypatch.setattr(api_v2, "run_in_threadpool", _immediate)
    supplied = "0123456789abcdef0123456789abcdef"

    with caplog.at_level(logging.INFO, logger=api_v2.REQUEST_LOGGER_NAME):
        response = TestClient(api_v2.app).post(
            "/search/v2",
            json={"query": "x"},
            headers={
                "Authorization": "Bearer irrelevant",
                "X-Request-Id": supplied,
            },
        )

    assert _emitted_records(caplog)[0]["request_id"] == supplied
    assert response.headers["x-request-id"] == supplied


@pytest.mark.parametrize(
    "hostile",
    [
        "not-hex",
        "0123456789abcdef0123456789abcdef0",
        "0123456789ABCDEF0123456789abcdef",
        "../../etc/passwd",
        'x" injected="1',
        "",
        "0123456789abcdef 0123456789abcde",
    ],
)
def test_a_hostile_correlation_identifier_is_replaced_not_echoed(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    hostile: str,
) -> None:
    """Un id client est une donnée : il ne devient jamais du contenu de journal."""
    monkeypatch.setattr(api_v2, "require_bff_service", lambda *_a, **_k: None)
    monkeypatch.setattr(api_v2, "_database_runtime_ready", lambda: True)
    monkeypatch.setattr(api_v2, "run_in_threadpool", _immediate)

    with caplog.at_level(logging.INFO, logger=api_v2.REQUEST_LOGGER_NAME):
        response = TestClient(api_v2.app).post(
            "/search/v2",
            json={"query": "x"},
            headers={
                "Authorization": "Bearer irrelevant",
                "X-Request-Id": hostile,
            },
        )

    entry = _emitted_records(caplog)[0]
    assert REQUEST_ID_PATTERN.match(str(entry["request_id"]))
    assert entry["request_id"] != hostile
    assert response.headers["x-request-id"] == entry["request_id"]
    assert hostile not in json.dumps(entry) or hostile == ""


def test_each_request_line_is_a_single_parsable_json_object(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Une ligne = un objet JSON : sinon aucun collecteur ne peut l'ingérer."""
    monkeypatch.setattr(api_v2, "require_bff_service", lambda *_a, **_k: None)
    monkeypatch.setattr(api_v2, "_database_runtime_ready", lambda: True)

    with caplog.at_level(logging.INFO, logger=api_v2.REQUEST_LOGGER_NAME):
        TestClient(api_v2.app).get("/health")

    for record in caplog.records:
        if record.name != api_v2.REQUEST_LOGGER_NAME:
            continue
        message = record.getMessage()
        assert "\n" not in message
        json.loads(message)


def test_request_logger_emits_without_any_external_logging_configuration() -> None:
    """Le conteneur ne configure aucun logger : l'app doit s'équiper elle-même.

    Uvicorn ne configure que ses propres loggers ; le logger racine reste sans
    handler et au niveau WARNING. Un logger applicatif laissé aux valeurs par
    défaut n'écrit donc rien du tout en production — le journal existerait dans
    le code et nulle part sur le disque.
    """
    logger = logging.getLogger(api_v2.REQUEST_LOGGER_NAME)

    assert logger.isEnabledFor(logging.INFO)
    handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.StreamHandler)
    ]
    assert len(handlers) == 1, logger.handlers
    assert handlers[0].stream is sys.stdout
    assert handlers[0].formatter is not None
    assert handlers[0].formatter.format(
        logging.LogRecord(
            api_v2.REQUEST_LOGGER_NAME, logging.INFO, __file__, 1, '{"a":1}', None, None
        )
    ) == '{"a":1}'


def test_request_logging_configuration_is_idempotent() -> None:
    """Un rechargement du module ne doit jamais dupliquer chaque ligne."""
    before = len(logging.getLogger(api_v2.REQUEST_LOGGER_NAME).handlers)
    api_v2._configure_request_logging()
    api_v2._configure_request_logging()
    assert len(logging.getLogger(api_v2.REQUEST_LOGGER_NAME).handlers) == before
