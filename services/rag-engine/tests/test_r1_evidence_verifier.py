"""R1 evidence verifier -- adversarial proof suite.

Never touches PostgreSQL: the sealed-release fixture, the profile-authority
fixture, and the bootstrap fixture are all plain files built in
``tmp_path``. The sealed-release fixture reuses the same
MULTILEVEL_SUBJECT_RELEASE_V1 / MULTILEVEL_AGGREGATE_RELEASE_V1 shape already
proven in ``test_release_readiness.py`` (a WAVE0-shaped subject with its
``release_kind`` overridden, exactly as that suite's own
``test_multilevel_aggregate_uses_its_extended_authority_contract`` does) --
this test module does not invent a second release-file schema. The profile-
authority fixture reuses the real ``CollectionProfile`` contract and the
real ``profile_fingerprint``/``manifest_fingerprint`` functions -- it does
not invent a second fingerprint scheme either.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
import yaml
from nexus_contracts import seal_resource_registry_bootstrap
from nexus_contracts.ingestion import CollectionProfile
from nexus_contracts.resource_registry_bootstrap import ResourceRegistryBootstrapPayload

from ingestor.ingestion_profiles.manifest import manifest_fingerprint
from ingestor.ingestion_profiles.registry import profile_fingerprint as compute_profile_fingerprint
from ingestor.r1_evidence_verifier import R1EvidenceVerifierError, verify_r1_evidence
from ingestor.resource_registry_bootstrap import build_resource_registry_bootstrap_inventory

ARTIFACT_SHA = "a" * 64
PLACEMENT_ID = "b" * 64
CHUNK_ID = "c" * 64
CHUNK_SHA = "d" * 64
COLLECTION = "rag_nexus_r1a_fixture_specialite"
MODEL_ID = "intfloat/multilingual-e5-large"
RESOURCE_ID = UUID("11111111-1111-4111-8111-111111111111")
VERSION_ID = UUID("22222222-2222-4222-8222-222222222222")
RUN_ID = UUID("33333333-3333-4333-8333-333333333333")
GENERATED_AT = datetime(2026, 8, 30, 12, tzinfo=UTC)
SOURCE_URI = "https://eduscol.education.fr/programme.pdf"
DEFAULT_AUDIENCE = ("libre", "aefe")
PROFILE_VERSION = "1.0.0"


def _write_json(path: Path, payload: object) -> str:
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _multilevel_authorities() -> dict[str, str]:
    names = (
        "corpus_manifest_sha256",
        "parent_sealed_catalog_sha256",
        "placement_catalog_sha256",
        "catalog_delta_sha256",
        "effective_catalog_authority_sha256",
        "candidate_inventory_sha256",
        "currentness_evidence_sha256",
        "pii_evidence_sha256",
        "pii_policy_sha256",
        "pii_scanner_sha256",
        "rights_registry_sha256",
        "preflight_evidence_sha256",
        "programme_registry_sha256",
        "profile_manifest_sha256",
        "level_mapping_sha256",
        "subject_mapping_sha256",
        "document_type_mapping_sha256",
        "embedding_inventory_sha256",
        "reranker_inventory_sha256",
    )
    return {name: hashlib.sha256(name.encode("utf-8")).hexdigest() for name in names}


# ---------------------------------------------------------------------------
# Profile authority fixture -- the real CollectionProfile contract and the
# real profile_fingerprint()/manifest_fingerprint() functions, never a
# hand-rolled fingerprint scheme.
# ---------------------------------------------------------------------------


def _profile_dict(
    *,
    collection: str,
    profile_version: str = PROFILE_VERSION,
    audience: tuple[str, ...] = DEFAULT_AUDIENCE,
    candidat: str = "scolarise",
    matiere: str = "r1a",
) -> dict[str, object]:
    return {
        "profile_version": profile_version,
        "enabled": True,
        "scope": {
            "tenant": "nexus",
            "collection": collection,
            "niveau": "terminale",
            "voie": "generale",
            "matiere": matiere,
            "candidat": candidat,
            "audience": list(audience),
            "visibility": "internal",
            "school_year": "2026-2027",
            "programme_version": "fixture-2026",
        },
        "title": f"Fixture profile {collection}",
        "language": "fr",
        "owner": "Fixture Owner",
        "expected_topics": ["fixture topic"],
        "expected_resource_types": ["ressource_officielle"],
        "allowed_domains": ["eduscol.education.fr"],
        "source_authority": "official",
        "search_cadence": "manual",
        "max_queries_per_run": 1,
        "max_documents_per_run": 1,
        "max_chunk_size": 800,
        "chunk_overlap": 100,
        "min_source_confidence": 0.9,
        "min_scope_confidence": 0.9,
        "min_extraction_quality": 0.1,
        "reject_unknown_rights": True,
        "reject_ambiguous_routing": True,
    }


def _write_profile_authority(
    tmp_path: Path,
    *,
    collections: tuple[str, ...] = (COLLECTION,),
    audience: tuple[str, ...] = DEFAULT_AUDIENCE,
    candidat: str = "scolarise",
    matiere: str = "r1a",
    profile_version: str = PROFILE_VERSION,
) -> tuple[Path, Path, str, dict[str, str]]:
    """Writes real, pydantic-validated CollectionProfile YAML files plus the
    signed manifest that seals them. Returns
    ``(profile_root, manifest_path, manifest_fingerprint, fingerprint_by_collection)``."""
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    fp_by_collection: dict[str, str] = {}
    manifest_profiles: list[dict[str, object]] = []
    for collection in collections:
        data = _profile_dict(
            collection=collection,
            profile_version=profile_version,
            audience=audience,
            candidat=candidat,
            matiere=matiere,
        )
        profile = CollectionProfile.model_validate(data)
        fp = compute_profile_fingerprint(profile)
        fp_by_collection[collection] = fp
        (profiles_dir / f"{collection}.yml").write_text(
            yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
        )
        manifest_profiles.append(
            {
                "collection": collection,
                "profile_version": profile_version,
                "fingerprint": fp,
                "approved_by": "fixture",
                "approved_at": "2026-08-30T00:00:00+00:00",
            }
        )
    manifest_data: dict[str, object] = {
        "manifest_version": "1",
        "provenance": "fixture",
        "generated_at": "2026-08-30T00:00:00+00:00",
        "profiles": manifest_profiles,
    }
    manifest_fp = manifest_fingerprint(manifest_data)
    manifest_path = tmp_path / "manifest.yml"
    manifest_path.write_text(yaml.safe_dump(manifest_data, sort_keys=False), encoding="utf-8")
    return profiles_dir, manifest_path, manifest_fp, fp_by_collection


# ---------------------------------------------------------------------------
# Sealed-release fixture (unchanged shape from R1A, now parameterized on the
# real profile fingerprint/manifest digest instead of a placeholder).
# ---------------------------------------------------------------------------


def _placement_payload(
    *, collection: str = COLLECTION, candidat: str = "scolarise", placement_id: str = PLACEMENT_ID
) -> dict[str, object]:
    """Sealed-RELEASE placement shape (no ``audience``/``source_uri``: the
    real committed release files structurally lack them -- ``audience`` is
    instead carried transitively via the sealed profile authority, see
    ``_write_profile_authority`` and the module docstring on
    ``r1_evidence_verifier``; carries ``source_placement_id``/``source_scope``
    instead, which the bootstrap/DB shape does not)."""
    return {
        "placement_id": placement_id,
        "source_placement_id": "catalog-placement-r1a",
        "source_scope": "lycee/general/r1a-fixture",
        "collection": collection,
        "tenant": "nexus",
        "niveau": "terminale",
        "voie": "generale",
        "matiere": "r1a",
        "statut_enseignement": "specialite",
        "candidat": candidat,
        "visibility": "internal",
        "school_year": "2026-2027",
        "programme_version": "fixture-2026",
        "currentness": "current",
        "placement_status": "active",
        "review_status": "reviewed",
    }


def _bootstrap_placement_payload(
    *,
    collection: str = COLLECTION,
    candidat: str = "scolarise",
    placement_id: str = PLACEMENT_ID,
    audience: tuple[str, ...] = DEFAULT_AUDIENCE,
) -> dict[str, object]:
    """Bootstrap/DB placement shape (``_PlacementRow``): carries
    ``audience``/``source_uri``, never ``source_placement_id``/``source_scope``."""
    return {
        "placement_id": placement_id,
        "collection": collection,
        "tenant": "nexus",
        "niveau": "terminale",
        "voie": "generale",
        "matiere": "r1a",
        "statut_enseignement": "specialite",
        "candidat": candidat,
        "audience": list(audience),
        "visibility": "internal",
        "school_year": "2026-2027",
        "programme_version": "fixture-2026",
        "currentness": "current",
        "placement_status": "active",
        "review_status": "reviewed",
        "source_uri": SOURCE_URI,
    }


def _sealed_release(
    tmp_path: Path,
    *,
    collection: str = COLLECTION,
    profile_fingerprint: str,
    profile_manifest_fp: str,
    candidat: str = "scolarise",
) -> tuple[Path, str]:
    """A MULTILEVEL_AGGREGATE_RELEASE_V1 + one subject file it SHA256-pins,
    wrapped in a release-registry.json -- exactly what
    ``load_release_registry_file`` (reused unmodified) already parses."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    authorities = _multilevel_authorities()
    authorities["profile_manifest_sha256"] = profile_manifest_fp
    subject = {
        "release_kind": "MULTILEVEL_SUBJECT_RELEASE_V1",
        "release_id": f"r1a-fixture-2026-2027-{collection}",
        "school_year": "2026-2027",
        "collection": collection,
        "programme_version": "fixture-2026",
        "authorities": authorities,
        "profile": {
            "version": PROFILE_VERSION,
            "fingerprint": profile_fingerprint,
            "manifest_digest": profile_manifest_fp,
        },
        "models": {
            "embedding": {"model_id": MODEL_ID, "inventory_sha256": "1" * 64, "dimension": 1024},
            "reranker": {
                "model_id": "cross-encoder/ms-marco-MiniLM-L-6-v2",
                "inventory_sha256": "2" * 64,
            },
        },
        "expected_counts": {"artifacts": 1, "placements": 1, "chunks": 1},
        "artifacts": [
            {
                "content_sha256": ARTIFACT_SHA,
                "source_path": "01_EDUSCOL_OFFICIEL/LYCEE/R1A/a.pdf",
                "source_url": SOURCE_URI,
                "title": "Fixture R1A",
                "type_doc": "ressource_officielle",
                "page_count": 1,
                "placement_id_set_digest": hashlib.sha256(
                    json.dumps([PLACEMENT_ID]).encode()
                ).hexdigest(),
                "chunk_id_set_digest": hashlib.sha256(
                    json.dumps([CHUNK_ID]).encode()
                ).hexdigest(),
                "chunk_sha256_set_digest": hashlib.sha256(
                    json.dumps([CHUNK_SHA]).encode()
                ).hexdigest(),
                "page_coverage_digest": hashlib.sha256(json.dumps([1]).encode()).hexdigest(),
                "placements": [_placement_payload(collection=collection, candidat=candidat)],
                "chunks": [
                    {
                        "chunk_id": CHUNK_ID,
                        "chunk_index": 0,
                        "chunk_sha256": CHUNK_SHA,
                        "page_start": 1,
                        "page_end": 1,
                    }
                ],
            }
        ],
    }
    subject_path = tmp_path / f"{collection}.release.json"
    subject_sha = _write_json(subject_path, subject)

    aggregate = {
        "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V1",
        "release_id": "r1a-fixture-2026-2027",
        "school_year": "2026-2027",
        "authorities": authorities,
        "models": subject["models"],
        "expected_counts": {"artifacts": 1, "placements": 1, "chunks": 1},
        "subjects": [
            {"path": subject_path.name, "sha256": subject_sha, "collection": collection}
        ],
    }
    aggregate_path = tmp_path / "aggregate.release.json"
    aggregate_sha = _write_json(aggregate_path, aggregate)

    registry = {
        "registry_version": "1",
        "school_year": "2026-2027",
        "releases": [
            {
                "release_id": aggregate["release_id"],
                "release_kind": aggregate["release_kind"],
                "collections": [collection],
                "manifest_path": aggregate_path.name,
                "expected_manifest_sha256": aggregate_sha,
            }
        ],
    }
    registry_path = tmp_path / "release-registry.json"
    registry_sha = _write_json(registry_path, registry)
    return registry_path, registry_sha


