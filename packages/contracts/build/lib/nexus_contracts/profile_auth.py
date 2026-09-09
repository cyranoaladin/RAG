"""HMAC-signed student profile tokens (source unique).

Pure crypto module — no psycopg, no FastAPI dependency.
Used by retrieval_api.py (verify) and issue_profile_token.py (sign).

Token format: b64url(payload_json).hmac_sha256_hex
  - payload_json: canonical JSON {"niveau":"...","audience":"..."}
  - HMAC computed over the b64url-encoded payload with server secret
  - Token characters: [A-Za-z0-9_-] + "." (header-safe, RFC 7515)
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from dataclasses import dataclass

VALID_NIVEAUX = {"terminale", "premiere", "seconde", "troisieme"}
VALID_AUDIENCES = {"libre", "aefe", "tous"}

# Token regex: base64url segment + dot + 64-char hex HMAC
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+\.[0-9a-f]{64}$")


@dataclass(frozen=True)
class StudentProfile:
    """Server-verified profile. Determines filtering — cryptographically bound."""

    niveau: str
    audience: str


def _b64url_encode(data: bytes) -> str:
    """Base64url encode without padding (RFC 7515)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """Base64url decode with padding restoration."""
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


def sign_profile(niveau: str, audience: str, secret: str) -> str:
    """Create a signed profile token: b64url(payload_json).hmac_hex.

    The payload is canonical JSON encoded as base64url (no padding).
    The HMAC-SHA256 is computed over the encoded payload string.
    """
    payload_json = json.dumps(
        {"niveau": niveau, "audience": audience}, separators=(",", ":")
    )
    encoded = _b64url_encode(payload_json.encode())
    sig = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{sig}"


def verify_profile(token: str, secret: str) -> StudentProfile:
    """Verify a signed profile token and return the profile.

    Raises ValueError if the token is malformed, the signature is invalid,
    or the payload contains invalid niveau/audience values.
    """
    if not TOKEN_RE.fullmatch(token):
        raise ValueError("malformed token")
    encoded_payload, provided_sig = token.rsplit(".", 1)
    expected_sig = hmac.new(
        secret.encode(), encoded_payload.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise ValueError("invalid signature")
    try:
        payload_bytes = _b64url_decode(encoded_payload)
        data = json.loads(payload_bytes)
    except (json.JSONDecodeError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("malformed payload") from exc
    if not isinstance(data, dict):
        raise ValueError("malformed payload")
    niveau = data.get("niveau", "")
    audience = data.get("audience", "")
    if niveau not in VALID_NIVEAUX:
        raise ValueError(f"invalid niveau: {niveau}")
    if audience not in VALID_AUDIENCES:
        raise ValueError(f"invalid audience: {audience}")
    return StudentProfile(niveau=niveau, audience=audience)
