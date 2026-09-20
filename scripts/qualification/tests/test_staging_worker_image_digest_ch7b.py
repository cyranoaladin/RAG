"""CH7B — le digest worker autorisé change, et lui seul.

Ces épreuves portent sur l'autorisation versionnée et sur la preuve de
provenance qui l'accompagne. Les faits mesurés sur les octets réels de
l'image — contrats 0.19.0, `staging_readiness_gate.py` présent, garde
d'identité présente, refus effectifs, absence de secret — ont été relevés
hors `nexus-prod` et consignés dans cette preuve ; ce fichier vérifie que
l'autorisation et la preuve disent la MÊME chose.

Un test qui tirerait l'image depuis la CI mesurerait le réseau, pas la
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

PREUVE = "docs/reports/evidence/staging_worker_image_provenance_ch7b.json"

DIGEST_CH6 = "sha256:2ce7533d00e171f47d42a579ad6afe1d8b5d51e91c63f14cf6ae051592109029"
DIGEST_CH7B = "sha256:1fb70485f94a539c83142a372b24fa657daea398524173c5cdb5a3d2a9c38efb"
COMMIT_CH7A = "f66a04cb364191c53eb56c9a9e1208e9e386ae16"
DEPOT = "ghcr.io/cyranoaladin/rag-multilevel-worker-production"


@pytest.fixture()
def document() -> dict:
    return json.loads((RACINE / autorisation.AUTORISATION).read_text(encoding="utf-8"))


@pytest.fixture()
def preuve() -> dict:
    return json.loads((RACINE / PREUVE).read_text(encoding="utf-8"))


def _plan_sha(document: dict) -> str:
    return hashlib.sha256(
        (RACINE / document["execution_plan"]["path"]).read_bytes()
    ).hexdigest()


def _image(document: dict) -> dict:
    return document["scope"]["staging_worker_image"]


def _ecarts(document: dict) -> list[str]:
    return autorisation.evaluer(document, plan_sha256=_plan_sha(document))


def _ecarts_image(document: dict) -> list[str]:
    return [ecart for ecart in _ecarts(document) if "image worker" in ecart]


# ==========================================================================
# 1 & 2. L'ancien digest cède la place au nouveau
# ==========================================================================


def test_1_l_ancien_digest_ch6_est_refuse(document: dict) -> None:
    """Y revenir n'est pas un retour en arrière neutre : cette image précède
    la chaîne de readiness de répétition et ne peut plus rien exécuter."""
    copie = copy.deepcopy(document)
    copie["scope"]["staging_worker_image"]["image_digest"] = DIGEST_CH6
    copie["scope"]["staging_worker_image"]["reference"] = f"{DEPOT}@{DIGEST_CH6}"
    ecarts = _ecarts_image(copie)
    assert any("digest de CH6 a ete remis en place" in ecart for ecart in ecarts)


def test_1bis_l_amendement_nomme_le_digest_qu_il_remplace(document: dict) -> None:
    assert _image(document)["supersedes_image_digest"] == DIGEST_CH6
    copie = copy.deepcopy(document)
    del copie["scope"]["staging_worker_image"]["supersedes_image_digest"]
    assert any("digest qu'il remplace" in ecart for ecart in _ecarts_image(copie))


def test_1ter_la_preuve_dit_pourquoi_l_ancienne_image_ne_convient_plus(
    preuve: dict,
) -> None:
    remplace = preuve["supersedes"]
    assert remplace["worker_image_digest"] == DIGEST_CH6
    assert "staging_readiness_gate" in remplace["observed_refusal"]
    assert "CQ" in remplace["reason"] and "CH7A" in remplace["reason"]


def test_2_le_nouveau_digest_est_celui_autorise(document: dict, preuve: dict) -> None:
    image = _image(document)
    assert image["image_digest"] == DIGEST_CH7B
    assert image["reference"] == f"{DEPOT}@{DIGEST_CH7B}"
    assert preuve["worker_image"]["image_digest"] == DIGEST_CH7B
    assert _ecarts_image(document) == []


# ==========================================================================
# 3, 4, 5. Le digest, jamais le tag
# ==========================================================================


def test_3_un_tag_seul_est_refuse(document: dict) -> None:
    copie = copy.deepcopy(document)
    copie["scope"]["staging_worker_image"]["reference"] = f"{DEPOT}:latest"
    assert any("reference" in ecart for ecart in _ecarts_image(copie))


def test_3bis_tag_alone_accepted_reste_false(document: dict) -> None:
    assert _image(document)["tag_alone_accepted"] is False
    copie = copy.deepcopy(document)
    copie["scope"]["staging_worker_image"]["tag_alone_accepted"] = True
    assert any("tag_alone_accepted" in ecart for ecart in _ecarts_image(copie))


def test_3ter_aucun_tag_latest_n_est_publie(preuve: dict) -> None:
    assert preuve["worker_image"]["latest_tag_published"] is False
    assert preuve["worker_image"]["tags_published"] == [f"sha-{COMMIT_CH7A}"]


def test_4_un_digest_absent_est_refuse(document: dict) -> None:
    copie = copy.deepcopy(document)
    del copie["scope"]["staging_worker_image"]["image_digest"]
    assert any("image_digest" in ecart for ecart in _ecarts_image(copie))


def test_5_un_digest_divergent_est_refuse(document: dict) -> None:
    copie = copy.deepcopy(document)
    copie["scope"]["staging_worker_image"]["image_digest"] = "sha256:" + "0" * 64
    assert any("image_digest" in ecart for ecart in _ecarts_image(copie))


# ==========================================================================
# 6. Le commit source est celui qui porte CH7A
# ==========================================================================


def test_6_un_commit_source_different_est_refuse(document: dict) -> None:
    assert _image(document)["source_commit_sha"] == COMMIT_CH7A
    copie = copy.deepcopy(document)
    copie["scope"]["staging_worker_image"]["source_commit_sha"] = "0" * 40
    assert any("source_commit_sha" in ecart for ecart in _ecarts_image(copie))


def test_6bis_le_commit_source_est_celui_du_build_gouverne(
    document: dict, preuve: dict
) -> None:
    image = _image(document)
    construit = preuve["built_off_host"]
    assert image["source_commit_sha"] == construit["source_commit_sha"]
    assert image["source_tree_sha"] == construit["source_tree_sha"]
    assert image["build_workflow_run_id"] == construit["run_id"]
    assert construit["workflow_ref"] == "refs/heads/main"
    assert construit["workflow"] == ".github/workflows/production-image-provenance.yml"


def test_6ter_le_commit_source_contient_bien_ch7a() -> None:
    """La garde d'identité d'image doit exister à ce commit, pas seulement
    dans la preuve qui l'affirme."""
    import subprocess

    resultat = subprocess.run(
        [
            "git", "-C", str(RACINE), "cat-file", "-e",
            f"{COMMIT_CH7A}:services/rag-engine/src/ingestor/ingestion_profiles/"
            "staging_readiness_gate.py",
        ],
        capture_output=True, text=True, check=False,
    )
    if resultat.returncode != 0 and "not a valid object" in resultat.stderr:
        pytest.skip("objet git indisponible dans ce checkout")
    assert resultat.returncode == 0, resultat.stderr


