"""Ce que le niveau de preuve d'une applicabilité refuse de confondre.

Le défaut visé : fondre « le canal commanditaire a vérifié le texte officiel »
et « cette session sait re-télécharger les octets ». Un serveur qui rend 403 à
un agent non navigateur ne rend pas le fait moins vrai, et un téléchargement
réussi ne vérifie rien à lui seul.
"""

from __future__ import annotations

import dataclasses

import pytest

from rag_pedago.governance import applicabilite_programme as ap


def technologie(**remplacements) -> ap.ApplicabiliteProgramme:
    champs = {
        "scope_id": "cinquieme/technologie",
        "niveau": "cinquieme",
        "matiere": "technologie",
        "modality": None,
        "school_year": "2026-2027",
        "official_reference": "BOEN_9_2024-02-29",
        "nor": "MENE2402802A",
        "official_reference_kind": "PROGRAM_MODIFICATION",
        "effective_from": "2024-2025",
        "official_source_identifier": "BOEN n°9 du 29 février 2024",
        "verified_at": "2026-09-08",
        "evidence_receipt_sha256": ap.receipt_sha256("BOEN_9_2024-02-29", "MENE2402802A"),
        "evidence_status": ap.VERIFIE_OFFICIEL,
    }
    champs.update(remplacements)
    return ap.ApplicabiliteProgramme(**champs)


# --- la séparation des deux propriétés --------------------------------------


def test_un_fait_verifie_le_reste_quand_le_reseau_refuse():
    # 110 refus 403 mesurés sur 111 URL institutionnelles. Si le réseau
    # rétrogradait le fait, aucune applicabilité ne serait jamais opposable.
    fait = technologie(local_official_evidence_reproducible=False)
    assert fait.evidence_status == ap.VERIFIE_OFFICIEL
    assert fait.opposable is True


def test_la_reproductibilite_locale_ne_verifie_rien_a_elle_seule():
    declare = technologie(
        evidence_status=ap.DECLARE,
        local_official_evidence_reproducible=True,
        official_snapshot_sha256="0" * 64,
    )
    assert declare.opposable is False


def test_un_instantane_sans_reproductibilite_est_refuse():
    # Une empreinte d'instantané officiel sans fetch reproductible serait une
    # preuve sans provenance : personne ne pourrait dire d'où viennent ces
    # octets.
    with pytest.raises(ValueError, match="provenance"):
        technologie(official_snapshot_sha256="0" * 64,
                    local_official_evidence_reproducible=False)


# --- « vérifié » exige de nommer ce qui est vérifié --------------------------


@pytest.mark.parametrize("champ", ap.CHAMPS_REQUIS_POUR_VERIFIE)
def test_verifie_sans_l_un_des_champs_requis_est_refuse(champ):
    with pytest.raises(ValueError, match=champ):
        technologie(**{champ: None})


def test_un_statut_hors_enum_est_refuse():
    with pytest.raises(ValueError, match="enum fermée"):
        technologie(evidence_status="PROBABLEMENT_VRAI")


def test_seul_le_statut_verifie_est_opposable():
    for statut in ap.STATUTS_PREUVE:
        if statut == ap.VERIFIE_OFFICIEL:
            continue
        fait = dataclasses.replace(technologie(), evidence_status=statut)
        assert fait.opposable is False, statut


# --- LCA : jamais un seul scope ---------------------------------------------


def test_les_trois_familles_lca_ne_se_confondent_jamais():
    college = ap.resoudre_scope_lca("cinquieme", "ENSEIGNEMENT_COMPLEMENT_LCA")
    option = ap.resoudre_scope_lca("terminale", "LCA_OPTION")
    specialite = ap.resoudre_scope_lca("terminale", "LLCA_SPECIALITE")
    assert college == ap.LCA_CYCLE4_COMPLEMENT
    assert option == ap.LCA_GT_OPTION_TERMINALE
    assert specialite == ap.LLCA_SPECIALITE_TERMINALE
    assert len({college, option, specialite}) == 3


def test_l_option_lycee_depend_du_niveau():
    assert ap.resoudre_scope_lca("seconde", "LCA_OPTION") == ap.LCA_GT_OPTION_SECONDE
    assert ap.resoudre_scope_lca("premiere", "LCA_OPTION") == ap.LCA_GT_OPTION_PREMIERE
    assert ap.resoudre_scope_lca("terminale", "LCA_OPTION") == ap.LCA_GT_OPTION_TERMINALE


def test_une_matiere_lca_sans_modalite_ne_resout_rien():
    # Le défaut visé : appliquer BOEN_11_2016-03-17 à tout ce qui porte
    # « lca ». La nouvelle autorité résout des scopes précis ; elle ne
    # transforme pas des métadonnées pauvres en preuve.
    assert ap.resoudre_scope_lca(None, None) == ap.LCA_MODALITE_INCONNUE
    assert ap.resoudre_scope_lca("cinquieme", None) == ap.LCA_MODALITE_INCONNUE
    assert ap.resoudre_scope_lca(None, "LCA_OPTION") == ap.LCA_MODALITE_INCONNUE


def test_une_combinaison_inexistante_ne_resout_rien():
    # La spécialité LLCA n'existe pas en seconde.
    assert ap.resoudre_scope_lca("seconde", "LLCA_SPECIALITE") == ap.LCA_MODALITE_INCONNUE
    assert ap.resoudre_scope_lca("cinquieme", "LCA_OPTION") == ap.LCA_MODALITE_INCONNUE


# --- le reçu scelle le contenu ----------------------------------------------


def test_le_recu_change_avec_ce_qui_est_rapporte():
    a = ap.receipt_sha256("BOEN_9_2024-02-29", "MENE2402802A")
    b = ap.receipt_sha256("BOEN_9_2024-02-29", "MENE2402802B")
    assert a != b
    assert a == ap.receipt_sha256("BOEN_9_2024-02-29", "MENE2402802A")


def test_deux_applicabilites_pour_un_scope_ne_resolvent_pas():
    doublon = [technologie(), technologie(official_reference="BOEN_31_2020-07-30")]
    assert ap.autorite_applicable("cinquieme/technologie", doublon) is None
    assert ap.autorite_applicable("cinquieme/technologie", doublon[:1]) is not None
