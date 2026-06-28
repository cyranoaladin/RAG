"""Tests for profile_auth — HMAC token signing/verification.

Includes mutation-proof tests for non-dict JSON payloads (P1 fix lot 18.1).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest

from nexus_contracts.profile_auth import (
    StudentProfile,
    sign_profile,
    verify_profile,
)

SECRET = "test-secret-key"


# --- Helpers ---

def _forge_token(payload_obj: object, secret: str = SECRET) -> str:
    """Sign an arbitrary JSON payload (not necessarily a dict)."""
    payload_json = json.dumps(payload_obj, separators=(",", ":"))
    encoded = base64.urlsafe_b64encode(payload_json.encode()).rstrip(b"=").decode("ascii")
    sig = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{sig}"


# --- Happy path ---

class TestSignVerifyRoundTrip:
    def test_roundtrip(self) -> None:
        token = sign_profile("terminale", "libre", SECRET)
        profile = verify_profile(token, SECRET)
        assert profile == StudentProfile(niveau="terminale", audience="libre")

    def test_all_valid_niveaux(self) -> None:
        for niv in ("terminale", "premiere", "seconde", "troisieme"):
            token = sign_profile(niv, "libre", SECRET)
            assert verify_profile(token, SECRET).niveau == niv

    def test_all_valid_audiences(self) -> None:
        for aud in ("libre", "aefe", "tous"):
            token = sign_profile("terminale", aud, SECRET)
            assert verify_profile(token, SECRET).audience == aud


# --- Error paths ---

class TestVerifyErrors:
    def test_malformed_token_no_dot(self) -> None:
        with pytest.raises(ValueError, match="malformed token"):
            verify_profile("nodot", SECRET)

    def test_invalid_signature(self) -> None:
        token = sign_profile("terminale", "libre", SECRET)
        bad = token[:-4] + "dead"
        with pytest.raises(ValueError, match="invalid signature"):
            verify_profile(bad, SECRET)

    def test_invalid_niveau(self) -> None:
        token = _forge_token({"niveau": "cm2", "audience": "libre"})
        with pytest.raises(ValueError, match="invalid niveau"):
            verify_profile(token, SECRET)

    def test_invalid_audience(self) -> None:
        token = _forge_token({"niveau": "terminale", "audience": "vip"})
        with pytest.raises(ValueError, match="invalid audience"):
            verify_profile(token, SECRET)


# --- P1 fix: non-dict JSON payloads → ValueError, not AttributeError ---

class TestNonDictPayload:
    """A correctly-signed token whose JSON payload is NOT a dict must raise
    ValueError (caught by resolve_profile → 401), never AttributeError (→ 500).

    Mutation-proof: removing the isinstance(data, dict) guard causes
    AttributeError on data.get() for these payloads.
    """

    @pytest.mark.parametrize("payload", [
        123,
        "x",
        [1, 2],
        None,
        True,
        42.5,
    ], ids=["int", "str", "list", "null", "bool", "float"])
    def test_non_dict_raises_valueerror(self, payload: object) -> None:
        token = _forge_token(payload)
        with pytest.raises(ValueError, match="malformed payload"):
            verify_profile(token, SECRET)

    @pytest.mark.parametrize("payload", [
        123,
        [1, 2],
        "x",
        None,
    ], ids=["int", "list", "str", "null"])
    def test_mutation_proof_without_guard_would_raise_attribute_error(
        self, payload: object
    ) -> None:
        """Prove that without the isinstance guard, data.get() would fail
        with AttributeError — confirming the guard is load-bearing."""
        data = json.loads(json.dumps(payload))
        assert not isinstance(data, dict)
        with pytest.raises(AttributeError):
            data.get("niveau", "")  # type: ignore[union-attr]
