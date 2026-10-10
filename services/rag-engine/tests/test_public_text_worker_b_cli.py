"""Le Worker B public ne réclame aucun job sous une autorité C absente."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from nexus_contracts.staging_readiness import STAGING_READINESS_PROTOCOL

from ingestor.ingestion_worker import multilevel_publication_resume_cli as cli

SHA = "a" * 64
WORKER_IMAGE = "ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:" + SHA


def _public_args() -> list[str]:
    return [
        "--public-successor-bundle-root", "/bundle",
        "--artifact-store-dir", "/artifacts",
        "--owner", "worker-b-public",
        "--expected-role", "ingestion_control_app",
        "--embedding-artifact-root", "/models/e5",
        "--embedding-inventory-sha256", SHA,
        "--collection", "rag_nexus_dgemc_terminale_option",
        "--once",
    ]


def test_public_worker_refuses_missing_C_before_any_database_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor.ingestion_worker import public_text_publication_resume_cli as public_cli

    monkeypatch.setenv("NEXUS_EXPECTED_READINESS_PROTOCOL", STAGING_READINESS_PROTOCOL)
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_SHA256", SHA)
    monkeypatch.setenv("NEXUS_PUBLIC_SCOPE_AUTHORITY_SHA256", SHA)
    monkeypatch.setattr(
        public_cli, "enforce_staging_readiness_gate",
        lambda: SimpleNamespace(
            environment="rehearsal",
            manifest=SimpleNamespace(
                public_successor_phase="PUBLICATION",
                public_successor_content_anchor_digest=SHA,
                public_successor_phase_authority_digest=SHA,
                allowed_release_id="student-public-successor-test",
                allowed_release_manifest_sha256=SHA,
            ),
        ),
    )
    monkeypatch.setattr(
        public_cli, "verify_public_successor_activation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("C unavailable")),
    )
    monkeypatch.setattr(public_cli, "require_running_image_matches_manifest", lambda *_args: "sha256:image")
    opened: list[object] = []
    monkeypatch.setattr(cli.psycopg, "connect", lambda *_args, **_kwargs: opened.append(1))

    assert cli.main(_public_args()) == 1
    assert opened == []


def test_public_worker_refuses_staging_image_mismatch_before_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor.ingestion_worker import public_text_publication_resume_cli as public_cli

    monkeypatch.setenv("NEXUS_EXPECTED_READINESS_PROTOCOL", STAGING_READINESS_PROTOCOL)
    monkeypatch.setattr(public_cli, "enforce_staging_readiness_gate", lambda: SimpleNamespace(
        environment="rehearsal",
        manifest=SimpleNamespace(public_successor_phase="PUBLICATION"),
    ))
    monkeypatch.setattr(
        public_cli, "require_running_image_matches_manifest",
        lambda *_args: (_ for _ in ()).throw(ValueError("running image differs")),
        raising=False,
    )
    opened: list[object] = []
    monkeypatch.setattr(cli.psycopg, "connect", lambda *_args, **_kwargs: opened.append(1))

    with pytest.raises(ValueError, match="running image differs"):
        public_cli._signed_publication(Path("/bundle"))
    assert cli.main(_public_args()) == 1
    assert opened == []


def test_public_loop_rechecks_authority_before_lease_reap() -> None:
    class Connection:
        def commit(self) -> None:
            raise AssertionError("no transaction may start after C expired")

    with pytest.raises(RuntimeError, match="expired C"):
        cli._run_worker_loop(
            Connection(),
            deps=SimpleNamespace(claim_release_id="public", claim_release_manifest_sha256=SHA),
            args=SimpleNamespace(min_job_interval_s=0.0),
            max_iterations=1,
            pre_iteration=lambda: (_ for _ in ()).throw(RuntimeError("expired C")),
        )


def test_production_public_readiness_derives_release_id_from_pinned_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path

    from ingestor.ingestion_worker import public_text_publication_resume_cli as public_cli

    monkeypatch.delenv("NEXUS_EXPECTED_READINESS_PROTOCOL", raising=False)
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_SHA256", SHA)
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_PATH", "/bundle/release/release-registry.json")
    monkeypatch.setenv("NEXUS_ACTUAL_WORKER_IMAGE", WORKER_IMAGE)
    monkeypatch.setattr(
        public_cli, "enforce_readiness_gate",
        lambda: SimpleNamespace(
            environment="production",
            manifest=SimpleNamespace(
                sealed_manifest_digest=SHA,
                public_successor_content_manifest_digest=SHA,
                public_successor_content_anchor_digest=SHA,
                public_successor_authority_envelope_digest=SHA,
                application_image_digests={"multilevel-worker-b-production": WORKER_IMAGE},
            ),
        ),
    )
    monkeypatch.setattr(
        public_cli,
        "load_selected_release_registry",
        lambda *_args: SimpleNamespace(
            manifests=[
                SimpleNamespace(
                    expected_sha256=SHA,
                    expectation=SimpleNamespace(release_id="student-public-successor-test"),
                )
            ]
        ),
    )

    signed = public_cli._signed_publication(Path("/bundle"))

    assert signed.environment == "production"
    assert signed.release_id == "student-public-successor-test"


def test_production_public_readiness_rejects_ambiguous_release_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path

    from ingestor.ingestion_worker import public_text_publication_resume_cli as public_cli

    monkeypatch.delenv("NEXUS_EXPECTED_READINESS_PROTOCOL", raising=False)
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_PATH", "/bundle/release/release-registry.json")
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_SHA256", SHA)
    monkeypatch.setenv("RAG_RELEASE_MANIFEST_PATH", "/other/manifest.json")
    monkeypatch.setenv("RAG_RELEASE_MANIFEST_SHA256", SHA)
    monkeypatch.setenv("NEXUS_ACTUAL_WORKER_IMAGE", WORKER_IMAGE)
    monkeypatch.setattr(public_cli, "enforce_readiness_gate", lambda: SimpleNamespace(
        environment="production",
        manifest=SimpleNamespace(
            sealed_manifest_digest=SHA,
            public_successor_content_manifest_digest=SHA,
            public_successor_content_anchor_digest=SHA,
            public_successor_authority_envelope_digest=SHA,
            application_image_digests={"multilevel-worker-b-production": WORKER_IMAGE},
        ),
    ))
    with pytest.raises(ValueError, match="ambiguous"):
        public_cli._signed_publication(Path("/bundle"))


def test_production_public_worker_requires_signed_running_image_before_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor.ingestion_worker import public_text_publication_resume_cli as public_cli

    monkeypatch.delenv("NEXUS_EXPECTED_READINESS_PROTOCOL", raising=False)
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_PATH", "/bundle/release/release-registry.json")
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_SHA256", SHA)
    monkeypatch.setenv("NEXUS_ACTUAL_WORKER_IMAGE", "ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:" + "b" * 64)
    manifest = SimpleNamespace(
        sealed_manifest_digest=SHA,
        public_successor_content_manifest_digest=SHA,
        public_successor_content_anchor_digest=SHA,
        public_successor_authority_envelope_digest=SHA,
        application_image_digests={
            "multilevel-worker-b-production": "ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:" + "a" * 64,
        },
    )
    monkeypatch.setattr(public_cli, "enforce_readiness_gate", lambda: SimpleNamespace(
        environment="production", manifest=manifest,
    ))
    with pytest.raises(RuntimeError, match="running image"):
        public_cli._signed_publication(Path("/bundle"))

    manifest.application_image_digests = {"ingestor": "ghcr.io/cyranoaladin/rag-ingestor@sha256:" + "a" * 64}
    with pytest.raises(ValueError, match="multilevel-worker-b-production"):
        public_cli._signed_publication(Path("/bundle"))


def test_lot42_live_preflight_rejects_missing_attestation_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import UUID

    from ingestor.ingestion_worker import public_text_publication_resume_cli as public_cli

    resource = UUID(int=1)
    fake_facts = SimpleNamespace(
        release_manifest_sha256=SHA,
        candidate_inventory_sha256=SHA,
        artifact_transfer_manifest_sha256=SHA,
        subjects=1,
        placements=1,
        unique_artifacts=1,
        unique_chunks=1,
        collections=("public_collection",),
        par_ressource={resource: (UUID(int=2), "b" * 64, "public_collection", "scope")},
    )
    monkeypatch.setattr(public_cli, "measure_release_batch_facts", lambda *_a, **_k: fake_facts)
    monkeypatch.setattr(public_cli, "require_facts_match_catalog", lambda *_a: None)

    class Connection:
        def cursor(self):
            class Cursor:
                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return None

                def execute(self, *_args):
                    return None

                def fetchall(self):
                    return []

            return Cursor()

        def commit(self):
            raise AssertionError("preflight failure must not commit")

    with pytest.raises(ValueError, match="coverage incomplete"):
        public_cli.require_public_lot42_db(
            Connection(),
            activation=SimpleNamespace(
                release_id="public-release",
                content_manifest_sha256=SHA,
                counts={"subjects": 1, "placements": 1, "unique_artifacts": 1, "unique_chunks": 1},
            ),
            authorities=SimpleNamespace(
                sealed_release_catalog=object(),
                placement_resolver=SimpleNamespace(
                    _candidate_inventory_sha256=SHA,
                    collections=frozenset({"public_collection"}),
                ),
            ),
            transfer_sha256=SHA,
        )


def test_lot42_live_preflight_ends_read_only_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import UUID

    from ingestor.ingestion_worker import public_text_publication_resume_cli as public_cli

    resource = UUID(int=1)
    facts = SimpleNamespace(
        release_manifest_sha256=SHA,
        candidate_inventory_sha256=SHA,
        artifact_transfer_manifest_sha256=SHA,
        subjects=1,
        placements=1,
        unique_artifacts=1,
        unique_chunks=1,
        collections=("public_collection",),
        par_ressource={resource: (UUID(int=2), "b" * 64, "public_collection", "scope")},
    )
    monkeypatch.setattr(public_cli, "measure_release_batch_facts", lambda *_a, **_k: facts)
    monkeypatch.setattr(public_cli, "require_facts_match_catalog", lambda *_a: None)

    class Connection:
        rolled_back = False

        def cursor(self):
            class Cursor:
                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return None

                def execute(self, *_args):
                    return None

                def fetchall(self):
                    return [(resource, "b" * 64, "public_collection", UUID(int=3))]

            return Cursor()

        def commit(self):
            raise AssertionError("read-only preflight must not commit")

        def rollback(self):
            self.rolled_back = True

    conn = Connection()
    public_cli.require_public_lot42_db(
        conn,
        activation=SimpleNamespace(
            release_id="public-release",
            content_manifest_sha256=SHA,
            counts={"subjects": 1, "placements": 1, "unique_artifacts": 1, "unique_chunks": 1},
        ),
        authorities=SimpleNamespace(
            sealed_release_catalog=object(),
            placement_resolver=SimpleNamespace(
                _candidate_inventory_sha256=SHA,
                collections=frozenset({"public_collection"}),
            ),
        ),
        transfer_sha256=SHA,
    )
    assert conn.rolled_back


@pytest.mark.parametrize(
    "extra",
    [
        ["--max-iterations", "-1"],
        ["--max-idle-polls", "0"],
        ["--poll-interval-s", "nan"],
        ["--min-job-interval-s", "-0.1"],
    ],
)
def test_public_worker_rejects_invalid_loop_budgets(extra: list[str]) -> None:
    from ingestor.ingestion_worker import public_text_publication_resume_cli as public_cli

    with pytest.raises(SystemExit):
        public_cli._build_arg_parser().parse_args([*_public_args(), *extra])
