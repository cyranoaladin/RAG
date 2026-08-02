"""Test du démarrage de l'ingestor dans l'image Docker aplatie."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_SRC = REPOSITORY_ROOT / "packages" / "contracts" / "src"
INGESTOR_SRC = REPOSITORY_ROOT / "services" / "rag-engine" / "src" / "ingestor"


def test_ingestor_api_starts_from_flattened_runtime(tmp_path: Path) -> None:
    code = "\n".join(
        (
            "import sys",
            f"sys.path.insert(0, {str(CONTRACTS_SRC)!r})",
            f"sys.path.insert(0, {str(INGESTOR_SRC)!r})",
            "import api",
            "print(api.app.title)",
        )
    )

    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "RAG Ingestor API"
