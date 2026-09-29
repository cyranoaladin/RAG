"""Worker B charge ses autorités pour la release complémentaire HGGSP V5.

La release ne porte que 2 collections et ne scelle que leurs 2 taxonomies,
alors que le manifeste de profils qu'elle nomme gouverne 11 profils. Sans
Docker, sur les octets scellés de V5 et la chaîne PII réelle : le chargement
réussit, le manifeste reste vérifié sur le registre complet, et seules les
collections de la release sont réclamables.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests/integration"))

from _banc_releases_reelles import (  # noqa: E402
    PROFILE_MANIFEST_V4,
    PROFILES_V4,
    arguments_worker_b,
    sha,
    transfert_nomme,
)

from ingestor.multilevel_verified_placement import MultilevelPlacementResolutionError  # noqa: E402

V5_DIR = ENGINE_ROOT.parents[1] / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_hggsp_v5/release-b34b11e678bf9559/profile_gate"
)
V5_ID = "production-profile-gate-2026-2027-v5-hggsp"
SUBJECTS_MAPPING_V5 = "services/rag-engine/configs/mappings/eduscol_profile_gate_subjects_hggsp.yml"
HGGSP = ("rag_nexus_hggsp_premiere_specialite", "rag_nexus_hggsp_terminale_specialite")


def test_les_autorites_de_worker_b_se_chargent_pour_la_release_v5(tmp_path: Path) -> None:
    from ingestor.ingestion_profiles.registry import load_profile_registry
    from ingestor.ingestion_profiles.release_qualification import (
        qualify_release_from_staging_readiness,
    )
    from ingestor.ingestion_worker.multilevel_publication_resume_cli import _build_arg_parser
    from ingestor.ingestion_worker.multilevel_runtime_authority import (
        load_multilevel_runtime_authorities,
        multilevel_runtime_authority_inputs_from_args,
    )

    manifeste = V5_DIR / "production-profile-gate.release.json"
    image = "ghcr.io/nexus/ingestion-worker-bench@sha256:" + "a" * 64
    args = _build_arg_parser().parse_args(arguments_worker_b(
        release_dir=V5_DIR, profiles_dir=PROFILES_V4, profile_manifest=PROFILE_MANIFEST_V4,
        magasin=tmp_path, transfert=transfert_nomme(tmp_path, V5_ID, release_dir=V5_DIR),
        modele=tmp_path, subjects_mapping=SUBJECTS_MAPPING_V5,
    ))
    qualification = qualify_release_from_staging_readiness(
        SimpleNamespace(
            environment="rehearsal", manifest_sha256="a" * 64,
            manifest=SimpleNamespace(
                allowed_release_id=V5_ID, allowed_release_manifest_sha256=sha(manifeste),
                worker_image=image,
            ),
        ),
        release_manifest_path=manifeste, release_manifest_sha256=sha(manifeste),
        running_image=image,
    )
    profils = load_profile_registry(args.profiles_dir)
    assert len(profils) == 11
    autorites = load_multilevel_runtime_authorities(
        multilevel_runtime_authority_inputs_from_args(args),
        profile_registry=profils, environment="rehearsal", qualification=qualification,
    )
    resolver = autorites.placement_resolver
    assert resolver.release_collections == set(HGGSP)
    resolver.require_collections_governed(HGGSP)
    with pytest.raises(MultilevelPlacementResolutionError, match="outside the release"):
        resolver.require_collections_governed(("rag_nexus_nsi_terminale_specialite",))
