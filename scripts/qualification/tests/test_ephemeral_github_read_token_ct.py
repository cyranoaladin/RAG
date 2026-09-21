"""CT — le jeton GitHub éphémère : lecture seule, borné, retiré après usage.

Le worker doit relire l'artefact d'autorisation au head approuvé. C'est ce
qui détecte qu'un artefact aurait été modifié **après** l'approbation — ce
que le sceau d'ADR-0058 ne peut pas voir, puisqu'il enregistre ce qui
*était*, pas ce qui *est encore*.

Il lui faut donc un accès GitHub. Ces épreuves fixent ce que cet accès a le
droit d'être, et surtout ce qu'il n'a pas le droit d'être.
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


@pytest.fixture()
def document() -> dict:
    return json.loads((RACINE / autorisation.AUTORISATION).read_text(encoding="utf-8"))


def _plan_sha(document: dict) -> str:
    return hashlib.sha256(
        (RACINE / document["execution_plan"]["path"]).read_bytes()
    ).hexdigest()


def _jeton(document: dict) -> dict:
    return document["scope"]["ephemeral_github_read_token"]


def _ecarts(document: dict) -> list[str]:
    return autorisation.evaluer(document, plan_sha256=_plan_sha(document))


def _ecarts_jeton(document: dict) -> list[str]:
    return [e for e in _ecarts(document) if "jeton ephemere" in e]


# --------------------------------------------------------------------------
# Lecture seule, un seul dépôt, durée bornée
# --------------------------------------------------------------------------


def test_le_jeton_est_en_lecture_seule(document: dict) -> None:
    jeton = _jeton(document)
    assert jeton["token_permissions"] == {"contents": "read", "metadata": "read"}
    assert _ecarts_jeton(document) == []


@pytest.mark.parametrize(
    "permissions",
    [
        {"contents": "write", "metadata": "read"},
        {"contents": "read", "metadata": "read", "pull_requests": "write"},
        {"contents": "read", "metadata": "read", "workflows": "write"},
        {"contents": "read", "metadata": "read", "secrets": "read"},
        {"contents": "read", "metadata": "read", "administration": "read"},
    ],
)
def test_toute_permission_supplementaire_est_refusee(
    document: dict, permissions: dict
) -> None:
    copie = copy.deepcopy(document)
    copie["scope"]["ephemeral_github_read_token"]["token_permissions"] = permissions
    assert any("token_permissions" in e for e in _ecarts_jeton(copie))


def test_le_jeton_ne_couvre_qu_un_depot(document: dict) -> None:
    assert _jeton(document)["token_repository_selection"] == ["cyranoaladin/RAG"]
    copie = copy.deepcopy(document)
    copie["scope"]["ephemeral_github_read_token"]["token_repository_selection"] = [
        "cyranoaladin/RAG", "cyranoaladin/autre"
    ]
    assert any("token_repository_selection" in e for e in _ecarts_jeton(copie))


def test_la_duree_est_bornee_a_un_jour(document: dict) -> None:
    assert _jeton(document)["max_lifetime_days"] == 1
    copie = copy.deepcopy(document)
    copie["scope"]["ephemeral_github_read_token"]["max_lifetime_days"] = 90
    assert any("max_lifetime_days" in e for e in _ecarts_jeton(copie))


def test_l_autorisation_nomme_ce_que_le_jeton_ne_porte_pas(document: dict) -> None:
    """Un périmètre qui ne dit que ce qu'il permet se lit mal."""
    interdits = " ".join(_jeton(document)["token_must_not_carry"])
    for mot in ("write", "administration", "secrets", "workflows"):
        assert mot in interdits, mot

    copie = copy.deepcopy(document)
    copie["scope"]["ephemeral_github_read_token"]["token_must_not_carry"] = []
    assert any("ne porte pas" in e for e in _ecarts_jeton(copie))


def test_le_jeton_est_distinct_de_celui_de_la_revue(document: dict) -> None:
    """Le worker n'hérite jamais des privilèges d'une revue."""
    distinct = _jeton(document)["distinct_from"]
    assert "abenrhouma" in distinct
    assert "administration" in distinct


# --------------------------------------------------------------------------
# Injection par fichier — jamais par l'environnement ni un argument
# --------------------------------------------------------------------------


def test_le_jeton_est_injecte_par_fichier(document: dict) -> None:
    injection = _jeton(document)["injection"]
    assert injection["env_var"] == "NEXUS_GITHUB_TOKEN_FILE"
    assert injection["value_in_environment"] is False
    assert injection["value_in_command_arguments"] is False
    assert injection["file_mode"] == "0600"
    assert injection["directory_mode"] == "0700"


@pytest.mark.parametrize(
    ("cle", "valeur"),
    [
        ("value_in_environment", True),
        ("value_in_command_arguments", True),
        ("file_mode", "0644"),
        ("directory_mode", "0755"),
        ("env_var", "NEXUS_GITHUB_TOKEN"),
    ],
)
def test_tout_relachement_de_l_injection_est_refuse(
    document: dict, cle: str, valeur: object
) -> None:
    """Élargir les droits du fichier pour résoudre un problème d'UID est
    exactement le raccourci que cette garde refuse."""
    copie = copy.deepcopy(document)
    copie["scope"]["ephemeral_github_read_token"]["injection"][cle] = valeur
    assert any(f"injection.{cle}" in e for e in _ecarts_jeton(copie))


def test_le_code_lit_bien_le_fichier_avant_l_environnement() -> None:
    """La garde vit dans le code, pas seulement dans l'autorisation."""
    source = (
        RACINE / "services/rag-engine/src/ingestor/ingestion_control/github_authority.py"
    ).read_text(encoding="utf-8")
    assert "_TOKEN_FILE_ENV" in source
    assert "/proc/<pid>/environ" in source


