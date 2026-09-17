#!/usr/bin/env python3
"""PROPOSE des décisions PII / actualité. Une proposition n'est pas une décision.

Rien de ce que ce script écrit n'a d'effet : ni import, ni scellement, ni compteur.
Les décisions ne deviennent effectives que par l'approbation humaine de la PR qui
porte cette proposition, puis par l'import gouverné (lot CE).

Deux règles, et seulement deux :

1. RECONDUCTION — pour un contenu déjà tranché par le reviewer en V1, et
   seulement si la preuve est IDENTIQUE : mêmes instruments (politique, scanner,
   foyer de pages) et, finding par finding, mêmes motif, page, empreinte de la
   correspondance et empreinte du contexte. La proposition reprend alors les
   dispositions, la décision, la catégorie et le motif que le reviewer avait
   lui-même écrits. Un seul finding différent, et la règle ne s'applique pas.
2. EXCLUSION PAR PRÉCAUTION — pour tout autre contenu. Le script ne lit aucune
   matière brute et n'examine aucun finding : il ne peut donc rien « blanchir ».
   Chaque finding est présumé donnée personnelle, et le motif le dit tel quel.

Actualité : la source déclare l'archive et ADR-0055 la refuse ; sans source en
vigueur vérifiée, la seule proposition recevable est l'exclusion de la release.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_pii_currentness_decision_packet as dossier  # noqa: E402

KIND = "NEXUS-PII-CURRENTNESS-DECISION-PROPOSAL-V1"
REVIEWER = "abenrhouma"
DECISIONS_V1 = dossier.DECISIONS_V1
INDEX_PII = dossier.INDEX_PII

SORTIE_TSV = "docs/reports/go_live/pii_currentness_decision_proposal.tsv"
SORTIE_JSON = "docs/reports/evidence/pii_currentness_decision_proposal.json"
SORTIE_SHA = "docs/reports/evidence/pii_currentness_decision_proposal.sha256"

_INSTRUMENTS = ("policy_sha256", "scanner_sha256", "page_policy_sha256")
_OPTION_DE = {"APPROVED": "PII_CLEARED"}


def _cle_finding(f: dict[str, Any]) -> tuple:
    return (f["pattern_id"], f.get("page", f.get("page_number")), f["match_sha256"], f["context_sha256"])


def reconductibles(index_v2: dict[str, Any], v1: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Décisions V1 dont la preuve V2 est identique. Rend {content_sha256: décision V1}."""
    if any(index_v2[k] != v1[k] for k in _INSTRUMENTS):
        return {}
    paquets = {b["content_sha256"]: b for b in index_v2["bundles"]}
    retenues = {}
    for decision in v1["decisions"]:
        paquet = paquets.get(decision["content_sha256"])
        if paquet is None or decision["decision"] not in _OPTION_DE:
            continue
        anciens = {_cle_finding(f): f["disposition"] for f in decision["findings"]}
        if len(anciens) == len(decision["findings"]) and set(anciens) == {_cle_finding(f) for f in paquet["findings"]}:
            retenues[decision["content_sha256"]] = {**decision, "_par_finding": anciens}
    return retenues


