"""Parse sealed student text derivatives without exposing their metadata as text.

The receipt supplies byte ranges for native PDF blocks.  This parser verifies
the complete V2 serialization, including every skipped page and review group,
before returning only SAFE_TEXT_CANDIDATE group text to the chunker.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


_MAGIC = b"NEXUS-STUDENT-TEXT-DERIVATIVE-V2\n"
_ATTRIBUTION_KEYS = frozenset({
    "source_uri", "source_label", "source_updated_at", "source_date_kind",
    "licensor", "licence_id", "derivative_notice",
})


@dataclass(frozen=True)
class DerivativePage:
    page_number: int
    groups: tuple[str, ...]


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"derivative {name} is invalid")
    return value


def _parse_attribution(receipt: Mapping[str, Any]) -> Mapping[str, Any]:
    attribution = _mapping(receipt.get("source_attribution"), "attribution")
    if set(attribution) != _ATTRIBUTION_KEYS or any(
        not isinstance(value, str) or not value.strip()
        for value in attribution.values()
    ):
        raise ValueError("derivative attribution is incomplete")
    return attribution


def parse_verified_derivative_pages(
    content: bytes, receipt: Mapping[str, Any],
) -> tuple[DerivativePage, ...]:
    """Verify exact bytes and receipt topology; return native-text groups only.

    This is an ingestion parser, not an independent rights authority.  Callers
    must also verify the approved receipt pack and source rights gate.
    """
    receipt = _mapping(receipt, "receipt")
    if (
        receipt.get("kind") != "NEXUS-STUDENT-NATIVE-TEXT-DERIVATIVE-V1"
        or receipt.get("status") != "PREPARED_PRIVATE"
        or receipt.get("serialization_protocol")
        != "NEXUS-STUDENT-TEXT-DERIVATIVE-SERIALIZATION-V2"
        or receipt.get("derivative_media_type") != "text/plain"
        or receipt.get("derivative_encoding") != "utf-8"
    ):
        raise ValueError("derivative serialization protocol is invalid")
    if any(receipt.get(flag) is not False for flag in (
        "ocr_used", "images_copied", "graphic_renders_copied",
    )):
        raise ValueError("derivative OCR or graphic content is forbidden")
    if receipt.get("all_source_pages_inspected") is not True:
        raise ValueError("derivative source pages were not all inspected")
    if type(receipt.get("derivative_byte_count")) is not int or (
        receipt["derivative_byte_count"] != len(content)
    ):
        raise ValueError("derivative byte count mismatch")
    if receipt.get("derivative_content_sha256") != _sha(content):
        raise ValueError("derivative sha mismatch")

    source_sha = receipt.get("source_content_sha256")
    if not isinstance(source_sha, str) or len(source_sha) != 64 or any(
        char not in "0123456789abcdef" for char in source_sha
    ):
        raise ValueError("derivative source sha is invalid")
    attribution = _parse_attribution(receipt)
    header = _MAGIC + _canonical_json({
        "source_pdf_sha256": source_sha, **attribution,
    }) + b"\n"
    if not content.startswith(header):
        raise ValueError("derivative header attribution mismatch")

    pages_raw = receipt.get("pages")
    if not isinstance(pages_raw, list) or (
        type(receipt.get("source_page_count")) is not int
        or len(pages_raw) != receipt["source_page_count"]
        or not pages_raw
    ):
        raise ValueError("derivative page count mismatch")

    parsed: list[DerivativePage] = []
    cursor = len(header)
    for page_number, page_raw in enumerate(pages_raw, 1):
        page = _mapping(page_raw, "page")
        if page.get("page_number") != page_number or page.get("byte_start") != cursor:
            raise ValueError("derivative page order or start mismatch")
        blocks_raw = page.get("all_blocks")
        selected = page.get("selected_block_indices")
        groups_raw = page.get("review_groups")
        if (not isinstance(blocks_raw, list) or not isinstance(selected, list)
                or not isinstance(groups_raw, list)):
            raise ValueError("derivative page block or group map is invalid")
        blocks: dict[int, Mapping[str, Any]] = {}
        safe_indices: list[int] = []
        for position, block_raw in enumerate(blocks_raw):
            block = _mapping(block_raw, "block")
            index = block.get("block_index")
            if type(index) is not int or index != position:
                raise ValueError("derivative block index order is invalid")
            blocks[index] = block
            if block.get("block_class") == "SAFE_TEXT_CANDIDATE":
                if type(block.get("block_type")) is not int or block["block_type"] != 0:
                    raise ValueError("derivative selected block is not native text")
                safe_indices.append(index)
            elif "byte_start" in block or "byte_end" in block:
                raise ValueError("derivative excluded block has public bytes")
        if selected != safe_indices:
            raise ValueError("derivative selected blocks are not exactly SAFE_TEXT_CANDIDATE")

        texts: dict[int, str] = {}
        for index in selected:
            block = blocks[index]
            citation = {"source_pdf_sha256": source_sha,
                        "source_page": page_number, **attribution}
            if block.get("citation") != citation:
                raise ValueError("derivative block attribution mismatch")
            prefix = f"\n[PAGE {page_number} BLOCK {index}]\n".encode("ascii")
            prefix += _canonical_json(citation) + b"\n"
            if content[cursor:cursor + len(prefix)] != prefix:
                raise ValueError("derivative block serialization mismatch")
            cursor += len(prefix)
            if block.get("byte_start") != cursor:
                raise ValueError("derivative block byte start mismatch")
            end = block.get("byte_end")
            if type(end) is not int or end <= cursor or end >= len(content):
                raise ValueError("derivative block byte end mismatch")
            block_bytes = content[cursor:end]
            if block.get("normalized_text_sha256") != _sha(block_bytes):
                raise ValueError("derivative block sha mismatch")
            try:
                text = block_bytes.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError("derivative block UTF-8 invalid") from error
            if not text.strip() or text.strip() != text or "\r" in text:
                raise ValueError("derivative block text is not normalized")
            if content[end:end + 1] != b"\n":
                raise ValueError("derivative block separator mismatch")
            texts[index] = text
            cursor = end + 1

        if page.get("byte_end") != cursor or (
            page.get("derived_page_text_sha256")
            != _sha(content[page["byte_start"]:cursor])
        ):
            raise ValueError("derivative page bytes or sha mismatch")

        groups: list[str] = []
        covered: list[int] = []
        for group_number, group_raw in enumerate(groups_raw, 1):
            group = _mapping(group_raw, "group")
            indices = group.get("block_indices")
            if not isinstance(indices, list) or not indices or any(
                type(index) is not int or index not in texts for index in indices
            ):
                raise ValueError("derivative group block identity invalid")
            covered.extend(indices)
            group_text = "\n\n".join(texts[index] for index in indices)
            if (group.get("group_index") != group_number
                    or group.get("group_count") != len(groups_raw)
                    or group.get("citation") != {
                        "source_pdf_sha256": source_sha,
                        "source_page": page_number, **attribution,
                    }
                    or group.get("byte_start") != blocks[indices[0]]["byte_start"]
                    or group.get("byte_end") != blocks[indices[-1]]["byte_end"]):
                raise ValueError("derivative group order or attribution mismatch")
            if group.get("group_text_sha256") != _sha(group_text.encode("utf-8")):
                raise ValueError("derivative group sha mismatch")
            groups.append(group_text)
        if covered != selected:
            raise ValueError("derivative group coverage mismatch")
        parsed.append(DerivativePage(page_number=page_number, groups=tuple(groups)))
    if cursor != len(content):
        raise ValueError("derivative trailing bytes outside verified pages")
    return tuple(parsed)


__all__ = ["DerivativePage", "parse_verified_derivative_pages"]
