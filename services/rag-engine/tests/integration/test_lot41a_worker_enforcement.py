"""LOT41A — enforcement du scope **pendant** l'ingestion (item **D**).

PostgreSQL réel, worker réel, chaîne Scout→QualityAgent réelle. Ce que ce
fichier prouve, et que les suites de contrat ne peuvent pas prouver seules :

- l'autorisation vérifiée est **conservée et appliquée**, pas calculée puis
  jetée ;
- chaque point de contrôle refuse pour de vrai, au bon moment, et laisse un
  ``SCOPE_AUTHORIZATION_DENIED`` **durable** nommant le point de contrôle ;
- une redirection hors domaine autorisé interrompt le téléchargement,
  scénario invisible depuis le seul payload du job ;
- une révocation survenue *pendant* le traitement empêche la ressource
  d'avancer, sans attendre le job suivant.
"""
from __future__ import annotations

import hashlib
import socket
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _authorization_stub import (  # noqa: E402
    STUB_AUTHORIZATION_ID,
    stub_verifier,
    verified_authorization,
)
from _pg_authority import (  # noqa: E402
    app_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)
from nexus_contracts.ingestion import CollectionProfile  # noqa: E402

from ingestor.ingestion_control.jobs import create_job  # noqa: E402
from ingestor.ingestion_control.scope_authority import (  # noqa: E402
    ScopeAuthorizationDeniedError,
)
from ingestor.ingestion_profiles.registry import profile_fingerprint  # noqa: E402
from ingestor.ingestion_worker import runner as runner_module  # noqa: E402
from ingestor.ingestion_worker.runner import WorkerDeps, run_worker_iteration  # noqa: E402
from ingestor.ingestion_worker.storage import (  # noqa: E402
    make_filesystem_artifact_reader,
    make_filesystem_artifact_store,
)
from ingestor.ssrf_guard import safe_fetch  # noqa: E402

pytestmark = [pytest.mark.integration, requires_docker]

MANIFEST_DIGEST = "7" * 64
#: Manifeste de corpus des preuves scellées de ce banc.
CORPUS_MANIFEST_SHA = "d" * 64
FETCH_CONTENT = b"<p>Cours d'algorithmique: recursivite, tris, structures.</p>"

VALID_SCOPE: dict[str, Any] = {
    "tenant": "libre_terminale",
    "collection": "rag_nexus_nsi_terminale_specialite",
    "niveau": "terminale",
    "voie": "generale",
    "matiere": "nsi",
    "candidat": "libre",
    "audience": ["libre", "tous"],
    "visibility": "internal",
    "school_year": "2026-2027",
    "programme_version": "BOEN_special_8_2019-07-25",
}

PROFILE = CollectionProfile.model_validate({
    "profile_version": "v1",
    "enabled": True,
    "scope": VALID_SCOPE,
    "title": "NSI Terminale Spécialité",
    "owner": "equipe-nsi",
    "expected_topics": ["algorithmique"],
    "expected_resource_types": ["cours"],
    "allowed_domains": ["eduscol.education.fr", "eduscol.education.gouv.fr"],
    "source_authority": "official",
    "search_cadence": "weekly",
    "max_queries_per_run": 10,
    "max_documents_per_run": 20,
    "max_chunk_size": 800,
    "chunk_overlap": 100,
    "min_source_confidence": 0.7,
    "min_scope_confidence": 0.7,
    "min_extraction_quality": 0.1,
})
REGISTRY = {(PROFILE.scope.collection, PROFILE.profile_version): PROFILE}


def job_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "scope": VALID_SCOPE,
        "dedup_key": "e" * 64,
        "source_url": "https://eduscol.education.fr/nsi/algo",
        "canonical_url": "https://eduscol.education.fr/nsi/algo",
        "domain": "eduscol.education.fr",
        "proposed_type_doc": "cours",
        "profile_version": "v1",
        "scope_authorization_id": STUB_AUTHORIZATION_ID,
    }
    payload.update(overrides)
    return payload


