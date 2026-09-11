#!/usr/bin/env python3
"""Recense le corpus Drive et le confronte aux autorités du dépôt.

Ce script existe parce qu'une question restait sans réponse mesurée : le dépôt
raisonnait sur 2530 contenus sans jamais avoir regardé la source documentaire
d'où ils viennent. Tant que personne n'avait confronté les deux, « le corpus
est couvert » restait une croyance.

Il ne prononce aucun chiffre écrit à la main. Chaque total est dérivé du
manifeste scellé du Drive, du catalogue de provenance, de la matrice de
servabilité et de l'ensemble promu canonique. Une entrée manquante est refusée
en la nommant, jamais traitée comme un zéro : un zéro non mesuré et un zéro
mesuré se ressemblent dans un rapport et ne disent pas la même chose.

Ce que ce script établit, et ce qu'il n'établit pas :

- il établit la présence d'un contenu dans le Drive et son recensement par la
  matrice ;
- il n'établit PAS que ce contenu est ingéré, indexé, ni servi. Ces niveaux
  relèvent d'une base de données, pas d'un manifeste, et aucun d'eux n'est
  observable depuis le dépôt.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

KIND = "NEXUS-DRIVE-CORPUS-INVENTORY-V1"

RACINE_DRIVE = "NEXUS_RAG_GDRIVE_READY"

#: Zones dont le contenu est candidat à une ingestion pédagogique.
ZONES_PEDAGOGIQUES = (
    "01_EDUSCOL_OFFICIEL",
    "02_NEXUS_DIAGNOSTICS",
    "03_RESSOURCES_INTERACTIVES",
    "04_COMPLEMENTS_PEDAGOGIQUES",
)

#: Zones de traçabilité et d'administration. Le README du corpus les exclut
#: explicitement de l'ingestion : elles servent à prouver, pas à enseigner.
ZONES_DE_GESTION = ("00_ADMIN", "00_INDEX_PROVENANCE")

MATRICE = "docs/reports/handoff/servability_matrix_v1.json"
CALCULATEUR_PROMU = "scripts/qualification/compute_promoted_content_set.py"

VERDICT_CANDIDAT = "CANDIDATE_NO_BLOCKING_DIMENSION"


class EntreeManquante(RuntimeError):
    """Une entrée nécessaire au calcul est absente ou inexploitable."""


def racine_depot() -> Path:
    surcharge = os.environ.get("NEXUS_REPO_ROOT")
    if surcharge:
        return Path(surcharge).resolve()
    return Path(__file__).resolve().parents[2]


def _lire(chemin: Path) -> str:
    if not chemin.is_file():
        raise EntreeManquante(f"entrée absente : {chemin}")
    texte = chemin.read_text(encoding="utf-8")
    if not texte.strip():
        raise EntreeManquante(f"entrée vide : {chemin}")
    return texte


def lire_manifeste(chemin: Path) -> list[tuple[str, str]]:
    """Retourne les paires (sha256, chemin relatif) du manifeste scellé."""
    entrees: list[tuple[str, str]] = []
    for numero, ligne in enumerate(_lire(chemin).splitlines(), start=1):
        if not ligne.strip():
            continue
        sha, separateur, reste = ligne.partition("  ")
        if not separateur or len(sha) != 64:
            raise EntreeManquante(f"{chemin}:{numero} : ligne de manifeste illisible")
        entrees.append((sha, reste.strip()))
    if not entrees:
        raise EntreeManquante(f"manifeste sans aucune entrée : {chemin}")
    return entrees


def zone_de(chemin_relatif: str) -> str:
    tete, separateur, _ = chemin_relatif.partition("/")
    if not separateur:
        return "RACINE"
    return tete


def lire_catalogue(chemin: Path) -> dict[str, set[str]]:
    """Associe chaque sha256 du catalogue à ses URL de provenance."""
    lignes = _lire(chemin).splitlines()
    entete = lignes[0].split("\t")
    for colonne in ("sha256", "url_source"):
        if colonne not in entete:
            raise EntreeManquante(
                f"{chemin} : colonne « {colonne} » absente ; colonnes vues : {entete}"
            )
    i_sha = entete.index("sha256")
    i_url = entete.index("url_source")
    urls: dict[str, set[str]] = {}
    for ligne in lignes[1:]:
        if not ligne.strip():
            continue
        champs = ligne.split("\t")
        if len(champs) <= max(i_sha, i_url):
            continue
        url = champs[i_url].strip()
        if url:
            urls.setdefault(champs[i_sha].strip(), set()).add(url)
    if not urls:
        raise EntreeManquante(f"catalogue sans aucune URL exploitable : {chemin}")
    return urls


def lire_matrice(racine: Path) -> dict[str, dict]:
    chemin = racine / MATRICE
    lignes = json.loads(_lire(chemin)).get("rows")
    if not lignes:
        raise EntreeManquante(f"matrice sans lignes : {chemin}")
    return {ligne["content_sha256"]: ligne for ligne in lignes}


def lire_ensemble_promu(racine: Path) -> set[str]:
    """Délègue au calculateur canonique. Aucune autre lecture n'est admise."""
    import subprocess
    import tempfile

    chemin = racine / CALCULATEUR_PROMU
    if not chemin.is_file():
        raise EntreeManquante(f"calculateur canonique absent : {chemin}")
    with tempfile.TemporaryDirectory() as repertoire:
        sortie = Path(repertoire) / "promu.json"
        execution = subprocess.run(
            [sys.executable, str(chemin), "--output", str(sortie)],
            cwd=str(racine),
            capture_output=True,
            text=True,
        )
        if execution.returncode != 0:
            raise EntreeManquante(
                f"le calculateur canonique a échoué ({execution.returncode}) : "
                f"{execution.stderr.strip()[:400]}"
            )
        promus = set(json.loads(_lire(sortie))["content_sha256"])
    if not promus:
        raise EntreeManquante("le calculateur canonique retourne un ensemble promu vide")
    return promus


