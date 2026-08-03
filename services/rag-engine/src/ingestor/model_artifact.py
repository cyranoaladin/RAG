"""Vérification générique et hors-ligne d'un artefact modèle immuable."""

from __future__ import annotations

import json
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from pathlib import Path
from typing import NoReturn


class ModelArtifactError(RuntimeError):
    """L'identité ou l'intégrité de l'artefact ne peut pas être prouvée."""


_CHECKSUM_LINE = re.compile(r"(?P<digest>[0-9a-f]{64})  (?P<path>[^\r\n]+)")
_MAX_HEALTH_INVENTORY_BYTES = 16 * 1024 * 1024
_MAX_HEALTH_ENTRIES = 10_000


@dataclass(frozen=True)
class _ArtifactEntryState:
    relative_path: str
    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class ModelArtifactAttestation:
    """État borné d'un artefact intégralement vérifié au démarrage."""

    root: Path
    inventory_sha256: str
    entries: tuple[_ArtifactEntryState, ...]


def _fail_invalid() -> NoReturn:
    raise ModelArtifactError("MODEL_ARTIFACT_INVALID")


def _entry_state(path: Path, relative_path: str) -> _ArtifactEntryState:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        _fail_invalid()
    return _ArtifactEntryState(
        relative_path=relative_path,
        device=metadata.st_dev,
        inode=metadata.st_ino,
        mode=metadata.st_mode,
        size=metadata.st_size,
        mtime_ns=metadata.st_mtime_ns,
        ctime_ns=metadata.st_ctime_ns,
    )


def _bounded_entry_paths(root: Path) -> tuple[Path, ...]:
    """Énumérer au plus la borne publique, afin de détecter tout ajout."""
    entries: list[Path] = []
    for entry in root.rglob("*"):
        entries.append(entry)
        if len(entries) > _MAX_HEALTH_ENTRIES:
            _fail_invalid()
    return tuple(sorted(entries, key=lambda path: path.as_posix()))


def _read_bounded_inventory(path: Path) -> bytes:
    with path.open("rb") as handle:
        content = handle.read(_MAX_HEALTH_INVENTORY_BYTES + 1)
    if len(content) > _MAX_HEALTH_INVENTORY_BYTES:
        _fail_invalid()
    return content


def verify_model_artifact(
    artifact_root: Path,
    *,
    expected_inventory_sha256: str,
    expected_manifest: Mapping[str, object],
    required_files: frozenset[str] = frozenset(),
    require_model_weights: bool = False,
) -> Path:
    """Prouver l'identité et l'inventaire liés à une ancre externe."""
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

        if re.fullmatch(r"[0-9a-f]{64}", expected_inventory_sha256) is None:
            _fail_invalid()
        inventory_bytes = (root / "SHA256SUMS").read_bytes()
        if not compare_digest(
            sha256(inventory_bytes).hexdigest(),
            expected_inventory_sha256,
        ):
            _fail_invalid()

        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or any(
            manifest.get(key) != value for key, value in expected_manifest.items()
        ):
            _fail_invalid()

        checksums: dict[str, str] = {}
        for line in inventory_bytes.decode("utf-8").splitlines():
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


def attest_verified_model_artifact(
    artifact_root: Path,
    *,
    expected_inventory_sha256: str,
) -> ModelArtifactAttestation:
    """Mémoriser les métadonnées d'un artefact déjà haché intégralement.

    Le résultat permet à une sonde publique de détecter les remplacements,
    ajouts et suppressions usuels sans relire les poids potentiellement
    multi-gigaoctets. Les montages de production restent obligatoirement en
    lecture seule ; le chargement du modèle refait la preuve cryptographique.
    """
    if re.fullmatch(r"[0-9a-f]{64}", expected_inventory_sha256) is None:
        _fail_invalid()
    try:
        root = artifact_root.resolve(strict=True)
        if root.is_symlink() or not root.is_dir():
            _fail_invalid()
        entries = _bounded_entry_paths(root)
        inventory = root / "SHA256SUMS"
        inventory_bytes = _read_bounded_inventory(inventory)
        if not compare_digest(
            sha256(inventory_bytes).hexdigest(),
            expected_inventory_sha256,
        ):
            _fail_invalid()
        states = (_entry_state(root, "."),) + tuple(
            _entry_state(entry, entry.relative_to(root).as_posix())
            for entry in entries
        )
    except ModelArtifactError:
        raise
    except (OSError, ValueError) as exc:
        raise ModelArtifactError("MODEL_ARTIFACT_INVALID") from exc
    return ModelArtifactAttestation(
        root=root,
        inventory_sha256=expected_inventory_sha256,
        entries=states,
    )


def model_artifact_attestation_ready(
    attestation: ModelArtifactAttestation,
    *,
    expected_inventory_sha256: str,
) -> bool:
    """Contrôler à coût borné l'état attesté, sans rehacher les poids."""
    if not compare_digest(
        attestation.inventory_sha256,
        expected_inventory_sha256,
    ):
        return False
    try:
        entries = _bounded_entry_paths(attestation.root)
        current_states = (_entry_state(attestation.root, "."),) + tuple(
            _entry_state(entry, entry.relative_to(attestation.root).as_posix())
            for entry in entries
        )
        return current_states == attestation.entries
    except (ModelArtifactError, OSError, ValueError):
        return False


__all__ = [
    "ModelArtifactAttestation",
    "ModelArtifactError",
    "attest_verified_model_artifact",
    "model_artifact_attestation_ready",
    "verify_model_artifact",
]
