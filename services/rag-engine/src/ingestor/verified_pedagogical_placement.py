"""Résolution Wave 0 liée au catalogue, à la currentness et au profil exacts.

Le catalogue conserve sa classification physique candidate. Ce module ne la
réécrit pas : il superpose une décision de currentness artifact-bound puis
vérifie un unique placement Nexus avant de rendre un fait consommable par les
deux workers.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import urlparse
from uuid import UUID

import yaml
from nexus_contracts.document import Niveau, TypeDoc, Voie
from nexus_contracts.ingestion import ResourceScope

from .governed_publisher_v2 import EligiblePlacement
from .ingestion_profiles.registry import (
    ProfileRegistry,
    profile_fingerprint,
    select_profile,
)

CURRENTNESS_EVIDENCE_KIND = "WAVE0_ARTIFACT_CURRENTNESS_V1"
SEALED_CATALOG_KIND = "REAL_SEALED_CORPUS"
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_SCHOOL_YEAR = re.compile(r"\A[0-9]{4}-[0-9]{4}\Z")
_WAVE0_CURRENTNESS_SCOPE = {
    "49ccdca4d97ba4cf25875dfc731474e84d0332985c15396d3abfb9107f5f545a": (
        "01_EDUSCOL_OFFICIEL/COLLEGE/3E/MATHEMATIQUES/02_REPERES_ATTENDUS/2019/"
        "attendus-de-fin-d-annee-en-mathematiques-en-3e-pdf-1-26-mo--49ccdca4d9.pdf",
        "3e",
        "mathematiques",
    ),
    "c8662b03ca8a7f08bedad5081bafc7da8d2cc8a31b07fa967421fb15304d76bf": (
        "01_EDUSCOL_OFFICIEL/COLLEGE/3E/FRANCAIS/02_REPERES_ATTENDUS/2019/"
        "attendus-de-fin-d-annee-en-francais-en-3e-pdf-971-01-ko--c8662b03ca.pdf",
        "3e",
        "francais",
    ),
}


class PlacementResolutionError(RuntimeError):
    """Une preuve manque, dérive ou désigne un placement ambigu."""


@dataclass(frozen=True)
class _CurrentnessArtifact:
    content_sha256: str
    exact_path: str
    external_level: str
    subject: str
    effective_currentness: str
    current_for_school_year: str


@dataclass(frozen=True)
class _NexusMapping:
    external_level: str
    external_scope: str
    external_subject: str
    external_document_type: str
    nexus_collection: str
    nexus_niveau: Niveau
    nexus_voie: Voie
    nexus_matiere: str
    nexus_statut_enseignement: str
    type_doc: TypeDoc


_MAPPINGS = (
    _NexusMapping(
        external_level="3e",
        external_scope="college/cycle-4/francais",
        external_subject="francais",
        external_document_type="reperes-attendus",
        nexus_collection="rag_nexus_francais_troisieme_tc",
        nexus_niveau=Niveau.troisieme,
        nexus_voie=Voie.college,
        nexus_matiere="francais",
        nexus_statut_enseignement="tronc_commun",
        type_doc=TypeDoc.ressource_officielle,
    ),
    _NexusMapping(
        external_level="3e",
        external_scope="college/cycle-4/mathematiques",
        external_subject="mathematiques",
        external_document_type="reperes-attendus",
        nexus_collection="rag_nexus_maths_troisieme_tc",
        nexus_niveau=Niveau.troisieme,
        nexus_voie=Voie.college,
        nexus_matiere="maths",
        nexus_statut_enseignement="tronc_commun",
        type_doc=TypeDoc.ressource_officielle,
    ),
)


@dataclass(frozen=True)
class VerifiedPedagogicalPlacement:
    content_sha256: str
    source_path: str
    source_url: str
    source_placement_id: str
    external_level: str
    external_subject: str
    external_scope: str
    external_document_type: str
    effective_currentness: str
    nexus_collection: str
    nexus_niveau: Niveau
    nexus_voie: Voie
    nexus_matiere: str
    nexus_statut_enseignement: str
    nexus_programme_version: str
    nexus_domain: str
    nexus_scope: ResourceScope
    type_doc: TypeDoc
    profile_version: str
    profile_fingerprint: str
    corpus_manifest_sha256: str
    catalog_sha256: str
    placement_catalog_sha256: str
    currentness_evidence_sha256: str
    programme_index_sha256: str
    niveau_conformity: bool
    voie_conformity: bool
    matiere_conformity: bool
    programme_conformity: bool


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_sha(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PlacementResolutionError(f"{label} must be a lowercase 64-hex SHA")
    return value


def _require_file_digest(path: Path, expected: str, *, label: str) -> str:
    _require_sha(expected, label=f"expected {label} SHA")
    actual = _file_sha256(path)
    if actual != expected:
        raise PlacementResolutionError(
            f"{label} hashes to {actual}, not expected digest {expected}"
        )
    return actual


def _mapping_for(placement: Mapping[str, object], collection: str) -> _NexusMapping:
    matching = [
        mapping
        for mapping in _MAPPINGS
        if mapping.nexus_collection == collection
        and placement.get("level") == mapping.external_level
        and placement.get("scope") == mapping.external_scope
        and placement.get("subject") == mapping.external_subject
        and placement.get("document_type") == mapping.external_document_type
    ]
    if len(matching) != 1:
        raise PlacementResolutionError(
            "catalog placement has no unique governed external-to-Nexus mapping"
        )
    return matching[0]


def _load_currentness(
    path: Path,
    *,
    expected_sha256: str,
    expected_manifest_sha256: str,
) -> tuple[str, str, dict[str, _CurrentnessArtifact]]:
    evidence_sha = _require_file_digest(
        path, expected_sha256, label="currentness evidence"
    )
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise PlacementResolutionError("currentness evidence cannot be read") from exc
    if not isinstance(document, Mapping):
        raise PlacementResolutionError("currentness evidence must be a mapping")
    if document.get("evidence_kind") != CURRENTNESS_EVIDENCE_KIND:
        raise PlacementResolutionError("currentness evidence kind is invalid")
    school_year = document.get("school_year")
    if not isinstance(school_year, str) or _SCHOOL_YEAR.fullmatch(school_year) is None:
        raise PlacementResolutionError("currentness evidence school year is invalid")
    if document.get("corpus_manifest_sha256") != expected_manifest_sha256:
        raise PlacementResolutionError("currentness evidence manifest differs")
    raw_artifacts = document.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise PlacementResolutionError("currentness evidence artifacts are absent")

    artifacts: dict[str, _CurrentnessArtifact] = {}
    required = {
        "content_sha256",
        "exact_path",
        "external_level",
        "subject",
        "effective_currentness",
        "current_for_school_year",
    }
    for raw in raw_artifacts:
        if not isinstance(raw, Mapping) or not required <= set(raw):
            raise PlacementResolutionError("currentness artifact fields are incomplete")
        sha = _require_sha(raw.get("content_sha256"), label="currentness artifact SHA")
        if sha in artifacts:
            raise PlacementResolutionError(f"content {sha} appears twice in currentness evidence")
        exact_path = raw.get("exact_path")
        if not isinstance(exact_path, str) or not exact_path.startswith(
            "01_EDUSCOL_OFFICIEL/"
        ):
            raise PlacementResolutionError("currentness artifact path is invalid")
        if raw.get("effective_currentness") != "actuel":
            raise PlacementResolutionError("currentness must be 'actuel' on the positive path")
        if raw.get("current_for_school_year") != school_year:
            raise PlacementResolutionError("artifact currentness school year differs")
        level = raw.get("external_level")
        subject = raw.get("subject")
        if not isinstance(level, str) or not level:
            raise PlacementResolutionError("currentness artifact level is invalid")
        if not isinstance(subject, str) or not subject:
            raise PlacementResolutionError("currentness artifact subject is invalid")
        artifacts[sha] = _CurrentnessArtifact(
            content_sha256=sha,
            exact_path=exact_path,
            external_level=level,
            subject=subject,
            effective_currentness="actuel",
            current_for_school_year=school_year,
        )
    if set(artifacts) != set(_WAVE0_CURRENTNESS_SCOPE):
        raise PlacementResolutionError(
            "currentness evidence differs from the exact two-artifact scope"
        )
    for sha, (exact_path, level, subject) in _WAVE0_CURRENTNESS_SCOPE.items():
        artifact = artifacts[sha]
        if (
            artifact.exact_path != exact_path
            or artifact.external_level != level
            or artifact.subject != subject
        ):
            raise PlacementResolutionError(
                "currentness evidence differs from the exact two-artifact scope"
            )
    return evidence_sha, school_year, artifacts


def _load_programme_index(
    path: Path,
    *,
    expected_sha256: str,
) -> tuple[str, dict[str, str]]:
    index_sha = _require_file_digest(
        path, expected_sha256, label="canonical programme index"
    )
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise PlacementResolutionError("canonical programme index cannot be read") from exc
    if not isinstance(document, Mapping):
        raise PlacementResolutionError("canonical programme index must be a mapping")
    if document.get("niveau") != Niveau.troisieme.value or document.get("voie") != "college":
        raise PlacementResolutionError("canonical programme index scope is invalid")
    raw_fiches = document.get("fiches")
    if not isinstance(raw_fiches, list) or not raw_fiches:
        raise PlacementResolutionError("canonical programme index has no entries")
    by_collection: dict[str, str] = {}
    for raw in raw_fiches:
        if not isinstance(raw, Mapping):
            raise PlacementResolutionError("canonical programme entry is malformed")
        collection = raw.get("collection_cible")
        programme = raw.get("programme_version")
        if (
            not isinstance(collection, str)
            or not collection
            or not isinstance(programme, str)
            or not programme
        ):
            raise PlacementResolutionError("canonical programme entry is incomplete")
        if collection in by_collection:
            raise PlacementResolutionError("canonical programme collection is duplicated")
        by_collection[collection] = programme
    return index_sha, by_collection


@dataclass(frozen=True)
class VerifiedPedagogicalPlacementResolver:
    catalog_sha256: str
    corpus_manifest_sha256: str
    placement_catalog_sha256: str
    currentness_evidence_sha256: str
    currentness_school_year: str
    programme_index_sha256: str
    _artifacts: Mapping[str, Mapping[str, object]]
    _currentness: Mapping[str, _CurrentnessArtifact]
    _profiles: ProfileRegistry
    _collection_config: Mapping[str, object]
    _canonical_programme_by_collection: Mapping[str, str]

    @classmethod
    def load(
        cls,
        *,
        catalog_path: Path,
        expected_catalog_sha256: str,
        currentness_evidence_path: Path,
        expected_currentness_evidence_sha256: str,
        expected_manifest_sha256: str,
        profile_registry: ProfileRegistry,
        collection_config: Mapping[str, object],
        programme_index_path: Path,
        expected_programme_index_sha256: str,
    ) -> VerifiedPedagogicalPlacementResolver:
        manifest = _require_sha(expected_manifest_sha256, label="expected manifest SHA")
        catalog_sha = _require_file_digest(
            catalog_path, expected_catalog_sha256, label="sealed catalog"
        )
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PlacementResolutionError("sealed catalog cannot be read") from exc
        if not isinstance(catalog, Mapping):
            raise PlacementResolutionError("sealed catalog must be a mapping")
        if catalog.get("catalog_kind") != SEALED_CATALOG_KIND:
            raise PlacementResolutionError("sealed catalog kind is invalid")
        if catalog.get("verification_passed") is not True:
            raise PlacementResolutionError("sealed catalog is not verified")
        if catalog.get("manifest_sha256") != manifest:
            raise PlacementResolutionError("sealed catalog manifest differs")
        placement_catalog_sha = _require_sha(
            catalog.get("placement_catalog_sha256"), label="placement catalog SHA"
        )
        artifacts = catalog.get("artifacts")
        if not isinstance(artifacts, Mapping):
            raise PlacementResolutionError("sealed catalog artifacts are absent")
        evidence_sha, school_year, currentness = _load_currentness(
            currentness_evidence_path,
            expected_sha256=expected_currentness_evidence_sha256,
            expected_manifest_sha256=manifest,
        )
        programme_index_sha, canonical_programmes = _load_programme_index(
            programme_index_path,
            expected_sha256=expected_programme_index_sha256,
        )
        return cls(
            catalog_sha256=catalog_sha,
            corpus_manifest_sha256=manifest,
            placement_catalog_sha256=placement_catalog_sha,
            currentness_evidence_sha256=evidence_sha,
            currentness_school_year=school_year,
            programme_index_sha256=programme_index_sha,
            _artifacts=cast(Mapping[str, Mapping[str, object]], artifacts),
            _currentness=currentness,
            _profiles=dict(profile_registry),
            _collection_config=dict(collection_config),
            _canonical_programme_by_collection=canonical_programmes,
        )

    def resolve(
        self,
        *,
        content_sha256: str,
        collection: str,
        profile_version: str,
        school_year: str,
        claimed_source_path: str | None = None,
        claimed_source_url: str | None = None,
        claimed_type_doc: str | None = None,
    ) -> VerifiedPedagogicalPlacement:
        sha = _require_sha(content_sha256, label="content SHA")
        currentness = self._currentness.get(sha)
        if currentness is None:
            raise PlacementResolutionError(f"content {sha} has no currentness evidence")
        if school_year != self.currentness_school_year:
            raise PlacementResolutionError("requested school year differs from currentness evidence")

        artifact = self._artifacts.get(sha)
        if not isinstance(artifact, Mapping) or artifact.get("sha256") != sha:
            raise PlacementResolutionError("content is absent from the sealed catalog")
        physical_objects = artifact.get("physical_objects")
        placements = artifact.get("pedagogical_placements")
        if not isinstance(physical_objects, list) or len(physical_objects) != 1:
            raise PlacementResolutionError("artifact must have exactly one physical object")
        if not isinstance(placements, list) or len(placements) != 1:
            raise PlacementResolutionError("artifact must have exactly one pedagogical placement")
        if artifact.get("physical_object_count") != 1:
            raise PlacementResolutionError("artifact physical object count differs")
        if artifact.get("pedagogical_placement_count") != 1:
            raise PlacementResolutionError("artifact placement count differs")
        physical = physical_objects[0]
        placement = placements[0]
        if not isinstance(physical, Mapping) or not isinstance(placement, Mapping):
            raise PlacementResolutionError("artifact placement records are malformed")
        if physical.get("content_sha256") != sha or placement.get("content_sha256") != sha:
            raise PlacementResolutionError("catalog content SHA differs")
        source_path = physical.get("path")
        if not isinstance(source_path, str) or source_path != currentness.exact_path:
            raise PlacementResolutionError("currentness path differs from sealed catalog path")
        if claimed_source_path is not None and claimed_source_path != source_path:
            raise PlacementResolutionError("claimed source path differs from sealed catalog")
        if placement.get("level") != currentness.external_level:
            raise PlacementResolutionError("currentness level differs from catalog placement")
        if placement.get("subject") != currentness.subject:
            raise PlacementResolutionError("currentness subject differs from catalog placement")

        mapping = _mapping_for(placement, collection)
        profile = select_profile(
            self._profiles, collection=collection, profile_version=profile_version
        )
        source_url = placement.get("source_url")
        if not isinstance(source_url, str) or not source_url:
            raise PlacementResolutionError("catalog placement source URL is absent")
        if claimed_source_url is not None and claimed_source_url != source_url:
            raise PlacementResolutionError("claimed source URL differs from sealed catalog")
        if claimed_type_doc is not None and claimed_type_doc != mapping.type_doc.value:
            raise PlacementResolutionError("claimed document type differs from governed mapping")
        if urlparse(source_url).hostname not in profile.allowed_domains:
            raise PlacementResolutionError("catalog source URL is outside profile domains")
        if (
            profile.scope.collection != mapping.nexus_collection
            or profile.scope.niveau is not mapping.nexus_niveau
            or profile.scope.voie is not mapping.nexus_voie
            or profile.scope.matiere != mapping.nexus_matiere
            or profile.scope.school_year != school_year
        ):
            raise PlacementResolutionError("profile scope differs from governed placement")
        if not str(profile.scope.programme_version).strip():
            raise PlacementResolutionError("profile programme version is absent")
        canonical_programme = self._canonical_programme_by_collection.get(collection)
        if canonical_programme != str(profile.scope.programme_version):
            raise PlacementResolutionError(
                "profile differs from the canonical programme version"
            )

        raw_collections = self._collection_config.get("collections")
        collection_entry = (
            raw_collections.get(collection)
            if isinstance(raw_collections, Mapping)
            else None
        )
        if not isinstance(collection_entry, Mapping):
            raise PlacementResolutionError("Nexus collection is not declared")
        nexus_domain = collection_entry.get("domain")
        if not isinstance(nexus_domain, str) or not nexus_domain.strip():
            raise PlacementResolutionError("declared collection domain is absent")
        catalogue_voie = collection_entry.get("voie")
        if (
            collection_entry.get("niveau") != mapping.nexus_niveau.value
            or collection_entry.get("matiere") != mapping.nexus_matiere
            or collection_entry.get("statut") != mapping.nexus_statut_enseignement
            or catalogue_voie != mapping.nexus_voie.value
        ):
            raise PlacementResolutionError("declared collection differs from governed placement")

        source_placement_id = placement.get("scope_path")
        if not isinstance(source_placement_id, str) or not source_placement_id:
            raise PlacementResolutionError("catalog source placement identity is absent")

        niveau_conformity = (
            placement.get("level") == currentness.external_level
            and mapping.external_level == currentness.external_level
            and profile.scope.niveau is mapping.nexus_niveau
        )
        voie_conformity = (
            str(placement.get("scope", "")).startswith("college/")
            and mapping.nexus_voie is Voie.college
            and profile.scope.voie is Voie.college
        )
        matiere_conformity = (
            placement.get("subject") == currentness.subject
            and mapping.external_subject == currentness.subject
            and profile.scope.matiere == mapping.nexus_matiere
        )
        programme_conformity = (
            currentness.effective_currentness == "actuel"
            and currentness.current_for_school_year == school_year
            and profile.scope.school_year == school_year
            and str(profile.scope.programme_version) == canonical_programme
        )

        return VerifiedPedagogicalPlacement(
            content_sha256=sha,
            source_path=source_path,
            source_url=source_url,
            source_placement_id=source_placement_id,
            external_level=mapping.external_level,
            external_subject=mapping.external_subject,
            external_scope=mapping.external_scope,
            external_document_type=mapping.external_document_type,
            effective_currentness=currentness.effective_currentness,
            nexus_collection=mapping.nexus_collection,
            nexus_niveau=mapping.nexus_niveau,
            nexus_voie=mapping.nexus_voie,
            nexus_matiere=mapping.nexus_matiere,
            nexus_statut_enseignement=mapping.nexus_statut_enseignement,
            nexus_programme_version=str(profile.scope.programme_version),
            nexus_domain=nexus_domain,
            nexus_scope=profile.scope,
            type_doc=mapping.type_doc,
            profile_version=profile.profile_version,
            profile_fingerprint=profile_fingerprint(profile),
            corpus_manifest_sha256=self.corpus_manifest_sha256,
            catalog_sha256=self.catalog_sha256,
            placement_catalog_sha256=self.placement_catalog_sha256,
            currentness_evidence_sha256=self.currentness_evidence_sha256,
            programme_index_sha256=self.programme_index_sha256,
            niveau_conformity=niveau_conformity,
            voie_conformity=voie_conformity,
            matiere_conformity=matiere_conformity,
            programme_conformity=programme_conformity,
        )


def to_eligible_placement(
    placement: VerifiedPedagogicalPlacement,
    *,
    resource_id: UUID,
    current_profile_manifest_digest: str,
) -> EligiblePlacement:
    """Convertir avec le digest du manifest de profils, jamais celui du corpus."""
    return EligiblePlacement(
        resource_id=resource_id,
        scope=placement.nexus_scope,
        statut_enseignement=placement.nexus_statut_enseignement,
        domain=placement.nexus_domain,
        source_scope=placement.external_scope,
        source_placement_id=placement.source_placement_id,
        source_path=placement.source_path,
        source_uri=placement.source_url,
        current_profile_fingerprint=placement.profile_fingerprint,
        current_manifest_digest=current_profile_manifest_digest,
        currentness="current",
    )


__all__ = [
    "CURRENTNESS_EVIDENCE_KIND",
    "PlacementResolutionError",
    "VerifiedPedagogicalPlacement",
    "VerifiedPedagogicalPlacementResolver",
    "to_eligible_placement",
]
