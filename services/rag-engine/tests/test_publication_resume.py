"""Worker B lie le job, le placement scellé et la publication gouvernée."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from nexus_contracts.document import Rights

import ingestor.ingestion_worker.publication_resume as resume_module
from ingestor.ingestion_control.jobs import JobClaim
from ingestor.ingestion_worker.publication_resume import (
    PublicationResumeDeps,
    PublicationResumeError,
    resume_publication,
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
    def publish(_control: object, _product: object, governed: object, *_a: object) -> object:
        published["governed"] = governed
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
        embed_chunks=lambda _chunks: [[0.0] * 1024],
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
        embed_chunks=lambda _chunks: (),
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
        embed_chunks=lambda _chunks: (),
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
        embed_chunks=lambda _chunks: [[0.0] * 1024],
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
