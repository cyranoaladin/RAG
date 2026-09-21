"""CS — le digest worker suit ADR-0058, et `merge_sha` nomme le build.

Deux faits liés, et une leçon qui se répète : **une image épinglée par digest
conserve exactement son contenu**. Fusionner du code sur `main` ne la met pas
à jour. C'est vrai pour CH6 → CH7B (garde d'identité), et de nouveau pour
CH7B → CS (revue scellée).

La seconde moitié du lot ferme la boucle inverse : si le manifeste de
readiness devait nommer le commit d'AUTORISATION, chaque PR documentaire
imposerait de reconstruire l'image pour que le manifeste redevienne vrai.
Il nomme donc le commit de BUILD.
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

PREUVE = "docs/reports/evidence/staging_worker_image_provenance_cs.json"
RUNBOOK = RACINE / "docs/runbooks/ceremonie_cle_readiness_repetition.md"

DIGEST_CH6 = "sha256:2ce7533d00e171f47d42a579ad6afe1d8b5d51e91c63f14cf6ae051592109029"
DIGEST_CH7B = "sha256:1fb70485f94a539c83142a372b24fa657daea398524173c5cdb5a3d2a9c38efb"
DIGEST_CS = "sha256:431264a02e2e2a5484cef7d5ac620a3aa7fa16f66be1497fde886dfb7f83ccd8"
COMMIT_ADR_0058 = "39f1314ec3576eb72a5ad0650938eb64252be3a7"
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


def _ecarts_image(document: dict) -> list[str]:
    return [
        e for e in autorisation.evaluer(document, plan_sha256=_plan_sha(document))
        if "image worker" in e
    ]


# --------------------------------------------------------------------------
# Le digest autorisé est celui construit depuis ADR-0058
# --------------------------------------------------------------------------


def test_le_digest_autorise_est_celui_de_l_image_adr_0058(
    document: dict, preuve: dict
) -> None:
    image = _image(document)
    assert image["image_digest"] == DIGEST_CS
    assert image["reference"] == f"{DEPOT}@{DIGEST_CS}"
    assert image["source_commit_sha"] == COMMIT_ADR_0058
    assert preuve["worker_image"]["image_digest"] == DIGEST_CS
    assert _ecarts_image(document) == []


def test_l_image_porte_effectivement_adr_0058(preuve: dict) -> None:
    """Mesuré dans l'image, pas lu dans le checkout."""
    mesure = preuve["verification"]["adr_0058_in_the_image"]
    assert mesure["_verify_sealed_review_present"] is True
    assert mesure["_verify_live_review_used_at_use_time"] is False
    assert mesure["trusted_review_evidence_contract_installed"] is True


def test_l_image_remplacee_ne_portait_pas_adr_0058(preuve: dict) -> None:
    """Le fait qui rend le rebuild obligatoire, et non facultatif."""
    remplacee = preuve["supersedes"]
    assert remplacee["worker_image_digest"] == DIGEST_CH7B
    mesure = remplacee["measured_in_the_superseded_image"]
    assert mesure["_verify_sealed_review_present"] is False
    assert mesure["_verify_live_review_used_at_use_time"] is True
    assert "epinglee par digest" in remplacee["why_a_rebuild_was_mandatory"]


def test_les_gardes_anterieures_sont_toujours_presentes(preuve: dict) -> None:
    """Un rebuild ne doit rien perdre : CQ, CR et CH7A sont dans l'image."""
    gardes = preuve["verification"]["entrypoint_and_guards"]
    assert gardes["sealed_release_ingestion_cli_present"] is True
    assert gardes["staging_readiness_gate_present"] is True
    assert gardes["calls_enforce_staging_readiness_gate"] is True
    assert gardes["image_binding_guard_present"] is True


# --------------------------------------------------------------------------
# Les digests écartés le restent
# --------------------------------------------------------------------------


@pytest.mark.parametrize("digest", [DIGEST_CH6, DIGEST_CH7B])
def test_un_digest_ecarte_ne_peut_plus_etre_autorise(
    document: dict, digest: str
) -> None:
    copie = copy.deepcopy(document)
    copie["scope"]["staging_worker_image"]["image_digest"] = digest
    copie["scope"]["staging_worker_image"]["reference"] = f"{DEPOT}@{digest}"
    assert any("a ete ecarte" in e for e in _ecarts_image(copie))


def test_l_amendement_nomme_le_digest_qu_il_remplace(document: dict) -> None:
    assert _image(document)["supersedes_image_digest"] == DIGEST_CH7B


