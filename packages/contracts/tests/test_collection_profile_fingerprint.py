"""Empreinte pure partagée d'un profil de collection."""

from __future__ import annotations

from nexus_contracts.ingestion import (
    CollectionProfile,
    collection_profile_fingerprint,
    profile_manifest_fingerprint,
)


def _profile() -> CollectionProfile:
    return CollectionProfile.model_validate(
        {
            "profile_version": "v1",
            "enabled": True,
            "scope": {
                "tenant": "libre_terminale",
                "collection": "collection_maths",
                "niveau": "terminale",
                "voie": "generale",
                "matiere": "mathematiques",
                "candidat": "libre",
                "audience": ["libre", "tous"],
                "visibility": "internal",
                "school_year": "2026-2027",
                "programme_version": "BOEN_test_v1",
            },
            "title": "Profil test",
            "owner": "tests",
            "expected_topics": ["algèbre"],
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


def test_collection_profile_fingerprint_is_deterministic_and_content_bound() -> None:
    profile = _profile()
    changed = profile.model_copy(update={"title": "Profil modifié"})

    assert collection_profile_fingerprint(profile) == collection_profile_fingerprint(
        profile
    )
    assert collection_profile_fingerprint(profile) != collection_profile_fingerprint(
        changed
    )
    assert len(collection_profile_fingerprint(profile)) == 64


def test_profile_manifest_fingerprint_is_order_independent() -> None:
    manifest = {
        "manifest_version": "1",
        "provenance": "test",
        "profiles": [{"collection": "maths", "fingerprint": "a" * 64}],
    }

    assert profile_manifest_fingerprint(manifest) == profile_manifest_fingerprint(
        dict(reversed(tuple(manifest.items())))
    )
