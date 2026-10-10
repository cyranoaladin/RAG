"""Le scan distingue un hash de citation des octets de passage."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/go_live"))

from scan_student_derivative_pii import (  # noqa: E402
    classify_pattern_matches,
    reverify_pdf_blocks,
    source_hash_metadata_ranges,
)


def _raw(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode()


def _example(passage: bytes) -> tuple[bytes, dict, str]:
    source_sha = "0123456789" + "a" * 54
    attribution = {"source_uri": "https://eduscol.education.gouv.fr/source.pdf"}
    header = b"NEXUS-STUDENT-TEXT-DERIVATIVE-V2\n" + _raw({
        "source_pdf_sha256": source_sha, **attribution,
    }) + b"\n"
    citation = {"source_pdf_sha256": source_sha, "source_page": 1, **attribution}
    prefix = b"\n[PAGE 1 BLOCK 0]\n" + _raw(citation) + b"\n"
    content = header + prefix + passage + b"\n"
    start = len(header) + len(prefix)
    receipt = {"source_attribution": attribution, "source_content_sha256": source_sha,
               "pages": [{"page_number": 1, "byte_start": len(header),
                          "byte_end": len(content), "selected_block_indices": [0],
                          "all_blocks": [{"block_index": 0, "byte_start": start,
                                          "byte_end": start + len(passage),
                                          "citation": citation}]}]}
    return content, receipt, source_sha


def test_hash_digits_in_exact_serialized_citations_are_structural() -> None:
    text, receipt, source_sha = _example(b"La notion est enseignee.")
    ranges = source_hash_metadata_ranges(text, receipt, source_sha)
    result = classify_pattern_matches(
        text, [SimpleNamespace(pattern_id="phone_french",
                               regex=re.compile("0123456789"))], ranges,
    )
    assert result == {"pattern_hits": {"phone_french": 2},
                      "source_hash_metadata_hits": 2,
                      "unresolved_hits": 0}
    assert "0123456789" not in json.dumps(result)


def test_same_digits_in_native_passage_are_not_excused() -> None:
    text, receipt, source_sha = _example(b"Numero 0123456789")
    result = classify_pattern_matches(
        text, [SimpleNamespace(pattern_id="phone_french",
                               regex=re.compile("0123456789"))],
        source_hash_metadata_ranges(text, receipt, source_sha),
    )
    assert result["source_hash_metadata_hits"] == 2
    assert result["unresolved_hits"] == 1


def test_spoofed_hash_outside_citation_is_not_excused() -> None:
    text, receipt, source_sha = _example(b"Texte")
    text += b"0123456789"
    result = classify_pattern_matches(
        text, [SimpleNamespace(pattern_id="phone_french",
                               regex=re.compile("0123456789"))],
        source_hash_metadata_ranges(text, receipt, source_sha),
    )
    assert result["unresolved_hits"] == 1


def test_changed_citation_is_rejected() -> None:
    text, receipt, source_sha = _example(b"Texte")
    modified = text.replace(source_sha.encode(), b"f" * 64, 1)
    with pytest.raises(ValueError, match="SOURCE_HASH_CITATION_MISMATCH"):
        source_hash_metadata_ranges(modified, receipt, source_sha)


def test_exact_native_block_is_reverified_against_pdf(tmp_path: Path) -> None:
    import fitz  # noqa: PLC0415

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Texte scolaire")
    raw = pdf.tobytes()
    pdf.close()
    path = tmp_path / "source.pdf"
    path.write_bytes(raw)
    receipt = {"source_page_count": 1, "pages": [{
        "page_number": 1, "selected_block_indices": [0],
        "all_blocks": [{"block_index": 0, "byte_start": 0,
                        "byte_end": len(b"Texte scolaire"),
                        "normalized_text_sha256": hashlib.sha256(b"Texte scolaire").hexdigest()}],
    }]}
    assert reverify_pdf_blocks(path, b"Texte scolaire", receipt,
                               hashlib.sha256(raw).hexdigest()) == 1
    with pytest.raises(ValueError, match="SOURCE_NATIVE_BLOCK_MISMATCH"):
        reverify_pdf_blocks(path, b"Texte contraire", receipt,
                            hashlib.sha256(raw).hexdigest())


def test_real_pack_scan_is_sanitized() -> None:
    private = Path.home() / "nexus-student-public-release-eb39f6cd0423e184"
    if not private.is_dir():
        pytest.skip("CAS privé #312 absent")
    from scan_student_derivative_pii import scan_repository  # noqa: PLC0415
    result = scan_repository(ROOT, private, scanned_at_utc="2026-10-10T13:00:00Z")
    assert result["artifact_count"] == 253
    assert result["unresolved_artifact_count"] == 0
    assert result["source_hash_metadata_hits"] == 677
    assert result["pattern_hit_count"] == 677
    assert all(set(row) == {"content_sha256", "source_pdf_sha256",
                                "derivative_receipt_sha256", "text_byte_count",
                                "pattern_hits", "source_hash_metadata_hits",
                                "unresolved_hits", "status"}
               for row in result["rows"])
    raw = json.dumps(result, sort_keys=True).encode()
    assert hashlib.sha256(raw).hexdigest()
