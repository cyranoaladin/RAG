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


def test_package_version_is_0_16_0() -> None:
    """0.16.0 (ADR-0052) publie 18 RetrievalScopeArtifactV2 supplémentaires.

    Évolution strictement additive : le registre passe de 31 à 49 scopes, les
    18 `_v1` de la release production restant packagés et inchangés. ADR-0045
    interdit de muter le `source_sha256` d'un scope publié — les enveloppes
    émises le référencent — de sorte qu'un rescellement de release ajoute des
    scopes au lieu d'en réécrire.

    Historique : 0.15.0 (ADR-0050) avait ajouté sixieme et cinquieme à l'enum
    Niveau, également sans rupture des contrats V1.
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


def test_cockpit_generator_declares_retrieval_scope_v2_schema() -> None:
    root = Path(__file__).resolve().parents[3]
    generator = (
        root / "services" / "cockpit" / "scripts" / "generate-contracts.mjs"
    ).read_text()

    assert "['retrieval-scope-artifact-v2.json', 'RetrievalScopeArtifactV2']" in generator
    assert "'RetrievalScopeArtifactV2'" in generator.partition("const validatorNames = [")[2]