def test_les_trois_digests_sont_distincts() -> None:
    assert len({DIGEST_CH6, DIGEST_CH7B, DIGEST_CS}) == 3


# --------------------------------------------------------------------------
# `merge_sha` nomme le build — pas l'autorisation
# --------------------------------------------------------------------------


def test_le_contrat_definit_merge_sha_comme_le_commit_de_build() -> None:
    source = (
        RACINE / "packages/contracts/src/nexus_contracts/staging_readiness.py"
    ).read_text(encoding="utf-8")
    assert "dont l'image worker a été construite" in source


def test_le_runbook_dit_explicitement_lequel_des_deux_commits() -> None:
    """La boucle évitée : un manifeste nommant le commit d'autorisation
    imposerait de reconstruire l'image après chaque PR documentaire."""
    texte = RUNBOOK.read_text(encoding="utf-8")
    assert "commit dont l'image a été CONSTRUITE" in texte
    assert "boucle" in texte
    assert "source_commit_sha de l'inventaire de build" in texte


def test_la_declaration_nomme_le_commit_de_build(document: dict) -> None:
    declaration = document["authorization_statement"]
    assert COMMIT_ADR_0058 in declaration
    assert "staging cloisonne uniquement" in declaration


@pytest.mark.parametrize(
    "mention",
    ["ni build sur nexus-prod", "ni tag non epingle", "ni Worker B",
     "ni ecriture DB production", "ni current switch", "ni exposition publique"],
)
def test_retirer_une_mention_de_la_declaration_est_refuse(
    document: dict, mention: str
) -> None:
    copie = copy.deepcopy(document)
    copie["authorization_statement"] = copie["authorization_statement"].replace(
        mention, ""
    )
    ecarts = autorisation.evaluer(copie, plan_sha256=_plan_sha(copie))
    assert any("mention manquante" in e for e in ecarts)


# --------------------------------------------------------------------------
# Le schéma de staging, et le droit qui manquait
# --------------------------------------------------------------------------


def test_le_schema_de_staging_est_passe_a_15(preuve: dict) -> None:
    schema = preuve["staging_schema"]
    assert schema["schema_head_before"] == 14
    assert schema["schema_head_after"] == 15
    assert schema["migrations_applied"] == 1
    assert schema["schema_verification"] == "OK"
    assert schema["rows_with_sealed_evidence_after_migration"] == 0


def test_le_registre_de_revocation_est_lisible_par_le_worker(preuve: dict) -> None:
    """Sans ce droit, une preuve révoquée continuerait d'autoriser."""
    droits = preuve["staging_schema"]["effective_privileges_on_revoked_review_evidence"]
    assert droits["ingestion_control_app"] == ["SELECT"]
    assert droits["ingestion_control_attestor"] == ["SELECT"]
    assert sorted(droits["ingestion_control_authority"]) == ["INSERT", "SELECT"]
    assert "INSERT" not in droits["ingestion_control_app"]
    assert "permission denied" in preuve["staging_schema"]["note"]


# --------------------------------------------------------------------------
# Le périmètre ne bouge pas
# --------------------------------------------------------------------------


def test_l_image_api_reste_inchangee(document: dict, preuve: dict) -> None:
    assert document["scope"]["ingestor_image_digest"].startswith("sha256:d0134f49")
    assert preuve["scope_unchanged"]["api_image_untouched"] is True


@pytest.mark.parametrize(
    "interdit",
    ["worker_b", "production_db", "current_switch", "public_exposure"],
)
def test_les_interdictions_sont_maintenues(preuve: dict, interdit: str) -> None:
    assert preuve["scope_unchanged"][interdit] == "forbidden"


def test_rien_na_ete_execute_par_ce_lot(preuve: dict) -> None:
    assert "aucune execution du point d'entree" in preuve["not_performed"]
    assert "aucune ecriture dans scope_authorizations" in preuve["not_performed"]


def test_la_preuve_est_liee_par_digest_a_l_autorisation(document: dict) -> None:
    declare = _image(document)["evidence"]
    observe = hashlib.sha256((RACINE / declare["path"]).read_bytes()).hexdigest()
    assert declare["path"] == PREUVE
    assert declare["sha256"] == observe


def test_cs_est_consigne_comme_amendement(document: dict) -> None:
    """CS reste a sa place, quels que soient les amendements ulterieurs.

    Un amendement ajoute une ligne ; il n'en reecrit aucune.
    """
    assert document["amended_by"][:6] == ["CH2", "CH3", "CH4", "CH6", "CH7B", "CS"]
