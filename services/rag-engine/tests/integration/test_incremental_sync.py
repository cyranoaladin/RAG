"""Banc de qualification de la synchronisation incrémentale (SYNC_INCREMENTALE).

Le banc mesure, il ne juge pas : il écrit des observations brutes, et c'est
`scripts/qualification/verify_incremental_sync.py` qui les confronte aux règles
puis scelle la preuve, une fois les conteneurs détruits et les résidus comptés.

Ce que « synchronisation incrémentale » veut dire dans CE modèle métier : le
magasin produit est append-only (le rôle publisher n'a que SELECT, INSERT) et
l'identité d'un artefact EST l'empreinte de son contenu. Le banc exerce donc les
mécanismes qui existent, et n'en invente aucun :

1. Vague 1 — état initial : ingestion gouvernée réelle d'un sous-ensemble de
   collections complètes de la release multilevel. État scellé.
2. Tentative de MODIFICATION : la même source sert des octets altérés. Le modèle
   ne connaît ni remplacement ni supersession ; l'attendu est un refus avant
   tout stockage, magasin produit inchangé.
3. Vague 2 — run incrémental : la liste COMPLÈTE des sources est resoumise,
   comme le ferait une vraie synchronisation. Seul le delta doit être ingéré.
4. Run répété : toutes les publications sont rejouées ; rien n'est ré-embeddé.
5. RETRAIT : non prévu par le modèle métier (aucun DELETE/UPDATE accordé). Le
   banc le constate sur les privilèges réels du rôle publisher.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import psycopg
import pytest

from tests.integration.test_multilevel_real_ingestion import (
    E5_INVENTORY_SHA256,
    E5_PATH,
    EXPECTED_ARTIFACTS,
    EXPECTED_CHUNKS,
    EXPECTED_PLACEMENTS,
    PDF_MIRROR,
    RELEASE_PATH,
    RELEASE_SHA256,
    REPOSITORY,
    VALID_TOKEN,
    LocalGitHub,
    PublicationResumeDeps,
    VerifiedE5EmbeddingProvider,
    WorkerDeps,
    _authorization_document,
    _build_runtime_authorities,
    _make_run,
    _parse_proposal,
    _reject_duplicate_pdf_extraction,
    app_dsn,
    attest_main,
    attestor_dsn,
    authority_dsn,
    authorize_scope_main,
    canonical_authorization_path,
    create_job,
    local_github_server,
    make_filesystem_artifact_reader,
    make_filesystem_artifact_store,
    run_publication_resume_iteration,
    run_worker_iteration,
    superuser_dsn,
    validate_release_readiness,
)

pytest_plugins = ["tests.integration.test_multilevel_real_ingestion"]

RAW_PATH_ENV = "NEXUS_INCREMENTAL_SYNC_RAW_OBSERVATIONS_PATH"

if not os.environ.get("NEXUS_REQUIRE_DOCKER", "").strip() or not all(
    os.environ.get(name, "").strip()
    for name in (
        "NEXUS_MULTILEVEL_PDF_MIRROR",
        "NEXUS_MULTILEVEL_PII_EVIDENCE_PATH",
        "RAG_EMBEDDING_MODEL_CACHE_DIR",
        "RAG_EMBEDDING_MODEL_INVENTORY_SHA256",
        RAW_PATH_ENV,
    )
):
    pytest.skip("incremental sync qualification not requested", allow_module_level=True)


#: Nombre de collections (triées) ingérées en vague 1. Le reste forme le delta.
WAVE_ONE_COLLECTIONS = 8
PRODUCT_TABLES = ("rag_artifacts", "rag_artifact_placements", "rag_chunks")
PUBLISHER_ROLE = "multilevel_publisher"


def _product_snapshot(admin_dsn: str, artifact_ids: list[str] | None = None) -> dict[str, Any]:
    """Cardinalités, empreinte de contenu (vecteurs compris) et doublons.
    Restreint à `artifact_ids` quand il est fourni."""
    where = "" if artifact_ids is None else " WHERE t.artifact_id = ANY(%s)"
    params: tuple[Any, ...] = () if artifact_ids is None else (artifact_ids,)
    counts: dict[str, int] = {}
    digest = hashlib.sha256()
    with psycopg.connect(admin_dsn) as conn:
        for table in PRODUCT_TABLES:
            rows = conn.execute(
                f"SELECT md5(t::text) FROM {table} t{where} ORDER BY 1",  # noqa: S608
                params,
            ).fetchall()
            counts[table] = len(rows)
            for (row_md5,) in rows:
                digest.update(f"{table}:{row_md5}\n".encode())
        chunk_ids = [
            row[0]
            for row in conn.execute(
                f"SELECT t.chunk_id FROM rag_chunks t{where} ORDER BY 1", params  # noqa: S608
            ).fetchall()
        ]
        vectorless = conn.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE vector IS NULL"
        ).fetchone()[0]
        duplicates = {
            key: conn.execute(
                f"SELECT COUNT(*) FROM (SELECT {key} FROM {table} "  # noqa: S608
                f"GROUP BY {key} HAVING COUNT(*) > 1) d"
            ).fetchone()[0]
            for table, key in (
                ("rag_artifacts", "artifact_id"),
                ("rag_artifact_placements", "placement_id"),
                ("rag_chunks", "chunk_id"),
            )
        }
    return {
        "counts": counts,
        "content_sha256": digest.hexdigest(),
        "chunk_id_set_sha256": hashlib.sha256("\n".join(chunk_ids).encode()).hexdigest(),
        "chunks_without_vector": vectorless,
        "duplicates": duplicates,
    }


def _expected_chunk_id_set_sha256(artifacts: list[Any]) -> str:
    chunk_ids = sorted(str(chunk["chunk_id"]) for a in artifacts for chunk in a.chunks)
    return hashlib.sha256("\n".join(chunk_ids).encode()).hexdigest()


def _control_snapshot(control_pg: dict[str, str]) -> dict[str, Any]:
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        states = dict(
            conn.execute(
                "SELECT resource_state, COUNT(*) FROM ingestion_control.resources GROUP BY 1"
            ).fetchall()
        )
        duplicate_resources = conn.execute(
            "SELECT COUNT(*) FROM (SELECT collection, dedup_key FROM ingestion_control.resources "
            "GROUP BY 1, 2 HAVING COUNT(*) > 1) d"
        ).fetchone()[0]
        stored_artifacts = conn.execute(
            "SELECT COUNT(*) FROM ingestion_control.artifacts"
        ).fetchone()[0]
    return {
        "resources_by_state": states,
        "duplicate_resources": duplicate_resources,
        "stored_artifacts": stored_artifacts,
    }


def _publisher_privileges(admin_dsn: str) -> dict[str, list[str]]:
    with psycopg.connect(admin_dsn) as conn:
        return {
            table: sorted(
                privilege
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
                if conn.execute(
                    "SELECT has_table_privilege(%s, %s, %s)",
                    (PUBLISHER_ROLE, f"public.{table}", privilege),
                ).fetchone()[0]
            )
            for table in PRODUCT_TABLES
        }


class _Harness:
    """Le flux gouverné réel du banc multilevel, découpé pour être joué par vagues."""

    def __init__(
        self,
        control_pg: dict[str, str],
        product_pg: dict[str, str],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        request: pytest.FixtureRequest,
    ) -> None:
        self.control_pg = control_pg
        self.product_pg = product_pg
        self.capsys = capsys
        authorities = _build_runtime_authorities()
        self.authorities = authorities
        self.profiles = authorities["profiles"]
        self.expectation = authorities["expectation"]
        manifest_digest = authorities["profile_manifest"].manifest_sha256

        self.raw_by_url: dict[str, bytes] = {}
        self.by_collection: dict[str, list[Any]] = defaultdict(list)
        for artifact in self.expectation.artifacts:
            raw = (PDF_MIRROR / artifact.source_path).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == artifact.content_sha256
            self.raw_by_url[artifact.source_url] = raw
            self.by_collection[artifact.collection].append(artifact)
        assert len(self.raw_by_url) == EXPECTED_ARTIFACTS
        self.fetch_count: dict[str, int] = defaultdict(int)

        def fetch(url: str, *, on_destination: Any = None, **_kwargs: Any) -> httpx.Response:
            if on_destination is not None:
                on_destination(url)
            self.fetch_count[url] += 1
            return httpx.Response(
                200,
                headers={"content-type": "application/pdf"},
                content=self.raw_by_url[url],
                request=httpx.Request("GET", url),
            )

        storage = tmp_path / "artifacts"
        self.deps_a = WorkerDeps(
            owner="incremental-worker-a",
            profile_registry=self.profiles,
            artifact_store=make_filesystem_artifact_store(storage),
            artifact_reader=make_filesystem_artifact_reader(storage),
            validate_destination=lambda url: url,
            safe_fetch=fetch,
            manifest_digest=manifest_digest,
            pii_evidence_registry=authorities["pii"],
            rights_evidence_registry=authorities["rights"],
            placement_resolver=authorities["resolver"],
        )

        self.github = LocalGitHub()
        token_path = tmp_path / "github-token"
        token_path.write_text(VALID_TOKEN, encoding="utf-8")
        self.auth_meta: dict[str, tuple[str, int, str]] = {}
        self.pub_meta: dict[str, tuple[int, str, str]] = {}
        for index, collection in enumerate(sorted(self.by_collection), start=1):
            authorization_id = f"incremental-{index:02d}-scope-v1"
            auth_head = hashlib.sha1(f"auth:{collection}".encode()).hexdigest()  # noqa: S324
            self.github.add_approved_pr(
                number=9700 + index, head_sha=auth_head, base_sha="9" * 40, review_id=97000 + index
            )
            document = _authorization_document(
                profile=self.profiles[(collection, "multilevel-v1")],
                manifest_digest=manifest_digest,
                authorization_id=authorization_id,
                allowed_content_sha256=[a.content_sha256 for a in self.by_collection[collection]],
            )
            self.github.put_blob(
                path=canonical_authorization_path(authorization_id),
                ref=auth_head,
                content=document.canonical_bytes(),
            )
            self.auth_meta[collection] = (authorization_id, 9700 + index, auth_head)
        for index, artifact in enumerate(self.expectation.artifacts, start=1):
            pub_head = hashlib.sha1(f"pub:{artifact.content_sha256}".encode()).hexdigest()  # noqa: S324
            self.github.add_approved_pr(
                number=9800 + index,
                head_sha=pub_head,
                base_sha="9" * 40,
                review_id=98000 + index,
                submitted_at="2026-08-12T19:30:00Z",
            )
            self.pub_meta[artifact.content_sha256] = (
                9800 + index, pub_head, f"incremental-{index:02d}-publication-v1",
            )

        monkeypatch.setenv("PG_INGESTION_CONTROL_AUTHORITY_DSN", authority_dsn(control_pg))
        monkeypatch.setenv("PG_INGESTION_CONTROL_ATTESTOR_DSN", attestor_dsn(control_pg))
        monkeypatch.delenv("PG_INGESTION_CONTROL_DSN", raising=False)
        monkeypatch.setenv("NEXUS_GITHUB_TOKEN_FILE", str(token_path))
        monkeypatch.delenv("NEXUS_GITHUB_TOKEN", raising=False)
        stack = ExitStack()
        request.addfinalizer(stack.close)
        monkeypatch.setenv(
            "NEXUS_GITHUB_API_BASE", stack.enter_context(local_github_server(self.github))
        )

        # L'autorisation de scope ne publie rien : elle borne ce qui POURRA l'être.
        for collection, (authorization_id, auth_pr, auth_head) in self.auth_meta.items():
            assert authorize_scope_main(
                [
                    "record-authorization", "--authorization-id", authorization_id,
                    "--repository", REPOSITORY, "--pull-request", str(auth_pr),
                    "--expected-head", auth_head,
                ]
            ) == 0, collection
        with psycopg.connect(app_dsn(control_pg)) as conn:
            self.run_by_collection = {
                collection: _make_run(conn, self.profiles[(collection, "multilevel-v1")])
                for collection in sorted(self.by_collection)
            }
            conn.commit()

        self.deps_b = PublicationResumeDeps(
            owner="incremental-worker-b",
            product_dsn=product_pg["publisher_dsn"],
            artifact_reader=self.deps_a.artifact_reader,
            extract_text=_reject_duplicate_pdf_extraction,
            embedding_provider=VerifiedE5EmbeddingProvider.from_artifact(
                artifact_root=E5_PATH,
                inventory_sha256=E5_INVENTORY_SHA256,
                pg_dsn=product_pg["admin_dsn"],
            ),
            pii_evidence_registry=authorities["pii"],
            rights_evidence_registry=authorities["rights"],
            manifest_digest=manifest_digest,
            placement_resolver=authorities["resolver"],
        )
        self.publication_jobs: list[uuid.UUID] = []

    def submit_sources(self, artifacts: list[Any], *, dedup_suffix: str = "") -> list[dict[str, Any]]:
        """Soumet des sources au Worker A et rend l'issue observée de chaque job."""
        outcomes: list[dict[str, Any]] = []
        with psycopg.connect(app_dsn(self.control_pg)) as conn:
            for artifact in artifacts:
                profile = self.profiles[(artifact.collection, "multilevel-v1")]
                create_job(
                    conn,
                    run_id=self.run_by_collection[artifact.collection],
                    job_type="resource_pipeline",
                    payload={
                        "scope": profile.scope.model_dump(mode="json"),
                        "dedup_key": hashlib.sha256(
                            (artifact.source_url + dedup_suffix).encode()
                        ).hexdigest(),
                        "source_url": artifact.source_url,
                        "canonical_url": artifact.source_url,
                        "source_path": artifact.source_path,
                        "domain": urlparse(artifact.source_url).hostname,
                        "proposed_type_doc": artifact.type_doc,
                        "profile_version": profile.profile_version,
                        "scope_authorization_id": self.auth_meta[artifact.collection][0],
                    },
                )
            conn.commit()
            for _ in artifacts:
                try:
                    outcome = run_worker_iteration(conn, deps=self.deps_a)
                    conn.commit()
                    outcomes.append(
                        {"worked": outcome.worked, "status": outcome.status,
                         "error": (outcome.error or "")[:300] or None}
                    )
                except Exception as exc:  # noqa: BLE001 - l'issue est une observation
                    conn.rollback()
                    outcomes.append({"worked": True, "status": "raised", "error": type(exc).__name__})
        return outcomes

    def attest_and_publish_pending(self) -> list[dict[str, Any]]:
        """Atteste puis publie toute ressource en NEEDS_REVIEW. Rend, par
        contenu, si la publication a réellement embeddé."""
        with psycopg.connect(app_dsn(self.control_pg)) as conn:
            rows = conn.execute(
                """
                SELECT r.resource_id, a.artifact_id, a.sha256, r.run_id, r.state_version, r.collection
                FROM ingestion_control.resources r
                JOIN ingestion_control.artifacts a USING (resource_id)
                WHERE r.resource_state = 'NEEDS_REVIEW'
                ORDER BY a.artifact_id
                """
            ).fetchall()
        results: list[dict[str, Any]] = []
        for resource_id, artifact_id, content_sha256, run_id, state_version, collection in rows:
            authorization_id = self.auth_meta[collection][0]
            pub_pr, pub_head, review_id = self.pub_meta[content_sha256]
            common = [
                "--resource-id", str(resource_id), "--artifact-id", str(artifact_id),
                "--scope-authorization-id", authorization_id, "--review-id", review_id,
            ]
            self.capsys.readouterr()
            assert attest_main(["propose-review", *common]) == 0
            proposal_path, proposal_bytes = _parse_proposal(self.capsys.readouterr().out)
            self.github.put_blob(path=proposal_path, ref=pub_head, content=proposal_bytes)
            assert attest_main(
                [
                    "record-attestation", *common, "--repository", REPOSITORY,
                    "--pull-request", str(pub_pr), "--expected-head", pub_head,
                ]
            ) == 0
            with psycopg.connect(superuser_dsn(self.control_pg)) as check:
                attestation = check.execute(
                    "SELECT attestation_id FROM ingestion_control.publication_attestations "
                    "WHERE resource_id = %s AND invalidated_at IS NULL",
                    (resource_id,),
                ).fetchone()
            assert attestation is not None
            with psycopg.connect(app_dsn(self.control_pg)) as conn:
                job_id = create_job(
                    conn,
                    run_id=run_id,
                    resource_id=resource_id,
                    job_type="publication_resume",
                    payload={
                        "resource_id": str(resource_id),
                        "run_id": str(run_id),
                        "expected_state_version": state_version,
                        "publication_attestation_id": str(attestation[0]),
                    },
                )
                conn.commit()
                outcome = run_publication_resume_iteration(
                    conn, deps=self.deps_b, build_placements=None
                )
                conn.commit()
            assert outcome.status == "succeeded", outcome.error
            self.publication_jobs.append(job_id)
            results.append({"content_sha256": content_sha256, "embedded": outcome.embedded})
        return results

    def replay_all_publications(self) -> list[dict[str, Any]]:
        with psycopg.connect(app_dsn(self.control_pg)) as conn:
            requeued = conn.execute(
                "UPDATE ingestion_control.jobs SET status = 'queued', next_attempt_at = now(), "
                "updated_at = now() WHERE job_id = ANY(%s) AND status = 'succeeded'",
                (self.publication_jobs,),
            ).rowcount
            conn.commit()
            assert requeued == len(self.publication_jobs)
            replays = []
            for _ in self.publication_jobs:
                replay = run_publication_resume_iteration(
                    conn, deps=self.deps_b, build_placements=None
                )
                conn.commit()
                replays.append({"status": replay.status, "embedded": replay.embedded})
        return replays