def construire(racine: Path, repertoire_drive: Path) -> dict:
    manifeste = lire_manifeste(repertoire_drive / "SHA256SUMS.txt")
    catalogue = lire_catalogue(repertoire_drive / "catalogue-complet.tsv")
    matrice = lire_matrice(racine)
    promus = lire_ensemble_promu(racine)

    par_zone: dict[str, set[str]] = {}
    fichiers_par_zone: Counter[str] = Counter()
    for sha, chemin_relatif in manifeste:
        zone = zone_de(chemin_relatif)
        par_zone.setdefault(zone, set()).add(sha)
        fichiers_par_zone[zone] += 1

    pedagogique: set[str] = set()
    for zone in ZONES_PEDAGOGIQUES:
        pedagogique |= par_zone.get(zone, set())

    tous = {sha for sha, _ in manifeste}
    connus_matrice = set(matrice)

    zones = []
    for zone in sorted(par_zone):
        contenus = par_zone[zone]
        verdicts = Counter(
            matrice[sha]["verdict"] for sha in contenus if sha in matrice
        )
        zones.append(
            {
                "zone": zone,
                "role": (
                    "PEDAGOGIQUE"
                    if zone in ZONES_PEDAGOGIQUES
                    else "GESTION"
                    if zone in ZONES_DE_GESTION
                    else "RACINE"
                ),
                "fichiers": fichiers_par_zone[zone],
                "contenus_uniques": len(contenus),
                "recenses_par_la_matrice": len(contenus & connus_matrice),
                "promus": len(contenus & promus),
                "avec_url_de_provenance": len(contenus & set(catalogue)),
                "verdicts": dict(sorted(verdicts.items())),
            }
        )

    candidats = {
        sha
        for sha in pedagogique
        if matrice.get(sha, {}).get("verdict") == VERDICT_CANDIDAT
    }
    promus_non_candidats = sorted(promus - candidats)

    return {
        "kind": KIND,
        "drive_root_folder": RACINE_DRIVE,
        "manifest_entries": len(manifeste),
        "distinct_content_sha256": len(tous),
        "zones": zones,
        "pedagogical_scope": {
            "contenus": len(pedagogique),
            "recenses_par_la_matrice": len(pedagogique & connus_matrice),
            "non_recenses_par_la_matrice": sorted(pedagogique - connus_matrice),
            "candidats_servables": len(candidats),
            "promus": len(pedagogique & promus),
        },
        "matrix": {
            "lignes": len(matrice),
            "absentes_du_drive": sorted(connus_matrice - tous),
            "hors_zone_pedagogique": sorted(connus_matrice - pedagogique),
        },
        "promoted": {
            "total": len(promus),
            "hors_drive": sorted(promus - tous),
            "hors_zone_pedagogique": sorted(promus - pedagogique),
            "non_candidats_servables": len(promus_non_candidats),
            "non_candidats_par_verdict": dict(
                sorted(
                    Counter(
                        matrice[sha]["verdict"]
                        for sha in promus_non_candidats
                        if sha in matrice
                    ).items()
                )
            ),
        },
        "url_provenance": {
            "contenus_couverts_par_le_catalogue": len(set(catalogue) & tous),
            "zone_pedagogique_sans_url": sorted(pedagogique - set(catalogue)),
        },
        "not_measured_here": [
            "contenu ingéré",
            "contenu exploitable par recherche",
            "contenu réellement servi en production",
        ],
    }


