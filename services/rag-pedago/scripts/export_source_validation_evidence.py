#!/usr/bin/env python3
"""Export versionne des preuves de validation des sources (revue PR #74).

Constat Codex : les verdicts signes produits par ``source_validator`` vivent
sous ``data/`` (ignore par git) ; ni la revue ni un deploiement ulterieur ne
peuvent prouver qu'un couple URL/contenu precis a recu ``verified_candidate``.

Ce script consigne les verdicts signes (dernier par source) dans
``docs/validation/source_validation_evidence.json`` — fichier VERSIONNE.

Portes FAIL-CLOSED (round 7) — l'export est REFUSE (exit 1) si :
  - le ledger contient une ligne non vide malformee (JSON invalide) : une
    troncature ne doit pas laisser un vieux verdict paraitre courant ;
  - un verdict ne respecte pas le SCHEMA COURANT (validator, url, final_url,
    content_sha256 64 hex, signature 16 hex, validated_at) : les verdicts
    d'une version anterieure (v2, sans liaison au contenu) sont perimes ;
  - la signature ne se RECALCULE pas sur le contenu canonique (sha256 du
    JSON trie sans le champ signature, 16 premiers hex) : une entree
    fabriquee ou alteree ne peut pas autoriser l'ingestion ;
  - une source ``status: verified`` suivie par le ledger n'a pas de verdict
    ``verified_candidate`` valide a la meme URL.

Les 9 sources verifiees avant LOT 31 ne sont pas suivies par le ledger :
hors perimetre de cette porte.

Usage (depuis services/rag-pedago) :

    python3 scripts/export_source_validation_evidence.py

Code de sortie : 0 si l'export est ecrit et coherent, 1 sinon.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]  # services/rag-pedago
REPO_ROOT = ROOT.parents[1]  # racine du depot
LEDGER_PATH = ROOT / "data" / "ledger" / "source_validation.jsonl"
SOURCES_PATH = ROOT / "configs" / "eduscol_sources.yml"
EVIDENCE_PATH = REPO_ROOT / "docs" / "validation" / "source_validation_evidence.json"

EXPECTED_VALIDATOR = "source_validator_v5"
# Liste GELEE des 9 sources verifiees avant LOT 31 (hors ledger) : seules
# celles-ci peuvent etre `verified` sans verdict signe. Toute AUTRE source
# `verified` absente du ledger est une violation (revue PR #74, round 9) —
# une source ajoutee directement en `verified` ne peut pas se faire passer
# pour une source legacy.
LEGACY_SOURCES = {
    "eduscol_maths_voie_gt": "https://eduscol.education.gouv.fr/5817/programmes-et-ressources-en-mathematiques-voie-gt",
    "eduscol_philo_voie_gt": "https://eduscol.education.gouv.fr/5826/programmes-et-ressources-en-philosophie-voie-gt",
    "eduscol_nsi_voie_g": "https://eduscol.education.gouv.fr/5823/programmes-et-ressources-en-numerique-et-sciences-informatiques-voie-g",
    "eduscol_snt_seconde": "https://eduscol.education.gouv.fr/5841/programmes-et-ressources-en-sciences-numeriques-et-technologie-voie-gt",
    "eduscol_hlp_voie_gt": "https://eduscol.education.gouv.fr/5805/programmes-et-ressources-en-humanites-litterature-et-philosophie-voie-g",
    "eduscol_eam": "https://eduscol.education.gouv.fr/5688/epreuve-anticipee-de-mathematiques-aux-baccalaureats-general-et-technologique",
    "eduscol_epreuves_terminales_bac_general": "https://eduscol.education.gouv.fr/5706/les-epreuves-terminales-du-baccalaureat-general",
    "eduscol_francais_lycee_gt": "https://eduscol.education.gouv.fr/31197/domaines-enseignement/francais-lycee-gt",
    "eduscol_ses_voie_gt": "https://eduscol.education.gouv.fr/5838/programmes-et-ressources-en-sciences-economiques-et-sociales-voie-gt",
}
_REQUIRED_STR_FIELDS = ("source_id", "url", "final_url", "verdict",
                        "validated_at", "validator")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX16_RE = re.compile(r"^[0-9a-f]{16}$")


def recompute_signature(verdict: dict) -> str:
    """Recalcule la signature v3 : sha256 du JSON canonique (cles triees,
    champ ``signature`` exclu), 16 premiers caracteres hex — meme
    canonisation que ``agents.source_validator``."""
    payload = {k: v for k, v in verdict.items() if k != "signature"}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def schema_errors(verdict: dict) -> list[str]:
    """Defauts de conformite d'un verdict au schema courant (v3)."""
    errors: list[str] = []
    for field in _REQUIRED_STR_FIELDS:
        if not isinstance(verdict.get(field), str) or not verdict.get(field):
            errors.append(f"champ requis absent/invalide: {field}")
    if verdict.get("validator") != EXPECTED_VALIDATOR:
        errors.append(f"validator != {EXPECTED_VALIDATOR} "
                      f"(lu: {verdict.get('validator')!r}) — verdict perime")
    if not _HEX64_RE.match(str(verdict.get("content_sha256", ""))):
        errors.append("content_sha256 absent ou non-hex64")
    if not _HEX16_RE.match(str(verdict.get("signature", ""))):
        errors.append("signature absente ou non-hex16")
    if not errors and recompute_signature(verdict) != verdict["signature"]:
        errors.append("signature non recalculable (entree alteree ou fabriquee)")
    return errors


