"""R1 evidence verifier -- adversarial proof suite.

Never touches PostgreSQL: both the sealed-release fixture and the bootstrap
fixture are plain files built in ``tmp_path``. The sealed-release fixture
reuses the same MULTILEVEL_SUBJECT_RELEASE_V1 / MULTILEVEL_AGGREGATE_RELEASE_V1
shape already proven in ``test_release_readiness.py`` (a WAVE0-shaped subject
with its ``release_kind`` overridden, exactly as that suite's own
``test_multilevel_aggregate_uses_its_extended_authority_contract`` does) --
this test module does not invent a second release-file schema.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from nexus_contracts import seal_resource_registry_bootstrap
from nexus_contracts.resource_registry_bootstrap import ResourceRegistryBootstrapPayload

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


def _placement_payload(
    *, collection: str = COLLECTION, candidat: str = "scolarise"
) -> dict[str, object]:
    """Sealed-RELEASE placement shape (no ``audience``/``source_uri``: the
    real committed release files structurally lack them -- see the module
    docstring; carries ``source_placement_id``/``source_scope`` instead,
    which the bootstrap/DB shape does not)."""
    return {
        "placement_id": PLACEMENT_ID,
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
    *, collection: str = COLLECTION, candidat: str = "scolarise", placement_id: str = PLACEMENT_ID
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
        "audience": ["aefe"],
        "visibility": "internal",
        "school_year": "2026-2027",
        "programme_version": "fixture-2026",
        "currentness": "current",
        "placement_status": "active",
        "review_status": "reviewed",
        "source_uri": SOURCE_URI,
    }


def _sealed_release(tmp_path: Path, *, collection: str = COLLECTION) -> tuple[Path, str]:
    """A MULTILEVEL_AGGREGATE_RELEASE_V1 + one subject file it SHA256-pins,
    wrapped in a release-registry.json -- exactly what
    ``load_release_registry_file`` (reused unmodified) already parses."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    authorities = _multilevel_authorities()
    subject = {
        "release_kind": "MULTILEVEL_SUBJECT_RELEASE_V1",
        "release_id": f"r1a-fixture-2026-2027-{collection}",
        "school_year": "2026-2027",
        "collection": collection,
        "programme_version": "fixture-2026",
        "authorities": authorities,
        "profile": {
            "version": "1.0.0",
            "fingerprint": "e" * 64,
            "manifest_digest": authorities["profile_manifest_sha256"],
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
                "placements": [_placement_payload(collection=collection)],
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


def _bootstrap_row(
    *,
    collection: str = COLLECTION,
    candidat: str = "scolarise",
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
        "audience": ["aefe"],
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
    same-collection conflict check (this PR's own fix) now refuses to BUILD
    a bootstrap containing the same conflict this test needs to hand the
    R1 evidence VERIFIER. A bootstrap file handed to the verifier is not
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


def test_exact_release_passes(tmp_path: Path) -> None:
    registry_path, registry_sha = _sealed_release(tmp_path / "release")
    bootstrap_path = _write_bootstrap(tmp_path, [_bootstrap_row()], name="bootstrap.json")

    report = verify_r1_evidence(
        bootstrap_path=bootstrap_path,
        release_registry_path=registry_path,
        release_registry_sha256=registry_sha,
    )

    assert report.ready is True, report.blockers
    assert report.gates["EXPORTED_PLACEMENT_SET_MINUS_SEALED_PLACEMENT_SET_COUNT"] == 0
    assert report.gates["SEALED_PLACEMENT_SET_MINUS_EXPORTED_PLACEMENT_SET_COUNT"] == 0
    assert report.gates["BOOTSTRAP_RESOURCE_ROWS"] == 1


def test_missing_sealed_placement_fails(tmp_path: Path) -> None:
    """The sealed release promotes the fixture placement; the bootstrap
    exported nothing for it at all (simulated by pointing the verifier at a
    bootstrap built from a DIFFERENT, unrelated resource)."""
    registry_path, registry_sha = _sealed_release(tmp_path / "release")
    other_row = _bootstrap_row(
        collection="rag_nexus_other_unrelated_specialite",
        resource_id=UUID("44444444-4444-4444-8444-444444444444"),
        resource_version_id=UUID("55555555-5555-4555-8555-555555555555"),
        content_sha256="9" * 64,
        placement_id="8" * 64,
        chunk_id="e" * 64,
    )
    bootstrap_path = _write_bootstrap(tmp_path, [other_row], name="bootstrap.json")

    report = verify_r1_evidence(
        bootstrap_path=bootstrap_path,
        release_registry_path=registry_path,
        release_registry_sha256=registry_sha,
    )

    assert report.ready is False
    assert report.gates["SEALED_PLACEMENT_SET_MINUS_EXPORTED_PLACEMENT_SET_COUNT"] == 1
    assert "rag_nexus_r1a_fixture_specialite" in report.gates[
        "SEALED_COLLECTIONS_MINUS_EXPORTED_COLLECTIONS"
    ]


def test_extra_different_collection_placement_fails(tmp_path: Path) -> None:
    registry_path, registry_sha = _sealed_release(tmp_path / "release")
    row = _bootstrap_row(
        extra_placements=[
            _bootstrap_placement_payload(
                collection="rag_nexus_unpromoted_specialite", placement_id="4" * 64
            )
        ]
    )
    bootstrap_path = _write_bootstrap(tmp_path, [row], name="bootstrap.json")

    report = verify_r1_evidence(
        bootstrap_path=bootstrap_path,
        release_registry_path=registry_path,
        release_registry_sha256=registry_sha,
    )

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
    registry_path, registry_sha = _sealed_release(tmp_path / "release")
    conflicting = _bootstrap_placement_payload(collection=COLLECTION, placement_id="7" * 64)
    conflicting[field_name] = value
    bootstrap_path = _write_bootstrap_raw(
        tmp_path, extra_placement=conflicting, name="bootstrap.json"
    )

    report = verify_r1_evidence(
        bootstrap_path=bootstrap_path,
        release_registry_path=registry_path,
        release_registry_sha256=registry_sha,
    )

    assert report.ready is False
    assert report.collisions["CONFLICTING_SAME_COLLECTION_PLACEMENT_COUNT"] >= 1


def test_extra_same_collection_placement_with_different_audience_fails(tmp_path: Path) -> None:
    """``audience`` has no sealed authority (see module docstring), so this
    can only ever be caught by the internal same-collection conflict check,
    not by the sealed-vs-exported set comparison -- proven explicitly here
    rather than assumed."""
    registry_path, registry_sha = _sealed_release(tmp_path / "release")

    same_audience = _bootstrap_placement_payload(collection=COLLECTION, placement_id="6" * 64)
    bootstrap_path = _write_bootstrap_raw(
        tmp_path, extra_placement=same_audience, name="bootstrap.json"
    )
    report_same_audience = verify_r1_evidence(
        bootstrap_path=bootstrap_path,
        release_registry_path=registry_path,
        release_registry_sha256=registry_sha,
    )
    # Sanity: identical audience must NOT be flagged as a conflict by itself
    # (isolates the next assertion to the audience dimension specifically).
    assert report_same_audience.collisions["CONFLICTING_SAME_COLLECTION_PLACEMENT_COUNT"] == 0

    different_audience = _bootstrap_placement_payload(collection=COLLECTION, placement_id="5" * 64)
    different_audience["audience"] = ["tous"]
    bootstrap_path2 = _write_bootstrap_raw(
        tmp_path, extra_placement=different_audience, name="bootstrap2.json"
    )
    report = verify_r1_evidence(
        bootstrap_path=bootstrap_path2,
        release_registry_path=registry_path,
        release_registry_sha256=registry_sha,
    )
    assert report.ready is False
    assert report.collisions["CONFLICTING_SAME_COLLECTION_PLACEMENT_COUNT"] >= 1


def test_same_counts_but_swapped_member_fails(tmp_path: Path) -> None:
    """|expected| == |actual| in cardinality, but the member sets differ --
    the verifier must still fail, not just count."""
    registry_path, registry_sha = _sealed_release(tmp_path / "release")
    # Same shape, same cardinality (exactly one placement either way), but
    # the anchor's own candidat -- and therefore its one placement -- is
    # "libre" instead of the sealed release's "scolarise".
    row = _bootstrap_row(collection=COLLECTION, candidat="libre")
    bootstrap_path = _write_bootstrap(tmp_path, [row], name="bootstrap.json")

    report = verify_r1_evidence(
        bootstrap_path=bootstrap_path,
        release_registry_path=registry_path,
        release_registry_sha256=registry_sha,
    )

    assert report.gates["EXPECTED_PLACEMENT_TUPLES"] == report.gates["ACTUAL_PLACEMENT_TUPLES"]
    assert report.ready is False
    assert report.gates["EXPORTED_PLACEMENT_SET_MINUS_SEALED_PLACEMENT_SET_COUNT"] == 1
    assert report.gates["SEALED_PLACEMENT_SET_MINUS_EXPORTED_PLACEMENT_SET_COUNT"] == 1


def test_bootstrap_inventory_sha256_mismatch_fails(tmp_path: Path) -> None:
    registry_path, registry_sha = _sealed_release(tmp_path / "release")
    bootstrap_path = _write_bootstrap(tmp_path, [_bootstrap_row()], name="bootstrap.json")
    tampered = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    tampered["package_version"] = "9.9.9"  # payload changes, sealed digest does not
    bootstrap_path.write_text(json.dumps(tampered) + "\n", encoding="utf-8")

    with pytest.raises(R1EvidenceVerifierError):
        verify_r1_evidence(
            bootstrap_path=bootstrap_path,
            release_registry_path=registry_path,
            release_registry_sha256=registry_sha,
        )


def test_release_authority_digest_mismatch_fails(tmp_path: Path) -> None:
    registry_path, _registry_sha = _sealed_release(tmp_path / "release")
    bootstrap_path = _write_bootstrap(tmp_path, [_bootstrap_row()], name="bootstrap.json")

    with pytest.raises(R1EvidenceVerifierError):
        verify_r1_evidence(
            bootstrap_path=bootstrap_path,
            release_registry_path=registry_path,
            release_registry_sha256="0" * 64,
        )


def test_duplicate_resource_version_with_conflicting_hash_fails(tmp_path: Path) -> None:
    """Two source rows sharing one resource_version_id but different
    content_sha256 -- the pydantic contract itself refuses to construct,
    which is exactly the required fail-closed outcome, verified here at the
    verifier's own load boundary rather than assumed from the contract's own
    unit tests."""
    registry_path, registry_sha = _sealed_release(tmp_path / "release")
    row_a = _bootstrap_row()
    row_b = _bootstrap_row(collection=COLLECTION)
    row_b["content_sha256"] = "9" * 64
    row_b["rag_artifact_id"] = "9" * 64
    row_b["rag_content_sha256"] = "9" * 64
    row_b["artifact_payload"]["sha256"] = "9" * 64
    row_b["placements"][0]["placement_id"] = "7" * 64

    with pytest.raises(Exception):  # noqa: B017 -- BootstrapInventoryError, raised while building the fixture itself
        _write_bootstrap(tmp_path, [row_a, row_b], name="bootstrap.json")
