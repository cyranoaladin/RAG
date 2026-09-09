#!/usr/bin/env python3
"""Thin executable wrapper for Phase A of a governed R1 export attempt."""

from __future__ import annotations

import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))

from ingestor.r1_attempt_preflight_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
