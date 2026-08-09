"""LOT42 lie la publication H2 au FETCHED autorisé et durable."""
from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from nexus_contracts.document import Rights
from nexus_contracts.ingestion import ResourceScope

import ingestor.ingestion_control.publication_attestation as attestation_module
from ingestor.ingestion_control.publication_attestation import (
    PublicationAttestationInvalidError,
    verify_publication_attestation,
)
from ingestor.ingestion_control.publication_evidence import (
    PublicationEvidenceMissingError,
    PublicationFacts,
    collect_publication_facts,
)
from ingestor.ingestion_control.scope_authority import VerifiedAuthorization

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
CONTENT_SHA = "1" * 64
AUTHORIZATION_ID = "h2-content-bound-v2"
AUTHORIZATION_DIGEST = "2" * 64


def _scope() -> ResourceScope:
    return ResourceScope(
        tenant="libre_terminale",
        collection="rag_nexus_philo_terminale_tc",
        niveau="terminale",
        voie="generale",
        matiere="philosophie",
        candidat="libre",
        audience=["libre", "tous"],
        visibility="internal",
        school_year="2026-2027",
        programme_version="BOEN_special_8_2019-07-25",
    )


def _authorization(**overrides: Any) -> VerifiedAuthorization:
    defaults: dict[str, Any] = {
        "authorization_id": AUTHORIZATION_ID,
        "scope": _scope(),
        "manifest_digest": "3" * 64,
        "profile_id": "rag_nexus_philo_terminale_tc",
        "profile_version": "h2c-v1",
        "profile_fingerprint": "4" * 64,
        "allowed_domains": ("eduscol.education.gouv.fr",),
        "rights_categories": (Rights.officiel_public.value,),
        "exclusions": (),
        "pii_absence_attested": True,
        "valid_from": NOW - timedelta(days=1),
        "valid_until": NOW + timedelta(days=1),
        "artifact_path": "governance/authorizations/h2-content-bound-v2.json",
        "artifact_blob_sha": "5" * 40,
        "authorization_digest": AUTHORIZATION_DIGEST,
        "evidence_repository": "cyranoaladin/RAG",
        "evidence_pull_request": 96,
        "evidence_base_sha": "6" * 40,
        "evidence_head_sha": "7" * 40,
        "evidence_review_id": 8,
        "evidence_reviewer": "abenrhouma",
        "evidence_challenge": "NEXUS-TRUSTED-REVIEW-V1:" + "8" * 64,
        "verified_at": NOW,
        "protocol_version": "LOT41A-V2",
        "allowed_content_sha256": (CONTENT_SHA,),
    }
    defaults.update(overrides)
    return VerifiedAuthorization(**defaults)


def _facts(**overrides: Any) -> PublicationFacts:
    defaults: dict[str, Any] = {
        "resource_id": uuid4(),
        "artifact_id": uuid4(),
        "collection": "rag_nexus_philo_terminale_tc",
        "canonical_url": "https://eduscol.education.gouv.fr/philosophie.pdf",
        "content_sha256": CONTENT_SHA,
        "content_event_id": uuid4(),
        "content_scope_authorization_id": AUTHORIZATION_ID,
        "content_scope_authorization_digest": AUTHORIZATION_DIGEST,
        "content_scope_authorization_protocol_version": "LOT41A-V2",
        "rights_status": Rights.officiel_public,
        "rights_assessed_at": NOW,
        "rights_event_id": uuid4(),
        "quality_passed": True,
        "quality_report_digest": "9" * 64,
        "quality_assessed_at": NOW,
        "quality_event_id": uuid4(),
        "gate_passed": True,
        "gate_name": "h2-governed",
        "gate_evaluated_at": NOW,
        "gate_event_id": uuid4(),
    }
    defaults.update(overrides)
    return PublicationFacts(**defaults)


def _verify_with(
    monkeypatch: pytest.MonkeyPatch,
    *,
    authorization: VerifiedAuthorization,
    facts: PublicationFacts,
    require_content_bound_authority: bool = True,
) -> object:
    row = {
        "attestation_id": uuid4(),
        "resource_id": facts.resource_id,
        "artifact_id": facts.artifact_id,
        "content_sha256": facts.content_sha256,
        "profile_fingerprint": authorization.profile_fingerprint,
        "manifest_digest": authorization.manifest_digest,
        "scope_authorization_id": AUTHORIZATION_ID,
        "review_id": "LOT42-H2-V2",
        "attestation_digest": "a" * 64,
    }
    monkeypatch.setattr(attestation_module, "_load_active_row", lambda *_a, **_k: row)
    monkeypatch.setattr(attestation_module, "collect_publication_facts", lambda *_a, **_k: facts)
    monkeypatch.setattr(attestation_module, "_verify_human_review", lambda *_a, **_k: object())
    monkeypatch.setattr(
        attestation_module,
        "_verify_review_artifact",
        lambda *_a, **_k: SimpleNamespace(),
    )
    monkeypatch.setattr(attestation_module, "_require_row_matches_artifact", lambda *_a, **_k: None)
    monkeypatch.setattr(attestation_module, "_require_facts_still_hold", lambda *_a, **_k: None)
    monkeypatch.setattr(attestation_module, "verify_scope_authorization", lambda *_a, **_k: authorization)
    monkeypatch.setattr(attestation_module, "authorization_allows_rights", lambda *_a, **_k: True)
    monkeypatch.setattr(attestation_module, "_mark_invalidated", lambda *_a, **_k: None)

    return verify_publication_attestation(
        object(),
        resource_id=facts.resource_id,
        current_content_sha256=facts.content_sha256,
        current_profile_fingerprint=authorization.profile_fingerprint,
        current_manifest_digest=authorization.manifest_digest,
        require_content_bound_authority=require_content_bound_authority,
    )


