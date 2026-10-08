#!/usr/bin/env python3
"""Mesurer C0 contre l'API réelle du staging final, sans écrire dans sa base.

Ce banc utilise les 33 requêtes positives de la suite V4/V5 figée. Il ne
construit ni corpus de test ni identité de substitution : les enveloppes sont
émises par le client opérateur canonique et validées par le moteur servi.
Les credentials arrivent uniquement par environnement et n'entrent jamais
dans le rapport.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import psycopg
import threading
import urllib.parse

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
import rag_query  # noqa: E402

DEFAULT_BUDGET = REPOSITORY_ROOT / "docs/reports/go_live/concurrency_load_budget_final_v4_v5.json"
DEFAULT_SUITE = REPOSITORY_ROOT / "services/rag-engine/tests/fixtures/final_v4_v5_acceptance.json"


def _assert_canonical_input_paths(suite_path: Path, budget_path: Path) -> None:
    if suite_path.resolve() != DEFAULT_SUITE.resolve():
        raise ValueError("suite canonique finale requise")
    if budget_path.resolve() != DEFAULT_BUDGET.resolve():
        raise ValueError("budget canonique final requis")
    for path in (DEFAULT_SUITE, DEFAULT_BUDGET):
        subprocess.check_output(
            ["git", "-C", str(REPOSITORY_ROOT), "ls-files", "--error-unmatch", "--",
             str(path.relative_to(REPOSITORY_ROOT))],
            text=True,
        )


def _live_main_sha() -> str:
    """Lire la référence distante, sans croire le cache origin/main local."""
    output = subprocess.check_output(
        ["git", "-C", str(REPOSITORY_ROOT), "ls-remote", "origin", "refs/heads/main"],
        text=True,
        timeout=15,
    ).strip()
    parts = output.split("\t")
    if (len(parts) != 2 or parts[1] != "refs/heads/main" or len(parts[0]) != 40
            or any(char not in "0123456789abcdef" for char in parts[0])):
        raise ValueError("main distant introuvable ou invalide")
    return parts[0]


def validate_api_url(value: str) -> str:
    """Le banc staging ne doit jamais pointer vers un endpoint public/prod."""
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port != 18003
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("C0 exige une URL locale staging sans credential")
    return value.rstrip("/")


def nearest_rank(values: list[float], percentile: int) -> float:
    """Percentile par rang supérieur, y compris pour une petite population."""
    if not values or not 0 < percentile <= 100:
        raise ValueError("population ou percentile invalide")
    return sorted(values)[math.ceil(len(values) * percentile / 100) - 1]


def evaluate_measurement(measurement: Mapping[str, Any], budget_doc: Mapping[str, Any]) -> dict[str, Any]:
    """Verdict fermé sur la population réelle, jamais sur les seuls HTTP 200."""
    profile = budget_doc["load_profile"]
    limits = budget_doc["budget"]
    rows = measurement["requests"]
    expected = int(profile["measured_requests_total"])
    latencies = [float(row["latency_ms"]) for row in rows]
    errors = sum(row.get("outcome") not in {"ok", "timeout"} or row.get("status") not in {200, None}
                 for row in rows)
    timeouts = sum(row.get("outcome") == "timeout" for row in rows)
    http_503 = sum(row.get("status") == 503 for row in rows)
    db = measurement["db_connections"]
    p50 = nearest_rank(latencies, 50) if latencies else None
    p95 = nearest_rank(latencies, 95) if latencies else None
    p99 = nearest_rank(latencies, 99) if latencies else None
    checks = {
        "clients": measurement["concurrent_clients"] == profile["concurrent_clients"],
        "requests": len(rows) == expected,
        "valid_rows": all(
            row.get("outcome") == "ok"
            and row.get("status") == 200
            and isinstance(row.get("latency_ms"), (int, float))
            and 0 <= row["latency_ms"] <= profile["client_timeout_ms"]
            for row in rows
        ),
        "errors": errors <= limits["errors_max"],
        "error_rate": errors / expected <= limits["error_rate_max"],
        "timeouts": timeouts <= limits["timeouts_max"],
        "p50": p50 is not None and p50 <= limits["p50_ms_max"],
        "p95": p95 is not None and p95 <= limits["p95_ms_max"],
        "p99": p99 is not None and p99 <= limits["p99_ms_max"],
        "db_samples": db["samples_count"] > 0,
        "db_sampler": db.get("sampler_failure") is None,
        "db_connections": 0 <= db["peak_during_load"] <= limits["db_connections_peak_max"],
    }
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "requests": len(rows),
        "errors": errors,
        "timeouts": timeouts,
        "http_503": http_503,
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
        "db_connections_peak": db["peak_during_load"],
    }


def _cases(suite: Mapping[str, Any]) -> list[tuple[str, str, str, str]]:
    collections = suite["collections"]
    if len(collections) != 11:
        raise ValueError("C0 exige les 11 collections finales")
    cases: list[tuple[str, str, str, str]] = []
    for collection, spec in sorted(collections.items()):
        if len(spec["positive"]) != 3:
            raise ValueError(f"{collection}: trois cas positifs requis")
        for case in spec["positive"]:
            if case["collection"] != collection or not case["query"].strip():
                raise ValueError(f"{collection}: requête invalide")
            cases.append((collection, spec["scope_id"], case["query"], case["expected_content_sha256"]))
    return cases


def _db_connections(dsn: str) -> int:
    with psycopg.connect(
        dsn, autocommit=True, connect_timeout=2,
        options="-c default_transaction_read_only=on -c statement_timeout=2000",
    ) as conn:
        dbname, role = conn.execute("SELECT current_database(), current_user").fetchone()
        if dbname != "ragdb_profile_gate_v4" or role != "rag_reader":
            raise RuntimeError("cible DB ou rôle inattendu")
        return int(conn.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
            "AND usename=current_user AND pid <> pg_backend_pid()"
        ).fetchone()[0])


class _DbSampler(threading.Thread):
    def __init__(self, dsn: str) -> None:
        super().__init__(daemon=True)
        self.dsn = dsn
        self.samples: list[int] = []
        self.failure: str | None = None
        self.stop_event = threading.Event()

    def run(self) -> None:
        try:
            while not self.stop_event.is_set():
                self.samples.append(_db_connections(self.dsn))
                self.stop_event.wait(0.25)
        except Exception as exc:  # échec fermé, sans inclure le DSN dans le rapport
            self.failure = type(exc).__name__

    def stop(self) -> None:
        self.stop_event.set()
        self.join(timeout=10)
        if self.is_alive():
            self.failure = "SamplerJoinTimeout"


def _one_request(
    case: tuple[str, str, str, str],
    *,
    config: rag_query.ClientConfig,
    api_key: str,
    timeout_s: float,
    client: httpx.Client,
    identity_token: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    collection, scope_id, query, expected_sha = case
    started = time.perf_counter()
    status: int | None = None
    outcome, detail = "error", "transport"
    try:
        response = client.post(
            "/search/v2",
            headers={
                "Authorization": f"Bearer {config.bff_token}",
                "X-RAG-API-Key": api_key,
                "X-Nexus-Identity": identity_token,
            },
            json=payload,
            timeout=timeout_s,
        )
        status = response.status_code
        if status != 200:
            detail = f"http_{status}"
        else:
            parsed = rag_query.RetrievalResponse.model_validate(response.json())
            if not parsed.results:
                detail = "empty_results"
            elif any(
                result.metadata.get("collection") != collection
                or result.citation is None
                or not result.citation.source_uri.strip()
                or not result.citation.source_label.strip()
                or not isinstance(result.metadata.get("content_sha256"), str)
                or len(result.metadata["content_sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in result.metadata["content_sha256"])
                for result in parsed.results
            ):
                detail = "scope_or_citation"
            elif expected_sha not in {
                str(result.metadata.get("content_sha256")) for result in parsed.results
            }:
                detail = "expected_source_absent"
            else:
                outcome, detail = "ok", None
    except httpx.TimeoutException:
        outcome, detail = "timeout", "client_timeout"
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        outcome, detail = "error", type(exc).__name__
    return {
        "collection": collection,
        "scope_id": scope_id,
        "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
        "status": status,
        "outcome": outcome,
        "detail": detail,
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def _prepare_request(
    case: tuple[str, str, str, str], config: rag_query.ClientConfig
) -> tuple[str, dict[str, Any]]:
    token, artifact = rag_query.issue_scope_identity(case[1], config=config)
    payload = rag_query.build_request(case[2], artifact).model_dump(mode="json")
    return token, payload


def run_c0(
    *, suite_path: Path, budget_path: Path, api_url: str, environ: Mapping[str, str]
) -> dict[str, Any]:
    api_url = validate_api_url(api_url)
    _assert_canonical_input_paths(suite_path, budget_path)
    suite_bytes, budget_bytes = suite_path.read_bytes(), budget_path.read_bytes()
    suite, budget = json.loads(suite_bytes), json.loads(budget_bytes)
    registry_path = REPOSITORY_ROOT / suite["mixed_registry_path"]
    if hashlib.sha256(registry_path.read_bytes()).hexdigest() != suite["mixed_registry_sha256"]:
        raise ValueError("registre mixte divergent")
    checkout_sha = subprocess.check_output(
        ["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    origin_main_sha = _live_main_sha()
    if checkout_sha != origin_main_sha:
        raise ValueError("C0 exige le main courant, pas un ancien checkout")
    if subprocess.check_output(
        ["git", "-C", str(REPOSITORY_ROOT), "status", "--porcelain"], text=True
    ).strip():
        raise ValueError("checkout C0 modifié")
    cases = _cases(suite)
    profile = budget["load_profile"]
    if (profile["concurrent_clients"], profile["measured_requests_total"],
            profile["client_timeout_ms"]) != (8, 240, 7500):
        raise ValueError("profil C0 déclaré divergent")
    if any(budget["budget"][key] != value for key, value in {
        "p50_ms_max": 3000, "p95_ms_max": 6000, "p99_ms_max": 7500,
        "errors_max": 0, "error_rate_max": 0, "timeouts_max": 0,
        "db_connections_peak_max": 10,
    }.items()):
        raise ValueError("seuil C0 déclaré divergent")
    config = rag_query.load_client_config({**environ, "RAG_API_URL": api_url})
    api_key = environ.get("COCKPIT_STAGING_API_KEY", "")
    dsn = environ.get("PG_RAG_DSN", "")
    if not api_key or not dsn:
        raise ValueError("credentials staging absents")
    _db_connections(dsn)
    timeout_s = profile["client_timeout_ms"] / 1000
    warmup = int(profile["warmup_requests"])
    with httpx.Client(base_url=api_url) as client:
        for case in cases[:warmup]:
            token, payload = _prepare_request(case, config)
            result = _one_request(
                case, config=config, api_key=api_key, timeout_s=120,
                client=client, identity_token=token, payload=payload,
            )
            if result["outcome"] != "ok":
                raise RuntimeError(f"échauffement C0 refusé: {result['detail']}")
    # Une requête au plafond de 7,5 s sur 8 clients donne au maximum
    # 30 vagues (225 s), sous les 300 s de validité des enveloppes signées.
    prepared = [(case, *_prepare_request(case, config)) for case in cases]
    sampler = _DbSampler(dsn)
    sampler.start()
    started = time.perf_counter()
    try:
        with httpx.Client(base_url=api_url) as client:

            def request(index: int) -> dict[str, Any]:
                case, token, payload = prepared[index % len(prepared)]
                return _one_request(
                    case, config=config, api_key=api_key,
                    timeout_s=timeout_s, client=client,
                    identity_token=token, payload=payload,
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                rows = list(pool.map(request, range(240)))
    finally:
        sampler.stop()
    result: dict[str, Any] = {
        "kind": "NEXUS-FINAL-STAGING-C0-V1",
        "observed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checkout_sha": checkout_sha,
        "suite_sha256": hashlib.sha256(suite_bytes).hexdigest(),
        "mixed_registry_sha256": suite["mixed_registry_sha256"],
        "budget_sha256": hashlib.sha256(budget_bytes).hexdigest(),
        "api_url": api_url,
        "concurrent_clients": 8,
        "distinct_queries": len(cases),
        "load_wall_s": round(time.perf_counter() - started, 3),
        "requests": rows,
        "db_connections": {
            "samples_count": len(sampler.samples),
            "peak_during_load": max(sampler.samples) if sampler.samples else -1,
            "sampler_failure": sampler.failure,
        },
    }
    result["verdict"] = evaluate_measurement(result, budget)
    return result


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    """Écrire une preuve privée nouvelle ; une mesure précédente est immuable."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--budget", type=Path, default=DEFAULT_BUDGET)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if args.output.exists():
            raise FileExistsError("preuve C0 existante")
        report = run_c0(
            suite_path=args.suite, budget_path=args.budget,
            api_url=args.api_url, environ=os.environ,
        )
        write_report(args.output, report)
        print(json.dumps({"verdict": report["verdict"], "output": str(args.output)}, sort_keys=True))
        return 0 if report["verdict"]["pass"] else 1
    except Exception as exc:
        # Un échec de transport peut contenir des paramètres de connexion :
        # son type suffit au diagnostic public, jamais sa représentation.
        print(f"C0 refusé: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
