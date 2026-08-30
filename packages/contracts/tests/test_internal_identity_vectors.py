from __future__ import annotations

from nexus_contracts import InternalIdentityEnvelope, canonical_identity_envelope_bytes


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
