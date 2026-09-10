#!/usr/bin/env python3
"""Résout les citations ATTRIBUÉES contre l'autorité d'applicabilité courante.

Seules les occurrences dont le scope est établi par structure explicite entrent
ici. Une occurrence ``UNATTRIBUTABLE`` n'est pas résolue : elle reste
``UNKNOWN``, et ne devient jamais ``INCOMPATIBLE``. C'est la règle qui avait
manqué aux 66 liaisons retirées — citer un programme n'est pas relever de ce
programme, et ne pas savoir n'est pas être incompatible.

La sortie est un verdict PÉDAGOGIQUE. Elle ne produit aucun placement
d'autorisation : ``rag_artifact_placements`` reste seule autorité d'accès.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import psycopg
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag_pedago.governance.applicabilite_programme import (  # noqa: E402
    STATUTS_OPPOSABLES,
)
from rag_pedago.governance.attribution_citation import (  # noqa: E402
    ATTRIBUE,
    MULTI_SCOPE,
)

COURANTE = "CITED_REFERENCE_IS_CURRENT_FOR_SCOPE"
REMPLACEE = "CITED_REFERENCE_SUPERSEDED_FOR_SCOPE"
HORS_AUTORITE = "CITED_REFERENCE_NOT_IN_SCOPE_AUTHORITY"
AUTORITE_INCONNUE = "SCOPE_AUTHORITY_UNKNOWN"

COMPATIBLE = "COMPATIBLE"
INCOMPATIBLE = "INCOMPATIBLE"
MIXTE = "MIXED"
INCONNU = "UNKNOWN"


def statut_opposable(chemin_preuve: Path, reference: str) -> tuple[str, bool]:
    """Le niveau de preuve de l'autorité qui remplace cette référence.

    Une incompatibilité ne se prononce que sur une applicabilité VÉRIFIÉE. Un
    fait seulement DÉCLARÉ nourrit une hypothèse ; il ne condamne pas un
    artefact. Sans ce filtre, le verdict aurait la même forme quel que soit son
    niveau de preuve, et un lecteur ne pourrait plus les distinguer.
    """
    document = yaml.safe_load(chemin_preuve.read_text(encoding="utf-8"))
    for valeur in document.values():
        if not isinstance(valeur, dict):
            continue
        if valeur.get("official_reference") == reference:
            statut = str(valeur.get("evidence_status", ""))
            return statut, statut in STATUTS_OPPOSABLES
    return "NO_SEALED_EVIDENCE", False


def charger_autorite(chemin: Path) -> list[dict]:
    """Aplatit le seed en entrées (niveau exact, matière) — jamais en cycle."""
    document = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    entrees: list[dict] = []
    for cle, valeur in document.items():
        if not isinstance(valeur, list):
            continue
        for entree in valeur:
            if not isinstance(entree, dict) or not entree.get("matiere"):
                continue
            for niveau in entree.get("niveau_exact") or []:
                entrees.append({
                    "groupe": cle,
                    "niveau": niveau,
                    "matiere": entree["matiere"],
                    "modality": entree.get("modality"),
                    "official_reference": entree.get("official_reference"),
                    "supersedes": entree.get("supersedes") or [],
                    "applicability": entree.get("applicability"),
                })
    return entrees


def resoudre_occurrence(reference: str, niveau: str, matiere: str,
                        autorite: list[dict]) -> tuple[str, list[str]]:
    candidats = [e for e in autorite if e["niveau"] == niveau and e["matiere"] == matiere]
    if not candidats:
        return AUTORITE_INCONNUE, []
    references = [e["official_reference"] for e in candidats if e["official_reference"]]
    remplacees = {r for e in candidats for r in e["supersedes"]}
    if reference in references:
        return COURANTE, sorted(set(references))
    if reference in remplacees:
        return REMPLACEE, sorted(set(references))
    return HORS_AUTORITE, sorted(set(references))


def main() -> int:
    parseur = argparse.ArgumentParser()
    parseur.add_argument("--attributions", type=Path, required=True)
    parseur.add_argument("--autorite", type=Path, required=True)
    parseur.add_argument("--preuve-applicabilite", type=Path, required=True)
    parseur.add_argument("--sortie", type=Path, required=True)
    parseur.add_argument("--dsn", default=os.environ.get("DRIVE_STAGING_DSN"))
    arguments = parseur.parse_args()

    attributions = json.loads(arguments.attributions.read_text(encoding="utf-8"))
    autorite = charger_autorite(arguments.autorite)

    artefacts = sorted({o["content_sha256"] for o in attributions["occurrences"]})
    metadonnees: dict[str, dict] = {}
    with psycopg.connect(arguments.dsn) as connexion:
        for identifiant, niveau, matiere, nature in connexion.execute(
            "select artifact_id, niveau, matiere, nature from drive_staging.artifacts"
            " where artifact_id = any(%s)", (artefacts,),
        ).fetchall():
            metadonnees[identifiant] = {"niveau": niveau, "matiere": matiere, "nature": nature}

    resolutions = []
    for occurrence in attributions["occurrences"]:
        if occurrence["disposition"] not in (ATTRIBUE, MULTI_SCOPE):
            continue
        meta = metadonnees[occurrence["content_sha256"]]
        for niveau in occurrence["attributed_scope_levels"]:
            verdict, references = resoudre_occurrence(
                occurrence["normalized_reference"], niveau, meta["matiere"], autorite)
            # Le remplacement n'est retenu que si l'autorité REMPLAÇANTE porte
            # une applicabilité vérifiée. Sinon le fait existe, mais il n'est
            # pas opposable, et le verdict reste inconnu.
            statuts = [statut_opposable(arguments.preuve_applicabilite, r) for r in references]
            opposable = bool(statuts) and all(o for _s, o in statuts)
            if verdict == REMPLACEE and not opposable:
                verdict = AUTORITE_INCONNUE
            resolutions.append({
                "authority_evidence_status": sorted({s for s, _o in statuts}) or ["NO_AUTHORITY"],
                "authority_opposable": opposable,
                "reference_occurrence_id": occurrence["reference_occurrence_id"],
                "content_sha256": occurrence["content_sha256"],
                "normalized_reference": occurrence["normalized_reference"],
                "attributed_scope_level": niveau,
                "matiere": meta["matiere"],
                "resolution": verdict,
                "authority_current_references": references,
                "attribution_basis": occurrence["attribution_basis"],
            })

    # Agrégation par artefact. MIXED n'existe que si des scopes RÉELLEMENT
    # différents divergent — jamais parce qu'une partie est inconnue.
    par_artefact: dict[str, set[str]] = defaultdict(set)
    for resolution in resolutions:
        par_artefact[resolution["content_sha256"]].add(resolution["resolution"])

    verdicts: dict[str, str] = {}
    for artefact in artefacts:
        etats = par_artefact.get(artefact, set())
        connus = etats - {AUTORITE_INCONNUE, HORS_AUTORITE}
        if not connus:
            verdicts[artefact] = INCONNU
        elif connus == {COURANTE}:
            verdicts[artefact] = COMPATIBLE
        elif connus == {REMPLACEE}:
            verdicts[artefact] = INCOMPATIBLE
        else:
            verdicts[artefact] = MIXTE

    comptes = Counter(verdicts.values())
    rapport = {
        "kind": "NEXUS-CITATION-SCOPE-RESOLUTION-V1",
        "applied": False,
        "sealed_applicability_evidence": str(arguments.preuve_applicabilite.name),
        "seed_applicability_evidence_status": yaml.safe_load(
            arguments.autorite.read_text(encoding="utf-8"))["applicability_evidence_status"],
        "resolved_from": attributions["kind"],
        "TRANSVERSAL_ARTIFACTS_TOTAL": len(artefacts),
        "RESOLVED_OCCURRENCE_SCOPES": len(resolutions),
        "resolution_histogram": dict(Counter(r["resolution"] for r in resolutions)),
        "ARTIFACT_PROGRAM_COMPATIBLE": comptes[COMPATIBLE],
        "ARTIFACT_PROGRAM_INCOMPATIBLE": comptes[INCOMPATIBLE],
        "ARTIFACT_PROGRAM_MIXED": comptes[MIXTE],
        "ARTIFACT_PROGRAM_UNKNOWN": comptes[INCONNU],
        "resolutions": sorted(resolutions, key=lambda r: (
            r["content_sha256"], r["normalized_reference"], r["attributed_scope_level"])),
        "artifact_verdicts": {a: verdicts[a] for a in artefacts if verdicts[a] != INCONNU},
    }
    if sum(comptes.values()) != len(artefacts):
        raise SystemExit("REFUS : les verdicts d'artefact ne couvrent pas la population")
    arguments.sortie.write_text(
        json.dumps(rapport, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    print(f"TRANSVERSAL_ARTIFACTS_TOTAL      = {len(artefacts)}")
    print(f"RESOLVED_OCCURRENCE_SCOPES       = {len(resolutions)}")
    print(f"resolution_histogram             = {rapport['resolution_histogram']}")
    print(f"ARTIFACT_PROGRAM_COMPATIBLE      = {comptes[COMPATIBLE]}")
    print(f"ARTIFACT_PROGRAM_INCOMPATIBLE    = {comptes[INCOMPATIBLE]}")
    print(f"ARTIFACT_PROGRAM_MIXED           = {comptes[MIXTE]}")
    print(f"ARTIFACT_PROGRAM_UNKNOWN         = {comptes[INCONNU]}")
    print(f"somme                            = {sum(comptes.values())}")
    print("authority_evidence_status        = "
          f"{sorted({s for r in resolutions for s in r['authority_evidence_status']})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