# ==========================================================================
# 7, 8, 9. Ce que l'image doit porter, et ne pas porter
# ==========================================================================


def test_7_l_image_contient_staging_readiness_gate(preuve: dict) -> None:
    verif = preuve["verification"]
    assert verif["staging_readiness_gate_present"] is True
    assert verif["entrypoint_calls_enforce_staging_readiness_gate"] is True
    assert verif["entrypoint_calls_enforce_readiness_gate"] is False
    assert (
        "ingestor.ingestion_profiles.staging_readiness_gate" in verif["imports_ok"]
    )


def test_8_l_image_contient_la_garde_d_identite(document: dict, preuve: dict) -> None:
    verif = preuve["verification"]
    assert verif["image_binding_guard_present"] is True
    assert verif["actual_worker_image_env_present_in_gate"] is True
    assert _image(document)["runtime_image_binding_guard"] == "NEXUS_ACTUAL_WORKER_IMAGE"


def test_8bis_la_garde_a_ete_mesuree_dans_l_image_pas_seulement_lue(
    preuve: dict,
) -> None:
    """Quatre refus et une acceptation, constatés en exécutant l'image."""
    mesure = preuve["verification"]["guard_behaviour_measured_inside_the_image"]
    assert mesure["missing_variable_refused"] is True
    assert mesure["superseded_ch6_digest_refused"] is True
    assert mesure["tag_only_refused"] is True
    assert mesure["same_digest_other_repository_refused"] is True
    assert mesure["exact_signed_image_accepted"] is True


