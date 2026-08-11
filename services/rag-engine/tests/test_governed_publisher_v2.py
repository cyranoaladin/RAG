"""Contrat du publisher produit interne et gouverné H2-C."""

from __future__ import annotations

import hashlib
import inspect
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from nexus_contracts import Candidat, Niveau, Voie
from nexus_contracts.document import Rights
from nexus_contracts.ingestion import ResourceScope

import ingestor.governed_publisher_v2 as publisher_module
from ingestor.governed_publisher_v2 import (
    EligiblePlacement,
    GovernedArtifact,
    GovernedPublicationError,
    canonical_placement_id,
    publish_governed_artifact,
)
from ingestor.ingestion_control.publication_attestation import VerifiedAttestation

CONTENT = b"octets canoniques d'un document pedagogique"
CONTENT_SHA = hashlib.sha256(CONTENT).hexdigest()


def _scope(
    *,
    collection: str,
    matiere: str,
    audience: list[str] | None = None,
) -> ResourceScope:
    return ResourceScope(
        tenant="libre_terminale",
        collection=collection,
        niveau=Niveau.terminale,
        voie=Voie.generale,
        matiere=matiere,
        candidat=Candidat.libre,
        audience=audience or ["tous"],
        visibility="public",
        school_year="2026-2027",
        programme_version="BOEN_2025",
    )


def _placement(*, collection: str, matiere: str) -> EligiblePlacement:
    return EligiblePlacement(
        resource_id=uuid4(),
        scope=_scope(collection=collection, matiere=matiere),
        statut_enseignement="tronc_commun",
        domain="lycee",
        source_scope=f"01_EDUSCOL_OFFICIEL/terminale/{matiere}",
        source_placement_id=f"eduscol:5793:terminale:{matiere}",
        source_path=f"01_EDUSCOL_OFFICIEL/{matiere}/source.pdf",
        source_uri=f"https://eduscol.education.gouv.fr/{matiere}",
        current_profile_fingerprint="1" * 64,
        current_manifest_digest="2" * 64,
    )


def test_artifact_identity_is_exactly_the_content_sha() -> None:
    artifact = GovernedArtifact(
        content=CONTENT,
        content_sha256=CONTENT_SHA,
        source_label="Ressource Eduscol",
        source_uri="https://eduscol.education.fr/document.pdf",
        rights="officiel_public",
        official=True,
        source_kind="eduscol",
        type_doc="ressource_officielle",
    )

    assert artifact.artifact_id == CONTENT_SHA
    assert artifact.content_sha256 == hashlib.sha256(artifact.content).hexdigest()


def test_artifact_rejects_a_content_sha_drift() -> None:
    with pytest.raises(ValueError, match="content SHA-256"):
        GovernedArtifact(
            content=CONTENT,
            content_sha256="0" * 64,
            source_label="Ressource Eduscol",
            source_uri="https://eduscol.education.fr/document.pdf",
            rights="officiel_public",
            official=True,
            source_kind="eduscol",
            type_doc="ressource_officielle",
        )


def test_placement_identity_changes_without_changing_artifact_identity() -> None:
    philosophy = _placement(
        collection="rag_nexus_philo_terminale_tc",
        matiere="philosophie",
    )
    arts = _placement(
        collection="rag_nexus_arts_terminale_option",
        matiere="arts",
    )

    assert canonical_placement_id(CONTENT_SHA, philosophy) != canonical_placement_id(
        CONTENT_SHA, arts
    )
    assert canonical_placement_id(CONTENT_SHA, philosophy) == canonical_placement_id(
        CONTENT_SHA, philosophy
    )


def test_placement_preserves_its_own_source_uri() -> None:
    philosophy = _placement(
        collection="rag_nexus_philo_terminale_tc",
        matiere="philosophie",
    )

    assert philosophy.source_uri == "https://eduscol.education.gouv.fr/philosophie"


