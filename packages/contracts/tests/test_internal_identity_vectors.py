from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path

from nexus_contracts import InternalIdentityEnvelope, canonical_identity_envelope_bytes

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "internal-identity-envelope-v1.json"
)


def test_internal_identity_envelope_has_stable_cross_runtime_bytes() -> None:
    envelope = InternalIdentityEnvelope.model_validate_json(
        """{
          "protocol_version":"1",
          "iss":"nexus-web",
          "aud":"rag-engine",
          "sub":"psn_abcdefghijklmnopqrst",
          "jti":"request_1234",
          "iat":100,
          "exp":130,
          "identity":{
            "aud":"rag-engine",
            "exp":130,
            "iss":"nexus-web",
            "jti":"request_1234",
            "tenant":"nexus",
            "niveau":"terminale",
            "role":"student",
            "school_year":"2026-2027",
            "sub":"psn_abcdefghijklmnopqrst",
            "pedagogical_profile":{
              "voie":"generale",
              "matieres":["mathematiques"],
              "statut_enseignement":"specialite",
              "candidat":"scolarise",
              "audience":"aefe"
            }
          },
          "scope_id":"terminale_maths",
          "scope_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "allowed_collections":["terminale_maths"],
          "request_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "manifest_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
        }"""
    )

    assert canonical_identity_envelope_bytes(envelope) == (
        b'{"allowed_collections":["terminale_maths"],"aud":"rag-engine",'
        b'"exp":130,"iat":100,"identity":{"aud":"rag-engine","exp":130,'
        b'"iss":"nexus-web","jti":"request_1234","niveau":"terminale",'
        b'"pedagogical_profile":{"audience":"aefe","candidat":"scolarise",'
        b'"matieres":["mathematiques"],"statut_enseignement":"specialite",'
        b'"voie":"generale"},"role":"student","school_year":"2026-2027",'
        b'"sub":"psn_abcdefghijklmnopqrst","tenant":"nexus"},"iss":"nexus-web",'
        b'"jti":"request_1234","manifest_sha256":"cccccccccccccccccccccccccccccccc'
        b'cccccccccccccccccccccccccccccccc","protocol_version":"1",'
        b'"request_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
        b'"scope_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        b'"scope_id":"terminale_maths","sub":"psn_abcdefghijklmnopqrst"}'
    )


def test_versioned_cross_runtime_fixture_binds_request_scope_and_signature() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    envelope = InternalIdentityEnvelope.model_validate(fixture["envelope"])
    canonical = canonical_identity_envelope_bytes(envelope)

    assert base64.b64decode(fixture["canonicalEnvelopeBase64"]) == canonical
    assert envelope.request_sha256 == fixture["requestSha256"]
    assert envelope.scope_digest == fixture["retrievalScopeSha256"]
    header, payload, signature = fixture["jwt"].split(".")
    public_test_key = hashlib.sha256(
        fixture["publicTestKeyDerivation"].encode("utf-8")
    ).hexdigest()
    expected = hmac.new(
        public_test_key.encode(),
        f"{header}.{payload}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    assert hmac.compare_digest(
        base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)),
        expected,
    )
