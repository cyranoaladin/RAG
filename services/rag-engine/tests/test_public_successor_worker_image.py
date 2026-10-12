"""L'image Worker A/B publique emporte ses modules d'entrée réels."""

import os
import subprocess
from pathlib import Path

import pytest


def test_multilevel_worker_copies_public_successor_db_guard() -> None:
    dockerfile = (
        Path(__file__).resolve().parents[1]
        / "infra/Dockerfile.multilevel-worker-production"
    ).read_text(encoding="utf-8")
    instructions = {
        line.strip() for line in dockerfile.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert (
        "COPY services/rag-engine/src/ingestor/public_successor_db_guard.py "
        "/app/services/rag-engine/src/ingestor/public_successor_db_guard.py"
    ) in instructions


def test_public_successor_cli_imports_inside_built_image() -> None:
    image = os.environ.get("NEXUS_PUBLIC_WORKER_IMAGE", "").strip()
    if not image:
        pytest.skip("set NEXUS_PUBLIC_WORKER_IMAGE to test a built worker image")
    result = subprocess.run(
        [
            "docker", "run", "--rm", "--network", "none", "--read-only",
            "--tmpfs", "/tmp", "--security-opt", "no-new-privileges:true",
            "--entrypoint", "python", image, "-c",
            "import ingestor.ingestion_worker.public_text_enqueue_cli; "
            "import ingestor.ingestion_worker.public_text_publication_resume_cli; "
            "print('PUBLIC_WORKER_ENTRYPOINTS_IMPORT_OK')",
        ],
        capture_output=True, text=True, check=False, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PUBLIC_WORKER_ENTRYPOINTS_IMPORT_OK"
