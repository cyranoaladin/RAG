"""Readiness Wave 0 : seul un manifest exactement matérialisé autorise le runtime."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor import release_readiness as readiness  # noqa: E402
from ingestor.release_readiness import (  # noqa: E402
    ReleaseDatabaseSnapshot,
    collect_release_snapshot,
    evaluate_release_snapshot,
    load_release_expectation,
    validate_release_readiness,
)

COLLECTION = "rag_nexus_maths_troisieme_tc"
CANONICAL_COLLECTIONS = Path(__file__).resolve().parents[1] / "configs" / "rag_collections.yml"
REPO_ROOT = Path(__file__).resolve().parents[3]
WAVE0_RELEASE = (
    REPO_ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027/wave0/wave0.release.json"
)
MULTILEVEL_RELEASE = (
    REPO_ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/multilevel.release.json"
)
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


def _release_files(
    tmp_path: Path,
    *,
    collection: str = COLLECTION,
    artifact_sha: str = ARTIFACT_SHA,
    placement_id: str = PLACEMENT_ID,
    chunk_id: str = CHUNK_ID,
    chunk_sha: str = CHUNK_SHA,
    embedding_inventory_sha256: str = "1" * 64,
) -> tuple[Path, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    subject = {
        "release_kind": "WAVE0_SUBJECT_RELEASE_V1",
        "release_id": "wave0-maths-3e-2026-2027",
        "school_year": "2026-2027",
        "collection": collection,
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
                "inventory_sha256": embedding_inventory_sha256,
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
                "content_sha256": artifact_sha,
                "source_path": "01_EDUSCOL_OFFICIEL/COLLEGE/3E/MATHEMATIQUES/a.pdf",
                "source_url": "https://eduscol.education.fr/document/a/download",
                "title": "Attendus de mathématiques",
                "type_doc": "ressource_officielle",
                "page_count": 1,
                "placement_id_set_digest": _set_digest([placement_id]),
                "chunk_id_set_digest": _set_digest([chunk_id]),
                "chunk_sha256_set_digest": _set_digest([chunk_sha]),
                "page_coverage_digest": _set_digest([1]),
                "placements": [
                    {
                        "placement_id": placement_id,
                        "source_placement_id": "catalog-placement-maths",
                        "source_scope": "college/cycle-4/mathematiques",
                        "collection": collection,
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
                        "chunk_id": chunk_id,
                        "chunk_index": 0,
                        "chunk_sha256": chunk_sha,
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
                "collection": collection,
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


def test_multilevel_aggregate_uses_its_extended_authority_contract(
    tmp_path: Path,
) -> None:
    manifest, _digest = _release_files(tmp_path)
    aggregate = json.loads(manifest.read_text(encoding="utf-8"))
    subject_path = tmp_path / aggregate["subjects"][0]["path"]
    subject = json.loads(subject_path.read_text(encoding="utf-8"))
    authority_names = (
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
    authorities = {
        name: hashlib.sha256(name.encode("utf-8")).hexdigest()
        for name in authority_names
    }
    subject["release_kind"] = "MULTILEVEL_SUBJECT_RELEASE_V1"
    subject["authorities"] = authorities
    subject_sha = _write_json(subject_path, subject)
    aggregate["release_kind"] = "MULTILEVEL_AGGREGATE_RELEASE_V1"
    aggregate["authorities"] = authorities
    aggregate["subjects"][0]["sha256"] = subject_sha
    aggregate_sha = _write_json(manifest, aggregate)

    expectation = load_release_expectation(manifest, aggregate_sha)

    assert expectation.collections == (COLLECTION,)
    assert expectation.release_kind == "MULTILEVEL_AGGREGATE_RELEASE_V1"
    assert expectation.artifacts[0].content_sha256 == ARTIFACT_SHA


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
    assert expectation.release_kind == "WAVE0_AGGREGATE_RELEASE_V1"
    assert expectation.subject_manifest_sha256_by_collection == (
        (COLLECTION, hashlib.sha256((tmp_path / "maths_troisieme.release.json").read_bytes()).hexdigest()),
    )


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


def test_release_registry_requires_at_least_one_explicit_manifest() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        readiness.load_release_registry(())


def test_release_registry_loads_two_exact_manifests(tmp_path: Path) -> None:
    first = _release_files(tmp_path / "first")
    second = _release_files(
        tmp_path / "second",
        collection="rag_nexus_francais_seconde_tc",
        artifact_sha="3" * 64,
        placement_id="4" * 64,
        chunk_id="5" * 64,
        chunk_sha="6" * 64,
    )

    registry = readiness.load_release_registry((first, second))

    assert registry.collections == (
        COLLECTION,
        "rag_nexus_francais_seconde_tc",
    )
    assert registry.model_contract == (
        MODEL_ID,
        "1" * 64,
        1024,
        "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "2" * 64,
    )


def test_release_registry_refuses_manifest_digest_drift(tmp_path: Path) -> None:
    manifest, _digest = _release_files(tmp_path)

    with pytest.raises(ValueError, match="digest mismatch"):
        readiness.load_release_registry(((manifest, "0" * 64),))


def test_release_registry_refuses_collection_collision(tmp_path: Path) -> None:
    first = _release_files(tmp_path / "first")
    second = _release_files(
        tmp_path / "second",
        artifact_sha="3" * 64,
        placement_id="4" * 64,
        chunk_id="5" * 64,
        chunk_sha="6" * 64,
    )

    with pytest.raises(ValueError, match="collection collision"):
        readiness.load_release_registry((first, second))


def test_release_registry_refuses_artifact_collision(tmp_path: Path) -> None:
    first = _release_files(tmp_path / "first")
    second = _release_files(
        tmp_path / "second",
        collection="rag_nexus_francais_seconde_tc",
        placement_id="4" * 64,
        chunk_id="5" * 64,
        chunk_sha="6" * 64,
    )

    with pytest.raises(ValueError, match="artifact collision"):
        readiness.load_release_registry((first, second))


def test_release_registry_refuses_model_contract_drift(tmp_path: Path) -> None:
    first = _release_files(tmp_path / "first")
    second = _release_files(
        tmp_path / "second",
        collection="rag_nexus_francais_seconde_tc",
        artifact_sha="3" * 64,
        placement_id="4" * 64,
        chunk_id="5" * 64,
        chunk_sha="6" * 64,
        embedding_inventory_sha256="9" * 64,
    )

    with pytest.raises(ValueError, match="model contract mismatch"):
        readiness.load_release_registry((first, second))


def test_release_registry_database_reports_are_collection_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    second_collection = "rag_nexus_francais_seconde_tc"
    registry = readiness.load_release_registry(
        (
            _release_files(tmp_path / "first"),
            _release_files(
                tmp_path / "second",
                collection=second_collection,
                artifact_sha="3" * 64,
                placement_id="4" * 64,
                chunk_id="5" * 64,
                chunk_sha="6" * 64,
            ),
        )
    )
    requested: list[tuple[str, ...]] = []

    def collect(_connection: object, collections: tuple[str, ...]) -> ReleaseDatabaseSnapshot:
        requested.append(collections)
        if collections == (COLLECTION,):
            return _snapshot()
        return ReleaseDatabaseSnapshot(artifacts=(), placements=(), chunks=())

    monkeypatch.setattr(readiness, "collect_release_snapshot", collect)

    reports = readiness.validate_release_registry_readiness(registry, object())

    assert reports[COLLECTION].ready is True
    assert reports[second_collection].ready is False
    assert reports[second_collection].missing_artifacts == 1
    assert requested == [(COLLECTION,), (second_collection,)]


def test_runtime_release_registry_uses_explicit_path_digest_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor import retrieval_v2_endpoint as endpoint

    first = _release_files(tmp_path / "first")
    second = _release_files(
        tmp_path / "second",
        collection="rag_nexus_francais_seconde_tc",
        artifact_sha="3" * 64,
        placement_id="4" * 64,
        chunk_id="5" * 64,
        chunk_sha="6" * 64,
    )
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_SHA256", raising=False)
    monkeypatch.setenv(
        "RAG_RELEASE_MANIFESTS_JSON",
        json.dumps(
            [
                {"path": str(path), "sha256": digest}
                for path, digest in (first, second)
            ]
        ),
    )

    registry = endpoint._configured_release_registry()

    assert registry is not None
    assert registry.collections == (
        COLLECTION,
        "rag_nexus_francais_seconde_tc",
    )
    assert endpoint.configured_release_model_contract() == registry.model_contract


def test_runtime_release_registry_refuses_ambiguous_legacy_and_multi_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor import retrieval_v2_endpoint as endpoint

    manifest, digest = _release_files(tmp_path)
    monkeypatch.setenv("RAG_RELEASE_MANIFEST_PATH", str(manifest))
    monkeypatch.setenv("RAG_RELEASE_MANIFEST_SHA256", digest)
    monkeypatch.setenv(
        "RAG_RELEASE_MANIFESTS_JSON",
        json.dumps([{"path": str(manifest), "sha256": digest}]),
    )

    with pytest.raises(ValueError, match="ambiguous"):
        endpoint._configured_release_registry()


def test_runtime_release_registry_keeps_single_manifest_compatibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor import retrieval_v2_endpoint as endpoint

    manifest, digest = _release_files(tmp_path)
    monkeypatch.delenv("RAG_RELEASE_MANIFESTS_JSON", raising=False)
    monkeypatch.setenv("RAG_RELEASE_MANIFEST_PATH", str(manifest))
    monkeypatch.setenv("RAG_RELEASE_MANIFEST_SHA256", digest)

    registry = endpoint._configured_release_registry()

    assert registry is not None
    assert registry.collections == (COLLECTION,)


def test_runtime_release_registry_refuses_non_explicit_or_malformed_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor import retrieval_v2_endpoint as endpoint

    monkeypatch.delenv("RAG_RELEASE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_SHA256", raising=False)
    for payload in (
        [{"path": str(tmp_path / "*.json"), "sha256": "1" * 64}],
        [{"path": str(tmp_path / "release.json")}],
        {"path": str(tmp_path / "release.json"), "sha256": "1" * 64},
    ):
        monkeypatch.setenv("RAG_RELEASE_MANIFESTS_JSON", json.dumps(payload))
        with pytest.raises(ValueError):
            endpoint._configured_release_registry()


def test_real_wave0_and_multilevel_registry_preserves_all_twelve_collections() -> None:
    bindings = tuple(
        (path, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in (WAVE0_RELEASE, MULTILEVEL_RELEASE)
    )

    registry = readiness.load_release_registry(bindings)

    assert len(registry.collections) == 12
    assert {
        "rag_nexus_maths_troisieme_tc",
        "rag_nexus_francais_troisieme_tc",
    } < set(registry.collections)
    assert len(
        set(registry.collections)
        - {
            "rag_nexus_maths_troisieme_tc",
            "rag_nexus_francais_troisieme_tc",
        }
    ) == 10
    assert registry.model_contract == (
        "intfloat/multilingual-e5-large",
        "e2c7384ba36096b3f3bdfff4973f728596104aff0f1d38f1b6463e60765fe22a",
        1024,
        "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "bdcedc4d7cfe647b9aaa5a7546822dfee7826ebb3c64472bf89eae7592e08fe1",
    )


def test_runtime_startup_accepts_wave0_and_multilevel_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yaml
    from nexus_contracts import load_retrieval_scope_registry

    from ingestor import retrieval_v2_endpoint as endpoint

    bindings = [
        {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in (WAVE0_RELEASE, MULTILEVEL_RELEASE)
    ]
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_SHA256", raising=False)
    monkeypatch.setenv("RAG_RELEASE_MANIFESTS_JSON", json.dumps(bindings))
    config = yaml.safe_load(CANONICAL_COLLECTIONS.read_text(encoding="utf-8"))

    endpoint.validate_release_startup_configuration(
        load_retrieval_scope_registry(),
        config,
    )
