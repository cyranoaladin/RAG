"""Chargement fail-closed et hors-ligne du reranker canonique v2."""

from __future__ import annotations

import json
import os
import re
from hashlib import sha256
from pathlib import Path
from typing import Any, Final, NoReturn

CANONICAL_RERANK_MODEL: Final = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class RerankerContractError(RuntimeError):
    """Le reranker canonique ne peut pas être prouvé disponible hors-ligne."""


_CHECKSUM_LINE = re.compile(r"(?P<digest>[0-9a-f]{64})  (?P<path>[^\r\n]+)")


def _fail_invalid() -> NoReturn:
    raise RerankerContractError("RERANKER_MODEL_ARTIFACT_INVALID")


def verify_reranker_artifact(artifact_root: Path) -> Path:
    """Vérifier identité, inventaire et SHA-256 avant tout chargement de poids."""
    if artifact_root.is_symlink() or not artifact_root.is_dir():
        raise RerankerContractError("RERANKER_MODEL_ARTIFACT_PATH_MISSING")

    try:
        root = artifact_root.resolve(strict=True)
        entries = tuple(root.rglob("*"))
        if any(entry.is_symlink() for entry in entries):
            _fail_invalid()
        files = {
            entry.relative_to(root).as_posix()
            for entry in entries
            if entry.is_file()
        }
        if "manifest.json" not in files or "SHA256SUMS" not in files:
            _fail_invalid()

        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if (
            not isinstance(manifest, dict)
            or manifest.get("model_id") != CANONICAL_RERANK_MODEL
        ):
            _fail_invalid()

        checksums: dict[str, str] = {}
        for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            match = _CHECKSUM_LINE.fullmatch(line)
            if match is None:
                _fail_invalid()
            relative = match.group("path")
            candidate = Path(relative)
            if (
                candidate.is_absolute()
                or relative == "SHA256SUMS"
                or any(part in ("", ".", "..") for part in candidate.parts)
                or relative in checksums
            ):
                _fail_invalid()
            resolved = (root / candidate).resolve(strict=True)
            resolved.relative_to(root)
            if not resolved.is_file():
                _fail_invalid()
            checksums[relative] = match.group("digest")

        expected_files = files - {"SHA256SUMS"}
        if set(checksums) != expected_files or "manifest.json" not in checksums:
            _fail_invalid()
        for relative, expected_digest in checksums.items():
            digest = sha256()
            with (root / relative).open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != expected_digest:
                _fail_invalid()
    except RerankerContractError:
        raise
    except (OSError, ValueError) as exc:
        raise RerankerContractError("RERANKER_MODEL_ARTIFACT_INVALID") from exc
    return root


def load_reranker_model() -> Any:
    """Charger exclusivement l'artefact local, sans téléchargement implicite."""
    configured = os.environ.get("RAG_RERANKER_MODEL_CACHE_DIR", "").strip()
    if not configured:
        raise RerankerContractError("RERANKER_MODEL_ARTIFACT_PATH_REQUIRED")
    model_source = verify_reranker_artifact(Path(configured))

    try:
        from sentence_transformers import CrossEncoder

        return CrossEncoder(
            str(model_source),
            max_length=512,
            local_files_only=True,
        )
    except RerankerContractError:
        raise
    except Exception as exc:
        raise RerankerContractError("RERANKER_MODEL_UNAVAILABLE") from exc


__all__ = [
    "CANONICAL_RERANK_MODEL",
    "RerankerContractError",
    "load_reranker_model",
    "verify_reranker_artifact",
]
