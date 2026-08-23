"""Recalcul read-only du set final de release et de sa comptabilité terminale.

Le script compose les compilateurs et gates existants. Il ne contient ni set
pré-calculé, ni total de release attendu. Tous les artefacts produits sont
écrits sous le ``--output-dir`` explicite.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from rag_pedago.imports import corpus_catalog_compiler as ccc  # noqa: E402
from rag_pedago.imports import h2b_coverage_report as h2b  # noqa: E402
from rag_pedago.imports import pii_scan_reconciliation as pii_recon  # noqa: E402


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _canonical_sha_set_bytes(values: frozenset[str]) -> bytes:
    """Sérialise un set de SHA avec la convention du gate H2 existant."""
    return "".join(f"{value}\n" for value in sorted(values)).encode("ascii")


def _terminal_accounting(
    physical_objects: list[dict[str, Any]],
    authority_required: frozenset[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Résout une disposition terminale fail-closed par identité de contenu."""
    by_sha: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in physical_objects:
        if item.get("is_manifest_self") is True:
            continue
        by_sha[str(item["content_sha256"])].append(item)

    rows: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for content_sha256 in sorted(by_sha):
        placements = by_sha[content_sha256]
        dispositions = sorted({str(item.get("disposition")) for item in placements})
        base_dispositions = sorted({str(item.get("base_disposition")) for item in placements})
        final_conflict = len(dispositions) != 1
        base_conflict = len(base_dispositions) != 1
        if content_sha256 in authority_required and final_conflict:
            raise ValueError(
                f"authority-required content {content_sha256} has conflicting "
                f"final dispositions {dispositions!r}"
            )
        if content_sha256 in authority_required and base_conflict:
            raise ValueError(
                f"authority-required content {content_sha256} has conflicting "
                f"base dispositions {base_dispositions!r}"
            )
        if final_conflict or base_conflict:
            conflicts.append(
                {
                    "base_dispositions": base_dispositions,
                    "content_sha256": content_sha256,
                    "dispositions": dispositions,
                }
            )
        canonical_disposition = (
            dispositions[0] if not final_conflict and not base_conflict else "REVIEW_REQUIRED"
        )
        release_disposition = (
            "INGEST_CANDIDATE" if content_sha256 in authority_required else canonical_disposition
        )
        rows.append(
            {
                "base_dispositions": base_dispositions,
                "canonical_disposition": canonical_disposition,
                "content_sha256": content_sha256,
                "paths": sorted(str(item.get("path")) for item in placements),
                "release_terminal_disposition": release_disposition,
            }
        )
    return rows, conflicts


