"""Protocole LOT42 de revue de publication pour release scellée (ADR-0056).

Une revue humaine unique ne vaut pour un ensemble que si cet ensemble est
IMMUABLE et vérifiable. Ces épreuves fixent les refus qui rendent cette
affirmation défendable — et vérifient d'abord que `LOT42-V1`, lui, n'a pas
bougé d'un champ.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from nexus_contracts.authority_artifacts import (
    CanonicalArtifactError,
    PublicationReviewArtifact,
    ReleaseBatchPublicationReviewArtifact,
    ReleaseBatchReviewMismatch,
    parse_release_batch_publication_review_artifact,
    require_release_batch_review_matches_release,
)

CONTRACTS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CONTRACTS_ROOT.parents[1]
RELEASE_DIR = REPO_ROOT / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2/"
    "release-1b9eba0c0eb0ab13/profile_gate"
)

RELEASE_ID = "production-profile-gate-2026-2027-v2"
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
COUNTS = {"subjects": 11, "unique_artifacts": 315, "placements": 479, "unique_chunks": 8268}
ETATS = {"review_status": ("reviewed",), "placement_status": ("active",),
         "currentness": ("current",)}
URL_COUNT = 19

D_RELEASE = "e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864"
D_ARTIFACTS = "a" * 64
D_INVENTORY = "b" * 64
D_TRANSFER = "1f63939b4e1510ad261d1076f16f15b47422d6745f69145fab3789f466eb6e47"


def _artefact(**surcharges: Any) -> ReleaseBatchPublicationReviewArtifact:
    base: dict[str, Any] = {
        "protocol_version": "LOT42-RELEASE-BATCH-V1",
        "review_id": "lot42-release-batch-profile-gate-v2",
        "decision": "AUTHORIZE_SEALED_RELEASE_PUBLICATION",
        "release_id": RELEASE_ID,
        "release_manifest_sha256": D_RELEASE,
        "artifacts_release_sha256": D_ARTIFACTS,
        "candidate_inventory_sha256": D_INVENTORY,
        "artifact_transfer_manifest_sha256": D_TRANSFER,
        "expected_counts": dict(COUNTS),
        "collections": COLLECTIONS,
        "placement_evidence": {"review_status": "reviewed",
                               "placement_status": "active",
                               "currentness": "current"},
        "scope_authorization_ids": tuple(
            sorted("lot41a-staging-v2-" + c.removeprefix("rag_nexus_").replace("_", "-")
                   for c in COLLECTIONS)
        ),
        "provenance_source_url_count": URL_COUNT,
        "provenance_note": (
            "source_url de candidate_inventory.json, conservée comme provenance ; "
            "aucune URL canonique documentaire n'existe par artefact dans cette release"
        ),
        "valid_from": datetime(2026, 9, 20, tzinfo=UTC),
        "valid_until": datetime(2027, 8, 31, tzinfo=UTC),
    }
    base.update(surcharges)
    return ReleaseBatchPublicationReviewArtifact(**base)


def _verifie(artefact: ReleaseBatchPublicationReviewArtifact, **surcharges: Any) -> None:
    observe: dict[str, Any] = {
        "observed_release_id": RELEASE_ID,
        "observed_release_manifest_sha256": D_RELEASE,
        "observed_artifacts_release_sha256": D_ARTIFACTS,
        "observed_candidate_inventory_sha256": D_INVENTORY,
        "observed_transfer_manifest_sha256": D_TRANSFER,
        "observed_collections": COLLECTIONS,
        "observed_counts": dict(COUNTS),
        "observed_placement_states": dict(ETATS),
        "observed_source_url_count": URL_COUNT,
    }
    observe.update(surcharges)
    require_release_batch_review_matches_release(artefact, **observe)


# --- 1 / 2 — LOT42-V1 n'a pas bougé --------------------------------------


def test_lot42_v1_exige_toujours_canonical_url() -> None:
    """Le protocole de découverte n'est ni élargi ni assoupli par ADR-0056."""
    champs = PublicationReviewArtifact.model_fields
    assert "canonical_url" in champs
    assert champs["canonical_url"].is_required()
    assert champs["resource_id"].is_required()
    assert champs["artifact_id"].is_required()


def test_lot42_v1_reste_unitaire() -> None:
    """Un seul resource_id, un seul artifact_id : aucun ensemble."""
    champs = PublicationReviewArtifact.model_fields
    for nom in ("resource_id", "artifact_id", "content_sha256"):
        assert "tuple" not in str(champs[nom].annotation).lower()
        assert "list" not in str(champs[nom].annotation).lower()


# --- 16 / 17 — le protocole batch n'a pas de canonical_url ---------------


