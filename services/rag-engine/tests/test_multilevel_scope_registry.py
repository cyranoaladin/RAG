"""Isolation identité, collection et picker des scopes multi-niveaux."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from nexus_contracts import (
    InternalIdentityEnvelope,
    PilotRetrievalScopeArtifact,
    RetrievalScopeArtifactV2,
    load_retrieval_scope_artifact,
    load_retrieval_scope_registry,
)
from starlette.requests import Request

from src.ingestor import retrieval_v2_endpoint as endpoint
from src.ingestor.collection_config import load_collection_config
from src.ingestor.identity_v2 import VerifiedInternalIdentity
from src.ingestor.retrieval_scope_v2 import (
    RetrievalScopeError,
    build_server_retrieval_scope,
    effective_signed_collections,
    validate_scope_registry_catalogue_alignment,
)

ENGINE_ROOT = Path(__file__).resolve().parents[1]
RELEASE_REGISTRY = (
    Path(__file__).resolve().parents[3]
    / "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json"
)
COLLECTION_CONFIG = ENGINE_ROOT / "configs" / "rag_collections.yml"
MULTILEVEL_RELEASE = (
    ENGINE_ROOT.parent
    / "rag-pedago"
    / "data"
    / "releases"
    / "prerentree_2026_2027"
    / "multilevel"
    / "multilevel.release.json"
)
WAVE0_RELEASE = (
    ENGINE_ROOT.parent
    / "rag-pedago"
    / "data"
    / "releases"
    / "prerentree_2026_2027"
    / "wave0"
    / "wave0.release.json"
)
WAVE0_RELEASE_SHA256 = (
    "0cf9c5d8ceaa2766aa97195743e949ec0a907ed0f609f116275a7d1f8202498d"
)
MULTILEVEL_RELEASE_SHA256 = (
    "d8ee6703d3497e34e6e5273bee00da90ab9c82094f0f9a1257eef0ff91da1828"
)

MULTILEVEL_SCOPE_COLLECTIONS = {
    "entree_premiere_maths_v1": "rag_nexus_maths_seconde_tc",
    "entree_premiere_francais_v1": "rag_nexus_francais_seconde_tc",
    "entree_troisieme_maths_v1": "rag_nexus_maths_quatrieme_tc",
    "entree_troisieme_francais_v1": "rag_nexus_francais_quatrieme_tc",
    "entree_terminale_maths_v1": "rag_nexus_maths_premiere_gen_specialite",
    "entree_terminale_nsi_v1": "rag_nexus_nsi_premiere_specialite",
    "eaf_premiere_francais_v1": "rag_nexus_francais_premiere_tc",
    "terminale_maths_v1": "rag_nexus_maths_terminale_gen_specialite",
    "terminale_nsi_v1": "rag_nexus_nsi_terminale_specialite",
    "terminale_physique_chimie_v1": "rag_nexus_pc_terminale_specialite",
}


def _multilevel_v2_release_registry(
    *subject_sha256_by_collection: tuple[str, str],
) -> SimpleNamespace:
    expectation = SimpleNamespace(
        release_kind="MULTILEVEL_AGGREGATE_RELEASE_V2",
        subject_manifest_sha256_by_collection=subject_sha256_by_collection,
    )
    manifest = SimpleNamespace(expectation=expectation)
    collections = tuple(collection for collection, _sha256 in subject_sha256_by_collection)
    return SimpleNamespace(
        collections=collections,
        manifests=(manifest,),
        manifest_for_collection=lambda collection: (
            manifest if collection in collections else None
        ),
    )


def _verified(scope_id: str, *, role: str = "teacher") -> VerifiedInternalIdentity:
    artifact = load_retrieval_scope_artifact(scope_id)
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    target = artifact.target_identity
    evidence = artifact.evidence_subject
    envelope = InternalIdentityEnvelope.model_validate(
        {
            "protocol_version": "1",
            "iss": "cockpit-internal",
            "aud": "rag-engine",
            "sub": "psn_1234567890abcdef",
            "jti": "jti-multilevel-123",
            "iat": 1_799_999_990,
            "exp": 1_800_000_300,
            "identity": {
                "aud": "nexus-cockpit",
                "exp": 1_800_000_600,
                "iss": "nexus-issuer",
                "jti": "jti-multilevel-123",
                "tenant": target.tenant,
                "niveau": target.niveau,
                "role": role,
                "school_year": evidence.school_year,
                "sub": "psn_1234567890abcdef",
                "pedagogical_profile": {
                    "voie": target.voie,
                    "matieres": [target.matiere],
                    "statut_enseignement": target.statut_enseignement,
                    "candidat": target.candidates[0],
                    "audience": target.audience,
                },
            },
            "scope_id": artifact.scope_id,
            "scope_digest": artifact.sha256_digest(),
            "allowed_collections": [evidence.collection],
        }
    )
    return VerifiedInternalIdentity(envelope=envelope, artifact=artifact)


def _legacy_verified() -> VerifiedInternalIdentity:
    artifact = load_retrieval_scope_artifact("libre_terminale_maths_nsi_real_v1")
    assert isinstance(artifact, PilotRetrievalScopeArtifact)
    envelope = InternalIdentityEnvelope.model_validate(
        {
            "protocol_version": "1",
            "iss": "cockpit-internal",
            "aud": "rag-engine",
            "sub": "psn_1234567890abcdef",
            "jti": "jti-legacy-123",
            "iat": 1_799_999_990,
            "exp": 1_800_000_300,
            "identity": {
                "aud": "nexus-cockpit",
                "exp": 1_800_000_600,
                "iss": "nexus-issuer",
                "jti": "jti-legacy-123",
                "tenant": artifact.identity.tenant,
                "niveau": artifact.identity.niveau,
                "role": "teacher",
                "school_year": artifact.school_year,
                "sub": "psn_1234567890abcdef",
                "pedagogical_profile": {
                    "voie": artifact.identity.voie,
                    "matieres": ["nsi"],
                    "statut_enseignement": artifact.identity.statut_enseignement,
                    "candidat": "libre",
                    "audience": artifact.identity.audience,
                },
            },
            "scope_id": artifact.scope_id,
            "scope_digest": artifact.sha256_digest(),
            "allowed_collections": [item.collection for item in artifact.subjects],
        }
    )
    return VerifiedInternalIdentity(envelope=envelope, artifact=artifact)


def _all_multilevel_instantiated() -> dict[str, object]:
    config = deepcopy(load_collection_config(COLLECTION_CONFIG))
    for collection in MULTILEVEL_SCOPE_COLLECTIONS.values():
        config["collections"][collection]["instanciee"] = True
    return config


def test_complete_registry_aligns_with_adr_0041_catalogue_activation() -> None:
    config = load_collection_config(COLLECTION_CONFIG)

    validate_scope_registry_catalogue_alignment(
        load_retrieval_scope_registry(),
        config,
    )
    # ADR-0041 prévoyait l'activation de la Quatrième après réconciliation ;
    # aucune release scellée ne l'a jamais portée. Le validateur de registre ne
    # dépend pas de ce flag, et le flag suit la release servie (restaté 2026-09-02).
    served = {
        collection
        for release in json.loads(RELEASE_REGISTRY.read_text(encoding="utf-8"))["releases"]
        for collection in release["collections"]
    }
    for name in ("rag_nexus_maths_quatrieme_tc", "rag_nexus_francais_quatrieme_tc"):
        assert config["collections"][name]["instanciee"] is (name in served)


def test_each_scope_source_sha_is_its_exact_subject_release_sha() -> None:
    aggregate = json.loads(MULTILEVEL_RELEASE.read_text(encoding="utf-8"))
    release_sha_by_collection = {
        subject["collection"]: subject["sha256"] for subject in aggregate["subjects"]
    }

    assert set(release_sha_by_collection) == set(MULTILEVEL_SCOPE_COLLECTIONS.values())
    for scope_id, collection in MULTILEVEL_SCOPE_COLLECTIONS.items():
        artifact = load_retrieval_scope_artifact(scope_id)
        assert isinstance(artifact, RetrievalScopeArtifactV2)
        assert artifact.source_sha256 == release_sha_by_collection[collection]


@pytest.mark.parametrize(
    ("scope_id", "collection"),
    MULTILEVEL_SCOPE_COLLECTIONS.items(),
)
def test_teacher_identity_resolves_only_its_internal_collection(
    scope_id: str,
    collection: str,
) -> None:
    verified = _verified(scope_id)
    scope = build_server_retrieval_scope(
        verified,
        collection=collection,
        collection_config=_all_multilevel_instantiated(),
    )

    assert effective_signed_collections(verified) == (collection,)
    assert scope.collection == collection
    assert scope.visibilities == ("internal",)
    assert scope.source_sha256 == verified.artifact.source_sha256


@pytest.mark.parametrize("scope_id", MULTILEVEL_SCOPE_COLLECTIONS)
def test_student_identity_cannot_read_an_internal_multilevel_scope(
    scope_id: str,
) -> None:
    verified = _verified(scope_id, role="student")
    collection = MULTILEVEL_SCOPE_COLLECTIONS[scope_id]

    with pytest.raises(RetrievalScopeError, match="retrieval scope forbidden"):
        build_server_retrieval_scope(
            verified,
            collection=collection,
            collection_config=_all_multilevel_instantiated(),
        )


@pytest.mark.parametrize(
    ("scope_id", "collection"),
    MULTILEVEL_SCOPE_COLLECTIONS.items(),
)
def test_collections_picker_returns_only_the_signed_collection(
    monkeypatch: pytest.MonkeyPatch,
    scope_id: str,
    collection: str,
) -> None:
    verified = _verified(scope_id)
    config = _all_multilevel_instantiated()
    monkeypatch.setattr(endpoint, "_require_retrieval_identity", lambda *_args, **_kwargs: verified)
    monkeypatch.setattr(endpoint, "load_collection_config", lambda: config)
    monkeypatch.setattr(endpoint, "_release_evidence_for_collection", lambda _name: True)
    request = Request({"type": "http", "method": "GET", "path": "/collections/v2"})

    response = endpoint.list_retrievable_collections(request)

    assert [item["name"] for item in response["collections"]] == [collection]


def test_cross_scope_identity_cannot_select_another_multilevel_collection() -> None:
    verified = _verified("entree_premiere_maths_v1")

    with pytest.raises(RetrievalScopeError, match="retrieval scope forbidden"):
        build_server_retrieval_scope(
            verified,
            collection="rag_nexus_francais_seconde_tc",
            collection_config=_all_multilevel_instantiated(),
        )


def test_v1_historical_retrieval_is_not_gated_by_a_new_v2_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def release_state(collection: str) -> bool:
        events.append(collection)
        return False

    monkeypatch.setattr(
        endpoint,
        "_release_evidence_for_collection",
        release_state,
    )

    definition = endpoint._check_retrievable(
        "rag_nexus_nsi_terminale_specialite",
        _all_multilevel_instantiated(),
        verified=_legacy_verified(),
    )

    assert definition["matiere"] == "nsi"
    assert events == []


@pytest.mark.parametrize("release_state", [None, False])
def test_v2_retrieval_requires_release_readiness_exactly_true(
    monkeypatch: pytest.MonkeyPatch,
    release_state: bool | None,
) -> None:
    monkeypatch.setattr(
        endpoint,
        "_release_evidence_for_collection",
        lambda _collection: release_state,
    )

    with pytest.raises(HTTPException) as exc_info:
        endpoint._check_retrievable(
            "rag_nexus_nsi_terminale_specialite",
            _all_multilevel_instantiated(),
            verified=_verified("terminale_nsi_v1"),
        )

    assert getattr(exc_info.value, "status_code", None) == 503


def test_v2_retrieval_accepts_exact_release_readiness_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        endpoint,
        "_release_evidence_for_collection",
        lambda _collection: True,
    )

    definition = endpoint._check_retrievable(
        "rag_nexus_nsi_terminale_specialite",
        _all_multilevel_instantiated(),
        verified=_verified("terminale_nsi_v1"),
    )

    assert definition["matiere"] == "nsi"


def test_v2_picker_hides_collection_when_release_manifest_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified = _verified("terminale_nsi_v1")
    monkeypatch.setattr(
        endpoint,
        "_require_retrieval_identity",
        lambda *_args, **_kwargs: verified,
    )
    monkeypatch.setattr(
        endpoint,
        "load_collection_config",
        _all_multilevel_instantiated,
    )
    monkeypatch.setattr(
        endpoint,
        "_release_evidence_for_collection",
        lambda _collection: None,
    )

    response = endpoint.list_retrievable_collections(
        Request({"type": "http", "method": "GET", "path": "/collections/v2"})
    )

    assert response == {"collections": []}


def test_startup_accepts_explicit_nonempty_release_subset_of_v2_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restaté le 2026-09-02 : la release explicite est celle des onze
    collections servies (profile_gate), avec le catalogue réel — la vague 0
    (Troisième) n'a jamais été servie et ne recouvre plus le catalogue."""
    import hashlib

    aggregate = (
        ENGINE_ROOT.parent
        / "rag-pedago/data/releases/prerentree_2026_2027/profile_gate"
        / "production-profile-gate.release.json"
    )
    monkeypatch.setenv("RAG_RELEASE_MANIFEST_PATH", str(aggregate))
    monkeypatch.setenv(
        "RAG_RELEASE_MANIFEST_SHA256", hashlib.sha256(aggregate.read_bytes()).hexdigest()
    )

    endpoint.validate_release_startup_configuration(
        load_retrieval_scope_registry(),
        load_collection_config(COLLECTION_CONFIG),
    )


