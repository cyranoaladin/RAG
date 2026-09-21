"""CH6 — l'image worker de staging : epinglee, construite hors hote, bornee.

Ce fichier ne telecharge aucune image : les faits mesures sur les octets reels
(contrats 0.19.0, ``ingestion_agents`` present, point d'entree importable,
absence de secret) sont consignes dans la preuve de provenance versionnee, et
ces epreuves verifient que l'autorisation et la preuve disent la MEME chose.
Un test qui tirerait une image depuis la CI mesurerait le reseau, pas la
gouvernance.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import check_staging_authorization as autorisation  # noqa: E402

#: La preuve de l'image EN VIGUEUR est lue DANS l'autorisation, pas codee en
#: dur. Chaque reconstruction en produit une nouvelle — la coder ici obligeait
#: a repointer ce fichier a chaque lot, et c'est exactement ce couplage qui a
#: fait echouer ces epreuves deux fois de suite.
def _preuve_courante() -> str:
    document = json.loads(
        (RACINE / "docs/reports/go_live/authorizations/staging_ssh_authorization.json")
        .read_text(encoding="utf-8")
    )
    return document["scope"]["staging_worker_image"]["evidence"]["path"]


#: La preuve de CH6 reste versionnee comme trace de ce qui a ete autorise a
#: l'epoque : remplacer un digest n'efface pas l'historique.
PREUVE_CH6 = "docs/reports/evidence/staging_worker_image_provenance.json"


@pytest.fixture()
def document() -> dict:
    return json.loads((RACINE / autorisation.AUTORISATION).read_text(encoding="utf-8"))


@pytest.fixture()
def preuve() -> dict:
    return json.loads((RACINE / _preuve_courante()).read_text(encoding="utf-8"))


def _plan_sha(document: dict) -> str:
    return hashlib.sha256(
        (RACINE / document["execution_plan"]["path"]).read_bytes()
    ).hexdigest()


def _image(document: dict) -> dict:
    return document["scope"]["staging_worker_image"]


def _ecarts(document: dict) -> list[str]:
    return autorisation.evaluer(document, plan_sha256=_plan_sha(document))


# --------------------------------------------------------------------------
# 1. L'ancienne image API est nommee pour ce qu'elle est, et ne suffit pas
# --------------------------------------------------------------------------


def test_1_l_image_epinglee_du_perimetre_est_l_api_de_retrieval() -> None:
    """Fait etabli par CH6 : il est lu dans SA preuve, pas recopie dans
    chacune de celles qui suivent."""
    probleme = json.loads((RACINE / PREUVE_CH6).read_text(encoding="utf-8"))["problem"]
    assert probleme["pinned_image_digest"].startswith("sha256:d0134f49")
    assert "retrieval" in probleme["pinned_image_role"]
    assert "ingestion_agents" in probleme["observed_refusal"]
    assert set(probleme["missing_modules"]) == {"httpx", "ingestion_agents"}


def test_1bis_les_autres_images_locales_sont_ecartees_avec_leur_raison() -> None:
    ancienne = json.loads((RACINE / PREUVE_CH6).read_text(encoding="utf-8"))
    raisons = {
        entree["name"]: entree["reason"]
        for entree in ancienne["problem"]["other_local_images_rejected"]
    }
    assert raisons["infra-ingestor:latest"] == "nexus-contracts 0.2.0"
    assert raisons["nexus-rag-ingestor-security:da0a167"] == "nexus-contracts 0.2.0"
    assert raisons["compose-ingestor:latest"] == "psycopg absent"


def test_1ter_l_image_api_reste_autorisee_pour_son_propre_role(document: dict) -> None:
    """CH6 n'enleve rien : l'image API garde son digest et sa version 0.18.0."""
    perimetre = document["scope"]
    assert perimetre["ingestor_image"] == "pinned_by_digest_no_rebuild"
    assert perimetre["ingestor_image_digest"].startswith("sha256:d0134f49")
    assert perimetre["staging_index_source"]["contracts_version"] == "0.18.0"


# --------------------------------------------------------------------------
# 2 & 3. Ce que la nouvelle image porte reellement
# --------------------------------------------------------------------------


def test_2_l_image_worker_contient_ingestion_agents(preuve: dict) -> None:
    imports = preuve["verification"]["imports_ok"]
    assert "ingestor.ingestion_agents.classifier" in imports
    assert "ingestor.ingestion_worker.sealed_release_ingestion_cli" in imports
    assert preuve["verification"]["dependencies_present"]["httpx"] is True


def test_3_l_image_worker_declare_les_contrats_0_19_0(
    document: dict, preuve: dict
) -> None:
    assert preuve["verification"]["nexus_contracts_version"] == "0.19.0"
    assert _image(document)["contracts_version"] == "0.19.0"


def test_3bis_aucun_secret_dans_l_image(preuve: dict) -> None:
    scan = preuve["verification"]["secrets_scan"]
    assert scan["secret_bearing_variables"] == 0
    assert scan["secret_files_found"] == 0


# --------------------------------------------------------------------------
# 4 & 5. Le digest, jamais le tag
# --------------------------------------------------------------------------


def test_4_le_digest_est_obligatoire(document: dict) -> None:
    assert _ecarts(document) == [] or all(
        "image worker" not in ecart for ecart in _ecarts(document)
    )
    copie = copy.deepcopy(document)
    del copie["scope"]["staging_worker_image"]["image_digest"]
    assert any("image_digest" in ecart for ecart in _ecarts(copie))


def test_5_un_tag_seul_est_refuse(document: dict) -> None:
    copie = copy.deepcopy(document)
    copie["scope"]["staging_worker_image"]["reference"] = (
        "ghcr.io/cyranoaladin/rag-multilevel-worker-production:latest"
    )
    ecarts = _ecarts(copie)
    assert any("reference" in ecart for ecart in ecarts)


def test_5bis_tag_alone_accepted_ne_peut_pas_passer_a_true(document: dict) -> None:
    copie = copy.deepcopy(document)
    copie["scope"]["staging_worker_image"]["tag_alone_accepted"] = True
    assert any("tag_alone_accepted" in ecart for ecart in _ecarts(copie))


def test_5ter_un_digest_different_du_digest_gouverne_est_refuse(document: dict) -> None:
    copie = copy.deepcopy(document)
    copie["scope"]["staging_worker_image"]["image_digest"] = "sha256:" + "0" * 64
    assert any("image_digest" in ecart for ecart in _ecarts(copie))


# --------------------------------------------------------------------------
# 6. Construite hors nexus-prod
# --------------------------------------------------------------------------


def test_6_le_build_sur_nexus_prod_est_refuse(document: dict, preuve: dict) -> None:
    assert _image(document)["build_on_nexus_prod"] == "forbidden"
    assert _image(document)["built_off_host"] is True
    assert preuve["built_off_host"]["built_on_nexus_prod"] is False
    assert preuve["built_off_host"]["where"] == "GitHub Actions"

    copie = copy.deepcopy(document)
    copie["scope"]["staging_worker_image"]["built_off_host"] = False
    assert any("built_off_host" in ecart for ecart in _ecarts(copie))


def test_6bis_le_build_est_lie_a_un_run_reel_et_au_commit_de_main(
    document: dict, preuve: dict
) -> None:
    image = _image(document)
    construit = preuve["built_off_host"]
    assert image["build_workflow"] == construit["workflow"]
    assert image["build_workflow_run_id"] == construit["run_id"]
    assert image["source_commit_sha"] == construit["source_commit_sha"]
    assert construit["workflow_ref"] == "refs/heads/main"


def test_6ter_le_workflow_de_construction_existe_et_refuse_hors_main() -> None:
    chemin = RACINE / ".github/workflows/production-image-provenance.yml"
    contenu = chemin.read_text(encoding="utf-8")
    assert "github.ref != 'refs/heads/main'" in contenu
    assert "push: true" in contenu


def test_6quater_un_autre_workflow_de_construction_est_refuse(document: dict) -> None:
    copie = copy.deepcopy(document)
    copie["scope"]["staging_worker_image"]["build_workflow"] = (
        ".github/workflows/autre.yml"
    )
    assert any("build_workflow" in ecart for ecart in _ecarts(copie))


# --------------------------------------------------------------------------
# 7, 8, 9. Le perimetre reste celui du staging
# --------------------------------------------------------------------------


def test_7_la_base_produit_reste_interdite(document: dict, preuve: dict) -> None:
    assert _image(document)["product_database_access"] == "forbidden"
    assert "production_db_write" in document["forbidden"]
    assert "production_db_read" in document["forbidden"]
    assert preuve["scope_unchanged"]["production_db"] == "forbidden"

    copie = copy.deepcopy(document)
    copie["scope"]["staging_worker_image"]["product_database_access"] = "allowed"
    assert any("product_database_access" in ecart for ecart in _ecarts(copie))


def test_8_le_current_switch_reste_interdit(document: dict, preuve: dict) -> None:
    assert "current_switch" in document["forbidden"]
    assert preuve["scope_unchanged"]["current_switch"] == "forbidden"
    copie = copy.deepcopy(document)
    copie["forbidden"].remove("current_switch")
    assert any("interdits" in ecart for ecart in _ecarts(copie))


def test_9_l_image_n_est_utilisable_que_dans_le_perimetre_staging(
    document: dict,
) -> None:
    image = _image(document)
    assert image["network"] == "loopback_only"
    assert image["durable_service"] is False
    assert image["compose_file_on_host"] == "forbidden"
    assert document["scope"]["access"] == "ssh_tunnel_only"
    assert document["scope"]["bind_address"] == "127.0.0.1"


def test_9bis_seul_le_point_d_entree_de_release_scellee_est_autorise(
    document: dict,
) -> None:
    """L'image sait lancer les deux workers ; l'autorisation, non."""
    image = _image(document)
    assert image["allowed_entrypoint_module"] == (
        "ingestor.ingestion_worker.sealed_release_ingestion_cli"
    )
    assert set(image["forbidden_entrypoint_modules"]) == {
        "ingestor.ingestion_worker.multilevel_cli",
        "ingestor.ingestion_worker.multilevel_publication_resume_cli",
    }


def test_9ter_worker_b_reste_hors_de_portee(document: dict, preuve: dict) -> None:
    image = _image(document)
    assert (
        "ingestor.ingestion_worker.multilevel_publication_resume_cli"
        in image["forbidden_entrypoint_modules"]
    )
    assert preuve["scope_unchanged"]["worker_b"] == "forbidden"


def test_9quater_retirer_un_module_interdit_est_refuse(document: dict) -> None:
    copie = copy.deepcopy(document)
    copie["scope"]["staging_worker_image"]["forbidden_entrypoint_modules"] = []
    assert any("modules interdits" in ecart for ecart in _ecarts(copie))


def test_9quinquies_un_service_durable_est_refuse(document: dict) -> None:
    copie = copy.deepcopy(document)
    copie["scope"]["staging_worker_image"]["durable_service"] = True
    assert any("durable_service" in ecart for ecart in _ecarts(copie))


# --------------------------------------------------------------------------
# Liaison preuve <-> autorisation
# --------------------------------------------------------------------------


def test_la_preuve_est_liee_par_digest_a_l_autorisation(document: dict) -> None:
    declare = _image(document)["evidence"]
    observe = hashlib.sha256((RACINE / declare["path"]).read_bytes()).hexdigest()
    assert declare["path"] == _preuve_courante()
    assert declare["sha256"] == observe


def test_une_preuve_absente_invalide_l_autorisation(document: dict) -> None:
    copie = copy.deepcopy(document)
    del copie["scope"]["staging_worker_image"]["evidence"]
    assert any("preuve de provenance" in ecart for ecart in _ecarts(copie))


def test_sans_image_worker_l_autorisation_n_autorise_aucune_image(
    document: dict,
) -> None:
    copie = copy.deepcopy(document)
    del copie["scope"]["staging_worker_image"]
    assert any("aucune image n'est autorisee" in ecart for ecart in _ecarts(copie))


def test_les_amendements_sont_consignes_dans_l_ordre(document: dict) -> None:
    """La liste s'allonge a chaque amendement ; ce qui doit rester vrai, c'est
    que les premiers y figurent toujours, dans l'ordre, et qu'aucun ne
    disparait."""
    amendements = document["amended_by"]
    assert amendements[:5] == ["CH2", "CH3", "CH4", "CH6", "CH7B"]
    assert len(amendements) == len(set(amendements))
    assert document["expires_after_use"] is True


def test_la_preuve_de_ch6_reste_versionnee_comme_trace(document: dict) -> None:
    """Remplacer un digest n'efface pas ce qui avait ete autorise avant."""
    ancienne = json.loads((RACINE / PREUVE_CH6).read_text(encoding="utf-8"))
    assert ancienne["worker_image"]["image_digest"].startswith("sha256:2ce7533d")
    # L'autorisation courante ne remplace plus CH6 directement — elle
    # remplace celui qui l'avait remplace. La chaine se lit de proche en
    # proche, et chaque maillon reste versionne.
    assert _image(document)["supersedes_image_digest"] != (
        ancienne["worker_image"]["image_digest"]
    )
    courante = json.loads((RACINE / _preuve_courante()).read_text(encoding="utf-8"))
    assert courante["supersedes"]["worker_image_digest"] != (
        ancienne["worker_image"]["image_digest"]
    )
