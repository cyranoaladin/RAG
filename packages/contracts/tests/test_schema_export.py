from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path


REVIEW_SCHEMAS = {
    "review-decision-payload.json": "ReviewDecisionPayload",
    "review-decision-request.json": "ReviewDecisionRequest",
    "review-decision-response.json": "ReviewDecisionResponse",
    "review-queue-payload.json": "ReviewQueuePayload",
    "review-queue-response.json": "ReviewQueueResponse",
}


def test_package_version_is_0_5_0() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    assert pyproject["project"]["version"] == "0.5.0"


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
        *REVIEW_SCHEMAS,
        "search-payload.json",
    }
    assert {path.name for path in first.glob("*.json")} == expected
    for filename in expected:
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
        assert f"/v0.5/{filename}" in (first / filename).read_text()


def test_cockpit_generator_declares_review_schemas_and_validators() -> None:
    root = Path(__file__).resolve().parents[3]
    generator = (
        root / "services" / "cockpit" / "scripts" / "generate-contracts.mjs"
    ).read_text()

    for filename, model_name in REVIEW_SCHEMAS.items():
        assert f"['{filename}', '{model_name}']" in generator
        assert f"'{model_name}'" in generator.partition("const validatorNames = [")[2]