def test_startup_rejects_scope_source_sha_different_from_subject_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = dict(load_retrieval_scope_registry())
    artifact = registry["entree_premiere_maths_v1"]
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    registry[artifact.scope_id] = artifact.model_copy(
        update={"source_sha256": "0" * 64}
    )
    monkeypatch.setenv("RAG_RELEASE_MANIFEST_PATH", str(MULTILEVEL_RELEASE))
    monkeypatch.setenv(
        "RAG_RELEASE_MANIFEST_SHA256",
        MULTILEVEL_RELEASE_SHA256,
    )

    with pytest.raises(RuntimeError, match="subject release"):
        endpoint.validate_release_startup_configuration(
            registry,
            _all_multilevel_instantiated(),
        )


def test_request_gate_rejects_multilevel_scope_source_sha_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = load_retrieval_scope_artifact("entree_premiere_maths_v1")
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    drifted = artifact.model_copy(update={"source_sha256": "0" * 64})
    monkeypatch.setenv("RAG_RELEASE_MANIFEST_PATH", str(MULTILEVEL_RELEASE))
    monkeypatch.setenv(
        "RAG_RELEASE_MANIFEST_SHA256",
        MULTILEVEL_RELEASE_SHA256,
    )
    monkeypatch.setattr(
        endpoint,
        "_release_evidence_for_collection",
        lambda _collection: True,
    )

    assert endpoint._release_evidence_for_v2_artifact(drifted) is False


