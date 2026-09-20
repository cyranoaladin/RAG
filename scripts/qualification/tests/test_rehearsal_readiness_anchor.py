"""L'ancre de répétition : rien qu'une clé publique, et distincte de production.

Ces épreuves portent sur les **octets réellement versionnés** de l'ancre, pas
sur une forme construite en mémoire. Une ancre est un fichier de gouvernance :
ce qui compte est ce qu'il contient une fois commité.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "packages/contracts/src"))

from nexus_contracts.production_readiness import (  # noqa: E402
    ProductionReadinessError,
    parse_production_readiness_trust_anchor,
)
from nexus_contracts.staging_readiness import (  # noqa: E402
    StagingReadinessError,
    parse_staging_readiness_trust_anchor,
)

ANCRE_REPETITION = RACINE / "governance/trust-anchors/rehearsal-readiness-v1.json"
ANCRE_PRODUCTION = RACINE / "governance/trust-anchors/production-readiness-v1.json"

KEY_ID = "nexus-rehearsal-readiness-20260920-01"

#: La chaîne de production, épinglée par le lot CQ. Reprise ici pour que
#: l'ajout d'une ancre de répétition prouve, lui aussi, n'avoir rien déplacé.
CHAINE_DE_PRODUCTION_INTACTE = {
    "services/rag-engine/src/ingestor/ingestion_profiles/readiness_gate.py":
        "a22d4dc2b4436df5f5501dc865ed48aade54e4f6056ed32839814128188f3a28",
    "packages/contracts/src/nexus_contracts/production_readiness.py":
        "2e3398903b9a46fca1cbc7dfd923bb67cdb25e44b249ed2915ec3635ad430245",
    "governance/trust-anchors/production-readiness-v1.json":
        "f123e9f35a9430d02092df675e5ed657fbccf8fb10af90fe03416335e7d1d238",
}


@pytest.fixture()
def brut() -> bytes:
    return ANCRE_REPETITION.read_bytes()


@pytest.fixture()
def document(brut: bytes) -> dict:
    return json.loads(brut.decode("utf-8"))


# --------------------------------------------------------------------------
# L'ancre est valide et nomme la clé attendue
# --------------------------------------------------------------------------


def test_l_ancre_se_valide_contre_son_propre_contrat(brut: bytes) -> None:
    ancre = parse_staging_readiness_trust_anchor(brut)
    assert ancre.protocol_version == "NEXUS-STAGING-READINESS-V1"
    assert len(ancre.keys) == 1


def test_l_ancre_nomme_exactement_la_cle_de_la_ceremonie(brut: bytes) -> None:
    cle = parse_staging_readiness_trust_anchor(brut).key(KEY_ID)
    assert cle.algorithm == "ed25519"
    assert cle.environment == "rehearsal"


def test_la_cle_publique_est_un_point_ed25519_reel(document: dict) -> None:
    """Soixante-quatre hex ne font pas une clé : celle-ci doit se charger."""
    publique = document["keys"][0]["public_key"]
    assert re.fullmatch(r"[0-9a-f]{64}", publique)
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(publique))


def test_une_cle_inconnue_nest_pas_resolue(brut: bytes) -> None:
    ancre = parse_staging_readiness_trust_anchor(brut)
    with pytest.raises(StagingReadinessError, match="not declared"):
        ancre.key("nexus-rehearsal-readiness-20260920-02")


# --------------------------------------------------------------------------
# Rien que la clé publique
# --------------------------------------------------------------------------


CHAMPS_ATTENDUS = {"key_id", "algorithm", "public_key", "environment", "comment"}


def test_l_ancre_ne_porte_aucun_champ_au_dela_des_cinq_attendus(
    document: dict,
) -> None:
    assert set(document) == {"protocol_version", "keys"}
    assert set(document["keys"][0]) == CHAMPS_ATTENDUS


def test_aucun_secret_ni_cle_privee_dans_l_ancre(brut: bytes) -> None:
    texte = brut.decode("utf-8").lower()
    for motif in (
        "private", "secret", "seed", "graine", "password", "token",
        "-----begin", "ssh-rsa",
    ):
        assert motif not in texte, motif


def test_un_seul_bloc_de_64_hex_et_cest_la_cle_publique(
    brut: bytes, document: dict
) -> None:
    """Une graine aurait exactement la même forme : on compte les occurrences."""
    trouves = re.findall(r"\b[0-9a-f]{64}\b", brut.decode("utf-8"))
    assert trouves == [document["keys"][0]["public_key"]]


def test_l_ancre_ne_contient_aucun_placeholder(document: dict) -> None:
    publique = document["keys"][0]["public_key"]
    assert publique != "0" * 64
    assert publique != "f" * 64
    assert len(set(publique)) > 4, "une clé réelle n'est pas une répétition"
    texte = json.dumps(document).lower()
    for motif in ("todo", "fixme", "placeholder", "xxxx", "a_remplir", "tbd"):
        assert motif not in texte, motif


def test_aucun_manifeste_signe_naccompagne_l_ancre() -> None:
    """L'ancre n'autorise rien par elle-même : sans manifeste, le gate refuse."""
    dossier = ANCRE_REPETITION.parent
    for chemin in dossier.iterdir():
        contenu = chemin.read_text(encoding="utf-8")
        assert "signature" not in contenu, chemin
        assert "manifest_digest" not in contenu, chemin


# --------------------------------------------------------------------------
# Distincte de la production — dans les deux sens
# --------------------------------------------------------------------------


def test_l_ancre_de_repetition_nest_pas_acceptee_comme_ancre_de_production(
    brut: bytes,
) -> None:
    with pytest.raises(ProductionReadinessError):
        parse_production_readiness_trust_anchor(brut)


def test_l_ancre_de_production_nest_pas_acceptee_comme_ancre_de_repetition() -> None:
    with pytest.raises(StagingReadinessError):
        parse_staging_readiness_trust_anchor(ANCRE_PRODUCTION.read_bytes())


def test_les_deux_ancres_ne_partagent_aucune_cle(document: dict) -> None:
    production = json.loads(ANCRE_PRODUCTION.read_text(encoding="utf-8"))
    publiques_prod = {cle["public_key"] for cle in production["keys"]}
    identifiants_prod = {cle["key_id"] for cle in production["keys"]}
    for cle in document["keys"]:
        assert cle["public_key"] not in publiques_prod
        assert cle["key_id"] not in identifiants_prod


def test_les_deux_ancres_declarent_des_protocoles_distincts(document: dict) -> None:
    production = json.loads(ANCRE_PRODUCTION.read_text(encoding="utf-8"))
    assert document["protocol_version"] == "NEXUS-STAGING-READINESS-V1"
    assert production["protocol_version"] == "NEXUS-PRODUCTION-READINESS-V1"
    assert document["protocol_version"] != production["protocol_version"]


def test_aucune_cle_de_repetition_ne_declare_production(document: dict) -> None:
    assert all(cle["environment"] == "rehearsal" for cle in document["keys"])


def test_le_nom_de_fichier_differe_de_celui_de_l_ancre_gouvernee() -> None:
    """Le gate refuse un chemin dont le nom est celui de l'ancre de production."""
    assert ANCRE_REPETITION.name != ANCRE_PRODUCTION.name
    assert ANCRE_REPETITION.name == "rehearsal-readiness-v1.json"


