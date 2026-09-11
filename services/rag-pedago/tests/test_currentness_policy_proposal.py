"""La politique d'actualité, éprouvée sur fixtures — jamais appliquée.

Ce que ces épreuves protègent : la distinction entre PREUVE et POLITIQUE, et
la séparation des autorités.

Une politique peut légitimement autoriser à servir un instantané
institutionnel dont l'URL n'est plus vérifiable. Elle ne peut jamais dire
qu'il est `VERIFIED_CURRENT` : ce serait falsifier le niveau de preuve, et un
lecteur ne pourrait plus distinguer un document dont les octets ont été
confrontés d'un document qu'une règle a laissé passer.

Elle ne peut pas non plus décider à la place du gate programme, du gate PII,
des droits, de la classification ni du placement. Une version antérieure le
faisait, et contredisait ADR-0051.

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
INCONNU = "UNKNOWN"

#: Décisions appartenant à d'autres autorités. La politique d'actualité ne
#: doit en porter aucune.
GATES_ETRANGERS = (
    "PROGRAM_VERSION_COMPATIBLE",
    "PII_GATE_PASS",
    "RIGHTS_GATE_PASS",
    "CLASSIFICATION_GATE_PASS",
    "PLACEMENT_GATE_PASS",
)


@pytest.fixture(scope="module")
def politique() -> dict:
    return yaml.safe_load(POLITIQUE.read_text(encoding="utf-8"))


# --- ce que la politique produit : UNE dimension, rien d'autre ---------


def disposition_actualite(cas: dict, politique: dict) -> str:
    """Rend la SEULE sortie de la politique : une disposition d'actualité.

    Implémentation d'épreuve : elle vit ici, pas dans le plan de contrôle,
    parce que la politique n'est pas adoptée. La coder dans le producteur
    reviendrait à l'appliquer.
    """
    if cas.get("source_status") == "ARCHIVE":
        return ARCHIVE_DECLARE
    if cas.get("content_identity_match") is True:
        return VERIFIED
    exigences = politique["fallback_rule"]["conditions_all_required"]
    satisfaites = {
        "OFFICIAL_INSTITUTIONAL_PROVENANCE": cas.get("official_provenance") is True,
        "CONTENT_SHA_PROVENANCE_MATCH": cas.get("sha_provenance_match") is True,
        "SOURCE_STATUS_NOT_EXPLICIT_ARCHIVE": cas.get("source_status") != "ARCHIVE",
        "NO_KNOWN_SUPERSEDING_CONFLICT": not cas.get("superseding_conflict", False),
    }
    manquantes = [nom for nom in exigences if nom not in satisfaites]
    assert not manquantes, (
        "la règle de repli exige une condition que la politique d'actualité ne "
        f"sait pas évaluer : {manquantes}. Elle appartient à une autre autorité."
    )
    if all(satisfaites[nom] for nom in exigences):
        return politique["fallback_rule"]["disposition"]
    return INCONNU


# --- ce que le GATE compose : la politique n'y participe qu'en entrée --


def servabilite(cas: dict, actualite: str) -> str:
    """Compose les autorités. Ce code n'appartient PAS à la politique.

    Il est ici pour éprouver la composition, et pour rendre visible que
    chaque refus vient d'une autorité nommée.
    """
    if cas.get("pii_gate") in ("NOT_ASSESSABLE", "REJECTED"):
        return "BLOCKED"                      # PII_GATE
    if actualite == ARCHIVE_DECLARE:
        return "BLOCKED"                      # CURRENTNESS_GATE
    if cas.get("program") == "INCOMPATIBLE":
        return "BLOCKED"                      # PROGRAM_GATE
    for gate in ("rights_gate", "classification_gate", "placement_gate"):
        if cas.get(gate, "PASS") != "PASS":
            return "BLOCKED"
    if actualite == INCONNU:
        return "BLOCKED"                      # CURRENTNESS_GATE
    # ADR-0051 : un programme inconnu ne bloque pas.
    return "CANDIDATE"


def decider(cas: dict, politique: dict) -> tuple[str, str]:
    actualite = disposition_actualite(cas, politique)
    return servabilite(cas, actualite), actualite


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


def test_officiel_actuel_reseau_inverifiable_est_candidat(politique) -> None:
    """Le cas central : l'absence de preuve réseau n'est pas une preuve
    d'obsolescence."""
    servable, actualite = decider(_cas(), politique)
    assert servable == "CANDIDATE"
    assert actualite == SNAPSHOT


