"""Épreuves du re-découpage sous budget de tokens.

Le lot précédent a échoué parce que les chunks dépassaient la limite du
modèle. Ces épreuves portent sur ce qui doit rendre ce défaut impossible :
un budget lu sur le modèle, un refus dès le premier dépassement, et un
contenu manquant nommé plutôt que compté zéro.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import rechunk_publication_token_budget as rechunk  # noqa: E402

RAPPORT = RACINE / "docs/reports/go_live/rechunk_publication_token_budget.json"
ECART = RACINE / "docs/reports/go_live/rag_searchability_gap.json"


class _Compteur:
    """Compteur de tokens jouet : un token par caractère."""

    def __init__(self, limite: int = 10) -> None:
        self.max_sequence_length = limite

    def passage_token_count(self, texte: str) -> int:
        return len(texte)


class _Chunk:
    def __init__(self, texte: str) -> None:
        self.text = texte
        self.page_start = 1
        self.page_end = 1


# --- Budget : refus dès le premier dépassement ----------------------------


def test_un_seul_chunk_au_dela_du_budget_fait_echouer():
    compteur = _Compteur(10)
    chunks = [_Chunk("court"), _Chunk("x" * 11)]
    with pytest.raises(rechunk.BudgetNonTenu, match="11 tokens"):
        rechunk.verifier_budget(chunks, compteur)


def test_des_chunks_tous_dans_le_budget_sont_acceptes():
    """Le refus doit discriminer, sinon il ne prouve rien."""
    compteur = _Compteur(10)
    assert rechunk.verifier_budget([_Chunk("abc"), _Chunk("x" * 10)], compteur) == 10


def test_la_limite_vient_du_compteur_pas_d_une_constante():
    """Recopier 512 ici en ferait une seconde autorité, libre de diverger."""
    source = Path(rechunk.__file__).read_text(encoding="utf-8")
    assert "512" not in source
    assert "compteur.max_sequence_length" in source


# --- Le miroir est indexé par empreinte, pas par nom ----------------------


def test_le_miroir_est_indexe_par_empreinte_de_contenu(tmp_path):
    """Le nom d'un fichier ne prouve rien ; son empreinte si."""
    (tmp_path / "sous").mkdir()
    octets = b"contenu de test"
    (tmp_path / "sous" / "nom-trompeur.pdf").write_bytes(octets)
    index = rechunk.indexer_miroir(tmp_path)
    attendu = hashlib.sha256(octets).hexdigest()
    assert attendu in index
    assert index[attendu].name == "nom-trompeur.pdf"


def test_un_miroir_absent_n_est_pas_un_miroir_vide(tmp_path):
    with pytest.raises(rechunk.EntreeManquante, match="absent"):
        rechunk.indexer_miroir(tmp_path / "nexistepas")


def test_un_miroir_vide_est_refuse(tmp_path):
    """Zéro objet n'est pas un résultat : c'est une entrée manquante."""
    with pytest.raises(rechunk.EntreeManquante, match="vide"):
        rechunk.indexer_miroir(tmp_path)


def test_un_perimetre_absent_est_refuse(tmp_path):
    with pytest.raises(rechunk.EntreeManquante):
        rechunk.perimetre_autorise(tmp_path)


def test_le_module_ne_lit_pas_la_base_de_revue():
    """Les octets viennent du miroir ; la base de revue n'est pas touchée."""
    source = Path(rechunk.__file__).read_text(encoding="utf-8")
    assert "REVIEW_DB" not in source
    assert "drivestaging" not in source


def test_le_module_n_ecrit_que_dans_la_base_dediee():
    source = Path(rechunk.__file__).read_text(encoding="utf-8")
    assert rechunk.VAR_DEDIEE in source
    for interdit in ("drive_staging.chunks", "drive_staging.artifacts"):
        assert f"INSERT INTO {interdit}" not in source
        assert f"UPDATE {interdit}" not in source


def test_le_decoupeur_et_le_compteur_sont_ceux_du_depot():
    source = Path(rechunk.__file__).read_text(encoding="utf-8")
    assert "from ingestor.publication_chunking import chunk_publication" in source
    assert "VerifiedE5EmbeddingProvider" in source


# --- Le rapport VERSIONNÉ -------------------------------------------------


@pytest.fixture(scope="module")
def rapport() -> dict:
    if not RAPPORT.is_file():
        pytest.skip("re-découpage pas encore exécuté")
    return json.loads(RAPPORT.read_text(encoding="utf-8"))


def test_aucun_chunk_ne_depasse_la_limite(rapport):
    assert rapport["chunks_over_token_limit"] == 0
    assert rapport["max_tokens"] <= rapport["model_sequence_limit"]


def test_tous_les_contenus_autorises_ont_leurs_octets(rapport):
    """Un contenu sans octets est NOMMÉ, pas compté zéro."""
    assert rapport["contents_without_pdf_bytes"] == len(
        rapport["contents_without_pdf_bytes_ids"]
    )
    assert rapport["contents_without_pdf_bytes"] == 0, (
        f"octets manquants pour {rapport['contents_without_pdf_bytes_ids'][:5]}"
    )


def test_les_contenus_sans_texte_extractible_sont_nommes(rapport):
    assert rapport["contents_without_extractable_text"] == len(
        rapport["contents_without_extractable_text_ids"]
    )


def test_le_perimetre_est_celui_de_l_ecart(rapport):
    ecart = json.loads(ECART.read_text(encoding="utf-8"))["indexable_scope"]
    assert rapport["input_digest"] == ecart["indexable_digest"]
    assert rapport["authorized_contents"] == ecart["count"]


def test_aucune_exclusion_n_est_violee(rapport):
    for champ in (
        "gate_refused_intersection",
        "pii_undecided_intersection",
        "currentness_refused_intersection",
        "no_url_provenance_intersection",
        "non_indexable_intersection",
    ):
        assert rapport[champ] == 0, champ


def test_la_base_de_revue_reste_hors_du_chemin(rapport):
    assert rapport["review_db_read"] is False
    assert rapport["review_db_written"] is False


def test_le_decoupage_conserve_la_pagination(rapport):
    """C'est la raison de repartir des octets : garder des citations vérifiables."""
    assert rapport["pages_covered"] > 0
    assert "pagination" in Path(rechunk.__file__).read_text(encoding="utf-8")


def test_le_nombre_de_chunks_en_base_correspond_au_compte(rapport):
    assert rapport["chunks_in_database"] == rapport["chunks_total"]
