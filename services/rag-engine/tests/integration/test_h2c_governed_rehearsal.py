"""Répétition H2-C réelle : un PDF scellé, sept placements, une seule indexation.

Ce test est opt-in parce que les octets du corpus restent hors Git. Le runner
``h2c_governed_rehearsal.py`` lui fournit le PDF et le catalogue vérifiés.
GitHub est remplacé par le serveur HTTP local réaliste des tests LOT41/LOT42 ;
les vérificateurs, artefacts canoniques, rôles et deux PostgreSQL restent réels.
Il s'agit d'une répétition isolée, jamais d'une attestation de production.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import threading
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import httpx
import psycopg
import pytest
from pypdf import PdfReader

ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _local_github import (  # noqa: E402
    REPOSITORY,
    VALID_TOKEN,
    LocalGitHub,
    local_github_server,
)
from _pg_authority import (  # noqa: E402
    app_dsn,
    attestor_dsn,
    authority_dsn,
    requires_docker,
    start_ingestion_control_postgres,
)
from nexus_contracts import Candidat, Niveau, Rights, Voie  # noqa: E402
from nexus_contracts.authority_artifacts import (  # noqa: E402
    ScopeAuthorizationArtifactV2,
    canonical_authorization_path,
)
from nexus_contracts.ingestion import (  # noqa: E402
    ArtifactRecord,
    CollectionProfile,
    ResourceCandidate,
    ResourceScope,
)
from nexus_contracts.resource_state import ResourceState  # noqa: E402

from ingestor.governed_publisher_v2 import (  # noqa: E402
    EligiblePlacement,
    GovernedArtifact,
    publish_governed_artifact,
)
from ingestor.ingestion_agents.classifier import ConformityResult  # noqa: E402
from ingestor.ingestion_agents.fetcher import (  # noqa: E402
    ContentAuthorizationBinding,
    run_fetcher,
)
from ingestor.ingestion_agents.quality_agent import run_quality_agent  # noqa: E402
from ingestor.ingestion_agents.rights_agent import run_rights_agent  # noqa: E402
from ingestor.ingestion_agents.transitions import (  # noqa: E402
    apply_resource_transition,
)
from ingestor.ingestion_control.governed_publication_path import (  # noqa: E402
    promote_reviewed_publication,
    stage_publication_for_review,
)
from ingestor.ingestion_control.provisioning import (  # noqa: E402
    create_resource,
    get_resource_state,
    persist_artifact,
    persist_resource_candidate,
)
from ingestor.ingestion_control.scope_authority import (  # noqa: E402
    verify_scope_authorization,
)
from ingestor.ingestion_control.scope_enforcement import (  # noqa: E402
    ScopeEnforcementViolation,
    enforce_before_fetch,
    enforce_content_sha256,
    enforce_destination,
    require_h2_content_bound_authority,
)
from ingestor.ingestion_profiles.registry import profile_fingerprint  # noqa: E402
from ingestor.ingestion_worker.attest_publication_cli import (  # noqa: E402
    main as attest_main,
)
from ingestor.ingestion_worker.authorize_scope_cli import (  # noqa: E402
    main as authorize_scope_main,
)
from ingestor.retrieval_hybrid_v2 import EMBED_DIMENSION  # noqa: E402
from ingestor.retrieval_pg_v2 import PgCandidateStore  # noqa: E402
from ingestor.retrieval_scope_v2 import ServerRetrievalScope  # noqa: E402

pytestmark = [pytest.mark.integration, requires_docker]

REAL_SHA = "371d0c82ed1f47614ee9cbfdaa86cfb4add1f239a84882d9731fbd125105925d"
CORPUS_MANIFEST_SHA = (
    "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
)
PII_EVIDENCE_SHA = (
    "76e6ba3cd5b1c116c8647b611eb3fdeb2aba6b8c7fdfbad9e71048354956f311"
)
AUTH_PR, AUTH_HEAD, BASE_HEAD, AUTH_REVIEW = 4410, "a" * 40, "9" * 40, 44101
PUB_PR, PUB_HEAD, PUB_REVIEW = 4420, "b" * 40, 44201
SCHOOL_YEAR = "2026-2027"
PROGRAMME_VERSION = "BO_SPECIAL_1_2019-01-22"
TENANT = "libre_lycee_gt"
STATUT = "specialite"

PDF_PATH = Path(os.environ.get("NEXUS_H2C_REAL_PDF_PATH", ""))
CATALOG_PATH = Path(os.environ.get("NEXUS_H2C_REAL_CATALOG_PATH", ""))
APP_DSN = os.environ.get("LOT40_PG_DSN", "").strip()
ADMIN_DSN = os.environ.get("LOT40_PG_ADMIN_DSN", "").strip()
PUBLISHER_DSN = os.environ.get("LOT42_PG_PUBLISHER_DSN", "").strip()
if (
    not os.environ.get("NEXUS_H2C_REAL_REHEARSAL", "").strip()
    or not APP_DSN
    or not ADMIN_DSN
    or not PUBLISHER_DSN
):
    pytest.skip("répétition réelle H2-C non demandée", allow_module_level=True)


@pytest.fixture(scope="module")
def control_pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("h2c-governed-rehearsal")


def _real_inputs() -> tuple[bytes, tuple[dict[str, Any], ...]]:
    raw = PDF_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == REAL_SHA
    document = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    artifacts = document.get("artifacts")
    if isinstance(artifacts, dict):
        entry = artifacts.get(REAL_SHA)
    else:
        assert isinstance(artifacts, list)
        entry = next(item for item in artifacts if item.get("sha256") == REAL_SHA)
    assert isinstance(entry, dict)
    placements = entry.get("pedagogical_placements")
    assert isinstance(placements, list)
    assert len(placements) == 7
    assert all(item.get("classified") is True for item in placements)
    assert all(item.get("content_sha256") == REAL_SHA for item in placements)
    assert all(item.get("status") == "actuel" for item in placements)
    return raw, tuple(placements)


def _slug(value: str) -> str:
    return value.replace("-", "_")


def _scope(source: dict[str, Any]) -> ResourceScope:
    subject = _slug(str(source["subject"]))
    return ResourceScope(
        tenant=TENANT,
        collection=f"h2c_rehearsal_{subject}",
        niveau=Niveau.lycee_gt,
        voie=Voie.generale,
        matiere=subject,
        candidat=Candidat.libre,
        audience=["libre", "tous"],
        visibility="internal",
        school_year=SCHOOL_YEAR,
        programme_version=PROGRAMME_VERSION,
    )


def _profile(scope: ResourceScope) -> CollectionProfile:
    return CollectionProfile(
        profile_version="h2c-rehearsal-v1",
        enabled=True,
        scope=scope,
        title=f"Répétition isolée {scope.matiere}",
        owner="nexus-reussite",
        expected_topics=["arts"],
        expected_resource_types=["programme_officiel"],
        allowed_domains=["eduscol.education.gouv.fr"],
        source_authority="official",
        search_cadence="manual",
        max_queries_per_run=1,
        max_documents_per_run=1,
        max_chunk_size=800,
        chunk_overlap=100,
        min_source_confidence=0.7,
        min_scope_confidence=0.7,
        min_extraction_quality=0.1,
    )


def _authorization_id(source: dict[str, Any]) -> str:
    return f"h2c-rehearsal-{_slug(str(source['subject']))}"


def _authorization(
    source: dict[str, Any], profile: CollectionProfile
) -> ScopeAuthorizationArtifactV2:
    now = datetime.now(UTC)
    return ScopeAuthorizationArtifactV2(
        protocol_version="LOT41A-V2",
        authorization_id=_authorization_id(source),
        decision="AUTHORIZE_INGESTION_SCOPE",
        scope=profile.scope,
        manifest_digest=CORPUS_MANIFEST_SHA,
        profile_id=str(profile.scope.collection),
        profile_version=profile.profile_version,
        profile_fingerprint=profile_fingerprint(profile),
        allowed_domains=("eduscol.education.gouv.fr",),
        rights_categories=(Rights.officiel_public,),
        exclusions=(),
        allowed_content_sha256=(REAL_SHA,),
        pii_absence_attested=True,
        pii_absence_evidence=(
            f"H2 PII evidence sha256={PII_EVIDENCE_SHA}; "
            f"content_sha256={REAL_SHA}; status=CLEARED"
        ),
        valid_from=now - timedelta(hours=1),
        valid_until=now + timedelta(days=7),
    )


def _make_run(conn: psycopg.Connection[Any], scope: ResourceScope) -> uuid.UUID:
    row = conn.execute(
        """
        INSERT INTO ingestion_control.ingestion_runs
            (tenant, collection, niveau, voie, matiere, candidat, audience,
             visibility, school_year, programme_version, profile_version,
             trigger, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                'h2c-rehearsal-v1', 'manual', 'planned')
        RETURNING run_id
        """,
        (
            scope.tenant,
            scope.collection,
            scope.niveau.value,
            scope.voie.value,
            scope.matiere,
            scope.candidat.value,
            [value.value for value in scope.audience],
            scope.visibility,
            scope.school_year,
            scope.programme_version,
        ),
    ).fetchone()
    assert row is not None
    run_id = row[0]
    assert isinstance(run_id, uuid.UUID)
    return run_id


@contextmanager
def _local_pdf_server(content: bytes) -> Iterator[str]:
    """Sert les octets négatifs par un vrai aller-retour HTTP local."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - API BaseHTTPRequestHandler
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        host_text = host.decode("ascii") if isinstance(host, bytes) else host
        yield f"http://{host_text}:{port}/same-domain-unlisted.pdf"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _candidate_at_candidate_state(
    control_dsn: str,
    *,
    source: dict[str, Any],
    profile: CollectionProfile,
) -> tuple[ResourceCandidate, int]:
    source_url = str(source["source_url"])
    negative_dedup_key = hashlib.sha256(
        f"{source_url}#h2e-same-domain-unlisted".encode()
    ).hexdigest()
    with psycopg.connect(control_dsn) as conn:
        run_id = _make_run(conn, profile.scope)
        resource_id = create_resource(
            conn,
            run_id=run_id,
            dedup_key=negative_dedup_key,
            scope=profile.scope,
        )
        candidate = ResourceCandidate(
            candidate_id=uuid.uuid4(),
            resource_id=resource_id,
            run_id=run_id,
            scope=profile.scope,
            discovered_at=datetime.now(UTC),
            source_url=source_url,
            canonical_url=source_url,
            domain="eduscol.education.gouv.fr",
            proposed_type_doc="programme_officiel",
            title=str(source["title"]),
            publisher="Eduscol",
            language="fr",
            relevance_evidence=[str(source["scope_path"])],
            dedup_key=negative_dedup_key,
        )
        persist_resource_candidate(conn, candidate=candidate)
        current = get_resource_state(conn, resource_id=resource_id)
        assert current is not None
        state, version = current
        transition = apply_resource_transition(
            conn,
            resource_id=resource_id,
            expected_state=state,
            expected_version=version,
            new_state=ResourceState.CANDIDATE,
            actor="h2e-negative-rehearsal",
            run_id=run_id,
        )
        conn.commit()
    return candidate, transition.state_version


