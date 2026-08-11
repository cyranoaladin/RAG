"""LOT42 lie la publication H2 au FETCHED autorisé et durable."""
from __future__ import annotations

import inspect
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from nexus_contracts.document import Rights
from nexus_contracts.ingestion import ResourceScope

import ingestor.ingestion_control.publication_attestation as attestation_module
from ingestor.ingestion_control.artifact_attribution import attribution_digest
from ingestor.ingestion_control.publication_attestation import (
    PublicationAttestationInvalidError,
    attempt_retrieval_eligible_transition,
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

#: Attribution H2-F telle que le pipeline gouverné l'aurait persistée pour
#: cet artefact. Le digest est recalculé depuis l'``ingestion_artifact_id``
#: réellement demandé — un tuple figé masquerait la liaison entre les quatre
#: faits et leur artefact, qui est précisément ce que ce digest prouve.
ATTRIBUTION_FACTS = ("Référentiel officiel", True, "eduscol.education.gouv.fr", "programme_officiel")


def _attribution_row(params: object) -> tuple[object, ...]:
    artifact_id = params[0] if isinstance(params, tuple) else params
    source_label, official, source_kind, type_doc = ATTRIBUTION_FACTS
    return (
        *ATTRIBUTION_FACTS,
        attribution_digest(
            ingestion_artifact_id=artifact_id,
            source_label=source_label,
            official=official,
            source_kind=source_kind,
            type_doc=type_doc,
        ),
    )


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
        # H2-F Défaut 6: Attribution durable
        "source_label": "Éduscol officiel",
        "official": True,
        "source_kind": "programme",
        "type_doc": "programme",
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
        # ADR-0035 : la ligne attestée porte désormais sa version de
        # protocole et le digest d'attribution qu'elle scelle. Ce test
        # cible l'axe LOT41A (autorité liée au contenu) ; il fournit donc
        # une ligne LOT42-V2 conforme pour ne rien masquer de cet axe-là.
        "protocol_version": "LOT42-V2",
        "attributed_facts_digest": "b" * 64,
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


def test_retrieval_anchor_has_no_content_authority_downgrade_parameter() -> None:
    parameters = inspect.signature(attempt_retrieval_eligible_transition).parameters

    assert "require_content_bound_authority" not in parameters


def test_direct_retrieval_anchor_rejects_v1_before_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource_id = uuid4()
    calls = {"verify": 0, "cas": 0}

    def verify(_conn: object, **kwargs: object) -> object:
        calls["verify"] += 1
        if kwargs.get("require_content_bound_authority") is True:
            raise PublicationAttestationInvalidError(
                "CONTENT_ALLOWLIST_AUTHORITY_REQUIRED"
            )
        return object()

    def cas(*_args: object, **_kwargs: object) -> object:
        calls["cas"] += 1
        return object()

    monkeypatch.setattr(attestation_module, "verify_publication_attestation", verify)
    monkeypatch.setattr(attestation_module, "cas_transition", cas)

    with pytest.raises(
        PublicationAttestationInvalidError,
        match="CONTENT_ALLOWLIST_AUTHORITY_REQUIRED",
    ):
        attempt_retrieval_eligible_transition(
            object(),
            resource_id=resource_id,
            run_id=uuid4(),
            expected_version=7,
            actor="test-direct-anchor",
            current_content_sha256=CONTENT_SHA,
            current_profile_fingerprint="4" * 64,
            current_manifest_digest="3" * 64,
        )

    assert calls == {"verify": 1, "cas": 0}


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
        self.params: object = ()

    def __enter__(self) -> _MissingFetchedCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: object) -> None:
        self.query = query
        self.params = params

    def fetchone(self) -> tuple[object, ...] | None:
        if "FROM ingestion_control.resources" in self.query:
            return ("rag_nexus_philo_terminale_tc",)
        if "FROM ingestion_control.artifacts" in self.query:
            return (CONTENT_SHA,)
        # H2-F (défaut 6) : attribution lue dans le plan de contrôle.
        if "FROM ingestion_control.artifact_attributions" in self.query:
            return _attribution_row(self.params)
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
        self.raw_params: object = ()

    def __enter__(self) -> _TamperedFetchedCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: object) -> None:
        self.query = query
        self.raw_params = params
        self.params = params if isinstance(params, dict) else {}

    def fetchone(self) -> tuple[object, ...] | None:
        if "FROM ingestion_control.resources" in self.query:
            return ("rag_nexus_philo_terminale_tc",)
        if "FROM ingestion_control.artifacts" in self.query:
            return (CONTENT_SHA,)
        # H2-F (défaut 6) : attribution lue dans le plan de contrôle.
        if "FROM ingestion_control.artifact_attributions" in self.query:
            return _attribution_row(self.raw_params)
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


# ---------------------------------------------------------------------------
# G4 — la troisième barrière LOT42-V1 : le blob Git relu est un V1.
#
# Les quatre barrières refusent toutes une V1, mais pour des raisons
# distinctes et à des étapes distinctes. Les épingler séparément est ce qui
# empêche un test de rester vert alors que la barrière qu'il prétend
# mesurer a disparu et qu'une autre l'a remplacée par accident.
# ---------------------------------------------------------------------------


