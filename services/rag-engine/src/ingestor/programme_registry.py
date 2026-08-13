"""Registre borné des index de programmes canoniques Nexus."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")


class ProgrammeRegistryError(RuntimeError):
    """Le registre ou l'un de ses index n'est pas exact."""


@dataclass(frozen=True)
class ProgrammeIndexRegistry:
    sha256: str
    school_year: str
    index_sha256_by_path: Mapping[str, str]
    taxonomy_sha256_by_collection: Mapping[str, str]
    programme_by_collection: Mapping[str, str]

    def programme_for(self, collection: str) -> str:
        try:
            return self.programme_by_collection[collection]
        except KeyError as exc:
            raise ProgrammeRegistryError(
                f"collection {collection!r} has no canonical programme index"
            ) from exc


def _require_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ProgrammeRegistryError(f"{label} must be a lowercase SHA-256")
    return value


def _read_digest_bound_yaml(
    path: Path, *, expected_sha256: str, label: str
) -> tuple[str, Mapping[str, object]]:
    expected = _require_sha256(expected_sha256, label=f"expected {label} digest")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ProgrammeRegistryError(f"{label} cannot be read") from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ProgrammeRegistryError(f"{label} digest differs")
    try:
        document = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ProgrammeRegistryError(f"{label} YAML is invalid") from exc
    if not isinstance(document, Mapping):
        raise ProgrammeRegistryError(f"{label} must be a mapping")
    return actual, document


def _resolve_bounded(repository_root: Path, relative_path: object) -> tuple[str, Path]:
    if not isinstance(relative_path, str) or not relative_path:
        raise ProgrammeRegistryError("programme index path is invalid")
    raw = Path(relative_path)
    if raw.is_absolute() or ".." in raw.parts:
        raise ProgrammeRegistryError("programme index path escapes the repository")
    root = repository_root.resolve()
    resolved = (root / raw).resolve()
    if not resolved.is_relative_to(root):
        raise ProgrammeRegistryError("programme index path escapes the repository")
    return raw.as_posix(), resolved


def load_programme_index_registry(
    *,
    registry_path: Path,
    expected_registry_sha256: str,
    repository_root: Path,
) -> ProgrammeIndexRegistry:
    registry_sha, document = _read_digest_bound_yaml(
        registry_path,
        expected_sha256=expected_registry_sha256,
        label="programme index registry",
    )
    if set(document) != {"registry_kind", "school_year", "indexes", "taxonomies"}:
        raise ProgrammeRegistryError("programme index registry fields are not exact")
    if document.get("registry_kind") != "NEXUS_PROGRAMME_INDEX_REGISTRY_V3":
        raise ProgrammeRegistryError("programme index registry kind is invalid")
    school_year = document.get("school_year")
    if (
        not isinstance(school_year, str)
        or re.fullmatch(r"[0-9]{4}-[0-9]{4}", school_year) is None
    ):
        raise ProgrammeRegistryError("programme index registry school year is invalid")
    raw_indexes = document.get("indexes")
    if not isinstance(raw_indexes, list) or not raw_indexes:
        raise ProgrammeRegistryError("programme index registry is empty")

    index_digests: dict[str, str] = {}
    programmes: dict[str, str] = {}
    taxonomy_path_by_collection: dict[str, str] = {}
    for raw_entry in raw_indexes:
        if not isinstance(raw_entry, Mapping) or set(raw_entry) != {"path", "sha256"}:
            raise ProgrammeRegistryError("programme index registry entry is not exact")
        relative, index_path = _resolve_bounded(repository_root, raw_entry.get("path"))
        if relative in index_digests:
            raise ProgrammeRegistryError("programme index path is duplicated")
        expected_index_sha = _require_sha256(
            raw_entry.get("sha256"), label="programme index digest"
        )
        index_sha, index = _read_digest_bound_yaml(
            index_path,
            expected_sha256=expected_index_sha,
            label=f"programme index {relative}",
        )
        if not isinstance(index.get("niveau"), str) or not isinstance(
            index.get("voie"), str
        ):
            raise ProgrammeRegistryError("programme index scope is incomplete")
        if index.get("school_year", school_year) != school_year:
            raise ProgrammeRegistryError("programme index school year differs")
        fiches = index.get("fiches")
        if not isinstance(fiches, list) or not fiches:
            raise ProgrammeRegistryError("programme index has no entries")
        for fiche in fiches:
            if not isinstance(fiche, Mapping):
                raise ProgrammeRegistryError("programme index entry is malformed")
            collection = fiche.get("collection_cible")
            programme = fiche.get("programme_version")
            filename = fiche.get("fichier")
            matiere = fiche.get("matiere")
            statut = fiche.get("statut_enseignement")
            taxonomy_file = fiche.get("taxonomy_file")
            if (
                not isinstance(collection, str)
                or not collection
                or not isinstance(programme, str)
                or not programme
                or not isinstance(filename, str)
                or not filename
                or not isinstance(matiere, str)
                or not matiere
                or not isinstance(statut, str)
                or not statut
                or not isinstance(taxonomy_file, str)
                or not taxonomy_file
            ):
                raise ProgrammeRegistryError("programme index entry is incomplete")
            if collection in programmes:
                raise ProgrammeRegistryError(
                    f"canonical programme collection {collection!r} is duplicated"
                )
            if not (index_path.parent / filename).is_file():
                raise ProgrammeRegistryError(
                    f"programme index fiche {filename!r} is absent"
                )
            taxonomy_path = repository_root / "services" / "rag-pedago" / "taxonomy"
            if Path(taxonomy_file).is_absolute() or ".." in Path(taxonomy_file).parts:
                raise ProgrammeRegistryError("programme taxonomy path is invalid")
            if not (taxonomy_path / taxonomy_file).is_file():
                raise ProgrammeRegistryError(
                    f"programme taxonomy {taxonomy_file!r} is absent"
                )
            programmes[collection] = programme
            taxonomy_path_by_collection[collection] = (
                Path("services")
                / "rag-pedago"
                / "taxonomy"
                / taxonomy_file
            ).as_posix()
        index_digests[relative] = index_sha

    raw_taxonomies = document.get("taxonomies")
    if not isinstance(raw_taxonomies, list) or not raw_taxonomies:
        raise ProgrammeRegistryError("programme taxonomy registry is empty")
    taxonomy_digests: dict[str, str] = {}
    taxonomy_fields = {
        "collection",
        "path",
        "sha256",
        "niveau",
        "voie",
        "matiere",
        "statut_enseignement",
        "programme_version",
    }
    for raw_entry in raw_taxonomies:
        if not isinstance(raw_entry, Mapping) or set(raw_entry) != taxonomy_fields:
            raise ProgrammeRegistryError("programme taxonomy entry is not exact")
        collection = raw_entry.get("collection")
        if not isinstance(collection, str) or not collection:
            raise ProgrammeRegistryError("programme taxonomy collection is invalid")
        if collection in taxonomy_digests:
            raise ProgrammeRegistryError("programme taxonomy collection is duplicated")
        relative, taxonomy_path = _resolve_bounded(
            repository_root, raw_entry.get("path")
        )
        if taxonomy_path_by_collection.get(collection) != relative:
            raise ProgrammeRegistryError(
                f"programme taxonomy path differs for {collection!r}"
            )
        taxonomy_sha, taxonomy = _read_digest_bound_yaml(
            taxonomy_path,
            expected_sha256=_require_sha256(
                raw_entry.get("sha256"), label="programme taxonomy digest"
            ),
            label=f"programme taxonomy {collection}",
        )
        for field in (
            "niveau",
            "voie",
            "matiere",
            "statut_enseignement",
            "programme_version",
        ):
            expected = raw_entry.get(field)
            if not isinstance(expected, str) or not expected:
                raise ProgrammeRegistryError(
                    f"programme taxonomy {field} is invalid"
                )
            if taxonomy.get(field) != expected:
                raise ProgrammeRegistryError(
                    f"programme taxonomy {field} differs for {collection!r}"
                )
        if programmes.get(collection) != raw_entry.get("programme_version"):
            raise ProgrammeRegistryError(
                f"canonical programme differs for {collection!r}"
            )
        taxonomy_digests[collection] = taxonomy_sha
    return ProgrammeIndexRegistry(
        sha256=registry_sha,
        school_year=school_year,
        index_sha256_by_path=index_digests,
        taxonomy_sha256_by_collection=taxonomy_digests,
        programme_by_collection=programmes,
    )


__all__ = [
    "ProgrammeIndexRegistry",
    "ProgrammeRegistryError",
    "load_programme_index_registry",
]
