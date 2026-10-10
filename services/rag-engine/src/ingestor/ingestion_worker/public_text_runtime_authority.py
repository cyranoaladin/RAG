"""Adaptateur Worker B pour les dérivés texte du successeur public A/C.

Ce module ne crée aucune autorité. Son appelant vérifie C contre la readiness
signée ; ici A et ses sidecars sont relus et confrontés avant de fournir les
interfaces que le publisher gouverné consomme déjà. Les PDF V4/V5 ne font
jamais partie de ce catalogue.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nexus_contracts.document import Niveau, Rights, TypeDoc, Voie
from nexus_release_chain.public_successor_activation import (
    PublicSuccessorActivationVerdict,
    verify_content_anchor,
)

from ingestor.collection_config import canonicalize_catalogue_voie, load_collection_config
from ingestor.ingestion_control.sealed_evidence import RightsClearance
from ingestor.ingestion_control.sealed_release_catalog import (
    TEXT_MEDIA_TYPE,
    VerifiedSealedReleaseCatalog,
    load_sealed_release_catalog,
)
from ingestor.ingestion_profiles.registry import (
    ProfileRegistry,
    load_profile_registry,
    profile_fingerprint,
    select_profile,
)
from ingestor.verified_pedagogical_placement import VerifiedPedagogicalPlacement

_SHA = re.compile(r"[0-9a-f]{64}\Z")


class PublicTextRuntimeAuthorityError(RuntimeError):
    """Le Worker B ne peut pas justifier cette publication publique."""


def _read_json(path: Path, expected_sha256: str) -> dict[str, Any]:
    if _SHA.fullmatch(expected_sha256) is None or path.is_symlink() or not path.is_file():
        raise PublicTextRuntimeAuthorityError(f"authority missing or unsafe: {path.name}")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise PublicTextRuntimeAuthorityError(f"authority digest differs: {path.name}")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicTextRuntimeAuthorityError(f"invalid authority JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise PublicTextRuntimeAuthorityError(f"invalid authority object: {path.name}")
    return value


@dataclass(frozen=True)
class PublicDerivativePIIRegistry:
    _entries: frozenset[str]

    def verify_content_clearance(self, content_sha256: str) -> None:
        if content_sha256 not in self._entries:
            raise PublicTextRuntimeAuthorityError("public derivative PII clearance absent")


@dataclass(frozen=True)
class PublicDerivativeRightsRegistry:
    registry_sha256: str
    _paths: dict[str, str]
    _decision_id: str
    _expires_at_utc: datetime

    def resolve_rights(self, *, content_sha256: str, source_path: str) -> RightsClearance:
        if datetime.now(UTC) >= self._expires_at_utc:
            raise PublicTextRuntimeAuthorityError("public derivative rights authority expired")
        if self._paths.get(content_sha256) != source_path:
            raise PublicTextRuntimeAuthorityError("public derivative rights or path absent")
        return RightsClearance(
            content_sha256=content_sha256,
            rights=Rights.public_allowed,
            zone="student_public_derivative",
            decision_id=self._decision_id,
            registry_sha256=self.registry_sha256,
        )


@dataclass(frozen=True)
class PublicTextPlacementResolver:
    release_profile_manifest_digest: str
    release_embedding_model_id: str
    release_embedding_inventory_sha256: str
    release_embedding_dimension: int
    currentness_school_year: str
    collections: frozenset[str]
    _placements: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]
    _profiles: ProfileRegistry
    _domains: dict[str, str]
    _catalog_sha256: str
    _candidate_inventory_sha256: str
    _currentness_sha256: str
    _manifest_sha256: str

    def require_collections_governed(self, collections: tuple[str, ...] | None) -> None:
        if not collections or not set(collections) <= self.collections:
            raise PublicTextRuntimeAuthorityError("public Worker B requires explicit governed collections")

    def resolve(
        self,
        *,
        content_sha256: str,
        collection: str,
        profile_version: str,
        school_year: str,
        source_placement_id: str | None = None,
        claimed_source_path: str | None = None,
        claimed_source_url: str | None = None,
        claimed_type_doc: str | None = None,
    ) -> VerifiedPedagogicalPlacement:
        facts = self._placements.get((collection, content_sha256))
        if facts is None:
            raise PublicTextRuntimeAuthorityError("content is not an A public text derivative")
        candidate, release_placement, artifact = facts
        if (
            school_year != self.currentness_school_year
            or profile_version != release_placement["profile_version"]
            or (source_placement_id is not None
                and source_placement_id != release_placement["source_placement_id"])
            or (claimed_source_path is not None
                and claimed_source_path != candidate["physical_path"])
            or (claimed_source_url is not None
                and claimed_source_url != artifact["source_url"])
            or (claimed_type_doc is not None
                and claimed_type_doc != artifact["type_doc"])
        ):
            raise PublicTextRuntimeAuthorityError("public text placement claim differs from A")
        profile = select_profile(
            self._profiles, collection=collection, profile_version=profile_version,
        )
        scope = profile.scope
        if scope.visibility != "public" or scope.collection != collection or (
            scope.niveau.value != release_placement["niveau"]
            or scope.voie.value != release_placement["voie"]
            or scope.matiere != release_placement["matiere"]
            or scope.school_year != school_year
            or scope.programme_version != release_placement["programme_version"]
        ):
            raise PublicTextRuntimeAuthorityError("public profile differs from A placement")
        return VerifiedPedagogicalPlacement(
            content_sha256=content_sha256,
            source_path=candidate["physical_path"],
            source_url=artifact["source_url"],
            source_placement_id=release_placement["source_placement_id"],
            external_level=candidate["external_level"],
            external_subject=candidate["external_subject"],
            external_scope=candidate["external_scope"],
            external_document_type=candidate["external_document_type"],
            effective_currentness=release_placement["currentness"],
            nexus_collection=collection,
            nexus_niveau=Niveau(release_placement["niveau"]),
            nexus_voie=Voie(release_placement["voie"]),
            nexus_matiere=release_placement["matiere"],
            nexus_statut_enseignement=release_placement["statut_enseignement"],
            nexus_programme_version=release_placement["programme_version"],
            nexus_domain=self._domains[collection],
            nexus_scope=scope,
            type_doc=TypeDoc(artifact["type_doc"]),
            profile_version=profile_version,
            profile_fingerprint=profile_fingerprint(profile),
            corpus_manifest_sha256=self._manifest_sha256,
            catalog_sha256=self._catalog_sha256,
            placement_catalog_sha256=self._candidate_inventory_sha256,
            currentness_evidence_sha256=self._currentness_sha256,
            programme_index_sha256=self._manifest_sha256,
            niveau_conformity=True,
            voie_conformity=True,
            matiere_conformity=True,
            programme_conformity=True,
            product_currentness=release_placement["currentness"],
        )


@dataclass(frozen=True)
class PublicTextRuntimeAuthorities:
    release_id: str
    placement_resolver: PublicTextPlacementResolver
    pii_evidence_registry: PublicDerivativePIIRegistry
    rights_evidence_registry: PublicDerivativeRightsRegistry
    sealed_release_catalog: VerifiedSealedReleaseCatalog


def load_public_text_runtime_authorities(
    *,
    release_root: Path,
    content_anchor_path: Path,
    expected_content_anchor_sha256: str,
    activation: PublicSuccessorActivationVerdict | None,
    transfer_manifest_path: Path,
    expected_transfer_manifest_sha256: str,
    now_utc: datetime | None = None,
) -> PublicTextRuntimeAuthorities:
    """Relire A sous un verdict C déjà vérifié par le gate de readiness signé."""
    if not isinstance(activation, PublicSuccessorActivationVerdict):
        raise PublicTextRuntimeAuthorityError("verified activation C is required")
    now = now_utc or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now) or (
        activation.expires_at_utc.tzinfo is None or now >= activation.expires_at_utc
    ):
        raise PublicTextRuntimeAuthorityError("public activation C expired or clock invalid")
    try:
        content = verify_content_anchor(
            content_anchor_path, expected_content_anchor_sha256, release_root,
        )
    except Exception as exc:
        raise PublicTextRuntimeAuthorityError("public content anchor A invalid") from exc
    if any((
        activation.release_id != content.release_id,
        activation.content_anchor_sha256 != content.content_anchor_sha256,
        activation.content_manifest_sha256 != content.content_manifest_sha256,
        activation.artifact_registry_sha256 != content.artifact_registry_sha256,
        activation.release_registry_sha256 != content.release_registry_sha256,
        dict(activation.subject_sha256_by_collection)
        != content.subject_sha256_by_collection,
        dict(activation.counts) != content.expected_counts,
    )):
        raise PublicTextRuntimeAuthorityError("activation C differs from content A")
    anchor = _read_json(content_anchor_path, expected_content_anchor_sha256)
    sidecars = anchor["preparation_sidecars"]
    candidate_inventory_sha256 = anchor["candidate_inventory_sha256"]
    gate = release_root / "profile_gate"
    inventory = _read_json(gate / "candidate_inventory.json", candidate_inventory_sha256)
    registry = _read_json(gate / "artifacts.release.json", content.artifact_registry_sha256)
    rights = _read_json(
        gate / "public_rights_registry.json",
        sidecars["public_rights_registry.json"],
    )
    pii = _read_json(
        gate / "public_pii_registry.json",
        sidecars["public_pii_registry.json"],
    )
    currentness = _read_json(
        gate / "public_currentness_registry.json", content.currentness_registry_sha256,
    )
    inclusion = _read_json(
        gate / "inclusion_attestation.json", sidecars["inclusion_attestation.json"],
    )
    profiles_registry = _read_json(
        gate / "public_profiles.json", sidecars["public_profiles.json"],
    )
    artifact_by_sha = {row["content_sha256"]: row for row in registry["artifacts"]}
    if (
        len(artifact_by_sha) != content.expected_counts["unique_artifacts"]
        or any(row.get("media_type") != TEXT_MEDIA_TYPE
               or row.get("content_sha256") == row.get("source_pdf_sha256")
               or row.get("source_path") != f"{sha}.txt"
               for sha, row in artifact_by_sha.items())
    ):
        raise PublicTextRuntimeAuthorityError("A registry is not an exclusive text derivative set")
    rights_by_sha = {row["content_sha256"]: row for row in rights["entries"]}
    pii_by_sha = {row["content_sha256"]: row for row in pii["entries"]}
    current_by_sha = {row["content_sha256"]: row for row in currentness["entries"]}
    included_by_sha = {row["content_sha256"]: row for row in inclusion["decisions"]}
    try:
        currentness_expiry = datetime.fromisoformat(
            currentness["valid_until_utc"].replace("Z", "+00:00")
        )
    except (KeyError, AttributeError, ValueError) as exc:
        raise PublicTextRuntimeAuthorityError("public currentness expiry invalid") from exc
    if (
        currentness_expiry.tzinfo is None
        or currentness_expiry.utcoffset() != UTC.utcoffset(now)
        or now >= currentness_expiry
        or rights.get("kind") != "NEXUS_STUDENT_PUBLIC_DERIVATIVE_RIGHTS_REGISTRY_V2"
        or rights.get("status") != "CANDIDATE_NOT_AUTHORIZED"
        or rights.get("release_id") != content.release_id
        or rights.get("authorized_use") != "student_retrieval_excerpt_only"
        or rights.get("full_pdf_redistribution_allowed") is not False
        or rights.get("answer_generation_allowed") is not False
        or rights.get("inclusion_attestation_sha256") != sidecars["inclusion_attestation.json"]
        or rights.get("rights_authority_sha256") != inclusion.get("rights_authority_sha256")
        or rights.get("evidence_pack_sha256") != pii.get("evidence_pack_sha256")
        or rights.get("source_currentness_attestation_sha256")
        != currentness.get("source_currentness_attestation_sha256")
        or inclusion.get("source_currentness_attestation_sha256")
        != currentness.get("source_currentness_attestation_sha256")
        or inclusion.get("decision_count") != len(artifact_by_sha)
        or len(included_by_sha) != len(artifact_by_sha)
        or set(included_by_sha) != set(artifact_by_sha)
        or any(row.get("disposition") != "INCLUDE" for row in included_by_sha.values())
    ):
        raise PublicTextRuntimeAuthorityError("public rights authority or inclusion differs")
    if any(
        len(registry["entries"]) != len(artifact_by_sha)
        for registry in (rights, pii, currentness)
    ) or any(set(rows) != set(artifact_by_sha) for rows in (
        rights_by_sha, pii_by_sha, current_by_sha,
    )) or any(
        row.get("rights_basis") != "EDUSCOL_ETALAB_2_0_SITEWIDE"
        for row in rights_by_sha.values()
    ) or any(
        row.get("pii_gate_status") != "PASS_BY_DERIVATIVE_FULL_TEXT_ADJUDICATION"
        for row in pii_by_sha.values()
    ) or any(
        row.get("currentness_status") != "PASS"
        or row.get("revocation_status") != "PASS_CURRENT_OFFICIAL_PUBLICATION"
        for row in current_by_sha.values()
    ):
        raise PublicTextRuntimeAuthorityError("public rights, PII or currentness differs")
    for sha, artifact in artifact_by_sha.items():
        citation_raw = (
            json.dumps(artifact["citation"], sort_keys=True, indent=2, ensure_ascii=False)
            + "\n"
        ).encode("utf-8")
        rights_row = rights_by_sha[sha]
        pii_row = pii_by_sha[sha]
        current_row = current_by_sha[sha]
        included = included_by_sha[sha]
        citation = artifact["citation"]
        if (
            rights_row.get("source_pdf_sha256") != artifact["source_pdf_sha256"]
            or rights_row.get("derivative_receipt_sha256")
            != artifact["derivative_receipt_sha256"]
            or rights_row.get("citation_sha256") != hashlib.sha256(citation_raw).hexdigest()
            or pii_row.get("source_pdf_sha256") != artifact["source_pdf_sha256"]
            or pii_row.get("derivative_receipt_sha256")
            != artifact["derivative_receipt_sha256"]
            or current_row.get("source_pdf_sha256") != artifact["source_pdf_sha256"]
            or current_row.get("currentness_evidence_sha256")
            != rights_row.get("currentness_evidence_sha256")
            or included.get("source_pdf_sha256") != artifact["source_pdf_sha256"]
            or included.get("currentness_evidence_sha256")
            != current_row.get("currentness_evidence_sha256")
            or included.get("fresh_source_checkpoint_file_sha256")
            != current_row.get("fresh_source_checkpoint_file_sha256")
            or included.get("pii_evidence_sha256") != pii_row.get("pii_evidence_sha256")
            or any(_SHA.fullmatch(str(row.get(field, ""))) is None for row, field in (
                (included, "evidence_sha256"),
                (pii_row, "pii_evidence_sha256"),
                (current_row, "currentness_evidence_sha256"),
            ))
            or citation.get("licence_id") != "ETALAB-2.0"
            or not citation.get("licensor")
            or not citation.get("source_updated_at")
            or not citation.get("source_label")
            or not citation.get("derivative_notice")
            or citation.get("source_uri") != artifact["source_url"]
            or citation.get("source_pdf_sha256") != artifact["source_pdf_sha256"]
        ):
            raise PublicTextRuntimeAuthorityError("public derivative evidence is misbound")
    profiles = load_profile_registry(gate / "profiles")
    profile_rows = {row["collection"]: row for row in profiles_registry["entries"]}
    if len(profiles_registry["entries"]) != len(content.subject_sha256_by_collection) or (
        set(profile_rows) != set(content.subject_sha256_by_collection)
    ):
        raise PublicTextRuntimeAuthorityError("public profile population differs")
    collection_config = load_collection_config()
    configured = collection_config.get("collections", {})
    domains: dict[str, str] = {}
    placements: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = {}
    for collection_row in inventory["collections"]:
        collection = collection_row["collection"]
        if collection not in content.subject_sha256_by_collection or collection in domains:
            raise PublicTextRuntimeAuthorityError("A collection population is foreign or duplicated")
        subject = _read_json(
            gate / "subjects" / f"{collection}.release.json",
            content.subject_sha256_by_collection[collection],
        )
        profile_version = subject["profile"]["version"]
        profile = select_profile(profiles, collection=collection, profile_version=profile_version)
        if (
            subject["profile"]["fingerprint"] != profile_fingerprint(profile)
            or subject["profile"]["manifest_digest"]
            != sidecars["public_profiles.json"]
            or profile_rows[collection]["scope"]
            != {**profile.scope.model_dump(mode="json"),
                "statut_enseignement": subject["placements"][0]["statut_enseignement"]}
        ):
            raise PublicTextRuntimeAuthorityError("A subject or public profile differs")
        configured_row = configured.get(collection)
        if not isinstance(configured_row, dict) or (
            configured_row.get("matiere") != profile.scope.matiere
            or configured_row.get("niveau") != profile.scope.niveau.value
            or configured_row.get("statut")
            != subject["placements"][0]["statut_enseignement"]
            or canonicalize_catalogue_voie(configured_row.get("voie"))
            != profile.scope.voie.value
            or not isinstance(configured_row.get("domain"), str)
        ):
            raise PublicTextRuntimeAuthorityError("public collection config differs")
        domains[collection] = configured_row["domain"]
        subject_by_source = {row["source_placement_id"]: row for row in subject["placements"]}
        if len(subject_by_source) != len(subject["placements"]):
            raise PublicTextRuntimeAuthorityError("A subject placement duplicated")
        for candidate in collection_row["candidates"]:
            sha = candidate["content_sha256"]
            artifact = artifact_by_sha.get(sha)
            if (
                artifact is None or candidate.get("media_type") != TEXT_MEDIA_TYPE
                or candidate.get("physical_path") != artifact["source_path"]
                or candidate.get("source_pdf_sha256") != artifact["source_pdf_sha256"]
                or len(candidate.get("placements", [])) != 1
            ):
                raise PublicTextRuntimeAuthorityError("A derivative candidate differs")
            external = candidate["placements"][0]
            released = subject_by_source.get(external["source_placement_id"])
            if (
                released is None or released["artifact_id"] != artifact["artifact_id"]
                or released["collection"] != collection
                or released["visibility"] != "public"
                or released["placement_status"] != "active"
                or released["review_status"] != "reviewed"
            ):
                raise PublicTextRuntimeAuthorityError("A released placement differs")
            key = (collection, sha)
            if key in placements:
                raise PublicTextRuntimeAuthorityError("ambiguous public derivative placement")
            placements[key] = (
                {
                    "physical_path": candidate["physical_path"],
                    **external,
                },
                {**released, "profile_version": profile_version}, artifact,
            )
    if (
        len(domains) != content.expected_counts["subjects"]
        or len(placements) != content.expected_counts["placements"]
    ):
        raise PublicTextRuntimeAuthorityError("A public population differs")
    try:
        sealed_catalog = load_sealed_release_catalog(
            gate,
            expected_release_manifest_sha256=content.content_manifest_sha256,
            transfer_manifest_path=transfer_manifest_path,
            expected_transfer_manifest_sha256=expected_transfer_manifest_sha256,
        )
    except Exception as exc:
        raise PublicTextRuntimeAuthorityError("public text transfer manifest invalid") from exc
    if (
        sealed_catalog.media_type_invariant != TEXT_MEDIA_TYPE
        or set(sealed_catalog.artifacts) != set(artifact_by_sha)
    ):
        raise PublicTextRuntimeAuthorityError("public transfer is not exclusive text")
    model = _read_json(gate / "production-profile-gate.release.json", content.content_manifest_sha256)["models"]["embedding"]
    resolver = PublicTextPlacementResolver(
        release_profile_manifest_digest=sidecars["public_profiles.json"],
        release_embedding_model_id=model["model_id"],
        release_embedding_inventory_sha256=model["inventory_sha256"],
        release_embedding_dimension=model["dimension"],
        currentness_school_year=registry["school_year"],
        collections=frozenset(domains),
        _placements=placements,
        _profiles=profiles,
        _domains=domains,
        _catalog_sha256=content.artifact_registry_sha256,
        _candidate_inventory_sha256=candidate_inventory_sha256,
        _currentness_sha256=content.currentness_registry_sha256,
        _manifest_sha256=content.content_manifest_sha256,
    )
    return PublicTextRuntimeAuthorities(
        release_id=content.release_id,
        placement_resolver=resolver,
        pii_evidence_registry=PublicDerivativePIIRegistry(frozenset(pii_by_sha)),
        rights_evidence_registry=PublicDerivativeRightsRegistry(
            registry_sha256=sidecars["public_rights_registry.json"],
            _paths={sha: row["source_path"] for sha, row in artifact_by_sha.items()},
            _decision_id=activation.authority_envelope_sha256,
            _expires_at_utc=min(activation.expires_at_utc, currentness_expiry),
        ),
        sealed_release_catalog=sealed_catalog,
    )


__all__ = [
    "PublicTextRuntimeAuthorityError",
    "PublicTextRuntimeAuthorities",
    "load_public_text_runtime_authorities",
]
