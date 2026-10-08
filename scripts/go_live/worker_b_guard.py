#!/usr/bin/env python3
"""Garde « aucun Worker B de publication actif » avant la migration 020.

Lit sur l'entrée standard le JSON de ``docker inspect`` des conteneurs EN COURS
et refuse (code 4) si l'un d'eux est un Worker B de publication, identifié par
des propriétés que le nom seul ne peut pas masquer :

* l'image du runtime de publication (``rag-multilevel-worker-production``,
  quel que soit le digest : les anciens Worker B V4 en ont d'autres) ;
* le module lancé (``multilevel_publication_resume_cli``) ;
* les noms canoniques (``nexus-v4-worker-b…``, ``nexus-hggsp-successor-worker-b…``).

Un service sans rapport (Celery, NPC…) ne bloque pas, même si son nom contient
« worker ». Tout ce qui est ambigu est refusé (code 5) : entrée vide ou non
JSON, conteneur sans ``Config``, champ d'identité absent.

Codes : 0 aucun Worker B actif ; 4 Worker B identifié ; 5 inspection ambiguë.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

IMAGE_RUNTIME = "rag-multilevel-worker-production"
MODULE_PUBLICATION = "multilevel_publication_resume_cli"
NOMS_CANONIQUES = re.compile(r"^nexus-(v4|hggsp)[a-z0-9-]*worker-b(-|$)")


class InspectionAmbigue(ValueError):
    """L'inspection ne permet pas de conclure : la garde refuse."""


def _texte(valeur: Any, champ: str) -> str:
    if valeur is None:
        return ""
    if isinstance(valeur, str):
        return valeur
    if isinstance(valeur, list) and all(isinstance(x, str) for x in valeur):
        return " ".join(valeur)
    raise InspectionAmbigue(f"champ {champ} de forme inattendue")


def raisons_worker_b(conteneur: Any) -> list[str]:
    """Raisons pour lesquelles ce conteneur est un Worker B ; [] s'il n'en est pas un."""
    if not isinstance(conteneur, dict) or not isinstance(conteneur.get("Config"), dict):
        raise InspectionAmbigue("conteneur sans Config")
    nom = conteneur.get("Name")
    if not isinstance(nom, str) or not nom:
        raise InspectionAmbigue("conteneur sans nom")
    config = conteneur["Config"]
    image = _texte(config.get("Image"), "Config.Image")
    commande = " ".join((_texte(config.get("Entrypoint"), "Config.Entrypoint"),
                         _texte(config.get("Cmd"), "Config.Cmd")))
    if not image and not commande.strip():
        raise InspectionAmbigue(f"conteneur {nom} sans image ni commande")
    raisons = []
    if NOMS_CANONIQUES.match(nom.lstrip("/")):
        raisons.append("nom canonique de Worker B")
    if IMAGE_RUNTIME in image:
        raisons.append("image du runtime de publication")
    if MODULE_PUBLICATION in commande:
        raisons.append("module de publication lancé")
    return raisons


def evaluer(brut: str) -> tuple[int, list[str]]:
    """(code, lignes de diagnostic) pour la sortie de ``docker inspect``."""
    try:
        conteneurs = json.loads(brut)
    except ValueError:
        return 5, ["INSPECTION_AMBIGUE : sortie de docker inspect illisible"]
    if not isinstance(conteneurs, list) or not conteneurs:
        return 5, ["INSPECTION_AMBIGUE : aucune inspection exploitable"]
    trouves, ambigus = [], []
    for conteneur in conteneurs:
        try:
            raisons = raisons_worker_b(conteneur)
        except InspectionAmbigue as exc:
            ambigus.append(str(exc))
            continue
        if raisons:
            trouves.append(f"{conteneur['Name'].lstrip('/')} ({', '.join(raisons)})")
    if trouves:
        return 4, ["WORKER_ACTIF : aucune migration pendant un Worker B : " + "; ".join(trouves)]
    if ambigus:
        return 5, ["INSPECTION_AMBIGUE : " + "; ".join(ambigus)]
    return 0, []


def main() -> int:
    code, lignes = evaluer(sys.stdin.read())
    for ligne in lignes:
        print(ligne, file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
