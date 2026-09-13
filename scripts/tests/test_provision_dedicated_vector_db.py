"""Épreuves du provisionnement de la base de vectorisation dédiée.

Le risque de ce lot n'est pas de mal créer une base : c'est de la créer au
mauvais endroit, ou de lui donner à indexer ce que le gate refuse. Les épreuves
qui suivent portent donc sur les refus, pas sur le chemin heureux.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import provision_dedicated_vector_db as provisionnement  # noqa: E402

RAPPORT = RACINE / "docs/reports/go_live/dedicated_vector_db_provisioning.json"
ECART = RACINE / "docs/reports/go_live/rag_searchability_gap.json"
MATRICE = RACINE / "docs/reports/handoff/servability_matrix_v1.json"
READINESS = RACINE / "docs/reports/go_live/go_live_readiness_state.json"

DSN_REVUE = "postgresql://role@127.0.0.1:55435/drivestaging"


def _empreinte(ids) -> str:
    return hashlib.sha256(
        "".join(f"{i}\n" for i in sorted(ids)).encode("utf-8")
    ).hexdigest()


def _ecart_jouet(racine: Path, autorises, refuses, *, count=None, digest=None):
    dossier = racine / "docs/reports/go_live"
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "rag_searchability_gap.json").write_text(
        json.dumps(
            {
                "indexable_scope": {
                    "count": len(autorises) if count is None else count,
                    "indexable": sorted(autorises),
                    "indexable_digest": (
                        _empreinte(autorises) if digest is None else digest
                    ),
                    "never_indexable": sorted(refuses),
                }
            }
        ),
        encoding="utf-8",
    )


def _provisionneur(loaded, vector_rows=0, version="0.8.2", base="dediee"):
    def faux(dsn, autorises):
        return {
            "dbname": base,
            "loaded": loaded if loaded is not None else len(autorises),
            "vector_rows": vector_rows,
            "pgvector_version": version,
        }

    return faux


# --- Refus de cible --------------------------------------------------------


def test_viser_la_base_de_revue_par_son_nom_est_refuse():
    with pytest.raises(provisionnement.CibleInterdite, match="base de revue"):
        provisionnement.refuser_si_base_de_revue(
            provisionnement.decrire_dsn(DSN_REVUE), None
        )


def test_renommer_la_base_ne_suffit_pas_a_quitter_le_serveur_de_revue():
    """Le nom est cosmétique ; l'hôte et le port ne le sont pas."""
    cible = provisionnement.decrire_dsn("postgresql://role@127.0.0.1:55435/autre")
    with pytest.raises(provisionnement.CibleInterdite, match="serveur de"):
        provisionnement.refuser_si_base_de_revue(
            cible, provisionnement.decrire_dsn(DSN_REVUE)
        )


def test_un_dsn_sans_nom_de_base_est_refuse():
    with pytest.raises(provisionnement.CibleInterdite):
        provisionnement.refuser_si_base_de_revue(
            provisionnement.decrire_dsn("postgresql://role@127.0.0.1:55436/"), None
        )


def test_une_base_dediee_sur_un_autre_serveur_est_acceptee():
    """Le refus doit discriminer, sinon il ne prouve rien."""
    provisionnement.refuser_si_base_de_revue(
        provisionnement.decrire_dsn("postgresql://role@127.0.0.1:55436/dediee"),
        provisionnement.decrire_dsn(DSN_REVUE),
    )


# --- Refus d'entrée --------------------------------------------------------


def test_un_contenu_refuse_par_le_gate_dans_l_entree_fait_echouer(tmp_path):
    _ecart_jouet(tmp_path, ["aa", "bb"], ["bb"])
    with pytest.raises(provisionnement.CibleInterdite, match="refusés par le gate"):
        provisionnement.perimetre_autorise(tmp_path)


def test_un_compteur_qui_ne_correspond_pas_a_la_liste_fait_echouer(tmp_path):
    _ecart_jouet(tmp_path, ["aa", "bb"], [], count=2529)
    with pytest.raises(provisionnement.EntreeManquante, match="se contredit"):
        provisionnement.perimetre_autorise(tmp_path)


def test_une_empreinte_non_reproductible_fait_echouer(tmp_path):
    _ecart_jouet(tmp_path, ["aa", "bb"], [], digest="0" * 64)
    with pytest.raises(provisionnement.EntreeManquante, match="non reproductible"):
        provisionnement.perimetre_autorise(tmp_path)


def test_un_ecart_absent_n_est_pas_un_perimetre_vide(tmp_path):
    """Une entrée manquante n'autorise rien : elle interrompt."""
    with pytest.raises(provisionnement.EntreeManquante):
        provisionnement.perimetre_autorise(tmp_path)


def test_une_liste_blanche_partiellement_chargee_fait_echouer(tmp_path):
    _ecart_jouet(tmp_path, ["aa", "bb", "cc"], [])
    with pytest.raises(provisionnement.EntreeManquante, match="incomplète"):
        provisionnement.construire(
            tmp_path,
            "postgresql://role@127.0.0.1:55436/dediee",
            DSN_REVUE,
            "c",
            provisionneur=_provisionneur(loaded=2),
            sonde_extension=lambda _dsn: False,
        )


def test_des_vecteurs_deja_presents_font_echouer(tmp_path):
    """Ce lot n'écrit pas dans une base qui porte déjà des vecteurs."""
    _ecart_jouet(tmp_path, ["aa"], [])
    with pytest.raises(provisionnement.CibleInterdite, match="vecteurs présents"):
        provisionnement.construire(
            tmp_path,
            "postgresql://role@127.0.0.1:55436/dediee",
            DSN_REVUE,
            "c",
            provisionneur=_provisionneur(loaded=None, vector_rows=7),
            sonde_extension=lambda _dsn: False,
        )