def load_verdicts(ledger_path: Path) -> tuple[list[dict], list[str]]:
    """Dernier verdict par source_id + erreurs de lignes malformees.

    Toute ligne non vide invalide est une ERREUR (fail-closed) : une
    troncature d'append ne doit pas faire paraitre un vieux verdict comme
    le plus recent."""
    if not ledger_path.is_file():
        return [], [f"ledger absent: {ledger_path}"]
    latest: dict[str, dict] = {}
    order: list[str] = []
    errors: list[str] = []
    for lineno, line in enumerate(
            ledger_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"ligne {lineno}: JSON malforme (ledger corrompu?)")
            continue
        sid = entry.get("source_id")
        if not sid or "verdict" not in entry:
            continue  # resume de run, pas un verdict signe
        if sid not in latest:
            order.append(sid)
        latest[sid] = entry
    return [latest[sid] for sid in order], errors


def coherence_violations(verdicts: list[dict], sources: list[dict]) -> list[str]:
    """Violations de coherence config/preuve : une source `verified` doit
    avoir un verdict `verified_candidate` a la MEME url, ou etre une source
    legacy gelee (id ET url) — regle partagee export / controle CI."""
    by_id = {v["source_id"]: v for v in verdicts}
    violations: list[str] = []
    for s in sources:
        if s.get("status") != "verified":
            continue
        sid = s.get("id") or s.get("source_id")
        v = by_id.get(sid)
        if v is None:
            # Absente des verdicts : acceptable UNIQUEMENT si source legacy
            # gelee (id ET url), sinon violation (revue PR #74, round 9).
            if LEGACY_SOURCES.get(sid) == s.get("url"):
                continue
            violations.append(
                f"{sid} (verified sans verdict et hors liste legacy)")
            continue
        if v.get("verdict") != "verified_candidate":
            violations.append(f"{sid} (verdict={v.get('verdict')})")
        elif s.get("url") and v.get("url") and s["url"] != v["url"]:
            violations.append(f"{sid} (url divergente config/ledger)")
    return violations


def check(evidence_path: Path, sources_path: Path) -> tuple[int, str]:
    """Controle CI (revue PR #74, round 11) : la preuve COMMITEE doit
    couvrir la config courante — sinon la porte fail-closed est lettre
    morte. Ne depend PAS du ledger (data/ est ignore par git).

    Refuse si : preuve absente/illisible, schema perime, verdict non
    conforme ou signature non recalculable, ou source `verified` non
    couverte (hors legacy gelee)."""
    if not evidence_path.is_file():
        return 1, f"preuve absente: {evidence_path}"
    try:
        data = json.loads(evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return 1, f"preuve illisible: {exc}"
    if data.get("validator_schema") != EXPECTED_VALIDATOR:
        return 1, (f"preuve au schema perime "
                   f"{data.get('validator_schema')!r} "
                   f"(attendu {EXPECTED_VALIDATOR}) — reexport requis")
    verdicts = data.get("verdicts")
    if not isinstance(verdicts, list) or not verdicts:
        return 1, "preuve sans verdicts"
    bad: list[str] = []
    for v in verdicts:
        if not isinstance(v, dict):
            bad.append("verdict non-objet")
            continue
        problems = schema_errors(v)
        if problems:
            bad.append(f"{v.get('source_id', '?')}: {'; '.join(problems)}")
    if bad:
        return 1, "PREUVE NON CONFORME: " + " | ".join(bad)
    cfg = yaml.safe_load(sources_path.read_text(encoding="utf-8")) or {}
    violations = coherence_violations(verdicts, cfg.get("sources", []) or [])
    if violations:
        return 1, "VIOLATIONS preuves sources: " + "; ".join(violations)
    return 0, (f"preuve conforme: {len(verdicts)} verdict(s) couvrent la "
               "config courante")


def export(ledger_path: Path, sources_path: Path,
           evidence_path: Path) -> tuple[int, str]:
    """Exporte les preuves et verifie la coherence config/ledger."""
    verdicts, errors = load_verdicts(ledger_path)
    if errors:
        return 1, "LEDGER INVALIDE: " + "; ".join(errors)
    if not verdicts:
        return 1, f"AUCUN verdict signe dans {ledger_path} — rien a exporter"

    # 1. Integrite cryptographique : CHAQUE verdict exporte doit etre au
    #    schema courant avec une signature recalculable.
    bad: list[str] = []
    for v in verdicts:
        problems = schema_errors(v)
        if problems:
            bad.append(f"{v.get('source_id', '?')}: {'; '.join(problems)}")
    if bad:
        return 1, ("VERDICTS NON CONFORMES au schema "
                   f"{EXPECTED_VALIDATOR}: " + " | ".join(bad))

    # 2. Coherence config (meme regle que le controle CI --check).
    cfg = yaml.safe_load(sources_path.read_text(encoding="utf-8")) or {}
    violations = coherence_violations(verdicts, cfg.get("sources", []) or [])
    if violations:
        return 1, "VIOLATIONS preuves sources: " + "; ".join(violations)

    ledger_bytes = ledger_path.read_bytes()
    evidence = {
        "exported_at": datetime.now(UTC).isoformat(),
        "validator_schema": EXPECTED_VALIDATOR,
        "ledger": str(ledger_path.relative_to(REPO_ROOT))
        if ledger_path.is_relative_to(REPO_ROOT) else str(ledger_path),
        "ledger_sha256": hashlib.sha256(ledger_bytes).hexdigest(),
        "verdicts_count": len(verdicts),
        "verdicts": verdicts,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return 0, (f"evidence exportee: {len(verdicts)} verdict(s) signe(s) "
               f"-> {evidence_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="controle CI de la preuve committee (pas d'export)")
    args = parser.parse_args()
    if args.check:
        code, msg = check(EVIDENCE_PATH, SOURCES_PATH)
    else:
        code, msg = export(LEDGER_PATH, SOURCES_PATH, EVIDENCE_PATH)
    print(msg, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