def rendre_markdown(etat: dict) -> str:
    lignes = [
        "# Inventaire du corpus Drive",
        "",
        "Document dérivé. Ne pas éditer à la main :",
        "`scripts/go_live/build_drive_corpus_inventory.py` le régénère.",
        "",
        f"Racine Drive : `{etat['drive_root_folder']}`",
        "",
        f"- entrées du manifeste scellé : **{etat['manifest_entries']}**",
        f"- contenus distincts (SHA-256) : **{etat['distinct_content_sha256']}**",
        "",
        "## Zones",
        "",
        "| zone | rôle | fichiers | contenus | recensés matrice | URL provenance | promus |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for zone in etat["zones"]:
        lignes.append(
            f"| `{zone['zone']}` | {zone['role']} | {zone['fichiers']} | "
            f"{zone['contenus_uniques']} | {zone['recenses_par_la_matrice']} | "
            f"{zone['avec_url_de_provenance']} | {zone['promus']} |"
        )

    perimetre = etat["pedagogical_scope"]
    lignes += [
        "",
        "## Périmètre pédagogique",
        "",
        f"- contenus : **{perimetre['contenus']}**",
        f"- recensés par la matrice : **{perimetre['recenses_par_la_matrice']}**",
        f"- candidats servables : **{perimetre['candidats_servables']}**",
        f"- promus : **{perimetre['promus']}**",
        "",
        "## Confrontation",
        "",
        f"- lignes de matrice absentes du Drive : "
        f"**{len(etat['matrix']['absentes_du_drive'])}**",
        f"- contenus pédagogiques non recensés par la matrice : "
        f"**{len(perimetre['non_recenses_par_la_matrice'])}**",
        f"- contenus promus hors du Drive : **{len(etat['promoted']['hors_drive'])}**",
        f"- contenus promus qui ne sont pas candidats servables : "
        f"**{etat['promoted']['non_candidats_servables']}**",
        "",
        "## Ce que ce document ne mesure pas",
        "",
    ]
    lignes += [f"- {niveau}" for niveau in etat["not_measured_here"]]
    lignes.append("")
    return "\n".join(lignes)


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--drive-dir",
        required=True,
        help="répertoire contenant SHA256SUMS.txt et catalogue-complet.tsv du Drive",
    )
    analyseur.add_argument("--output-json", default="docs/reports/go_live/drive_corpus_inventory.json")
    analyseur.add_argument("--output-md", default="docs/reports/go_live/DRIVE_CORPUS_INVENTORY.md")
    arguments = analyseur.parse_args(argv)

    racine = racine_depot()
    try:
        etat = construire(racine, Path(arguments.drive_dir))
    except EntreeManquante as erreur:
        print(f"ENTREE_MANQUANTE: {erreur}", file=sys.stderr)
        return 2

    chemin_json = racine / arguments.output_json
    chemin_md = racine / arguments.output_md
    chemin_json.parent.mkdir(parents=True, exist_ok=True)
    chemin_json.write_text(
        json.dumps(etat, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    chemin_md.write_text(rendre_markdown(etat), encoding="utf-8")
    print(f"écrit : {chemin_json}")
    print(f"écrit : {chemin_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
