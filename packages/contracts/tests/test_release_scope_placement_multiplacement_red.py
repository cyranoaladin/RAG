"""RED, then GREEN: V1's `ReleaseScopePlacementV1`/producer assume a content
appears in at most one placement. The real, sealed R1 release
(production-profile-gate-2026-2027-v1) has 167 contents legitimately placed
in two collections each -- V1 cannot represent this at all. This file
proves the V1 failure (RED, captured before any V2 code exists) against
the real producer's internal composition function, minus the strict-YAML
profile-source-file layer (exercised separately, end-to-end, against the
real sealed release in the real-scale projection test).
"""
from __future__ import annotations

import pytest
from nexus_contracts.authorization_set import VerifiedProfileFactV1, release_placement_binding_key
from nexus_contracts.ingestion import (
    CollectionProfile,
    ResourceScope,
    collection_profile_fingerprint,
)
from nexus_contracts.release_scope_placement import (
    ReleaseScopePlacementProducerError,
    _compose_release_scope_placement,
    _compose_release_scope_placement_v2,
)

CONTENT_A = "a" * 64
RELEASE_ID = "test-release-multiplacement-v1"
MANIFEST_DIGEST = "f" * 64


def _scope(*, collection: str, niveau: str) -> ResourceScope:
    return ResourceScope.model_validate(
        {
            "tenant": "libre_" + niveau,
            "collection": collection,
            "niveau": niveau,
            "voie": "generale",
            "matiere": "hlp",
            "candidat": "libre",
            "audience": ["libre"],
            "visibility": "public",
            "school_year": "2026-2027",
            "programme_version": "2026",
        }
    )


def _profile(*, collection: str, niveau: str) -> CollectionProfile:
    return CollectionProfile.model_validate(
        {
            "profile_version": "v1",
            "enabled": True,
            "scope": _scope(collection=collection, niveau=niveau).model_dump(mode="json"),
            "title": f"{collection} — test",
            "owner": "test",
            "expected_topics": ["topic"],
            "expected_resource_types": ["programme_officiel"],
            "allowed_domains": ["eduscol.education.gouv.fr"],
            "source_authority": "official",
            "search_cadence": "manual",
            "max_queries_per_run": 1,
            "max_documents_per_run": 1,
            "max_chunk_size": 800,
            "chunk_overlap": 100,
            "min_source_confidence": 0.9,
            "min_scope_confidence": 0.9,
            "min_extraction_quality": 0.1,
        }
    )


def _fact(*, collection: str, niveau: str) -> VerifiedProfileFactV1:
    return VerifiedProfileFactV1.model_validate(
        {
            "profile_id": collection,
            "profile_version": "v1",
            "profile_fingerprint": collection_profile_fingerprint(
                _profile(collection=collection, niveau=niveau)
            ),
            "scope": _scope(collection=collection, niveau=niveau).model_dump(mode="json"),
        }
    )


_PROFILES_BY_PATH = {
    "configs/hlp_premiere.yml": _profile(collection="hlp_premiere", niveau="premiere"),
    "configs/hlp_terminale.yml": _profile(collection="hlp_terminale", niveau="terminale"),
}


def _matrix_partition(*, collection: str, niveau: str, evidence_path: str) -> dict:
    scope = _scope(collection=collection, niveau=niveau)
    dims = scope.model_dump(mode="json")
    return {
        "partition_id": f"{collection}-v1",
        "partition_kind": "EXACT_VERSIONED_RELEASE_PROFILE",
        "content_count": 1,
        "content_sha256": [CONTENT_A],
        "profile_decision_required": False,
        "evidence_sources": [evidence_path],
        "dimensions": {
            field: {"grounded": True, "source_of_truth": evidence_path, "value": value}
            for field, value in dims.items()
        },
    }


