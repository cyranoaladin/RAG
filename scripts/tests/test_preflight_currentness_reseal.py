"""Tests du préflight de reseal.

Ce qui est protégé : qu'on n'exclue que ce qui est visé, qu'aucun contenu en
attente de décision PII ne bouge, que le préflight ne rescelle rien — et qu'il
ne redevienne jamais une seconde autorité sur l'unicité d'identité de release.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts" / "go_live"))

import preflight_currentness_reseal as pf  # noqa: E402

ARCHIVE = pf.VERDICT_ARCHIVE
PII = pf.VERDICT_PII
CANDIDAT = pf.VERDICT_CANDIDAT

#: L'autorité canonique vit dans le producteur de release. Les tests de
#: périmètre n'ont pas à la rejouer : ils la remplacent par un verdict connu.
LIBRE = (True, "libre pour le test")
PRISE = (False, "identité déjà publiée")


def _sha(graine: str) -> str:
    return (graine * 64)[:64]


def _poser(tmp_path: Path, verdicts: dict, promus: list[str]) -> Path:
    racine = tmp_path / "depot"
    (racine / "docs/reports/handoff").mkdir(parents=True)
    (racine / "scripts/qualification").mkdir(parents=True)
    (racine / pf.MATRICE).write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "content_sha256": sha,
                        "verdict": verdict,
                        "pii": "PII_UNDECIDED"
                        if verdict == PII
                        else "PII_CLEARED_OR_NOT_SCANNED",
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
    return racine


@pytest.fixture
def autorite_libre(monkeypatch):
    monkeypatch.setattr(pf, "identite_est_libre", lambda racine, identite: LIBRE)
    monkeypatch.setattr(
        pf, "identites_existantes", lambda racine: ({"deja-publiee"}, "test")
    )


# --- l'unicité d'identité appartient au producteur de release ---------------


def test_l_identite_est_decidee_par_l_autorite_canonique(monkeypatch, tmp_path):
    """Le préflight ne recense plus : il demande.

    Une version antérieure greppait le dépôt. Elle comptait « prise » une
    identité seulement ÉVOQUÉE dans un ADR, et s'invalidait elle-même dès que
    son propre rapport nommait la proposition.
    """
    a = _sha("a")
    racine = _poser(tmp_path, {a: ARCHIVE}, [a])
    monkeypatch.setattr(pf, "identites_existantes", lambda r: ({"x"}, "autorite"))
    monkeypatch.setattr(pf, "identite_est_libre", lambda r, i: PRISE)
    etat = pf.preflight(racine, "peu-importe")
    assert etat["release_identity"]["is_free"] is False
    assert "release_identity_already_used" in etat["blocking_findings"]
    assert etat["preflight_passed"] is False


def test_une_identite_acceptee_par_l_autorite_passe(monkeypatch, tmp_path):
    a = _sha("a")
    racine = _poser(tmp_path, {a: ARCHIVE}, [a])
    monkeypatch.setattr(pf, "identites_existantes", lambda r: ({"x"}, "autorite"))
    monkeypatch.setattr(pf, "identite_est_libre", lambda r, i: LIBRE)
    etat = pf.preflight(racine, "identite-neuve")
    assert etat["release_identity"]["is_free"] is True
    assert etat["preflight_passed"] is True


def test_le_module_ne_recense_plus_les_identites_lui_meme():
    """Deux autorités sur l'unicité finiraient par ne pas dire la même chose."""
    source = (
        RACINE / "scripts/go_live/preflight_currentness_reseal.py"
    ).read_text(encoding="utf-8")
    assert '"git", "grep"' not in source, "le recensement par grep est revenu"
    assert "MOTIF_IDENTITE" not in source
    assert "require_governed_release_id" in source
    assert "PUBLISHED_RELEASE_IDS" in source


def test_l_autorite_reelle_refuse_l_identite_historique():
    """Épreuve d'intégration : l'autorité consultée est bien la bonne."""
    libre, motif = pf.identite_est_libre(RACINE, "production-profile-gate-2026-2027-v1")
    assert libre is False
    assert "publi" in motif.lower()


# --- le périmètre d'exclusion ----------------------------------------------


def test_seuls_les_contenus_d_actualite_sont_exclus(autorite_libre, tmp_path):
    arch, pii, cand = _sha("a"), _sha("b"), _sha("c")
    racine = _poser(
        tmp_path, {arch: ARCHIVE, pii: PII, cand: CANDIDAT}, [arch, pii, cand]
    )
    etat = pf.preflight(racine, "identite-neuve")
    assert etat["contents_to_exclude"]["content_sha256"] == [arch]
    assert etat["pii_contents_untouched"]["count"] == 1
    assert etat["pii_contents_untouched"]["intersects_exclusion"] is False


def test_un_contenu_a_exclure_avec_pii_indecise_refuse(autorite_libre, tmp_path):
    """Un contenu ne sort pas par l'actualité si sa PII est en attente."""
    a = _sha("a")
    racine = _poser(tmp_path, {a: ARCHIVE}, [a])
    matrice = json.loads((racine / pf.MATRICE).read_text())
    matrice["rows"][0]["pii"] = "PII_UNDECIDED"
    (racine / pf.MATRICE).write_text(json.dumps(matrice), encoding="utf-8")
    etat = pf.preflight(racine, "identite-neuve")
    assert etat["contents_to_exclude"]["all_pii_cleared"] is False
    assert "excluded_content_has_undecided_pii" in etat["blocking_findings"]


def test_sans_contenu_a_exclure_le_preflight_refuse(autorite_libre, tmp_path):
    """Un reseal qui n'exclut rien n'a pas de raison d'être."""
    a = _sha("a")
    racine = _poser(tmp_path, {a: CANDIDAT}, [a])
    etat = pf.preflight(racine, "identite-neuve")
    assert etat["contents_to_exclude"]["count"] == 0
    assert "no_content_to_exclude" in etat["blocking_findings"]


def test_l_impact_attendu_laisse_le_go_live_refuse(autorite_libre, tmp_path):
    arch, pii = _sha("a"), _sha("b")
    racine = _poser(tmp_path, {arch: ARCHIVE, pii: PII}, [arch, pii])
    etat = pf.preflight(racine, "identite-neuve")
    impact = etat["expected_impact"]
    assert impact["promoted_content_set_size"] == {"before": 2, "after": 1}
    assert impact["release_promoted_refused_contents"] == {"before": 2, "after": 1}
    assert impact["release_promoted_refused_by_currentness"] == {"before": 1, "after": 0}
    assert impact["pii_undecided_unchanged"] is True
    assert impact["GO_LIVE_READY"]["after"] is False


def test_le_preflight_ne_rescelle_rien(autorite_libre, tmp_path):
    a = _sha("a")
    racine = _poser(tmp_path, {a: ARCHIVE}, [a])
    etat = pf.preflight(racine, "identite-neuve")
    assert etat["status"] == "PREFLIGHT_ONLY_NOT_APPLIED"
    assert etat["requires_human_authorization"] is True
    assert not (racine / "data").exists()


def test_le_preflight_ne_lit_aucun_verdict_qu_il_ne_compose():
    source = (
        RACINE / "scripts/go_live/preflight_currentness_reseal.py"
    ).read_text(encoding="utf-8")
    for interdit in ("NOT_INDEXABLE_BY_ROLE", "BLOCKED_NO_URL_PROVENANCE",
                     "REFUSED_PROGRAM_INCOMPATIBLE"):
        assert interdit not in source
