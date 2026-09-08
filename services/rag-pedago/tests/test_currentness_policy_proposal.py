"""La matrice de servabilité, éprouvée sur fixtures — jamais appliquée.

Ce que ces épreuves protègent : la distinction entre PREUVE et POLITIQUE.

Une politique peut légitimement autoriser à servir un instantané
institutionnel dont l'URL n'est plus vérifiable. Elle ne peut jamais dire
qu'il est `VERIFIED_CURRENT` : ce serait falsifier le niveau de preuve, et un
lecteur ne pourrait plus distinguer un document dont les octets ont été
confrontés d'un document qu'une règle a laissé passer.

Aucun contenu réel n'entre ici. La politique reste `applied: false`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

POLITIQUE = (
    Path(__file__).resolve().parents[1]
    / "configs/proposals/nexus_rag_currentness_policy_v1.yml"
)

VERIFIED = "VERIFIED_CURRENT"
SNAPSHOT = "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE"
ARCHIVE_DECLARE = "NOT_CURRENT_DECLARED_BY_SOURCE"


@pytest.fixture(scope="module")
def politique() -> dict:
    return yaml.safe_load(POLITIQUE.read_text(encoding="utf-8"))


def decider(cas: dict, politique: dict) -> tuple[str, str]:
    """Applique la règle proposée à UN cas. Rend (servabilité, actualité).

    Implémentation d'épreuve : elle vit ici, pas dans le plan de contrôle,
    parce que la politique n'est pas adoptée. La coder dans le producteur
    reviendrait à l'appliquer."""
    if cas.get("pii_gate") in ("NOT_ASSESSABLE", "REJECTED"):
        return "BLOCKED", "UNKNOWN"
    if cas.get("source_status") == "ARCHIVE":
        return "BLOCKED", ARCHIVE_DECLARE
    if cas.get("content_identity_match") is True:
        return "CANDIDATE", VERIFIED
    exigences = politique["fallback_rule"]["conditions_all_required"]
    satisfaites = {
        "OFFICIAL_INSTITUTIONAL_PROVENANCE": cas.get("official_provenance") is True,
        "CONTENT_SHA_PROVENANCE_MATCH": cas.get("sha_provenance_match") is True,
        "SOURCE_STATUS_NOT_EXPLICIT_ARCHIVE": cas.get("source_status") != "ARCHIVE",
        "PROGRAM_VERSION_COMPATIBLE": cas.get("program") == "COMPATIBLE",
        "PII_GATE_PASS": cas.get("pii_gate") == "PASS",
        "RIGHTS_GATE_PASS": cas.get("rights_gate", "PASS") == "PASS",
        "CLASSIFICATION_GATE_PASS": cas.get("classification_gate", "PASS") == "PASS",
        "PLACEMENT_GATE_PASS": cas.get("placement_gate", "PASS") == "PASS",
        "NO_KNOWN_SUPERSEDING_CONFLICT": not cas.get("superseding_conflict", False),
    }
    if all(satisfaites[nom] for nom in exigences):
        return "CANDIDATE", SNAPSHOT
    if cas.get("program") == "UNKNOWN":
        return "GOVERNED_NOT_SERVABLE_REVIEW_REQUIRED", "UNKNOWN"
    return "BLOCKED", "UNKNOWN"


def _cas(**surcharges) -> dict:
    base = {
        "official_provenance": True,
        "sha_provenance_match": True,
        "source_status": "CURRENT_DECLARED_BY_CATALOGUE",
        "program": "COMPATIBLE",
        "pii_gate": "PASS",
        "content_identity_match": None,
    }
    base.update(surcharges)
    return base


# --- la matrice imposée -----------------------------------------------


def test_officiel_actuel_reseau_invérifiable_est_candidat(politique) -> None:
    """Le cas central : l'absence de preuve réseau n'est pas une preuve
    d'obsolescence."""
    servabilite, actualite = decider(_cas(), politique)
    assert servabilite == "CANDIDATE"
    assert actualite == SNAPSHOT


