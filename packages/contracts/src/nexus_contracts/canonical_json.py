"""Canonical JSON helpers shared by signed and digested public contracts."""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel


def canonical_model_bytes(model: BaseModel, *, exclude: set[str] | None = None) -> bytes:
    payload = model.model_dump(mode="json", exclude=exclude or set())
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_model_sha256(
    model: BaseModel, *, exclude: set[str] | None = None
) -> str:
    return hashlib.sha256(canonical_model_bytes(model, exclude=exclude)).hexdigest()


__all__ = ["canonical_model_bytes", "canonical_model_sha256"]
