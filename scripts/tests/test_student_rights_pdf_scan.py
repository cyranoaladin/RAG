"""La preuve de scan couvre les octets et chaque page, sans divulguer leur contenu."""

from __future__ import annotations

import hashlib
import json
import sys
import traceback
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))

from student_rights_pdf_scan import PdfScanError, scan_pdf  # noqa: E402


def _pdf(path: Path, *, graphic: bool = False, attachment: bool = False) -> tuple[str, int]:
    doc = fitz.open()
    first = doc.new_page(width=250, height=250)
    first.insert_text((24, 50), "UNIQUE_PRIVATE_CANARY", fontsize=12)
    if graphic:
        second = doc.new_page(width=250, height=250)
        second.draw_rect(fitz.Rect(30, 30, 100, 100), color=(1, 0, 0), fill=(1, 0, 0))
    if attachment:
        doc.embfile_add("annex.txt", b"UNIQUE_ATTACHMENT_CANARY")
    doc.save(path)
    doc.close()
    return hashlib.sha256(path.read_bytes()).hexdigest(), 2 if graphic else 1


def test_scans_every_page_and_returns_only_hashes_for_content(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    sha, pages = _pdf(path, graphic=True)

    result = scan_pdf(path, sha, pages)

    assert result["content_sha256"] == sha
    assert result["exact_bytes_match"] is True
    assert result["file_size_bytes"] == path.stat().st_size
    assert result["page_count"] == 2
    assert result["full_document_scan_complete"] is True
    assert result["annexes_scan_complete"] is True
    assert result["images_and_annexes_checked"] is True
    assert result["embedded_file_count"] == 0
    assert len(result["pages"]) == 2
    assert [page["page_number"] for page in result["pages"]] == [1, 2]
    assert all(len(page["text_sha256"]) == 64 for page in result["pages"])
    assert result["pages"][1]["vector_drawing_count"] > 0
    assert len(result["pages"][1]["render_sha256"]) == 64
    assert len(result["metadata_sha256"]) == 64
    assert "UNIQUE_PRIVATE_CANARY" not in json.dumps(result)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sha


@pytest.mark.parametrize(
    ("expected_sha", "expected_pages", "reason"),
    [("0" * 64, 1, "PDF_SHA256_MISMATCH"), (None, 2, "PDF_PAGE_COUNT_MISMATCH")],
)
def test_mismatched_identity_fails_closed_without_path_or_content(
    tmp_path: Path, expected_sha: str | None, expected_pages: int, reason: str
) -> None:
    path = tmp_path / "UNIQUE_PRIVATE_CANARY.pdf"
    sha, _ = _pdf(path)

    with pytest.raises(PdfScanError) as caught:
        scan_pdf(path, expected_sha or sha, expected_pages)

    assert caught.value.reason_code == reason
    assert "UNIQUE_PRIVATE_CANARY" not in str(caught.value)


def test_embedded_attachment_is_refused_instead_of_claiming_complete_scan(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.pdf"
    sha, pages = _pdf(path, attachment=True)

    with pytest.raises(PdfScanError) as caught:
        scan_pdf(path, sha, pages)

    assert caught.value.reason_code == "PDF_EMBEDDED_FILES_UNSUPPORTED"


def test_graphic_page_ocr_is_hashed_and_not_emitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "synthetic.pdf"
    sha, pages = _pdf(path, graphic=True)
    import student_rights_pdf_scan as scanner

    monkeypatch.setattr(scanner, "_ocr_text", lambda _png: "UNIQUE_OCR_PRIVATE_CANARY")
    result = scan_pdf(path, sha, pages)

    graphic = result["pages"][1]
    assert graphic["ocr_required"] is True
    assert graphic["ocr_complete"] is True
    assert graphic["ocr_sha256"] == hashlib.sha256(b"UNIQUE_OCR_PRIVATE_CANARY").hexdigest()
    assert "UNIQUE_OCR_PRIVATE_CANARY" not in json.dumps(result)


def test_ocr_also_covers_graphic_page_with_extractable_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "synthetic.pdf"
    sha, pages = _pdf(path)
    doc = fitz.open(path)
    doc[0].draw_rect(fitz.Rect(30, 80, 100, 150), color=(1, 0, 0))
    doc[0].insert_text(
        (24, 65),
        "This is a long synthetic text line with more than fifty extractable characters.",
        fontsize=6,
    )
    doc.saveIncr()
    doc.close()
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    import student_rights_pdf_scan as scanner

    monkeypatch.setattr(scanner, "_ocr_text", lambda _png: "IMAGE_TEXT_CANARY")
    result = scan_pdf(path, sha, pages)

    assert result["pages"][0]["text_character_count"] > 0
    assert result["pages"][0]["ocr_required"] is True
    assert result["pages"][0]["ocr_sha256"] == hashlib.sha256(b"IMAGE_TEXT_CANARY").hexdigest()


def test_annotation_content_is_accounted_for_without_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "synthetic.pdf"
    sha, pages = _pdf(path)
    doc = fitz.open(path)
    doc[0].add_text_annot((50, 50), "ANNOTATION_PRIVATE_CANARY")
    doc.saveIncr()
    doc.close()
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    import student_rights_pdf_scan as scanner

    monkeypatch.setattr(scanner, "_ocr_text", lambda _png: "")
    result = scan_pdf(path, sha, pages)

    assert result["pages"][0]["annotation_count"] == 1
    assert len(result["pages"][0]["annotations_sha256"]) == 64
    assert result["pages"][0]["render_sha256"] is not None
    assert "ANNOTATION_PRIVATE_CANARY" not in json.dumps(result)


def test_unreadable_source_error_does_not_leak_path_in_traceback(tmp_path: Path) -> None:
    path = tmp_path / "PRIVATE_PERSON_NAME.pdf"

    try:
        scan_pdf(path, "0" * 64, 1)
    except PdfScanError as exc:
        trace = "".join(traceback.format_exception(exc))
        assert exc.reason_code == "PDF_UNREADABLE"
        assert "PRIVATE_PERSON_NAME" not in trace
    else:
        pytest.fail("Source absente acceptée")


def test_annex_marker_is_detected_from_text_or_ocr_without_claiming_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "synthetic.pdf"
    _pdf(path, graphic=True)
    doc = fitz.open(path)
    doc[0].insert_text((24, 75), "ANNEXE 1", fontsize=12)
    doc.saveIncr()
    doc.close()
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    import student_rights_pdf_scan as scanner

    monkeypatch.setattr(scanner, "_ocr_text", lambda _png: "Annexes du document")
    result = scan_pdf(path, sha, 2)

    assert result["pages"][0]["annex_page"] is True
    assert result["pages"][1]["annex_page"] is True