def test_le_lot_ne_peut_pas_declarer_une_vectorisation_executee(tmp_path):
    _ecart_jouet(tmp_path, ["aa", "bb"], [])
    etat = provisionnement.construire(
        tmp_path,
        "postgresql://role@127.0.0.1:55436/dediee",
        DSN_REVUE,
        "c",
        provisionneur=_provisionneur(loaded=None),
        sonde_extension=lambda _dsn: False,
    )
    assert etat["vectorization_executed"] is False
    assert etat["vector_rows"] == 0
    assert etat["production_touched"] is False
    assert etat["current_switch"] is False


def test_le_module_ne_sait_pas_ecrire_un_vecteur():
    """Aucun chemin d'écriture de vecteur n'existe dans ce code.

    Ni modèle d'embedding, ni écriture dans la table de vecteurs. Le
    provisionnement ne peut donc pas déborder en vectorisation par accident.
    """
    source = Path(provisionnement.__file__).read_text(encoding="utf-8")
    for interdit in (
        "SentenceTransformer",
        "sentence_transformers",
        "import torch",
        "INSERT INTO",
    ):
        assert interdit not in source, f"chemin de vectorisation présent : {interdit}"
    # La seule écriture de données est la liste blanche. La table de vecteurs
    # n'est que CRÉÉE, jamais alimentée.
    for instruction in ("COPY", "UPDATE ", "INSERT"):
        for ligne in source.splitlines():
            if instruction in ligne and provisionnement.TABLE_VECTEURS in ligne:
                pytest.fail(f"écriture dans la table de vecteurs : {ligne.strip()}")


def test_le_module_ne_lit_pas_la_matrice():
    """Une seule autorité dérive le périmètre indexable ; ce n'est pas celle-ci."""
    source = Path(provisionnement.__file__).read_text(encoding="utf-8")
    assert "servability_matrix" not in source


# --- Épreuves sur les artefacts VERSIONNÉS ---------------------------------


@pytest.fixture(scope="module")
def rapport() -> dict:
    if not RAPPORT.is_file():
        pytest.skip("provisionnement pas encore produit")
    return json.loads(RAPPORT.read_text(encoding="utf-8"))


def test_le_corpus_brut_n_est_pas_la_cible(rapport):
    """2529 est le corpus pédagogique : il contient les refusés du gate."""
    assert rapport["input_scope"] == "SERVABLE_CANDIDATE_SET"
    assert rapport["input_count"] == 2264
    assert rapport["input_count"] != 2529


def test_le_perimetre_versionne_est_reproductible(rapport):
    ecart = json.loads(ECART.read_text(encoding="utf-8"))["indexable_scope"]
    assert rapport["input_digest"] == ecart["indexable_digest"]
    assert rapport["input_digest"] == _empreinte(ecart["indexable"])
    assert rapport["allowlist_rows"] == rapport["input_count"]


def test_aucun_contenu_en_attente_de_decision_pii_dans_l_entree():
    """Vérifié contre la matrice elle-même, pas contre un champ recopié."""
    lignes = json.loads(MATRICE.read_text(encoding="utf-8"))["rows"]
    autorises = set(
        json.loads(ECART.read_text(encoding="utf-8"))["indexable_scope"]["indexable"]
    )
    en_attente = {
        ligne["content_sha256"]
        for ligne in lignes
        if ligne["pii"] in {"PII_UNDECIDED", "NOT_ASSESSABLE", "REJECTED"}
    }
    assert en_attente, "aucun contenu PII en attente : l'épreuve ne prouverait rien"
    assert not (autorises & en_attente)


def test_aucun_contenu_refuse_pour_actualite_dans_l_entree():
    lignes = json.loads(MATRICE.read_text(encoding="utf-8"))["rows"]
    autorises = set(
        json.loads(ECART.read_text(encoding="utf-8"))["indexable_scope"]["indexable"]
    )
    refuses = {
        ligne["content_sha256"]
        for ligne in lignes
        if ligne["verdict"]
        in {"BLOCKED_NOT_CURRENT_BY_SOURCE", "BLOCKED_CURRENTNESS_UNKNOWN"}
    }
    assert refuses, "aucun refus d'actualité : l'épreuve ne prouverait rien"
    assert not (autorises & refuses)


def test_pgvector_reste_absent_de_la_base_de_revue(rapport):
    assert rapport["pgvector_installed_in_review_db"] is False
    assert rapport["pgvector_installed_in_dedicated_db"] is True
    assert rapport["source_review_db_readonly"] is True
    assert rapport["review_db_written"] is False


def test_la_base_dediee_n_est_pas_la_base_de_revue(rapport):
    assert rapport["dedicated_db_name"] != provisionnement.BASE_DE_REVUE
    assert rapport["dedicated_db_port"] != 55435


def test_un_retour_arriere_est_nomme(rapport):
    assert rapport["rollback_command"]
    assert "drivestaging" not in rapport["rollback_command"]


def test_le_go_live_reste_refuse():
    """Provisionner une base ne rend rien servable.

    L'épreuve portait aussi `staging_vectors_present == 0`. C'était vrai à
    l'instant du provisionnement, et c'est devenu faux dès que la phase A a
    produit des vecteurs — sans que la CLAIM de cette épreuve change. Un
    compteur qui bouge légitimement n'a pas sa place dans une épreuve qui
    parle d'autre chose : ce qu'elle doit tenir, c'est que provisionner ne
    rend rien interrogeable.
    """
    etat = json.loads(READINESS.read_text(encoding="utf-8"))
    assert etat["go_live_ready"] is False
    assert etat["rag_searchability_blocker"] is True
    assert etat["target_scope_searchable"] is False
