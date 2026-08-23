"""Republication gouvernée du catalogue candidat vers INGEST.

Aucune autorité de production n'est exercée ici : ``_install_governed_root``
installe une fausse racine gouvernée sous ``tmp_path`` pour chaque test,
jamais le vrai dépôt. Les fixtures d'autorité/liaison de revue reprennent
fidèlement celles de ``test_h2b_coverage_report.py`` — même corpus réel
minimal, mêmes trois couches ADR-0035 — pour que ce module soit exercé
contre exactement ce que ``h2b_coverage_report.py`` valide déjà.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_h2b_coverage_report as gate_fixtures  # noqa: E402
from nexus_contracts.authority_artifacts import (  # noqa: E402
    ScopeAuthorizationArtifactV2,
    canonical_authorization_path,
    git_blob_sha1,
)
from nexus_contracts.authorization_set import (  # noqa: E402
    AuthorizationSetMemberV1,
    AuthorizationSetV1,
    ReleaseScopePlacementEntryV1,
    ReleaseScopePlacementV1,
    VerifiedAuthorizationSetV1,
    content_set_digest,
    scope_digest,
)
from nexus_contracts.ingestion import (  # noqa: E402
    CollectionProfile,
    ResourceScope,
    collection_profile_fingerprint,
    profile_manifest_fingerprint,
)
from nexus_contracts.review_binding import (  # noqa: E402
    REVIEW_BINDING_PROTOCOL_VERSION,
    TRUSTED_REVIEW_PROTOCOL,
    ScopeAuthorizationReviewBindingV1,
    expected_challenge_digest,
    public_key_hex,
    sign_review_binding,
)

from rag_pedago.governance import catalog_republish as catalog_republish_module  # noqa: E402
from rag_pedago.governance.catalog_republish import (  # noqa: E402
    CATALOG_DIGEST_PROTOCOL_VERSION,
    CATALOG_DIGEST_V2_PROTOCOL_VERSION,
    CatalogRepublishError,
    republish_catalog,
)
from rag_pedago.governance.catalog_republish import (
    republish_catalog_v2 as republish_catalog_v2_production,
)
from rag_pedago.governance.corpus_campaign import (  # noqa: E402
    CorpusCampaignV1,
    CorpusCampaignV2,
)
from rag_pedago.governance.release_scope_placement import (  # noqa: E402
    ReleaseScopePlacementGitInputs,
)
from rag_pedago.imports import h2b_coverage_report as h2b_module  # noqa: E402

AUTHORITY_NOW = datetime(2026, 6, 1, tzinfo=UTC)
TEST_SIGNING_SEED = "44" * 32
TEST_KEY_ID = "nexus-governance-test-1"
REPOSITORY = "cyranoaladin/RAG"
TRUSTED_REVIEWER = "abenrhouma"
PR_AUTHOR = "cyranoaladin"
PULL_REQUEST = 95
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40

CONTENT_SHA256 = "a" * 64
_MANIFEST_CONTENT = f"{CONTENT_SHA256}  01_EDUSCOL_OFFICIEL/current.pdf\n"
MANIFEST_SHA256 = hashlib.sha256(_MANIFEST_CONTENT.encode()).hexdigest()
CAMPAIGN_ID = "eduscol-philo-terminale-republish-test"
AUTHORIZATION_ID = "catalog-republish-test-authority"


@pytest.fixture(autouse=True)
def _trusted_v2_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        catalog_republish_module,
        "_trusted_utc_now",
        lambda: AUTHORITY_NOW,
        raising=False,
    )


def republish_catalog_v2(
    *,
    campaign: CorpusCampaignV2,
    catalog_path: Path,
    authorization_set: AuthorizationSetV1,
    verified_authorization_set: VerifiedAuthorizationSetV1,
    release_scope_placement: ReleaseScopePlacementV1,
    authorization_member_bytes: dict[str, bytes | bytearray],
    out_root: Path,
    currentness_verification_path: Path | None = None,
    rights_path: Path | None = None,
    pii_path: Path | None = None,
    routing_path: Path | None = None,
):
    """Harness explicite du core privé ; jamais le boundary production."""
    snapshot = catalog_republish_module._snapshot_v2_catalog_evidence(  # noqa: SLF001
        catalog_path=catalog_path,
        currentness_verification_path=currentness_verification_path,
        rights_path=rights_path,
        pii_path=pii_path,
        routing_path=routing_path,
    )
    return catalog_republish_module._republish_catalog_v2_verified(  # noqa: SLF001
        campaign=campaign,
        prepared_catalog=catalog_republish_module._prepare_v2_catalog(  # noqa: SLF001
            snapshot
        ),
        authorization_set=authorization_set,
        verified_authorization_set=verified_authorization_set,
        release_scope_placement=release_scope_placement,
        authorization_member_bytes=authorization_member_bytes,
        out_root=out_root,
        moment=AUTHORITY_NOW,
    )


def _install_governed_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    anchor_environment: str = "production",
    anchor_seed: str = TEST_SIGNING_SEED,
    revoked: list[str] | None = None,
) -> Path:
    root = tmp_path / "governed_root"
    (root / "governance" / "trust-anchors").mkdir(parents=True, exist_ok=True)
    for marker in h2b_module._GOVERNED_ROOT_MARKERS:
        target = root / marker
        target.parent.mkdir(parents=True, exist_ok=True)
        if "." in target.name:
            target.write_text("", encoding="utf-8")
        else:
            target.mkdir(parents=True, exist_ok=True)
    (root / h2b_module._GOVERNED_TRUST_ANCHOR_PATH).write_text(
        json.dumps(
            {
                "protocol_version": REVIEW_BINDING_PROTOCOL_VERSION,
                "keys": [
                    {
                        "key_id": TEST_KEY_ID,
                        "algorithm": "ed25519",
                        "public_key": public_key_hex(anchor_seed),
                        "environment": anchor_environment,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / h2b_module._GOVERNED_REVOCATIONS_PATH).write_text(
        json.dumps(
            {
                "protocol_version": h2b_module._REVOCATIONS_PROTOCOL_VERSION,
                "revoked_authorization_ids": revoked or [],
            }
        ),
        encoding="utf-8",
    )
    reviewers_path = root / h2b_module._TRUSTED_REVIEWERS_CONFIG
    reviewers_path.parent.mkdir(parents=True, exist_ok=True)
    reviewers_path.write_text(
        (h2b_module._REPOSITORY_ROOT / h2b_module._TRUSTED_REVIEWERS_CONFIG).read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(h2b_module, "_GOVERNED_REPOSITORY_ROOT", root)
    return root


def _authority_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "protocol_version": "LOT41A-V2",
        "authorization_id": AUTHORIZATION_ID,
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "manifest_digest": MANIFEST_SHA256,
        "profile_id": "catalog-republish-test-profile",
        "profile_version": "1.0.0",
        "profile_fingerprint": "f" * 64,
        "allowed_domains": ["eduscol.education.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "pii_absence_attested": True,
        "pii_absence_evidence": "Manual review: no PII found",
        "valid_from": "2026-01-01T00:00:00.000000Z",
        "valid_until": "2026-12-31T23:59:59.999999Z",
        "allowed_content_sha256": [CONTENT_SHA256],
        "scope": {
            "audience": ["libre"],
            "candidat": "libre",
            "collection": "test_collection",
            "matiere": "philosophie",
            "niveau": "terminale",
            "programme_version": "v1",
            "school_year": "2026-2027",
            "tenant": "libre_terminale",
            "visibility": "public",
            "voie": "generale",
        },
    }
    document.update(overrides)
    return document


def _write_authority(path: Path, document: dict[str, Any]) -> Path:
    path.write_bytes(ScopeAuthorizationArtifactV2.model_validate(document).canonical_bytes())
    return path


def _review_binding_document(authority_document: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    raw = ScopeAuthorizationArtifactV2.model_validate(authority_document).canonical_bytes()
    authorization_id = str(authority_document["authorization_id"])
    document: dict[str, Any] = {
        "protocol_version": REVIEW_BINDING_PROTOCOL_VERSION,
        "repository": REPOSITORY,
        "pull_request": PULL_REQUEST,
        "base_ref": "main",
        "base_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "authorization_artifact_path": canonical_authorization_path(authorization_id),
        "authorization_artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "authorization_artifact_git_blob_sha1": git_blob_sha1(raw),
        "authorization_id": authorization_id,
        "authorization_decision": "AUTHORIZE_INGESTION_SCOPE",
        "review_id": 4242,
        "reviewer_login": TRUSTED_REVIEWER,
        "reviewer_permission": "admin",
        "author_login": PR_AUTHOR,
        "submitted_at": "2026-05-01T10:00:00Z",
        "challenge_protocol": TRUSTED_REVIEW_PROTOCOL,
        "challenge_digest": expected_challenge_digest(
            repository=REPOSITORY,
            pull_request=PULL_REQUEST,
            base_ref="main",
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
            author=PR_AUTHOR,
            reviewer=TRUSTED_REVIEWER,
        ),
        "verified_at": "2026-05-15T09:00:00Z",
        "verifier_version": "nexus-review-binding-producer/1",
        "expires_at": "2026-12-01T09:00:00Z",
    }
    document.update(overrides)
    return document


def _write_review_binding(
    tmp_path: Path,
    authority_document: dict[str, Any],
    *,
    seed: str = TEST_SIGNING_SEED,
    key_id: str = TEST_KEY_ID,
    filename: str = "review_binding.json",
    **overrides: Any,
) -> Path:
    binding = ScopeAuthorizationReviewBindingV1.model_validate(
        _review_binding_document(authority_document, **overrides)
    )
    path = tmp_path / filename
    path.write_bytes(sign_review_binding(binding, private_key_hex=seed, key_id=key_id).canonical_bytes())
    return path


def _write_real_catalog(tmp_path: Path) -> Path:
    catalog = {
        "catalog_kind": "REAL_SEALED_CORPUS",
        "manifest_sha256": MANIFEST_SHA256,
        "manifest_entries": 1,
        "physical_object_count": 2,
        "content_artifact_count": 2,
        "disposition_counts": {
            "INGEST": 0,
            "REVIEW_REQUIRED": 1,
            "QUARANTINE": 0,
            "ARCHIVE_ONLY": 0,
            "EXCLUDE": 1,
            "UNSUPPORTED": 0,
        },
        "unclassified": 0,
        "multiple_primary_disposition": 0,
        "verification_passed": True,
        "verification_errors": [],
        "physical_objects": [
            {
                "content_sha256": CONTENT_SHA256,
                "path": "01_EDUSCOL_OFFICIEL/current.pdf",
                "base_disposition": "INGEST",
                "disposition": "REVIEW_REQUIRED",
                "zone": "01_EDUSCOL_OFFICIEL/",
                "currentness": "actuel",
                "rights_category_candidate": "officiel_public",
                "gate_statuses": {
                    "rights": "PASS",
                    "pii": "PASS",
                    "authority": "BLOCKED_NOT_CLEARED",
                },
                "provenance_status": "VERIFIED",
                "attribution_metadata": {
                    "source": "Eduscol",
                    "source_url": "https://eduscol.education.gouv.fr/test",
                },
            },
            {
                "content_sha256": MANIFEST_SHA256,
                "path": "00_ADMIN/SHA256SUMS.txt",
                "base_disposition": "EXCLUDE",
                "disposition": "EXCLUDE",
                "zone": "00_ADMIN/",
                "currentness": None,
                "gate_statuses": {},
                "provenance_status": "VERIFIED",
                "attribution_metadata": {
                    "source": "NEXUS_CORPUS_GOVERNANCE",
                    "source_reference": "00_ADMIN/SHA256SUMS.txt",
                },
            },
        ],
    }
    path = tmp_path / "real-catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    return path


def _campaign_fields(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "protocol_version": "NEXUS-CORPUS-CAMPAIGN-V1",
        "campaign_id": CAMPAIGN_ID,
        "scope": {
            "tenant": "libre_terminale",
            "collection": "rag_nexus_philo_terminale_tc",
            "niveau": "terminale",
            "voie": "generale",
            "matiere": "philosophie",
            "candidat": "libre",
            "audience": ["libre"],
            "visibility": "internal",
            "school_year": "2026-2027",
            "programme_version": "BOEN_special_8_2019-07-25",
        },
        "source_kind": "ghcr-oci",
        "source_registry": "ghcr.io",
        "source_repository": "cyranoaladin/rag-corpus",
        "source_oci_digest": "sha256:" + "1" * 64,
        "source_archive_sha256": "2" * 64,
        "source_tree_digest": "3" * 64,
        "archive_format": "tar.zst",
        "source_root": "corpus",
        "expected_manifest_sha256": MANIFEST_SHA256,
        "expected_catalog_digest": "0" * 64,  # overridden by the caller once known
        "authorization_id": AUTHORIZATION_ID,
        "compiler_version": "corpus-catalog-compiler/1",
        "routing_config_digest": "6" * 64,
        "rights_config_digest": "7" * 64,
        "pii_config_digest": "8" * 64,
        "golden_spec_digest": "9" * 64,
        "environment": "production",
        "retention_days": 90,
    }
    fields.update(overrides)
    return fields


def _campaign(**overrides: Any) -> CorpusCampaignV1:
    return CorpusCampaignV1(**_campaign_fields(**overrides))


def _setup_real(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    campaign_environment: str = "production",
    anchor_environment: str = "production",
) -> tuple[CorpusCampaignV1, Path, Path, Path]:
    """Assemble un jeu complet et réel : ancre gouvernée, autorité,
    liaison de revue, catalogue. Rend ``(campaign_with_real_digest,
    catalog_path, authority_path, binding_path)``."""
    _install_governed_root(monkeypatch, tmp_path, anchor_environment=anchor_environment)
    catalog_path = _write_real_catalog(tmp_path)
    authority = _authority_document()
    authority_path = _write_authority(tmp_path / "authority.json", authority)
    binding_path = _write_review_binding(tmp_path, authority)

    # Premier calcul, en rehearsal (aucune contrainte de digest), pour
    # découvrir le vrai digest que produirait la promotion — exactement
    # ce qu'un opérateur ferait localement avant de le faire réviser.
    from rag_pedago.governance.catalog_republish import republish_catalog as _rc

    probe_campaign = _campaign(environment="production", expected_catalog_digest="0" * 64)
    try:
        _rc(
            campaign=probe_campaign,
            catalog_path=catalog_path,
            authority_path=authority_path,
            authority_review_binding_path=binding_path,
            out_root=tmp_path / "probe_out",
            now=AUTHORITY_NOW,
        )
    except CatalogRepublishError as exc:
        message = str(exc)
        marker = "computed="
        start = message.index(marker) + len(marker)
        real_digest = message[start : start + 64]
    else:  # pragma: no cover - le probe n'est jamais censé réussir
        raise AssertionError("probe run unexpectedly matched the placeholder digest")

    campaign = _campaign(
        environment=campaign_environment, expected_catalog_digest=real_digest
    )
    return campaign, catalog_path, authority_path, binding_path


def test_real_authority_republishes_a_promoted_catalog_matching_the_approved_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign, catalog_path, authority_path, binding_path = _setup_real(tmp_path, monkeypatch)
    out_root = tmp_path / "repo"

    result = republish_catalog(
        campaign=campaign,
        catalog_path=catalog_path,
        authority_path=authority_path,
        authority_review_binding_path=binding_path,
        out_root=out_root,
        now=AUTHORITY_NOW,
    )

    assert result.campaign_id == CAMPAIGN_ID
    assert result.promoted_count == 1
    assert result.already_published is False
    assert result.catalog_sha256 == campaign.expected_catalog_digest

    written_catalog = json.loads(result.catalog_path.read_text(encoding="utf-8"))
    promoted_item = next(
        item
        for item in written_catalog["physical_objects"]
        if item["content_sha256"] == CONTENT_SHA256
    )
    assert promoted_item["disposition"] == "INGEST"
    assert promoted_item["gate_statuses"]["authority"] == "PASS"

    digest_document = json.loads(result.digest_path.read_text(encoding="utf-8"))
    assert digest_document["protocol_version"] == CATALOG_DIGEST_PROTOCOL_VERSION
    assert digest_document["campaign_id"] == CAMPAIGN_ID
    assert digest_document["catalog_sha256"] == result.catalog_sha256
    assert digest_document["promoted_count"] == 1

    assert result.catalog_path == out_root / "governance/corpus-campaigns" / CAMPAIGN_ID / "catalog.json"
    assert result.digest_path == out_root / "governance/corpus-campaigns" / CAMPAIGN_ID / "catalog.digest.json"


def _v2_scope(*, collection: str = "test_collection") -> ResourceScope:
    return ResourceScope.model_validate(
        {
            "audience": ["libre"],
            "candidat": "libre",
            "collection": collection,
            "matiere": "philosophie",
            "niveau": "terminale",
            "programme_version": "v1",
            "school_year": "2026-2027",
            "tenant": "libre_terminale",
            "visibility": "internal",
            "voie": "generale",
        }
    )


def _v2_release(
    *,
    placement_scope: ResourceScope | None = None,
    member_contents: tuple[str, ...] = (CONTENT_SHA256,),
    rights_categories: tuple[str, ...] = ("officiel_public",),
) -> tuple[
    AuthorizationSetV1,
    VerifiedAuthorizationSetV1,
    ReleaseScopePlacementV1,
    dict[str, bytes],
]:
    scope = _v2_scope()
    placement = ReleaseScopePlacementV1.build(
        profile_manifest_digest="d" * 64,
        placements=tuple(
            ReleaseScopePlacementEntryV1.model_validate(
                {
                    "content_sha256": content,
                    "profile_id": "test_collection",
                    "profile_version": "1.0.0",
                    "profile_fingerprint": "f" * 64,
                    "scope": placement_scope or scope,
                }
            )
            for content in member_contents
        ),
    )
    artifact = ScopeAuthorizationArtifactV2.model_validate(
        {
            "protocol_version": "LOT41A-V2",
            "authorization_id": "auth-v2-test",
            "decision": "AUTHORIZE_INGESTION_SCOPE",
            "scope": scope,
            "manifest_digest": "d" * 64,
            "profile_id": "test_collection",
            "profile_version": "1.0.0",
            "profile_fingerprint": "f" * 64,
            "allowed_domains": ["eduscol.education.fr"],
            "rights_categories": list(rights_categories),
            "exclusions": [],
            "pii_absence_attested": True,
            "pii_absence_evidence": "fixture sans PII",
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_until": "2027-01-01T00:00:00Z",
            "allowed_content_sha256": sorted(member_contents),
        }
    )
    artifact_bytes = artifact.canonical_bytes()
    member = AuthorizationSetMemberV1.model_validate(
        {
            "authorization_id": artifact.authorization_id,
            "authorization_digest": hashlib.sha256(artifact_bytes).hexdigest(),
            "review_binding_digest": "2" * 64,
            "scope": scope,
            "scope_digest": scope_digest(scope),
            "allowed_content_sha256": sorted(member_contents),
            "allowed_content_count": len(member_contents),
            "allowed_content_set_sha256": content_set_digest(member_contents),
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_until": "2027-01-01T00:00:00Z",
        }
    )
    authorization_set = AuthorizationSetV1.build(
        members=(member,),
        corpus_manifest_sha256=MANIFEST_SHA256,
        profile_manifest_digest="d" * 64,
        release_scope_placement_digest=placement.digest(),
        authority_required_content_sha256=member_contents,
    )
    verified = VerifiedAuthorizationSetV1(
        authorization_set_bytes=authorization_set.canonical_bytes(),
        authorization_set_digest=authorization_set.digest(),
        authorization_ids=(member.authorization_id,),
        content_authorization_ids=tuple(
            (content, member.authorization_id) for content in sorted(member_contents)
        ),
        scope_authorization_ids=((member.scope_digest, member.authorization_id),),
        authorizations_effective_valid_from=member.valid_from,
        authorizations_effective_valid_until=member.valid_until,
        earliest_review_submitted_at=datetime(2026, 5, 1, tzinfo=UTC),
        earliest_review_binding_verified_at=datetime(2026, 5, 2, tzinfo=UTC),
        earliest_review_binding_expires_at=datetime(2026, 12, 1, tzinfo=UTC),
        verified_at=AUTHORITY_NOW,
    )
    return (
        authorization_set,
        verified,
        placement,
        {canonical_authorization_path(artifact.authorization_id): artifact_bytes},
    )


def _v2_campaign(
    authorization_set: AuthorizationSetV1,
    *,
    expected_catalog_digest: str,
    expected_manifest_sha256: str = MANIFEST_SHA256,
) -> CorpusCampaignV2:
    return CorpusCampaignV2.build(
        campaign_id="multi-auth-republish-test",
        source_kind="ghcr-oci",
        source_registry="ghcr.io",
        source_repository="cyranoaladin/rag-corpus",
        source_oci_digest="sha256:" + "4" * 64,
        source_archive_sha256="5" * 64,
        source_tree_digest="6" * 64,
        archive_format="tar.zst",
        source_root="corpus",
        expected_manifest_sha256=expected_manifest_sha256,
        expected_catalog_digest=expected_catalog_digest,
        authorization_set_digest=authorization_set.digest(),
        authority_required_count=authorization_set.authority_required_count,
        authority_required_set_sha256=authorization_set.authority_required_set_sha256,
        profile_manifest_digest=authorization_set.profile_manifest_digest,
        release_scope_placement_digest=authorization_set.release_scope_placement_digest,
        compiler_version="corpus-catalog-compiler/1",
        routing_config_digest="7" * 64,
        rights_config_digest="8" * 64,
        pii_config_digest="9" * 64,
        golden_spec_digest="a" * 64,
        environment="production",
        retention_days=90,
    )


def _write_two_scope_production_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, str, str, ReleaseScopePlacementGitInputs, AuthorizationSetV1]:
    """Deux partitions réelles : set, bindings et profils dans un tree Git."""
    content_b = "b" * 64
    manifest_content = (
        f"{CONTENT_SHA256}  01_EDUSCOL_OFFICIEL/philo.pdf\n"
        f"{content_b}  01_EDUSCOL_OFFICIEL/francais.pdf\n"
    )
    manifest_sha256 = hashlib.sha256(manifest_content.encode()).hexdigest()
    catalog = {
        "catalog_kind": "REAL_SEALED_CORPUS",
        "manifest_sha256": manifest_sha256,
        "manifest_entries": 2,
        "physical_object_count": 3,
        "content_artifact_count": 2,
        "disposition_counts": {
            "INGEST": 0,
            "REVIEW_REQUIRED": 2,
            "QUARANTINE": 0,
            "ARCHIVE_ONLY": 0,
            "EXCLUDE": 1,
            "UNSUPPORTED": 0,
        },
        "unclassified": 0,
        "multiple_primary_disposition": 0,
        "verification_passed": True,
        "verification_errors": [],
        "physical_objects": [],
    }
    for content, name in (
        (CONTENT_SHA256, "philo"),
        (content_b, "francais"),
    ):
        catalog["physical_objects"].append(
            {
                "content_sha256": content,
                "path": f"01_EDUSCOL_OFFICIEL/{name}.pdf",
                "base_disposition": "INGEST",
                "disposition": "REVIEW_REQUIRED",
                "zone": "01_EDUSCOL_OFFICIEL/",
                "currentness": "actuel",
                "rights_category_candidate": "officiel_public",
                "gate_statuses": {
                    "rights": "PASS",
                    "pii": "PASS",
                    "authority": "BLOCKED_NOT_CLEARED",
                },
                "provenance_status": "VERIFIED",
                "attribution_metadata": {
                    "source": "Eduscol",
                    "source_url": f"https://eduscol.education.gouv.fr/{name}",
                },
            }
        )
    catalog["physical_objects"].append(
        {
            "content_sha256": manifest_sha256,
            "path": "00_ADMIN/SHA256SUMS.txt",
            "base_disposition": "EXCLUDE",
            "disposition": "EXCLUDE",
            "zone": "00_ADMIN/",
            "currentness": None,
            "gate_statuses": {},
            "provenance_status": "VERIFIED",
            "attribution_metadata": {
                "source": "NEXUS_CORPUS_GOVERNANCE",
                "source_reference": "00_ADMIN/SHA256SUMS.txt",
            },
        }
    )
    catalog_path = tmp_path / "two-scope-catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    root = _install_governed_root(monkeypatch, tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    scopes = (
        _v2_scope(collection="test_collection"),
        ResourceScope.model_validate(
            {
                **_v2_scope(collection="francais_collection").model_dump(mode="json"),
                "matiere": "francais",
            }
        ),
    )
    contents = (CONTENT_SHA256, content_b)
    profile_paths = ("profiles/philo.yml", "profiles/francais.yml")
    profile_fingerprints: list[str] = []
    for scope, title, profile_path in zip(
        scopes, ("Philosophie", "Français"), profile_paths, strict=True
    ):
        profile_document: dict[str, Any] = {
            "profile_version": "1.0.0",
            "enabled": True,
            "scope": scope.model_dump(mode="json"),
            "title": title,
            "owner": "tests",
            "expected_topics": ["notion"],
            "expected_resource_types": ["cours"],
            "allowed_domains": ["eduscol.education.fr"],
            "source_authority": "official",
            "search_cadence": "weekly",
            "max_queries_per_run": 1,
            "max_documents_per_run": 1,
            "max_chunk_size": 800,
            "chunk_overlap": 100,
            "min_source_confidence": 0.7,
            "min_scope_confidence": 0.7,
            "min_extraction_quality": 0.7,
        }
        profile = CollectionProfile.model_validate(profile_document)
        profile_fingerprints.append(collection_profile_fingerprint(profile))
        target = root / profile_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml.safe_dump(profile_document, sort_keys=True), encoding="utf-8")

    manifest = {
        "manifest_version": "1",
        "provenance": "fixture production deux scopes",
        "generated_at": "2026-08-23T00:00:00Z",
        "profiles": [
            {
                "collection": scope.collection,
                "profile_version": "1.0.0",
                "fingerprint": fingerprint,
                "approved_by": "test-authority",
                "approved_at": "2026-08-23T00:00:00Z",
            }
            for scope, fingerprint in zip(scopes, profile_fingerprints, strict=True)
        ],
    }
    profile_manifest_digest = profile_manifest_fingerprint(manifest)
    paths = {
        "matrix": "governance/profile-matrix.json",
        "placements": "governance/placements.json",
        "registry": "governance/release-registry.json",
        "contents": "governance/expected-contents.txt",
        "profiles": "governance/verified-profiles.json",
        "manifest": "governance/profile-manifest.yml",
        "set": "governance/authorization-sets/two-scope.json",
    }

    def write_json(relative: str, value: Any) -> None:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    matrix = []
    placements = []
    verified_profiles = []
    for index, (content, scope, fingerprint, profile_path) in enumerate(
        zip(contents, scopes, profile_fingerprints, profile_paths, strict=True), start=1
    ):
        matrix.append(
            {
                "partition_id": f"P{index:02d}",
                "partition_kind": "EXACT_VERSIONED_RELEASE_PROFILE",
                "content_count": 1,
                "content_sha256": [content],
                "profile_decision_required": False,
                "evidence_sources": [profile_path],
                "dimensions": {
                    name: {
                        "value": value,
                        "grounded": True,
                        "source_of_truth": profile_path,
                    }
                    for name, value in scope.model_dump(mode="json").items()
                },
            }
        )
        placements.append(
            {
                "content_sha256": content,
                "release_id": "release-two-scope",
                "collection": scope.collection,
                "profile_version": "1.0.0",
            }
        )
        verified_profiles.append(
            {
                "profile_id": scope.collection,
                "profile_version": "1.0.0",
                "profile_fingerprint": fingerprint,
                "scope": scope.model_dump(mode="json"),
                "source_path": profile_path,
            }
        )
    write_json(paths["matrix"], matrix)
    write_json(paths["placements"], placements)
    write_json(
        paths["registry"],
        {
            "registry_version": "1",
            "school_year": "2026-2027",
            "releases": [
                {
                    "release_id": "release-two-scope",
                    "collections": [scope.collection for scope in scopes],
                }
            ],
        },
    )
    (root / paths["contents"]).write_text(
        "".join(f"{content}\n" for content in sorted(contents)), encoding="utf-8"
    )
    write_json(
        paths["profiles"],
        {
            "profile_manifest_digest": profile_manifest_digest,
            "profiles": verified_profiles,
        },
    )
    (root / paths["manifest"]).write_text(
        yaml.safe_dump(manifest, sort_keys=True), encoding="utf-8"
    )

    preliminary_placement = ReleaseScopePlacementV1.build(
        profile_manifest_digest=profile_manifest_digest,
        placements=tuple(
            ReleaseScopePlacementEntryV1(
                content_sha256=content,
                profile_id=scope.collection,
                profile_version="1.0.0",
                profile_fingerprint=fingerprint,
                scope=scope,
            )
            for content, scope, fingerprint in zip(
                contents, scopes, profile_fingerprints, strict=True
            )
        ),
    )
    members: list[AuthorizationSetMemberV1] = []
    for index, (content, scope, fingerprint) in enumerate(
        zip(contents, scopes, profile_fingerprints, strict=True), start=1
    ):
        authorization_document = {
            "protocol_version": "LOT41A-V2",
            "authorization_id": f"auth-two-scope-{index}",
            "decision": "AUTHORIZE_INGESTION_SCOPE",
            "scope": scope.model_dump(mode="json"),
            "manifest_digest": profile_manifest_digest,
            "profile_id": scope.collection,
            "profile_version": "1.0.0",
            "profile_fingerprint": fingerprint,
            "allowed_domains": ["eduscol.education.fr"],
            "rights_categories": ["officiel_public"],
            "exclusions": [],
            "pii_absence_attested": True,
            "pii_absence_evidence": "fixture sans PII",
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_until": "2027-01-01T00:00:00Z",
            "allowed_content_sha256": [content],
        }
        artifact = ScopeAuthorizationArtifactV2.model_validate(authorization_document)
        binding = _write_review_binding(
            tmp_path,
            authorization_document,
            filename=f"binding-{index}.json",
        ).read_bytes()
        auth_path = root / canonical_authorization_path(artifact.authorization_id)
        auth_path.parent.mkdir(parents=True, exist_ok=True)
        auth_path.write_bytes(artifact.canonical_bytes())
        binding_path = root / f"governance/review-bindings/{artifact.authorization_id}.json"
        binding_path.parent.mkdir(parents=True, exist_ok=True)
        binding_path.write_bytes(binding)
        members.append(
            AuthorizationSetMemberV1(
                authorization_id=artifact.authorization_id,
                authorization_digest=artifact.digest(),
                review_binding_digest=hashlib.sha256(binding).hexdigest(),
                scope=scope,
                scope_digest=scope_digest(scope),
                allowed_content_sha256=(content,),
                allowed_content_count=1,
                allowed_content_set_sha256=content_set_digest((content,)),
                valid_from=artifact.valid_from,
                valid_until=artifact.valid_until,
            )
        )
    authorization_set = AuthorizationSetV1.build(
        members=members,
        corpus_manifest_sha256=manifest_sha256,
        profile_manifest_digest=profile_manifest_digest,
        release_scope_placement_digest=preliminary_placement.digest(),
        authority_required_content_sha256=contents,
    )
    set_path = root / paths["set"]
    set_path.parent.mkdir(parents=True, exist_ok=True)
    set_path.write_bytes(authorization_set.canonical_bytes())
    placeholder_campaign = _v2_campaign(
        authorization_set,
        expected_catalog_digest="0" * 64,
        expected_manifest_sha256=authorization_set.corpus_manifest_sha256,
    )
    campaign_relative_path = placeholder_campaign.canonical_path()
    campaign_path = root / campaign_relative_path
    campaign_path.parent.mkdir(parents=True, exist_ok=True)
    campaign_path.write_bytes(placeholder_campaign.canonical_bytes())
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Nexus Tests",
            "-c",
            "user.email=tests@nexus.invalid",
            "commit",
            "-qm",
            "two scope release",
        ],
        cwd=root,
        check=True,
    )
    tree_sha = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return (
        catalog_path,
        paths["set"],
        campaign_relative_path,
        ReleaseScopePlacementGitInputs(
            repository_root=root,
            source_tree_sha=tree_sha,
            profile_proposal_matrix_path=paths["matrix"],
            accepted_placements_path=paths["placements"],
            release_registry_path=paths["registry"],
            expected_contents_path=paths["contents"],
            verified_profiles_path=paths["profiles"],
            profile_manifest_path=paths["manifest"],
        ),
        authorization_set,
    )


def _commit_two_scope_campaign(
    *,
    release_inputs: ReleaseScopePlacementGitInputs,
    campaign_relative_path: str,
    authorization_set: AuthorizationSetV1,
    expected_catalog_digest: str,
) -> ReleaseScopePlacementGitInputs:
    campaign = _v2_campaign(
        authorization_set,
        expected_catalog_digest=expected_catalog_digest,
        expected_manifest_sha256=authorization_set.corpus_manifest_sha256,
    )
    (release_inputs.repository_root / campaign_relative_path).write_bytes(
        campaign.canonical_bytes()
    )
    subprocess.run(
        ["git", "add", campaign_relative_path],
        cwd=release_inputs.repository_root,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Nexus Tests",
            "-c",
            "user.email=tests@nexus.invalid",
            "commit",
            "-qm",
            "bind exact campaign",
        ],
        cwd=release_inputs.repository_root,
        check=True,
    )
    tree_sha = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=release_inputs.repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return replace(release_inputs, source_tree_sha=tree_sha)


def _write_two_scope_currentness_inputs(
    tmp_path: Path, catalog_path: Path
) -> tuple[Path, Path, Path, Path]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    manifest_sha256 = catalog["manifest_sha256"]
    candidates = [
        item
        for item in catalog["physical_objects"]
        if item["path"].startswith("01_EDUSCOL_OFFICIEL/")
    ]
    currentness_path = tmp_path / "two-scope-currentness.yml"
    rights_path = tmp_path / "two-scope-rights.yml"
    pii_path = tmp_path / "two-scope-pii.json"
    routing_path = tmp_path / "two-scope-routing.yml"
    currentness_path.write_text(
        yaml.safe_dump(
            {
                "evidence_kind": "MULTILEVEL_ARTIFACT_CURRENTNESS_V1",
                "corpus_manifest_sha256": manifest_sha256,
                "artifacts": [],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    routing_path.write_text(
        yaml.safe_dump(
            {
                "config_id": "two-scope-routing-v1",
                "manifest_sha256": manifest_sha256,
                "rights_evidence_perimeter": [
                    "00_ADMIN/",
                    "01_EDUSCOL_OFFICIEL/",
                ],
                "zone_rules": [
                    {
                        "zone_prefix": "00_ADMIN/",
                        "disposition": "EXCLUDE",
                        "reason": "admin",
                    },
                    {
                        "zone_prefix": "01_EDUSCOL_OFFICIEL/",
                        "disposition": "INGEST",
                        "currentness": "actuel",
                    },
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    rights_path.write_text(
        yaml.safe_dump(
            {
                "registry_id": "two-scope-rights-v1",
                "human_rights_decisions": {
                    "eduscol": {
                        "decision_type": "HUMAN_ORGANIZATIONAL_RIGHTS_APPROVAL",
                        "decision_maker": "Nexus Réussite",
                        "decision_date": "2026-08-08",
                        "scope_manifest_sha256": manifest_sha256,
                        "scope_zone": "01_EDUSCOL_OFFICIEL/",
                        "approved_for_production_rag": True,
                        "generic_rights_blocker": False,
                    }
                },
                "source_evidence": {
                    "admin": {
                        "zone": "00_ADMIN/",
                        "rights_status": "REVIEW_REQUIRED",
                        "disposition_override": "EXCLUDE",
                    },
                    "eduscol": {
                        "zone": "01_EDUSCOL_OFFICIEL/",
                        "rights_status": "CLEARED_BY_HUMAN_DECISION",
                        "rights_decision_ref": "eduscol",
                    },
                },
                "summary": {"total_zones": 2},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    required_paths = sorted(str(item["path"]) for item in candidates)
    pii_path.write_text(
        json.dumps(
            {
                "evidence_kind": "REAL_CORPUS_PII_SCAN",
                "scanner_version": "two-scope-scanner-v1",
                "scanner_sha256": "1" * 64,
                "policy_version": "two-scope-policy-v1",
                "policy_sha256": "2" * 64,
                "corpus_manifest_sha256": manifest_sha256,
                "remote_access_mode": "READ_ONLY",
                "remote_write_operations": 0,
                "raw_pii_in_output": False,
                "raw_pii_in_logs": False,
                "required_pdf_path_count": len(required_paths),
                "required_pdf_path_set_digest": hashlib.sha256(
                    "".join(f"{value}\n" for value in required_paths).encode()
                ).hexdigest(),
                "summary": {
                    "total_scanned": len(candidates),
                    "pii_scan_required": len(candidates),
                    "pii_scan_exempt": 0,
                    "sha256_mismatches": 0,
                    "pii_scan_scope": "ALL_CORPUS_PDFS",
                },
                "results": [
                    {
                        "content_sha256": item["content_sha256"],
                        "physical_object_count": 1,
                        "status": "CLEARED",
                        "error_code": None,
                    }
                    for item in candidates
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return currentness_path, rights_path, pii_path, routing_path


def test_production_v2_verifies_two_authorizations_profiles_and_exact_partition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog_path, set_relative, campaign_relative, release_inputs, authorization_set = (
        _write_two_scope_production_release(tmp_path, monkeypatch)
    )
    with pytest.raises(CatalogRepublishError, match="computed=") as caught:
        republish_catalog_v2_production(
            campaign_relative_path=campaign_relative,
            catalog_path=catalog_path,
            authorization_set_relative_path=set_relative,
            release_scope_git_inputs=release_inputs,
            out_root=tmp_path / "probe-production",
        )
    catalog_digest = str(caught.value).split("computed=", 1)[1][:64]
    release_inputs = _commit_two_scope_campaign(
        release_inputs=release_inputs,
        campaign_relative_path=campaign_relative,
        authorization_set=authorization_set,
        expected_catalog_digest=catalog_digest,
    )

    result = republish_catalog_v2_production(
        campaign_relative_path=campaign_relative,
        catalog_path=catalog_path,
        authorization_set_relative_path=set_relative,
        release_scope_git_inputs=release_inputs,
        out_root=tmp_path / "published-production",
    )

    document = json.loads(result.catalog_path.read_text(encoding="utf-8"))
    promoted = [
        item for item in document["physical_objects"] if item["disposition"] == "INGEST"
    ]
    assert len(promoted) == 2
    assert {item["scope_authorization_id"] for item in promoted} == {
        "auth-two-scope-1",
        "auth-two-scope-2",
    }
    assert {item["profile_id"] for item in promoted} == {
        "test_collection",
        "francais_collection",
    }
    assert {item["scope"]["collection"] for item in promoted} == {
        "test_collection",
        "francais_collection",
    }
    assert result.mapped_content_count == 2


@pytest.mark.parametrize(
    "input_name", ["catalog", "currentness", "rights", "pii", "routing"]
)
def test_production_v2_reads_each_catalog_evidence_input_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    input_name: str,
) -> None:
    catalog_path, set_relative, campaign_relative, release_inputs, _set = (
        _write_two_scope_production_release(tmp_path, monkeypatch)
    )
    currentness_path, rights_path, pii_path, routing_path = (
        _write_two_scope_currentness_inputs(tmp_path, catalog_path)
    )
    paths = {
        "catalog": catalog_path,
        "currentness": currentness_path,
        "rights": rights_path,
        "pii": pii_path,
        "routing": routing_path,
    }
    target = paths[input_name]
    original_read_bytes = Path.read_bytes
    reads = 0

    def fail_on_second_read(path: Path) -> bytes:
        nonlocal reads
        if path == target:
            reads += 1
            if reads > 1:
                raise AssertionError(f"TOCTOU second read of {input_name}")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_on_second_read)
    with pytest.raises(CatalogRepublishError, match="computed="):
        republish_catalog_v2_production(
            campaign_relative_path=campaign_relative,
            catalog_path=catalog_path,
            authorization_set_relative_path=set_relative,
            release_scope_git_inputs=release_inputs,
            out_root=tmp_path / f"single-read-{input_name}",
            currentness_verification_path=currentness_path,
            rights_path=rights_path,
            pii_path=pii_path,
            routing_path=routing_path,
        )
    assert reads == 1


def test_production_v2_ignores_uncommitted_fabricated_campaign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog_path, set_relative, campaign_relative, release_inputs, authorization_set = (
        _write_two_scope_production_release(tmp_path, monkeypatch)
    )
    with pytest.raises(CatalogRepublishError, match="computed=") as caught:
        republish_catalog_v2_production(
            campaign_relative_path=campaign_relative,
            catalog_path=catalog_path,
            authorization_set_relative_path=set_relative,
            release_scope_git_inputs=release_inputs,
            out_root=tmp_path / "probe-campaign",
        )
    catalog_digest = str(caught.value).split("computed=", 1)[1][:64]
    forged = _v2_campaign(
        authorization_set,
        expected_catalog_digest=catalog_digest,
        expected_manifest_sha256=authorization_set.corpus_manifest_sha256,
    )
    (release_inputs.repository_root / campaign_relative).write_bytes(
        forged.canonical_bytes()
    )

    with pytest.raises(CatalogRepublishError, match="computed="):
        republish_catalog_v2_production(
            campaign_relative_path=campaign_relative,
            catalog_path=catalog_path,
            authorization_set_relative_path=set_relative,
            release_scope_git_inputs=release_inputs,
            out_root=tmp_path / "uncommitted-campaign",
        )


def test_production_v2_freezes_authority_material_from_exact_git_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog_path, set_relative, campaign_relative, release_inputs, authorization_set = (
        _write_two_scope_production_release(tmp_path, monkeypatch)
    )
    dirty_authorization = (
        release_inputs.repository_root
        / canonical_authorization_path("auth-two-scope-1")
    )
    dirty_authorization.write_bytes(b"{}\n")

    with pytest.raises(CatalogRepublishError, match="computed="):
        republish_catalog_v2_production(
            campaign_relative_path=campaign_relative,
            catalog_path=catalog_path,
            authorization_set_relative_path=set_relative,
            release_scope_git_inputs=release_inputs,
            out_root=tmp_path / "exact-tree",
        )


def test_production_v2_refuses_expired_real_clock_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_path, set_relative, campaign_relative, release_inputs, authorization_set = (
        _write_two_scope_production_release(tmp_path, monkeypatch)
    )
    monkeypatch.setattr(
        catalog_republish_module,
        "_trusted_utc_now",
        lambda: datetime(2027, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(CatalogRepublishError, match="expired"):
        republish_catalog_v2_production(
            campaign_relative_path=campaign_relative,
            catalog_path=catalog_path,
            authorization_set_relative_path=set_relative,
            release_scope_git_inputs=release_inputs,
            out_root=tmp_path / "expired",
        )


def test_production_v2_refuses_set_catalog_manifest_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_path, set_relative, campaign_relative, release_inputs, authorization_set = (
        _write_two_scope_production_release(tmp_path, monkeypatch)
    )
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["manifest_sha256"] = "0" * 64
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(CatalogRepublishError, match="corpus manifest differs"):
        republish_catalog_v2_production(
            campaign_relative_path=campaign_relative,
            catalog_path=catalog_path,
            authorization_set_relative_path=set_relative,
            release_scope_git_inputs=release_inputs,
            out_root=tmp_path / "mismatch",
        )


def test_production_v2_refuses_profile_manifest_set_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_path, set_relative, campaign_relative, release_inputs, authorization_set = (
        _write_two_scope_production_release(tmp_path, monkeypatch)
    )
    profile_manifest = release_inputs.repository_root / release_inputs.profile_manifest_path
    document = yaml.safe_load(profile_manifest.read_text(encoding="utf-8"))
    document["provenance"] = "manifest divergent"
    profile_manifest.write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=release_inputs.repository_root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Nexus Tests",
            "-c",
            "user.email=tests@nexus.invalid",
            "commit",
            "-qm",
            "diverge profile manifest",
        ],
        cwd=release_inputs.repository_root,
        check=True,
    )
    tree_sha = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=release_inputs.repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    release_inputs = replace(release_inputs, source_tree_sha=tree_sha)
    with pytest.raises(CatalogRepublishError, match="PROFILE_MANIFEST_MISMATCH"):
        republish_catalog_v2_production(
            campaign_relative_path=campaign_relative,
            catalog_path=catalog_path,
            authorization_set_relative_path=set_relative,
            release_scope_git_inputs=release_inputs,
            out_root=tmp_path / "profile-mismatch",
        )


def _discover_v2_catalog_digest(
    *,
    catalog_path: Path,
    authorization_set: AuthorizationSetV1,
    verified: VerifiedAuthorizationSetV1,
    placement: ReleaseScopePlacementV1,
    authorization_member_bytes: dict[str, bytes],
    tmp_path: Path,
) -> str:
    with pytest.raises(CatalogRepublishError, match="computed=") as caught:
        republish_catalog_v2(
            campaign=_v2_campaign(
                authorization_set, expected_catalog_digest="0" * 64
            ),
            catalog_path=catalog_path,
            authorization_set=authorization_set,
            verified_authorization_set=verified,
            release_scope_placement=placement,
            authorization_member_bytes=authorization_member_bytes,
            out_root=tmp_path / "probe-v2",
        )
    return str(caught.value).split("computed=", 1)[1][:64]


def test_v2_republish_materializes_exact_authorization_profile_and_scope(
    tmp_path: Path,
) -> None:
    catalog_path = _write_real_catalog(tmp_path)
    authorization_set, verified, placement, member_bytes = _v2_release()
    catalog_digest = _discover_v2_catalog_digest(
        catalog_path=catalog_path,
        authorization_set=authorization_set,
        verified=verified,
        placement=placement,
        authorization_member_bytes=member_bytes,
        tmp_path=tmp_path,
    )

    result = republish_catalog_v2(
        campaign=_v2_campaign(
            authorization_set, expected_catalog_digest=catalog_digest
        ),
        catalog_path=catalog_path,
        authorization_set=authorization_set,
        verified_authorization_set=verified,
        release_scope_placement=placement,
        authorization_member_bytes=member_bytes,
        out_root=tmp_path / "published-v2",
    )

    catalog = json.loads(result.catalog_path.read_text(encoding="utf-8"))
    promoted = next(
        item for item in catalog["physical_objects"] if item["content_sha256"] == CONTENT_SHA256
    )
    placement_entry = placement.placements[0]
    assert promoted["disposition"] == "INGEST"
    assert promoted["scope_authorization_id"] == "auth-v2-test"
    assert promoted["profile_id"] == placement_entry.profile_id
    assert promoted["profile_version"] == placement_entry.profile_version
    assert promoted["profile_fingerprint"] == placement_entry.profile_fingerprint
    assert promoted["scope"] == placement_entry.scope.model_dump(mode="json")
    assert result.authorization_set_digest == authorization_set.digest()
    digest_document = json.loads(result.digest_path.read_text(encoding="utf-8"))
    assert digest_document["protocol_version"] == CATALOG_DIGEST_V2_PROTOCOL_VERSION
    assert digest_document["authorization_set_digest"] == authorization_set.digest()
    assert digest_document["mapped_content_count"] == 1
    assert digest_document["authority_required_count"] == 1
    assert digest_document["authority_required_set_sha256"] == (
        authorization_set.authority_required_set_sha256
    )
    assert digest_document["content_mapping_digest"]
    assert digest_document["content_mappings"] == [
        {
            "authorization_digest": authorization_set.members[0].authorization_digest,
            "authorized_rights_categories": ["officiel_public"],
            "content_sha256": CONTENT_SHA256,
            "profile_fingerprint": placement_entry.profile_fingerprint,
            "profile_id": placement_entry.profile_id,
            "profile_version": placement_entry.profile_version,
            "required_rights_category": "officiel_public",
            "review_binding_digest": authorization_set.members[0].review_binding_digest,
            "scope": placement_entry.scope.model_dump(mode="json"),
            "scope_authorization_id": "auth-v2-test",
            "scope_digest": authorization_set.members[0].scope_digest,
        }
    ]


def test_v2_republish_refuses_set_union_extra_to_catalog(tmp_path: Path) -> None:
    catalog_path = _write_real_catalog(tmp_path)
    authorization_set, verified, placement, member_bytes = _v2_release(
        member_contents=(CONTENT_SHA256, "b" * 64)
    )
    with pytest.raises(CatalogRepublishError, match="extra"):
        republish_catalog_v2(
            campaign=_v2_campaign(
                authorization_set, expected_catalog_digest="0" * 64
            ),
            catalog_path=catalog_path,
            authorization_set=authorization_set,
            verified_authorization_set=verified,
            release_scope_placement=placement,
            authorization_member_bytes=member_bytes,
            out_root=tmp_path / "out",
        )


def test_v2_republish_refuses_placement_scope_mismatch(tmp_path: Path) -> None:
    catalog_path = _write_real_catalog(tmp_path)
    authorization_set, verified, placement, member_bytes = _v2_release(
        placement_scope=_v2_scope(collection="another_collection")
    )
    with pytest.raises(CatalogRepublishError, match="scope mismatch"):
        republish_catalog_v2(
            campaign=_v2_campaign(
                authorization_set, expected_catalog_digest="0" * 64
            ),
            catalog_path=catalog_path,
            authorization_set=authorization_set,
            verified_authorization_set=verified,
            release_scope_placement=placement,
            authorization_member_bytes=member_bytes,
            out_root=tmp_path / "out",
        )


def test_v2_republish_refuses_catalog_candidate_missing_from_set(tmp_path: Path) -> None:
    catalog_path = _write_real_catalog(tmp_path)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    second = dict(catalog["physical_objects"][0])
    second["content_sha256"] = "b" * 64
    second["path"] = "01_EDUSCOL_OFFICIEL/second.pdf"
    second["attribution_metadata"] = {
        "source": "Eduscol",
        "source_url": "https://eduscol.education.gouv.fr/second",
    }
    catalog["physical_objects"].insert(1, second)
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    authorization_set, verified, placement, member_bytes = _v2_release()

    with pytest.raises(CatalogRepublishError, match="gap"):
        republish_catalog_v2(
            campaign=_v2_campaign(
                authorization_set, expected_catalog_digest="0" * 64
            ),
            catalog_path=catalog_path,
            authorization_set=authorization_set,
            verified_authorization_set=verified,
            release_scope_placement=placement,
            authorization_member_bytes=member_bytes,
            out_root=tmp_path / "out",
        )


def test_v2_republish_refuses_stale_or_forged_verified_projection(tmp_path: Path) -> None:
    catalog_path = _write_real_catalog(tmp_path)
    authorization_set, verified, placement, member_bytes = _v2_release()
    campaign = _v2_campaign(authorization_set, expected_catalog_digest="0" * 64)

    with pytest.raises(CatalogRepublishError, match="republish moment"):
        republish_catalog_v2(
            campaign=campaign,
            catalog_path=catalog_path,
            authorization_set=authorization_set,
            verified_authorization_set=replace(
                verified, verified_at=datetime(2026, 5, 31, tzinfo=UTC)
            ),
            release_scope_placement=placement,
            authorization_member_bytes=member_bytes,
            out_root=tmp_path / "stale",
        )

    with pytest.raises(CatalogRepublishError, match="content authorization mapping"):
        republish_catalog_v2(
            campaign=campaign,
            catalog_path=catalog_path,
            authorization_set=authorization_set,
            verified_authorization_set=replace(
                verified,
                content_authorization_ids=((CONTENT_SHA256, "another-auth"),),
            ),
            release_scope_placement=placement,
            authorization_member_bytes=member_bytes,
            out_root=tmp_path / "forged",
        )


@pytest.mark.parametrize(
    ("rights_category", "message"),
    [
        (None, "non-canonical"),
        ("OFFICIEL_PUBLIC", "non-canonical"),
        ("restricted", "does not grant"),
    ],
)
def test_v2_republish_verifies_every_required_rights_occurrence(
    tmp_path: Path,
    rights_category: str | None,
    message: str,
) -> None:
    catalog_path = _write_real_catalog(tmp_path)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    candidate = catalog["physical_objects"][0]
    if rights_category is None:
        candidate.pop("rights_category_candidate")
    else:
        candidate["rights_category_candidate"] = rights_category
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    authorization_set, verified, placement, member_bytes = _v2_release()

    with pytest.raises(CatalogRepublishError, match=message):
        republish_catalog_v2(
            campaign=_v2_campaign(
                authorization_set, expected_catalog_digest="0" * 64
            ),
            catalog_path=catalog_path,
            authorization_set=authorization_set,
            verified_authorization_set=verified,
            release_scope_placement=placement,
            authorization_member_bytes=member_bytes,
            out_root=tmp_path / "out",
        )


def test_v2_republish_refuses_duplicate_sha_with_divergent_rights(tmp_path: Path) -> None:
    catalog_path = _write_real_catalog(tmp_path)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    duplicate = json.loads(json.dumps(catalog["physical_objects"][0]))
    duplicate["path"] = "01_EDUSCOL_OFFICIEL/duplicate.pdf"
    duplicate["rights_category_candidate"] = "restricted"
    catalog["physical_objects"].insert(1, duplicate)
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    authorization_set, verified, placement, member_bytes = _v2_release(
        rights_categories=("officiel_public", "restricted")
    )

    with pytest.raises(CatalogRepublishError, match="divergent rights"):
        republish_catalog_v2(
            campaign=_v2_campaign(
                authorization_set, expected_catalog_digest="0" * 64
            ),
            catalog_path=catalog_path,
            authorization_set=authorization_set,
            verified_authorization_set=verified,
            release_scope_placement=placement,
            authorization_member_bytes=member_bytes,
            out_root=tmp_path / "out",
        )


@pytest.mark.parametrize(("mutation", "message"), [("missing", "missing"), ("extra", "extras"), ("digest", "digest mismatch")])
def test_v2_republish_requires_exact_member_bytes(
    tmp_path: Path, mutation: str, message: str
) -> None:
    catalog_path = _write_real_catalog(tmp_path)
    authorization_set, verified, placement, member_bytes = _v2_release()
    supplied: dict[str, bytes | bytearray] = dict(member_bytes)
    if mutation == "missing":
        supplied.clear()
    elif mutation == "extra":
        supplied["governance/authorizations/extra.json"] = b"{}\n"
    else:
        supplied[next(iter(supplied))] = bytearray(b"{}\n")

    with pytest.raises(CatalogRepublishError, match=message):
        republish_catalog_v2(
            campaign=_v2_campaign(
                authorization_set, expected_catalog_digest="0" * 64
            ),
            catalog_path=catalog_path,
            authorization_set=authorization_set,
            verified_authorization_set=verified,
            release_scope_placement=placement,
            authorization_member_bytes=supplied,
            out_root=tmp_path / "out",
        )


def test_v2_republish_uses_internal_clock_and_refuses_expired_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del tmp_path, monkeypatch
    parameters = inspect.signature(republish_catalog_v2_production).parameters
    assert "campaign" not in parameters
    assert "campaign_relative_path" in parameters
    assert "now" not in parameters
    assert "verified_authorization_set" not in parameters
    assert "authorization_set" not in parameters
    assert "authorization_member_bytes" not in parameters


def _publish_valid_v2(
    tmp_path: Path,
) -> tuple[
    CorpusCampaignV2,
    AuthorizationSetV1,
    VerifiedAuthorizationSetV1,
    ReleaseScopePlacementV1,
    dict[str, bytes],
    Path,
    Path,
]:
    catalog_path = _write_real_catalog(tmp_path)
    authorization_set, verified, placement, member_bytes = _v2_release()
    catalog_digest = _discover_v2_catalog_digest(
        catalog_path=catalog_path,
        authorization_set=authorization_set,
        verified=verified,
        placement=placement,
        authorization_member_bytes=member_bytes,
        tmp_path=tmp_path,
    )
    campaign = _v2_campaign(
        authorization_set, expected_catalog_digest=catalog_digest
    )
    out_root = tmp_path / "published"
    result = republish_catalog_v2(
        campaign=campaign,
        catalog_path=catalog_path,
        authorization_set=authorization_set,
        verified_authorization_set=verified,
        release_scope_placement=placement,
        authorization_member_bytes=member_bytes,
        out_root=out_root,
    )
    return (
        campaign,
        authorization_set,
        verified,
        placement,
        member_bytes,
        catalog_path,
        result.digest_path,
    )


@pytest.mark.parametrize(
    "field",
    [
        "protocol_version",
        "campaign_id",
        "catalog_sha256",
        "promoted_count",
        "mapped_content_count",
        "authorization_set_digest",
        "release_scope_placement_digest",
        "profile_manifest_digest",
        "authority_required_count",
        "authority_required_set_sha256",
        "content_mapping_digest",
        "content_mappings",
        "generated_at",
        "missing",
        "extra",
    ],
)
def test_v2_republish_refuses_every_mutated_existing_proof_field(
    tmp_path: Path, field: str
) -> None:
    (
        campaign,
        authorization_set,
        verified,
        placement,
        member_bytes,
        catalog_path,
        digest_path,
    ) = _publish_valid_v2(tmp_path)
    document = json.loads(digest_path.read_text(encoding="utf-8"))
    if field == "missing":
        document.pop("campaign_id")
    elif field == "extra":
        document["unexpected"] = "forbidden"
    elif field == "generated_at":
        document[field] = "2026-06-02T00:00:00Z"
    elif field in {"promoted_count", "mapped_content_count", "authority_required_count"}:
        document[field] = True
    elif field == "content_mappings":
        document[field][0]["required_rights_category"] = "restricted"
    else:
        document[field] = (
            "NEXUS-CATALOG-REPUBLISH-DIGEST-V999"
            if field == "protocol_version"
            else "0" * 64
        )
    digest_path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(CatalogRepublishError, match="V2 digest"):
        republish_catalog_v2(
            campaign=campaign,
            catalog_path=catalog_path,
            authorization_set=authorization_set,
            verified_authorization_set=verified,
            release_scope_placement=placement,
            authorization_member_bytes=member_bytes,
            out_root=tmp_path / "published",
        )


def test_v2_republish_refuses_noncanonical_existing_proof_bytes(tmp_path: Path) -> None:
    (
        campaign,
        authorization_set,
        verified,
        placement,
        member_bytes,
        catalog_path,
        digest_path,
    ) = _publish_valid_v2(tmp_path)
    document = json.loads(digest_path.read_text(encoding="utf-8"))
    digest_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(CatalogRepublishError, match="not canonical"):
        republish_catalog_v2(
            campaign=campaign,
            catalog_path=catalog_path,
            authorization_set=authorization_set,
            verified_authorization_set=verified,
            release_scope_placement=placement,
            authorization_member_bytes=member_bytes,
            out_root=tmp_path / "published",
        )


def test_v2_republish_accepts_only_fully_consistent_existing_proof(tmp_path: Path) -> None:
    (
        campaign,
        authorization_set,
        verified,
        placement,
        member_bytes,
        catalog_path,
        _digest_path,
    ) = _publish_valid_v2(tmp_path)

    result = republish_catalog_v2(
        campaign=campaign,
        catalog_path=catalog_path,
        authorization_set=authorization_set,
        verified_authorization_set=verified,
        release_scope_placement=placement,
        authorization_member_bytes=member_bytes,
        out_root=tmp_path / "published",
    )
    assert result.already_published is True


def _replay_component_publication(
    *,
    campaign: CorpusCampaignV2,
    authorization_set: AuthorizationSetV1,
    verified: VerifiedAuthorizationSetV1,
    placement: ReleaseScopePlacementV1,
    member_bytes: dict[str, bytes],
    catalog_path: Path,
    out_root: Path,
):
    return republish_catalog_v2(
        campaign=campaign,
        catalog_path=catalog_path,
        authorization_set=authorization_set,
        verified_authorization_set=verified,
        release_scope_placement=placement,
        authorization_member_bytes=member_bytes,
        out_root=out_root,
    )


def test_v2_publication_refuses_symlinked_output_components(tmp_path: Path) -> None:
    (
        campaign,
        authorization_set,
        verified,
        placement,
        member_bytes,
        catalog_path,
        _digest_path,
    ) = _publish_valid_v2(tmp_path)
    unsafe_root = tmp_path / "unsafe-root"
    outside = tmp_path / "outside"
    unsafe_root.mkdir()
    outside.mkdir()
    (unsafe_root / "governance").symlink_to(outside, target_is_directory=True)

    with pytest.raises(CatalogRepublishError, match="unsafe governed publication"):
        _replay_component_publication(
            campaign=campaign,
            authorization_set=authorization_set,
            verified=verified,
            placement=placement,
            member_bytes=member_bytes,
            catalog_path=catalog_path,
            out_root=unsafe_root,
        )
    assert list(outside.iterdir()) == []


def test_v2_publication_recovers_exact_orphan_catalog_without_overwrite(
    tmp_path: Path,
) -> None:
    (
        campaign,
        authorization_set,
        verified,
        placement,
        member_bytes,
        catalog_path,
        digest_path,
    ) = _publish_valid_v2(tmp_path)
    source_catalog = digest_path.with_name("catalog.json").read_bytes()
    recovery_root = tmp_path / "recovery"
    recovery_dir = recovery_root / campaign.canonical_dir()
    recovery_dir.mkdir(parents=True)
    orphan_catalog = recovery_dir / "catalog.json"
    orphan_catalog.write_bytes(source_catalog)

    result = _replay_component_publication(
        campaign=campaign,
        authorization_set=authorization_set,
        verified=verified,
        placement=placement,
        member_bytes=member_bytes,
        catalog_path=catalog_path,
        out_root=recovery_root,
    )

    assert result.already_published is False
    assert orphan_catalog.read_bytes() == source_catalog
    assert result.digest_path.is_file()


def test_v2_publication_refuses_inconsistent_orphan_catalog_or_sidecar(
    tmp_path: Path,
) -> None:
    (
        campaign,
        authorization_set,
        verified,
        placement,
        member_bytes,
        catalog_path,
        _digest_path,
    ) = _publish_valid_v2(tmp_path)
    for kind in ("catalog", "sidecar"):
        out_root = tmp_path / kind
        campaign_dir = out_root / campaign.canonical_dir()
        campaign_dir.mkdir(parents=True)
        if kind == "catalog":
            (campaign_dir / "catalog.json").write_bytes(b"{}\n")
            message = "never overwritten"
        else:
            (campaign_dir / "catalog.digest.json").write_bytes(b"{}\n")
            message = "orphan V2 digest"
        with pytest.raises(CatalogRepublishError, match=message):
            _replay_component_publication(
                campaign=campaign,
                authorization_set=authorization_set,
                verified=verified,
                placement=placement,
                member_bytes=member_bytes,
                catalog_path=catalog_path,
                out_root=out_root,
            )


def test_v2_publication_recovers_crash_before_sidecar_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        campaign,
        authorization_set,
        verified,
        placement,
        member_bytes,
        catalog_path,
        _digest_path,
    ) = _publish_valid_v2(tmp_path)
    out_root = tmp_path / "crash-recovery"
    original = catalog_republish_module._atomic_create_file  # noqa: SLF001
    calls = 0

    def fail_before_commit(directory_fd: int, name: str, raw: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated crash before commit marker")
        original(directory_fd, name, raw)

    monkeypatch.setattr(
        catalog_republish_module, "_atomic_create_file", fail_before_commit
    )
    with pytest.raises(CatalogRepublishError, match="simulated crash"):
        _replay_component_publication(
            campaign=campaign,
            authorization_set=authorization_set,
            verified=verified,
            placement=placement,
            member_bytes=member_bytes,
            catalog_path=catalog_path,
            out_root=out_root,
        )
    campaign_dir = out_root / campaign.canonical_dir()
    assert (campaign_dir / "catalog.json").is_file()
    assert not (campaign_dir / "catalog.digest.json").exists()

    monkeypatch.setattr(catalog_republish_module, "_atomic_create_file", original)
    recovered = _replay_component_publication(
        campaign=campaign,
        authorization_set=authorization_set,
        verified=verified,
        placement=placement,
        member_bytes=member_bytes,
        catalog_path=catalog_path,
        out_root=out_root,
    )
    assert recovered.digest_path.is_file()


def test_v2_publication_refuses_symlinked_catalog_member(tmp_path: Path) -> None:
    (
        campaign,
        authorization_set,
        verified,
        placement,
        member_bytes,
        catalog_path,
        _digest_path,
    ) = _publish_valid_v2(tmp_path)
    out_root = tmp_path / "symlink-member"
    campaign_dir = out_root / campaign.canonical_dir()
    campaign_dir.mkdir(parents=True)
    outside = tmp_path / "outside-catalog.json"
    outside.write_bytes(b"{}\n")
    (campaign_dir / "catalog.json").symlink_to(outside)

    with pytest.raises(CatalogRepublishError, match="atomic governed publication"):
        _replay_component_publication(
            campaign=campaign,
            authorization_set=authorization_set,
            verified=verified,
            placement=placement,
            member_bytes=member_bytes,
            catalog_path=catalog_path,
            out_root=out_root,
        )


def test_republish_and_h2_report_compute_the_same_authority_required_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8 de l'audit du 2026-08-15 :
    ``H2_AUTHORITY_REQUIRED_SET_SHA256 == REPUBLISH_AUTHORITY_REQUIRED_SET_SHA256``
    pour le même catalogue promu -- les deux producteurs réutilisent
    ``authority_required_candidate_facts``/``authority_required_set_digest``,
    ils ne doivent jamais diverger silencieusement."""
    campaign, catalog_path, authority_path, binding_path = _setup_real(
        tmp_path, monkeypatch
    )

    result = republish_catalog(
        campaign=campaign,
        catalog_path=catalog_path,
        authority_path=authority_path,
        authority_review_binding_path=binding_path,
        out_root=tmp_path / "repo",
        now=AUTHORITY_NOW,
    )
    assert result.authority_required_set_sha256

    # CONTENT_SHA256/MANIFEST_SHA256 ici sont dérivés de la même formule
    # que dans ``test_h2b_coverage_report.py`` (même contenu, même chemin)
    # -- les preuves externes de ce module s'appliquent donc telles
    # quelles au catalogue local de ce fichier.
    assert gate_fixtures.CONTENT_SHA256 == CONTENT_SHA256
    assert gate_fixtures.MANIFEST_SHA256 == MANIFEST_SHA256
    routing_path, rights_path, pii_path, _unused, manifest_path = (
        gate_fixtures._write_external_evidence(tmp_path, include_authority=False)
    )
    golden_path = gate_fixtures._write_golden_spec(
        tmp_path,
        expected_final="REVIEW_REQUIRED",
        expected_authority="BLOCKED_NOT_CLEARED",
    )

    report = h2b_module.generate_coverage_report(
        catalog_path,
        rights_path=rights_path,
        pii_path=pii_path,
        routing_path=routing_path,
        golden_path=golden_path,
        manifest_path=manifest_path,
        authority_path=authority_path,
        authority_review_binding_path=binding_path,
        authority_environment="production",
        expected_total=2,
        expected_manifest_sha256=MANIFEST_SHA256,
        authority_now=AUTHORITY_NOW,
    )
    assert report.authority_required_set_sha256

    assert report.authority_required_set_sha256 == result.authority_required_set_sha256


