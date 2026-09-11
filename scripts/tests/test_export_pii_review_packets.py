"""Tests de l'export des paquets de revue PII.

Trois choses sont protégées ici, et ce sont les trois façons de rendre une
revue PII sans valeur : statuer à la place du reviewer, lui montrer un texte
qui n'est pas celui qui a été scanné, et écrire de la PII dans le dépôt.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts" / "go_live"))

import export_pii_review_packets as export  # noqa: E402


def _sha(graine: str) -> str:
    return (graine * 64)[:64]


def _paquet(contenu: str, texte: str, *, classes=("email_address",), chemin="p.pdf"):
    return {
        "bundle_id": f"campagne:{contenu}",
        "content_sha256": contenu,
        "canonical_text_sha256": texte,
        "signal_classes": list(classes),
        "finding_count": 2,
        "findings": [{"page_number": 3}, {"page_number": 5}],
        "placements": ["LYCEE/PREMIERE"],
        "source_path": chemin,
        "page_provenance_digest": _sha("d"),
        "bundle_sha256": _sha("e"),
    }


def _poser(tmp_path: Path, paquets, contenus_matrice):
    racine = tmp_path / "depot"
    (racine / "docs/reports/evidence-index").mkdir(parents=True)
    (racine / "docs/reports/handoff").mkdir(parents=True)
    (racine / export.INDEX_REVUE).write_text(
        json.dumps({"bundles": paquets, "campaign_id": "c", "protocol_version": "v"}),
        encoding="utf-8",
    )
    (racine / export.MATRICE).write_text(
        json.dumps(
            {
                "rows": [
                    {"content_sha256": c, "verdict": export.VERDICT_PII}
                    for c in contenus_matrice
                ]
            }
        ),
        encoding="utf-8",
    )
    return racine


def test_un_paquet_est_exporte_quand_le_texte_concorde(tmp_path: Path):
    a, t = _sha("a"), _sha("t")
    racine = _poser(tmp_path, [_paquet(a, t)], [a])
    etat = export.construire(racine, {a: t}, set())
    assert etat["counts"]["packets_exported"] == 1
    assert etat["counts"]["divergent_review_text"] == 0


def test_un_texte_divergent_est_refuse_et_nomme(tmp_path: Path):
    """Le contrôle central : statuer sur un autre texte ne prouverait rien."""
    a, t, autre = _sha("a"), _sha("t"), _sha("z")
    racine = _poser(tmp_path, [_paquet(a, t)], [a])
    etat = export.construire(racine, {a: autre}, set())
    assert etat["counts"]["packets_exported"] == 0
    assert etat["counts"]["divergent_review_text"] == 1
    divergence = etat["divergences"][0]
    assert divergence["index_canonical_text_sha256"] == t
    assert divergence["database_canonical_text_sha256"] == autre


def test_un_contenu_absent_de_la_base_est_refuse_pas_invente(tmp_path: Path):
    a = _sha("a")
    racine = _poser(tmp_path, [_paquet(a, _sha("t"))], [a])
    etat = export.construire(racine, {}, set())
    assert etat["counts"]["packets_exported"] == 0
    assert etat["absent_from_database"] == [a]


def test_aucune_decision_n_est_prise(tmp_path: Path):
    a, t = _sha("a"), _sha("t")
    racine = _poser(tmp_path, [_paquet(a, t)], [a])
    etat = export.construire(racine, {a: t}, set())
    assert etat["decisions_made_here"] == 0
    assert etat["packets"][0]["reviewer_decision"] == ""
    assert etat["packets"][0]["evidence"] == ""
    assert etat["packets"][0]["audit_trail"] == ""
    assert set(etat["allowed_decisions"]) == set(export.DECISIONS_AUTORISEES)


def test_aucune_pii_brute_n_est_ecrite(tmp_path: Path):
    a, t = _sha("a"), _sha("t")
    racine = _poser(tmp_path, [_paquet(a, t)], [a])
    etat = export.construire(racine, {a: t}, set())
    assert etat["raw_pii_in_output"] is False
    assert etat["packets"][0]["raw_pii_included"] is False
    # Le paquet ne porte que des empreintes, des classes et des comptes.
    assert "excerpt" not in etat["packets"][0]
    assert "match_text" not in json.dumps(etat)


def test_les_contenus_promus_passent_en_premier(tmp_path: Path):
    a, b, c = _sha("a"), _sha("b"), _sha("c")
    t = _sha("t")
    paquets = [
        _paquet(a, t, chemin="z.pdf"),
        _paquet(b, t, chemin="a.pdf"),
        _paquet(c, t, chemin="m.pdf"),
    ]
    racine = _poser(tmp_path, paquets, [a, b, c])
    etat = export.construire(racine, {a: t, b: t, c: t}, {c})
    assert etat["packets"][0]["content_sha256"] == c
    assert etat["packets"][0]["promoted"] is True
    assert etat["counts"]["promoted_among_exported"] == 1


def test_un_contenu_promu_porte_un_impact_d_exclusion_different(tmp_path: Path):
    a, t = _sha("a"), _sha("t")
    racine = _poser(tmp_path, [_paquet(a, t)], [a])
    promu = export.construire(racine, {a: t}, {a})["packets"][0]
    non_promu = export.construire(racine, {a: t}, set())["packets"][0]
    assert "release" in promu["impact_if_excluded"]
    assert promu["impact_if_excluded"] != non_promu["impact_if_excluded"]
    assert "priorité" in promu["recommended_action"]


def test_le_rapport_dit_ce_qu_il_ne_change_pas(tmp_path: Path):
    a, t = _sha("a"), _sha("t")
    racine = _poser(tmp_path, [_paquet(a, t)], [a])
    etat = export.construire(racine, {a: t}, set())
    assert "le compteur pii_undecided" in etat["does_not_change"]
    assert "la matrice de servabilité" in etat["does_not_change"]


def test_la_feuille_de_decision_sort_vide_cote_decision(tmp_path: Path):
    a, t = _sha("a"), _sha("t")
    racine = _poser(tmp_path, [_paquet(a, t)], [a])
    etat = export.construire(racine, {a: t}, set())
    feuille = export.rendre_feuille(etat).splitlines()
    assert feuille[0].split("\t") == list(export.COLONNES_FEUILLE)
    champs = feuille[1].split("\t")
    indice = export.COLONNES_FEUILLE.index("decision")
    assert champs[indice] == ""
    assert champs[export.COLONNES_FEUILLE.index("reviewer")] == ""


def test_index_de_revue_absent_refuse(tmp_path: Path):
    racine = tmp_path / "vide"
    (racine / "docs/reports/evidence-index").mkdir(parents=True)
    with pytest.raises(export.EntreeManquante):
        export.construire(racine, {}, set())


def test_index_sans_paquet_refuse(tmp_path: Path):
    racine = _poser(tmp_path, [], [_sha("a")])
    with pytest.raises(export.EntreeManquante, match="sans paquet"):
        export.construire(racine, {}, set())


def test_un_desaccord_entre_l_index_et_la_matrice_est_signale(tmp_path: Path):
    """La matrice est lue pour être contredite, pas pour décider.

    Cette épreuve tient la ligne `MATRIX_READER` de la baseline : aucun verdict
    n'est produit ici, et la seule chose que la matrice sert à établir est que
    les deux recensements portent bien sur le même ensemble.
    """
    a, b, t = _sha("a"), _sha("b"), _sha("t")
    # La matrice bloque un contenu que l'index de revue ignore.
    racine = _poser(tmp_path, [_paquet(a, t)], [a, b])
    etat = export.construire(racine, {a: t}, set())
    accord = etat["index_matrix_agreement"]
    assert accord["agree"] is False
    assert accord["in_matrix_not_in_index"] == [b]
    assert accord["in_index_not_in_matrix"] == []


def test_l_accord_est_constate_quand_les_deux_recensements_coincident(tmp_path: Path):
    a, t = _sha("a"), _sha("t")
    racine = _poser(tmp_path, [_paquet(a, t)], [a])
    etat = export.construire(racine, {a: t}, set())
    assert etat["index_matrix_agreement"]["agree"] is True


def test_le_module_ne_lit_aucun_verdict_autre_que_le_blocage_pii():
    source = (
        RACINE / "scripts/go_live/export_pii_review_packets.py"
    ).read_text(encoding="utf-8")
    for interdit in ("CANDIDATE_NO_BLOCKING_DIMENSION", "REFUSED_PROGRAM_INCOMPATIBLE",
                     "NOT_INDEXABLE_BY_ROLE", "BLOCKED_NO_URL_PROVENANCE"):
        assert interdit not in source
