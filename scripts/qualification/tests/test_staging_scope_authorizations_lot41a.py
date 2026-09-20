"""Épreuves des autorisations de scope LOT41A du staging V2 (lot CH4).

Ces tests ne créent aucun job et n'écrivent nulle part. Ils prouvent que les
onze décisions d'autorisation portent EXACTEMENT le périmètre de la release V2
scellée, qu'elles sont canoniques octet à octet, et qu'aucune d'elles ne peut
être élargie sans que la suite échoue.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "services/rag-engine/src"))

from nexus_contracts.authority_artifacts import (  # noqa: E402
    CanonicalArtifactError,
    canonical_authorization_path,
    parse_scope_authorization_artifact,
)

AUTORISATIONS = RACINE / "governance/authorizations"
PROFILS = RACINE / "services/rag-engine/configs/ingestion_profiles/v2_livraison_319"
MANIFESTE = (
    RACINE / "services/rag-engine/configs/ingestion_profiles"
    / "ingestion_manifest_v2_livraison_319.yml"
)
RELEASE = RACINE / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2/"
    "release-1b9eba0c0eb0ab13/profile_gate/production-profile-gate.release.json"
)
#: Manifeste de transfert du corpus V2 — les 315 PDF vérifiés sur l'hôte.
TRANSFER_MANIFEST_SHA256 = (
    "1f63939b4e1510ad261d1076f16f15b47422d6745f69145fab3789f466eb6e47"
)

PREFIXE = "lot41a-staging-v2-"

#: Les trois collections qu'ADR-0053 a fait décider. Leur présence ici n'est
#: pas décorative : sans elles, l'ingestion V2 reste incomplète.
COLLECTIONS_DECIDEES = frozenset(
    {
        "rag_nexus_hggsp_premiere_specialite",
        "rag_nexus_hggsp_terminale_specialite",
        "rag_nexus_hlp_terminale_specialite",
    }
)


def _release() -> dict[str, Any]:
    return json.loads(RELEASE.read_bytes())


def _collections_de_la_release() -> set[str]:
    return {str(s["collection"]) for s in _release()["subjects"]}


def _artefacts() -> dict[str, Any]:
    out = {}
    for chemin in sorted(AUTORISATIONS.glob(f"{PREFIXE}*.json")):
        out[chemin.name] = parse_scope_authorization_artifact(chemin.read_bytes())
    return out


# --- 5/6/7 — le périmètre est celui de la release, ni plus ni moins -------


def test_une_autorisation_par_collection_de_la_release() -> None:
    """Ni collection manquante, ni collection supplémentaire."""
    autorisees = {a.scope.collection for a in _artefacts().values()}
    assert autorisees == _collections_de_la_release()


def test_le_nombre_d_autorisations_egale_le_nombre_de_subjects() -> None:
    release = _release()
    assert len(_artefacts()) == release["expected_counts"]["subjects"] == 11


def test_aucune_collection_hors_release() -> None:
    hors = {a.scope.collection for a in _artefacts().values()} - _collections_de_la_release()
    assert hors == set()


# --- 15 — les trois collections décidées sous ADR-0053 sont couvertes ----


def test_les_trois_collections_hggsp_hlp_sont_autorisees() -> None:
    autorisees = {a.scope.collection for a in _artefacts().values()}
    assert COLLECTIONS_DECIDEES <= autorisees


# --- 1/10 — pas d'autorisation, pas de job ------------------------------


def test_chaque_autorisation_est_a_son_chemin_canonique() -> None:
    """L'identifiant seul dérive le chemin : il ne peut pas sortir du dossier."""
    for nom, artefact in _artefacts().items():
        attendu = canonical_authorization_path(artefact.authorization_id)
        assert attendu == f"governance/authorizations/{nom}"
        assert (RACINE / attendu).is_file()


def test_un_identifiant_inconnu_n_a_pas_d_artefact() -> None:
    inconnu = "lot41a-staging-v2-collection-inexistante"
    assert not (RACINE / canonical_authorization_path(inconnu)).exists()