def _default_fixture(
    tmp_path: Path,
    *,
    collection: str = COLLECTION,
    audience: tuple[str, ...] = DEFAULT_AUDIENCE,
    candidat: str = "scolarise",
) -> tuple[Path, str, Path, Path]:
    """Bundles a matched profile authority + sealed release into one call --
    the shape almost every test in this module needs.
    Returns ``(registry_path, registry_sha, profile_root, profile_manifest_path)``."""
    profile_root, manifest_path, manifest_fp, fp_by_collection = _write_profile_authority(
        tmp_path / "profiles", collections=(collection,), audience=audience, candidat=candidat
    )
    registry_path, registry_sha = _sealed_release(
        tmp_path / "release",
        collection=collection,
        profile_fingerprint=fp_by_collection[collection],
        profile_manifest_fp=manifest_fp,
        candidat=candidat,
    )
    return registry_path, registry_sha, profile_root, manifest_path


def _bootstrap_row(
    *,
    collection: str = COLLECTION,
    candidat: str = "scolarise",
    audience: tuple[str, ...] = DEFAULT_AUDIENCE,
    extra_placements: list[dict[str, object]] | None = None,
    resource_id: UUID = RESOURCE_ID,
    resource_version_id: UUID = VERSION_ID,
    content_sha256: str = ARTIFACT_SHA,
    placement_id: str = PLACEMENT_ID,
    chunk_id: str = CHUNK_ID,
) -> dict[str, object]:
    scope = {
        "tenant": "nexus",
        "collection": collection,
        "niveau": "terminale",
        "voie": "generale",
        "matiere": "r1a",
        "candidat": candidat,
        "audience": list(audience),
        "visibility": "internal",
        "school_year": "2026-2027",
        "programme_version": "fixture-2026",
    }
    artifact_payload = {
        "artifact_id": str(resource_version_id),
        "resource_id": str(resource_id),
        "run_id": str(RUN_ID),
        "scope": scope,
        "sha256": content_sha256,
        "size_bytes": 42,
        "mime_declared": "application/pdf",
        "mime_detected": "application/pdf",
        "original_url": SOURCE_URI,
        "final_url": SOURCE_URI,
        "collected_at": "2026-08-30T10:00:00Z",
        "domain": "eduscol.education.fr",
        "publisher": "Ministère de l'Éducation nationale",
        "title": "Fixture R1A",
        "license": "Licence Ouverte 2.0",
        "rights_status": "officiel_public",
        "pages_count": 1,
        "version": "2026",
        "extracted_text_ref": None,
    }
    placement = {
        "placement_id": placement_id,
        "collection": collection,
        "currentness": "current",
        "placement_status": "active",
        "review_status": "reviewed",
        "source_uri": SOURCE_URI,
        **scope,
        "statut_enseignement": "specialite",
    }
    return {
        "resource_id": resource_id,
        "resource_version_id": resource_version_id,
        "run_id": RUN_ID,
        "run_status": "succeeded",
        "resource_state": "RETRIEVAL_ELIGIBLE",
        **scope,
        "content_sha256": content_sha256,
        "size_bytes": 42,
        "mime_detected": "application/pdf",
        "artifact_payload": artifact_payload,
        "rag_artifact_id": content_sha256,
        "rag_content_sha256": content_sha256,
        "rag_source_label": "Fixture R1A",
        "rag_source_uri": SOURCE_URI,
        "rag_rights": "officiel_public",
        "rag_official": True,
        "rag_source_kind": "eduscol",
        "rag_type_doc": "programme_officiel",
        "attribution_resource_id": resource_id,
        "attribution_source_label": "Fixture R1A",
        "attribution_official": True,
        "attribution_source_kind": "eduscol",
        "attribution_type_doc": "programme_officiel",
        "placements": [placement, *(extra_placements or [])],
        "chunks": [
            {
                "chunk_id": chunk_id,
                "artifact_id": content_sha256,
                "doc_id": content_sha256,
                "chunk_sha256": CHUNK_SHA,
                "chunk_index": 0,
                "page_start": 1,
                "page_end": 1,
                "source_uri": SOURCE_URI,
                "rights": "officiel_public",
                "source_label": "Fixture R1A",
                "official": True,
                "source_kind": "eduscol",
                "type_doc": "programme_officiel",
                "review_status": "reviewed",
                **scope,
                "statut_enseignement": "specialite",
            }
        ],
    }


