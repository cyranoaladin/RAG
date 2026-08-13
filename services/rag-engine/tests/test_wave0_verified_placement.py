"""Wave 0 : release artifact-bound et placement pédagogique gouverné."""
from __future__ import annotations

import hashlib
import inspect
import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import yaml
from nexus_contracts.document import Niveau, TypeDoc, Voie
from nexus_contracts.ingestion import CollectionProfile

from ingestor.ingestion_profiles.manifest import verify_profile_manifest
from ingestor.ingestion_profiles.registry import load_profile_registry
from ingestor.ingestion_profiles.registry import profile_fingerprint as compute_profile_fingerprint
from ingestor.verified_pedagogical_placement import (
    PlacementResolutionError,
    VerifiedPedagogicalPlacementResolver,
    to_eligible_placement,
)

MANIFEST_SHA = "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
PROGRAMME_VERSION = "BOEN_special_11_2018-07-26_aj_2020"
PLACEMENT_CATALOG_SHA = "095ca37cc4c2126d06b77106f9f1663d4f5ad881ae4952dbf5b951477fd54c39"
FR_SHA = "c8662b03ca8a7f08bedad5081bafc7da8d2cc8a31b07fa967421fb15304d76bf"
FR_PATH = (
    "01_EDUSCOL_OFFICIEL/COLLEGE/3E/FRANCAIS/02_REPERES_ATTENDUS/2019/"
    "attendus-de-fin-d-annee-en-francais-en-3e-pdf-971-01-ko--c8662b03ca.pdf"
)
MATHS_SHA = "49ccdca4d97ba4cf25875dfc731474e84d0332985c15396d3abfb9107f5f545a"
MATHS_PATH = (
    "01_EDUSCOL_OFFICIEL/COLLEGE/3E/MATHEMATIQUES/02_REPERES_ATTENDUS/2019/"
    "attendus-de-fin-d-annee-en-mathematiques-en-3e-pdf-1-26-mo--49ccdca4d9.pdf"
)
FR_SOURCE_URL = (
    "https://eduscol.education.gouv.fr/5733/"
    "ressources-d-accompagnement-du-programme-de-francais-au-cycle-4"
)
FR_PLACEMENT_ID = (
    "par-scope/college/cycle-4/francais/3e/reperes-attendus/2019/"
    "attendus-de-fin-d-annee-en-francais-en-3e-pdf-971-01-ko--c8662b03ca.pdf"
)
COLLECTION = "rag_nexus_francais_troisieme_tc"
PROFILE_VERSION = "wave0-v1"
ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ENGINE_ROOT.parents[1]
STAGING_PROFILES_DIR = ENGINE_ROOT / "configs" / "ingestion_profiles" / "staging"
STAGING_PROFILE_MANIFEST = ENGINE_ROOT / "configs" / "ingestion_manifest_wave0_staging.yml"
PROGRAMME_INDEX = REPOSITORY_ROOT / "corpus" / "College" / "Troisieme" / "_index.yml"
PROGRAMME_INDEX_SHA = "d5b2bbfe97d0a2e8b85f446c2d3f862798d03db4f8cf48a22cf22e1cb4da0f45"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _profile() -> CollectionProfile:
    return CollectionProfile.model_validate(
        {
            "profile_version": PROFILE_VERSION,
            "enabled": True,
            "scope": {
                "tenant": "libre_troisieme",
                "collection": COLLECTION,
                "niveau": "troisieme",
                "voie": "college",
                "matiere": "francais",
                "candidat": "libre",
                "audience": ["libre", "tous"],
                "visibility": "internal",
                "school_year": "2026-2027",
                "programme_version": PROGRAMME_VERSION,
            },
            "title": "Français 3e — attendus Wave 0",
            "owner": "Nexus Réussite",
            "expected_topics": ["lecture", "écriture", "oral", "langue"],
            "expected_resource_types": ["ressource_officielle"],
            "allowed_domains": ["eduscol.education.gouv.fr"],
            "seed_urls": [FR_SOURCE_URL],
            "source_authority": "official",
            "search_cadence": "manual",
            "max_queries_per_run": 1,
            "max_documents_per_run": 1,
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


def _catalog() -> dict[str, Any]:
    placement = {
        "classified": True,
        "content_sha256": FR_SHA,
        "document_type": "reperes-attendus",
        "family": "college-cycle-4",
        "level": "3e",
        "scope": "college/cycle-4/francais",
        "scope_path": (
            "par-scope/college/cycle-4/francais/3e/reperes-attendus/2019/"
            "attendus-de-fin-d-annee-en-francais-en-3e-pdf-971-01-ko--c8662b03ca.pdf"
        ),
        "source_url": FR_SOURCE_URL,
        "status": "transition-ou-actuel",
        "subject": "francais",
        "title": "Attendus de fin d'année en français en 3e",
        "year": "2019",
    }
    return {
        "catalog_kind": "REAL_SEALED_CORPUS",
        "manifest_sha256": MANIFEST_SHA,
        "placement_catalog_sha256": PLACEMENT_CATALOG_SHA,
        "verification_passed": True,
        "artifacts": {
            FR_SHA: {
                "sha256": FR_SHA,
                "pedagogical_placement_count": 1,
                "pedagogical_placements": [placement],
                "physical_object_count": 1,
                "physical_objects": [
                    {
                        "base_disposition": "REVIEW_REQUIRED",
                        "content_sha256": FR_SHA,
                        "currentness": "unclassified",
                        "disposition": "REVIEW_REQUIRED",
                        "path": FR_PATH,
                    }
                ],
            }
        },
    }


def _inventory() -> dict[str, Any]:
    placement = _catalog()["artifacts"][FR_SHA]["pedagogical_placements"][0]
    return {
        "inventory_kind": "WAVE0_EXACT_GRADE_CANDIDATE_INVENTORY_V1",
        "school_year": "2026-2027",
        "corpus_manifest_sha256": MANIFEST_SHA,
        "sealed_catalog_sha256": "catalog digest is injected by _write_inputs",
        "placement_catalog_sha256": PLACEMENT_CATALOG_SHA,
        "selection": {
            "external_level": "3e",
            "external_subjects": ["francais", "mathematiques", "maths"],
            "source_zone": "01_EDUSCOL_OFFICIEL/",
            "media_type": "application/pdf",
        },
        "counts": {
            "unique_artifacts": 1,
            "placements": 1,
            "physical_objects": 1,
            "multi_placement_artifacts": 0,
        },
        "candidates": [
            {
                "content_sha256": FR_SHA,
                "physical_path": FR_PATH,
                "source_url": FR_SOURCE_URL,
                "title": placement["title"],
                "source_placement_id": placement["scope_path"],
                "external_scope": placement["scope"],
                "external_level": placement["level"],
                "external_subject": placement["subject"],
                "external_document_type": placement["document_type"],
                "pedagogical_status": placement["status"],
                "physical_currentness_candidate": "unclassified",
                "physical_disposition_candidate": "REVIEW_REQUIRED",
            }
        ],
    }


def _evidence(*, inventory_sha: str) -> dict[str, Any]:
    return {
        "evidence_kind": "WAVE0_ARTIFACT_CURRENTNESS_V2",
        "school_year": "2026-2027",
        "corpus_manifest_sha256": MANIFEST_SHA,
        "candidate_inventory_sha256": inventory_sha,
        "decision": {
            "decision_maker": "Nexus Réussite",
            "decision_source": "EXPLICIT_PEDAGOGICAL_DECISION",
            "decided_at": "2026-08-12T09:54:44Z",
            "scope": "Wave 0 pre-rentree 2026-2027",
        },
        "regulatory_basis": {
            "new_cycle4_program_3e_effective_school_year": "2028-2029"
        },
        "artifacts": [
            {
                "content_sha256": FR_SHA,
                "exact_path": FR_PATH,
                "external_level": "3e",
                "subject": "francais",
                "effective_currentness": "actuel",
                "current_for_school_year": "2026-2027",
                "current_source_listing_url": FR_SOURCE_URL,
                "current_download_url": "https://eduscol.education.fr/document/14062/download",
                "current_download_sha256": FR_SHA,
                "byte_identity": True,
            },
        ],
    }


def _mapping() -> dict[str, Any]:
    return {
        "mapping_kind": "EDUSCOL_WAVE0_PEDAGOGICAL_MAPPING_V1",
        "pedagogical_mappings": [
            {
                "external_level": "3e",
                "external_scope": "college/cycle-4/francais",
                "external_subject": "francais",
                "nexus_collection": COLLECTION,
                "nexus_niveau": "troisieme",
                "nexus_voie": "college",
                "nexus_matiere": "francais",
                "nexus_statut_enseignement": "tronc_commun",
            }
        ],
        "document_types": {"reperes-attendus": "ressource_officielle"},
    }


def _release(*, inventory_sha: str, currentness_sha: str) -> dict[str, Any]:
    return {
        "release_kind": "WAVE0_SUBJECT_RELEASE_V1",
        "release_id": "wave0-francais-troisieme-2026-2027",
        "school_year": "2026-2027",
        "collection": COLLECTION,
        "authorities": {
            "corpus_manifest_sha256": MANIFEST_SHA,
            "sealed_catalog_sha256": "catalog digest is injected by _write_inputs",
            "placement_catalog_sha256": PLACEMENT_CATALOG_SHA,
            "candidate_inventory_sha256": inventory_sha,
            "currentness_evidence_sha256": currentness_sha,
            "pii_evidence_sha256": "4" * 64,
            "pii_policy_sha256": "5" * 64,
            "rights_registry_sha256": "6" * 64,
        },
        "programme_version": PROGRAMME_VERSION,
        "profile": {
            "version": PROFILE_VERSION,
            "fingerprint": compute_profile_fingerprint(_profile()),
            "manifest_digest": "8" * 64,
        },
        "models": {
            "embedding": {
                "model_id": "intfloat/multilingual-e5-large",
                "inventory_sha256": "9" * 64,
                "dimension": 1024,
            },
            "reranker": {
                "model_id": "cross-encoder/ms-marco-MiniLM-L-6-v2",
                "inventory_sha256": "a" * 64,
            },
        },
        "expected_counts": {"artifacts": 1, "placements": 1, "chunks": 1},
        "artifacts": [
            {
                "content_sha256": FR_SHA,
                "source_path": FR_PATH,
                "placements": [
                    {
                        "source_placement_id": FR_PLACEMENT_ID,
                        "collection": COLLECTION,
                    }
                ],
                "chunks": [{"chunk_id": "b" * 64}],
            }
        ],
    }


def _collections() -> dict[str, Any]:
    return {
        "collections": {
            COLLECTION: {
                "matiere": "francais",
                "niveau": "troisieme",
                "voie": "college",
                "statut": "tronc_commun",
                "domain": "education",
                "taxonomy_file": "francais/troisieme.yml",
                "instanciee": False,
            }
        }
    }


def _write_inputs(
    tmp_path: Path,
    *,
    catalog: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    inventory: dict[str, Any] | None = None,
    mapping: dict[str, Any] | None = None,
    release: dict[str, Any] | None = None,
) -> dict[str, Path | str]:
    catalog_path = tmp_path / "h2e_governed_catalog.json"
    catalog_path.write_text(
        json.dumps(catalog or _catalog(), sort_keys=True), encoding="utf-8"
    )
    catalog_sha = _sha(catalog_path)
    inventory_document = deepcopy(inventory or _inventory())
    inventory_document["sealed_catalog_sha256"] = catalog_sha
    inventory_path = tmp_path / "wave0_candidate_inventory.json"
    inventory_path.write_text(
        json.dumps(inventory_document, sort_keys=True), encoding="utf-8"
    )
    inventory_sha = _sha(inventory_path)
    evidence_document = deepcopy(evidence or _evidence(inventory_sha=inventory_sha))
    evidence_document["candidate_inventory_sha256"] = inventory_sha
    evidence_path = tmp_path / "wave0_currentness_evidence_v2.yml"
    evidence_path.write_text(
        yaml.safe_dump(evidence_document, sort_keys=False), encoding="utf-8"
    )
    evidence_sha = _sha(evidence_path)
    mapping_path = tmp_path / "eduscol_wave0_document_types.yml"
    mapping_path.write_text(
        yaml.safe_dump(mapping or _mapping(), sort_keys=False), encoding="utf-8"
    )
    release_document = deepcopy(
        release
        or _release(inventory_sha=inventory_sha, currentness_sha=evidence_sha)
    )
    release_document["authorities"]["sealed_catalog_sha256"] = catalog_sha
    release_document["authorities"]["candidate_inventory_sha256"] = inventory_sha
    release_document["authorities"]["currentness_evidence_sha256"] = evidence_sha
    subject_path = tmp_path / "francais_troisieme.release.json"
    subject_path.write_text(json.dumps(release_document, sort_keys=True), encoding="utf-8")
    subject_sha = _sha(subject_path)
    aggregate_document = {
        "release_kind": "WAVE0_AGGREGATE_RELEASE_V1",
        "release_id": "wave0-exact-grade-troisieme-2026-2027-v1",
        "school_year": "2026-2027",
        "authorities": release_document["authorities"],
        "models": release_document["models"],
        "expected_counts": release_document["expected_counts"],
        "subjects": [
            {
                "collection": COLLECTION,
                "path": subject_path.name,
                "sha256": subject_sha,
            }
        ],
    }
    release_path = tmp_path / "wave0.release.json"
    release_path.write_text(json.dumps(aggregate_document, sort_keys=True), encoding="utf-8")
    return {
        "catalog_path": catalog_path,
        "catalog_sha": catalog_sha,
        "inventory_path": inventory_path,
        "inventory_sha": inventory_sha,
        "evidence_path": evidence_path,
        "evidence_sha": evidence_sha,
        "mapping_path": mapping_path,
        "mapping_sha": _sha(mapping_path),
        "release_path": release_path,
        "release_sha": _sha(release_path),
    }


def _resolver(
    tmp_path: Path,
    *,
    catalog: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    inventory: dict[str, Any] | None = None,
    mapping: dict[str, Any] | None = None,
    release: dict[str, Any] | None = None,
    profile: CollectionProfile | None = None,
) -> VerifiedPedagogicalPlacementResolver:
    inputs = _write_inputs(
        tmp_path,
        catalog=catalog,
        evidence=evidence,
        inventory=inventory,
        mapping=mapping,
        release=release,
    )
    selected_profile = profile or _profile()
    return VerifiedPedagogicalPlacementResolver.load(
        catalog_path=Path(inputs["catalog_path"]),
        expected_catalog_sha256=str(inputs["catalog_sha"]),
        candidate_inventory_path=Path(inputs["inventory_path"]),
        expected_candidate_inventory_sha256=str(inputs["inventory_sha"]),
        currentness_evidence_path=Path(inputs["evidence_path"]),
        expected_currentness_evidence_sha256=str(inputs["evidence_sha"]),
        mapping_path=Path(inputs["mapping_path"]),
        expected_mapping_sha256=str(inputs["mapping_sha"]),
        release_manifest_path=Path(inputs["release_path"]),
        expected_release_manifest_sha256=str(inputs["release_sha"]),
        expected_manifest_sha256=MANIFEST_SHA,
        profile_registry={(COLLECTION, PROFILE_VERSION): selected_profile},
        collection_config=_collections(),
        programme_index_path=PROGRAMME_INDEX,
        expected_programme_index_sha256=PROGRAMME_INDEX_SHA,
    )


def test_profile_programme_must_match_canonical_troisieme_index(
    tmp_path: Path,
) -> None:
    raw_profile = _profile().model_dump(mode="json")
    raw_profile["scope"]["programme_version"] = "BOEN_2018"
    divergent = CollectionProfile.model_validate(raw_profile)

    with pytest.raises(PlacementResolutionError, match="runtime profile"):
        _resolver(tmp_path, profile=divergent).resolve(
            content_sha256=FR_SHA,
            collection=COLLECTION,
            profile_version=PROFILE_VERSION,
            school_year="2026-2027",
        )


def test_resolves_french_external_3e_to_canonical_nexus_placement(tmp_path: Path) -> None:
    placement = _resolver(tmp_path).resolve(
        content_sha256=FR_SHA,
        collection=COLLECTION,
        profile_version=PROFILE_VERSION,
        school_year="2026-2027",
    )

    assert placement.source_path == FR_PATH
    assert placement.source_url == FR_SOURCE_URL
    assert placement.external_level == "3e"
    assert placement.external_scope == "college/cycle-4/francais"
    assert placement.effective_currentness == "actuel"
    assert placement.nexus_collection == COLLECTION
    assert placement.nexus_niveau is Niveau.troisieme
    assert placement.nexus_voie is Voie.college
    assert placement.nexus_matiere == "francais"
    assert placement.nexus_statut_enseignement == "tronc_commun"
    assert placement.nexus_programme_version == _profile().scope.programme_version
    assert placement.nexus_scope == _profile().scope
    assert placement.type_doc is TypeDoc.ressource_officielle
    assert placement.niveau_conformity is True
    assert placement.voie_conformity is True
    assert placement.matiere_conformity is True
    assert placement.programme_conformity is True
    assert len(placement.profile_fingerprint) == 64
    assert placement.corpus_manifest_sha256 == MANIFEST_SHA
    assert placement.source_placement_id.startswith("par-scope/")
    assert placement.placement_catalog_sha256 == PLACEMENT_CATALOG_SHA
    assert len(placement.currentness_evidence_sha256) == 64


def test_converts_verified_placement_with_profile_manifest_not_corpus_manifest(
    tmp_path: Path,
) -> None:
    placement = _resolver(tmp_path).resolve(
        content_sha256=FR_SHA,
        collection=COLLECTION,
        profile_version=PROFILE_VERSION,
        school_year="2026-2027",
    )
    profile_manifest_digest = "a" * 64

    eligible = to_eligible_placement(
        placement,
        resource_id=UUID("00000000-0000-0000-0000-000000000123"),
        current_profile_manifest_digest=profile_manifest_digest,
    )

    assert eligible.scope == placement.nexus_scope
    assert eligible.source_path == FR_PATH
    assert eligible.source_uri == FR_SOURCE_URL
    assert eligible.current_profile_fingerprint == placement.profile_fingerprint
    assert eligible.current_manifest_digest == profile_manifest_digest
    assert eligible.current_manifest_digest != placement.corpus_manifest_sha256
    assert eligible.currentness == "current"


def test_versioned_wave0_profiles_are_isolated_in_staging_registry() -> None:
    registry = load_profile_registry(STAGING_PROFILES_DIR)

    assert set(registry) == {
        ("rag_nexus_francais_troisieme_tc", PROFILE_VERSION),
        ("rag_nexus_maths_troisieme_tc", PROFILE_VERSION),
    }
    assert all(profile.enabled for profile in registry.values())
    assert all(profile.scope.school_year == "2026-2027" for profile in registry.values())
    assert all(
        profile.scope.programme_version == PROGRAMME_VERSION
        for profile in registry.values()
    )


def test_wave0_staging_manifest_binds_the_exact_two_profile_fingerprints() -> None:
    registry = load_profile_registry(STAGING_PROFILES_DIR)

    verification = verify_profile_manifest(registry, STAGING_PROFILE_MANIFEST)

    assert verification.declared_count == 2
    assert len(verification.manifest_fingerprint) == 64
    assert set(verification.authorities) == set(registry)


def test_payload_source_path_is_only_an_equality_claim(tmp_path: Path) -> None:
    resolver = _resolver(tmp_path)
    with pytest.raises(PlacementResolutionError, match="claimed source path"):
        resolver.resolve(
            content_sha256=FR_SHA,
            collection=COLLECTION,
            profile_version=PROFILE_VERSION,
            school_year="2026-2027",
            claimed_source_path="https://eduscol.education.gouv.fr/document/14062/download",
        )


@pytest.mark.parametrize(
    ("claimed_source_url", "claimed_type_doc", "message"),
    [
        ("https://eduscol.education.gouv.fr/other", "ressource_officielle", "source URL"),
        (FR_SOURCE_URL, "programme_officiel", "document type"),
    ],
)
def test_candidate_claims_must_match_governed_placement(
    tmp_path: Path,
    claimed_source_url: str,
    claimed_type_doc: str,
    message: str,
) -> None:
    with pytest.raises(PlacementResolutionError, match=message):
        _resolver(tmp_path).resolve(
            content_sha256=FR_SHA,
            collection=COLLECTION,
            profile_version=PROFILE_VERSION,
            school_year="2026-2027",
            claimed_source_url=claimed_source_url,
            claimed_type_doc=claimed_type_doc,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda e: e.update(school_year="2027-2028"), "school year"),
        (lambda e: e.update(corpus_manifest_sha256="a" * 64), "manifest"),
        (
            lambda e: e["artifacts"][0].update(content_sha256="not-a-sha"),
            "SHA",
        ),
        (lambda e: e["artifacts"][0].update(exact_path=""), "path"),
        (
            lambda e: e["artifacts"][0].update(effective_currentness="transition"),
            "currentness",
        ),
    ],
    ids=("wrong-year", "wrong-manifest", "invalid-sha", "empty-path", "not-current"),
)
def test_currentness_evidence_fails_closed(
    tmp_path: Path, mutation: Any, message: str
) -> None:
    evidence = _evidence(inventory_sha="0" * 64)
    mutation(evidence)
    with pytest.raises(PlacementResolutionError, match=message):
        _resolver(tmp_path, evidence=evidence)