# --------------------------------------------------------------------------
# La destination de l'API n'est pas détournable
# --------------------------------------------------------------------------


def test_la_base_d_api_ne_peut_pas_etre_surchargee(document: dict) -> None:
    jeton = _jeton(document)
    assert jeton["api_base_override_forbidden"] is True
    assert jeton["tls_verification_disabled_forbidden"] is True
    for cle in ("api_base_override_forbidden", "tls_verification_disabled_forbidden"):
        copie = copy.deepcopy(document)
        copie["scope"]["ephemeral_github_read_token"][cle] = False
        assert any(cle in e for e in _ecarts_jeton(copie))


# --------------------------------------------------------------------------
# Le worker n'obtient pas l'autorité en passant
# --------------------------------------------------------------------------


def test_le_worker_tourne_sous_le_role_applicatif(document: dict) -> None:
    base = _jeton(document)["database"]
    assert base["role"] == "ingestion_control_app"
    assert base["authority_dsn_in_worker"] is False


def test_monter_le_dsn_d_autorite_dans_le_worker_est_refuse(document: dict) -> None:
    """Faciliter un test ne justifie pas d'y mettre le droit d'écrire des
    autorisations."""
    copie = copy.deepcopy(document)
    copie["scope"]["ephemeral_github_read_token"]["database"][
        "authority_dsn_in_worker"
    ] = True
    assert any("DSN d'autorite" in e for e in _ecarts_jeton(copie))


def test_un_autre_role_de_base_est_refuse(document: dict) -> None:
    copie = copy.deepcopy(document)
    copie["scope"]["ephemeral_github_read_token"]["database"]["role"] = (
        "ingestion_control_authority"
    )
    assert any("ingestion_control_app" in e for e in _ecarts_jeton(copie))


# --------------------------------------------------------------------------
# Fin d'opération : quatre gestes, aucun facultatif
# --------------------------------------------------------------------------


@pytest.mark.parametrize("geste", list(autorisation.FIN_OPERATION_REQUISE))
def test_chaque_geste_de_fin_est_exige(document: dict, geste: str) -> None:
    copie = copy.deepcopy(document)
    restants = [
        g for g in copie["scope"]["ephemeral_github_read_token"]["end_of_operation"]
        if g != geste
    ]
    copie["scope"]["ephemeral_github_read_token"]["end_of_operation"] = restants
    assert any("fin d'operation incomplete" in e for e in _ecarts_jeton(copie))


def test_suppression_et_revocation_sont_deux_resultats_distincts(
    document: dict,
) -> None:
    """Une expiration future annoncée n'est pas une révocation effectuée."""
    texte = _jeton(document)["cleanup_is_verified_not_assumed"]
    assert "deux resultats distincts" in texte
    assert "expiration future" in texte


# --------------------------------------------------------------------------
# La clarification réseau n'élargit rien
# --------------------------------------------------------------------------


def test_la_clarification_reseau_distingue_exposition_et_sortie(
    document: dict,
) -> None:
    image = document["scope"]["staging_worker_image"]
    assert image["network"] == "no_inbound_exposure"
    clarification = image["network_clarification"]
    assert "EXPOSITION" in clarification
    assert "SORTIE" in clarification
    assert "aucune permission n'est ajoutee" in clarification
    assert "aucun pare-feu n'est modifie" in clarification


def test_la_sortie_autorisee_se_limite_a_l_api_github(document: dict) -> None:
    egress = document["scope"]["staging_worker_image"]["egress"]
    assert egress["allowed"] == ["https://api.github.com"]
    assert egress["inbound_exposure_added"] is False
    assert egress["firewall_modified"] is False


def test_la_sortie_est_justifiee_par_ce_que_le_sceau_ne_voit_pas(
    document: dict,
) -> None:
    """La relecture n'est pas un reliquat : elle couvre un angle mort réel."""
    raison = document["scope"]["staging_worker_image"]["egress"]["purpose"]
    assert "APRES l'approbation" in raison
    assert "sceau ne peut pas voir" in raison


# --------------------------------------------------------------------------
# Le reste du périmètre ne bouge pas
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "interdit",
    ["current_switch", "production_db_write", "production_db_read",
     "public_exposure", "production_secret_read"],
)
def test_les_interdictions_historiques_sont_maintenues(
    document: dict, interdit: str
) -> None:
    assert interdit in document["forbidden"]


def test_worker_b_reste_interdit(document: dict) -> None:
    image = document["scope"]["staging_worker_image"]
    assert (
        "ingestor.ingestion_worker.multilevel_publication_resume_cli"
        in image["forbidden_entrypoint_modules"]
    )
    jeton = _jeton(document)
    assert jeton["processes"] == [
        "ingestor.ingestion_worker.sealed_release_ingestion_cli",
        "verifications de pre-vol et de post-execution de cette intervention",
    ]


def test_la_declaration_couvre_le_jeton(document: dict) -> None:
    declaration = document["authorization_statement"]
    assert "LECTURE SEULE" in declaration
    assert "NEXUS_GITHUB_TOKEN_FILE" in declaration
    assert "revocation en fin d'operation" in declaration
    assert "ni secret de production" in declaration


def test_ct_est_consigne_comme_amendement(document: dict) -> None:
    assert document["amended_by"][-1] == "CT"
    assert document["amended_by"][:6] == ["CH2", "CH3", "CH4", "CH6", "CH7B", "CS"]