def test_un_identifiant_non_canonique_est_refuse() -> None:
    for mauvais in ("../evasion", "Lot41A-Majuscules", ""):
        with pytest.raises(ValueError):
            canonical_authorization_path(mauvais)


# --- 2/3/4 — la canonicité octet à octet lie la revue humaine ------------


def test_les_octets_commits_sont_canoniques(tmp_path: Path) -> None:
    """Un seul octet modifié et la décision n'est plus celle qui a été relue."""
    for chemin in sorted(AUTORISATIONS.glob(f"{PREFIXE}*.json")):
        brut = chemin.read_bytes()
        artefact = parse_scope_authorization_artifact(brut)
        assert artefact.canonical_bytes() == brut, chemin.name


@pytest.mark.parametrize(
    "alteration",
    [
        lambda raw: raw.replace(b'  "', b'   "', 1),          # indentation
        lambda raw: raw.replace(b"libre", b"LIBRE", 1),        # casse
        lambda raw: raw + b"\n",                               # octet ajouté
    ],
)
def test_toute_alteration_d_octet_casse_la_canonicite(alteration: Any) -> None:
    chemin = sorted(AUTORISATIONS.glob(f"{PREFIXE}*.json"))[0]
    with pytest.raises(CanonicalArtifactError):
        parse_scope_authorization_artifact(alteration(chemin.read_bytes()))


def test_l_artefact_ne_porte_jamais_sa_propre_approbation() -> None:
    """Un artefact ne peut pas contenir la preuve de sa propre revue.

    L'évidence GitHub — reviewer, head, challenge — est relue en direct par
    l'outil, jamais fournie par l'opérateur. Si elle pouvait figurer ici,
    n'importe qui pourrait écrire « approuvé par abenrhouma ».
    """
    interdits = {"evidence_reviewer", "evidence_head_sha", "evidence_challenge",
                 "evidence_review_id", "approved_by", "reviewer"}
    for chemin in sorted(AUTORISATIONS.glob(f"{PREFIXE}*.json")):
        document = json.loads(chemin.read_text(encoding="utf-8"))
        assert interdits & set(document) == set(), chemin.name


# --- 9 — le profil autorisé est celui de v2_livraison_319 ---------------


def test_chaque_autorisation_cite_le_manifeste_de_profils_v2() -> None:
    attendu = hashlib.sha256(MANIFESTE.read_bytes()).hexdigest()
    for artefact in _artefacts().values():
        assert artefact.manifest_digest == attendu


def test_les_empreintes_de_profil_sont_celles_du_manifeste() -> None:
    """Un profil d'un autre répertoire produirait une autre empreinte."""
    manifeste = yaml.safe_load(MANIFESTE.read_text(encoding="utf-8"))
    declarees = {p["collection"]: p["fingerprint"] for p in manifeste["profiles"]}
    for artefact in _artefacts().values():
        assert artefact.profile_fingerprint == declarees[artefact.scope.collection]
        assert artefact.profile_version == "profile-gate-v2"
        assert artefact.profile_id == artefact.scope.collection


def test_les_profils_v2_existent_bien_dans_le_repertoire_attendu() -> None:
    for collection in _collections_de_la_release():
        assert (PROFILS / f"{collection}.yml").is_file(), collection


# --- 8 — le périmètre chiffré de la release est cité --------------------


def test_les_comptes_de_la_release_sont_ceux_attendus() -> None:
    """Si la release changeait de comptes, cette autorisation ne la couvrirait plus."""
    assert _release()["expected_counts"] == {
        "subjects": 11,
        "unique_artifacts": 315,
        "placements": 479,
        "unique_chunks": 8268,
    }


def test_le_digest_du_manifeste_de_release_est_celui_scelle() -> None:
    assert hashlib.sha256(RELEASE.read_bytes()).hexdigest() == (
        "e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864"
    )


# --- 16 — le corpus transféré est référencé -----------------------------