def _enforce_fetched_content(
    control_dsn: str,
    *,
    source: dict[str, Any],
    profile: CollectionProfile,
    authorization: ScopeAuthorizationArtifactV2,
    content: bytes,
    trace: dict[str, bool],
) -> None:
    """Exercise both live checks around fetch before any semantic processing."""
    scope = profile.scope
    source_url = str(source["source_url"])
    with psycopg.connect(control_dsn) as conn:
        verified = verify_scope_authorization(
            conn,
            authorization_id=authorization.authorization_id,
            scope=scope,
        )
        enforce_before_fetch(
            verified,
            authorization_id=authorization.authorization_id,
            scope=scope,
            manifest_digest=CORPUS_MANIFEST_SHA,
            profile_id=str(scope.collection),
            profile_version=profile.profile_version,
            profile_fingerprint=profile_fingerprint(profile),
            now=datetime.now(UTC),
        )
        enforce_destination(verified, url=source_url)
        trace["domain_gate_pass"] = True
        trace["fetch_called"] = True
        content_sha256 = hashlib.sha256(content).hexdigest()
        verified = verify_scope_authorization(
            conn,
            authorization_id=authorization.authorization_id,
            scope=scope,
        )
        require_h2_content_bound_authority(verified)
        enforce_content_sha256(verified, content_sha256=content_sha256)
        trace["content_gate_pass"] = True


