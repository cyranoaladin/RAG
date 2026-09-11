#!/usr/bin/env python3
"""Réacquiert les contenus non-PDF depuis le Drive et vérifie leur identité.

Le dépôt portait déjà les demandes de réacquisition — identifiant Drive,
empreinte attendue, taille attendue — mais personne n'avait exécuté la
vérification. Le compteur restait à zéro, et la raison affichée devenait
fausse avec le temps : ce n'est pas l'identifiant qui manquait, c'est la
confrontation des octets à l'empreinte attendue.

Ce script fait cette confrontation et rien d'autre.

Ce qu'il prouve : les octets servis par le Drive pour un identifiant donné ont
l'empreinte et la taille que le manifeste attendait.

Ce qu'il ne prouve PAS, et qu'il ne faut pas lui faire dire :

- il ne prouve pas qu'une copie durable est conservée. Un répertoire de
  destination éphémère reste éphémère ; la conservation est une décision de
  gouvernance sur un emplacement, pas un effet de bord de ce script ;
- il ne prouve pas la provenance : savoir qu'un fichier est dans le Drive ne
  dit pas de quelle URL institutionnelle il provient ;
- il ne rend rien servable, ingéré, ni recherchable.

Un écart d'empreinte n'est jamais toléré ni réparé silencieusement : le
fichier est refusé et nommé.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

KIND = "NEXUS-NON-PDF-REACQUISITION-AUDIT-V1"

MANIFESTE = "docs/reports/handoff/non_pdf_reacquisition_manifest.json"

MODELE_URL = "https://drive.google.com/uc?export=download&id={identifiant}"

VERDICT_CONFORME = "CONFORME"
VERDICT_NON_CONFORME = "NON_CONFORME"

ECHEC_TELECHARGEMENT = "FETCH_FAILED"
ECART_EMPREINTE = "SHA256_MISMATCH"
ECART_TAILLE = "SIZE_MISMATCH"
VERIFIE = "VERIFIED"


class EntreeManquante(RuntimeError):
    """Une entrée nécessaire au calcul est absente ou inexploitable."""


def racine_depot() -> Path:
    surcharge = os.environ.get("NEXUS_REPO_ROOT")
    if surcharge:
        return Path(surcharge).resolve()
    return Path(__file__).resolve().parents[2]


def telecharger(identifiant: str, destination: Path) -> None:
    """Récupère un objet Drive public. Isolé pour être substituable en test."""
    subprocess.run(
        [
            "curl",
            "-sL",
            "--fail",
            "--max-time",
            "180",
            MODELE_URL.format(identifiant=identifiant),
            "-o",
            str(destination),
        ],
        check=False,
    )


def lire_manifeste(racine: Path) -> list[dict]:
    chemin = racine / MANIFESTE
    if not chemin.is_file():
        raise EntreeManquante(f"manifeste de réacquisition absent : {chemin}")
    document = json.loads(chemin.read_text(encoding="utf-8"))
    demandes = document.get("requests")
    if not demandes:
        raise EntreeManquante(f"manifeste sans aucune demande : {chemin}")
    for numero, demande in enumerate(demandes, start=1):
        for champ in ("drive_file_id", "expected_content_sha256", "expected_size"):
            if not demande.get(champ):
                raise EntreeManquante(
                    f"{chemin} : demande {numero} sans champ « {champ} »"
                )
    return demandes


def verifier(
    racine: Path,
    destination: Path,
    *,
    telechargeur=telecharger,
) -> dict:
    demandes = lire_manifeste(racine)
    document = json.loads((racine / MANIFESTE).read_text(encoding="utf-8"))
    acceptation = document.get("acceptance") or {}

    destination.mkdir(parents=True, exist_ok=True)
    resultats: list[dict] = []
    for demande in demandes:
        identifiant = demande["drive_file_id"]
        attendu = demande["expected_content_sha256"]
        taille_attendue = int(demande["expected_size"])
        fichier = destination / identifiant

        if not fichier.exists() or fichier.stat().st_size == 0:
            telechargeur(identifiant, fichier)

        if not fichier.exists() or fichier.stat().st_size == 0:
            resultats.append({"drive_file_id": identifiant, "status": ECHEC_TELECHARGEMENT})
            continue

        octets = fichier.read_bytes()
        obtenu = hashlib.sha256(octets).hexdigest()
        if obtenu != attendu:
            resultats.append(
                {
                    "drive_file_id": identifiant,
                    "status": ECART_EMPREINTE,
                    "expected_content_sha256": attendu,
                    "observed_content_sha256": obtenu,
                }
            )
            continue
        if len(octets) != taille_attendue:
            resultats.append(
                {
                    "drive_file_id": identifiant,
                    "status": ECART_TAILLE,
                    "expected_size": taille_attendue,
                    "observed_size": len(octets),
                }
            )
            continue
        resultats.append({"drive_file_id": identifiant, "status": VERIFIE})

    def compter(statut: str) -> int:
        return sum(1 for resultat in resultats if resultat["status"] == statut)

    verifies = compter(VERIFIE)
    mesures = {
        "NON_PDF_REQUESTS": len(demandes),
        "REACQUIRED_NON_PDF": verifies,
        "SHA256_MISMATCH": compter(ECART_EMPREINTE),
        "SIZE_MISMATCH": compter(ECART_TAILLE),
        "FETCH_FAILED": compter(ECHEC_TELECHARGEMENT),
    }

    # Une seule condition, et elle porte sur les résultats eux-mêmes : toute
    # demande doit être vérifiée. Compter les échecs par catégorie sert au
    # rapport, pas au verdict — un statut ajouté plus tard sans compteur
    # dédié ne doit pas pouvoir passer pour une conformité.
    # `bool(resultats)` est une redondance assumée : `lire_manifeste` refuse
    # déjà un manifeste sans demande, donc ce cas n'est pas atteignable par
    # l'API publique et aucun test ne peut l'en distinguer. La garde reste
    # parce qu'un `all([])` vaut True, et qu'un ensemble vide ne doit jamais
    # pouvoir se lire comme une réussite.
    toutes_verifiees = bool(resultats) and all(
        resultat["status"] == VERIFIE for resultat in resultats
    )
    # Les critères que le manifeste se donne sont opposables au résultat.
    acceptation_respectee = all(
        mesures.get(critere) == valeur
        for critere, valeur in acceptation.items()
        if critere in mesures
    )
    conforme = toutes_verifiees and acceptation_respectee

    return {
        "kind": KIND,
        "measurements": mesures,
        "acceptance_criteria": acceptation,
        "verdict": VERDICT_CONFORME if conforme else VERDICT_NON_CONFORME,
        "failures": [r for r in resultats if r["status"] != VERIFIE],
        "durable_copy_retained": False,
        "durable_copy_note": (
            "La conservation durable est une décision de gouvernance sur un "
            "emplacement. Ce rapport atteste une vérification d'identité, pas "
            "une rétention."
        ),
        "proves_nothing_about": [
            "provenance URL du contenu",
            "servabilité",
            "ingestion",
            "exploitabilité par recherche",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--destination", required=True)
    analyseur.add_argument(
        "--output",
        default="docs/reports/go_live/non_pdf_drive_reacquisition_audit.json",
    )
    arguments = analyseur.parse_args(argv)

    racine = racine_depot()
    try:
        rapport = verifier(racine, Path(arguments.destination))
    except EntreeManquante as erreur:
        print(f"ENTREE_MANQUANTE: {erreur}", file=sys.stderr)
        return 2

    chemin = racine / arguments.output
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(rapport, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"écrit : {chemin}")
    print(json.dumps(rapport["measurements"], ensure_ascii=False))
    return 0 if rapport["verdict"] == VERDICT_CONFORME else 1


if __name__ == "__main__":
    raise SystemExit(main())
