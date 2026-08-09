"""H2-C : résolution fail-closed des placements du corpus initial réel."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from ingestor.collection_config import load_collection_config
from ingestor.h2c_placement_readiness import (
    AuthorityReadinessReport,
    PlacementReadinessError,
    compile_initial_placement_readiness,
    finalize_initial_authority,
    load_initial_placement_policy,
)
from ingestor.ingestion_control.scope_authority import VerifiedAuthorization
from ingestor.ingestion_profiles.manifest import verify_profile_manifest
from ingestor.ingestion_profiles.registry import load_profile_registry

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parents[1]
POLICY_PATH = ENGINE_ROOT / "configs" / "h2_initial_placement_policy.yml"
COLLECTIONS_PATH = ENGINE_ROOT / "configs" / "rag_collections.yml"
PROFILES_DIR = ENGINE_ROOT / "configs" / "ingestion_profiles"
MANIFEST_PATH = ENGINE_ROOT / "configs" / "ingestion_manifest.yml"
TERMINALE_INDEX_PATH = (
    REPO_ROOT / "corpus" / "Lycee" / "Terminale" / "Tronc_commun" / "_index.yml"
)
PHILOSOPHIE_CARD_PATH = TERMINALE_INDEX_PATH.with_name("T_PHILOSOPHIE.md")
PROGRAMME_REGISTRY_PATH = (
    REPO_ROOT
    / "services"
    / "rag-pedago"
    / "data"
    / "programmes"
    / "registre_programmes.yml"
)

MANIFEST_SHA = "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
PII_EVIDENCE_SHA = "76e6ba3cd5b1c116c8647b611eb3fdeb2aba6b8c7fdfbad9e71048354956f311"
SAFE_SHA = "03f268dc1f2628dbc76c58921ed868624437f06a15432ea055fff844f12aaf91"
QUARANTINE_SHA = "b81201b857c67e4e928a079cfe9d5b9b402537d0101bfccc730465631d5e8376"


def _placement(*, sha: str, scope: str, classified: bool = False) -> dict[str, object]:
    return {
        "classified": classified,
        "content_sha256": sha,
        "document_type": "programme-officiel",
        "family": "lycee-terminal",
        "level": "non-classe",
        "scope": scope,
        "source_url": "https://eduscol.education.gouv.fr/5826/programmes-et-ressources-en-philosophie-voie-gt",
        "status": "actuel",
        "subject": "philosophie",
        "title": "Ressource de philosophie",
        "year": "2020",
    }


def _artifact(
    *, sha: str, placements: list[dict[str, object]], pii: str = "PASS"
) -> dict[str, object]:
    return {
        "sha256": sha,
        "pedagogical_placement_count": len(placements),
        "pedagogical_placements": placements,
        "physical_object_count": 1,
        "physical_objects": [
            {
                "base_disposition": "INGEST",
                "content_sha256": sha,
                "currentness": "actuel",
                "disposition": "REVIEW_REQUIRED" if pii == "PASS" else "QUARANTINE",
                "gate_statuses": {
                    "authority": "BLOCKED_NOT_CLEARED",
                    "pii": pii,
                    "rights": "PASS",
                },
                "path": f"01_EDUSCOL_OFFICIEL/{sha}.pdf",
            }
        ],
    }


def _catalog() -> dict[str, object]:
    unknown_sha = "1" * 64
    return {
        "catalog_kind": "REAL_SEALED_CORPUS",
        "manifest_sha256": MANIFEST_SHA,
        "physical_object_count": 3,
        "eduscol_placements_unclassified": 3,
        "artifacts": {
            SAFE_SHA: _artifact(
                sha=SAFE_SHA,
                placements=[_placement(sha=SAFE_SHA, scope="lycee/terminal/philosophie")],
            ),
            unknown_sha: _artifact(
                sha=unknown_sha,
                placements=[_placement(sha=unknown_sha, scope="lycee/commun/philosophie")],
            ),
            QUARANTINE_SHA: _artifact(
                sha=QUARANTINE_SHA,
                pii="BLOCKED_PII_DETECTED",
                placements=[_placement(sha=QUARANTINE_SHA, scope="lycee/commun/francais")],
            ),
        },
    }


def _single_artifact_policy():
    policy = load_initial_placement_policy(POLICY_PATH)
    return replace(policy, approved_artifacts={SAFE_SHA: policy.approved_artifacts[SAFE_SHA]})


def _placement_readiness():
    return compile_initial_placement_readiness(
        _catalog(),
        _single_artifact_policy(),
        load_collection_config(COLLECTIONS_PATH),
    )


def _authorization(**overrides: Any) -> VerifiedAuthorization:
    now = datetime.now(UTC)
    profile = load_profile_registry(PROFILES_DIR)[
        ("rag_nexus_philo_terminale_tc", "h2c-v1")
    ]
    defaults: dict[str, Any] = {
        "authorization_id": "h2-staging-philosophie-v2",
        "scope": profile.scope,
        "manifest_digest": MANIFEST_SHA,
        "profile_id": "rag_nexus_philo_terminale_tc",
        "profile_version": "h2c-v1",
        "profile_fingerprint": "a" * 64,
        "allowed_domains": ("eduscol.education.gouv.fr",),
        "rights_categories": ("officiel_public",),
        "exclusions": (),
        "pii_absence_attested": True,
        "valid_from": now - timedelta(days=1),
        "valid_until": now + timedelta(days=1),
        "artifact_path": "governance/authorizations/h2-staging-philosophie-v2.json",
        "artifact_blob_sha": "b" * 40,
        "authorization_digest": "c" * 64,
        "evidence_repository": "cyranoaladin/RAG",
        "evidence_pull_request": 999,
        "evidence_base_sha": "d" * 40,
        "evidence_head_sha": "e" * 40,
        "evidence_review_id": 1,
        "evidence_reviewer": "abenrhouma",
        "evidence_challenge": "NEXUS-TRUSTED-REVIEW-V1:" + "f" * 64,
        "verified_at": now,
        "protocol_version": "LOT41A-V2",
        "allowed_content_sha256": (SAFE_SHA,),
    }
    defaults.update(overrides)
    return VerifiedAuthorization(**defaults)


def test_policy_resolves_only_exact_allowlisted_placement() -> None:
    policy = _single_artifact_policy()
    config = load_collection_config(COLLECTIONS_PATH)

    report = compile_initial_placement_readiness(_catalog(), policy, config)

    assert report.base_candidate_artifacts == 3
    assert report.pii_cleared_artifacts == 2
    assert report.initial_candidate_placements == 3
    assert report.initial_cleared_placements == 2
    assert report.eligible_artifacts == (SAFE_SHA,)
    assert report.eligible_placements == 1
    assert report.placement_blocked_artifacts == 1
    assert report.placements_collection_resolved == 1
    assert report.placements_collection_unresolved == 0
    assert report.required_collections == ("rag_nexus_philo_terminale_tc",)
    assert report.required_collections_instantiated == 1
    assert report.required_collections_not_instantiated == ()
    assert report.ingested_placements_with_unknown_scope == 0
    assert QUARANTINE_SHA not in report.eligible_artifacts


def test_v2_authority_finalizes_only_exact_placement_ready_sha() -> None:
    report = finalize_initial_authority(
        _placement_readiness(),
        _single_artifact_policy(),
        _authorization(),
    )

    assert isinstance(report, AuthorityReadinessReport)
    assert report.protocol_state == "LOT41A-V2"
    assert report.placement_ready_artifacts == (SAFE_SHA,)
    assert report.placement_ready_count == 1
    assert report.authorized_artifacts == (SAFE_SHA,)
    assert report.authorized_count == 1
    assert report.authority_blocked_artifacts == ()
    assert report.authority_blocked_count == 0
    assert report.decisions[0].status == "PASS"
    assert report.decisions[0].reason == "CONTENT_SHA256_AUTHORIZED"


def test_same_scope_unlisted_sha_is_authority_blocked() -> None:
    report = finalize_initial_authority(
        _placement_readiness(),
        _single_artifact_policy(),
        _authorization(allowed_content_sha256=("2" * 64,)),
    )

    assert report.authorized_artifacts == ()
    assert report.authority_blocked_artifacts == (SAFE_SHA,)
    assert report.decisions[0].reason == "CONTENT_SHA256_NOT_AUTHORIZED"


@pytest.mark.parametrize(
    ("authorization", "protocol_state", "reason"),
    (
        (None, "ABSENT", "SCOPE_AUTHORIZATION_NOT_PRESENT"),
        (
            _authorization(
                protocol_version="LOT41A-V1", allowed_content_sha256=None
            ),
            "LOT41A-V1",
            "CONTENT_ALLOWLIST_AUTHORITY_REQUIRED",
        ),
        (
            _authorization(allowed_content_sha256=(SAFE_SHA.upper(),)),
            "INVALID_LOT41A-V2",
            "INVALID_CONTENT_BOUND_AUTHORITY",
        ),
    ),
)
def test_missing_v1_or_malformed_v2_authority_blocks_all(
    authorization: VerifiedAuthorization | None,
    protocol_state: str,
    reason: str,
) -> None:
    report = finalize_initial_authority(
        _placement_readiness(),
        _single_artifact_policy(),
        authorization,
    )

    assert report.protocol_state == protocol_state
    assert report.authorized_artifacts == ()
    assert report.authority_blocked_artifacts == (SAFE_SHA,)
    assert report.decisions[0].reason == reason


@pytest.mark.parametrize(
    ("authorization", "reason"),
    (
        (
            _authorization(manifest_digest="0" * 64),
            "AUTHORITY_MANIFEST_MISMATCH",
        ),
        (
            _authorization(
                scope=load_profile_registry(PROFILES_DIR)[
                    ("rag_nexus_philo_terminale_tc", "h2c-v1")
                ].scope.model_copy(update={"collection": "rag_nexus_autre_collection"})
            ),
            "AUTHORITY_COLLECTION_MISMATCH",
        ),
    ),
)
def test_manifest_or_collection_authority_drift_blocks_all(
    authorization: VerifiedAuthorization,
    reason: str,
) -> None:
    report = finalize_initial_authority(
        _placement_readiness(),
        _single_artifact_policy(),
        authorization,
    )

    assert report.authorized_artifacts == ()
    assert report.decisions[0].reason == reason


def test_authority_is_intersection_only_and_never_widens_to_quarantine() -> None:
    report = finalize_initial_authority(
        _placement_readiness(),
        _single_artifact_policy(),
        _authorization(
            allowed_content_sha256=tuple(sorted((SAFE_SHA, QUARANTINE_SHA, "2" * 64)))
        ),
    )

    assert report.authorized_artifacts == (SAFE_SHA,)
    assert QUARANTINE_SHA not in report.authorized_artifacts
    assert "2" * 64 not in report.authorized_artifacts


def test_source_scope_drift_is_review_required_not_guessed() -> None:
    catalog = _catalog()
    safe = catalog["artifacts"][SAFE_SHA]  # type: ignore[index]
    safe["pedagogical_placements"][0]["scope"] = "lycee/commun/philosophie"  # type: ignore[index]

    report = compile_initial_placement_readiness(
        catalog,
        _single_artifact_policy(),
        load_collection_config(COLLECTIONS_PATH),
    )

    assert report.eligible_artifacts == ()
    assert report.placement_blocked_artifacts == 2
    assert report.placements_collection_resolved == 0


def test_manifest_or_pii_evidence_drift_fails_closed() -> None:
    policy_data = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    policy_data["corpus_manifest_sha256"] = "0" * 64
    with pytest.raises(PlacementReadinessError, match="manifest"):
        compile_initial_placement_readiness(
            _catalog(),
            load_initial_placement_policy(policy_data),
            load_collection_config(COLLECTIONS_PATH),
        )

    policy_data = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    policy_data["pii_evidence_sha256"] = "0" * 64
    with pytest.raises(PlacementReadinessError, match="PII evidence"):
        load_initial_placement_policy(policy_data)


def test_known_quarantine_can_never_be_allowlisted() -> None:
    policy_data = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    policy_data["approved_artifacts"][QUARANTINE_SHA] = policy_data["approved_artifacts"][
        SAFE_SHA
    ]
    with pytest.raises(PlacementReadinessError, match="quarantine"):
        load_initial_placement_policy(policy_data)


def test_canonical_profile_manifest_is_exact_and_organizationally_attributed() -> None:
    registry = load_profile_registry(PROFILES_DIR)
    verification = verify_profile_manifest(registry, MANIFEST_PATH)

    assert verification.declared_count == 1
    key = ("rag_nexus_philo_terminale_tc", "h2c-v1")
    assert registry[key].scope.niveau.value == "terminale"
    assert registry[key].scope.matiere == "philosophie"
    assert verification.authorities[key].approved_by == "Nexus Réussite"


def test_philosophy_profile_uses_the_canonical_terminale_programme() -> None:
    index = yaml.safe_load(TERMINALE_INDEX_PATH.read_text(encoding="utf-8"))
    philosophy_entry = next(
        item for item in index["fiches"] if item["fichier"] == "T_PHILOSOPHIE.md"
    )
    canonical_programme = philosophy_entry["programme_version"]

    registry_document = yaml.safe_load(
        PROGRAMME_REGISTRY_PATH.read_text(encoding="utf-8")
    )
    registry_entry = next(
        item
        for item in registry_document["programmes"]
        if item["matiere"] == "philosophie"
        and item["niveau"] == "terminale"
        and item["voie"] == "generale"
        and item["type"] == "tronc_commun"
    )
    philosophy_card = PHILOSOPHIE_CARD_PATH.read_text(encoding="utf-8")
    profile = load_profile_registry(PROFILES_DIR)[
        ("rag_nexus_philo_terminale_tc", "h2c-v1")
    ]

    assert canonical_programme == "BOEN_special_8_2019-07-25"
    assert registry_entry["boen_reference"] == "BOEN spécial n°8 du 25 juillet 2019"
    assert canonical_programme in philosophy_card
    assert profile.scope.programme_version == canonical_programme


def test_policy_is_canonical_json_serializable_without_machine_paths() -> None:
    policy = load_initial_placement_policy(POLICY_PATH)
    rendered = json.dumps(policy.as_evidence(), sort_keys=True)
    assert "/home/" not in rendered
    assert "/tmp/" not in rendered
    assert policy.corpus_manifest_sha256 == MANIFEST_SHA
    assert policy.pii_evidence_sha256 == PII_EVIDENCE_SHA
