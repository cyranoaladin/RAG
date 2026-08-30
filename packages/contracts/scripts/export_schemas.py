"""Export deterministic JSON Schema artifacts from the canonical Pydantic models."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
CONTRACT_VERSION = "0.5"
PACKAGE_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
    "version"
]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nexus_contracts import (  # noqa: E402
    ChatRequest,
    ChatResponse,
    ChatPayload,
    InternalIdentity,
    InternalIdentityEnvelope,
    PilotRetrievalScopeArtifact,
    RetrievalScopeArtifactV2,
    RetrievalError,
    RetrievalRequest,
    RetrievalResponse,
    ResourceRegistryBootstrap,
    ServableCorpusIndex,
    ServableCorpusManifest,
    ReviewDecisionPayload,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewQueuePayload,
    ReviewQueueResponse,
    SearchPayload,
)

Model = TypeVar("Model", bound=BaseModel)
SCHEMAS: dict[str, type[BaseModel]] = {
    "retrieval-request.json": RetrievalRequest,
    "retrieval-response.json": RetrievalResponse,
    "retrieval-error.json": RetrievalError,
    "resource-registry-bootstrap-v1.json": ResourceRegistryBootstrap,
    "servable-corpus-index-v1.json": ServableCorpusIndex,
    "servable-corpus-manifest-v1.json": ServableCorpusManifest,
    "review-decision-payload.json": ReviewDecisionPayload,
    "review-decision-request.json": ReviewDecisionRequest,
    "review-decision-response.json": ReviewDecisionResponse,
    "review-queue-payload.json": ReviewQueuePayload,
    "review-queue-response.json": ReviewQueueResponse,
    "chat-request.json": ChatRequest,
    "chat-response.json": ChatResponse,
    "chat-payload.json": ChatPayload,
    "internal-identity.json": InternalIdentity,
    "internal-identity-envelope.json": InternalIdentityEnvelope,
    "pilot-retrieval-scope-artifact.json": PilotRetrievalScopeArtifact,
    "retrieval-scope-artifact-v2.json": RetrievalScopeArtifactV2,
    "search-payload.json": SearchPayload,
}


def schema_bytes(filename: str, model: type[Model]) -> bytes:
    schema = model.model_json_schema()
    schema["$id"] = f"https://nexusreussite.academy/contracts/v{CONTRACT_VERSION}/{filename}"
    return (json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def lock_bytes(schemas: dict[str, bytes]) -> bytes:
    lock = {
        "packageVersion": PACKAGE_VERSION,
        "schemas": {
            filename: {
                "$id": (
                    "https://nexusreussite.academy/contracts/"
                    f"v{CONTRACT_VERSION}/{filename}"
                ),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for filename, content in sorted(schemas.items())
        },
    }
    return (json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def export(output: Path, *, check: bool) -> int:
    expected = {
        filename: schema_bytes(filename, model) for filename, model in SCHEMAS.items()
    }
    expected["contracts.lock.json"] = lock_bytes(expected)
    if check:
        if not output.is_dir():
            return 1
        actual = {path.name for path in output.glob("*.json")}
        return int(
            actual != set(expected)
            or any(
                not (output / filename).is_file()
                or (output / filename).read_bytes() != content
                for filename, content in expected.items()
            )
        )
    output.mkdir(parents=True, exist_ok=True)
    for filename, content in expected.items():
        (output / filename).write_bytes(content)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "schema")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    return export(args.output, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