def _write_bootstrap(tmp_path: Path, rows: list[dict[str, object]], *, name: str) -> Path:
    inventory = build_resource_registry_bootstrap_inventory(
        rows,
        producer_repository="cyranoaladin/RAG",
        producer_commit="f" * 40,
        generated_at=GENERATED_AT,
        package_version="0.15.0",
    )
    path = tmp_path / name
    path.write_bytes(inventory.model_dump_json(indent=2).encode("utf-8") + b"\n")
    return path


def _write_bootstrap_raw(
    tmp_path: Path, *, extra_placement: dict[str, object], name: str
) -> Path:
    """Constructs a ``ResourceRegistryBootstrap`` directly at the pydantic
    contract layer, WITHOUT going through
    ``build_resource_registry_bootstrap_inventory``'s row-level
    ``_validate_placements`` -- deliberately, because that function's own
    same-collection conflict check (R1A's own fix) now refuses to BUILD a
    bootstrap containing the same conflict this test needs to hand the R1
    evidence VERIFIER. A bootstrap file handed to the verifier is not
    assumed to have been produced by this exact code path -- proving the
    verifier catches the conflict independently, as its own defense-in-depth
    layer, is the point of this helper."""
    bootstrap_placement_fields = (
        "tenant",
        "collection",
        "niveau",
        "voie",
        "matiere",
        "candidat",
        "audience",
        "visibility",
        "school_year",
        "programme_version",
        "statut_enseignement",
    )

    def _as_bootstrap_placement(raw: dict[str, object]) -> dict[str, object]:
        return {key: raw[key] for key in bootstrap_placement_fields}

    resource = {
        "resource_id": str(RESOURCE_ID),
        "resource_version_id": str(VERSION_ID),
        "content_sha256": ARTIFACT_SHA,
        "rag_artifact_id": ARTIFACT_SHA,
        "size_bytes": 42,
        "mime_type": "application/pdf",
        "source_label": "Fixture R1A",
        "source_uri": SOURCE_URI,
        "rights": "officiel_public",
        "official": True,
        "source_kind": "eduscol",
        "type_doc": "programme_officiel",
        "placements": [
            _as_bootstrap_placement(_bootstrap_placement_payload(collection=COLLECTION)),
            _as_bootstrap_placement(extra_placement),
        ],
        "chunks": [
            {
                "chunk_id": CHUNK_ID,
                "locator": {"chunk_index": 0, "page_start": 1, "page_end": 1},
            }
        ],
    }
    payload = ResourceRegistryBootstrapPayload.model_validate(
        {
            "protocol_version": "1",
            "producer_repository": "cyranoaladin/RAG",
            "producer_commit": "f" * 40,
            "package_version": "0.15.0",
            "source_snapshot_sha256": "0" * 64,
            "generated_at": GENERATED_AT.isoformat(),
            "resources": [resource],
        }
    )
    sealed = seal_resource_registry_bootstrap(payload)
    path = tmp_path / name
    path.write_bytes(sealed.model_dump_json(indent=2).encode("utf-8") + b"\n")
    return path


