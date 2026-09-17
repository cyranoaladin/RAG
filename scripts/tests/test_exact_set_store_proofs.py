"""La couverture d'un magasin se prouve en ENSEMBLE, sur ses lignes et ses octets.

Deux magasins sont éprouvés ici : le magasin vectoriel (audit) et le magasin
CAS (harnais C6). Dans les deux cas, la mutation décisive est la même : un
identifiant attendu remplacé par un étranger, à cardinal strictement égal. Un
contrôle par compteur ne la voit pas.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts/go_live"))
sys.path.insert(0, str(RACINE / "scripts/qualification"))

import audit_vector_store as audit  # noqa: E402
import servable_target  # noqa: E402
import verify_corpus_cas_c6 as c6  # noqa: E402

_REVUE = {"source": {}, "vector_extension": False, "vector_columns": 0, "artifacts": 1}


def _octets(i: int) -> bytes:
    return f"contenu gouverné numéro {i}".encode()


_OBJETS = {hashlib.sha256(_octets(i)).hexdigest(): _octets(i) for i in range(5)}
_CIBLE = sorted(_OBJETS)
_ETRANGER_OCTETS = b"contenu que la matrice n'a jamais admis"
_ETRANGER = hashlib.sha256(_ETRANGER_OCTETS).hexdigest()


def _depot(tmp_path: Path, cible=_CIBLE, refuses=()) -> Path:
    racine = tmp_path / "depot"
    (racine / "docs/reports/handoff").mkdir(parents=True)
    (racine / "docs/reports/go_live").mkdir(parents=True)
    lignes = [
        {"content_sha256": s, "verdict": servable_target.VERDICT_CANDIDAT, "pii": "PII_CLEARED"}
        for s in cible
    ] + [
        {"content_sha256": s, "verdict": "BLOCKED_PII_HUMAN_REVIEW", "pii": "REJECTED"}
        for s in refuses
    ]
    (racine / servable_target.MATRICE).write_text(json.dumps({"rows": lignes}))
    (racine / c6.ECART_RECHERCHE).write_text(
        json.dumps(
            {
                "indexable_scope": {
                    "indexable": sorted(cible),
                    "count": len(cible),
                    "indexable_digest": servable_target.empreinte_ensemble(cible),
                }
            }
        )
    )
    return racine


# --- Magasin vectoriel -------------------------------------------------------


def _dediee(liste_blanche, vectorises) -> dict:
    return {
        "source": {},
        "vector_extension": True,
        "vector_rows": 10,
        "vectorized_contents": len(vectorises),
        "allowlist_rows": len(liste_blanche),
        "dimension_mismatch": 0,
        "unauthorized_rows": 0,
        "allowlist_contents": sorted(liste_blanche),
        "vectorized_content_ids": sorted(vectorises),
    }


def _audit(tmp_path, liste_blanche, vectorises) -> dict:
    cible = servable_target.perimetre_courant(_depot(tmp_path))
    return audit.construire(_dediee(liste_blanche, vectorises), _REVUE, cible=cible)


def test_l_audit_derive_les_ensembles_reels_des_lignes(tmp_path):
    etat = _audit(tmp_path, _CIBLE, _CIBLE)
    d = etat["dedicated"]
    attendu = servable_target.empreinte_ensemble(_CIBLE)
    assert d["actual_allowlist_content_count"] == len(_CIBLE)
    assert d["actual_allowlist_content_set_sha256"] == attendu
    assert d["actual_vectorized_content_count"] == len(_CIBLE)
    assert d["actual_vectorized_content_set_sha256"] == attendu
    lien = etat["target_binding"]
    assert lien["target_servable_content_count"] == len(_CIBLE)
    assert lien["target_servable_content_set_sha256"] == attendu
    assert lien["allowlist_set_equals_target"] is True
    assert lien["vectorized_set_equals_target"] is True


def test_l_audit_voit_un_etranger_a_cardinal_egal(tmp_path):
    mute = _CIBLE[:-1] + [_ETRANGER]
    etat = _audit(tmp_path, mute, mute)
    assert etat["dedicated"]["actual_vectorized_content_count"] == len(_CIBLE)
    lien = etat["target_binding"]
    assert lien["allowlist_set_equals_target"] is False
    assert lien["vectorized_set_equals_target"] is False
    assert lien["vectorized_missing"] == [_CIBLE[-1]]
    assert lien["vectorized_extra"] == [_ETRANGER]


def test_l_audit_distingue_liste_blanche_et_vecteurs(tmp_path):
    etat = _audit(tmp_path, _CIBLE, _CIBLE[:-1])
    assert etat["target_binding"]["allowlist_set_equals_target"] is True
    assert etat["target_binding"]["vectorized_set_equals_target"] is False


# --- Magasin CAS : le harnais C6 relit les OCTETS ---------------------------


def _cas(tmp_path: Path, objets: dict[str, bytes], *, declares=None) -> Path:
    racine = tmp_path / "cas"
    (racine / "objects").mkdir(parents=True)
    entrees = []
    for sha, octets in objets.items():
        (racine / "objects" / sha).write_bytes(octets)
    for sha in declares if declares is not None else objets:
        entrees.append(
            {
                "content_sha256": sha,
                "locator": f"objects/{sha}",
                "byte_size": len(objets.get(sha, b"")),
            }
        )
    (racine / "manifest.json").write_text(
        json.dumps({"schema": c6.SCHEMA, "entries": entrees})
    )
    return racine


def test_c6_ferme_sur_un_magasin_exact(tmp_path):
    preuve = c6.run_c6_qualification(_depot(tmp_path), "0" * 40, _cas(tmp_path, _OBJETS))
    assert preuve["summary"]["failed_check_names"] == []
    assert preuve["verification_status"] == "VERIFIED"
    assert preuve["kind"].endswith("-V2")
    assert preuve["actual_cas"]["objects_verified_on_bytes"] == len(_CIBLE)
    assert preuve["target_scope"]["content_set_digest"] == (
        servable_target.empreinte_ensemble(_CIBLE)
    )
    assert preuve["verifications"]["expected_objects_missing"] == 0
    assert preuve["verifications"]["extra_objects_count"] == 0
    assert preuve["verifications"]["wrong_sha_count"] == 0


def _echoue(preuve, *noms):
    assert preuve["verification_status"] == "FAILED"
    for nom in noms:
        assert nom in preuve["summary"]["failed_check_names"], nom


def test_c6_refuse_un_magasin_absent(tmp_path):
    """L'ancien harnais fermait sans jamais ouvrir le magasin."""
    preuve = c6.run_c6_qualification(_depot(tmp_path), "0" * 40, tmp_path / "nulle-part")
    _echoue(preuve, "ALL_OBJECTS_READ_FROM_DISK", "CAS_MANIFEST_EXISTS")
    assert preuve["actual_cas"]["present"] is False
    assert preuve["verifications"]["expected_objects_missing"] == len(_CIBLE)


