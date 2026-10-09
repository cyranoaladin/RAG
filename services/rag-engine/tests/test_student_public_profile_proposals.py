"""Les profils publics proposés ne changent que l'identité et la visibilité.

Ils ne sont pas chargés par le manifeste actif avant la décision ADR-0064.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from nexus_release_chain.ingestion_profiles.registry import (
    load_profile_registry,
    profile_fingerprint,
)

ROOT = Path(__file__).resolve().parents[3]
PROFILE_ROOT = ROOT / "services/rag-engine/configs/ingestion_profiles"
INTERNAL = PROFILE_ROOT / "v3_livraison_315"
PUBLIC_PROPOSAL = PROFILE_ROOT / "v4_student_public_315"
COLLECTIONS = (
    "rag_nexus_dgemc_terminale_option",
    "rag_nexus_hggsp_premiere_specialite",
    "rag_nexus_hggsp_terminale_specialite",
    "rag_nexus_hlp_premiere_specialite",
    "rag_nexus_hlp_terminale_specialite",
    "rag_nexus_nsi_premiere_specialite",
    "rag_nexus_nsi_terminale_specialite",
    "rag_nexus_ses_premiere_specialite",
    "rag_nexus_ses_terminale_specialite",
    "rag_nexus_svt_premiere_specialite",
    "rag_nexus_svt_terminale_specialite",
)


def test_exactly_eleven_public_profile_proposals_are_present() -> None:
    assert {p.stem for p in PUBLIC_PROPOSAL.glob("*.yml")} == set(COLLECTIONS)


def test_public_proposals_are_canonical_profiles_with_distinct_fingerprints() -> None:
    profiles = load_profile_registry(PUBLIC_PROPOSAL)
    assert {key[0] for key in profiles} == set(COLLECTIONS)
    assert {key[1] for key in profiles} == {"profile-gate-v4-public"}
    assert len({profile_fingerprint(profile) for profile in profiles.values()}) == 11


def test_each_public_profile_changes_only_version_and_visibility() -> None:
    for collection in COLLECTIONS:
        historical = yaml.safe_load((INTERNAL / f"{collection}.yml").read_text())
        proposal = yaml.safe_load((PUBLIC_PROPOSAL / f"{collection}.yml").read_text())
        assert historical["scope"]["visibility"] == "internal"
        assert proposal["scope"]["visibility"] == "public"
        assert proposal["profile_version"] == "profile-gate-v4-public"
        proposal["scope"]["visibility"] = historical["scope"]["visibility"]
        proposal["profile_version"] = historical["profile_version"]
        assert proposal == historical, collection


def test_proposals_are_not_in_the_active_profile_manifest() -> None:
    active = PROFILE_ROOT / "ingestion_manifest_v3_livraison_315.yml"
    declared = {
        (entry["collection"], entry["profile_version"], entry["fingerprint"])
        for entry in yaml.safe_load(active.read_text(encoding="utf-8"))["profiles"]
    }
    proposals = {
        (collection, version, profile_fingerprint(profile))
        for (collection, version), profile in load_profile_registry(PUBLIC_PROPOSAL).items()
    }
    assert declared.isdisjoint(proposals)
    assert {(collection, version) for collection, version, _ in declared}.isdisjoint(
        {(collection, version) for collection, version, _ in proposals}
    )
