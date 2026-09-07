"""Ce que la réconciliation d'URL refuse de supposer.

Le défaut qu'elle existe pour empêcher : une URL dérivée du nom de fichier.
Elle aurait la forme d'une preuve sans en être une, et la citation d'un
document pointerait vers une page que personne n'a confrontée à ses octets.

Toutes les données de ces épreuves sont des FIXTURES construites ici. Aucune
ne prétend venir du Drive : une épreuve qui dépendrait d'un fichier réel
n'existerait plus le jour où ce fichier change.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/reconcilier_catalogue_urls.py"


def _module():
    spec = importlib.util.spec_from_file_location("reconcilier_catalogue_urls", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _relation(sha: str, **surcharges: object) -> dict[str, object]:
    base: dict[str, object] = {
        "artifact_id": sha,
        "content_sha256": sha,
        "drive_file_id": f"drive-{sha[:6]}",
        "serving_relevance": "INDEXABLE",
    }
    base.update(surcharges)
    return base


def _tsv(chemin: Path, entetes: list[str], lignes: list[list[str]]) -> Path:
    chemin.write_text(
        "\n".join(["\t".join(entetes)] + ["\t".join(ligne) for ligne in lignes]) + "\n",
        encoding="utf-8",
    )
    return chemin


# --- le manifeste d'empreintes ----------------------------------------


def test_un_manifeste_sha256_est_lu_avec_ses_chemins(tmp_path: Path) -> None:
    m = _module()
    fichier = tmp_path / "corpus.sha256"
    fichier.write_text(f"{SHA_A}  a/un.pdf\n{SHA_B}  b/deux.pdf\n", encoding="utf-8")
    assert m.charger_manifeste_empreintes(fichier) == {
        SHA_A: ["a/un.pdf"],
        SHA_B: ["b/deux.pdf"],
    }


def test_une_empreinte_qui_designe_deux_chemins_les_garde_tous(tmp_path: Path) -> None:
    """Le même contenu publié à deux endroits est une information, pas une
    anomalie : la taire rendrait une ambiguïté invisible."""
    m = _module()
    fichier = tmp_path / "corpus.sha256"
    fichier.write_text(f"{SHA_A}  a/un.pdf\n{SHA_A}  autre/un.pdf\n", encoding="utf-8")
    assert m.charger_manifeste_empreintes(fichier)[SHA_A] == ["a/un.pdf", "autre/un.pdf"]


def test_un_manifeste_illisible_est_un_refus_pas_une_lecture_partielle(
    tmp_path: Path,
) -> None:
    """Un manifeste lu de travers produirait des jointures fausses."""
    m = _module()
    fichier = tmp_path / "corpus.sha256"
    fichier.write_text(f"{SHA_A}  a/un.pdf\nceci n'est pas une ligne\n", encoding="utf-8")
    with pytest.raises(m.ReconciliationError, match="format inattendu"):
        m.charger_manifeste_empreintes(fichier)


# --- le catalogue : ses colonnes sont RELEVÉES, pas supposées ---------


def test_les_colonnes_sont_relevees_dans_l_entete(tmp_path: Path) -> None:
    m = _module()
    c = m.charger_catalogue(
        _tsv(tmp_path / "cat.tsv", ["SHA256", "Chemin", "URL", "Download_URL", "ID"], [])
    )
    assert c.colonnes["empreinte"] == "SHA256"
    assert c.colonnes["chemin"] == "Chemin"
    assert c.colonnes["url_navigation"] == "URL"
    assert c.colonnes["url_directe"] == "Download_URL"
    assert c.colonnes["identifiant"] == "ID"


def test_un_catalogue_sans_colonne_d_url_est_refuse_en_nommant_ce_qu_il_a_vu(
    tmp_path: Path,
) -> None:
    """Un catalogue sans URL n'est pas un catalogue d'URL ; le lire quand même
    ne produirait que des lignes vides."""
    m = _module()
    with pytest.raises(m.ReconciliationError, match="aucune colonne d'URL"):
        m.charger_catalogue(_tsv(tmp_path / "cat.tsv", ["sha256", "chemin"], []))


def test_un_catalogue_sans_cle_de_jointure_est_refuse(tmp_path: Path) -> None:
    m = _module()
    with pytest.raises(m.ReconciliationError, match="rien sur quoi joindre"):
        m.charger_catalogue(_tsv(tmp_path / "cat.tsv", ["titre", "url"], []))


def test_le_separateur_est_confirme_par_l_entete(tmp_path: Path) -> None:
    """Une extension ment parfois. La lire sans confirmer produirait une seule
    colonne portant toute la ligne."""
    m = _module()
    chemin = tmp_path / "cat.tsv"
    chemin.write_text("sha256,url\n" + f"{SHA_A},https://x/1\n", encoding="utf-8")
    assert m.charger_catalogue(chemin).colonnes["url_navigation"] == "url"


# --- la jointure : par identité, jamais par nom ------------------------


def test_la_jointure_par_empreinte_est_preferee(tmp_path: Path) -> None:
    m = _module()
    cat = m.charger_catalogue(
        _tsv(tmp_path / "cat.tsv", ["sha256", "url", "id"], [[SHA_A, "https://x/a", "R1"]])
    )
    rendu = m.reconcilier([_relation(SHA_A)], catalogues=[cat], manifestes={})
    (ligne,) = rendu["relations"]
    assert ligne["disposition"] == "URL_EVIDENCE_FOUND"
    assert ligne["evidence_source"] == "CATALOGUE_SHA256_JOIN"
    assert ligne["navigation_url"] == "https://x/a"
    assert ligne["evidence_row_id"] == "R1"
    assert rendu["URL_PROVENANCE_FOUND"] == 1


def test_la_jointure_par_chemin_part_du_manifeste_jamais_du_nom_de_la_relation(
    tmp_path: Path,
) -> None:
    """LE point du lot.

    Le chemin employé pour joindre vient du manifeste d'empreintes, donc d'une
    identité de CONTENU. Partir du nom de fichier de la relation serait une
    jointure lexicale — exactement ce qui est interdit."""
    m = _module()
    cat = m.charger_catalogue(
        _tsv(tmp_path / "cat.tsv", ["chemin", "url"], [["dossier/vrai.pdf", "https://x/v"]])
    )
    # La relation ne porte AUCUN chemin : seule l'empreinte permet d'y arriver.
    rendu = m.reconcilier(
        [_relation(SHA_A)], catalogues=[cat], manifestes={SHA_A: ["dossier/vrai.pdf"]}
    )
    (ligne,) = rendu["relations"]
    assert ligne["evidence_source"] == "MANIFEST_PATH_JOIN"
    assert ligne["manifest_match"] is True
    assert ligne["navigation_url"] == "https://x/v"


def test_sans_manifeste_aucun_chemin_n_est_devine(tmp_path: Path) -> None:
    """Sans identité de contenu vers un chemin, il n'y a pas de jointure —
    et surtout pas une jointure inventée depuis un nom."""
    m = _module()
    cat = m.charger_catalogue(
        _tsv(tmp_path / "cat.tsv", ["chemin", "url"], [["dossier/vrai.pdf", "https://x/v"]])
    )
    rendu = m.reconcilier([_relation(SHA_A)], catalogues=[cat], manifestes={})
    (ligne,) = rendu["relations"]
    assert ligne["disposition"] == "NO_URL_EVIDENCE"
    assert ligne["navigation_url"] is None


# --- les dispositions -------------------------------------------------


def test_deux_urls_differentes_rendent_la_preuve_ambigue(tmp_path: Path) -> None:
    m = _module()
    cat = m.charger_catalogue(
        _tsv(
            tmp_path / "cat.tsv", ["sha256", "url", "id"],
            [[SHA_A, "https://x/a", "R1"], [SHA_A, "https://y/a", "R2"]],
        )
    )
    rendu = m.reconcilier([_relation(SHA_A)], catalogues=[cat], manifestes={})
    (ligne,) = rendu["relations"]
    assert ligne["disposition"] == "AMBIGUOUS_URL_EVIDENCE"
    assert ligne["evidence_row_id"] == ["R1", "R2"]
    assert ligne["navigation_url"] is None


def test_deux_lignes_qui_disent_la_meme_url_ne_sont_pas_ambigues(
    tmp_path: Path,
) -> None:
    """Une ambiguïté est un DÉSACCORD, pas une répétition."""
    m = _module()
    cat = m.charger_catalogue(
        _tsv(
            tmp_path / "cat.tsv", ["sha256", "url", "id"],
            [[SHA_A, "https://x/a", "R1"], [SHA_A, "https://x/a", "R2"]],
        )
    )
    rendu = m.reconcilier([_relation(SHA_A)], catalogues=[cat], manifestes={})
    assert rendu["relations"][0]["disposition"] == "URL_EVIDENCE_FOUND"


def test_une_ligne_de_catalogue_sans_url_reste_une_absence_de_preuve(
    tmp_path: Path,
) -> None:
    m = _module()
    cat = m.charger_catalogue(
        _tsv(tmp_path / "cat.tsv", ["sha256", "url"], [[SHA_A, ""]])
    )
    rendu = m.reconcilier([_relation(SHA_A)], catalogues=[cat], manifestes={})
    assert rendu["relations"][0]["disposition"] == "NO_URL_EVIDENCE"


def test_un_document_non_indexable_est_sans_objet(tmp_path: Path) -> None:
    m = _module()
    cat = m.charger_catalogue(_tsv(tmp_path / "cat.tsv", ["sha256", "url"], []))
    rendu = m.reconcilier(
        [_relation(SHA_A, serving_relevance="NON_INDEXABLE")],
        catalogues=[cat], manifestes={},
    )
    assert rendu["relations"][0]["disposition"] == "NOT_APPLICABLE"


def test_une_empreinte_malformee_est_une_erreur_pas_une_absence(
    tmp_path: Path,
) -> None:
    """Confondre « je n'ai pas trouvé » et « je n'ai pas pu chercher » ferait
    passer un défaut d'entrée pour un constat sur le corpus."""
    m = _module()
    cat = m.charger_catalogue(_tsv(tmp_path / "cat.tsv", ["sha256", "url"], []))
    rendu = m.reconcilier(
        [_relation("pas-une-empreinte")], catalogues=[cat], manifestes={}
    )
    assert rendu["relations"][0]["disposition"] == "ERROR"
    assert rendu["URL_ERRORS"] == 1


