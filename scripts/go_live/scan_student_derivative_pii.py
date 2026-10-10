"""Scan PII déterministe des textes privés #312, sans journaliser de valeurs.

Un résultat clair signifie seulement « aucun motif de la politique dans les
passages natifs et les métadonnées hors SHA de citation ». Il ne remplace ni une
revue PII du dérivé ni une preuve de révocation fraîche.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from student_derivative_pii_currentness_gate import (
    EVIDENCE_RELATIVE,
    assess_repository,
)

ROOT = Path(__file__).resolve().parents[2]
POLICY_RELATIVE = Path("services/rag-pedago/configs/pii_gate_policy.yml")
SCANNER_RELATIVE = Path("services/rag-pedago/rag_pedago/imports/pii_scanner.py")
SHA64 = re.compile(r"[0-9a-f]{64}\Z")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def _compact(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode()


def _sha_value_range(serialized: bytes, source_sha: str, offset: int) -> tuple[int, int]:
    token = b'"source_pdf_sha256":"' + source_sha.encode("ascii") + b'"'
    if serialized.count(token) != 1:
        raise ValueError("SOURCE_HASH_CITATION_MISMATCH")
    start = offset + serialized.index(token) + len(b'"source_pdf_sha256":"')
    return start, start + 64


def source_hash_metadata_ranges(
    content: bytes, receipt: Mapping[str, Any], source_sha: str,
) -> list[tuple[int, int]]:
    """Seuls les SHA dans l'en-tête et les citations canoniques sont exemptés."""
    if not isinstance(source_sha, str) or SHA64.fullmatch(source_sha) is None:
        raise ValueError("SOURCE_HASH_CITATION_MISMATCH")
    attribution = receipt.get("source_attribution")
    pages = receipt.get("pages")
    if not isinstance(attribution, dict) or not isinstance(pages, list) or not pages:
        raise ValueError("SOURCE_HASH_CITATION_MISMATCH")
    header_json = _compact({"source_pdf_sha256": source_sha, **attribution})
    header = b"NEXUS-STUDENT-TEXT-DERIVATIVE-V2\n" + header_json + b"\n"
    if not content.startswith(header) or pages[0].get("byte_start") != len(header):
        raise ValueError("SOURCE_HASH_CITATION_MISMATCH")
    ranges = [_sha_value_range(header_json, source_sha,
                               len(b"NEXUS-STUDENT-TEXT-DERIVATIVE-V2\n"))]
    for page in pages:
        selected = page.get("selected_block_indices")
        blocks = page.get("all_blocks")
        if not isinstance(selected, list) or not isinstance(blocks, list):
            raise ValueError("SOURCE_HASH_CITATION_MISMATCH")
        by_index = {block.get("block_index"): block for block in blocks}
        for index in selected:
            block = by_index.get(index)
            if not isinstance(block, dict) or not isinstance(block.get("citation"), dict):
                raise ValueError("SOURCE_HASH_CITATION_MISMATCH")
            citation = block["citation"]
            if (citation.get("source_pdf_sha256") != source_sha
                    or citation.get("source_page") != page.get("page_number")):
                raise ValueError("SOURCE_HASH_CITATION_MISMATCH")
            citation_json = _compact(citation)
            end = block.get("byte_start")
            if type(end) is not int or end < len(citation_json) + 1:
                raise ValueError("SOURCE_HASH_CITATION_MISMATCH")
            start = end - len(citation_json) - 1
            if content[start:end] != citation_json + b"\n":
                raise ValueError("SOURCE_HASH_CITATION_MISMATCH")
            ranges.append(_sha_value_range(citation_json, source_sha, start))
    return ranges


def classify_pattern_matches(
    content: bytes, patterns: list[Any], source_sha_ranges: list[tuple[int, int]],
) -> dict[str, Any]:
    """Aucune allowlist générale ; seules les plages de SHA exactes sont connues."""
    text = content.decode("utf-8")
    counts: Counter[str] = Counter()
    structural, unresolved = 0, 0
    for pattern in patterns:
        for match in pattern.regex.finditer(text):
            counts[pattern.pattern_id] += 1
            start = len(text[:match.start()].encode("utf-8"))
            end = len(text[:match.end()].encode("utf-8"))
            if any(left <= start and end <= right for left, right in source_sha_ranges):
                structural += 1
            else:
                unresolved += 1
    return {
        "pattern_hits": dict(sorted(counts.items())),
        "source_hash_metadata_hits": structural,
        "unresolved_hits": unresolved,
    }