def authorization(**overrides: Any) -> Any:
    defaults: dict[str, Any] = {
        "scope": VALID_SCOPE,
        "manifest_digest": MANIFEST_DIGEST,
        "profile_id": PROFILE.scope.collection,
        "profile_version": PROFILE.profile_version,
        "profile_fingerprint": profile_fingerprint(PROFILE),
    }
    defaults.update(overrides)
    return verified_authorization(**defaults)


def fetch_ok(url: str, *, max_bytes: int, **kwargs: Any) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/html"},
        content=FETCH_CONTENT,
        request=httpx.Request("GET", url),
    )


def sealed_registries(tmp_path: Path) -> tuple[Any, Any]:
    """Registres scellés RÉELS pour un worker de test.

    Ce banc construisait un worker sans aucun registre. Depuis que la preuve
    scellée est obligatoire, `require_sealed_evidence` refusait donc AVANT
    d'atteindre les points de contrôle que ces tests mesurent : l'échec ne
    disait plus rien sur les droits ni sur le périmètre.

    `non_publishable=True` aurait fait passer les tests — et les aurait
    VIDÉS : ce drapeau saute entièrement la résolution des droits
    (`runner.py`, « if not deps.non_publishable »). Un test vert qui n'exerce
    plus la garde qu'il prétend tenir est pire que le rouge qu'il remplace.

    Les registres sont donc réels, et volontairement ÉTROITS : ils
    n'approuvent qu'une zone `01_EDUSCOL_OFFICIEL/`, dans laquelle le contenu
    récupéré par ce banc ne tombe pas. Le worker atteint le point de contrôle
    des droits et refuse — ce qui est exactement ce qu'on veut prouver."""
    import hashlib
    import json

    from ingestor.ingestion_control.sealed_evidence import (
        VerifiedPIIEvidenceRegistry,
        VerifiedRightsEvidenceRegistry,
    )

    root = tmp_path / "sealed"
    root.mkdir(parents=True, exist_ok=True)
    content_sha = hashlib.sha256(FETCH_CONTENT).hexdigest()
    pii = root / "pii.json"
    pii.write_text(
        json.dumps(
            {
                "evidence_kind": "REAL_CORPUS_PII_SCAN",
                "corpus_manifest_sha256": CORPUS_MANIFEST_SHA,
                "remote_access_mode": "READ_ONLY",
                "remote_write_operations": 0,
                "raw_pii_in_output": False,
                "raw_pii_in_logs": False,
                "results": [
                    {"content_sha256": content_sha, "status": "CLEARED", "pii_detected": False}
                ],
            }
        ),
        encoding="utf-8",
    )
    rights = root / "rights.yml"
    rights.write_text(
        "registry_id: worker-enforcement\n"
        "human_rights_decisions:\n"
        "  eduscol:\n"
        f'    scope_manifest_sha256: "{CORPUS_MANIFEST_SHA}"\n'
        "    scope_zone: 01_EDUSCOL_OFFICIEL/\n"
        "    approved_for_production_rag: true\n"
        "source_evidence:\n"
        "  eduscol:\n"
        "    zone: 01_EDUSCOL_OFFICIEL/\n"
        "    recommended_rights_category: officiel_public\n",
        encoding="utf-8",
    )
    return (
        VerifiedPIIEvidenceRegistry.load(
            pii,
            expected_evidence_sha256=hashlib.sha256(pii.read_bytes()).hexdigest(),
            expected_corpus_manifest_sha256=CORPUS_MANIFEST_SHA,
        ),
        VerifiedRightsEvidenceRegistry.load(
            rights,
            expected_registry_sha256=hashlib.sha256(rights.read_bytes()).hexdigest(),
            expected_corpus_manifest_sha256=CORPUS_MANIFEST_SHA,
        ),
    )


