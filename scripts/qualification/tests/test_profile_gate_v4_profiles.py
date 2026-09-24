"""Les profils de V4 : un seul sens pour `programme_version`, la visibilité servie (ADR-0061).

Chaque profil V4 est son profil V2 à trois champs près, dérivés et non saisis :
`profile_version`, `scope.programme_version` = la référence officielle que la
taxonomie de SA collection établit (celle du registre de programme de la
release et du scope de retrieval), et `scope.visibility` = la visibilité servie.
La provenance du corpus reste nommée par le manifeste.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "scripts/go_live"))
for paquet in ("contracts", "release-chain", "pdf-page-policy"):
    sys.path.insert(0, str(RACINE / f"packages/{paquet}/src"))

import build_profile_gate_v4_profiles as v4  # noqa: E402
from nexus_release_chain.ingestion_profiles.manifest import verify_profile_manifest  # noqa: E402
from nexus_release_chain.ingestion_profiles.registry import load_profile_registry  # noqa: E402

CHAMPS_CHANGES = {"profile_version", ("scope", "programme_version"), ("scope", "visibility")}


@pytest.fixture(scope="module")
def profils() -> dict[str, dict]:
    return v4.deriver_profils(RACINE)


def _ancien(collection: str) -> dict:
    return yaml.safe_load((RACINE / v4.ANCIENS / f"{collection}.yml").read_text(encoding="utf-8"))


def _politique(collection: str) -> dict:
    return v4.politique_de(RACINE, collection)


def test_onze_profils(profils):
    assert len(profils) == 11


def test_seuls_trois_champs_changent(profils):
    for collection, nouveau in profils.items():
        ancien = _ancien(collection)
        differents = {k for k in set(ancien) | set(nouveau) if k != "scope" and ancien.get(k) != nouveau.get(k)}
        differents |= {("scope", k) for k in set(ancien["scope"]) | set(nouveau["scope"])
                       if ancien["scope"].get(k) != nouveau["scope"].get(k)}
        assert differents == CHAMPS_CHANGES, (collection, differents)


def test_le_programme_est_celui_de_la_taxonomie_et_du_scope_servi(profils):
    for collection, profil in profils.items():
        taxonomie = v4.taxonomie_de(RACINE, collection)
        assert profil["scope"]["programme_version"] == taxonomie["programme_version"]
        assert profil["scope"]["programme_version"] == _politique(collection)["programme_version"]
        assert profil["scope"]["programme_version"] != "EDUSCOL_CORPUS_20260808"


def test_la_taxonomie_concorde_avec_le_profil_sur_niveau_matiere_statut(profils):
    for collection, profil in profils.items():
        taxonomie = v4.taxonomie_de(RACINE, collection)
        assert profil["scope"]["niveau"] == taxonomie["niveau"]
        assert profil["scope"]["matiere"] == taxonomie["matiere"]


def test_la_visibilite_est_la_politique_servie_et_jamais_plus_large(profils):
    ordre = ["public", "internal", "restricted", "private"]
    for collection, profil in profils.items():
        assert profil["scope"]["visibility"] == _politique(collection)["policy_visibility"]
        assert ordre.index(profil["scope"]["visibility"]) >= ordre.index(_ancien(collection)["scope"]["visibility"])


def test_droits_audience_domaines_inchanges(profils):
    for collection, profil in profils.items():
        ancien = _ancien(collection)
        assert profil["scope"]["audience"] == ancien["scope"]["audience"]
        assert profil["allowed_domains"] == ancien["allowed_domains"]
        assert profil["reject_unknown_rights"] == ancien["reject_unknown_rights"]


def test_les_fichiers_verses_sont_les_profils_derives_et_le_manifeste_verifie(profils):
    dossier = RACINE / v4.NOUVEAUX
    for collection, profil in profils.items():
        assert yaml.safe_load((dossier / f"{collection}.yml").read_text(encoding="utf-8")) == profil
    registre = load_profile_registry(dossier)
    verification = verify_profile_manifest(registre, RACINE / v4.MANIFESTE)
    assert verification.declared_count == 11


def test_le_manifeste_nomme_la_provenance_et_l_approbation(profils):
    manifeste = yaml.safe_load((RACINE / v4.MANIFESTE).read_text(encoding="utf-8"))
    assert "EDUSCOL_CORPUS_20260808" in manifeste["provenance"]
    assert all("ADR-0061" in e["approved_by"] for e in manifeste["profiles"])


def test_les_profils_historiques_ne_sont_pas_modifies():
    for fichier in sorted((RACINE / v4.ANCIENS).glob("rag_nexus_*.yml")):
        assert yaml.safe_load(fichier.read_text(encoding="utf-8"))["scope"]["programme_version"] == (
            "EDUSCOL_CORPUS_20260808"
        )


def test_la_provenance_du_corpus_reste_nommee_par_la_politique(profils):
    for collection in profils:
        assert _politique(collection)["corpus_provenance_id"] == "EDUSCOL_CORPUS_20260808"
        assert _politique(collection)["evidence_visibility"] == _ancien(collection)["scope"]["visibility"]
