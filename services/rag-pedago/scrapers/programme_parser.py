"""Extract notions from official programme PDFs.

Produces a correspondence report: taxonomy notions vs PDF content.
Uses pypdf (available in rag-pedago deps) for text extraction.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from schema.taxonomy import TaxonomySpec


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from a PDF file."""
    try:
        from pypdf import PdfReader
    except ImportError:
        # Fallback: try to read as text (for non-PDF content like HTML error pages)
        content = pdf_path.read_bytes()
        return content.decode("utf-8", errors="replace")

    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n".join(pages)


def _normalize(text: str) -> str:
    """Normalize text for matching."""
    import unicodedata
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text


def _find_notion_in_text(notion_id: str, label: str | None, text_normalized: str) -> bool:
    """Check if a notion appears in the normalized text."""
    # Try label first (more descriptive)
    if label:
        label_norm = _normalize(label)
        # Look for significant words (>3 chars) from the label
        words = [w for w in re.findall(r"[a-z]+", label_norm) if len(w) > 3]
        if words and all(w in text_normalized for w in words):
            return True

    # Try notion_id
    id_norm = _normalize(notion_id.replace("_", " "))
    words = [w for w in re.findall(r"[a-z]+", id_norm) if len(w) > 3]
    if words and all(w in text_normalized for w in words):
        return True

    return False


def build_correspondence_report(
    taxonomy_path: Path,
    pdf_path: Path,
) -> dict[str, Any]:
    """Compare taxonomy notions against PDF programme content."""
    # Load taxonomy
    data = yaml.safe_load(taxonomy_path.read_text(encoding="utf-8"))
    spec = TaxonomySpec.model_validate(data)

    # Extract and normalize PDF text
    pdf_text = extract_text_from_pdf(pdf_path)
    text_norm = _normalize(pdf_text)

    # Check each notion
    found: list[dict[str, Any]] = []
    not_found: list[dict[str, Any]] = []

    for theme in spec.themes:
        for notion in theme.notions:
            entry = {
                "theme": theme.id,
                "notion_id": notion.id,
                "notion_label": notion.label or notion.id,
            }
            if _find_notion_in_text(notion.id, notion.label, text_norm):
                entry["status"] = "found_in_bo"
                found.append(entry)
            else:
                entry["status"] = "not_found_in_bo"
                not_found.append(entry)

            # Check subnotions
            for sub in notion.subnotions:
                sub_entry = {
                    "theme": theme.id,
                    "notion_id": f"{notion.id}/{sub}",
                    "notion_label": sub,
                }
                if _find_notion_in_text(sub, None, text_norm):
                    sub_entry["status"] = "found_in_bo"
                    found.append(sub_entry)
                else:
                    sub_entry["status"] = "not_found_in_bo"
                    not_found.append(sub_entry)

    return {
        "taxonomy": str(taxonomy_path.name),
        "programme": str(pdf_path.name),
        "matiere": spec.matiere,
        "niveau": spec.niveau.value,
        "pdf_text_length": len(pdf_text),
        "total_notions_checked": len(found) + len(not_found),
        "found_in_bo": len(found),
        "not_found_in_bo": len(not_found),
        "coverage_pct": round(len(found) / max(len(found) + len(not_found), 1) * 100, 1),
        "found": found,
        "not_found": not_found,
    }