def assert_rights_were_not_manufactured(outcome: Any) -> None:
    """Le worker a refusé FAUTE de droits — jamais en les inférant.

    L'assertion portait sur la chaîne `Rights.unknown`, produite par une
    version antérieure du registre. L'architecture actuelle refuse en
    NOMMANT les zones qu'un humain a approuvées, ce qui est plus précis, pas
    moins : recopier la nouvelle chaîne aurait juste déplacé le problème.

    Ce qui est vérifié ici est la propriété, et elle n'a pas bougé : le job
    ne réussit pas, et le refus parle de droits que personne n'a accordés."""
    assert outcome.status in ("retried", "dead_letter"), (
        f"un job sans droits résolus ne doit jamais réussir (statut {outcome.status!r})"
    )
    error = str(outcome.error)
    assert "rights" in error.lower(), (
        f"le refus doit nommer les droits, pas une cause accessoire : {error!r}"
    )
    assert "inferring" in error or "unknown rights" in error, (
        "le refus doit dire qu'aucun droit n'est INFÉRÉ — un worker qui se "
        f"rabattrait sur la licence de l'artefact ne dirait pas cela : {error!r}"
    )


def deps_for(
    tmp_path: Path, *, auth: Any, safe_fetch_impl: Any = fetch_ok,
    manifest_digest: str = MANIFEST_DIGEST, owner: str = "worker-enforcement",
    artifact_store_impl: Any = None,
) -> WorkerDeps:
    return WorkerDeps(
        owner=owner,
        profile_registry=REGISTRY,
        artifact_store=(
            artifact_store_impl
            if artifact_store_impl is not None
            else make_filesystem_artifact_store(tmp_path / "artifacts")
        ),
        artifact_reader=make_filesystem_artifact_reader(tmp_path / "artifacts"),
        validate_destination=lambda url: url,
        safe_fetch=safe_fetch_impl,
        verify_scope_authorization=stub_verifier(auth),
        manifest_digest=manifest_digest,
        **dict(zip(
            ("pii_evidence_registry", "rights_evidence_registry"),
            sealed_registries(tmp_path),
            strict=True,
        )),
    )


@pytest.fixture(scope="module")
def pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("lot41a-enforce")