def test_aucune_relation_n_est_jamais_non_comptee(tmp_path: Path) -> None:
    """Une relation sans URL devient NO_URL_EVIDENCE, jamais UNACCOUNTED."""
    m = _module()
    cat = m.charger_catalogue(
        _tsv(tmp_path / "cat.tsv", ["sha256", "url"], [[SHA_A, "https://x/a"]])
    )
    rendu = m.reconcilier(
        [
            _relation(SHA_A),
            _relation(SHA_B),
            _relation(SHA_C, serving_relevance="NON_INDEXABLE"),
            _relation("court"),
        ],
        catalogues=[cat], manifestes={},
    )
    assert rendu["URL_RELATIONS_TOTAL"] == 4
    assert rendu["URL_RELATIONS_ACCOUNTED"] == 4
    assert rendu["URL_UNACCOUNTED"] == 0
    assert rendu["URL_PROVENANCE_FOUND"] == 1
    assert rendu["URL_NO_EVIDENCE"] == 1
    assert rendu["URL_NOT_APPLICABLE"] == 1
    assert rendu["URL_ERRORS"] == 1


def test_aucune_disposition_ne_prononce_verified_current(tmp_path: Path) -> None:
    """Le catalogue prouve qu'un SHA ÉTAIT lié à une URL, pas que cette URL est
    encore actuelle. Le dire ici serait une conclusion que rien ne soutient."""
    m = _module()
    assert "VERIFIED_CURRENT" not in m.DISPOSITIONS
    cat = m.charger_catalogue(
        _tsv(tmp_path / "cat.tsv", ["sha256", "url"], [[SHA_A, "https://x/a"]])
    )
    rendu = m.reconcilier([_relation(SHA_A)], catalogues=[cat], manifestes={})
    assert all(r["disposition"] != "VERIFIED_CURRENT" for r in rendu["relations"])


