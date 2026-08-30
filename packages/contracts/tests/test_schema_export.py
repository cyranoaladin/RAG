from __future__ import annotations

import subprocess
import sys
import tomllib
import hashlib
import json
from pathlib import Path


REVIEW_SCHEMAS = {
    "review-decision-payload.json": "ReviewDecisionPayload",
    "review-decision-request.json": "ReviewDecisionRequest",
    "review-decision-response.json": "ReviewDecisionResponse",
    "review-queue-payload.json": "ReviewQueuePayload",
    "review-queue-response.json": "ReviewQueueResponse",
}


def test_package_version_is_0_15_0() -> None:
    """0.15.0 ajoute les manifests servables sans rupture des contrats V1."""
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    assert pyproject["project"]["version"] == "0.15.0"


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
        "retrieval-error.json",
        "resource-registry-bootstrap-v1.json",
        "resource-registry-snapshot-v1.json",
        "servable-corpus-index-v1.json",
        "servable-corpus-manifest-v1.json",
        "chat-request.json",
        "chat-response.json",
        "chat-payload.json",
        "internal-identity-envelope.json",
        "internal-identity.json",
        "pilot-retrieval-scope-artifact.json",
        "retrieval-scope-artifact-v2.json",
        *REVIEW_SCHEMAS,
        "search-payload.json",
    }
    assert {path.name for path in first.glob("*.json")} == {
        *expected,
        "contracts.lock.json",
    }
    for filename in expected:
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
        assert f"/v0.5/{filename}" in (first / filename).read_text()

    first_lock = json.loads((first / "contracts.lock.json").read_text())
    second_lock = json.loads((second / "contracts.lock.json").read_text())
    assert first_lock == second_lock
    assert first_lock["packageVersion"] == "0.15.0"
    assert set(first_lock["schemas"]) == expected
    for filename in expected:
        schema = (first / filename).read_bytes()
        assert first_lock["schemas"][filename] == {
            "$id": (
                "https://nexusreussite.academy/contracts/"
                f"v0.5/{filename}"
            ),
            "sha256": hashlib.sha256(schema).hexdigest(),
        }


def test_cockpit_generator_declares_review_schemas_and_validators() -> None:
    root = Path(__file__).resolve().parents[3]
    generator = (
        root / "services" / "cockpit" / "scripts" / "generate-contracts.mjs"
    ).read_text()

    for filename, model_name in REVIEW_SCHEMAS.items():
        assert f"['{filename}', '{model_name}']" in generator
        assert f"'{model_name}'" in generator.partition("const validatorNames = [")[2]


def test_cockpit_generator_declares_retrieval_scope_v2_schema() -> None:
    root = Path(__file__).resolve().parents[3]
    generator = (
        root / "services" / "cockpit" / "scripts" / "generate-contracts.mjs"
    ).read_text()

    assert "['retrieval-scope-artifact-v2.json', 'RetrievalScopeArtifactV2']" in generator
    assert "'RetrievalScopeArtifactV2'" in generator.partition("const validatorNames = [")[2]
