"""Ce que l'attribution de scope refuse de deviner.

Le défaut d'origine : 148 liaisons trouvées, 10 conservées. Les 138 autres
venaient d'un document qui CITE un programme sans relever de ce programme —
« citer un programme n'est pas relever de ce programme ». Ce module attribue
donc une citation à la SECTION où elle se trouve, et à rien d'autre.
"""

from __future__ import annotations

from rag_pedago.governance import attribution_citation as ac


def unite(texte: str, rang: int = 0, **kw) -> ac.UniteTexte:
    return ac.UniteTexte(identifiant=f"chunk-{rang}", rang=rang, texte=texte, **kw)


BO1 = "Bulletin officiel spécial n° 1 du 22 janvier 2019"
REF1 = "BOEN_special_1_2019-01-22"
BO8 = "BO spécial n° 8 du 25 juillet 2019"
REF8 = "BOEN_special_8_2019-07-25"


# --- l'enum est fermée ------------------------------------------------------


def test_les_bases_interdites_ne_sont_pas_des_bases_autorisees():
    assert not set(ac.BASES_INTERDITES) & set(ac.BASES_AUTORISEES)
    for interdite in ("SEMANTIC_SIMILARITY", "NEARBY_WORDS", "FILENAME_GUESS",
                      "FOLDER_GUESS", "MODEL_INFERENCE"):
        assert interdite in ac.BASES_INTERDITES


# --- ce qui est un intitulé, et ce qui n'en est pas -------------------------


def test_un_intitule_de_section_attribue():
    texte = f"Classe de première\n\nLe programme est défini par le {BO1}.\n"
    (occurrence,) = ac.attribuer_document("sha", [unite(texte)], [REF1])
    assert occurrence.disposition == ac.ATTRIBUE
    assert occurrence.attributed_scope_levels == ["premiere"]
    assert occurrence.attribution_basis == ac.BASE_SECTION
    assert occurrence.heading_text_normalized == "classe_de_premiere"


def test_une_mention_dans_une_phrase_n_attribue_rien():
    # Le défaut visé : `NEARBY_WORDS`. « en première » au fil d'une phrase
    # n'est pas une délimitation de section.
    texte = f"En première, les élèves rencontrent cette notion ; voir le {BO1}.\n"
    (occurrence,) = ac.attribuer_document("sha", [unite(texte)], [REF1])
    assert occurrence.disposition == ac.NON_ATTRIBUABLE
    assert occurrence.attributed_scope_levels == []
    assert occurrence.attribution_basis is None


def test_le_qualificatif_dun_intitule_ne_delimite_pas():
    # « Classe de terminale : rappels de première » délimite une section de
    # TERMINALE. Lire « première » dans le qualificatif attribuerait la section
    # au mauvais niveau.
    texte = f"Classe de terminale : rappels de première\n\nVoir le {BO1}.\n"
    (occurrence,) = ac.attribuer_document("sha", [unite(texte)], [REF1])
    assert occurrence.attributed_scope_levels == ["terminale"]


def test_un_intitule_sans_niveau_ne_coupe_pas_la_section_precedente():
    texte = (
        "Classe de seconde\n\nIntroduction\n\nDémarche générale\n\n"
        f"Le texte de référence est le {BO1}.\n"
    )
    (occurrence,) = ac.attribuer_document("sha", [unite(texte)], [REF1])
    assert occurrence.disposition == ac.ATTRIBUE
    assert occurrence.attributed_scope_levels == ["seconde"]


# --- la portée d'une section traverse les unités de texte -------------------


def test_une_section_reste_ouverte_dans_le_chunk_suivant():
    # Le défaut visé : un chunk est un découpage technique. Sans héritage, une
    # citation tombant dans un chunk sans intitulé perdrait l'attribution que
    # la structure du document porte pourtant.
    unites = [
        unite("Classe de terminale\n\nPremière partie du cours.\n", rang=0),
        unite(f"Suite du cours, qui s'appuie sur le {BO1}.\n", rang=1),
    ]
    (occurrence,) = ac.attribuer_document("sha", unites, [REF1])
    assert occurrence.disposition == ac.ATTRIBUE
    assert occurrence.attributed_scope_levels == ["terminale"]
    assert occurrence.section_unit == "chunk-0"


def test_le_dernier_intitule_avant_la_citation_l_emporte():
    texte = (
        "Classe de seconde\n\nContenu de seconde.\n\n"
        f"Classe de terminale\n\nContenu de terminale, voir le {BO1}.\n"
    )
    (occurrence,) = ac.attribuer_document("sha", [unite(texte)], [REF1])
    assert occurrence.attributed_scope_levels == ["terminale"]


# --- multi-scope ------------------------------------------------------------


def test_un_intitule_qui_nomme_deux_niveaux_est_multi_scope():
    texte = f"Classe de première et terminale\n\nRéférence : {BO1}.\n"
    (occurrence,) = ac.attribuer_document("sha", [unite(texte)], [REF1])
    assert occurrence.disposition == ac.MULTI_SCOPE
    assert occurrence.attributed_scope_levels == ["premiere", "terminale"]
    assert occurrence.attribution_basis == ac.BASE_MULTI