def recompute(args: argparse.Namespace) -> dict[str, Any]:
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_sha256 = _sha256_file(args.manifest)
    routing_config = ccc.load_routing_config(args.routing)
    routing_config["manifest_sha256"] = manifest_sha256
    manifest_entries = ccc._parse_sealed_manifest(args.manifest)  # noqa: SLF001

    pii_evidence = pii_recon.reconcile_pii_scan_evidence(
        exhaustive_scan_path=args.pii_exhaustive,
        campaign_scan_path=args.pii_campaign,
        manifest_entries=manifest_entries,
        manifest_sha256=manifest_sha256,
        policy_version="nexus-final-release-recalculation/1.0.0",
        scanner_version="nexus-final-release-recalculation/1.0.0",
    )
    pii_path = output_dir / "reconciled_pii_evidence.json"
    _write_json(pii_path, pii_evidence)

    rights_registry = yaml.safe_load(args.rights.read_text(encoding="utf-8"))
    catalog = ccc.compile_governed_sealed_catalog(
        args.manifest,
        args.placements,
        routing_config,
        rights_registry,
        pii_evidence,
    )
    catalog_dict = catalog.to_dict(include_objects=True)
    catalog_path = output_dir / "governed_sealed_catalog.json"
    _write_json(catalog_path, catalog_dict)

    report = h2b.generate_coverage_report(
        catalog_path=catalog_path,
        rights_path=args.rights,
        pii_path=pii_path,
        routing_path=args.routing,
        golden_path=args.golden,
        manifest_path=args.manifest,
        authority_path=None,
        authority_revocations_path=None,
        authority_review_binding_path=None,
        authority_trust_anchor_path=None,
        authority_environment="production",
        expected_total=int(catalog_dict["physical_object_count"]),
        expected_manifest_sha256=manifest_sha256,
        currentness_verification_path=args.currentness,
    )
    (output_dir / "h2_coverage_no_authority.md").write_text(
        h2b.render_markdown(report) + "\n",
        encoding="utf-8",
    )

    physical_objects = copy.deepcopy(catalog_dict["physical_objects"])
    currentness_verified = h2b._load_currentness_verification_evidence(  # noqa: SLF001
        args.currentness,
        manifest_sha256=manifest_sha256,
    )
    clearance_entries = [
        (str(item.get("content_sha256")), str(item.get("path"))) for item in physical_objects
    ]
    rights_cleared = frozenset(
        ccc._derive_rights_clearances(  # noqa: SLF001
            clearance_entries,
            manifest_sha256,
            rights_registry,
            routing_config,
        )
    )
    pii_cleared, pii_quarantined = ccc._derive_pii_clearances(  # noqa: SLF001
        clearance_entries,
        manifest_sha256,
        pii_evidence,
        routing_config,
    )
    promoted_count = h2b._promote_currentness_verified_candidates(  # noqa: SLF001
        physical_objects,
        currentness_verified_sha256=currentness_verified,
        rights_cleared_sha256=rights_cleared,
        pii_cleared_sha256=frozenset(pii_cleared),
        pii_quarantined_sha256=frozenset(pii_quarantined),
    )
    required_set, _required_rights = h2b.authority_required_candidate_facts(physical_objects)
    required_digest = h2b.authority_required_set_digest(required_set)
    exact_set_bytes = _canonical_sha_set_bytes(required_set)
    (output_dir / "final_authority_required_set.txt").write_bytes(exact_set_bytes)

    terminal_rows, canonical_conflicts = _terminal_accounting(
        physical_objects,
        required_set,
    )
    (output_dir / "terminal_content_dispositions.jsonl").write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in terminal_rows
        ),
        encoding="utf-8",
    )
    release_counts = Counter(row["release_terminal_disposition"] for row in terminal_rows)
    canonical_counts = Counter(row["canonical_disposition"] for row in terminal_rows)
    unique_content_count = len(terminal_rows)
    expected_content_sha256 = {content_sha256 for content_sha256, _ in manifest_entries}
    accounted_content_sha256 = {row["content_sha256"] for row in terminal_rows}
    unaccounted_content_sha256 = sorted(expected_content_sha256 - accounted_content_sha256)
    unexpected_content_sha256 = sorted(accounted_content_sha256 - expected_content_sha256)
    coverage_percent = (
        len(expected_content_sha256 & accounted_content_sha256) / len(expected_content_sha256) * 100
        if expected_content_sha256
        else 0.0
    )
    base_ingest_candidates = sum(
        any(item.get("base_disposition") == "INGEST" for item in placements)
        for placements in _group_by_content(physical_objects).values()
    )

    summary: dict[str, Any] = {
        "input_digests": {
            str(path): _sha256_file(path)
            for path in (
                args.manifest,
                args.placements,
                args.pii_exhaustive,
                args.pii_campaign,
                args.routing,
                args.rights,
                args.golden,
                args.currentness,
            )
        },
        "catalog": {
            "content_artifact_count": catalog_dict.get("content_artifact_count"),
            "currentness_promoted_physical_count": promoted_count,
            "manifest_entry_count": len(manifest_entries),
            "physical_object_count": catalog_dict["physical_object_count"],
            "unique_content_sha256": unique_content_count,
        },
        "final_base_ingest_candidates": base_ingest_candidates,
        "final_non_authority_blocked_count": report.non_authority_blocked_final_count,
        "final_authority_required_count": len(required_set),
        "final_authority_required_set_sha256": required_digest,
        "h2_report": {
            "authority_covered_count": report.authority_covered_count,
            "authority_required_count": report.authority_required_count,
            "authority_required_set_sha256": report.authority_required_set_sha256,
            "blocked_ingest_candidates": report.blocked_ingest_candidates,
            "decision_coverage_complete": report.decision_coverage_complete,
            "final_ingest_count": report.final_ingest_count,
            "golden_controls": (f"{report.golden_controls_passed}/{report.golden_controls_total}"),
            "golden_validation_pass": report.golden_validation_pass,
            "h2_coverage_gate_pass": report.h2_coverage_gate_pass,
        },
        "terminal_content_accounting": {
            "canonical_conflict_count": len(canonical_conflicts),
            "canonical_conflicts": canonical_conflicts,
            "canonical_disposition_counts": dict(sorted(canonical_counts.items())),
            "coverage_percent": coverage_percent,
            "release_terminal_disposition_counts": dict(sorted(release_counts.items())),
            "unaccounted_content_sha256": unaccounted_content_sha256,
            "unaccounted_contents": len(unaccounted_content_sha256),
            "unexpected_content_sha256": unexpected_content_sha256,
            "unexpected_contents": len(unexpected_content_sha256),
        },
    }
    _write_json(output_dir / "summary.json", summary)
    return summary


def _group_by_content(
    physical_objects: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in physical_objects:
        if item.get("is_manifest_self") is not True:
            grouped[str(item["content_sha256"])].append(item)
    return grouped


def _parser() -> argparse.ArgumentParser:
    configs = SERVICE_ROOT / "configs"
    sealed_root = Path(
        os.environ.get(
            "NEXUS_SEALED_CORPUS_ROOT",
            Path.home() / "Téléchargements" / "NEXUS_RAG_GDRIVE_READY",
        )
    )
    evidence_root = Path(
        os.environ.get(
            "NEXUS_H2_EVIDENCE_ROOT",
            Path.home() / "Documents" / "NEXUS_RAG_H2_EVIDENCE",
        )
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=sealed_root / "00_ADMIN" / "SHA256SUMS.txt",
    )
    parser.add_argument(
        "--placements",
        type=Path,
        default=sealed_root / "00_ADMIN" / "eduscol_affectations.tsv",
    )
    parser.add_argument(
        "--pii-exhaustive",
        type=Path,
        default=evidence_root / "h2b_exhaustive_pii_scan_20260813.jsonl",
    )
    parser.add_argument(
        "--pii-campaign",
        type=Path,
        default=evidence_root / "h2b_pii_evidence_20260808.json",
    )
    parser.add_argument(
        "--routing",
        type=Path,
        default=configs / "corpus_zone_routing.yml",
    )
    parser.add_argument(
        "--rights",
        type=Path,
        default=configs / "rights_evidence_registry.yml",
    )
    parser.add_argument(
        "--golden",
        type=Path,
        default=configs / "golden_corpus_h2b.yml",
    )
    parser.add_argument(
        "--currentness",
        type=Path,
        default=(configs / "prerentree_2026_2027" / "multilevel_currentness_evidence.yml"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    summary = recompute(_parser().parse_args(argv))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
