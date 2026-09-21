"""Le renouvellement LOT41A (ADR-0058) : identité technique neuve, métier intact.

Ces épreuves portent sur les vingt-deux artefacts versionnés et sur la carte
de correspondance. Elles distinguent deux choses qu'il serait commode de
confondre :

* ce qui **doit** changer — `authorization_id`, donc le chemin canonique et
  l'empreinte de l'enveloppe ;
* ce qui **ne doit pas** changer — tout le contenu métier.

Prétendre que les enveloppes sont identiques octet pour octet serait faux :
`authorization_id` y figure. L'invariance est vérifiée champ par champ.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "packages/contracts/src"))

from nexus_contracts.authority_artifacts import (  # noqa: E402
    canonical_authorization_path,
    parse_scope_authorization_artifact,
)

AUTORISATIONS = RACINE / "governance/authorizations"
CARTE = RACINE / "docs/governance/lot41a_staging_v2_renewal_map.json"
SUFFIXE = "-r2"

#: Le seul champ dont le changement est autorisé par ce lot.
CHAMP_TECHNIQUE = "authorization_id"


@pytest.fixture()
def carte() -> dict:
    return json.loads(CARTE.read_text(encoding="utf-8"))


def _document(authorization_id: str) -> dict:
    return json.loads(
        (AUTORISATIONS / f"{authorization_id}.json").read_text(encoding="utf-8")
    )


def _octets(authorization_id: str) -> bytes:
    return (AUTORISATIONS / f"{authorization_id}.json").read_bytes()


# --------------------------------------------------------------------------
# La carte couvre exactement les onze, et rien d'autre
# --------------------------------------------------------------------------


def test_la_carte_couvre_les_onze_collections(carte: dict) -> None:
    assert carte["count"] == 11
    assert len(carte["mapping"]) == 11
    collections = {entree["collection"] for entree in carte["mapping"]}
    assert len(collections) == 11


def test_chaque_nouvel_identifiant_derive_de_l_ancien(carte: dict) -> None:
    for entree in carte["mapping"]:
        assert entree["nouveau"]["authorization_id"] == (
            entree["ancien"]["authorization_id"] + SUFFIXE
        )


def test_les_deux_series_existent_sur_disque(carte: dict) -> None:
    """L'ancienne n'est ni supprimée ni modifiée : elle reste lisible."""
    for entree in carte["mapping"]:
        for cote in ("ancien", "nouveau"):
            chemin = AUTORISATIONS / f"{entree[cote]['authorization_id']}.json"
            assert chemin.is_file(), chemin


# --------------------------------------------------------------------------
# Ce qui change, et seulement cela
# --------------------------------------------------------------------------


def test_seul_l_identifiant_change(carte: dict) -> None:
    """Le cœur du lot : invariance métier, champ par champ."""
    for entree in carte["mapping"]:
        ancien = _document(entree["ancien"]["authorization_id"])
        nouveau = _document(entree["nouveau"]["authorization_id"])
        assert set(ancien) == set(nouveau), entree["collection"]
        ecarts = {
            champ for champ in ancien if ancien[champ] != nouveau[champ]
        }
        assert ecarts == {CHAMP_TECHNIQUE}, (entree["collection"], sorted(ecarts))


@pytest.mark.parametrize(
    "champ",
    [
        "scope", "manifest_digest", "profile_id", "profile_version",
        "profile_fingerprint", "allowed_domains", "rights_categories",
        "exclusions", "pii_absence_attested", "pii_absence_evidence",
        "valid_from", "valid_until", "decision", "protocol_version",
    ],
)
def test_chaque_champ_metier_est_recopie_tel_quel(carte: dict, champ: str) -> None:
    for entree in carte["mapping"]:
        ancien = _document(entree["ancien"]["authorization_id"])
        nouveau = _document(entree["nouveau"]["authorization_id"])
        assert ancien[champ] == nouveau[champ], (entree["collection"], champ)


def test_la_fenetre_de_validite_nest_pas_etendue(carte: dict) -> None:
    """Étendre une validité est une décision distincte, pas une conséquence
    automatique du renouvellement."""
    for entree in carte["mapping"]:
        ancien = _document(entree["ancien"]["authorization_id"])
        nouveau = _document(entree["nouveau"]["authorization_id"])
        assert ancien["valid_from"] == nouveau["valid_from"]
        assert ancien["valid_until"] == nouveau["valid_until"]


def test_les_droits_et_exclusions_ne_sont_pas_elargis(carte: dict) -> None:
    for entree in carte["mapping"]:
        ancien = _document(entree["ancien"]["authorization_id"])
        nouveau = _document(entree["nouveau"]["authorization_id"])
        assert ancien["rights_categories"] == nouveau["rights_categories"]
        assert ancien["exclusions"] == nouveau["exclusions"]
        assert ancien["allowed_domains"] == nouveau["allowed_domains"]
        assert ancien["scope"]["audience"] == nouveau["scope"]["audience"]
        assert ancien["scope"]["visibility"] == nouveau["scope"]["visibility"]


# --------------------------------------------------------------------------
# Ce qu'on ne prétend PAS
# --------------------------------------------------------------------------


def test_les_enveloppes_ne_sont_pas_identiques_octet_pour_octet(carte: dict) -> None:
    """Le dire serait faux : `authorization_id` figure dans l'enveloppe."""
    for entree in carte["mapping"]:
        ancien = _octets(entree["ancien"]["authorization_id"])
        nouveau = _octets(entree["nouveau"]["authorization_id"])
        assert ancien != nouveau
        assert hashlib.sha256(ancien).hexdigest() == entree["ancien"]["artifact_sha256"]
        assert hashlib.sha256(nouveau).hexdigest() == entree["nouveau"]["artifact_sha256"]
        assert entree["ancien"]["artifact_sha256"] != entree["nouveau"]["artifact_sha256"]