def _base_kwargs(*, accepted_placements: list[dict]) -> dict:
    return dict(
        accepted_placements=accepted_placements,
        release_registry={
            "school_year": "2026-2027",
            "releases": [
                {
                    "release_id": RELEASE_ID,
                    "collections": ["hlp_premiere", "hlp_terminale"],
                }
            ],
        },
        verified_profiles=[
            _fact(collection="hlp_premiere", niveau="premiere"),
            _fact(collection="hlp_terminale", niveau="terminale"),
        ],
        profile_manifest_digest=MANIFEST_DIGEST,
        expected_content_sha256=[CONTENT_A],
        profile_source_loader=lambda path: _PROFILES_BY_PATH[path],
        evidence_blob_loader=lambda path: b"evidence",
        profile_source_path_by_identity={
            ("hlp_premiere", "v1"): "configs/hlp_premiere.yml",
            ("hlp_terminale", "v1"): "configs/hlp_terminale.yml",
        },
    )


def test_v1_producer_fails_closed_on_a_legitimately_multiplaced_content() -> None:
    """RED, captured against the real V1 producer before any V2 code exists.

    One physical content (CONTENT_A) accepted into TWO legitimate release
    placements -- exactly the shape of all 167 real multi-placement
    contents in the sealed production-profile-gate-2026-2027-v1 release.
    V1's `identity_by_content` dict is keyed by content_sha256 alone and
    raises AMBIGUOUS_PLACEMENT the instant a second, different
    (release_id, collection, profile_version) identity is seen for the
    same content -- there is no way to express "one physical content, two
    legitimate release placements" in the V1 protocol at all.
    """
    accepted_placements = [
        {
            "content_sha256": CONTENT_A,
            "release_id": RELEASE_ID,
            "collection": "hlp_premiere",
            "profile_version": "v1",
        },
        {
            "content_sha256": CONTENT_A,
            "release_id": RELEASE_ID,
            "collection": "hlp_terminale",
            "profile_version": "v1",
        },
    ]
    # Only one matrix partition is needed: expected_content_sha256 lists
    # CONTENT_A once, and matrix coverage is checked against that set
    # (unique content), not against the number of placements.
    matrix = [
        _matrix_partition(
            collection="hlp_premiere", niveau="premiere", evidence_path="configs/hlp_premiere.yml"
        )
    ]

    with pytest.raises(ReleaseScopePlacementProducerError) as excinfo:
        _compose_release_scope_placement(
            profile_proposal_matrix=matrix,
            **_base_kwargs(accepted_placements=accepted_placements),
        )
    assert "AMBIGUOUS_PLACEMENT" in str(excinfo.value)


def test_v2_producer_represents_the_same_legitimately_multiplaced_content() -> None:
    """GREEN: the exact same accepted placements V1 refused (RED test
    above) are represented correctly by the V2 producer -- two entries,
    same content_sha256, two distinct scopes, no ambiguity."""
    accepted_placements = [
        {
            "content_sha256": CONTENT_A,
            "release_id": RELEASE_ID,
            "collection": "hlp_premiere",
            "profile_version": "v1",
        },
        {
            "content_sha256": CONTENT_A,
            "release_id": RELEASE_ID,
            "collection": "hlp_terminale",
            "profile_version": "v1",
        },
    ]
    matrix = [
        _matrix_partition(
            collection="hlp_premiere", niveau="premiere", evidence_path="configs/hlp_premiere.yml"
        ),
        _matrix_partition(
            collection="hlp_terminale", niveau="terminale", evidence_path="configs/hlp_terminale.yml"
        ),
    ]
    # Two contents needed in `expected_content_sha256` this time: the
    # matrix coverage check counts unique content_sha256 values, and both
    # partitions above declare CONTENT_A -- V2 must not double-count it as
    # "extra" simply because two partitions govern two of its placements.
    kwargs = _base_kwargs(accepted_placements=accepted_placements)
    kwargs["expected_content_sha256"] = [CONTENT_A]

    placement = _compose_release_scope_placement_v2(
        profile_proposal_matrix=matrix,
        **kwargs,
    )

    assert len(placement.placements) == 2
    assert {entry.content_sha256 for entry in placement.placements} == {CONTENT_A}
    bindings = {release_placement_binding_key(entry) for entry in placement.placements}
    assert len(bindings) == 2  # two distinct (content, scope) bindings, never merged
