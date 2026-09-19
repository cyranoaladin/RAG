"""Épreuves de l'autorisation SSH de staging : périmètre borné, fail-closed, liée au plan."""

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
    return hashlib.sha256((RACINE / document["execution_plan"]["path"]).read_bytes()).hexdigest()


def test_autorisation_versionnee_valide_et_liee_au_plan_courant(document):
    assert autorisation.evaluer(document, plan_sha256=_plan_sha(document)) == []


def test_refuse_si_le_plan_a_change_apres_l_autorisation(document):
    assert any("plan" in e for e in autorisation.evaluer(document, plan_sha256="0" * 64))


@pytest.mark.parametrize(
    ("cle", "valeur"),
    [("host", "autre-hote"), ("compose_project", "rag"), ("bind_address", "0.0.0.0"),
     ("access", "public"), ("pgvector_container_required", "rag_pgvector"), ("ingestor_image", "latest")],
)
def test_refuse_un_perimetre_elargi(document, cle, valeur):
    document["scope"][cle] = valeur
    assert any(cle in e for e in autorisation.evaluer(document, plan_sha256=_plan_sha(document)))


@pytest.mark.parametrize("interdit", sorted(autorisation.INTERDITS_REQUIS))
def test_refuse_une_interdiction_omise(document, interdit):
    document["forbidden"].remove(interdit)
    assert any("interdits" in e for e in autorisation.evaluer(document, plan_sha256=_plan_sha(document)))


def test_refuse_autre_approbateur_usage_multiple_ou_sans_conditions_d_arret(document):
    for muter in (
        lambda d: d.update(granted_by_pull_request_approval_of="quelquun"),
        lambda d: d.update(expires_after_use=False),
        lambda d: d.update(stop_conditions=""),
        lambda d: d["scope"].update(loopback_ports={"ingestor": 80}),
    ):
        copie = copy.deepcopy(document)
        muter(copie)
        assert autorisation.evaluer(copie, plan_sha256=_plan_sha(copie))


def test_accepte_port_18003_et_refuse_ancien_port_18001(document):
    assert document["scope"]["loopback_ports"]["ingestor"] == 18003
    assert autorisation.evaluer(document, plan_sha256=_plan_sha(document)) == []

    copie = copy.deepcopy(document)
    copie["scope"]["loopback_ports"]["ingestor"] = 18001
    ecarts = autorisation.evaluer(copie, plan_sha256=_plan_sha(copie))
    assert any("18001" in e or "ports loopback non conformes" in e for e in ecarts)


def test_refuse_port_non_loopback_ou_invalide(document):
    for ports_invalides in (
        {"ingestor": 80, "pgvector": 15435, "prometheus": 19191},
        {"ingestor": 70000, "pgvector": 15435, "prometheus": 19191},
        {"ingestor": 18003, "pgvector": 15435},
    ):
        copie = copy.deepcopy(document)
        copie["scope"]["loopback_ports"] = ports_invalides
        ecarts = autorisation.evaluer(copie, plan_sha256=_plan_sha(copie))
        assert any("ports loopback" in e for e in ecarts)


def test_sans_fichier_aucune_autorisation(tmp_path):
    assert any("aucune autorisation" in e for e in autorisation.verifier(tmp_path))


def test_une_autorisation_consommee_n_autorise_plus(tmp_path, document):
    document["consumed"] = True
    for relatif, contenu in (
        (autorisation.AUTORISATION, json.dumps(document)),
        (document["execution_plan"]["path"], (RACINE / document["execution_plan"]["path"]).read_text(encoding="utf-8")),
    ):
        (tmp_path / relatif).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relatif).write_text(contenu, encoding="utf-8")
    assert any("consommée" in e or "origin/main" in e for e in autorisation.verifier(tmp_path))


def test_aucun_secret_ni_adresse_dans_l_autorisation(document):
    texte = json.dumps(document).lower()
    for motif in ("password", "token=", "bearer ", "@", "ssh-rsa", "-----begin"):
        assert motif not in texte


# --- CH3 — la source de l'index cesse d'être une phrase ------------------


