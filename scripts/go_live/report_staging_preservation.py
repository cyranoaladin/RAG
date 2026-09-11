#!/usr/bin/env python3
"""Rend compte de la préservation de la base de revue, sans jamais publier de secret.

La base du run est la seule chose qui rende la revue PII réamorçable : le texte
de revue y est retrouvé, pas recalculé. Elle vivait dans un conteneur dont le
volume est anonyme — exactement ce qu'un élagage de volumes emporte sans
prévenir. Ce script rend compte de ce qui a été mis à l'abri.

Trois principes qu'il applique et qu'il faut garder en tête en le lisant :

- une sauvegarde non restaurée n'est pas une sauvegarde. La preuve de
  restauration compare les comptages ET un digest logique du texte de revue ;
  des comptages égaux sur un texte différent ne prouveraient rien ;
- une variable d'environnement dont le nom évoque un secret est masquée, quelle
  que soit sa valeur. On ne publie pas un mot de passe parce qu'il est
  « seulement local » ;
- rien ici ne ferme un compteur. Mettre des octets à l'abri n'est pas décider
  d'une politique de conservation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

KIND_INVENTAIRE = "NEXUS-STAGING-PRESERVATION-INVENTORY-V1"
KIND_PREUVE = "NEXUS-STAGING-BACKUP-RESTORE-PROOF-V1"
KIND_NON_PDF = "NEXUS-NON-PDF-DURABLE-STORAGE-MANIFEST-V1"

#: Toute variable dont le nom contient l'un de ces fragments est masquée.
FRAGMENTS_SECRETS = ("PASSWORD", "SECRET", "TOKEN", "KEY", "CREDENTIAL", "PASS")

MASQUE = "<masqué>"


class EntreeManquante(RuntimeError):
    """Une entrée nécessaire au calcul est absente ou inexploitable."""


def racine_depot() -> Path:
    surcharge = os.environ.get("NEXUS_REPO_ROOT")
    if surcharge:
        return Path(surcharge).resolve()
    return Path(__file__).resolve().parents[2]


def _lire_json(chemin: Path):
    if not chemin.is_file():
        raise EntreeManquante(f"entrée absente : {chemin}")
    texte = chemin.read_text(encoding="utf-8")
    if not texte.strip():
        raise EntreeManquante(f"entrée vide : {chemin}")
    return json.loads(texte)


def est_secret(nom: str) -> bool:
    majuscule = nom.upper()
    return any(fragment in majuscule for fragment in FRAGMENTS_SECRETS)


def masquer_env(variables: list[str]) -> list[str]:
    sorties = []
    for variable in variables:
        nom, _, _ = variable.partition("=")
        sorties.append(f"{nom}={MASQUE}" if est_secret(nom) else variable)
    return sorties


def construire_inventaire(inspect: list | dict) -> dict:
    conteneur = inspect[0] if isinstance(inspect, list) else inspect
    etat = conteneur["State"]
    montages = [
        {
            "type": montage["Type"],
            "name": montage.get("Name", ""),
            "destination": montage["Destination"],
            "read_write": montage.get("RW"),
            "anonymous_volume": montage["Type"] == "volume"
            and len(montage.get("Name", "")) == 64,
        }
        for montage in conteneur.get("Mounts", [])
    ]
    return {
        "kind": KIND_INVENTAIRE,
        "container_name": conteneur["Name"].lstrip("/"),
        "container_id": conteneur["Id"][:16],
        "image": conteneur["Config"]["Image"],
        "state": etat["Status"],
        "started_at": etat.get("StartedAt", ""),
        "restart_count": conteneur.get("RestartCount", 0),
        "restart_policy": conteneur["HostConfig"]["RestartPolicy"].get("Name", ""),
        "health": etat.get("Health", {}).get("Status", "NO_HEALTHCHECK"),
        "ports": conteneur["NetworkSettings"]["Ports"],
        "networks": sorted(conteneur["NetworkSettings"]["Networks"]),
        "labels": conteneur["Config"].get("Labels") or {},
        "mounts": montages,
        "env": masquer_env(conteneur["Config"].get("Env") or []),
        "risk": {
            # Un volume anonyme sans politique de redémarrage est le cas le plus
            # fragile : rien ne le nomme, donc rien ne le protège d'un élagage.
            "anonymous_volumes": sum(1 for m in montages if m["anonymous_volume"]),
            "restart_policy_is_none": conteneur["HostConfig"]["RestartPolicy"].get(
                "Name"
            )
            in ("no", "", None),
            "why_it_matters": (
                "un volume anonyme est supprimé par un élagage de volumes sans "
                "qu'aucun nom ne le rattache à ce travail"
            ),
        },
        "secrets_published": False,
    }


def construire_preuve(
    comptages_source: dict[str, int],
    comptages_restaures: dict[str, int],
    digests_source: dict[str, str],
    digests_restaures: dict[str, str],
    controles: dict[str, int],
) -> dict:
    tables = sorted(set(comptages_source) | set(comptages_restaures))
    ecarts = [
        {
            "table": table,
            "source": comptages_source.get(table),
            "restored": comptages_restaures.get(table),
        }
        for table in tables
        if comptages_source.get(table) != comptages_restaures.get(table)
    ]
    digests_divergents = [
        {
            "scope": cle,
            "source": digests_source.get(cle),
            "restored": digests_restaures.get(cle),
        }
        for cle in sorted(set(digests_source) | set(digests_restaures))
        if digests_source.get(cle) != digests_restaures.get(cle)
    ]
    if not comptages_source or not digests_source:
        raise EntreeManquante(
            "une preuve de restauration exige des comptages ET des digests de source"
        )
    prouve = not ecarts and not digests_divergents
    return {
        "kind": KIND_PREUVE,
        "table_counts_source": comptages_source,
        "table_counts_restored": comptages_restaures,
        "count_mismatches": ecarts,
        "review_text_digests_match": not digests_divergents,
        "digest_mismatches": digests_divergents,
        "checks": controles,
        "restore_proven": prouve,
        "why": (
            "comptages et digests logiques du texte de revue identiques"
            if prouve
            else "au moins un comptage ou un digest diffère : la restauration n'est pas prouvée"
        ),
    }


def normaliser_emplacement(chemin: str) -> str:
    """Rend l'emplacement lisible sans publier l'arborescence de la machine.

    Le dépôt ne doit porter aucun chemin absolu machine-local. Un chemin
    relatif au foyer reste actionnable pour qui exploite la sauvegarde, sans
    inscrire dans le versionné la structure du poste qui l'a produite.
    """
    foyer = str(Path.home())
    if chemin.startswith(foyer):
        return "~" + chemin[len(foyer) :]
    return chemin


def construire_manifeste_non_pdf(
    emplacement: str, fichiers: list[dict], total_attendu: int
) -> dict:
    emplacement = normaliser_emplacement(emplacement)
    return {
        "kind": KIND_NON_PDF,
        "durable_location": emplacement,
        "files": len(fichiers),
        "bytes": sum(f["size"] for f in fichiers),
        "expected_requests": total_attendu,
        "complete": len(fichiers) == total_attendu,
        "closes_gate_counter": False,
        "why_not": (
            "ce manifeste décrit un emplacement ; la décision de fermeture "
            "appartient au gate, qui mesure sous la politique de conservation"
        ),
        "coverage_authority": (
            "docs/reports/go_live/non_pdf_37_vs_57_reconciliation.json porte la "
            "couverture ligne à ligne ; ce manifeste ne décrit que l'emplacement"
        ),
        "sha256sums": sorted(fichiers, key=lambda f: f["name"]),
    }


def rendre_inventaire_md(etat: dict) -> str:
    risque = etat["risk"]
    lignes = [
        "# Conteneur de revue : inventaire de préservation",
        "",
        "Document dérivé. Ne pas éditer à la main :",
        "`scripts/go_live/report_staging_preservation.py` le régénère.",
        "",
        f"- conteneur : `{etat['container_name']}` (`{etat['container_id']}`)",
        f"- image : `{etat['image']}`",
        f"- état : **{etat['state']}**, démarré {etat['started_at'][:19]}, "
        f"{etat['restart_count']} redémarrage(s)",
        f"- politique de redémarrage : `{etat['restart_policy']}`",
        f"- santé : {etat['health']}",
        f"- réseaux : {', '.join(etat['networks'])}",
        "",
        "## Montages",
        "",
        "| type | nom | destination | anonyme |",
        "| --- | --- | --- | :---: |",
    ]
    for montage in etat["mounts"]:
        lignes.append(
            f"| {montage['type']} | `{montage['name'][:16]}…` | "
            f"`{montage['destination']}` | "
            f"{'**oui**' if montage['anonymous_volume'] else 'non'} |"
        )
    lignes += [
        "",
        "## Risque",
        "",
        f"- volumes anonymes : **{risque['anonymous_volumes']}**",
        f"- sans politique de redémarrage : "
        f"**{'oui' if risque['restart_policy_is_none'] else 'non'}**",
        "",
        f"{risque['why_it_matters']}.",
        "",
        "Aucun secret n'est publié dans ce document : toute variable dont le nom",
        "évoque un secret est masquée, quelle que soit sa valeur.",
        "",
    ]
    return "\n".join(lignes)


def rendre_preuve_md(etat: dict) -> str:
    lignes = [
        "# Sauvegarde de la base de revue : preuve de restauration",
        "",
        "Document dérivé. Ne pas éditer à la main.",
        "",
        "Une sauvegarde non restaurée n'est pas une sauvegarde.",
        "",
        f"Restauration prouvée : **{'oui' if etat['restore_proven'] else 'NON'}** — {etat['why']}.",
        "",
        "## Comptages",
        "",
        "| table | source | restauré |",
        "| --- | ---: | ---: |",
    ]
    for table in sorted(etat["table_counts_source"]):
        lignes.append(
            f"| `{table}` | {etat['table_counts_source'][table]} | "
            f"{etat['table_counts_restored'].get(table, '—')} |"
        )
    lignes += [
        "",
        f"Digests logiques du texte de revue identiques : "
        f"**{'oui' if etat['review_text_digests_match'] else 'NON'}**.",
        "",
        "Des comptages égaux sur un texte différent ne prouveraient rien : c'est",
        "pourquoi les digests sont comparés en plus des comptages.",
        "",
        "## Contrôles",
        "",
        "| contrôle | valeur |",
        "| --- | ---: |",
    ]
    for controle, valeur in sorted(etat["checks"].items()):
        lignes.append(f"| {controle} | {valeur} |")
    lignes.append("")
    return "\n".join(lignes)


def rendre_non_pdf_md(etat: dict) -> str:
    return "\n".join(
        [
            "# Non-PDF : conservation durable",
            "",
            "Document dérivé. Ne pas éditer à la main.",
            "",
            f"- emplacement : `{etat['durable_location']}`",
            f"- fichiers : **{etat['files']}** / {etat['expected_requests']} attendus",
            f"- octets : **{etat['bytes']}**",
            f"- complet : **{'oui' if etat['complete'] else 'non'}**",
            "",
            f"Ferme le compteur du gate : **{'oui' if etat['closes_gate_counter'] else 'non'}** — "
            f"{etat['why_not']}.",
            "",
            etat["coverage_authority"] + ".",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--inspect", required=True)
    analyseur.add_argument("--proof-input", required=True, help="JSON des mesures de restauration")
    analyseur.add_argument("--non-pdf-input", required=True, help="JSON du magasin durable")
    arguments = analyseur.parse_args(argv)

    racine = racine_depot()
    try:
        inventaire = construire_inventaire(_lire_json(Path(arguments.inspect)))
        mesures = _lire_json(Path(arguments.proof_input))
        preuve = construire_preuve(
            mesures["counts_source"],
            mesures["counts_restored"],
            mesures["digests_source"],
            mesures["digests_restored"],
            mesures["checks"],
        )
        magasin = _lire_json(Path(arguments.non_pdf_input))
        non_pdf = construire_manifeste_non_pdf(
            magasin["location"], magasin["files"], magasin["expected_requests"]
        )
    except EntreeManquante as erreur:
        print(f"ENTREE_MANQUANTE: {erreur}", file=sys.stderr)
        return 2

    sorties = (
        ("docs/reports/go_live/staging_container_preservation_inventory.json", inventaire, None),
        ("docs/reports/go_live/STAGING_CONTAINER_PRESERVATION_INVENTORY.md", inventaire, rendre_inventaire_md),
        ("docs/reports/go_live/staging_backup_restore_proof.json", preuve, None),
        ("docs/reports/go_live/STAGING_BACKUP_RESTORE_PROOF.md", preuve, rendre_preuve_md),
        ("docs/reports/go_live/non_pdf_durable_storage_manifest.json", non_pdf, None),
        ("docs/reports/go_live/NON_PDF_DURABLE_STORAGE_MANIFEST.md", non_pdf, rendre_non_pdf_md),
    )
    for relatif, etat, rendu in sorties:
        chemin = racine / relatif
        chemin.parent.mkdir(parents=True, exist_ok=True)
        contenu = (
            rendu(etat)
            if rendu
            else json.dumps(etat, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        )
        chemin.write_text(contenu, encoding="utf-8")
        print(f"écrit : {chemin}")
    return 0 if preuve["restore_proven"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
