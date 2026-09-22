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
#: ADR-0059 : la preuve parle le vocabulaire de la politique d'actualité
#: (ADR-0055). Un instantané officiel s'y distingue d'une identité d'octets
#: prouvée, et ne peut pas s'en réclamer.
CURRENTNESS_KIND_V3 = "MULTILEVEL_ARTIFACT_CURRENTNESS_V3"
CURRENTNESS_KINDS = frozenset({CURRENTNESS_KIND, CURRENTNESS_KIND_V2, CURRENTNESS_KIND_V3})

VERIFIED_CURRENT = "VERIFIED_CURRENT"
OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE = "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE"
NOT_CURRENT_DECLARED_BY_SOURCE = "NOT_CURRENT_DECLARED_BY_SOURCE"
UNKNOWN_CURRENTNESS = "UNKNOWN"
#: Les quatre dispositions de la politique, et aucune autre.
CURRENTNESS_DISPOSITIONS = (
    VERIFIED_CURRENT,
    OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE,
    NOT_CURRENT_DECLARED_BY_SOURCE,
    UNKNOWN_CURRENTNESS,
)
#: Ce que le produit enregistre de chaque disposition publiable. `current`
#: reste réservé à l'identité d'octets prouvée ; les deux autres dispositions
#: ne sont jamais publiées.
PRODUCT_CURRENTNESS_BY_DISPOSITION = {
    VERIFIED_CURRENT: "current",
    OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE: "official_snapshot",
}
CURRENTNESS_POLICY_ID = "NEXUS-RAG-CURRENTNESS-POLICY-V1"
#: Les quatre conditions de la règle de repli de la politique : toutes
#: doivent être vraies pour qu'un contenu soit un instantané officiel.
SNAPSHOT_FALLBACK_CONDITIONS = frozenset(
    {
        "OFFICIAL_INSTITUTIONAL_PROVENANCE",
        "CONTENT_SHA_PROVENANCE_MATCH",
        "SOURCE_STATUS_NOT_EXPLICIT_ARCHIVE",
        "NO_KNOWN_SUPERSEDING_CONFLICT",
    }
)
#: Ce que l'audit réseau déclare quand il n'a rien pu vérifier.
_UNVERIFIED_AUDIT_STATUS = "CURRENTNESS_UNVERIFIED_SOURCE_UNREACHABLE"
_OFFICIAL_LISTING_HOSTS = frozenset({"eduscol.education.gouv.fr"})
_OFFICIAL_DOWNLOAD_HOSTS = frozenset({"eduscol.education.gouv.fr", "www.education.gouv.fr"})
_VERIFICATION_FACTS = (
    "effective_currentness",
    "current_source_listing_url",
    "current_download_url",
    "current_download_sha256",
    "byte_identity",
)
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
    #: La valeur déclarée, telle quelle : `CURRENT`/`REVIEW_REQUIRED` en V1 et
    #: V2, la disposition elle-même en V3. Elle sert à nommer un refus.
    decision: str
    effective_currentness: str | None
    current_for_school_year: str
    current_source_listing_url: str | None
    current_download_url: str | None
    #: La disposition de la politique (ADR-0055) : `CURRENT` de V1/V2 vaut
    #: `VERIFIED_CURRENT`, `REVIEW_REQUIRED` vaut `UNKNOWN`.
    disposition: str = UNKNOWN_CURRENTNESS
    provenance_url: str | None = None

    @property
    def product_currentness(self) -> str | None:
        """La valeur que le produit enregistre, ou `None` si non publiable."""
        return PRODUCT_CURRENTNESS_BY_DISPOSITION.get(self.disposition)