def test_le_perimetre_v2_chiffre_est_accepte(document):
    """Les quatre comptes sont ceux que la release scellée déclare elle-même."""
    source = document["scope"]["staging_index_source"]
    assert source["release_id"] == "production-profile-gate-2026-2027-v2"
    assert source["expected_counts"] == {
        "subjects": 11,
        "unique_artifacts": 315,
        "placements": 479,
        "unique_chunks": 8268,
    }
    assert source["contracts_version"] == "0.18.0"
    assert source["contracts_scopes_available"] == 52
    assert autorisation.evaluer(document, plan_sha256=_plan_sha(document)) == []


def test_les_comptes_v2_sont_ceux_de_la_release_scellee(document):
    """Contre-épreuve : le registre n'invente pas ses chiffres, il les LIT."""
    source = document["scope"]["staging_index_source"]
    manifeste = (
        RACINE
        / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2"
        / "release-1b9eba0c0eb0ab13/profile_gate/production-profile-gate.release.json"
    )
    octets = manifeste.read_bytes()
    assert hashlib.sha256(octets).hexdigest() == source["release_manifest_sha256"]
    release = json.loads(octets)
    assert release["release_id"] == source["release_id"]
    assert release["expected_counts"] == source["expected_counts"]


def test_refuse_l_ancien_perimetre_en_phrase_libre(document):
    """« 11 PDF officiels, 353 chunks » ne vaut plus preuve : c'est du texte."""
    document["scope"]["staging_index_source"] = (
        "ingestion gouvernée de la release multilevel scellée "
        "(11 PDF officiels, 353 chunks) contre la base de staging"
    )
    ecarts = autorisation.evaluer(document, plan_sha256=_plan_sha(document))
    assert any("périmètre chiffré" in e for e in ecarts)


def test_refuse_une_source_d_index_absente(document):
    del document["scope"]["staging_index_source"]
    assert any(
        "périmètre chiffré" in e
        for e in autorisation.evaluer(document, plan_sha256=_plan_sha(document))
    )


@pytest.mark.parametrize(
    ("cle", "valeur"),
    [
        ("release_id", "production-profile-gate-2026-2027-v1"),
        ("target_pgvector_container", "rag_pgvector"),
        ("contracts_version", "0.17.0"),
        ("contracts_scopes_available", 41),
        ("production_database", "allowed"),
    ],
)
def test_refuse_une_source_d_index_deviee(document, cle, valeur):
    document["scope"]["staging_index_source"][cle] = valeur
    assert any(
        cle in e for e in autorisation.evaluer(document, plan_sha256=_plan_sha(document))
    )


@pytest.mark.parametrize(
    "compte", ["subjects", "unique_artifacts", "placements", "unique_chunks"]
)
def test_refuse_un_compte_v2_altere(document, compte):
    """Un seul compte faux suffit à refuser : ils sont indissociables."""
    document["scope"]["staging_index_source"]["expected_counts"][compte] = 1
    assert any(
        "expected_counts" in e
        for e in autorisation.evaluer(document, plan_sha256=_plan_sha(document))
    )


def test_refuse_des_comptes_v2_incomplets(document):
    del document["scope"]["staging_index_source"]["expected_counts"]["unique_chunks"]
    assert any(
        "expected_counts" in e
        for e in autorisation.evaluer(document, plan_sha256=_plan_sha(document))
    )


def test_le_digest_de_l_image_staging_est_epingle(document):
    """L'image qualifiée est nommée : une autre en service est un refus."""
    assert document["scope"]["ingestor_image_digest"].startswith("sha256:")
    document["scope"]["ingestor_image_digest"] = "sha256:" + "0" * 64
    assert any(
        "ingestor_image_digest" in e
        for e in autorisation.evaluer(document, plan_sha256=_plan_sha(document))
    )


def test_l_autorisation_amendee_reste_a_usage_unique(document):
    """CH3 élargit la source d'index, jamais le régime de consommation."""
    assert document["expires_after_use"] is True
    assert document.get("consumed") is not True
    document["expires_after_use"] = False
    assert any(
        "usage unique" in e
        for e in autorisation.evaluer(document, plan_sha256=_plan_sha(document))
    )


def test_ch3_n_ajoute_aucune_permission_machine(document):
    """Les quinze interdictions machine restent toutes exigées."""
    assert autorisation.INTERDITS_REQUIS <= set(document["forbidden"])
    for interdit in ("production_db_write", "production_ingestion", "public_exposure"):
        assert interdit in document["forbidden"]