def _verify(
    bootstrap_path: Path, registry_path: Path, registry_sha: str, profile_root: Path, manifest_path: Path
):
    return verify_r1_evidence(
        bootstrap_path=bootstrap_path,
        release_registry_path=registry_path,
        release_registry_sha256=registry_sha,
        profile_root=profile_root,
        profile_manifest_path=manifest_path,
    )


# ---------------------------------------------------------------------------
# R1A cases, carried forward with the profile authority now wired in.
# ---------------------------------------------------------------------------


def test_exact_release_passes(tmp_path: Path) -> None:
    registry_path, registry_sha, profile_root, manifest_path = _default_fixture(tmp_path)
    bootstrap_path = _write_bootstrap(tmp_path, [_bootstrap_row()], name="bootstrap.json")

    report = _verify(bootstrap_path, registry_path, registry_sha, profile_root, manifest_path)

    assert report.ready is True, report.blockers
    assert report.gates["EXPORTED_PLACEMENT_SET_MINUS_SEALED_PLACEMENT_SET_COUNT"] == 0
    assert report.gates["SEALED_PLACEMENT_SET_MINUS_EXPORTED_PLACEMENT_SET_COUNT"] == 0
    assert report.gates["BOOTSTRAP_RESOURCE_ROWS"] == 1
    assert report.gates["R1_PROFILE_MANIFEST_AUTHORITY"] == "PASS"
    assert report.gates["R1_PROFILE_RELEASE_SCOPE_CONSISTENCY"] == "PASS"
    assert report.gates["AUDIENCE_COMPARED_AGAINST_SEALED_AUTHORITY"] is True
    assert report.gates["R1_CANONICAL_PLACEMENT_DIMENSIONS"] == 11
    assert report.gates["EXPORTED_CHUNK_SET_MINUS_SEALED_CHUNK_SET"] == 0
    assert report.gates["SEALED_CHUNK_SET_MINUS_EXPORTED_CHUNK_SET"] == 0
    assert report.gates["OUT_OF_RELEASE_CHUNKS"] == 0
    assert report.gates["R1_BOOTSTRAP_CHUNK_IDENTITY_BINDING"] == "PASS"
    assert report.gates["R1_CHUNK_RELEASE_BINDING"] == "PASS"
    assert report.gates["R1_CANONICAL_CHUNK_DIMENSIONS"] == [
        "content_sha256",
        "chunk_id",
        "chunk_index",
        "page_start",
        "page_end",
    ]