_ORDERING_CONTENT_OLD = "5" * 64
_ORDERING_CONTENT_NEW = "6" * 64
_ORDERING_MANIFEST_CONTENT = (
    f"{_ORDERING_CONTENT_OLD}  01_EDUSCOL_OFFICIEL/old.pdf\n"
    f"{_ORDERING_CONTENT_NEW}  01_EDUSCOL_OFFICIEL/new.pdf\n"
)
_ORDERING_MANIFEST_SHA256 = hashlib.sha256(_ORDERING_MANIFEST_CONTENT.encode()).hexdigest()


def _write_ordering_regression_fixtures(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, Path]:
    """Deux candidats : l'un déjà ``actuel`` (stand-in pour les 64
    historiques), l'autre ``unclassified`` qui ne devient un candidat
    INGEST réel qu'après promotion par currentness (stand-in pour les 9
    de PR#122). Rend ``(catalog, routing, rights, pii, currentness_evidence)``."""
    manifest_path = tmp_path / "00_ADMIN" / "SHA256SUMS.txt"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(_ORDERING_MANIFEST_CONTENT, encoding="utf-8")

    catalog = {
        "catalog_kind": "REAL_SEALED_CORPUS",
        "manifest_sha256": _ORDERING_MANIFEST_SHA256,
        "manifest_entries": 2,
        "physical_object_count": 3,
        "content_artifact_count": 2,
        "disposition_counts": {
            "INGEST": 0,
            "REVIEW_REQUIRED": 2,
            "QUARANTINE": 0,
            "ARCHIVE_ONLY": 0,
            "EXCLUDE": 1,
            "UNSUPPORTED": 0,
        },
        "unclassified": 0,
        "multiple_primary_disposition": 0,
        "verification_passed": True,
        "verification_errors": [],
        "physical_objects": [
            {
                "content_sha256": _ORDERING_CONTENT_OLD,
                "path": "01_EDUSCOL_OFFICIEL/old.pdf",
                "base_disposition": "INGEST",
                "disposition": "REVIEW_REQUIRED",
                "zone": "01_EDUSCOL_OFFICIEL/",
                "currentness": "actuel",
                "rights_category_candidate": "officiel_public",
                "gate_statuses": {
                    "rights": "PASS",
                    "pii": "PASS",
                    "authority": "BLOCKED_NOT_CLEARED",
                },
                "provenance_status": "VERIFIED",
                "attribution_metadata": {
                    "source": "Eduscol",
                    "source_url": "https://eduscol.education.gouv.fr/old",
                },
            },
            {
                "content_sha256": _ORDERING_CONTENT_NEW,
                "path": "01_EDUSCOL_OFFICIEL/new.pdf",
                "base_disposition": "REVIEW_REQUIRED",
                "disposition": "REVIEW_REQUIRED",
                "zone": "01_EDUSCOL_OFFICIEL/",
                "currentness": "unclassified",
                "rights_category_candidate": "officiel_public",
                "gate_statuses": {},
                "provenance_status": "VERIFIED",
                "attribution_metadata": {
                    "source": "Eduscol",
                    "source_url": "https://eduscol.education.gouv.fr/new",
                },
            },
            {
                "content_sha256": _ORDERING_MANIFEST_SHA256,
                "path": "00_ADMIN/SHA256SUMS.txt",
                "base_disposition": "EXCLUDE",
                "disposition": "EXCLUDE",
                "zone": "00_ADMIN/",
                "currentness": None,
                "gate_statuses": {},
                "provenance_status": "VERIFIED",
                "attribution_metadata": {
                    "source": "NEXUS_CORPUS_GOVERNANCE",
                    "source_reference": "00_ADMIN/SHA256SUMS.txt",
                },
            },
        ],
    }
    catalog_path = tmp_path / "ordering-catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    routing = {
        "config_id": "ordering-routing-v1",
        "manifest_sha256": _ORDERING_MANIFEST_SHA256,
        "rights_evidence_perimeter": ["00_ADMIN/", "01_EDUSCOL_OFFICIEL/"],
        "zone_rules": [
            {"zone_prefix": "00_ADMIN/", "disposition": "EXCLUDE", "reason": "admin"},
            {
                "zone_prefix": "01_EDUSCOL_OFFICIEL/",
                "disposition": "INGEST",
                "currentness": "actuel",
            },
        ],
    }
    rights = {
        "registry_id": "ordering-rights-v1",
        "human_rights_decisions": {
            "eduscol": {
                "decision_type": "HUMAN_ORGANIZATIONAL_RIGHTS_APPROVAL",
                "decision_maker": "Nexus Réussite",
                "decision_date": "2026-08-08",
                "scope_manifest_sha256": _ORDERING_MANIFEST_SHA256,
                "scope_zone": "01_EDUSCOL_OFFICIEL/",
                "approved_for_production_rag": True,
                "generic_rights_blocker": False,
            }
        },
        "source_evidence": {
            "admin": {
                "zone": "00_ADMIN/",
                "rights_status": "REVIEW_REQUIRED",
                "disposition_override": "EXCLUDE",
            },
            "eduscol": {
                "zone": "01_EDUSCOL_OFFICIEL/",
                "rights_status": "CLEARED_BY_HUMAN_DECISION",
                "rights_decision_ref": "eduscol",
            },
        },
        "summary": {"total_zones": 2},
    }
    required_paths = sorted(
        ["01_EDUSCOL_OFFICIEL/old.pdf", "01_EDUSCOL_OFFICIEL/new.pdf"]
    )
    pii = {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "scanner_version": "ordering-scanner-v1",
        "scanner_sha256": "1" * 64,
        "policy_version": "ordering-policy-v1",
        "policy_sha256": "2" * 64,
        "corpus_manifest_sha256": _ORDERING_MANIFEST_SHA256,
        "remote_access_mode": "READ_ONLY",
        "remote_write_operations": 0,
        "raw_pii_in_output": False,
        "raw_pii_in_logs": False,
        "required_pdf_path_count": len(required_paths),
        "required_pdf_path_set_digest": hashlib.sha256(
            "".join(f"{value}\n" for value in required_paths).encode()
        ).hexdigest(),
        "summary": {
            "sha256_mismatches": 0,
            "pii_scan_scope": "ALL_CORPUS_PDFS",
            "pii_scan_required": len(required_paths),
            "pii_scan_exempt": 0,
        },
        "results": [
            {
                "content_sha256": _ORDERING_CONTENT_OLD,
                "physical_object_count": 1,
                "status": "CLEARED",
                "error_code": None,
            },
            {
                "content_sha256": _ORDERING_CONTENT_NEW,
                "physical_object_count": 1,
                "status": "CLEARED",
                "error_code": None,
            },
        ],
    }
    routing_path = tmp_path / "ordering-routing.yml"
    rights_path = tmp_path / "ordering-rights.yml"
    pii_path = tmp_path / "ordering-pii.json"
    routing_path.write_text(yaml.safe_dump(routing), encoding="utf-8")
    rights_path.write_text(yaml.safe_dump(rights), encoding="utf-8")
    pii_path.write_text(json.dumps(pii), encoding="utf-8")

    currentness_evidence_path = tmp_path / "ordering-currentness.yml"
    currentness_evidence_path.write_text(
        yaml.safe_dump(
            {
                "evidence_kind": "MULTILEVEL_ARTIFACT_CURRENTNESS_V1",
                "corpus_manifest_sha256": _ORDERING_MANIFEST_SHA256,
                "artifacts": [
                    {
                        "content_sha256": _ORDERING_CONTENT_NEW,
                        "decision": "CURRENT",
                        "byte_identity": True,
                        "current_download_sha256": _ORDERING_CONTENT_NEW,
                        "effective_currentness": "actuel",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    return catalog_path, routing_path, rights_path, pii_path, currentness_evidence_path


def test_republish_refuses_when_authority_misses_the_currentness_promoted_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Régression directe pour ``catalog_republish.py`` du même Finding
    #1 que ``test_currentness_promoted_candidate_is_required_by_authority``
    (``test_currentness_verification_promotion.py``) : le périmètre requis
    doit être mesuré ICI aussi après la promotion currentness, jamais
    avant -- une autorité qui ne couvre que l'ancien candidat doit être
    refusée."""
    _install_governed_root(monkeypatch, tmp_path)
    (
        catalog_path,
        routing_path,
        rights_path,
        pii_path,
        currentness_evidence_path,
    ) = _write_ordering_regression_fixtures(tmp_path)

    authority_document = _authority_document(
        authorization_id="ordering-regression-authority",
        manifest_digest=_ORDERING_MANIFEST_SHA256,
        # Ne couvre QUE l'ancien candidat -- jamais celui promu par
        # currentness.
        allowed_content_sha256=[_ORDERING_CONTENT_OLD],
    )
    authority_path = _write_authority(tmp_path / "authority.json", authority_document)
    binding_path = _write_review_binding(tmp_path, authority_document)

    campaign = _campaign(
        expected_manifest_sha256=_ORDERING_MANIFEST_SHA256,
        authorization_id="ordering-regression-authority",
        expected_catalog_digest="0" * 64,  # jamais atteint : refus avant
    )

    with pytest.raises(ValueError, match="SEMANTIC_VALIDATION"):
        republish_catalog(
            campaign=campaign,
            catalog_path=catalog_path,
            authority_path=authority_path,
            authority_review_binding_path=binding_path,
            out_root=tmp_path / "repo",
            now=AUTHORITY_NOW,
            currentness_verification_path=currentness_evidence_path,
            rights_path=rights_path,
            pii_path=pii_path,
            routing_path=routing_path,
        )


def test_rehearsal_campaign_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    campaign, catalog_path, authority_path, binding_path = _setup_real(
        tmp_path, monkeypatch, campaign_environment="rehearsal"
    )

    with pytest.raises(CatalogRepublishError, match="rehearsal"):
        republish_catalog(
            campaign=campaign,
            catalog_path=catalog_path,
            authority_path=authority_path,
            authority_review_binding_path=binding_path,
            out_root=tmp_path / "repo",
            now=AUTHORITY_NOW,
        )


def test_authorization_id_mismatch_between_campaign_and_authority_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_governed_root(monkeypatch, tmp_path)
    catalog_path = _write_real_catalog(tmp_path)
    authority = _authority_document()
    authority_path = _write_authority(tmp_path / "authority.json", authority)
    binding_path = _write_review_binding(tmp_path, authority)
    campaign = _campaign(authorization_id="a-different-authorization")

    with pytest.raises(CatalogRepublishError, match="authorization"):
        republish_catalog(
            campaign=campaign,
            catalog_path=catalog_path,
            authority_path=authority_path,
            authority_review_binding_path=binding_path,
            out_root=tmp_path / "repo",
            now=AUTHORITY_NOW,
        )


def test_manifest_mismatch_between_catalog_and_campaign_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_governed_root(monkeypatch, tmp_path)
    catalog_path = _write_real_catalog(tmp_path)
    authority = _authority_document()
    authority_path = _write_authority(tmp_path / "authority.json", authority)
    binding_path = _write_review_binding(tmp_path, authority)
    campaign = _campaign(expected_manifest_sha256="f" * 64)

    with pytest.raises(CatalogRepublishError, match="manifest"):
        republish_catalog(
            campaign=campaign,
            catalog_path=catalog_path,
            authority_path=authority_path,
            authority_review_binding_path=binding_path,
            out_root=tmp_path / "repo",
            now=AUTHORITY_NOW,
        )


def test_computed_digest_not_matching_campaigns_expected_catalog_digest_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_governed_root(monkeypatch, tmp_path)
    catalog_path = _write_real_catalog(tmp_path)
    authority = _authority_document()
    authority_path = _write_authority(tmp_path / "authority.json", authority)
    binding_path = _write_review_binding(tmp_path, authority)
    # Digest placeholder délibérément faux : aucune promotion réelle ne
    # peut jamais y correspondre.
    campaign = _campaign(expected_catalog_digest="0" * 64)

    with pytest.raises(CatalogRepublishError, match="computed="):
        republish_catalog(
            campaign=campaign,
            catalog_path=catalog_path,
            authority_path=authority_path,
            authority_review_binding_path=binding_path,
            out_root=tmp_path / "repo",
            now=AUTHORITY_NOW,
        )
    assert not (tmp_path / "repo" / "governance" / "corpus-campaigns").exists()


def test_second_call_with_identical_inputs_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign, catalog_path, authority_path, binding_path = _setup_real(tmp_path, monkeypatch)
    out_root = tmp_path / "repo"

    first = republish_catalog(
        campaign=campaign,
        catalog_path=catalog_path,
        authority_path=authority_path,
        authority_review_binding_path=binding_path,
        out_root=out_root,
        now=AUTHORITY_NOW,
    )
    assert first.already_published is False
    written_bytes_first = first.catalog_path.read_bytes()

    second = republish_catalog(
        campaign=campaign,
        catalog_path=catalog_path,
        authority_path=authority_path,
        authority_review_binding_path=binding_path,
        out_root=out_root,
        now=AUTHORITY_NOW,
    )
    assert second.already_published is True
    assert second.catalog_sha256 == first.catalog_sha256
    # Le fichier n'a jamais été touché une seconde fois.
    assert second.catalog_path.read_bytes() == written_bytes_first


def test_diverging_content_under_the_same_campaign_id_is_never_silently_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign, catalog_path, authority_path, binding_path = _setup_real(tmp_path, monkeypatch)
    out_root = tmp_path / "repo"
    republish_catalog(
        campaign=campaign,
        catalog_path=catalog_path,
        authority_path=authority_path,
        authority_review_binding_path=binding_path,
        out_root=out_root,
        now=AUTHORITY_NOW,
    )

    digest_path = out_root / "governance/corpus-campaigns" / CAMPAIGN_ID / "catalog.digest.json"
    document = json.loads(digest_path.read_text(encoding="utf-8"))
    document["catalog_sha256"] = "9" * 64
    digest_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(CatalogRepublishError, match="never silently overwritten"):
        republish_catalog(
            campaign=campaign,
            catalog_path=catalog_path,
            authority_path=authority_path,
            authority_review_binding_path=binding_path,
            out_root=out_root,
            now=AUTHORITY_NOW,
        )


def test_missing_authority_file_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_governed_root(monkeypatch, tmp_path)
    catalog_path = _write_real_catalog(tmp_path)
    campaign = _campaign()

    with pytest.raises(CatalogRepublishError, match="does not exist"):
        republish_catalog(
            campaign=campaign,
            catalog_path=catalog_path,
            authority_path=tmp_path / "missing-authority.json",
            authority_review_binding_path=tmp_path / "missing-binding.json",
            out_root=tmp_path / "repo",
            now=AUTHORITY_NOW,
        )


def test_missing_review_binding_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_governed_root(monkeypatch, tmp_path)
    catalog_path = _write_real_catalog(tmp_path)
    authority = _authority_document()
    authority_path = _write_authority(tmp_path / "authority.json", authority)
    campaign = _campaign()

    with pytest.raises(CatalogRepublishError, match="review binding"):
        republish_catalog(
            campaign=campaign,
            catalog_path=catalog_path,
            authority_path=authority_path,
            authority_review_binding_path=tmp_path / "missing-binding.json",
            out_root=tmp_path / "repo",
            now=AUTHORITY_NOW,
        )


def test_currentness_verification_without_rights_pii_routing_paths_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La promotion par currentness réévalue réellement droits et PII --
    elle ne peut jamais s'appliquer sans cette évidence, même si un
    chemin de vérification de currentness est fourni."""
    campaign, catalog_path, authority_path, binding_path = _setup_real(tmp_path, monkeypatch)

    with pytest.raises(CatalogRepublishError, match="rights_path, pii_path and routing_path"):
        republish_catalog(
            campaign=campaign,
            catalog_path=catalog_path,
            authority_path=authority_path,
            authority_review_binding_path=binding_path,
            out_root=tmp_path / "repo",
            now=AUTHORITY_NOW,
            currentness_verification_path=tmp_path / "currentness_evidence.yml",
        )
