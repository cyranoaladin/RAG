#!/usr/bin/env python3
"""Revue PII guidée, document par document, finding par finding (pré-gel § 17).

Le reviewer ne manipule aucun JSON cryptographique : l'outil lit l'index
versionné et les paquets locaux, montre chaque finding avec son contexte
local, enregistre les dispositions et la décision documentaire, puis écrit le
BROUILLON hors dépôt que `sceller_decisions_pii.py sceller` transforme en
forme canonique. Rien n'est décidé par l'outil ; une réponse vide, un
placeholder ou une contradiction (APPROVED avec un finding personnel) est
refusé au scellement.

    python scripts/revue_pii_cli.py \\
        --index ../../docs/reports/evidence-index/pii_review_index_20260902.json \\
        --bundles ~/nexus-pii-review-20260902 \\
        --draft ~/nexus-pii-review-20260902/decisions.draft.json \\
        --reviewer-login abenrhouma --corpus-manifest-sha256 <empreinte des octets> \\
        [--only <content_sha256>] [--reponses fichier.json]

Reprise : un brouillon existant est rechargé et seules les entrées non
décidées sont proposées (`--only` force un document).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

DISPOSITIONS = (
    "FALSE_POSITIVE_TECHNICAL",
    "PUBLIC_INSTITUTIONAL_DATA",
    "SYNTHETIC_EXAMPLE",
    "PERSONAL_DATA_PRESENT",
)
CATEGORIES = (
    "INSTITUTIONAL_CONTACT",
    "PEDAGOGICAL_EXAMPLE",
    "FICTIONAL_IDENTITY",
    "TECHNICAL_FALSE_POSITIVE",
    "PUBLIC_OFFICIAL_PUBLICATION",
    "PERSONAL_DATA_PRESENT",
)
PLACEHOLDER = "__A_DECIDER__"

#: Le fichier d'autorité que le producteur lie à la revue
#: (`build_production_profile_release.corpus_manifest_authority_file_sha256`).
DEFAULT_CORPUS_MANIFEST_AUTHORITY = (
    Path(__file__).resolve().parents[1]
    / "data/releases/prerentree_2026_2027/profile_gate/corpus_manifest_authority.json"
)
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")

Ask = Callable[[str], str]


def _charger_brouillon(draft: Path, index: dict, reviewer_login: str) -> dict:
    if draft.is_file():
        document = json.loads(draft.read_text(encoding="utf-8"))
        if document.get("reviewer_login") != reviewer_login:
            raise ValueError("le brouillon existant porte un autre reviewer")
        return document
    return {
        "decision_set_id": index["campaign_id"],
        "corpus_manifest_sha256": None,
        "reviewer_login": reviewer_login,
        "decisions": {},
    }


def _manifeste_du_corpus(
    brouillon: dict, demande: str | None, autorite: Path | None
) -> str:
    """L'empreinte du corpus revu : explicite, vérifiée, jamais écrasée.

    Le brouillon enregistre l'empreinte des OCTETS du fichier d'autorité, pas
    la valeur que ce fichier déclare. Un brouillon qui en porte déjà une la
    garde : un argument différent est refusé au lieu de la remplacer."""
    existant = brouillon.get("corpus_manifest_sha256")
    if existant and demande and existant != demande:
        raise ValueError(
            f"le brouillon porte corpus_manifest_sha256 {existant[:16]}… ; "
            f"{demande[:16]}… ne le remplace pas silencieusement"
        )
    valeur = existant or demande
    if not isinstance(valeur, str) or not _HEX64.match(valeur):
        raise ValueError("corpus_manifest_sha256 explicite (64 hex) requis pour un nouveau brouillon")
    if autorite is not None:
        octets = autorite.read_bytes()
        attendu = hashlib.sha256(octets).hexdigest()
        if valeur != attendu:
            declaree = json.loads(octets.decode("utf-8")).get("authority_sha256")
            motif = " (c'est la valeur qu'il DÉCLARE, pas son empreinte)" if valeur == declaree else ""
            raise ValueError(
                f"corpus_manifest_sha256 {valeur[:16]}… n'est pas l'empreinte du "
                f"corpus manifest authority {autorite.name} ({attendu[:16]}…){motif}"
            )
    return valeur


def _choisir(ask: Ask, invite: str, choix: Sequence[str], out: Callable[[str], None]) -> str:
    for numero, valeur in enumerate(choix, start=1):
        out(f"    [{numero}] {valeur}")
    while True:
        reponse = ask(f"{invite} (1-{len(choix)}) : ").strip()
        if reponse.isdigit() and 1 <= int(reponse) <= len(choix):
            return choix[int(reponse) - 1]
        if reponse in choix:
            return reponse
        out("    réponse invalide")


def revoir(
    *,
    index_path: Path,
    bundles_root: Path,
    draft: Path,
    reviewer_login: str,
    corpus_manifest_sha256: str | None,
    ask: Ask,
    out: Callable[[str], None] = print,
    only: str | None = None,
    corpus_manifest_authority: Path | None = None,
) -> dict:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    brouillon = _charger_brouillon(draft, index, reviewer_login)
    brouillon["corpus_manifest_sha256"] = _manifeste_du_corpus(
        brouillon, corpus_manifest_sha256, corpus_manifest_authority
    )
    entries = sorted(index["bundles"], key=lambda e: e["content_sha256"])
    total = len(entries)
    for position, entry in enumerate(entries, start=1):
        sha = entry["content_sha256"]
        if only and sha != only:
            continue
        deja = brouillon["decisions"].get(sha)
        if deja and not only and deja.get("decision") not in (None, PLACEHOLDER):
            continue
        manifest_path = bundles_root / entry["bundle_dir"] / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["content_sha256"] != sha:
            raise ValueError(f"paquet {entry['bundle_dir']} : contenu inattendu")
        signals = {s["finding_id"]: s for s in manifest["signals"]}
        out("")
        out(f"Document {position:02d}/{total}")
        out(f"  SHA        {sha}")
        out(f"  titre      {entry.get('title')}")
        out(f"  source     {entry.get('source_path')}")
        out(f"  placements {', '.join(entry.get('placements', []))}")
        out(f"  paquet     {manifest_path.parent}  (document.pdf, pages/)")
        out(f"  findings   {entry['finding_count']}")
        dispositions: dict[str, dict[str, str]] = {}
        for numero, finding in enumerate(sorted(entry["findings"], key=lambda f: f["finding_id"]), start=1):
            signal = signals[finding["finding_id"]]
            out("")
            out(f"  [{numero}] {finding['pattern_id']}  page {finding.get('page', finding.get('page_number'))}"
                + (f"  clé NIR valide : {finding['checksum_valid']}" if "checksum_valid" in finding else ""))
            out(f"      correspondance : {signal['match_text']}")
            out(f"      contexte       : …{signal['context']}…")
            disposition = _choisir(ask, "      disposition", DISPOSITIONS, out)
            dispositions[finding["finding_id"]] = {"disposition": disposition}
        personal = any(d["disposition"] == "PERSONAL_DATA_PRESENT" for d in dispositions.values())
        out("")
        out("  Décision document" + ("  (un finding est PERSONAL_DATA_PRESENT : APPROVED impossible)" if personal else ""))
        decision = _choisir(ask, "  décision", ("REJECTED",) if personal else ("APPROVED", "REJECTED"), out)
        out("  Justification")
        category = _choisir(ask, "  catégorie", CATEGORIES, out)
        while True:
            statement = ask("  motif (20 à 1000 caractères, sans citer la matière) : ").strip()
            if 20 <= len(statement) <= 1000:
                break
            out("    longueur invalide")
        brouillon["decisions"][sha] = {
            "findings": dispositions,
            "decision": decision,
            "decided_at": datetime.now(UTC).isoformat(),
            "justification": {"category": category, "statement": statement},
        }
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text(json.dumps(brouillon, ensure_ascii=False, indent=2), encoding="utf-8")
        out(f"  enregistré ({len(brouillon['decisions'])}/{total} décidés)")
    return brouillon


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--bundles", type=Path, required=True)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--reviewer-login", required=True)
    parser.add_argument(
        "--corpus-manifest-sha256",
        help="empreinte des octets du fichier d'autorité ; requise pour un nouveau brouillon",
    )
    parser.add_argument(
        "--corpus-manifest-authority", type=Path, default=DEFAULT_CORPUS_MANIFEST_AUTHORITY,
        help="fichier d'autorité contre lequel l'empreinte est vérifiée",
    )
    parser.add_argument("--only")
    parser.add_argument("--reponses", type=Path, help="réponses scriptées (liste JSON), pour rejouer")
    args = parser.parse_args(argv)
    if args.reponses:
        reponses = iter(json.loads(args.reponses.read_text(encoding="utf-8")))
        ask: Ask = lambda _invite: str(next(reponses))  # noqa: E731
    else:
        ask = input
    try:
        brouillon = revoir(
            index_path=args.index, bundles_root=args.bundles, draft=args.draft,
            reviewer_login=args.reviewer_login, corpus_manifest_sha256=args.corpus_manifest_sha256,
            ask=ask, only=args.only, corpus_manifest_authority=args.corpus_manifest_authority,
        )
    except (ValueError, StopIteration, FileNotFoundError) as exc:
        print(f"REFUS: {exc}", file=sys.stderr)
        return 1
    decided = sum(1 for d in brouillon["decisions"].values() if d.get("decision") not in (None, PLACEHOLDER))
    print(json.dumps({"draft": str(args.draft), "decided": decided}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
