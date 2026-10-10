"""L'image Worker B contient les imports nécessaires à son entrée CLI."""

from pathlib import Path


def test_worker_installs_release_chain_package() -> None:
    dockerfile = (
        Path(__file__).resolve().parents[1] / "infra/Dockerfile.ingestion-worker"
    ).read_text(encoding="utf-8")
    assert "COPY packages/release-chain /tmp/nexus-release-chain" in dockerfile
    assert "pip install --no-cache-dir /tmp/nexus-release-chain" in dockerfile