def test_le_protocole_batch_ne_porte_aucun_canonical_url() -> None:
    champs = set(ReleaseBatchPublicationReviewArtifact.model_fields)
    assert "canonical_url" not in champs
    assert "source_url" not in champs


def test_un_canonical_url_fabrique_est_refuse() -> None:
    """Le modèle est strict : un champ inventé ne passe pas en silence."""
    with pytest.raises(ValidationError):
        _artefact(canonical_url="https://eduscol.education.gouv.fr/5799/")


def test_la_provenance_est_declaree_sans_etre_promue_en_ressource() -> None:
    artefact = _artefact()
    assert artefact.provenance_source_url_count == URL_COUNT
    assert "provenance" in artefact.provenance_note.lower()
    assert "canonique" in artefact.provenance_note.lower()


# --- le cas nominal, pour que les refus aient un point de comparaison ----


def test_une_revue_conforme_a_la_release_est_acceptee() -> None:
    _verifie(_artefact())


def test_la_revue_est_canonique_octet_a_octet() -> None:
    brut = _artefact().canonical_bytes()
    relu = parse_release_batch_publication_review_artifact(brut)
    assert relu.canonical_bytes() == brut


@pytest.mark.parametrize(
    "alteration",
    [lambda b: b.replace(b"  ", b"   ", 1), lambda b: b + b"\n"],
)
def test_toute_alteration_d_octet_casse_la_canonicite(alteration: Any) -> None:
    with pytest.raises(CanonicalArtifactError):
        parse_release_batch_publication_review_artifact(alteration(_artefact().canonical_bytes()))


# --- 3 / 4 — release non scellée ou digest divergent ---------------------


def test_un_release_id_divergent_est_refuse() -> None:
    with pytest.raises(ReleaseBatchReviewMismatch, match="release_id"):
        _verifie(_artefact(), observed_release_id="production-profile-gate-2026-2027-v1")


@pytest.mark.parametrize(
    ("cle", "champ"),
    [
        ("observed_release_manifest_sha256", "release_manifest_sha256"),
        ("observed_artifacts_release_sha256", "artifacts_release_sha256"),
        ("observed_candidate_inventory_sha256", "candidate_inventory_sha256"),
        ("observed_transfer_manifest_sha256", "artifact_transfer_manifest_sha256"),
    ],
)
def test_un_digest_divergent_est_refuse(cle: str, champ: str) -> None:
    with pytest.raises(ReleaseBatchReviewMismatch, match=champ):
        _verifie(_artefact(), **{cle: "f" * 64})


# --- 5 / 6 / 7 / 10 — artefacts, placements et comptes -------------------


@pytest.mark.parametrize("compte", sorted(COUNTS))
def test_un_compte_divergent_est_refuse(compte: str) -> None:
    observes = dict(COUNTS)
    observes[compte] = observes[compte] - 1          # un artefact / placement manquant
    with pytest.raises(ReleaseBatchReviewMismatch, match=compte):
        _verifie(_artefact(), observed_counts=observes)


@pytest.mark.parametrize("compte", sorted(COUNTS))
def test_un_compte_en_surplus_est_refuse(compte: str) -> None:
    observes = dict(COUNTS)
    observes[compte] = observes[compte] + 1
    with pytest.raises(ReleaseBatchReviewMismatch, match=compte):
        _verifie(_artefact(), observed_counts=observes)


def test_les_comptes_declares_sont_ceux_de_la_release_scellee() -> None:
    """Contre-épreuve : ces quatre nombres ne sont pas inventés ici."""
    manifeste = json.loads((RELEASE_DIR / "production-profile-gate.release.json").read_bytes())
    assert manifeste["expected_counts"] == COUNTS
    assert manifeste["release_id"] == RELEASE_ID


# --- 8 / 9 / 11 — collections -------------------------------------------


def test_une_collection_manquante_est_refusee() -> None:
    with pytest.raises(ReleaseBatchReviewMismatch, match="manquantes"):
        _verifie(_artefact(), observed_collections=COLLECTIONS + ("rag_nexus_autre",))


def test_une_collection_en_surplus_est_refusee() -> None:
    with pytest.raises(ReleaseBatchReviewMismatch, match="surplus"):
        _verifie(_artefact(), observed_collections=COLLECTIONS[:-1])


@pytest.mark.parametrize(
    "absente",
    ["rag_nexus_hggsp_premiere_specialite", "rag_nexus_hggsp_terminale_specialite",
     "rag_nexus_hlp_terminale_specialite"],
)
def test_une_revue_sans_hggsp_ou_hlp_ne_couvre_pas_la_release(absente: str) -> None:
    """Les trois collections décidées sous ADR-0053 ne peuvent pas être omises."""
    reduites = tuple(c for c in COLLECTIONS if c != absente)
    with pytest.raises(ValidationError):
        _artefact(collections=reduites)          # 10 ≠ expected_counts.subjects = 11