def test_le_repli_ne_produit_jamais_verified_current(politique) -> None:
    """LE garde-fou du lot. Autoriser à servir n'est pas prouver l'actualité."""
    _servable, actualite = decider(_cas(), politique)
    assert actualite != VERIFIED
    assert politique["currentness_dispositions"][SNAPSHOT][
        "never_equivalent_to"
    ] == VERIFIED


def test_une_archive_est_bloquee_malgre_le_repli(politique) -> None:
    """Ne pas pouvoir vérifier une URL n'annule pas une déclaration positive
    d'archivage."""
    servable, actualite = decider(_cas(source_status="ARCHIVE"), politique)
    assert servable == "BLOCKED"
    assert actualite == ARCHIVE_DECLARE


def test_un_403_n_est_pas_une_preuve_d_obsolescence(politique) -> None:
    """Un refus réseau laisse l'actualité indécidée, il ne la nie pas."""
    _servable, actualite = decider(_cas(network_response=403), politique)
    assert actualite == SNAPSHOT
    assert actualite != ARCHIVE_DECLARE


def test_une_identite_d_octets_donne_la_seule_actualite_verifiee(politique) -> None:
    _servable, actualite = decider(_cas(content_identity_match=True), politique)
    assert actualite == VERIFIED


# --- la séparation des autorités ---------------------------------------


def test_la_politique_ne_porte_aucune_condition_d_une_autre_autorite(politique) -> None:
    """Le défaut corrigé : cinq gates étrangers dans la règle de repli."""
    exigences = set(politique["fallback_rule"]["conditions_all_required"])
    intrus = sorted(exigences & set(GATES_ETRANGERS))
    assert intrus == [], (
        f"la politique d'actualité s'arroge {intrus}. Ces décisions "
        "appartiennent à d'autres autorités et sont composées par le gate."
    )


def test_chaque_condition_retiree_est_rendue_a_une_autorite_nommee(politique) -> None:
    """Retirer sans nommer le nouveau propriétaire perdrait la condition."""
    rendues = politique["fallback_rule"]["conditions_returned_to_their_authority"]
    assert set(rendues) == set(GATES_ETRANGERS)
    assert all(isinstance(v, str) and v.endswith("_GATE") for v in rendues.values())


def test_la_politique_declare_ne_rien_posseder_d_autre(politique) -> None:
    p = politique["ownership"]
    assert p["CURRENTNESS_POLICY_OWNS_CURRENTNESS_DISPOSITION"] is True
    for cle in (
        "CURRENTNESS_POLICY_OWNS_PROGRAM_DECISION",
        "CURRENTNESS_POLICY_OWNS_PII_DECISION",
        "CURRENTNESS_POLICY_OWNS_AUTHORIZATION_DECISION",
        "CURRENTNESS_POLICY_OWNS_RIGHTS_DECISION",
        "CURRENTNESS_POLICY_OWNS_CLASSIFICATION_DECISION",
        "CURRENTNESS_POLICY_OWNS_PLACEMENT_DECISION",
        "CURRENTNESS_POLICY_OWNS_SERVABILITY_VERDICT",
    ):
        assert p[cle] is False, f"{cle} doit rester false"
    assert p["output"] == "currentness_disposition"
    assert p["composed_by"] == "SERVABILITY_GATE"


def test_un_programme_inconnu_ne_bloque_plus_par_la_politique(politique) -> None:
    """La contradiction avec ADR-0051, éprouvée dans le sens qui compte.

    Avant, PROGRAM_VERSION_COMPATIBLE dans la règle de repli écartait 2520
    contenus sur 2530. ADR-0051 décide l'inverse.
    """
    servable, actualite = decider(_cas(program="UNKNOWN"), politique)
    assert actualite == SNAPSHOT
    assert servable == "CANDIDATE"


def test_un_programme_prouve_incompatible_bloque_toujours(politique) -> None:
    """Rendre la décision au gate programme ne l'affaiblit pas."""
    servable, _ = decider(_cas(program="INCOMPATIBLE"), politique)
    assert servable == "BLOCKED"


