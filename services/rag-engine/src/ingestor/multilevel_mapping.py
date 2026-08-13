"""Mappings externes multi-niveaux fermés et liés par digest."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml
from nexus_contracts.document import Niveau, TypeDoc

_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")


class MultilevelMappingError(RuntimeError):
    """Une table de mapping est absente, a dérivé ou ne résout pas un fait."""


@dataclass(frozen=True)
class MultilevelMappedFacts:
    niveau: Niveau
    matiere: str
    type_doc: TypeDoc


@dataclass(frozen=True)
class ClosedMultilevelMapping:
    levels_sha256: str
    subjects_sha256: str
    document_types_sha256: str
    levels: Mapping[str, Niveau]
    subjects: Mapping[str, str]
    document_types: Mapping[str, TypeDoc]

    def resolve(
        self,
        *,
        external_level: str,
        external_subject: str,
        external_document_type: str,
    ) -> MultilevelMappedFacts:
        try:
            niveau = self.levels[external_level]
        except KeyError as exc:
            raise MultilevelMappingError(
                f"external level {external_level!r} is not governed"
            ) from exc
        try:
            matiere = self.subjects[external_subject]
        except KeyError as exc:
            raise MultilevelMappingError(
                f"external subject {external_subject!r} is not governed"
            ) from exc
        try:
            type_doc = self.document_types[external_document_type]
        except KeyError as exc:
            raise MultilevelMappingError(
                f"external document type {external_document_type!r} is not governed"
            ) from exc
        return MultilevelMappedFacts(
            niveau=niveau,
            matiere=matiere,
            type_doc=type_doc,
        )


def _load_table(
    path: Path,
    *,
    expected_sha256: str,
    expected_kind: str,
    field: str,
) -> tuple[str, Mapping[str, object]]:
    if _SHA256.fullmatch(expected_sha256) is None:
        raise MultilevelMappingError(f"expected {field} SHA is invalid")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise MultilevelMappingError(f"{field} mapping cannot be read") from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise MultilevelMappingError(f"{field} mapping digest differs")
    try:
        document = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise MultilevelMappingError(f"{field} mapping YAML is invalid") from exc
    if not isinstance(document, Mapping) or set(document) != {"mapping_kind", field}:
        raise MultilevelMappingError(f"{field} mapping fields are not exact")
    if document.get("mapping_kind") != expected_kind:
        raise MultilevelMappingError(f"{field} mapping kind is invalid")
    table = document.get(field)
    if not isinstance(table, Mapping) or not table:
        raise MultilevelMappingError(f"{field} mapping is empty")
    if any(
        not isinstance(key, str)
        or not key
        or not isinstance(value, str)
        or not value
        for key, value in table.items()
    ):
        raise MultilevelMappingError(f"{field} mapping entries are invalid")
    return actual, table


def load_multilevel_mapping(
    *,
    levels_path: Path,
    expected_levels_sha256: str,
    subjects_path: Path,
    expected_subjects_sha256: str,
    document_types_path: Path,
    expected_document_types_sha256: str,
) -> ClosedMultilevelMapping:
    levels_sha, raw_levels = _load_table(
        levels_path,
        expected_sha256=expected_levels_sha256,
        expected_kind="EDUSCOL_MULTILEVEL_LEVELS_V1",
        field="external_levels",
    )
    subjects_sha, raw_subjects = _load_table(
        subjects_path,
        expected_sha256=expected_subjects_sha256,
        expected_kind="EDUSCOL_MULTILEVEL_SUBJECTS_V1",
        field="external_subjects",
    )
    document_types_sha, raw_document_types = _load_table(
        document_types_path,
        expected_sha256=expected_document_types_sha256,
        expected_kind="EDUSCOL_MULTILEVEL_DOCUMENT_TYPES_V1",
        field="document_types",
    )
    try:
        levels = {str(key): Niveau(str(value)) for key, value in raw_levels.items()}
        document_types = {
            str(key): TypeDoc(str(value)) for key, value in raw_document_types.items()
        }
    except ValueError as exc:
        raise MultilevelMappingError("mapping targets are not Nexus enum values") from exc
    return ClosedMultilevelMapping(
        levels_sha256=levels_sha,
        subjects_sha256=subjects_sha,
        document_types_sha256=document_types_sha,
        levels=levels,
        subjects={str(key): str(value) for key, value in raw_subjects.items()},
        document_types=document_types,
    )


__all__ = [
    "ClosedMultilevelMapping",
    "MultilevelMappedFacts",
    "MultilevelMappingError",
    "load_multilevel_mapping",
]