@pytest.fixture
def conn(pg: dict[str, str]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(app_dsn(pg)) as connection:
        yield connection


@pytest.fixture(autouse=True)
def _clean(pg: dict[str, str]) -> Iterator[None]:
    with psycopg.connect(superuser_dsn(pg)) as connection:
        with connection.cursor() as cur:
            for table in (
                "publication_attestations", "workflow_events", "artifacts",
                "resource_candidates", "jobs", "resources", "ingestion_runs",
            ):
                cur.execute(f"DELETE FROM ingestion_control.{table}")  # noqa: S608
        connection.commit()
    yield


def make_run(conn: psycopg.Connection) -> uuid.UUID:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.ingestion_runs
                (tenant, collection, niveau, voie, matiere, candidat, audience,
                 visibility, school_year, programme_version, profile_version,
                 trigger, status)
            VALUES (%(tenant)s, %(collection)s, %(niveau)s, %(voie)s, %(matiere)s,
                    %(candidat)s, %(audience)s, %(visibility)s, %(school_year)s,
                    %(programme_version)s, 'v1', 'manual', 'planned')
            RETURNING run_id
            """,
            {**VALID_SCOPE, "audience": sorted(VALID_SCOPE["audience"])},
        )
        row = cur.fetchone()
    assert row is not None
    conn.commit()
    return row[0]


def denial_events(conn: psycopg.Connection) -> list[dict[str, Any]]:
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM ingestion_control.workflow_events "
            "WHERE event_type = 'SCOPE_AUTHORIZATION_DENIED' ORDER BY occurred_at"
        )
        return [row[0] for row in cur.fetchall()]


def run_once(conn: psycopg.Connection, deps: WorkerDeps) -> Any:
    return run_worker_iteration(conn, deps=deps)


def submit(conn: psycopg.Connection, **payload_overrides: Any) -> uuid.UUID:
    run_id = make_run(conn)
    create_job(
        conn, run_id=run_id, job_type="resource_pipeline",
        payload=job_payload(**payload_overrides),
    )
    conn.commit()
    return run_id


class TestRightsEvidenceIsIndependentFromScopeAuthority:
    def test_scope_authority_alone_cannot_manufacture_rights_evidence(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        submit(conn)
        outcome = run_once(conn, deps_for(tmp_path, auth=authorization()))
        assert_rights_were_not_manufactured(outcome)
        assert denial_events(conn) == []
        with conn.cursor() as cur:
            cur.execute(
                "SELECT j.payload ? 'license', a.payload->>'license' "
                "FROM ingestion_control.jobs j "
                "JOIN ingestion_control.artifacts a ON a.resource_id = j.resource_id"
            )
            row = cur.fetchone()
        assert row == (False, None), (
            "the supported job shape carries no caller-controlled license; "
            "LOT41A constrains categories but is never itself license evidence"
        )

    def test_a_payload_license_cannot_inject_rights_evidence(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        submit(conn, license="FORGED-OPERATOR-ASSERTION")
        outcome = run_once(conn, deps_for(tmp_path, auth=authorization()))
        assert_rights_were_not_manufactured(outcome)
        with conn.cursor() as cur:
            cur.execute("SELECT payload->>'license' FROM ingestion_control.artifacts")
            row = cur.fetchone()
        assert row == (None,)


class TestPreFetchCheckpointIsDurable:
    @pytest.mark.parametrize(
        ("label", "kwargs", "fragment"),
        [
            ("manifest drift", {"manifest_digest": "9" * 64}, "manifest drift"),
            ("profile fingerprint drift",
             {"authorization_override": {"profile_fingerprint": "9" * 64}},
             "profile drift"),
            ("profile version drift",
             {"authorization_override": {"profile_version": "v9"}},
             "profile drift"),
        ],
    )
    def test_drift_fails_closed_and_is_journaled(
        self, conn: psycopg.Connection, tmp_path: Path,
        label: str, kwargs: dict[str, Any], fragment: str,
    ) -> None:
        submit(conn)
        overrides = kwargs.get("authorization_override", {})
        deps = deps_for(
            tmp_path,
            auth=authorization(**overrides),
            manifest_digest=kwargs.get("manifest_digest", MANIFEST_DIGEST),
        )
        outcome = run_once(conn, deps)
        assert outcome.status in ("retried", "dead_letter")
        events = denial_events(conn)
        assert len(events) == 1, events
        assert events[0]["checkpoint"] == "pre_fetch"
        assert fragment in events[0]["reason"]
        assert events[0]["scope_authorization_id"] == STUB_AUTHORIZATION_ID

    def test_a_job_naming_an_unknown_authorization_is_denied(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        """Item C au niveau du worker : le job nomme une autorisation qui
        n'existe pas — aucune autre ne prend sa place."""
        submit(conn, scope_authorization_id="auth-does-not-exist")
        outcome = run_once(conn, deps_for(tmp_path, auth=authorization()))
        assert outcome.status in ("retried", "dead_letter")
        events = denial_events(conn)
        assert len(events) == 1
        assert events[0]["scope_authorization_id"] == "auth-does-not-exist"

    def test_a_job_without_an_authorization_id_is_rejected(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        run_id = make_run(conn)
        payload = job_payload()
        del payload["scope_authorization_id"]
        create_job(conn, run_id=run_id, job_type="resource_pipeline", payload=payload)
        conn.commit()
        outcome = run_once(conn, deps_for(tmp_path, auth=authorization()))
        assert outcome.status in ("retried", "dead_letter")
        assert "scope_authorization_id" in str(outcome.error)

    def test_an_authorization_valid_only_in_the_future_is_denied(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        future = datetime.now(UTC) + timedelta(days=5)
        submit(conn)
        auth = authorization(
            valid_from=future, valid_until=future + timedelta(days=30)
        )
        outcome = run_once(conn, deps_for(tmp_path, auth=auth))
        assert outcome.status in ("retried", "dead_letter")
        assert denial_events(conn)[0]["checkpoint"] == "pre_fetch"

    def test_an_expired_authorization_is_denied(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        past = datetime.now(UTC) - timedelta(days=5)
        submit(conn)
        auth = authorization(valid_from=past - timedelta(days=30), valid_until=past)
        outcome = run_once(conn, deps_for(tmp_path, auth=auth))
        assert outcome.status in ("retried", "dead_letter")
        assert "expired" in denial_events(conn)[0]["reason"]

    def test_nothing_is_fetched_when_the_pre_fetch_checkpoint_denies(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        """La preuve que le refus arrive AVANT tout accès réseau : le
        téléchargeur injecté n'est jamais appelé."""
        calls: list[str] = []

        def recording_fetch(url: str, *, max_bytes: int, **kwargs: Any) -> httpx.Response:
            calls.append(url)
            return fetch_ok(url, max_bytes=max_bytes, **kwargs)

        submit(conn)
        deps = deps_for(
            tmp_path, auth=authorization(), safe_fetch_impl=recording_fetch,
            manifest_digest="9" * 64,
        )
        run_once(conn, deps)
        assert calls == []


class TestDestinationCheckpoint:
    def test_an_out_of_scope_source_url_is_denied(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        submit(
            conn,
            source_url="https://attacker.test/nsi",
            canonical_url="https://attacker.test/nsi",
            domain="attacker.test",
        )
        outcome = run_once(conn, deps_for(tmp_path, auth=authorization()))
        assert outcome.status in ("retried", "dead_letter")
        events = denial_events(conn)
        assert events[0]["checkpoint"] == "destination"
        assert "attacker.test" in events[0]["reason"]

    def test_an_out_of_scope_canonical_url_is_denied(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        """Le payload peut être conforme sur ``source_url`` et divergent sur
        ``canonical_url`` — les deux sont contrôlées."""
        submit(conn, canonical_url="https://attacker.test/nsi")
        outcome = run_once(conn, deps_for(tmp_path, auth=authorization()))
        assert outcome.status in ("retried", "dead_letter")
        assert denial_events(conn)[0]["checkpoint"] == "destination"

    def test_an_excluded_path_is_denied(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        submit(
            conn,
            source_url="https://eduscol.education.fr/prive/x",
            canonical_url="https://eduscol.education.fr/prive/x",
        )
        auth = authorization(exclusions=("/prive",))
        outcome = run_once(conn, deps_for(tmp_path, auth=auth))
        assert outcome.status in ("retried", "dead_letter")
        assert "matches exclusion" in denial_events(conn)[0]["reason"]

    def test_a_redirect_out_of_scope_stops_the_download(
        self,
        conn: psycopg.Connection,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Scénario invisible depuis le payload : l'URL demandée est
        autorisée, la redirection ne l'est pas. Le vrai ``safe_fetch`` est
        utilisé, avec un transport httpx local qui redirige réellement."""
        hops: list[str] = []

        class RedirectingTransport(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                hops.append(str(request.url))
                if request.url.host == "eduscol.education.fr":
                    return httpx.Response(
                        302, headers={"location": "https://attacker.test/leak"},
                        request=request,
                    )
                return httpx.Response(200, content=b"leaked", request=request)

        def real_safe_fetch(url: str, *, max_bytes: int, **kwargs: Any) -> httpx.Response:
            kwargs.pop("transport", None)
            return safe_fetch(
                url, max_bytes=max_bytes, transport=RedirectingTransport(), **kwargs
            )

        # Le scénario porte sur la redirection et non sur le résolveur DNS de
        # l'hôte de CI. Une résolution DNS64 (64:ff9b::/96) ferait refuser
        # l'URL initiale par le garde SSRF avant même le premier saut.
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *_args, **_kwargs: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
            ],
        )
        submit(conn)
        deps = deps_for(
            tmp_path,
            auth=authorization(
                protocol_version="LOT41A-V2",
                allowed_content_sha256=(hashlib.sha256(b"leaked").hexdigest(),),
            ),
            safe_fetch_impl=real_safe_fetch,
        )
        outcome = run_once(conn, deps)
        assert outcome.status in ("retried", "dead_letter")
        assert "attacker.test" in str(outcome.error)
        assert not any("attacker.test" in hop for hop in hops), (
            f"la redirection hors domaine ne doit JAMAIS être contactée, hops={hops}"
        )

    def test_an_allowed_sha_cannot_rescue_an_excluded_destination(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        content_sha = hashlib.sha256(FETCH_CONTENT).hexdigest()
        submit(
            conn,
            source_url="https://eduscol.education.fr/prive/approved.pdf",
            canonical_url="https://eduscol.education.fr/prive/approved.pdf",
        )
        auth = authorization(
            protocol_version="LOT41A-V2",
            allowed_content_sha256=(content_sha,),
            exclusions=("/prive",),
        )
        fetch_calls: list[str] = []

        def should_not_fetch(url: str, *, max_bytes: int, **kwargs: Any) -> httpx.Response:
            fetch_calls.append(url)
            return fetch_ok(url, max_bytes=max_bytes, **kwargs)

        outcome = run_once(
            conn, deps_for(tmp_path, auth=auth, safe_fetch_impl=should_not_fetch)
        )
        assert outcome.status in ("retried", "dead_letter")
        assert fetch_calls == []
        assert denial_events(conn)[0]["checkpoint"] == "destination"


class TestContentCheckpoint:
    def test_same_host_unlisted_bytes_are_denied_before_any_persistence_or_agent(
        self,
        conn: psycopg.Connection,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        source_url = "https://eduscol.education.gouv.fr/philosophie/unapproved.pdf"
        unapproved_bytes = b"same-host bytes outside reviewed allowlist"
        approved_sha = hashlib.sha256(b"different approved bytes").hexdigest()
        fetch_calls: list[str] = []
        store_calls: list[bytes] = []
        downstream_calls: list[str] = []

        def same_host_fetch(url: str, *, max_bytes: int, **kwargs: Any) -> httpx.Response:
            fetch_calls.append(url)
            return httpx.Response(
                200,
                headers={"content-type": "application/pdf"},
                content=unapproved_bytes,
                request=httpx.Request("GET", url),
            )

        def record_store(*, artifact_id: object, content: bytes) -> str:
            store_calls.append(content)
            return f"mem://{artifact_id}"

        def forbidden_downstream(*args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            downstream_calls.append("called")
            raise AssertionError("a denied document reached a downstream agent")

        monkeypatch.setattr(runner_module, "run_extractor", forbidden_downstream)
        monkeypatch.setattr(runner_module, "run_rights_agent", forbidden_downstream)
        monkeypatch.setattr(runner_module, "run_quality_agent", forbidden_downstream)

        submit(
            conn,
            source_url=source_url,
            canonical_url=source_url,
            domain="eduscol.education.gouv.fr",
        )
        auth = authorization(
            protocol_version="LOT41A-V2",
            allowed_content_sha256=(approved_sha,),
            allowed_domains=("eduscol.education.gouv.fr",),
        )
        (tmp_path / "artifacts").mkdir()
        outcome = run_once(
            conn,
            deps_for(
                tmp_path,
                auth=auth,
                safe_fetch_impl=same_host_fetch,
                artifact_store_impl=record_store,
            ),
        )

        assert outcome.status in ("retried", "dead_letter")
        assert fetch_calls == [source_url], "the allowed-domain download occurs exactly once"
        assert store_calls == [], "unauthorized bytes must never reach artifact storage"
        assert downstream_calls == [], "extractor/rights/quality must remain unreachable"
        events = denial_events(conn)
        assert len(events) == 1
        assert events[0]["checkpoint"] == "content"
        assert approved_sha not in events[0]["reason"]
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM ingestion_control.artifacts")
            assert cur.fetchone() == (0,)
            cur.execute("SELECT resource_state FROM ingestion_control.resources")
            assert cur.fetchone() == ("CANDIDATE",)
            cur.execute(
                "SELECT count(*) FROM ingestion_control.workflow_events "
                "WHERE to_state IN ('FETCHED', 'STORED', 'EXTRACTED', "
                "'RIGHTS_CHECKED', 'QUALITY_CHECKED', 'RETRIEVAL_ELIGIBLE')"
            )
            assert cur.fetchone() == (0,)

    def test_allowed_v2_bytes_bind_the_fetched_event_before_rights_fail_closed(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        expected_sha = hashlib.sha256(FETCH_CONTENT).hexdigest()
        auth = authorization(
            protocol_version="LOT41A-V2",
            allowed_content_sha256=(expected_sha,),
        )
        submit(conn)
        outcome = run_once(conn, deps_for(tmp_path, auth=auth))
        assert_rights_were_not_manufactured(outcome)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM ingestion_control.workflow_events "
                "WHERE to_state = 'FETCHED'"
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0]["sha256"] == expected_sha
        assert row[0]["scope_authorization_id"] == auth.authorization_id
        assert row[0]["scope_authorization_digest"] == auth.authorization_digest
        assert row[0]["scope_authorization_protocol_version"] == "LOT41A-V2"


class TestRightsCheckpoint:
    def test_scope_categories_do_not_replace_missing_rights_evidence(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        """Même une catégorie autorisée ne crée aucune licence."""
        submit(conn)
        auth = authorization(rights_categories=("officiel_public",))
        outcome = run_once(conn, deps_for(tmp_path, auth=auth))
        assert_rights_were_not_manufactured(outcome)
        assert denial_events(conn) == []

    def test_the_resource_never_reaches_quality_checked_when_rights_are_denied(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        submit(conn)
        auth = authorization(rights_categories=("restricted",))
        run_once(conn, deps_for(tmp_path, auth=auth))
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SELECT resource_state FROM ingestion_control.resources")
            states = [row[0] for row in cur.fetchall()]
        assert "QUALITY_CHECKED" not in states
        assert "ROUTED" not in states


class TestRevocationTakesEffectMidRun:
    def test_an_authorization_revoked_during_processing_stops_the_resource(
        self, conn: psycopg.Connection, tmp_path: Path
    ) -> None:
        """L'autorisation vérifie au premier point de contrôle puis cesse de
        vérifier : la ressource ne franchit même pas ``FETCHED``. C'est la
        preuve que la revalidation live du checkpoint ``content`` est réelle
        — un seul appel au démarrage aurait laissé passer ce run."""
        state = {"calls": 0}
        auth = authorization(
            protocol_version="LOT41A-V2",
            allowed_content_sha256=(hashlib.sha256(FETCH_CONTENT).hexdigest(),),
        )

        def revoking_verifier(
            connection: psycopg.Connection, *, authorization_id: str,
            scope: Any = None, now: Any = None,
        ) -> Any:
            state["calls"] += 1
            if state["calls"] == 1:
                return auth
            raise ScopeAuthorizationDeniedError(
                f"authorization {authorization_id!r} was revoked at 2026-08-08 "
                "(reason='revoquee pendant le run')"
            )

        submit(conn)
        deps = WorkerDeps(
            owner="worker-revocation",
            profile_registry=REGISTRY,
            artifact_store=make_filesystem_artifact_store(tmp_path / "artifacts"),
            artifact_reader=make_filesystem_artifact_reader(tmp_path / "artifacts"),
            validate_destination=lambda url: url,
            safe_fetch=fetch_ok,
            verify_scope_authorization=revoking_verifier,
            manifest_digest=MANIFEST_DIGEST,
        )
        outcome = run_once(conn, deps)
        assert outcome.status in ("retried", "dead_letter")
        assert state["calls"] >= 2, (
            "l'autorisation doit être revalidée en direct à un second point de "
            "contrôle — sinon une révocation en cours de run passerait"
        )
        events = denial_events(conn)
        assert events[0]["checkpoint"] == "content"
        assert "revoked" in events[0]["reason"]

        with conn.cursor() as cur:
            cur.execute("SELECT resource_state FROM ingestion_control.resources")
            states = [row[0] for row in cur.fetchall()]
            cur.execute("SELECT count(*) FROM ingestion_control.artifacts")
            artifact_count = cur.fetchone()
        assert states == ["CANDIDATE"]
        assert artifact_count == (0,)
        assert "QUALITY_CHECKED" not in states
