"""Extract notions from official programme PDFs — bidirectional correspondence.

Produces a correspondence report:
- taxo→BO: which taxonomy notions appear in the programme text
- BO→taxo: which programme section headings are absent from taxonomy
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml

from schema.taxonomy import TaxonomySpec

# Window size for proximity matching (max words between notion terms)
PROXIMITY_WINDOW = 8
MIN_EXTRACTED_TEXT = 500


def extract_text_from_pdf(pdf_path: Path) -> tuple[str, str]:
    """Extract text from a PDF. Returns (text, status).

    status: 'ok' | 'failed'
    Never falls back to raw UTF-8 silently.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", "failed"

    try:
        reader = PdfReader(str(pdf_path))
        pages: list[str] = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        full_text = "\n".join(pages)

        # Corruption check
        if len(full_text) < MIN_EXTRACTED_TEXT:
            return full_text, "failed"
        non_printable = sum(1 for c in full_text if not c.isprintable() and c not in "\n\r\t")
        if non_printable / max(len(full_text), 1) > 0.1:
            return full_text, "failed"

        return full_text, "ok"
    except Exception:
        return "", "failed"


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _tokenize_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalize(text))


def _find_in_proximity(label_words: list[str], text_words: list[str], window: int) -> bool:
    """Check if all label words appear within a sliding window in text."""
    if not label_words:
        return False
    first = label_words[0]
    for i, word in enumerate(text_words):
        if word == first:
            # Check if all remaining label words appear within window
            window_slice = set(text_words[i : i + window])
            if all(w in window_slice for w in label_words):
                return True
    return False


def find_notion_in_text(
    notion_id: str, label: str | None, text_normalized_words: list[str]
) -> str:
    """Match a notion against text. Returns: found_exact | found_partial | not_found.

    Exact: all significant words (>3 chars) of the label or id appear within
    a proximity window. Single-word terms require length >= 6 to avoid noise.
    Partial: >= 2/3 of significant words found anywhere (dispersed).
    """
    # Include words >= 3 chars for proximity (not just > 3)
    label_words = [w for w in _tokenize_words(label) if len(w) >= 3] if label else []
    id_words = [w for w in _tokenize_words(notion_id.replace("_", " ")) if len(w) >= 3]

    # Exact: require >= 2 words in proximity (catches "loi normale" together)
    for words in [label_words, id_words]:
        if len(words) >= 2 and _find_in_proximity(words, text_normalized_words, PROXIMITY_WINDOW):
            return "found_exact"

    # Single word: must be very distinctive (>= 8 chars)
    for words in [label_words, id_words]:
        if len(words) == 1 and len(words[0]) >= 8 and words[0] in set(text_normalized_words):
            return "found_exact"

    # Partial: >= 2/3 of significant words (> 3 chars) found anywhere, minimum 2 found
    all_significant = set(
        [w for w in (label_words + id_words) if len(w) > 3]
    )
    if all_significant:
        text_set = set(text_normalized_words)
        found_count = sum(1 for w in all_significant if w in text_set)
        threshold = max(len(all_significant) * 2 // 3, 1)
        if found_count >= threshold and found_count >= 2:
            return "found_partial"

    return "not_found"


def _extract_bo_headings(text: str) -> list[str]:
    """Extract likely section headings from BO programme text.

    BO programmes have patterns like:
    - Lines in ALL CAPS or Title Case that are short
    - Lines starting with bullets followed by concept names
    - Patterns: "Contenus", "Capacités attendues", theme titles
    """
    headings: list[str] = []
    seen: set[str] = set()

    for line in text.split("\n"):
        line = line.strip()
        if not line or len(line) < 3 or len(line) > 120:
            continue

        # Skip common non-heading patterns
        if line.startswith(("•", "-", "–", "→", "Page", "©")):
            continue

        # Detect section-like lines (short, capitalized, no punctuation at end)
        words = line.split()
        if 1 <= len(words) <= 8:
            # Title-case or all-caps line
            if line[0].isupper() and not line.endswith((".", ",", ";", ":")):
                normalized = _normalize(line)
                if normalized not in seen and len(normalized) > 5:
                    seen.add(normalized)
                    headings.append(line)

    return headings


def build_correspondence_report(
    taxonomy_path: Path,
    pdf_path: Path,
) -> dict[str, Any]:
    """Bidirectional correspondence: taxo→BO and BO→taxo."""
    data = yaml.safe_load(taxonomy_path.read_text(encoding="utf-8"))
    spec = TaxonomySpec.model_validate(data)

    pdf_text, extraction_status = extract_text_from_pdf(pdf_path)

    if extraction_status == "failed":
        return {
            "taxonomy": taxonomy_path.name,
            "programme": pdf_path.name,
            "matiere": spec.matiere,
            "niveau": spec.niveau.value,
            "extraction_status": "failed",
            "pdf_text_length": len(pdf_text),
            "message": "PDF extraction failed or text too short/corrupted",
        }

    text_words = _tokenize_words(pdf_text)

    # --- Taxo → BO ---
    found_exact: list[dict[str, str]] = []
    found_partial: list[dict[str, str]] = []
    not_found: list[dict[str, str]] = []

    for theme in spec.themes:
        for notion in theme.notions:
            status = find_notion_in_text(notion.id, notion.label, text_words)
            entry = {"theme": theme.id, "notion_id": notion.id,
                     "label": notion.label or notion.id}
            if status == "found_exact":
                found_exact.append(entry)
            elif status == "found_partial":
                found_partial.append(entry)
            else:
                not_found.append(entry)

            for sub in notion.subnotions:
                sub_status = find_notion_in_text(sub, None, text_words)
                sub_entry = {"theme": theme.id, "notion_id": f"{notion.id}/{sub}",
                             "label": sub}
                if sub_status == "found_exact":
                    found_exact.append(sub_entry)
                elif sub_status == "found_partial":
                    found_partial.append(sub_entry)
                else:
                    not_found.append(sub_entry)

    # --- BO → Taxo ---
    bo_headings = _extract_bo_headings(pdf_text)
    known_ids = spec.known_notion_ids
    known_labels = {_normalize(n.label or n.id) for t in spec.themes for n in t.notions}

    bo_only: list[str] = []
    for heading in bo_headings:
        h_norm = _normalize(heading)
        h_words = set(_tokenize_words(heading))
        # Check if any taxonomy notion covers this heading
        if not any(_normalize(kid) in h_norm or h_norm in _normalize(kid) for kid in known_ids):
            if not any(kl in h_norm or h_norm in kl for kl in known_labels):
                if any(len(w) > 3 for w in h_words):
                    bo_only.append(heading)

    total = len(found_exact) + len(found_partial) + len(not_found)

    return {
        "taxonomy": taxonomy_path.name,
        "programme": pdf_path.name,
        "matiere": spec.matiere,
        "niveau": spec.niveau.value,
        "extraction_status": "ok",
        "pdf_text_length": len(pdf_text),
        "total_notions_checked": total,
        "found_exact": len(found_exact),
        "found_partial": len(found_partial),
        "not_found": len(not_found),
        "exact_pct": round(len(found_exact) / max(total, 1) * 100, 1),
        "bo_only_count": len(bo_only),
        "details_found_exact": found_exact,
        "details_found_partial": found_partial,
        "details_not_found": not_found,
        "bo_only": bo_only[:30],
    }
