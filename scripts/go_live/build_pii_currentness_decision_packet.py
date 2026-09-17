#!/usr/bin/env python3
"""Prépare le dossier de décision humaine PII / actualité. Ne décide rien.

Le dossier est DÉRIVÉ des autorités versionnées, qu'il CONSOMME sans les refaire :
tableau de pilotage PII (ordre de revue, niveau de risque), index de revue PII V2
(findings), impact de release (contenus promus refusés), état de readiness. Il ne
lit pas la matrice de servabilité : elle est dérivée, et ses lecteurs sont épinglés.

Ce qu'il ajoute à la feuille PII existante (`pii_review_decision_sheet.tsv`) : les
lignes d'actualité, une ligne PAR FINDING — le contrat de décisions exige une
disposition pour chacun —, et le rappel des décisions V1 non étendues. Il ne porte aucune
matière brute — ni `match_text` ni `context` : empreintes, classes de motif,
pages, comptes. Les extraits à lire sont dans les paquets de revue hors dépôt
(`preparer_paquets_revue_pii.py --output-root`), que chaque ligne désigne.

Trois choses qu'il s'interdit :
- pré-remplir une décision (toute colonne de décision sort vide) ;
- étendre une décision V1 aux empreintes V2 (elle est citée comme contexte) ;
- modifier un compteur : le readiness n'est ni lu en écriture ni régénéré ici.
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

KIND = "NEXUS-PII-CURRENTNESS-HUMAN-DECISION-PACKET-V1"

PILOTAGE = "docs/reports/go_live/pii_human_decision_dashboard.json"
INDEX_PII = "docs/reports/evidence-index/pii_review_index_v2_20260907.json"
IMPACT = "docs/reports/go_live/currentness_release_impact.json"
READINESS = "docs/reports/go_live/go_live_readiness_state.json"
DECISIONS_V1 = "governance/pii-review-decisions/pii-review-2026-09-03-final.json"

SORTIE_JSON = "docs/reports/evidence/pii_currentness_human_decision_packet.json"
SORTIE_SHA = "docs/reports/evidence/pii_currentness_human_decision_packet.sha256"
SORTIE_TSV = "docs/reports/go_live/pii_currentness_decision_sheet.tsv"
#: Extrait STRICT de la feuille complète : les seules lignes qui débloquent C1.
SORTIE_TSV_C1 = "docs/reports/go_live/pii_currentness_c1_minimal_sheet.tsv"
SORTIE_MD_C1 = "docs/reports/go_live/PII_CURRENTNESS_C1_MINIMAL_SHEET.md"
PRIORITE_C1 = "P1_PROMOTED_BLOCKS_RELEASE"

OPTIONS_PII = (
    "PII_CLEARED", "PII_REDACTION_REQUIRED", "EXCLUDE_FROM_SERVABLE_SET", "HUMAN_REVIEW_REQUIRED",
)
OPTIONS_ACTUALITE = (
    "KEEP_IF_STILL_CURRENT_WITH_EVIDENCE", "REPLACE_WITH_CURRENT_SOURCE",
    "EXCLUDE_FROM_PROMOTED_RELEASE", "HUMAN_REVIEW_REQUIRED",
)
#: Dispositions par finding du contrat `NEXUS-PII-REVIEW-DECISIONS-V1`.
DISPOSITIONS_FINDING = (
    "FALSE_POSITIVE_TECHNICAL", "PUBLIC_INSTITUTIONAL_DATA", "SYNTHETIC_EXAMPLE", "PERSONAL_DATA_PRESENT",
)
COLONNES = (
    "row_kind", "priority", "content_sha256", "promoted_in_release", "title", "source_path",
    "risk_tier", "signal_classes", "finding_count", "pages",
    "finding_id", "pattern_id", "page", "extraction_path",
    "review_bundle_dir", "prior_v1_decision_not_extended", "currentness_declared",
    "allowed_options", "HUMAN_DECISION", "FINDING_DISPOSITION", "JUSTIFICATION_CATEGORY",
    "REVIEWER_LOGIN", "EVIDENCE_REFERENCE", "COMMENT",
)


class EntreeIncoherente(RuntimeError):
    """Les autorités ne disent pas la même chose : on ne prépare pas un dossier dessus."""


def racine_depot() -> Path:
    return Path(__file__).resolve().parents[2]


def _charger(racine: Path, relatif: str) -> tuple[Any, str]:
    octets = (racine / relatif).read_bytes()
    return json.loads(octets), hashlib.sha256(octets).hexdigest()


def construire(racine: Path) -> dict[str, Any]:
    pilotage, sha_pilotage = _charger(racine, PILOTAGE)
    index, sha_index = _charger(racine, INDEX_PII)
    impact, sha_impact = _charger(racine, IMPACT)
    readiness, sha_readiness = _charger(racine, READINESS)
    v1, sha_v1 = _charger(racine, DECISIONS_V1)

    pilotes = {p["content_sha256"]: p for p in pilotage["packets"]}
    paquets = {b["content_sha256"]: b for b in index["bundles"]}
    promus_refuses = set(readiness["release_promoted_refused_content_ids"])
    impact_par_sha = {r["content_sha256"]: r for r in impact["rows"]}
    v1_par_sha = {d["content_sha256"]: d for d in v1["decisions"]}

    # Les autorités doivent se recouper exactement, sinon le dossier mentirait.
    if len(pilotes) != readiness["pii_undecided"]:
        raise EntreeIncoherente(f"pilotage {len(pilotes)} paquets != readiness {readiness['pii_undecided']}")
    if set(pilotes) != set(paquets):
        raise EntreeIncoherente("le tableau de pilotage et l'index de revue V2 ne recensent pas le même ensemble")
    if len(promus_refuses) != readiness["release_promoted_refused_contents"] or promus_refuses != set(impact_par_sha):
        raise EntreeIncoherente("contenus promus refusés : readiness et impact de release divergent")
    actualite = sorted(s for s, r in impact_par_sha.items() if r["blocking_gate_now"] == "CURRENTNESS_GATE")
    pii_promus = sorted(s for s, r in impact_par_sha.items() if r["blocking_gate_now"] == "PII_GATE")
    if len(actualite) != readiness["release_promoted_refused_by_currentness"]:
        raise EntreeIncoherente("contenus promus refusés pour actualité : readiness et impact divergent")
    if set(pii_promus) != {s for s, p in pilotes.items() if p["promoted"]}:
        raise EntreeIncoherente("contenus promus bloqués PII : pilotage et impact de release divergent")
    if len(actualite) + len(pii_promus) != len(promus_refuses):
        raise EntreeIncoherente("un contenu promu refusé n'est ni PII ni actualité")

    contenus_pii = []
    for sha in sorted(pilotes, key=lambda s: (pilotes[s]["review_order"], s)):
        paquet = paquets[sha]
        ancien = v1_par_sha.get(sha)
        contenus_pii.append(
            {
                "content_sha256": sha,
                "promoted_in_release": sha in promus_refuses,
                "priority": "P1_PROMOTED_BLOCKS_RELEASE" if sha in promus_refuses else "P2_CANDIDATE",
                "title": paquet["title"],
                "source_path": paquet["source_path"],
                "page_count": paquet["page_count"],
                "pages_with_findings": paquet["pages"],
                "signal_classes": paquet["signal_classes"],
                "finding_count": paquet["finding_count"],
                "review_order": pilotes[sha]["review_order"],
                "risk_tier": pilotes[sha]["risk_level"],
                "currentness": impact_par_sha[sha]["currentness_before"] if sha in impact_par_sha else "",
                "review_bundle": {
                    "bundle_id": paquet["bundle_id"],
                    "bundle_dir": paquet["bundle_dir"],
                    "bundle_sha256": paquet["bundle_sha256"],
                    "canonical_text_sha256": paquet["canonical_text_sha256"],
                    "minimal_extracts": "hors dépôt : <output-root>/<bundle_dir>/pages/page-NNNN.txt",
                },
                "findings": [
                    {
                        "finding_id": f["finding_id"],
                        "pattern_id": f["pattern_id"],
                        "page": f["page_number"],
                        "extraction_path": f["extraction_path"],
                        "match_sha256": f["match_sha256"],
                        "context_sha256": f["context_sha256"],
                        "human_disposition": None,
                    }
                    for f in paquet["findings"]
                ],
                "prior_v1_decision_not_extended": (
                    {
                        "decision_set_id": v1["decision_set_id"],
                        "decision": ancien["decision"],
                        "justification_category": ancien["justification"]["category"],
                        "why_not_extended": (
                            "rendue sur l'index de revue V1 ; la campagne V2 a un autre texte canonique "
                            "et un autre paquet : ADR-0047, aucune décision n'est étendue"
                        ),
                    }
                    if ancien
                    else None
                ),
                "allowed_options": list(OPTIONS_PII),
                "human_decision": None,
            }
        )

    contenus_actualite = [
        {
            "content_sha256": sha,
            "promoted_in_release": True,
            "priority": "P1_PROMOTED_BLOCKS_RELEASE",
            "drive_path": impact_par_sha[sha]["drive_path"],
            "currentness_declared": impact_par_sha[sha]["currentness_before"],
            "currentness_disposition": impact_par_sha[sha]["currentness_disposition"],
            "pii_status": impact_par_sha[sha]["pii_status"],
            "source_role": impact_par_sha[sha]["source_role"],
            "risk_rationale": (
                "la source déclare ce document archivé : le servir présente comme en vigueur un "
                "texte que son éditeur a retiré"
            ),
            "repository_possible_actions": impact_par_sha[sha]["possible_actions"],
            "allowed_options": list(OPTIONS_ACTUALITE),
            "human_decision": None,
        }
        for sha in actualite
    ]

    return {
        "kind": KIND,
        "status": "AWAITING_HUMAN_DECISION",
        "decision": "HUMAN_GATE_REQUIRED_PII_CURRENTNESS",
        "note": (
            "Dossier DÉRIVÉ. Aucune décision n'est pré-remplie, aucune décision V1 n'est étendue, "
            "aucun compteur n'est modifié, aucune release n'est produite."
        ),
        "raw_pii_in_packet": False,
        "inputs": {
            PILOTAGE: sha_pilotage, INDEX_PII: sha_index, IMPACT: sha_impact,
            READINESS: sha_readiness, DECISIONS_V1: sha_v1,
        },
        "review_campaign": {
            "campaign_id": index["campaign_id"],
            "review_index_sha256": sha_index,
            "content_set_sha256": index["content_set_sha256"],
            "bundle_generator": index["generator_path"],
            "decision_protocol": "NEXUS-PII-REVIEW-DECISIONS-V1",
            "decisions_dir": "governance/pii-review-decisions",
        },
        "counts": {
            "pii_undecided": len(pilotes),
            "pii_findings": sum(c["finding_count"] for c in contenus_pii),
            "pii_by_risk_level": {
                niveau: sum(c["risk_tier"] == niveau for c in contenus_pii)
                for niveau in sorted({c["risk_tier"] for c in contenus_pii})
            },
            "promoted_blocked_by_pii": len(pii_promus),
            "promoted_blocked_by_currentness": len(actualite),
            "release_promoted_refused_contents": len(promus_refuses),
            "decisions_prefilled": 0,
        },
        "option_semantics": {
            "PII_CLEARED": (
                "décision APPROVED du contrat : CHAQUE finding reçoit une disposition admissible "
                "(FALSE_POSITIVE_TECHNICAL, PUBLIC_INSTITUTIONAL_DATA, SYNTHETIC_EXAMPLE)"
            ),
            "PII_REDACTION_REQUIRED": (
                "décision REJECTED (au moins un PERSONAL_DATA_PRESENT). Le contenu caviardé est un AUTRE "
                "contenu (artifact_id = content_sha256) : nouvelle acquisition, nouveau scan, nouvelle revue"
            ),
            "EXCLUDE_FROM_SERVABLE_SET": "décision REJECTED ; le contenu sort du périmètre servable et de la release",
            "HUMAN_REVIEW_REQUIRED": "aucune décision : le contenu reste PII_UNDECIDED et continue de bloquer",
            "KEEP_IF_STILL_CURRENT_WITH_EVIDENCE": (
                "HUMAN_OVERRIDE_WITH_AUTHORITY : exige une preuve datée que le texte est en vigueur, "
                "contre la déclaration d'archive de la source"
            ),
            "REPLACE_WITH_CURRENT_SOURCE": "exclusion + acquisition de la source en vigueur (reconstruction de release)",
            "EXCLUDE_FROM_PROMOTED_RELEASE": "EXCLUDE_AND_RESEAL_RELEASE : retrait et rescellement sous identité neuve",
        },
        "finding_dispositions": list(DISPOSITIONS_FINDING),
        "pii_contents": contenus_pii,
        "currentness_contents": contenus_actualite,
        "does_not_do": [
            "ne choisit aucune option", "ne caviarde aucun contenu", "n'exclut aucun contenu",
            "ne réduit pas pii_undecided", "ne produit pas de release v3", "ne ferme aucun blocker",
        ],
    }


def rendre_tsv(dossier: dict[str, Any]) -> str:
    tampon = io.StringIO()
    ecrit = csv.DictWriter(tampon, fieldnames=COLONNES, delimiter="\t", lineterminator="\n")
    ecrit.writeheader()
    vide = dict.fromkeys(COLONNES, "")
    for c in dossier["currentness_contents"]:
        ecrit.writerow({
            **vide, "row_kind": "CURRENTNESS_CONTENT", "priority": c["priority"],
            "content_sha256": c["content_sha256"], "promoted_in_release": "true",
            "source_path": c["drive_path"], "currentness_declared": c["currentness_declared"],
            "allowed_options": "|".join(c["allowed_options"]),
        })
    for c in dossier["pii_contents"]:
        commun = {
            **vide, "priority": c["priority"], "content_sha256": c["content_sha256"],
            "promoted_in_release": str(c["promoted_in_release"]).lower(), "risk_tier": c["risk_tier"],
            "review_bundle_dir": c["review_bundle"]["bundle_dir"],
        }
        ancien = c["prior_v1_decision_not_extended"]
        ecrit.writerow({
            **commun, "row_kind": "PII_CONTENT", "title": c["title"], "source_path": c["source_path"],
            "signal_classes": "|".join(c["signal_classes"]), "finding_count": c["finding_count"],
            "pages": "|".join(map(str, c["pages_with_findings"])),
            "prior_v1_decision_not_extended": f"{ancien['decision']}/{ancien['justification_category']}" if ancien else "",
            "currentness_declared": c["currentness"], "allowed_options": "|".join(c["allowed_options"]),
        })
        for f in c["findings"]:
            ecrit.writerow({
                **commun, "row_kind": "PII_FINDING", "finding_id": f["finding_id"],
                "pattern_id": f["pattern_id"], "page": f["page"], "extraction_path": f["extraction_path"],
                "allowed_options": "|".join(DISPOSITIONS_FINDING),
            })
    return tampon.getvalue()


def rendre_tsv_c1(dossier: dict[str, Any]) -> str:
    """Les lignes de la feuille complète qui portent sur un contenu PROMU, à l'identique."""
    lignes = rendre_tsv(dossier).splitlines()
    colonne = COLONNES.index("priority")
    return "\n".join(
        [lignes[0], *(ligne for ligne in lignes[1:] if ligne.split("\t")[colonne] == PRIORITE_C1)]
    ) + "\n"


