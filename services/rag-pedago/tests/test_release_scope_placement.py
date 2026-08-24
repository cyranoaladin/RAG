"""Projection canonique indépendante contenu -> profil -> scope."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from nexus_contracts.authorization_set import (
    VerifiedProfileFactV1,
    parse_release_scope_placement,
)
from nexus_contracts.ingestion import (
    CollectionProfile,
    collection_profile_fingerprint,
)

from rag_pedago.governance.release_scope_placement import (
    ReleaseScopePlacementProducerError,
    _compose_release_scope_placement,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
MANIFEST_DIGEST = "d" * 64


def _scope(collection: str, *, niveau: str = "terminale") -> dict[str, Any]:
    return {
        "tenant": f"libre_{niveau}",
        "collection": collection,
        "niveau": niveau,
        "voie": "generale",
        "matiere": "mathematiques",
        "candidat": "libre",
        "audience": ["libre", "tous"],
        "visibility": "internal",
        "school_year": "2026-2027",
        "programme_version": "BOEN_test_v1",
    }


def _profile(
    collection: str, *, profile_version: str = "v1", niveau: str = "terminale"
) -> VerifiedProfileFactV1:
    profile = _collection_profile(collection, profile_version=profile_version, niveau=niveau)
    return VerifiedProfileFactV1(
        profile_id=collection,
        profile_version=profile.profile_version,
        profile_fingerprint=collection_profile_fingerprint(profile),
        scope=profile.scope,
    )


def _collection_profile(
    collection: str, *, profile_version: str = "v1", niveau: str = "terminale"
) -> CollectionProfile:
    return CollectionProfile.model_validate(
        {
            "profile_version": profile_version,
            "enabled": True,
            "scope": _scope(collection, niveau=niveau),
            "title": f"Profil {collection}",
            "owner": "tests",
            "expected_topics": ["notion"],
            "expected_resource_types": ["cours"],
            "allowed_domains": ["education.gouv.fr"],
            "source_authority": "official",
            "search_cadence": "weekly",
            "max_queries_per_run": 1,
            "max_documents_per_run": 1,
            "max_chunk_size": 800,
            "chunk_overlap": 100,
            "min_source_confidence": 0.7,
            "min_scope_confidence": 0.7,
            "min_extraction_quality": 0.7,
        }
    )


def _registry() -> dict[str, Any]:
    return {
        "registry_version": "1",
        "school_year": "2026-2027",
        "releases": [
            {
                "release_id": "release-a",
                "collections": ["collection_maths", "collection_francais"],
                "manifest_path": "release.json",
                "expected_manifest_sha256": "e" * 64,
                "release_kind": "TEST",
            }
        ],
    }


def _placements() -> list[dict[str, str]]:
    return [
        {
            "content_sha256": SHA_B,
            "release_id": "release-a",
            "collection": "collection_francais",
            "profile_version": "v1",
        },
        {
            "content_sha256": SHA_A,
            "release_id": "release-a",
            "collection": "collection_maths",
            "profile_version": "v1",
        },
    ]


def _profiles() -> tuple[VerifiedProfileFactV1, ...]:
    return (_profile("collection_maths"), _profile("collection_francais"))


def _decision_matrix(
    *contents: tuple[str, VerifiedProfileFactV1],
) -> list[dict[str, Any]]:
    selected = contents or (
        (SHA_A, _profile("collection_maths")),
        (SHA_B, _profile("collection_francais")),
    )
    rows: list[dict[str, Any]] = []
    for index, (content_sha256, profile) in enumerate(selected, start=1):
        scope = profile.scope.model_dump(mode="json")
        source_path = f"profiles/{profile.profile_id}.yml"
        rows.append(
            {
                "partition_id": f"P{index:02d}",
                "partition_kind": "EXACT_VERSIONED_RELEASE_PROFILE",
                "content_count": 1,
                "content_sha256": [content_sha256],
                "profile_decision_required": False,
                "evidence_sources": [source_path],
                "dimensions": {
                    name: {
                        "value": value,
                        "source_of_truth": source_path,
                        "grounded": True,
                    }
                    for name, value in scope.items()
                },
            }
        )
    return rows


def _compose(**kwargs: Any):
    def load_source(path: str) -> CollectionProfile:
        collection = Path(path).stem
        return _collection_profile(collection)

    source_paths = {
        (fact.profile_id, fact.profile_version): f"profiles/{fact.profile_id}.yml"
        for fact in _profiles()
    }
    return _compose_release_scope_placement(
        **kwargs,
        profile_source_loader=load_source,
        evidence_blob_loader=lambda _path: b"fixture",
        profile_source_path_by_identity=source_paths,
    )


def test_producer_emits_canonical_artifact_keyed_by_sorted_content_sha() -> None:
    placement = _compose(
        accepted_placements=_placements(),
        release_registry=_registry(),
        verified_profiles=_profiles(),
        profile_proposal_matrix=_decision_matrix(),
        profile_manifest_digest=MANIFEST_DIGEST,
        expected_content_sha256=(SHA_A, SHA_B),
    )

    assert [row.content_sha256 for row in placement.placements] == [SHA_A, SHA_B]
    assert [row.profile_id for row in placement.placements] == [
        "collection_maths",
        "collection_francais",
    ]
    assert parse_release_scope_placement(placement.canonical_bytes()) == placement


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda rows: [*rows, {**rows[0], "collection": "collection_maths"}],
            "AMBIGUOUS_PLACEMENT",
        ),
        (
            lambda rows: [*rows, dict(rows[0])],
            "DUPLICATE_CONTENT",
        ),
    ],
)
def test_producer_refuses_multiple_placements_for_one_content(mutate: Any, message: str) -> None:
    with pytest.raises(ReleaseScopePlacementProducerError, match=message):
        _compose(
            accepted_placements=mutate(_placements()),
            release_registry=_registry(),
            verified_profiles=_profiles(),
            profile_proposal_matrix=_decision_matrix(),
            profile_manifest_digest=MANIFEST_DIGEST,
            expected_content_sha256=(SHA_A, SHA_B),
        )


def test_producer_refuses_unknown_profile() -> None:
    with pytest.raises(ReleaseScopePlacementProducerError, match="UNKNOWN_PROFILE"):
        _compose(
            accepted_placements=_placements(),
            release_registry=_registry(),
            verified_profiles=(_profile("collection_maths"),),
            profile_proposal_matrix=_decision_matrix(),
            profile_manifest_digest=MANIFEST_DIGEST,
            expected_content_sha256=(SHA_A, SHA_B),
        )


def test_producer_refuses_unrepresentable_profile_scope() -> None:
    malformed = _profile("collection_maths").model_dump(mode="json")
    malformed["scope"]["niveau"] = "multi-niveaux"
    with pytest.raises(ReleaseScopePlacementProducerError, match="UNREPRESENTABLE_SCOPE"):
        _compose(
            accepted_placements=_placements(),
            release_registry=_registry(),
            verified_profiles=(malformed, _profile("collection_francais")),
            profile_proposal_matrix=_decision_matrix(),
            profile_manifest_digest=MANIFEST_DIGEST,
            expected_content_sha256=(SHA_A, SHA_B),
        )


def test_producer_refuses_missing_expected_content() -> None:
    with pytest.raises(ReleaseScopePlacementProducerError, match="MISSING_CONTENT"):
        _compose(
            accepted_placements=_placements()[:1],
            release_registry=_registry(),
            verified_profiles=_profiles(),
            profile_proposal_matrix=_decision_matrix(),
            profile_manifest_digest=MANIFEST_DIGEST,
            expected_content_sha256=(SHA_A, SHA_B),
        )


def test_producer_refuses_content_outside_expected_set() -> None:
    with pytest.raises(ReleaseScopePlacementProducerError, match="EXTRA_CONTENT"):
        _compose(
            accepted_placements=_placements(),
            release_registry=_registry(),
            verified_profiles=_profiles(),
            profile_proposal_matrix=_decision_matrix((SHA_A, _profile("collection_maths"))),
            profile_manifest_digest=MANIFEST_DIGEST,
            expected_content_sha256=(SHA_A,),
        )


def test_producer_refuses_collection_not_accepted_by_named_release() -> None:
    rows = _placements()
    rows[0]["release_id"] = "unknown-release"
    with pytest.raises(ReleaseScopePlacementProducerError, match="UNKNOWN_RELEASE"):
        _compose(
            accepted_placements=rows,
            release_registry=_registry(),
            verified_profiles=_profiles(),
            profile_proposal_matrix=_decision_matrix(),
            profile_manifest_digest=MANIFEST_DIGEST,
            expected_content_sha256=(SHA_A, SHA_B),
        )


def test_proposal_matrix_cannot_hide_an_ungrounded_dimension() -> None:
    matrix = _decision_matrix()
    matrix[0]["dimensions"]["niveau"]["grounded"] = False

    with pytest.raises(ReleaseScopePlacementProducerError, match="PROFILE_DECISION_REQUIRED"):
        _compose(
            accepted_placements=_placements(),
            release_registry=_registry(),
            verified_profiles=_profiles(),
            profile_proposal_matrix=matrix,
            profile_manifest_digest=MANIFEST_DIGEST,
            expected_content_sha256=(SHA_A, SHA_B),
        )


def test_direct_producer_requires_the_profile_decision_matrix() -> None:
    with pytest.raises(TypeError, match="profile_proposal_matrix"):
        _compose(
            accepted_placements=_placements(),
            release_registry=_registry(),
            verified_profiles=_profiles(),
            profile_manifest_digest=MANIFEST_DIGEST,
            expected_content_sha256=(SHA_A, SHA_B),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("content", "MATRIX_CONTENT_MISMATCH"),
        ("duplicate", "MATRIX_DUPLICATE_CONTENT"),
        ("scope", "MATRIX_SCOPE_MISMATCH"),
        ("profile", "MATRIX_PROFILE_MISMATCH"),
        ("release", "MATRIX_RELEASE_MISMATCH"),
    ],
)
def test_falsely_resolved_matrix_cannot_disagree_with_release_facts(
    mutation: str, message: str
) -> None:
    matrix = _decision_matrix()
    expected = (SHA_A, SHA_B)
    if mutation == "content":
        matrix[0]["content_sha256"] = ["c" * 64]
    elif mutation == "duplicate":
        matrix[1]["content_sha256"] = [SHA_A]
    elif mutation == "scope":
        matrix[0]["dimensions"]["matiere"]["value"] = "physique_chimie"
    elif mutation == "profile":
        matrix[0]["dimensions"]["collection"]["value"] = "collection_francais"
    else:
        matrix[0]["dimensions"]["school_year"]["value"] = "2025-2026"

    with pytest.raises(ReleaseScopePlacementProducerError, match=message):
        _compose(
            accepted_placements=_placements(),
            release_registry=_registry(),
            verified_profiles=_profiles(),
            profile_proposal_matrix=matrix,
            profile_manifest_digest=MANIFEST_DIGEST,
            expected_content_sha256=expected,
        )


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        (None, "INVALID_PARTITION_KIND"),
        ("ARBITRARY_KIND", "INVALID_PARTITION_KIND"),
        ("PLACEMENT_ONLY_UNRESOLVED", "PROFILE_DECISION_REQUIRED"),
    ],
)
def test_partition_kind_is_canonical_and_fail_closed(kind: str | None, message: str) -> None:
    matrix = _decision_matrix()
    if kind is None:
        matrix[0].pop("partition_kind")
    else:
        matrix[0]["partition_kind"] = kind

    with pytest.raises(ReleaseScopePlacementProducerError, match=message):
        _compose(
            accepted_placements=_placements(),
            release_registry=_registry(),
            verified_profiles=_profiles(),
            profile_proposal_matrix=matrix,
            profile_manifest_digest=MANIFEST_DIGEST,
            expected_content_sha256=(SHA_A, SHA_B),
        )
