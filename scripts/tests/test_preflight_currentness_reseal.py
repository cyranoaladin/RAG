"""Tests du préflight de reseal.

Ce qui est protégé : qu'on ne puisse pas réutiliser une identité de release,
ni exclure autre chose que ce qui est visé, ni toucher un contenu en attente de
décision PII — et que le préflight ne rescelle jamais rien.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts" / "go_live"))

import preflight_currentness_reseal as pf  # noqa: E402

ARCHIVE = pf.VERDICT_ARCHIVE
PII = pf.VERDICT_PII
CANDIDAT = pf.VERDICT_CANDIDAT


def _sha(graine: str) -> str:
    return (graine * 64)[:64]


def _poser(tmp_path: Path, verdicts: dict, promus: list[str], identites: str) -> Path:
    racine = tmp_path / "depot"
    (racine / "docs/reports/handoff").mkdir(parents=True)
    (racine / "scripts/qualification").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(racine)], check=True)
    (racine / pf.MATRICE).write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "content_sha256": sha,
                        "verdict": verdict,
                        "pii": "PII_UNDECIDED" if verdict == PII else "PII_CLEARED_OR_NOT_SCANNED",
                    }
                    for sha, verdict in sorted(verdicts.items())
                ]
            }
        ),
        encoding="utf-8",
    )
    (racine / pf.CALCULATEUR_PROMU).write_text(
        "import argparse, json\n"
        "a = argparse.ArgumentParser(); a.add_argument('--output', required=True)\n"
        "args = a.parse_args()\n"
        f"json.dump({{'content_sha256': {promus!r}}}, open(args.output, 'w'))\n",
        encoding="utf-8",
    )
    (racine / "identites.txt").write_text(identites, encoding="utf-8")
    subprocess.run(["git", "-C", str(racine), "add", "-A"], check=True)
    return racine


def test_une_identite_deja_utilisee_est_refusee(tmp_path: Path):
    """Le piège que ce préflight existe pour éviter."""
    a = _sha("a")
    racine = _poser(
        tmp_path, {a: ARCHIVE}, [a], "production-profile-gate-2026-2027-v2\n"
    )
    etat = pf.preflight(racine, "production-profile-gate-2026-2027-v2")
    assert etat["release_identity"]["is_free"] is False
    assert etat["preflight_passed"] is False
    assert "release_identity_already_used" in etat["blocking_findings"]


def test_une_identite_de_repetition_compte_comme_utilisee(tmp_path: Path):
    """Une identité employée pour une répétition a été employée."""
    a = _sha("a")
    racine = _poser(
        tmp_path, {a: ARCHIVE}, [a], "production-profile-gate-2026-2027-v9-rehearsal\n"
    )
    etat = pf.preflight(racine, "production-profile-gate-2026-2027-v9-rehearsal")
    assert etat["release_identity"]["is_free"] is False


def test_une_identite_libre_passe(tmp_path: Path):
    a = _sha("a")
    racine = _poser(
        tmp_path, {a: ARCHIVE}, [a], "production-profile-gate-2026-2027-v2\n"
    )
    etat = pf.preflight(racine, "production-profile-gate-2026-2027-v7")
    assert etat["release_identity"]["is_free"] is True
    assert etat["preflight_passed"] is True


def test_seuls_les_contenus_d_actualite_sont_exclus(tmp_path: Path):
    """Le périmètre ne déborde pas sur la PII ni sur les candidats."""
    arch, pii, cand = _sha("a"), _sha("b"), _sha("c")
    racine = _poser(
        tmp_path,
        {arch: ARCHIVE, pii: PII, cand: CANDIDAT},
        [arch, pii, cand],
        "production-profile-gate-2026-2027-v2\n",
    )
    etat = pf.preflight(racine, "production-profile-gate-2026-2027-v7")
    assert etat["contents_to_exclude"]["content_sha256"] == [arch]
    assert etat["pii_contents_untouched"]["count"] == 1
    assert etat["pii_contents_untouched"]["intersects_exclusion"] is False


def test_un_contenu_a_exclure_avec_pii_indecise_refuse(tmp_path: Path):
    """Un contenu ne doit pas sortir par l'actualité si sa PII est en attente."""
    a = _sha("a")
    racine = _poser(tmp_path, {a: ARCHIVE}, [a], "production-profile-gate-2026-2027-v2\n")
    matrice = json.loads((racine / pf.MATRICE).read_text())
    matrice["rows"][0]["pii"] = "PII_UNDECIDED"
    (racine / pf.MATRICE).write_text(json.dumps(matrice), encoding="utf-8")
    etat = pf.preflight(racine, "production-profile-gate-2026-2027-v7")
    assert etat["contents_to_exclude"]["all_pii_cleared"] is False
    assert etat["preflight_passed"] is False
    assert "excluded_content_has_undecided_pii" in etat["blocking_findings"]


