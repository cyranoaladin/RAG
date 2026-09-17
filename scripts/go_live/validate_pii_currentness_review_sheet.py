#!/usr/bin/env python3
"""Contrôle une feuille de revue PII / actualité REMPLIE. N'importe rien, ne décide rien.

Le reviewer le lance sur sa feuille avant de demander l'import : il apprend tout de
suite qu'une décision serait refusée par le contrat `NEXUS-PII-REVIEW-DECISIONS-V1`,
au lieu de l'apprendre au moment de l'import. Accepte la feuille complète comme
l'extrait minimal C1. N'écrit aucun fichier, ne touche aucun compteur.

    python3 scripts/go_live/validate_pii_currentness_review_sheet.py <feuille.tsv>
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_pii_currentness_decision_packet as dossier  # noqa: E402

COLONNES_DECISION = (
    "HUMAN_DECISION", "FINDING_DISPOSITION", "JUSTIFICATION_CATEGORY",
    "REVIEWER_LOGIN", "EVIDENCE_REFERENCE", "COMMENT",
)
CATEGORIES = (
    "INSTITUTIONAL_CONTACT", "PEDAGOGICAL_EXAMPLE", "FICTIONAL_IDENTITY",
    "TECHNICAL_FALSE_POSITIVE", "PUBLIC_OFFICIAL_PUBLICATION", "PERSONAL_DATA_PRESENT",
)
EN_ATTENTE = ("", "HUMAN_REVIEW_REQUIRED")
REJETS = ("PII_REDACTION_REQUIRED", "EXCLUDE_FROM_SERVABLE_SET")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


def _cle(ligne: dict) -> tuple[str, str, str]:
    return ligne.get("row_kind", ""), ligne.get("content_sha256", ""), ligne.get("finding_id", "")


def valider(racine: Path, feuille: Path) -> dict:
    reference = {
        _cle(r): r
        for r in csv.DictReader(io.StringIO(dossier.rendre_tsv(dossier.construire(racine))), delimiter="\t")
    }
    lignes = list(csv.DictReader(feuille.open(encoding="utf-8", newline=""), delimiter="\t"))
    erreurs: list[str] = []
    manquantes = [c for c in dossier.COLONNES if lignes and c not in lignes[0]]
    if not lignes or manquantes:
        return {"errors": [f"feuille vide ou colonnes manquantes : {manquantes}"], "counts": {}, "imports_nothing": True}

    lecture_seule = [c for c in dossier.COLONNES if c not in COLONNES_DECISION]
    vues: set[tuple[str, str, str]] = set()
    for n, ligne in enumerate(lignes, start=2):
        cle = _cle(ligne)
        if cle not in reference:
            erreurs.append(f"ligne {n} : ligne inconnue du dossier dérivé {cle[0]} {cle[1][:12]}")
            continue
        if cle in vues:
            erreurs.append(f"ligne {n} : ligne en double")
        vues.add(cle)
        modifiees = [c for c in lecture_seule if ligne[c] != reference[cle][c]]
        if modifiees:
            erreurs.append(f"ligne {n} : colonne(s) en lecture seule modifiée(s) : {modifiees}")

    connues = [ligne for ligne in lignes if _cle(ligne) in reference]
    findings_par_contenu: dict[str, list[dict]] = {}
    for ligne in connues:
        if ligne["row_kind"] == "PII_FINDING":
            findings_par_contenu.setdefault(ligne["content_sha256"], []).append(ligne)
            if any(ligne[c] for c in ("HUMAN_DECISION", "JUSTIFICATION_CATEGORY")):
                erreurs.append(f"finding {ligne['finding_id'][:12]} : une ligne PII_FINDING ne porte que FINDING_DISPOSITION")
            if ligne["FINDING_DISPOSITION"] and ligne["FINDING_DISPOSITION"] not in dossier.DISPOSITIONS_FINDING:
                erreurs.append(f"finding {ligne['finding_id'][:12]} : FINDING_DISPOSITION hors liste : {ligne['FINDING_DISPOSITION']!r}")

    decides = attente = 0
    for ligne in connues:
        if ligne["row_kind"] == "PII_FINDING":
            continue
        qui = f"{ligne['row_kind']} {ligne['content_sha256'][:12]}"
        decision = ligne["HUMAN_DECISION"]
        options = dossier.OPTIONS_PII if ligne["row_kind"] == "PII_CONTENT" else dossier.OPTIONS_ACTUALITE
        if decision and decision not in options:
            erreurs.append(f"{qui} : HUMAN_DECISION hors liste : {decision!r}")
            continue
        if decision in EN_ATTENTE:
            attente += 1
            continue
        decides += 1
        if not _LOGIN.fullmatch(ligne["REVIEWER_LOGIN"]):
            erreurs.append(f"{qui} : REVIEWER_LOGIN absent ou invalide")
        if ligne["row_kind"] == "CURRENTNESS_CONTENT":
            if decision == "KEEP_IF_STILL_CURRENT_WITH_EVIDENCE" and not ligne["EVIDENCE_REFERENCE"].strip():
                erreurs.append(f"{qui} : EVIDENCE_REFERENCE obligatoire pour KEEP_IF_STILL_CURRENT_WITH_EVIDENCE")
            continue
        attendus = sum(1 for cle in reference if cle[0] == "PII_FINDING" and cle[1] == ligne["content_sha256"])
        dispositions = [f["FINDING_DISPOSITION"] for f in findings_par_contenu.get(ligne["content_sha256"], [])]
        if len(dispositions) != attendus or not all(dispositions):
            erreurs.append(f"{qui} : décision rendue sans disposition sur chaque finding ({sum(map(bool, dispositions))}/{attendus})")
        if ligne["JUSTIFICATION_CATEGORY"] not in CATEGORIES:
            erreurs.append(f"{qui} : JUSTIFICATION_CATEGORY absente ou hors liste")
        personnels = dispositions.count("PERSONAL_DATA_PRESENT")
        if decision == "PII_CLEARED" and (personnels or ligne["JUSTIFICATION_CATEGORY"] == "PERSONAL_DATA_PRESENT"):
            erreurs.append(f"{qui} : PII_CLEARED impossible avec PERSONAL_DATA_PRESENT ({personnels} finding(s))")
        if decision in REJETS and not personnels:
            erreurs.append(f"{qui} : {decision} exige au moins un finding PERSONAL_DATA_PRESENT (contrat : REJECTED)")

    return {
        "sheet": str(feuille),
        "rows": len(lignes),
        "counts": {"decided": decides, "pending": attente, "invalid": len(erreurs)},
        "errors": erreurs,
        "imports_nothing": True,
        "note": "contrôle de forme et de cohérence ; l'import reste soumis à votre autorisation explicite",
    }


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - orchestration
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feuille", type=Path)
    args = parser.parse_args(argv)
    bilan = valider(Path(__file__).resolve().parents[2], args.feuille)
    print(json.dumps(bilan, ensure_ascii=False, indent=2))
    return 1 if bilan["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
