"""The release chunker indexes only verified native-text blocks."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from nexus_release_chain import publication_chunking


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class _Counter:
    max_sequence_length = 40

    def passage_token_count(self, text: str) -> int:
        return len(text.split())


def _candidate() -> tuple[bytes, dict]:
    source_sha = "a" * 64
    attribution = {
        "source_uri": "https://eduscol.education.gouv.fr/document.pdf",
        "source_label": "Document de test",
        "source_updated_at": "2026-10-10T00:00:00Z",
        "source_date_kind": "DATED_OFFICIAL_SNAPSHOT",
        "licensor": "Dgesco",
        "licence_id": "ETALAB-2.0",
        "derivative_notice": "Extrait textuel du snapshot 2026-10-10T00:00:00Z",
    }
    content = bytearray(b"NEXUS-STUDENT-TEXT-DERIVATIVE-V2\n")
    content.extend(_json({"source_pdf_sha256": source_sha, **attribution}) + b"\n")
    pages = []
    for number, blocks in enumerate(
        (
            ((0, "Une notion claire à expliquer."), (2, "Une deuxième phrase sur cette notion.")),
            ((0, "Le second feuillet traite un autre sujet."),),
            (),
        ),
        1,
    ):
        start = len(content)
        citation = {"source_pdf_sha256": source_sha, "source_page": number, **attribution}
        all_blocks = []
        selected = []
        for index, text in blocks:
            content.extend(f"\n[PAGE {number} BLOCK {index}]\n".encode())
            content.extend(_json(citation) + b"\n")
            block_start = len(content)
            content.extend(text.encode())
            block_end = len(content)
            content.extend(b"\n")
            all_blocks.append({
                "block_index": index,
                "block_type": 0,
                "block_class": "SAFE_TEXT_CANDIDATE",
                "normalized_text_sha256": _sha(text.encode()),
                "byte_start": block_start,
                "byte_end": block_end,
                "citation": citation,
            })
            selected.append(index)
        if number == 1:
            all_blocks.insert(1, {
                "block_index": 1,
                "block_class": "EXCLUDED_NON_TEXT",
                "normalized_text_sha256": "b" * 64,
            })
        groups = []
        if blocks:
            texts = [text for _, text in blocks]
            groups.append({
                "group_index": 1,
                "group_count": 1,
                "block_indices": selected,
                "group_text_sha256": _sha("\n\n".join(texts).encode()),
                "citation": citation,
                "byte_start": all_blocks[0]["byte_start"],
                "byte_end": all_blocks[-1]["byte_end"],
            })
        pages.append({
            "page_number": number,
            "byte_start": start,
            "byte_end": len(content),
            "derived_page_text_sha256": _sha(bytes(content[start:])),
            "all_blocks": all_blocks,
            "selected_block_indices": selected,
            "review_groups": groups,
        })
    raw = bytes(content)
    return raw, {
        "kind": "NEXUS-STUDENT-NATIVE-TEXT-DERIVATIVE-V1",
        "status": "PREPARED_PRIVATE",
        "serialization_protocol": "NEXUS-STUDENT-TEXT-DERIVATIVE-SERIALIZATION-V2",
        "derivative_media_type": "text/plain",
        "derivative_encoding": "utf-8",
        "derivative_content_sha256": _sha(raw),
        "derivative_byte_count": len(raw),
        "source_content_sha256": source_sha,
        "source_page_count": len(pages),
        "source_attribution": attribution,
        "ocr_used": False,
        "images_copied": False,
        "graphic_renders_copied": False,
        "all_source_pages_inspected": True,
        "publication_authorized": False,
        "pages": pages,
    }


def _chunks(content: bytes, receipt: dict, target_tokens: int = 7):
    return publication_chunking.chunk_verified_derivative(
        content=content,
        receipt=receipt,
        token_counter=_Counter(),
        target_tokens=target_tokens,
    )


def test_native_blocks_on_multiple_pages_are_bounded_without_indexing_metadata() -> None:
    content, receipt = _candidate()
    chunks = _chunks(content, receipt)
    assert [(chunk.page_start, chunk.page_end) for chunk in chunks] == [
        (1, 1), (1, 1), (2, 2),
    ]
    assert [chunk.text for chunk in chunks] == [
        "Une notion claire à expliquer.",
        "Une deuxième phrase sur cette notion.",
        "Le second feuillet traite un autre sujet.",
    ]
    assert [_sha(chunk.text.encode()) for chunk in chunks] == [
        "827f7c1e16fcd1efe85664271c4ee8dd9eaa1bcb6a90e1985ffa340a42721141",
        "bada662bcb5203c3c17c704cf287dd827951a898a449c08ae68153345fa170b3",
        "9e82eeb6a36f6080c4e92e130852376a7d6a41732952ac7cd7d6ff23303ec441",
    ]
    assert all("eduscol" not in chunk.text and "[PAGE" not in chunk.text for chunk in chunks)


def test_altered_block_hash_is_rejected_even_when_candidate_bytes_match() -> None:
    content, receipt = _candidate()
    receipt["pages"][0]["all_blocks"][0]["normalized_text_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="block.*sha"):
        _chunks(content, receipt)


def test_missing_page_is_rejected() -> None:
    content, receipt = _candidate()
    receipt["pages"].pop(1)
    with pytest.raises(ValueError, match="page"):
        _chunks(content, receipt)


def test_forbidden_ocr_or_excluded_block_selection_is_rejected() -> None:
    content, receipt = _candidate()
    receipt["ocr_used"] = True
    with pytest.raises(ValueError, match="OCR|graphic"):
        _chunks(content, receipt)

    _, receipt = _candidate()
    receipt["pages"][0]["selected_block_indices"].append(1)
    with pytest.raises(ValueError, match="SAFE_TEXT_CANDIDATE"):
        _chunks(content, receipt)


def test_altered_group_hash_or_attribution_is_rejected() -> None:
    content, receipt = _candidate()
    wrong_group = copy.deepcopy(receipt)
    wrong_group["pages"][0]["review_groups"][0]["group_text_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="group.*sha"):
        _chunks(content, wrong_group)

    wrong_attribution = copy.deepcopy(receipt)
    wrong_attribution["source_attribution"]["licence_id"] = "UNKNOWN"
    with pytest.raises(ValueError, match="attribution"):
        _chunks(content, wrong_attribution)


def test_extra_serialized_bytes_and_wrong_size_are_rejected() -> None:
    content, receipt = _candidate()
    with pytest.raises(ValueError, match="sha|byte"):
        _chunks(content + b"\n[OCR GRAPHIC]", receipt)
    receipt["derivative_byte_count"] -= 1
    with pytest.raises(ValueError, match="byte"):
        _chunks(content, receipt)


def test_uninspected_page_or_non_native_selected_block_is_rejected() -> None:
    content, receipt = _candidate()
    receipt["all_source_pages_inspected"] = False
    with pytest.raises(ValueError, match="inspected"):
        _chunks(content, receipt)

    _, receipt = _candidate()
    receipt["pages"][0]["all_blocks"][0]["block_type"] = 1
    with pytest.raises(ValueError, match="native"):
        _chunks(content, receipt)
