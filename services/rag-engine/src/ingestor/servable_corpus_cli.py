"""Fail-closed builder for immutable servable-corpus publication bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from nexus_contracts import (
    ResourceRegistryBootstrap,
    ResourceRegistrySnapshot,
    ServableCorpusIndex,
    ServableCorpusManifest,
)
from pydantic import TypeAdapter, ValidationError

try:
    from .servable_corpus_index import (
        ServableCorpusRepositoryError,
        build_servable_corpus_index,
        publish_servable_corpus_bundle,
    )
    from .servable_corpus_manifest import (
        CorpusBuildSpec,
        ServableCorpusBuildError,
        build_servable_corpus_manifest,
    )
except ImportError:
    from servable_corpus_index import (  # type: ignore[no-redef]
        ServableCorpusRepositoryError,
        build_servable_corpus_index,
        publish_servable_corpus_bundle,
    )
    from servable_corpus_manifest import (  # type: ignore[no-redef]
        CorpusBuildSpec,
        ServableCorpusBuildError,
        build_servable_corpus_manifest,
    )


class ServableCorpusCliError(ValueError):
    """A pinned input or requested publication bundle is invalid."""


def _read_pinned(path: Path, expected_sha256: str, label: str) -> bytes:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ServableCorpusCliError(f"{label} is unavailable") from exc
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ServableCorpusCliError(f"{label} file digest differs")
    return content


def build_and_publish_bundle(
    *,
    resource_inventory_path: Path,
    expected_resource_inventory_file_sha256: str,
    resource_registry_path: Path,
    expected_resource_registry_file_sha256: str,
    corpus_specs_path: Path,
    expected_corpus_specs_file_sha256: str,
    manifest_version: str,
    producer_commit: str,
    generated_at: datetime,
    output_directory: Path,
    previous_manifest_path: Path | None = None,
    expected_previous_manifest_file_sha256: str | None = None,
    previous_retire_at: datetime | None = None,
) -> tuple[ServableCorpusIndex, ServableCorpusManifest]:
    """Validate all externally pinned bytes before publishing active/N-1."""

    if (previous_manifest_path is None) != (
        expected_previous_manifest_file_sha256 is None
    ) or (previous_manifest_path is None) != (previous_retire_at is None):
        raise ServableCorpusCliError(
            "previous manifest path, digest and retire_at must be provided together"
        )
    try:
        resource_inventory = ResourceRegistryBootstrap.model_validate_json(
            _read_pinned(
                resource_inventory_path,
                expected_resource_inventory_file_sha256,
                "resource inventory",
            )
        )
        resource_registry = ResourceRegistrySnapshot.model_validate_json(
            _read_pinned(
                resource_registry_path,
                expected_resource_registry_file_sha256,
                "resource registry",
            )
        )
        corpus_specs = TypeAdapter(list[CorpusBuildSpec]).validate_json(
            _read_pinned(
                corpus_specs_path,
                expected_corpus_specs_file_sha256,
                "corpus specs",
            )
        )
        previous = (
            ServableCorpusManifest.model_validate_json(
                _read_pinned(
                    previous_manifest_path,
                    expected_previous_manifest_file_sha256,
                    "previous manifest",
                )
            )
            if previous_manifest_path is not None
            and expected_previous_manifest_file_sha256 is not None
            else None
        )
        active = build_servable_corpus_manifest(
            resource_inventory=resource_inventory,
            resource_registry=resource_registry,
            manifest_version=manifest_version,
            producer_repository="cyranoaladin/RAG",
            producer_commit=producer_commit,
            generated_at=generated_at,
            corpus_specs=corpus_specs,
        )
        index = build_servable_corpus_index(
            active_manifest=active,
            previous_manifest=previous,
            previous_retire_at=previous_retire_at,
            generated_at=generated_at,
            producer_repository="cyranoaladin/RAG",
            producer_commit=producer_commit,
        )
        publish_servable_corpus_bundle(
            output_directory,
            index=index,
            manifests=[active, *([previous] if previous is not None else [])],
        )
    except (
        json.JSONDecodeError,
        ValidationError,
        ServableCorpusBuildError,
        ServableCorpusRepositoryError,
    ) as exc:
        raise ServableCorpusCliError("servable corpus publication refused") from exc
    return index, active


def _aware_datetime(raw: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resource-inventory", required=True, type=Path)
    parser.add_argument("--resource-inventory-file-sha256", required=True)
    parser.add_argument("--resource-registry", required=True, type=Path)
    parser.add_argument("--resource-registry-file-sha256", required=True)
    parser.add_argument("--corpus-specs", required=True, type=Path)
    parser.add_argument("--corpus-specs-file-sha256", required=True)
    parser.add_argument("--manifest-version", required=True)
    parser.add_argument("--producer-commit", required=True)
    parser.add_argument("--generated-at", required=True, type=_aware_datetime)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--previous-manifest", type=Path)
    parser.add_argument("--previous-manifest-file-sha256")
    parser.add_argument("--previous-retire-at", type=_aware_datetime)
    args = parser.parse_args(argv)
    index, active = build_and_publish_bundle(
        resource_inventory_path=args.resource_inventory,
        expected_resource_inventory_file_sha256=args.resource_inventory_file_sha256,
        resource_registry_path=args.resource_registry,
        expected_resource_registry_file_sha256=args.resource_registry_file_sha256,
        corpus_specs_path=args.corpus_specs,
        expected_corpus_specs_file_sha256=args.corpus_specs_file_sha256,
        manifest_version=args.manifest_version,
        producer_commit=args.producer_commit,
        generated_at=args.generated_at,
        output_directory=args.output_directory,
        previous_manifest_path=args.previous_manifest,
        expected_previous_manifest_file_sha256=args.previous_manifest_file_sha256,
        previous_retire_at=args.previous_retire_at,
    )
    print(
        json.dumps(
            {
                "activeManifestSha256": active.manifest_sha256,
                "indexSha256": index.index_sha256,
                "resourceRegistrySha256": index.resource_registry_sha256,
            },
            sort_keys=True,
        )
    )
    return 0


__all__ = ["ServableCorpusCliError", "build_and_publish_bundle", "main"]