def test_le_repli_ne_produit_jamais_verified_current(politique) -> None:
    """LE garde-fou du lot. Autoriser à servir n'est pas prouver l'actualité."""
    _servabilite, actualite = decider(_cas(), politique)
    assert actualite != VERIFIED
    assert politique["currentness_dispositions"][SNAPSHOT][
        "never_equivalent_to"
    ] == VERIFIED


def test_une_archive_est_bloquee_malgre_le_repli(politique) -> None:
    """Ne pas pouvoir vérifier une URL n'annule pas une déclaration positive
    d'archivage."""
    servabilite, actualite = decider(_cas(source_status="ARCHIVE"), politique)
    assert servabilite == "BLOCKED"
    assert actualite == ARCHIVE_DECLARE


def test_a_verifier_avec_programme_compatible_est_candidat(politique) -> None:
    servabilite, _ = decider(
        _cas(source_status="NEEDS_SECONDARY_EVIDENCE", program="COMPATIBLE"), politique
    )
    assert servabilite == "CANDIDATE"


def test_a_verifier_avec_programme_incompatible_est_bloque(politique) -> None:
    servabilite, _ = decider(
        _cas(source_status="NEEDS_SECONDARY_EVIDENCE", program="INCOMPATIBLE"), politique
    )
    assert servabilite == "BLOCKED"


def test_a_verifier_avec_programme_inconnu_exige_une_revue(politique) -> None:
    """C'est l'état RÉEL de 2451 contenus aujourd'hui : ni servable, ni exclu."""
    servabilite, _ = decider(
        _cas(source_status="NEEDS_SECONDARY_EVIDENCE", program="UNKNOWN"), politique
    )
    assert servabilite == "GOVERNED_NOT_SERVABLE_REVIEW_REQUIRED"


@pytest.mark.parametrize("etat", ["NOT_ASSESSABLE", "REJECTED"])
def test_la_pii_bloque_quelle_que_soit_l_actualite(politique, etat) -> None:
    """Aucune actualité ne rachète une PII non évaluable ou rejetée."""
    servabilite, _ = decider(
        _cas(pii_gate=etat, content_identity_match=True), politique
    )
    assert servabilite == "BLOCKED"


def test_une_identite_d_octets_donne_la_seule_actualite_verifiee(politique) -> None:
    _servabilite, actualite = decider(_cas(content_identity_match=True), politique)
    assert actualite == VERIFIED


# --- ce que la politique refuse de faire -------------------------------


def test_chaque_condition_du_repli_est_bloquante(politique) -> None:
    """Une seule condition fausse suffit. Sans cela, la liste serait décorative."""
    for condition, surcharge in (
        ("OFFICIAL_INSTITUTIONAL_PROVENANCE", {"official_provenance": False}),
        ("CONTENT_SHA_PROVENANCE_MATCH", {"sha_provenance_match": False}),
        ("RIGHTS_GATE_PASS", {"rights_gate": "FAIL"}),
        ("CLASSIFICATION_GATE_PASS", {"classification_gate": "FAIL"}),
        ("PLACEMENT_GATE_PASS", {"placement_gate": "FAIL"}),
        ("NO_KNOWN_SUPERSEDING_CONFLICT", {"superseding_conflict": True}),
    ):
        servabilite, actualite = decider(_cas(**surcharge), politique)
        assert servabilite != "CANDIDATE", f"{condition} n'est pas bloquante"
        assert actualite != SNAPSHOT


def test_la_politique_reste_une_proposition(politique) -> None:
    """Elle ne doit pas pouvoir être appliquée par inadvertance."""
    assert politique["status"] == "PROPOSED"
    assert politique["applied"] is False
    assert politique["requires_adr"] is True


def test_les_cinq_dimensions_restent_separees(politique) -> None:
    """Les fondre ferait d'un 200 une preuve d'actualité pédagogique."""
    assert set(politique["dimensions"]) == {
        "PROVENANCE", "SOURCE_STATUS", "NETWORK_CURRENTNESS",
        "PROGRAM_VERSION", "SERVABILITY",
    }
    assert politique["dimensions"]["NETWORK_CURRENTNESS"]["current_state"] == "UNVERIFIABLE"
    assert politique["dimensions"]["SERVABILITY"]["current_state"] == "NOT_DECIDED"