def test_currentness_school_year_must_equal_candidate_inventory_year(
    tmp_path: Path,
) -> None:
    evidence = _evidence(inventory_sha="0" * 64)
    evidence["school_year"] = "2027-2028"
    for artifact in evidence["artifacts"]:
        artifact["current_for_school_year"] = "2027-2028"

    with pytest.raises(PlacementResolutionError, match="candidate inventory school year"):
        _resolver(tmp_path, evidence=evidence)


def test_duplicate_currentness_sha_is_rejected(tmp_path: Path) -> None:
    evidence = _evidence(inventory_sha="0" * 64)
    evidence["artifacts"].append(deepcopy(evidence["artifacts"][0]))
    with pytest.raises(PlacementResolutionError, match="twice"):
        _resolver(tmp_path, evidence=evidence)


def test_currentness_overlay_rejects_an_unrelated_third_artifact(tmp_path: Path) -> None:
    evidence = _evidence(inventory_sha="0" * 64)
    unrelated = deepcopy(evidence["artifacts"][0])
    unrelated["content_sha256"] = "b" * 64
    unrelated["current_download_sha256"] = "b" * 64
    unrelated["exact_path"] = "01_EDUSCOL_OFFICIEL/unrelated.pdf"
    evidence["artifacts"].append(unrelated)

    with pytest.raises(PlacementResolutionError, match="candidate inventory"):
        _resolver(tmp_path, evidence=evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("exact_path", "01_EDUSCOL_OFFICIEL/wrong.pdf"),
        ("subject", "mathematiques"),
        ("external_level", "4e"),
    ],
)
def test_currentness_must_match_catalog_placement(
    tmp_path: Path, field: str, value: str
) -> None:
    evidence = _evidence(inventory_sha="0" * 64)
    evidence["artifacts"][0][field] = value
    with pytest.raises(PlacementResolutionError, match="candidate inventory|catalog"):
        _resolver(tmp_path, evidence=evidence)