def test_c6_refuse_meme_cardinal_mauvais_membre(tmp_path):
    objets = {s: o for s, o in _OBJETS.items() if s != _CIBLE[-1]}
    objets[_ETRANGER] = _ETRANGER_OCTETS
    preuve = c6.run_c6_qualification(_depot(tmp_path), "0" * 40, _cas(tmp_path, objets))
    assert preuve["actual_cas"]["manifest_content_count"] == len(_CIBLE)
    _echoue(
        preuve,
        "CONTENT_SET_DIGEST_MATCHES_EXPECTED_AUTHORITY",
        "NO_EXPECTED_OBJECTS_MISSING",
        "NO_EXTRA_OBJECTS_SILENTLY_ACCEPTED",
    )


def test_c6_refuse_un_membre_manquant(tmp_path):
    objets = {s: o for s, o in _OBJETS.items() if s != _CIBLE[0]}
    preuve = c6.run_c6_qualification(_depot(tmp_path), "0" * 40, _cas(tmp_path, objets))
    _echoue(preuve, "NO_EXPECTED_OBJECTS_MISSING", "EXPECTED_COUNT_MATCHES_EXACTLY")
    assert preuve["verifications"]["expected_objects_missing"] == 1


def test_c6_refuse_un_membre_en_trop(tmp_path):
    objets = {**_OBJETS, _ETRANGER: _ETRANGER_OCTETS}
    preuve = c6.run_c6_qualification(_depot(tmp_path), "0" * 40, _cas(tmp_path, objets))
    _echoue(preuve, "NO_EXTRA_OBJECTS_SILENTLY_ACCEPTED")
    assert preuve["verifications"]["extra_objects_count"] == 1


