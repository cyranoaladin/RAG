"""Réconciliation des répétitions historiques du scan PII (lot CU).

`pii_evidence.json` de la release V2 porte **486 occurrences pour 319
contenus** : le producteur émettait une entrée par couple (contenu, chemin)
du manifeste, puis écrasait la distinction de chemin par un dictionnaire
indexé sur le seul sha. Les 167 répétitions sont donc devenues équivalentes
champ pour champ.

Le chargeur canonique les refusait toutes — « which of the two verdicts
applies cannot be decided ». Quand les entrées sont équivalentes, il n'y a
rien d'indécidable. Ces épreuves fixent la frontière exacte : la répétition
équivalente est réconciliée et tracée, **toute** différence reste un refus.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from ingestor.ingestion_control.sealed_evidence import (
    SealedEvidenceError,
    VerifiedPIIEvidenceRegistry,
)

CORPUS = "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
SHA_A = "a" * 64
SHA_B = "b" * 64


def _entree(sha: str = SHA_A, **surcharges: Any) -> dict[str, Any]:
    entree = {
        "content_sha256": sha,
        "status": "CLEARED",
        "pii_detected": False,
        "pages_scanned": 7,
        "characters_scanned": 15480,
        "source_path": "01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/HGGSP/doc.pdf",
        "evidence_sha256": "c" * 64,
    }
    entree.update(surcharges)
    return entree


def _fichier(tmp_path: Path, entrees: list[dict[str, Any]]) -> tuple[Path, str]:
    document = {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "corpus_manifest_sha256": CORPUS,
        "policy_sha256": "d" * 64,
        "remote_access_mode": "READ_ONLY",
        "remote_write_operations": 0,
        "raw_pii_in_output": False,
        "raw_pii_in_logs": False,
        "results": entrees,
    }
    brut = json.dumps(document, ensure_ascii=False).encode("utf-8")
    chemin = tmp_path / "pii_evidence.json"
    chemin.write_bytes(brut)
    return chemin, hashlib.sha256(brut).hexdigest()


def _charger(chemin: Path, digest: str) -> VerifiedPIIEvidenceRegistry:
    return VerifiedPIIEvidenceRegistry.load(
        chemin,
        expected_evidence_sha256=digest,
        expected_corpus_manifest_sha256=CORPUS,
    )


# --- 1 — la répétition équivalente est réconciliée ET tracée ---------------


def test_des_occurrences_equivalentes_donnent_une_entree_logique(
    tmp_path: Path,
) -> None:
    chemin, digest = _fichier(tmp_path, [_entree(), _entree()])
    registre = _charger(chemin, digest)
    assert len(registre._by_content) == 1
    # La multiplicité ne disparaît pas du rapport une fois la lecture corrigée.
    assert registre._occurrences == {SHA_A: 2}


def test_la_trace_distingue_occurrences_brutes_et_contenus(tmp_path: Path) -> None:
    chemin, digest = _fichier(
        tmp_path, [_entree(), _entree(), _entree(SHA_B)]
    )
    registre = _charger(chemin, digest)
    assert sum(registre._occurrences.values()) == 3
    assert len(registre._by_content) == 2


def test_l_ordre_des_cles_ne_cree_pas_de_difference(tmp_path: Path) -> None:
    """Équivalence STRUCTURELLE : l'identité des octets est une autre preuve."""
    premiere = _entree()
    seconde = dict(reversed(list(premiere.items())))
    chemin, digest = _fichier(tmp_path, [premiere, seconde])
    assert _charger(chemin, digest)._occurrences == {SHA_A: 2}


# --- 2 — toute différence, sur n'importe quel champ, reste un refus --------


@pytest.mark.parametrize(
    ("champ", "valeur"),
    [
        ("status", "DETECTED_REVIEWED_ACCEPTED"),
        ("pii_detected", True),
        ("source_path", "01_EDUSCOL_OFFICIEL/LYCEE/PREMIERE/HGGSP/doc.pdf"),
        ("pages_scanned", 8),
        ("characters_scanned", 15481),
        ("evidence_sha256", "e" * 64),
    ],
)
def test_une_difference_sur_un_champ_connu_est_refusee(
    tmp_path: Path, champ: str, valeur: Any
) -> None:
    chemin, digest = _fichier(tmp_path, [_entree(), _entree(**{champ: valeur})])
    with pytest.raises(SealedEvidenceError, match="differing entries"):
        _charger(chemin, digest)