def test_persisted_placement_uses_the_same_canonical_audience_order_as_identity() -> None:
    placement = EligiblePlacement(
        resource_id=uuid4(),
        scope=_scope(
            collection="rag_nexus_philo_terminale_tc",
            matiere="philosophie",
            audience=["tous", "libre"],
        ),
        statut_enseignement="tronc_commun",
        domain="lycee",
        source_scope="01_EDUSCOL_OFFICIEL/terminale/philosophie",
        source_placement_id="eduscol:5793:terminale:philosophie",
        source_path="01_EDUSCOL_OFFICIEL/philosophie/source.pdf",
        source_uri="https://eduscol.education.gouv.fr/philosophie",
        current_profile_fingerprint="1" * 64,
        current_manifest_digest="2" * 64,
    )

    class Cursor:
        inserted: tuple[object, ...] | None = None

        def execute(self, query: str, params: tuple[object, ...]) -> None:
            if "INSERT INTO" in query:
                self.inserted = params

        def fetchone(self) -> tuple[object, ...]:
            assert self.inserted is not None
            return self.inserted

    cursor = Cursor()
    verified = SimpleNamespace(
        placement=placement,
        attestation=SimpleNamespace(
            scope_authorization_id="AUTH-H2-V2",
            attestation_id=uuid4(),
        ),
    )

    publisher_module._insert_placement(
        cursor,
        artifact_id=CONTENT_SHA,
        verified=verified,
    )

    assert cursor.inserted is not None
    assert cursor.inserted[6] == ["libre", "tous"]


def test_publisher_surface_requires_governance_objects_not_bare_text() -> None:
    parameters = inspect.signature(publish_governed_artifact).parameters

    assert tuple(parameters) == (
        "control_conn",
        "product_conn",
        "artifact",
        "placements",
        "extract_text",
        "embed_chunks",
    )
    assert "text" not in parameters
    assert "collection" not in parameters


def test_no_http_writer_mount_imports_the_internal_publisher() -> None:
    engine_root = Path(__file__).resolve().parents[1]
    api = (engine_root / "src/ingestor/api_v2.py").read_text(encoding="utf-8")
    endpoint = (engine_root / "src/ingestor/retrieval_v2_endpoint.py").read_text(
        encoding="utf-8"
    )

    assert "governed_publisher_v2" not in api
    assert "governed_publisher_v2" not in endpoint