def construire(racine: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    paquet = dossier.construire(racine)
    lignes = list(csv.DictReader(io.StringIO(dossier.rendre_tsv(paquet)), delimiter="\t"))
    index_v2 = json.loads((racine / INDEX_PII).read_text(encoding="utf-8"))
    v1 = json.loads((racine / DECISIONS_V1).read_text(encoding="utf-8"))
    reconduites = reconductibles(index_v2, v1)
    findings_v2 = {f["finding_id"]: f for b in index_v2["bundles"] for f in b["findings"]}

    regles: dict[str, str] = {}
    for ligne in lignes:
        sha = ligne["content_sha256"]
        if ligne["row_kind"] == "CURRENTNESS_CONTENT":
            ligne.update(
                HUMAN_DECISION="EXCLUDE_FROM_PROMOTED_RELEASE", REVIEWER_LOGIN=REVIEWER,
                COMMENT=("Proposition : exclusion. La source déclare ce document archivé et ADR-0055 le refuse ; "
                         "aucune source en vigueur vérifiée n'est disponible pour un remplacement."),
            )
            regles[sha] = "CURRENTNESS_EXCLUSION"
        elif ligne["row_kind"] == "PII_FINDING":
            ancienne = reconduites.get(sha)
            ligne["FINDING_DISPOSITION"] = (
                ancienne["_par_finding"][_cle_finding(findings_v2[ligne["finding_id"]])]
                if ancienne else "PERSONAL_DATA_PRESENT"
            )
        else:
            ancienne = reconduites.get(sha)
            if ancienne:
                ligne.update(
                    HUMAN_DECISION=_OPTION_DE[ancienne["decision"]],
                    JUSTIFICATION_CATEGORY=ancienne["justification"]["category"],
                    REVIEWER_LOGIN=REVIEWER, COMMENT=ancienne["justification"]["statement"],
                )
                regles[sha] = "CARRY_OVER_IDENTICAL_EVIDENCE"
            else:
                ligne.update(
                    HUMAN_DECISION="EXCLUDE_FROM_SERVABLE_SET", JUSTIFICATION_CATEGORY="PERSONAL_DATA_PRESENT",
                    REVIEWER_LOGIN=REVIEWER,
                    COMMENT=(f"Exclusion par précaution : {ligne['finding_count']} signalement(s) "
                             f"({ligne['signal_classes'].replace('|', ', ')}) non examinés individuellement, "
                             "présumés données personnelles ; le contenu n'est pas servi."),
                )
                regles[sha] = "PRECAUTIONARY_EXCLUSION"

    contenus = [x for x in lignes if x["row_kind"] == "PII_CONTENT"]
    promus = {x["content_sha256"] for x in contenus if x["promoted_in_release"] == "true"}
    par_regle = {r: sorted(s for s, v in regles.items() if v == r) for r in sorted(set(regles.values()))}
    resume = {
        "kind": KIND,
        "status": "PROPOSED_NOT_EFFECTIVE",
        "effective_only_by": "approbation humaine de la PR qui porte cette proposition, puis import gouverné (lot CE)",
        "reviewer_expected": REVIEWER,
        "raw_pii_read": False,
        "raw_pii_in_proposal": False,
        "inputs": {
            INDEX_PII: hashlib.sha256((racine / INDEX_PII).read_bytes()).hexdigest(),
            DECISIONS_V1: hashlib.sha256((racine / DECISIONS_V1).read_bytes()).hexdigest(),
            "decision_packet_sha256": (racine / dossier.SORTIE_SHA).read_text(encoding="utf-8").split()[0],
        },
        "rules": {
            "CARRY_OVER_IDENTICAL_EVIDENCE": "décision V1 du reviewer reconduite : instruments identiques et chaque finding identique (motif, page, empreintes de correspondance et de contexte)",
            "PRECAUTIONARY_EXCLUSION": "aucun examen : chaque finding présumé donnée personnelle, contenu exclu du périmètre servable",
            "CURRENTNESS_EXCLUSION": "archive déclarée par la source, refusée par ADR-0055, aucune source en vigueur vérifiée",
        },
        "counts": {
            "pii_contents": len(contenus),
            "pii_findings": sum(1 for x in lignes if x["row_kind"] == "PII_FINDING"),
            "currentness_contents": sum(1 for x in lignes if x["row_kind"] == "CURRENTNESS_CONTENT"),
            "by_rule": {r: len(s) for r, s in par_regle.items()},
            "promoted_carried_over": len(promus & set(par_regle.get("CARRY_OVER_IDENTICAL_EVIDENCE", []))),
            "promoted_excluded_for_pii": len(promus & set(par_regle.get("PRECAUTIONARY_EXCLUSION", []))),
            "by_human_decision": {
                d: sum(1 for x in lignes if x["HUMAN_DECISION"] == d)
                for d in sorted({x["HUMAN_DECISION"] for x in lignes if x["HUMAN_DECISION"]})
            },
        },
        "expected_counters_after_governed_import": {
            "pii_undecided": 0,
            "release_promoted_refused_contents": "0 une fois la release rescellée sans les contenus d'actualité exclus",
            "changed_by_this_proposal": "aucun",
        },
        "content_ids_by_rule": par_regle,
        "sheet": SORTIE_TSV,
    }
    return lignes, resume


def rendre_tsv(lignes: list[dict[str, str]]) -> str:
    tampon = io.StringIO()
    ecrit = csv.DictWriter(tampon, fieldnames=dossier.COLONNES, delimiter="\t", lineterminator="\n")
    ecrit.writeheader()
    ecrit.writerows(lignes)
    return tampon.getvalue()


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - orchestration
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    racine = Path(__file__).resolve().parents[2]
    lignes, resume = construire(racine)
    (racine / SORTIE_TSV).write_text(rendre_tsv(lignes), encoding="utf-8")
    resume["sheet_sha256"] = hashlib.sha256((racine / SORTIE_TSV).read_bytes()).hexdigest()
    octets = (json.dumps(resume, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    (racine / SORTIE_JSON).write_bytes(octets)
    (racine / SORTIE_SHA).write_text(f"{hashlib.sha256(octets).hexdigest()}  {SORTIE_JSON}\n", encoding="utf-8")
    print(json.dumps(resume["counts"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
