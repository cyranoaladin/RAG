#!/usr/bin/env python3
"""Prépare la revue PII sans décider, et refuse un texte qui n'est pas celui scanné.

Ce script n'ouvre aucun PDF. Il confronte l'index de revue versionné à la base
du run, empreinte par empreinte, et n'émet un paquet que pour les contenus dont
le texte est prouvé identique des deux côtés. Une divergence est un refus, pas
un avertissement : un reviewer qui statuerait sur un texte autre que celui qui
a été scanné ne prouverait rien de ce sur quoi il croit statuer.

Ce qu'il ne fait jamais :

- il ne décide aucune disposition PII. Le champ de décision sort vide, et un
  paquet sans décision ne fait baisser aucun compteur ;
- il n'écrit aucune PII. Le dépôt ne reçoit que des empreintes, des classes de
  signal et des comptes. La matière brute vit hors dépôt, sous le préparateur
  de paquets gouverné, et n'a pas sa place ici ;
- il ne touche ni la matrice, ni le compteur `pii_undecided`.

L'ordre de présentation n'est pas cosmétique : les contenus déjà promus
passent en premier, parce qu'ils sont dans la release et que leur décision est
la plus urgente.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

KIND = "NEXUS-PII-REVIEW-PACKETS-V1"

INDEX_REVUE = "docs/reports/evidence-index/pii_review_index_v2_20260907.json"
MATRICE = "docs/reports/handoff/servability_matrix_v1.json"

VERDICT_PII = "BLOCKED_PII_HUMAN_REVIEW"

#: Les seules décisions qu'un reviewer peut inscrire. Aucune n'est prononcée ici.
DECISIONS_AUTORISEES = (
    "PII_CLEARED",
    "PII_REDACTION_REQUIRED",
    "EXCLUDE_FROM_SERVABLE_SET",
    "HUMAN_REVIEW_REQUIRED",
)

COLONNES_FEUILLE = (
    "pii_packet_id",
    "content_sha256",
    "promoted",
    "path",
    "pii_category",
    "decision",
    "decision_reason",
    "reviewer",
    "review_date",
    "evidence",
)


class EntreeManquante(RuntimeError):
    """Une entrée nécessaire au calcul est absente ou inexploitable."""


class TexteDeRevueDivergent(RuntimeError):
    """La base ne porte pas le texte que l'index dit avoir été scanné."""


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


def lire_textes_canoniques(dsn: str, schema: str) -> dict[str, str]:
    """Lecture seule. Retourne content_sha256 -> canonical_text_sha256."""
    try:
        import psycopg
    except ModuleNotFoundError as erreur:  # pragma: no cover - dépend de l'env
        raise EntreeManquante(f"psycopg indisponible : {erreur}") from erreur
    try:
        connexion = psycopg.connect(dsn)
    except psycopg.OperationalError as erreur:
        raise EntreeManquante(
            f"connexion refusée par la base ({type(erreur).__name__})"
        ) from None
    with connexion:
        with connexion.cursor() as curseur:
            curseur.execute(
                "select count(*) from pg_namespace where nspname = %s", (schema,)
            )
            if not curseur.fetchone()[0]:
                raise EntreeManquante(f"schéma « {schema} » absent de la base")
            curseur.execute(
                f'select content_sha256, canonical_text_sha256 from "{schema}".artifacts'  # noqa: S608
            )
            return {c: t for c, t in curseur.fetchall() if c}


