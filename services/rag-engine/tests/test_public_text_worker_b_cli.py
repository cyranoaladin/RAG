"""Le Worker B public ne réclame aucun job sous une autorité C absente."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from nexus_contracts.staging_readiness import STAGING_READINESS_PROTOCOL
from nexus_release_chain.public_successor_activation import PublicSuccessorActivationVerdict

from ingestor.ingestion_worker import multilevel_publication_resume_cli as cli

SHA = "a" * 64
WORKER_IMAGE = "ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:" + SHA


@pytest.mark.parametrize("environment,proof_key", [
    ("rehearsal", "signed_staging_readiness"),
    ("production", "signed_runtime_readiness"),
])
def test_public_worker_passes_verified_signed_c_proof_to_portable_gate(
    monkeypatch: pytest.MonkeyPatch, environment: str, proof_key: str,
) -> None:
    from ingestor.ingestion_worker import public_text_publication_resume_cli as public_cli

    signed = public_cli._SignedPublication(
        environment=environment, release_id="public-test", manifest_sha256=SHA,
        anchor_sha256=SHA, envelope_sha256=SHA, registry_sha256=SHA,
        target_pin_sha256=SHA,
    )
    verdict = PublicSuccessorActivationVerdict(
        release_id="public-test", content_anchor_sha256=SHA,
        content_manifest_sha256=SHA, authority_envelope_sha256=SHA,
        artifact_registry_sha256=SHA, release_registry_sha256=SHA,
        scope_authority_sha256=SHA, subject_sha256_by_collection={},
        scope_sha256_by_id={}, counts={},
        expires_at_utc=datetime.now(UTC) + timedelta(hours=1),
    )
    proof = (b"signed-readiness", b"trusted-anchor")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(public_cli, "_signed_publication", lambda _root: signed)
    monkeypatch.setattr(public_cli, "_read_signed_proof", lambda _signed: proof)
    monkeypatch.setattr(public_cli, "_required_sha_env", lambda _name: SHA)
    monkeypatch.setattr(public_cli, "verify_public_successor_activation",
                        lambda _root, **kwargs: calls.append(kwargs) or verdict)
    monkeypatch.setattr(public_cli, "_transfer_authority", lambda *_args: (Path("/transfer"), SHA))
    monkeypatch.setattr(public_cli, "load_public_text_runtime_authorities",
                        lambda **_kwargs: object())

    observed_signed, observed_verdict, _ = public_cli._verified_runtime(Path("/bundle"))
    assert observed_signed == signed and observed_verdict == verdict
    assert len(calls) == 1
    assert calls[0][proof_key] == proof
    other_key = (
        "signed_runtime_readiness" if proof_key == "signed_staging_readiness"
        else "signed_staging_readiness"
    )
    assert calls[0][other_key] is None


def test_public_worker_refuses_staging_readiness_changed_after_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor.ingestion_worker import public_text_publication_resume_cli as public_cli

    raw = b"signed-staging-readiness"
    manifest = tmp_path / "readiness.json"
    manifest.write_bytes(raw)
    manifest.chmod(0o600)
    anchor = tmp_path / "staging-anchor.json"
    anchor.write_bytes(b"trusted-staging-anchor")
    monkeypatch.setenv("NEXUS_READINESS_MANIFEST_PATH", str(manifest))
    monkeypatch.setenv("NEXUS_READINESS_MANIFEST_SHA256", hashlib.sha256(b"before").hexdigest())
    monkeypatch.setenv("NEXUS_STAGING_READINESS_TRUST_ANCHOR", str(anchor))
    signed = public_cli._SignedPublication(
        "rehearsal", "public-test", SHA, SHA, SHA, SHA, SHA,
    )
    with pytest.raises(ValueError, match="digest changed after gate"):
        public_cli._read_signed_proof(signed)


def test_public_worker_refuses_missing_production_signed_c_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor.ingestion_worker import public_text_publication_resume_cli as public_cli

    monkeypatch.delenv("NEXUS_READINESS_MANIFEST_PATH", raising=False)
    signed = public_cli._SignedPublication(
        "production", "public-test", SHA, SHA, SHA, SHA, SHA,
    )
    with pytest.raises(ValueError, match="path absent"):
        public_cli._read_signed_proof(signed)


def test_public_worker_uses_governed_production_anchor_and_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor.ingestion_worker import public_text_publication_resume_cli as public_cli

    manifest = tmp_path / "readiness.json"
    manifest.write_bytes(b"signed-production-readiness")
    manifest.chmod(0o600)
    monkeypatch.setenv("NEXUS_READINESS_MANIFEST_PATH", str(manifest))
    calls: list[str] = []

    def governed_anchor(environment: str) -> bytes:
        calls.append(environment)
        return b"governed-production-anchor"

    monkeypatch.setattr(public_cli, "_resolve_anchor_bytes", governed_anchor)
    signed = public_cli._SignedPublication(
        "production", "public-test", SHA, SHA, SHA, SHA, SHA,
    )
    assert public_cli._read_signed_proof(signed) == (
        b"signed-production-readiness", b"governed-production-anchor",
    )
    assert calls == ["production"]


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
                public_successor_target_pin_digest=SHA,
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
            manifest=SimpleNamespace(
                public_successor_phase="PUBLICATION",
                public_successor_target_pin_digest=SHA,
            ),
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
                public_successor_target_pin_digest=SHA,
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
            public_successor_target_pin_digest=SHA,
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
        public_successor_target_pin_digest=SHA,
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
