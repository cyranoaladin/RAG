"""Bounded, read-only PII scan runner for the sealed production corpus."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from rag_pedago.imports.corpus_catalog_compiler import _parse_sealed_manifest
from rag_pedago.imports.pii_scanner import (
    PIIScanResult,
    load_patterns_from_config,
    result_to_dict,
    scan_pdf,
)

CANONICAL_REMOTE_ROOT = "gdrive_ert:NEXUS_RAG/NEXUS_RAG_GDRIVE_READY"
SCANNER_VERSION = "pii_scanner_h2b_v2"

DownloadFile = Callable[[str, Path], None]
ScanFile = Callable[[Path], PIIScanResult]


class RemoteDownloadError(RuntimeError):
    """Sanitized failure for a read-only corpus download."""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rclone_download(remote_source: str, local_target: Path) -> None:
    """Copy exactly one canonical remote object to a local scratch target."""
    if not remote_source.startswith(f"{CANONICAL_REMOTE_ROOT}/"):
        raise ValueError("source is outside the canonical read-only corpus remote")
    if not local_target.is_absolute() or ":" in str(local_target):
        raise ValueError("rclone destination must be an absolute local path")
    try:
        subprocess.run(
            [
                "rclone",
                "copyto",
                "--no-traverse",
                "--retries",
                "3",
                "--low-level-retries",
                "5",
                remote_source,
                str(local_target),
            ],
            capture_output=True,
            check=True,
            text=False,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RemoteDownloadError("read-only corpus download failed") from error


def rclone_bulk_download(remote_root: str, local_root: Path) -> None:
    """Copy all PDFs from the canonical remote into a bounded local mirror."""
    if remote_root != CANONICAL_REMOTE_ROOT:
        raise ValueError("remote root is not the canonical read-only corpus remote")
    mirror = _validated_scratch(local_root)
    try:
        subprocess.run(
            [
                "rclone",
                "copy",
                "--include",
                "*.pdf",
                "--transfers",
                "8",
                "--checkers",
                "16",
                "--retries",
                "3",
                "--low-level-retries",
                "5",
                remote_root,
                str(mirror),
            ],
            capture_output=True,
            check=True,
            text=False,
            timeout=7200,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RemoteDownloadError("bulk read-only corpus download failed") from error


def _validated_policy(policy_path: Path) -> tuple[str, str]:
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict):
        raise ValueError("PII policy must be a mapping")
    policy_id = policy.get("policy_id")
    if not isinstance(policy_id, str) or not policy_id:
        raise ValueError("PII policy_id must be a non-empty string")
    return policy_id, _file_sha256(policy_path)


def _validated_scratch(scratch_dir: Path) -> Path:
    resolved = scratch_dir.resolve()
    tmp_root = Path("/tmp").resolve()
    if resolved == tmp_root or tmp_root not in resolved.parents:
        raise ValueError("PII scratch directory must be a dedicated path under /tmp")
    if not resolved.is_dir():
        raise ValueError("PII scratch directory must already exist")
    return resolved


def _safe_scan_payload(result: PIIScanResult) -> dict[str, Any]:
    payload = result_to_dict(result)
    payload.pop("sha256", None)
    return payload


def _build_summary(
    physical_pdf_count: int,
    unique_pdf_count: int,
    results: list[dict[str, Any]],
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
    not_scanned = physical_pdf_count - scanned
    coverage = scanned / physical_pdf_count if physical_pdf_count else 1.0
    return {
        "pdf_total": physical_pdf_count,
        "pii_scan_scope": "ALL_CORPUS_PDFS",
        "pii_scan_required": physical_pdf_count,
        "pii_scan_exempt": 0,
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
    scratch_dir: Path,
    *,
    expected_manifest_sha256: str,
    download_file: DownloadFile = rclone_download,
    scan_file: ScanFile = scan_pdf,
    local_mirror: Path | None = None,
) -> dict[str, Any]:
    """Scan all physical PDFs while downloading identical bytes only once."""
    if remote_root != CANONICAL_REMOTE_ROOT:
        raise ValueError("remote root is not the canonical read-only corpus remote")
    scratch = _validated_scratch(scratch_dir)
    mirror = _validated_scratch(local_mirror) if local_mirror else None
    manifest_sha256 = _file_sha256(manifest_path)
    if manifest_sha256 != expected_manifest_sha256:
        raise ValueError("corpus manifest SHA256 mismatch")
    policy_version, policy_sha256 = _validated_policy(policy_path)
    scanner_sha256 = _file_sha256(Path(__file__).with_name("pii_scanner.py"))

    pdf_entries = [
        (content_sha256, object_path)
        for content_sha256, object_path in _parse_sealed_manifest(manifest_path)
        if object_path.lower().endswith(".pdf")
    ]
    grouped: dict[str, list[str]] = {}
    for content_sha256, object_path in pdf_entries:
        grouped.setdefault(content_sha256, []).append(object_path)

    results: list[dict[str, Any]] = []
    for content_sha256, physical_paths in grouped.items():
        local_files: list[Path] = []
        cleanup_targets: list[Path] = []
        status = ""
        safe_payload: dict[str, Any] = {}
        error_code: str | None = None
        try:
            for index, physical_path in enumerate(physical_paths):
                if mirror is not None:
                    local_target = mirror.joinpath(*Path(physical_path).parts)
                else:
                    local_target = scratch / f"{content_sha256}-{index}.pdf"
                    if local_target.exists():
                        raise ValueError("PII scratch target unexpectedly exists")
                    download_file(f"{remote_root}/{physical_path}", local_target)
                cleanup_targets.append(local_target)
                if not local_target.is_file():
                    status = "REVIEW_REQUIRED_DOWNLOAD_FAILED"
                    error_code = "DOWNLOAD_DID_NOT_CREATE_FILE"
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
            status = "REVIEW_REQUIRED_DOWNLOAD_FAILED"
            error_code = "DOWNLOAD_FAILED"
        finally:
            for target in cleanup_targets:
                target.unlink(missing_ok=True)

        result = {
            "content_sha256": content_sha256,
            "physical_object_count": len(physical_paths),
            "status": status,
            "error_code": error_code,
            **safe_payload,
        }
        result.pop("extraction_error_code", None)
        results.append(result)

    summary = _build_summary(len(pdf_entries), len(grouped), results)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--remote-root", default=CANONICAL_REMOTE_ROOT)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--scratch-parent", type=Path, default=Path("/tmp"))
    args = parser.parse_args()

    patterns = load_patterns_from_config(args.policy)

    def configured_scan(path: Path) -> PIIScanResult:
        return scan_pdf(path, patterns)

    with tempfile.TemporaryDirectory(
        prefix="nexus-h2b-pii-",
        dir=args.scratch_parent,
    ) as scratch:
        scratch_path = Path(scratch)
        try:
            rclone_bulk_download(args.remote_root, scratch_path)
            evidence = scan_remote_corpus(
                args.manifest,
                args.policy,
                args.remote_root,
                scratch_path,
                expected_manifest_sha256=args.expected_manifest_sha256,
                scan_file=configured_scan,
                local_mirror=scratch_path,
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
    return 1 if summary["sha256_mismatches"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
