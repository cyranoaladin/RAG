from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from ingestor.resource_registry_bootstrap import (
    EXPORT_SQL,
    BootstrapInventoryError,
    build_resource_registry_bootstrap_inventory,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
RESOURCE_ID = UUID("11111111-1111-4111-8111-111111111111")
VERSION_ID = UUID("22222222-2222-4222-8222-222222222222")
RUN_ID = UUID("33333333-3333-4333-8333-333333333333")
GENERATED_AT = datetime(2026, 8, 30, 12, tzinfo=UTC)


def _scope() -> dict[str, object]:
    return {
        "tenant": "nexus",
        "collection": "terminale_maths",
        "niveau": "terminale",
        "voie": "generale",
        "matiere": "mathematiques",
        "candidat": "scolarise",
        "audience": ["aefe"],
        "visibility": "internal",
        "school_year": "2026-2027",
        "programme_version": "fr-national-2026",
    }


def _row(*, chunk_id: str = "chunk-001", chunk_index: int = 0) -> dict[str, object]:
    artifact_payload = {
        "artifact_id": str(VERSION_ID),
        "resource_id": str(RESOURCE_ID),
        "run_id": str(RUN_ID),
        "scope": _scope(),
        "sha256": SHA_A,
        "size_bytes": 42,
        "mime_declared": "application/pdf",
        "mime_detected": "application/pdf",
        "original_url": "https://eduscol.education.fr/programme.pdf",
        "final_url": "https://eduscol.education.fr/programme.pdf",
        "collected_at": "2026-08-30T10:00:00Z",
        "domain": "eduscol.education.fr",
        "publisher": "Ministère de l'Éducation nationale",
        "title": "Programme officiel de mathématiques",
        "license": "Licence Ouverte 2.0",
        "rights_status": "officiel_public",
        "pages_count": 10,
        "version": "2026",
        "extracted_text_ref": None,
    }
    return {
        "resource_id": RESOURCE_ID,
        "resource_version_id": VERSION_ID,
        "run_id": RUN_ID,
        "run_status": "succeeded",
        "resource_state": "RETRIEVAL_ELIGIBLE",
        **_scope(),
        "content_sha256": SHA_A,
        "size_bytes": 42,
        "mime_detected": "application/pdf",
        "artifact_payload": artifact_payload,
        "rag_artifact_id": SHA_A,
        "rag_content_sha256": SHA_A,
        "rag_source_label": "Programme officiel de mathématiques",
        "rag_source_uri": "https://eduscol.education.fr/programme.pdf",
        "rag_rights": "officiel_public",
        "rag_official": True,
        "rag_source_kind": "eduscol",
        "rag_type_doc": "programme_officiel",
        "attribution_resource_id": RESOURCE_ID,
        "attribution_source_label": "Programme officiel de mathématiques",
        "attribution_official": True,
        "attribution_source_kind": "eduscol",
        "attribution_type_doc": "programme_officiel",
        "placements": [
            {
                "collection": "terminale_maths",
                "currentness": "current",
                "placement_status": "active",
                "review_status": "reviewed",
                "source_uri": "https://eduscol.education.fr/programme.pdf",
                **_scope(),
                "statut_enseignement": "specialite",
            }
        ],
        "chunks": [
            {
                "chunk_id": chunk_id,
                "artifact_id": SHA_A,
                "doc_id": SHA_A,
                "chunk_index": chunk_index,
                "page_start": 2,
                "page_end": 4,
                "source_uri": "https://eduscol.education.fr/programme.pdf",
                "rights": "officiel_public",
                "source_label": "Programme officiel de mathématiques",
                "official": True,
                "source_kind": "eduscol",
                "type_doc": "programme_officiel",
                "review_status": "reviewed",
                **_scope(),
                "statut_enseignement": "specialite",
            }
        ],
    }


def _build(rows: list[dict[str, object]]):
    return build_resource_registry_bootstrap_inventory(
        rows,
        producer_repository="cyranoaladin/RAG",
        producer_commit=SHA_B[:40],
        generated_at=GENERATED_AT,
        package_version="0.15.0",
    )


def test_inventory_preserves_uuid_hash_provenance_and_locator() -> None:
    inventory = _build([_row()])
    item = inventory.resources[0]

    assert item.resource_id == RESOURCE_ID
    assert item.resource_version_id == VERSION_ID
    assert item.content_sha256 == SHA_A
    assert item.rag_artifact_id == SHA_A
    assert item.source_kind == "eduscol"
    assert item.placements[0].model_dump(mode="json") == {
        **_scope(),
        "statut_enseignement": "specialite",
    }
    assert item.chunks[0].locator.model_dump(exclude_none=True) == {
        "chunk_index": 0,
        "page_start": 2,
        "page_end": 4,
    }
    assert inventory.inventory_sha256 == inventory.compute_sha256()


def test_inventory_bytes_are_stable_for_source_row_order() -> None:
    first = _row(chunk_id="chunk-002", chunk_index=1)
    second = _row(chunk_id="chunk-001", chunk_index=0)
    first["resource_version_id"] = UUID("44444444-4444-4444-8444-444444444444")
    first["artifact_payload"] = dict(first["artifact_payload"])
    first["artifact_payload"]["artifact_id"] = str(first["resource_version_id"])

    left = _build([first, second])
    right = _build([second, first])

    assert left == right
    assert [str(item.resource_version_id) for item in left.resources] == sorted(
        str(item.resource_version_id) for item in left.resources
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("rag_artifact_id", SHA_B, "content hash"),
        ("rag_content_sha256", SHA_B, "content hash"),
        ("attribution_resource_id", UUID(int=0), "attribution"),
        ("attribution_source_kind", "generated", "attribution"),
    ],
)
def test_inventory_rejects_identity_or_attribution_divergence(
    field: str, value: object, message: str
) -> None:
    row = _row()
    row[field] = value
    with pytest.raises(BootstrapInventoryError, match=message):
        _build([row])


