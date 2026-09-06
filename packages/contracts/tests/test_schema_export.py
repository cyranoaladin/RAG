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


def test_package_version_is_0_16_0() -> None:
    """0.16.0 ajoute dix scopes de retrieval empaquetés (ADR-0048).

    Évolution publique ADDITIVE : une nouvelle population de ressources
    adressables, aucun schéma modifié, aucune rupture. Le dépôt applique à ce
    cas la MINEURE — ADR-0042 (0.11→0.12), ADR-0044 (0.12→0.13), ADR-0045
    (0.13→0.14, dix-huit scopes V2 ajoutés) et ARIA-B (0.14→0.15) l'ont fait
    avant nous.
    """
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    assert pyproject["project"]["version"] == "0.16.0"


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
        "retrieval-golden-suite-v1.json",
        "retrieval-evaluation-evidence-v1.json",
        "servable-corpus-index-v1.json",
        "servable-corpus-manifest-v1.json",
        "chat-request.json",
        "chat-response.json",
        "chat-payload.json",
        "internal-identity-envelope.json",
        "internal-identity.json",
        "pilot-retrieval-scope-artifact.json",
        "retrieval-scope-artifact-v2.json",
        "retrieval-scope-artifact-v3.json",
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
    assert first_lock["packageVersion"] == "0.16.0"
    assert set(first_lock["schemas"]) == expected
    fixture = root / "fixtures" / "internal-identity-envelope-v1.json"
    assert first_lock["fixtures"] == {
        "internal-identity-envelope-v1.json": {
            "sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        }
    }
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


def test_cockpit_generator_declares_retrieval_scope_v3_schema() -> None:
    root = Path(__file__).resolve().parents[3]
    generator = (
        root / "services" / "cockpit" / "scripts" / "generate-contracts.mjs"
    ).read_text(encoding="utf-8")

    assert "['retrieval-scope-artifact-v3.json', 'RetrievalScopeArtifactV3']" in generator
    assert "'RetrievalScopeArtifactV3'" in generator.partition("const validatorNames = [")[2]
