from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path


def test_package_version_is_0_4_0() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    assert pyproject["project"]["version"] == "0.4.0"


def test_schema_export_is_deterministic(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "export_schemas.py"
    first = tmp_path / "first"
    second = tmp_path / "second"

    for output in (first, second):
        subprocess.run(
            [sys.executable, str(script), "--output", str(output)],
            check=True,
            cwd=root,
        )

    expected = {
        "retrieval-request.json",
        "retrieval-response.json",
        "chat-request.json",
        "chat-response.json",
        "chat-payload.json",
        "internal-identity-envelope.json",
        "internal-identity.json",
        "pilot-retrieval-scope-artifact.json",
        "search-payload.json",
    }
    assert {path.name for path in first.glob("*.json")} == expected
    for filename in expected:
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
        assert f"/v0.4/{filename}" in (first / filename).read_text()
