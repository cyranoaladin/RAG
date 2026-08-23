"""Worker B lie le job, le placement scellé et la publication gouvernée."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from nexus_contracts.document import Rights

import ingestor.ingestion_worker.publication_resume as resume_module
from ingestor.embedding_provider import CallableEmbeddingProvider
from ingestor.ingestion_control.jobs import JobClaim, JobLeaseConflictError
from ingestor.ingestion_worker.publication_resume import (
    PublicationResumeDeps,
    PublicationResumeError,
    PublicationResumeOutcome,
    resume_publication,
    run_publication_resume_iteration,
)


class _ControlConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.status = "IDLE"
        self.events: list[str] = []

    def mark_read(self, event: str) -> None:
        self.status = "INTRANS"
        self.events.append(event)

    def commit(self) -> None:
        self.commits += 1
        self.status = "IDLE"
        self.events.append("control_commit")

    def rollback(self) -> None:
        self.status = "IDLE"
        self.events.append("control_rollback")


class _RecoveryCursor:
    def __init__(self, rows: list[tuple[str, str, dict[str, object]]]) -> None:
        self.rows = rows
        self.params: tuple[object, ...] | None = None

    def __enter__(self) -> _RecoveryCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _query: str, params: tuple[object, ...]) -> None:
        self.params = params

    def fetchall(self) -> list[tuple[str, str, dict[str, object]]]:
        return self.rows


class _RecoveryControlConnection(_ControlConnection):
    def __init__(self, rows: list[tuple[str, str, dict[str, object]]]) -> None:
        super().__init__()
        self.recovery_cursor = _RecoveryCursor(rows)

    def cursor(self) -> _RecoveryCursor:
        return self.recovery_cursor


class _ProductConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.status = "IDLE"

    def __enter__(self) -> _ProductConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


class _PIIRegistry:
    def verify_content_clearance(self, _sha256: str) -> None:
        return None


class _RightsRegistry:
    def __init__(self) -> None:
        self.source_paths: list[str] = []

    def resolve_rights(self, *, content_sha256: str, source_path: str) -> object:
        assert len(content_sha256) == 64
        self.source_paths.append(source_path)
        return SimpleNamespace(rights=Rights.officiel_public)


def _claim(
    *, resource_id: UUID, run_id: UUID, attestation_id: UUID, state_version: int
) -> JobClaim:
    return JobClaim(
        job_id=uuid4(),
        run_id=run_id,
        resource_id=resource_id,
        job_type="publication_resume",
        payload={
            "resource_id": str(resource_id),
            "run_id": str(run_id),
            "expected_state_version": state_version,
            "publication_attestation_id": str(attestation_id),
        },
        lease_token=uuid4(),
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        attempt_count=1,
    )


def test_worker_b_dependencies_reject_a_bare_embedding_callable() -> None:
    with pytest.raises(PublicationResumeError, match="explicit embedding provider"):
        PublicationResumeDeps(
            owner="publication-resume-test",
            product_dsn="postgresql://product",
            artifact_reader=lambda **_kwargs: b"unused",
            extract_text=lambda _content: "unused",
            embedding_provider=lambda _passages: (),  # type: ignore[arg-type]
        )


def test_resume_uses_governed_source_path_and_prebound_attestation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource_id, run_id, attestation_id = uuid4(), uuid4(), uuid4()
    raw_bytes = b"official French pilot bytes"
    content_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    sealed_source_path = "01_EDUSCOL_OFFICIEL/COLLEGE/3E/FRANCAIS/document.pdf"
    rights_registry = _RightsRegistry()
    placement = SimpleNamespace(
        source_path=sealed_source_path,
        source_uri="https://eduscol.education.gouv.fr/5733/francais-cycle-4",
        current_profile_fingerprint="a" * 64,
        current_manifest_digest="b" * 64,
    )
    artifact = SimpleNamespace(
        artifact_id=uuid4(),
        sha256=content_sha256,
        final_url="https://eduscol.education.fr/document.pdf",
        rights_status=Rights.officiel_public,
        extracted_text_ref="artifact://fr",
        mime_detected="application/pdf",
    )
    durable_facts = SimpleNamespace(
        rights_status=Rights.officiel_public,
        canonical_url=placement.source_uri,
        collection="rag_nexus_francais_troisieme_tc",
        type_doc="ressource_officielle",
    )
    promotion_kwargs: dict[str, object] = {}
    published: dict[str, object] = {}
    resolved: dict[str, object] = {}

    class Resolver:
        def resolve(self, **kwargs: object) -> object:
            resolved.update(kwargs)
            return SimpleNamespace(content_sha256=content_sha256)

    monkeypatch.setattr(
        resume_module, "get_resource_state", lambda *_a, **_k: ("NEEDS_REVIEW", 7)
    )
    monkeypatch.setattr(resume_module, "find_latest_artifact", lambda *_a, **_k: artifact)
    monkeypatch.setattr(
        resume_module, "collect_publication_facts", lambda *_a, **_k: durable_facts
    )
    monkeypatch.setattr(
        resume_module,
        "_load_run_placement_context",
        lambda *_a, **_k: ("rag_nexus_francais_troisieme_tc", "wave0-v1", "2026-2027"),
        raising=False,
    )
    monkeypatch.setattr(
        resume_module,
        "to_eligible_placement",
        lambda verified, *, resource_id, current_profile_manifest_digest: placement,
        raising=False,
    )
    monkeypatch.setattr(
        resume_module,
        "load_artifact_attribution",
        lambda *_a, **_k: (
            SimpleNamespace(
                source_label="Éduscol officiel",
                official=True,
                source_kind="eduscol",
                type_doc="ressource_officielle",
            ),
            "c" * 64,
        ),
    )

    def promote(_conn: object, **kwargs: object) -> object:
        promotion_kwargs.update(kwargs)
        return SimpleNamespace(attestation=SimpleNamespace(attestation_id=attestation_id))

    monkeypatch.setattr(resume_module, "promote_reviewed_publication", promote)
    provider = CallableEmbeddingProvider(
        encoder=lambda _chunks: [[1.0] + [0.0] * 1023]
    )

    def publish(
        _control: object,
        _product: object,
        governed: object,
        _placements: object,
        _extract_text: object,
        embedding_provider: object,
    ) -> object:
        published["governed"] = governed
        published["embedding_provider"] = embedding_provider
        return SimpleNamespace(
            artifact_id=content_sha256, chunk_rows=1, placement_rows=1
        )

    monkeypatch.setattr(resume_module, "publish_governed_artifact", publish)
    product_conn = _ProductConnection()
    monkeypatch.setattr(resume_module.psycopg, "connect", lambda *_a, **_k: product_conn)

    deps = PublicationResumeDeps(
        owner="publication-resume-test",
        product_dsn="postgresql://product",
        artifact_reader=lambda **_k: raw_bytes,
        extract_text=lambda _content: "texte",
        embedding_provider=provider,
        pii_evidence_registry=_PIIRegistry(),
        rights_evidence_registry=rights_registry,
        manifest_digest="b" * 64,
        placement_resolver=Resolver(),
    )

    outcome = resume_publication(
        _ControlConnection(),
        claim=_claim(
            resource_id=resource_id,
            run_id=run_id,
            attestation_id=attestation_id,
            state_version=7,
        ),
        deps=deps,
        build_placements=None,
    )

    assert outcome.status == "succeeded"
    assert rights_registry.source_paths == [sealed_source_path]
    assert promotion_kwargs["expected_attestation_id"] == attestation_id
    assert published["governed"].source_uri == placement.source_uri
    assert published["governed"].mime_detected == "application/pdf"
    assert published["embedding_provider"] is provider
    assert resolved == {
        "content_sha256": content_sha256,
        "collection": "rag_nexus_francais_troisieme_tc",
        "profile_version": "wave0-v1",
        "school_year": "2026-2027",
        "claimed_source_url": placement.source_uri,
        "claimed_type_doc": "ressource_officielle",
    }


def test_resume_rejects_payload_source_path_that_disagrees_with_placement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource_id, run_id, attestation_id = uuid4(), uuid4(), uuid4()
    claim = _claim(
        resource_id=resource_id,
        run_id=run_id,
        attestation_id=attestation_id,
        state_version=7,
    )
    claim.payload["source_path"] = "01_EDUSCOL_OFFICIEL/UNTRUSTED/document.pdf"
    artifact = SimpleNamespace(artifact_id=uuid4(), sha256="f" * 64)
    placement = SimpleNamespace(
        source_path="01_EDUSCOL_OFFICIEL/COLLEGE/3E/FRANCAIS/document.pdf",
        source_uri="https://eduscol.education.gouv.fr/francais",
    )

    class Resolver:
        def resolve(self, **_kwargs: object) -> object:
            return SimpleNamespace(content_sha256=artifact.sha256)

    monkeypatch.setattr(
        resume_module, "get_resource_state", lambda *_a, **_k: ("NEEDS_REVIEW", 7)
    )
    monkeypatch.setattr(resume_module, "find_latest_artifact", lambda *_a, **_k: artifact)
    monkeypatch.setattr(
        resume_module,
        "collect_publication_facts",
        lambda *_a, **_k: SimpleNamespace(
            collection="rag_nexus_francais_troisieme_tc",
            canonical_url="https://eduscol.education.gouv.fr/francais",
            rights_status=Rights.officiel_public,
            type_doc="ressource_officielle",
        ),
    )
    monkeypatch.setattr(
        resume_module,
        "_load_run_placement_context",
        lambda *_a, **_k: ("rag_nexus_francais_troisieme_tc", "wave0-v1", "2026-2027"),
        raising=False,
    )
    monkeypatch.setattr(
        resume_module,
        "to_eligible_placement",
        lambda verified, *, resource_id, current_profile_manifest_digest: placement,
        raising=False,
    )

    deps = PublicationResumeDeps(
        owner="publication-resume-test",
        product_dsn="postgresql://product",
        artifact_reader=lambda **_k: b"unused",
        extract_text=lambda _content: "unused",
        embedding_provider=CallableEmbeddingProvider(encoder=lambda _chunks: ()),
        manifest_digest="b" * 64,
        placement_resolver=Resolver(),
    )

    with pytest.raises(PublicationResumeError, match="source_path disagrees"):
        resume_publication(
            _ControlConnection(),
            claim=claim,
            deps=deps,
            build_placements=None,
        )


def test_resume_rejects_payload_run_that_disagrees_with_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource_id, run_id, attestation_id = uuid4(), uuid4(), uuid4()
    claim = _claim(
        resource_id=resource_id,
        run_id=run_id,
        attestation_id=attestation_id,
        state_version=7,
    )
    claim.payload["run_id"] = str(uuid4())
    monkeypatch.setattr(
        resume_module,
        "get_resource_state",
        lambda *_a, **_k: pytest.fail("state lookup must not run"),
    )

    deps = PublicationResumeDeps(
        owner="publication-resume-test",
        product_dsn="postgresql://product",
        artifact_reader=lambda **_k: b"unused",
        extract_text=lambda _content: "unused",
        embedding_provider=CallableEmbeddingProvider(encoder=lambda _chunks: ()),
    )

    with pytest.raises(PublicationResumeError, match="run_id disagrees"):
        resume_publication(
            _ControlConnection(),
            claim=claim,
            deps=deps,
        )


def test_resume_enters_promotion_and_publisher_with_idle_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource_id, run_id, attestation_id = uuid4(), uuid4(), uuid4()
    raw_bytes = b"transaction boundary bytes"
    content_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    control_conn = _ControlConnection()
    product_conn = _ProductConnection()
    placement = SimpleNamespace(
        source_path="01_EDUSCOL_OFFICIEL/COLLEGE/3E/FRANCAIS/document.pdf",
        source_uri="https://eduscol.education.gouv.fr/5733/francais-cycle-4",
        current_profile_fingerprint="a" * 64,
        current_manifest_digest="b" * 64,
    )
    artifact = SimpleNamespace(
        artifact_id=uuid4(),
        sha256=content_sha256,
        rights_status=Rights.officiel_public,
        extracted_text_ref="artifact://fr",
        mime_detected="application/pdf",
    )
    durable_facts = SimpleNamespace(
        rights_status=Rights.officiel_public,
        canonical_url=placement.source_uri,
        collection="rag_nexus_francais_troisieme_tc",
        type_doc="ressource_officielle",
    )

    class Resolver:
        def resolve(self, **_kwargs: object) -> object:
            return SimpleNamespace(content_sha256=content_sha256)

    def read_state(*_args: object, **_kwargs: object) -> tuple[str, int]:
        control_conn.mark_read("state")
        return "NEEDS_REVIEW", 7

    def read_artifact(*_args: object, **_kwargs: object) -> object:
        control_conn.mark_read("artifact")
        return artifact

    def read_attribution(*_args: object, **_kwargs: object) -> tuple[object, str]:
        control_conn.mark_read("attribution")
        return (
            SimpleNamespace(
                source_label="Éduscol officiel",
                official=True,
                source_kind="eduscol",
                type_doc="ressource_officielle",
            ),
            "c" * 64,
        )

    def promote(_conn: object, **_kwargs: object) -> object:
        assert control_conn.status == "IDLE"
        control_conn.events.append("promote")
        return SimpleNamespace(attestation=SimpleNamespace(attestation_id=attestation_id))

    def publish(
        actual_control: object, actual_product: object, *_args: object, **_kwargs: object
    ) -> object:
        assert actual_control is control_conn
        assert actual_product is product_conn
        assert control_conn.status == "IDLE"
        assert product_conn.status == "IDLE"
        control_conn.events.append("publish")
        return SimpleNamespace(
            artifact_id=content_sha256, chunk_rows=1, placement_rows=1
        )

    monkeypatch.setattr(resume_module, "get_resource_state", read_state)
    monkeypatch.setattr(resume_module, "find_latest_artifact", read_artifact)
    monkeypatch.setattr(
        resume_module, "collect_publication_facts", lambda *_a, **_k: durable_facts
    )
    monkeypatch.setattr(
        resume_module,
        "_load_run_placement_context",
        lambda *_a, **_k: ("rag_nexus_francais_troisieme_tc", "wave0-v1", "2026-2027"),
        raising=False,
    )
    monkeypatch.setattr(
        resume_module,
        "to_eligible_placement",
        lambda verified, *, resource_id, current_profile_manifest_digest: placement,
        raising=False,
    )
    monkeypatch.setattr(resume_module, "load_artifact_attribution", read_attribution)
    monkeypatch.setattr(resume_module, "promote_reviewed_publication", promote)
    monkeypatch.setattr(resume_module, "publish_governed_artifact", publish)
    monkeypatch.setattr(resume_module.psycopg, "connect", lambda *_a, **_k: product_conn)

    deps = PublicationResumeDeps(
        owner="publication-resume-test",
        product_dsn="postgresql://product",
        artifact_reader=lambda **_k: raw_bytes,
        extract_text=lambda _content: "texte",
        embedding_provider=CallableEmbeddingProvider(
            encoder=lambda _chunks: [[1.0] + [0.0] * 1023]
        ),
        pii_evidence_registry=_PIIRegistry(),
        rights_evidence_registry=_RightsRegistry(),
        manifest_digest="b" * 64,
        placement_resolver=Resolver(),
    )

    outcome = resume_publication(
        control_conn,
        claim=_claim(
            resource_id=resource_id,
            run_id=run_id,
            attestation_id=attestation_id,
            state_version=7,
        ),
        deps=deps,
        build_placements=None,
    )

    assert outcome.status == "succeeded"
    assert control_conn.events == [
        "state",
        "artifact",
        "attribution",
        "control_commit",
        "promote",
        "publish",
    ]
    assert product_conn.commits == 0


def _install_recovery_context(
    monkeypatch: pytest.MonkeyPatch,
    *,
    resource_id: UUID,
    run_id: UUID,
    attestation_id: UUID,
    raw_bytes: bytes,
    publish_embedded: bool,
) -> tuple[PublicationResumeDeps, dict[str, object]]:
    content_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    placement = SimpleNamespace(
        source_path="01_EDUSCOL_OFFICIEL/COLLEGE/3E/FRANCAIS/document.pdf",
        source_uri="https://eduscol.education.gouv.fr/5733/francais-cycle-4",
        current_profile_fingerprint="a" * 64,
        current_manifest_digest="b" * 64,
    )
    artifact = SimpleNamespace(
        artifact_id=uuid4(),
        sha256=content_sha256,
        extracted_text_ref="artifact://fr",
        mime_detected="application/pdf",
    )
    durable_facts = SimpleNamespace(
        rights_status=Rights.officiel_public,
        canonical_url=placement.source_uri,
        collection="rag_nexus_francais_troisieme_tc",
        type_doc="ressource_officielle",
    )
    calls: dict[str, object] = {
        "promote": 0,
        "verify": [],
        "publish": 0,
        "encoded": 0,
    }

    class Resolver:
        def resolve(self, **_kwargs: object) -> object:
            return SimpleNamespace(content_sha256=content_sha256)

    monkeypatch.setattr(
        resume_module,
        "get_resource_state",
        lambda *_a, **_k: ("RETRIEVAL_ELIGIBLE", 9),
    )
    monkeypatch.setattr(resume_module, "find_latest_artifact", lambda *_a, **_k: artifact)
    monkeypatch.setattr(
        resume_module, "collect_publication_facts", lambda *_a, **_k: durable_facts
    )
    monkeypatch.setattr(
        resume_module,
        "_load_run_placement_context",
        lambda *_a, **_k: ("rag_nexus_francais_troisieme_tc", "wave0-v1", "2026-2027"),
    )
    monkeypatch.setattr(
        resume_module,
        "to_eligible_placement",
        lambda verified, *, resource_id, current_profile_manifest_digest: placement,
    )
    monkeypatch.setattr(
        resume_module,
        "load_artifact_attribution",
        lambda *_a, **_k: (
            SimpleNamespace(
                source_label="Éduscol officiel",
                official=True,
                source_kind="eduscol",
                type_doc="ressource_officielle",
            ),
            "c" * 64,
        ),
    )

    def reject_duplicate_promotion(*_args: object, **_kwargs: object) -> object:
        calls["promote"] = int(calls["promote"]) + 1
        pytest.fail("a recovered RETRIEVAL_ELIGIBLE resource must not be promoted again")

    def verify(*_args: object, **kwargs: object) -> object:
        cast_calls = calls["verify"]
        assert isinstance(cast_calls, list)
        cast_calls.append(kwargs)
        return SimpleNamespace(attestation_id=attestation_id)

    def publish(*_args: object, **_kwargs: object) -> object:
        calls["publish"] = int(calls["publish"]) + 1
        return SimpleNamespace(
            artifact_id=content_sha256,
            chunk_rows=17,
            placement_rows=1,
            embedded=publish_embedded,
        )

    monkeypatch.setattr(
        resume_module, "promote_reviewed_publication", reject_duplicate_promotion
    )
    monkeypatch.setattr(resume_module, "verify_publication_attestation", verify)
    monkeypatch.setattr(resume_module, "publish_governed_artifact", publish)
    monkeypatch.setattr(
        resume_module.psycopg, "connect", lambda *_a, **_k: _ProductConnection()
    )

    def encode(_passages: object) -> list[list[float]]:
        calls["encoded"] = int(calls["encoded"]) + 1
        return [[1.0] + [0.0] * 1023]

    return (
        PublicationResumeDeps(
            owner="publication-resume-recovery-test",
            product_dsn="postgresql://product",
            artifact_reader=lambda **_k: raw_bytes,
            extract_text=lambda _content: "texte",
            embedding_provider=CallableEmbeddingProvider(encoder=encode),
            pii_evidence_registry=_PIIRegistry(),
            rights_evidence_registry=_RightsRegistry(),
            manifest_digest="b" * 64,
            placement_resolver=Resolver(),
        ),
        calls,
    )


def _completed_promotion_events(
    attestation_id: UUID,
) -> list[tuple[str, str, dict[str, object]]]:
    return [
        (
            "NEEDS_REVIEW",
            "REVIEWED",
            {"publication_attestation_id": str(attestation_id)},
        ),
        ("REVIEWED", "RETRIEVAL_ELIGIBLE", {}),
    ]


def test_resume_after_crash_at_eligibility_reuses_exact_promotion_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource_id, run_id, attestation_id = uuid4(), uuid4(), uuid4()
    deps, calls = _install_recovery_context(
        monkeypatch,
        resource_id=resource_id,
        run_id=run_id,
        attestation_id=attestation_id,
        raw_bytes=b"crash after eligibility",
        publish_embedded=True,
    )
    control_conn = _RecoveryControlConnection(
        _completed_promotion_events(attestation_id)
    )
    claim = _claim(
        resource_id=resource_id,
        run_id=run_id,
        attestation_id=attestation_id,
        state_version=7,
    )

    outcome = resume_publication(control_conn, claim=claim, deps=deps)

    assert outcome.status == "succeeded"
    assert outcome.embedded is True
    assert calls["promote"] == 0
    assert calls["publish"] == 1
    assert control_conn.recovery_cursor.params == (
        resource_id,
        run_id,
        claim.job_id,
    )
    verifies = calls["verify"]
    assert isinstance(verifies, list) and len(verifies) == 1
    assert verifies[0]["expected_attestation_id"] == attestation_id


def test_runtime_revocation_immediately_before_publication_keeps_pgvector_at_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource_id, run_id, attestation_id = uuid4(), uuid4(), uuid4()
    deps, calls = _install_recovery_context(
        monkeypatch,
        resource_id=resource_id,
        run_id=run_id,
        attestation_id=attestation_id,
        raw_bytes=b"must never reach pgvector",
        publish_embedded=True,
    )

    class RevokedContext:
        mapping = None

        def reverify(self):
            raise RuntimeError("authorization revoked immediately before publication")

    deps.authorization_context = RevokedContext()
    control_conn = _RecoveryControlConnection(
        _completed_promotion_events(attestation_id)
    )

    with pytest.raises(PublicationResumeError, match="revoked"):
        resume_publication(
            control_conn,
            claim=_claim(
                resource_id=resource_id,
                run_id=run_id,
                attestation_id=attestation_id,
                state_version=7,
            ),
            deps=deps,
        )

    assert calls["publish"] == 0
    assert calls["encoded"] == 0


@pytest.mark.parametrize(
    "events",
    [
        [("NEEDS_REVIEW", "REVIEWED", {})],
        [
            ("NEEDS_REVIEW", "REVIEWED", {"publication_attestation_id": str(uuid4())}),
            ("REVIEWED", "RETRIEVAL_ELIGIBLE", {}),
        ],
        [
            ("NEEDS_REVIEW", "REVIEWED", {"publication_attestation_id": "MATCH"}),
            ("REVIEWED", "RETRIEVAL_ELIGIBLE", {}),
            ("REVIEWED", "RETRIEVAL_ELIGIBLE", {}),
        ],
    ],
)
def test_recovery_refuses_missing_wrong_or_duplicate_promotion_events(
    monkeypatch: pytest.MonkeyPatch,
    events: list[tuple[str, str, dict[str, object]]],
) -> None:
    resource_id, run_id, attestation_id = uuid4(), uuid4(), uuid4()
    normalized = [
        (
            from_state,
            to_state,
            {
                key: str(attestation_id) if value == "MATCH" else value
                for key, value in payload.items()
            },
        )
        for from_state, to_state, payload in events
    ]
    deps, calls = _install_recovery_context(
        monkeypatch,
        resource_id=resource_id,
        run_id=run_id,
        attestation_id=attestation_id,
        raw_bytes=b"invalid promotion history",
        publish_embedded=True,
    )

    with pytest.raises(PublicationResumeError, match="promotion evidence"):
        resume_publication(
            _RecoveryControlConnection(normalized),
            claim=_claim(
                resource_id=resource_id,
                run_id=run_id,
                attestation_id=attestation_id,
                state_version=7,
            ),
            deps=deps,
        )

    assert calls["publish"] == 0


def test_resume_after_product_commit_reports_no_new_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource_id, run_id, attestation_id = uuid4(), uuid4(), uuid4()
    deps, calls = _install_recovery_context(
        monkeypatch,
        resource_id=resource_id,
        run_id=run_id,
        attestation_id=attestation_id,
        raw_bytes=b"crash after product commit",
        publish_embedded=False,
    )

    outcome = resume_publication(
        _RecoveryControlConnection(_completed_promotion_events(attestation_id)),
        claim=_claim(
            resource_id=resource_id,
            run_id=run_id,
            attestation_id=attestation_id,
            state_version=7,
        ),
        deps=deps,
    )

    assert outcome.status == "succeeded"
    assert outcome.embedded is False
    assert calls["publish"] == 1
    assert calls["encoded"] == 0


def test_lease_expiry_then_reclaim_completes_the_same_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource_id, run_id, attestation_id = uuid4(), uuid4(), uuid4()
    first = _claim(
        resource_id=resource_id,
        run_id=run_id,
        attestation_id=attestation_id,
        state_version=7,
    )
    second = JobClaim(
        **{
            **first.__dict__,
            "lease_token": uuid4(),
            "attempt_count": first.attempt_count + 1,
        }
    )
    claims = [first, second]
    completed: list[UUID] = []
    resume_claims: list[JobClaim] = []

    monkeypatch.setattr(resume_module, "claim_job", lambda *_a, **_k: claims.pop(0))

    def resumed(_conn: object, *, claim: JobClaim, **_kwargs: object) -> object:
        resume_claims.append(claim)
        return PublicationResumeOutcome(
            worked=True,
            job_id=claim.job_id,
            status="succeeded",
            error=None,
            artifact_id="a" * 64,
            chunk_rows=17,
            placement_rows=1,
            embedded=False,
        )

    monkeypatch.setattr(resume_module, "resume_publication", resumed)

    def complete(_conn: object, *, lease_token: UUID, **_kwargs: object) -> None:
        if lease_token == first.lease_token:
            raise JobLeaseConflictError("first lease expired")
        completed.append(lease_token)

    monkeypatch.setattr(resume_module, "complete_job", complete)
    deps = PublicationResumeDeps(
        owner="publication-resume-lease-test",
        product_dsn="postgresql://product",
        artifact_reader=lambda **_k: b"unused",
        extract_text=lambda _content: "unused",
        embedding_provider=CallableEmbeddingProvider(encoder=lambda _chunks: ()),
    )
    conn = _ControlConnection()

    lost = run_publication_resume_iteration(conn, deps=deps)
    recovered = run_publication_resume_iteration(conn, deps=deps)

    assert lost.status == "lease_lost"
    assert recovered.status == "succeeded"
    assert [claim.lease_token for claim in resume_claims] == [
        first.lease_token,
        second.lease_token,
    ]
    assert completed == [second.lease_token]