# ---------------------------------------------------------------------------
# R1G -- exact chunk-release binding, independently re-derived by the
# verifier from the bootstrap file alone (no DB access), against the same
# sealed ``ExpectedArtifact.chunks`` authority the exporter itself compares
# DB rows to. The R1 pré-GO forensic reproduced acceptance of an extra and a
# same-count swapped chunk against the pre-R1G verifier -- these are the
# static-file-level proof that the fix actually changed ``ready``/blockers,
# not merely computed unused gate values (the exact defect: BOOTSTRAP_CHUNKS
# and DISTINCT_CHUNK_IDS were already in ``gates`` before R1G, but no
# ``blockers.append`` call ever consulted them).
# ---------------------------------------------------------------------------


def test_extra_bootstrap_chunk_not_in_sealed_release_fails(tmp_path: Path) -> None:
    registry_path, registry_sha, profile_root, manifest_path = _default_fixture(tmp_path)
    row = _bootstrap_row()
    row["chunks"] = [
        *row["chunks"],
        {**row["chunks"][0], "chunk_id": "9" * 64, "chunk_index": 1, "page_start": 2, "page_end": 2},
    ]
    bootstrap_path = _write_bootstrap(tmp_path, [row], name="bootstrap.json")

    report = _verify(bootstrap_path, registry_path, registry_sha, profile_root, manifest_path)

    assert report.ready is False
    assert report.gates["EXPORTED_CHUNK_SET_MINUS_SEALED_CHUNK_SET"] == 1
    assert report.gates["SEALED_CHUNK_SET_MINUS_EXPORTED_CHUNK_SET"] == 0
    assert report.gates["R1_CHUNK_RELEASE_BINDING"] == "FAIL"
    assert any(
        blocker.startswith("EXPORTED_CHUNK_SET_MINUS_SEALED_CHUNK_SET=")
        for blocker in report.blockers
    )


def test_same_count_swapped_chunk_locator_fails(tmp_path: Path) -> None:
    """|expected chunks| == |actual chunks| == 1, but the bootstrap's own
    chunk asserts a different ``chunk_index`` than the sealed release
    declares for that exact ``chunk_id`` -- a set-membership defect a bare
    count comparison cannot see."""
    registry_path, registry_sha, profile_root, manifest_path = _default_fixture(tmp_path)
    row = _bootstrap_row()
    row["chunks"][0]["chunk_index"] = 1
    bootstrap_path = _write_bootstrap(tmp_path, [row], name="bootstrap.json")

    report = _verify(bootstrap_path, registry_path, registry_sha, profile_root, manifest_path)

    assert report.gates["EXPECTED_CHUNK_TUPLES"] == report.gates["ACTUAL_CHUNK_TUPLES"] == 1
    assert report.ready is False
    assert report.gates["EXPORTED_CHUNK_SET_MINUS_SEALED_CHUNK_SET"] == 1
    assert report.gates["SEALED_CHUNK_SET_MINUS_EXPORTED_CHUNK_SET"] == 1
    assert report.gates["R1_BOOTSTRAP_CHUNK_IDENTITY_BINDING"] == "FAIL"


def test_missing_sealed_placement_fails(tmp_path: Path) -> None:
    """The sealed release promotes the fixture placement; the bootstrap
    exported nothing for it at all (simulated by pointing the verifier at a
    bootstrap built from a DIFFERENT, unrelated resource)."""
    registry_path, registry_sha, profile_root, manifest_path = _default_fixture(tmp_path)
    other_row = _bootstrap_row(
        collection="rag_nexus_other_unrelated_specialite",
        resource_id=UUID("44444444-4444-4444-8444-444444444444"),
        resource_version_id=UUID("55555555-5555-4555-8555-555555555555"),
        content_sha256="9" * 64,
        placement_id="8" * 64,
        chunk_id="e" * 64,
    )
    bootstrap_path = _write_bootstrap(tmp_path, [other_row], name="bootstrap.json")

    report = _verify(bootstrap_path, registry_path, registry_sha, profile_root, manifest_path)

    assert report.ready is False
    assert report.gates["SEALED_PLACEMENT_SET_MINUS_EXPORTED_PLACEMENT_SET_COUNT"] == 1
    assert COLLECTION in report.gates["SEALED_COLLECTIONS_MINUS_EXPORTED_COLLECTIONS"]


def test_extra_different_collection_placement_fails(tmp_path: Path) -> None:
    registry_path, registry_sha, profile_root, manifest_path = _default_fixture(tmp_path)
    row = _bootstrap_row(
        extra_placements=[
            _bootstrap_placement_payload(
                collection="rag_nexus_unpromoted_specialite", placement_id="4" * 64
            )
        ]
    )
    bootstrap_path = _write_bootstrap(tmp_path, [row], name="bootstrap.json")

    report = _verify(bootstrap_path, registry_path, registry_sha, profile_root, manifest_path)

    assert report.ready is False
    assert report.gates["EXPORTED_PLACEMENT_SET_MINUS_SEALED_PLACEMENT_SET_COUNT"] >= 1
    assert "rag_nexus_unpromoted_specialite" in report.gates[
        "EXPORTED_COLLECTIONS_MINUS_SEALED_COLLECTIONS"
    ]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [("candidat", "libre"), ("visibility", "public"), ("matiere", "other_matiere")],
)
def test_extra_same_collection_placement_with_different_dimension_fails(
    tmp_path: Path, field_name: str, value: str
) -> None:
    registry_path, registry_sha, profile_root, manifest_path = _default_fixture(tmp_path)
    conflicting = _bootstrap_placement_payload(collection=COLLECTION, placement_id="7" * 64)
    conflicting[field_name] = value
    bootstrap_path = _write_bootstrap_raw(
        tmp_path, extra_placement=conflicting, name="bootstrap.json"
    )

    report = _verify(bootstrap_path, registry_path, registry_sha, profile_root, manifest_path)

    assert report.ready is False
    assert report.collisions["CONFLICTING_SAME_COLLECTION_PLACEMENT_COUNT"] >= 1


