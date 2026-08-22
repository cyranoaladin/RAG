"""ADR-0044 — ``republish_catalog_v2`` : liaison à un ``CorpusCampaignV2``
référençant un ``AuthorizationSetV1`` gouverné, plutôt qu'une égalité 1:1
``authorization_id``.

Réutilise le catalogue à deux contenus réels de
``test_h2b_authorization_set_multi_auth.py`` (même fichier frère) et le
patron « probe puis vrai digest » déjà établi par
``test_catalog_republish.py`` pour V1.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import test_h2b_authorization_set_multi_auth as multi_auth
import test_h2b_coverage_report as v1

from rag_pedago.governance.catalog_republish import (
    CatalogRepublishError,
    republish_catalog_v2,
)
from rag_pedago.governance.corpus_campaign import CorpusCampaignV2

AUTHORITY_NOW = datetime(2026, 6, 1, tzinfo=UTC)
CAMPAIGN_ID = "eduscol-multi-auth-republish-test"


def _campaign_fields(*, manifest_sha256: str, authorization_set_digest: str, **overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "protocol_version": "NEXUS-CORPUS-CAMPAIGN-V2",
        "campaign_id": CAMPAIGN_ID,
        "source_kind": "ghcr-oci",
        "source_registry": "ghcr.io",
        "source_repository": "cyranoaladin/rag-corpus",
        "source_oci_digest": "sha256:" + "1" * 64,
        "source_archive_sha256": "2" * 64,
        "source_tree_digest": "3" * 64,
        "archive_format": "tar.zst",
        "source_root": "corpus",
        "expected_manifest_sha256": manifest_sha256,
        "expected_catalog_digest": "0" * 64,  # écrasé une fois connu (probe)
        "authorization_set_digest": authorization_set_digest,
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


def _campaign(**overrides: Any) -> CorpusCampaignV2:
    return CorpusCampaignV2(**_campaign_fields(**overrides))


def _setup_real(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[CorpusCampaignV2, Path, list[Path], list[Path]]:
    v1._install_governed_root(monkeypatch, tmp_path)
    (
        catalog_path,
        _routing,
        _rights,
        _pii,
        _manifest,
        manifest_sha256,
    ) = multi_auth._write_two_good_catalog_and_evidence(tmp_path)
    authority_paths, binding_paths = multi_auth._write_pair(
        tmp_path, manifest_sha256=manifest_sha256
    )

    # Probe : découvrir le vrai digest de catalogue ET le vrai
    # authorization_set_digest avant de les faire "réviser" par la
    # campagne — même patron que le probe V1 de test_catalog_republish.py.
    probe_campaign = _campaign(
        manifest_sha256=manifest_sha256,
        authorization_set_digest="f" * 64,
    )
    try:
        republish_catalog_v2(
            campaign=probe_campaign,
            catalog_path=catalog_path,
            authority_paths=authority_paths,
            authority_review_binding_paths=binding_paths,
            out_root=tmp_path / "probe_out",
            now=AUTHORITY_NOW,
        )
    except CatalogRepublishError as exc:
        message = str(exc)
        marker = "digest="
        start = message.index(marker) + len(marker)
        real_authorization_set_digest = message[start : start + 64]
    else:  # pragma: no cover - le probe ne doit jamais réussir directement
        raise AssertionError("probe unexpectedly matched the placeholder digest")

    campaign_probe_2 = _campaign(
        manifest_sha256=manifest_sha256,
        authorization_set_digest=real_authorization_set_digest,
        expected_catalog_digest="0" * 64,
    )
    try:
        republish_catalog_v2(
            campaign=campaign_probe_2,
            catalog_path=catalog_path,
            authority_paths=authority_paths,
            authority_review_binding_paths=binding_paths,
            out_root=tmp_path / "probe_out_2",
            now=AUTHORITY_NOW,
        )
    except CatalogRepublishError as exc:
        message = str(exc)
        marker = "computed="
        start = message.index(marker) + len(marker)
        real_catalog_digest = message[start : start + 64]
    else:  # pragma: no cover
        raise AssertionError("second probe unexpectedly matched the placeholder digest")

    campaign = _campaign(
        manifest_sha256=manifest_sha256,
        authorization_set_digest=real_authorization_set_digest,
        expected_catalog_digest=real_catalog_digest,
    )
    return campaign, catalog_path, authority_paths, binding_paths


def test_two_authorizations_republish_a_promoted_catalog_matching_the_approved_digests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign, catalog_path, authority_paths, binding_paths = _setup_real(tmp_path, monkeypatch)
    out_root = tmp_path / "repo"

    result = republish_catalog_v2(
        campaign=campaign,
        catalog_path=catalog_path,
        authority_paths=authority_paths,
        authority_review_binding_paths=binding_paths,
        out_root=out_root,
        now=AUTHORITY_NOW,
    )

    assert result.campaign_id == CAMPAIGN_ID
    assert result.promoted_count == 2
    assert result.already_published is False
    assert result.catalog_sha256 == campaign.expected_catalog_digest

    written_catalog = json.loads(result.catalog_path.read_text(encoding="utf-8"))
    promoted_shas = {
        item["content_sha256"]
        for item in written_catalog["physical_objects"]
        if item.get("disposition") == "INGEST"
    }
    assert promoted_shas == {multi_auth.GOOD_A_SHA256, multi_auth.GOOD_B_SHA256}

    # Idempotence : rejouer exactement doit rendre already_published=True.
    result_again = republish_catalog_v2(
        campaign=campaign,
        catalog_path=catalog_path,
        authority_paths=authority_paths,
        authority_review_binding_paths=binding_paths,
        out_root=out_root,
        now=AUTHORITY_NOW,
    )
    assert result_again.already_published is True
    assert result_again.catalog_sha256 == result.catalog_sha256


def test_wrong_authorization_set_digest_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign, catalog_path, authority_paths, binding_paths = _setup_real(tmp_path, monkeypatch)
    wrong_campaign = campaign.model_copy(
        update={"authorization_set_digest": "e" * 64}
    )
    with pytest.raises(CatalogRepublishError, match="does not match the campaign's approved"):
        republish_catalog_v2(
            campaign=wrong_campaign,
            catalog_path=catalog_path,
            authority_paths=authority_paths,
            authority_review_binding_paths=binding_paths,
            out_root=tmp_path / "repo2",
            now=AUTHORITY_NOW,
        )


def test_zero_authority_paths_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    campaign, catalog_path, _authority_paths, _binding_paths = _setup_real(tmp_path, monkeypatch)
    with pytest.raises(CatalogRepublishError, match="at least one authority evidence file"):
        republish_catalog_v2(
            campaign=campaign,
            catalog_path=catalog_path,
            authority_paths=[],
            authority_review_binding_paths=[],
            out_root=tmp_path / "repo3",
            now=AUTHORITY_NOW,
        )