def test_la_carte_dit_explicitement_ce_qu_elle_ne_pretend_pas(carte: dict) -> None:
    assert "octet pour octet" in carte["what_is_not_claimed"]
    assert "ni modifiees, ni supprimees" in carte["why"]


# --------------------------------------------------------------------------
# Les nouveaux artefacts sont canoniques et enregistrables
# --------------------------------------------------------------------------


def test_chaque_nouvel_artefact_est_canonique(carte: dict) -> None:
    """Le parseur refuse toute non-canonicité : l'enregistrement le refera."""
    for entree in carte["mapping"]:
        identifiant = entree["nouveau"]["authorization_id"]
        artefact = parse_scope_authorization_artifact(_octets(identifiant))
        assert artefact.authorization_id == identifiant


def test_le_chemin_canonique_derive_de_l_identifiant(carte: dict) -> None:
    """La base contraint `artifact_path` à en dériver — un identifiant neuf
    impose donc un fichier neuf, et c'est pourquoi l'ancien survit."""
    for entree in carte["mapping"]:
        identifiant = entree["nouveau"]["authorization_id"]
        attendu = f"governance/authorizations/{identifiant}.json"
        assert canonical_authorization_path(identifiant) == attendu
        assert (RACINE / attendu).is_file()


def test_aucun_identifiant_ne_collisionne(carte: dict) -> None:
    identifiants = [e["nouveau"]["authorization_id"] for e in carte["mapping"]]
    identifiants += [e["ancien"]["authorization_id"] for e in carte["mapping"]]
    assert len(set(identifiants)) == 22


def test_la_release_v2_nest_pas_touchee_par_ce_lot() -> None:
    manifeste = json.loads(
        (
            RACINE
            / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2"
            / "release-1b9eba0c0eb0ab13/profile_gate/production-profile-gate.release.json"
        ).read_text(encoding="utf-8")
    )
    assert manifeste["promotion_status"] == "NOT_PROMOTABLE"
    assert manifeste["expected_counts"] == {
        "subjects": 11, "unique_artifacts": 315,
        "placements": 479, "unique_chunks": 8268,
    }