def _build_publishable_resource(
    control_dsn: str,
    *,
    source: dict[str, Any],
    profile: CollectionProfile,
    authorization: ScopeAuthorizationArtifactV2,
    content: bytes,
    extracted: str,
    trace: dict[str, bool],
) -> tuple[uuid.UUID, uuid.UUID]:
    scope = profile.scope
    source_url = str(source["source_url"])
    content_sha256 = hashlib.sha256(content).hexdigest()
    with psycopg.connect(control_dsn) as conn:
        run_id = _make_run(conn, scope)
        resource_id = create_resource(
            conn,
            run_id=run_id,
            dedup_key=hashlib.sha256(source_url.encode()).hexdigest(),
            scope=scope,
        )
        now = datetime.now(UTC)
        candidate = ResourceCandidate(
            candidate_id=uuid.uuid4(),
            resource_id=resource_id,
            run_id=run_id,
            scope=scope,
            discovered_at=now,
            source_url=source_url,
            canonical_url=source_url,
            domain="eduscol.education.gouv.fr",
            proposed_type_doc="programme_officiel",
            title=str(source["title"]),
            publisher="Eduscol",
            language="fr",
            relevance_evidence=[str(source["scope_path"])],
            dedup_key=hashlib.sha256(source_url.encode()).hexdigest(),
        )
        persist_resource_candidate(conn, candidate=candidate)
        artifact = ArtifactRecord(
            artifact_id=uuid.uuid4(),
            resource_id=resource_id,
            run_id=run_id,
            scope=scope,
            sha256=content_sha256,
            size_bytes=len(content),
            mime_declared="application/pdf",
            mime_detected="application/pdf",
            original_url=source_url,
            final_url=source_url,
            collected_at=now,
            domain="eduscol.education.gouv.fr",
            license="EDUSCOL_RIGHTS_HUMAN_REVIEW_APPROVED",
            rights_status=Rights.unknown,
            title=str(source["title"]),
            publisher="Eduscol",
            pages_count=60,
            version="2019",
        )
        persist_artifact(conn, artifact=artifact)
        current = get_resource_state(conn, resource_id=resource_id)
        assert current is not None
        _, version = current
        for before, after in (
            (ResourceState.DISCOVERED, ResourceState.CANDIDATE),
            (ResourceState.CANDIDATE, ResourceState.FETCHED),
            (ResourceState.FETCHED, ResourceState.STORED),
            (ResourceState.STORED, ResourceState.EXTRACTED),
            (ResourceState.EXTRACTED, ResourceState.CLASSIFIED),
        ):
            version = apply_resource_transition(
                conn,
                resource_id=resource_id,
                expected_state=before,
                expected_version=version,
                new_state=after,
                actor="h2c-rehearsal",
                run_id=run_id,
                payload=(
                    {
                        "artifact_id": str(artifact.artifact_id),
                        "sha256": artifact.sha256,
                        "scope_authorization_id": authorization.authorization_id,
                        "scope_authorization_digest": authorization.digest(),
                        "scope_authorization_protocol_version": (
                            authorization.protocol_version
                        ),
                    }
                    if after is ResourceState.FETCHED
                    else None
                ),
            ).state_version
        trace["rights_agent_called"] = True
        rights, transition = run_rights_agent(
            conn,
            artifact=artifact,
            profile=profile,
            expected_version=version,
            actor="h2c-rehearsal",
        )
        assert rights is Rights.officiel_public
        trace["quality_agent_called"] = True
        _, decision, routed = run_quality_agent(
            conn,
            artifact=artifact,
            profile=profile,
            conformity=ConformityResult(
                niveau_conformity=True,
                voie_conformity=True,
                matiere_conformity=True,
                programme_conformity=True,
                matiere_evidence=("arts",),
            ),
            rights=rights,
            extracted_text=extracted,
            declared_language="fr",
            pii_detected=False,
            duplicate_detected=False,
            report_id=uuid.uuid4(),
            decision_id=uuid.uuid4(),
            evaluated_at=now,
            expected_version=transition.state_version,
            actor="h2c-rehearsal",
        )
        assert decision.decision == "ROUTE"
        assert routed.to_state is ResourceState.ROUTED
        conn.commit()
    return resource_id, artifact.artifact_id


