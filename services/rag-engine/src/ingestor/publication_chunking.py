"""Chunking de publication borné, page-aware pour les PDF."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

try:
    from .ingestion_agents.extractor import PDF_MIME_TYPE, extract_pdf_pages
    from .pedagogical_chunker import _flatten_section, parse_sections
except ImportError:  # image Docker aplatie
    from ingestion_agents.extractor import (  # type: ignore[no-redef]
        PDF_MIME_TYPE,
        extract_pdf_pages,
    )
    from pedagogical_chunker import (  # type: ignore[no-redef]
        _flatten_section,
        parse_sections,
    )

DEFAULT_TARGET_TOKENS = 384
_SPACE = re.compile(r"\s+")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?;…])\s+")


class PassageTokenCounter(Protocol):
    max_sequence_length: int

    def passage_token_count(self, text: str) -> int: ...


@dataclass(frozen=True)
class PublicationChunk:
    text: str
    page_start: int | None
    page_end: int | None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("publication chunk text must be nonblank")
        if (self.page_start is None) != (self.page_end is None):
            raise ValueError("page_start and page_end must be both set or both null")
        if self.page_start is not None and (
            self.page_start < 1 or self.page_end is None or self.page_end < self.page_start
        ):
            raise ValueError("publication chunk page range is invalid")


def _normalize(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


def _largest_fitting_prefix(
    text: str,
    *,
    token_counter: PassageTokenCounter,
    budget: int,
) -> int:
    low, high = 1, len(text)
    best = 0
    while low <= high:
        middle = (low + high) // 2
        if token_counter.passage_token_count(text[:middle]) <= budget:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    if best == 0:
        raise ValueError("token budget cannot hold a single source character")
    if best < len(text):
        whitespace = text.rfind(" ", 0, best + 1)
        if whitespace > 0:
            best = whitespace
    return best


def _hard_split(
    text: str,
    *,
    token_counter: PassageTokenCounter,
    budget: int,
) -> list[str]:
    remaining = _normalize(text)
    chunks: list[str] = []
    while remaining:
        if token_counter.passage_token_count(remaining) <= budget:
            chunks.append(remaining)
            break
        split_at = _largest_fitting_prefix(
            remaining,
            token_counter=token_counter,
            budget=budget,
        )
        head = remaining[:split_at].strip()
        if not head:
            raise ValueError("hard split produced an empty publication chunk")
        chunks.append(head)
        remaining = remaining[split_at:].strip()
    return chunks


def _bounded_text(
    text: str,
    *,
    token_counter: PassageTokenCounter,
    budget: int,
) -> list[str]:
    source = text.strip()
    if not source:
        return []
    if token_counter.passage_token_count(source) <= budget:
        return [source]

    normalized = _normalize(source)
    units = [unit.strip() for unit in _SENTENCE_BOUNDARY.split(normalized) if unit.strip()]
    if not units:
        units = [normalized]

    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current} {unit}".strip() if current else unit
        if token_counter.passage_token_count(candidate) <= budget:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if token_counter.passage_token_count(unit) <= budget:
            current = unit
        else:
            chunks.extend(
                _hard_split(unit, token_counter=token_counter, budget=budget)
            )
    if current:
        chunks.append(current)
    if not chunks or any(not chunk.strip() for chunk in chunks):
        raise ValueError("bounded splitter produced an empty chunk set")
    return chunks


def chunk_publication(
    *,
    content: bytes,
    mime_detected: str,
    extracted_text: str,
    token_counter: PassageTokenCounter,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> tuple[PublicationChunk, ...]:
    """Produire les chunks réels sans reconstruire les pages depuis du texte aplati."""
    if target_tokens <= 0 or target_tokens > token_counter.max_sequence_length:
        raise ValueError("target token budget exceeds the provider sequence limit")

    chunks: list[PublicationChunk] = []
    if mime_detected == PDF_MIME_TYPE:
        for page_number, page in enumerate(extract_pdf_pages(content), start=1):
            if not page:
                # Page réellement vide, conservée par l'extracteur pour que la
                # numérotation reste celle du document. Aucun chunk à en tirer.
                continue
            for text in _bounded_text(
                page,
                token_counter=token_counter,
                budget=target_tokens,
            ):
                chunks.append(PublicationChunk(text, page_number, page_number))
    else:
        sections = parse_sections(extracted_text)
        raw_chunks = [raw for section in sections for raw in _flatten_section(section)]
        if raw_chunks:
            for raw in raw_chunks:
                if (
                    token_counter.passage_token_count(raw.text)
                    <= token_counter.max_sequence_length
                ):
                    chunks.append(PublicationChunk(raw.text, None, None))
                    continue
                for text in _bounded_text(
                    raw.text,
                    token_counter=token_counter,
                    budget=target_tokens,
                ):
                    chunks.append(PublicationChunk(text, None, None))
        else:
            for text in _bounded_text(
                extracted_text,
                token_counter=token_counter,
                budget=target_tokens,
            ):
                chunks.append(PublicationChunk(text, None, None))

    if not chunks:
        raise ValueError("publication chunking produced no content")
    if any(
        token_counter.passage_token_count(chunk.text)
        > token_counter.max_sequence_length
        for chunk in chunks
    ):
        raise ValueError("publication chunk exceeds the provider sequence limit")
    return tuple(chunks)


__all__ = [
    "DEFAULT_TARGET_TOKENS",
    "PDF_MIME_TYPE",
    "PassageTokenCounter",
    "PublicationChunk",
    "chunk_publication",
]
