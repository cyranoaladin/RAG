#!/usr/bin/env python3
"""CLI tool to issue HMAC-signed profile tokens (base64url format).

Reads PROFILE_SECRET from environment. Never exposed via HTTP.
Imports from nexus_contracts.profile_auth (source unique, no psycopg).

Usage:
    PROFILE_SECRET=... python scripts/issue_profile_token.py terminale libre
"""
from __future__ import annotations

import os
import sys

from nexus_contracts.profile_auth import VALID_AUDIENCES, VALID_NIVEAUX, sign_profile


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
