#!/usr/bin/env python3
"""Index de revue PII COMPLET compatible avec le scelleur gouverné (ADR-0047).

Pourquoi il existe. L'outil gouverné de scellement (`sceller_decisions_pii.py`,
ADR-0047) exige une décision pour CHAQUE contenu de l'index qu'on lui donne (149
contenus dans l'index V2). Et il lit `finding["page"]`, que l'index V2 nomme
`page_number` : sur l'index V2 brut, il échoue. Cet index-ci résout cette divergence
en adjoignant à chaque finding la clé `page` attendue par le scelleur, pour
l'intégralité des 149 bundles (479 findings). Le scelleur n'est pas modifié.

Ce qu'il est : une DÉRIVATION. Chaque paquet est celui de l'index V2, repris à
l'identique (même `bundle_sha256`, mêmes empreintes) ; les instruments (politique,
scanner, foyer de pages) sont ceux de l'index V2. Rien n'est re-scanné, rien n'est
décidé ici, aucun compteur ne bouge.

Ce fichier sera épinglé par le jeu de décisions (`review_index_sha256`) : il est
donc STABLE — ni date, ni horloge, ni chemin machine-local.

    python3 scripts/go_live/build_complete_pii_review_index.py            # (re)génère
    python3 scripts/go_live/build_complete_pii_review_index.py --verify-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

KIND = "NEXUS-COMPLETE-COMPATIBLE-REVIEW-INDEX-V1"

INDEX_V2 = "docs/reports/evidence-index/pii_review_index_v2_20260907.json"

SORTIE = "docs/reports/evidence/pii_review_complete_compatible_index.json"
SORTIE_SHA = "docs/reports/evidence/pii_review_complete_compatible_index.sha256"

#: Repris de l'index V2, jamais réécrits : une décision ne vaut que sous ses instruments.
INSTRUMENTS = (
    "protocol_version",
    "policy_path",
    "policy_sha256",
    "scanner_sha256",
    "page_policy_id",
    "page_policy_sha256",
    "contracts_version",
    "EXTRACTION_POLICY_ID",
    "FULL_DRIVE_PROCESSING_RUN_ID",
    "OCR_RUNTIME_IDENTITY",
    "PII_LEDGER_SHA256",
)
_CLES_DE_DECISION = frozenset(
    {
        "decision",
        "disposition",
        "human_decision",
        "human_disposition",
        "reviewer_decision",
        "reviewer",
        "reviewer_login",
        "decided_at",
        "justification",
    }
)
_CLES_DE_MATIERE_BRUTE = frozenset(
    {"match_text", "context", "text", "page_text", "excerpt"}
)
_CHEMIN_PERSONNEL = re.compile(
    r"(?:^|[\s\"'=(])(?:/home/|/Users/|/root/|[A-Za-z]:\\\\)"
)
_SECRET = re.compile(
    r"(?i)(?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S|bearer\s+[a-z0-9._-]{12,}|-----BEGIN"
)


class EntreeIncoherente(RuntimeError):
    """Les autorités ne se recoupent pas : on ne dérive pas un index dessus."""


def racine_depot() -> Path:
    return Path(__file__).resolve().parents[2]


def octets_canoniques(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def _charger(racine: Path, relatif: str) -> tuple[Any, str]:
    octets = (racine / relatif).read_bytes()
    return json.loads(octets), hashlib.sha256(octets).hexdigest()


def deriver(index_v2: dict[str, Any], *, sha_index: str) -> dict[str, Any]:
    """Dérivation pure : aucune lecture de fichier, aucune horloge."""
    paquets = []
    for paquet_source in index_v2["bundles"]:
        paquet = json.loads(json.dumps(paquet_source))
        for finding in paquet["findings"]:
            finding["page"] = finding["page_number"]
        paquets.append(paquet)

    return {
        "kind": KIND,
        **{cle: index_v2[cle] for cle in INSTRUMENTS},
        "campaign_id": f"{index_v2['campaign_id']}:complete-compatible",
        "derived_from": {
            "review_index": INDEX_V2,
            "review_index_campaign_id": index_v2["campaign_id"],
            "review_index_content_set_sha256": index_v2["content_set_sha256"],
            "review_index_sha256": sha_index,
        },
        "scope": {
            "rule": "tous les 149 paquets de l'index V2 avec ajout de la clé page = page_number",
            "content_set_sha256": index_v2["content_set_sha256"],
        },
        "content_set_sha256": index_v2["content_set_sha256"],
        "counts": {
            "bundles": len(paquets),
            "scanned": len(paquets),
            "findings": sum(int(p["finding_count"]) for p in paquets),
        },
        "finding_page_key": (
            "`page` ajouté à chaque finding, égal à `page_number` : "
            "clé lue par le scelleur gouverné et par le contrat de décisions"
        ),
        "raw_pii_in_output": False,
        "decisions_made_here": 0,
        "index_sha256_excluded": True,
        "bundles": paquets,
        "does_not_do": [
            "ne décide rien",
            "ne modifie aucun instrument ni empreinte",
            "ne remplace pas la feuille de décisions",
        ],
    }


def construire(racine: Path) -> dict[str, Any]:
    index_v2, sha_index = _charger(racine, INDEX_V2)
    return deriver(index_v2, sha_index=sha_index)


def _parcourir(valeur: Any, chemin: str = ""):
    if isinstance(valeur, dict):
        for cle, sous in valeur.items():
            yield chemin, cle, sous
            yield from _parcourir(sous, f"{chemin}/{cle}")
    elif isinstance(valeur, list):
        for i, sous in enumerate(valeur):
            yield from _parcourir(sous, f"{chemin}[{i}]")


def valider(racine: Path) -> list[str]:
    """Écarts de l'index versionné. Liste vide = valide. Fail-closed : tout doute est un écart."""
    index_path, sha_path = racine / SORTIE, racine / SORTIE_SHA
    if not index_path.is_file() or not sha_path.is_file():
        return [f"index complet compatible ou empreinte absent : {SORTIE}"]
    octets = index_path.read_bytes()
    scelle = sha_path.read_text(encoding="utf-8").split()
    if not scelle or scelle[0] != hashlib.sha256(octets).hexdigest():
        return [
            "index complet compatible altéré : l'empreinte scellée ne correspond pas au fichier"
        ]
    try:
        document = json.loads(octets)
        attendu = construire(racine)
    except (ValueError, KeyError, EntreeIncoherente, FileNotFoundError) as erreur:
        return [f"index complet compatible ou autorités illisibles : {erreur!r}"]

    ecarts: list[str] = []
    for _chemin, cle, valeur in _parcourir(document):
        if cle in _CLES_DE_DECISION:
            ecarts.append(f"décision préremplie ou champ de décision présent : {cle!r}")
        if cle in _CLES_DE_MATIERE_BRUTE:
            ecarts.append(f"matière PII brute dans le dépôt : {cle!r}")
        if isinstance(valeur, str):
            if _CHEMIN_PERSONNEL.search(valeur):
                ecarts.append(f"chemin absolu personnel sous {cle!r}")
            if _SECRET.search(valeur):
                ecarts.append(f"secret apparent sous {cle!r}")
    if (
        document.get("decisions_made_here") != 0
        or document.get("raw_pii_in_output") is not False
    ):
        ecarts.append("décision ou matière brute déclarée par l'index lui-même")

    for cle in INSTRUMENTS:
        if document.get(cle) != attendu[cle]:
            ecarts.append(f"instrument réécrit : {cle}")

    paquets = {b.get("content_sha256"): b for b in document.get("bundles", [])}
    paquets_attendus = {b["content_sha256"]: b for b in attendu["bundles"]}
    if set(paquets) != set(paquets_attendus):
        ecarts.append(
            f"ensembles de bundles divergents (reçus: {len(paquets)}, attendus: {len(paquets_attendus)})"
        )
    for sha in sorted(set(paquets) & set(paquets_attendus)):
        recus = {f.get("finding_id"): f for f in paquets[sha].get("findings", [])}
        voulus = {f["finding_id"]: f for f in paquets_attendus[sha]["findings"]}
        if recus != voulus:
            ecarts.append(f"finding PII manquant, en trop ou modifié pour {sha[:12]}")

    if not ecarts and document != attendu:
        ecarts.append(
            "l'index versionné n'est plus celui que les autorités donnent aujourd'hui"
        )
    return ecarts


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - orchestration
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    racine = racine_depot()
    if args.verify_only:
        ecarts = valider(racine)
        print(
            json.dumps(
                {"valid": not ecarts, "ecarts": ecarts},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if ecarts else 0
    try:
        document = construire(racine)
    except (EntreeIncoherente, KeyError, FileNotFoundError) as erreur:
        print(f"REFUS : {erreur!r}", file=sys.stderr)
        return 2
    octets = octets_canoniques(document)
    (racine / SORTIE).write_bytes(octets)
    (racine / SORTIE_SHA).write_text(
        f"{hashlib.sha256(octets).hexdigest()}  {SORTIE}\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"counts": document["counts"], "scope": document["scope"]}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