def test_unrelated_artifact_remains_unresolved(tmp_path: Path) -> None:
    with pytest.raises(PlacementResolutionError, match="release-eligible"):
        _resolver(tmp_path).resolve(
            content_sha256="b" * 64,
            collection=COLLECTION,
            profile_version=PROFILE_VERSION,
            school_year="2026-2027",
        )


def test_requires_a_matching_physical_object(tmp_path: Path) -> None:
    catalog = _catalog()
    artifact = catalog["artifacts"][FR_SHA]
    artifact["physical_objects"] = []
    artifact["physical_object_count"] = 0
    with pytest.raises(PlacementResolutionError, match="physical object"):
        _resolver(tmp_path, catalog=catalog).resolve(
            content_sha256=FR_SHA,
            collection=COLLECTION,
            profile_version=PROFILE_VERSION,
            school_year="2026-2027",
        )


def test_runtime_resolver_contains_no_pilot_sha_special_case() -> None:
    source = inspect.getsource(
        __import__(
            "ingestor.verified_pedagogical_placement", fromlist=["unused"]
        )
    )

    assert FR_SHA not in source
    assert MATHS_SHA not in source
    assert "_WAVE0_CURRENTNESS_SCOPE" not in source
    assert "_MAPPINGS" not in source


def test_unknown_external_document_type_is_denied_at_startup(tmp_path: Path) -> None:
    mapping = _mapping()
    mapping["document_types"] = {"programme": "programme_officiel"}

    with pytest.raises(PlacementResolutionError, match="document type"):
        _resolver(tmp_path, mapping=mapping)