def construire(
    racine: Path,
    textes_en_base: dict[str, str],
    promus: set[str],
) -> dict:
    index = _lire(racine, INDEX_REVUE)
    paquets = index.get("bundles")
    if not paquets:
        raise EntreeManquante(f"index de revue sans paquet : {racine / INDEX_REVUE}")

    lignes = _lire(racine, MATRICE).get("rows")
    if not lignes:
        raise EntreeManquante(f"matrice sans lignes : {racine / MATRICE}")
    bloques = {
        ligne["content_sha256"] for ligne in lignes if ligne["verdict"] == VERDICT_PII
    }

    divergents: list[dict] = []
    absents: list[str] = []
    sorties: list[dict] = []

    for paquet in paquets:
        contenu = paquet["content_sha256"]
        attendu = paquet["canonical_text_sha256"]
        observe = textes_en_base.get(contenu)

        if observe is None:
            absents.append(contenu)
            continue
        if observe != attendu:
            divergents.append(
                {
                    "content_sha256": contenu,
                    "index_canonical_text_sha256": attendu,
                    "database_canonical_text_sha256": observe,
                }
            )
            continue

        promu = contenu in promus
        classes = sorted(paquet.get("signal_classes") or [])
        sorties.append(
            {
                "pii_packet_id": paquet["bundle_id"],
                "content_sha256": contenu,
                "promoted": promu,
                "scope": sorted(paquet.get("placements") or []),
                "source_path": paquet.get("source_path", ""),
                "reviewed_text_sha256": attendu,
                "page_provenance_digest": paquet.get("page_provenance_digest", ""),
                "bundle_sha256": paquet.get("bundle_sha256", ""),
                "pii_categories": classes,
                "finding_count": paquet.get("finding_count", 0),
                "pages_with_findings": sorted(
                    {f["page_number"] for f in paquet.get("findings", [])}
                ),
                "why_undecided": (
                    "le scanner a relevé des correspondances ; aucune décision "
                    "humaine n'a été enregistrée pour ce contenu"
                ),
                "recommended_action": (
                    "revoir en priorité : ce contenu est déjà dans la release promue"
                    if promu
                    else "revoir avant toute promotion"
                ),
                "allowed_decisions": list(DECISIONS_AUTORISEES),
                "impact_if_cleared": (
                    "le contenu reste dans la release et devient candidat servable"
                    if promu
                    else "le contenu devient candidat servable"
                ),
                "impact_if_excluded": (
                    "le contenu doit sortir de la release promue, ce qui exige une "
                    "nouvelle identité de release"
                    if promu
                    else "le contenu reste hors du périmètre servable"
                ),
                # Champs laissés vides : ils appartiennent au reviewer.
                "reviewer_decision": "",
                "evidence": "",
                "audit_trail": "",
                "raw_pii_included": False,
            }
        )

    # Les contenus déjà promus d'abord : ils sont dans la release.
    sorties.sort(key=lambda p: (not p["promoted"], p["source_path"]))

    # La matrice n'est pas lue pour décider : elle est lue pour être CONTREDITE
    # si elle l'est. L'index de revue et la matrice recensent le même ensemble
    # de contenus en attente ; s'ils divergent, l'un des deux est périmé et une
    # revue conduite sur le mauvais ensemble laisserait passer un contenu.
    contenus_index = {paquet["content_sha256"] for paquet in paquets}
    index_seul = sorted(contenus_index - bloques)
    matrice_seule = sorted(bloques - contenus_index)
    accord = not index_seul and not matrice_seule

    return {
        "kind": KIND,
        "campaign_id": index.get("campaign_id", ""),
        "review_index_protocol": index.get("protocol_version", ""),
        "counts": {
            "packets_exported": len(sorties),
            "packets_in_index": len(paquets),
            "blocked_by_matrix": len(bloques),
            "promoted_among_exported": sum(1 for p in sorties if p["promoted"]),
            "divergent_review_text": len(divergents),
            "absent_from_database": len(absents),
        },
        "by_category": dict(
            sorted(Counter(c for p in sorties for c in p["pii_categories"]).items())
        ),
        "index_matrix_agreement": {
            "agree": accord,
            "in_index_not_in_matrix": index_seul,
            "in_matrix_not_in_index": matrice_seule,
            "why_it_matters": (
                "une revue conduite sur un ensemble périmé laisserait passer un "
                "contenu en attente de décision"
            ),
        },
        "divergences": divergents,
        "absent_from_database": sorted(absents),
        "allowed_decisions": list(DECISIONS_AUTORISEES),
        "decisions_made_here": 0,
        "raw_pii_in_output": False,
        "does_not_change": [
            "la matrice de servabilité",
            "le compteur pii_undecided",
            "l'ensemble promu",
        ],
        "packets": sorties,
    }