# --------------------------------------------------------------------------
# La chaîne de production reste intacte
# --------------------------------------------------------------------------


@pytest.mark.parametrize("chemin", sorted(CHAINE_DE_PRODUCTION_INTACTE))
def test_la_chaine_de_production_est_intacte_a_l_octet_pres(chemin: str) -> None:
    attendu = CHAINE_DE_PRODUCTION_INTACTE[chemin]
    observe = hashlib.sha256((RACINE / chemin).read_bytes()).hexdigest()
    assert observe == attendu, (
        f"{chemin} a changé : ajouter une ancre de répétition ne déplace rien "
        "de la chaîne de production."
    )


def test_l_ancre_de_production_porte_toujours_sa_seule_cle_offline() -> None:
    production = json.loads(ANCRE_PRODUCTION.read_text(encoding="utf-8"))
    assert len(production["keys"]) == 1
    assert production["keys"][0]["environment"] == "production"
    assert "offline" in production["keys"][0]["comment"].lower()


# --------------------------------------------------------------------------
# L'ancre seule n'autorise rien
# --------------------------------------------------------------------------
#
# La preuve — donner cette ancre au gate SANS manifeste et constater son refus
# — vit dans ``services/rag-engine/tests/test_staging_readiness_gate.py``,
# pas ici : elle importe le gate, donc ``psycopg``, que ce job de
# qualification n'installe pas. La deplacer est la seule reponse juste ; la
# marquer ``skip`` ici l'aurait rendue muette sans rien prouver ailleurs.
