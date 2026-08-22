"""One-off Tier A reproduction + set algebra report generator.

Reproduces the real H2 baseline (no authority) from scratch against the
sealed corpus trove, then computes the exact set algebra over the
currentness-verification registries (multilevel + Wave0) requested for the
2026-08-22 Tier A reconciliation lot. Calls only the real, already-reviewed
gate functions (pii_scan_reconciliation, corpus_catalog_compiler,
h2b_coverage_report) — never reimplements their logic.

Evidence trove paths are machine-local by convention (see
docs/reports/lot_fix_catalog_compiler_schema.md) and are therefore resolved
from environment overrides falling back to the documented ``$HOME``-relative
locations, never hard-coded outside of that fallback.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from rag_pedago.imports import corpus_catalog_compiler as ccc  # noqa: E402
from rag_pedago.imports import h2b_coverage_report as h2b  # noqa: E402
from rag_pedago.imports import pii_scan_reconciliation as pii_recon  # noqa: E402


def _env_path(var: str, default: Path) -> Path:
    raw = os.environ.get(var)
    return Path(raw).expanduser() if raw else default


GDRIVE_ROOT = _env_path(
    "NEXUS_SEALED_CORPUS_ROOT",
    Path.home() / "Téléchargements" / "NEXUS_RAG_GDRIVE_READY",
)
MANIFEST_PATH = _env_path(
    "NEXUS_SEALED_MANIFEST_PATH", GDRIVE_ROOT / "00_ADMIN" / "SHA256SUMS.txt"
)
PLACEMENT_CATALOG_PATH = _env_path(
    "NEXUS_PLACEMENT_CATALOG_PATH", GDRIVE_ROOT / "00_ADMIN" / "eduscol_affectations.tsv"
)
PII_TROVE_ROOT = _env_path(
    "NEXUS_H2_EVIDENCE_ROOT", Path.home() / "Documents" / "NEXUS_RAG_H2_EVIDENCE"
)
PII_EXHAUSTIVE_PATH = _env_path(
    "NEXUS_PII_EXHAUSTIVE_SCAN_PATH",
    PII_TROVE_ROOT / "h2b_exhaustive_pii_scan_20260813.jsonl",
)
PII_CAMPAIGN_PATH = _env_path(
    "NEXUS_PII_CAMPAIGN_SCAN_PATH", PII_TROVE_ROOT / "h2b_pii_evidence_20260808.json"
)

CONFIGS_ROOT = SERVICE_ROOT / "configs"
ROUTING_PATH = CONFIGS_ROOT / "corpus_zone_routing.yml"
RIGHTS_PATH = CONFIGS_ROOT / "rights_evidence_registry.yml"
GOLDEN_PATH = CONFIGS_ROOT / "golden_corpus_h2b.yml"
CURRENTNESS_MULTILEVEL_PATH = (
    CONFIGS_ROOT / "prerentree_2026_2027" / "multilevel_currentness_evidence.yml"
)
CURRENTNESS_WAVE0_PATH = (
    CONFIGS_ROOT / "prerentree_2026_2027" / "wave0_currentness_evidence_v2.yml"
)

WORK_DIR = _env_path("NEXUS_TIER_A_WORK_DIR", Path("/tmp/tier_a_set_algebra_work"))
WORK_DIR.mkdir(parents=True, exist_ok=True)
CATALOG_JSON_PATH = WORK_DIR / "governed_sealed_catalog.json"
PII_EVIDENCE_JSON_PATH = WORK_DIR / "reconciled_pii_evidence.json"

REPO_ROOT = SERVICE_ROOT.parents[1]
OUT_JSON = REPO_ROOT / "docs" / "reports" / "tier_a_set_algebra_reconciliation_20260822.json"
OUT_MD = REPO_ROOT / "docs" / "reports" / "lot_tier_a_set_algebra_20260822.md"


def _sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_of_sorted(values: list[str]) -> str:
    import hashlib

    canonical = "".join(f"{v}\n" for v in sorted(values)).encode()
    return hashlib.sha256(canonical).hexdigest()


def step1_reproduce_baseline() -> tuple[h2b.CoverageReport, ccc.SealedCorpusCatalog, dict]:
    manifest_sha256 = ccc.compute_file_sha256(MANIFEST_PATH)
    routing_config = ccc.load_routing_config(ROUTING_PATH)
    routing_config["manifest_sha256"] = manifest_sha256

    manifest_entries = ccc._parse_sealed_manifest(MANIFEST_PATH)  # noqa: SLF001

    pii_evidence = pii_recon.reconcile_pii_scan_evidence(
        exhaustive_scan_path=PII_EXHAUSTIVE_PATH,
        campaign_scan_path=PII_CAMPAIGN_PATH,
        manifest_entries=manifest_entries,
        manifest_sha256=manifest_sha256,
        policy_version="nexus-tier-a-set-algebra-20260822/1.0.0",
        scanner_version="nexus-tier-a-set-algebra-20260822/1.0.0",
    )
    required = pii_evidence["required_pdf_path_count"]
    results = pii_evidence["results"]
    cleared = sum(1 for r in results if r["status"] == "CLEARED")
    quarantined = sum(1 for r in results if r["status"] == "QUARANTINED_PII")
    review_required = sum(
        1 for r in results if r["status"] == "REVIEW_REQUIRED_EXTRACTION_FAILED"
    )
    print(
        f"[PII reconciliation] required_pdf_path_count={required} "
        f"results={len(results)} CLEARED={cleared} QUARANTINED_PII={quarantined} "
        f"REVIEW_REQUIRED_EXTRACTION_FAILED={review_required}"
    )
    expected = (2476, 2475, 2286, 146, 43)
    actual = (required, len(results), cleared, quarantined, review_required)
    if actual != expected:
        raise SystemExit(
            f"PII reconciliation MISMATCH vs PR#108 cross-check: expected {expected}, got {actual}"
        )

    PII_EVIDENCE_JSON_PATH.write_text(json.dumps(pii_evidence, ensure_ascii=False), encoding="utf-8")

    rights_registry = yaml.safe_load(RIGHTS_PATH.read_text(encoding="utf-8"))

    catalog = ccc.compile_governed_sealed_catalog(
        MANIFEST_PATH, PLACEMENT_CATALOG_PATH, routing_config, rights_registry, pii_evidence
    )
    catalog_dict = catalog.to_dict(include_objects=True)
    CATALOG_JSON_PATH.write_text(
        json.dumps(catalog_dict, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = h2b.generate_coverage_report(
        catalog_path=CATALOG_JSON_PATH,
        rights_path=RIGHTS_PATH,
        pii_path=PII_EVIDENCE_JSON_PATH,
        routing_path=ROUTING_PATH,
        golden_path=GOLDEN_PATH,
        manifest_path=MANIFEST_PATH,
        authority_path=None,
        authority_revocations_path=None,
        authority_review_binding_path=None,
        authority_trust_anchor_path=None,
        authority_environment="production",
        expected_total=2584,
        expected_manifest_sha256=None,
        currentness_verification_path=CURRENTNESS_MULTILEVEL_PATH,
    )
    print(
        "[H2 baseline] "
        f"blocked_ingest_candidates={report.blocked_ingest_candidates} "
        f"authority_required_count={report.authority_required_count} "
        f"authority_required_set_sha256={report.authority_required_set_sha256} "
        f"h2_coverage_gate_pass={report.h2_coverage_gate_pass} "
        f"golden_validation_pass={report.golden_validation_pass} "
        f"golden_controls={report.golden_controls_passed}/{report.golden_controls_total}"
    )
    expected_authority_sha = (
        "3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0"
    )
    pii_blocked = report.mandatory_gate_blockers.get("pii", None)
    ok = (
        report.blocked_ingest_candidates == 73
        and report.authority_required_count == 72
        and report.authority_required_set_sha256 == expected_authority_sha
        and report.h2_coverage_gate_pass is False
    )
    if not ok:
        raise SystemExit(
            "H2 baseline reproduction MISMATCH vs PR#125: "
            f"blocked={report.blocked_ingest_candidates} (want 73), "
            f"authority_required={report.authority_required_count} (want 72), "
            f"digest={report.authority_required_set_sha256} (want {expected_authority_sha}), "
            f"gate_pass={report.h2_coverage_gate_pass} (want False)"
        )
    print(f"[SANITY GATE] PASS — baseline reproduced exactly. pii_blocked={pii_blocked}")
    return report, catalog, catalog_dict


def _artifact_reason_codes(entry: dict) -> list[str]:
    codes = entry.get("reason_codes")
    return list(codes) if isinstance(codes, list) else []


def step2_5_set_algebra(catalog_dict: dict) -> dict:
    objects_by_sha: dict[str, dict] = {}
    for obj in catalog_dict.get("physical_objects", []):
        objects_by_sha.setdefault(obj["content_sha256"], obj)

    multilevel = json.loads(CURRENTNESS_MULTILEVEL_PATH.read_text(encoding="utf-8"))
    wave0 = yaml.safe_load(CURRENTNESS_WAVE0_PATH.read_text(encoding="utf-8"))

    multilevel_current = {
        a["content_sha256"] for a in multilevel["artifacts"] if a["decision"] == "CURRENT"
    }
    multilevel_review_required = {
        a["content_sha256"] for a in multilevel["artifacts"] if a["decision"] == "REVIEW_REQUIRED"
    }
    assert not (multilevel_current & multilevel_review_required)
    assert len(multilevel_current) == 12
    assert len(multilevel_review_required) == 138

    wave0_sha = {a["content_sha256"] for a in wave0["artifacts"]}
    assert len(wave0_sha) == 2

    def pool_status(sha: str) -> tuple[str | None, str | None]:
        obj = objects_by_sha.get(sha)
        if obj is None:
            return None, None
        return obj.get("base_disposition"), obj.get("currentness")

    undetermined_pool = {"unclassified", "a_verifier"}

    current_in_pool = {
        sha for sha in multilevel_current if pool_status(sha)[1] in undetermined_pool
    }
    current_already_elsewhere = multilevel_current - current_in_pool

    review_required_in_pool = {
        sha for sha in multilevel_review_required if pool_status(sha)[1] in undetermined_pool
    }
    review_required_not_in_pool = multilevel_review_required - review_required_in_pool

    wave0_in_pool = {sha for sha in wave0_sha if pool_status(sha)[1] in undetermined_pool}

    set_current = current_in_pool
    set_wave0 = wave0_in_pool
    set_review_required_pending = review_required_in_pool

    current_intersect_wave0 = set_current & set_wave0
    current_intersect_review = set_current & set_review_required_pending
    wave0_intersect_review = set_wave0 & set_review_required_pending
    triple = set_current & set_wave0 & set_review_required_pending
    union = set_current | set_wave0 | set_review_required_pending

    raw_registry_union = multilevel_current | multilevel_review_required | wave0_sha

    # ------------------------------------------------------------------
    # Step 3 — PII-cleared vs PII+rights-cleared universes
    # ------------------------------------------------------------------
    manifest_entries = ccc._parse_sealed_manifest(MANIFEST_PATH)  # noqa: SLF001
    unique_content_sha = {sha for sha, _ in manifest_entries}

    pii_evidence = json.loads(PII_EVIDENCE_JSON_PATH.read_text(encoding="utf-8"))
    pii_cleared_sha = {
        r["content_sha256"] for r in pii_evidence["results"] if r["status"] == "CLEARED"
    }

    rights_registry = yaml.safe_load(RIGHTS_PATH.read_text(encoding="utf-8"))
    routing_config = yaml.safe_load(ROUTING_PATH.read_text(encoding="utf-8"))
    routing_config["manifest_sha256"] = ccc.compute_file_sha256(MANIFEST_PATH)
    rights_cleared_sha = ccc._derive_rights_clearances(  # noqa: SLF001
        manifest_entries,
        routing_config["manifest_sha256"],
        rights_registry,
        routing_config,
    )

    registry_covered_sha = multilevel_current | multilevel_review_required | wave0_sha

    def classify_universe(candidate_sha: set[str]) -> dict:
        undetermined = {
            sha
            for sha in candidate_sha
            if pool_status(sha)[1] in undetermined_pool
            or pool_status(sha)[1] == "unclassified"
        }
        a_verifier_only = {sha for sha in undetermined if pool_status(sha)[1] == "a_verifier"}
        unclassified_only = {sha for sha in undetermined if pool_status(sha)[1] == "unclassified"}
        zero_registry = unclassified_only - registry_covered_sha
        registry_covered = unclassified_only & registry_covered_sha
        return {
            "UNCLASSIFIED_ZERO_REGISTRY": len(zero_registry),
            "UNCLASSIFIED_REGISTRY_COVERED": len(registry_covered),
            "A_VERIFIER": len(a_verifier_only),
            "TOTAL_CURRENTNESS_UNDETERMINED": len(undetermined),
        }

    pii_cleared_universe = classify_universe(pii_cleared_sha & unique_content_sha)
    pii_and_rights_universe = classify_universe(
        (pii_cleared_sha & rights_cleared_sha) & unique_content_sha
    )

    # ------------------------------------------------------------------
    # Step 4 — historical delta
    # ------------------------------------------------------------------
    historical_reported = 1252
    current_reproduced_predicate = pii_cleared_universe["UNCLASSIFIED_ZERO_REGISTRY"]

    # ------------------------------------------------------------------
    # Step 5 — byte-identity audit input list (SET_REVIEW_REQUIRED_PENDING)
    # ------------------------------------------------------------------
    byte_identity_rows = []
    multilevel_by_sha = {a["content_sha256"]: a for a in multilevel["artifacts"]}
    for sha in sorted(set_review_required_pending):
        obj = objects_by_sha.get(sha, {})
        art = multilevel_by_sha.get(sha, {})
        row = {
            "content_sha256": sha,
            "canonical_path": obj.get("path") or art.get("exact_path"),
            "source_registry": "multilevel_currentness_evidence.yml",
            "source_url": art.get("current_source_listing_url"),
            "programme_version": art.get("current_for_school_year"),
            "http_result": None,
            "download_sha256": None,
            "byte_identity": None,
            "decision": None,
            "effective_currentness": None,
            "reason_code": _artifact_reason_codes(art),
        }
        byte_identity_rows.append(row)

    return {
        "counts": {
            "set_current": len(set_current),
            "set_wave0": len(set_wave0),
            "set_review_required_pending": len(set_review_required_pending),
            "current_intersect_wave0": len(current_intersect_wave0),
            "current_intersect_review_required": len(current_intersect_review),
            "wave0_intersect_review_required": len(wave0_intersect_review),
            "triple_intersection": len(triple),
            "union_registry_covered_unclassified": len(union),
            "raw_registry_union_all_decisions": len(raw_registry_union),
            "multilevel_current_total": len(multilevel_current),
            "multilevel_current_already_elsewhere_ingest": len(current_already_elsewhere),
            "multilevel_review_required_total": len(multilevel_review_required),
            "multilevel_review_required_not_in_undetermined_pool": len(review_required_not_in_pool),
            "wave0_total_real_artifacts": len(wave0_sha),
            "wave0_outside_undetermined_pool": len(wave0_sha - wave0_in_pool),
        },
        "pii_cleared_currentness_undetermined": pii_cleared_universe,
        "pii_and_rights_cleared_currentness_undetermined": pii_and_rights_universe,
        "historical_delta": {
            "historical_reported_tier_a": historical_reported,
            "current_reproduced_historical_predicate": current_reproduced_predicate,
            "delta": historical_reported - current_reproduced_predicate,
            "forensically_resolvable": historical_reported == current_reproduced_predicate,
        },
        "byte_identity_audit_input": byte_identity_rows,
        "sets_debug": {
            "current_already_elsewhere_ingest_sha": sorted(current_already_elsewhere),
            "wave0_sha": sorted(wave0_sha),
            "wave0_outside_pool_sha": sorted(wave0_sha - wave0_in_pool),
        },
    }


def main() -> int:
    report, catalog, catalog_dict = step1_reproduce_baseline()
    algebra = step2_5_set_algebra(catalog_dict)

    generated_at = datetime.now(UTC).isoformat()
    manifest_sha256 = ccc.compute_file_sha256(MANIFEST_PATH)
    input_set_sha256 = _sha256_of_sorted(
        [row["content_sha256"] for row in algebra["byte_identity_audit_input"]]
    )

    output_doc = {
        "protocol_version": "NEXUS-TIER-A-SET-ALGEBRA-V1",
        "producer_version": "nexus-tier-a-set-algebra-report/1.0.0",
        "generated_at": generated_at,
        "manifest_sha256": manifest_sha256,
        "input_set_sha256": input_set_sha256,
        "h2_baseline_reproduction": {
            "blocked_ingest_candidates": report.blocked_ingest_candidates,
            "authority_required_count": report.authority_required_count,
            "authority_required_set_sha256": report.authority_required_set_sha256,
            "pii_blocked_count": report.mandatory_gate_blockers.get("pii"),
            "h2_coverage_gate_pass": report.h2_coverage_gate_pass,
            "golden_validation_pass": report.golden_validation_pass,
        },
        "set_algebra": algebra["counts"],
        "pii_cleared_currentness_undetermined": algebra["pii_cleared_currentness_undetermined"],
        "pii_and_rights_cleared_currentness_undetermined": algebra[
            "pii_and_rights_cleared_currentness_undetermined"
        ],
        "historical_delta": algebra["historical_delta"],
        "byte_identity_audit_input_count": len(algebra["byte_identity_audit_input"]),
        "byte_identity_audit_input": algebra["byte_identity_audit_input"],
        "sets_debug": algebra["sets_debug"],
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(output_doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote {OUT_JSON}")
    print(json.dumps(output_doc["set_algebra"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