def rendre_feuille(etat: dict) -> str:
    lignes = ["\t".join(COLONNES_FEUILLE)]
    for paquet in etat["packets"]:
        lignes.append(
            "\t".join(
                (
                    paquet["pii_packet_id"],
                    paquet["content_sha256"],
                    "yes" if paquet["promoted"] else "no",
                    paquet["source_path"],
                    ",".join(paquet["pii_categories"]),
                    "",  # decision — au reviewer
                    "",  # decision_reason
                    "",  # reviewer
                    "",  # review_date
                    "",  # evidence
                )
            )
        )
    return "\n".join(lignes) + "\n"


def rendre_markdown(etat: dict) -> str:
    comptes = etat["counts"]
    lignes = [
        "# Paquets de revue PII",
        "",
        "Document dérivé. Ne pas éditer à la main :",
        "`scripts/go_live/export_pii_review_packets.py` le régénère.",
        "",
        "Aucune décision n'est prise ici. Aucune PII n'est écrite ici :",
        "le dépôt ne reçoit que des empreintes, des classes de signal et des comptes.",
        "",
        f"- paquets exportés : **{comptes['packets_exported']}**",
        f"- dont déjà promus : **{comptes['promoted_among_exported']}**",
        f"- textes de revue divergents (refusés) : **{comptes['divergent_review_text']}**",
        f"- absents de la base (refusés) : **{comptes['absent_from_database']}**",
        f"- décisions prises par ce script : **{etat['decisions_made_here']}**",
        "",
        "## Catégories relevées",
        "",
        "| catégorie | contenus |",
        "| --- | ---: |",
    ]
    for categorie, nombre in etat["by_category"].items():
        lignes.append(f"| {categorie} | {nombre} |")
    lignes += [
        "",
        "## Décisions recevables",
        "",
    ]
    lignes += [f"- `{d}`" for d in etat["allowed_decisions"]]
    lignes += [
        "",
        "## Ce que ce document ne change pas",
        "",
    ]
    lignes += [f"- {x}" for x in etat["does_not_change"]]
    lignes += [
        "",
        "## À revoir en premier — contenus déjà dans la release",
        "",
        "| contenu | catégories | signalements |",
        "| --- | --- | ---: |",
    ]
    for paquet in etat["packets"]:
        if not paquet["promoted"]:
            continue
        lignes.append(
            f"| `{paquet['content_sha256'][:16]}…` | "
            f"{', '.join(paquet['pii_categories'])} | {paquet['finding_count']} |"
        )
    lignes.append("")
    return "\n".join(lignes)


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--dsn", required=True)
    analyseur.add_argument("--schema", default="drive_staging")
    analyseur.add_argument("--promoted-set", required=True)
    analyseur.add_argument(
        "--output-json", default="docs/reports/go_live/pii_review_packets.json"
    )
    analyseur.add_argument(
        "--output-md", default="docs/reports/go_live/PII_REVIEW_PACKETS.md"
    )
    analyseur.add_argument(
        "--output-sheet",
        default="docs/reports/go_live/pii_review_decision_sheet.tsv",
    )
    arguments = analyseur.parse_args(argv)

    racine = racine_depot()
    try:
        promus = set(
            json.loads(Path(arguments.promoted_set).read_text(encoding="utf-8"))[
                "content_sha256"
            ]
        )
        textes = lire_textes_canoniques(arguments.dsn, arguments.schema)
        etat = construire(racine, textes, promus)
    except EntreeManquante as erreur:
        print(f"ENTREE_MANQUANTE: {erreur}", file=sys.stderr)
        return 2

    for relatif, contenu in (
        (arguments.output_json, json.dumps(etat, indent=2, ensure_ascii=False, sort_keys=True) + "\n"),
        (arguments.output_md, rendre_markdown(etat)),
        (arguments.output_sheet, rendre_feuille(etat)),
    ):
        chemin = racine / relatif
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(contenu, encoding="utf-8")
        print(f"écrit : {chemin}")

    print(json.dumps(etat["counts"], ensure_ascii=False))
    # Un texte divergent, ou un désaccord entre l'index et la matrice, est un
    # refus : le lot ne peut pas se dire prêt.
    conforme = (
        etat["counts"]["divergent_review_text"] == 0
        and etat["counts"]["absent_from_database"] == 0
        and etat["index_matrix_agreement"]["agree"]
    )
    return 0 if conforme else 1


if __name__ == "__main__":
    raise SystemExit(main())
