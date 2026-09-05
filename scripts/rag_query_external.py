#!/usr/bin/env python3
"""Interroger `/search/v2` avec une identité déjà émise — client EXTERNE.

EXTERNAL_IDENTITY_ISSUER_REQUIRED=true

Ce client ne détient et ne lit JAMAIS `NEXUS_INTERNAL_TOKEN_SECRET` : il ne
sait pas signer sa propre identité HS256, et n'importe rien de
`ingestor.identity_v2` (le signeur interne) — même indirectement. Il reçoit
un jeton d'identité déjà émis, à courte durée de vie, par l'émetteur
canonique (BFF/gateway Nexus, provisionné hors de cette remédiation — cf.
`docs/reports/h2_exact_head_remediation_pre_go_live.md`), et le transmet
tel quel dans l'en-tête `X-Nexus-Identity`.

Pour l'outil OPÉRATEUR interne, qui détient le secret et émet sa propre
identité, voir `scripts/rag_query.py` (INTERNAL_OPERATOR_TOOL=true) —
jamais distribué à un agent externe.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "packages" / "contracts" / "src"))

from nexus_contracts import (  # noqa: E402
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

HTTP_TIMEOUT_SECONDS = 120.0
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_EXCERPT_CHARS = 240


class RagQueryExternalClientError(RuntimeError):
    """Le client refuse une configuration, un transport ou une réponse invalide."""


def available_scopes() -> tuple[str, ...]:
    """Scopes publics du registre canonique — métadonnée non secrète, sûre
    à charger côté client externe (contrairement à l'émission d'identité)."""
    return tuple(sorted(load_retrieval_scope_registry()))


@dataclass(frozen=True, repr=False)
class ExternalClientConfig:
    api_url: str
    bff_token: str = field(repr=False)
    #: Clé porteuse du client, distincte du credential machine. Le moteur
    #: exige les deux sur ses routes métier et n'accepte aucun repli de l'un
    #: sur l'autre : un client qui n'en enverrait qu'un reçoit 401.
    api_key: str = field(repr=False)
    identity_token: str = field(repr=False)


def _required(source: Mapping[str, str], key: str) -> str:
    value = source.get(key, "").strip()
    if not value:
        raise RagQueryExternalClientError(f"{key} requis")
    return value


def load_external_client_config(
    environ: Mapping[str, str] | None = None,
) -> ExternalClientConfig:
    """Charger uniquement les credentials externes : URL, jeton BFF, et une
    identité déjà émise. Jamais `NEXUS_INTERNAL_TOKEN_SECRET`, jamais lu par
    ce module, sous aucun nom."""
    source = os.environ if environ is None else environ
    api_url = _required(source, "RAG_API_URL").rstrip("/")
    parsed = urllib.parse.urlsplit(api_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RagQueryExternalClientError("URL API invalide")
    bff_token = _required(source, "RAG_BFF_SERVICE_TOKEN")
    if len(bff_token.encode("utf-8")) < 32:
        raise RagQueryExternalClientError("configuration invalide")
    api_key = _required(source, "RAG_API_KEY")
    identity_token = _required(source, "RAG_IDENTITY_TOKEN")
    return ExternalClientConfig(
        api_url=api_url,
        bff_token=bff_token,
        api_key=api_key,
        identity_token=identity_token,
    )


def build_request(query: str, artifact: RetrievalScopeArtifactV2) -> RetrievalRequest:
    """Même construction contractuelle que le client interne
    (`scripts/rag_query.py:build_request`) — jamais redéfinie en
    divergeant : ce client ne connaît la collection physique d'aucun scope,
    seulement les champs pédagogiques publics de l'artefact."""
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
    config: ExternalClientConfig,
) -> RetrievalResponse:
    """Appeler uniquement la route contractuelle, sans jamais fabriquer ni
    réémettre l'identité — une identité refusée par le serveur (absente,
    mauvaise, expirée, scope non couvert) remonte telle quelle comme une
    erreur HTTP, jamais retentée ni contournée localement."""
    body = request_payload.model_dump_json().encode("utf-8")
    request = urllib.request.Request(
        f"{config.api_url}/search/v2",
        data=body,
        headers={
            "Authorization": f"Bearer {config.bff_token}",
            "Content-Type": "application/json",
            "X-Nexus-Identity": config.identity_token,
            "X-RAG-API-Key": config.api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise RagQueryExternalClientError(f"API HTTP {response.status}")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise RagQueryExternalClientError(f"API HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise RagQueryExternalClientError("API indisponible") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RagQueryExternalClientError("réponse API trop volumineuse")
    try:
        return RetrievalResponse.model_validate_json(raw)
    except (ValidationError, ValueError):
        raise RagQueryExternalClientError("réponse API invalide") from None


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
        config = load_external_client_config()
        artifact = load_retrieval_scope_artifact(args.scope)
        if not isinstance(artifact, RetrievalScopeArtifactV2):
            raise RagQueryExternalClientError("scope non pris en charge par ce client")
        payload = build_request(args.query, artifact)
        response = post_search(payload, config=config)
    except (RagQueryExternalClientError, ValidationError, ValueError) as exc:
        message = str(exc) or "échec du client RAG externe"
        print(f"ERROR: {message}", file=sys.stderr)
        return 2
    print_response(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