def test_extra_same_collection_placement_with_different_audience_fails(tmp_path: Path) -> None:
    registry_path, registry_sha, profile_root, manifest_path = _default_fixture(tmp_path)

    same_audience = _bootstrap_placement_payload(collection=COLLECTION, placement_id="6" * 64)
    bootstrap_path = _write_bootstrap_raw(
        tmp_path, extra_placement=same_audience, name="bootstrap.json"
    )
    report_same_audience = _verify(
        bootstrap_path, registry_path, registry_sha, profile_root, manifest_path
    )
    # Sanity: identical audience must NOT be flagged as a conflict by itself
    # (isolates the next assertion to the audience dimension specifically).
    assert report_same_audience.collisions["CONFLICTING_SAME_COLLECTION_PLACEMENT_COUNT"] == 0

    different_audience = _bootstrap_placement_payload(
        collection=COLLECTION, placement_id="5" * 64, audience=("tous",)
    )
    bootstrap_path2 = _write_bootstrap_raw(
        tmp_path, extra_placement=different_audience, name="bootstrap2.json"
    )
    report = _verify(bootstrap_path2, registry_path, registry_sha, profile_root, manifest_path)
    assert report.ready is False
    assert report.collisions["CONFLICTING_SAME_COLLECTION_PLACEMENT_COUNT"] >= 1


def test_same_counts_but_swapped_member_fails(tmp_path: Path) -> None:
    """|expected| == |actual| in cardinality, but the member sets differ --
    the verifier must still fail, not just count."""
    registry_path, registry_sha, profile_root, manifest_path = _default_fixture(tmp_path)
    row = _bootstrap_row(collection=COLLECTION, candidat="libre")
    bootstrap_path = _write_bootstrap(tmp_path, [row], name="bootstrap.json")

    report = _verify(bootstrap_path, registry_path, registry_sha, profile_root, manifest_path)

    assert report.gates["EXPECTED_PLACEMENT_TUPLES"] == report.gates["ACTUAL_PLACEMENT_TUPLES"]
    assert report.ready is False
    assert report.gates["EXPORTED_PLACEMENT_SET_MINUS_SEALED_PLACEMENT_SET_COUNT"] == 1
    assert report.gates["SEALED_PLACEMENT_SET_MINUS_EXPORTED_PLACEMENT_SET_COUNT"] == 1


def test_bootstrap_inventory_sha256_mismatch_fails(tmp_path: Path) -> None:
    registry_path, registry_sha, profile_root, manifest_path = _default_fixture(tmp_path)
    bootstrap_path = _write_bootstrap(tmp_path, [_bootstrap_row()], name="bootstrap.json")
    tampered = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    tampered["package_version"] = "9.9.9"  # payload changes, sealed digest does not
    bootstrap_path.write_text(json.dumps(tampered) + "\n", encoding="utf-8")

    with pytest.raises(R1EvidenceVerifierError):
        _verify(bootstrap_path, registry_path, registry_sha, profile_root, manifest_path)


def test_release_authority_digest_mismatch_fails(tmp_path: Path) -> None:
    registry_path, _registry_sha, profile_root, manifest_path = _default_fixture(tmp_path)
    bootstrap_path = _write_bootstrap(tmp_path, [_bootstrap_row()], name="bootstrap.json")

    with pytest.raises(R1EvidenceVerifierError):
        _verify(bootstrap_path, registry_path, "0" * 64, profile_root, manifest_path)


def test_duplicate_resource_version_with_conflicting_hash_fails(tmp_path: Path) -> None:
    """Two source rows sharing one resource_version_id but different
    content_sha256 -- the pydantic contract itself refuses to construct,
    which is exactly the required fail-closed outcome, verified here at the
    fixture-building boundary rather than assumed from the contract's own
    unit tests."""
    row_a = _bootstrap_row()
    row_b = _bootstrap_row(collection=COLLECTION)
    row_b["content_sha256"] = "9" * 64
    row_b["rag_artifact_id"] = "9" * 64
    row_b["rag_content_sha256"] = "9" * 64
    row_b["artifact_payload"]["sha256"] = "9" * 64
    row_b["placements"][0]["placement_id"] = "7" * 64

    with pytest.raises(Exception):  # noqa: B017 -- BootstrapInventoryError, raised while building the fixture itself
        _write_bootstrap(tmp_path, [row_a, row_b], name="bootstrap.json")


# ---------------------------------------------------------------------------
# R1B -- audience now genuinely compared against the sealed profile
# authority, not merely reported as a distribution.
# ---------------------------------------------------------------------------


def test_same_ten_dimensions_wrong_audience_fails_via_sealed_placement_set(
    tmp_path: Path,
) -> None:
    registry_path, registry_sha, profile_root, manifest_path = _default_fixture(
        tmp_path, audience=("libre", "aefe")
    )
    row = _bootstrap_row(audience=("tous",))
    bootstrap_path = _write_bootstrap(tmp_path, [row], name="bootstrap.json")

    report = _verify(bootstrap_path, registry_path, registry_sha, profile_root, manifest_path)

    assert report.ready is False
    assert report.gates["EXPORTED_PLACEMENT_SET_MINUS_SEALED_PLACEMENT_SET_COUNT"] == 1
    assert report.gates["SEALED_PLACEMENT_SET_MINUS_EXPORTED_PLACEMENT_SET_COUNT"] == 1