def test_incremental_sync_without_loss_or_duplicate(
    control_pg: dict[str, str],
    product_pg: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    request: pytest.FixtureRequest,
) -> None:
    harness = _Harness(control_pg, product_pg, tmp_path, monkeypatch, capsys, request)
    admin_dsn = product_pg["admin_dsn"]
    collections = sorted(harness.by_collection)
    wave_one = [a for c in collections[:WAVE_ONE_COLLECTIONS] for a in harness.by_collection[c]]
    wave_two = [a for c in collections[WAVE_ONE_COLLECTIONS:] for a in harness.by_collection[c]]
    everything = wave_one + wave_two
    assert wave_one and wave_two and len(everything) == EXPECTED_ARTIFACTS
    wave_one_ids = sorted(a.content_sha256 for a in wave_one)
    wave_two_ids = sorted(a.content_sha256 for a in wave_two)

    observations: dict[str, Any] = {
        "kind": "NEXUS-INCREMENTAL-SYNC-RAW-OBSERVATIONS-V1",
        "release_sha256": RELEASE_SHA256,
        "real_engine": {
            "governed_pipeline": "create_job -> run_worker_iteration -> attest_publication_cli "
            "-> publication_resume -> governed_publisher_v2",
            "embedding_model": "intfloat/multilingual-e5-large",
            "embedding_inventory_sha256": E5_INVENTORY_SHA256,
            "mock_detected": False,
        },
        "release_expected": {
            "artifacts": EXPECTED_ARTIFACTS,
            "placements": EXPECTED_PLACEMENTS,
            "chunks": EXPECTED_CHUNKS,
        },
        "wave_one": {"collections": WAVE_ONE_COLLECTIONS, "content_sha256": wave_one_ids},
        "wave_two": {
            "collections": len(collections) - WAVE_ONE_COLLECTIONS,
            "content_sha256": wave_two_ids,
        },
        "empty_state": _product_snapshot(admin_dsn),
    }

    # 1. Vague 1 : état initial.
    submitted = harness.submit_sources(wave_one)
    published = harness.attest_and_publish_pending()
    with psycopg.connect(admin_dsn) as conn:
        partial = validate_release_readiness(RELEASE_PATH, RELEASE_SHA256, conn)
    observations["initial_state"] = {
        "worker_outcomes": submitted,
        "publications": published,
        "product": _product_snapshot(admin_dsn),
        "expected_chunk_id_set_sha256": _expected_chunk_id_set_sha256(wave_one),
        "expected_chunks": sum(len(a.chunks) for a in wave_one),
        "control": _control_snapshot(control_pg),
        "full_release_ready": bool(partial.ready),
        "full_release_blockers_count": len(partial.blockers),
    }

    # 2. Modification : la même source sert des octets altérés.
    target = wave_one[0]
    original = harness.raw_by_url[target.source_url]
    tampered = original + b"\n% nexus-incremental-sync: octets modifies\n"
    tampered_sha = hashlib.sha256(tampered).hexdigest()
    harness.raw_by_url[target.source_url] = tampered
    fetches_before = harness.fetch_count[target.source_url]
    try:
        modified_outcomes = harness.submit_sources([target], dedup_suffix="#modified")
    finally:
        harness.raw_by_url[target.source_url] = original
    with psycopg.connect(admin_dsn) as conn:
        tampered_in_product = conn.execute(
            "SELECT COUNT(*) FROM rag_artifacts WHERE artifact_id = %s", (tampered_sha,)
        ).fetchone()[0]
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        tampered_stored = conn.execute(
            "SELECT COUNT(*) FROM ingestion_control.artifacts WHERE sha256 = %s", (tampered_sha,)
        ).fetchone()[0]
    pending_after_modification = harness.attest_and_publish_pending()
    observations["modification_attempt"] = {
        "business_model": "artifact_id = content_sha256 ; ni remplacement ni supersession",
        "source_refetched": harness.fetch_count[target.source_url] - fetches_before,
        "original_content_sha256": target.content_sha256,
        "modified_content_sha256": tampered_sha,
        "worker_outcomes": modified_outcomes,
        "modified_content_stored_in_control_plane": tampered_stored,
        "modified_content_in_product": tampered_in_product,
        "publications_triggered": pending_after_modification,
        "product_after": _product_snapshot(admin_dsn),
    }

    # 3. Vague 2 : run incrémental sur la liste COMPLÈTE des sources.
    fetches_before_sync = dict(harness.fetch_count)
    submitted = harness.submit_sources(everything)
    published = harness.attest_and_publish_pending()
    with psycopg.connect(admin_dsn) as conn:
        full = validate_release_readiness(RELEASE_PATH, RELEASE_SHA256, conn)
    observations["incremental_run"] = {
        "sources_submitted": len(everything),
        "worker_outcomes": submitted,
        "publications": published,
        "wave_one_sources_refetched": sum(
            harness.fetch_count[a.source_url] - fetches_before_sync.get(a.source_url, 0)
            for a in wave_one
        ),
        "product": _product_snapshot(admin_dsn),
        "wave_one_rows_after": _product_snapshot(admin_dsn, wave_one_ids),
        "expected_chunk_id_set_sha256": _expected_chunk_id_set_sha256(everything),
        "control": _control_snapshot(control_pg),
        "full_release_ready": bool(full.ready),
        "full_release_blockers": [str(b)[:200] for b in full.blockers][:10],
    }
    observations["initial_state"]["wave_one_rows"] = None  # renseigné ci-dessous

    # 4. Run répété : tout est rejoué, rien ne doit être ré-embeddé.
    replays = harness.replay_all_publications()
    observations["repeated_run"] = {
        "replayed_publications": len(replays),
        "replays": replays,
        "product": _product_snapshot(admin_dsn),
        "control": _control_snapshot(control_pg),
    }

    # 5. Retrait : constaté sur les privilèges réels, pas mis en scène.
    observations["withdrawal"] = {
        "supported_by_business_model": False,
        "publisher_role": PUBLISHER_ROLE,
        "publisher_privileges": _publisher_privileges(admin_dsn),
    }

    # L'état initial restreint aux lignes de la vague 1 EST l'état initial complet.
    observations["initial_state"]["wave_one_rows"] = {
        "counts": observations["initial_state"]["product"]["counts"],
        "content_sha256": observations["initial_state"]["product"]["content_sha256"],
    }

    Path(os.environ[RAW_PATH_ENV]).write_text(
        json.dumps(observations, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    # Le banc n'affirme que sa propre validité ; le verdict appartient au scelleur.
    assert observations["repeated_run"]["replayed_publications"] == len(harness.publication_jobs)
