"""Readiness Wave 0 : seul un manifest exactement matérialisé autorise le runtime."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor import release_readiness as readiness  # noqa: E402
from ingestor.release_readiness import (  # noqa: E402
    ReleaseDatabaseSnapshot,
    ReleaseReadinessError,
    collect_release_snapshot,
    evaluate_release_snapshot,
    load_release_expectation,
    load_release_registry_file,
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
RELEASE_REGISTRY = (
    REPO_ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json"
)
REHEARSAL_DIR = (
    REPO_ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027/rehearsal_v2"
)
_rehearsal_candidates = sorted(REHEARSAL_DIR.glob("release-*"))
REHEARSAL_RELEASE_REGISTRY = (
    _rehearsal_candidates[-1] / "release-registry.json"
    if _rehearsal_candidates
    else RELEASE_REGISTRY
)
PRODUCTION_PROFILE_RELEASE_ROOT = RELEASE_REGISTRY.parent / "profile_gate"

ARTIFACT_SHA = "a" * 64
PLACEMENT_ID = "b" * 64
CHUNK_ID = "c" * 64
CHUNK_SHA = "d" * 64
MODEL_ID = "intfloat/multilingual-e5-large"
SECOND_COLLECTION = "rag_nexus_nsi_terminale_spe"


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


def _v2_placement(collection: str, index: int) -> dict[str, object]:
    is_terminale = collection == SECOND_COLLECTION
    return {
        "placement_id": PLACEMENT_ID if index == 0 else f"{index + 3:x}" * 64,
        "artifact_id": ARTIFACT_SHA,
        "source_placement_id": f"catalog-placement-{index}",
        "source_scope": (
            "lycee/terminale/nsi" if is_terminale else "college/cycle-4/mathematiques"
        ),
        "collection": collection,
        "tenant": "libre_terminale" if is_terminale else "libre_troisieme",
        "niveau": "terminale" if is_terminale else "troisieme",
        "voie": "generale" if is_terminale else "college",
        "matiere": "nsi" if is_terminale else "maths",
        "statut_enseignement": "specialite" if is_terminale else "tronc_commun",
        "candidat": "both",
        "visibility": "internal",
        "school_year": "2026-2027",
        "programme_version": "BOEN_special_11_2018-07-26_aj_2020",
        "currentness": "current",
        "placement_status": "active",
        "review_status": "reviewed",
    }


def _v2_release_files(
    tmp_path: Path,
    *,
    collections: tuple[str, ...] = (COLLECTION,),
    extra_authorities: dict[str, str] | None = None,
) -> tuple[Path, str, Path, tuple[Path, ...]]:
    """Materialise le contrat V2 explicite, avant son implementation lecteur."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    authorities = _multilevel_authorities()
    authorities.update(extra_authorities or {})
    models = {
        "embedding": {
            "model_id": MODEL_ID,
            "inventory_sha256": "1" * 64,
            "dimension": 1024,
        },
        "reranker": {
            "model_id": "cross-encoder/ms-marco-MiniLM-L-6-v2",
            "inventory_sha256": "2" * 64,
        },
    }
    artifact = {
        "artifact_id": ARTIFACT_SHA,
        "content_sha256": ARTIFACT_SHA,
        "source_path": "01_EDUSCOL_OFFICIEL/LYCEE/NSI/a.pdf",
        "source_url": "https://eduscol.education.fr/document/a/download",
        "title": "Ressource commune multi-niveaux",
        "type_doc": "ressource_officielle",
        "page_count": 1,
        "ignored_empty_pages": [],
        "chunk_id_set_digest": _set_digest([CHUNK_ID]),
        "chunk_sha256_set_digest": _set_digest([CHUNK_SHA]),
        "page_coverage_digest": _set_digest([1]),
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
    registry = {
        "release_kind": "MULTILEVEL_ARTIFACT_REGISTRY_V2",
        "release_id": "multilevel-2026-2027",
        "school_year": "2026-2027",
        "expected_counts": {"unique_artifacts": 1, "unique_chunks": 1},
        "artifacts": [artifact],
    }
    registry_path = tmp_path / "artifacts.release.json"
    registry_sha = _write_json(registry_path, registry)

    subjects_dir = tmp_path / "subjects"
    subjects_dir.mkdir()
    subject_paths: list[Path] = []
    subject_entries: list[dict[str, str]] = []
    for index, collection in enumerate(collections):
        placement = _v2_placement(collection, index)
        subject = {
            "release_kind": "MULTILEVEL_SUBJECT_RELEASE_V2",
            # Derive du release_id de l agregat, comme le producteur et les sujets V1 reels.
            "release_id": f"multilevel-2026-2027-{collection}",
            "school_year": "2026-2027",
            "collection": collection,
            "programme_version": "BOEN_special_11_2018-07-26_aj_2020",
            "authorities": authorities,
            "profile": {
                "version": "1.0.0",
                "fingerprint": "e" * 64,
                "manifest_digest": authorities["profile_manifest_sha256"],
            },
            "models": models,
            "artifact_registry": {
                "path": f"../{registry_path.name}",
                "sha256": registry_sha,
            },
            "expected_counts": {
                "unique_artifact_references": 1,
                "placements": 1,
            },
            "placements": [placement],
        }
        subject_path = subjects_dir / f"subject-{index}.release.json"
        subject_sha = _write_json(subject_path, subject)
        subject_paths.append(subject_path)
        subject_entries.append(
            {
                "path": subject_path.relative_to(tmp_path).as_posix(),
                "sha256": subject_sha,
                "collection": collection,
            }
        )

    aggregate = {
        "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V2",
        "release_id": "multilevel-2026-2027",
        "school_year": "2026-2027",
        "authorities": authorities,
        "models": models,
        "artifact_registry": {
            "path": registry_path.name,
            "sha256": registry_sha,
        },
        "expected_counts": {
            "unique_artifacts": 1,
            "placements": len(collections),
            "unique_chunks": 1,
            "subjects": len(collections),
        },
        "subjects": subject_entries,
    }
    aggregate_path = tmp_path / "multilevel.release.json"
    aggregate_sha = _write_json(aggregate_path, aggregate)
    return aggregate_path, aggregate_sha, registry_path, tuple(subject_paths)


def _reseal_v2_release(
    aggregate_path: Path,
    registry_path: Path,
    subject_paths: tuple[Path, ...],
) -> str:
    """Propage les empreintes apres une mutation semantique de fixture."""

    registry_sha = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["artifact_registry"]["sha256"] = registry_sha
    for index, subject_path in enumerate(subject_paths):
        subject = json.loads(subject_path.read_text(encoding="utf-8"))
        subject["artifact_registry"]["sha256"] = registry_sha
        subject_sha = _write_json(subject_path, subject)
        aggregate["subjects"][index]["sha256"] = subject_sha
    return _write_json(aggregate_path, aggregate)


def _set_v2_page_partition(
    aggregate_path: Path,
    registry_path: Path,
    subject_paths: tuple[Path, ...],
    *,
    page_count: int,
    covered_pages: list[int],
    ignored_empty_pages: object,
) -> str:
    """Écrit puis rescelle une partition sémantique dans une fixture jetable."""
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    artifact = registry["artifacts"][0]
    chunks = [
        {
            "chunk_id": hashlib.sha256(f"chunk-id:{page}".encode()).hexdigest(),
            "chunk_index": index,
            "chunk_sha256": hashlib.sha256(f"chunk:{page}".encode()).hexdigest(),
            "page_start": page,
            "page_end": page,
        }
        for index, page in enumerate(covered_pages)
    ]
    artifact["page_count"] = page_count
    artifact["ignored_empty_pages"] = ignored_empty_pages
    artifact["chunks"] = chunks
    artifact["chunk_id_set_digest"] = _set_digest(
        [chunk["chunk_id"] for chunk in chunks]
    )
    artifact["chunk_sha256_set_digest"] = _set_digest(
        [chunk["chunk_sha256"] for chunk in chunks]
    )
    # Ce digest garde sa sémantique historique : pages des chunks uniquement.
    artifact["page_coverage_digest"] = _set_digest(covered_pages)
    registry["expected_counts"]["unique_chunks"] = len(chunks)
    _write_json(registry_path, registry)
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["expected_counts"]["unique_chunks"] = len(chunks)
    _write_json(aggregate_path, aggregate)
    return _reseal_v2_release(aggregate_path, registry_path, subject_paths)


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


def test_v2_one_global_artifact_and_one_placement_is_accepted(
    tmp_path: Path,
) -> None:
    manifest, digest, _registry, _subjects = _v2_release_files(tmp_path)

    expectation = load_release_expectation(manifest, digest)

    assert expectation.release_kind == "MULTILEVEL_AGGREGATE_RELEASE_V2"
    assert expectation.collections == (COLLECTION,)
    assert len(expectation.artifacts) == 1
    assert expectation.artifacts[0].content_sha256 == ARTIFACT_SHA
    assert len(expectation.placements) == 1
    assert expectation.placements[0].artifact_id == ARTIFACT_SHA


def test_v2_one_global_artifact_with_two_subject_placements_is_accepted(
    tmp_path: Path,
) -> None:
    manifest, digest, _registry, _subjects = _v2_release_files(
        tmp_path,
        collections=(COLLECTION, SECOND_COLLECTION),
    )

    expectation = load_release_expectation(manifest, digest)

    assert expectation.collections == (COLLECTION, SECOND_COLLECTION)
    assert len(expectation.artifacts) == 1
    assert len(expectation.placements) == 2
    assert {placement.artifact_id for placement in expectation.placements} == {ARTIFACT_SHA}


def test_v1_complete_artifact_without_ignored_empty_pages_remains_accepted(
    tmp_path: Path,
) -> None:
    manifest, digest = _release_files(tmp_path)
    subject = json.loads(
        (tmp_path / "maths_troisieme.release.json").read_text(encoding="utf-8")
    )

    assert "ignored_empty_pages" not in subject["artifacts"][0]
    assert len(load_release_expectation(manifest, digest).artifacts) == 1


def test_v2_canonical_empty_page_partition_is_accepted(tmp_path: Path) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    digest = _set_v2_page_partition(
        manifest,
        registry_path,
        subject_paths,
        page_count=3,
        covered_pages=[1, 3],
        ignored_empty_pages=[2],
    )

    expectation = load_release_expectation(manifest, digest)

    assert [
        (chunk["page_start"], chunk["page_end"])
        for chunk in expectation.artifacts[0].chunks
    ] == [(1, 1), (3, 3)]


@pytest.mark.parametrize(
    ("page_count", "covered_pages", "ignored_empty_pages"),
    [
        (1, [1], [1]),
        (2, [1], []),
        (1, [1], [2]),
        (3, [1, 3], [2, 2]),
        (3, [1], [3, 2]),
        (2, [2], [True]),
        (2, [1], ["2"]),
        (2, [1], [2.0]),
        (2, [1], None),
    ],
    ids=(
        "overlap",
        "unexplained-hole",
        "out-of-bounds",
        "duplicate",
        "not-sorted",
        "bool",
        "string",
        "float",
        "not-an-array",
    ),
)
def test_v2_noncanonical_or_incomplete_empty_page_partition_is_refused(
    tmp_path: Path,
    page_count: int,
    covered_pages: list[int],
    ignored_empty_pages: object,
) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    digest = _set_v2_page_partition(
        manifest,
        registry_path,
        subject_paths,
        page_count=page_count,
        covered_pages=covered_pages,
        ignored_empty_pages=ignored_empty_pages,
    )

    with pytest.raises(
        ReleaseReadinessError,
        match=r"ignored_empty_pages|page partition|page coverage",
    ):
        load_release_expectation(manifest, digest)


def test_v2_page_coverage_digest_still_names_chunk_pages_only(
    tmp_path: Path,
) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    digest = _set_v2_page_partition(
        manifest,
        registry_path,
        subject_paths,
        page_count=3,
        covered_pages=[1, 3],
        ignored_empty_pages=[2],
    )
    load_release_expectation(manifest, digest)

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["artifacts"][0]["page_coverage_digest"] = _set_digest([1, 2, 3])
    _write_json(registry_path, registry)
    digest = _reseal_v2_release(manifest, registry_path, subject_paths)

    with pytest.raises(ReleaseReadinessError, match="page_coverage_digest"):
        load_release_expectation(manifest, digest)


def test_v2_unresealed_ignored_empty_pages_sabotage_is_refused(
    tmp_path: Path,
) -> None:
    manifest, digest, registry_path, _subject_paths = _v2_release_files(tmp_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["artifacts"][0]["ignored_empty_pages"] = [1]
    _write_json(registry_path, registry)

    with pytest.raises(ReleaseReadinessError, match="digest"):
        load_release_expectation(manifest, digest)


def test_v2_eligibility_full_chain_loads_two_placements_for_one_artifact(
    tmp_path: Path,
) -> None:
    from ingestor.multilevel_verified_placement import (
        load_multilevel_release_eligibility,
    )

    manifest, digest, _registry, _subjects = _v2_release_files(
        tmp_path,
        collections=(COLLECTION, SECOND_COLLECTION),
    )

    eligibility = load_multilevel_release_eligibility(
        manifest,
        expected_sha256=digest,
    )

    assert len(eligibility.placements) == 2
    assert {placement.collection for placement in eligibility.placements} == {
        COLLECTION,
        SECOND_COLLECTION,
    }
    assert {placement.content_sha256 for placement in eligibility.placements} == {
        ARTIFACT_SHA
    }


def test_v2_duplicate_global_artifact_definition_is_refused(
    tmp_path: Path,
) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["artifacts"].append(copy.deepcopy(registry["artifacts"][0]))
    _write_json(registry_path, registry)
    digest = _reseal_v2_release(manifest, registry_path, subject_paths)

    with pytest.raises(ReleaseReadinessError, match="duplicate artifact"):
        load_release_expectation(manifest, digest)


@pytest.mark.parametrize("collision", ["chunk_id", "artifact_chunk_index"])
def test_v2_duplicate_global_chunk_definition_is_refused(
    tmp_path: Path,
    collision: str,
) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    artifact = registry["artifacts"][0]
    duplicate = copy.deepcopy(artifact["chunks"][0])
    if collision == "chunk_id":
        duplicate["chunk_index"] = 1
    else:
        duplicate["chunk_id"] = "9" * 64
        duplicate["chunk_sha256"] = "8" * 64
    artifact["chunks"].append(duplicate)
    artifact["chunk_id_set_digest"] = _set_digest(
        [chunk["chunk_id"] for chunk in artifact["chunks"]]
    )
    artifact["chunk_sha256_set_digest"] = _set_digest(
        [chunk["chunk_sha256"] for chunk in artifact["chunks"]]
    )
    registry["expected_counts"]["unique_chunks"] = len(
        {chunk["chunk_id"] for chunk in artifact["chunks"]}
    )
    _write_json(registry_path, registry)
    digest = _reseal_v2_release(manifest, registry_path, subject_paths)

    with pytest.raises(ReleaseReadinessError, match="duplicate chunk"):
        load_release_expectation(manifest, digest)


def test_v2_placement_reference_to_absent_artifact_is_refused(
    tmp_path: Path,
) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    subject = json.loads(subject_paths[0].read_text(encoding="utf-8"))
    subject["placements"][0]["artifact_id"] = "9" * 64
    _write_json(subject_paths[0], subject)
    digest = _reseal_v2_release(manifest, registry_path, subject_paths)

    with pytest.raises(
        ReleaseReadinessError,
        match="unknown artifact|absent artifact|missing artifact",
    ):
        load_release_expectation(manifest, digest)


def test_v2_unreferenced_global_artifact_is_refused(tmp_path: Path) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    orphan = copy.deepcopy(registry["artifacts"][0])
    orphan["artifact_id"] = "9" * 64
    orphan["content_sha256"] = "9" * 64
    orphan["chunks"][0]["chunk_id"] = "8" * 64
    orphan["chunks"][0]["chunk_sha256"] = "7" * 64
    orphan["chunk_id_set_digest"] = _set_digest(["8" * 64])
    orphan["chunk_sha256_set_digest"] = _set_digest(["7" * 64])
    registry["artifacts"].append(orphan)
    registry["expected_counts"] = {"unique_artifacts": 2, "unique_chunks": 2}
    _write_json(registry_path, registry)
    aggregate = json.loads(manifest.read_text(encoding="utf-8"))
    aggregate["expected_counts"]["unique_artifacts"] = 2
    aggregate["expected_counts"]["unique_chunks"] = 2
    _write_json(manifest, aggregate)
    digest = _reseal_v2_release(manifest, registry_path, subject_paths)

    with pytest.raises(
        ReleaseReadinessError,
        match="orphan artifact|unreferenced artifact",
    ):
        load_release_expectation(manifest, digest)


def test_v2_two_placements_for_same_artifact_in_one_subject_are_refused(
    tmp_path: Path,
) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    subject = json.loads(subject_paths[0].read_text(encoding="utf-8"))
    duplicate_reference = copy.deepcopy(subject["placements"][0])
    duplicate_reference["placement_id"] = "9" * 64
    duplicate_reference["source_placement_id"] = "catalog-placement-duplicate"
    subject["placements"].append(duplicate_reference)
    subject["expected_counts"]["placements"] = 2
    _write_json(subject_paths[0], subject)
    aggregate = json.loads(manifest.read_text(encoding="utf-8"))
    aggregate["expected_counts"]["placements"] = 2
    _write_json(manifest, aggregate)
    digest = _reseal_v2_release(manifest, registry_path, subject_paths)

    with pytest.raises(
        ReleaseReadinessError,
        match="duplicate artifact reference|duplicate placement for artifact",
    ):
        load_release_expectation(manifest, digest)


def test_v2_two_subjects_reference_one_definition_without_divergence(
    tmp_path: Path,
) -> None:
    manifest, digest, registry_path, subject_paths = _v2_release_files(
        tmp_path,
        collections=(COLLECTION, SECOND_COLLECTION),
    )

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    subjects = [json.loads(path.read_text(encoding="utf-8")) for path in subject_paths]
    expectation = load_release_expectation(manifest, digest)

    assert len(registry["artifacts"]) == 1
    assert all("artifacts" not in subject for subject in subjects)
    assert all("chunks" not in subject for subject in subjects)
    assert [subject["placements"][0]["artifact_id"] for subject in subjects] == [
        ARTIFACT_SHA,
        ARTIFACT_SHA,
    ]
    assert len(expectation.artifacts) == 1
    assert len(expectation.placements) == 2
    assert {placement.artifact_id for placement in expectation.placements} == {ARTIFACT_SHA}


@pytest.mark.parametrize("forbidden_field", ["artifacts", "chunks"])
def test_v2_subject_cannot_redefine_artifacts_or_chunks(
    tmp_path: Path,
    forbidden_field: str,
) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    subject = json.loads(subject_paths[0].read_text(encoding="utf-8"))
    subject[forbidden_field] = []
    _write_json(subject_paths[0], subject)
    digest = _reseal_v2_release(manifest, registry_path, subject_paths)

    with pytest.raises(
        ReleaseReadinessError,
        match="must not define artifacts or chunks",
    ):
        load_release_expectation(manifest, digest)


def test_v2_subject_unrelated_extra_field_reports_only_schema_mismatch(
    tmp_path: Path,
) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    subject = json.loads(subject_paths[0].read_text(encoding="utf-8"))
    subject["comment"] = "not part of the sealed subject contract"
    _write_json(subject_paths[0], subject)
    digest = _reseal_v2_release(manifest, registry_path, subject_paths)

    with pytest.raises(ReleaseReadinessError) as exc_info:
        load_release_expectation(manifest, digest)

    assert "fields mismatch" in str(exc_info.value)
    assert "must not define artifacts or chunks" not in str(exc_info.value)


@pytest.mark.parametrize("mutation", ["artifact_fact", "chunk"])
def test_v2_unresealed_global_artifact_mutation_breaks_registry_digest(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest, digest, registry_path, _subject_paths = _v2_release_files(tmp_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if mutation == "artifact_fact":
        registry["artifacts"][0]["title"] = "Titre sabote"
    else:
        registry["artifacts"][0]["chunks"][0]["page_end"] = 2
    _write_json(registry_path, registry)

    with pytest.raises(ReleaseReadinessError, match="artifact registry digest mismatch"):
        load_release_expectation(manifest, digest)


def test_v2_unresealed_placement_mutation_breaks_subject_digest(
    tmp_path: Path,
) -> None:
    manifest, digest, _registry_path, subject_paths = _v2_release_files(tmp_path)
    subject = json.loads(subject_paths[0].read_text(encoding="utf-8"))
    subject["placements"][0]["tenant"] = "libre_seconde"
    _write_json(subject_paths[0], subject)

    with pytest.raises(ReleaseReadinessError, match="subject release manifest digest mismatch"):
        load_release_expectation(manifest, digest)


def test_v2_unresealed_subject_reference_removal_breaks_subject_digest(
    tmp_path: Path,
) -> None:
    manifest, digest, _registry_path, subject_paths = _v2_release_files(tmp_path)
    subject = json.loads(subject_paths[0].read_text(encoding="utf-8"))
    subject["placements"].clear()
    _write_json(subject_paths[0], subject)

    with pytest.raises(ReleaseReadinessError, match="subject release manifest digest mismatch"):
        load_release_expectation(manifest, digest)


@pytest.mark.parametrize(
    ("forbidden_field", "value"),
    [
        ("collection", COLLECTION),
        ("placements", []),
        ("profile", {"version": "owner-v1"}),
        ("placement", {"collection": COLLECTION}),
    ],
)
def test_v2_global_artifact_schema_rejects_placement_owned_fields_after_reseal(
    tmp_path: Path,
    forbidden_field: str,
    value: object,
) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["artifacts"][0][forbidden_field] = value
    _write_json(registry_path, registry)
    digest = _reseal_v2_release(manifest, registry_path, subject_paths)

    with pytest.raises(ReleaseReadinessError, match="artifact.*fields mismatch"):
        load_release_expectation(manifest, digest)


@pytest.mark.parametrize(
    ("forbidden_field", "value"),
    [
        ("collection", COLLECTION),
        ("artifact_id", ARTIFACT_SHA),
        ("owner", ARTIFACT_SHA),
        ("title", "Copie intrinseque interdite"),
    ],
)
def test_v2_global_chunk_schema_rejects_owner_fields_after_reseal(
    tmp_path: Path,
    forbidden_field: str,
    value: object,
) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["artifacts"][0]["chunks"][0][forbidden_field] = value
    _write_json(registry_path, registry)
    digest = _reseal_v2_release(manifest, registry_path, subject_paths)

    with pytest.raises(ReleaseReadinessError, match="chunk.*fields mismatch"):
        load_release_expectation(manifest, digest)


@pytest.mark.parametrize(
    ("forbidden_field", "value"),
    [
        ("chunks", []),
        ("title", "Copie du titre de l'artefact"),
        ("source_path", "copie/interdite.pdf"),
        ("source_url", "https://example.invalid/copie.pdf"),
    ],
)
def test_v2_placement_schema_rejects_intrinsic_artifact_fields_after_reseal(
    tmp_path: Path,
    forbidden_field: str,
    value: object,
) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    subject = json.loads(subject_paths[0].read_text(encoding="utf-8"))
    subject["placements"][0][forbidden_field] = value
    _write_json(subject_paths[0], subject)
    digest = _reseal_v2_release(manifest, registry_path, subject_paths)

    with pytest.raises(ReleaseReadinessError, match="placement.*fields mismatch"):
        load_release_expectation(manifest, digest)


def test_v2_expected_placements_preserve_each_subject_profile(
    tmp_path: Path,
) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(
        tmp_path,
        collections=(COLLECTION, SECOND_COLLECTION),
    )
    expected: list[tuple[str, str, str, str, str]] = []
    for index, subject_path in enumerate(subject_paths):
        subject = json.loads(subject_path.read_text(encoding="utf-8"))
        programme_version = f"programme-profil-{index}"
        profile_version = f"profil-v{index + 1}"
        profile_fingerprint = f"{index + 3}" * 64
        profile_manifest_digest = subject["authorities"]["profile_manifest_sha256"]
        subject["programme_version"] = programme_version
        subject["profile"] = {
            "version": profile_version,
            "fingerprint": profile_fingerprint,
            "manifest_digest": profile_manifest_digest,
        }
        subject["placements"][0]["programme_version"] = programme_version
        _write_json(subject_path, subject)
        expected.append(
            (
                subject["collection"],
                programme_version,
                profile_version,
                profile_fingerprint,
                profile_manifest_digest,
            )
        )
    digest = _reseal_v2_release(manifest, registry_path, subject_paths)

    expectation = load_release_expectation(manifest, digest)

    observed = [
        (
            placement.collection,
            placement.programme_version,
            placement.profile_version,
            placement.profile_fingerprint,
            placement.profile_manifest_digest,
        )
        for placement in expectation.placements
    ]
    assert observed == expected
    assert len({row[1:4] for row in observed}) == 2


@pytest.mark.parametrize(
    "path_owner",
    ["aggregate_artifact_registry", "subject_artifact_registry", "subject_entry"],
)
def test_v2_release_rejects_absolute_internal_paths_after_reseal(
    tmp_path: Path,
    path_owner: str,
) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    if path_owner == "aggregate_artifact_registry":
        aggregate = json.loads(manifest.read_text(encoding="utf-8"))
        aggregate["artifact_registry"]["path"] = str(registry_path.resolve())
        digest = _write_json(manifest, aggregate)
    elif path_owner == "subject_artifact_registry":
        subject = json.loads(subject_paths[0].read_text(encoding="utf-8"))
        subject["artifact_registry"]["path"] = str(registry_path.resolve())
        _write_json(subject_paths[0], subject)
        digest = _reseal_v2_release(manifest, registry_path, subject_paths)
    else:
        aggregate = json.loads(manifest.read_text(encoding="utf-8"))
        aggregate["subjects"][0]["path"] = str(subject_paths[0].resolve())
        digest = _write_json(manifest, aggregate)

    with pytest.raises(ReleaseReadinessError, match="relative"):
        load_release_expectation(manifest, digest)


@pytest.mark.parametrize(
    ("layer", "counter", "sabotaged_value"),
    [
        ("registry", "unique_artifacts", 2),
        ("registry", "unique_artifacts", True),
        ("registry", "unique_chunks", 2),
        ("registry", "unique_chunks", True),
        ("subject", "unique_artifact_references", 2),
        ("subject", "unique_artifact_references", True),
        ("subject", "placements", 2),
        ("subject", "placements", True),
        ("aggregate", "unique_artifacts", 2),
        ("aggregate", "unique_artifacts", True),
        ("aggregate", "placements", 2),
        ("aggregate", "placements", True),
        ("aggregate", "unique_chunks", 2),
        ("aggregate", "unique_chunks", True),
        ("aggregate", "subjects", 2),
        ("aggregate", "subjects", True),
    ],
)
def test_v2_release_rejects_sabotaged_exact_counts_after_reseal(
    tmp_path: Path,
    layer: str,
    counter: str,
    sabotaged_value: object,
) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    if layer == "registry":
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["expected_counts"][counter] = sabotaged_value
        _write_json(registry_path, registry)
        digest = _reseal_v2_release(manifest, registry_path, subject_paths)
    elif layer == "subject":
        subject = json.loads(subject_paths[0].read_text(encoding="utf-8"))
        subject["expected_counts"][counter] = sabotaged_value
        _write_json(subject_paths[0], subject)
        digest = _reseal_v2_release(manifest, registry_path, subject_paths)
    else:
        aggregate = json.loads(manifest.read_text(encoding="utf-8"))
        aggregate["expected_counts"][counter] = sabotaged_value
        digest = _write_json(manifest, aggregate)

    with pytest.raises(ReleaseReadinessError, match="expected_counts.*mismatch"):
        load_release_expectation(manifest, digest)


def test_v2_same_placement_id_in_two_subjects_is_refused(
    tmp_path: Path,
) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(
        tmp_path,
        collections=(COLLECTION, SECOND_COLLECTION),
    )
    second_subject = json.loads(subject_paths[1].read_text(encoding="utf-8"))
    second_subject["placements"][0]["placement_id"] = PLACEMENT_ID
    _write_json(subject_paths[1], second_subject)
    digest = _reseal_v2_release(manifest, registry_path, subject_paths)

    with pytest.raises(
        ReleaseReadinessError,
        match="placement is duplicated across subjects",
    ):
        load_release_expectation(manifest, digest)


@pytest.mark.parametrize(
    ("layer", "wrong_kind"),
    [
        ("aggregate", "MULTILEVEL_SUBJECT_RELEASE_V2"),
        ("aggregate", "NOT_A_RELEASE_KIND"),
        ("registry", "MULTILEVEL_AGGREGATE_RELEASE_V2"),
        ("registry", "NOT_A_RELEASE_KIND"),
        ("subject", "MULTILEVEL_ARTIFACT_REGISTRY_V2"),
        ("subject", "NOT_A_RELEASE_KIND"),
    ],
)
def test_v2_release_rejects_crossed_or_unknown_kinds_after_reseal(
    tmp_path: Path,
    layer: str,
    wrong_kind: str,
) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    if layer == "aggregate":
        aggregate = json.loads(manifest.read_text(encoding="utf-8"))
        aggregate["release_kind"] = wrong_kind
        digest = _write_json(manifest, aggregate)
    elif layer == "registry":
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["release_kind"] = wrong_kind
        _write_json(registry_path, registry)
        digest = _reseal_v2_release(manifest, registry_path, subject_paths)
    else:
        subject = json.loads(subject_paths[0].read_text(encoding="utf-8"))
        subject["release_kind"] = wrong_kind
        _write_json(subject_paths[0], subject)
        digest = _reseal_v2_release(manifest, registry_path, subject_paths)

    with pytest.raises(ReleaseReadinessError, match="kind.*unsupported|kind is unsupported"):
        load_release_expectation(manifest, digest)


@pytest.mark.parametrize("drift", ["path", "digest"])
def test_v2_subject_registry_reference_must_equal_aggregate_reference(
    tmp_path: Path,
    drift: str,
) -> None:
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    subject = json.loads(subject_paths[0].read_text(encoding="utf-8"))
    if drift == "path":
        other_registry = tmp_path / "artifacts-copy.release.json"
        shutil.copyfile(registry_path, other_registry)
        subject["artifact_registry"]["path"] = f"../{other_registry.name}"
    else:
        subject["artifact_registry"]["sha256"] = "9" * 64
    subject_sha = _write_json(subject_paths[0], subject)
    aggregate = json.loads(manifest.read_text(encoding="utf-8"))
    aggregate["subjects"][0]["sha256"] = subject_sha
    digest = _write_json(manifest, aggregate)

    with pytest.raises(ReleaseReadinessError, match="artifact_registry.*mismatch"):
        load_release_expectation(manifest, digest)


@pytest.mark.parametrize(
    "release_id",
    [
        "multilevel-2026-2027",
        "autre-release-2026-2027",
        f"multilevel-2026-2027-{COLLECTION}-bis",
        "multilevel-2026-2027-rag_nexus_autre_collection",
    ],
)
def test_v2_subject_release_id_must_derive_from_aggregate_after_reseal(
    tmp_path: Path,
    release_id: str,
) -> None:
    """Un sujet V2 n'a pas d'identite libre : son release_id est derive de celui
    de l'agregat et de sa collection. Un sujet rescelle sous un autre release_id
    (autre release, autre collection, suffixe arbitraire) est refuse."""
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    subject = json.loads(subject_paths[0].read_text(encoding="utf-8"))
    subject["release_id"] = release_id
    _write_json(subject_paths[0], subject)
    digest = _reseal_v2_release(manifest, registry_path, subject_paths)

    with pytest.raises(ReleaseReadinessError, match=r"release_id"):
        load_release_expectation(manifest, digest)


def test_v2_subject_moved_to_another_collection_is_refused_after_reseal(
    tmp_path: Path,
) -> None:
    """Un sujet valide, rescelle sous une autre collection dans l'agregat ET dans
    son propre champ, garde des placements et un release_id de sa collection
    d'origine : l'identite du sujet n'est pas un nom, c'est son contenu."""
    manifest, _digest, registry_path, subject_paths = _v2_release_files(tmp_path)
    subject = json.loads(subject_paths[0].read_text(encoding="utf-8"))
    subject["collection"] = SECOND_COLLECTION
    _write_json(subject_paths[0], subject)
    aggregate = json.loads(manifest.read_text(encoding="utf-8"))
    aggregate["subjects"][0]["collection"] = SECOND_COLLECTION
    _write_json(manifest, aggregate)
    digest = _reseal_v2_release(manifest, registry_path, subject_paths)

    with pytest.raises(ReleaseReadinessError):
        load_release_expectation(manifest, digest)


def test_v2_subject_of_another_release_with_same_ids_is_refused_by_the_registry(
    tmp_path: Path,
) -> None:
    """Deux releases portent le meme release_id et la meme collection ; le sujet
    de la seconde (contenu different : autre placement_id) est substitue dans la
    premiere puis tout est rescelle. Le registre, qui epingle l'agregat exact,
    refuse : le nom `release_id` n'est jamais une identite a lui seul."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest, digest, registry_path, subject_paths = _v2_release_files(first)
    registry_file, registry_digest = _write_registry(
        tmp_path,
        {
            "registry_version": "1",
            "school_year": "2026-2027",
            "releases": [
                _registry_entry(
                    manifest,
                    digest,
                    release_id="multilevel-2026-2027",
                    collections=[COLLECTION],
                    registry_root=tmp_path,
                    release_kind="MULTILEVEL_AGGREGATE_RELEASE_V2",
                )
            ],
        },
    )
    loaded = load_release_registry_file(registry_file, registry_digest)
    assert loaded.manifests[0].expectation.release_id == "multilevel-2026-2027"
    _other_manifest, _other_digest, _other_registry, other_subjects = _v2_release_files(second)
    other_subject = json.loads(other_subjects[0].read_text(encoding="utf-8"))
    other_subject["placements"][0]["placement_id"] = "e" * 64
    _write_json(subject_paths[0], other_subject)
    resealed = _reseal_v2_release(manifest, registry_path, subject_paths)
    assert resealed != digest
    assert load_release_expectation(manifest, resealed).placements[0].payload[
        "placement_id"
    ] == "e" * 64

    with pytest.raises(ReleaseReadinessError, match="digest mismatch"):
        load_release_registry_file(registry_file, registry_digest)


def test_release_registry_file_loads_v2_then_detects_aggregate_sabotage(
    tmp_path: Path,
) -> None:
    manifest, digest, _registry_path, _subject_paths = _v2_release_files(
        tmp_path / "multilevel-v2",
        collections=(COLLECTION, SECOND_COLLECTION),
    )
    registry_path, registry_digest = _write_registry(
        tmp_path,
        {
            "registry_version": "1",
            "school_year": "2026-2027",
            "releases": [
                _registry_entry(
                    manifest,
                    digest,
                    release_id="multilevel-2026-2027",
                    collections=[COLLECTION, SECOND_COLLECTION],
                    registry_root=tmp_path,
                    release_kind="MULTILEVEL_AGGREGATE_RELEASE_V2",
                )
            ],
        },
    )

    loaded = load_release_registry_file(registry_path, registry_digest)

    assert loaded.collections == (COLLECTION, SECOND_COLLECTION)
    assert loaded.manifests[0].expectation.release_kind == ("MULTILEVEL_AGGREGATE_RELEASE_V2")
    aggregate = json.loads(manifest.read_text(encoding="utf-8"))
    aggregate["expected_counts"]["subjects"] = 99
    _write_json(manifest, aggregate)
    with pytest.raises(ReleaseReadinessError, match="digest mismatch"):
        load_release_registry_file(registry_path, registry_digest)


def test_v1_valid_manifest_remains_accepted(tmp_path: Path) -> None:
    manifest, digest = _release_files(tmp_path)

    expectation = load_release_expectation(manifest, digest)

    assert expectation.release_kind == "WAVE0_AGGREGATE_RELEASE_V1"
    assert len(expectation.artifacts) == 1
    assert expectation.artifacts[0].collection == COLLECTION


def test_v2_global_artifact_has_no_owner_collection(tmp_path: Path) -> None:
    manifest, digest, _registry, _subjects = _v2_release_files(tmp_path)

    expectation = load_release_expectation(manifest, digest)

    assert expectation.artifacts[0].collection is None


def _shared_artifact_two_subjects(
    tmp_path: Path,
    *,
    mutate_second_artifact: Callable[[dict], None] | None = None,
) -> tuple[Path, str]:
    """Build a WAVE0 aggregate whose one physical artifact is placed in two
    subjects (première + terminale style sharing): same content_sha256, same
    chunks, distinct placement_id/collection per subject — the exact shape of
    the 167 artifacts genuinely shared across the real production release.

    ``mutate_second_artifact`` lets a caller corrupt the second subject's copy
    of the artifact (divergent-content counter-proof) after the placement is
    rewired but before the file is sealed.
    """
    aggregate_path, _digest = _release_files(tmp_path)
    first_subject_path = tmp_path / "maths_troisieme.release.json"
    first_subject = json.loads(first_subject_path.read_text(encoding="utf-8"))
    second_subject = copy.deepcopy(first_subject)
    second_subject["collection"] = SECOND_COLLECTION
    second_artifact = second_subject["artifacts"][0]
    second_placement = second_artifact["placements"][0]
    second_placement["placement_id"] = "9" * 64
    second_placement["collection"] = SECOND_COLLECTION
    second_artifact["placement_id_set_digest"] = _set_digest(
        [second_placement["placement_id"]]
    )
    if mutate_second_artifact is not None:
        mutate_second_artifact(second_artifact)
    second_path = tmp_path / "nsi_terminale.release.json"
    second_sha = _write_json(second_path, second_subject)
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["subjects"].append(
        {
            "path": second_path.name,
            "sha256": second_sha,
            "collection": SECOND_COLLECTION,
        }
    )
    aggregate["expected_counts"] = {
        "artifacts": 2,
        "placements": 2,
        "chunks": 2,
    }
    digest = _write_json(aggregate_path, aggregate)
    return aggregate_path, digest


def test_v1_identical_shared_artifact_across_subjects_is_accepted(
    tmp_path: Path,
) -> None:
    """One physical artifact placed in two subjects, byte-identical content:
    exactly the multi-placement pattern already sealed 167 times in the real
    production-profile-gate-2026-2027-v1 release (rag_artifact_placements is
    the authority for reachability, not a one-artifact-one-collection rule).
    """
    aggregate_path, digest = _shared_artifact_two_subjects(tmp_path)

    expectation = load_release_expectation(aggregate_path, digest)

    assert len(expectation.artifacts) == 2
    assert len({a.content_sha256 for a in expectation.artifacts}) == 1
    assert {a.collection for a in expectation.artifacts} == {COLLECTION, SECOND_COLLECTION}
    assert len(expectation.placements) == 2
    assert {p.collection for p in expectation.placements} == {COLLECTION, SECOND_COLLECTION}


def test_v1_divergent_shared_artifact_across_subjects_is_refused(
    tmp_path: Path,
) -> None:
    """Same content_sha256 claimed by two subjects, but the chunk content
    disagrees — a real corruption, not legitimate sharing. Must stay refused."""

    def diverge(second_artifact: dict) -> None:
        second_artifact["chunks"][0]["chunk_sha256"] = "8" * 64
        second_artifact["chunk_sha256_set_digest"] = _set_digest(["8" * 64])

    aggregate_path, digest = _shared_artifact_two_subjects(
        tmp_path, mutate_second_artifact=diverge
    )

    with pytest.raises(
        ReleaseReadinessError,
        match="artifact is duplicated across subjects",
    ):
        load_release_expectation(aggregate_path, digest)


def test_v1_duplicate_artifact_within_same_subject_remains_refused(
    tmp_path: Path,
) -> None:
    """The same content_sha256 listed twice inside ONE subject's own artifact
    list is never legitimate sharing (a subject owns each of its placements
    once) — unaffected by the cross-subject sharing fix."""
    aggregate_path, _digest = _release_files(tmp_path)
    subject_path = tmp_path / "maths_troisieme.release.json"
    subject = json.loads(subject_path.read_text(encoding="utf-8"))
    duplicate_artifact = copy.deepcopy(subject["artifacts"][0])
    duplicate_artifact["placements"][0]["placement_id"] = "9" * 64
    duplicate_artifact["placement_id_set_digest"] = _set_digest(["9" * 64])
    subject["artifacts"].append(duplicate_artifact)
    subject["expected_counts"]["artifacts"] = 2
    subject["expected_counts"]["placements"] = 2
    subject_sha = _write_json(subject_path, subject)
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    aggregate["subjects"][0]["sha256"] = subject_sha
    aggregate["expected_counts"] = {"artifacts": 2, "placements": 2, "chunks": 2}
    digest = _write_json(aggregate_path, aggregate)

    with pytest.raises(ReleaseReadinessError, match="contains duplicate artifacts"):
        load_release_expectation(aggregate_path, digest)


def test_v1_conflicting_placement_identity_across_subjects_remains_refused(
    tmp_path: Path,
) -> None:
    """Two subjects independently claiming the SAME placement_id for what the
    manifest treats as two different artifacts is a real identity conflict —
    never legitimate sharing, regardless of the artifact-content fix."""

    def reuse_placement_id(second_artifact: dict) -> None:
        # Overwrite the freshly-rewired placement_id back to the first
        # subject's own placement_id, and change the content so this is
        # unambiguously a different artifact colliding on placement identity,
        # not the legitimate shared-artifact case.
        second_artifact["placements"][0]["placement_id"] = PLACEMENT_ID
        second_artifact["placement_id_set_digest"] = _set_digest([PLACEMENT_ID])
        second_artifact["content_sha256"] = "7" * 64
        second_artifact["chunks"][0]["chunk_id"] = "6" * 64
        second_artifact["chunk_id_set_digest"] = _set_digest(["6" * 64])

    aggregate_path, digest = _shared_artifact_two_subjects(
        tmp_path, mutate_second_artifact=reuse_placement_id
    )

    with pytest.raises(
        ReleaseReadinessError,
        match="placement is duplicated across subjects",
    ):
        load_release_expectation(aggregate_path, digest)


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
    subject["profile"]["manifest_digest"] = authorities[
        "profile_manifest_sha256"
    ]
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
    chunk_cursor = connection.cursors[2]
    assert "WHERE collection = ANY(%s) OR artifact_id = ANY(%s)" in chunk_cursor.sql
    # No placements were returned for this collection, so the placement-derived
    # artifact_id scope is empty -- the chunk-tag scope alone still governs.
    assert chunk_cursor.params == ([COLLECTION], [])


def test_v2_database_snapshot_scopes_shared_chunks_by_artifact_identity(
    tmp_path: Path,
) -> None:
    manifest, digest, _registry, _subjects = _v2_release_files(
        tmp_path,
        collections=(COLLECTION, SECOND_COLLECTION),
    )
    expectation = load_release_expectation(manifest, digest)

    artifact_row = (
        ARTIFACT_SHA,
        ARTIFACT_SHA,
        "eduscol.education.fr",
        "https://eduscol.education.fr/document/a/download",
        "officiel_public",
        True,
        "eduscol.education.fr",
        "ressource_officielle",
    )
    placement_rows: list[tuple[object, ...]] = []
    for index, collection in enumerate((COLLECTION, SECOND_COLLECTION)):
        placement = _v2_placement(collection, index)
        placement_row = {
            **placement,
            "source_path": "01_EDUSCOL_OFFICIEL/LYCEE/NSI/a.pdf",
            "source_uri": "https://eduscol.education.fr/document/a/download",
            "authorization_id": f"LOT12-V2:auth:{index}",
            "publication_attestation_id": f"00000000-0000-0000-0000-{index + 1:012d}",
        }
        placement_rows.append(
            tuple(placement_row[column] for column in readiness._PLACEMENT_COLUMNS)
        )
    # La colonne historique est scalaire et porte ici la première collection.
    # Elle ne doit pas empêcher la seconde référence sujet de voir le chunk.
    chunk_row = (
        CHUNK_ID,
        ARTIFACT_SHA,
        COLLECTION,
        0,
        CHUNK_SHA,
        1,
        1,
        "reviewed",
        MODEL_ID,
        True,
        1024,
    )

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
                Cursor(placement_rows),
                Cursor([artifact_row]),
                Cursor([chunk_row]),
            ]
            self.index = 0

        def cursor(self) -> Cursor:
            cursor = self.cursors[self.index]
            self.index += 1
            return cursor

    connection = Connection()
    snapshot = collect_release_snapshot(
        connection,
        expectation.collections,
        expected_artifact_ids=tuple(
            artifact.content_sha256 for artifact in expectation.artifacts
        ),
        release_kind=expectation.release_kind,
    )

    assert evaluate_release_snapshot(expectation, snapshot).ready is True
    _placement_cursor, artifact_cursor, chunk_cursor = connection.cursors
    assert artifact_cursor.params == ([ARTIFACT_SHA],)
    assert chunk_cursor.params == ([ARTIFACT_SHA],)
    assert "WHERE artifact_id = ANY(%s)" in chunk_cursor.sql
    assert "WHERE collection = ANY(%s)" not in chunk_cursor.sql


def test_v1_collection_readiness_reaches_shared_chunks_placed_via_a_second_subject(
    tmp_path: Path,
) -> None:
    """The physical chunk of a shared V1 artifact is stored exactly once and
    tagged with its one home collection (say Première). A second subject
    (Terminale) legitimately reaches the SAME physical chunk only through
    ``rag_artifact_placements`` — never through the chunk's own denormalized
    ``collection`` column. Validating readiness for Terminale must not
    require the chunk to be re-tagged; the placement is the reachability
    authority, not ``legacy_chunk_collection``.
    """
    aggregate_path, digest = _shared_artifact_two_subjects(tmp_path)
    expectation = load_release_expectation(aggregate_path, digest)

    collection_placements = tuple(
        placement for placement in expectation.placements if placement.collection == SECOND_COLLECTION
    )
    referenced_artifact_ids = {placement.artifact_id for placement in collection_placements}
    collection_artifacts = tuple(
        artifact
        for artifact in expectation.artifacts
        if artifact.content_sha256 in referenced_artifact_ids
    )
    collection_expectation = replace(
        expectation,
        collections=(SECOND_COLLECTION,),
        artifacts=collection_artifacts,
        placements=collection_placements,
    )

    second_placement_payload = collection_placements[0].payload
    placement_row = {
        **second_placement_payload,
        "artifact_id": ARTIFACT_SHA,
        "source_path": "01_EDUSCOL_OFFICIEL/COLLEGE/3E/MATHEMATIQUES/a.pdf",
        "source_uri": "https://eduscol.education.fr/document/a/download",
        "authorization_id": "LOT12-V1:auth:shared",
        "publication_attestation_id": "00000000-0000-0000-0000-000000000001",
    }
    artifact_row = (
        ARTIFACT_SHA,
        ARTIFACT_SHA,
        "eduscol.education.fr",
        "https://eduscol.education.fr/document/a/download",
        "officiel_public",
        True,
        "eduscol.education.fr",
        "ressource_officielle",
    )
    # Physically stored under COLLECTION (its home subject), never re-tagged
    # for SECOND_COLLECTION -- only reachable there via the placement above.
    chunk_row = (
        CHUNK_ID,
        ARTIFACT_SHA,
        COLLECTION,
        0,
        CHUNK_SHA,
        1,
        1,
        "reviewed",
        MODEL_ID,
        True,
        1024,
    )

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
                Cursor([artifact_row]),
                Cursor([tuple(placement_row[column] for column in readiness._PLACEMENT_COLUMNS)]),
                Cursor([chunk_row]),
            ]
            self.index = 0

        def cursor(self) -> Cursor:
            cursor = self.cursors[self.index]
            self.index += 1
            return cursor

    connection = Connection()
    snapshot = collect_release_snapshot(connection, (SECOND_COLLECTION,))
    report = evaluate_release_snapshot(collection_expectation, snapshot)

    assert report.ready is True, report.blockers
    _artifact_cursor, _placement_cursor, chunk_cursor = connection.cursors
    assert "artifact_id = ANY(%s)" in chunk_cursor.sql


def test_v2_database_snapshot_includes_artifacts_observed_only_in_placements(
    tmp_path: Path,
) -> None:
    manifest, digest, _registry, _subjects = _v2_release_files(tmp_path)
    expectation = load_release_expectation(manifest, digest)
    unexpected_artifact_sha = "f" * 64
    unexpected_placement_id = "7" * 64
    unexpected_chunk_id = "8" * 64
    unexpected_chunk_sha = "9" * 64

    artifact_rows = (
        (
            ARTIFACT_SHA,
            ARTIFACT_SHA,
            "eduscol.education.fr",
            "https://eduscol.education.fr/document/a/download",
            "officiel_public",
            True,
            "eduscol.education.fr",
            "ressource_officielle",
        ),
        (
            unexpected_artifact_sha,
            unexpected_artifact_sha,
            "eduscol.education.fr",
            "https://eduscol.education.fr/document/z/download",
            "officiel_public",
            True,
            "eduscol.education.fr",
            "ressource_officielle",
        ),
    )
    expected_placement = {
        **_v2_placement(COLLECTION, 0),
        "source_path": "01_EDUSCOL_OFFICIEL/LYCEE/NSI/a.pdf",
        "source_uri": "https://eduscol.education.fr/document/a/download",
        "authorization_id": "LOT12-V2:auth:0",
        "publication_attestation_id": "00000000-0000-0000-0000-000000000001",
    }
    unexpected_placement = {
        **_v2_placement(COLLECTION, 1),
        "placement_id": unexpected_placement_id,
        "artifact_id": unexpected_artifact_sha,
        "source_placement_id": "catalog-placement-unexpected",
        "source_path": "01_EDUSCOL_OFFICIEL/LYCEE/NSI/z.pdf",
        "source_uri": "https://eduscol.education.fr/document/z/download",
        "authorization_id": "LOT12-V2:auth:unexpected",
        "publication_attestation_id": "00000000-0000-0000-0000-000000000002",
    }
    placement_rows = tuple(
        tuple(row[column] for column in readiness._PLACEMENT_COLUMNS)
        for row in (expected_placement, unexpected_placement)
    )
    chunk_rows = (
        (
            CHUNK_ID,
            ARTIFACT_SHA,
            COLLECTION,
            0,
            CHUNK_SHA,
            1,
            1,
            "reviewed",
            MODEL_ID,
            True,
            1024,
        ),
        (
            unexpected_chunk_id,
            unexpected_artifact_sha,
            COLLECTION,
            0,
            unexpected_chunk_sha,
            1,
            1,
            "reviewed",
            MODEL_ID,
            True,
            1024,
        ),
    )

    class Cursor:
        def __init__(self, connection: Connection) -> None:
            self.connection = connection
            self.sql = ""
            self.params: object = None

        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, sql: str, params: object) -> None:
            self.sql = sql
            self.params = params
            self.connection.cursors.append(self)

        def fetchall(self) -> list[tuple[object, ...]]:
            if "SELECT placement_id" in self.sql:
                return list(placement_rows)
            selected_ids = set(self.params[0])
            if "SELECT DISTINCT a.artifact_id" in self.sql:
                return [row for row in artifact_rows if row[0] in selected_ids]
            if "SELECT chunk_id" in self.sql:
                return [row for row in chunk_rows if row[1] in selected_ids]
            raise AssertionError(f"unexpected SQL: {self.sql}")

    class Connection:
        def __init__(self) -> None:
            self.cursors: list[Cursor] = []

        def cursor(self) -> Cursor:
            return Cursor(self)

    connection = Connection()
    snapshot = collect_release_snapshot(
        connection,
        expectation.collections,
        expected_artifact_ids=tuple(
            artifact.content_sha256 for artifact in expectation.artifacts
        ),
        release_kind=expectation.release_kind,
    )
    report = evaluate_release_snapshot(expectation, snapshot)

    artifact_cursor = next(
        cursor
        for cursor in connection.cursors
        if "SELECT DISTINCT a.artifact_id" in cursor.sql
    )
    chunk_cursor = next(
        cursor for cursor in connection.cursors if "SELECT chunk_id" in cursor.sql
    )
    expected_ids = [ARTIFACT_SHA, unexpected_artifact_sha]
    assert artifact_cursor.params == (expected_ids,)
    assert chunk_cursor.params == (expected_ids,)
    assert "WHERE artifact_id = ANY(%s)" in chunk_cursor.sql
    assert "WHERE collection = ANY(%s)" not in chunk_cursor.sql
    assert report.ready is False
    assert report.unexpected_placements == 1
    assert report.unexpected_artifacts == 1
    assert report.unexpected_chunks == 1


def test_v2_database_snapshot_includes_chunks_of_orphan_artifacts(
    tmp_path: Path,
) -> None:
    manifest, digest, _registry, _subjects = _v2_release_files(tmp_path)
    expectation = load_release_expectation(manifest, digest)
    orphan_artifact_sha = "f" * 64
    orphan_chunk_id = "8" * 64
    orphan_chunk_sha = "9" * 64

    artifact_rows = (
        (
            ARTIFACT_SHA,
            ARTIFACT_SHA,
            "eduscol.education.fr",
            "https://eduscol.education.fr/document/a/download",
            "officiel_public",
            True,
            "eduscol.education.fr",
            "ressource_officielle",
        ),
        (
            orphan_artifact_sha,
            orphan_artifact_sha,
            "eduscol.education.fr",
            "https://eduscol.education.fr/document/orphan/download",
            "officiel_public",
            True,
            "eduscol.education.fr",
            "ressource_officielle",
        ),
    )
    placement = {
        **_v2_placement(COLLECTION, 0),
        "source_path": "01_EDUSCOL_OFFICIEL/LYCEE/NSI/a.pdf",
        "source_uri": "https://eduscol.education.fr/document/a/download",
        "authorization_id": "LOT12-V2:auth:0",
        "publication_attestation_id": "00000000-0000-0000-0000-000000000001",
    }
    placement_row = tuple(
        placement[column] for column in readiness._PLACEMENT_COLUMNS
    )
    chunk_rows = (
        (
            CHUNK_ID,
            ARTIFACT_SHA,
            COLLECTION,
            0,
            CHUNK_SHA,
            1,
            1,
            "reviewed",
            MODEL_ID,
            True,
            1024,
        ),
        (
            orphan_chunk_id,
            orphan_artifact_sha,
            COLLECTION,
            0,
            orphan_chunk_sha,
            1,
            1,
            "reviewed",
            MODEL_ID,
            True,
            1024,
        ),
    )

    class Cursor:
        def __init__(self, connection: Connection) -> None:
            self.connection = connection
            self.sql = ""
            self.params: object = None

        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, sql: str, params: object) -> None:
            self.sql = sql
            self.params = params
            self.connection.cursors.append(self)

        def fetchall(self) -> list[tuple[object, ...]]:
            if "SELECT placement_id" in self.sql:
                return [placement_row]
            if "SELECT DISTINCT a.artifact_id" in self.sql:
                # Le second artefact satisfait la branche NOT EXISTS du SQL :
                # il n'a aucun placement et doit donc être exposé par le garde.
                return list(artifact_rows)
            if "SELECT chunk_id" in self.sql:
                selected_ids = set(self.params[0])
                return [row for row in chunk_rows if row[1] in selected_ids]
            raise AssertionError(f"unexpected SQL: {self.sql}")

    class Connection:
        def __init__(self) -> None:
            self.cursors: list[Cursor] = []

        def cursor(self) -> Cursor:
            return Cursor(self)

    connection = Connection()
    snapshot = collect_release_snapshot(
        connection,
        expectation.collections,
        expected_artifact_ids=tuple(
            artifact.content_sha256 for artifact in expectation.artifacts
        ),
        release_kind=expectation.release_kind,
    )
    report = evaluate_release_snapshot(expectation, snapshot)

    chunk_cursor = next(
        cursor for cursor in connection.cursors if "SELECT chunk_id" in cursor.sql
    )
    assert chunk_cursor.params == ([ARTIFACT_SHA, orphan_artifact_sha],)
    assert "WHERE artifact_id = ANY(%s)" in chunk_cursor.sql
    assert "WHERE collection = ANY(%s)" not in chunk_cursor.sql
    assert report.ready is False
    assert report.unexpected_artifacts == 1
    assert report.unexpected_chunks == 1


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


@pytest.mark.parametrize(
    ("shared_field", "message"),
    [("placement", "placement"), ("chunk", "chunk")],
)
def test_release_aggregate_refuses_cross_subject_identity_collision(
    tmp_path: Path,
    shared_field: str,
    message: str,
) -> None:
    aggregate_path, _digest = _release_files(tmp_path)
    first_subject_path = tmp_path / "maths_troisieme.release.json"
    first_subject = json.loads(first_subject_path.read_text())
    second_subject = copy.deepcopy(first_subject)
    second_collection = "rag_nexus_francais_seconde_tc"
    second_subject["collection"] = second_collection
    second_subject["artifacts"][0]["content_sha256"] = "3" * 64
    second_subject["artifacts"][0]["placements"][0]["collection"] = second_collection
    if shared_field != "placement":
        second_subject["artifacts"][0]["placements"][0]["placement_id"] = "4" * 64
    if shared_field != "chunk":
        second_subject["artifacts"][0]["chunks"][0]["chunk_id"] = "5" * 64
    artifact = second_subject["artifacts"][0]
    artifact["placement_id_set_digest"] = _set_digest(
        [artifact["placements"][0]["placement_id"]]
    )
    artifact["chunk_id_set_digest"] = _set_digest(
        [artifact["chunks"][0]["chunk_id"]]
    )
    second_path = tmp_path / "francais_seconde.release.json"
    second_sha = _write_json(second_path, second_subject)
    aggregate = json.loads(aggregate_path.read_text())
    aggregate["subjects"].append(
        {
            "path": second_path.name,
            "sha256": second_sha,
            "collection": second_collection,
        }
    )
    aggregate["expected_counts"] = {
        "artifacts": 2,
        "placements": 2,
        "chunks": 2,
    }
    digest = _write_json(aggregate_path, aggregate)

    with pytest.raises(ReleaseReadinessError, match=message):
        load_release_expectation(aggregate_path, digest)


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


def _write_registry(tmp_path: Path, payload: object, *, name: str = "release-registry.json") -> tuple[Path, str]:
    path = tmp_path / name
    digest = _write_json(path, payload)
    return path, digest


def _registry_entry(
    manifest: Path,
    digest: str,
    *,
    release_id: str,
    collections: list[str],
    registry_root: Path,
    release_kind: str = "WAVE0_AGGREGATE_RELEASE_V1",
) -> dict[str, object]:
    return {
        "release_id": release_id,
        "collections": collections,
        "manifest_path": str(
            Path(manifest).resolve().relative_to(Path(registry_root).resolve())
        ),
        "expected_manifest_sha256": digest,
        "release_kind": release_kind,
    }


def test_real_release_registry_file_exposes_all_eleven_production_collections() -> None:
    registry_sha256 = hashlib.sha256(REHEARSAL_RELEASE_REGISTRY.read_bytes()).hexdigest()

    registry = load_release_registry_file(REHEARSAL_RELEASE_REGISTRY, registry_sha256)

    assert len(registry.collections) == 11
    assert {
        "rag_nexus_dgemc_terminale_option",
        "rag_nexus_nsi_terminale_specialite",
    } < set(registry.collections)




def test_release_registry_file_refuses_digest_mismatch(tmp_path: Path) -> None:
    manifest, digest = _release_files(tmp_path / "wave0")
    registry_path, _registry_digest = _write_registry(
        tmp_path,
        {
            "registry_version": "1",
            "school_year": "2026-2027",
            "releases": [
                _registry_entry(
                    manifest,
                    digest,
                    release_id="wave0-2026-2027",
                    collections=[COLLECTION],
                    registry_root=tmp_path,
                )
            ],
        },
    )

    with pytest.raises(ReleaseReadinessError, match="digest mismatch"):
        load_release_registry_file(registry_path, "0" * 64)


def test_release_manifest_refuses_duplicate_json_object_keys(tmp_path: Path) -> None:
    manifest, _digest = _release_files(tmp_path)
    raw = manifest.read_text(encoding="utf-8").replace(
        '  "release_id": "wave0-2026-2027",',
        '  "release_id": "shadowed",\n  "release_id": "wave0-2026-2027",',
        1,
    )
    manifest.write_text(raw, encoding="utf-8")

    with pytest.raises(ReleaseReadinessError, match="duplicate JSON object key"):
        load_release_expectation(
            manifest, hashlib.sha256(manifest.read_bytes()).hexdigest()
        )


def test_release_registry_file_refuses_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ReleaseReadinessError, match="unavailable"):
        load_release_registry_file(tmp_path / "missing-registry.json", "0" * 64)


def test_release_registry_file_refuses_manifest_digest_drift(tmp_path: Path) -> None:
    manifest, _digest = _release_files(tmp_path / "wave0")
    registry_path, registry_digest = _write_registry(
        tmp_path,
        {
            "registry_version": "1",
            "school_year": "2026-2027",
            "releases": [
                _registry_entry(
                    manifest,
                    "0" * 64,
                    release_id="wave0-2026-2027",
                    collections=[COLLECTION],
                    registry_root=tmp_path,
                )
            ],
        },
    )

    with pytest.raises(ReleaseReadinessError, match="digest mismatch"):
        load_release_registry_file(registry_path, registry_digest)


def test_release_registry_file_refuses_manifest_absent(tmp_path: Path) -> None:
    registry_path, registry_digest = _write_registry(
        tmp_path,
        {
            "registry_version": "1",
            "school_year": "2026-2027",
            "releases": [
                {
                    "release_id": "r1",
                    "collections": [COLLECTION],
                    "manifest_path": "does-not-exist.json",
                    "expected_manifest_sha256": "0" * 64,
                    "release_kind": "WAVE0_AGGREGATE_RELEASE_V1",
                }
            ],
        },
    )

    with pytest.raises(ReleaseReadinessError, match="unavailable"):
        load_release_registry_file(registry_path, registry_digest)


def test_release_registry_file_refuses_absolute_manifest_path_inside_root(
    tmp_path: Path,
) -> None:
    manifest, digest = _release_files(tmp_path / "wave0")
    registry_path, registry_digest = _write_registry(
        tmp_path,
        {
            "registry_version": "1",
            "school_year": "2026-2027",
            "releases": [
                {
                    "release_id": "wave0-2026-2027",
                    "collections": [COLLECTION],
                    "manifest_path": str(manifest.resolve()),
                    "expected_manifest_sha256": digest,
                    "release_kind": "WAVE0_AGGREGATE_RELEASE_V1",
                }
            ],
        },
    )

    with pytest.raises(ReleaseReadinessError, match="relative"):
        load_release_registry_file(registry_path, registry_digest)


def test_release_registry_file_refuses_unsupported_version(tmp_path: Path) -> None:
    manifest, digest = _release_files(tmp_path / "wave0")
    registry_path, registry_digest = _write_registry(
        tmp_path,
        {
            "registry_version": "999",
            "school_year": "2026-2027",
            "releases": [
                _registry_entry(
                    manifest,
                    digest,
                    release_id="r1",
                    collections=[COLLECTION],
                    registry_root=tmp_path,
                )
            ],
        },
    )

    with pytest.raises(ReleaseReadinessError, match="version is unsupported"):
        load_release_registry_file(registry_path, registry_digest)


def test_release_registry_file_refuses_wildcard_manifest_path(tmp_path: Path) -> None:
    manifest, digest = _release_files(tmp_path / "wave0")
    registry_path, registry_digest = _write_registry(
        tmp_path,
        {
            "registry_version": "1",
            "school_year": "2026-2027",
            "releases": [
                {
                    "release_id": "r1",
                    "collections": [COLLECTION],
                    "manifest_path": "*.json",
                    "expected_manifest_sha256": digest,
                    "release_kind": "WAVE0_AGGREGATE_RELEASE_V1",
                }
            ],
        },
    )

    with pytest.raises(ReleaseReadinessError, match="must be explicit"):
        load_release_registry_file(registry_path, registry_digest)


def test_release_registry_file_refuses_duplicate_release_id(tmp_path: Path) -> None:
    first = _release_files(tmp_path / "first")
    second = _release_files(
        tmp_path / "second",
        collection="rag_nexus_francais_seconde_tc",
        artifact_sha="3" * 64,
        placement_id="4" * 64,
        chunk_id="5" * 64,
        chunk_sha="6" * 64,
    )
    registry_path, registry_digest = _write_registry(
        tmp_path,
        {
            "registry_version": "1",
            "school_year": "2026-2027",
            "releases": [
                _registry_entry(
                    *first,
                    release_id="same",
                    collections=[COLLECTION],
                    registry_root=tmp_path,
                ),
                _registry_entry(
                    *second,
                    release_id="same",
                    collections=["rag_nexus_francais_seconde_tc"],
                    registry_root=tmp_path,
                ),
            ],
        },
    )

    with pytest.raises(ReleaseReadinessError, match="duplicate release_id"):
        load_release_registry_file(registry_path, registry_digest)


def test_release_registry_file_refuses_release_id_drift(tmp_path: Path) -> None:
    manifest, digest = _release_files(tmp_path / "wave0")
    registry_path, registry_digest = _write_registry(
        tmp_path,
        {
            "registry_version": "1",
            "school_year": "2026-2027",
            "releases": [
                _registry_entry(
                    manifest,
                    digest,
                    release_id="not-the-manifest-release-id",
                    collections=[COLLECTION],
                    registry_root=tmp_path,
                )
            ],
        },
    )

    with pytest.raises(ReleaseReadinessError, match="release_id"):
        load_release_registry_file(registry_path, registry_digest)


def test_multilevel_subject_profile_manifest_matches_authority(tmp_path: Path) -> None:
    release_root = tmp_path / "profile_gate"
    shutil.copytree(PRODUCTION_PROFILE_RELEASE_ROOT, release_root)
    aggregate_path = release_root / "production-profile-gate.release.json"
    aggregate = json.loads(aggregate_path.read_text())
    subject_entry = aggregate["subjects"][0]
    subject_path = release_root / subject_entry["path"]
    subject = json.loads(subject_path.read_text())
    subject["profile"]["manifest_digest"] = "0" * 64
    subject_entry["sha256"] = _write_json(subject_path, subject)
    digest = _write_json(aggregate_path, aggregate)

    with pytest.raises(ReleaseReadinessError, match="profile manifest"):
        load_release_expectation(aggregate_path, digest)


def test_real_production_profile_gate_release_matches_canonical_volumetry() -> None:
    """Regression proof for the multi-placement fix: the real, sealed
    production-profile-gate-2026-2027-v1 release (167 artifacts legitimately
    shared across première/terminale subject collections) must now load
    cleanly through the unmodified pinned registry entry, and the resulting
    counts must match the volumetry every downstream consumer (the Nexus
    ARIA preview's canonical authority, the servable-corpus pipeline) has
    been built against. Before the fix, this same release raised
    ``ReleaseReadinessError: artifact is duplicated across subjects``.
    """
    aggregate_path = PRODUCTION_PROFILE_RELEASE_ROOT / "production-profile-gate.release.json"
    registry = json.loads(RELEASE_REGISTRY.read_text(encoding="utf-8"))
    matches = [
        r
        for r in registry["releases"]
        if r["release_id"] == "production-profile-gate-2026-2027-v1"
    ]
    assert len(matches) == 1, matches
    (entry,) = matches
    digest = entry["expected_manifest_sha256"]
    assert entry["manifest_path"] == "profile_gate/production-profile-gate.release.json"

    expectation = load_release_expectation(aggregate_path, digest)

    assert len(expectation.placements) == 486
    assert len({a.content_sha256 for a in expectation.artifacts}) == 319
    assert sum(len(a.chunks) for a in expectation.artifacts) == 12403

    nsi_terminale = [
        a for a in expectation.artifacts if a.collection == "rag_nexus_nsi_terminale_specialite"
    ]
    assert len(nsi_terminale) == 47
    assert sum(len(a.chunks) for a in nsi_terminale) == 904


def test_release_registry_file_refuses_declared_collection_collision(
    tmp_path: Path,
) -> None:
    first = _release_files(tmp_path / "first")
    second = _release_files(
        tmp_path / "second",
        collection="rag_nexus_francais_seconde_tc",
        artifact_sha="3" * 64,
        placement_id="4" * 64,
        chunk_id="5" * 64,
        chunk_sha="6" * 64,
    )
    registry_path, registry_digest = _write_registry(
        tmp_path,
        {
            "registry_version": "1",
            "school_year": "2026-2027",
            "releases": [
                _registry_entry(
                    *first,
                    release_id="r1",
                    collections=[COLLECTION],
                    registry_root=tmp_path,
                ),
                _registry_entry(
                    *second,
                    release_id="r2",
                    # Declares a collection already claimed by r1 — must be
                    # refused before the manifests are even reconciled.
                    collections=[COLLECTION],
                    registry_root=tmp_path,
                ),
            ],
        },
    )

    with pytest.raises(ReleaseReadinessError, match="collection collision"):
        load_release_registry_file(registry_path, registry_digest)


def test_release_registry_file_refuses_declared_collections_not_matching_manifest(
    tmp_path: Path,
) -> None:
    manifest, digest = _release_files(tmp_path / "wave0")
    registry_path, registry_digest = _write_registry(
        tmp_path,
        {
            "registry_version": "1",
            "school_year": "2026-2027",
            "releases": [
                _registry_entry(
                    manifest,
                    digest,
                    release_id="wave0-2026-2027",
                    collections=["rag_nexus_this_collection_does_not_exist"],
                    registry_root=tmp_path,
                )
            ],
        },
    )

    with pytest.raises(ReleaseReadinessError, match="declared collections"):
        load_release_registry_file(registry_path, registry_digest)


def test_release_registry_file_refuses_release_kind_drift(tmp_path: Path) -> None:
    manifest, digest = _release_files(tmp_path / "wave0")
    registry_path, registry_digest = _write_registry(
        tmp_path,
        {
            "registry_version": "1",
            "school_year": "2026-2027",
            "releases": [
                _registry_entry(
                    manifest,
                    digest,
                    release_id="wave0-2026-2027",
                    collections=[COLLECTION],
                    release_kind="MULTILEVEL_AGGREGATE_RELEASE_V1",
                    registry_root=tmp_path,
                )
            ],
        },
    )

    with pytest.raises(ReleaseReadinessError, match="release_kind"):
        load_release_registry_file(registry_path, registry_digest)


def test_runtime_uses_release_registry_file_as_primary_mechanism(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor import retrieval_v2_endpoint as endpoint

    registry_sha256 = hashlib.sha256(REHEARSAL_RELEASE_REGISTRY.read_bytes()).hexdigest()
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_SHA256", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFESTS_JSON", raising=False)
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_PATH", str(REHEARSAL_RELEASE_REGISTRY))
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_SHA256", registry_sha256)


    registry = endpoint._configured_release_registry()

    assert registry is not None
    assert len(registry.collections) == 11



def test_runtime_release_registry_file_refuses_ambiguous_with_manifests_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor import retrieval_v2_endpoint as endpoint

    manifest, digest = _release_files(tmp_path)
    registry_sha256 = hashlib.sha256(RELEASE_REGISTRY.read_bytes()).hexdigest()
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_SHA256", raising=False)
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_PATH", str(RELEASE_REGISTRY))
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_SHA256", registry_sha256)
    monkeypatch.setenv(
        "RAG_RELEASE_MANIFESTS_JSON",
        json.dumps([{"path": str(manifest), "sha256": digest}]),
    )

    with pytest.raises(ValueError, match="ambiguous"):
        endpoint._configured_release_registry()


def test_runtime_release_registry_file_refuses_ambiguous_with_legacy_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor import retrieval_v2_endpoint as endpoint

    manifest, digest = _release_files(tmp_path)
    registry_sha256 = hashlib.sha256(RELEASE_REGISTRY.read_bytes()).hexdigest()
    monkeypatch.delenv("RAG_RELEASE_MANIFESTS_JSON", raising=False)
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_PATH", str(RELEASE_REGISTRY))
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_SHA256", registry_sha256)
    monkeypatch.setenv("RAG_RELEASE_MANIFEST_PATH", str(manifest))
    monkeypatch.setenv("RAG_RELEASE_MANIFEST_SHA256", digest)

    with pytest.raises(ValueError, match="ambiguous"):
        endpoint._configured_release_registry()


def test_runtime_release_registry_file_incomplete_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor import retrieval_v2_endpoint as endpoint

    monkeypatch.delenv("RAG_RELEASE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_SHA256", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFESTS_JSON", raising=False)
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_PATH", str(RELEASE_REGISTRY))
    monkeypatch.delenv("RAG_RELEASE_REGISTRY_SHA256", raising=False)

    with pytest.raises(ValueError, match="incomplete"):
        endpoint._configured_release_registry()


def test_runtime_startup_accepts_release_registry_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil

    import yaml
    from nexus_contracts import load_retrieval_scope_registry

    from ingestor import retrieval_v2_endpoint as endpoint

    multilevel_copy = tmp_path / "multilevel"
    shutil.copytree(MULTILEVEL_RELEASE.parent, multilevel_copy)
    multilevel_sha256 = hashlib.sha256(
        (multilevel_copy / MULTILEVEL_RELEASE.name).read_bytes()
    ).hexdigest()
    multilevel_doc = json.loads((multilevel_copy / MULTILEVEL_RELEASE.name).read_text())
    registry_path, registry_digest = _write_registry(
        tmp_path,
        {
            "registry_version": "1",
            "school_year": "2026-2027",
            "releases": [
                {
                    "release_id": multilevel_doc["release_id"],
                    "collections": [s["collection"] for s in multilevel_doc["subjects"]],
                    "manifest_path": f"multilevel/{MULTILEVEL_RELEASE.name}",
                    "expected_manifest_sha256": multilevel_sha256,
                    "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V1",
                }
            ],
        },
    )
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_SHA256", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFESTS_JSON", raising=False)
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_SHA256", registry_digest)
    config = yaml.safe_load(CANONICAL_COLLECTIONS.read_text(encoding="utf-8"))

    endpoint.validate_release_startup_configuration(
        load_retrieval_scope_registry(),
        config,
    )


def test_runtime_startup_refuses_two_scopes_for_the_same_release_subject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil

    import yaml
    from nexus_contracts import load_retrieval_scope_registry

    from ingestor import retrieval_v2_endpoint as endpoint

    multilevel_copy = tmp_path / "multilevel"
    shutil.copytree(MULTILEVEL_RELEASE.parent, multilevel_copy)
    multilevel_sha256 = hashlib.sha256(
        (multilevel_copy / MULTILEVEL_RELEASE.name).read_bytes()
    ).hexdigest()
    multilevel_doc = json.loads((multilevel_copy / MULTILEVEL_RELEASE.name).read_text())
    registry_path, registry_digest = _write_registry(
        tmp_path,
        {
            "registry_version": "1",
            "school_year": "2026-2027",
            "releases": [
                {
                    "release_id": multilevel_doc["release_id"],
                    "collections": [s["collection"] for s in multilevel_doc["subjects"]],
                    "manifest_path": f"multilevel/{MULTILEVEL_RELEASE.name}",
                    "expected_manifest_sha256": multilevel_sha256,
                    "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V1",
                }
            ],
        },
    )
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_SHA256", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFESTS_JSON", raising=False)
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_SHA256", registry_digest)
    config = yaml.safe_load(CANONICAL_COLLECTIONS.read_text(encoding="utf-8"))
    artifacts = dict(load_retrieval_scope_registry())
    original = artifacts["terminale_nsi_v1"]
    artifacts["terminale_nsi_duplicate_v1"] = original.model_copy(
        update={"scope_id": "terminale_nsi_duplicate_v1"}
    )

    with pytest.raises(RuntimeError, match="ambiguous"):
        endpoint.validate_release_startup_configuration(artifacts, config)



def test_runtime_blocks_retrieval_for_a_collection_outside_the_active_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A canonically instanciated collection that the *active* registry does
    not cover must never be treated as retrievable: ``validate_release_
    startup_configuration`` tolerates a registry that is an explicit,
    non-empty subset of the instanciated V2 collections (phased rollout —
    see ``test_startup_accepts_explicit_nonempty_release_subset_of_v2_
    registry`` in ``test_multilevel_scope_registry.py``), but per-collection
    release evidence must still fail closed for whatever the registry
    leaves out, via ``_release_evidence_for_collection``."""
    import shutil

    from ingestor import retrieval_v2_endpoint as endpoint

    # Manifests must live under the registry's own root (no escaping paths),
    # so the real wave0/ tree is copied alongside the synthetic registry.
    wave0_copy = tmp_path / "wave0"
    shutil.copytree(WAVE0_RELEASE.parent, wave0_copy)
    wave0_sha256 = hashlib.sha256((wave0_copy / WAVE0_RELEASE.name).read_bytes()).hexdigest()
    registry_path, registry_digest = _write_registry(
        tmp_path,
        {
            "registry_version": "1",
            "school_year": "2026-2027",
            "releases": [
                {
                        "release_id": "wave0-exact-grade-troisieme-2026-2027-v1",
                    "collections": [
                        "rag_nexus_francais_troisieme_tc",
                        "rag_nexus_maths_troisieme_tc",
                    ],
                    "manifest_path": f"wave0/{WAVE0_RELEASE.name}",
                    "expected_manifest_sha256": wave0_sha256,
                    "release_kind": "WAVE0_AGGREGATE_RELEASE_V1",
                }
            ],
        },
    )
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_SHA256", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFESTS_JSON", raising=False)
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_SHA256", registry_digest)

    # Covered by the active (wave0-only) registry: eligible for evidence.
    assert (
        endpoint._release_evidence_for_collection("rag_nexus_maths_troisieme_tc")
        is not None
    )
    # Canonically instanciated but outside the active registry: never
    # silently treated as ready — the request path must refuse it.
    assert (
        endpoint._release_evidence_for_collection("rag_nexus_maths_seconde_tc")
        is None
    )


# ─────────────────────────────────────────────────────────────────────────
# Autorité de revue PII dans la chaîne d'autorité (ADR-0047)
# ─────────────────────────────────────────────────────────────────────────

# Dérivé du module, jamais recopié : si la chaîne s'allonge ou se raccourcit,
# les tests paramétrés doivent suivre d'eux-mêmes plutôt que de continuer à
# valider une liste devenue fausse.
from ingestor.release_readiness import _PII_REVIEW_AUTHORITY_FIELDS  # noqa: E402

_PII_REVIEW_AUTHORITIES = tuple(sorted(_PII_REVIEW_AUTHORITY_FIELDS))


class TestPiiReviewAuthoritiesAreAdmissible:
    """Une release qui admet un contenu détecté doit pouvoir dire sur quoi.

    La chaîne d'autorité était un ensemble FERMÉ de dix-neuf empreintes. Une
    release post-revue en porte quatre de plus — l'ensemble de décisions, son
    reçu, l'ancre qui vérifie ce reçu, et l'index des paquets qui l'ont fondé.
    Sans elles, la release affirmerait une admission dont rien, dans son propre
    manifeste, ne nommerait la source.

    Elles restent OPTIONNELLES : une release sans aucun contenu détecté n'a pas
    de décisions à joindre. Mais elles vont ensemble : un ensemble de décisions
    sans son reçu ne prouve rien, et la moitié d'une chaîne d'autorité est une
    chaîne rompue."""

    def _with(self, tmp_path: Path, extra: dict[str, str]):
        manifest, digest, _registry, _subjects = _v2_release_files(
            tmp_path, extra_authorities=extra
        )
        return load_release_expectation(manifest, digest)

    def test_a_release_without_review_authorities_is_still_accepted(
        self, tmp_path: Path
    ) -> None:
        expectation = self._with(tmp_path, {})
        assert expectation.release_kind == "MULTILEVEL_AGGREGATE_RELEASE_V2"

    def test_the_four_review_authorities_are_accepted_together(
        self, tmp_path: Path
    ) -> None:
        extra = {
            name: hashlib.sha256(name.encode("utf-8")).hexdigest()
            for name in _PII_REVIEW_AUTHORITIES
        }
        expectation = self._with(tmp_path, extra)
        assert expectation.release_kind == "MULTILEVEL_AGGREGATE_RELEASE_V2"

    @pytest.mark.parametrize("omitted", _PII_REVIEW_AUTHORITIES)
    def test_a_partial_review_authority_chain_is_refused(
        self, omitted: str, tmp_path: Path
    ) -> None:
        extra = {
            name: hashlib.sha256(name.encode("utf-8")).hexdigest()
            for name in _PII_REVIEW_AUTHORITIES
            if name != omitted
        }
        with pytest.raises(ReleaseReadinessError, match="review"):
            self._with(tmp_path, extra)

    def test_an_unknown_authority_field_is_still_refused(self, tmp_path: Path) -> None:
        """L'ensemble s'élargit d'exactement quatre champs, pas de n'importe quoi."""
        with pytest.raises(ReleaseReadinessError, match="authorities"):
            self._with(tmp_path, {"quelque_chose_sha256": "a" * 64})

    def test_a_review_authority_must_be_a_sha256(self, tmp_path: Path) -> None:
        extra = {
            name: hashlib.sha256(name.encode("utf-8")).hexdigest()
            for name in _PII_REVIEW_AUTHORITIES
        }
        extra["pii_decision_set_sha256"] = "pas-un-digest"
        with pytest.raises(ReleaseReadinessError):
            self._with(tmp_path, extra)


def test_the_vendored_release_readiness_copy_is_byte_identical() -> None:
    """Deux copies du même contrat doivent rester le même contrat.

    `services/rag-engine/src/ingestor/release_readiness.py` est une copie
    vendorée de `packages/release-chain/…/release_readiness.py`. Les laisser
    diverger ferait accepter au producteur ce que le worker refuse, ou
    l'inverse — sans que rien ne le signale."""
    root = Path(__file__).resolve().parents[3]
    vendored = root / "services/rag-engine/src/ingestor/release_readiness.py"
    canonical = root / "packages/release-chain/src/nexus_release_chain/release_readiness.py"
    assert vendored.read_bytes() == canonical.read_bytes()


class TestTheReviewChainIsCarriedNotDropped:
    """P1 — le manifeste annonçait une chaîne, le worker en vérifiait une autre.

    Les quatre empreintes de la chaîne de revue étaient contrôlées
    syntaxiquement puis JETÉES : `ReleaseExpectation` ne les portait pas. Le
    worker, lui, charge sa chaîne depuis ses propres arguments. Rien ne
    confrontait les deux — une release pouvait donc annoncer la chaîne A
    pendant que le worker en vérifiait une B, chacune valide de son côté."""

    def _expectation(self, tmp_path: Path, extra: dict[str, str] | None = None):
        manifest, digest, _r, _s = _v2_release_files(tmp_path, extra_authorities=extra)
        return load_release_expectation(manifest, digest)

    def test_a_release_without_a_review_chain_carries_none(self, tmp_path: Path) -> None:
        expectation = self._expectation(tmp_path, {})
        assert expectation.pii_decision_set_sha256 is None
        assert expectation.pii_review_receipt_sha256 is None
        assert expectation.pii_review_trust_anchor_sha256 is None
        assert expectation.pii_review_index_sha256 is None

    def test_the_four_digests_reach_the_expectation(self, tmp_path: Path) -> None:
        extra = {
            name: hashlib.sha256(name.encode("utf-8")).hexdigest()
            for name in _PII_REVIEW_AUTHORITIES
        }
        expectation = self._expectation(tmp_path, extra)
        assert expectation.pii_decision_set_sha256 == extra["pii_decision_set_sha256"]
        assert expectation.pii_review_receipt_sha256 == extra["pii_review_receipt_sha256"]
        assert (
            expectation.pii_review_trust_anchor_sha256
            == extra["pii_review_trust_anchor_sha256"]
        )
        assert expectation.pii_review_index_sha256 == extra["pii_review_index_sha256"]


class TestV1StaysClosedToV2ReviewAuthorities:
    """P2 — l'extension V2 ne doit pas ouvrir les lignées antérieures.

    `_require_authority_chain` soustrayait les quatre champs de revue de
    TOUTE chaîne déclarée, y compris celles des schémas Wave 0 et multi-niveaux
    V1, qui ne les définissent pas. Un manifeste V1 portant ces champs devenait
    acceptable, alors que rien dans son schéma ne les prévoit.

    L'ouverture dépend désormais du SCHÉMA de release, pas de la présence des
    champs — une heuristique de présence laisserait toujours le format ancien
    s'élargir de lui-même."""

    def test_v2_accepts_the_complete_review_chain(self, tmp_path: Path) -> None:
        extra = {
            name: hashlib.sha256(name.encode("utf-8")).hexdigest()
            for name in _PII_REVIEW_AUTHORITIES
        }
        manifest, digest, _r, _s = _v2_release_files(tmp_path, extra_authorities=extra)
        assert load_release_expectation(manifest, digest).release_kind.endswith("_V2")

    def test_the_v1_authority_set_refuses_a_single_review_field(self) -> None:
        from ingestor.release_readiness import (
            _MULTILEVEL_AUTHORITY_FIELDS,
            _require_authority_chain,
        )

        authorities = {
            name: hashlib.sha256(name.encode("utf-8")).hexdigest()
            for name in _MULTILEVEL_AUTHORITY_FIELDS
        }
        authorities["pii_decision_set_sha256"] = "a" * 64
        with pytest.raises(ReleaseReadinessError, match="fields mismatch"):
            _require_authority_chain(
                authorities, _MULTILEVEL_AUTHORITY_FIELDS, "authorities",
                review_chain_allowed=False,
            )

    def test_the_v1_authority_set_refuses_the_complete_review_chain(self) -> None:
        from ingestor.release_readiness import (
            _MULTILEVEL_AUTHORITY_FIELDS,
            _require_authority_chain,
        )

        authorities = {
            name: hashlib.sha256(name.encode("utf-8")).hexdigest()
            for name in _MULTILEVEL_AUTHORITY_FIELDS
        }
        for name in _PII_REVIEW_AUTHORITIES:
            authorities[name] = hashlib.sha256(name.encode("utf-8")).hexdigest()
        with pytest.raises(ReleaseReadinessError, match="fields mismatch"):
            _require_authority_chain(
                authorities, _MULTILEVEL_AUTHORITY_FIELDS, "authorities",
                review_chain_allowed=False,
            )

    def test_the_v1_authority_set_without_review_fields_still_passes(self) -> None:
        from ingestor.release_readiness import (
            _MULTILEVEL_AUTHORITY_FIELDS,
            _require_authority_chain,
        )

        authorities = {
            name: hashlib.sha256(name.encode("utf-8")).hexdigest()
            for name in _MULTILEVEL_AUTHORITY_FIELDS
        }
        _require_authority_chain(
            authorities, _MULTILEVEL_AUTHORITY_FIELDS, "authorities",
            review_chain_allowed=False,
        )
