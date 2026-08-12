"""Readiness Wave 0 : seul un manifest exactement matérialisé autorise le runtime."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor.release_readiness import (  # noqa: E402
    ReleaseDatabaseSnapshot,
    collect_release_snapshot,
    evaluate_release_snapshot,
    load_release_expectation,
    validate_release_readiness,
)

COLLECTION = "rag_nexus_maths_troisieme_tc"
CANONICAL_COLLECTIONS = Path(__file__).resolve().parents[1] / "configs" / "rag_collections.yml"
ARTIFACT_SHA = "a" * 64
PLACEMENT_ID = "b" * 64
CHUNK_ID = "c" * 64
CHUNK_SHA = "d" * 64
MODEL_ID = "intfloat/multilingual-e5-large"


def _write_json(path: Path, payload: object) -> str:
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _set_digest(values: list[object]) -> str:
    data = json.dumps(
        sorted(set(values)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(data).hexdigest()


def _release_files(tmp_path: Path) -> tuple[Path, str]:
    subject = {
        "release_kind": "WAVE0_SUBJECT_RELEASE_V1",
        "release_id": "wave0-maths-3e-2026-2027",
        "school_year": "2026-2027",
        "collection": COLLECTION,
        "programme_version": "BOEN_special_11_2018-07-26_aj_2020",
        "authorities": {
            name: str(index) * 64
            for index, name in enumerate(
                (
                    "corpus_manifest_sha256",
                    "sealed_catalog_sha256",
                    "placement_catalog_sha256",
                    "candidate_inventory_sha256",
                    "currentness_evidence_sha256",
                    "pii_evidence_sha256",
                    "pii_policy_sha256",
                    "rights_registry_sha256",
                ),
                start=1,
            )
        },
        "profile": {
            "version": "1.0.0",
            "fingerprint": "e" * 64,
            "manifest_digest": "f" * 64,
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
                "source_path": "01_EDUSCOL_OFFICIEL/COLLEGE/3E/MATHEMATIQUES/a.pdf",
                "source_url": "https://eduscol.education.fr/document/a/download",
                "title": "Attendus de mathématiques",
                "type_doc": "ressource_officielle",
                "page_count": 1,
                "placement_id_set_digest": _set_digest([PLACEMENT_ID]),
                "chunk_id_set_digest": _set_digest([CHUNK_ID]),
                "chunk_sha256_set_digest": _set_digest([CHUNK_SHA]),
                "page_coverage_digest": _set_digest([1]),
                "placements": [
                    {
                        "placement_id": PLACEMENT_ID,
                        "source_placement_id": "catalog-placement-maths",
                        "source_scope": "college/cycle-4/mathematiques",
                        "collection": COLLECTION,
                        "tenant": "libre_troisieme",
                        "niveau": "troisieme",
                        "voie": "college",
                        "matiere": "maths",
                        "statut_enseignement": "tronc_commun",
                        "candidat": "both",
                        "visibility": "internal",
                        "school_year": "2026-2027",
                        "programme_version": "BOEN_special_11_2018-07-26_aj_2020",
                        "currentness": "current",
                        "placement_status": "active",
                        "review_status": "reviewed",
                    }
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
    subject_path = tmp_path / "maths_troisieme.release.json"
    subject_sha = _write_json(subject_path, subject)
    aggregate = {
        "release_kind": "WAVE0_AGGREGATE_RELEASE_V1",
        "release_id": "wave0-2026-2027",
        "school_year": "2026-2027",
        "authorities": subject["authorities"],
        "models": subject["models"],
        "expected_counts": {"artifacts": 1, "placements": 1, "chunks": 1},
        "subjects": [
            {
                "path": subject_path.name,
                "sha256": subject_sha,
                "collection": COLLECTION,
            }
        ],
    }
    aggregate_path = tmp_path / "wave0.release.json"
    return aggregate_path, _write_json(aggregate_path, aggregate)


def _snapshot() -> ReleaseDatabaseSnapshot:
    return ReleaseDatabaseSnapshot(
        artifacts=(
            {
                "artifact_id": ARTIFACT_SHA,
                "content_sha256": ARTIFACT_SHA,
                "source_label": "eduscol.education.fr",
                "source_uri": "https://eduscol.education.fr/document/a/download",
                "rights": "officiel_public",
                "official": True,
                "source_kind": "eduscol.education.fr",
                "type_doc": "ressource_officielle",
            },
        ),
        placements=(
            {
                "placement_id": PLACEMENT_ID,
                "artifact_id": ARTIFACT_SHA,
                "collection": COLLECTION,
                "tenant": "libre_troisieme",
                "niveau": "troisieme",
                "voie": "college",
                "matiere": "maths",
                "statut_enseignement": "tronc_commun",
                "candidat": "both",
                "visibility": "internal",
                "school_year": "2026-2027",
                "programme_version": "BOEN_special_11_2018-07-26_aj_2020",
                "currentness": "current",
                "placement_status": "active",
                "review_status": "reviewed",
                "source_placement_id": "catalog-placement-maths",
                "source_scope": "college/cycle-4/mathematiques",
                "source_path": "01_EDUSCOL_OFFICIEL/COLLEGE/3E/MATHEMATIQUES/a.pdf",
                "source_uri": "https://eduscol.education.fr/document/a/download",
                "authorization_id": "LOT41A-V2:auth",
                "publication_attestation_id": "11111111-1111-1111-1111-111111111111",
            },
        ),
        chunks=(
            {
                "chunk_id": CHUNK_ID,
                "artifact_id": ARTIFACT_SHA,
                "collection": COLLECTION,
                "chunk_index": 0,
                "chunk_sha256": CHUNK_SHA,
                "page_start": 1,
                "page_end": 1,
                "review_status": "reviewed",
                "model": MODEL_ID,
                "vector_present": True,
                "vector_dimension": 1024,
            },
        ),
    )


def test_manifest_absent_fails_closed(tmp_path: Path) -> None:
    report = validate_release_readiness(tmp_path / "missing.json", "0" * 64, object())

    assert report.ready is False
    assert "release manifest unavailable" in report.blockers


def test_manifest_digest_drift_fails_closed(tmp_path: Path) -> None:
    manifest, _digest = _release_files(tmp_path)

    report = validate_release_readiness(manifest, "0" * 64, object())

    assert report.ready is False
    assert "release manifest digest mismatch" in report.blockers


def test_exact_snapshot_is_ready(tmp_path: Path) -> None:
    manifest, digest = _release_files(tmp_path)
    expectation = load_release_expectation(manifest, digest)

    report = evaluate_release_snapshot(expectation, _snapshot())

    assert report.ready is True
    assert report.collections == (COLLECTION,)
    assert report.blockers == ()
    assert report.missing_artifacts == 0
    assert report.unexpected_artifacts == 0
    assert report.missing_placements == 0
    assert report.unexpected_placements == 0
    assert report.missing_chunks == 0
    assert report.unexpected_chunks == 0


@pytest.mark.parametrize(
    ("kind", "mutation", "counter"),
    [
        ("artifacts", lambda rows: rows.clear(), "missing_artifacts"),
        (
            "artifacts",
            lambda rows: rows.append({**rows[0], "artifact_id": "9" * 64, "content_sha256": "9" * 64}),
            "unexpected_artifacts",
        ),
        ("placements", lambda rows: rows.clear(), "missing_placements"),
        (
            "placements",
            lambda rows: rows.append({**rows[0], "placement_id": "8" * 64}),
            "unexpected_placements",
        ),
        ("chunks", lambda rows: rows.clear(), "missing_chunks"),
        (
            "chunks",
            lambda rows: rows.append({**rows[0], "chunk_id": "7" * 64}),
            "unexpected_chunks",
        ),
        (
            "chunks",
            lambda rows: rows[0].update(chunk_sha256="0" * 64),
            "wrong_chunk_sha",
        ),
        (
            "chunks",
            lambda rows: rows[0].update(page_start=2),
            "wrong_page_metadata",
        ),
        (
            "chunks",
            lambda rows: rows[0].update(model="debug/deterministic-1024"),
            "wrong_model_rows",
        ),
        (
            "chunks",
            lambda rows: rows[0].update(vector_present=False),
            "null_vectors",
        ),
        (
            "chunks",
            lambda rows: rows[0].update(vector_dimension=3),
            "wrong_vector_dimensions",
        ),
        (
            "placements",
            lambda rows: rows[0].update(review_status="needs_review"),
            "wrong_review_status",
        ),
        (
            "placements",
            lambda rows: rows[0].update(currentness="review_required"),
            "wrong_currentness",
        ),
    ],
)
def test_any_database_drift_fails_closed(
    tmp_path: Path,
    kind: str,
    mutation: object,
    counter: str,
) -> None:
    manifest, digest = _release_files(tmp_path)
    expectation = load_release_expectation(manifest, digest)
    original = _snapshot()
    parts = {
        "artifacts": [dict(row) for row in original.artifacts],
        "placements": [dict(row) for row in original.placements],
        "chunks": [dict(row) for row in original.chunks],
    }
    mutate = mutation
    assert callable(mutate)
    mutate(parts[kind])
    snapshot = ReleaseDatabaseSnapshot(
        artifacts=tuple(parts["artifacts"]),
        placements=tuple(parts["placements"]),
        chunks=tuple(parts["chunks"]),
    )

    report = evaluate_release_snapshot(expectation, snapshot)

    assert report.ready is False
    assert getattr(report, counter) > 0


def test_wrong_artifact_and_placement_metadata_fail_closed(tmp_path: Path) -> None:
    manifest, digest = _release_files(tmp_path)
    expectation = load_release_expectation(manifest, digest)
    original = _snapshot()
    artifacts = [copy.deepcopy(dict(row)) for row in original.artifacts]
    placements = [copy.deepcopy(dict(row)) for row in original.placements]
    artifacts[0]["source_uri"] = "https://example.invalid/republication"
    placements[0]["source_path"] = "wrong/path.pdf"

    report = evaluate_release_snapshot(
        expectation,
        ReleaseDatabaseSnapshot(
            artifacts=tuple(artifacts),
            placements=tuple(placements),
            chunks=original.chunks,
        ),
    )

    assert report.ready is False
    assert report.wrong_artifact_metadata == 1
    assert report.wrong_placement_metadata == 1


def test_incomplete_runtime_manifest_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor import retrieval_v2_endpoint as endpoint

    monkeypatch.setenv("RAG_RELEASE_MANIFEST_PATH", "/missing/release.json")
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_SHA256", raising=False)

    assert endpoint._release_evidence_for_collection(COLLECTION) is False


def test_subject_manifest_requires_complete_page_coverage(tmp_path: Path) -> None:
    manifest, _digest = _release_files(tmp_path)
    subject_path = tmp_path / "maths_troisieme.release.json"
    subject = json.loads(subject_path.read_text())
    subject["artifacts"][0]["page_count"] = 2
    subject_sha = _write_json(subject_path, subject)
    aggregate = json.loads(manifest.read_text())
    aggregate["subjects"][0]["sha256"] = subject_sha
    digest = _write_json(manifest, aggregate)

    with pytest.raises(ValueError, match="page coverage"):
        load_release_expectation(manifest, digest)


def test_subject_manifest_requires_contiguous_chunk_indices(tmp_path: Path) -> None:
    manifest, _digest = _release_files(tmp_path)
    subject_path = tmp_path / "maths_troisieme.release.json"
    subject = json.loads(subject_path.read_text())
    subject["artifacts"][0]["chunks"][0]["chunk_index"] = 4
    subject_sha = _write_json(subject_path, subject)
    aggregate = json.loads(manifest.read_text())
    aggregate["subjects"][0]["sha256"] = subject_sha
    digest = _write_json(manifest, aggregate)

    with pytest.raises(ValueError, match="chunk indices"):
        load_release_expectation(manifest, digest)


def test_instanciated_v2_collection_requires_manifest_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nexus_contracts import load_retrieval_scope_registry

    from ingestor import retrieval_v2_endpoint as endpoint

    artifacts = load_retrieval_scope_registry()
    wave0_collections = {
        artifact.evidence_subject.collection
        for artifact in artifacts.values()
        if hasattr(artifact, "evidence_subject")
    }
    assert wave0_collections
    selected = sorted(wave0_collections)[0]
    cfg = {
        "collections": {
            collection: {"instanciee": collection == selected}
            for collection in wave0_collections
        }
    }
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_SHA256", raising=False)

    with pytest.raises(RuntimeError, match="release manifest"):
        endpoint.validate_release_startup_configuration(artifacts, cfg)


def test_canonical_wave0_activation_requires_manifest_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yaml
    from nexus_contracts import load_retrieval_scope_registry

    from ingestor import retrieval_v2_endpoint as endpoint

    cfg = yaml.safe_load(CANONICAL_COLLECTIONS.read_text(encoding="utf-8"))
    assert isinstance(cfg, dict)
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_SHA256", raising=False)

    with pytest.raises(RuntimeError, match="release manifest"):
        endpoint.validate_release_startup_configuration(
            load_retrieval_scope_registry(),
            cfg,
        )


def test_aggregate_and_subject_authorities_must_match(tmp_path: Path) -> None:
    manifest, _digest = _release_files(tmp_path)
    subject_path = tmp_path / "maths_troisieme.release.json"
    subject = json.loads(subject_path.read_text())
    subject["authorities"]["pii_evidence_sha256"] = "9" * 64
    subject_sha = _write_json(subject_path, subject)
    aggregate = json.loads(manifest.read_text())
    aggregate["subjects"][0]["sha256"] = subject_sha
    digest = _write_json(manifest, aggregate)

    with pytest.raises(ValueError, match="authorities mismatch"):
        load_release_expectation(manifest, digest)


def test_database_snapshot_counts_chunk_only_artifact_as_unexpected() -> None:
    class Cursor:
        def __init__(self, rows: list[tuple[object, ...]]) -> None:
            self.rows = rows
            self.sql = ""
            self.params: object = None

        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, sql: str, params: object) -> None:
            self.sql = sql
            self.params = params

        def fetchall(self) -> list[tuple[object, ...]]:
            return self.rows

    class Connection:
        def __init__(self) -> None:
            self.cursors = [
                Cursor([]),
                Cursor([]),
                Cursor([]),
            ]
            self.index = 0

        def cursor(self) -> Cursor:
            cursor = self.cursors[self.index]
            self.index += 1
            return cursor

    connection = Connection()

    collect_release_snapshot(connection, (COLLECTION,))

    artifact_cursor = connection.cursors[0]
    assert "UNION" in artifact_cursor.sql
    assert "FROM public.rag_chunks" in artifact_cursor.sql
    assert "NOT EXISTS" in artifact_cursor.sql
    assert artifact_cursor.params == ([COLLECTION], [COLLECTION])
    placement_cursor = connection.cursors[1]
    assert "source_scope" in placement_cursor.sql


def test_release_expectation_preserves_sealed_model_inventories(tmp_path: Path) -> None:
    manifest, digest = _release_files(tmp_path)

    expectation = load_release_expectation(manifest, digest)

    assert expectation.embedding_model_id == MODEL_ID
    assert expectation.embedding_inventory_sha256 == "1" * 64
    assert expectation.embedding_dimension == 1024
    assert expectation.reranker_model_id == "cross-encoder/ms-marco-MiniLM-L-6-v2"
    assert expectation.reranker_inventory_sha256 == "2" * 64


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("authorities", "pii_evidence_sha256"),
        ("profile", "fingerprint"),
        ("models", "reranker"),
    ],
)
def test_subject_manifest_refuses_incomplete_governance_links(
    tmp_path: Path,
    section: str,
    key: str,
) -> None:
    manifest, _digest = _release_files(tmp_path)
    subject_path = tmp_path / "maths_troisieme.release.json"
    subject = json.loads(subject_path.read_text())
    del subject[section][key]
    subject_sha = _write_json(subject_path, subject)
    aggregate = json.loads(manifest.read_text())
    aggregate["subjects"][0]["sha256"] = subject_sha
    if section in {"authorities", "models"}:
        aggregate[section] = subject[section]
    digest = _write_json(manifest, aggregate)

    with pytest.raises(ValueError, match=section):
        load_release_expectation(manifest, digest)
