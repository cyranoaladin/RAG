"""CY — la publication V3 sur le staging cloisonné, opération par opération.

L'autorisation SSH de base reste ce qu'elle est : elle ouvre l'accès au staging
et interdit Worker B, la base produit, les migrations et l'adoption. Une
autorisation gouvernée distincte, liée à la base par empreinte, ouvre ces
opérations — et seulement sur leur cible exacte : conteneur, base, schéma,
rôle et release nommés. Tout le reste reste refusé, la production d'abord.
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

BASE_SHA = "b" * 64
PLAN_SHA = "p" * 64
DIGEST = "sha256:" + "d" * 64


def _base() -> dict:
    return json.loads((RACINE / autorisation.AUTORISATION).read_text(encoding="utf-8"))


def _v3() -> dict:
    """Une autorisation V3 conforme, construite ici : le document réel attend son digest."""
    doc = copy.deepcopy(autorisation.GABARIT_V3)
    doc["extends"] = {"path": autorisation.AUTORISATION, "sha256": BASE_SHA}
    doc["execution_plan"] = {"path": autorisation.PLAN_V3, "sha256": PLAN_SHA}
    doc["runtime_image"].update({
        "image_digest": DIGEST,
        "reference": f"{autorisation.DEPOT_IMAGE}@{DIGEST}",
        "source_commit_sha": "c" * 40,
        "build_workflow_run_id": 1,
        "build_workflow_run_attempt": 1,
        "evidence": {"path": "docs/reports/evidence/x.json", "sha256": "e" * 64},
    })
    return doc


def _ecarts(doc: dict) -> list[str]:
    return autorisation.evaluer_v3(doc, base_sha256=BASE_SHA, plan_sha256=PLAN_SHA)


def _cible(operation: str) -> dict:
    return copy.deepcopy(autorisation.OPERATIONS_V3[operation]["cible"])


def _autorise(operation: str, cible: dict, v3: dict | None) -> list[str]:
    return autorisation.evaluer_operation(
        operation, cible, document_v3=v3, base_sha256=BASE_SHA, plan_v3_sha256=PLAN_SHA
    )


# ── l'autorisation de base, seule, continue de tout refuser ─────────────────

@pytest.mark.parametrize("operation", sorted(autorisation.OPERATIONS_V3))
def test_l_autorisation_de_base_seule_refuse_chaque_operation_de_publication(operation):
    ecarts = _autorise(operation, _cible(operation), v3=None)
    assert ecarts and "base" in ecarts[0]


def test_l_autorisation_de_base_interdit_toujours_worker_b():
    base = _base()
    assert "ni Worker B" in base["authorization_statement"]
    assert (
        "ingestor.ingestion_worker.multilevel_publication_resume_cli"
        in base["scope"]["staging_worker_image"]["forbidden_entrypoint_modules"]
    )


# ── la nouvelle autorisation, sur sa cible exacte ──────────────────────────

def test_une_autorisation_v3_conforme_est_acceptee():
    assert _ecarts(_v3()) == []


@pytest.mark.parametrize("operation", sorted(autorisation.OPERATIONS_V3))
def test_chaque_operation_est_acceptee_sur_sa_cible_exacte(operation):
    assert _autorise(operation, _cible(operation), _v3()) == []


@pytest.mark.parametrize(
    ("cle", "valeur"),
    [
        ("container", "rag_pgvector"),
        ("database", "postgres"),
        ("host", "nexus-prod-direct"),
        ("compose_project", "nexus"),
    ],
)
def test_worker_b_hors_de_sa_cible_est_refuse(cle, valeur):
    cible = _cible("worker_b_publication")
    cible[cle] = valeur
    assert _autorise("worker_b_publication", cible, _v3())


def test_worker_b_ne_recoit_ni_le_role_de_migration_ni_celui_de_revue():
    for role in ("postgres", "raguser", "ingestion_control_authority", "ingestion_control_attestor"):
        cible = _cible("worker_b_publication")
        cible["control_role"] = role
        assert _autorise("worker_b_publication", cible, _v3()), role


def test_la_publication_de_v2_reste_interdite():
    cible = _cible("worker_b_publication")
    cible["release_id"] = autorisation.PREDECESSEUR_V2["release_id"]
    assert _autorise("worker_b_publication", cible, _v3())


def test_v2_n_est_nommee_que_pour_le_rattrapage_et_l_adoption():
    for operation, spec in autorisation.OPERATIONS_V3.items():
        if spec["cible"].get("release_id") == autorisation.PREDECESSEUR_V2["release_id"]:
            assert operation == "attribution_backfill_v2", operation


def test_une_operation_inconnue_est_refusee():
    assert _autorise("current_switch", {}, _v3())


# ── ce que l'autorisation V3 doit dire, et qu'on ne peut pas retirer ───────

@pytest.mark.parametrize(
    ("chemin", "valeur"),
    [
        (("release", "release_id"), "production-profile-gate-2026-2027-v2"),
        (("release", "release_manifest_sha256"), "0" * 64),
        (("release", "served_currentness"), "current"),
        (("targets", "database"), "postgres"),
        (("targets", "container"), "rag_pgvector"),
        (("runtime_image", "contracts_version"), "0.19.0"),
        (("runtime_image", "tag_alone_accepted"), True),
        (("granted_by_pull_request_approval_of",), "quelqu-un"),
        (("expires_after_use",), False),
    ],
)
def test_un_perimetre_devie_est_refuse(chemin, valeur):
    doc = _v3()
    cible = doc
    for cle in chemin[:-1]:
        cible = cible[cle]
    cible[chemin[-1]] = valeur
    assert _ecarts(doc)


def test_une_image_par_tag_ou_ecartee_est_refusee():
    doc = _v3()
    doc["runtime_image"]["reference"] = f"{autorisation.DEPOT_IMAGE}:latest"
    assert _ecarts(doc)
    doc = _v3()
    doc["runtime_image"]["image_digest"] = autorisation.DIGESTS_ECARTES[0]
    doc["runtime_image"]["reference"] = f"{autorisation.DEPOT_IMAGE}@{autorisation.DIGESTS_ECARTES[0]}"
    assert _ecarts(doc)


@pytest.mark.parametrize("interdit", sorted(autorisation.INTERDITS_REQUIS | {"v2_publication"}))
def test_une_interdiction_de_production_omise_est_refusee(interdit):
    doc = _v3()
    doc["forbidden"] = [x for x in doc["forbidden"] if x != interdit]
    assert _ecarts(doc)


@pytest.mark.parametrize("mention", autorisation.MENTIONS_V3)
def test_retirer_une_mention_de_la_declaration_est_refuse(mention):
    doc = _v3()
    doc["authorization_statement"] = doc["authorization_statement"].replace(mention, "")
    assert _ecarts(doc)


def test_l_autorisation_v3_est_liee_a_la_base_et_au_plan_par_empreinte():
    doc = _v3()
    doc["extends"]["sha256"] = "0" * 64
    assert _ecarts(doc)
    doc = _v3()
    doc["execution_plan"]["sha256"] = "0" * 64
    assert _ecarts(doc)


def test_l_ordre_des_operations_est_celui_du_plan():
    assert list(autorisation.OPERATIONS_V3) == list(autorisation.ORDRE_V3)
    assert _v3()["operations"] == list(autorisation.ORDRE_V3)
    doc = _v3()
    doc["operations"] = list(reversed(doc["operations"]))
    assert _ecarts(doc)


def test_les_roles_sont_separes():
    roles = {spec["cible"].get("control_role") for spec in autorisation.OPERATIONS_V3.values()}
    assert autorisation.OPERATIONS_V3["worker_b_publication"]["cible"]["control_role"] == "ingestion_control_app"
    assert autorisation.OPERATIONS_V3["batch_review_proposal"]["cible"]["control_role"] == "ingestion_control_attestor"
    assert "ingestion_control_authority" not in roles  # aucune autorisation n'est enregistrée ici


def test_une_v3_consommee_n_autorise_plus():
    doc = _v3()
    doc["consumed"] = True
    assert _ecarts(doc)


def test_aucun_secret_ni_adresse_dans_le_gabarit():
    brut = json.dumps(autorisation.GABARIT_V3)
    assert "password" not in brut.lower() and "BEGIN" not in brut
    assert not any(c in brut for c in ("88.99.", "postgresql://"))


def test_le_digest_de_base_est_calcule_sur_les_octets():
    raw = (RACINE / autorisation.AUTORISATION).read_bytes()
    assert autorisation.empreinte_base(RACINE) == hashlib.sha256(raw).hexdigest()


# ── le document réel ──────────────────────────────────────────────────────

def _reel() -> dict:
    return json.loads((RACINE / autorisation.AUTORISATION_V3).read_text(encoding="utf-8"))


def test_l_autorisation_v3_reelle_est_conforme_et_liee_a_la_base_et_au_plan():
    doc = _reel()
    plan = hashlib.sha256((RACINE / autorisation.PLAN_V3).read_bytes()).hexdigest()
    assert autorisation.evaluer_v3(
        doc, base_sha256=autorisation.empreinte_base(RACINE), plan_sha256=plan
    ) == []


def test_l_image_autorisee_est_celle_de_la_preuve_de_provenance():
    image = _reel()["runtime_image"]
    brut = (RACINE / image["evidence"]["path"]).read_bytes()
    assert hashlib.sha256(brut).hexdigest() == image["evidence"]["sha256"]
    preuve = json.loads(brut)
    assert preuve["image_digest"] == image["image_digest"]
    assert preuve["build"]["source_commit_sha"] == image["source_commit_sha"]
    assert preuve["build"]["workflow_run_id"] == image["build_workflow_run_id"]
    assert preuve["verification"]["nexus_contracts_version"] == "0.20.0"
    assert preuve["build"]["worker_a_and_b_share_digest"] is True
    assert preuve["verification"]["secret_like_environment_variables"] == []
    for commande in ("adopt-predecessor-release", "propose-release-batch-review",
                     "record-release-batch-attestation"):
        assert commande in preuve["verification"]["attest_publication_cli_subcommands"]


def test_le_commit_de_build_n_est_pas_le_commit_d_autorisation():
    """Un commit documentaire n'impose aucune reconstruction (leçon CS)."""
    assert _reel()["runtime_image"]["source_commit_sha"] == "7c65ec4b9eeeb2db62905e0e258ba3d5ea3e90f4"
