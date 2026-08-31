"""Immutable filesystem repository for active and N-1 servable corpus manifests."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from nexus_contracts import (
    ServableCorpus,
    ServableCorpusIndex,
    ServableCorpusIndexPayload,
    ServableCorpusManifest,
    SupportedManifest,
    seal_servable_corpus_index,
)
from nexus_contracts.canonical_json import canonical_model_bytes
from pydantic import ValidationError


class ServableCorpusRepositoryError(ValueError):
    """A corpus artifact is unavailable, retired, mutated, or inconsistent."""


def build_servable_corpus_index(
    *,
    active_manifest: ServableCorpusManifest,
    previous_manifest: ServableCorpusManifest | None,
    previous_retire_at: datetime | None,
    generated_at: datetime,
    producer_repository: str,
    producer_commit: str,
) -> ServableCorpusIndex:
    """Build an exact active/N-1 compatibility window."""

    if previous_manifest is None and previous_retire_at is not None:
        raise ServableCorpusRepositoryError("retire_at requires a previous manifest")
    if previous_manifest is not None:
        if previous_retire_at is None or previous_retire_at <= generated_at:
            raise ServableCorpusRepositoryError("previous manifest retire_at is invalid")
    supported = [
        SupportedManifest(
            manifest_version=active_manifest.manifest_version,
            manifest_sha256=active_manifest.manifest_sha256,
            retire_at=None,
        )
    ]
    if previous_manifest is not None:
        supported.append(
            SupportedManifest(
                manifest_version=previous_manifest.manifest_version,
                manifest_sha256=previous_manifest.manifest_sha256,
                retire_at=previous_retire_at,
            )
        )
    try:
        payload = ServableCorpusIndexPayload(
            protocol_version="1",
            producer_repository=producer_repository,
            producer_commit=producer_commit,
            generated_at=generated_at,
            resource_registry_sha256=active_manifest.resource_registry_sha256,
            active_manifest_sha256=active_manifest.manifest_sha256,
            supported_manifests=supported,
        )
    except ValidationError as exc:
        raise ServableCorpusRepositoryError(f"servable corpus index is invalid: {exc}") from exc
    return seal_servable_corpus_index(payload)


def _write_immutable(path: Path, content: bytes) -> None:
    if path.is_symlink():
        raise ServableCorpusRepositoryError("servable corpus path cannot be a symlink")
    if path.exists():
        if not path.is_file() or path.read_bytes() != content:
            raise ServableCorpusRepositoryError("servable corpus artifact is immutable")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise ServableCorpusRepositoryError("servable corpus publication raced") from exc


def publish_servable_corpus_bundle(
    directory: Path,
    *,
    index: ServableCorpusIndex,
    manifests: Iterable[ServableCorpusManifest],
) -> None:
    """Publish digest-addressed bytes; an existing byte may never change."""

    root = directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest_by_digest = {item.manifest_sha256: item for item in manifests}
    required = {item.manifest_sha256 for item in index.supported_manifests}
    if set(manifest_by_digest) != required:
        raise ServableCorpusRepositoryError("supported manifest publication set differs")
    active_manifest = manifest_by_digest[index.active_manifest_sha256]
    if active_manifest.resource_registry_sha256 != index.resource_registry_sha256:
        raise ServableCorpusRepositoryError("resource registry digest differs")
    for digest, manifest in sorted(manifest_by_digest.items()):
        content = canonical_model_bytes(manifest) + b"\n"
        _write_immutable(
            root / "manifests" / f"{digest}.json",
            content,
        )
        _write_immutable(
            root / "manifests" / f"{digest}.aria-rag-manifest",
            content,
        )
    _write_immutable(
        root / "servable-corpus-index-v1.json",
        canonical_model_bytes(index) + b"\n",
    )


class FilesystemServableCorpusRepository:
    """Fail-closed runtime loader with an injected clock for retirement tests."""

    def __init__(
        self,
        *,
        directory: Path,
        expected_index_sha256: str,
        now: Callable[[], datetime],
    ) -> None:
        self._directory = directory.resolve()
        self._expected_index_sha256 = expected_index_sha256
        self._now = now

    @staticmethod
    def _read_model(path: Path, model: type[ServableCorpusIndex] | type[ServableCorpusManifest]):
        if path.is_symlink() or not path.is_file():
            raise ServableCorpusRepositoryError("servable corpus artifact is unavailable")
        try:
            return model.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise ServableCorpusRepositoryError("servable corpus manifest is invalid") from exc

    def index(self) -> ServableCorpusIndex:
        index = self._read_model(
            self._directory / "servable-corpus-index-v1.json",
            ServableCorpusIndex,
        )
        assert isinstance(index, ServableCorpusIndex)
        if index.index_sha256 != self._expected_index_sha256:
            raise ServableCorpusRepositoryError("servable corpus index digest differs")
        return index

    def manifest(self, manifest_sha256: str) -> ServableCorpusManifest:
        index = self.index()
        supported = next(
            (
                item
                for item in index.supported_manifests
                if item.manifest_sha256 == manifest_sha256
            ),
            None,
        )
        if supported is None:
            raise ServableCorpusRepositoryError("manifest is not supported")
        if supported.retire_at is not None and self._now() >= supported.retire_at:
            raise ServableCorpusRepositoryError("manifest is retired")
        manifest = self._read_model(
            self._directory / "manifests" / f"{manifest_sha256}.json",
            ServableCorpusManifest,
        )
        assert isinstance(manifest, ServableCorpusManifest)
        if manifest.manifest_sha256 != manifest_sha256:
            raise ServableCorpusRepositoryError("manifest digest differs")
        if (
            manifest_sha256 == index.active_manifest_sha256
            and manifest.resource_registry_sha256 != index.resource_registry_sha256
        ):
            raise ServableCorpusRepositoryError("resource registry digest differs")
        return manifest

    def resolve_corpus(
        self,
        *,
        manifest_sha256: str,
        corpus_id: str,
        corpus_version_id: str,
    ) -> ServableCorpus:
        manifest = self.manifest(manifest_sha256)
        matches = [
            item
            for item in manifest.corpora
            if item.corpus_id == corpus_id
            and item.corpus_version_id == corpus_version_id
        ]
        if len(matches) != 1:
            raise ServableCorpusRepositoryError("corpus identity is unavailable")
        return matches[0]


__all__ = [
    "FilesystemServableCorpusRepository",
    "ServableCorpusRepositoryError",
    "build_servable_corpus_index",
    "publish_servable_corpus_bundle",
]