def test_c6_refuse_un_contenu_refuse_reintroduit(tmp_path):
    objets = {**_OBJETS, _ETRANGER: _ETRANGER_OCTETS}
    racine = _depot(tmp_path, refuses=[_ETRANGER])
    preuve = c6.run_c6_qualification(racine, "0" * 40, _cas(tmp_path, objets))
    _echoue(preuve, "NO_MATRIX_REFUSED_CONTENT_ADMITTED")
    assert preuve["verifications"]["matrix_refused_admitted"] == 1


def test_c6_refuse_des_octets_qui_ne_hachent_pas_vers_leur_nom(tmp_path):
    objets = dict(_OBJETS)
    objets[_CIBLE[0]] = b"octets substitues sous le bon localisateur"
    preuve = c6.run_c6_qualification(_depot(tmp_path), "0" * 40, _cas(tmp_path, objets))
    _echoue(preuve, "ALL_OBJECTS_READ_FROM_DISK", "SHA256_RECALCULATED_ON_BYTES")
    assert preuve["verifications"]["wrong_sha_count"] == 1


def test_c6_refuse_un_objet_declare_mais_absent_du_disque(tmp_path):
    objets = {s: o for s, o in _OBJETS.items() if s != _CIBLE[0]}
    cas = _cas(tmp_path, objets, declares=_CIBLE)
    preuve = c6.run_c6_qualification(_depot(tmp_path), "0" * 40, cas)
    # Le manifeste est exact ; ce sont les OCTETS qui manquent.
    assert preuve["verdicts"]["CONTENT_SET_DIGEST_MATCHES_EXPECTED_AUTHORITY"] is True
    _echoue(preuve, "ALL_OBJECTS_READ_FROM_DISK", "NO_EXPECTED_OBJECTS_MISSING")


def test_c6_refuse_un_ecart_de_recherche_perime(tmp_path):
    """Nouvelle matrice, ancien écart : la cible a bougé, la preuve ne suit pas."""
    racine = _depot(tmp_path)
    ecart = json.loads((racine / c6.ECART_RECHERCHE).read_text())
    ecart["indexable_scope"]["indexable"] = _CIBLE[:-1]
    (racine / c6.ECART_RECHERCHE).write_text(json.dumps(ecart))
    preuve = c6.run_c6_qualification(racine, "0" * 40, _cas(tmp_path, _OBJETS))
    _echoue(preuve, "SEARCHABILITY_GAP_MATCHES_CURRENT_MATRIX")


def test_c6_refuse_un_candidat_au_statut_pii_inconnu(tmp_path):
    racine = _depot(tmp_path)
    matrice = json.loads((racine / servable_target.MATRICE).read_text())
    matrice["rows"][0]["pii"] = "STATUT_FUTUR_INCONNU"
    (racine / servable_target.MATRICE).write_text(json.dumps(matrice))
    preuve = c6.run_c6_qualification(racine, "0" * 40, _cas(tmp_path, _OBJETS))
    _echoue(preuve, "NO_PII_UNDECIDED_CONTENT_PROMOTED")


def test_aucun_cardinal_historique_ne_subsiste_dans_les_verificateurs():
    """Ni l'ancien cardinal, ni le nouveau : la cible se lit, elle ne s'écrit pas."""
    import re

    for relatif in (
        "scripts/go_live/servable_target.py",
        "scripts/go_live/build_rag_searchability_gap.py",
        "scripts/go_live/audit_vector_store.py",
        "scripts/go_live/build_qualification_blockers.py",
        "scripts/qualification/verify_corpus_cas_c6.py",
    ):
        texte = (RACINE / relatif).read_text(encoding="utf-8")
        trouve = re.findall(r"2\s?264|2\s?286|55\s?251|227617d4c436", texte)
        assert not trouve, f"{relatif} : littéral de périmètre {trouve}"
