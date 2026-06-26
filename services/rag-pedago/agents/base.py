"""Base class for acquisition agents (ADR-0005)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs" / "pedago_interface_contract.yml"


class AcquisitionAgent(ABC):
    """Interface for all acquisition agents."""

    def check_staging_allowed(self) -> bool:
        """Check data_staging_allowed verrou. YAML empty/non-dict → blocked."""
        if not CONTRACT_PATH.is_file():
            return False
        config = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            return False
        return config.get("data_staging_allowed") is True

    def check_ingestion_blocked(self) -> bool:
        """Verify ingestion_allowed is false. YAML empty/non-dict → blocked."""
        if not CONTRACT_PATH.is_file():
            return True
        config = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            return True
        return config.get("ingestion_allowed") is not True

    @abstractmethod
    def plan(self) -> dict[str, Any]:
        """Produce an acquisition plan."""

    @abstractmethod
    def fetch(self, max_notions: int | None = None) -> dict[str, Any]:
        """Execute the acquisition plan."""

    @abstractmethod
    def report(self) -> dict[str, Any]:
        """Produce a summary report."""