def test_la_meme_reference_citee_dans_deux_sections_est_multi_scope():
    # Ce n'est PAS un conflit : le document sert les deux niveaux, et les deux
    # preuves sont vraies. Les déclarer contradictoires perdrait l'information.
    texte = (
        f"Classe de première\n\nÉvaluation portant sur le {BO1}.\n\n"
        f"Classe de terminale\n\nÉvaluation portant sur le {BO1}.\n"
    )
    (occurrence,) = ac.attribuer_document("sha", [unite(texte)], [REF1])
    assert occurrence.disposition == ac.MULTI_SCOPE
    assert occurrence.attributed_scope_levels == ["premiere", "terminale"]


# --- conflit : deux mécanismes INDÉPENDANTS qui se contredisent -------------


def test_un_manifeste_qui_contredit_l_intitule_est_un_conflit():
    texte = f"Classe de seconde\n\nRéférence : {BO1}.\n"
    unites = [unite(texte, page=4)]
    plages = [ac.PlageManifeste(page_debut=1, page_fin=10, niveaux=("terminale",))]
    (occurrence,) = ac.attribuer_document("sha", unites, [REF1], plages)
    assert occurrence.disposition == ac.CONFLIT
    assert occurrence.conflict_bases == sorted([ac.BASE_MANIFESTE, ac.BASE_SECTION])
    # Un conflit ne publie AUCUN scope : deux preuves contradictoires n'en
    # font pas une.
    assert occurrence.attributed_scope_levels == []
    assert occurrence.attribution_basis is None


def test_un_manifeste_qui_confirme_l_intitule_n_est_pas_un_conflit():
    texte = f"Classe de seconde\n\nRéférence : {BO1}.\n"
    unites = [unite(texte, page=4)]
    plages = [ac.PlageManifeste(page_debut=1, page_fin=10, niveaux=("seconde",))]
    (occurrence,) = ac.attribuer_document("sha", unites, [REF1], plages)
    assert occurrence.disposition == ac.ATTRIBUE
    assert occurrence.attributed_scope_levels == ["seconde"]


# --- ce que la sortie ne contient jamais ------------------------------------


def test_aucun_contexte_brut_n_est_publie():
    secret = "Élève Dupont, 3 rue des Lilas"
    texte = f"Classe de première\n\n{secret}\n\nRéférence : {BO1}.\n"
    (occurrence,) = ac.attribuer_document("sha", [unite(texte)], [REF1])
    publie = repr(occurrence.__dict__) + occurrence.reference_occurrence_id
    assert secret not in publie
    assert "Dupont" not in publie
    assert "Lilas" not in publie


def test_l_identifiant_doccurrence_est_stable_et_derive_du_contrat():
    a, = ac.attribuer_document("sha", [unite(f"Classe de première\n{BO1}")], [REF1])
    b, = ac.attribuer_document("sha", [unite(f"Classe de terminale\n{BO1}")], [REF1])
    assert a.reference_occurrence_id == b.reference_occurrence_id
    assert ac.CONTRACT_ID not in a.reference_occurrence_id


# --- plusieurs références dans le même document -----------------------------


def test_deux_references_sont_attribuees_separement():
    texte = (
        f"Classe de première\n\nProgramme : {BO1}.\n\n"
        f"Classe de terminale\n\nProgramme : {BO8}.\n"
    )
    par_ref = {o.normalized_reference: o for o in
               ac.attribuer_document("sha", [unite(texte)], [REF1, REF8])}
    assert par_ref[REF1].attributed_scope_levels == ["premiere"]
    assert par_ref[REF8].attributed_scope_levels == ["terminale"]


def test_une_reference_attendue_absente_du_texte_est_non_attribuable():
    (occurrence,) = ac.attribuer_document(
        "sha", [unite("Classe de première\n\nAucune citation ici.\n")], [REF1])
    assert occurrence.disposition == ac.NON_ATTRIBUABLE
    assert occurrence.textual_instances == 0


def test_une_cellule_de_tableau_repliee_n_est_pas_un_intitule():
    # Le défaut visé, constaté sur un document réel : dans un tableau extrait
    # d'un PDF, « Classe de ⏎ terminale » commence en début de ligne et finit
    # en fin de ligne. C'est une CELLULE, pas un intitulé de section, et
    # l'accepter faisait entrer la mise en page dans la structure.
    texte = (
        "de la \npratique à 12 \npoints \nClasse de \nterminale \n"
        f"Badminton en \nsimple \nRéférence {BO8}\n"
    )
    (occurrence,) = ac.attribuer_document("sha", [unite(texte)], [REF8])
    assert occurrence.disposition == ac.NON_ATTRIBUABLE


def test_un_intitule_sur_une_seule_ligne_reste_un_intitule():
    texte = f"Classe de terminale\nBadminton en simple\nRéférence {BO8}\n"
    (occurrence,) = ac.attribuer_document("sha", [unite(texte)], [REF8])
    assert occurrence.disposition == ac.ATTRIBUE
    assert occurrence.attributed_scope_levels == ["terminale"]