def rendre_markdown_c1(dossier: dict[str, Any]) -> str:
    """Vue de lecture. Aucune colonne de décision n'y figure : on décide dans le TSV."""
    promus = [c for c in dossier["pii_contents"] if c["promoted_in_release"]]
    sortie = [
        "# Chemin minimal pour débloquer C1 — vue de lecture",
        "",
        "Document dérivé (`scripts/go_live/build_pii_currentness_decision_packet.py`). Ne pas éditer à la main.",
        f"Les décisions se saisissent dans `{SORTIE_TSV_C1}`, jamais ici. **Aucune décision n'est pré-remplie.**",
        "",
        f"- contenus d'actualité : **{len(dossier['currentness_contents'])}**",
        f"- contenus PII promus : **{len(promus)}**, findings : **{sum(c['finding_count'] for c in promus)}**",
        "",
        "## 1. Actualité — la source déclare ces documents archivés",
        "",
        "| # | Document | Déclaré | Empreinte |",
        "|---|---|---|---|",
    ]
    for i, c in enumerate(dossier["currentness_contents"], 1):
        sortie.append(
            f"| A{i} | `{c['drive_path'].rsplit('/', 1)[-1]}` | {c['currentness_declared']} | `{c['content_sha256'][:12]}…` |"
        )
    sortie += [
        "",
        "## 2. PII — contenus promus, dans l'ordre de revue du tableau de pilotage",
        "",
        "| # | Risque | Document | Classes | Findings | Pages | Décision V1 (non étendue) | Paquet hors dépôt |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, c in enumerate(promus, 1):
        ancien = c["prior_v1_decision_not_extended"]
        sortie.append(
            f"| P{i} | {c['risk_tier']} | `{c['title']}` | {', '.join(c['signal_classes'])} | {c['finding_count']} | "
            f"{', '.join(map(str, c['pages_with_findings']))} | "
            f"{ancien['decision'] + ' / ' + ancien['justification_category'] if ancien else '—'} | "
            f"`{c['review_bundle']['bundle_dir'][:12]}…` |"
        )
    return "\n".join(sortie) + "\n"


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - orchestration
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    racine = racine_depot()
    try:
        dossier = construire(racine)
    except (EntreeIncoherente, KeyError, FileNotFoundError) as erreur:
        print(f"REFUS : {erreur!r}", file=sys.stderr)
        return 2
    octets = (json.dumps(dossier, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    (racine / SORTIE_JSON).write_bytes(octets)
    (racine / SORTIE_SHA).write_text(
        f"{hashlib.sha256(octets).hexdigest()}  {SORTIE_JSON}\n", encoding="utf-8"
    )
    (racine / SORTIE_TSV).write_text(rendre_tsv(dossier), encoding="utf-8")
    (racine / SORTIE_TSV_C1).write_text(rendre_tsv_c1(dossier), encoding="utf-8")
    (racine / SORTIE_MD_C1).write_text(rendre_markdown_c1(dossier), encoding="utf-8")
    print(json.dumps(dossier["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
