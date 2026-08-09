"""H2-C : résolution fail-closed des placements du corpus initial réel."""
from __future__ import annotations

import inspect
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from nexus_contracts.ingestion import CollectionProfile

import ingestor.h2c_placement_readiness as readiness_module
from ingestor.collection_config import load_collection_config
from ingestor.h2c_placement_readiness import (
    AuthorityReadinessReport,
    PlacementReadinessError,
    _finalize_verified_initial_authority,
    compile_initial_placement_readiness,
    finalize_initial_authority,
    load_initial_placement_policy,
)
from ingestor.ingestion_control.scope_authority import VerifiedAuthorization
from ingestor.ingestion_profiles.manifest import verify_profile_manifest
from ingestor.ingestion_profiles.registry import (
    load_profile_registry,
    profile_fingerprint,
)

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
NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


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


def _profile() -> CollectionProfile:
    return load_profile_registry(PROFILES_DIR)[
        ("rag_nexus_philo_terminale_tc", "h2c-v1")
    ]


def _authorization(**overrides: Any) -> VerifiedAuthorization:
    profile = _profile()
    defaults: dict[str, Any] = {
        "authorization_id": "h2-staging-philosophie-v2",
        "scope": profile.scope,
        "manifest_digest": MANIFEST_SHA,
        "profile_id": "rag_nexus_philo_terminale_tc",
        "profile_version": "h2c-v1",
        "profile_fingerprint": profile_fingerprint(profile),
        "allowed_domains": ("eduscol.education.gouv.fr",),
        "rights_categories": ("officiel_public",),
        "exclusions": (),
        "pii_absence_attested": True,
        "valid_from": NOW - timedelta(days=1),
        "valid_until": NOW + timedelta(days=1),
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
        "verified_at": NOW,
        "protocol_version": "LOT41A-V2",
        "allowed_content_sha256": (SAFE_SHA,),
    }
    defaults.update(overrides)
    return VerifiedAuthorization(**defaults)


def _finalize(
    authorization: VerifiedAuthorization | None,
    *,
    readiness=None,
    policy=None,
    profile: CollectionProfile | None = None,
) -> AuthorityReadinessReport:
    return _finalize_verified_initial_authority(
        readiness or _placement_readiness(),
        policy or _single_artifact_policy(),
        profile or _profile(),
        authorization,
        authorization_id=(
            authorization.authorization_id
            if authorization is not None
            else "h2-staging-philosophie-v2"
        ),
        now=NOW,
    )


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
    authorization = _authorization()
    report = _finalize(authorization)

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
    assert report.batch_status == "PASS"
    assert report.batch_reason == "AUTHORITY_EXACT_BATCH_MATCH"
    assert report.authorization_id == authorization.authorization_id
    assert report.authorization_digest == authorization.authorization_digest
    assert report.evidence_head_sha == authorization.evidence_head_sha
    assert report.profile_fingerprint == authorization.profile_fingerprint
    assert report.verified_at == NOW.isoformat()
    assert report.protocol_version == "LOT41A-V2"


def test_same_scope_unlisted_sha_is_authority_blocked() -> None:
    report = _finalize(_authorization(allowed_content_sha256=("2" * 64,)))

    assert report.authorized_artifacts == ()
    assert report.authority_blocked_artifacts == (SAFE_SHA,)
    assert report.decisions[0].reason == "CONTENT_SHA256_NOT_AUTHORIZED"
    assert report.batch_reason == "AUTHORITY_ALLOWLIST_SET_MISMATCH"


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
    report = _finalize(authorization)

    assert report.protocol_state == protocol_state
    assert report.authorized_artifacts == ()
    assert report.authority_blocked_artifacts == (SAFE_SHA,)
    assert report.decisions[0].reason == reason
    if authorization is None:
        assert report.authorization_id is None
        assert report.authorization_digest is None
        assert report.evidence_head_sha is None
        assert report.profile_fingerprint is None
        assert report.verified_at is None
        assert report.protocol_version is None


@pytest.mark.parametrize(
    "authorization",
    (
        _authorization(
            scope=_profile().scope.model_copy(update={"tenant": "aefe_terminale"})
        ),
        _authorization(
            scope=_profile().scope.model_copy(update={"matiere": "mathematiques"})
        ),
        _authorization(
            scope=_profile().scope.model_copy(
                update={"programme_version": "BOEN_drift_2026"}
            )
        ),
        _authorization(
            scope=_profile().scope.model_copy(update={"audience": ["libre"]})
        ),
        _authorization(profile_version="h2c-v2"),
        _authorization(profile_fingerprint="9" * 64),
        _authorization(valid_until=NOW),
        _authorization(valid_from=NOW + timedelta(seconds=1)),
        _authorization(verified_at=NOW - timedelta(seconds=1)),
    ),
)
def test_scope_profile_or_validity_drift_never_passes(
    authorization: VerifiedAuthorization,
) -> None:
    report = _finalize(authorization)

    assert report.authorized_artifacts == ()
    assert report.authority_blocked_artifacts == (SAFE_SHA,)
    assert report.batch_reason == "AUTHORITY_SCOPE_PROFILE_OR_VALIDITY_MISMATCH"
    assert report.decisions[0].status == "BLOCKED"


@pytest.mark.parametrize(
    "authorization",
    (
        _authorization(allowed_domains=("example.test",)),
        _authorization(
            exclusions=("/5826/programmes-et-ressources-en-philosophie-voie-gt",)
        ),
    ),
)
def test_forbidden_or_excluded_approved_source_url_never_passes(
    authorization: VerifiedAuthorization,
) -> None:
    report = _finalize(authorization)

    assert report.authorized_artifacts == ()
    assert report.batch_reason == "AUTHORITY_DESTINATION_NOT_ALLOWED"
    assert report.decisions[0].status == "BLOCKED"


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
    report = _finalize(authorization)

    assert report.authorized_artifacts == ()
    assert report.decisions[0].reason == reason