def test_le_nombre_de_collections_doit_egaler_le_compte_de_subjects() -> None:
    with pytest.raises(ValidationError, match="subjects"):
        _artefact(collections=COLLECTIONS[:8])


@pytest.mark.parametrize(
    "mauvaises",
    [tuple(reversed(COLLECTIONS)), COLLECTIONS[:10] + (COLLECTIONS[0],)],
)
def test_des_collections_non_triees_ou_dupliquees_sont_refusees(mauvaises: tuple) -> None:
    with pytest.raises(ValidationError):
        _artefact(collections=mauvaises)


# --- 12 / 13 / 14 — l'état des placements --------------------------------


@pytest.mark.parametrize(
    ("champ", "observe"),
    [("review_status", "pending"), ("currentness", "stale"),
     ("placement_status", "inactive")],
)
def test_un_etat_de_placement_non_conforme_est_refuse(champ: str, observe: str) -> None:
    etats = {k: v for k, v in ETATS.items()}
    etats[champ] = (observe,)
    with pytest.raises(ReleaseBatchReviewMismatch, match=champ):
        _verifie(_artefact(), observed_placement_states=etats)


def test_un_etat_de_placement_heterogene_est_refuse() -> None:
    """Un seul placement non revu suffit : l'ensemble cesse d'être uniforme."""
    etats = {k: v for k, v in ETATS.items()}
    etats["review_status"] = ("reviewed", "pending")
    with pytest.raises(ReleaseBatchReviewMismatch, match="review_status"):
        _verifie(_artefact(), observed_placement_states=etats)


@pytest.mark.parametrize("valeur", ["pending", "unknown", ""])
def test_le_modele_n_accepte_que_reviewed_active_current(valeur: str) -> None:
    with pytest.raises(ValidationError):
        _artefact(placement_evidence={"review_status": valeur,
                                      "placement_status": "active",
                                      "currentness": "current"})


# --- 15 — la provenance doit être présente -------------------------------


def test_un_nombre_d_url_de_provenance_divergent_est_refuse() -> None:
    with pytest.raises(ReleaseBatchReviewMismatch, match="provenance_source_url_count"):
        _verifie(_artefact(), observed_source_url_count=URL_COUNT + 1)


@pytest.mark.parametrize("absent", [0, -1])
def test_une_provenance_absente_est_refusee(absent: int) -> None:
    with pytest.raises(ValidationError):
        _artefact(provenance_source_url_count=absent)


def test_une_note_de_provenance_vide_est_refusee() -> None:
    with pytest.raises(ValidationError):
        _artefact(provenance_note="")


# --- LOT41A reste exigé, la revue ne le remplace pas ---------------------


def test_la_revue_cite_les_autorisations_lot41a() -> None:
    artefact = _artefact()
    assert len(artefact.scope_authorization_ids) == len(COLLECTIONS)
    assert all(a.startswith("lot41a-") for a in artefact.scope_authorization_ids)


def test_une_revue_sans_autorisation_de_scope_est_refusee() -> None:
    with pytest.raises(ValidationError):
        _artefact(scope_authorization_ids=())


# --- fenêtre de validité -------------------------------------------------


def test_une_fenetre_de_validite_inversee_est_refusee() -> None:
    with pytest.raises(ValidationError, match="valid_until"):
        _artefact(valid_from=datetime(2027, 1, 1, tzinfo=UTC),
                  valid_until=datetime(2026, 1, 1, tzinfo=UTC))


# --- 21 / 22 — cette PR n'écrit nulle part -------------------------------


def test_le_validateur_est_pur_et_ne_lit_aucun_fichier() -> None:
    """Une fonction qui irait chercher la release pourrait en choisir une autre."""
    source = Path(require_release_batch_review_matches_release.__code__.co_filename)
    texte = source.read_text(encoding="utf-8")
    corps = texte.split("def require_release_batch_review_matches_release(")[1]
    corps = corps.split("\ndef ")[0]
    for interdit in ("open(", "read_bytes", "read_text", "psycopg", "requests", "Path("):
        assert interdit not in corps, interdit


def test_aucune_ecriture_de_base_n_est_possible_depuis_ce_module() -> None:
    texte = Path(
        require_release_batch_review_matches_release.__code__.co_filename
    ).read_text(encoding="utf-8")
    assert not re.search(r"\bINSERT\b|\bUPDATE\b|\bDELETE\b", texte)
