"""DB — la publication V4 sur le staging cloisonné, opération par opération.

L'autorisation SSH de base reste ce qu'elle est : elle ouvre l'accès au staging
et interdit Worker B, la base produit, les migrations et toute écriture
d'autorité. Une autorisation gouvernée distincte, liée à la base par empreinte,
ouvre ces opérations — et seulement sur leur cible exacte : conteneur, base,
schéma, rôle, image et release nommés. Tout le reste reste refusé, la
production d'abord ; ni V2, ni V3, ni adoption.
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
DIGEST_SONDE = "sha256:" + "a" * 64
COMMIT = "c" * 40


def _base() -> dict:
    return json.loads((RACINE / autorisation.AUTORISATION).read_text(encoding="utf-8"))


def _v4() -> dict:
    """Une autorisation V4 conforme, construite ici : le document réel attend son digest."""
    doc = copy.deepcopy(autorisation.GABARIT_V4)
    doc["extends"] = {"path": autorisation.AUTORISATION, "sha256": BASE_SHA}
    doc["execution_plan"] = {"path": autorisation.PLAN_V4, "sha256": PLAN_SHA}
    for cle, depot, digest in (
        ("runtime_image", autorisation.DEPOT_IMAGE, DIGEST),
        ("probe_image", autorisation.DEPOT_INGESTOR, DIGEST_SONDE),
    ):
        doc[cle].update({
            "image_digest": digest,
            "reference": f"{depot}@{digest}",
            "source_commit_sha": COMMIT,
            "build_workflow_run_id": 1,
            "build_workflow_run_attempt": 1,
            "evidence": {"path": "docs/reports/evidence/x.json", "sha256": "e" * 64},
        })
    return doc


def _ecarts(doc: dict) -> list[str]:
    return autorisation.evaluer_v4(doc, base_sha256=BASE_SHA, plan_sha256=PLAN_SHA)


def _cible(operation: str) -> dict:
    return copy.deepcopy(autorisation.OPERATIONS_V4[operation]["cible"])


def _autorise(operation: str, cible: dict, v4: dict | None) -> list[str]:
    return autorisation.evaluer_operation(
        operation, cible, document_v4=v4, base_sha256=BASE_SHA, plan_v4_sha256=PLAN_SHA
    )


# ── l'autorisation de base, seule, continue de tout refuser ─────────────────

@pytest.mark.parametrize("operation", sorted(autorisation.OPERATIONS_V4))
def test_l_autorisation_de_base_seule_refuse_chaque_operation_de_publication(operation):
    ecarts = _autorise(operation, _cible(operation), v4=None)
    assert ecarts and "base" in ecarts[0]


def test_l_autorisation_de_base_interdit_toujours_worker_b():
    base = _base()
    assert "ni Worker B" in base["authorization_statement"]
    assert (
        "ingestor.ingestion_worker.multilevel_publication_resume_cli"
        in base["scope"]["staging_worker_image"]["forbidden_entrypoint_modules"]
    )


# ── la nouvelle autorisation, sur sa cible exacte ──────────────────────────

def test_une_autorisation_v4_conforme_est_acceptee():
    assert _ecarts(_v4()) == []


@pytest.mark.parametrize("operation", sorted(autorisation.OPERATIONS_V4))
def test_chaque_operation_est_acceptee_sur_sa_cible_exacte(operation):
    assert _autorise(operation, _cible(operation), _v4()) == []


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
    assert _autorise("worker_b_publication", cible, _v4())


def test_worker_b_ne_recoit_ni_le_role_de_migration_ni_celui_de_revue_ni_celui_d_autorite():
    for role in ("postgres", "raguser", "ingestion_control_authority", "ingestion_control_attestor"):
        cible = _cible("worker_b_publication")
        cible["control_role"] = role
        assert _autorise("worker_b_publication", cible, _v4()), role


def test_worker_b_n_est_autorise_que_sous_qualification_liee_a_la_release():
    cible = _cible("worker_b_publication")
    assert cible["authority_mode"] == "RELEASE_BOUND_STAGING_QUALIFICATION"
    cible["authority_mode"] = "PRODUCTION_READINESS"
    assert _autorise("worker_b_publication", cible, _v4())


@pytest.mark.parametrize(
    "release_id", ["production-profile-gate-2026-2027-v2", "production-profile-gate-2026-2027-v3"]
)
def test_aucune_operation_ne_vise_un_predecesseur(release_id):
    for operation, spec in autorisation.OPERATIONS_V4.items():
        cible = copy.deepcopy(spec["cible"])
        if "release_id" in cible:
            assert cible["release_id"] == autorisation.RELEASE_V4["release_id"], operation
            cible["release_id"] = release_id
            assert _autorise(operation, cible, _v4()), operation


def test_ni_rattrapage_ni_adoption_ne_sont_des_operations():
    for operation in ("attribution_backfill_v2", "adoption_v3", "adoption_v4", "bind_publication_authorities"):
        assert operation not in autorisation.OPERATIONS_V4
        assert _autorise(operation, {}, _v4())
    assert "predecessor_adoption" in autorisation.GABARIT_V4["forbidden"]


def test_une_operation_inconnue_est_refusee():
    assert _autorise("current_switch", {}, _v4())


# ── les r4 : la PR, son head, le rôle d'autorité, et rien d'autre ──────────

def test_l_enregistrement_des_r4_nomme_leur_pr_et_son_head_approuve():
    cible = _cible("scope_authorization_registration_r4")
    assert (cible["pull_request"], cible["expected_head"]) == (
        autorisation.AUTORISATIONS_R4["pull_request"], autorisation.AUTORISATIONS_R4["expected_head"]
    )
    for cle, valeur in (("pull_request", 999), ("expected_head", "0" * 40)):
        autre = copy.deepcopy(cible)
        autre[cle] = valeur
        assert _autorise("scope_authorization_registration_r4", autre, _v4()), cle


def test_le_role_d_autorite_n_existe_que_pour_l_enregistrement_des_r4():
    avec = [op for op, spec in autorisation.OPERATIONS_V4.items()
            if spec["cible"].get("control_role") == "ingestion_control_authority"]
    assert avec == ["scope_authorization_registration_r4"]
    assert "DSN ingestion_control_authority" in autorisation.CIBLES_V4["worker_never_receives"]


def test_l_ingestion_suit_l_enregistrement_des_r4():
    ordre = list(autorisation.ORDRE_V4)
    assert ordre.index("scope_authorization_registration_r4") < ordre.index("sealed_ingestion_v4")
    assert ordre.index("control_migrations") < ordre.index("scope_authorization_registration_r4")


# ── ce que l'autorisation V4 doit dire, et qu'on ne peut pas retirer ───────

@pytest.mark.parametrize(
    ("chemin", "valeur"),
    [
        (("release", "release_id"), "production-profile-gate-2026-2027-v3"),
        (("release", "release_manifest_sha256"), "0" * 64),
        (("release", "served_currentness"), "current"),
        (("release", "served_visibility"), "public"),
        (("release", "profiles_dir"), "services/rag-engine/configs/ingestion_profiles/v2_livraison_319"),
        (("predecessors", "publication"), "allowed"),
        (("scope_authorizations", "pull_request"), 1),
        (("scope_authorizations", "protocol_version"), "LOT41A-V1"),
        (("targets", "database"), "postgres"),
        (("targets", "container"), "rag_pgvector"),
        (("runtime_image", "contracts_version"), "0.20.0"),
        (("runtime_image", "tag_alone_accepted"), True),
        (("probe_image", "durable_service"), True),
        (("probe_image", "image_repository"), "ghcr.io/cyranoaladin/rag-api"),
        (("granted_by_pull_request_approval_of",), "quelqu-un"),
        (("expires_after_use",), False),
    ],
)
def test_un_perimetre_devie_est_refuse(chemin, valeur):
    doc = _v4()
    cible = doc
    for cle in chemin[:-1]:
        cible = cible[cle]
    cible[chemin[-1]] = valeur
    assert _ecarts(doc)


@pytest.mark.parametrize("cle", ["runtime_image", "probe_image"])
def test_une_image_par_tag_est_refusee(cle):
    doc = _v4()
    depot = doc[cle]["image_repository"]
    doc[cle]["reference"] = f"{depot}:latest"
    assert _ecarts(doc)


@pytest.mark.parametrize("digest", autorisation.DIGESTS_ECARTES_V4)
def test_une_image_ecartee_est_refusee(digest):
    doc = _v4()
    doc["runtime_image"]["image_digest"] = digest
    doc["runtime_image"]["reference"] = f"{autorisation.DEPOT_IMAGE}@{digest}"
    assert _ecarts(doc)


def test_l_image_de_cy_est_ecartee():
    assert "sha256:f931f59cb75aecacfb88959aa7b0d85302fd7b40e60851bdb8b1c6860dd35002" in autorisation.DIGESTS_ECARTES_V4


def test_les_deux_images_viennent_du_meme_commit():
    doc = _v4()
    doc["probe_image"]["source_commit_sha"] = "f" * 40
    assert any("même commit" in e for e in _ecarts(doc))


@pytest.mark.parametrize(
    "interdit",
    sorted(autorisation.INTERDITS_REQUIS | {"v2_publication", "v3_publication", "predecessor_adoption"}),
)
def test_une_interdiction_omise_est_refusee(interdit):
    doc = _v4()
    doc["forbidden"] = [x for x in doc["forbidden"] if x != interdit]
    assert _ecarts(doc)


@pytest.mark.parametrize("mention", autorisation.MENTIONS_V4)
def test_retirer_une_mention_de_la_declaration_est_refuse(mention):
    doc = _v4()
    doc["authorization_statement"] = doc["authorization_statement"].replace(mention, "")
    assert _ecarts(doc)


def test_l_autorisation_v4_est_liee_a_la_base_et_au_plan_par_empreinte():
    doc = _v4()
    doc["extends"]["sha256"] = "0" * 64
    assert _ecarts(doc)
    doc = _v4()
    doc["execution_plan"]["sha256"] = "0" * 64
    assert _ecarts(doc)


def test_l_ordre_des_operations_est_celui_du_plan():
    assert list(autorisation.OPERATIONS_V4) == list(autorisation.ORDRE_V4)
    assert _v4()["operations"] == list(autorisation.ORDRE_V4)
    doc = _v4()
    doc["operations"] = list(reversed(doc["operations"]))
    assert _ecarts(doc)


def test_les_roles_sont_separes():
    ops = autorisation.OPERATIONS_V4
    assert ops["worker_b_publication"]["cible"]["control_role"] == "ingestion_control_app"
    assert ops["sealed_ingestion_v4"]["cible"]["control_role"] == "ingestion_control_app"
    assert ops["batch_review_proposal"]["cible"]["control_role"] == "ingestion_control_attestor"
    assert ops["independent_verification"]["cible"]["product_role"] == "rag_reader"


def test_la_tete_de_controle_est_019_et_son_runner_celui_qui_provisionne_les_roles():
    cible = _cible("control_migrations")
    assert cible["target_head"] == "019"
    assert cible["runner"].endswith("provision_and_bootstrap_ingestion_control.sh")
    assert (RACINE / cible["runner"]).is_file()


def test_une_v4_consommee_n_autorise_plus():
    doc = _v4()
    doc["consumed"] = True
    assert _ecarts(doc)


def test_aucun_secret_ni_adresse_dans_le_gabarit():
    brut = json.dumps(autorisation.GABARIT_V4)
    assert "password" not in brut.lower() and "BEGIN" not in brut
    assert not any(c in brut for c in ("88.99.", "postgresql://"))


def test_le_digest_de_base_est_calcule_sur_les_octets():
    raw = (RACINE / autorisation.AUTORISATION).read_bytes()
    assert autorisation.empreinte_base(RACINE) == hashlib.sha256(raw).hexdigest()


# ── le document réel ──────────────────────────────────────────────────────

def _reel() -> dict:
    return json.loads((RACINE / autorisation.AUTORISATION_V4).read_text(encoding="utf-8"))


def test_l_autorisation_v4_reelle_est_conforme_et_liee_a_la_base_et_au_plan():
    doc = _reel()
    plan = hashlib.sha256((RACINE / autorisation.PLAN_V4).read_bytes()).hexdigest()
    assert autorisation.evaluer_v4(
        doc, base_sha256=autorisation.empreinte_base(RACINE), plan_sha256=plan
    ) == []


def test_les_images_autorisees_sont_celles_de_la_preuve_de_provenance():
    doc = _reel()
    image = doc["runtime_image"]
    brut = (RACINE / image["evidence"]["path"]).read_bytes()
    assert hashlib.sha256(brut).hexdigest() == image["evidence"]["sha256"]
    assert doc["probe_image"]["evidence"] == image["evidence"]
    preuve = json.loads(brut)
    assert preuve["image_digest"] == image["image_digest"]
    assert preuve["probe_image"]["image_digest"] == doc["probe_image"]["image_digest"]
    assert preuve["build"]["source_commit_sha"] == image["source_commit_sha"]
    assert preuve["build"]["workflow_run_id"] == image["build_workflow_run_id"]
    assert preuve["verification"]["nexus_contracts_version"] == "0.21.0"
    assert preuve["probe_image"]["nexus_contracts_version"] == "0.21.0"
    assert preuve["build"]["worker_a_and_b_share_digest"] is True
    for commande in ("bind-publication-authorities", "propose-release-batch-review",
                     "record-release-batch-attestation"):
        assert commande in preuve["verification"]["attest_publication_cli_subcommands"]


def test_le_commit_de_build_porte_adr_0060_et_0061():
    """L'image vient du commit de fusion de #251, qui porte le code qualifié."""
    assert _reel()["runtime_image"]["source_commit_sha"] == "0569aff60092251eef691ed2a730dec3bdf7ec81"
