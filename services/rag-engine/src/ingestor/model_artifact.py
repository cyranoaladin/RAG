"""Vérification générique et hors-ligne d'un artefact modèle immuable."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import NoReturn


class ModelArtifactError(RuntimeError):
    """L'identité ou l'intégrité de l'artefact ne peut pas être prouvée."""


_CHECKSUM_LINE = re.compile(r"(?P<digest>[0-9a-f]{64})  (?P<path>[^\r\n]+)")


def _fail_invalid() -> NoReturn:
    raise ModelArtifactError("MODEL_ARTIFACT_INVALID")


def verify_model_artifact(
    artifact_root: Path,
    *,
    expected_manifest: Mapping[str, object],
    required_files: frozenset[str] = frozenset(),
    require_model_weights: bool = False,
) -> Path:
    """Prouver l'identité et l'inventaire SHA-256 exact avant chargement."""
    if artifact_root.is_symlink() or not artifact_root.is_dir():
        raise ModelArtifactError("MODEL_ARTIFACT_PATH_MISSING")

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
        if not required_files.issubset(files):
            _fail_invalid()
        if require_model_weights and not any(
            Path(relative).name == "pytorch_model.bin"
            or Path(relative).name.endswith(".safetensors")
            for relative in files
        ):
            _fail_invalid()

        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or any(
            manifest.get(key) != value for key, value in expected_manifest.items()
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
    except ModelArtifactError:
        raise
    except (OSError, ValueError) as exc:
        raise ModelArtifactError("MODEL_ARTIFACT_INVALID") from exc
    return root


__all__ = ["ModelArtifactError", "verify_model_artifact"]