def _patterns(root: Path) -> list[Any]:
    # Réutilise la politique et le compilateur du service du même checkout.
    sys.path.insert(0, str(root / "services/rag-pedago"))
    sys.path.insert(0, str(root / "packages/pdf-page-policy/src"))
    from rag_pedago.imports.pii_scanner import load_patterns_from_config  # noqa: PLC0415

    return load_patterns_from_config(root / POLICY_RELATIVE)


def reverify_pdf_blocks(
    pdf_path: Path, content: bytes, receipt: Mapping[str, Any], expected_pdf_sha: str,
) -> int:
    """Recompare tous les blocs retenus au PDF source de SHA exact."""
    import fitz  # noqa: PLC0415

    if _sha(pdf_path.read_bytes()) != expected_pdf_sha:
        raise ValueError("SOURCE_PDF_SHA_MISMATCH")
    pdf = fitz.open(pdf_path)
    count = 0
    try:
        pages = receipt.get("pages")
        if not isinstance(pages, list) or len(pdf) != receipt.get("source_page_count"):
            raise ValueError("SOURCE_PDF_PAGE_COUNT_MISMATCH")
        for page_receipt in pages:
            number = page_receipt.get("page_number")
            if type(number) is not int or not 1 <= number <= len(pdf):
                raise ValueError("SOURCE_PDF_PAGE_COUNT_MISMATCH")
            source_blocks = pdf.load_page(number - 1).get_text("blocks", sort=True)
            by_index = {block["block_index"]: block
                        for block in page_receipt["all_blocks"]}
            for index in page_receipt["selected_block_indices"]:
                block = by_index.get(index)
                if (type(index) is not int or index < 0 or index >= len(source_blocks)
                        or not isinstance(block, dict) or source_blocks[index][6] != 0):
                    raise ValueError("SOURCE_NATIVE_BLOCK_MISMATCH")
                source_text = unicodedata.normalize("NFC", str(source_blocks[index][4]))
                source_text = source_text.replace("\r\n", "\n").replace("\r", "\n").strip()
                start, end = block.get("byte_start"), block.get("byte_end")
                if (type(start) is not int or type(end) is not int
                        or start < 0 or end < start or end > len(content)
                        or content[start:end] != source_text.encode("utf-8")
                        or block.get("normalized_text_sha256") != _sha(source_text.encode("utf-8"))):
                    raise ValueError("SOURCE_NATIVE_BLOCK_MISMATCH")
                count += 1
    finally:
        pdf.close()
    return count


