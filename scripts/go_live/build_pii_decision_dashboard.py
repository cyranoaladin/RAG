#!/usr/bin/env python3
"""Rend les décisions PII actionnables, sans en prendre aucune.

Cent quarante-neuf paquets attendent une décision humaine. Présentés en vrac,
ils se valent tous ; hiérarchisés, ils ne se valent plus du tout — vingt-trois
portent sur des contenus **déjà dans la release promue**, et ceux-là ne sont
pas en attente de promotion : ils sont déjà là.

Ce tableau de bord classe, chiffre l'effet de chaque décision, et s'arrête là.
Il ne décide rien, et il n'écrit aucune PII : le dépôt ne reçoit que des
empreintes, des classes de signal et des comptes. La matière brute vit hors
dépôt, sous le préparateur de paquets gouverné.

Le risque affiché n'est pas un verdict. Il ordonne la revue ; il ne la
remplace pas, et un contenu « à faible risque » reste indécis tant qu'un
humain ne l'a pas tranché.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

KIND = "NEXUS-PII-HUMAN-DECISION-DASHBOARD-V1"

PAQUETS = "docs/reports/go_live/pii_review_packets.json"
ETAT = "docs/reports/go_live/go_live_readiness_state.json"

DECISIONS_AUTORISEES = (
    "PII_CLEARED",
    "PII_REDACTION_REQUIRED",
    "EXCLUDE_FROM_SERVABLE_SET",
    "HUMAN_REVIEW_REQUIRED",
)

#: Classes de signal qui désignent une personne identifiable de façon directe.
#: Leur présence ne décide rien : elle place le contenu plus haut dans l'ordre
#: de revue.
CLASSES_DIRECTES = frozenset(
    {"french_ssn", "email_address", "phone_french", "postal_address"}
)


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


def _risque(classes: list[str]) -> str:
    """Ordonne la revue. Ne prononce aucun verdict."""
    directes = CLASSES_DIRECTES & set(classes)
    if "french_ssn" in directes:
        return "ELEVE"
    if directes:
        return "MOYEN"
    return "A_QUALIFIER"


def construire(racine: Path) -> dict:
    paquets = _lire(racine, PAQUETS)
    etat = _lire(racine, ETAT)
    lignes = paquets.get("packets")
    if not lignes:
        raise EntreeManquante(f"aucun paquet de revue : {racine / PAQUETS}")

    sorties = []
    for paquet in lignes:
        promu = bool(paquet["promoted"])
        classes = sorted(paquet.get("pii_categories") or [])
        sorties.append(
            {
                "content_sha256": paquet["content_sha256"],
                "pii_packet_id": paquet["pii_packet_id"],
                "promoted": promu,
                "release_impact": promu,
                "pii_categories": classes,
                "finding_count": paquet.get("finding_count", 0),
                "risk_level": _risque(classes),
                "expected_human_action": (
                    "revoir en priorité : ce contenu est DÉJÀ dans la release promue"
                    if promu
                    else "revoir avant toute promotion"
                ),
                "allowed_decisions": list(DECISIONS_AUTORISEES),
                "effect_if_cleared": {
                    "pii_undecided": -1,
                    "release_promoted_refused_contents": -1 if promu else 0,
                    "promoted_content_set_size": 0,
                    "GO_LIVE_READY": False,
                },
                "effect_if_excluded": {
                    "pii_undecided": -1,
                    "release_promoted_refused_contents": -1 if promu else 0,
                    "promoted_content_set_size": -1 if promu else 0,
                    "requires_release_reseal": promu,
                    "GO_LIVE_READY": False,
                },
                "decision": "",
                "reviewer": "",
                "raw_pii_included": False,
            }
        )

    # Les contenus déjà dans la release d'abord, puis le risque, puis l'empreinte.
    ordre_risque = {"ELEVE": 0, "MOYEN": 1, "A_QUALIFIER": 2}
    sorties.sort(
        key=lambda p: (
            not p["promoted"],
            ordre_risque[p["risk_level"]],
            p["content_sha256"],
        )
    )
    for rang, paquet in enumerate(sorties, start=1):
        paquet["review_order"] = rang

    promus = [p for p in sorties if p["promoted"]]
    return {
        "kind": KIND,
        "counts": {
            "packets_total": len(sorties),
            "promoted_packets": len(promus),
            "non_promoted_packets": len(sorties) - len(promus),
            "by_risk": dict(sorted(Counter(p["risk_level"] for p in sorties).items())),
            "by_category": dict(
                sorted(Counter(c for p in sorties for c in p["pii_categories"]).items())
            ),
        },
        "current_counters": {
            "pii_undecided": etat["pii_undecided"],
            "release_promoted_refused_contents": etat[
                "release_promoted_refused_contents"
            ],
            "go_live_ready": etat["go_live_ready"],
        },
        "allowed_decisions": list(DECISIONS_AUTORISEES),
        "decisions_made_here": 0,
        "raw_pii_in_output": False,
        "closing_all_pii_does_not_open_go_live": (
            "trancher les 149 ferme pii_undecided et une partie de l incoherence "
            "de release ; la recherche, la qualification et les PR bloquantes "
            "restent ouvertes, et le corpus reste sans vecteurs"
        ),
        "packets": sorties,
    }


def rendre_markdown(etat: dict) -> str:
    comptes = etat["counts"]
    lignes = [
        "# Décisions PII — tableau de pilotage",
        "",
        "Document dérivé. Ne pas éditer à la main :",
        "`scripts/go_live/build_pii_decision_dashboard.py` le régénère.",
        "",
        "**Aucune décision n'est prise ici. Aucune PII n'est écrite ici** :",
        "le dépôt ne reçoit que des empreintes, des classes de signal et des comptes.",
        "",
        f"- paquets en attente : **{comptes['packets_total']}**",
        f"- dont **déjà dans la release promue** : **{comptes['promoted_packets']}**",
        f"- autres : {comptes['non_promoted_packets']}",
        "",
        "## Pourquoi l'ordre compte",
        "",
        "Présentés en vrac, les paquets se valent tous. Ceux qui portent sur des",
        "contenus déjà promus ne sont pas en attente de promotion : ils sont déjà",
        "dans la release. Ils passent donc en premier.",
        "",
        "Le niveau de risque **ordonne** la revue ; il ne la remplace pas. Un",
        "contenu à faible risque reste indécis tant qu'un humain ne l'a pas tranché.",
        "",
        "## Répartition",
        "",
        "| risque | paquets |",
        "| --- | ---: |",
    ]
    for risque, nombre in comptes["by_risk"].items():
        lignes.append(f"| {risque} | {nombre} |")
    lignes += ["", "| catégorie relevée | contenus |", "| --- | ---: |"]
    for categorie, nombre in comptes["by_category"].items():
        lignes.append(f"| {categorie} | {nombre} |")
    lignes += [
        "",
        "## Décisions recevables",
        "",
    ]
    lignes += [f"- `{d}`" for d in etat["allowed_decisions"]]
    lignes += [
        "",
        "## Effet de chaque décision",
        "",
        "Pour un contenu **déjà promu** :",
        "",
        "- `PII_CLEARED` — sort de `pii_undecided` et de l'incohérence de release ;",
        "  la release garde le contenu ;",
        "- `EXCLUDE_FROM_SERVABLE_SET` — sort aussi, mais **exige un reseal** sous",
        "  une identité neuve, puisque le contenu quitte la release ;",
        "- `PII_REDACTION_REQUIRED` — le contenu doit être repris avant toute",
        "  décision de servabilité ;",
        "- `HUMAN_REVIEW_REQUIRED` — reste indécis, et le reste tant que personne",
        "  ne tranche.",
        "",
        "## Ce que fermer la PII ne fait pas",
        "",
        etat["closing_all_pii_does_not_open_go_live"] + ".",
        "",
        "## À revoir en premier",
        "",
        "| ordre | contenu | risque | catégories | signalements |",
        "| ---: | --- | --- | --- | ---: |",
    ]
    for paquet in etat["packets"][:23]:
        lignes.append(
            f"| {paquet['review_order']} | `{paquet['content_sha256'][:16]}…` | "
            f"{paquet['risk_level']} | {', '.join(paquet['pii_categories'])} | "
            f"{paquet['finding_count']} |"
        )
    lignes.append("")
    return "\n".join(lignes)


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--output-json",
        default="docs/reports/go_live/pii_human_decision_dashboard.json",
    )
    analyseur.add_argument(
        "--output-md",
        default="docs/reports/go_live/PII_HUMAN_DECISION_DASHBOARD.md",
    )
    arguments = analyseur.parse_args(argv)

    racine = racine_depot()
    try:
        etat = construire(racine)
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
    print(json.dumps(etat["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