def test_v1_or_unbound_attestation_fails_before_any_product_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = GovernedArtifact(
        content=CONTENT,
        content_sha256=CONTENT_SHA,
        source_label="Ressource Eduscol",
        source_uri="https://eduscol.education.gouv.fr/philosophie",
        rights="officiel_public",
        official=True,
        source_kind="eduscol",
        type_doc="ressource_officielle",
    )
    placement = _placement(
        collection="rag_nexus_philo_terminale_tc",
        matiere="philosophie",
    )
    verifier_calls: list[bool] = []

    def deny_v1(_conn: object, **kwargs: object) -> object:
        verifier_calls.append(bool(kwargs.get("require_content_bound_authority")))
        raise RuntimeError("CONTENT_ALLOWLIST_AUTHORITY_REQUIRED")

    class NoProductWrites:
        def transaction(self) -> object:
            pytest.fail("product transaction must not start after LOT42 denial")

    class ControlConnection:
        def transaction(self) -> object:
            return nullcontext()

    monkeypatch.setattr(publisher_module, "verify_publication_attestation", deny_v1)
    monkeypatch.setattr(
        publisher_module,
        "_lock_governance_commit_fence",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(RuntimeError, match="CONTENT_ALLOWLIST_AUTHORITY_REQUIRED"):
        publish_governed_artifact(
            ControlConnection(),
            NoProductWrites(),
            artifact,
            (placement,),
            lambda raw: raw.decode(),
            lambda _chunks: (),
        )

    assert verifier_calls == [True]


def test_atomic_reverification_denial_rolls_back_before_product_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = GovernedArtifact(
        content=CONTENT,
        content_sha256=CONTENT_SHA,
        source_label="Ressource Eduscol",
        source_uri="https://eduscol.education.gouv.fr/philosophie",
        rights="officiel_public",
        official=True,
        source_kind="eduscol",
        type_doc="ressource_officielle",
    )
    placement = _placement(
        collection="rag_nexus_philo_terminale_tc",
        matiere="philosophie",
    )
    facts = SimpleNamespace(
        content_sha256=CONTENT_SHA,
        collection=str(placement.scope.collection),
        canonical_url=placement.source_uri,
        rights_status=Rights.officiel_public,
        # H2-F (défaut 6) : le publisher confronte désormais l'attribution
        # attestée à celle de l'artefact publié.
        source_label="Ressource Eduscol",
        official=True,
        source_kind="eduscol",
        type_doc="ressource_officielle",
    )
    verified = VerifiedAttestation(
        attestation_id=uuid4(),
        resource_id=placement.resource_id,
        artifact_id=uuid4(),
        content_sha256=CONTENT_SHA,
        scope_authorization_id="h2-v2",
        profile_fingerprint=placement.current_profile_fingerprint,
        manifest_digest=placement.current_manifest_digest,
        review_id="lot42-v2",
        attestation_digest="3" * 64,
        authorization=SimpleNamespace(scope=placement.scope),
        facts=facts,
    )
    calls = {"verify": 0, "transaction": 0, "cursor": 0}

    def verify(_conn: object, **kwargs: object) -> VerifiedAttestation:
        assert kwargs["require_content_bound_authority"] is True
        calls["verify"] += 1
        if calls["verify"] == 2:
            raise RuntimeError("authority revoked during product transaction")
        return verified

    class ProductConnection:
        def transaction(self) -> object:
            calls["transaction"] += 1
            return nullcontext()

        def cursor(self) -> object:
            calls["cursor"] += 1
            pytest.fail("no product cursor is allowed after atomic reverify denial")

    class ControlConnection:
        def transaction(self) -> object:
            return nullcontext()

    monkeypatch.setattr(publisher_module, "verify_publication_attestation", verify)
    monkeypatch.setattr(
        publisher_module,
        "_lock_governance_commit_fence",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        publisher_module,
        "_resource_is_retrieval_eligible",
        lambda *_args, **_kwargs: True,
    )

    with pytest.raises(RuntimeError, match="revoked during product transaction"):
        publish_governed_artifact(
            ControlConnection(),
            ProductConnection(),
            artifact,
            (placement,),
            lambda raw: raw.decode(),
            lambda _chunks: (),
        )

    assert calls == {"verify": 2, "transaction": 0, "cursor": 0}


def test_external_authority_pin_commits_before_fenced_product_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = GovernedArtifact(
        content=CONTENT,
        content_sha256=CONTENT_SHA,
        source_label="Ressource Eduscol",
        source_uri="https://eduscol.education.gouv.fr/philosophie",
        rights="officiel_public",
        official=True,
        source_kind="eduscol",
        type_doc="ressource_officielle",
    )
    placement = _placement(
        collection="rag_nexus_philo_terminale_tc",
        matiere="philosophie",
    )
    facts = SimpleNamespace(
        content_sha256=CONTENT_SHA,
        collection=str(placement.scope.collection),
        canonical_url=placement.source_uri,
        rights_status=Rights.officiel_public,
        # H2-F (défaut 6) : le publisher confronte désormais l'attribution
        # attestée à celle de l'artefact publié.
        source_label="Ressource Eduscol",
        official=True,
        source_kind="eduscol",
        type_doc="ressource_officielle",
    )
    verified = VerifiedAttestation(
        attestation_id=uuid4(),
        resource_id=placement.resource_id,
        artifact_id=uuid4(),
        content_sha256=CONTENT_SHA,
        scope_authorization_id="h2-v2",
        profile_fingerprint=placement.current_profile_fingerprint,
        manifest_digest=placement.current_manifest_digest,
        review_id="lot42-v2",
        attestation_digest="3" * 64,
        authorization=SimpleNamespace(
            authorization_id="h2-v2",
            authorization_digest="4" * 64,
            scope=placement.scope,
        ),
        facts=facts,
    )
    events: list[str] = []

    class Transaction:
        def __init__(self, label: str) -> None:
            self.label = label

        def __enter__(self) -> None:
            events.append(f"{self.label}:enter")

        def __exit__(self, *_args: object) -> None:
            events.append(f"{self.label}:exit")

    class Cursor:
        last_query = ""

        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, query: str, _params: object = None) -> None:
            self.last_query = query

        def fetchone(self) -> tuple[int]:
            return (1,)

    class Connection:
        def __init__(self, label: str) -> None:
            self.label = label

        def transaction(self) -> Transaction:
            return Transaction(self.label)

        def cursor(self) -> Cursor:
            return Cursor()

    def verify(*_args: object, **_kwargs: object) -> VerifiedAttestation:
        events.append("verify")
        return verified

    def fence(*_args: object, **_kwargs: object) -> None:
        events.append("fence")

    def pin(*_args: object, **_kwargs: object) -> tuple[str, ...]:
        events.append("pin")
        return ("5" * 64,)

    monkeypatch.setattr(publisher_module, "verify_publication_attestation", verify)
    monkeypatch.setattr(
        publisher_module,
        "_resource_is_retrieval_eligible",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(publisher_module, "_lock_governance_commit_fence", fence)
    monkeypatch.setattr(publisher_module, "_persist_external_authority_pins", pin)
    monkeypatch.setattr(publisher_module, "_lock_artifact", lambda *_args: None)
    monkeypatch.setattr(
        publisher_module,
        "_artifact_row",
        lambda *_args: (
            CONTENT_SHA,
            artifact.rights,
            artifact.official,
            artifact.source_kind,
            artifact.type_doc,
        ),
    )
    monkeypatch.setattr(publisher_module, "_insert_placement", lambda *_args, **_kwargs: None)

    result = publish_governed_artifact(
        Connection("control"),
        Connection("product"),
        artifact,
        (placement,),
        lambda raw: raw.decode(),
        lambda _chunks: (),
    )

    assert result.artifact_created is False
    first_control_exit = events.index("control:exit")
    product_enter = events.index("product:enter")
    assert events.index("pin") < first_control_exit < product_enter
    assert events.count("pin") == 2
    assert events.count("control:enter") == 2
    assert events[-1] == "control:exit"
    assert events.index("product:exit") < len(events) - 1


def test_external_pin_drift_refuses_before_the_product_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = GovernedArtifact(
        content=CONTENT,
        content_sha256=CONTENT_SHA,
        source_label="Ressource Eduscol",
        source_uri="https://eduscol.education.gouv.fr/philosophie",
        rights="officiel_public",
        official=True,
        source_kind="eduscol",
        type_doc="ressource_officielle",
    )
    placement = _placement(
        collection="rag_nexus_philo_terminale_tc",
        matiere="philosophie",
    )
    facts = SimpleNamespace(
        content_sha256=CONTENT_SHA,
        collection=str(placement.scope.collection),
        canonical_url=placement.source_uri,
        rights_status=Rights.officiel_public,
        # H2-F (défaut 6) : le publisher confronte désormais l'attribution
        # attestée à celle de l'artefact publié.
        source_label="Ressource Eduscol",
        official=True,
        source_kind="eduscol",
        type_doc="ressource_officielle",
    )
    verified = VerifiedAttestation(
        attestation_id=uuid4(),
        resource_id=placement.resource_id,
        artifact_id=uuid4(),
        content_sha256=CONTENT_SHA,
        scope_authorization_id="h2-v2",
        profile_fingerprint=placement.current_profile_fingerprint,
        manifest_digest=placement.current_manifest_digest,
        review_id="lot42-v2",
        attestation_digest="3" * 64,
        authorization=SimpleNamespace(
            authorization_id="h2-v2",
            authorization_digest="4" * 64,
            scope=placement.scope,
        ),
        facts=facts,
    )
    pins = iter((("5" * 64,), ("6" * 64,)))

    class ControlConnection:
        def transaction(self) -> object:
            return nullcontext()

    class NoProductWrites:
        def transaction(self) -> object:
            pytest.fail("pin drift must refuse before product transaction")

    monkeypatch.setattr(
        publisher_module,
        "verify_publication_attestation",
        lambda *_args, **_kwargs: verified,
    )
    monkeypatch.setattr(
        publisher_module,
        "_resource_is_retrieval_eligible",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        publisher_module,
        "_lock_governance_commit_fence",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        publisher_module,
        "_persist_external_authority_pins",
        lambda *_args, **_kwargs: next(pins),
    )

    with pytest.raises(GovernedPublicationError, match="external authority pin drift"):
        publish_governed_artifact(
            ControlConnection(),
            NoProductWrites(),
            artifact,
            (placement,),
            lambda raw: raw.decode(),
            lambda _chunks: (),
        )
