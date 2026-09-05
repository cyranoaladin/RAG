"""POST /search/v2 — filtre de notion honoré, accès journalisé sans la requête.

Deux propriétés, exercées à la frontière HTTP réelle :

1. `need.notions` n'est plus refusé : il descend jusqu'au magasin de
   candidats, **conjoint** au prédicat de placement (la preuve qu'il ne peut
   pas élargir l'accès est faite sur base réelle par
   `tests/integration/test_c6_chunk_metadata_filters_never_widen_placement.py`) ;
2. chaque requête produit une ligne de journal exploitable — et cette ligne
   ne contient jamais le texte de la requête.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor.retrieval_observability import ACCESS_LOGGER_NAME  # noqa: E402
from ingestor.retrieval_scope_v2 import ServerRetrievalScope  # noqa: E402

from nexus_contracts import Rights  # noqa: E402  # isort: skip

CFG = {
    "version": 3,
    "domains": {"education": {"retrievable": True}},
    "collections": {
        "rag_nexus_nsi_terminale_specialite": {
            "matiere": "nsi",
            "niveau": "terminale",
            "voie": "gen",
            "statut": "specialite",
            "domain": "education",
            "instanciee": True,
        }
    },
}

SCOPE = ServerRetrievalScope(
    tenant="libre_terminale",
    niveau="terminale",
    voie="generale",
    matiere="nsi",
    statut_enseignement="specialite",
    candidat="individuel",
    audiences=("libre", "tous"),
    rights=(Rights.officiel_public,),
    visibilities=("public",),
    school_year="2026-2027",
    collection="rag_nexus_nsi_terminale_specialite",
    programme_version="BOEN_special_8_2019-07-25",
    scope_id="scope-obs",
    scope_digest="a" * 64,
    source_sha256="b" * 64,
)

QUERY = "comment fonctionne la recursivite terminale"


def _payload(*, notions: list[str] | None = None) -> dict[str, object]:
    need: dict[str, object] = {"intent": "context", "query": QUERY}
    if notions is not None:
        need["notions"] = notions
    return {
        "student_profile": {
            "niveau": "terminale",
            "voie": "generale",
            "matieres": ["nsi"],
            "statut_enseignement": "specialite",
            "candidat": "individuel",
            "school_year": "2026-2027",
            "zone": "libre",
        },
        "need": need,
        "retrieval": {"k": 5, "hybrid": True, "rerank": True, "include_citations": True},
    }


def _hit():
    from ingestor.retrieval_hybrid_v2 import HybridHit, RetrievalCandidate

    return HybridHit(
        candidate=RetrievalCandidate(
            chunk_id="chunk-1",
            doc_id="doc-1",
            source_label="Programme NSI",
            source_uri="https://example.edu/doc-1",
            rights="officiel_public",
            type_doc="programme_officiel",
            text="La recursivite definit une fonction par elle-meme.",
            page_start=3,
            vector=(1.0,) + (0.0,) * 1023,
            review_status="reviewed",
            dense_score=0.81,
            lexical_score=0.42,
        ),
        dense_rank=1,
        lexical_rank=1,
        rrf_score=0.016,
        rerank_score=2.75,
        mmr_score=0.612,
        score_final=0.884,
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ingestor import retrieval_v2_endpoint as endpoint

    verified = SimpleNamespace(
        artifact=SimpleNamespace(
            subjects=(
                SimpleNamespace(
                    matiere="nsi",
                    collection="rag_nexus_nsi_terminale_specialite",
                ),
            )
        )
    )
    monkeypatch.setattr(endpoint, "load_collection_config", lambda: CFG)
    monkeypatch.setattr(
        endpoint,
        "_require_retrieval_identity",
        lambda _request, *, endpoint, payload=None: verified,
    )
    monkeypatch.setattr(
        endpoint,
        "effective_signed_collections",
        lambda _verified: ("rag_nexus_nsi_terminale_specialite",),
    )
    monkeypatch.setattr(
        endpoint,
        "build_server_retrieval_scope",
        lambda _verified, *, collection, collection_config: replace(
            SCOPE, collection=collection
        ),
    )
    monkeypatch.setattr(endpoint, "_check_retrievable", lambda *_args: {})

    app = FastAPI()
    app.include_router(endpoint.router)
    return endpoint, TestClient(app)


def _install_recording_pipeline(endpoint, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Capturer ce que l'endpoint transmet, et renseigner les diagnostics."""
    seen: dict[str, object] = {}

    def retrieve(query, collection, k, scope, *, metadata_filters=None, diagnostics=None):
        seen["query"] = query
        seen["metadata_filters"] = metadata_filters
        if diagnostics is not None:
            diagnostics.embedding_status = "ok"
            diagnostics.dense_status = "ok"
            diagnostics.lexical_status = "empty"
            diagnostics.reranker_status = "ok"
            diagnostics.dense_count = 7
            diagnostics.lexical_count = 0
            diagnostics.candidate_count = 7
            diagnostics.returned_count = 1
        return [_hit()]

    monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", retrieve, raising=False)
    return seen


