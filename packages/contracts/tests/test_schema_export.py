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

# LOT44a — contrats canoniques du moteur d'ingestion.
INGESTION_SCHEMAS = {
    "collection-profile.json": "CollectionProfile",
    "search-plan.json": "SearchPlan",
    "resource-candidate.json": "ResourceCandidate",
    "artifact-record.json": "ArtifactRecord",
    "routing-decision.json": "RoutingDecision",
    "quality-report.json": "QualityReport",
    "ingestion-run.json": "IngestionRun",
    "coverage-snapshot.json": "CoverageSnapshot",
}


def test_package_version_is_0_6_0() -> None:
    """LOT44a (ADR-0024) : ajout rétro-compatible de huit modèles canoniques
    d'ingestion — bump mineur selon la règle SemVer d'ADR-0002 (« ajout
    rétro-compatible » = mineur)."""
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    assert pyproject["project"]["version"] == "0.6.0"


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
        *INGESTION_SCHEMAS,
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


def test_cockpit_generator_declares_ingestion_schemas_and_validators() -> None:
    root = Path(__file__).resolve().parents[3]
    generator = (
        root / "services" / "cockpit" / "scripts" / "generate-contracts.mjs"
    ).read_text()

    for filename, model_name in INGESTION_SCHEMAS.items():
        assert f"['{filename}', '{model_name}']" in generator
        assert f"'{model_name}'" in generator.partition("const validatorNames = [")[2]


def test_ingestion_schema_ids_use_the_contract_version() -> None:
    root = Path(__file__).resolve().parents[1]
    schema_dir = root / "schema"

    for filename in INGESTION_SCHEMAS:
        content = (schema_dir / filename).read_text(encoding="utf-8")
        assert f"/v0.5/{filename}" in content


def test_ingestion_schemas_reference_a_shared_resource_scope_definition() -> None:
    """Les huit modèles canoniques portent tous le scope complet — vérifié
    ici au niveau JSON Schema (pas seulement au niveau pydantic) pour
    prouver que la contrainte survit à l'export."""
    import json

    root = Path(__file__).resolve().parents[1]
    schema_dir = root / "schema"

    for filename in INGESTION_SCHEMAS:
        schema = json.loads((schema_dir / filename).read_text(encoding="utf-8"))
        required = schema.get("required", [])
        assert "scope" in required, f"{filename} doit rendre 'scope' obligatoire"
        assert "ResourceScope" in schema.get("$defs", {}), (
            f"{filename} doit référencer la définition partagée ResourceScope"
        )
