"""Attribution d'un artefact de release scellée — dérivation et refus.

Ces épreuves n'ouvrent aucune base et ne lancent aucun conteneur : elles
portent sur la DÉRIVATION elle-même, celle qui décide de ce qui sera publié
dans ``rag_artifacts`` et lu par le retrieval. Le profil utilisé est un
profil **gouverné** du dépôt, pas un profil fabriqué pour le test.
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))

from ingestor.ingestion_control.artifact_attribution import (  # noqa: E402
    SEALED_RELEASE_SOURCE_KIND,
    ArtifactAttributionError,
    derive_sealed_release_artifact_attribution,
)
from ingestor.ingestion_profiles.registry import load_profile_registry  # noqa: E402

PROFILS_DIR = ENGINE_ROOT / "configs/ingestion_profiles/staging/multilevel"
COLLECTION = "rag_nexus_nsi_premiere_specialite"
VERSION = "multilevel-v1"


@pytest.fixture(scope="module")
def profil() -> object:
    return load_profile_registry(PROFILS_DIR)[(COLLECTION, VERSION)]


def _entree(**remplacements: object) -> dict[str, object]:
    entree: dict[str, object] = {
        "type_doc": "programme_officiel",
        "source_url": (
            "https://eduscol.education.gouv.fr/sites/default/files/document/x.pdf"
        ),
    }
    entree.update(remplacements)
    return entree


def test_les_quatre_faits_viennent_du_catalogue_et_du_profil(profil: object) -> None:
    """Le type vient de la release, l'éditeur de sa provenance, le reste du profil."""
    identite = uuid4()
    attribution = derive_sealed_release_artifact_attribution(
        ingestion_artifact_id=identite,
        catalog_entry=_entree(),
        profile=profil,
    )
    assert attribution.ingestion_artifact_id == identite
    assert attribution.type_doc == "programme_officiel"
    assert attribution.source_label == "eduscol.education.gouv.fr"
    assert attribution.source_kind == SEALED_RELEASE_SOURCE_KIND
    assert attribution.official is True


def test_un_type_hors_du_perimetre_du_profil_est_refuse(profil: object) -> None:
    """La confrontation au profil est ce qui distingue un type d'une déclaration.

    Sans elle, le batch publiait n'importe quelle valeur — y compris le nom
    de sa propre collection.
    """
    with pytest.raises(ArtifactAttributionError, match="not among the resource types"):
        derive_sealed_release_artifact_attribution(
            ingestion_artifact_id=uuid4(),
            catalog_entry=_entree(type_doc="annale"),
            profile=profil,
        )


def test_le_nom_d_une_collection_n_est_pas_un_type_documentaire(
    profil: object,
) -> None:
    """La contre-épreuve exacte du défaut corrigé."""
    with pytest.raises(ArtifactAttributionError):
        derive_sealed_release_artifact_attribution(
            ingestion_artifact_id=uuid4(),
            catalog_entry=_entree(type_doc=COLLECTION),
            profile=profil,
        )


def test_un_catalogue_sans_type_est_refuse_et_non_complete(profil: object) -> None:
    with pytest.raises(ArtifactAttributionError, match="establishes no type_doc"):
        derive_sealed_release_artifact_attribution(
            ingestion_artifact_id=uuid4(),
            catalog_entry=_entree(type_doc=""),
            profile=profil,
        )


def test_une_provenance_hors_des_domaines_autorises_est_refusee(
    profil: object,
) -> None:
    """L'éditeur publié ne peut pas être un domaine que personne n'a autorisé."""
    with pytest.raises(ArtifactAttributionError, match="not among the domains"):
        derive_sealed_release_artifact_attribution(
            ingestion_artifact_id=uuid4(),
            catalog_entry=_entree(source_url="https://exemple.invalide/x.pdf"),
            profile=profil,
        )


def test_une_provenance_sans_hote_est_refusee(profil: object) -> None:
    with pytest.raises(ArtifactAttributionError, match="no provenance host"):
        derive_sealed_release_artifact_attribution(
            ingestion_artifact_id=uuid4(),
            catalog_entry=_entree(source_url="pas-une-url"),
            profile=profil,
        )
