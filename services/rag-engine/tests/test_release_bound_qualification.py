"""ADR-0060 — qualifier sur le staging les octets exacts d'une release de production.

La qualification ne s'active jamais par un argument : elle se déduit d'une
readiness de staging VÉRIFIÉE qui nomme la release exacte. Elle permet trois
choses, et trois seulement : consommer le manifeste de profils de production
de CETTE release, vérifier sa chaîne documentaire PII avec les clés publiques
qui l'ont réellement signée, et rien de plus — aucune activation de production.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))

from ingestor.ingestion_profiles.release_qualification import (  # noqa: E402
    ReleaseBoundQualification,
    ReleaseQualificationError,
    qualify_release_from_staging_readiness,
)
from ingestor.ingestion_worker.multilevel_runtime_authority import (  # noqa: E402
    review_verification_environment,
)
from ingestor.multilevel_verified_placement import (  # noqa: E402
    MultilevelPlacementResolutionError,
    ProductionProfileManifestVerification,
    require_profile_manifest_authority,
)
from ingestor.staging_profile_manifest import StagingProfileManifestVerification  # noqa: E402

RELEASE_ID = "production-profile-gate-2026-2027-v3"
IMAGE = "ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:" + "f" * 64


def _manifeste_de_release(tmp_path: Path, release_id: str = RELEASE_ID) -> tuple[Path, str]:
    chemin = tmp_path / "production-profile-gate.release.json"
    chemin.write_text(json.dumps({"release_id": release_id}), encoding="utf-8")
    return chemin, hashlib.sha256(chemin.read_bytes()).hexdigest()


def _readiness(sha: str, *, release_id: str = RELEASE_ID, environment: str = "rehearsal"):
    return SimpleNamespace(
        environment=environment,
        manifest_sha256="a" * 64,
        manifest=SimpleNamespace(
            allowed_release_id=release_id,
            allowed_release_manifest_sha256=sha,
            worker_image=IMAGE,
        ),
    )


def _qualifier(tmp_path: Path, **readiness_kwargs):
    chemin, sha = _manifeste_de_release(tmp_path)
    return qualify_release_from_staging_readiness(
        _readiness(readiness_kwargs.pop("sha", sha), **readiness_kwargs),
        release_manifest_path=chemin,
        release_manifest_sha256=readiness_kwargs.pop("argument_sha", sha),
        running_image=IMAGE,
    )


# ── la qualification naît d'une readiness vérifiée, jamais d'un argument ──

def test_une_readiness_qui_nomme_la_release_exacte_qualifie(tmp_path):
    qualification = _qualifier(tmp_path)
    assert qualification.release_id == RELEASE_ID
    assert qualification.worker_image == IMAGE


def test_une_autre_release_est_refusee(tmp_path):
    with pytest.raises(ReleaseQualificationError, match="release"):
        _qualifier(tmp_path, release_id="production-profile-gate-2026-2027-v2")


def test_un_autre_manifeste_de_release_est_refuse(tmp_path):
    with pytest.raises(ReleaseQualificationError, match="manifest"):
        _qualifier(tmp_path, sha="0" * 64)


def test_des_octets_de_release_alteres_sont_refuses(tmp_path):
    chemin, sha = _manifeste_de_release(tmp_path)
    chemin.write_text(json.dumps({"release_id": RELEASE_ID, "x": 1}), encoding="utf-8")
    with pytest.raises(ReleaseQualificationError, match="bytes"):
        qualify_release_from_staging_readiness(
            _readiness(sha), release_manifest_path=chemin,
            release_manifest_sha256=sha, running_image=IMAGE,
        )


def test_une_readiness_de_production_ne_qualifie_pas(tmp_path):
    with pytest.raises(ReleaseQualificationError, match="rehearsal"):
        _qualifier(tmp_path, environment="production")


def test_une_autre_image_que_celle_signee_est_refusee(tmp_path):
    chemin, sha = _manifeste_de_release(tmp_path)
    with pytest.raises(ReleaseQualificationError, match="image"):
        qualify_release_from_staging_readiness(
            _readiness(sha), release_manifest_path=chemin,
            release_manifest_sha256=sha, running_image=IMAGE.replace("f" * 64, "e" * 64),
        )


def test_la_qualification_ne_se_construit_pas_a_la_main():
    with pytest.raises(ReleaseQualificationError):
        ReleaseBoundQualification(
            release_id=RELEASE_ID, release_manifest_sha256="a" * 64,
            readiness_manifest_sha256="b" * 64, worker_image=IMAGE,
        )


# ── la chaîne PII réelle se vérifie avec la clé qui l'a signée ─────────────

def test_une_repetition_ordinaire_reste_sur_les_cles_de_test():
    assert review_verification_environment("rehearsal") == "test"
    assert review_verification_environment("production") == "production"


def test_une_qualification_verifie_la_chaine_avec_la_cle_qui_l_a_signee(tmp_path):
    assert review_verification_environment("rehearsal", qualification=_qualifier(tmp_path)) == "production"


def test_une_qualification_ne_s_applique_jamais_a_la_production(tmp_path):
    with pytest.raises(ValueError, match="rehearsal"):
        review_verification_environment("production", qualification=_qualifier(tmp_path))


# ── les profils : ceux de la release, seulement sous qualification ────────

def _production() -> ProductionProfileManifestVerification:
    return ProductionProfileManifestVerification(manifest_sha256="c" * 64, declared_count=11)


def _staging() -> StagingProfileManifestVerification:
    return StagingProfileManifestVerification(
        manifest_sha256="d" * 64, declared_count=11, provenance="banc", generated_at="2026-09-24",
        authority_mode="STAGING_LOCAL_GITHUB_ONLY", production_approval=False,
    )


def test_sans_qualification_la_repetition_refuse_les_profils_de_production():
    with pytest.raises(MultilevelPlacementResolutionError, match="staging"):
        require_profile_manifest_authority(_production(), environment="rehearsal", profile_count=11)


def test_sous_qualification_la_repetition_accepte_les_profils_de_la_release():
    require_profile_manifest_authority(
        _production(), environment="rehearsal", profile_count=11, release_bound=True
    )


def test_sous_qualification_des_profils_de_staging_sont_refuses():
    with pytest.raises(MultilevelPlacementResolutionError, match="release"):
        require_profile_manifest_authority(
            _staging(), environment="rehearsal", profile_count=11, release_bound=True
        )


def test_la_production_ne_connait_pas_la_qualification():
    with pytest.raises(MultilevelPlacementResolutionError, match="production"):
        require_profile_manifest_authority(
            _production(), environment="production", profile_count=11, release_bound=True
        )


def test_le_compte_de_profils_reste_verifie_sous_qualification():
    with pytest.raises(MultilevelPlacementResolutionError, match="count"):
        require_profile_manifest_authority(
            _production(), environment="rehearsal", profile_count=10, release_bound=True
        )
