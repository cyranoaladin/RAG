"""Tests de l'inventaire du corpus Drive.

Chaque test vise une affirmation que le rapport prétend porter. Un test qui
passerait encore après avoir cassé la règle qu'il surveille ne prouve rien :
les mutations de la PR servent à le vérifier.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts" / "go_live"))

import build_drive_corpus_inventory as inventaire  # noqa: E402

CALCULATEUR = """#!/usr/bin/env python3
import argparse, json
a = argparse.ArgumentParser(); a.add_argument("--output", required=True)
args = a.parse_args()
json.dump({"content_sha256": %(promus)r, "count": len(%(promus)r)}, open(args.output, "w"))
"""


def _sha(graine: str) -> str:
    return (graine * 64)[:64]


def _poser_depot(
    tmp_path: Path,
    *,
    manifeste: list[tuple[str, str]],
    catalogue: list[tuple[str, str]],
    matrice: list[dict],
    promus: list[str],
    calculateur_echoue: bool = False,
    entete_catalogue: str = "sha256\turl_source",
) -> tuple[Path, Path]:
    racine = tmp_path / "depot"
    drive = tmp_path / "drive"
    (racine / "docs/reports/handoff").mkdir(parents=True)
    (racine / "scripts/qualification").mkdir(parents=True)
    drive.mkdir()

    (drive / "SHA256SUMS.txt").write_text(
        "".join(f"{sha}  {chemin}\n" for sha, chemin in manifeste), encoding="utf-8"
    )
    lignes = [entete_catalogue] + [f"{sha}\t{url}" for sha, url in catalogue]
    (drive / "catalogue-complet.tsv").write_text("\n".join(lignes) + "\n", encoding="utf-8")

    (racine / inventaire.MATRICE).write_text(json.dumps({"rows": matrice}), encoding="utf-8")

    corps = CALCULATEUR % {"promus": promus}
    if calculateur_echoue:
        corps = "import sys\nsys.exit(3)\n"
    (racine / inventaire.CALCULATEUR_PROMU).write_text(corps, encoding="utf-8")
    return racine, drive


def _ligne(sha: str, verdict: str = inventaire.VERDICT_CANDIDAT) -> dict:
    return {"content_sha256": sha, "verdict": verdict}


@pytest.fixture
def corpus_coherent(tmp_path: Path):
    a, b, c = _sha("a"), _sha("b"), _sha("c")
    return _poser_depot(
        tmp_path,
        manifeste=[
            (a, "01_EDUSCOL_OFFICIEL/LYCEE/a.pdf"),
            (b, "03_RESSOURCES_INTERACTIVES/GEOGEBRA/FICHIERS/b.ggb"),
            (c, "00_ADMIN/TREE.txt"),
        ],
        catalogue=[(a, "https://eduscol.education.gouv.fr/a")],
        matrice=[_ligne(a), _ligne(b, "BLOCKED_NO_URL_PROVENANCE")],
        promus=[a],
    )


def test_recense_les_zones_et_derive_le_perimetre_pedagogique(corpus_coherent):
    racine, drive = corpus_coherent
    etat = inventaire.construire(racine, drive)

    assert etat["manifest_entries"] == 3
    assert etat["pedagogical_scope"]["contenus"] == 2
    assert etat["pedagogical_scope"]["candidats_servables"] == 1
    assert etat["pedagogical_scope"]["promus"] == 1

    zones = {zone["zone"]: zone for zone in etat["zones"]}
    assert zones["00_ADMIN"]["role"] == "GESTION"
    assert zones["01_EDUSCOL_OFFICIEL"]["role"] == "PEDAGOGIQUE"
    assert zones["01_EDUSCOL_OFFICIEL"]["avec_url_de_provenance"] == 1
    assert zones["03_RESSOURCES_INTERACTIVES"]["avec_url_de_provenance"] == 0


def test_un_contenu_pedagogique_absent_de_la_matrice_est_nomme(tmp_path: Path):
    a, b = _sha("a"), _sha("b")
    racine, drive = _poser_depot(
        tmp_path,
        manifeste=[(a, "01_EDUSCOL_OFFICIEL/a.pdf"), (b, "01_EDUSCOL_OFFICIEL/b.pdf")],
        catalogue=[(a, "https://eduscol.education.gouv.fr/a")],
        matrice=[_ligne(a)],
        promus=[a],
    )
    etat = inventaire.construire(racine, drive)
    assert etat["pedagogical_scope"]["non_recenses_par_la_matrice"] == [b]


def test_un_contenu_promu_hors_du_drive_est_nomme(tmp_path: Path):
    a, absent = _sha("a"), _sha("f")
    racine, drive = _poser_depot(
        tmp_path,
        manifeste=[(a, "01_EDUSCOL_OFFICIEL/a.pdf")],
        catalogue=[(a, "https://eduscol.education.gouv.fr/a")],
        matrice=[_ligne(a), _ligne(absent)],
        promus=[a, absent],
    )
    etat = inventaire.construire(racine, drive)
    assert etat["promoted"]["hors_drive"] == [absent]
    assert etat["matrix"]["absentes_du_drive"] == [absent]


def test_un_promu_bloque_est_compte_comme_non_candidat(tmp_path: Path):
    a = _sha("a")
    racine, drive = _poser_depot(
        tmp_path,
        manifeste=[(a, "01_EDUSCOL_OFFICIEL/a.pdf")],
        catalogue=[(a, "https://eduscol.education.gouv.fr/a")],
        matrice=[_ligne(a, "BLOCKED_PII_HUMAN_REVIEW")],
        promus=[a],
    )
    etat = inventaire.construire(racine, drive)
    assert etat["promoted"]["non_candidats_servables"] == 1
    assert etat["promoted"]["non_candidats_par_verdict"] == {"BLOCKED_PII_HUMAN_REVIEW": 1}


def test_manifeste_absent_refuse(corpus_coherent):
    racine, drive = corpus_coherent
    (drive / "SHA256SUMS.txt").unlink()
    with pytest.raises(inventaire.EntreeManquante, match="SHA256SUMS"):
        inventaire.construire(racine, drive)


def test_manifeste_vide_refuse(corpus_coherent):
    racine, drive = corpus_coherent
    (drive / "SHA256SUMS.txt").write_text("   \n", encoding="utf-8")
    with pytest.raises(inventaire.EntreeManquante):
        inventaire.construire(racine, drive)


def test_ligne_de_manifeste_illisible_refusee(corpus_coherent):
    racine, drive = corpus_coherent
    (drive / "SHA256SUMS.txt").write_text("pas-un-sha  x.pdf\n", encoding="utf-8")
    with pytest.raises(inventaire.EntreeManquante, match="illisible"):
        inventaire.construire(racine, drive)


def test_colonne_de_catalogue_absente_refusee_en_nommant_ce_qui_a_ete_cherche(
    tmp_path: Path,
):
    a = _sha("a")
    racine, drive = _poser_depot(
        tmp_path,
        manifeste=[(a, "01_EDUSCOL_OFFICIEL/a.pdf")],
        catalogue=[(a, "https://eduscol.education.gouv.fr/a")],
        matrice=[_ligne(a)],
        promus=[a],
        entete_catalogue="sha256\tlien",
    )
    with pytest.raises(inventaire.EntreeManquante) as erreur:
        inventaire.construire(racine, drive)
    message = str(erreur.value)
    assert "url_source" in message and "lien" in message


def test_calculateur_promu_en_echec_refuse(corpus_coherent):
    racine, drive = corpus_coherent
    (racine / inventaire.CALCULATEUR_PROMU).write_text("import sys\nsys.exit(3)\n")
    with pytest.raises(inventaire.EntreeManquante, match="calculateur canonique"):
        inventaire.construire(racine, drive)


def test_ensemble_promu_vide_refuse(corpus_coherent):
    racine, drive = corpus_coherent
    (racine / inventaire.CALCULATEUR_PROMU).write_text(CALCULATEUR % {"promus": []})
    with pytest.raises(inventaire.EntreeManquante, match="vide"):
        inventaire.construire(racine, drive)


def test_calculateur_promu_absent_refuse(corpus_coherent):
    racine, drive = corpus_coherent
    (racine / inventaire.CALCULATEUR_PROMU).unlink()
    with pytest.raises(inventaire.EntreeManquante, match="calculateur canonique absent"):
        inventaire.construire(racine, drive)


def test_matrice_absente_refuse(corpus_coherent):
    racine, drive = corpus_coherent
    (racine / inventaire.MATRICE).unlink()
    with pytest.raises(inventaire.EntreeManquante):
        inventaire.construire(racine, drive)


def test_les_niveaux_non_mesures_sont_declares(corpus_coherent):
    racine, drive = corpus_coherent
    etat = inventaire.construire(racine, drive)
    assert "contenu ingéré" in etat["not_measured_here"]
    assert "contenu réellement servi en production" in etat["not_measured_here"]


def test_le_markdown_ne_prononce_aucun_chiffre_absent_de_l_etat(corpus_coherent):
    racine, drive = corpus_coherent
    etat = inventaire.construire(racine, drive)
    rendu = inventaire.rendre_markdown(etat)
    assert f"**{etat['pedagogical_scope']['contenus']}**" in rendu
    assert "Ne pas éditer à la main" in rendu


def test_entree_manquante_sort_en_code_2(corpus_coherent, tmp_path: Path):
    racine, drive = corpus_coherent
    (drive / "SHA256SUMS.txt").unlink()
    execution = subprocess.run(
        [
            sys.executable,
            str(RACINE / "scripts/go_live/build_drive_corpus_inventory.py"),
            "--drive-dir",
            str(drive),
        ],
        capture_output=True,
        text=True,
        env={"NEXUS_REPO_ROOT": str(racine), "PATH": "/usr/bin:/bin"},
    )
    assert execution.returncode == 2
    assert "ENTREE_MANQUANTE" in execution.stderr


def test_l_inventaire_ne_rend_aucun_verdict_de_servabilite(tmp_path: Path):
    """Il compte les verdicts de la matrice ; il n'en prononce jamais un.

    Cette épreuve tient la ligne `MATRIX_READER` de la baseline d'unicité
    d'autorité : l'inventaire lit la matrice pour en rendre compte, et un
    contenu qu'elle bloque ne peut pas ressortir candidat de son côté.
    """
    a, b, c, d = _sha("a"), _sha("b"), _sha("c"), _sha("d")
    bloquants = [
        "BLOCKED_PII_HUMAN_REVIEW",
        "BLOCKED_NO_URL_PROVENANCE",
        "NOT_INDEXABLE_BY_ROLE",
        "REFUSED_PROGRAM_INCOMPATIBLE",
    ]
    racine, drive = _poser_depot(
        tmp_path,
        manifeste=[
            (sha, f"01_EDUSCOL_OFFICIEL/{sha[:4]}.pdf") for sha in (a, b, c, d)
        ],
        catalogue=[(a, "https://eduscol.education.gouv.fr/a")],
        matrice=[
            _ligne(sha, verdict) for sha, verdict in zip((a, b, c, d), bloquants)
        ],
        promus=[a],
    )
    etat = inventaire.construire(racine, drive)

    # Aucun contenu bloqué par la matrice ne devient candidat ici.
    assert etat["pedagogical_scope"]["candidats_servables"] == 0
    # Et l'inventaire le signale plutôt que de le taire.
    assert etat["promoted"]["non_candidats_servables"] == 1


def test_le_module_ne_definit_aucun_verdict_de_servabilite():
    """Le seul verdict qu'il nomme est celui qu'il cherche, pas un qu'il crée."""
    source = (
        RACINE / "scripts/go_live/build_drive_corpus_inventory.py"
    ).read_text(encoding="utf-8")
    for interdit in (
        "BLOCKED_PII_HUMAN_REVIEW",
        "BLOCKED_NO_URL_PROVENANCE",
        "NOT_INDEXABLE_BY_ROLE",
        "REFUSED_PROGRAM_INCOMPATIBLE",
    ):
        assert interdit not in source, (
            f"{interdit} est écrit dans l'inventaire : il déciderait au lieu de compter"
        )
