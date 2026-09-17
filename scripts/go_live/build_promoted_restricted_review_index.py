#!/usr/bin/env python3
"""Index de revue PII / actualité RESTREINT aux contenus promus que le gate refuse.

Pourquoi il existe. L'outil gouverné de scellement (`sceller_decisions_pii.py`,
ADR-0047) exige une décision pour CHAQUE contenu de l'index qu'on lui donne :
contre l'index V2 (149 contenus), décider les seuls contenus promus n'est pas
scellable. Et il lit `finding["page"]`, que l'index V2 nomme `page_number` : sur
l'index V2 il ne s'exécute pas du tout. Cet index-ci borne la revue aux contenus
promus bloquants et rend à chaque finding la clé `page` que le scelleur, le
contrat de décisions et la projection de release attendent. Le scelleur n'est
pas modifié.

Ce qu'il est : une DÉRIVATION. Chaque paquet est celui de l'index V2, repris à
l'identique (même `bundle_sha256`, mêmes findings, mêmes empreintes) ; les
instruments (politique, scanner, foyer de pages) sont ceux de l'index V2 ; le
périmètre est `release_promoted_refused_content_ids` du readiness, recoupé avec
l'impact de release. Rien n'est re-scanné, rien n'est décidé, aucun compteur ne
bouge. Il ne lit pas la matrice de servabilité.

Ce fichier sera épinglé par le jeu de décisions (`review_index_sha256`) : il est
donc STABLE — ni date, ni empreinte d'un fichier régénéré à chaque lot.

    python3 scripts/go_live/build_promoted_restricted_review_index.py            # (re)génère
    python3 scripts/go_live/build_promoted_restricted_review_index.py --verify-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

KIND = "NEXUS-PROMOTED-RESTRICTED-REVIEW-INDEX-V1"

INDEX_V2 = "docs/reports/evidence-index/pii_review_index_v2_20260907.json"
IMPACT = "docs/reports/go_live/currentness_release_impact.json"
READINESS = "docs/reports/go_live/go_live_readiness_state.json"

SORTIE = "docs/reports/evidence/promoted_pii_currentness_restricted_review_index.json"
SORTIE_SHA = "docs/reports/evidence/promoted_pii_currentness_restricted_review_index.sha256"

#: Repris de l'index V2, jamais réécrits : une décision ne vaut que sous ses instruments.
INSTRUMENTS = (
    "protocol_version", "policy_path", "policy_sha256", "scanner_sha256",
    "page_policy_id", "page_policy_sha256", "contracts_version",
    "EXTRACTION_POLICY_ID", "FULL_DRIVE_PROCESSING_RUN_ID", "OCR_RUNTIME_IDENTITY", "PII_LEDGER_SHA256",
)
_CLES_DE_DECISION = frozenset(
    {"decision", "disposition", "human_decision", "human_disposition", "reviewer_decision",
     "reviewer", "reviewer_login", "decided_at", "justification"}
)
_CLES_DE_MATIERE_BRUTE = frozenset({"match_text", "context", "text", "page_text", "excerpt"})
_CHEMIN_PERSONNEL = re.compile(r"(?:^|[\s\"'=(])(?:/home/|/Users/|/root/|[A-Za-z]:\\\\)")
_SECRET = re.compile(r"(?i)(?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S|bearer\s+[a-z0-9._-]{12,}|-----BEGIN")


class EntreeIncoherente(RuntimeError):
    """Les autorités ne se recoupent pas : on ne dérive pas un index dessus."""


def racine_depot() -> Path:
    return Path(__file__).resolve().parents[2]


def octets_canoniques(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _charger(racine: Path, relatif: str) -> tuple[Any, str]:
    octets = (racine / relatif).read_bytes()
    return json.loads(octets), hashlib.sha256(octets).hexdigest()


def _empreinte_ensemble(identifiants: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(identifiants)).encode()).hexdigest()


def restreindre(
    index_v2: dict[str, Any],
    *,
    pii_promus: list[str],
    actualite: list[str],
    impact_par_sha: dict[str, dict[str, Any]],
    sources: dict[str, str],
) -> dict[str, Any]:
    """Dérivation pure : aucune lecture de fichier, aucune horloge."""
    paquets_v2 = {b["content_sha256"]: b for b in index_v2["bundles"]}
    absents = sorted(set(pii_promus) - set(paquets_v2))
    if absents:
        raise EntreeIncoherente(f"contenus promus bloqués PII absents de l'index V2 : {absents}")
    paquets = []
    for sha in sorted(pii_promus):
        paquet = json.loads(json.dumps(paquets_v2[sha]))
        for finding in paquet["findings"]:
            finding["page"] = finding["page_number"]
        paquets.append(paquet)
    return {
        "kind": KIND,
        **{cle: index_v2[cle] for cle in INSTRUMENTS},
        "campaign_id": f"{index_v2['campaign_id']}:promoted-blocking",
        "derived_from": {
            "review_index": INDEX_V2,
            "review_index_campaign_id": index_v2["campaign_id"],
            "review_index_content_set_sha256": index_v2["content_set_sha256"],
            **sources,
        },
        "scope": {
            "rule": "release_promoted_refused_content_ids du readiness, recoupé avec l'impact de release",
            "promoted_refused_content_set_sha256": _empreinte_ensemble([*pii_promus, *actualite]),
            "pii_content_set_sha256": _empreinte_ensemble(pii_promus),
            "currentness_content_set_sha256": _empreinte_ensemble(actualite),
        },
        "content_set_sha256": _empreinte_ensemble(pii_promus),
        "counts": {
            "bundles": len(paquets),
            "scanned": len(paquets),
            "findings": sum(int(p["finding_count"]) for p in paquets),
            "currentness_contents": len(actualite),
        },
        "finding_page_key": "`page` ajouté à chaque finding, égal à `page_number` : clé lue par le scelleur gouverné et par le contrat de décisions",
        "raw_pii_in_output": False,
        "decisions_made_here": 0,
        "index_sha256_excluded": True,
        "bundles": paquets,
        # Hors `bundles` : le scelleur PII exigerait sinon une décision PII sur des contenus sans PII.
        "currentness_contents": [
            {
                "content_sha256": sha,
                **{
                    cle: impact_par_sha[sha][cle]
                    for cle in ("drive_path", "currentness_before", "currentness_disposition", "pii_status",
                                "source_role", "release_authority", "possible_actions")
                },
            }
            for sha in sorted(actualite)
        ],
        "does_not_do": [
            "ne décide rien", "ne réduit ni pii_undecided ni release_promoted_refused_contents",
            "ne ferme pas C1", "ne produit aucune release", "ne remplace pas l'index V2 pour les 126 autres contenus",
        ],
    }


def construire(racine: Path) -> dict[str, Any]:
    index_v2, sha_index = _charger(racine, INDEX_V2)
    impact, sha_impact = _charger(racine, IMPACT)
    readiness, _ = _charger(racine, READINESS)

    promus = list(readiness["release_promoted_refused_content_ids"])
    impact_par_sha = {r["content_sha256"]: r for r in impact["rows"]}
    if len(promus) != readiness["release_promoted_refused_contents"] or set(promus) != set(impact_par_sha):
        raise EntreeIncoherente("contenus promus refusés : readiness et impact de release divergent")
    if not all(r.get("promoted") is True for r in impact_par_sha.values()):
        raise EntreeIncoherente("l'impact de release recense un contenu non promu")
    actualite = [s for s, r in impact_par_sha.items() if r["blocking_gate_now"] == "CURRENTNESS_GATE"]
    pii_promus = [s for s, r in impact_par_sha.items() if r["blocking_gate_now"] == "PII_GATE"]
    if len(actualite) != readiness["release_promoted_refused_by_currentness"]:
        raise EntreeIncoherente("contenus promus refusés pour actualité : readiness et impact divergent")
    if len(actualite) + len(pii_promus) != len(promus):
        raise EntreeIncoherente("un contenu promu refusé n'est ni PII ni actualité")
    return restreindre(
        index_v2, pii_promus=pii_promus, actualite=actualite, impact_par_sha=impact_par_sha,
        sources={"review_index_sha256": sha_index, "release_impact": IMPACT, "release_impact_sha256": sha_impact},
    )


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
        return [f"index restreint ou empreinte absent : {SORTIE}"]
    octets = index_path.read_bytes()
    scelle = sha_path.read_text(encoding="utf-8").split()
    if not scelle or scelle[0] != hashlib.sha256(octets).hexdigest():
        return ["index restreint altéré : l'empreinte scellée ne correspond pas au fichier"]
    try:
        document = json.loads(octets)
        attendu = construire(racine)
    except (ValueError, KeyError, EntreeIncoherente, FileNotFoundError) as erreur:
        return [f"index restreint ou autorités illisibles : {erreur!r}"]

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
    if document.get("decisions_made_here") != 0 or document.get("raw_pii_in_output") is not False:
        ecarts.append("décision ou matière brute déclarée par l'index lui-même")

    for cle in INSTRUMENTS:
        if document.get(cle) != attendu[cle]:
            ecarts.append(f"instrument réécrit : {cle}")

    paquets = {b.get("content_sha256"): b for b in document.get("bundles", [])}
    paquets_attendus = {b["content_sha256"]: b for b in attendu["bundles"]}
    for sha in sorted(set(paquets) - set(paquets_attendus), key=str):
        ecarts.append(f"contenu non promu (ou non bloqué PII) dans l'index : {str(sha)[:12]}")
    for sha in sorted(set(paquets_attendus) - set(paquets)):
        ecarts.append(f"contenu promu manquant : {sha[:12]}")
    for sha in sorted(set(paquets) & set(paquets_attendus)):
        recus = {f.get("finding_id"): f for f in paquets[sha].get("findings", [])}
        voulus = {f["finding_id"]: f for f in paquets_attendus[sha]["findings"]}
        if recus != voulus:
            ecarts.append(f"finding PII manquant, en trop ou modifié pour {sha[:12]}")
        elif {k: v for k, v in paquets[sha].items() if k not in ("findings", *_CLES_DE_DECISION, *_CLES_DE_MATIERE_BRUTE)} != {
            k: v for k, v in paquets_attendus[sha].items() if k != "findings"
        }:
            ecarts.append(f"paquet différent de celui de l'index V2 pour {sha[:12]}")

    if document.get("currentness_contents") != attendu["currentness_contents"]:
        ecarts.append("contenu d'actualité manquant, en trop ou modifié")
    if not ecarts and document != attendu:
        ecarts.append("l'index versionné n'est plus celui que les autorités donnent aujourd'hui")
    return ecarts


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - orchestration
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    racine = racine_depot()
    if args.verify_only:
        ecarts = valider(racine)
        print(json.dumps({"valid": not ecarts, "ecarts": ecarts}, ensure_ascii=False, indent=2))
        return 1 if ecarts else 0
    try:
        document = construire(racine)
    except (EntreeIncoherente, KeyError, FileNotFoundError) as erreur:
        print(f"REFUS : {erreur!r}", file=sys.stderr)
        return 2
    octets = octets_canoniques(document)
    (racine / SORTIE).write_bytes(octets)
    (racine / SORTIE_SHA).write_text(f"{hashlib.sha256(octets).hexdigest()}  {SORTIE}\n", encoding="utf-8")
    print(json.dumps({"counts": document["counts"], "scope": document["scope"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
