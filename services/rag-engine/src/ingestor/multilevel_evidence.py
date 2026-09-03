"""Autorités d'inventaire et de currentness pour l'ingestion multi-niveaux."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

INVENTORY_KIND = "MULTILEVEL_CANDIDATE_INVENTORY_V1"
CURRENTNESS_KIND = "MULTILEVEL_ARTIFACT_CURRENTNESS_V1"
CURRENTNESS_KIND_V2 = "MULTILEVEL_ARTIFACT_CURRENTNESS_V2"
CURRENTNESS_KINDS = frozenset({CURRENTNESS_KIND, CURRENTNESS_KIND_V2})
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_SCHOOL_YEAR = re.compile(r"\A[0-9]{4}-[0-9]{4}\Z")
_OFFICIAL_PREFIX = "01_EDUSCOL_OFFICIEL/"


class MultilevelEvidenceError(RuntimeError):
    """Une autorité multi-niveaux est absente, ambiguë ou a dérivé."""


@dataclass(frozen=True)
class MultilevelCandidatePlacement:
    collection: str
    content_sha256: str
    physical_path: str
    source_placement_id: str
    source_url: str
    title: str
    external_level: str
    external_subject: str
    external_scope: str
    external_document_type: str


@dataclass(frozen=True)
class MultilevelCandidateInventory:
    sha256: str
    school_year: str
    corpus_manifest_sha256: str
    sealed_catalog_sha256: str
    placement_catalog_sha256: str
    catalog_delta_sha256: str
    effective_catalog_authority_sha256: str
    placements: tuple[MultilevelCandidatePlacement, ...]

    @property
    def unique_content_sha256(self) -> frozenset[str]:
        return frozenset(item.content_sha256 for item in self.placements)

    def placements_for(
        self, *, content_sha256: str, collection: str
    ) -> tuple[MultilevelCandidatePlacement, ...]:
        return tuple(
            item
            for item in self.placements
            if item.content_sha256 == content_sha256 and item.collection == collection
        )


@dataclass(frozen=True)
class MultilevelCurrentnessArtifact:
    content_sha256: str
    exact_path: str
    collections: frozenset[str]
    decision: str
    effective_currentness: str | None
    current_for_school_year: str
    current_source_listing_url: str | None
    current_download_url: str | None


@dataclass(frozen=True)
class MultilevelCurrentnessEvidence:
    sha256: str
    school_year: str
    artifacts: Mapping[str, MultilevelCurrentnessArtifact]

    @property
    def current_content_sha256(self) -> frozenset[str]:
        return frozenset(
            sha for sha, artifact in self.artifacts.items() if artifact.decision == "CURRENT"
        )

    def for_content(self, content_sha256: str) -> MultilevelCurrentnessArtifact:
        try:
            return self.artifacts[content_sha256]
        except KeyError as exc:
            raise MultilevelEvidenceError(
                f"content {content_sha256!r} has no currentness decision"
            ) from exc


def _require_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise MultilevelEvidenceError(f"{label} must be a lowercase SHA-256")
    return value


def _require_nonempty(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MultilevelEvidenceError(f"{label} must be a non-empty string")
    return value


def _read_digest_bound(
    path: Path, *, expected_sha256: str, json_only: bool, label: str
) -> tuple[str, Mapping[str, object]]:
    expected = _require_sha256(expected_sha256, label=f"expected {label} digest")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise MultilevelEvidenceError(f"{label} cannot be read") from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise MultilevelEvidenceError(f"{label} digest differs")
    try:
        document: Any = (
            json.loads(raw.decode("utf-8")) if json_only else yaml.safe_load(raw)
        )
    except (UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise MultilevelEvidenceError(f"{label} is invalid") from exc
    if not isinstance(document, Mapping):
        raise MultilevelEvidenceError(f"{label} must be a mapping")
    return actual, document


def _require_exact_keys(
    value: Mapping[str, object], expected: set[str], *, label: str
) -> None:
    if set(value) != expected:
        raise MultilevelEvidenceError(f"{label} fields are not exact")


def _require_count(
    counts: Mapping[str, object], field: str, actual: int, *, label: str
) -> None:
    if counts.get(field) != actual:
        raise MultilevelEvidenceError(f"{label} {field} count differs")


def load_multilevel_candidate_inventory(
    path: Path, *, expected_sha256: str
) -> MultilevelCandidateInventory:
    inventory_sha, document = _read_digest_bound(
        path,
        expected_sha256=expected_sha256,
        json_only=True,
        label="multilevel candidate inventory",
    )
    _require_exact_keys(
        document,
        {
            "inventory_kind",
            "school_year",
            "corpus_manifest_sha256",
            "sealed_catalog_sha256",
            "placement_catalog_sha256",
            "catalog_delta_sha256",
            "catalog_delta_payload_sha256",
            "effective_catalog_authority_sha256",
            "counts",
            "collection_partition",
            "candidate_partition",
            "collections",
        },
        label="multilevel candidate inventory",
    )
    if document.get("inventory_kind") != INVENTORY_KIND:
        raise MultilevelEvidenceError("multilevel candidate inventory kind is invalid")
    school_year = document.get("school_year")
    if not isinstance(school_year, str) or _SCHOOL_YEAR.fullmatch(school_year) is None:
        raise MultilevelEvidenceError("multilevel candidate inventory school year is invalid")
    authorities = {
        field: _require_sha256(document.get(field), label=field)
        for field in (
            "corpus_manifest_sha256",
            "sealed_catalog_sha256",
            "placement_catalog_sha256",
            "catalog_delta_sha256",
            "catalog_delta_payload_sha256",
            "effective_catalog_authority_sha256",
        )
    }
    raw_collections = document.get("collections")
    if not isinstance(raw_collections, list) or not raw_collections:
        raise MultilevelEvidenceError("multilevel candidate inventory is empty")
    placements: list[MultilevelCandidatePlacement] = []
    collections: set[str] = set()
    physical_by_sha: dict[str, str] = {}
    placement_keys: set[tuple[str, str, str]] = set()
    for raw_collection in raw_collections:
        if not isinstance(raw_collection, Mapping):
            raise MultilevelEvidenceError("multilevel inventory collection is malformed")
        _require_exact_keys(
            raw_collection,
            {
                "phase",
                "collection",
                "external_level",
                "external_subject",
                "external_scope",
                "counts",
                "observed_values",
                "discovery_routes",
                "inventory_disposition",
                "candidate_partition",
                "candidates",
            },
            label="multilevel inventory collection",
        )
        collection = _require_nonempty(
            raw_collection.get("collection"), label="inventory collection"
        )
        collection_level = _require_nonempty(
            raw_collection.get("external_level"), label="collection external level"
        )
        collection_subject = _require_nonempty(
            raw_collection.get("external_subject"),
            label="collection external subject",
        )
        collection_scope = _require_nonempty(
            raw_collection.get("external_scope"), label="collection external scope"
        )
        if collection in collections:
            raise MultilevelEvidenceError("multilevel inventory collection is duplicated")
        collections.add(collection)
        raw_candidates = raw_collection.get("candidates")
        if not isinstance(raw_candidates, list) or not raw_candidates:
            raise MultilevelEvidenceError("multilevel inventory collection has no candidates")
        collection_shas: set[str] = set()
        collection_placements = 0
        for raw_candidate in raw_candidates:
            if not isinstance(raw_candidate, Mapping):
                raise MultilevelEvidenceError("multilevel inventory candidate is malformed")
            _require_exact_keys(
                raw_candidate,
                {
                    "content_sha256",
                    "physical_path",
                    "physical_currentness_candidate",
                    "physical_disposition_candidate",
                    "placements",
                },
                label="multilevel inventory candidate",
            )
            content_sha = _require_sha256(
                raw_candidate.get("content_sha256"), label="candidate content SHA"
            )
            physical_path = _require_nonempty(
                raw_candidate.get("physical_path"), label="candidate physical path"
            )
            if not physical_path.startswith(_OFFICIAL_PREFIX):
                raise MultilevelEvidenceError("candidate physical path is outside Eduscol")
            previous_path = physical_by_sha.setdefault(content_sha, physical_path)
            if previous_path != physical_path:
                raise MultilevelEvidenceError("candidate content has conflicting physical paths")
            collection_shas.add(content_sha)
            raw_placements = raw_candidate.get("placements")
            if not isinstance(raw_placements, list) or not raw_placements:
                raise MultilevelEvidenceError("multilevel candidate has no placements")
            for raw_placement in raw_placements:
                if not isinstance(raw_placement, Mapping):
                    raise MultilevelEvidenceError("multilevel placement is malformed")
                _require_exact_keys(
                    raw_placement,
                    {
                        "source_placement_id",
                        "source_url",
                        "title",
                        "external_level",
                        "external_subject",
                        "external_scope",
                        "external_document_type",
                        "pedagogical_status",
                        "year",
                        "placement_origin",
                        "placement_reason_code",
                    },
                    label="multilevel placement",
                )
                placement_id = _require_nonempty(
                    raw_placement.get("source_placement_id"),
                    label="source placement identity",
                )
                key = (collection, content_sha, placement_id)
                if key in placement_keys:
                    raise MultilevelEvidenceError("multilevel placement is duplicated")
                placement_keys.add(key)
                placement_level = _require_nonempty(
                    raw_placement.get("external_level"), label="external level"
                )
                placement_subject = _require_nonempty(
                    raw_placement.get("external_subject"), label="external subject"
                )
                placement_scope = _require_nonempty(
                    raw_placement.get("external_scope"), label="external scope"
                )
                if (
                    placement_level != collection_level
                    or placement_subject != collection_subject
                    or placement_scope != collection_scope
                ):
                    raise MultilevelEvidenceError(
                        "placement differs from its collection facts"
                    )
                placements.append(
                    MultilevelCandidatePlacement(
                        collection=collection,
                        content_sha256=content_sha,
                        physical_path=physical_path,
                        source_placement_id=placement_id,
                        source_url=_require_nonempty(
                            raw_placement.get("source_url"), label="placement source URL"
                        ),
                        title=_require_nonempty(
                            raw_placement.get("title"), label="placement title"
                        ),
                        external_level=placement_level,
                        external_subject=placement_subject,
                        external_scope=placement_scope,
                        external_document_type=_require_nonempty(
                            raw_placement.get("external_document_type"),
                            label="external document type",
                        ),
                    )
                )
                collection_placements += 1
        raw_counts = raw_collection.get("counts")
        if not isinstance(raw_counts, Mapping):
            raise MultilevelEvidenceError("multilevel collection counts are absent")
        _require_count(
            raw_counts,
            "unique_artifacts",
            len(collection_shas),
            label=f"collection {collection}",
        )
        _require_count(
            raw_counts,
            "placements",
            collection_placements,
            label=f"collection {collection}",
        )

    raw_counts = document.get("counts")
    if not isinstance(raw_counts, Mapping):
        raise MultilevelEvidenceError("multilevel inventory counts are absent")
    unique_shas = set(physical_by_sha)
    _require_count(raw_counts, "target_collections", len(collections), label="inventory")
    _require_count(raw_counts, "unique_artifacts", len(unique_shas), label="inventory")
    _require_count(raw_counts, "placements", len(placements), label="inventory")
    _require_count(raw_counts, "physical_objects", len(physical_by_sha), label="inventory")
    multiplicities = Counter(item.content_sha256 for item in placements)
    multi_placement = sum(1 for count in multiplicities.values() if count > 1)
    _require_count(
        raw_counts,
        "multi_placement_artifacts",
        multi_placement,
        label="inventory",
    )
    partition = document.get("candidate_partition")
    if not isinstance(partition, Mapping):
        raise MultilevelEvidenceError("candidate partition is absent")
    pending = partition.get("exact_grade_gate_pending")
    named = partition.get("named_noneligible")
    unevaluated = partition.get("unevaluated")
    if (
        not isinstance(pending, list)
        or not isinstance(named, list)
        or not isinstance(unevaluated, list)
    ):
        raise MultilevelEvidenceError("candidate partition is invalid")
    partition_values = [*pending, *named, *unevaluated]
    if (
        any(not isinstance(value, str) for value in partition_values)
        or len(partition_values) != len(set(partition_values))
        or set(partition_values) != unique_shas
    ):
        raise MultilevelEvidenceError("candidate partition differs from artifact set")
    return MultilevelCandidateInventory(
        sha256=inventory_sha,
        school_year=school_year,
        corpus_manifest_sha256=authorities["corpus_manifest_sha256"],
        sealed_catalog_sha256=authorities["sealed_catalog_sha256"],
        placement_catalog_sha256=authorities["placement_catalog_sha256"],
        catalog_delta_sha256=authorities["catalog_delta_sha256"],
        effective_catalog_authority_sha256=authorities[
            "effective_catalog_authority_sha256"
        ],
        placements=tuple(placements),
    )


#: Nom du fichier d'audit reseau livre A COTE de la preuve de fraicheur par le
#: producteur. C'est lui que `currentness_audit_sha256` nomme : sans ce fichier,
#: l'empreinte est un chiffre que personne ne peut rehacher.
CURRENTNESS_NETWORK_AUDIT_FILENAME = "currentness_network_audit.json"


def content_set_sha256(content_sha256_values: Iterable[str]) -> str:
    """Empreinte canonique d'un ensemble de contenus : SHA tries, un par ligne,
    saut de ligne final — la meme canonicalisation que le producteur
    (`_final_set_digest`) et que le registre de droits."""
    return hashlib.sha256(
        ("\n".join(sorted(set(content_sha256_values))) + "\n").encode("utf-8")
    ).hexdigest()


def _bind_currentness_network_audit(
    evidence_path: Path,
    declared_digest: object,
    *,
    evidence_kind: str,
    candidate_inventory: MultilevelCandidateInventory,
) -> str:
    """Rend `currentness_audit_sha256` opposable, ou refuse.

    - la valeur doit avoir la forme d'un SHA-256 (jamais `NOT-A-SHA`) ;
    - une preuve V2 est livree avec son audit reseau frere, dont les octets
      doivent porter exactement cette empreinte, et cet audit doit NOMMER le
      corpus qu'il a mesure : meme manifeste corpus et meme ensemble exact de
      contenus que l'inventaire. Un audit d'un autre corpus, ou d'un autre
      denominateur, ne prouve rien sur celui-ci, meme rescelle ;
    - une preuve V1 conserve son contrat historique (audit hors bande possible),
      mais si un audit frere est present il doit lui aussi correspondre : une
      preuve qui contredit le fichier livre a cote d'elle est refusee.
    """
    digest = _require_sha256(declared_digest, label="currentness audit digest")
    audit_path = evidence_path.parent / CURRENTNESS_NETWORK_AUDIT_FILENAME
    if not audit_path.is_file():
        if evidence_kind == CURRENTNESS_KIND_V2:
            raise MultilevelEvidenceError(
                "currentness network audit is missing next to the V2 evidence — "
                "the declared digest names nothing that can be re-hashed"
            )
        return digest
    raw = audit_path.read_bytes()
    observed = hashlib.sha256(raw).hexdigest()
    if observed != digest:
        raise MultilevelEvidenceError(
            "currentness network audit digest differs from the audit file delivered "
            "with the evidence"
        )
    if evidence_kind != CURRENTNESS_KIND_V2:
        return digest
    try:
        audit = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MultilevelEvidenceError(
            "currentness network audit is not a JSON document"
        ) from exc
    if not isinstance(audit, Mapping):
        raise MultilevelEvidenceError("currentness network audit is not a JSON object")
    if audit.get("corpus_manifest_sha256") != candidate_inventory.corpus_manifest_sha256:
        raise MultilevelEvidenceError(
            "currentness network audit names another corpus manifest than the "
            "candidate inventory — an audit of another corpus proves nothing here"
        )
    expected_set = content_set_sha256(candidate_inventory.unique_content_sha256)
    if audit.get("content_set_sha256") != expected_set:
        raise MultilevelEvidenceError(
            "currentness network audit names another content set than the candidate "
            "inventory — its denominator is not this release"
        )
    return digest


def load_multilevel_currentness(
    path: Path,
    *,
    expected_sha256: str,
    candidate_inventory: MultilevelCandidateInventory,
) -> MultilevelCurrentnessEvidence:
    evidence_sha, document = _read_digest_bound(
        path,
        expected_sha256=expected_sha256,
        json_only=False,
        label="multilevel currentness evidence",
    )
    _require_exact_keys(
        document,
        {
            "evidence_kind",
            "school_year",
            "candidate_inventory_sha256",
            "corpus_manifest_sha256",
            "sealed_catalog_sha256",
            "placement_catalog_sha256",
            "catalog_delta_sha256",
            "effective_catalog_authority_sha256",
            "currentness_audit_sha256",
            "decision_basis",
            "counts",
            "partition",
            "artifacts",
        },
        label="multilevel currentness evidence",
    )
    evidence_kind = document.get("evidence_kind")
    if evidence_kind not in CURRENTNESS_KINDS:
        raise MultilevelEvidenceError("multilevel currentness evidence kind is invalid")
    _bind_currentness_network_audit(
        path,
        document.get("currentness_audit_sha256"),
        evidence_kind=str(evidence_kind),
        candidate_inventory=candidate_inventory,
    )
    if document.get("school_year") != candidate_inventory.school_year:
        raise MultilevelEvidenceError("currentness school year differs from inventory")
    expected_bindings = {
        "candidate_inventory_sha256": candidate_inventory.sha256,
        "corpus_manifest_sha256": candidate_inventory.corpus_manifest_sha256,
        "sealed_catalog_sha256": candidate_inventory.sealed_catalog_sha256,
        "placement_catalog_sha256": candidate_inventory.placement_catalog_sha256,
        "catalog_delta_sha256": candidate_inventory.catalog_delta_sha256,
        "effective_catalog_authority_sha256": (
            candidate_inventory.effective_catalog_authority_sha256
        ),
    }
    if any(document.get(field) != value for field, value in expected_bindings.items()):
        raise MultilevelEvidenceError("currentness authorities differ from inventory")
    raw_artifacts = document.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise MultilevelEvidenceError("currentness artifacts are absent")
    inventory_by_sha: dict[str, list[MultilevelCandidatePlacement]] = {}
    for placement in candidate_inventory.placements:
        inventory_by_sha.setdefault(placement.content_sha256, []).append(placement)
    artifacts: dict[str, MultilevelCurrentnessArtifact] = {}
    for raw_artifact in raw_artifacts:
        if not isinstance(raw_artifact, Mapping):
            raise MultilevelEvidenceError("currentness artifact is malformed")
        sha = _require_sha256(
            raw_artifact.get("content_sha256"), label="currentness content SHA"
        )
        if sha in artifacts:
            raise MultilevelEvidenceError("currentness content is duplicated")
        exact_path = _require_nonempty(
            raw_artifact.get("exact_path"), label="currentness exact path"
        )
        inventory_placements = inventory_by_sha.get(sha, [])
        if not inventory_placements or any(
            placement.physical_path != exact_path for placement in inventory_placements
        ):
            raise MultilevelEvidenceError("currentness path differs from inventory")
        collections = raw_artifact.get("collections")
        if (
            not isinstance(collections, list)
            or not collections
            or any(not isinstance(value, str) or not value for value in collections)
            or set(collections)
            != {placement.collection for placement in inventory_placements}
        ):
            raise MultilevelEvidenceError("currentness collections differ from inventory")
        raw_facts = raw_artifact.get("placement_facts")
        if not isinstance(raw_facts, list):
            raise MultilevelEvidenceError("currentness placement facts are absent")
        facts = {
            (
                raw.get("collection"),
                raw.get("source_placement_id"),
                raw.get("external_level"),
                raw.get("external_subject"),
                raw.get("external_scope"),
                raw.get("external_document_type"),
            )
            for raw in raw_facts
            if isinstance(raw, Mapping)
        }
        expected_facts = {
            (
                placement.collection,
                placement.source_placement_id,
                placement.external_level,
                placement.external_subject,
                placement.external_scope,
                placement.external_document_type,
            )
            for placement in inventory_placements
        }
        if facts != expected_facts or len(raw_facts) != len(facts):
            raise MultilevelEvidenceError("currentness placement facts differ from inventory")
        if raw_artifact.get("current_for_school_year") != candidate_inventory.school_year:
            raise MultilevelEvidenceError("currentness artifact school year differs")
        decision = raw_artifact.get("decision")
        if decision not in {"CURRENT", "REVIEW_REQUIRED"}:
            raise MultilevelEvidenceError("currentness decision is invalid")
        effective = raw_artifact.get("effective_currentness")
        if decision == "CURRENT":
            if (
                effective != "actuel"
                or raw_artifact.get("byte_identity") is not True
                or raw_artifact.get("current_download_sha256") != sha
            ):
                raise MultilevelEvidenceError("CURRENT byte identity is not exact")
            allowed_hosts = {
                "current_source_listing_url": {"eduscol.education.gouv.fr"},
                "current_download_url": {
                    "eduscol.education.gouv.fr",
                    "www.education.gouv.fr",
                },
            }
            for field, hosts in allowed_hosts.items():
                url = raw_artifact.get(field)
                if (
                    not isinstance(url, str)
                    or urlparse(url).hostname not in hosts
                ):
                    raise MultilevelEvidenceError("CURRENT official URL is invalid")
            listing_url = raw_artifact.get("current_source_listing_url")
            if any(
                placement.source_url != listing_url
                for placement in inventory_placements
            ):
                raise MultilevelEvidenceError(
                    "CURRENT listing URL differs from candidate inventory"
                )
        elif any(
            raw_artifact.get(field) is not None
            for field in (
                "effective_currentness",
                "current_source_listing_url",
                "current_download_url",
                "current_download_sha256",
                "byte_identity",
            )
        ):
            raise MultilevelEvidenceError(
                "REVIEW_REQUIRED cannot contain positive currentness facts"
            )
        artifacts[sha] = MultilevelCurrentnessArtifact(
            content_sha256=sha,
            exact_path=exact_path,
            collections=frozenset(collections),
            decision=str(decision),
            effective_currentness=effective if isinstance(effective, str) else None,
            current_for_school_year=candidate_inventory.school_year,
            current_source_listing_url=(
                raw_artifact.get("current_source_listing_url")
                if isinstance(raw_artifact.get("current_source_listing_url"), str)
                else None
            ),
            current_download_url=(
                raw_artifact.get("current_download_url")
                if isinstance(raw_artifact.get("current_download_url"), str)
                else None
            ),
        )
    if set(artifacts) != candidate_inventory.unique_content_sha256:
        raise MultilevelEvidenceError("currentness artifact set differs from inventory")
    partition = document.get("partition")
    if not isinstance(partition, Mapping):
        raise MultilevelEvidenceError("currentness partition is absent")
    current = partition.get("current")
    review = partition.get("review_required")
    unevaluated = partition.get("unevaluated")
    if not isinstance(current, list) or not isinstance(review, list) or unevaluated != []:
        raise MultilevelEvidenceError("currentness partition is invalid")
    if (
        set(current)
        != {sha for sha, artifact in artifacts.items() if artifact.decision == "CURRENT"}
        or set(review)
        != {
            sha
            for sha, artifact in artifacts.items()
            if artifact.decision == "REVIEW_REQUIRED"
        }
        or len(current) != len(set(current))
        or len(review) != len(set(review))
    ):
        raise MultilevelEvidenceError("currentness partition differs from decisions")
    counts = document.get("counts")
    if not isinstance(counts, Mapping):
        raise MultilevelEvidenceError("currentness counts are absent")
    if evidence_kind == CURRENTNESS_KIND_V2:
        expected_count_keys = {
            "unique_artifacts",
            "evaluated",
            "current",
            "review_required",
            "unevaluated",
        }
        if set(counts) != expected_count_keys:
            raise MultilevelEvidenceError("currentness V2 counts are not canonical")
        _require_count(
            counts, "unique_artifacts", len(artifacts), label="currentness"
        )
    else:
        _require_count(counts, "artifacts", len(artifacts), label="currentness")
    _require_count(counts, "evaluated", len(artifacts), label="currentness")
    _require_count(counts, "current", len(current), label="currentness")
    _require_count(counts, "review_required", len(review), label="currentness")
    _require_count(counts, "unevaluated", 0, label="currentness")
    return MultilevelCurrentnessEvidence(
        sha256=evidence_sha,
        school_year=candidate_inventory.school_year,
        artifacts=artifacts,
    )


__all__ = [
    "CURRENTNESS_KIND",
    "CURRENTNESS_KIND_V2",
    "INVENTORY_KIND",
    "MultilevelCandidateInventory",
    "MultilevelCandidatePlacement",
    "MultilevelCurrentnessArtifact",
    "MultilevelCurrentnessEvidence",
    "MultilevelEvidenceError",
    "content_set_sha256",
    "load_multilevel_candidate_inventory",
    "load_multilevel_currentness",
]