def test_authority_collection_must_remain_instantiated() -> None:
    readiness = replace(
        _placement_readiness(),
        required_collections_not_instantiated=("rag_nexus_philo_terminale_tc",),
    )

    with pytest.raises(PlacementReadinessError, match="collection readiness"):
        _finalize(_authorization(), readiness=readiness)


def test_authority_allowlist_must_equal_the_ready_batch_exactly() -> None:
    report = _finalize(
        _authorization(
            allowed_content_sha256=tuple(sorted((SAFE_SHA, QUARANTINE_SHA, "2" * 64)))
        )
    )

    assert report.authorized_artifacts == ()
    assert report.authority_blocked_artifacts == (SAFE_SHA,)
    assert report.batch_reason == "AUTHORITY_ALLOWLIST_SET_MISMATCH"
    assert QUARANTINE_SHA not in report.authorized_artifacts
    assert "2" * 64 not in report.authorized_artifacts


def test_one_scope_authority_cannot_partially_pass_a_multi_collection_batch() -> None:
    other_sha = "0" * 64
    policy = _single_artifact_policy()
    original = policy.approved_artifacts[SAFE_SHA]
    other_collection = "rag_nexus_autre_collection"
    policy = replace(
        policy,
        approved_artifacts={
            other_sha: replace(
                original,
                content_sha256=other_sha,
                collection=other_collection,
            ),
            SAFE_SHA: original,
        },
    )
    readiness = replace(
        _placement_readiness(),
        eligible_artifacts=(other_sha, SAFE_SHA),
        eligible_placements=2,
        placement_blocked_artifacts=0,
        placements_collection_resolved=2,
        required_collections=tuple(
            sorted((other_collection, "rag_nexus_philo_terminale_tc"))
        ),
        required_collections_instantiated=2,
    )

    report = _finalize(
        _authorization(allowed_content_sha256=(other_sha, SAFE_SHA)),
        readiness=readiness,
        policy=policy,
    )

    assert report.batch_status == "BLOCKED"
    assert report.batch_reason == "AUTHORITY_COLLECTION_MISMATCH"
    assert report.authorized_artifacts == ()


@pytest.mark.parametrize(
    ("eligible_artifacts", "message"),
    (
        ((SAFE_SHA, SAFE_SHA), "unique"),
        ((SAFE_SHA, "0" * 64), "sorted"),
        (("Z" * 64,), "lowercase SHA256"),
    ),
)
def test_malformed_or_noncanonical_readiness_fails_closed(
    eligible_artifacts: tuple[str, ...],
    message: str,
) -> None:
    readiness = replace(
        _placement_readiness(),
        eligible_artifacts=eligible_artifacts,
        eligible_placements=len(eligible_artifacts),
        placements_collection_resolved=len(eligible_artifacts),
        placement_blocked_artifacts=max(0, 2 - len(eligible_artifacts)),
    )
    policy = _single_artifact_policy()
    if "0" * 64 in eligible_artifacts:
        original = policy.approved_artifacts[SAFE_SHA]
        policy = replace(
            policy,
            approved_artifacts={
                SAFE_SHA: original,
                "0" * 64: replace(original, content_sha256="0" * 64),
            },
        )

    with pytest.raises(PlacementReadinessError, match=message):
        _finalize(_authorization(), readiness=readiness, policy=policy)


@pytest.mark.parametrize(
    "readiness",
    (
        replace(_placement_readiness(), eligible_placements=2),
        replace(_placement_readiness(), placements_collection_resolved=2),
        replace(_placement_readiness(), placement_blocked_artifacts=0),
        replace(
            _placement_readiness(),
            required_collections=("z_collection", "a_collection"),
        ),
        replace(_placement_readiness(), required_collections_instantiated=0),
    ),
)
def test_internally_inconsistent_readiness_fails_closed(readiness: object) -> None:
    with pytest.raises(PlacementReadinessError, match="inconsistent|canonical"):
        _finalize(_authorization(), readiness=readiness)


def test_eligible_artifact_must_be_covered_by_policy() -> None:
    readiness = replace(
        _placement_readiness(),
        eligible_artifacts=("2" * 64,),
    )

    with pytest.raises(PlacementReadinessError, match="placement policy"):
        _finalize(_authorization(), readiness=readiness)


def test_production_entrypoint_live_verifies_exact_authority_and_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()
    authorization = _authorization()
    connection = object()
    calls: list[tuple[object, str, object, datetime | None]] = []

    def fake_verify(
        conn: object,
        *,
        authorization_id: str,
        scope: object,
        now: datetime | None = None,
    ) -> VerifiedAuthorization:
        calls.append((conn, authorization_id, scope, now))
        return authorization

    monkeypatch.setattr(
        readiness_module,
        "verify_scope_authorization",
        fake_verify,
    )

    report = finalize_initial_authority(
        connection,
        authorization_id=authorization.authorization_id,
        readiness=_placement_readiness(),
        policy=_single_artifact_policy(),
        profile=profile,
        now=NOW,
    )

    assert report.authorized_artifacts == (SAFE_SHA,)
    assert calls == [
        (connection, authorization.authorization_id, profile.scope, NOW)
    ]
    assert "allowed_content_sha256" not in inspect.signature(
        finalize_initial_authority
    ).parameters


def test_source_scope_drift_is_review_required_not_guessed() -> None:
    catalog = _catalog()
    safe = catalog["artifacts"][SAFE_SHA]  # type: ignore[index]
    safe["pedagogical_placements"][0]["scope"] = "lycee/commun/philosophie"

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