def test_8ter_retirer_la_garde_de_l_autorisation_est_refuse(document: dict) -> None:
    copie = copy.deepcopy(document)
    del copie["scope"]["staging_worker_image"]["runtime_image_binding_guard"]
    assert any(
        "runtime_image_binding_guard" in ecart for ecart in _ecarts_image(copie)
    )


def test_9_aucun_secret_aucune_cle_aucun_manifeste_dans_l_image(preuve: dict) -> None:
    scan = preuve["verification"]["secrets_scan"]
    assert scan["secret_bearing_variables"] == 0
    assert scan["secret_files_found"] == 0
    assert scan["private_key_files"] == 0
    assert scan["seed_files"] == 0
    assert scan["signed_manifest_embedded"] is False
    assert scan["trust_anchor_embedded"] is False
    assert scan["hex64_literals_in_application_code"] == 0


def test_9bis_les_contrats_de_l_image_sont_ceux_du_depot(
    document: dict, preuve: dict
) -> None:
    assert preuve["verification"]["nexus_contracts_version"] == "0.19.0"
    assert _image(document)["contracts_version"] == "0.19.0"


# ==========================================================================
# 10 à 15. Ce que l'amendement ne desserre pas
# ==========================================================================


def test_10_le_build_sur_nexus_prod_reste_refuse(
    document: dict, preuve: dict
) -> None:
    assert _image(document)["build_on_nexus_prod"] == "forbidden"
    assert _image(document)["built_off_host"] is True
    assert preuve["built_off_host"]["built_on_nexus_prod"] is False
    assert preuve["nexus_prod_untouched_by_this_lot"]["image_built_on_host"] is False

    copie = copy.deepcopy(document)
    copie["scope"]["staging_worker_image"]["build_on_nexus_prod"] = "allowed"
    assert any("build_on_nexus_prod" in ecart for ecart in _ecarts_image(copie))


def test_10bis_l_epinglage_sans_rebuild_est_maintenu(document: dict) -> None:
    assert _image(document)["pinning"] == "pinned_by_digest_no_rebuild"
    assert document["scope"]["ingestor_image"] == "pinned_by_digest_no_rebuild"


def test_11_worker_b_reste_interdit(document: dict, preuve: dict) -> None:
    image = _image(document)
    assert (
        "ingestor.ingestion_worker.multilevel_publication_resume_cli"
        in image["forbidden_entrypoint_modules"]
    )
    assert (
        image["allowed_entrypoint_module"]
        == "ingestor.ingestion_worker.sealed_release_ingestion_cli"
    )
    assert preuve["scope_unchanged"]["worker_b"] == "forbidden"

    copie = copy.deepcopy(document)
    copie["scope"]["staging_worker_image"]["forbidden_entrypoint_modules"] = []
    assert any("modules interdits" in ecart for ecart in _ecarts_image(copie))


def test_11bis_le_cmd_par_defaut_de_l_image_nest_pas_autorise(preuve: dict) -> None:
    """L'image sait lancer Worker A ; l'autorisation, non."""
    verif = preuve["verification"]
    assert "multilevel_cli" in verif["default_cmd"]
    assert "n'autorise PAS" in verif["default_cmd_note"]


def test_12_la_base_produit_reste_interdite(document: dict, preuve: dict) -> None:
    assert _image(document)["product_database_access"] == "forbidden"
    assert "production_db_write" in document["forbidden"]
    assert "production_db_read" in document["forbidden"]
    assert preuve["scope_unchanged"]["production_db"] == "forbidden"
    assert preuve["nexus_prod_untouched_by_this_lot"]["production_db_writes"] == 0


def test_13_le_current_switch_reste_interdit(document: dict, preuve: dict) -> None:
    assert "current_switch" in document["forbidden"]
    assert preuve["scope_unchanged"]["current_switch"] == "forbidden"
    copie = copy.deepcopy(document)
    copie["forbidden"].remove("current_switch")
    assert any("interdits" in ecart for ecart in _ecarts(copie))