@pytest.mark.parametrize("etat", ["NOT_ASSESSABLE", "REJECTED"])
def test_la_pii_bloque_quelle_que_soit_l_actualite(politique, etat) -> None:
    """Aucune actualité ne rachète une PII non évaluable ou rejetée."""
    servable, _ = decider(_cas(pii_gate=etat, content_identity_match=True), politique)
    assert servable == "BLOCKED"


def test_chaque_condition_du_repli_est_bloquante(politique) -> None:
    """Une seule condition fausse suffit. Sans cela, la liste serait décorative."""
    for condition, surcharge in (
        ("OFFICIAL_INSTITUTIONAL_PROVENANCE", {"official_provenance": False}),
        ("CONTENT_SHA_PROVENANCE_MATCH", {"sha_provenance_match": False}),
        ("NO_KNOWN_SUPERSEDING_CONFLICT", {"superseding_conflict": True}),
    ):
        servable, actualite = decider(_cas(**surcharge), politique)
        assert actualite != SNAPSHOT, f"{condition} n'est pas bloquante"
        assert servable != "CANDIDATE"


def test_les_gates_etrangers_bloquent_toujours_mais_ailleurs(politique) -> None:
    """Rendus au gate, ils gardent leur effet. Rien n'est perdu au change."""
    for surcharge in (
        {"rights_gate": "FAIL"},
        {"classification_gate": "FAIL"},
        {"placement_gate": "FAIL"},
    ):
        servable, actualite = decider(_cas(**surcharge), politique)
        assert servable == "BLOCKED", surcharge
        # L'actualité, elle, reste ce qu'elle est : le refus vient d'ailleurs.
        assert actualite == SNAPSHOT


def test_la_politique_est_appliquee_et_consommee(politique) -> None:
    """Elle est appliquée — et le drapeau ne peut pas mentir.

    Ce test figeait `applied is False` : il protégeait contre une bascule par
    inadvertance, à une époque où rien ne consommait la politique. Un drapeau
    seul aurait alors fait baisser un compteur sans qu'aucun comportement ne
    change.

    Ce n'est plus le cas. Le constructeur de la matrice CHARGE la politique et
    REFUSE de se construire si elle ne s'applique pas : le drapeau et le
    comportement ne peuvent plus diverger. Ce qui est protégé ici n'est donc
    plus la valeur du drapeau, mais l'existence de ses consommateurs.
    """
    assert politique["status"] == "ACCEPTED"
    assert politique["applied"] is True
    assert politique["requires_adr"] is True
    assert politique["applied_by_adr"] == "ADR-0055"

    consommateurs = politique["consumed_by"]
    assert consommateurs, "appliquée sans consommateur : le drapeau mentirait"
    racine = POLITIQUE.resolve().parents[4]
    for relatif in consommateurs:
        assert (racine / relatif).is_file(), f"consommateur déclaré absent : {relatif}"


def test_les_cinq_dimensions_restent_separees(politique) -> None:
    """Les fondre ferait d'un 200 une preuve d'actualité pédagogique."""
    assert set(politique["dimensions"]) == {
        "PROVENANCE", "SOURCE_STATUS", "NETWORK_CURRENTNESS",
        "PROGRAM_VERSION", "SERVABILITY",
    }
    assert politique["dimensions"]["NETWORK_CURRENTNESS"]["current_state"] == "UNVERIFIABLE"
    assert politique["dimensions"]["SERVABILITY"]["current_state"] == "NOT_DECIDED"
    assert politique["dimensions"]["SERVABILITY"]["proven_by"].startswith(
        "le gate de servabilité"
    )
    assert politique["dimensions"]["PROGRAM_VERSION"]["decided_elsewhere"] == "PROGRAM_GATE"


def test_aucun_statut_de_source_ne_rend_un_verdict_de_servabilite(politique) -> None:
    """`servable: false` dans la table des statuts était un verdict, pas une
    dimension."""
    for statut, entree in politique["source_status_mapping"].items():
        assert "servable" not in entree, (
            f"le statut {statut} rend encore un verdict de servabilité"
        )
        assert entree["currentness_disposition"] in politique["currentness_dispositions"]