def test_une_notion_demandee_descend_jusqu_au_magasin(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    endpoint, http = client
    seen = _install_recording_pipeline(endpoint, monkeypatch)

    response = http.post("/search/v2", json=_payload(notions=["recursivite"]))

    assert response.status_code == 200
    filters = seen["metadata_filters"]
    assert filters is not None and filters.notions == ("recursivite",)
    assert response.json()["filters_applied"]["notions"] == ["recursivite"]


def test_sans_notion_aucun_filtre_n_est_transmis(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le prédicat de placement décide seul quand rien n'est demandé."""
    endpoint, http = client
    seen = _install_recording_pipeline(endpoint, monkeypatch)

    response = http.post("/search/v2", json=_payload())

    assert response.status_code == 200
    filters = seen["metadata_filters"]
    assert filters is not None and filters.is_empty
    assert "notions" not in response.json()["filters_applied"]


def test_une_notion_vide_est_refusee_avant_toute_requete(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    endpoint, http = client
    seen = _install_recording_pipeline(endpoint, monkeypatch)

    response = http.post("/search/v2", json=_payload(notions=["   "]))

    assert response.status_code == 422
    assert "query" not in seen


def test_trop_de_notions_est_refuse(client, monkeypatch: pytest.MonkeyPatch) -> None:
    endpoint, http = client
    _install_recording_pipeline(endpoint, monkeypatch)

    response = http.post(
        "/search/v2", json=_payload(notions=[f"notion-{index}" for index in range(17)])
    )

    assert response.status_code == 422


def _access_lines(caplog: pytest.LogCaptureFixture) -> list[dict]:
    return [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == ACCESS_LOGGER_NAME
    ]


def test_chaque_requete_produit_une_ligne_d_acces_exploitable(
    client, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    endpoint, http = client
    _install_recording_pipeline(endpoint, monkeypatch)

    with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER_NAME):
        response = http.post(
            "/search/v2",
            json=_payload(notions=["recursivite"]),
            headers={"X-Request-ID": "corr-42"},
        )

    assert response.status_code == 200
    (line,) = _access_lines(caplog)
    assert line["event"] == "retrieval_access"
    assert line["request_id"] == "corr-42"
    assert line["endpoint"] == "/search/v2"
    assert line["client_id"] == "unattributed"
    assert line["granted_scopes"] == ["rag:search"]
    assert line["status_code"] == 200
    assert line["filters"]["collection"] == "rag_nexus_nsi_terminale_specialite"
    assert line["filters"]["notions"] == ["recursivite"]
    assert line["candidate_count"] == 7
    assert line["returned_count"] == 1
    assert line["dense_status"] == "ok"
    assert line["lexical_status"] == "empty"
    assert line["reranker_status"] == "ok"
    assert isinstance(line["latency_ms"], float)


def test_le_journal_ne_contient_jamais_la_requete_brute(
    client, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Une requête d'élève peut nommer une personne ou une difficulté.

    Elle ne quitte pas le processus : seule son empreinte et sa longueur
    sont journalisées."""
    import hashlib

    endpoint, http = client
    _install_recording_pipeline(endpoint, monkeypatch)

    with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER_NAME):
        http.post("/search/v2", json=_payload())

    (line,) = _access_lines(caplog)
    assert QUERY not in json.dumps(line, ensure_ascii=False)
    assert line["query_sha256"] == hashlib.sha256(QUERY.encode("utf-8")).hexdigest()
    assert line["query_length"] == len(QUERY)


def test_un_identifiant_de_correlation_hostile_est_remplace(
    client, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """L'en-tête vient du client : il est borné avant d'entrer dans un log."""
    endpoint, http = client
    _install_recording_pipeline(endpoint, monkeypatch)

    with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER_NAME):
        http.post(
            "/search/v2",
            json=_payload(),
            headers={"X-Request-ID": "a" * 500},
        )

    (line,) = _access_lines(caplog)
    assert line["request_id"] != "a" * 500
    assert len(line["request_id"]) == 32
