"""Export the shared Python/Node manifest-bound identity signing vector."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nexus_contracts import (  # noqa: E402
    InternalIdentityEnvelope,
    RetrievalNeed,
    RetrievalRequest,
    RetrievalScopeArtifactV3,
    StudentProfile,
)
from nexus_contracts.canonical_json import canonical_model_bytes  # noqa: E402

FIXTURE_PATH = ROOT / "fixtures" / "internal-identity-envelope-v1.json"
PUBLIC_TEST_KEY_DERIVATION = "ARIA-B-cross-language-public-test-vector-v1"


def fixture_signing_key() -> str:
    """Derive a public test-only HMAC key without publishing a credential field."""
    return hashlib.sha256(PUBLIC_TEST_KEY_DERIVATION.encode("utf-8")).hexdigest()


def _b64url(content: bytes) -> str:
    return base64.urlsafe_b64encode(content).rstrip(b"=").decode("ascii")


def fixture_bytes() -> bytes:
    scope = RetrievalScopeArtifactV3.model_validate(
        {
            "artifact_version": "3",
            "scope_id": "aria_maths_premiere_v1",
            "status": "eligible_for_promotion",
            "source_sha256": "a" * 64,
            "target_policy": {
                "tenant": "nexus",
                "niveau": "premiere",
                "voie": "generale",
                "matiere": "mathematiques",
                "statut_enseignement": "specialite",
                "audiences": ["aefe", "libre"],
                "candidates": ["scolarise", "aefe", "libre"],
                "roles": ["student"],
            },
            "evidence_subject": {
                "collection": "rag_nexus_maths_premiere_gen_specialite",
                "tenant": "nexus",
                "niveau": "premiere",
                "voie": "generale",
                "matiere": "mathematiques",
                "statut_enseignement": "specialite",
                "candidat": "scolarise",
                "audiences": ["aefe", "tous"],
                "visibility": "public",
                "rights": ["officiel_public"],
                "school_year": "2026-2027",
                "programme_version": "fr-national-2026",
            },
        }
    )
    request = RetrievalRequest(
        student_profile=StudentProfile.model_validate(
            {
                "status_detail": "aefe",
                "niveau": "premiere",
                "voie": "generale",
                "matieres": ["mathematiques"],
                "statut_enseignement": "specialite",
                "candidat": "scolarise",
                "school_year": "2026-2027",
                "zone": "aefe",
            }
        ),
        curriculum_scope={
            "niveau": "premiere",
            "voie": "generale",
            "matiere": "mathematiques",
            "statut_enseignement": "specialite",
        },
        need=RetrievalNeed(intent="context", query="Dérivation et tangente"),
        manifest_sha256="c" * 64,
        corpus_id="aria-maths-premiere",
        corpus_version_id="2026-08-30.1",
    )
    request_sha256 = hashlib.sha256(canonical_model_bytes(request)).hexdigest()
    envelope = InternalIdentityEnvelope.model_validate(
        {
            "protocol_version": "1",
            "iss": "nexus-cockpit",
            "aud": "nexus-rag-engine",
            "sub": "psn_1234567890abcdef",
            "jti": "aria-fixture-jti-001",
            "iat": 1_785_320_370,
            "exp": 1_785_320_400,
            "identity": {
                "aud": "nexus-rag-engine",
                "exp": 1_785_320_400,
                "iss": "nexus-cockpit",
                "jti": "aria-fixture-jti-001",
                "tenant": "nexus",
                "niveau": "premiere",
                "role": "student",
                "school_year": "2026-2027",
                "sub": "psn_1234567890abcdef",
                "pedagogical_profile": {
                    "voie": "generale",
                    "matieres": ["mathematiques"],
                    "statut_enseignement": "specialite",
                    "candidat": "scolarise",
                    "audience": "aefe",
                },
            },
            "scope_id": scope.scope_id,
            "scope_digest": scope.sha256_digest(),
            "request_sha256": request_sha256,
            "manifest_sha256": request.manifest_sha256,
            "allowed_collections": [scope.evidence_subject.collection],
        }
    )
    header = b'{"alg":"HS256","typ":"JWT"}'
    payload = canonical_model_bytes(envelope)
    signing_input = f"{_b64url(header)}.{_b64url(payload)}"
    signature = hmac.new(
        fixture_signing_key().encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    document = {
        "fixtureVersion": 1,
        "publicTestKeyDerivation": PUBLIC_TEST_KEY_DERIVATION,
        "request": request.model_dump(mode="json"),
        "requestSha256": request_sha256,
        "retrievalScope": scope.model_dump(mode="json"),
        "retrievalScopeSha256": scope.sha256_digest(),
        "envelope": envelope.model_dump(mode="json"),
        "canonicalEnvelopeBase64": base64.b64encode(payload).decode("ascii"),
        "jwt": f"{signing_input}.{_b64url(signature)}",
    }
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = fixture_bytes()
    if args.check:
        return int(not FIXTURE_PATH.is_file() or FIXTURE_PATH.read_bytes() != expected)
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_bytes(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