def test_request_gate_accepts_v2_subject_manifest_source_sha_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = load_retrieval_scope_artifact("entree_premiere_maths_v1")
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    collection = str(artifact.evidence_subject.collection)
    registry = _multilevel_v2_release_registry((collection, artifact.source_sha256))
    monkeypatch.setattr(endpoint, "_release_evidence_for_collection", lambda _name: True)
    monkeypatch.setattr(endpoint, "_configured_release_registry", lambda: registry)

    assert endpoint._release_evidence_for_v2_artifact(artifact) is True


def test_request_gate_rejects_v2_subject_manifest_source_sha_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = load_retrieval_scope_artifact("entree_premiere_maths_v1")
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    collection = str(artifact.evidence_subject.collection)
    registry = _multilevel_v2_release_registry((collection, "0" * 64))
    monkeypatch.setattr(endpoint, "_release_evidence_for_collection", lambda _name: True)
    monkeypatch.setattr(endpoint, "_configured_release_registry", lambda: registry)

    assert endpoint._release_evidence_for_v2_artifact(artifact) is False


def test_startup_rejects_ambiguous_v2_scope_for_one_subject_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = load_retrieval_scope_artifact("entree_premiere_maths_v1")
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    collection = str(artifact.evidence_subject.collection)
    registry = _multilevel_v2_release_registry((collection, artifact.source_sha256))
    duplicate = artifact.model_copy(update={"scope_id": f"{artifact.scope_id}-duplicate"})
    monkeypatch.setattr(endpoint, "_configured_release_registry", lambda: registry)

    with pytest.raises(RuntimeError, match="ambiguous"):
        endpoint.validate_release_startup_configuration(
            {artifact.scope_id: artifact, duplicate.scope_id: duplicate},
            _all_multilevel_instantiated(),
        )