@dataclass(frozen=True)
class MultilevelCurrentnessEvidence:
    sha256: str
    school_year: str
    artifacts: Mapping[str, MultilevelCurrentnessArtifact]

    @property
    def current_content_sha256(self) -> frozenset[str]:
        return frozenset(
            sha
            for sha, artifact in self.artifacts.items()
            if artifact.disposition == VERIFIED_CURRENT
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
) -> tuple[str, Mapping[str, object] | None]:
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
    bound_to_corpus = evidence_kind in {CURRENTNESS_KIND_V2, CURRENTNESS_KIND_V3}
    if not audit_path.is_file():
        if bound_to_corpus:
            raise MultilevelEvidenceError(
                "currentness network audit is missing next to the V2 evidence — "
                "the declared digest names nothing that can be re-hashed"
            )
        return digest, None
    raw = audit_path.read_bytes()
    observed = hashlib.sha256(raw).hexdigest()
    if observed != digest:
        raise MultilevelEvidenceError(
            "currentness network audit digest differs from the audit file delivered "
            "with the evidence"
        )
    if not bound_to_corpus:
        return digest, None
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
    return digest, audit


_CURRENTNESS_DOCUMENT_KEYS = frozenset(
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
    }
)
_CURRENTNESS_V3_BINDING_KEYS = frozenset(
    {"currentness_policy_id", "currentness_policy_sha256", "servability_matrix_sha256"}
)
_CURRENTNESS_V3_ARTIFACT_KEYS = frozenset(
    {
        "content_sha256",
        "exact_path",
        "collections",
        "placement_facts",
        "current_for_school_year",
        "currentness_disposition",
        "source_status",
        "provenance_url",
        "fallback_conditions",
        "reason_codes",
        *_VERIFICATION_FACTS,
    }
)
#: Une date n'est pas une poignée d'accès : le producteur peut la garder.
_CURRENTNESS_V3_OPTIONAL_ARTIFACT_KEYS = frozenset({"drive_modified_time"})


def _require_official_url(value: object, *, hosts: frozenset[str], label: str) -> str:
    if not isinstance(value, str):
        raise MultilevelEvidenceError(f"{label} is invalid")
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in hosts:
        raise MultilevelEvidenceError(f"{label} is invalid")
    return value


def _require_verified_byte_identity(
    raw_artifact: Mapping[str, object],
    *,
    sha: str,
    inventory_placements: list[MultilevelCandidatePlacement],
    label: str,
) -> None:
    """Les faits d'une identité d'octets prouvée — les règles de `CURRENT`."""
    if (
        raw_artifact.get("effective_currentness") != "actuel"
        or raw_artifact.get("byte_identity") is not True
        or raw_artifact.get("current_download_sha256") != sha
    ):
        raise MultilevelEvidenceError(f"{label} byte identity is not exact")
    for field, hosts in (
        ("current_source_listing_url", _OFFICIAL_LISTING_HOSTS),
        ("current_download_url", _OFFICIAL_DOWNLOAD_HOSTS),
    ):
        url = raw_artifact.get(field)
        if not isinstance(url, str) or urlparse(url).hostname not in hosts:
            raise MultilevelEvidenceError(f"{label} official URL is invalid")
    listing_url = raw_artifact.get("current_source_listing_url")
    if any(placement.source_url != listing_url for placement in inventory_placements):
        raise MultilevelEvidenceError(f"{label} listing URL differs from candidate inventory")


def _require_no_verification_fact(
    raw_artifact: Mapping[str, object], *, message: str
) -> None:
    if any(raw_artifact.get(field) is not None for field in _VERIFICATION_FACTS):
        raise MultilevelEvidenceError(message)


