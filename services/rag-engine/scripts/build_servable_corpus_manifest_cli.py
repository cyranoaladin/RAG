#!/usr/bin/env python3
"""Thin executable wrapper for the pinned servable-corpus builder."""

from __future__ import annotations

import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))

from ingestor.servable_corpus_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
