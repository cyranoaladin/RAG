"""Bounded, read-only PII scan runner for the sealed production corpus."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeGuard

import yaml

from rag_pedago.imports.corpus_catalog_compiler import (
    Disposition,
    _determine_disposition,
    _parse_sealed_manifest,
    load_routing_config,
)
from rag_pedago.imports.pii_scanner import (
    PIIScanResult,
    load_patterns_from_config,
    result_to_dict,
    scan_pdf,
)

CANONICAL_REMOTE_ROOT = "gdrive_ert:NEXUS_RAG/NEXUS_RAG_GDRIVE_READY"
SCANNER_VERSION = "pii_scanner_h2b_v2"

ScanFile = Callable[[Path], PIIScanResult]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validated_policy(policy_path: Path) -> tuple[str, str]:
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict):
        raise ValueError("PII policy must be a mapping")
    policy_id = policy.get("policy_id")
    if not isinstance(policy_id, str) or not policy_id:
        raise ValueError("PII policy_id must be a non-empty string")
    return policy_id, _file_sha256(policy_path)


def _validated_local_mirror(local_mirror: Path) -> Path:
    resolved = local_mirror.resolve()
    tmp_root = Path("/tmp").resolve()
    if resolved == tmp_root or tmp_root not in resolved.parents:
        raise ValueError("PII local mirror must be a dedicated path under /tmp")
    if not resolved.is_dir():
        raise ValueError("PII local mirror must already exist")
    return resolved


def _safe_scan_payload(result: PIIScanResult) -> dict[str, Any]:
    payload = result_to_dict(result)
    payload.pop("sha256", None)
    return payload


def _build_summary(
    physical_pdf_total: int,
    required_pdf_count: int,
    unique_pdf_count: int,
    results: list[dict[str, Any]],
    *,
    scan_scope: str,
) -> dict[str, int | float | str]:
    def physical_count(*statuses: str) -> int:
        accepted = set(statuses)
        return sum(
            int(item["physical_object_count"])
            for item in results
            if item["status"] in accepted
        )

    scanned = physical_count("CLEARED", "QUARANTINED_PII")
    cleared = physical_count("CLEARED")
    review_required = sum(
        int(item["physical_object_count"])
        for item in results
        if str(item["status"]).startswith("REVIEW_REQUIRED_")
    )
    quarantined = sum(
        int(item["physical_object_count"])
        for item in results
        if str(item["status"]).startswith("QUARANTINED_")
    )
    extraction_failed = physical_count("REVIEW_REQUIRED_EXTRACTION_FAILED")
    sha256_mismatches = physical_count("QUARANTINED_SHA_MISMATCH")
    not_scanned = required_pdf_count - scanned
    coverage = scanned / required_pdf_count if required_pdf_count else 1.0
    return {
        "pdf_total": physical_pdf_total,
        "pii_scan_scope": scan_scope,
        "pii_scan_required": required_pdf_count,
        "pii_scan_exempt": physical_pdf_total - required_pdf_count,
        "unique_pdf_content": unique_pdf_count,
        "unique_content_attempted": len(results),
        "pii_scanned": scanned,
        "pii_cleared": cleared,
        "pii_review_required": review_required,
        "pii_quarantined": quarantined,
        "pii_extraction_failed": extraction_failed,
        "pii_not_scanned": not_scanned,
        "pii_scan_coverage": coverage,
        "sha256_mismatches": sha256_mismatches,
    }


def scan_remote_corpus(
    manifest_path: Path,
    policy_path: Path,
    remote_root: str,
    local_mirror: Path,
    *,
    expected_manifest_sha256: str,
    scan_file: ScanFile = scan_pdf,
    required_pdf_paths: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """Scan only a pre-staged local mirror; this boundary performs no transport."""
    if remote_root != CANONICAL_REMOTE_ROOT:
        raise ValueError("remote root is not the canonical read-only corpus remote")
    mirror = _validated_local_mirror(local_mirror)
    manifest_sha256 = _file_sha256(manifest_path)
    if manifest_sha256 != expected_manifest_sha256:
        raise ValueError("corpus manifest SHA256 mismatch")
    policy_version, policy_sha256 = _validated_policy(policy_path)
    scanner_sha256 = _file_sha256(Path(__file__).with_name("pii_scanner.py"))

    all_pdf_entries = [
        (content_sha256, object_path)
        for content_sha256, object_path in _parse_sealed_manifest(manifest_path)
        if object_path.lower().endswith(".pdf")
    ]
    all_pdf_paths = {object_path for _, object_path in all_pdf_entries}
    if required_pdf_paths is None:
        pdf_entries = all_pdf_entries
        scan_scope = "ALL_CORPUS_PDFS"
    else:
        if not required_pdf_paths or not required_pdf_paths <= all_pdf_paths:
            raise ValueError("required PDF paths must be a non-empty manifest subset")
        pdf_entries = [
            entry for entry in all_pdf_entries if entry[1] in required_pdf_paths
        ]
        scan_scope = "INITIAL_PRODUCTION_ELIGIBLE_PDFS"
    grouped: dict[str, list[str]] = {}
    for content_sha256, object_path in pdf_entries:
        grouped.setdefault(content_sha256, []).append(object_path)

    results: list[dict[str, Any]] = []
    for content_sha256, physical_paths in grouped.items():
        local_files: list[Path] = []
        status = ""
        safe_payload: dict[str, Any] = {}
        error_code: str | None = None
        try:
            for physical_path in physical_paths:
                local_target = mirror.joinpath(*Path(physical_path).parts)
                if not local_target.is_file():
                    status = "REVIEW_REQUIRED_LOCAL_FILE_MISSING"
                    error_code = "LOCAL_FILE_MISSING"
                    break
                if _file_sha256(local_target) != content_sha256:
                    status = "QUARANTINED_SHA_MISMATCH"
                    error_code = "CONTENT_SHA256_MISMATCH"
                    break
                local_files.append(local_target)

            if not status:
                try:
                    scan_result = scan_file(local_files[0])
                except Exception:
                    status = "REVIEW_REQUIRED_SCANNER_FAILED"
                    error_code = "SCANNER_FAILED"
                else:
                    safe_payload = _safe_scan_payload(scan_result)
                    if scan_result.extraction_error:
                        status = "REVIEW_REQUIRED_EXTRACTION_FAILED"
                        error_code = str(safe_payload["extraction_error_code"])
                    elif scan_result.pii_detected:
                        status = "QUARANTINED_PII"
                    else:
                        status = "CLEARED"
        except Exception:
            status = "REVIEW_REQUIRED_LOCAL_INPUT_FAILED"
            error_code = "LOCAL_INPUT_FAILED"

        result = {
            "content_sha256": content_sha256,
            "physical_object_count": len(physical_paths),
            "status": status,
            "error_code": error_code,
            **safe_payload,
        }
        result.pop("extraction_error_code", None)
        results.append(result)

    summary = _build_summary(
        len(all_pdf_entries),
        len(pdf_entries),
        len(grouped),
        results,
        scan_scope=scan_scope,
    )
    required_path_digest = hashlib.sha256(
        "".join(f"{value}\n" for value in sorted(path for _, path in pdf_entries)).encode()
    ).hexdigest()
    return {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "generated_at": datetime.now(UTC).isoformat(),
        "scanner_version": SCANNER_VERSION,
        "scanner_sha256": scanner_sha256,
        "policy_version": policy_version,
        "policy_sha256": policy_sha256,
        "corpus_manifest_sha256": manifest_sha256,
        "remote_root": remote_root,
        "remote_access_mode": "READ_ONLY",
        "remote_write_operations": 0,
        "raw_pii_in_output": False,
        "raw_pii_in_logs": False,
        "required_pdf_path_count": len(pdf_entries),
        "required_pdf_path_set_digest": required_path_digest,
        "summary": summary,
        "results": results,
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def pii_scan_exit_code(summary: dict[str, int | float | str]) -> int:
    """Return success only for a non-empty, conclusively scanned perimeter."""
    def is_exact_int(value: object) -> TypeGuard[int]:
        return isinstance(value, int) and not isinstance(value, bool)

    required = summary.get("pii_scan_required")
    scanned = summary.get("pii_scanned")
    cleared = summary.get("pii_cleared")
    quarantined = summary.get("pii_quarantined")
    not_scanned = summary.get("pii_not_scanned")
    review_required = summary.get("pii_review_required")
    extraction_failed = summary.get("pii_extraction_failed")
    coverage = summary.get("pii_scan_coverage")
    mismatches = summary.get("sha256_mismatches")
    complete = (
        is_exact_int(required)
        and required > 0
        and is_exact_int(scanned)
        and scanned == required
        and is_exact_int(cleared)
        and cleared >= 0
        and is_exact_int(quarantined)
        and quarantined >= 0
        and cleared + quarantined == scanned
        and is_exact_int(not_scanned)
        and not_scanned == 0
        and is_exact_int(review_required)
        and review_required == 0
        and is_exact_int(extraction_failed)
        and extraction_failed == 0
        and isinstance(coverage, int | float)
        and not isinstance(coverage, bool)
        and coverage == 1.0
        and is_exact_int(mismatches)
        and mismatches == 0
    )
    return 0 if complete else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--remote-root", default=CANONICAL_REMOTE_ROOT)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--local-mirror", type=Path, required=True)
    parser.add_argument(
        "--scan-scope",
        choices=("all", "initial-production-eligible"),
        default="all",
    )
    parser.add_argument("--routing-config", type=Path)
    args = parser.parse_args()

    patterns = load_patterns_from_config(args.policy)

    def configured_scan(path: Path) -> PIIScanResult:
        return scan_pdf(path, patterns)

    try:
        if _file_sha256(args.manifest) != args.expected_manifest_sha256:
            raise ValueError("corpus manifest SHA256 mismatch")
        all_entries = _parse_sealed_manifest(args.manifest)
        required_pdf_paths: set[str] | None = None
        if args.scan_scope == "initial-production-eligible":
            if args.routing_config is None:
                raise ValueError("initial scan scope requires a routing config")
            routing = load_routing_config(args.routing_config)
            required_pdf_paths = {
                object_path
                for _, object_path in all_entries
                if object_path.lower().endswith(".pdf")
                and _determine_disposition(object_path, routing)[0]
                is Disposition.INGEST
            }
        evidence = scan_remote_corpus(
            args.manifest,
            args.policy,
            args.remote_root,
            args.local_mirror,
            expected_manifest_sha256=args.expected_manifest_sha256,
            scan_file=configured_scan,
            required_pdf_paths=required_pdf_paths,
        )
    except KeyboardInterrupt:
        print("PII_SCAN_INTERRUPTED=true")
        return 130
    except Exception:
        print("PII_SCAN_FAILED=true")
        return 2
    _write_json_atomic(args.output, evidence)
    summary = evidence["summary"]
    print(f"PII_SCAN_REQUIRED={summary['pii_scan_required']}")
    print(f"PII_SCANNED={summary['pii_scanned']}")
    print(f"PII_CLEARED={summary['pii_cleared']}")
    print(f"PII_REVIEW_REQUIRED={summary['pii_review_required']}")
    print(f"PII_QUARANTINED={summary['pii_quarantined']}")
    print(f"PII_EXTRACTION_FAILED={summary['pii_extraction_failed']}")
    print(f"PII_NOT_SCANNED={summary['pii_not_scanned']}")
    return pii_scan_exit_code(summary)


if __name__ == "__main__":
    raise SystemExit(main())
