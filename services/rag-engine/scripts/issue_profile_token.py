#!/usr/bin/env python3
"""CLI tool to issue HMAC-signed profile tokens.

Reads PROFILE_SECRET from environment. Never exposed via HTTP.

Usage:
    PROFILE_SECRET=... python scripts/issue_profile_token.py terminale libre
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Import sign_profile from retrieval_api
sys.path.insert(0, str(Path(__file__).resolve().parent))
from retrieval_api import VALID_AUDIENCES, VALID_NIVEAUX, sign_profile


def main() -> int:
    secret = os.environ.get("PROFILE_SECRET", "")
    if not secret:
        print("ERROR: PROFILE_SECRET not set", file=sys.stderr)
        return 1

    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <niveau> <audience>", file=sys.stderr)
        print(f"  niveaux:  {sorted(VALID_NIVEAUX)}", file=sys.stderr)
        print(f"  audiences: {sorted(VALID_AUDIENCES)}", file=sys.stderr)
        return 1

    niveau, audience = sys.argv[1], sys.argv[2]
    if niveau not in VALID_NIVEAUX:
        print(f"ERROR: invalid niveau '{niveau}'", file=sys.stderr)
        return 1
    if audience not in VALID_AUDIENCES:
        print(f"ERROR: invalid audience '{audience}'", file=sys.stderr)
        return 1

    token = sign_profile(niveau, audience, secret)
    print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