def scan_repository(
    root: Path, private_root: Path, *, scanned_at_utc: str,
    source_pdf_root: Path | None = None,
) -> dict[str, Any]:
    """Produit des statistiques sans aucune valeur ni contexte de match."""
    structural = assess_repository(root, private_root)
    if structural["structural_pass_count"] != 253:
        raise ValueError("DERIVATIVE_STRUCTURAL_GATE_RED")
    evidence = root / EVIDENCE_RELATIVE
    manifest_raw = (evidence / "public_derivative_candidate_manifest_20261010.json").read_bytes()
    manifest = json.loads(manifest_raw)
    patterns = _patterns(root)
    packet_by_sha: dict[str, dict] = {}
    if source_pdf_root is not None:
        packet = json.loads((root / "docs/reports/go_live/"
                             "student_public_rights_individual_review_packet_20261009.json").read_bytes())
        packet_by_sha = {row["content_sha256"]: row for row in packet["artifacts"]}
    rows = []
    verified_pdfs = 0
    verified_blocks = 0
    for entry in sorted(manifest["entries"], key=lambda row: row["derivative_content_sha256"]):
        derivative_sha = entry["derivative_content_sha256"]
        source_sha = entry["source_content_sha256"]
        receipt_sha = entry["derivative_receipt_sha256"]
        content = (private_root / f"{derivative_sha}.txt").read_bytes()
        if _sha(content) != derivative_sha:
            raise ValueError("DERIVATIVE_TEXT_SHA_MISMATCH")
        receipt_raw = (evidence / "derivative_receipts" / receipt_sha[:2]
                       / f"{receipt_sha}.json").read_bytes()
        if _sha(receipt_raw) != receipt_sha:
            raise ValueError("DERIVATIVE_RECEIPT_SHA_MISMATCH")
        receipt = json.loads(receipt_raw)
        ranges = source_hash_metadata_ranges(content, receipt, source_sha)
        findings = classify_pattern_matches(content, patterns, ranges)
        if source_pdf_root is not None:
            source_row = packet_by_sha.get(source_sha)
            if not isinstance(source_row, dict):
                raise ValueError("SOURCE_PDF_PACKET_MISSING")
            pdf_path = (source_pdf_root / source_row["source_path"]).resolve()
            if not pdf_path.is_relative_to(source_pdf_root.resolve()):
                raise ValueError("SOURCE_PDF_PATH_INVALID")
            source_evidence = json.loads((evidence / f"{source_sha}.json").read_bytes())
            pdf_scan = source_evidence.get("pdf_scan_evidence", {})
            if (pdf_scan.get("content_sha256") != source_sha
                    or pdf_scan.get("exact_bytes_match") is not True
                    or pdf_scan.get("full_document_scan_complete") is not True
                    or pdf_scan.get("annexes_scan_complete") is not True):
                raise ValueError("PR300_FULL_SOURCE_SCAN_UNPROVEN")
            verified_blocks += reverify_pdf_blocks(pdf_path, content, receipt, source_sha)
            verified_pdfs += 1
        rows.append({
            "content_sha256": derivative_sha,
            "source_pdf_sha256": source_sha,
            "derivative_receipt_sha256": receipt_sha,
            "text_byte_count": len(content),
            **findings,
            "status": ("PATTERN_SCREEN_CLEAR_ONLY" if findings["unresolved_hits"] == 0
                       else "BLOCKED_UNRESOLVED_PII_SIGNAL"),
        })
    unresolved_artifacts = sum(row["unresolved_hits"] > 0 for row in rows)
    return {
        "kind": "NEXUS_STUDENT_DERIVATIVE_PII_PATTERN_SCREEN_V1",
        "scanned_at_utc": scanned_at_utc,
        "candidate_manifest_sha256": _sha(manifest_raw),
        "pr300_evidence_index_sha256": structural["pr300_evidence_index_sha256"],
        "artifact_registry_sha256": structural["artifact_registry_sha256"],
        "policy_sha256": _sha((root / POLICY_RELATIVE).read_bytes()),
        "scanner_code_sha256": _sha((root / SCANNER_RELATIVE).read_bytes()),
        "producer_code_sha256": _sha(Path(__file__).read_bytes()),
        "artifact_count": len(rows),
        "text_byte_count": sum(row["text_byte_count"] for row in rows),
        "pattern_hit_count": sum(sum(row["pattern_hits"].values()) for row in rows),
        "source_hash_metadata_hits": sum(row["source_hash_metadata_hits"] for row in rows),
        "unresolved_artifact_count": unresolved_artifacts,
        "unresolved_signal_count": sum(row["unresolved_hits"] for row in rows),
        "source_pdf_reverified_count": verified_pdfs,
        "native_block_reverified_count": verified_blocks,
        "scope": "PATTERN_SCREEN_ONLY_NOT_FULL_PII_ADJUDICATION",
        "rows": rows,
    }


def _write_atomic(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".derivative-pii-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--source-pdf-root", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    report = scan_repository(args.repository_root, args.private_root, scanned_at_utc=now,
                             source_pdf_root=args.source_pdf_root)
    raw = _canonical(report)
    _write_atomic(args.output, raw)
    _write_atomic(args.output.with_suffix(args.output.suffix + ".sha256"),
                  f"{_sha(raw)}  {args.output.name}\n".encode("ascii"))
    print(json.dumps({
        "artifact_count": report["artifact_count"],
        "pattern_hit_count": report["pattern_hit_count"],
        "source_hash_metadata_hits": report["source_hash_metadata_hits"],
        "unresolved_artifact_count": report["unresolved_artifact_count"],
        "source_pdf_reverified_count": report["source_pdf_reverified_count"],
        "native_block_reverified_count": report["native_block_reverified_count"],
        "report_sha256": _sha(raw),
        "scope": report["scope"],
    }, sort_keys=True))
    return 0 if report["unresolved_artifact_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
