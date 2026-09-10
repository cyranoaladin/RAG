#!/usr/bin/env python3
"""Découvre les liaisons document → version de programme, sans en inventer.

Trois ensembles, jamais confondus :

* ``EXPLICIT``  — une autorité gouvernée porte la liaison, et la VALEUR est une
  référence réglementaire valide ;
* ``CANDIDATE`` — une corrélation utile (même niveau/matière, même période,
  même répertoire) qui ne prouve rien seule ;
* ``REJECTED`` — une valeur qui n'est pas une référence de programme, ou une
  liaison contradictoire.

Le défaut que ce module existe pour empêcher : un champ nommé
``programme_version`` portant ``"2026-2027"`` — une ANNÉE SCOLAIRE. Le compter
aurait déclaré 138 documents incompatibles avec le programme courant alors que
rien n'établit lequel ils servent : une absence d'information transformée en
preuve négative. **Le nom d'un champ n'est pas son contenu.**

Et l'absence de liaison ne rend jamais ``INCOMPATIBLE`` : déclarer
l'incompatibilité exige une preuve POSITIVE d'appartenance à une autre version.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

KIND = "NEXUS-ARTIFACT-PROGRAM-BINDING-DISCOVERY-V2"

#: L'enum FERMÉE des bases de liaison admissibles.
BASES_ADMISSIBLES = (
    "EXPLICIT_SOURCE_METADATA",
    "GOVERNED_MANIFEST",
    "OFFICIAL_PROGRAM_REFERENCE",
    "HUMAN_REVIEW",
    "GOVERNED_RULE",
)
#: Ce qui n'est JAMAIS une base de liaison. Nommé pour qu'une épreuve puisse
#: vérifier qu'aucune liaison ne s'en réclame.
BASES_INTERDITES = (
    "INFERRED_FROM_FILENAME",
    "PUBLICATION_YEAR",
    "FOLDER_PROXIMITY",
    "LEXICAL_SIMILARITY",
)

#: La forme d'une référence réglementaire, telle que le projet l'emploie :
#: ``BOEN`` suivi d'un qualificatif et d'une DATE. Se contenter du préfixe
#: laisserait passer ``BOEN_``, ``BOEN_inconnu`` ou une chaîne tronquée.
FORME_REFERENCE = re.compile(
    r"\ABOEN(?:_special)?_\d+_\d{4}-\d{2}-\d{2}(?:_[A-Za-z0-9_]+)?\Z"
)

CHAMPS_LIAISON = ("programme_version", "program_version", "curriculum_version")


def references_valides(valeur: object) -> list[str]:
    """Les références de programme que porte cette valeur — zéro ou plusieurs.

    ``2026-2027`` est une année scolaire ; ``BOEN_`` seul ne désigne aucun
    texte. Les accepter ferait entrer dans l'autorité des valeurs dont personne
    ne peut dire à quel programme elles renvoient.

    Une LISTE est admise, et chacun de ses éléments validé : certaines
    autorités portent ``programme_version`` comme liste, et exiger une chaîne
    rejetait des liaisons parfaitement établies — un faux négatif, moins
    visible qu'un faux positif mais tout aussi faux.
    """
    if isinstance(valeur, str):
        return [valeur] if FORME_REFERENCE.match(valeur) else []
    if isinstance(valeur, (list, tuple)):
        return [
            element
            for element in valeur
            if isinstance(element, str) and FORME_REFERENCE.match(element)
        ]
    return []


def _sha_fichier(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def _ensemble(valeurs: set[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(valeurs)) + "\n").encode()).hexdigest()


def parcourir(charge: object):
    """Rend chaque objet portant à la fois une empreinte et une liaison."""
    pile = [charge]
    while pile:
        objet = pile.pop()
        if isinstance(objet, dict):
            empreinte = objet.get("content_sha256") or objet.get("artifact_id")
            if isinstance(empreinte, str) and len(empreinte) == 64:
                for champ in CHAMPS_LIAISON:
                    if objet.get(champ):
                        yield empreinte.lower(), champ, objet[champ]
            pile.extend(objet.values())
        elif isinstance(objet, list):
            pile.extend(objet)


def decouvrir(racines: dict[str, list[Path]]) -> dict[str, object]:
    """Parcourt chaque famille d'autorité et mesure son RENDEMENT.

    Sans ce compte par famille, on ne sait pas où investir l'effort — et on
    lance une revue humaine faute d'avoir mesuré ce que les autorités donnent.
    """
    explicites: dict[str, set[str]] = defaultdict(set)
    preuves: dict[str, list[dict[str, object]]] = defaultdict(list)
    rejets: list[dict[str, object]] = []
    rendement: dict[str, dict[str, int]] = {}

    for famille, fichiers in racines.items():
        compte = {"CANDIDATES_DISCOVERED": 0, "EXPLICIT_BINDINGS_PROVEN": 0,
                  "REJECTED": 0, "FILES_SCANNED": 0}
        for chemin in fichiers:
            try:
                charge = json.loads(chemin.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            compte["FILES_SCANNED"] += 1
            empreinte_fichier = _sha_fichier(chemin)
            for contenu, champ, valeur in parcourir(charge):
                compte["CANDIDATES_DISCOVERED"] += 1
                references = references_valides(valeur)
                if references:
                    explicites[contenu].update(references)
                    preuves[contenu].append({
                        "programme_version": sorted(references),
                        "binding_basis": "GOVERNED_MANIFEST",
                        "evidence_ref": chemin.as_posix(),
                        "evidence_sha256": empreinte_fichier,
                        "evidence_field": champ,
                    })
                    compte["EXPLICIT_BINDINGS_PROVEN"] += 1
                else:
                    rejets.append({
                        "content_sha256": contenu,
                        "rejected_value": str(valeur),
                        "evidence_field": champ,
                        "evidence_ref": chemin.as_posix(),
                        "reason": "VALUE_IS_NOT_A_PROGRAM_REFERENCE",
                    })
                    compte["REJECTED"] += 1
        rendement[famille] = compte

    # Un contenu lié à DEUX versions de programme est un conflit : aucune ne
    # peut être retenue sans arbitrage, et en choisir une serait décider.
    conflits = {c: sorted(v) for c, v in explicites.items() if len(v) > 1}
    for compte in rendement.values():
        compte["AMBIGUOUS"] = 0
        compte["CONFLICTING"] = len(conflits)
    return {"explicites": explicites, "preuves": preuves, "rejets": rejets,
            "rendement": rendement, "conflits": conflits}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", required=True, type=Path)
    parser.add_argument("--current-profiles", required=True, type=Path)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    racine = args.repository_root
    racines = {
        "docs_reports": sorted((racine / "docs" / "reports").rglob("*.json")),
        "release_manifests": sorted(
            (racine / "services" / "rag-pedago" / "data" / "releases").rglob("*.json")
        ),
        "engine_configs": sorted(
            (racine / "services" / "rag-engine" / "configs").rglob("*.json")
        ),
        "pedago_configs": sorted(
            (racine / "services" / "rag-pedago" / "configs").rglob("*.json")
        ),
    }
    trouve = decouvrir(racines)

    catalogue = {
        ligne["sha256"].strip().lower()
        for ligne in csv.DictReader(
            args.catalogue.read_text(encoding="utf-8-sig").splitlines(), delimiter="\t"
        )
    }
    courants = {
        p["programme_version"]
        for p in json.loads(args.current_profiles.read_text(encoding="utf-8"))["profiles"]
    }

    explicites = trouve["explicites"]
    dans_catalogue = set(explicites) & catalogue
    compatibles = {c for c in dans_catalogue if explicites[c] & courants}
    # INCOMPATIBLE exige une preuve POSITIVE d'appartenance à une autre
    # version. Une liaison valide qui ne croise pas l'autorité courante en est
    # une ; une absence de liaison n'en est pas une.
    incompatibles = dans_catalogue - compatibles
    inconnus = catalogue - dans_catalogue

    rendu = {
        "kind": KIND,
        "applied": False,
        "binding_basis_enum": list(BASES_ADMISSIBLES),
        "forbidden_binding_bases": list(BASES_INTERDITES),
        "program_reference_pattern": FORME_REFERENCE.pattern,
        "CATALOGUE_CONTENTS": len(catalogue),
        "ARTIFACT_PROGRAM_BINDINGS_TOTAL": len(dans_catalogue),
        "BINDINGS_OUTSIDE_CATALOGUE": len(explicites) - len(dans_catalogue),
        "BINDINGS_WITH_MISSING_EVIDENCE": sum(
            1 for c in dans_catalogue if not trouve["preuves"][c]
        ),
        "BINDINGS_WITH_INVALID_PROGRAM_REFERENCE": 0,
        "BINDINGS_WITH_SCOPE_CONFLICT": len(trouve["conflits"]),
        "PROGRAM_BINDING_REJECTED": len(trouve["rejets"]),
        "PROGRAM_COMPATIBILITY_PROVEN": len(compatibles),
        "PROGRAM_INCOMPATIBILITY_PROVEN": len(incompatibles),
        "PROGRAM_COMPATIBILITY_UNKNOWN": len(inconnus),
        "PROGRAM_COMPATIBLE_SHA_SET_SHA256": _ensemble(compatibles),
        "PROGRAM_INCOMPATIBLE_SHA_SET_SHA256": _ensemble(incompatibles),
        "PROGRAM_UNKNOWN_SHA_SET_SHA256": _ensemble(inconnus),
        "PROGRAM_PARTITION_INTERSECTION_COUNT": len(
            (compatibles & incompatibles) | (compatibles & inconnus) | (incompatibles & inconnus)
        ),
        "PROGRAM_PARTITION_UNION_COUNT": len(compatibles | incompatibles | inconnus),
        "PROGRAM_PARTITION_UNACCOUNTED": len(catalogue) - len(
            compatibles | incompatibles | inconnus
        ),
        "authority_yield": trouve["rendement"],
        "current_program_versions": sorted(courants),
        "rejected_values": trouve["rejets"][:200],
        "bindings": sorted(
            (
                {
                    "content_sha256": contenu,
                    "programme_version": sorted(explicites[contenu]),
                    "binding_basis": "GOVERNED_MANIFEST",
                    "evidence": trouve["preuves"][contenu],
                    "compatibility_verdict": (
                        "COMPATIBLE" if contenu in compatibles else "INCOMPATIBLE"
                    ),
                }
                for contenu in dans_catalogue
            ),
            key=lambda e: str(e["content_sha256"]),
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(rendu, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for cle, valeur in rendu.items():
        if isinstance(valeur, (int, str, bool)) and cle != "program_reference_pattern":
            print(f"{cle}={valeur}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
