#!/usr/bin/env python3
"""Réconcilie les deux totaux non-PDF, et dit lequel le gate mesure.

Deux nombres circulaient sans que leur rapport soit écrit : 37 ressources
interactives uniques annoncées par le corpus, 57 demandes de réacquisition
portées par le dépôt. Un lecteur pouvait y voir une contradiction, ou pire,
faire passer l'un pour l'autre — et un compteur qu'on prend pour un autre est
un compteur qu'on peut faire baisser sans rien avoir fermé.

Il n'y a pas de contradiction tant que chaque total dit ce qu'il compte. Ce
script l'établit ligne par ligne, depuis le manifeste de réacquisition et la
consolidation des dispositions, sans réécrire aucun des deux.

Le statut de conservation est mesuré sur les octets, pas déclaré : un fichier
est retenu si et seulement si ses octets sont présents dans l'emplacement
durable nommé, et que leur empreinte est celle attendue. Une vérification
passée dans un répertoire temporaire ne retient rien.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

KIND = "NEXUS-NON-PDF-COUNT-RECONCILIATION-V1"

MANIFESTE = "docs/reports/handoff/non_pdf_reacquisition_manifest.json"
CONSOLIDATION = (
    "docs/reports/evidence-index/non_pdf_disposition_consolidation_20260907.json"
)

#: La classification qui alimente le compteur servable du gate.
CLASSIFICATION_SERVABLE = "INTERACTIVE_RESOURCE_SERVABLE"

#: Dispositions de reconciliation. Aucune n'est un conflit : elles disent
#: pourquoi une ligne entre dans un total et pas dans l'autre.
UNIQUE_GGB_FILE = "UNIQUE_GGB_FILE"
NON_GGB_NON_PDF = "NON_GGB_NON_PDF"
DUPLICATE_REQUEST_SAME_BYTES = "DUPLICATE_REQUEST_SAME_BYTES"

RETENU = "RETAINED_VERIFIED"
ABSENT = "NOT_RETAINED"
ALTERE = "RETAINED_BUT_DIGEST_DIFFERS"


class EntreeManquante(RuntimeError):
    """Une entrée nécessaire au calcul est absente ou inexploitable."""


def racine_depot() -> Path:
    surcharge = os.environ.get("NEXUS_REPO_ROOT")
    if surcharge:
        return Path(surcharge).resolve()
    return Path(__file__).resolve().parents[2]


def _lire(racine: Path, relatif: str):
    chemin = racine / relatif
    if not chemin.is_file():
        raise EntreeManquante(f"entrée absente : {chemin}")
    return json.loads(chemin.read_text(encoding="utf-8"))


def statut_de_conservation(demande: dict, magasin: Path | None) -> str:
    if magasin is None:
        return ABSENT
    fichier = magasin / demande["drive_file_id"]
    if not fichier.is_file():
        return ABSENT
    octets = fichier.read_bytes()
    if hashlib.sha256(octets).hexdigest() != demande["expected_content_sha256"]:
        return ALTERE
    if len(octets) != int(demande["expected_size"]):
        return ALTERE
    return RETENU


def reconcilier(racine: Path, magasin: Path | None) -> dict:
    manifeste = _lire(racine, MANIFESTE)
    demandes = manifeste.get("requests")
    if not demandes:
        raise EntreeManquante(f"manifeste sans demande : {racine / MANIFESTE}")
    consolidation = _lire(racine, CONSOLIDATION)
    for compteur in ("NON_PDF_SERVABLE", "NON_PDF_TOTAL", "NON_PDF_LOCAL_COPY_RETAINED"):
        if compteur not in consolidation:
            raise EntreeManquante(
                f"{CONSOLIDATION} : compteur « {compteur} » absent ;"
                f" compteurs vus : {sorted(consolidation)}"
            )

    occurrences = Counter(d["expected_content_sha256"] for d in demandes)

    lignes = []
    for demande in demandes:
        chemin = Path(demande["drive_path"])
        extension = chemin.suffix.lower()
        servable = demande["classification"] == CLASSIFICATION_SERVABLE
        empreinte = demande["expected_content_sha256"]

        if occurrences[empreinte] > 1:
            disposition = DUPLICATE_REQUEST_SAME_BYTES
        elif extension == ".ggb":
            disposition = UNIQUE_GGB_FILE
        else:
            disposition = NON_GGB_NON_PDF

        lignes.append(
            {
                "drive_file_id": demande["drive_file_id"],
                "filename": chemin.name,
                "extension": extension,
                "sha256": empreinte,
                "drive_path": demande["drive_path"],
                "classification": demande["classification"],
                "disposition": disposition,
                "counted_in_37": servable,
                "reason_counted_in_37": (
                    "ressource interactive servable"
                    if servable
                    else "hors du sous-ensemble servable"
                ),
                "counted_in_57": True,
                "reason_counted_in_57": "demande de réacquisition non-PDF",
                "servability_status": demande.get("target_disposition", ""),
                "retained_copy_status": statut_de_conservation(demande, magasin),
                "exploitation_strategy": (
                    "extraction gouvernée puis gate PII avant toute recherche"
                    if extension == ".ggb"
                    else "non indexable par rôle : aucune exploitation de recherche"
                ),
            }
        )

    servables = [ligne for ligne in lignes if ligne["counted_in_37"]]
    retenus = [ligne for ligne in lignes if ligne["retained_copy_status"] == RETENU]
    retenus_servables = [
        ligne for ligne in servables if ligne["retained_copy_status"] == RETENU
    ]

    total_57 = len(lignes)
    total_37 = len(servables)
    coherent = (
        consolidation["NON_PDF_SERVABLE"] == total_37
        and consolidation["NON_PDF_TOTAL"] == total_57
        and len({ligne["sha256"] for ligne in lignes}) == total_57
    )

    return {
        "kind": KIND,
        "totals": {
            "requests_57": total_57,
            "servable_37": total_37,
            "non_indexable": total_57 - total_37,
            "distinct_sha256": len({ligne["sha256"] for ligne in lignes}),
            "distinct_drive_ids": len({ligne["drive_file_id"] for ligne in lignes}),
        },
        "gate_counts": {
            "NON_PDF_SERVABLE": consolidation["NON_PDF_SERVABLE"],
            "NON_PDF_TOTAL": consolidation["NON_PDF_TOTAL"],
            "NON_PDF_LOCAL_COPY_RETAINED": consolidation["NON_PDF_LOCAL_COPY_RETAINED"],
        },
        "what_the_gate_measures": (
            "le sous-ensemble SERVABLE, soit les ressources interactives uniques ; "
            "les autres demandes non-PDF sont non indexables par rôle et n'entrent "
            "pas dans ce compteur"
        ),
        "reconciled": coherent,
        "by_disposition": dict(sorted(Counter(ligne["disposition"] for ligne in lignes).items())),
        "by_extension": dict(sorted(Counter(ligne["extension"] for ligne in lignes).items())),
        "retention": {
            "durable_store_named": magasin is not None,
            "retained_verified": len(retenus),
            "retained_servable": len(retenus_servables),
            "not_retained": total_57 - len(retenus),
            # La rétention mesurée ne ferme aucun compteur par elle-même : la
            # politique de conservation doit d'abord être versionnée.
            "closes_gate_counter": False,
            "why_not": (
                "la politique de conservation n'est pas versionnée ; un emplacement "
                "choisi en séance n'est pas une décision de gouvernance"
            ),
        },
        "rows": sorted(lignes, key=lambda ligne: (not ligne["counted_in_37"], ligne["filename"])),
    }


def rendre_markdown(etat: dict) -> str:
    totaux = etat["totals"]
    retention = etat["retention"]
    lignes = [
        "# Non-PDF : 37 et 57 réconciliés",
        "",
        "Document dérivé. Ne pas éditer à la main :",
        "`scripts/go_live/reconcile_non_pdf_counts.py` le régénère.",
        "",
        "## Les deux totaux",
        "",
        f"- demandes de réacquisition non-PDF : **{totaux['requests_57']}**",
        f"- dont ressources interactives servables : **{totaux['servable_37']}**",
        f"- dont non indexables par rôle : **{totaux['non_indexable']}**",
        f"- empreintes distinctes : **{totaux['distinct_sha256']}**",
        f"- identifiants Drive distincts : **{totaux['distinct_drive_ids']}**",
        "",
        f"Réconciliés : **{'oui' if etat['reconciled'] else 'NON'}**.",
        "",
        f"Ce que le gate mesure : {etat['what_the_gate_measures']}.",
        "",
        "## Conservation",
        "",
        f"- emplacement durable nommé : **{'oui' if retention['durable_store_named'] else 'non'}**",
        f"- octets retenus et vérifiés : **{retention['retained_verified']}**",
        f"- dont servables : **{retention['retained_servable']}**",
        f"- non retenus : **{retention['not_retained']}**",
        "",
        f"Ferme le compteur du gate : **{'oui' if retention['closes_gate_counter'] else 'non'}** — "
        f"{retention['why_not']}.",
        "",
        "## Lignes",
        "",
        "| fichier | ext | dans 37 | disposition | conservation |",
        "| --- | --- | :---: | --- | --- |",
    ]
    for ligne in etat["rows"]:
        lignes.append(
            f"| `{ligne['filename']}` | {ligne['extension']} | "
            f"{'oui' if ligne['counted_in_37'] else 'non'} | {ligne['disposition']} | "
            f"{ligne['retained_copy_status']} |"
        )
    lignes.append("")
    return "\n".join(lignes)


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--durable-store",
        help="répertoire des octets conservés durablement (nommés par drive_file_id)",
    )
    analyseur.add_argument(
        "--output-json",
        default="docs/reports/go_live/non_pdf_37_vs_57_reconciliation.json",
    )
    analyseur.add_argument(
        "--output-md",
        default="docs/reports/go_live/NON_PDF_37_VS_57_RECONCILIATION.md",
    )
    arguments = analyseur.parse_args(argv)

    racine = racine_depot()
    magasin = Path(arguments.durable_store) if arguments.durable_store else None
    try:
        etat = reconcilier(racine, magasin)
    except EntreeManquante as erreur:
        print(f"ENTREE_MANQUANTE: {erreur}", file=sys.stderr)
        return 2

    for relatif, contenu in (
        (arguments.output_json, json.dumps(etat, indent=2, ensure_ascii=False, sort_keys=True) + "\n"),
        (arguments.output_md, rendre_markdown(etat)),
    ):
        chemin = racine / relatif
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(contenu, encoding="utf-8")
        print(f"écrit : {chemin}")
    return 0 if etat["reconciled"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