def test_inventory_rejects_invalid_artifact_payload_or_typed_column_drift() -> None:
    row = _row()
    row["artifact_payload"] = dict(row["artifact_payload"])
    row["artifact_payload"]["sha256"] = SHA_B
    with pytest.raises(BootstrapInventoryError, match="artifact payload"):
        _build([row])


@pytest.mark.parametrize("field", ["chunks", "placements"])
def test_inventory_rejects_orphan_chunk_or_unservable_placement(field: str) -> None:
    row = _row()
    row[field] = []
    with pytest.raises(BootstrapInventoryError, match=field):
        _build([row])


def test_inventory_rejects_chunk_identity_metadata_or_index_drift() -> None:
    for field, value in (
        ("artifact_id", SHA_B),
        ("doc_id", SHA_B),
        ("source_uri", "https://example.invalid/other.pdf"),
        ("review_status", "needs_review"),
    ):
        row = _row()
        row["chunks"][0][field] = value
        with pytest.raises(BootstrapInventoryError, match="chunk"):
            _build([row])


def test_inventory_rejects_multiple_rag_artifacts_for_one_ingestion_version() -> None:
    with pytest.raises(BootstrapInventoryError, match="multiple RAG artifacts"):
        _build([_row(), _row()])


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("root", "run_status", "partial"),
        ("placement", "matiere", "nsi"),
        ("chunk", "school_year", "2025-2026"),
    ],
)
def test_inventory_rejects_unpromoted_or_cross_scope_evidence(
    target: str, field: str, value: object
) -> None:
    row = _row()
    if target == "root":
        row[field] = value
    elif target == "placement":
        row["placements"][0][field] = value
    else:
        row["chunks"][0][field] = value
    with pytest.raises(BootstrapInventoryError, match="run|scope"):
        _build([row])


def test_inventory_serialization_excludes_content_paths_vectors_and_pii() -> None:
    serialized = _build([_row()]).model_dump_json()
    assert "source_path" not in serialized
    assert "vector" not in serialized
    assert "chunk text" not in serialized
    assert "student" not in serialized


def test_export_query_uses_one_snapshot_and_separate_aggregations() -> None:
    assert EXPORT_SQL.count("JOIN LATERAL") == 2
    assert "SET TRANSACTION" not in EXPORT_SQL
    assert "c.text" not in EXPORT_SQL
    assert "c.vector" not in EXPORT_SQL
    assert "source_path" not in EXPORT_SQL
    assert "r.resource_state = 'RETRIEVAL_ELIGIBLE'" in EXPORT_SQL
    assert "ir.status = 'succeeded'" in EXPORT_SQL
    assert "r.collection = ANY(%(release_collections)s)" in EXPORT_SQL
    assert "ra.content_sha256 = ANY(%(release_artifact_sha256s)s)" in EXPORT_SQL
