"""Banc de qualification du comportement sous concurrence (CONCURRENCE).

Ce banc mesure, il ne juge pas : il écrit des mesures brutes, et c'est
`scripts/qualification/verify_concurrency_load.py` qui les confronte au budget
déclaré (`docs/reports/go_live/concurrency_load_budget.json`) puis scelle la
preuve, une fois les conteneurs détruits et les résidus comptés.

1. PostgreSQL/pgvector éphémère et ingestion réelle de la release multilevel.
2. API de retrieval réelle (uvicorn, E5 et reranker locaux), aucun mock.
3. Référence séquentielle, puis N requêtes `/search/v2` sous C clients concurrents.
4. Chaque réponse est vérifiée : résultats, citations, artefact attendu retrouvé.
5. Connexions PostgreSQL du rôle de retrieval échantillonnées pendant la charge,
   puis recomptées après l'arrêt du moteur (fuite).
6. Cardinalités et empreinte de contenu de la base comparées avant/après (corruption).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest

from tests.integration.test_multilevel_real_ingestion import (
    E5_INVENTORY_SHA256,
    E5_PATH,
    ENGINE_ROOT,
    EXPECTED_CHUNKS,
    RELEASE_PATH,
    RELEASE_SHA256,
    REPOSITORY_ROOT,
    RERANKER_INVENTORY_SHA256,
    RERANKER_PATH,
    SEARCH_CASES,
    TARGET_COLLECTIONS,
    _identity_token,
    _search_payload,
    free_port,
    run_multilevel_ingestion_and_publication,
)

pytest_plugins = ["tests.integration.test_multilevel_real_ingestion"]

RAW_PATH_ENV = "NEXUS_CONCURRENCY_RAW_MEASUREMENTS_PATH"

if not os.environ.get("NEXUS_REQUIRE_DOCKER", "").strip() or not all(
    os.environ.get(name, "").strip()
    for name in (
        "NEXUS_MULTILEVEL_PDF_MIRROR",
        "NEXUS_MULTILEVEL_PII_EVIDENCE_PATH",
        "RAG_EMBEDDING_MODEL_CACHE_DIR",
        "RAG_EMBEDDING_MODEL_INVENTORY_SHA256",
        "RAG_RERANKER_MODEL_CACHE_DIR",
        "RAG_RERANKER_MODEL_INVENTORY_SHA256",
        RAW_PATH_ENV,
    )
):
    pytest.skip("concurrency load qualification not requested", allow_module_level=True)


BUDGET_PATH = REPOSITORY_ROOT / "docs/reports/go_live/concurrency_load_budget.json"
RETRIEVAL_ROLE = "multilevel_retrieval"
COUNTED_TABLES = ("rag_chunks", "rag_artifacts", "rag_artifact_placements")


def _database_snapshot(admin_dsn: str) -> dict[str, Any]:
    """Cardinalités et empreinte du contenu complet, vecteurs compris."""
    with psycopg.connect(admin_dsn) as conn:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
            for table in COUNTED_TABLES
        }
        digest = hashlib.sha256()
        for table in COUNTED_TABLES:
            rows = conn.execute(
                f"SELECT md5(t::text) FROM {table} t ORDER BY 1"  # noqa: S608
            ).fetchall()
            for (row_md5,) in rows:
                digest.update(f"{table}:{row_md5}\n".encode())
        duplicates = conn.execute(
            "SELECT COUNT(*) FROM (SELECT chunk_id FROM rag_chunks "
            "GROUP BY chunk_id HAVING COUNT(*) > 1) duplicate"
        ).fetchone()[0]
    return {"counts": counts, "content_sha256": digest.hexdigest(), "duplicate_chunk_ids": duplicates}


def _retrieval_connections(admin_dsn: str) -> int:
    with psycopg.connect(admin_dsn) as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM pg_stat_activity WHERE usename = %s",
                (RETRIEVAL_ROLE,),
            ).fetchone()[0]
        )


class _ConnectionSampler(threading.Thread):
    def __init__(self, admin_dsn: str) -> None:
        super().__init__(daemon=True)
        self._admin_dsn = admin_dsn
        self._stop_event = threading.Event()
        self.samples: list[int] = []

    def run(self) -> None:
        with psycopg.connect(self._admin_dsn, autocommit=True) as conn:
            while not self._stop_event.is_set():
                self.samples.append(
                    int(
                        conn.execute(
                            "SELECT COUNT(*) FROM pg_stat_activity WHERE usename = %s",
                            (RETRIEVAL_ROLE,),
                        ).fetchone()[0]
                    )
                )
                self._stop_event.wait(0.1)

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=10)


def _one_request(
    client: httpx.Client, headers: Mapping[str, str], scope_id: str, case: Any
) -> dict[str, Any]:
    started = time.perf_counter()
    outcome = "ok"
    status: int | None = None
    detail: str | None = None
    try:
        response = client.post(
            "/search/v2", headers=dict(headers), json=_search_payload(scope_id, case.query)
        )
        status = response.status_code
        if status != 200:
            outcome, detail = "error", f"http_{status}"
        else:
            results = response.json().get("results") or []
            if not results:
                outcome, detail = "error", "empty_results"
            elif any(
                not (r.get("citation") or {}).get("source_uri")
                or not isinstance((r.get("citation") or {}).get("page"), int)
                for r in results
            ):
                outcome, detail = "error", "missing_citation"
            elif case.expected_artifact_sha256 not in {
                str((r.get("metadata") or {}).get("content_sha256")) for r in results
            }:
                outcome, detail = "error", "expected_artifact_not_returned"
    except httpx.TimeoutException:
        outcome, detail = "timeout", "client_timeout"
    except httpx.HTTPError as exc:
        outcome, detail = "error", type(exc).__name__
    return {
        "scope_id": scope_id,
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "status": status,
        "outcome": outcome,
        "detail": detail,
    }


def _run_concurrency_load(product_pg: Mapping[str, str], tmp_path: Path) -> dict[str, Any]:
    budget_bytes = BUDGET_PATH.read_bytes()
    budget = json.loads(budget_bytes)
    profile = budget["load_profile"]
    concurrency = int(profile["concurrent_clients"])
    total_requests = int(profile["measured_requests_total"])
    warmup_requests = int(profile["warmup_requests"])
    client_timeout_s = float(profile["client_timeout_ms"]) / 1000

    admin_dsn = product_pg["admin_dsn"]
    bff_token = secrets.token_urlsafe(48)
    identity_secret = secrets.token_urlsafe(48)
    api_client_token = secrets.token_urlsafe(32)
    token_issuer = "concurrency-http-bff"
    token_audience = "concurrency-rag-engine"
    identity_issuer = "concurrency-nexus-sso"
    identity_audience = "concurrency-nexus-cockpit"
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"

    env = dict(os.environ)
    for name in (
        "RAG_RELEASE_MANIFEST_PATH",
        "RAG_RELEASE_MANIFEST_SHA256",
        "RAG_RELEASE_MANIFESTS_JSON",
        "RAG_API_CLIENTS_FILE",
    ):
        env.pop(name, None)
    env.update(
        {
            "PYTHONPATH": str(ENGINE_ROOT),
            "RAG_ENV": "production",
            "RAG_API_CLIENTS": json.dumps(
                [
                    {
                        "client_id": "concurrency-load-qualification",
                        "token_sha256": hashlib.sha256(api_client_token.encode()).hexdigest(),
                        "scopes": ["rag:search"],
                    }
                ]
            ),
            "RAG_BFF_SERVICE_TOKEN": bff_token,
            "NEXUS_INTERNAL_TOKEN_SECRET": identity_secret,
            "NEXUS_INTERNAL_TOKEN_ISSUER": token_issuer,
            "NEXUS_INTERNAL_TOKEN_AUDIENCE": token_audience,
            "NEXUS_SSO_ISSUER": identity_issuer,
            "NEXUS_SSO_AUDIENCE": identity_audience,
            "PG_RAG_DSN": product_pg["retrieval_dsn"],
            "PG_REVIEW_DSN": product_pg["review_dsn"],
            "RAG_COLLECTIONS_CONFIG": str(
                ENGINE_ROOT / "configs" / "staging" / "rag_collections_multilevel.yml"
            ),
            "RAG_RELEASE_MANIFESTS_JSON": json.dumps(
                [{"path": str(RELEASE_PATH), "sha256": RELEASE_SHA256}], separators=(",", ":")
            ),
            "RAG_EMBEDDING_MODEL_CACHE_DIR": str(E5_PATH),
            "RAG_EMBEDDING_MODEL_INVENTORY_SHA256": E5_INVENTORY_SHA256,
            "RAG_RERANKER_MODEL_CACHE_DIR": str(RERANKER_PATH),
            "RAG_RERANKER_MODEL_INVENTORY_SHA256": RERANKER_INVENTORY_SHA256,
            "EMBED_MODEL": "intfloat/multilingual-e5-large",
            "EMBED_DIM": "1024",
            "CUDA_VISIBLE_DEVICES": "",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
    )
    pool_max_size = int(env.get("PG_POOL_MAX_SIZE", "10"))

    snapshot_before = _database_snapshot(admin_dsn)
    assert snapshot_before["counts"]["rag_chunks"] == EXPECTED_CHUNKS
    connections_before_engine = _retrieval_connections(admin_dsn)

    engine_log = (tmp_path / "engine-concurrency.log").open("w")
    engine = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "src.ingestor.api_v2:app",
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        ],
        cwd=ENGINE_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=engine_log,
        text=True,
    )
    sampler = _ConnectionSampler(admin_dsn)
    sequential: list[dict[str, Any]] = []
    measured: list[dict[str, Any]] = []
    load_wall_s = 0.0
    connections_idle_after_load = -1
    try:
        deadline = time.monotonic() + 300
        with httpx.Client(base_url=base_url, timeout=30.0) as probe:
            while True:
                assert engine.poll() is None, "uvicorn exited before readiness"
                try:
                    if probe.get("/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                assert time.monotonic() < deadline, "engine readiness deadline exceeded"
                time.sleep(0.25)

        def mint_headers() -> dict[str, dict[str, str]]:
            return {
                scope_id: {
                    "Authorization": f"Bearer {bff_token}",
                    "X-RAG-API-Key": api_client_token,
                    "X-Nexus-Identity": _identity_token(
                        scope_id,
                        secret=identity_secret,
                        issuer=token_issuer,
                        audience=token_audience,
                        identity_issuer=identity_issuer,
                        identity_audience=identity_audience,
                    ),
                }
                for scope_id in SEARCH_CASES
            }

        suite = [(scope_id, case) for scope_id, cases in SEARCH_CASES.items() for case in cases]
        assert len(suite) == TARGET_COLLECTIONS * 3

        # Échauffement (chargement paresseux des modèles) : non mesuré, délai large.
        headers = mint_headers()
        with httpx.Client(base_url=base_url, timeout=120.0) as warm:
            for scope_id, case in suite[:warmup_requests]:
                warmed = _one_request(warm, headers[scope_id], scope_id, case)
                assert warmed["outcome"] == "ok", warmed

        # Référence séquentielle : une requête à la fois, même délai client que la charge.
        with httpx.Client(base_url=base_url, timeout=client_timeout_s) as seq:
            for scope_id, case in suite:
                sequential.append(_one_request(seq, headers[scope_id], scope_id, case))

        # Charge concurrente mesurée.
        headers = mint_headers()
        local = threading.local()

        def task(index: int) -> dict[str, Any]:
            if not hasattr(local, "client"):
                local.client = httpx.Client(base_url=base_url, timeout=client_timeout_s)
            scope_id, case = suite[index % len(suite)]
            return _one_request(local.client, headers[scope_id], scope_id, case)

        sampler.start()
        load_started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            measured = list(pool.map(task, range(total_requests)))
        load_wall_s = time.perf_counter() - load_started
        time.sleep(2.0)
        connections_idle_after_load = _retrieval_connections(admin_dsn)
        sampler.stop()
    finally:
        if sampler.is_alive():
            sampler.stop()
        engine.terminate()
        try:
            engine.wait(timeout=20)
        except subprocess.TimeoutExpired:
            engine.kill()
            engine.wait(timeout=20)
        engine_log.close()

    time.sleep(1.0)
    connections_after_engine_stop = _retrieval_connections(admin_dsn)
    snapshot_after = _database_snapshot(admin_dsn)

    return {
        "kind": "NEXUS-CONCURRENCY-LOAD-RAW-MEASUREMENTS-V1",
        "budget_sha256": hashlib.sha256(budget_bytes).hexdigest(),
        "load_profile_executed": {
            "concurrent_clients": concurrency,
            "measured_requests_total": total_requests,
            "warmup_requests": warmup_requests,
            "client_timeout_ms": profile["client_timeout_ms"],
            "endpoint": "POST /search/v2",
            "distinct_queries": len(suite),
            "collections": TARGET_COLLECTIONS,
        },
        "engine": {
            "entrypoint": "uvicorn src.ingestor.api_v2:app",
            "rag_env": "production",
            "real_embedding_model": "intfloat/multilingual-e5-large",
            "embedding_inventory_sha256": E5_INVENTORY_SHA256,
            "reranker_inventory_sha256": RERANKER_INVENTORY_SHA256,
            "release_sha256": RELEASE_SHA256,
            "pg_pool_max_size": pool_max_size,
            "mock_detected": False,
            "engine_exit_code": engine.returncode,
        },
        "corpus": {
            "indexed_chunks": snapshot_before["counts"]["rag_chunks"],
            "expected_chunks": EXPECTED_CHUNKS,
        },
        "database_targets": [
            {"dsn_host": "127.0.0.1", "role": role, "ephemeral_docker_container": True}
            for role in ("admin", RETRIEVAL_ROLE, "multilevel_review")
        ],
        "sequential_baseline": sequential,
        "measured_requests": measured,
        "load_wall_seconds": round(load_wall_s, 3),
        "db_connections": {
            "role": RETRIEVAL_ROLE,
            "before_engine_start": connections_before_engine,
            "samples_count": len(sampler.samples),
            "peak_during_load": max(sampler.samples) if sampler.samples else -1,
            "idle_after_load": connections_idle_after_load,
            "after_engine_stop": connections_after_engine_stop,
        },
        "database_snapshot_before": snapshot_before,
        "database_snapshot_after": snapshot_after,
    }


def test_concurrency_load_against_real_engine(
    control_pg: dict[str, str],
    product_pg: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    request: pytest.FixtureRequest,
) -> None:
    run_multilevel_ingestion_and_publication(
        control_pg, product_pg, tmp_path, monkeypatch, capsys, request
    )
    raw = _run_concurrency_load(product_pg, tmp_path)
    Path(os.environ[RAW_PATH_ENV]).write_text(
        json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    # Le banc n'affirme que sa propre validité ; le budget est jugé par le scelleur.
    assert len(raw["measured_requests"]) == raw["load_profile_executed"]["measured_requests_total"]
    assert raw["db_connections"]["samples_count"] > 0