def test_un_champ_inconnu_du_code_est_pris_en_compte(tmp_path: Path) -> None:
    """Un champ qu'aucune version du code ne connaît ne doit pas disparaître
    avant la comparaison : sinon deux verdicts distincts se confondraient."""
    chemin, digest = _fichier(
        tmp_path, [_entree(), _entree(champ_futur="valeur")]
    )
    with pytest.raises(SealedEvidenceError, match="differing entries"):
        _charger(chemin, digest)


def test_une_entree_enrichie_ne_se_confond_pas_avec_une_entree_pauvre(
    tmp_path: Path,
) -> None:
    complete = _entree(restriction_tierce="editeur X")
    chemin, digest = _fichier(tmp_path, [_entree(), complete])
    with pytest.raises(SealedEvidenceError, match="differing entries"):
        _charger(chemin, digest)


@pytest.mark.parametrize(
    ("a", "b"),
    [(1, "1"), (1, 1.0), (0, False), (None, "")],
)
def test_les_types_ne_sont_pas_aplatis(tmp_path: Path, a: Any, b: Any) -> None:
    """Une conversion préalable ne doit pas rendre égales deux valeurs
    initialement différentes."""
    chemin, digest = _fichier(
        tmp_path, [_entree(pages_scanned=a), _entree(pages_scanned=b)]
    )
    with pytest.raises(SealedEvidenceError, match="differing entries"):
        _charger(chemin, digest)


def test_une_cle_absente_differe_d_une_cle_nulle(tmp_path: Path) -> None:
    sans = _entree()
    sans.pop("evidence_sha256")
    chemin, digest = _fichier(tmp_path, [_entree(evidence_sha256=None), sans])
    with pytest.raises(SealedEvidenceError, match="differing entries"):
        _charger(chemin, digest)


# --- 3 — la divergence est détectée sur TOUT le fichier chargé -------------


def test_une_divergence_tardive_est_refusee(tmp_path: Path) -> None:
    """Trois occurrences dont seule la dernière diffère : le refus doit
    survenir, jamais être absorbé par les deux premières."""
    chemin, digest = _fichier(
        tmp_path, [_entree(), _entree(), _entree(pages_scanned=9)]
    )
    with pytest.raises(SealedEvidenceError, match="differing entries"):
        _charger(chemin, digest)


def test_une_divergence_sur_un_contenu_non_publie_est_refusee(
    tmp_path: Path,
) -> None:
    """La contradiction porte sur l'ensemble CHARGÉ. Aucun filtrage préalable
    sur le sous-ensemble publié ne doit la faire disparaître."""
    chemin, digest = _fichier(
        tmp_path, [_entree(), _entree(SHA_B), _entree(SHA_B, pii_detected=True)]
    )
    with pytest.raises(SealedEvidenceError, match="differing entries"):
        _charger(chemin, digest)


# --- 4 — le représentant logique subit les contrôles habituels -------------


def test_des_occurrences_identiques_mais_invalides_restent_refusees(
    tmp_path: Path,
) -> None:
    """Deux entrées identiques ne deviennent pas valides parce qu'identiques :
    une admission sans autorité de revue reste refusée."""
    admise = _entree(status="DETECTED_REVIEWED_ACCEPTED", pii_detected=True)
    chemin, digest = _fichier(tmp_path, [admise, admise])
    with pytest.raises(SealedEvidenceError) as erreur:
        _charger(chemin, digest)
    assert "differing entries" not in str(erreur.value)


def test_un_sha_invalide_reste_refuse_meme_repete(tmp_path: Path) -> None:
    mauvais = _entree(content_sha256="pas-un-sha")
    chemin, digest = _fichier(tmp_path, [mauvais, mauvais])
    with pytest.raises(SealedEvidenceError, match="no valid content SHA"):
        _charger(chemin, digest)


# --- 5 — l'empreinte du fichier brut reste exigée EN AMONT ----------------


def test_un_fichier_different_de_son_empreinte_est_refuse_avant_tout(
    tmp_path: Path,
) -> None:
    """La réconciliation intervient APRÈS la vérification du fichier brut.
    Elle ne peut donc jamais servir à accepter un fichier substitué."""
    chemin, _ = _fichier(tmp_path, [_entree(), _entree()])
    with pytest.raises(SealedEvidenceError) as erreur:
        _charger(chemin, "f" * 64)
    assert "differing entries" not in str(erreur.value)