def _capture_cli(function: Any, arguments: list[str]) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = function(arguments)
    return int(code), stdout.getvalue(), stderr.getvalue()


def _proposal(raw_output: str) -> tuple[str, bytes]:
    lines = raw_output.splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines) if line.startswith("REVIEW_ARTIFACT_PATH "))
    path = lines[index].split(" ", 1)[1].strip()
    assert lines[index + 1].startswith("REVIEW_ARTIFACT_DIGEST ")
    return path, "".join(lines[index + 2 :]).encode()


def _extract_pdf(content: bytes) -> str:
    return "\n\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)


def _embed(passages: Sequence[str]) -> list[tuple[float, ...]]:
    vectors: list[tuple[float, ...]] = []
    for passage in passages:
        digest = hashlib.sha256(passage.encode()).digest()
        second = (int.from_bytes(digest[:8], "big") + 1) / (2**64 + 1)
        vectors.append((1.0, second) + (0.0,) * (EMBED_DIMENSION - 2))
    return vectors


@contextmanager
def _retrieval_connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(APP_DSN) as conn:
        yield conn


def _retrieval_scope(scope: ResourceScope) -> ServerRetrievalScope:
    return ServerRetrievalScope(
        tenant=str(scope.tenant),
        niveau=scope.niveau.value,
        voie=scope.voie.value,
        matiere=str(scope.matiere),
        statut_enseignement=STATUT,
        candidat=scope.candidat.value,
        audiences=tuple(value.value for value in scope.audience),
        rights=(Rights.officiel_public,),
        visibilities=(str(scope.visibility),),
        school_year=str(scope.school_year),
        collection=str(scope.collection),
        programme_version=str(scope.programme_version),
        scope_id="h2c_rehearsal_scope",
        scope_digest="c" * 64,
        source_sha256="d" * 64,
    )