def test_le_manifeste_de_transfert_du_corpus_est_present_et_intact() -> None:
    chemin = RACINE / "docs/reports/evidence/external_staging_v2_artifact_transfer_manifest.json"
    assert chemin.is_file()
    brut = chemin.read_bytes()
    assert hashlib.sha256(brut).hexdigest() == TRANSFER_MANIFEST_SHA256
    manifeste = json.loads(brut)
    assert manifeste["file_count"] == 315
    assert manifeste["digest_mismatches"] == 0
    assert manifeste["digest_missing"] == 0
    assert manifeste["destination_path"] == "/srv/nexus-staging/artifact-store/"


# --- 12/13/14 — jamais la base ni le conteneur de production ------------


def test_aucune_autorisation_ne_nomme_une_ressource_de_production() -> None:
    interdits = ("rag_pgvector", "infra_rag_net", "PG_RAG_DSN_PROD", "nexus_prod_db")
    for chemin in sorted(AUTORISATIONS.glob(f"{PREFIXE}*.json")):
        texte = chemin.read_text(encoding="utf-8")
        for mot in interdits:
            assert mot not in texte, (chemin.name, mot)


def test_aucune_autorisation_ne_contient_de_secret() -> None:
    """Ni mot de passe, ni DSN complet : une décision n'est pas un identifiant."""
    for chemin in sorted(AUTORISATIONS.glob(f"{PREFIXE}*.json")):
        texte = chemin.read_text(encoding="utf-8")
        assert "postgresql://" not in texte, chemin.name
        assert "password" not in texte.lower(), chemin.name


# --- 11 — la séparation des DSN vaut dans TOUS les environnements -------


def test_la_garde_de_separation_des_dsn_n_est_plus_reservee_a_la_production() -> None:
    """Lot CH4 : le refus s'appliquait en production seulement.

    Un staging pouvait donc publier avec un DSN unique, ce qui effondre la
    séparation entre contrôle d'ingestion et base produit — précisément là où
    on la qualifie.
    """
    source = (
        RACINE
        / "services/rag-engine/src/ingestor/ingestion_worker"
        / "multilevel_publication_resume_cli.py"
    ).read_text(encoding="utf-8")
    assert "_require_distinct_control_and_product_dsn" in source
    avant_production = source.split('if readiness.environment == "production":')[0]
    assert "_require_distinct_control_and_product_dsn(product_dsn)" in avant_production


#: La preuve COMPORTEMENTALE de cette garde vit dans la suite rag-engine
#: (`services/rag-engine/tests/test_worker_b_dsn_separation.py`) : elle importe
#: le CLI, donc `psycopg`, que ce job de qualification n'installe pas. Le test
#: statique ci-dessus reste ici parce qu'il ne dépend d'aucun runtime.


# --- 17 — cette PR ne touche ni release, ni scope packagé ---------------


def _fichiers_changes() -> list[tuple[str, str]] | None:
    try:
        base = subprocess.run(
            ["git", "merge-base", "HEAD", "main"],
            cwd=RACINE, capture_output=True, text=True, timeout=30, check=False,
        )
        if base.returncode != 0:
            return None
        diff = subprocess.run(
            ["git", "diff", "--name-status", base.stdout.strip(), "HEAD"],
            cwd=RACINE, capture_output=True, text=True, timeout=30, check=False,
        )
        if diff.returncode != 0:
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    lignes = [ligne for ligne in diff.stdout.splitlines() if ligne]
    return [(ligne.split("\t")[0], ligne.split("\t")[-1]) for ligne in lignes]


def test_aucune_release_n_est_modifiee_par_ce_lot() -> None:
    changes = _fichiers_changes()
    if changes is None:
        pytest.skip("dépôt git indisponible")
    for statut, chemin in changes:
        assert not chemin.startswith("services/rag-pedago/data/releases/"), (statut, chemin)


def test_aucun_scope_de_retrieval_n_est_modifie_par_ce_lot() -> None:
    changes = _fichiers_changes()
    if changes is None:
        pytest.skip("dépôt git indisponible")
    for statut, chemin in changes:
        assert not chemin.startswith(
            "packages/contracts/src/nexus_contracts/artifacts/"
        ), (statut, chemin)
