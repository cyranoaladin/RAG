#!/usr/bin/env python3
"""CLI tool to issue HMAC-signed profile tokens (base64url format).

Reads PROFILE_SECRET from environment. Never exposed via HTTP.
Self-contained: does not import retrieval_api (avoids psycopg dependency).

Usage:
    PROFILE_SECRET=... python scripts/issue_profile_token.py terminale libre
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys

VALID_NIVEAUX = {"terminale", "premiere", "seconde", "troisieme"}
VALID_AUDIENCES = {"libre", "aefe", "tous"}


def sign_profile(niveau: str, audience: str, secret: str) -> str:
    """Create a signed token: b64url(payload_json).hmac_hex."""
    payload_json = json.dumps(
        {"niveau": niveau, "audience": audience}, separators=(",", ":")
    )
    encoded = base64.urlsafe_b64encode(payload_json.encode()).rstrip(b"=").decode("ascii")
    sig = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{sig}"


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
