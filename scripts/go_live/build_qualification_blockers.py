#!/usr/bin/env python3
"""Dérive l'état des blocages de qualification, au lieu de le tenir à la main.

Le recensement était une liste maintenue à la main : treize entrées, toutes
`closed=false, proof=null`, sans condition de fermeture écrite nulle part.
Deux défauts en découlaient. Un blocage dont la preuve existait pouvait rester
ouvert faute que quelqu'un pense à le fermer. Et un blocage pouvait être fermé
d'un coup d'éditeur, sans preuve, puisque rien ne s'y opposait.

Ici, chaque blocage porte sa CONDITION DE FERMETURE en clair, et son état est
DÉRIVÉ d'une mesure. Un blocage sans vérificateur reste ouvert : ne pas savoir
n'est pas une raison de fermer. Et `closed=true` avec `proof=null` est refusé
à la construction — c'est la règle que le mandat pose, tenue par le code
plutôt que par la vigilance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

KIND = "NEXUS-GO-LIVE-QUALIFICATION-BLOCKERS-V2"

SORTIE = "docs/reports/go_live/qualification_blockers.json"
SORTIE_MD = "docs/reports/go_live/QUALIFICATION_BLOCKERS.md"

RECONCILIATION = "docs/reports/go_live/non_pdf_37_vs_57_reconciliation.json"
MANIFESTE_STORE = "docs/reports/go_live/non_pdf_durable_storage_manifest.json"
POLITIQUE = "docs/reports/go_live/non_pdf_retention_policy.json"


class EntreeManquante(RuntimeError):
    """Une entrée nécessaire est absente. Jamais un zéro."""


class PreuveAbsente(RuntimeError):
    """Un blocage ne peut pas être fermé sans preuve."""


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


def verifier_non_pdf(racine: Path) -> dict:
    """Vérifie la condition écrite dans la politique, sur les octets réels.

    La politique dit : « les 37 ressources servables sont présentes au store
    durable canonique, taille et SHA-256 conformes ». On ne lit pas un drapeau
    qui l'affirme — on recalcule les empreintes des fichiers présents.
    """
    reconciliation = _lire(racine, RECONCILIATION)
    manifeste = _lire(racine, MANIFESTE_STORE)
    politique = _lire(racine, POLITIQUE)

    if not politique.get("adopted"):
        return {"closed": False, "proof": None, "why": "politique non adoptée"}

    servables = [
        ligne for ligne in reconciliation["rows"] if ligne.get("counted_in_37")
    ]
    attendu = reconciliation["gate_counts"]["NON_PDF_SERVABLE"]
    if len(servables) != attendu:
        return {
            "closed": False,
            "proof": None,
            "why": f"{len(servables)} lignes servables pour {attendu} annoncées",
        }

    store = Path(manifeste["durable_location"])
    if not store.is_dir():
        return {
            "closed": False,
            "proof": None,
            "why": f"store durable absent : {store}",
        }

    presents: dict[str, int] = {}
    for chemin in store.rglob("*"):
        if chemin.is_file():
            octets = chemin.read_bytes()
            presents[hashlib.sha256(octets).hexdigest()] = len(octets)

    manquants = [
        ligne["sha256"] for ligne in servables if ligne["sha256"] not in presents
    ]
    if manquants:
        return {
            "closed": False,
            "proof": None,
            "why": f"{len(manquants)} ressources servables absentes du store",
            "missing": manquants,
        }

    tailles = {entree["sha256"]: entree.get("bytes") for entree in manifeste["sha256sums"]}
    discordances = [
        ligne["sha256"]
        for ligne in servables
        if tailles.get(ligne["sha256"]) not in (None, presents[ligne["sha256"]])
    ]
    if discordances:
        return {
            "closed": False,
            "proof": None,
            "why": f"{len(discordances)} tailles discordantes",
        }

    return {
        "closed": True,
        "proof": {
            "condition": politique["closes_blocker_when"],
            "servable_resources_expected": attendu,
            "servable_resources_verified": len(servables),
            "durable_store": str(store),
            "verification": (
                "empreinte sha256 RECALCULÉE sur les octets présents, comparée "
                "ligne à ligne à la réconciliation ; les tailles sont comparées "
                "au manifeste"
            ),
            "does_not_close": politique.get("does_not_close", []),
        },
        "why": None,
    }


#: Un blocage sans vérificateur reste ouvert. La condition est écrite pour que
#: son propriétaire sache ce qu'il doit produire, et pour qu'on ne la
#: redécouvre pas à chaque lot.
BLOCAGES = (
    ("C1", "Autorite de release et couverture promue", "operateur",
     "une release gouvernée couvre l ensemble promu, sans contenu refusé", None),
    ("C2", "Ingestion multilevel reelle bout en bout", "session H2-C externe",
     "une ingestion multilevel réelle aboutit et est rejouable", None),
    ("C3", "Worker CLI multilevel bout en bout", "session H2-C externe",
     "le worker CLI traite un lot multilevel de bout en bout", None),
    ("C4", "Contrat de retrieval sur corpus servable", "operateur",
     "le contrat de retrieval est validé sur le corpus SERVABLE, pas seulement "
     "sur un index de staging : les huit conditions de l écart de recherche "
     "doivent être tenues", None),
    ("C5", "Autorite d acces et portees", "operateur",
     "l autorité d accès refuse une portée non autorisée, prouvé par épreuve", None),
    ("C6", "Qualification CAS et couverture de magasin", "operateur",
     "la qualification CAS couvre le magasin réel", None),
    ("COCKPIT_E2E", "Cockpit bout en bout contre l API de retrieval", "operateur",
     "le cockpit interroge l API de retrieval de bout en bout", None),
    ("STAGING_EXTERNE", "Staging externe ingere et qualifie", "operateur",
     "un staging externe est ingéré puis qualifié", None),
    ("CONCURRENCE", "Comportement sous concurrence", "operateur",
     "le comportement sous concurrence est mesuré et borné", None),
    ("SYNC_INCREMENTALE", "Synchronisation incrementale", "operateur",
     "une synchronisation incrémentale est prouvée sans perte ni doublon", None),
    ("ROLLBACK", "Mecanisme de rollback eprouve", "operateur",
     "le rollback de la RELEASE de production est éprouvé. Le rollback de la "
     "base vectorielle de staging, prouvé au lot BK, ne ferme pas celui-ci : "
     "ce ne sont pas les mêmes objets", None),
    ("MANIFESTE_PRODUCTION", "Manifeste de readiness de production signe", "operateur",
     "un manifeste de readiness de production est signé", None),
    ("NON_PDF_REACQUISITION", "Reacquisition des 37 ressources interactives servables",
     "operateur",
     "les 37 ressources servables sont présentes au store durable canonique, "
     "taille et SHA-256 conformes", verifier_non_pdf),
)


def construire(racine: Path) -> dict:
    blocages = []
    for identifiant, titre, proprietaire, condition, verificateur in BLOCAGES:
        if verificateur is None:
            etat = {
                "closed": False,
                "proof": None,
                "why": "aucun vérificateur : ne pas savoir n est pas fermer",
            }
        else:
            etat = verificateur(racine)
        if etat["closed"] and not etat.get("proof"):
            raise PreuveAbsente(
                f"{identifiant} serait fermé sans preuve : refusé à la construction"
            )
        blocages.append(
            {
                "id": identifiant,
                "titre": titre,
                "owner": proprietaire,
                "closing_condition": condition,
                "closed": etat["closed"],
                "proof": etat.get("proof"),
                "why_still_open": etat.get("why"),
            }
        )
    ouverts = [b for b in blocages if not b["closed"]]
    return {
        "kind": KIND,
        "note": (
            "État DÉRIVÉ, jamais tenu à la main. Un blocage sans vérificateur "
            "reste ouvert. `closed=true` avec `proof=null` est refusé à la "
            "construction."
        ),
        "blockers": blocages,
        "open_count": len(ouverts),
        "closed_count": len(blocages) - len(ouverts),
    }


def rendre_markdown(etat: dict) -> str:
    lignes = [
        "# Blocages de qualification du go-live",
        "",
        f"- kind : `{etat['kind']}`",
        f"- ouverts : **{etat['open_count']}** / fermés : {etat['closed_count']}",
        "",
        f"> {etat['note']}",
        "",
        "| Blocage | Propriétaire | Fermé | Condition de fermeture |",
        "|---|---|---|---|",
    ]
    for bloc in etat["blockers"]:
        lignes.append(
            f"| `{bloc['id']}` | {bloc['owner']} | "
            f"**{'oui' if bloc['closed'] else 'non'}** | {bloc['closing_condition']} |"
        )
    fermes = [b for b in etat["blockers"] if b["closed"]]
    if fermes:
        lignes += ["", "## Preuves des blocages fermés", ""]
        for bloc in fermes:
            lignes += [
                f"### `{bloc['id']}`",
                "",
                f"- condition : {bloc['closing_condition']}",
                f"- vérification : {bloc['proof']['verification']}",
                "",
                "Ce que cette fermeture ne ferme pas :",
                "",
            ]
            lignes += [f"- {x}" for x in bloc["proof"].get("does_not_close", [])]
            lignes.append("")
    return "\n".join(lignes) + "\n"


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - orchestration
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    racine = racine_depot()
    try:
        etat = construire(racine)
    except (EntreeManquante, PreuveAbsente) as erreur:
        print(f"REFUS : {erreur}", file=sys.stderr)
        return 2
    (racine / SORTIE).write_text(
        json.dumps(etat, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (racine / SORTIE_MD).write_text(rendre_markdown(etat), encoding="utf-8")
    print(f"écrit : {racine / SORTIE} — {etat['open_count']} ouverts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
