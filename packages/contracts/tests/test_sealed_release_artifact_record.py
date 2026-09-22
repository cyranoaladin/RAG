"""Le contrat de l'artefact de release scellée (lot CU).

``ArtifactRecord`` décrit un artefact **acquis par découverte réseau** :
``original_url``, ``final_url``, ``domain`` et ``collected_at`` y sont
obligatoires parce qu'un téléchargement les produit toujours. Une release
scellée n'en produit aucun. Ces épreuves fixent la frontière : le batch a sa
propre représentation, et le chemin unitaire n'est pas assoupli pour autant.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from nexus_contracts.ingestion import (
    ArtifactRecord,
    ResourceScope,
    SealedReleaseArtifactRecord,
)

SHA = "a" * 64
PROVENANCE = "https://eduscol.education.gouv.fr/5793/programmes-et-ressources"


def _scope() -> ResourceScope:
    return ResourceScope(
        tenant="libre_terminale",
        collection="rag_nexus_nsi_terminale_specialite",
        niveau="terminale",
        voie="generale",
        matiere="nsi",
        candidat="libre",
        audience=["aefe", "libre"],
        visibility="public",
        school_year="2026-2027",
        programme_version="EDUSCOL_CORPUS_20260808",
    )


def _record(**surcharges: object) -> SealedReleaseArtifactRecord:
    champs: dict[str, object] = {
        "pipeline_kind": "sealed_release_pipeline",
        "artifact_id": uuid4(),
        "resource_id": uuid4(),
        "run_id": uuid4(),
        "scope": _scope(),
        "sha256": SHA,
        "size_bytes": 242490,
        "mime_declared": "application/pdf",
        "release_id": "production-profile-gate-2026-2027-v2",
        "release_manifest_sha256": "b" * 64,
        "content_sha256": SHA,
        "provenance_artifact_url": PROVENANCE,
        "rights_status": "officiel_public",
        "rights_decision_id": "eduscol_generic_approval",
        "rights_registry_sha256": "c" * 64,
        "pages_count": 7,
        "chunk_count": 23,
    }
    champs.update(surcharges)
    return SealedReleaseArtifactRecord(**champs)  # type: ignore[arg-type]


# --- 1 — les faits de téléchargement n'existent pas dans ce modèle --------


@pytest.mark.parametrize(
    "fabrique", ["original_url", "final_url", "domain", "collected_at"]
)
def test_un_fait_de_telechargement_est_refuse(fabrique: str) -> None:
    """Le modèle est STRICT : fournir un de ces champs est une erreur, pas un
    extra silencieusement ignoré. On ne peut donc pas les faire entrer par
    inadvertance."""
    with pytest.raises(ValidationError):
        _record(**{fabrique: "valeur"})


@pytest.mark.parametrize(
    "fabrique", ["original_url", "final_url", "domain", "collected_at"]
)
def test_le_modele_ne_declare_aucun_de_ces_champs(fabrique: str) -> None:
    assert fabrique not in SealedReleaseArtifactRecord.model_fields


def test_le_chemin_unitaire_les_exige_toujours() -> None:
    """Le batch n'assouplit rien : ``ArtifactRecord`` garde ses obligations."""
    for champ in ("original_url", "final_url", "domain", "collected_at"):
        assert ArtifactRecord.model_fields[champ].is_required(), champ


# --- 2 — le discriminateur est durable et fermé ---------------------------


def test_le_discriminateur_n_accepte_que_le_pipeline_scelle() -> None:
    with pytest.raises(ValidationError):
        _record(pipeline_kind="resource_pipeline")


def test_le_discriminateur_est_obligatoire() -> None:
    champs = SealedReleaseArtifactRecord.model_fields
    assert champs["pipeline_kind"].is_required()


# --- 3 — les autorités ne sont pas facultatives ---------------------------


@pytest.mark.parametrize(
    "champ",
    ["rights_status", "rights_decision_id", "rights_registry_sha256",
     "release_id", "release_manifest_sha256", "content_sha256",
     "provenance_artifact_url"],
)
def test_une_autorite_manquante_empeche_la_construction(champ: str) -> None:
    """Un record ne peut pas exister sans dire d'où viennent ses droits ni à
    quelle release il appartient."""
    champs = {
        "pipeline_kind": "sealed_release_pipeline", "artifact_id": uuid4(),
        "resource_id": uuid4(), "run_id": uuid4(), "scope": _scope(),
        "sha256": SHA, "size_bytes": 1, "mime_declared": "application/pdf",
        "release_id": "r", "release_manifest_sha256": "b" * 64,
        "content_sha256": SHA, "provenance_artifact_url": PROVENANCE,
        "rights_status": "officiel_public",
        "rights_decision_id": "eduscol_generic_approval",
        "rights_registry_sha256": "c" * 64, "pages_count": 1, "chunk_count": 0,
    }
    del champs[champ]
    with pytest.raises(ValidationError):
        SealedReleaseArtifactRecord(**champs)  # type: ignore[arg-type]


def test_les_droits_ne_sont_pas_une_chaine_libre() -> None:
    """``Rights`` est une énumération gouvernée : une catégorie inventée est
    refusée, et ne pourrait donc pas contourner le résolveur."""
    with pytest.raises(ValidationError):
        _record(rights_status="tout_permis")


# --- 4 — la détection est distincte de la déclaration ---------------------


def test_le_type_detecte_est_absent_tant_qu_aucune_detection_n_a_eu_lieu() -> None:
    """Le nom du champ ne doit pas laisser croire à une mesure : ``None``
    signifie « non détecté », jamais « identique au déclaré »."""
    record = _record()
    assert record.mime_declared == "application/pdf"
    assert record.content_type_detected is None


def test_un_type_detecte_peut_differer_du_declare() -> None:
    record = _record(content_type_detected="application/octet-stream")
    assert record.content_type_detected != record.mime_declared


# --- 5 — bornes de valeurs -----------------------------------------------


def test_un_document_sans_page_est_refuse() -> None:
    with pytest.raises(ValidationError):
        _record(pages_count=0)


def test_un_document_sans_chunk_reste_representable() -> None:
    """Zéro chunk est un FAIT possible ; c'est au prédicat de qualité de le
    refuser, pas au modèle de le rendre inexprimable."""
    assert _record(chunk_count=0).chunk_count == 0


@pytest.mark.parametrize("mauvais", ["", "pas-un-sha", "A" * 64, "a" * 63])
def test_une_empreinte_mal_formee_est_refusee(mauvais: str) -> None:
    with pytest.raises(ValidationError):
        _record(sha256=mauvais)


def test_une_provenance_vide_est_refusee() -> None:
    with pytest.raises(ValidationError):
        _record(provenance_artifact_url="")


# --- 6 — le modèle est strict --------------------------------------------


def test_un_champ_inconnu_est_refuse() -> None:
    """Sans quoi une valeur mal nommée serait silencieusement perdue."""
    with pytest.raises(ValidationError):
        _record(canonical_url="https://exemple.invalide/doc.pdf")


def test_le_scope_est_obligatoire_et_type() -> None:
    with pytest.raises(ValidationError):
        _record(scope={"collection": "rag_nexus_nsi_terminale_specialite"})
