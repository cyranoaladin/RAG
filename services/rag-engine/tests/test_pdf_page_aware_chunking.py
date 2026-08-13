from __future__ import annotations

import re
from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from ingestor.publication_chunking import PublicationChunk, chunk_publication


class WordTokenCounter:
    max_sequence_length = 32

    def passage_token_count(self, text: str) -> int:
        # Simule le préfixe E5 + deux special tokens, avec une borne assez
        # petite pour exercer le hard split sans dépendre d'un modèle réseau.
        return len(text.split()) + 3


def _pdf_with_pages(*texts: str) -> bytes:
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = DecodedStreamObject()
        stream.set_data(
            f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def test_real_pdf_path_is_page_aware_and_preserves_all_text() -> None:
    pages = (
        "Premiere page courte avec une notion.",
        " ".join(f"mot{i}" for i in range(70)),
    )

    chunks = chunk_publication(
        content=_pdf_with_pages(*pages),
        mime_detected="application/pdf",
        extracted_text="must not be used to reconstruct PDF page boundaries",
        token_counter=WordTokenCounter(),
        target_tokens=24,
    )

    assert len(chunks) > 2
    assert all(isinstance(chunk, PublicationChunk) for chunk in chunks)
    assert {chunk.page_start for chunk in chunks} == {1, 2}
    assert all(chunk.page_start == chunk.page_end for chunk in chunks)
    assert all(chunk.text.strip() for chunk in chunks)
    assert all(WordTokenCounter().passage_token_count(chunk.text) <= 24 for chunk in chunks)
    for page_number, expected in enumerate(pages, start=1):
        observed = " ".join(
            chunk.text for chunk in chunks if chunk.page_start == page_number
        )
        assert _normalized(observed) == _normalized(expected)


def test_long_sentence_without_punctuation_is_hard_split_under_budget() -> None:
    page = " ".join(f"unite{i}" for i in range(95))

    chunks = chunk_publication(
        content=_pdf_with_pages(page),
        mime_detected="application/pdf",
        extracted_text=page,
        token_counter=WordTokenCounter(),
        target_tokens=20,
    )

    assert len(chunks) > 1
    assert all(chunk.page_start == chunk.page_end == 1 for chunk in chunks)
    assert all(0 < WordTokenCounter().passage_token_count(chunk.text) <= 20 for chunk in chunks)
    assert _normalized(" ".join(chunk.text for chunk in chunks)) == _normalized(page)


def test_structured_markdown_keeps_heading_aware_chunks() -> None:
    markdown = "# Chapitre\n\nTexte du chapitre.\n\n## Sous-partie\n\nAutre texte."

    chunks = chunk_publication(
        content=markdown.encode(),
        mime_detected="text/markdown",
        extracted_text=markdown,
        token_counter=WordTokenCounter(),
        target_tokens=24,
    )

    assert len(chunks) == 2
    assert chunks[0].text.startswith("[Chapitre]")
    assert chunks[1].text.startswith("[Chapitre › Sous-partie]")
    assert all(chunk.page_start is None and chunk.page_end is None for chunk in chunks)


def test_structured_markdown_preserves_a_historical_chunk_below_model_limit() -> None:
    class LargeModelTokenCounter(WordTokenCounter):
        max_sequence_length = 512

    body = " ".join(f"notion{i}" for i in range(383))
    markdown = f"# Chapitre\n\n{body}"
    counter = LargeModelTokenCounter()

    chunks = chunk_publication(
        content=markdown.encode(),
        mime_detected="text/markdown",
        extracted_text=markdown,
        token_counter=counter,
        target_tokens=384,
    )

    assert len(chunks) == 1
    assert chunks[0].text.startswith("[Chapitre]")
    assert counter.passage_token_count(chunks[0].text) <= 512


def test_plain_text_is_bounded_without_page_metadata() -> None:
    text = " ".join(f"texte{i}" for i in range(80))

    chunks = chunk_publication(
        content=text.encode(),
        mime_detected="text/plain",
        extracted_text=text,
        token_counter=WordTokenCounter(),
        target_tokens=18,
    )

    assert len(chunks) > 1
    assert all(chunk.page_start is None and chunk.page_end is None for chunk in chunks)
    assert all(WordTokenCounter().passage_token_count(chunk.text) <= 18 for chunk in chunks)
    assert _normalized(" ".join(chunk.text for chunk in chunks)) == _normalized(text)
