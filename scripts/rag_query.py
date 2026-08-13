#!/usr/bin/env python3
"""Interroger `/search/v2` avec un scope signé et étroit.

INTERNAL_OPERATOR_TOOL=true

Outil opérateur INTERNE — il détient (`NEXUS_INTERNAL_TOKEN_SECRET`) et
utilise le secret de signature d'identité interne pour émettre sa propre
enveloppe HS256. Il ne doit **jamais** être distribué à un agent externe
ni exécuté hors d'un environnement opérateur de confiance : quiconque
détient ce secret peut signer une identité pour n'importe quel scope
qu'il connaît. Pour un client destiné à un agent externe, voir
`scripts/rag_query_external.py`, qui ne lit jamais ce secret et reçoit une
identité déjà émise.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "services" / "rag-engine" / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT / "packages" / "contracts" / "src"))

from nexus_contracts import (  # noqa: E402
    InternalIdentity,
    InternalIdentityEnvelope,
    PedagogicalProfile,
    RetrievalCurriculumScope,
    RetrievalNeed,
    RetrievalOptions,
    RetrievalRequest,
    RetrievalResponse,
    RetrievalScopeArtifactV2,
    StudentProfile,
    load_retrieval_scope_artifact,
    load_retrieval_scope_registry,
)
from pydantic import ValidationError  # noqa: E402

from ingestor.identity_v2 import (  # noqa: E402
    IdentityVerifierConfig,
    verify_identity_token,
)


def available_scopes() -> tuple[str, ...]:
    """Dériver les scopes autorisés depuis le registre canonique — jamais
    une allowlist recopiée à la main, qui divergerait silencieusement du
    backend dès qu'un scope y est ajouté ou retiré."""
    return tuple(sorted(load_retrieval_scope_registry()))


HTTP_TIMEOUT_SECONDS = 120.0
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
IDENTITY_TTL_SECONDS = 300
MAX_EXCERPT_CHARS = 240


class RagQueryClientError(RuntimeError):
    """Le client refuse une configuration, un transport ou une réponse invalide."""


@dataclass(frozen=True, repr=False)
class ClientConfig:
    api_url: str
    bff_token: str = field(repr=False)
    internal_secret: str = field(repr=False)
    internal_issuer: str
    internal_audience: str
    identity_issuer: str
    identity_audience: str


def _required(source: Mapping[str, str], key: str) -> str:
    value = source.get(key, "").strip()
    if not value:
        raise RagQueryClientError("configuration d'identité invalide")
    return value