def test_multi_placement_artifact_requires_exact_placement_identity(
    tmp_path: Path,
) -> None:
    catalog = _catalog()
    second = deepcopy(catalog["artifacts"][FR_SHA]["pedagogical_placements"][0])
    second["scope_path"] = f"{FR_PLACEMENT_ID}.second"
    catalog["artifacts"][FR_SHA]["pedagogical_placements"].append(second)
    catalog["artifacts"][FR_SHA]["pedagogical_placement_count"] = 2

    inventory = _inventory()
    second_candidate = deepcopy(inventory["candidates"][0])
    second_candidate["source_placement_id"] = second["scope_path"]
    inventory["candidates"].append(second_candidate)
    inventory["counts"]["placements"] = 2
    inventory["counts"]["multi_placement_artifacts"] = 1

    # Les digests sont injectés par le helper : seule la forme métier compte ici.
    placeholder_inventory_sha = "0" * 64
    placeholder_currentness_sha = "1" * 64
    release = _release(
        inventory_sha=placeholder_inventory_sha,
        currentness_sha=placeholder_currentness_sha,
    )
    release["artifacts"][0]["placements"].append(
        {"source_placement_id": second["scope_path"], "collection": COLLECTION}
    )
    release["expected_counts"]["placements"] = 2
    resolver = _resolver(
        tmp_path, catalog=catalog, inventory=inventory, release=release
    )

    with pytest.raises(PlacementResolutionError, match="ambiguous"):
        resolver.resolve(
            content_sha256=FR_SHA,
            collection=COLLECTION,
            profile_version=PROFILE_VERSION,
            school_year="2026-2027",
        )

    verified = resolver.resolve(
        content_sha256=FR_SHA,
        collection=COLLECTION,
        profile_version=PROFILE_VERSION,
        school_year="2026-2027",
        source_placement_id=second["scope_path"],
    )
    assert verified.source_placement_id == second["scope_path"]