# --- 6 — noms répétés dans un objet : refusés AVANT toute réconciliation ---
#
# `json.loads` conserve par défaut la DERNIÈRE valeur d'un nom répété. Sans
# `object_pairs_hook`, l'entrée ci-dessous se lirait comme un simple CLEARED
# et `_pii_entry_identity` comparerait une ambiguïté déjà effacée.


def _fichier_brut(tmp_path: Path, texte: str) -> tuple[Path, str]:
    brut = texte.encode("utf-8")
    chemin = tmp_path / "pii_evidence.json"
    chemin.write_bytes(brut)
    return chemin, hashlib.sha256(brut).hexdigest()


_ENVELOPPE = (
    '{"evidence_kind":"REAL_CORPUS_PII_SCAN",'
    f'"corpus_manifest_sha256":"{CORPUS}",'
    '"policy_sha256":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",'
    '"remote_access_mode":"READ_ONLY","remote_write_operations":0,'
    '"raw_pii_in_output":false,"raw_pii_in_logs":false,'
    '"results":[%s]}'
)


def test_un_nom_repete_a_la_racine_d_une_entree_est_refuse(tmp_path: Path) -> None:
    entree = (
        f'{{"content_sha256":"{SHA_A}",'
        '"status":"DETECTED_RECORDED","status":"CLEARED","pii_detected":false}'
    )
    chemin, digest = _fichier_brut(tmp_path, _ENVELOPPE % entree)
    with pytest.raises(SealedEvidenceError, match="repeated name 'status'"):
        _charger(chemin, digest)


def test_un_nom_repete_dans_un_objet_imbrique_est_refuse(tmp_path: Path) -> None:
    """Le hook est appelé pour CHAQUE objet, imbriqués compris."""
    entree = (
        f'{{"content_sha256":"{SHA_A}","status":"CLEARED","pii_detected":false,'
        '"scan":{"pages":7,"pages":9}}'
    )
    chemin, digest = _fichier_brut(tmp_path, _ENVELOPPE % entree)
    with pytest.raises(SealedEvidenceError, match="repeated name 'pages'"):
        _charger(chemin, digest)


def test_un_nom_repete_dans_l_enveloppe_est_refuse(tmp_path: Path) -> None:
    texte = (_ENVELOPPE % "").replace(
        '"raw_pii_in_logs":false', '"raw_pii_in_logs":true,"raw_pii_in_logs":false'
    )
    chemin, digest = _fichier_brut(tmp_path, texte)
    with pytest.raises(SealedEvidenceError, match="repeated name"):
        _charger(chemin, digest)


def test_le_diagnostic_des_noms_repetes_est_distinct(tmp_path: Path) -> None:
    """Deux défauts, deux messages : on ne confond pas un objet ambigu avec
    des occurrences divergentes."""
    entree = (
        f'{{"content_sha256":"{SHA_A}","status":"CLEARED","status":"CLEARED",'
        '"pii_detected":false}'
    )
    chemin, digest = _fichier_brut(tmp_path, _ENVELOPPE % entree)
    with pytest.raises(SealedEvidenceError) as erreur:
        _charger(chemin, digest)
    assert "differing entries" not in str(erreur.value)
    assert "ambiguous" in str(erreur.value)


@pytest.mark.parametrize("litteral", ["NaN", "Infinity", "-Infinity"])
def test_un_nombre_non_conforme_est_refuse(tmp_path: Path, litteral: str) -> None:
    """Python accepte ces littéraux par extension ; le JSON ne les définit
    pas, et ``NaN != NaN`` rendrait l'équivalence indéfinie."""
    entree = (
        f'{{"content_sha256":"{SHA_A}","status":"CLEARED","pii_detected":false,'
        f'"characters_scanned":{litteral}}}'
    )
    chemin, digest = _fichier_brut(tmp_path, _ENVELOPPE % entree)
    with pytest.raises(SealedEvidenceError, match="non-conforming JSON number"):
        _charger(chemin, digest)


def test_les_octets_verifies_sont_ceux_qui_sont_analyses(tmp_path: Path) -> None:
    """Une seule lecture : l'empreinte et l'analyse portent sur la même
    matière. Un fichier substitué entre les deux ne peut pas passer."""
    chemin, digest = _fichier(tmp_path, [_entree(), _entree()])
    assert _charger(chemin, digest)._occurrences == {SHA_A: 2}
    chemin.write_bytes(json.dumps({"evidence_kind": "AUTRE"}).encode("utf-8"))
    with pytest.raises(SealedEvidenceError, match="hashes to"):
        _charger(chemin, digest)
