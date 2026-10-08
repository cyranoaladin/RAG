"""Le journal de recherche doit sortir du conteneur sous la configuration Uvicorn."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_retrieval_access_is_emitted_once_per_request_under_uvicorn_logging() -> None:
    src = Path(__file__).resolve().parents[1] / "src"
    script = """
import logging.config
from uvicorn.config import LOGGING_CONFIG

logging.config.dictConfig(LOGGING_CONFIG)
from ingestor.retrieval_observability import RetrievalAccessRecord, log_retrieval_access

for request_id in ("request-1", "request-2"):
    log_retrieval_access(RetrievalAccessRecord(
        request_id=request_id,
        endpoint="/search/v2",
        client_id="unattributed",
        granted_scopes=(),
        status_code=401,
        latency_ms=1.5,
        cause="authentication",
    ))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(src)},
    )

    lines = [line for line in (result.stdout + result.stderr).splitlines() if line]
    records = [json.loads(line) for line in lines]
    assert [record["request_id"] for record in records] == ["request-1", "request-2"]
    assert all(record["event"] == "retrieval_access" for record in records)
    assert all(record["cause"] == "authentication" for record in records)