def test_audience_member_removed_fails(tmp_path: Path) -> None:
    registry_path, registry_sha, profile_root, manifest_path = _default_fixture(
        tmp_path, audience=("libre", "aefe")
    )
    row = _bootstrap_row(audience=("libre",))
    bootstrap_path = _write_bootstrap(tmp_path, [row], name="bootstrap.json")

    report = _verify(bootstrap_path, registry_path, registry_sha, profile_root, manifest_path)

    assert report.ready is False


def test_audience_member_added_fails(tmp_path: Path) -> None:
    registry_path, registry_sha, profile_root, manifest_path = _default_fixture(
        tmp_path, audience=("libre", "aefe")
    )
    row = _bootstrap_row(audience=("libre", "aefe", "tous"))
    bootstrap_path = _write_bootstrap(tmp_path, [row], name="bootstrap.json")

    report = _verify(bootstrap_path, registry_path, registry_sha, profile_root, manifest_path)

    assert report.ready is False


def test_audience_same_members_different_order_passes(tmp_path: Path) -> None:
    registry_path, registry_sha, profile_root, manifest_path = _default_fixture(
        tmp_path, audience=("libre", "aefe")
    )
    row = _bootstrap_row(audience=("aefe", "libre"))  # deliberately reversed
    bootstrap_path = _write_bootstrap(tmp_path, [row], name="bootstrap.json")

    report = _verify(bootstrap_path, registry_path, registry_sha, profile_root, manifest_path)

    assert report.ready is True, report.blockers


def test_profile_yaml_changed_without_manifest_update_fails(tmp_path: Path) -> None:
    """A profile file edited on disk after the manifest was signed --
    ``verify_profile_manifest`` must refuse, since it recomputes the
    fingerprint from the real file rather than trusting the manifest's
    stale declared value."""
    registry_path, registry_sha, profile_root, manifest_path = _default_fixture(tmp_path)
    bootstrap_path = _write_bootstrap(tmp_path, [_bootstrap_row()], name="bootstrap.json")

    profile_file = profile_root / f"{COLLECTION}.yml"
    data = yaml.safe_load(profile_file.read_text(encoding="utf-8"))
    data["scope"]["audience"] = ["tous"]  # edited post-signature, fingerprint now stale
    profile_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(R1EvidenceVerifierError):
        _verify(bootstrap_path, registry_path, registry_sha, profile_root, manifest_path)


def test_manifest_profile_fingerprint_tampered_fails(tmp_path: Path) -> None:
    registry_path, registry_sha, profile_root, manifest_path = _default_fixture(tmp_path)
    bootstrap_path = _write_bootstrap(tmp_path, [_bootstrap_row()], name="bootstrap.json")

    manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest_data["profiles"][0]["fingerprint"] = "0" * 64
    manifest_path.write_text(yaml.safe_dump(manifest_data, sort_keys=False), encoding="utf-8")

    with pytest.raises(R1EvidenceVerifierError):
        _verify(bootstrap_path, registry_path, registry_sha, profile_root, manifest_path)


def test_profile_from_another_collection_supplied_fails(tmp_path: Path) -> None:
    """The declared release's collection has no corresponding profile in the
    supplied registry at all (its file was replaced by one that registers
    under a different collection key) -- select_profile finds nothing,
    which must surface as a scope-consistency failure, never a silent pass."""
    registry_path, registry_sha, profile_root, manifest_path = _default_fixture(tmp_path)
    bootstrap_path = _write_bootstrap(tmp_path, [_bootstrap_row()], name="bootstrap.json")

    # Replace the real profile file's own content with one for an unrelated
    # collection -- load_profile_registry keys strictly by content
    # (scope.collection), so this collection now has no registry entry at
    # all, while a DIFFERENT, undeclared collection appears instead.
    profile_file = profile_root / f"{COLLECTION}.yml"
    other = _profile_dict(collection="rag_nexus_someone_elses_collection")
    profile_file.write_text(yaml.safe_dump(other, sort_keys=False), encoding="utf-8")

    with pytest.raises(R1EvidenceVerifierError):
        # verify_profile_manifest itself fails first: the manifest declares
        # a fingerprint for COLLECTION that the registry no longer contains
        # under that key.
        _verify(bootstrap_path, registry_path, registry_sha, profile_root, manifest_path)


def test_profile_scope_agrees_on_audience_but_disagrees_on_matiere_fails(
    tmp_path: Path,
) -> None:
    """The profile is internally consistent and correctly signed, but its
    OTHER scope dimension (matiere) disagrees with what the sealed
    subject-release placement declares for the same collection -- proving
    the cross-check runs on every shared dimension, not only audience."""
    profile_root, manifest_path, manifest_fp, fp_by_collection = _write_profile_authority(
        tmp_path / "profiles",
        collections=(COLLECTION,),
        audience=DEFAULT_AUDIENCE,
        matiere="a_different_matiere",
    )
    registry_path, registry_sha = _sealed_release(
        tmp_path / "release",
        collection=COLLECTION,
        profile_fingerprint=fp_by_collection[COLLECTION],
        profile_manifest_fp=manifest_fp,
    )  # subject placement still declares matiere="r1a" by default
    bootstrap_path = _write_bootstrap(tmp_path, [_bootstrap_row()], name="bootstrap.json")

    report = _verify(bootstrap_path, registry_path, registry_sha, profile_root, manifest_path)

    assert report.ready is False
    assert report.gates["R1_PROFILE_RELEASE_SCOPE_CONSISTENCY"] == "FAIL"
    assert any("matiere" in mismatch for mismatch in report.gates["profile_scope_mismatches"])


