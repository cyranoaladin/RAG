"""Tombstone de la migration directe ChromaDB vers pgvector."""

from __future__ import annotations

import sys

EX_CONFIG = 78
TOMBSTONE_MESSAGE = (
    "Migration directe ChromaDB vers pgvector desactivee : "
    "utilisez la preparation de convergence gouvernee.\n"
)


def main() -> int:
    """Refuser toute invocation avant connexion ou mutation."""
    sys.stderr.write(TOMBSTONE_MESSAGE)
    return EX_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