# --- l'égalité des ensembles, pas le compte ---------------------------


def test_deux_populations_de_meme_taille_et_de_contenus_differents_sont_refusees(
    tmp_path: Path,
) -> None:
    m = _module()
    with pytest.raises(m.ReconciliationError, match="ensembles disjoints"):
        m.verifier_egalite_des_ensembles(
            [{"content_sha256": SHA_A}, {"content_sha256": SHA_B}],
            [{"content_sha256": SHA_A}, {"content_sha256": SHA_C}],
        )


def test_des_ensembles_egaux_passent(tmp_path: Path) -> None:
    m = _module()
    m.verifier_egalite_des_ensembles(
        [{"content_sha256": SHA_A}], [{"content_sha256": SHA_A}]
    )


# --- de bout en bout --------------------------------------------------


def test_le_cli_rend_zero_non_compte_et_ecrit_ses_colonnes_relevees(
    tmp_path: Path,
) -> None:
    m = _module()
    handoff = tmp_path / "handoff.json"
    handoff.write_text(
        json.dumps({"relations": [_relation(SHA_A), _relation(SHA_B)]}), encoding="utf-8"
    )
    cat = _tsv(tmp_path / "cat.tsv", ["sha256", "url", "id"], [[SHA_A, "https://x/a", "R1"]])
    manifeste = tmp_path / "corpus.sha256"
    manifeste.write_text(f"{SHA_A}  a/un.pdf\n", encoding="utf-8")
    sortie = tmp_path / "out.json"
    code = m.main(
        ["--handoff", str(handoff), "--catalogue", str(cat),
         "--sha256-manifest", str(manifeste), "--output", str(sortie)]
    )
    assert code == 0
    rendu = json.loads(sortie.read_text(encoding="utf-8"))
    assert rendu["URL_UNACCOUNTED"] == 0
    assert rendu["URL_PROVENANCE_FOUND"] == 1
    assert rendu["URL_NO_EVIDENCE"] == 1
    # Les colonnes relevées sont PUBLIÉES : une réconciliation dont on ne sait
    # pas sur quelles colonnes elle a porté ne se relit pas.
    assert rendu["inputs"]["catalogue_columns"][0]["empreinte"] == "sha256"