def test_14_la_release_v2_nest_pas_modifiee(document: dict, preuve: dict) -> None:
    source = document["scope"]["staging_index_source"]
    assert source["release_id"] == "production-profile-gate-2026-2027-v2"
    assert source["expected_counts"] == {
        "subjects": 11, "unique_artifacts": 315,
        "placements": 479, "unique_chunks": 8268,
    }
    assert preuve["scope_unchanged"]["release_v2_modified"] is False


def test_15_la_v2_nest_pas_rendue_promotable(preuve: dict) -> None:
    assert preuve["scope_unchanged"]["release_v2_promotable"] is False
    manifeste = json.loads(
        (
            RACINE
            / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2"
            / "release-1b9eba0c0eb0ab13/profile_gate/production-profile-gate.release.json"
        ).read_text(encoding="utf-8")
    )
    assert manifeste["promotion_status"] == "NOT_PROMOTABLE"
    assert manifeste["activation_status"] == "NO_PRODUCTION_ACTIVATION"


# ==========================================================================
# L'image API et le périmètre ne bougent pas
# ==========================================================================


def test_l_image_api_reste_inchangee(document: dict, preuve: dict) -> None:
    """CH7B remplace le digest WORKER. L'API garde le sien, et sa version."""
    assert document["scope"]["ingestor_image_digest"].startswith("sha256:d0134f49")
    assert document["scope"]["staging_index_source"]["contracts_version"] == "0.18.0"
    assert preuve["scope_unchanged"]["api_image_untouched"] is True
    assert preuve["scope_unchanged"]["api_image_contracts_version"] == "0.18.0"


def test_le_perimetre_reste_loopback_et_tunnel(document: dict) -> None:
    assert document["scope"]["access"] == "ssh_tunnel_only"
    assert document["scope"]["bind_address"] == "127.0.0.1"
    assert _image(document)["network"] == "loopback_only"
    assert _image(document)["durable_service"] is False
    assert _image(document)["compose_file_on_host"] == "forbidden"


def test_aucune_exposition_publique(document: dict, preuve: dict) -> None:
    assert "public_exposure" in document["forbidden"]
    assert preuve["scope_unchanged"]["public_exposure"] == "forbidden"


# ==========================================================================
# La déclaration d'autorisation est explicite et vérifiée
# ==========================================================================


def test_la_declaration_d_autorisation_est_presente_et_complete(
    document: dict,
) -> None:
    declaration = document["authorization_statement"]
    for mention in (
        "abenrhouma",
        "staging cloisonne uniquement",
        COMMIT_CH7A,
        "production-image-provenance.yml",
        "ni build sur nexus-prod",
        "ni tag non epingle",
        "ni Worker B",
        "ni ecriture DB production",
        "ni current switch",
        "ni exposition publique",
    ):
        assert mention in declaration, mention


@pytest.mark.parametrize(
    "mention",
    [
        "staging cloisonne uniquement",
        COMMIT_CH7A,
        "ni build sur nexus-prod",
        "ni tag non epingle",
        "ni Worker B",
        "ni ecriture DB production",
        "ni current switch",
        "ni exposition publique",
    ],
)
def test_retirer_une_mention_de_la_declaration_est_refuse(
    document: dict, mention: str
) -> None:
    copie = copy.deepcopy(document)
    copie["authorization_statement"] = copie["authorization_statement"].replace(
        mention, ""
    )
    assert any("mention manquante" in ecart for ecart in _ecarts(copie))


def test_la_preuve_est_liee_par_digest_a_l_autorisation(document: dict) -> None:
    declare = _image(document)["evidence"]
    observe = hashlib.sha256((RACINE / declare["path"]).read_bytes()).hexdigest()
    assert declare["path"] == PREUVE
    assert declare["sha256"] == observe


def test_le_point_d_entree_na_pas_ete_execute(preuve: dict) -> None:
    """CH7B autorise ; il n'exécute pas."""
    intact = preuve["nexus_prod_untouched_by_this_lot"]
    assert intact["entrypoint_executed"] == 0
    assert intact["containers_started"] == 0