def test_real_pdf_runs_through_lot41_lot42_publisher_and_retrieval(
    control_pg: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw, source_placements = _real_inputs()
    profiles = tuple(_profile(_scope(source)) for source in source_placements)
    authorizations = tuple(
        _authorization(source, profile)
        for source, profile in zip(source_placements, profiles, strict=True)
    )
    github = LocalGitHub()
    for authorization in authorizations:
        github.put_blob(
            path=canonical_authorization_path(authorization.authorization_id),
            ref=AUTH_HEAD,
            content=authorization.canonical_bytes(),
        )
    github.add_approved_pr(
        number=AUTH_PR,
        head_sha=AUTH_HEAD,
        base_sha=BASE_HEAD,
        review_id=AUTH_REVIEW,
    )
    token_file = tmp_path / "github-token"
    token_file.write_text(VALID_TOKEN, encoding="utf-8")
    monkeypatch.setenv("PG_INGESTION_CONTROL_AUTHORITY_DSN", authority_dsn(control_pg))
    monkeypatch.setenv("PG_INGESTION_CONTROL_ATTESTOR_DSN", attestor_dsn(control_pg))
    monkeypatch.setenv("NEXUS_GITHUB_TOKEN_FILE", str(token_file))
    monkeypatch.delenv("NEXUS_GITHUB_TOKEN", raising=False)

    with local_github_server(github) as api_base:
        monkeypatch.setenv("NEXUS_GITHUB_API_BASE", api_base)
        for authorization in authorizations:
            code, _, error = _capture_cli(
                authorize_scope_main,
                [
                    "record-authorization",
                    "--authorization-id",
                    authorization.authorization_id,
                    "--repository",
                    REPOSITORY,
                    "--pull-request",
                    str(AUTH_PR),
                    "--expected-head",
                    AUTH_HEAD,
                ],
            )
            assert code == 0, error

        control_dsn = app_dsn(control_pg)
        negative_bytes = raw + b"\n% H2E same-domain unlisted bytes\n"
        negative_sha = hashlib.sha256(negative_bytes).hexdigest()
        assert negative_sha != REAL_SHA
        negative_source = source_placements[0]
        negative_profile = profiles[0]
        negative_authorization = authorizations[0]
        negative_candidate, negative_version = _candidate_at_candidate_state(
            control_dsn,
            source=negative_source,
            profile=negative_profile,
        )
        fetch_calls: list[str] = []
        domain_gate_passes: list[str] = []
        store_calls: list[bytes] = []
        extractor_spy = Mock(name="negative_extractor")
        rights_agent_spy = Mock(name="negative_rights_agent")
        quality_agent_spy = Mock(name="negative_quality_agent")

        with psycopg.connect(control_dsn) as negative_conn:

            def authorize_content(
                *, content_sha256: str, final_url: str
            ) -> ContentAuthorizationBinding:
                verified = verify_scope_authorization(
                    negative_conn,
                    authorization_id=negative_authorization.authorization_id,
                    scope=negative_profile.scope,
                )
                enforce_destination(verified, url=final_url)
                require_h2_content_bound_authority(verified)
                enforce_content_sha256(verified, content_sha256=content_sha256)
                return ContentAuthorizationBinding(
                    authorization_id=verified.authorization_id,
                    authorization_digest=verified.authorization_digest,
                    protocol_version=verified.protocol_version,
                )

            def store_negative(*, artifact_id: uuid.UUID, content: bytes) -> str:
                del artifact_id
                store_calls.append(content)
                return "memory://forbidden"

            with _local_pdf_server(negative_bytes) as local_url:

                def safe_fetch(
                    url: str, *, max_bytes: int, **kwargs: Any
                ) -> httpx.Response:
                    del kwargs
                    verified = verify_scope_authorization(
                        negative_conn,
                        authorization_id=negative_authorization.authorization_id,
                        scope=negative_profile.scope,
                    )
                    enforce_before_fetch(
                        verified,
                        authorization_id=negative_authorization.authorization_id,
                        scope=negative_profile.scope,
                        manifest_digest=CORPUS_MANIFEST_SHA,
                        profile_id=str(negative_profile.scope.collection),
                        profile_version=negative_profile.profile_version,
                        profile_fingerprint=profile_fingerprint(negative_profile),
                        now=datetime.now(UTC),
                    )
                    enforce_destination(verified, url=url)
                    domain_gate_passes.append(url)
                    fetch_calls.append(url)
                    response = httpx.get(local_url, timeout=10)
                    assert len(response.content) <= max_bytes
                    return httpx.Response(
                        response.status_code,
                        headers=response.headers,
                        content=response.content,
                        request=httpx.Request("GET", url),
                    )

                with pytest.raises(ScopeEnforcementViolation) as denied:
                    artifact, _, _ = run_fetcher(
                        negative_conn,
                        candidate=negative_candidate,
                        artifact_id=uuid.uuid4(),
                        collected_at=datetime.now(UTC),
                        expected_version=negative_version,
                        actor="h2e-negative-rehearsal",
                        max_bytes=len(negative_bytes) + 1,
                        store_artifact=store_negative,
                        authorize_content=authorize_content,
                        safe_fetch=safe_fetch,
                    )
                    extracted_negative = extractor_spy(artifact)
                    rights_negative = rights_agent_spy(artifact, extracted_negative)
                    quality_agent_spy(artifact, rights_negative)
        assert denied.value.checkpoint == "content"
        assert fetch_calls == [str(negative_source["source_url"])]
        assert domain_gate_passes == fetch_calls
        assert store_calls == []
        extractor_spy.assert_not_called()
        rights_agent_spy.assert_not_called()
        quality_agent_spy.assert_not_called()
        with psycopg.connect(ADMIN_DSN) as conn:
            negative_product_rows = conn.execute(
                "SELECT COUNT(*) FROM rag_artifacts WHERE content_sha256 = %s",
                (negative_sha,),
            ).fetchone()
        assert negative_product_rows == (0,)
        with psycopg.connect(control_dsn) as conn:
            negative_state_row = get_resource_state(
                conn, resource_id=negative_candidate.resource_id
            )
            assert negative_state_row is not None
            negative_state, _ = negative_state_row
            negative_control_artifact_row = conn.execute(
                "SELECT COUNT(*) FROM ingestion_control.artifacts WHERE sha256 = %s",
                (negative_sha,),
            ).fetchone()
            negative_eligibility_row = conn.execute(
                "SELECT COUNT(*) FROM ingestion_control.workflow_events "
                "WHERE resource_id = %s AND to_state = 'RETRIEVAL_ELIGIBLE'",
                (negative_candidate.resource_id,),
            ).fetchone()
        assert negative_control_artifact_row == (0,)
        assert negative_eligibility_row == (0,)
        assert negative_state is ResourceState.CANDIDATE
        negative_control_artifact_rows = int(negative_control_artifact_row[0])
        negative_retrieval_eligible = bool(negative_eligibility_row[0])

        resources: list[tuple[uuid.UUID, uuid.UUID]] = []
        positive_traces: list[dict[str, bool]] = []
        for source, profile, authorization in zip(
            source_placements, profiles, authorizations, strict=True
        ):
            trace = {
                "domain_gate_pass": False,
                "fetch_called": False,
                "content_gate_pass": False,
                "rights_agent_called": False,
                "quality_agent_called": False,
            }
            _enforce_fetched_content(
                control_dsn,
                source=source,
                profile=profile,
                authorization=authorization,
                content=raw,
                trace=trace,
            )
            positive_traces.append(trace)

        extraction_calls = 0

        def measured_extract(content: bytes) -> str:
            nonlocal extraction_calls
            extraction_calls += 1
            return _extract_pdf(content)

        extracted = measured_extract(raw)
        assert len(extracted.strip()) > 100_000

        def cached_extract(content: bytes) -> str:
            assert hashlib.sha256(content).hexdigest() == REAL_SHA
            return extracted

        for source, profile, authorization, trace in zip(
            source_placements,
            profiles,
            authorizations,
            positive_traces,
            strict=True,
        ):
            resources.append(
                _build_publishable_resource(
                    control_dsn,
                    source=source,
                    profile=profile,
                    authorization=authorization,
                    content=raw,
                    extracted=extracted,
                    trace=trace,
                )
            )
        assert all(all(trace.values()) for trace in positive_traces)

        proposals: list[tuple[str, bytes]] = []
        for index, ((resource_id, artifact_id), authorization) in enumerate(
            zip(resources, authorizations, strict=True)
        ):
            code, output, error = _capture_cli(
                attest_main,
                [
                    "propose-review",
                    "--resource-id",
                    str(resource_id),
                    "--artifact-id",
                    str(artifact_id),
                    "--scope-authorization-id",
                    authorization.authorization_id,
                    "--review-id",
                    f"h2c-rehearsal-{index}",
                ],
            )
            assert code == 0, error
            proposals.append(_proposal(output))
        for path, proposal in proposals:
            github.put_blob(path=path, ref=PUB_HEAD, content=proposal)
        github.add_approved_pr(
            number=PUB_PR,
            head_sha=PUB_HEAD,
            base_sha=BASE_HEAD,
            review_id=PUB_REVIEW,
            submitted_at="2026-08-09T00:00:00Z",
        )

        for index, ((resource_id, artifact_id), authorization) in enumerate(
            zip(resources, authorizations, strict=True)
        ):
            code, _, error = _capture_cli(
                attest_main,
                [
                    "record-attestation",
                    "--resource-id",
                    str(resource_id),
                    "--artifact-id",
                    str(artifact_id),
                    "--scope-authorization-id",
                    authorization.authorization_id,
                    "--review-id",
                    f"h2c-rehearsal-{index}",
                    "--repository",
                    REPOSITORY,
                    "--pull-request",
                    str(PUB_PR),
                    "--expected-head",
                    PUB_HEAD,
                ],
            )
            assert code == 0, error

        for (resource_id, _), authorization in zip(
            resources, authorizations, strict=True
        ):
            with psycopg.connect(control_dsn) as conn:
                current = conn.execute(
                    "SELECT run_id, state_version FROM ingestion_control.resources "
                    "WHERE resource_id = %s",
                    (resource_id,),
                ).fetchone()
                assert current is not None
                run_id, version = current
                staged = stage_publication_for_review(
                    conn,
                    resource_id=resource_id,
                    run_id=run_id,
                    expected_version=version,
                    actor="h2c-rehearsal",
                )
                promoted = promote_reviewed_publication(
                    conn,
                    resource_id=resource_id,
                    run_id=run_id,
                    expected_version=staged.needs_review.state_version,
                    actor="h2c-rehearsal",
                    current_content_sha256=REAL_SHA,
                    current_profile_fingerprint=authorization.profile_fingerprint,
                    current_manifest_digest=CORPUS_MANIFEST_SHA,
                )
                assert promoted.retrieval_eligible.to_state is ResourceState.RETRIEVAL_ELIGIBLE
                conn.commit()

        artifact = GovernedArtifact(
            content=raw,
            content_sha256=REAL_SHA,
            source_label=str(source_placements[0]["title"]),
            source_uri=f"urn:nexus:sha256:{REAL_SHA}",
            rights=Rights.officiel_public.value,
            official=True,
            source_kind="eduscol",
            type_doc="programme_officiel",
        )
        placements = tuple(
            EligiblePlacement(
                resource_id=resource_id,
                scope=profile.scope,
                statut_enseignement=STATUT,
                domain="eduscol.education.gouv.fr",
                source_scope=str(source["scope"]),
                source_placement_id=hashlib.sha256(
                    str(source["scope_path"]).encode()
                ).hexdigest(),
                source_path=str(source["technical_path"]),
                source_uri=str(source["source_url"]),
                current_profile_fingerprint=authorization.profile_fingerprint,
                current_manifest_digest=CORPUS_MANIFEST_SHA,
            )
            for source, profile, authorization, (resource_id, _) in zip(
                source_placements,
                profiles,
                authorizations,
                resources,
                strict=True,
            )
        )
        with (
            psycopg.connect(control_dsn) as control_conn,
            psycopg.connect(PUBLISHER_DSN) as product_conn,
        ):
            published = publish_governed_artifact(
                control_conn,
                product_conn,
                artifact,
                placements,
                cached_extract,
                _embed,
            )
            retried = publish_governed_artifact(
                control_conn,
                product_conn,
                artifact,
                placements,
                cached_extract,
                _embed,
            )

        assert published.artifact_created is True
        assert published.placement_rows == 7
        assert published.chunk_rows > 0
        assert published.embedded is True
        assert retried.artifact_created is False
        assert retried.placement_rows == 7
        assert retried.chunk_rows == published.chunk_rows
        assert retried.embedded is False

        with psycopg.connect(ADMIN_DSN) as conn:
            counts = conn.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM rag_artifacts WHERE artifact_id = %s),
                  (SELECT COUNT(*) FROM rag_artifact_placements WHERE artifact_id = %s),
                  (SELECT COUNT(*) FROM rag_chunks WHERE artifact_id = %s),
                  (SELECT COUNT(DISTINCT artifact_id) FROM rag_chunks WHERE artifact_id = %s)
                """,
                (REAL_SHA, REAL_SHA, REAL_SHA, REAL_SHA),
            ).fetchone()
        assert counts == (1, 7, published.chunk_rows, 1)

        query_vector = _embed(("programme arts première terminale",))[0]
        retrieval: dict[str, Any] = {}
        for source, profile in zip(source_placements, profiles, strict=True):
            candidates = PgCandidateStore(
                _retrieval_connection,
                _retrieval_scope(profile.scope),
            ).dense(
                query_vector=query_vector,
                collection=str(profile.scope.collection),
                limit=10,
            )
            assert candidates
            assert len({candidate.chunk_id for candidate in candidates}) == len(candidates)
            assert all(candidate.artifact_id == REAL_SHA for candidate in candidates)
            assert all(candidate.content_sha256 == REAL_SHA for candidate in candidates)
            assert all(candidate.source_uri == source["source_url"] for candidate in candidates)
            assert all(candidate.placement_source_path == source["technical_path"] for candidate in candidates)
            retrieval[str(profile.scope.collection)] = candidates

        wrong_scope = profiles[0].scope.model_copy(
            update={"collection": "h2c_rehearsal_wrong_scope"}
        )
        wrong = PgCandidateStore(
            _retrieval_connection,
            _retrieval_scope(wrong_scope),
        ).dense(
            query_vector=query_vector,
            collection="h2c_rehearsal_wrong_scope",
            limit=10,
        )
        assert wrong == []
        assert github.non_get_requests == []

    result = {
        "artifact_rows_for_sha": 1,
        "chunk_set_count": 1,
        "citation_traceability_pass": True,
        "duplicate_chunk_sets": 0,
        "duplicate_result_chunks": 0,
        "duplicate_vector_sets": 0,
        "full_governed_rehearsal_pass": True,
        "lot41a_v2_content_bound": True,
        "lot42_pipeline_path_implemented": True,
        "placement_rows": 7,
        "placement_traceability_pass": True,
        "real_multi_placement_placements": 7,
        "real_multi_placement_sha": REAL_SHA,
        "negative_same_domain_unlisted": {
            "content_allowlist_gate": "DENY",
            "control_artifact_rows": negative_control_artifact_rows,
            "domain_gate": "PASS" if domain_gate_passes == fetch_calls else "DENY",
            "extractor_called": bool(extractor_spy.call_count),
            "quality_agent_called": bool(quality_agent_spy.call_count),
            "resource_state": negative_state.value,
            "retrieval_eligible": negative_retrieval_eligible,
            "rights_agent_called": bool(rights_agent_spy.call_count),
            "store_called": bool(store_calls),
            "pgvector_rows_created": int(negative_product_rows[0]),
        },
        "positive_content_allowlist_gate": "PASS",
        "positive_extractor_calls": extraction_calls,
        "scope_a_retrieval_pass": bool(retrieval),
        "scope_b_retrieval_pass": len(retrieval) >= 2,
        "wrong_scope_retrieval_blocked": True,
    }
    print("H2E_V2_GOVERNED_REHEARSAL_RESULT=" + json.dumps(result, sort_keys=True))
