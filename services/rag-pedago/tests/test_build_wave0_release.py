"""Release Wave 0 : inventaire exact, gates exhaustifs et manifests stables."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from typing import Any, Protocol, cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "services" / "rag-pedago" / "scripts" / "build_wave0_release.py"
CORPUS_SHA = "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
CATALOG_SHA = "a" * 64
PLACEMENT_CATALOG_SHA = "b" * 64
MATHS_SHA = "1" * 64
FR_SHA = "2" * 64


class ReleaseBuilder(Protocol):
    def canonical_json_bytes(self, value: object) -> bytes: ...

    def build_candidate_inventory(
        self,
        catalog: dict[str, Any],
        *,
        sealed_catalog_sha256: str,
        school_year: str,
    ) -> dict[str, Any]: ...

    def build_full_pii_evidence(
        self,
        source_scan: dict[str, Any],
        *,
        source_scan_sha256: str,
        candidate_inventory_sha256: str,
        candidate_content_sha256: set[str],
    ) -> dict[str, Any]: ...

    def evaluate_release_candidates(
        self,
        inventory: dict[str, Any],
        *,
        currentness_by_sha: dict[str, dict[str, Any]],
        pii_by_sha: dict[str, dict[str, Any]],
        rights_by_sha: dict[str, str],
        preflight_by_sha: dict[str, dict[str, Any]],
    ) -> dict[str, Any]: ...

    def build_subject_release_manifest(
        self,
        *,
        subject: str,
        inventory: dict[str, Any],
        eligibility: dict[str, Any],
        artifact_preflights: dict[str, dict[str, Any]],
        authorities: dict[str, str],
        profile: dict[str, str],
        models: dict[str, Any],
    ) -> dict[str, Any]: ...


def _module() -> ReleaseBuilder:
    spec = importlib.util.spec_from_file_location("build_wave0_release", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(ReleaseBuilder, module)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _artifact(
    sha: str,
    *,
    subject: str,
    scope: str,
    level: str = "3e",
    document_type: str = "reperes-attendus",
) -> dict[str, Any]:
    filename = f"attendus-{subject}-{sha[:10]}.pdf"
    return {
        "sha256": sha,
        "physical_object_count": 1,
        "physical_objects": [
            {
                "content_sha256": sha,
                "path": f"01_EDUSCOL_OFFICIEL/COLLEGE/3E/{subject.upper()}/{filename}",
                "currentness": "unclassified",
                "disposition": "REVIEW_REQUIRED",
            }
        ],
        "pedagogical_placement_count": 1,
        "pedagogical_placements": [
            {
                "content_sha256": sha,
                "level": level,
                "subject": subject,
                "scope": scope,
                "document_type": document_type,
                "status": "transition-ou-actuel",
                "title": f"Attendus {subject}",
                "source_url": f"https://eduscol.education.gouv.fr/{sha[:4]}",
                "scope_path": f"par-scope/{scope}/{level}/{filename}",
            }
        ],
    }


def _catalog() -> dict[str, Any]:
    return {
        "catalog_kind": "REAL_SEALED_CORPUS",
        "verification_passed": True,
        "manifest_sha256": CORPUS_SHA,
        "placement_catalog_sha256": PLACEMENT_CATALOG_SHA,
        "artifacts": {
            MATHS_SHA: _artifact(
                MATHS_SHA,
                subject="mathematiques",
                scope="college/cycle-4/mathematiques",
            ),
            FR_SHA: _artifact(
                FR_SHA,
                subject="francais",
                scope="college/cycle-4/francais",
            ),
            "3" * 64: _artifact(
                "3" * 64,
                subject="mathematiques",
                scope="college/cycle-4/mathematiques",
                level="cycle-4",
            ),
            "4" * 64: _artifact(
                "4" * 64,
                subject="histoire",
                scope="college/cycle-4/histoire",
            ),
        },
    }


def test_candidate_inventory_is_exact_grade_deterministic_and_deduplicated() -> None:
    builder = _module()

    inventory = builder.build_candidate_inventory(
        _catalog(),
        sealed_catalog_sha256=CATALOG_SHA,
        school_year="2026-2027",
    )

    assert inventory["inventory_kind"] == "WAVE0_EXACT_GRADE_CANDIDATE_INVENTORY_V1"
    assert [row["content_sha256"] for row in inventory["candidates"]] == [
        MATHS_SHA,
        FR_SHA,
    ]
    assert inventory["counts"] == {
        "unique_artifacts": 2,
        "placements": 2,
        "physical_objects": 2,
        "multi_placement_artifacts": 0,
        "by_subject": {
            "francais": {"unique_artifacts": 1, "placements": 1},
            "mathematiques": {"unique_artifacts": 1, "placements": 1},
        },
    }
    assert inventory["selection"] == {
        "external_level": "3e",
        "external_subjects": ["francais", "mathematiques", "maths"],
        "source_zone": "01_EDUSCOL_OFFICIEL/",
        "media_type": "application/pdf",
    }
    assert builder.canonical_json_bytes(inventory).endswith(b"\n")
    assert b"cycle-4\"" not in builder.canonical_json_bytes(inventory)


def test_candidate_inventory_rejects_ambiguous_physical_objects() -> None:
    builder = _module()
    catalog = _catalog()
    catalog["artifacts"][MATHS_SHA]["physical_objects"].append(
        dict(catalog["artifacts"][MATHS_SHA]["physical_objects"][0])
    )
    catalog["artifacts"][MATHS_SHA]["physical_object_count"] = 2

    with pytest.raises(ValueError, match="physical object"):
        builder.build_candidate_inventory(
            catalog,
            sealed_catalog_sha256=CATALOG_SHA,
            school_year="2026-2027",
        )


def test_full_pii_evidence_is_bound_to_inventory_and_four_authorities() -> None:
    builder = _module()
    inventory_sha = "c" * 64
    scan = {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "corpus_manifest_sha256": CORPUS_SHA,
        "remote_access_mode": "READ_ONLY",
        "remote_write_operations": 0,
        "raw_pii_in_output": False,
        "raw_pii_in_logs": False,
        "scanner_sha256": "d" * 64,
        "policy_sha256": "e" * 64,
        "required_pdf_path_count": 2,
        "summary": {
            "pii_scan_required": 2,
            "pii_scanned": 2,
            "pii_cleared": 2,
            "pii_not_scanned": 0,
            "sha256_mismatches": 0,
            "pii_scan_coverage": 1.0,
        },
        "results": [
            {"content_sha256": MATHS_SHA, "status": "CLEARED", "pii_detected": False},
            {"content_sha256": FR_SHA, "status": "CLEARED", "pii_detected": False},
        ],
    }

    full = builder.build_full_pii_evidence(
        scan,
        source_scan_sha256="f" * 64,
        candidate_inventory_sha256=inventory_sha,
        candidate_content_sha256={MATHS_SHA, FR_SHA},
    )

    assert full["evidence_kind"] == "REAL_CORPUS_PII_SCAN"
    assert full["candidate_inventory_sha256"] == inventory_sha
    assert full["corpus_manifest_sha256"] == CORPUS_SHA
    assert full["policy_sha256"] == "e" * 64
    assert full["scanner_sha256"] == "d" * 64
    assert full["source_scan_evidence_sha256"] == "f" * 64
    assert [row["content_sha256"] for row in full["results"]] == [MATHS_SHA, FR_SHA]
    assert full["summary"]["pdf_total"] == 2
    assert full["summary"]["pii_scan_exempt"] == 0
    assert full["summary"]["pii_scan_scope"] == "WAVE0_EXACT_GRADE_3E_UNIQUE_ARTIFACTS"


def test_full_pii_evidence_rejects_a_different_candidate_set() -> None:
    builder = _module()
    scan = {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "corpus_manifest_sha256": CORPUS_SHA,
        "remote_access_mode": "READ_ONLY",
        "remote_write_operations": 0,
        "raw_pii_in_output": False,
        "raw_pii_in_logs": False,
        "scanner_sha256": "d" * 64,
        "policy_sha256": "e" * 64,
        "summary": {
            "pii_scan_required": 1,
            "pii_scanned": 1,
            "pii_not_scanned": 0,
            "sha256_mismatches": 0,
            "pii_scan_coverage": 1.0,
        },
        "results": [
            {"content_sha256": MATHS_SHA, "status": "CLEARED", "pii_detected": False}
        ],
    }

    with pytest.raises(ValueError, match="candidate set"):
        builder.build_full_pii_evidence(
            scan,
            source_scan_sha256="f" * 64,
            candidate_inventory_sha256="c" * 64,
            candidate_content_sha256={MATHS_SHA, FR_SHA},
        )


def _positive_gates(inventory: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    currentness = {
        row["content_sha256"]: {
            "effective_currentness": "actuel",
            "exact_path": row["physical_path"],
            "current_for_school_year": "2026-2027",
        }
        for row in inventory["candidates"]
    }
    pii = {
        row["content_sha256"]: {"status": "CLEARED", "pii_detected": False}
        for row in inventory["candidates"]
    }
    rights = {row["content_sha256"]: "officiel_public" for row in inventory["candidates"]}
    preflight = {
        row["content_sha256"]: {
            "extraction_complete": True,
            "page_count": 2,
            "empty_extracted_pages": 0,
            "placement_clear": True,
            "programme_conformity": True,
            "profile_conformity": True,
            "chunking_complete": True,
            "page_coverage": 1.0,
            "empty_chunks": 0,
            "oversized_model_chunks": 0,
            "null_page_metadata": 0,
        }
        for row in inventory["candidates"]
    }
    return currentness, pii, rights, preflight


def test_eligibility_partitions_every_candidate_without_stopping_on_failure() -> None:
    builder = _module()
    inventory = builder.build_candidate_inventory(
        _catalog(), sealed_catalog_sha256=CATALOG_SHA, school_year="2026-2027"
    )
    currentness, pii, rights, preflight = _positive_gates(inventory)
    pii[FR_SHA] = {"status": "QUARANTINED_PII", "pii_detected": True}

    evaluated = builder.evaluate_release_candidates(
        inventory,
        currentness_by_sha=currentness,
        pii_by_sha=pii,
        rights_by_sha=rights,
        preflight_by_sha=preflight,
    )

    assert evaluated["counts"] == {
        "candidates": 2,
        "release_eligible": 1,
        "review_required": 1,
    }
    assert evaluated["by_content"][MATHS_SHA]["release_eligible"] is True
    assert evaluated["by_content"][FR_SHA]["release_eligible"] is False
    assert evaluated["by_content"][FR_SHA]["reason_codes"] == ["PII_NOT_CLEARED"]


def test_subject_manifest_fixes_complete_expected_sets() -> None:
    builder = _module()
    inventory = builder.build_candidate_inventory(
        _catalog(), sealed_catalog_sha256=CATALOG_SHA, school_year="2026-2027"
    )
    currentness, pii, rights, preflight = _positive_gates(inventory)
    eligibility = builder.evaluate_release_candidates(
        inventory,
        currentness_by_sha=currentness,
        pii_by_sha=pii,
        rights_by_sha=rights,
        preflight_by_sha=preflight,
    )
    chunks = [
        {
            "chunk_id": _sha(f"{MATHS_SHA}:0:alpha".encode()),
            "chunk_index": 0,
            "chunk_sha256": _sha(b"alpha"),
            "page_start": 1,
            "page_end": 1,
        },
        {
            "chunk_id": _sha(f"{MATHS_SHA}:1:beta".encode()),
            "chunk_index": 1,
            "chunk_sha256": _sha(b"beta"),
            "page_start": 2,
            "page_end": 2,
        },
    ]
    placement_id = "9" * 64
    artifact_preflights = {
        MATHS_SHA: {
            "page_count": 2,
            "placements": [
                {
                    "placement_id": placement_id,
                    "source_placement_id": inventory["candidates"][0]["source_placement_id"],
                    "source_scope": "college/cycle-4/mathematiques",
                    "collection": "rag_nexus_maths_troisieme_tc",
                    "tenant": "libre_troisieme",
                    "niveau": "troisieme",
                    "voie": "college",
                    "matiere": "maths",
                    "statut_enseignement": "tronc_commun",
                    "candidat": "libre",
                    "visibility": "internal",
                    "school_year": "2026-2027",
                    "programme_version": "BOEN_special_11_2018-07-26_aj_2020",
                    "currentness": "current",
                    "placement_status": "active",
                    "review_status": "reviewed",
                }
            ],
            "chunks": chunks,
        }
    }
    authorities = {
        key: value * 64
        for key, value in {
            "corpus_manifest_sha256": "1",
            "sealed_catalog_sha256": "2",
            "placement_catalog_sha256": "3",
            "candidate_inventory_sha256": "4",
            "currentness_evidence_sha256": "5",
            "pii_evidence_sha256": "6",
            "pii_policy_sha256": "7",
            "rights_registry_sha256": "8",
        }.items()
    }
    models = {
        "embedding": {
            "model_id": "intfloat/multilingual-e5-large",
            "inventory_sha256": (
                "e2c7384ba36096b3f3bdfff4973f728596104aff0f1d38f1b6463e60765fe22a"
            ),
            "dimension": 1024,
        },
        "reranker": {
            "model_id": "cross-encoder/ms-marco-MiniLM-L-6-v2",
            "inventory_sha256": (
                "bdcedc4d7cfe647b9aaa5a7546822dfee7826ebb3c64472bf89eae7592e08fe1"
            ),
        },
    }

    manifest = builder.build_subject_release_manifest(
        subject="mathematiques",
        inventory=inventory,
        eligibility=eligibility,
        artifact_preflights=artifact_preflights,
        authorities=authorities,
        profile={
            "version": "wave0-v1",
            "fingerprint": "c" * 64,
            "manifest_digest": "d" * 64,
        },
        models=models,
    )

    assert manifest["release_kind"] == "WAVE0_SUBJECT_RELEASE_V1"
    assert manifest["expected_counts"] == {"artifacts": 1, "placements": 1, "chunks": 2}
    artifact = manifest["artifacts"][0]
    assert artifact["content_sha256"] == MATHS_SHA
    assert artifact["page_count"] == 2
    assert artifact["placements"][0]["placement_id"] == placement_id
    assert artifact["chunks"] == chunks
    assert artifact["placement_id_set_digest"]
    assert artifact["chunk_id_set_digest"]
    assert artifact["chunk_sha256_set_digest"]
    assert artifact["page_coverage_digest"]
