#!/usr/bin/env python3
"""Prépare les demandes de récupération adressées au canal Drive.

Ce script ne devine rien et ne fabrique aucune URL. Il produit des TABLES
adressées par `drive_file_id`, pour que le commanditaire relise sur le Drive
connecté ce que cette session ne peut pas atteindre — puis que chaque relation
finisse dans une catégorie explicite plutôt que dans un compteur d'absence.

Une URL dérivée d'un slug de nom de fichier aurait la forme d'une preuve sans
en être une : un lecteur ne pourrait pas distinguer une URL relevée d'une URL
devinée. Aucune n'est donc produite ici.

Trois sorties :

* `drive_url_provenance_handoff` — une ligne par objet du plan de données, plus
  la demande PRIORITAIRE des index de provenance qui portent probablement la
  réponse pour des milliers de lignes d'un coup ;
* `non_pdf_reacquisition_manifest` — les 57 objets non-PDF à réacquérir, avec
  la taille et l'empreinte ATTENDUES, pour que la récupération se vérifie ;
* `not_assessable_source_lookup` — les documents dont une page reste illisible,
  pour la recherche d'une source alternative gouvernée.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

KIND_URL = "NEXUS-DRIVE-URL-PROVENANCE-HANDOFF-V1"
KIND_NON_PDF = "NEXUS-NON-PDF-REACQUISITION-MANIFEST-V1"
KIND_NOT_ASSESSABLE = "NEXUS-NOT-ASSESSABLE-SOURCE-LOOKUP-V1"

#: Ce que la zone dit du RÔLE de la source. Distinct de la nature du document :
#: une ressource interactive d'auteur et un programme officiel ne se cherchent
#: pas au même endroit.
ROLES_PAR_ZONE = {
    "01_EDUSCOL_OFFICIEL": "INSTITUTIONAL_PUBLICATION",
    "02_NEXUS_DIAGNOSTICS": "AUTHOR_DIAGNOSTIC",
    "03_RESSOURCES_INTERACTIVES": "AUTHOR_INTERACTIVE_RESOURCE",
    "04_COMPLEMENTS_PEDAGOGIQUES": "AUTHOR_COMPLEMENT",
    "00_ADMIN": "CONTROL_PLANE",
    "00_INDEX_PROVENANCE": "CONTROL_PLANE_PROVENANCE_INDEX",
    # Un objet à la racine du Drive n'a pas de zone. C'est la documentation
    # d'exploitation du dépôt Drive lui-même, pas un document qui enseigne.
    "": "OPERATIONAL_DOCUMENTATION",
}

#: Les catégories terminales. Une relation qui n'y aboutit pas reste comptée
#: comme non résolue — `NO_URL_EVIDENCE` n'est pas `VERIFIED_CURRENT`.
CATEGORIES_TERMINALES = (
    "VERIFIED_CURRENT",
    "UNVERIFIABLE_WITH_EVIDENCE",
    "NO_URL_EVIDENCE",
    "NOT_APPLICABLE",
    "ERROR",
)


def _sha(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def urls_connues_du_depot(racine: Path) -> dict[str, str]:
    """Les paires (content_sha256, source_url) que le dépôt déclare déjà.

    C'est la seule évidence locale : elle vient des manifestes de release de la
    lignée historique, donc d'un périmètre plus étroit que le corpus."""
    connues: dict[str, str] = {}
    motifs = (
        racine / "services" / "rag-pedago" / "data" / "releases",
        racine / "docs" / "reports",
    )
    for base in motifs:
        for fichier in base.rglob("*.json"):
            try:
                charge = json.loads(fichier.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            pile = [charge]
            while pile:
                objet = pile.pop()
                if isinstance(objet, dict):
                    url, contenu = objet.get("source_url"), objet.get("content_sha256")
                    if (
                        isinstance(url, str)
                        and isinstance(contenu, str)
                        and len(contenu) == 64
                    ):
                        connues.setdefault(contenu, url)
                    pile.extend(objet.values())
                elif isinstance(objet, list):
                    pile.extend(objet)
    return connues


def _canonique(charge: object) -> bytes:
    return (
        json.dumps(charge, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--corpus-root", required=True, type=Path)
    parser.add_argument("--non-pdf-dispositions", required=True, type=Path)
    parser.add_argument("--run-report", required=True, type=Path)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    inventaire = [
        json.loads(ligne)
        for ligne in args.inventory.read_text(encoding="utf-8").splitlines()
        if ligne.strip()
    ]
    connues = urls_connues_du_depot(args.repository_root)
    non_pdf = {
        entree["content_sha256"]: entree
        for entree in json.loads(
            args.non_pdf_dispositions.read_text(encoding="utf-8")
        )["entries"]
    }
    par_drive_id = {entree["drive_file_id"]: entree for entree in non_pdf.values()}
    run = json.loads(args.run_report.read_text(encoding="utf-8"))

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # --- 1. la table des relations URL ---------------------------------
    lignes: list[dict[str, object]] = []
    etats: Counter[str] = Counter()
    for objet in inventaire:
        chemin = args.corpus_root / objet["relative_path"]
        role = ROLES_PAR_ZONE.get(objet["zone"], "UNKNOWN_ZONE")
        if chemin.is_file():
            contenu = _sha(chemin)
        else:
            # Non conservé localement : l'empreinte vient de la disposition qui
            # l'a relevée sur les OCTETS au moment de la récupération, ou reste
            # inconnue. On ne la déduit jamais de la taille annoncée.
            entree = par_drive_id.get(objet["drive_file_id"])
            contenu = entree["content_sha256"] if entree else None

        if not objet["servable"]:
            etat, demande = "NOT_APPLICABLE", "NONE"
        elif contenu in connues:
            etat, demande = "KNOWN_FROM_RELEASE_MANIFEST", "URL_CURRENCY_CONFIRMATION"
        else:
            etat, demande = "NO_LOCAL_EVIDENCE", "DRIVE_PROVENANCE_INDEX"
        etats[etat] += 1
        # Ce que le document deviendra s'il est servi. Renseigné pour que le
        # commanditaire voie quelles relations peuvent légitimement finir en
        # `NOT_APPLICABLE` — sans que ce script en décide à sa place : un
        # document non indexable n'a pas de citation à porter, mais c'est une
        # disposition, pas une déduction de cet outil.
        disposition = non_pdf.get(contenu or "", {}).get("disposition")
        if disposition is None:
            pertinence = "INDEXABLE" if objet["servable"] else "CONTROL_PLANE"
        elif disposition.endswith("NON_INDEXABLE"):
            pertinence = "NON_INDEXABLE"
        else:
            pertinence = "INDEXABLE"
        lignes.append(
            {
                "artifact_id": contenu,
                "serving_relevance": pertinence,
                "drive_file_id": objet["drive_file_id"],
                "drive_path": objet["source_id"].split(":", 1)[-1],
                "content_sha256": contenu,
                "source_role": role,
                "known_source_url": connues.get(contenu or "", None),
                "url_evidence_status": etat,
                "required_provenance_lookup": demande,
            }
        )

    index_provenance = [
        {
            "drive_file_id": objet["drive_file_id"],
            "drive_path": objet["source_id"].split(":", 1)[-1],
            "expected_size": objet["size"],
            "mime": objet["mime_type"],
        }
        for objet in inventaire
        if objet["zone"] == "00_INDEX_PROVENANCE"
    ]
    index_provenance.sort(key=lambda e: str(e["drive_path"]))

    plan_de_donnees = [ligne for ligne in lignes if ligne["url_evidence_status"] != "NOT_APPLICABLE"]
    handoff = {
        "kind": KIND_URL,
        "terminal_categories": list(CATEGORIES_TERMINALES),
        # La demande PRIORITAIRE : ces objets portent probablement la réponse
        # pour des milliers de lignes d'un coup. Les demander AVANT toute
        # recherche unitaire évite de faire chercher 2202 fois ce qu'un
        # catalogue donne en une fois.
        "priority_request": {
            "reason": (
                "la zone 00_INDEX_PROVENANCE porte des catalogues et des "
                "manifestes d'empreintes qui couvrent probablement l'essentiel "
                "du corpus ; les lire d'abord évite des milliers de recherches "
                "unitaires"
            ),
            "objects": index_provenance,
            "count": len(index_provenance),
            "total_bytes": sum(int(e["expected_size"]) for e in index_provenance),
        },
        "DATA_PLANE_TOTAL": len(plan_de_donnees),
        "CONTROL_PLANE_TOTAL": len(lignes) - len(plan_de_donnees),
        "URL_KNOWN_FROM_LOCAL_EVIDENCE": etats["KNOWN_FROM_RELEASE_MANIFEST"],
        "URL_NO_LOCAL_EVIDENCE": etats["NO_LOCAL_EVIDENCE"],
        "FULL_URL_LOOKUP_REQUESTS": len(plan_de_donnees),
        "FULL_URL_UNACCOUNTED_AFTER_LOCAL_EVIDENCE": etats["NO_LOCAL_EVIDENCE"],
        "relations": sorted(
            plan_de_donnees, key=lambda e: (str(e["source_role"]), str(e["drive_path"]))
        ),
    }
    (args.output_dir / "drive_url_provenance_handoff.json").write_bytes(
        _canonique(handoff)
    )

    # --- 2. le manifeste de réacquisition des non-PDF ------------------
    par_id = {objet["drive_file_id"]: objet for objet in inventaire}
    reacquisition = []
    for empreinte, entree in sorted(non_pdf.items()):
        objet = par_id.get(entree["drive_file_id"])
        reacquisition.append(
            {
                "drive_file_id": entree["drive_file_id"],
                "drive_path": (
                    objet["source_id"].split(":", 1)[-1] if objet else entree["relative_path"]
                ),
                "expected_size": entree["size"],
                "expected_content_sha256": empreinte,
                "mime": entree["mime_type"],
                "classification": entree["disposition"],
                "target_disposition": entree["disposition"],
            }
        )
    (args.output_dir / "non_pdf_reacquisition_manifest.json").write_bytes(
        _canonique(
            {
                "kind": KIND_NON_PDF,
                "NON_PDF_REQUESTS": len(reacquisition),
                "acceptance": {
                    "REACQUIRED_NON_PDF": len(reacquisition),
                    "SIZE_MISMATCH": 0,
                    "SHA256_MISMATCH": 0,
                    "NON_PDF_UNACCOUNTED": 0,
                },
                "ggb_handling": (
                    "Pour les .ggb, le SHA du FICHIER PHYSIQUE reste l'identité "
                    "de source. Toute extraction de geogebra.xml destinée à "
                    "devenir recherchable passe ensuite le gate PII. Aucune "
                    "exécution de macro ni de script ; protections zip bomb, "
                    "path traversal, lien symbolique et XXE conservées."
                ),
                "requests": reacquisition,
            }
        )
    )

    # --- 3. les documents dont une page reste illisible ----------------
    lookups = []
    for entree in sorted(
        run["pages_non_evaluables"], key=lambda e: str(e["artifact_id"])
    ):
        objet = par_id.get(entree["drive_file_id"])
        lookups.append(
            {
                "content_sha256": entree["artifact_id"],
                "drive_file_id": entree["drive_file_id"],
                "drive_path": objet["source_id"].split(":", 1)[-1] if objet else None,
                "affected_pages": entree["pages"],
                "page_policy_verdicts": entree["page_policy_verdicts"],
                "current_source_sha256": entree["artifact_id"],
            }
        )
    (args.output_dir / "not_assessable_source_lookup.json").write_bytes(
        _canonique(
            {
                "kind": KIND_NOT_ASSESSABLE,
                "NOT_ASSESSABLE_SOURCE_REQUESTS": len(lookups),
                "interim_disposition": {
                    "disposition": "GOVERNED_NOT_SERVABLE",
                    "blocker_codes": [
                        "PII_NOT_ASSESSABLE",
                        "SOURCE_EXTRACTION_INCOMPLETE",
                    ],
                },
                "note": (
                    "Aucun texte : la page est justement celle que personne n'a "
                    "su lire. Une source alternative doit être gouvernée et "
                    "tracée ; le PDF existant n'est jamais remplacé en silence."
                ),
                "requests": lookups,
            }
        )
    )

    print("DRIVE_REACQUISITION_HANDOFF_READY=true")
    print(f"PROVENANCE_INDEX_REQUESTS={len(index_provenance)}")
    print(f"NON_PDF_REQUESTS={len(reacquisition)}")
    print(f"NOT_ASSESSABLE_SOURCE_REQUESTS={len(lookups)}")
    print(f"FULL_URL_LOOKUP_REQUESTS={handoff['FULL_URL_LOOKUP_REQUESTS']}")
    print(
        "FULL_URL_UNACCOUNTED_AFTER_LOCAL_EVIDENCE="
        f"{handoff['FULL_URL_UNACCOUNTED_AFTER_LOCAL_EVIDENCE']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