def test_sans_contenu_a_exclure_le_preflight_refuse(tmp_path: Path):
    """Un reseal qui n'exclut rien n'a pas de raison d'être."""
    a = _sha("a")
    racine = _poser(tmp_path, {a: CANDIDAT}, [a], "production-profile-gate-2026-2027-v2\n")
    etat = pf.preflight(racine, "production-profile-gate-2026-2027-v7")
    assert etat["contents_to_exclude"]["count"] == 0
    assert etat["preflight_passed"] is False
    assert "no_content_to_exclude" in etat["blocking_findings"]


def test_l_impact_attendu_laisse_le_go_live_refuse(tmp_path: Path):
    arch, pii = _sha("a"), _sha("b")
    racine = _poser(
        tmp_path, {arch: ARCHIVE, pii: PII}, [arch, pii], "production-profile-gate-2026-2027-v2\n"
    )
    etat = pf.preflight(racine, "production-profile-gate-2026-2027-v7")
    impact = etat["expected_impact"]
    assert impact["promoted_content_set_size"] == {"before": 2, "after": 1}
    assert impact["release_promoted_refused_contents"] == {"before": 2, "after": 1}
    assert impact["release_promoted_refused_by_currentness"] == {"before": 1, "after": 0}
    assert impact["pii_undecided_unchanged"] is True
    assert impact["GO_LIVE_READY"]["after"] is False


def test_le_preflight_ne_rescelle_rien(tmp_path: Path):
    a = _sha("a")
    racine = _poser(tmp_path, {a: ARCHIVE}, [a], "production-profile-gate-2026-2027-v2\n")
    etat = pf.preflight(racine, "production-profile-gate-2026-2027-v7")
    assert etat["status"] == "PREFLIGHT_ONLY_NOT_APPLIED"
    assert etat["requires_human_authorization"] is True
    assert "aucune release écrite" in etat["not_done_here"]
    assert not (racine / "data").exists()


def test_un_recensement_vide_est_refuse(tmp_path: Path):
    """Un recensement vide ne prouve pas qu'une identité est libre."""
    a = _sha("a")
    racine = _poser(tmp_path, {a: ARCHIVE}, [a], "aucune identite ici\n")
    with pytest.raises(pf.EntreeManquante, match="recensement"):
        pf.preflight(racine, "production-profile-gate-2026-2027-v7")


def test_le_preflight_ne_lit_aucun_verdict_de_servabilite_qu_il_ne_compose():
    """Il lit la matrice pour SÉLECTIONNER, jamais pour décider.

    Cette épreuve tient la ligne `MATRIX_READER` de la baseline d'unicité
    d'autorité : le préflight ne rend aucun verdict et n'en invente aucun.
    """
    source = (
        RACINE / "scripts/go_live/preflight_currentness_reseal.py"
    ).read_text(encoding="utf-8")
    for interdit in ("NOT_INDEXABLE_BY_ROLE", "BLOCKED_NO_URL_PROVENANCE",
                     "REFUSED_PROGRAM_INCOMPATIBLE"):
        assert interdit not in source


def test_le_preflight_ne_s_auto_invalide_pas(tmp_path: Path):
    """Son propre rapport nomme la proposition : le compter la refuserait.

    Sans cette exclusion, proposer une identité une fois suffirait à la rendre
    « déjà utilisée » au passage suivant — le préflight refuserait toutes les
    identités qu'il a lui-même examinées.
    """
    a = _sha("a")
    racine = _poser(
        tmp_path, {a: ARCHIVE}, [a], "production-profile-gate-2026-2027-v2\n"
    )
    propose = "production-profile-gate-2026-2027-v7"
    # Le rapport de préflight existe déjà et cite la proposition.
    sortie = racine / "docs/reports/go_live/currentness_reseal_preflight.json"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(
        json.dumps({"release_identity": {"proposed": propose}}), encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(racine), "add", "-A"], check=True)

    etat = pf.preflight(racine, propose)
    assert etat["release_identity"]["is_free"] is True, (
        "le préflight s'invalide lui-même : son propre rapport a été recensé"
    )
    assert propose not in etat["release_identity"]["existing_identities"]
