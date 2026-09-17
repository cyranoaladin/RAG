#!/usr/bin/env python3
"""Convertit une feuille de revue REMPLIE et VALIDÉE en brouillon pour le scelleur gouverné.

Ne décide rien : il TRANSCRIT ce que le reviewer a écrit, et refuse tout ce que le
validateur refuse. Il ne scelle pas, n'écrit rien dans le dépôt, ne touche aucun
compteur. Le scellement reste l'affaire de `sceller_decisions_pii.py` (ADR-0047),
contre l'index de revue restreint ; l'effet sur la release reste l'affaire du lot BW.

À n'exécuter que sur ordre explicite de l'opérateur (`PII_DECISIONS_VALIDATED … IMPORT AUTORISÉ`).

    python3 scripts/go_live/convert_review_sheet_to_sealer_draft.py <feuille.tsv> \\
        --decision-set-id pii-review-<date>-promoted-blocking \\
        --corpus-manifest-sha256 <64 hex> --decided-at <ISO 8601 avec fuseau> \\
        --sortie <répertoire HORS dépôt>
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_complete_pii_review_index as complet  # noqa: E402
import build_promoted_restricted_review_index as restreint  # noqa: E402
import validate_pii_currentness_review_sheet as validateur  # noqa: E402

#: Option humaine → décision du contrat. Les deux rejets donnent REJECTED ; leur nuance
#: (caviarder ou exclure) est conservée à part, pour le lot BW : le contrat ne la porte pas.
DECISION_DU_CONTRAT = {
    "PII_CLEARED": "APPROVED",
    "PII_REDACTION_REQUIRED": "REJECTED",
    "EXCLUDE_FROM_SERVABLE_SET": "REJECTED",
}


class ConversionRefusee(RuntimeError):
    """La feuille n'est pas convertible : rien n'est écrit."""


def convertir(
    racine: Path,
    feuille: Path,
    *,
    decision_set_id: str,
    corpus_manifest_sha256: str,
    decided_at: str,
    index_relatif: str | None = None,
) -> dict:
    bilan = validateur.valider(racine, feuille)
    if bilan["errors"]:
        raise ConversionRefusee(f"feuille invalide ({len(bilan['errors'])} erreur(s)) : {bilan['errors'][:3]}")
    if not bilan["sealable"]:
        raise ConversionRefusee(f"feuille non scellable : contenus PII encore en attente {bilan.get('pii')}")

    if index_relatif is None:
        index_relatif = complet.SORTIE if bilan["pii"]["decided"] == 149 else restreint.SORTIE

    if index_relatif == complet.SORTIE:
        ecarts = complet.valider(racine)
    else:
        ecarts = restreint.valider(racine)
    if ecarts:
        raise ConversionRefusee(f"index de revue {index_relatif} invalide : {ecarts}")

    moment = datetime.fromisoformat(decided_at)
    if moment.tzinfo is None:
        raise ConversionRefusee("--decided-at doit porter un fuseau horaire")

    index = json.loads((racine / index_relatif).read_text(encoding="utf-8"))
    attendus = {b["content_sha256"] for b in index["bundles"]}
    lignes = list(csv.DictReader(feuille.open(encoding="utf-8", newline=""), delimiter="\t"))
    contenus = {x["content_sha256"]: x for x in lignes if x["row_kind"] == "PII_CONTENT"}
    if set(contenus) != attendus:
        raise ConversionRefusee(
            "la feuille ne couvre pas exactement l'index restreint "
            f"(manquants : {len(attendus - set(contenus))}, en trop : {len(set(contenus) - attendus)})"
        )
    dispositions: dict[str, dict[str, dict]] = {}
    for x in lignes:
        if x["row_kind"] == "PII_FINDING":
            dispositions.setdefault(x["content_sha256"], {})[x["finding_id"]] = {"disposition": x["FINDING_DISPOSITION"]}

    brouillon = {
        "decision_set_id": decision_set_id,
        "corpus_manifest_sha256": corpus_manifest_sha256,
        "reviewer_login": bilan["reviewer_login"],
        "decisions": {
            sha: {
                "decision": DECISION_DU_CONTRAT[x["HUMAN_DECISION"]],
                "decided_at": moment.isoformat(),
                "justification": {"category": x["JUSTIFICATION_CATEGORY"], "statement": x["COMMENT"].strip()},
                "findings": dispositions[sha],
            }
            for sha, x in sorted(contenus.items())
        },
    }
    return {
        "sealer_draft": brouillon,
        "human_options": {sha: x["HUMAN_DECISION"] for sha, x in sorted(contenus.items())},
        "currentness_decisions": [
            {k: x[k] for k in ("content_sha256", "HUMAN_DECISION", "REVIEWER_LOGIN", "EVIDENCE_REFERENCE", "COMMENT")}
            for x in lignes
            if x["row_kind"] == "CURRENTNESS_CONTENT"
        ],
        "currentness_protocol": "AUCUN protocole scellé n'existe pour l'actualité : forme à fixer par ADR (lot BW)",
        "review_index": index_relatif,
    }


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - orchestration
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feuille", type=Path)
    parser.add_argument("--decision-set-id", required=True)
    parser.add_argument("--corpus-manifest-sha256", required=True)
    parser.add_argument("--decided-at", required=True)
    parser.add_argument("--sortie", type=Path, required=True)
    parser.add_argument("--index", type=str, default=None, help="Chemin relatif de l'index de revue")
    args = parser.parse_args(argv)
    racine = Path(__file__).resolve().parents[2]
    sortie = args.sortie.expanduser().resolve()
    if sortie == racine or racine in sortie.parents:
        print("REFUS : --sortie doit être HORS du dépôt (convention du scelleur)", file=sys.stderr)
        return 2
    try:
        resultat = convertir(
            racine,
            args.feuille,
            decision_set_id=args.decision_set_id,
            corpus_manifest_sha256=args.corpus_manifest_sha256,
            decided_at=args.decided_at,
            index_relatif=args.index,
        )
    except (ConversionRefusee, ValueError) as erreur:
        print(f"REFUS : {erreur}", file=sys.stderr)
        return 1
    sortie.mkdir(parents=True, exist_ok=True, mode=0o700)
    for nom, cle in (
        ("decisions.draft.json", "sealer_draft"),
        ("human_options.json", "human_options"),
        ("currentness_decisions.json", "currentness_decisions"),
    ):
        chemin = sortie / nom
        chemin.write_text(json.dumps(resultat[cle], ensure_ascii=False, indent=2), encoding="utf-8")
        chemin.chmod(0o600)
    print(
        json.dumps(
            {
                "written_outside_repository": str(sortie),
                "decisions": len(resultat["sealer_draft"]["decisions"]),
                "next": f"sceller_decisions_pii.py sceller --draft … --index {resultat['review_index']}",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
