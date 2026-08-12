"""Tests du scope de retrieval autoritatif et immuable."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest
from nexus_contracts import (
    InternalIdentity,
    InternalIdentityEnvelope,
    Rights,
    load_pilot_retrieval_scope,
    load_retrieval_scope_registry,
)

from src.ingestor.collection_config import (
    CollectionConfigLoadError,
    canonicalize_catalogue_voie,
    resolve_collection_v2,
    validate_collection_catalogue_v2,
)
from src.ingestor.identity_v2 import VerifiedInternalIdentity
from src.ingestor.retrieval_scope_v2 import (
    RetrievalScopeError,
    ServerRetrievalScope,
    allowed_rights_for_role,
    allowed_visibilities_for_role,
    build_server_readiness_scope,
    build_server_retrieval_scope,
    effective_signed_collections,
    validate_pilot_scope_catalogue_alignment,
    validate_scope_registry_catalogue_alignment,
)

ARTIFACT = load_pilot_retrieval_scope()
IDENTITY = InternalIdentity.model_validate(
    {
        "aud": "nexus-cockpit",
        "exp": 1_800_000_600,
        "iss": "nexus-issuer",
        "jti": "jti-12345",
        "tenant": "libre_terminale",
        "niveau": "terminale",
        "role": "student",
        "school_year": "2026-2027",
        "sub": "psn_1234567890abcdef",
        "pedagogical_profile": {
            "voie": "generale",
            "matieres": ["maths", "nsi"],
            "statut_enseignement": "specialite",
            "candidat": "individuel",
            "audience": "libre",
        },
    }
)
ENVELOPE = InternalIdentityEnvelope(
    protocol_version="1",
    iss="cockpit-internal",
    aud="rag-engine",
    sub=IDENTITY.sub,
    jti=IDENTITY.jti,
    iat=1_799_999_990,
    exp=1_800_000_300,
    identity=IDENTITY,
    scope_id=ARTIFACT.scope_id,
    scope_digest=ARTIFACT.sha256_digest(),
    allowed_collections=[subject.collection for subject in ARTIFACT.subjects],
)
VERIFIED = VerifiedInternalIdentity(envelope=ENVELOPE, artifact=ARTIFACT)
ENGINE_CONFIG = {
    "collections": {
        "rag_nexus_maths_terminale_gen_specialite": {
            "matiere": "maths",
            "niveau": "terminale",
            "voie": "gen",
            "statut": "specialite",
            "domain": "education",
            "instanciee": True,
        },
        "rag_nexus_nsi_terminale_specialite": {
            "matiere": "nsi",
            "niveau": "terminale",
            "voie": "gen",
            "statut": "specialite",
            "domain": "education",
            "instanciee": True,
        },
    },
    "domains": {"education": {"retrievable": True}},
}


def _verified_for_matieres(matieres: list[str]) -> VerifiedInternalIdentity:
    identity_payload = IDENTITY.model_dump(mode="json")
    identity_payload["pedagogical_profile"]["matieres"] = matieres
    identity = InternalIdentity.model_validate(identity_payload)
    envelope_payload = ENVELOPE.model_dump(mode="json")
    envelope_payload["identity"] = identity.model_dump(mode="json")
    envelope = InternalIdentityEnvelope.model_validate(envelope_payload)
    return VerifiedInternalIdentity(envelope=envelope, artifact=ARTIFACT)


@pytest.mark.parametrize(
    ("matieres", "expected"),
    [
        (["maths"], ("rag_nexus_maths_terminale_gen_specialite",)),
        (["nsi"], ("rag_nexus_nsi_terminale_specialite",)),
        (
            ["maths", "nsi"],
            (
                "rag_nexus_maths_terminale_gen_specialite",
                "rag_nexus_nsi_terminale_specialite",
            ),
        ),
    ],
)
def test_effective_collections_follow_only_signed_profile_subjects(
    matieres: list[str],
    expected: tuple[str, ...],
) -> None:
    assert effective_signed_collections(_verified_for_matieres(matieres)) == expected


def test_pilot_scope_catalogue_alignment_rejects_declared_dormant_subjects() -> None:
    config = deepcopy(ENGINE_CONFIG)
    config["collections"]["rag_nexus_maths_terminale_gen_specialite"][
        "instanciee"
    ] = False

    with pytest.raises(RetrievalScopeError, match="retrieval scope forbidden"):
        validate_pilot_scope_catalogue_alignment(ARTIFACT, config)


def test_mounted_catalogue_aligns_every_instantiated_pilot_subject() -> None:
    validate_pilot_scope_catalogue_alignment(
        ARTIFACT,
        validate_collection_catalogue_v2(),
    )


def test_runtime_registry_alignment_accepts_declared_dormant_legacy_scope() -> None:
    config = validate_collection_catalogue_v2()

    validate_scope_registry_catalogue_alignment(
        load_retrieval_scope_registry(),
        config,
    )


def test_runtime_registry_alignment_rejects_a_scope_key_mismatch() -> None:
    registry = dict(load_retrieval_scope_registry())
    registry["not-the-artifact-scope-id"] = registry.pop(
        "entree_seconde_maths_v1"
    )

    with pytest.raises(RetrievalScopeError, match="retrieval scope forbidden"):
        validate_scope_registry_catalogue_alignment(
            registry,
            validate_collection_catalogue_v2(),
        )


@pytest.mark.parametrize(
    ("drift", "value"),
    (
        ("missing_collection", None),
        ("instanciee", False),
        ("domain_retrievable", False),
        ("matiere", "nsi"),
        ("niveau", "premiere"),
        ("voie", "stmg"),
        ("statut", "tronc_commun"),
    ),
)
def test_pilot_scope_catalogue_alignment_rejects_every_runtime_drift(
    drift: str,
    value: object,
) -> None:
    config = deepcopy(ENGINE_CONFIG)
    collection = "rag_nexus_maths_terminale_gen_specialite"
    if drift == "missing_collection":
        del config["collections"][collection]
    elif drift == "domain_retrievable":
        config["domains"]["education"]["retrievable"] = value
    else:
        config["collections"][collection][drift] = value

    with pytest.raises(RetrievalScopeError, match="retrieval scope forbidden"):
        validate_pilot_scope_catalogue_alignment(ARTIFACT, config)


@pytest.mark.parametrize(
    ("catalogue_value", "expected"),
    [
        ("gen", "generale"),
        ("stmg", "technologique"),
        ("generale", "generale"),
        ("technologique", "technologique"),
        ("college", "college"),
        (None, None),
    ],
)
def test_catalogue_voie_adapter_is_central_and_exhaustive(
    catalogue_value: str | None,
    expected: str | None,
) -> None:
    assert canonicalize_catalogue_voie(catalogue_value) == expected


@pytest.mark.parametrize("unknown", ["pro", "STMG", "", 7])
def test_catalogue_voie_adapter_rejects_unknown_values(unknown: object) -> None:
    with pytest.raises(CollectionConfigLoadError, match="Unknown catalogue voie"):
        canonicalize_catalogue_voie(unknown)


def test_v2_loader_returns_only_the_canonical_voie() -> None:
    config = {
        "collections": {
            "maths": {
                "matiere": "maths",
                "niveau": "terminale",
                "voie": "gen",
                "statut": "specialite",
                "instanciee": True,
            }
        }
    }

    definition = resolve_collection_v2("maths", config)

    assert definition["voie"] == "generale"


def test_student_gets_only_public_rights_without_inferred_enrolment() -> None:
    assert allowed_rights_for_role("student") == (
        Rights.officiel_public,
        Rights.public_allowed,
    )
    assert allowed_visibilities_for_role("student") == ("public",)


@pytest.mark.parametrize(
    ("role", "expected_rights", "expected_visibilities"),
    [
        (
            "teacher",
            (
                Rights.officiel_public,
                Rights.public_allowed,
                Rights.nexus_proprietaire,
                Rights.usage_interne,
                Rights.commercial_confidential,
            ),
            ("public", "internal"),
        ),
        (
            "reviewer",
            (
                Rights.officiel_public,
                Rights.public_allowed,
                Rights.nexus_proprietaire,
                Rights.usage_interne,
                Rights.commercial_confidential,
            ),
            ("public", "internal", "restricted"),
        ),
        (
            "ingest_agent",
            (
                Rights.officiel_public,
                Rights.public_allowed,
                Rights.nexus_proprietaire,
                Rights.usage_interne,
                Rights.commercial_confidential,
            ),
            ("internal", "restricted"),
        ),
        (
            "admin",
            (
                Rights.officiel_public,
                Rights.public_allowed,
                Rights.nexus_proprietaire,
                Rights.usage_interne,
                Rights.student_private,
                Rights.parent_private,
                Rights.commercial_confidential,
                Rights.restricted,
            ),
            ("public", "internal", "restricted", "private"),
        ),
    ],
)
def test_non_student_role_access_is_a_closed_mapping(
    role: str,
    expected_rights: tuple[Rights, ...],
    expected_visibilities: tuple[str, ...],
) -> None:
    assert allowed_rights_for_role(role) == expected_rights
    assert allowed_visibilities_for_role(role) == expected_visibilities


def test_server_scope_derives_every_filter_from_verified_identity_and_artifact() -> None:
    scope = build_server_retrieval_scope(
        VERIFIED,
        collection="rag_nexus_maths_terminale_gen_specialite",
        collection_config=ENGINE_CONFIG,
    )

    assert isinstance(scope, ServerRetrievalScope)
    assert scope.tenant == "libre_terminale"
    assert scope.niveau == "terminale"
    assert scope.voie == "generale"
    assert scope.matiere == "maths"
    assert scope.statut_enseignement == "specialite"
    assert scope.candidat == "individuel"
    assert scope.audiences == ("libre", "tous")
    assert scope.rights == (Rights.officiel_public, Rights.public_allowed)
    assert scope.visibilities == ("public",)
    assert scope.school_year == "2026-2027"
    assert scope.collection == "rag_nexus_maths_terminale_gen_specialite"
    assert scope.programme_version == "BOEN_special_8_2019-07-25"
    assert scope.review_status == "reviewed"
    assert scope.scope_digest == ARTIFACT.sha256_digest()
    assert scope.source_sha256 == ARTIFACT.source_sha256
    assert len(scope.filter_digest) == 64
    assert IDENTITY.sub not in repr(scope)
    assert IDENTITY.jti not in repr(scope)

    with pytest.raises(FrozenInstanceError):
        scope.collection = "rag_nexus_nsi_terminale_specialite"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("collection", "expected_matiere"),
    [
        ("rag_nexus_maths_terminale_gen_specialite", "maths"),
        ("rag_nexus_nsi_terminale_specialite", "nsi"),
    ],
)
def test_each_authorized_subject_derives_its_programme_scope(
    collection: str,
    expected_matiere: str,
) -> None:
    scope = build_server_retrieval_scope(
        VERIFIED,
        collection=collection,
        collection_config=ENGINE_CONFIG,
    )

    assert scope.matiere == expected_matiere
    assert scope.programme_version == "BOEN_special_8_2019-07-25"


def test_readiness_scope_validates_a_declared_dormant_collection_without_opening_it() -> None:
    config = deepcopy(ENGINE_CONFIG)
    config["collections"]["rag_nexus_maths_terminale_gen_specialite"][
        "instanciee"
    ] = False

    readiness_scope = build_server_readiness_scope(
        VERIFIED,
        collection="rag_nexus_maths_terminale_gen_specialite",
        collection_config=config,
    )

    assert readiness_scope.collection == "rag_nexus_maths_terminale_gen_specialite"
    assert readiness_scope.matiere == "maths"
    with pytest.raises(RetrievalScopeError, match="retrieval scope forbidden"):
        build_server_retrieval_scope(
            VERIFIED,
            collection="rag_nexus_maths_terminale_gen_specialite",
            collection_config=config,
        )


@pytest.mark.parametrize(
    ("dimension", "divergent_value"),
    [
        ("niveau", "premiere"),
        ("voie", "stmg"),
        ("matiere", "nsi"),
        ("statut", "tronc_commun"),
    ],
)
def test_readiness_scope_still_rejects_every_signed_dimension_mismatch(
    dimension: str,
    divergent_value: str,
) -> None:
    config = deepcopy(ENGINE_CONFIG)
    definition = config["collections"]["rag_nexus_maths_terminale_gen_specialite"]
    definition["instanciee"] = False
    definition[dimension] = divergent_value

    with pytest.raises(RetrievalScopeError, match="retrieval scope forbidden"):
        build_server_readiness_scope(
            VERIFIED,
            collection="rag_nexus_maths_terminale_gen_specialite",
            collection_config=config,
        )


def test_arbitrary_collection_is_rejected_before_catalogue_resolution() -> None:
    with pytest.raises(RetrievalScopeError, match="retrieval scope forbidden"):
        build_server_retrieval_scope(
            VERIFIED,
            collection="rag_nexus_nsi_premiere_specialite",
            collection_config={},
        )


@pytest.mark.parametrize(
    ("dimension", "divergent_value"),
    [
        ("niveau", "premiere"),
        ("voie", "stmg"),
        ("matiere", "nsi"),
        ("statut", "tronc_commun"),
    ],
)
def test_collection_dimension_mismatch_is_rejected(
    dimension: str,
    divergent_value: str,
) -> None:
    config = deepcopy(ENGINE_CONFIG)
    definition = config["collections"]["rag_nexus_maths_terminale_gen_specialite"]
    definition[dimension] = divergent_value

    with pytest.raises(RetrievalScopeError, match="retrieval scope forbidden"):
        build_server_retrieval_scope(
            VERIFIED,
            collection="rag_nexus_maths_terminale_gen_specialite",
            collection_config=config,
        )
