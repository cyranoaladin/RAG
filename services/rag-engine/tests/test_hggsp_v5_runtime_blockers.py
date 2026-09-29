"""Scénario B HGGSP — deux défauts runtime constatés, reproduits sans Docker.

Le banc ``tests/integration/test_hggsp_v5_first_publication_pg.py`` les a
révélés sur la vraie chaîne (vrai CLI de Worker B, PostgreSQL jetables). Ils
sont reproduits ici au plus près du code, sur les octets scellés de V5.

Chaque test énonce le comportement ATTENDU et reste ``xfail(strict=True)`` :
il échoue aujourd'hui ; le jour où la correction arrive, il passe et la
contrainte stricte oblige à retirer le marqueur. Ce lot ne livre aucune des
deux corrections : elles dépassent son périmètre et sont décrites dans
``docs/reports/lot_go_live_hggsp_successor_control_resource_identity.md``.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
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

from ingestor.ingestion_worker.publication_resume import PublicationResumeError  # noqa: E402
from ingestor.ingestion_worker.runtime_authority import RuntimeAuthorityStartupError  # noqa: E402

V5_DIR = ENGINE_ROOT.parents[1] / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_hggsp_v5/release-b34b11e678bf9559/profile_gate"
)
V5_ID = "production-profile-gate-2026-2027-v5-hggsp"
SUBJECTS_MAPPING_V5 = "services/rag-engine/configs/mappings/eduscol_profile_gate_subjects_hggsp.yml"


@contextmanager
def _seul_le_defaut(attendu: type[Exception], message: str) -> Iterator[None]:
    """Seul le défaut documenté vaut échec attendu ; toute autre cause
    (runtime non canonique, octets absents…) échoue franchement."""
    try:
        yield
    except attendu as exc:
        if message not in str(exc):
            raise AssertionError(f"échec sans rapport avec le défaut : {exc}") from exc
        raise


@pytest.mark.xfail(
    strict=True,
    raises=RuntimeAuthorityStartupError,
    reason="défaut 1 : chaque profil du registre (11) exige une taxonomie ; V5 n'en scelle que 2",
)
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
    with _seul_le_defaut(RuntimeAuthorityStartupError,
                         "collection 'rag_nexus_dgemc_terminale_option' has no sealed taxonomy"):
        autorites = load_multilevel_runtime_authorities(
            multilevel_runtime_authority_inputs_from_args(args),
            profile_registry=load_profile_registry(args.profiles_dir),
            environment="rehearsal", qualification=qualification,
        )
    autorites.placement_resolver.require_collections_governed((
        "rag_nexus_hggsp_premiere_specialite", "rag_nexus_hggsp_terminale_specialite",
    ))


@pytest.mark.xfail(
    strict=True,
    raises=PublicationResumeError,
    reason="défaut 2 : une ressource successeur V2 naît à state_version 0, lu comme absent",
)
def test_une_version_d_etat_nulle_est_une_version() -> None:
    from ingestor.ingestion_worker.publication_resume import _require_payload

    payload = {
        "resource_id": str(uuid.uuid4()), "run_id": str(uuid.uuid4()),
        "expected_state_version": 0, "publication_attestation_id": str(uuid.uuid4()),
    }
    with _seul_le_defaut(PublicationResumeError,
                         "publication_resume payload is missing ['expected_state_version']"):
        assert _require_payload(payload) == payload