def _publication_review_document(protocol_version: str, **overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "protocol_version": protocol_version,
        "review_id": "pub-g4-001",
        "decision": "AUTHORIZE_PUBLICATION",
        "resource_id": "11111111-1111-4111-8111-111111111111",
        "artifact_id": "22222222-2222-4222-8222-222222222222",
        "collection": "rag_nexus_philo_terminale_tc",
        "canonical_url": "https://eduscol.education.gouv.fr/philosophie",
        "content_sha256": "d" * 64,
        "scope_authorization_id": AUTHORIZATION_ID,
        "profile_id": "rag_nexus_philo_terminale_tc",
        "profile_version": "v1",
        "profile_fingerprint": "b" * 64,
        "manifest_digest": "a" * 64,
        "rights_status": "officiel_public",
        "rights_assessed_at": "2026-08-08T10:00:00Z",
        "quality_passed": True,
        "quality_report_digest": "e" * 64,
        "quality_assessed_at": "2026-08-08T10:01:00Z",
        "gate_passed": True,
        "gate_name": "routing_gate",
        "gate_evaluated_at": "2026-08-08T10:02:00Z",
        "evidence_event_ids": ["33333333-3333-4333-8333-333333333333"],
    }
    document.update(overrides)
    return document


def test_a_v1_blob_in_git_is_refused_when_the_artifact_is_re_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Barrière 3/4 : ``_verify_review_artifact`` relit le blob approuvé et
    exige LOT42-V2 avant toute comparaison de champs.

    Seule la frontière réseau est substituée : ``fetch_blob_at_ref`` rend
    des octets canoniques V1. La barrière mesurée — ``require_publication
    _review_v2`` à l'intérieur de la fonction testée — n'est pas
    monkeypatchée."""
    from nexus_contracts.authority_artifacts import (
        LOT42_PROTOCOL_VERSION,
        PublicationReviewArtifactV1,
        canonical_publication_review_path,
    )

    artifact = PublicationReviewArtifactV1.model_validate(
        _publication_review_document(LOT42_PROTOCOL_VERSION)
    )
    raw = artifact.canonical_bytes()
    digest = artifact.digest()
    row = {
        "attestation_id": uuid4(),
        "review_id": artifact.review_id,
        "attestation_digest": digest,
        "review_artifact_path": canonical_publication_review_path(
            review_id=artifact.review_id, digest=digest
        ),
        "review_artifact_blob_sha": "f" * 40,
    }

    monkeypatch.setattr(
        attestation_module,
        "fetch_blob_at_ref",
        lambda **_kwargs: SimpleNamespace(
            content=raw, blob_sha=row["review_artifact_blob_sha"]
        ),
    )
    monkeypatch.setattr(attestation_module, "_mark_invalidated", lambda *_a, **_k: None)

    invalidator = attestation_module._Invalidator(object(), row["attestation_id"])
    live = SimpleNamespace(repository="cyranoaladin/RAG", head_sha="c" * 40)

    with pytest.raises(
        PublicationAttestationInvalidError, match=r"not canonical.*LOT42-V2"
    ):
        attestation_module._verify_review_artifact(
            row, live=live, invalidator=invalidator
        )


def test_a_v2_blob_in_git_passes_the_same_barrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Garde-fou de sensibilité : le refus ci-dessus vient de la version du
    protocole, pas de la mécanique de relecture elle-même."""
    from nexus_contracts.authority_artifacts import (
        LOT42_V2_PROTOCOL_VERSION,
        PublicationReviewArtifactV2,
        canonical_publication_review_path,
    )

    artifact = PublicationReviewArtifactV2.model_validate(
        _publication_review_document(
            LOT42_V2_PROTOCOL_VERSION, attributed_facts_digest="ab" * 32
        )
    )
    raw = artifact.canonical_bytes()
    digest = artifact.digest()
    row = {
        "attestation_id": uuid4(),
        "review_id": artifact.review_id,
        "attestation_digest": digest,
        "review_artifact_path": canonical_publication_review_path(
            review_id=artifact.review_id, digest=digest
        ),
        "review_artifact_blob_sha": "f" * 40,
    }

    monkeypatch.setattr(
        attestation_module,
        "fetch_blob_at_ref",
        lambda **_kwargs: SimpleNamespace(
            content=raw, blob_sha=row["review_artifact_blob_sha"]
        ),
    )
    monkeypatch.setattr(attestation_module, "_mark_invalidated", lambda *_a, **_k: None)

    invalidator = attestation_module._Invalidator(object(), row["attestation_id"])
    live = SimpleNamespace(repository="cyranoaladin/RAG", head_sha="c" * 40)

    verified = attestation_module._verify_review_artifact(
        row, live=live, invalidator=invalidator
    )
    assert verified.protocol_version == LOT42_V2_PROTOCOL_VERSION
