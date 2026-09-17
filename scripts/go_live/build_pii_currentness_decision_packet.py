#!/usr/bin/env python3
"""Prépare le dossier de décision humaine PII / actualité. Ne décide rien.

Le dossier est DÉRIVÉ des autorités versionnées : matrice de servabilité, index
de revue PII V2, impact de release, état de readiness. Il ne porte aucune
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

MATRICE = "docs/reports/handoff/servability_matrix_v1.json"
INDEX_PII = "docs/reports/evidence-index/pii_review_index_v2_20260907.json"
IMPACT = "docs/reports/go_live/currentness_release_impact.json"
READINESS = "docs/reports/go_live/go_live_readiness_state.json"
DECISIONS_V1 = "governance/pii-review-decisions/pii-review-2026-09-03-final.json"

SORTIE_JSON = "docs/reports/evidence/pii_currentness_human_decision_packet.json"
SORTIE_SHA = "docs/reports/evidence/pii_currentness_human_decision_packet.sha256"
SORTIE_TSV = "docs/reports/go_live/pii_currentness_decision_sheet.tsv"

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
#: Classes dont un vrai positif identifie directement une personne physique.
CLASSES_SENSIBLES = frozenset({"french_ssn", "date_of_birth", "student_name_pattern"})

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


def _risque(classes: list[str]) -> tuple[str, str]:
    sensibles = sorted(set(classes) & CLASSES_SENSIBLES)
    if sensibles:
        return "HIGH", (
            f"classe(s) {sensibles} : un vrai positif identifie une personne physique, "
            "possiblement un élève mineur"
        )
    return "STANDARD", (
        "coordonnées (courriel, téléphone, adresse) : souvent institutionnelles dans une "
        "publication officielle, mais un contact privé reste possible"
    )


def construire(racine: Path) -> dict[str, Any]:
    matrice, sha_matrice = _charger(racine, MATRICE)
    index, sha_index = _charger(racine, INDEX_PII)
    impact, sha_impact = _charger(racine, IMPACT)
    readiness, sha_readiness = _charger(racine, READINESS)
    v1, sha_v1 = _charger(racine, DECISIONS_V1)

    lignes = {r["content_sha256"]: r for r in matrice["rows"] if "content_sha256" in r}
    indecis = sorted(s for s, r in lignes.items() if r.get("pii") == "PII_UNDECIDED")
    paquets = {b["content_sha256"]: b for b in index["bundles"]}
    promus_refuses = set(readiness["release_promoted_refused_content_ids"])
    impact_par_sha = {r["content_sha256"]: r for r in impact["rows"]}
    v1_par_sha = {d["content_sha256"]: d for d in v1["decisions"]}

    # Les autorités doivent se recouper exactement, sinon le dossier mentirait.
    if len(indecis) != readiness["pii_undecided"]:
        raise EntreeIncoherente(f"matrice {len(indecis)} indécis != readiness {readiness['pii_undecided']}")
    if set(indecis) != set(paquets):
        raise EntreeIncoherente("l'ensemble PII_UNDECIDED n'est pas celui des paquets de revue V2")
    if len(promus_refuses) != readiness["release_promoted_refused_contents"] or promus_refuses != set(impact_par_sha):
        raise EntreeIncoherente("contenus promus refusés : readiness et impact de release divergent")
    actualite = sorted(
        s for s in promus_refuses if lignes[s]["verdict"] == "BLOCKED_NOT_CURRENT_BY_SOURCE"
    )
    pii_promus = sorted(s for s in promus_refuses if lignes[s]["verdict"] == "BLOCKED_PII_HUMAN_REVIEW")
    if len(actualite) != readiness["release_promoted_refused_by_currentness"] or not set(pii_promus) <= set(indecis):
        raise EntreeIncoherente("répartition PII / actualité des contenus promus incohérente")
    if len(actualite) + len(pii_promus) != len(promus_refuses):
        raise EntreeIncoherente("un contenu promu refusé n'est ni PII ni actualité")

    contenus_pii = []
    for sha in sorted(indecis, key=lambda s: (s not in promus_refuses, s)):
        paquet = paquets[sha]
        niveau, pourquoi = _risque(paquet["signal_classes"])
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
                "risk_tier": niveau,
                "risk_rationale": pourquoi,
                "currentness": lignes[sha]["currentness"],
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
            "currentness_declared": lignes[sha]["currentness"],
            "currentness_disposition": lignes[sha]["currentness_disposition"],
            "pii_status": lignes[sha]["pii"],
            "source_role": lignes[sha]["source_role"],
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
            MATRICE: sha_matrice, INDEX_PII: sha_index, IMPACT: sha_impact,
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
            "pii_undecided": len(indecis),
            "pii_findings": sum(c["finding_count"] for c in contenus_pii),
            "pii_high_risk_contents": sum(c["risk_tier"] == "HIGH" for c in contenus_pii),
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
    print(json.dumps(dossier["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