def test_content_bound_verification_rejects_v1_but_legacy_default_preserves_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization(
        protocol_version="LOT41A-V1",
        allowed_content_sha256=None,
    )
    facts = _facts(content_scope_authorization_protocol_version="LOT41A-V1")

    assert _verify_with(
        monkeypatch,
        authorization=authorization,
        facts=facts,
        require_content_bound_authority=False,
    )
    with pytest.raises(
        PublicationAttestationInvalidError,
        match="CONTENT_ALLOWLIST_AUTHORITY_REQUIRED",
    ):
        _verify_with(monkeypatch, authorization=authorization, facts=facts)


@pytest.mark.parametrize(
    "facts",
    (
        _facts(content_scope_authorization_id="another-authorization"),
        _facts(content_scope_authorization_digest="f" * 64),
        _facts(content_scope_authorization_protocol_version="LOT41A-V1"),
    ),
)
def test_fetched_authority_binding_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    facts: PublicationFacts,
) -> None:
    with pytest.raises(PublicationAttestationInvalidError, match="FETCHED authority"):
        _verify_with(monkeypatch, authorization=_authorization(), facts=facts)


def test_unlisted_fetched_content_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization(allowed_content_sha256=("f" * 64,))

    with pytest.raises(PublicationAttestationInvalidError, match="not in authorization"):
        _verify_with(monkeypatch, authorization=authorization, facts=_facts())


def test_content_event_is_part_of_canonical_evidence_ids() -> None:
    facts = _facts()

    assert str(facts.content_event_id) in facts.evidence_event_ids
    assert len(facts.evidence_event_ids) == 4


class _MissingFetchedCursor(AbstractContextManager["_MissingFetchedCursor"]):
    def __init__(self) -> None:
        self.query = ""

    def __enter__(self) -> _MissingFetchedCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, _params: object) -> None:
        self.query = query

    def fetchone(self) -> tuple[object, ...] | None:
        if "FROM ingestion_control.resources" in self.query:
            return ("rag_nexus_philo_terminale_tc",)
        if "FROM ingestion_control.artifacts" in self.query:
            return (CONTENT_SHA,)
        if "FROM ingestion_control.resource_candidates" in self.query:
            return ("https://eduscol.education.gouv.fr/philosophie.pdf",)
        return None


class _MissingFetchedConnection:
    def cursor(self) -> _MissingFetchedCursor:
        return _MissingFetchedCursor()


def test_missing_durable_fetched_content_event_fails_before_other_facts() -> None:
    with pytest.raises(PublicationEvidenceMissingError, match="FETCHED"):
        collect_publication_facts(
            _MissingFetchedConnection(),
            resource_id=uuid4(),
            artifact_id=uuid4(),
        )


class _TamperedFetchedCursor(AbstractContextManager["_TamperedFetchedCursor"]):
    def __init__(self, fetched_payload: dict[str, object]) -> None:
        self.fetched_payload = fetched_payload
        self.query = ""
        self.params: dict[str, object] = {}

    def __enter__(self) -> _TamperedFetchedCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: object) -> None:
        self.query = query
        self.params = params if isinstance(params, dict) else {}

    def fetchone(self) -> tuple[object, ...] | None:
        if "FROM ingestion_control.resources" in self.query:
            return ("rag_nexus_philo_terminale_tc",)
        if "FROM ingestion_control.artifacts" in self.query:
            return (CONTENT_SHA,)
        if "FROM ingestion_control.resource_candidates" in self.query:
            return ("https://eduscol.education.gouv.fr/philosophie.pdf",)
        if self.params.get("to_state") == "FETCHED":
            return (uuid4(), self.fetched_payload)
        return None


class _TamperedFetchedConnection:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def cursor(self) -> _TamperedFetchedCursor:
        return _TamperedFetchedCursor(self.payload)


@pytest.mark.parametrize(
    ("payload_override", "message"),
    (
        ({"sha256": "f" * 64}, "sha256"),
        ({"sha256": int(CONTENT_SHA)}, "sha256"),
        ({"artifact_id": str(uuid4())}, "artifact_id"),
        ({"scope_authorization_id": 123}, "scope_authorization_id"),
        ({"scope_authorization_digest": "not-a-digest"}, "digest"),
        ({"scope_authorization_digest": int(AUTHORIZATION_DIGEST)}, "digest"),
    ),
)
def test_tampered_fetched_event_cannot_become_publication_facts(
    payload_override: dict[str, object],
    message: str,
) -> None:
    artifact_id = uuid4()
    payload: dict[str, object] = {
        "artifact_id": str(artifact_id),
        "sha256": CONTENT_SHA,
        "scope_authorization_id": AUTHORIZATION_ID,
        "scope_authorization_digest": AUTHORIZATION_DIGEST,
        "scope_authorization_protocol_version": "LOT41A-V2",
    }
    payload.update(payload_override)

    with pytest.raises(PublicationEvidenceMissingError, match=message):
        collect_publication_facts(
            _TamperedFetchedConnection(payload),
            resource_id=uuid4(),
            artifact_id=artifact_id,
        )
