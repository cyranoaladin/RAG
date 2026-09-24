"""ADR-0060 — l'autorité de publication d'un placement adopté couvre CE contenu, CETTE collection."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))

from ingestor.ingestion_control.scope_authority import VerifiedAuthorization  # noqa: E402
from ingestor.ingestion_control.sealed_release_adoption import (  # noqa: E402
    SealedReleaseAdoptionError,
    require_publication_authority_covers,
)

A, B = "a" * 64, "b" * 64


def _autorisation(**champs) -> VerifiedAuthorization:
    scope = type("Scope", (), {"collection": "rag_nexus_svt_terminale_specialite"})()
    base = dict(
        authorization_id="lot41a-staging-v3-svt-terminale-specialite-r3",
        scope=scope, manifest_digest="c" * 64, profile_id="p", profile_version="v",
        profile_fingerprint="f" * 64, allowed_domains=("eduscol.education.gouv.fr",),
        rights_categories=("officiel_public",), exclusions=(), pii_absence_attested=True,
        valid_from=datetime(2026, 9, 1, tzinfo=UTC), valid_until=datetime(2027, 8, 31, tzinfo=UTC),
        artifact_path="governance/authorizations/x.json", artifact_blob_sha="1" * 40,
        authorization_digest="d" * 64, evidence_repository="cyranoaladin/RAG",
        evidence_pull_request=1, evidence_base_sha="2" * 40, evidence_head_sha="3" * 40,
        evidence_review_id=1, evidence_reviewer="abenrhouma", evidence_challenge="x",
        verified_at=datetime(2026, 9, 24, tzinfo=UTC), protocol_version="LOT41A-V2",
        allowed_content_sha256=(A,),
    )
    base.update(champs)
    return VerifiedAuthorization(**base)  # type: ignore[arg-type]


def _couvre(autorisation, *, contenu=A, collection="rag_nexus_svt_terminale_specialite"):
    require_publication_authority_covers(autorisation, content_sha256=contenu, collection=collection)


def test_une_autorisation_v2_qui_nomme_le_contenu_et_la_collection_couvre():
    _couvre(_autorisation())


def test_une_autorisation_v1_ne_couvre_jamais_une_publication():
    with pytest.raises(SealedReleaseAdoptionError, match="LOT41A-V2"):
        _couvre(_autorisation(protocol_version="LOT41A-V1", allowed_content_sha256=None))


def test_un_autre_contenu_n_est_pas_couvert():
    with pytest.raises(SealedReleaseAdoptionError, match="content"):
        _couvre(_autorisation(), contenu=B)


def test_une_autre_collection_n_est_pas_couverte():
    with pytest.raises(SealedReleaseAdoptionError, match="collection"):
        _couvre(_autorisation(), collection="rag_nexus_svt_premiere_specialite")


def test_une_liste_positive_vide_ne_couvre_rien():
    with pytest.raises(SealedReleaseAdoptionError):
        _couvre(replace(_autorisation(), allowed_content_sha256=()))