def load_client_config(environ: Mapping[str, str] | None = None) -> ClientConfig:
    """Charger les autorités HTTP et HS256 sans jamais les rendre affichables."""
    source = os.environ if environ is None else environ
    api_url = _required(source, "RAG_API_URL").rstrip("/")
    parsed = urllib.parse.urlsplit(api_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RagQueryClientError("URL API invalide")
    bff_token = _required(source, "RAG_BFF_SERVICE_TOKEN")
    internal_secret = _required(source, "NEXUS_INTERNAL_TOKEN_SECRET")
    if len(bff_token.encode("utf-8")) < 32 or len(internal_secret.encode("utf-8")) < 32:
        raise RagQueryClientError("configuration d'identité invalide")
    identity_audience = _required(source, "NEXUS_SSO_AUDIENCE")
    if "," in identity_audience:
        raise RagQueryClientError("configuration d'identité invalide")
    return ClientConfig(
        api_url=api_url,
        bff_token=bff_token,
        internal_secret=internal_secret,
        internal_issuer=_required(source, "NEXUS_INTERNAL_TOKEN_ISSUER"),
        internal_audience=_required(source, "NEXUS_INTERNAL_TOKEN_AUDIENCE"),
        identity_issuer=_required(source, "NEXUS_SSO_ISSUER"),
        identity_audience=identity_audience,
    )


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _sign_hs256(payload: Mapping[str, object], *, secret: str) -> str:
    header = _b64url(
        json.dumps(
            {"alg": "HS256", "typ": "JWT"},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    body = _b64url(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    signed = f"{header}.{body}"
    signature = hmac.new(
        secret.encode("utf-8"), signed.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{signed}.{_b64url(signature)}"


def issue_scope_identity(
    scope_id: str,
    *,
    config: ClientConfig,
    now: int | None = None,
) -> tuple[str, RetrievalScopeArtifactV2]:
    """Émettre puis revérifier localement l'enveloppe par le verifier canonique."""
    artifact = load_retrieval_scope_artifact(scope_id)
    if not isinstance(artifact, RetrievalScopeArtifactV2):
        raise RagQueryClientError("scope Wave 0 invalide")
    issued_at = int(time.time()) if now is None else now
    expires_at = issued_at + IDENTITY_TTL_SECONDS
    target = artifact.target_identity
    evidence = artifact.evidence_subject
    jti = f"rq_{uuid.uuid4().hex}"
    pseudonymous_subject = "psn_" + hmac.new(
        config.internal_secret.encode("utf-8"),
        f"rag-query:{scope_id}".encode("ascii"),
        hashlib.sha256,
    ).hexdigest()[:32]
    identity = InternalIdentity(
        aud=config.identity_audience,
        exp=expires_at,
        iss=config.identity_issuer,
        jti=jti,
        tenant=target.tenant,
        niveau=target.niveau,
        role="teacher",
        school_year=evidence.school_year,
        sub=pseudonymous_subject,
        pedagogical_profile=PedagogicalProfile(
            voie=target.voie,
            matieres=[target.matiere],
            statut_enseignement=target.statut_enseignement,
            candidat=target.candidates[0],
            audience=target.audience,
        ),
    )
    envelope = InternalIdentityEnvelope(
        protocol_version="1",
        iss=config.internal_issuer,
        aud=config.internal_audience,
        sub=pseudonymous_subject,
        jti=jti,
        iat=issued_at,
        exp=expires_at,
        identity=identity,
        scope_id=artifact.scope_id,
        scope_digest=artifact.sha256_digest(),
        allowed_collections=[evidence.collection],
    )
    token = _sign_hs256(envelope.model_dump(mode="json"), secret=config.internal_secret)
    registry = load_retrieval_scope_registry()
    verify_identity_token(
        token,
        config=IdentityVerifierConfig(
            secret=config.internal_secret,
            issuer=config.internal_issuer,
            audience=config.internal_audience,
            identity_issuer=config.identity_issuer,
            identity_audience=config.identity_audience,
            artifact=artifact,
            artifacts=registry,
        ),
        now=issued_at,
    )
    return token, artifact


def build_request(query: str, artifact: RetrievalScopeArtifactV2) -> RetrievalRequest:
    """Construire le contrat en séparant cible Seconde et preuve Troisième."""
    target = artifact.target_identity
    evidence = artifact.evidence_subject
    return RetrievalRequest(
        student_profile=StudentProfile(
            niveau=target.niveau,
            voie=target.voie,
            matieres=[target.matiere],
            statut_enseignement=target.statut_enseignement,
            candidat=target.candidates[0],
            school_year=evidence.school_year,
            zone=target.audience,
        ),
        curriculum_scope=RetrievalCurriculumScope(
            niveau=evidence.niveau,
            voie=evidence.voie,
            matiere=evidence.matiere,
            statut_enseignement=evidence.statut_enseignement,
        ),
        need=RetrievalNeed(intent="remediation", query=query),
        retrieval=RetrievalOptions(
            k=8,
            hybrid=True,
            rerank=True,
            include_citations=True,
        ),
    )


def post_search(
    request_payload: RetrievalRequest,
    *,
    identity_token: str,
    config: ClientConfig,
) -> RetrievalResponse:
    """Appeler uniquement la route contractuelle et valider sa réponse fermée."""
    body = request_payload.model_dump_json().encode("utf-8")
    request = urllib.request.Request(
        f"{config.api_url}/search/v2",
        data=body,
        headers={
            "Authorization": f"Bearer {config.bff_token}",
            "Content-Type": "application/json",
            "X-Nexus-Identity": identity_token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise RagQueryClientError(f"API HTTP {response.status}")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise RagQueryClientError(f"API HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise RagQueryClientError("API indisponible") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RagQueryClientError("réponse API trop volumineuse")
    try:
        return RetrievalResponse.model_validate_json(raw)
    except (ValidationError, ValueError):
        raise RagQueryClientError("réponse API invalide") from None


def _one_line(value: object, *, limit: int | None = None) -> str:
    text = " ".join(str(value).split()) if value is not None else "none"
    if limit is not None and len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def print_response(response: RetrievalResponse) -> None:
    """Afficher seulement les champs utiles, jamais les credentials."""
    print(f"results={len(response.results)}")
    for result in response.results:
        citation = result.citation
        metadata = result.metadata
        print(f"score={result.score:.6f}")
        print(f"titre={_one_line(result.title)}")
        print(f"extrait={_one_line(result.excerpt, limit=MAX_EXCERPT_CHARS)}")
        print(f"page={citation.page if citation is not None else 'none'}")
        print(f"source={_one_line(citation.source_uri if citation else None)}")
        print(f"rights={_one_line(citation.rights if citation else None)}")
        print(f"sha={_one_line(metadata.get('content_sha256'))}")
        print(f"path={_one_line(metadata.get('placement_source_path'))}")


def _parser(*, scopes: Sequence[str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list-scopes",
        action="store_true",
        help="Lister les scopes du registre canonique et quitter, sans requête.",
    )
    parser.add_argument("--scope", choices=tuple(scopes))
    parser.add_argument("--query")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    scopes = available_scopes()
    args = _parser(scopes=scopes).parse_args(argv)
    if args.list_scopes:
        for scope_id in scopes:
            print(scope_id)
        return 0
    if not args.scope:
        print("ERROR: --scope requis (ou --list-scopes)", file=sys.stderr)
        return 2
    if not args.query or not args.query.strip():
        print("ERROR: requête vide", file=sys.stderr)
        return 2
    try:
        config = load_client_config()
        token, artifact = issue_scope_identity(args.scope, config=config)
        payload = build_request(args.query, artifact)
        response = post_search(payload, identity_token=token, config=config)
    except (RagQueryClientError, ValidationError, ValueError) as exc:
        message = str(exc) or "échec du client RAG"
        print(f"ERROR: {message}", file=sys.stderr)
        return 2
    print_response(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