def _v3_disposition(
    raw_artifact: Mapping[str, object],
    *,
    sha: str,
    inventory_placements: list[MultilevelCandidatePlacement],
    audit: Mapping[str, object] | None,
) -> tuple[str, str | None]:
    """Vérifie les faits qu'une disposition V3 exige, et seulement ceux-là.

    Rend la disposition et l'URL de provenance retenue.
    """
    disposition = raw_artifact.get("currentness_disposition")
    if disposition not in CURRENTNESS_DISPOSITIONS:
        raise MultilevelEvidenceError("currentness disposition is invalid")
    source_status = raw_artifact.get("source_status")
    if not isinstance(source_status, str) or not source_status.strip():
        raise MultilevelEvidenceError(f"{disposition} source status is absent")
    archived = "ARCHIVE" in source_status.upper()
    fallback = raw_artifact.get("fallback_conditions")
    provenance = raw_artifact.get("provenance_url")
    if disposition == VERIFIED_CURRENT:
        if audit is not None and audit.get("currentness_status") == _UNVERIFIED_AUDIT_STATUS:
            raise MultilevelEvidenceError(
                "VERIFIED_CURRENT is declared next to a network audit that verified "
                "nothing — byte identity cannot be claimed without a verification"
            )
        if archived:
            raise MultilevelEvidenceError(
                "VERIFIED_CURRENT source status declares an archive"
            )
        if fallback is not None:
            raise MultilevelEvidenceError(
                "VERIFIED_CURRENT does not rest on the snapshot fallback"
            )
        _require_verified_byte_identity(
            raw_artifact,
            sha=sha,
            inventory_placements=inventory_placements,
            label="VERIFIED_CURRENT",
        )
        return VERIFIED_CURRENT, (provenance if isinstance(provenance, str) else None)
    if disposition == OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE:
        _require_no_verification_fact(
            raw_artifact,
            message=(
                "an official snapshot carries a network verification fact — a "
                "snapshot is never VERIFIED_CURRENT (ADR-0055)"
            ),
        )
        if archived:
            raise MultilevelEvidenceError(
                "an official snapshot source status declares an archive — the "
                "fallback never resurrects an archive (ADR-0055)"
            )
        if not isinstance(fallback, Mapping) or set(fallback) != SNAPSHOT_FALLBACK_CONDITIONS:
            raise MultilevelEvidenceError(
                "an official snapshot does not carry exactly the four fallback conditions"
            )
        if any(value is not True for value in fallback.values()):
            raise MultilevelEvidenceError(
                "an official snapshot fallback condition does not hold"
            )
        provenance_url = _require_official_url(
            provenance, hosts=_OFFICIAL_DOWNLOAD_HOSTS, label="snapshot provenance URL"
        )
        if any(placement.source_url != provenance_url for placement in inventory_placements):
            raise MultilevelEvidenceError(
                "snapshot provenance URL differs from candidate inventory"
            )
        return OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE, provenance_url
    _require_no_verification_fact(
        raw_artifact,
        message=f"{disposition} cannot contain positive currentness facts",
    )
    if fallback is not None:
        raise MultilevelEvidenceError(
            f"{disposition} cannot carry snapshot fallback conditions"
        )
    if disposition == NOT_CURRENT_DECLARED_BY_SOURCE and not archived:
        raise MultilevelEvidenceError(
            "NOT_CURRENT_DECLARED_BY_SOURCE source status does not declare an archive"
        )
    return str(disposition), (provenance if isinstance(provenance, str) else None)


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
    evidence_kind = document.get("evidence_kind")
    if evidence_kind not in CURRENTNESS_KINDS:
        raise MultilevelEvidenceError("multilevel currentness evidence kind is invalid")
    is_v3 = evidence_kind == CURRENTNESS_KIND_V3
    _require_exact_keys(
        document,
        set(_CURRENTNESS_DOCUMENT_KEYS | (_CURRENTNESS_V3_BINDING_KEYS if is_v3 else set())),
        label="multilevel currentness evidence",
    )
    if is_v3:
        if document.get("currentness_policy_id") != CURRENTNESS_POLICY_ID:
            raise MultilevelEvidenceError("currentness policy is not the adopted policy")
        _require_sha256(
            document.get("currentness_policy_sha256"), label="currentness policy digest"
        )
        _require_sha256(
            document.get("servability_matrix_sha256"), label="servability matrix digest"
        )
    _, audit = _bind_currentness_network_audit(
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
        if is_v3:
            keys = set(raw_artifact)
            if not (
                _CURRENTNESS_V3_ARTIFACT_KEYS
                <= keys
                <= _CURRENTNESS_V3_ARTIFACT_KEYS | _CURRENTNESS_V3_OPTIONAL_ARTIFACT_KEYS
            ):
                raise MultilevelEvidenceError("currentness V3 artifact fields are not exact")
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
        provenance_url: str | None = None
        if is_v3:
            disposition, provenance_url = _v3_disposition(
                raw_artifact,
                sha=sha,
                inventory_placements=inventory_placements,
                audit=audit,
            )
            decision = disposition
        else:
            decision = str(raw_artifact.get("decision"))
            if decision not in {"CURRENT", "REVIEW_REQUIRED"}:
                raise MultilevelEvidenceError("currentness decision is invalid")
            if decision == "CURRENT":
                _require_verified_byte_identity(
                    raw_artifact,
                    sha=sha,
                    inventory_placements=inventory_placements,
                    label="CURRENT",
                )
                disposition = VERIFIED_CURRENT
            else:
                _require_no_verification_fact(
                    raw_artifact,
                    message="REVIEW_REQUIRED cannot contain positive currentness facts",
                )
                disposition = UNKNOWN_CURRENTNESS
        effective = raw_artifact.get("effective_currentness")
        listing = raw_artifact.get("current_source_listing_url")
        download = raw_artifact.get("current_download_url")
        artifacts[sha] = MultilevelCurrentnessArtifact(
            content_sha256=sha,
            exact_path=exact_path,
            collections=frozenset(collections),
            decision=decision,
            effective_currentness=effective if isinstance(effective, str) else None,
            current_for_school_year=candidate_inventory.school_year,
            current_source_listing_url=listing if isinstance(listing, str) else None,
            current_download_url=download if isinstance(download, str) else None,
            disposition=disposition,
            provenance_url=provenance_url,
        )
    if set(artifacts) != candidate_inventory.unique_content_sha256:
        raise MultilevelEvidenceError("currentness artifact set differs from inventory")
    partition = document.get("partition")
    if not isinstance(partition, Mapping):
        raise MultilevelEvidenceError("currentness partition is absent")
    counts = document.get("counts")
    if not isinstance(counts, Mapping):
        raise MultilevelEvidenceError("currentness counts are absent")
    if is_v3:
        _require_v3_partition_and_counts(partition, counts, artifacts)
    else:
        _require_legacy_partition_and_counts(
            partition, counts, artifacts, evidence_kind=str(evidence_kind)
        )
    return MultilevelCurrentnessEvidence(
        sha256=evidence_sha,
        school_year=candidate_inventory.school_year,
        artifacts=artifacts,
    )


def _require_v3_partition_and_counts(
    partition: Mapping[str, object],
    counts: Mapping[str, object],
    artifacts: Mapping[str, MultilevelCurrentnessArtifact],
) -> None:
    if set(partition) != set(CURRENTNESS_DISPOSITIONS):
        raise MultilevelEvidenceError("currentness partition is invalid")
    for disposition in CURRENTNESS_DISPOSITIONS:
        members = partition.get(disposition)
        if (
            not isinstance(members, list)
            or len(members) != len(set(members))
            or set(members)
            != {sha for sha, item in artifacts.items() if item.disposition == disposition}
        ):
            raise MultilevelEvidenceError("currentness partition differs from dispositions")
    if set(counts) != {"unique_artifacts", "evaluated", *CURRENTNESS_DISPOSITIONS}:
        raise MultilevelEvidenceError("currentness V3 counts are not canonical")
    _require_count(counts, "unique_artifacts", len(artifacts), label="currentness")
    _require_count(counts, "evaluated", len(artifacts), label="currentness")
    for disposition in CURRENTNESS_DISPOSITIONS:
        members = partition[disposition]
        assert isinstance(members, list)
        _require_count(counts, disposition, len(members), label="currentness")


def _require_legacy_partition_and_counts(
    partition: Mapping[str, object],
    counts: Mapping[str, object],
    artifacts: Mapping[str, MultilevelCurrentnessArtifact],
    *,
    evidence_kind: str,
) -> None:
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

__all__ = [
    "CURRENTNESS_KIND",
    "CURRENTNESS_DISPOSITIONS",
    "CURRENTNESS_KIND_V2",
    "CURRENTNESS_KIND_V3",
    "INVENTORY_KIND",
    "NOT_CURRENT_DECLARED_BY_SOURCE",
    "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE",
    "PRODUCT_CURRENTNESS_BY_DISPOSITION",
    "MultilevelCandidateInventory",
    "MultilevelCandidatePlacement",
    "MultilevelCurrentnessArtifact",
    "MultilevelCurrentnessEvidence",
    "MultilevelEvidenceError",
    "UNKNOWN_CURRENTNESS",
    "VERIFIED_CURRENT",
    "content_set_sha256",
    "load_multilevel_candidate_inventory",
    "load_multilevel_currentness",
]
