"""L'image Worker B contient les imports nécessaires à son entrée CLI."""

from pathlib import Path

import pytest


def assert_worker_release_chain_dependency(dockerfile: str) -> None:
    """Inspect only active Dockerfile instructions in their build order."""
    instructions = [
        line.strip() for line in dockerfile.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    copies = [
        index for index, line in enumerate(instructions)
        if line.split() == ["COPY", "packages/release-chain", "/tmp/nexus-release-chain"]
    ]
    installs = [
        index for index, line in enumerate(instructions)
        if line.split()[:4] == [
            "RUN", "pip", "install", "--no-cache-dir",
        ] and line.split()[4:5] == ["/tmp/nexus-release-chain"]
    ]
    assert len(copies) == len(installs) == 1
    assert copies[0] < installs[0]


def test_worker_installs_release_chain_package() -> None:
    dockerfile = (
        Path(__file__).resolve().parents[1] / "infra/Dockerfile.ingestion-worker"
    ).read_text(encoding="utf-8")
    assert_worker_release_chain_dependency(dockerfile)


@pytest.mark.parametrize("dockerfile", [
    "# COPY packages/release-chain /tmp/nexus-release-chain\n"
    "RUN pip install --no-cache-dir /tmp/nexus-release-chain\n",
    "COPY packages/release-chain /tmp/nexus-release-chain\n"
    "# RUN pip install --no-cache-dir /tmp/nexus-release-chain\n",
    "RUN pip install --no-cache-dir /tmp/nexus-release-chain\n"
    "COPY packages/release-chain /tmp/nexus-release-chain\n",
])
def test_worker_dependency_refuses_comment_or_install_before_copy(dockerfile: str) -> None:
    with pytest.raises(AssertionError):
        assert_worker_release_chain_dependency(dockerfile)
