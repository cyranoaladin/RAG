"""Produit la projection canonique indépendante contenu -> profil -> scope.

Ce module ne connaît ni set d'autorisations, ni fichier d'autorité. Il ne
compose que des faits déjà acceptés par le plan de contrôle : placements de
release, registre de releases et profils vérifiés.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from nexus_contracts.authorization_set import (
    ReleaseScopePlacementEntryV1,
    ReleaseScopePlacementV1,
    VerifiedProfileFactV1,
    scope_digest,
)
from nexus_contracts.ingestion import (
    CollectionProfile,
    ResourceScope,
    collection_profile_fingerprint,
)
from nexus_contracts.profile_manifest import (
    CanonicalProfileVersionError,
    ProductionProfileManifestError,
    StrictYamlError,
    require_canonical_profile_version,
    strict_yaml_mapping,
    validate_production_profile_manifest,
)
from pydantic import ValidationError

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ReleaseScopePlacementProducerError(ValueError):
    """Un fait d'entrée ne permet pas une projection exacte et totale."""


def _fail(code: str, detail: str) -> ReleaseScopePlacementProducerError:
    return ReleaseScopePlacementProducerError(f"{code}: {detail}")


@dataclass(frozen=True)
class _MatrixPartition:
    partition_id: str
    content_sha256: tuple[str, ...]
    scope: ResourceScope
    source_paths: tuple[str, ...]
    evidence_paths: tuple[str, ...]


@dataclass(frozen=True)
class ReleaseScopePlacementProvenance:
    source_tree_sha: str
    input_blob_sha256: Mapping[str, str]
    input_git_entries: Mapping[str, str]


@dataclass(frozen=True)
class ProducedReleaseScopePlacement:
    placement: ReleaseScopePlacementV1
    provenance: ReleaseScopePlacementProvenance


def _reject_duplicate_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _fail("DUPLICATE_JSON_KEY", f"duplicate key {key!r}")
        result[key] = value
    return result


def _parse_strict_json(raw: bytes, *, path: str) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _fail("INVALID_INPUT", f"{path} is not valid UTF-8: {exc}") from exc
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_json_pairs)
    except ReleaseScopePlacementProducerError:
        raise
    except json.JSONDecodeError as exc:
        raise _fail("INVALID_INPUT", f"{path} is not valid JSON: {exc}") from exc


def _parse_expected_contents(raw: bytes, *, path: str) -> tuple[str, ...]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _fail("INVALID_INPUT", f"{path} is not valid UTF-8: {exc}") from exc
    if not text or not text.endswith("\n") or "\r" in text:
        raise _fail("INVALID_INPUT", f"{path} must use canonical LF-final lines")
    lines = text[:-1].split("\n")
    if any(not line for line in lines):
        raise _fail("INVALID_INPUT", f"{path} contains an empty line")
    return tuple(lines)


def _canonical_repo_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise _fail("INVALID_REPO_PATH", "repository path is null or blank")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "://" in value
        or "\\" in value
        or value != path.as_posix()
    ):
        raise _fail("INVALID_REPO_PATH", f"unsafe repository path {value!r}")
    return value


@dataclass(frozen=True)
class _GitTreeEntry:
    mode: str
    object_type: str
    object_id: str
    path: str


def _parse_git_tree_entry(raw: bytes, *, expected_path: str) -> _GitTreeEntry:
    """Parse une unique entrée ``git ls-tree -z`` sans déquotage de chemin."""
    if not raw or not raw.endswith(b"\0"):
        raise _fail(
            "INVALID_GIT_TREE_ENTRY",
            f"missing exact tree entry for {expected_path!r}",
        )
    records = raw[:-1].split(b"\0")
    if len(records) != 1 or not records[0]:
        raise _fail(
            "INVALID_GIT_TREE_ENTRY",
            f"expected one exact tree entry for {expected_path!r}",
        )
    metadata, separator, path_bytes = records[0].partition(b"\t")
    if not separator or path_bytes != expected_path.encode("utf-8"):
        raise _fail(
            "INVALID_GIT_TREE_ENTRY",
            f"tree entry path does not exactly match {expected_path!r}",
        )
    fields = metadata.split(b" ")
    if len(fields) != 3:
        raise _fail("INVALID_GIT_TREE_ENTRY", f"malformed metadata for {expected_path!r}")
    try:
        mode, object_type, object_id = (field.decode("ascii") for field in fields)
    except UnicodeDecodeError as exc:
        raise _fail(
            "INVALID_GIT_TREE_ENTRY",
            f"non-ASCII metadata for {expected_path!r}",
        ) from exc
    if object_type != "blob":
        raise _fail(
            "INVALID_GIT_TREE_ENTRY",
            f"refusing type {object_type} for {expected_path!r}",
        )
    if mode != "100644":
        raise _fail(
            "INVALID_GIT_TREE_ENTRY",
            f"refusing mode {mode} for {expected_path!r}",
        )
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", object_id) is None:
        raise _fail(
            "INVALID_GIT_TREE_ENTRY",
            f"invalid object id for {expected_path!r}",
        )
    return _GitTreeEntry(
        mode=mode,
        object_type=object_type,
        object_id=object_id,
        path=expected_path,
    )


