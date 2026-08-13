"""Autorité release Wave 0 : loaders data-driven et strictement bornés."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from ingestor.wave0_release import (
    ReleaseAuthorityError,
    load_aggregate_release,
    load_candidate_inventory,
    load_pedagogical_mapping,
    load_release_authority,
)

MANIFEST_SHA = "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
CATALOG_SHA = "3" * 64
PLACEMENT_CATALOG_SHA = "9" * 64
CURRENTNESS_SHA = "2" * 64
FR_SHA = "c" * 64
FR_PLACEMENT_ID = "par-scope/college/cycle-4/francais/3e/reperes-attendus/fr.pdf"
FR_PATH = "01_EDUSCOL_OFFICIEL/COLLEGE/3E/FRANCAIS/fr.pdf"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory() -> dict[str, Any]:
    return {
        "inventory_kind": "WAVE0_EXACT_GRADE_CANDIDATE_INVENTORY_V1",
        "school_year": "2026-2027",
        "corpus_manifest_sha256": MANIFEST_SHA,
        "sealed_catalog_sha256": CATALOG_SHA,
        "placement_catalog_sha256": PLACEMENT_CATALOG_SHA,
        "selection": {
            "external_level": "3e",
            "external_subjects": ["francais", "mathematiques", "maths"],
            "source_zone": "01_EDUSCOL_OFFICIEL/",
            "media_type": "application/pdf",
        },
        "counts": {
            "unique_artifacts": 1,
            "placements": 1,
            "physical_objects": 1,
            "multi_placement_artifacts": 0,
        },
        "candidates": [
            {
                "content_sha256": FR_SHA,
                "physical_path": FR_PATH,
                "source_url": "https://eduscol.education.gouv.fr/fr",
                "title": "Français 3e",
                "source_placement_id": FR_PLACEMENT_ID,
                "external_scope": "college/cycle-4/francais",
                "external_level": "3e",
                "external_subject": "francais",
                "external_document_type": "reperes-attendus",
                "pedagogical_status": "transition-ou-actuel",
                "physical_currentness_candidate": "unclassified",
                "physical_disposition_candidate": "REVIEW_REQUIRED",
            }
        ],
    }


def _mapping() -> dict[str, Any]:
    return {
        "mapping_kind": "EDUSCOL_WAVE0_PEDAGOGICAL_MAPPING_V1",
        "pedagogical_mappings": [
            {
                "external_level": "3e",
                "external_scope": "college/cycle-4/francais",
                "external_subject": "francais",
                "nexus_collection": "rag_nexus_francais_troisieme_tc",
                "nexus_niveau": "troisieme",
                "nexus_voie": "college",
                "nexus_matiere": "francais",
                "nexus_statut_enseignement": "tronc_commun",
            }
        ],
        "document_types": {"reperes-attendus": "ressource_officielle"},
    }


def _write_json(path: Path, document: dict[str, Any]) -> tuple[Path, str]:
    path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return path, _sha(path)


def _write_yaml(path: Path, document: dict[str, Any]) -> tuple[Path, str]:
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path, _sha(path)


def test_candidate_inventory_loads_exact_grade_sets_and_digest(tmp_path: Path) -> None:
    path, digest = _write_json(tmp_path / "inventory.json", _inventory())

    inventory = load_candidate_inventory(path, expected_sha256=digest)

    assert inventory.sha256 == digest
    assert inventory.unique_content_sha256 == frozenset({FR_SHA})
    assert inventory.placement_identities == frozenset({(FR_SHA, FR_PLACEMENT_ID)})
    assert inventory.candidates[0].physical_path == FR_PATH


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda document: document["candidates"].append(
                deepcopy(document["candidates"][0])
            ),
            "duplicated",
        ),
        (
            lambda document: document["candidates"][0].update(external_level="cycle-4"),
            "exact-grade",
        ),
        (
            lambda document: document["candidates"][0].update(
                external_scope="college/cycle-4/histoire"
            ),
            "scope",
        ),
        (
            lambda document: document["counts"].update(unique_artifacts=2),
            "counts",
        ),
    ],
)
def test_candidate_inventory_rejects_drift(
    tmp_path: Path, mutation: Any, message: str
) -> None:
    document = _inventory()
    mutation(document)
    path, digest = _write_json(tmp_path / "inventory.json", document)

    with pytest.raises(ReleaseAuthorityError, match=message):
        load_candidate_inventory(path, expected_sha256=digest)


def test_closed_mapping_rejects_unknown_document_type(tmp_path: Path) -> None:
    path, digest = _write_yaml(tmp_path / "mapping.yml", _mapping())
    mapping = load_pedagogical_mapping(path, expected_sha256=digest)

    assert mapping.resolve_type_doc("reperes-attendus").value == "ressource_officielle"
    with pytest.raises(ReleaseAuthorityError, match="document type"):
        mapping.resolve_type_doc("unknown-external-type")


def test_release_allowlist_must_be_subset_of_exact_inventory(tmp_path: Path) -> None:
    inventory_path, inventory_sha = _write_json(
        tmp_path / "inventory.json", _inventory()
    )
    inventory = load_candidate_inventory(inventory_path, expected_sha256=inventory_sha)
    release = {
        "release_kind": "WAVE0_SUBJECT_RELEASE_V1",
        "release_id": "wave0-francais-troisieme-2026-2027",
        "school_year": "2026-2027",
        "collection": "rag_nexus_francais_troisieme_tc",
        "authorities": {
            "corpus_manifest_sha256": MANIFEST_SHA,
            "sealed_catalog_sha256": CATALOG_SHA,
            "placement_catalog_sha256": PLACEMENT_CATALOG_SHA,
            "candidate_inventory_sha256": inventory_sha,
            "currentness_evidence_sha256": CURRENTNESS_SHA,
            "pii_evidence_sha256": "4" * 64,
            "pii_policy_sha256": "5" * 64,
            "rights_registry_sha256": "6" * 64,
        },
        "programme_version": "BOEN_special_11_2018-07-26_aj_2020",
        "profile": {
            "version": "wave0-v1",
            "fingerprint": "7" * 64,
            "manifest_digest": "8" * 64,
        },
        "models": {
            "embedding": {
                "model_id": "intfloat/multilingual-e5-large",
                "inventory_sha256": "9" * 64,
                "dimension": 1024,
            },
            "reranker": {
                "model_id": "cross-encoder/ms-marco-MiniLM-L-6-v2",
                "inventory_sha256": "a" * 64,
            },
        },
        "expected_counts": {"artifacts": 1, "placements": 1, "chunks": 1},
        "artifacts": [
            {
                "content_sha256": FR_SHA,
                "source_path": FR_PATH,
                "placements": [
                    {
                        "source_placement_id": FR_PLACEMENT_ID,
                        "collection": "rag_nexus_francais_troisieme_tc",
                    }
                ],
                "chunks": [{"chunk_id": "b" * 64}],
            }
        ],
    }
    path, digest = _write_json(tmp_path / "release.json", release)

    authority = load_release_authority(
        path,
        expected_sha256=digest,
        candidate_inventory=inventory,
        expected_currentness_evidence_sha256=CURRENTNESS_SHA,
    )

    assert authority.is_allowed(
        collection="rag_nexus_francais_troisieme_tc",
        content_sha256=FR_SHA,
        source_placement_id=FR_PLACEMENT_ID,
    )

    release["artifacts"][0]["content_sha256"] = "a" * 64
    bad_path, bad_digest = _write_json(tmp_path / "bad-release.json", release)
    with pytest.raises(ReleaseAuthorityError, match="candidate inventory"):
        load_release_authority(
            bad_path,
            expected_sha256=bad_digest,
            candidate_inventory=inventory,
            expected_currentness_evidence_sha256=CURRENTNESS_SHA,
        )


def test_aggregate_release_merges_exact_subjects_and_rejects_model_drift(
    tmp_path: Path,
) -> None:
    inventory_path, inventory_sha = _write_json(
        tmp_path / "inventory.json", _inventory()
    )
    inventory = load_candidate_inventory(inventory_path, expected_sha256=inventory_sha)
    subject = {
        "release_kind": "WAVE0_SUBJECT_RELEASE_V1",
        "release_id": "wave0-francais-troisieme-2026-2027",
        "school_year": "2026-2027",
        "collection": "rag_nexus_francais_troisieme_tc",
        "programme_version": "BOEN_special_11_2018-07-26_aj_2020",
        "authorities": {
            "corpus_manifest_sha256": MANIFEST_SHA,
            "sealed_catalog_sha256": CATALOG_SHA,
            "placement_catalog_sha256": PLACEMENT_CATALOG_SHA,
            "candidate_inventory_sha256": inventory_sha,
            "currentness_evidence_sha256": CURRENTNESS_SHA,
            "pii_evidence_sha256": "4" * 64,
            "pii_policy_sha256": "5" * 64,
            "rights_registry_sha256": "6" * 64,
        },
        "profile": {
            "version": "wave0-v1",
            "fingerprint": "7" * 64,
            "manifest_digest": "8" * 64,
        },
        "models": {
            "embedding": {
                "model_id": "intfloat/multilingual-e5-large",
                "inventory_sha256": "9" * 64,
                "dimension": 1024,
            },
            "reranker": {
                "model_id": "cross-encoder/ms-marco-MiniLM-L-6-v2",
                "inventory_sha256": "a" * 64,
            },
        },
        "expected_counts": {"artifacts": 1, "placements": 1, "chunks": 1},
        "artifacts": [
            {
                "content_sha256": FR_SHA,
                "source_path": FR_PATH,
                "placements": [
                    {
                        "source_placement_id": FR_PLACEMENT_ID,
                        "collection": "rag_nexus_francais_troisieme_tc",
                    }
                ],
                "chunks": [{"chunk_id": "b" * 64}],
            }
        ],
    }
    subject_path, subject_sha = _write_json(tmp_path / "fr.release.json", subject)
    aggregate = {
        "release_kind": "WAVE0_AGGREGATE_RELEASE_V1",
        "release_id": "wave0-exact-grade-troisieme-2026-2027-v1",
        "school_year": "2026-2027",
        "authorities": subject["authorities"],
        "models": subject["models"],
        "expected_counts": {"artifacts": 1, "placements": 1, "chunks": 1},
        "subjects": [
            {
                "collection": "rag_nexus_francais_troisieme_tc",
                "path": subject_path.name,
                "sha256": subject_sha,
            }
        ],
    }
    aggregate_path, aggregate_sha = _write_json(tmp_path / "wave0.release.json", aggregate)

    authority = load_aggregate_release(
        aggregate_path,
        expected_sha256=aggregate_sha,
        candidate_inventory=inventory,
        expected_currentness_evidence_sha256=CURRENTNESS_SHA,
    )
    assert set(authority.artifacts) == {
        ("rag_nexus_francais_troisieme_tc", FR_SHA)
    }

    drifted = deepcopy(subject)
    drifted["models"]["embedding"]["dimension"] = 768
    _, drifted_sha = _write_json(tmp_path / "fr.release.json", drifted)
    aggregate["subjects"][0]["sha256"] = drifted_sha
    drifted_path, drifted_aggregate_sha = _write_json(
        tmp_path / "drifted.release.json", aggregate
    )
    with pytest.raises(ReleaseAuthorityError, match="models"):
        load_aggregate_release(
            drifted_path,
            expected_sha256=drifted_aggregate_sha,
            candidate_inventory=inventory,
            expected_currentness_evidence_sha256=CURRENTNESS_SHA,
        )
