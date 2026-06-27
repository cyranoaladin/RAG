"""Base for query agents (ADR-0012).

Query agents interrogate the retrieval API and assemble CONTEXT.
They never generate answers (answer_generation_allowed gate).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs" / "pedago_interface_contract.yml"

# Retrieval API base URL (rag-engine, cross-service)
RETRIEVAL_API_URL = os.environ.get("RETRIEVAL_API_URL", "http://localhost:8100")


def load_contract() -> dict[str, Any]:
    """Load the pedago interface contract."""
    if not CONTRACT_PATH.is_file():
        return {}
    data = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return data


def is_answer_generation_allowed() -> bool:
    """Check answer_generation_allowed verrou."""
    return load_contract().get("answer_generation_allowed") is True


def is_answer_without_source_allowed() -> bool:
    """Check answer_without_source_allowed in citation_policy."""
    contract = load_contract()
    policy = contract.get("citation_policy")
    if not isinstance(policy, dict):
        return False
    return policy.get("answer_without_source_allowed") is True