class _GitTreeReader:
    def __init__(self, *, repository_root: Path, source_tree_sha: str) -> None:
        if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", source_tree_sha) is None:
            raise _fail("INVALID_TREE_SHA", "source tree SHA must be exact lowercase hex")
        self.repository_root = repository_root.resolve()
        self.source_tree_sha = source_tree_sha
        self.input_blob_sha256: dict[str, str] = {}
        self.input_git_entries: dict[str, str] = {}
        self._blob_cache: dict[str, bytes] = {}
        kind = self._git("cat-file", "-t", source_tree_sha).decode().strip()
        if kind != "tree":
            raise _fail("INVALID_TREE_SHA", f"{source_tree_sha} is not a Git tree")

    def _git(self, *args: str) -> bytes:
        environment = dict(os.environ)
        environment["GIT_LITERAL_PATHSPECS"] = "1"
        try:
            completed = subprocess.run(
                ["git", "-C", str(self.repository_root), *args],
                capture_output=True,
                check=False,
                env=environment,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise _fail("GIT_READ_FAILED", str(exc)) from exc
        if completed.returncode != 0:
            raise _fail("GIT_READ_FAILED", f"git {' '.join(args[:2])} failed")
        return completed.stdout

    def read_blob(self, path: str) -> bytes:
        canonical = _canonical_repo_path(path)
        cached = self._blob_cache.get(canonical)
        if cached is not None:
            return cached
        entry = _parse_git_tree_entry(
            self._git("ls-tree", "-z", self.source_tree_sha, "--", canonical),
            expected_path=canonical,
        )
        raw = self._git("cat-file", "blob", entry.object_id)
        self.input_blob_sha256[canonical] = hashlib.sha256(raw).hexdigest()
        self.input_git_entries[canonical] = f"{entry.mode} {entry.object_type} {entry.object_id}"
        self._blob_cache[canonical] = raw
        return raw


def _release_collections(release_registry: Mapping[str, Any]) -> dict[str, set[str]]:
    releases = release_registry.get("releases")
    if not isinstance(releases, list):
        raise _fail("INVALID_RELEASE_REGISTRY", "'releases' must be a list")
    result: dict[str, set[str]] = {}
    for index, release in enumerate(releases):
        if not isinstance(release, Mapping):
            raise _fail("INVALID_RELEASE_REGISTRY", f"release #{index} must be an object")
        release_id = release.get("release_id")
        collections = release.get("collections")
        if not isinstance(release_id, str) or not release_id:
            raise _fail("INVALID_RELEASE_REGISTRY", f"release #{index} has no release_id")
        if release_id in result:
            raise _fail("INVALID_RELEASE_REGISTRY", f"duplicate release_id {release_id!r}")
        if (
            not isinstance(collections, list)
            or not collections
            or any(not isinstance(value, str) or not value for value in collections)
        ):
            raise _fail(
                "INVALID_RELEASE_REGISTRY",
                f"release {release_id!r} has invalid collections",
            )
        if len(collections) != len(set(collections)):
            raise _fail(
                "INVALID_RELEASE_REGISTRY",
                f"release {release_id!r} repeats a collection",
            )
        result[release_id] = set(collections)
    return result


def _profile_index(
    records: Sequence[VerifiedProfileFactV1 | Mapping[str, Any]],
) -> dict[tuple[str, str], VerifiedProfileFactV1]:
    profiles: dict[tuple[str, str], VerifiedProfileFactV1] = {}
    for index, record in enumerate(records):
        try:
            fact = (
                record
                if isinstance(record, VerifiedProfileFactV1)
                else VerifiedProfileFactV1.model_validate(record)
            )
        except ValidationError as exc:
            raise _fail(
                "UNREPRESENTABLE_SCOPE",
                f"verified profile record #{index} is invalid: {exc}",
            ) from exc
        key = (fact.profile_id, fact.profile_version)
        if key in profiles:
            raise _fail("AMBIGUOUS_PROFILE", f"profile identity repeated: {key!r}")
        if fact.scope.collection != fact.profile_id:
            raise _fail(
                "UNREPRESENTABLE_SCOPE",
                f"profile_id {fact.profile_id!r} differs from scope collection",
            )
        profiles[key] = fact
    return profiles


def _sha_set(values: Iterable[str], *, label: str) -> set[str]:
    result = list(values)
    if any(not isinstance(value, str) or _HEX64.fullmatch(value) is None for value in result):
        raise _fail("INVALID_CONTENT_SHA256", f"{label} contains a malformed SHA-256")
    if len(result) != len(set(result)):
        raise _fail("DUPLICATE_CONTENT", f"{label} repeats a content SHA-256")
    return set(result)


def _validated_matrix_partitions(
    proposal_matrix: Any,
    *,
    expected_content_sha256: set[str],
) -> tuple[_MatrixPartition, ...]:
    """Valide d'abord couverture/décisions, puis les scopes représentables."""
    if not isinstance(proposal_matrix, list) or not proposal_matrix:
        raise _fail("INVALID_PROPOSAL_MATRIX", "top-level value must be a non-empty list")

    scope_fields = set(ResourceScope.model_fields)
    seen_partition_ids: set[str] = set()
    seen_contents: set[str] = set()
    raw_partitions: list[
        tuple[
            str,
            tuple[str, ...],
            Mapping[str, Mapping[str, Any]],
            tuple[str, ...],
        ]
    ] = []
    unresolved: list[tuple[str, int]] = []

    for index, row in enumerate(proposal_matrix):
        if not isinstance(row, Mapping):
            raise _fail("INVALID_PROPOSAL_MATRIX", f"partition #{index} must be an object")
        partition_id = row.get("partition_id")
        partition_kind = row.get("partition_kind")
        content_count = row.get("content_count")
        contents = row.get("content_sha256")
        decision_required = row.get("profile_decision_required")
        dimensions = row.get("dimensions")
        evidence_sources = row.get("evidence_sources")
        if not isinstance(partition_id, str) or not partition_id:
            raise _fail("INVALID_PROPOSAL_MATRIX", f"partition #{index} has no partition_id")
        if partition_id in seen_partition_ids:
            raise _fail(
                "INVALID_PROPOSAL_MATRIX",
                f"partition_id {partition_id!r} is repeated",
            )
        seen_partition_ids.add(partition_id)
        if type(content_count) is not int or content_count <= 0:
            raise _fail(
                "INVALID_PROPOSAL_MATRIX",
                f"partition {partition_id!r} has invalid content_count",
            )
        if partition_kind != "EXACT_VERSIONED_RELEASE_PROFILE":
            if partition_kind == "PLACEMENT_ONLY_UNRESOLVED":
                unresolved.append((partition_id, content_count))
            else:
                raise _fail(
                    "INVALID_PARTITION_KIND",
                    f"partition {partition_id!r} has unsupported kind {partition_kind!r}",
                )
        if not isinstance(contents, list) or len(contents) != content_count:
            raise _fail(
                "INVALID_PROPOSAL_MATRIX",
                f"partition {partition_id!r} content_count does not match its list",
            )
        if any(
            not isinstance(content, str) or _HEX64.fullmatch(content) is None
            for content in contents
        ):
            raise _fail(
                "INVALID_PROPOSAL_MATRIX",
                f"partition {partition_id!r} contains a malformed SHA-256",
            )
        typed_contents = cast(list[str], contents)
        if len(typed_contents) != len(set(typed_contents)):
            raise _fail(
                "MATRIX_DUPLICATE_CONTENT",
                f"partition {partition_id!r} repeats a content",
            )
        overlap = seen_contents.intersection(typed_contents)
        if overlap:
            raise _fail(
                "MATRIX_DUPLICATE_CONTENT",
                f"contents occur in multiple partitions: {sorted(overlap)}",
            )
        seen_contents.update(typed_contents)
        if type(decision_required) is not bool:
            raise _fail(
                "INVALID_PROPOSAL_MATRIX",
                f"partition {partition_id!r} has no boolean decision flag",
            )
        if (
            not isinstance(evidence_sources, list)
            or not evidence_sources
            or any(not isinstance(source, str) or not source.strip() for source in evidence_sources)
        ):
            raise _fail(
                "INVALID_PROPOSAL_MATRIX",
                f"partition {partition_id!r} has invalid evidence_sources",
            )
        typed_evidence_sources = cast(list[str], evidence_sources)
        if len(typed_evidence_sources) != len(set(typed_evidence_sources)):
            raise _fail(
                "INVALID_PROPOSAL_MATRIX",
                f"partition {partition_id!r} repeats an evidence source",
            )
        if not isinstance(dimensions, Mapping) or set(dimensions) != scope_fields:
            raise _fail(
                "INVALID_PROPOSAL_MATRIX",
                f"partition {partition_id!r} must declare exactly {sorted(scope_fields)}",
            )

        typed_dimensions = cast(Mapping[str, Mapping[str, Any]], dimensions)
        all_grounded = True
        for name, dimension in typed_dimensions.items():
            if not isinstance(dimension, Mapping):
                raise _fail(
                    "INVALID_PROPOSAL_MATRIX",
                    f"partition {partition_id!r} dimension {name!r} is invalid",
                )
            grounded = dimension.get("grounded")
            if type(grounded) is not bool:
                raise _fail(
                    "INVALID_PROPOSAL_MATRIX",
                    f"partition {partition_id!r} dimension {name!r} has no boolean grounded flag",
                )
            all_grounded = all_grounded and grounded
        if decision_required or not all_grounded:
            if (partition_id, content_count) not in unresolved:
                unresolved.append((partition_id, content_count))
        raw_partitions.append(
            (
                partition_id,
                tuple(typed_contents),
                typed_dimensions,
                tuple(typed_evidence_sources),
            )
        )

    missing = sorted(expected_content_sha256 - seen_contents)
    extra = sorted(seen_contents - expected_content_sha256)
    if missing or extra:
        raise _fail(
            "MATRIX_CONTENT_MISMATCH",
            f"missing={missing}, extra={extra}",
        )
    if unresolved:
        raise _fail(
            "PROFILE_DECISION_REQUIRED",
            f"{len(unresolved)} partitions / {sum(count for _, count in unresolved)} "
            f"contents: {sorted(partition_id for partition_id, _ in unresolved)}",
        )

    result: list[_MatrixPartition] = []
    for partition_id, contents, dimensions, evidence_sources in raw_partitions:
        source_paths: set[str] = set()
        for name, dimension in dimensions.items():
            source = dimension.get("source_of_truth")
            if not isinstance(source, str) or not source.strip():
                raise _fail(
                    "INVALID_SOURCE_OF_TRUTH",
                    f"partition {partition_id!r} dimension {name!r} has no source",
                )
            try:
                source = _canonical_repo_path(source)
            except ReleaseScopePlacementProducerError as exc:
                raise _fail(
                    "INVALID_SOURCE_OF_TRUTH",
                    f"partition {partition_id!r} dimension {name!r}: {exc}",
                ) from exc
            if source not in evidence_sources:
                raise _fail(
                    "UNLISTED_SOURCE_OF_TRUTH",
                    f"partition {partition_id!r} dimension {name!r} source is unlisted",
                )
            source_paths.add(source)
        scope_document = {name: dimension.get("value") for name, dimension in dimensions.items()}
        try:
            scope = ResourceScope.model_validate(scope_document)
        except ValidationError as exc:
            raise _fail(
                "UNREPRESENTABLE_SCOPE",
                f"partition {partition_id!r} scope is invalid: {exc}",
            ) from exc
        result.append(
            _MatrixPartition(
                partition_id=partition_id,
                content_sha256=contents,
                scope=scope,
                source_paths=tuple(sorted(source_paths)),
                evidence_paths=tuple(sorted(evidence_sources)),
            )
        )
    return tuple(result)


def _compose_release_scope_placement(
    *,
    accepted_placements: Sequence[Mapping[str, Any]],
    release_registry: Mapping[str, Any],
    verified_profiles: Sequence[VerifiedProfileFactV1 | Mapping[str, Any]],
    profile_proposal_matrix: Any,
    profile_manifest_digest: str,
    expected_content_sha256: Iterable[str],
    profile_source_loader: Callable[[str], CollectionProfile],
    evidence_blob_loader: Callable[[str], bytes],
    profile_source_path_by_identity: Mapping[tuple[str, str], str],
) -> ReleaseScopePlacementV1:
    """Construit une projection totale et univoque sans lire d'autorité."""
    releases = _release_collections(release_registry)
    expected = _sha_set(expected_content_sha256, label="expected content set")
    matrix_partitions = _validated_matrix_partitions(
        profile_proposal_matrix,
        expected_content_sha256=expected,
    )
    for partition in matrix_partitions:
        for evidence_path in partition.evidence_paths:
            evidence_blob_loader(evidence_path)
    profiles = _profile_index(verified_profiles)
    entries_by_content: dict[str, ReleaseScopePlacementEntryV1] = {}
    identity_by_content: dict[str, tuple[str, str, str]] = {}

    for index, placement in enumerate(accepted_placements):
        if not isinstance(placement, Mapping):
            raise _fail("INVALID_PLACEMENT", f"placement #{index} must be an object")
        content_sha256 = placement.get("content_sha256")
        release_id = placement.get("release_id")
        collection = placement.get("collection")
        profile_version = placement.get("profile_version")
        if not isinstance(content_sha256, str) or _HEX64.fullmatch(content_sha256) is None:
            raise _fail("INVALID_CONTENT_SHA256", f"placement #{index} has invalid content")
        if not all(
            isinstance(value, str) and value for value in (release_id, collection, profile_version)
        ):
            raise _fail("INVALID_PLACEMENT", f"placement #{index} is incomplete")
        release_id = cast(str, release_id)
        collection = cast(str, collection)
        profile_version = cast(str, profile_version)
        identity = (release_id, collection, profile_version)
        previous = identity_by_content.get(content_sha256)
        if previous is not None:
            code = "DUPLICATE_CONTENT" if previous == identity else "AMBIGUOUS_PLACEMENT"
            raise _fail(code, f"content {content_sha256} has multiple placements")
        identity_by_content[content_sha256] = identity

        accepted_collections = releases.get(release_id)
        if accepted_collections is None:
            raise _fail("UNKNOWN_RELEASE", f"release_id {release_id!r} is not registered")
        if collection not in accepted_collections:
            raise _fail(
                "UNACCEPTED_COLLECTION",
                f"collection {collection!r} is not in release {release_id!r}",
            )
        profile = profiles.get((collection, profile_version))
        if profile is None:
            raise _fail(
                "UNKNOWN_PROFILE",
                f"profile {(collection, profile_version)!r} was not verified",
            )
        entries_by_content[content_sha256] = ReleaseScopePlacementEntryV1(
            content_sha256=content_sha256,
            profile_id=profile.profile_id,
            profile_version=profile.profile_version,
            profile_fingerprint=profile.profile_fingerprint,
            scope=profile.scope,
        )

    actual = set(entries_by_content)
    missing = sorted(expected - actual)
    if missing:
        raise _fail("MISSING_CONTENT", f"missing {len(missing)} contents: {missing}")
    extra = sorted(actual - expected)
    if extra:
        raise _fail("EXTRA_CONTENT", f"unexpected {len(extra)} contents: {extra}")

    registry_school_year = release_registry.get("school_year")
    if not isinstance(registry_school_year, str) or not registry_school_year:
        raise _fail("INVALID_RELEASE_REGISTRY", "release registry has no school_year")
    for partition in matrix_partitions:
        selected_identities = {identity_by_content[content] for content in partition.content_sha256}
        selected_profiles = {
            (collection, profile_version) for _, collection, profile_version in selected_identities
        }
        selected_releases = {release_id for release_id, _, _ in selected_identities}
        if len(selected_profiles) != 1 or len(selected_releases) != 1:
            raise _fail(
                "MATRIX_PROFILE_MISMATCH",
                f"partition {partition.partition_id!r} does not select one profile/release",
            )
        collection, profile_version = next(iter(selected_profiles))
        if partition.scope.collection != collection:
            raise _fail(
                "MATRIX_PROFILE_MISMATCH",
                f"partition {partition.partition_id!r} names collection "
                f"{partition.scope.collection!r}, placement selects {collection!r}",
            )
        selected_profile = profiles[(collection, profile_version)]
        expected_profile_source = profile_source_path_by_identity.get((collection, profile_version))
        if expected_profile_source is None:
            raise _fail(
                "MISSING_PROFILE_SOURCE",
                f"profile {(collection, profile_version)!r} has no governed source",
            )
        if partition.scope.school_year != registry_school_year:
            raise _fail(
                "MATRIX_RELEASE_MISMATCH",
                f"partition {partition.partition_id!r} school_year differs from registry",
            )
        if scope_digest(partition.scope) != scope_digest(selected_profile.scope):
            raise _fail(
                "MATRIX_SCOPE_MISMATCH",
                f"partition {partition.partition_id!r} differs from selected profile scope",
            )
        for source_path in partition.source_paths:
            if source_path != expected_profile_source:
                raise _fail(
                    "MATRIX_PROFILE_SOURCE_MISMATCH",
                    f"partition {partition.partition_id!r} source {source_path!r} "
                    f"differs from governed source {expected_profile_source!r}",
                )
            source_profile = profile_source_loader(source_path)
            if not source_profile.enabled:
                raise _fail(
                    "PROFILE_SOURCE_DISABLED",
                    f"partition {partition.partition_id!r} source {source_path!r} is disabled",
                )
            if (
                source_profile.scope.collection != collection
                or source_profile.profile_version != profile_version
                or scope_digest(source_profile.scope) != scope_digest(selected_profile.scope)
                or collection_profile_fingerprint(source_profile)
                != selected_profile.profile_fingerprint
            ):
                raise _fail(
                    "PROFILE_SOURCE_MISMATCH",
                    f"partition {partition.partition_id!r} source {source_path!r} "
                    "does not prove the selected profile fact",
                )
    try:
        return ReleaseScopePlacementV1.build(
            placements=tuple(entries_by_content.values()),
            profile_manifest_digest=profile_manifest_digest,
        )
    except Exception as exc:  # noqa: BLE001 - frontière du contrat partagé
        raise _fail("INVALID_PROJECTION", str(exc)) from exc


def _parse_profile_source(raw: bytes, *, path: str) -> CollectionProfile:
    try:
        document = strict_yaml_mapping(raw, source=path)
        profile = CollectionProfile.model_validate(document)
        require_canonical_profile_version(profile.profile_version, source=path)
        return profile
    except (CanonicalProfileVersionError, StrictYamlError, ValidationError) as exc:
        raise _fail("INVALID_PROFILE_SOURCE", f"{path}: {exc}") from exc


def produce_release_scope_placement_from_git(
    *,
    repository_root: Path,
    source_tree_sha: str,
    profile_proposal_matrix_path: str,
    accepted_placements_path: str,
    release_registry_path: str,
    expected_contents_path: str,
    verified_profiles_path: str,
    profile_manifest_path: str,
) -> ProducedReleaseScopePlacement:
    """Produit depuis les seuls blobs d'un tree Git explicitement nommé."""
    reader = _GitTreeReader(
        repository_root=repository_root,
        source_tree_sha=source_tree_sha,
    )
    matrix = _parse_strict_json(
        reader.read_blob(profile_proposal_matrix_path),
        path=profile_proposal_matrix_path,
    )
    placements = _parse_strict_json(
        reader.read_blob(accepted_placements_path), path=accepted_placements_path
    )
    registry = _parse_strict_json(
        reader.read_blob(release_registry_path), path=release_registry_path
    )
    expected = _parse_expected_contents(
        reader.read_blob(expected_contents_path), path=expected_contents_path
    )
    profiles_document = _parse_strict_json(
        reader.read_blob(verified_profiles_path), path=verified_profiles_path
    )
    profile_manifest_raw = reader.read_blob(profile_manifest_path)
    if not isinstance(matrix, list) or not isinstance(placements, list):
        raise _fail("INVALID_INPUT", "matrix and placements must be JSON lists")
    if not isinstance(registry, Mapping):
        raise _fail("INVALID_INPUT", "release registry must be a JSON object")
    if not isinstance(profiles_document, Mapping) or set(profiles_document) != {
        "profile_manifest_digest",
        "profiles",
    }:
        raise _fail("INVALID_INPUT", "verified profiles document has invalid fields")
    profile_manifest_digest = profiles_document.get("profile_manifest_digest")
    profiles = profiles_document.get("profiles")
    if not isinstance(profile_manifest_digest, str) or not isinstance(profiles, list):
        raise _fail("INVALID_INPUT", "verified profiles document is incomplete")
    profile_fingerprints: dict[tuple[str, str], str] = {}
    profile_source_paths: dict[tuple[str, str], str] = {}
    source_identities: dict[str, tuple[str, str]] = {}
    profile_facts: list[VerifiedProfileFactV1] = []
    source_cache: dict[str, CollectionProfile] = {}
    fact_fields = set(VerifiedProfileFactV1.model_fields)
    for index, record in enumerate(profiles):
        if not isinstance(record, Mapping):
            raise _fail("INVALID_INPUT", f"verified profile fact #{index} is not an object")
        source_path = record.get("source_path")
        if not isinstance(source_path, str) or not source_path.strip():
            raise _fail(
                "MISSING_PROFILE_SOURCE",
                f"verified profile fact #{index} has no source_path",
            )
        if set(record) != fact_fields | {"source_path"}:
            raise _fail(
                "INVALID_INPUT",
                f"verified profile fact #{index} has invalid fields",
            )
        try:
            source_path = _canonical_repo_path(source_path)
            fact = VerifiedProfileFactV1.model_validate(
                {field: record[field] for field in fact_fields}
            )
        except ValidationError as exc:
            raise _fail(
                "INVALID_INPUT", f"verified profile fact #{index} is invalid: {exc}"
            ) from exc
        identity = (fact.profile_id, fact.profile_version)
        if identity in profile_fingerprints:
            raise _fail("AMBIGUOUS_PROFILE", f"profile identity repeated: {identity!r}")
        previous_identity = source_identities.get(source_path)
        if previous_identity is not None:
            raise _fail(
                "DUPLICATE_PROFILE_SOURCE",
                f"source {source_path!r} proves both {previous_identity!r} and {identity!r}",
            )
        source_profile = _parse_profile_source(reader.read_blob(source_path), path=source_path)
        if not source_profile.enabled:
            raise _fail(
                "PROFILE_SOURCE_DISABLED",
                f"profile {identity!r} source {source_path!r} is disabled",
            )
        if (
            source_profile.scope.collection != fact.profile_id
            or source_profile.profile_version != fact.profile_version
            or scope_digest(source_profile.scope) != scope_digest(fact.scope)
            or collection_profile_fingerprint(source_profile) != fact.profile_fingerprint
        ):
            raise _fail(
                "PROFILE_SOURCE_MISMATCH",
                f"source {source_path!r} does not prove profile fact {identity!r}",
            )
        profile_fingerprints[identity] = fact.profile_fingerprint
        profile_source_paths[identity] = source_path
        source_identities[source_path] = identity
        source_cache[source_path] = source_profile
        profile_facts.append(fact)
    try:
        verified_manifest = validate_production_profile_manifest(
            profile_manifest_raw,
            profile_fingerprints=profile_fingerprints,
            source=profile_manifest_path,
        )
    except ProductionProfileManifestError as exc:
        raise _fail("INVALID_PROFILE_MANIFEST", str(exc)) from exc
    actual_manifest_digest = verified_manifest.manifest_fingerprint
    if profile_manifest_digest != actual_manifest_digest:
        raise _fail(
            "PROFILE_MANIFEST_MISMATCH",
            "verified profile facts do not bind the exact profile manifest blob",
        )

    def load_profile_source(path: str) -> CollectionProfile:
        if path not in source_cache:
            source_cache[path] = _parse_profile_source(reader.read_blob(path), path=path)
        return source_cache[path]

    placement = _compose_release_scope_placement(
        accepted_placements=placements,
        release_registry=registry,
        verified_profiles=profile_facts,
        profile_proposal_matrix=matrix,
        profile_manifest_digest=profile_manifest_digest,
        expected_content_sha256=expected,
        profile_source_loader=load_profile_source,
        evidence_blob_loader=reader.read_blob,
        profile_source_path_by_identity=profile_source_paths,
    )
    return ProducedReleaseScopePlacement(
        placement=placement,
        provenance=ReleaseScopePlacementProvenance(
            source_tree_sha=source_tree_sha,
            input_blob_sha256=dict(sorted(reader.input_blob_sha256.items())),
            input_git_entries=dict(sorted(reader.input_git_entries.items())),
        ),
    )


__all__ = [
    "ProducedReleaseScopePlacement",
    "ReleaseScopePlacementProducerError",
    "ReleaseScopePlacementProvenance",
    "produce_release_scope_placement_from_git",
]
