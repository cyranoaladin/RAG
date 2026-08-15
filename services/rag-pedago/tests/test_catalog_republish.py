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
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from nexus_contracts.authority_artifacts import (
    ScopeAuthorizationArtifactV2,
    canonical_authorization_path,
    git_blob_sha1,
)
from nexus_contracts.review_binding import (
    REVIEW_BINDING_PROTOCOL_VERSION,
    TRUSTED_REVIEW_PROTOCOL,
    ScopeAuthorizationReviewBindingV1,
    expected_challenge_digest,
    public_key_hex,
    sign_review_binding,
)

from rag_pedago.governance.catalog_republish import (
    CATALOG_DIGEST_PROTOCOL_VERSION,
    CatalogRepublishError,
    republish_catalog,
)
from rag_pedago.governance.corpus_campaign import CorpusCampaignV1
from rag_pedago.imports import h2b_coverage_report as h2b_module

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
        "physical_objects": [
            {
                "content_sha256": CONTENT_SHA256,
                "path": "01_EDUSCOL_OFFICIEL/current.pdf",
                "base_disposition": "INGEST",
                "disposition": "BLOCKED_NOT_CLEARED",
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