def test_duplicate_identical_placement_is_blocking(tmp_path: Path) -> None:
    """Issue #155's own rule: an unexplained producer duplicate is never
    silently deduplicated. Two placement rows under different placement_ids
    but an IDENTICAL semantic tuple must never yield ready=True, even though
    they disagree with nothing else."""
    registry_path, registry_sha, profile_root, manifest_path = _default_fixture(tmp_path)
    duplicate = _bootstrap_placement_payload(collection=COLLECTION, placement_id="6" * 64)
    bootstrap_path = _write_bootstrap_raw(
        tmp_path, extra_placement=duplicate, name="bootstrap.json"
    )

    report = _verify(bootstrap_path, registry_path, registry_sha, profile_root, manifest_path)

    assert report.collisions["DUPLICATE_IDENTICAL_PLACEMENT_COUNT"] >= 1
    assert report.ready is False


# ---------------------------------------------------------------------------
# Legitimate multi-placement must remain unaffected by every R1B change.
# ---------------------------------------------------------------------------

SECOND_COLLECTION = "rag_nexus_r1b_second_specialite"


def test_two_sealed_different_collections_passes(tmp_path: Path) -> None:
    profile_root, manifest_path, manifest_fp, fp_by_collection = _write_profile_authority(
        tmp_path / "profiles", collections=(COLLECTION, SECOND_COLLECTION)
    )
    release_dir = tmp_path / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    authorities = _multilevel_authorities()
    authorities["profile_manifest_sha256"] = manifest_fp

    def _subject(collection: str, placement_id: str) -> dict[str, object]:
        return {
            "release_kind": "MULTILEVEL_SUBJECT_RELEASE_V1",
            "release_id": f"r1b-fixture-{collection}",
            "school_year": "2026-2027",
            "collection": collection,
            "programme_version": "fixture-2026",
            "authorities": authorities,
            "profile": {
                "version": PROFILE_VERSION,
                "fingerprint": fp_by_collection[collection],
                "manifest_digest": manifest_fp,
            },
            "models": {
                "embedding": {
                    "model_id": MODEL_ID,
                    "inventory_sha256": "1" * 64,
                    "dimension": 1024,
                },
                "reranker": {
                    "model_id": "cross-encoder/ms-marco-MiniLM-L-6-v2",
                    "inventory_sha256": "2" * 64,
                },
            },
            "expected_counts": {"artifacts": 1, "placements": 1, "chunks": 1},
            "artifacts": [
                {
                    "content_sha256": ARTIFACT_SHA,
                    "source_path": "01_EDUSCOL_OFFICIEL/LYCEE/R1A/a.pdf",
                    "source_url": SOURCE_URI,
                    "title": "Fixture R1A shared",
                    "type_doc": "ressource_officielle",
                    "page_count": 1,
                    "placement_id_set_digest": hashlib.sha256(
                        json.dumps([placement_id]).encode()
                    ).hexdigest(),
                    "chunk_id_set_digest": hashlib.sha256(
                        json.dumps([CHUNK_ID]).encode()
                    ).hexdigest(),
                    "chunk_sha256_set_digest": hashlib.sha256(
                        json.dumps([CHUNK_SHA]).encode()
                    ).hexdigest(),
                    "page_coverage_digest": hashlib.sha256(json.dumps([1]).encode()).hexdigest(),
                    "placements": [
                        _placement_payload(collection=collection, placement_id=placement_id)
                    ],
                    "chunks": [
                        {
                            "chunk_id": CHUNK_ID,
                            "chunk_index": 0,
                            "chunk_sha256": CHUNK_SHA,
                            "page_start": 1,
                            "page_end": 1,
                        }
                    ],
                }
            ],
        }

    placement_id_by_collection = {COLLECTION: PLACEMENT_ID, SECOND_COLLECTION: "3" * 64}
    subject_paths_shas: list[tuple[str, str, str]] = []
    for collection in (COLLECTION, SECOND_COLLECTION):
        subject_path = release_dir / f"{collection}.release.json"
        subject_sha = _write_json(
            subject_path, _subject(collection, placement_id_by_collection[collection])
        )
        subject_paths_shas.append((collection, subject_path.name, subject_sha))

    aggregate = {
        "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V1",
        "release_id": "r1b-fixture-2026-2027",
        "school_year": "2026-2027",
        "authorities": authorities,
        "models": _subject(COLLECTION, PLACEMENT_ID)["models"],
        "expected_counts": {"artifacts": 2, "placements": 2, "chunks": 2},
        "subjects": [
            {"path": name, "sha256": sha, "collection": collection}
            for collection, name, sha in subject_paths_shas
        ],
    }
    aggregate_path = release_dir / "aggregate.release.json"
    aggregate_sha = _write_json(aggregate_path, aggregate)
    registry = {
        "registry_version": "1",
        "school_year": "2026-2027",
        "releases": [
            {
                "release_id": aggregate["release_id"],
                "release_kind": aggregate["release_kind"],
                "collections": [COLLECTION, SECOND_COLLECTION],
                "manifest_path": aggregate_path.name,
                "expected_manifest_sha256": aggregate_sha,
            }
        ],
    }
    registry_path = release_dir / "release-registry.json"
    registry_sha = _write_json(registry_path, registry)

    row = _bootstrap_row(
        extra_placements=[
            _bootstrap_placement_payload(collection=SECOND_COLLECTION, placement_id="9" * 64)
        ]
    )
    bootstrap_path = _write_bootstrap(tmp_path, [row], name="bootstrap.json")

    report = _verify(bootstrap_path, registry_path, registry_sha, profile_root, manifest_path)

    assert report.ready is True, report.blockers
    assert report.gates["BOOTSTRAP_PLACEMENTS"] == 2
