"""Resolver multi-niveaux gouverné, sans allowlist SHA codée en Python."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import cast

import pytest
from nexus_contracts.document import Niveau, TypeDoc, Voie
from nexus_contracts.ingestion import CollectionProfile

from ingestor.ingestion_profiles.registry import profile_fingerprint
from ingestor.multilevel_evidence import (
    MultilevelEvidenceError,
    load_multilevel_candidate_inventory,
    load_multilevel_currentness,
)
from ingestor.multilevel_mapping import ClosedMultilevelMapping
from ingestor.multilevel_verified_placement import (
    MultilevelPlacementResolutionError,
    MultilevelReleaseEligibility,
    MultilevelReleasePlacement,
    MultilevelVerifiedPedagogicalPlacementResolver,
    load_multilevel_release_eligibility,
)
from ingestor.programme_registry import ProgrammeIndexRegistry
from ingestor.release_readiness import load_release_expectation
from ingestor.staging_profile_manifest import StagingProfileManifestVerification

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REAL_MULTILEVEL_RELEASE = (
    _REPO_ROOT
    / "services"
    / "rag-pedago"
    / "data"
    / "releases"
    / "prerentree_2026_2027"
    / "multilevel"
    / "multilevel.release.json"
)
_REAL_MULTILEVEL_RELEASE_SHA256 = (
    "d8ee6703d3497e34e6e5273bee00da90ab9c82094f0f9a1257eef0ff91da1828"
)


def _json_bytes(document: object) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, document: object) -> str:
    raw = _json_bytes(document)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _placement(
    *,
    placement_id: str,
    level: str,
    subject: str,
    scope: str,
    document_type: str,
) -> dict[str, object]:
    return {
        "source_placement_id": placement_id,
        "source_url": "https://eduscol.education.gouv.fr/programmes",
        "title": f"Document officiel {level}",
        "external_level": level,
        "external_subject": subject,
        "external_scope": scope,
        "external_document_type": document_type,
        "pedagogical_status": "a-verifier",
        "year": "2026",
        "placement_origin": "SEALED_PARENT_CATALOG",
        "placement_reason_code": None,
    }


def _candidate(
    *, content_sha256: str, path: str, placement: dict[str, object]
) -> dict[str, object]:
    return {
        "content_sha256": content_sha256,
        "physical_path": path,
        "physical_currentness_candidate": "unclassified",
        "physical_disposition_candidate": "REVIEW_REQUIRED",
        "placements": [placement],
    }


def _collection(
    *,
    collection: str,
    phase: str,
    level: str,
    subject: str,
    scope: str,
    candidates: list[dict[str, object]],
) -> dict[str, object]:
    shas = [str(candidate["content_sha256"]) for candidate in candidates]
    placement_count = sum(
        len(cast(list[object], candidate["placements"])) for candidate in candidates
    )
    return {
        "phase": phase,
        "collection": collection,
        "external_level": level,
        "external_subject": subject,
        "external_scope": scope,
        "counts": {
            "unique_artifacts": len(set(shas)),
            "placements": placement_count,
            "physical_objects": len(set(shas)),
            "multi_placement_artifacts": 0,
        },
        "observed_values": {},
        "discovery_routes": [],
        "inventory_disposition": "EXACT_GRADE_GATES_PENDING",
        "candidate_partition": {
            "exact_grade_gate_pending": sorted(set(shas)),
            "named_noneligible": [],
            "unevaluated": [],
        },
        "candidates": candidates,
    }


def _evidence_documents() -> tuple[dict[str, object], dict[str, object]]:
    fourth_sha = "1" * 64
    seconde_sha = "2" * 64
    review_sha = "3" * 64
    fourth_path = "01_EDUSCOL_OFFICIEL/COLLEGE/4E/MATHEMATIQUES/fourth.pdf"
    seconde_path = "01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/MATHEMATIQUES/seconde.pdf"
    review_path = "01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/MATHEMATIQUES/review.pdf"
    fourth_placement = _placement(
        placement_id="par-scope/college/cycle-4/mathematiques/4e/fourth.pdf",
        level="4e",
        subject="mathematiques",
        scope="college/cycle-4/mathematiques",
        document_type="reperes-attendus",
    )
    seconde_placement = _placement(
        placement_id="par-scope/lycee/commun/mathematiques/seconde/seconde.pdf",
        level="seconde",
        subject="mathematiques",
        scope="lycee/commun/mathematiques",
        document_type="programme-officiel",
    )
    review_placement = _placement(
        placement_id="par-scope/lycee/commun/mathematiques/seconde/review.pdf",
        level="seconde",
        subject="mathematiques",
        scope="lycee/commun/mathematiques",
        document_type="programme-officiel",
    )
    collections = [
        _collection(
            collection="rag_nexus_maths_quatrieme_tc",
            phase="A",
            level="4e",
            subject="mathematiques",
            scope="college/cycle-4/mathematiques",
            candidates=[
                _candidate(
                    content_sha256=fourth_sha,
                    path=fourth_path,
                    placement=fourth_placement,
                )
            ],
        ),
        _collection(
            collection="rag_nexus_maths_seconde_tc",
            phase="A",
            level="seconde",
            subject="mathematiques",
            scope="lycee/commun/mathematiques",
            candidates=[
                _candidate(
                    content_sha256=seconde_sha,
                    path=seconde_path,
                    placement=seconde_placement,
                ),
                _candidate(
                    content_sha256=review_sha,
                    path=review_path,
                    placement=review_placement,
                ),
            ],
        ),
    ]
    inventory = {
        "inventory_kind": "MULTILEVEL_CANDIDATE_INVENTORY_V1",
        "school_year": "2026-2027",
        "corpus_manifest_sha256": "a" * 64,
        "sealed_catalog_sha256": "b" * 64,
        "placement_catalog_sha256": "c" * 64,
        "catalog_delta_sha256": "d" * 64,
        "catalog_delta_payload_sha256": "e" * 64,
        "effective_catalog_authority_sha256": "f" * 64,
        "counts": {
            "target_collections": 2,
            "unique_artifacts": 3,
            "placements": 3,
            "physical_objects": 3,
            "multi_placement_artifacts": 0,
        },
        "collection_partition": {
            "exact_grade_gates_pending": [
                "rag_nexus_maths_quatrieme_tc",
                "rag_nexus_maths_seconde_tc",
            ],
            "placement_proof_or_corpus_delta_required": [],
            "unevaluated": [],
        },
        "candidate_partition": {
            "exact_grade_gate_pending": [fourth_sha, seconde_sha, review_sha],
            "named_noneligible": [],
            "unevaluated": [],
        },
        "collections": collections,
    }

    def currentness_row(
        *,
        sha: str,
        path: str,
        collection: str,
        placement: dict[str, object],
        current: bool,
    ) -> dict[str, object]:
        return {
            "content_sha256": sha,
            "exact_path": path,
            "collections": [collection],
            "placement_facts": [
                {
                    "collection": collection,
                    "source_placement_id": placement["source_placement_id"],
                    "external_level": placement["external_level"],
                    "external_subject": placement["external_subject"],
                    "external_scope": placement["external_scope"],
                    "external_document_type": placement["external_document_type"],
                }
            ],
            "current_for_school_year": "2026-2027",
            "decision": "CURRENT" if current else "REVIEW_REQUIRED",
            "reason_codes": [
                "OFFICIAL_CURRENT_BYTE_IDENTITY_EXACT"
                if current
                else "CURRENT_SOURCE_BYTE_IDENTITY_NOT_AUDITED"
            ],
            "effective_currentness": "actuel" if current else None,
            "current_source_listing_url": (
                "https://eduscol.education.gouv.fr/programmes" if current else None
            ),
            "current_download_url": (
                "https://eduscol.education.gouv.fr/document.pdf" if current else None
            ),
            "current_download_sha256": sha if current else None,
            "byte_identity": True if current else None,
        }

    currentness = {
        "evidence_kind": "MULTILEVEL_ARTIFACT_CURRENTNESS_V1",
        "school_year": "2026-2027",
        "candidate_inventory_sha256": "TO_BE_BOUND",
        "corpus_manifest_sha256": inventory["corpus_manifest_sha256"],
        "sealed_catalog_sha256": inventory["sealed_catalog_sha256"],
        "placement_catalog_sha256": inventory["placement_catalog_sha256"],
        "catalog_delta_sha256": inventory["catalog_delta_sha256"],
        "effective_catalog_authority_sha256": inventory[
            "effective_catalog_authority_sha256"
        ],
        "currentness_audit_sha256": "4" * 64,
        "decision_basis": {"kind": "OFFICIAL_NETWORK_AUDIT"},
        "counts": {
            "artifacts": 3,
            "evaluated": 3,
            "current": 2,
            "review_required": 1,
            "unevaluated": 0,
            "by_collection": {},
        },
        "partition": {
            "current": [fourth_sha, seconde_sha],
            "review_required": [review_sha],
            "unevaluated": [],
        },
        "artifacts": [
            currentness_row(
                sha=fourth_sha,
                path=fourth_path,
                collection="rag_nexus_maths_quatrieme_tc",
                placement=fourth_placement,
                current=True,
            ),
            currentness_row(
                sha=seconde_sha,
                path=seconde_path,
                collection="rag_nexus_maths_seconde_tc",
                placement=seconde_placement,
                current=True,
            ),
            currentness_row(
                sha=review_sha,
                path=review_path,
                collection="rag_nexus_maths_seconde_tc",
                placement=review_placement,
                current=False,
            ),
        ],
    }
    return cast(dict[str, object], inventory), cast(dict[str, object], currentness)


def _write_evidence(tmp_path: Path) -> tuple[Path, str, Path, str]:
    inventory_document, currentness_document = _evidence_documents()
    inventory_path = tmp_path / "inventory.json"
    inventory_sha = _write_json(inventory_path, inventory_document)
    currentness_document["candidate_inventory_sha256"] = inventory_sha
    currentness_path = tmp_path / "currentness.json"
    currentness_sha = _write_json(currentness_path, currentness_document)
    return inventory_path, inventory_sha, currentness_path, currentness_sha


def test_loaders_bind_complete_inventory_and_retain_review_decisions(
    tmp_path: Path,
) -> None:
    inventory_path, inventory_sha, currentness_path, currentness_sha = (
        _write_evidence(tmp_path)
    )

    inventory = load_multilevel_candidate_inventory(
        inventory_path, expected_sha256=inventory_sha
    )
    currentness = load_multilevel_currentness(
        currentness_path,
        expected_sha256=currentness_sha,
        candidate_inventory=inventory,
    )

    assert len(inventory.placements) == 3
    assert currentness.for_content("1" * 64).decision == "CURRENT"
    assert currentness.for_content("3" * 64).decision == "REVIEW_REQUIRED"
    assert currentness.current_content_sha256 == frozenset({"1" * 64, "2" * 64})


def test_currentness_loader_rejects_an_incomplete_artifact_partition(
    tmp_path: Path,
) -> None:
    inventory_document, currentness_document = _evidence_documents()
    inventory_path = tmp_path / "inventory.json"
    inventory_sha = _write_json(inventory_path, inventory_document)
    currentness_document["candidate_inventory_sha256"] = inventory_sha
    cast(list[object], currentness_document["artifacts"]).pop()
    currentness_path = tmp_path / "currentness.json"
    currentness_sha = _write_json(currentness_path, currentness_document)
    inventory = load_multilevel_candidate_inventory(
        inventory_path, expected_sha256=inventory_sha
    )

    with pytest.raises(MultilevelEvidenceError, match="artifact set"):
        load_multilevel_currentness(
            currentness_path,
            expected_sha256=currentness_sha,
            candidate_inventory=inventory,
        )


def test_inventory_loader_rejects_placement_scope_drift_from_collection(
    tmp_path: Path,
) -> None:
    inventory_document, _currentness_document = _evidence_documents()
    collections = cast(list[dict[str, object]], inventory_document["collections"])
    candidates = cast(list[dict[str, object]], collections[0]["candidates"])
    placements = cast(list[dict[str, object]], candidates[0]["placements"])
    placements[0]["external_scope"] = "lycee/commun/mathematiques"
    inventory_path = tmp_path / "inventory.json"
    inventory_sha = _write_json(inventory_path, inventory_document)

    with pytest.raises(MultilevelEvidenceError, match="collection facts"):
        load_multilevel_candidate_inventory(
            inventory_path, expected_sha256=inventory_sha
        )


def test_currentness_loader_rejects_a_non_official_current_url(
    tmp_path: Path,
) -> None:
    inventory_document, currentness_document = _evidence_documents()
    inventory_path = tmp_path / "inventory.json"
    inventory_sha = _write_json(inventory_path, inventory_document)
    currentness_document["candidate_inventory_sha256"] = inventory_sha
    currentness_document["artifacts"][0]["current_download_url"] = (  # type: ignore[index]
        "https://example.invalid/document.pdf"
    )
    currentness_path = tmp_path / "currentness.json"
    currentness_sha = _write_json(currentness_path, currentness_document)
    inventory = load_multilevel_candidate_inventory(
        inventory_path, expected_sha256=inventory_sha
    )

    with pytest.raises(MultilevelEvidenceError, match="official URL"):
        load_multilevel_currentness(
            currentness_path,
            expected_sha256=currentness_sha,
            candidate_inventory=inventory,
        )


def test_currentness_loader_rejects_listing_url_drift_from_inventory(
    tmp_path: Path,
) -> None:
    inventory_document, currentness_document = _evidence_documents()
    inventory_path = tmp_path / "inventory.json"
    inventory_sha = _write_json(inventory_path, inventory_document)
    currentness_document["candidate_inventory_sha256"] = inventory_sha
    currentness_document["artifacts"][0]["current_source_listing_url"] = (  # type: ignore[index]
        "https://eduscol.education.gouv.fr/another-listing"
    )
    currentness_path = tmp_path / "currentness.json"
    currentness_sha = _write_json(currentness_path, currentness_document)
    inventory = load_multilevel_candidate_inventory(
        inventory_path, expected_sha256=inventory_sha
    )

    with pytest.raises(MultilevelEvidenceError, match="listing URL"):
        load_multilevel_currentness(
            currentness_path,
            expected_sha256=currentness_sha,
            candidate_inventory=inventory,
        )


def test_currentness_loader_rejects_fabricated_positive_facts_on_review(
    tmp_path: Path,
) -> None:
    inventory_document, currentness_document = _evidence_documents()
    inventory_path = tmp_path / "inventory.json"
    inventory_sha = _write_json(inventory_path, inventory_document)
    currentness_document["candidate_inventory_sha256"] = inventory_sha
    currentness_document["artifacts"][2]["current_download_url"] = (  # type: ignore[index]
        "https://eduscol.education.gouv.fr/fabricated.pdf"
    )
    currentness_path = tmp_path / "currentness.json"
    currentness_sha = _write_json(currentness_path, currentness_document)
    inventory = load_multilevel_candidate_inventory(
        inventory_path, expected_sha256=inventory_sha
    )

    with pytest.raises(MultilevelEvidenceError, match="REVIEW_REQUIRED"):
        load_multilevel_currentness(
            currentness_path,
            expected_sha256=currentness_sha,
            candidate_inventory=inventory,
        )


def _profile(*, collection: str, niveau: str, voie: str, programme: str) -> CollectionProfile:
    return CollectionProfile.model_validate(
        {
            "profile_version": "multilevel-v1",
            "enabled": True,
            "scope": {
                "tenant": f"libre_{niveau}",
                "collection": collection,
                "niveau": niveau,
                "voie": voie,
                "matiere": "maths",
                "candidat": "libre",
                "audience": ["libre", "tous"],
                "visibility": "internal",
                "school_year": "2026-2027",
                "programme_version": programme,
            },
            "title": f"Profil {collection}",
            "language": "fr",
            "owner": "Nexus Réussite",
            "expected_topics": ["programme"],
            "expected_resource_types": ["ressource_officielle"],
            "excluded_topics": [],
            "allowed_domains": ["eduscol.education.gouv.fr"],
            "seed_urls": ["https://eduscol.education.gouv.fr/programmes"],
            "source_authority": "official",
            "search_cadence": "manual",
            "max_queries_per_run": 1,
            "max_documents_per_run": 4,
            "max_chunk_size": 800,
            "chunk_overlap": 100,
            "min_source_confidence": 0.9,
            "min_scope_confidence": 0.9,
            "min_extraction_quality": 0.1,
            "reject_unknown_rights": True,
            "reject_ambiguous_routing": True,
            "publication": {"mode": "human_review", "auto_publish": False},
        }
    )


def _resolver(
    tmp_path: Path,
    *,
    mapping: ClosedMultilevelMapping | None = None,
    release_inventory_sha256: str | None = None,
    release_status: str = "tronc_commun",
    release_profile_version: str = "multilevel-v1",
    release_profile_fingerprint: str | None = None,
    release_programme_version: str | None = None,
) -> MultilevelVerifiedPedagogicalPlacementResolver:
    inventory_path, inventory_sha, currentness_path, currentness_sha = (
        _write_evidence(tmp_path)
    )
    inventory = load_multilevel_candidate_inventory(
        inventory_path, expected_sha256=inventory_sha
    )
    currentness = load_multilevel_currentness(
        currentness_path,
        expected_sha256=currentness_sha,
        candidate_inventory=inventory,
    )
    mapping = mapping or ClosedMultilevelMapping(
        levels_sha256="5" * 64,
        subjects_sha256="6" * 64,
        document_types_sha256="7" * 64,
        levels={"4e": Niveau.quatrieme, "seconde": Niveau.seconde},
        subjects={"mathematiques": "maths"},
        document_types={
            "reperes-attendus": TypeDoc.ressource_officielle,
            "programme-officiel": TypeDoc.programme_officiel,
        },
    )
    programmes = {
        "rag_nexus_maths_quatrieme_tc": "PROGRAMME_QUATRIEME",
        "rag_nexus_maths_seconde_tc": "PROGRAMME_SECONDE",
    }
    programme_registry = ProgrammeIndexRegistry(
        sha256="8" * 64,
        school_year="2026-2027",
        index_sha256_by_path={"index.yml": "9" * 64},
        taxonomy_sha256_by_collection={
            collection: "a" * 64 for collection in programmes
        },
        programme_by_collection=programmes,
    )
    profiles = {
        ("rag_nexus_maths_quatrieme_tc", "multilevel-v1"): _profile(
            collection="rag_nexus_maths_quatrieme_tc",
            niveau="quatrieme",
            voie="college",
            programme="PROGRAMME_QUATRIEME",
        ),
        ("rag_nexus_maths_seconde_tc", "multilevel-v1"): _profile(
            collection="rag_nexus_maths_seconde_tc",
            niveau="seconde",
            voie="generale",
            programme="PROGRAMME_SECONDE",
        ),
    }
    profile_manifest = StagingProfileManifestVerification(
        manifest_sha256="b" * 64,
        declared_count=2,
        provenance="test staging",
        generated_at="2026-08-12T00:00:00Z",
        authority_mode="STAGING_LOCAL_GITHUB_ONLY",
        production_approval=False,
    )
    release_eligibility = MultilevelReleaseEligibility(
        manifest_sha256="c" * 64,
        candidate_inventory_sha256=release_inventory_sha256 or inventory.sha256,
        currentness_evidence_sha256=currentness.sha256,
        programme_registry_sha256=programme_registry.sha256,
        profile_manifest_sha256=profile_manifest.manifest_sha256,
        levels_mapping_sha256=mapping.levels_sha256,
        subjects_mapping_sha256=mapping.subjects_sha256,
        document_types_mapping_sha256=mapping.document_types_sha256,
        pii_evidence_sha256="d" * 64,
        pii_policy_sha256="e" * 64,
        rights_registry_sha256="f" * 64,
        embedding_model_id="intfloat/multilingual-e5-large",
        embedding_inventory_sha256="1" * 64,
        embedding_dimension=1024,
        reranker_model_id="cross-encoder/ms-marco-MiniLM-L-6-v2",
        reranker_inventory_sha256="2" * 64,
        placements=frozenset(
            {
                MultilevelReleasePlacement(
                    collection=placement.collection,
                    content_sha256=placement.content_sha256,
                    source_placement_id=placement.source_placement_id,
                    nexus_statut_enseignement=release_status,
                    programme_version=(
                        release_programme_version
                        or str(
                            profiles[(placement.collection, "multilevel-v1")]
                            .scope.programme_version
                        )
                    ),
                    profile_version=release_profile_version,
                    profile_fingerprint=(
                        release_profile_fingerprint
                        or profile_fingerprint(
                            profiles[(placement.collection, "multilevel-v1")]
                        )
                    ),
                    profile_manifest_digest=profile_manifest.manifest_sha256,
                )
                for placement in inventory.placements
            }
        ),
    )
    collection_config = {
        "collections": {
            "rag_nexus_maths_quatrieme_tc": {
                "niveau": "quatrieme",
                "voie": "college",
                "matiere": "maths",
                "statut": "tronc_commun",
                "domain": "education",
            },
            "rag_nexus_maths_seconde_tc": {
                "niveau": "seconde",
                "voie": "generale",
                "matiere": "maths",
                "statut": "tronc_commun",
                "domain": "education",
            },
        }
    }
    return MultilevelVerifiedPedagogicalPlacementResolver.from_authorities(
        candidate_inventory=inventory,
        currentness=currentness,
        mapping=mapping,
        profiles=profiles,
        profile_manifest=profile_manifest,
        environment="rehearsal",
        programme_registry=programme_registry,
        collection_config=collection_config,
        release_eligibility=release_eligibility,
    )


@pytest.mark.parametrize(
    (
        "content_sha256",
        "collection",
        "source_placement_id",
        "expected_niveau",
        "expected_voie",
        "expected_type_doc",
    ),
    [
        (
            "1" * 64,
            "rag_nexus_maths_quatrieme_tc",
            "par-scope/college/cycle-4/mathematiques/4e/fourth.pdf",
            Niveau.quatrieme,
            Voie.college,
            TypeDoc.ressource_officielle,
        ),
        (
            "2" * 64,
            "rag_nexus_maths_seconde_tc",
            "par-scope/lycee/commun/mathematiques/seconde/seconde.pdf",
            Niveau.seconde,
            Voie.generale,
            TypeDoc.programme_officiel,
        ),
    ],
)
def test_resolver_returns_worker_compatible_governed_placement(
    tmp_path: Path,
    content_sha256: str,
    collection: str,
    source_placement_id: str,
    expected_niveau: Niveau,
    expected_voie: Voie,
    expected_type_doc: TypeDoc,
) -> None:
    resolver = _resolver(tmp_path)

    placement = resolver.resolve(
        content_sha256=content_sha256,
        collection=collection,
        profile_version="multilevel-v1",
        school_year="2026-2027",
        source_placement_id=source_placement_id,
        claimed_source_url="https://eduscol.education.gouv.fr/document.pdf",
        claimed_type_doc=expected_type_doc.value,
    )

    assert placement.nexus_collection == collection
    assert placement.nexus_niveau is expected_niveau
    assert placement.nexus_voie is expected_voie
    assert placement.nexus_matiere == "maths"
    assert placement.nexus_statut_enseignement == "tronc_commun"
    assert placement.type_doc is expected_type_doc
    assert placement.source_url == "https://eduscol.education.gouv.fr/document.pdf"
    assert placement.niveau_conformity is True
    assert placement.voie_conformity is True
    assert placement.matiere_conformity is True
    assert placement.programme_conformity is True
    assert resolver.release_manifest_sha256 == "c" * 64


def test_resolver_denies_review_required_even_when_release_allowlist_contains_it(
    tmp_path: Path,
) -> None:
    resolver = _resolver(tmp_path)

    with pytest.raises(MultilevelPlacementResolutionError, match="REVIEW_REQUIRED"):
        resolver.resolve(
            content_sha256="3" * 64,
            collection="rag_nexus_maths_seconde_tc",
            profile_version="multilevel-v1",
            school_year="2026-2027",
            source_placement_id=(
                "par-scope/lycee/commun/mathematiques/seconde/review.pdf"
            ),
        )


def test_resolver_construction_rejects_release_authority_digest_drift(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        MultilevelPlacementResolutionError, match="authority digest differs"
    ):
        _resolver(tmp_path, release_inventory_sha256="d" * 64)


def test_resolver_rejects_collection_teaching_status_drift_from_release(
    tmp_path: Path,
) -> None:
    resolver = _resolver(tmp_path, release_status="specialite")

    with pytest.raises(MultilevelPlacementResolutionError, match="teaching status"):
        resolver.resolve(
            content_sha256="2" * 64,
            collection="rag_nexus_maths_seconde_tc",
            profile_version="multilevel-v1",
            school_year="2026-2027",
        )


@pytest.mark.parametrize(
    ("resolver_kwargs", "message"),
    [
        ({"release_profile_version": "wrong-v1"}, "profile version"),
        ({"release_profile_fingerprint": "f" * 64}, "profile fingerprint"),
        ({"release_programme_version": "WRONG_PROGRAMME"}, "programme version"),
    ],
)
def test_resolver_rejects_release_profile_or_programme_drift(
    tmp_path: Path,
    resolver_kwargs: dict[str, str],
    message: str,
) -> None:
    resolver = _resolver(tmp_path, **resolver_kwargs)

    with pytest.raises(MultilevelPlacementResolutionError, match=message):
        resolver.resolve(
            content_sha256="2" * 64,
            collection="rag_nexus_maths_seconde_tc",
            profile_version="multilevel-v1",
            school_year="2026-2027",
        )


def test_resolver_rejects_an_unknown_external_mapping(tmp_path: Path) -> None:
    mapping = ClosedMultilevelMapping(
        levels_sha256="5" * 64,
        subjects_sha256="6" * 64,
        document_types_sha256="7" * 64,
        levels={"seconde": Niveau.seconde},
        subjects={"mathematiques": "maths"},
        document_types={
            "reperes-attendus": TypeDoc.ressource_officielle,
            "programme-officiel": TypeDoc.programme_officiel,
        },
    )
    resolver = _resolver(tmp_path, mapping=mapping)

    with pytest.raises(MultilevelPlacementResolutionError, match="external level"):
        resolver.resolve(
            content_sha256="1" * 64,
            collection="rag_nexus_maths_quatrieme_tc",
            profile_version="multilevel-v1",
            school_year="2026-2027",
        )


@pytest.mark.parametrize(
    ("claim", "message"),
    [
        ({"claimed_source_path": "01_EDUSCOL_OFFICIEL/wrong.pdf"}, "source path"),
        ({"claimed_source_url": "https://eduscol.education.gouv.fr/programmes"}, "source URL"),
        ({"claimed_type_doc": "diaporama"}, "document type"),
    ],
)
def test_resolver_rejects_payload_claim_drift(
    tmp_path: Path, claim: dict[str, str], message: str
) -> None:
    resolver = _resolver(tmp_path)

    with pytest.raises(MultilevelPlacementResolutionError, match=message):
        resolver.resolve(
            content_sha256="2" * 64,
            collection="rag_nexus_maths_seconde_tc",
            profile_version="multilevel-v1",
            school_year="2026-2027",
            **claim,
        )


def test_resolver_runtime_contains_no_content_sha_allowlist() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "ingestor"
        / "multilevel_verified_placement.py"
    ).read_text(encoding="utf-8")

    assert re.findall(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", source) == []
    for field in (
        "niveau_conformity",
        "voie_conformity",
        "matiere_conformity",
        "programme_conformity",
    ):
        assert f"{field}=True" not in source


def test_real_multilevel_release_loader_has_exact_final_counts() -> None:
    expectation = load_release_expectation(
        _REAL_MULTILEVEL_RELEASE,
        _REAL_MULTILEVEL_RELEASE_SHA256,
    )
    eligibility = load_multilevel_release_eligibility(
        _REAL_MULTILEVEL_RELEASE,
        expected_sha256=_REAL_MULTILEVEL_RELEASE_SHA256,
    )

    assert len(expectation.collections) == 10
    assert sum(len(item.placements) for item in expectation.artifacts) == 11
    assert sum(len(item.chunks) for item in expectation.artifacts) == 359
    assert len(eligibility.placements) == 11
    assert eligibility.manifest_sha256 == _REAL_MULTILEVEL_RELEASE_SHA256
    assert {item.profile_version for item in eligibility.placements} == {
        "multilevel-v1"
    }
    assert all(item.profile_fingerprint for item in eligibility.placements)
    assert {
        item.profile_manifest_digest for item in eligibility.placements
    } == {eligibility.profile_manifest_sha256}
    assert all(item.programme_version for item in eligibility.placements)