def test_chat_separates_target_identity_from_n_minus_one_evidence() -> None:
    verified = _verified("entree_premiere_maths_v1")
    artifact = verified.artifact
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    scope = build_server_retrieval_scope(
        verified,
        collection=artifact.evidence_subject.collection,
        collection_config=_all_multilevel_instantiated(),
    )
    payload = {
        "student_profile": {
            "niveau": "premiere",
            "voie": "generale",
            "matieres": ["maths"],
            "statut_enseignement": "tronc_commun",
            "candidat": "libre",
            "school_year": "2026-2027",
            "zone": "libre",
        },
        "query": "Préparer l'entrée en première",
        "collections": [artifact.evidence_subject.collection],
    }

    endpoint._require_chat_profile_match(
        endpoint.ChatRequest.model_validate(payload),
        [artifact.evidence_subject.collection],
        {artifact.evidence_subject.collection: scope},
        verified=verified,
    )


def test_chat_rejects_evidence_level_claimed_as_student_target() -> None:
    verified = _verified("entree_premiere_maths_v1")
    artifact = verified.artifact
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    scope = build_server_retrieval_scope(
        verified,
        collection=artifact.evidence_subject.collection,
        collection_config=_all_multilevel_instantiated(),
    )
    payload = {
        "student_profile": {
            "niveau": "seconde",
            "voie": "generale",
            "matieres": ["maths"],
            "statut_enseignement": "tronc_commun",
            "candidat": "libre",
            "school_year": "2026-2027",
            "zone": "libre",
        },
        "query": "Préparer l'entrée en première",
        "collections": [artifact.evidence_subject.collection],
    }

    with pytest.raises(HTTPException) as exc_info:
        endpoint._require_chat_profile_match(
            endpoint.ChatRequest.model_validate(payload),
            [artifact.evidence_subject.collection],
            {artifact.evidence_subject.collection: scope},
            verified=verified,
        )

    assert exc_info.value.status_code == 403
