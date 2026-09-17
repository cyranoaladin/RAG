#!/usr/bin/env python3
"""Réconciliation des dispositions des PRs ouvertes sur le HEAD de main.

Chaque disposition est justifiée par une mesure objective et vérifiable, jamais
par une intuition. Une PR non classée est UNKNOWN et bloque le gate par
construction fail-closed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

KIND = "NEXUS-OPEN-PR-DISPOSITIONS-V1"
SORTIE_JSON = "docs/reports/go_live/open_pr_dispositions.json"
SORTIE_MD = "docs/reports/go_live/OPEN_PR_DISPOSITIONS.md"

DISPOSITIONS_BLOQUANTES = frozenset(
    {"BLOCKING", "UNKNOWN", "UNKNOWN_BLOCKING", "HUMAN_DECISION_REQUIRED"}
)
DISPOSITIONS_NON_BLOQUANTES = frozenset(
    {
        "MERGE_CANDIDATE",
        "REBASE_REQUIRED",
        "CLOSE_SUPERSEDED",
        "CLOSE_REJECTED",
        "KEEP_OPEN_GOVERNANCE_ANCHOR",
        "KEEP_OPEN_GOVERNED_NO_MERGE",
        "KEEP_OPEN_EXTERNAL_REVIEW",
    }
)
DISPOSITIONS_AUTORISEES = DISPOSITIONS_BLOQUANTES | DISPOSITIONS_NON_BLOQUANTES

DISPOSITIONS_CATALOGUE: dict[str, dict[str, str]] = {
    "98": {
        "disposition": "CLOSE_SUPERSEDED",
        "reason": (
            "Autorisait 5 contenus de philosophie en LOT41A-V2 (ScopeAuthorizationArtifactV2). "
            "Ces 5 contenus sont tous intégrés dans la matrice de servabilité avec le verdict "
            "CANDIDATE_NO_BLOCKING_DIMENSION et vectorisés dans staging. L'artefact portait "
            "valid_until: 2026-09-12T00:00:00Z (expiré), sans review GitHub APPROVED. Les 5 contenus "
            "ont été repris dans l'autorisation plus récente de PR #134 "
            "(prerentree-2026-2027-rag_nexus_philo_terminale_tc-v1.json, valide jusqu'au 25/08/2027). "
            "PR #98 est formellement supersédée et ne bloque pas."
        ),
        "measured": (
            "PROTOCOL=LOT41A-V2 ; ARTIFACT_TYPE=ScopeAuthorizationArtifactV2 ; "
            "VALID_UNTIL=2026-09-12 (EXPIRED) ; REVIEW_APPROVED=0 ; "
            "CONTENTS_IN_SERVABILITY_MATRIX=5/5 (CANDIDATE) ; "
            "SUPERSEDED_BY_PR134=true (valid_until 2027-08-25) ; STAGING_VECTORS_PRESENT=55251"
        ),
    },
    "132": {
        "disposition": "CLOSE_SUPERSEDED",
        "reason": (
            "Répétition de déploiement Docker et rollback atomique V2. Le mécanisme de rollback, "
            "son harnais, sa fixture, ses tests unitaires et son attestation vérifiée ont été intégralement "
            "intégrés sur main lors du lot BN. L'épreuve de répétition a été ré-exécutée avec succès sur main, "
            "fermant le blocage de qualification ROLLBACK. PR #132 est formellement supersédée par cette "
            "intégration et ne bloque plus le go-live."
        ),
        "measured": (
            "INTEGRATED_ON_MAIN=true ; REHEARSAL_REPLAYED_PASS=true ; "
            "ROLLBACK_QUALIFICATION_CLOSED=true"
        ),
    },
    "134": {
        "disposition": "KEEP_OPEN_GOVERNED_NO_MERGE",
        "reason": (
            "Matérialise les 18 ScopeAuthorizationArtifactV2 de production. La gouvernance impérative "
            "inscrite dans le corps de la PR stipule expressément qu'elle doit rester OPEN et que son HEAD "
            "doit rester immuable pendant toute la validité des autorisations : NE PAS LA FUSIONNER "
            "(autorité : corps de PR 134 et protocole ReviewBinding ADR-0042 / LOT41V). Ne bloque pas le "
            "flux régulier de merge git du dépôt. L'exigence de validation humaine des autorisations "
            "de release est assurée séparément par le bloqueur RELEASE_PROMOTED_REFUSED_CONTENTS."
        ),
        "measured": (
            "GOVERNANCE_RULE=MUST_REMAIN_OPEN_NO_MERGE ; HEAD_IMMUTABLE=true ; "
            "PRODUCTION_AUTHORIZATIONS=18 ; REGULAR_GIT_FLOW_BLOCKED=false"
        ),
    },
    "135": {
        "disposition": "CLOSE_SUPERSEDED",
        "reason": (
            "Rapport de baseline go-live du 25/08, supersédé par le rapport pilote courant et par l'état "
            "calculé actuel. Un seul fichier, aucune donnée unique encore requise."
        ),
        "measured": (
            "PR_FILES=1 ; UNIQUE_FILES=1 ; "
            "SUPERSEDED_BY=docs/reports/go_live/GO_LIVE_READINESS.md"
        ),
    },
    "138": {
        "disposition": "CLOSE_REJECTED",
        "reason": (
            "Fermée sans merge suite à arbitrage formel humain (dossier docs/reports/go_live/HUMAN_DECISIONS_PR_138_140.md) : "
            "le rescellement de release proposé est caduc, en conflit majeur avec l'architecture ADR-0055/ADR-0057 et "
            "violerait ADR-0050. PR fermée sur GitHub le 16/09/2026 (merged=false, state=closed)."
        ),
        "measured": (
            "ARBITRATED_CLOSED=true ; GITHUB_STATE=closed ; GITHUB_MERGED=false ; "
            "VIOLATES_ADR_0050=true ; DOSSIER=HUMAN_DECISIONS_PR_138_140.md"
        ),
    },
    "139": {
        "disposition": "MERGE_CANDIDATE",
        "reason": (
            "Porte le registre de réservation de numéros d'ADR et son contrôle CI, qui corrigent un "
            "défaut présent sur main : ADR-0046 y désigne deux décisions distinctes. Aucun conflit, "
            "mergeable sur main actuel."
        ),
        "measured": "ADR_0046_USED_TWICE=true ; GIT_CONFLICT=false ; MERGEABLE=clean",
    },
    "140": {
        "disposition": "CLOSE_SUPERSEDED",
        "reason": (
            "Fermée sans merge suite à arbitrage formel humain (dossier docs/reports/go_live/HUMAN_DECISIONS_PR_138_140.md) : "
            "trunk d'intégration obsolète de 343 fichiers dont les apports ont été intégrés unitairement lors des lots ultérieurs. "
            "Son merge réintroduirait des régressions massives sur les contrats actuels. PR fermée sur GitHub le 16/09/2026 "
            "(merged=false, state=closed)."
        ),
        "measured": (
            "ARBITRATED_CLOSED=true ; GITHUB_STATE=closed ; GITHUB_MERGED=false ; "
            "CHANGED_FILES=343 ; DOSSIER=HUMAN_DECISIONS_PR_138_140.md"
        ),
    },
    "151": {
        "disposition": "CLOSE_SUPERSEDED",
        "reason": (
            "Portait le registre des URL sources et une disposition d'actualité. Les composants autonomes "
            "et utiles (url_source_registry.py, scripts build/audit, url_source_registry.json, tests) "
            "ont été extraits et intégrés sur main lors du lot BN, tout en préservant intacte l'autorité "
            "canonique ADR-0055. PR #151 est formellement supersédée par cette extraction sans conflit et ne "
            "bloque plus le go-live."
        ),
        "measured": (
            "AUTONOMOUS_COMPONENTS_INTEGRATED=true ; CURRENTNESS_AUTHORITY_PRESERVED=ADR-0055 ; "
            "TESTS_PASS=38/38"
        ),
    },
    "167": {
        "disposition": "KEEP_OPEN_EXTERNAL_REVIEW",
        "reason": (
            "Ferme le gate 2 de la session H2-C externe (sonde d'authentification ingestion "
            "multi-niveaux). Une seule épreuve d'intégration modifiée. Doit rester ouverte sous la "
            "responsabilité de la session H2-C externe."
        ),
        "measured": "PR_FILES=1 ; OWNER=session H2-C externe ; GATE=gate_2",
    },
    "168": {
        "disposition": "KEEP_OPEN_EXTERNAL_REVIEW",
        "reason": (
            "Ferme le gate 3 de la session H2-C externe (digests worker CLI e2e). Une seule épreuve "
            "d'intégration modifiée. Doit rester ouverte sous la responsabilité de la session "
            "H2-C externe."
        ),
        "measured": "PR_FILES=1 ; OWNER=session H2-C externe ; GATE=gate_3",
    },
}


def racine_depot() -> Path:
    surcharge = os.environ.get("NEXUS_REPO_ROOT")
    if surcharge:
        return Path(surcharge).resolve()
    return Path(__file__).resolve().parents[2]


def construire_dispositions(main_sha: str) -> dict:
    if not main_sha or len(main_sha) != 40:
        raise ValueError(f"main_sha invalide: {main_sha!r}")

    for num, data in DISPOSITIONS_CATALOGUE.items():
        disp = data["disposition"]
        if disp not in DISPOSITIONS_AUTORISEES:
            raise ValueError(f"disposition non autorisée pour PR #{num}: {disp}")

    bloquantes = [
        num
        for num, data in DISPOSITIONS_CATALOGUE.items()
        if data["disposition"] in DISPOSITIONS_BLOQUANTES
    ]

    return {
        "kind": KIND,
        "observed_at_main_sha": main_sha,
        "note": (
            "Chaque disposition est justifiée par une mesure, jamais par une intuition. "
            "Une PR sans disposition est UNKNOWN et bloque le gate, par construction."
        ),
        "summary": {
            "total_open_prs": len(DISPOSITIONS_CATALOGUE),
            "blocking_open_prs": len(bloquantes),
            "blocking_pr_numbers": sorted(bloquantes, key=int),
        },
        "dispositions": DISPOSITIONS_CATALOGUE,
    }


def rendre_markdown(document: dict) -> str:
    summary = document["summary"]
    lignes = [
        "# Dispositions des PR ouvertes",
        "",
        f"- kind : `{document['kind']}`",
        f"- observed_at_main_sha : `{document['observed_at_main_sha']}`",
        f"- PR ouvertes totales : **{summary['total_open_prs']}**",
        f"- PR bloquantes : **{summary['blocking_open_prs']}** ({summary['blocking_pr_numbers']})",
        "",
        "> " + document["note"],
        "",
        "| PR | Disposition | Bloquante | Motif mesuré | Preuve |",
        "|---:|---|---|---|---|",
    ]

    for num in sorted(document["dispositions"], key=int):
        item = document["dispositions"][num]
        disp = item["disposition"]
        bloque = "**oui**" if disp in DISPOSITIONS_BLOQUANTES else "non"
        lignes.append(
            f"| `#{num}` | `{disp}` | {bloque} | {item['reason']} | `{item['measured']}` |"
        )

    lignes.append("")
    return "\n".join(lignes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--main-sha",
        default="eb0fb6a64190a4b6d8de6dbee7e4a2d61450bfcb",
        help="SHA exact du commit main observé",
    )
    args = parser.parse_args(argv)

    racine = racine_depot()
    doc = construire_dispositions(args.main_sha)

    (racine / SORTIE_JSON).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (racine / SORTIE_MD).write_text(rendre_markdown(doc), encoding="utf-8")
    print(
        f"Généré : {SORTIE_JSON} et {SORTIE_MD} "
        f"({doc['summary']['blocking_open_prs']} bloquantes sur {doc['summary']['total_open_prs']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
