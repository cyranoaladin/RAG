#!/usr/bin/env python3
"""Audit complet du cockpit, avec UNE exception temporaire, bornée et fail-closed.

Contexte : l'avis GHSA-vfj7-8cjw-p6xm (CVE-2026-93687, ``braces`` <= 3.0.3, sévérité haute, aucune
version corrigée publiée) fait échouer ``npm audit`` pour sept paquets de développement
(``tailwindcss`` et ses dépendances). Cette politique restaure le caractère utile du contrôle
au lieu de le désactiver : elle n'accepte l'échec de ``npm audit`` que si l'ensemble des
vulnérabilités est EXACTEMENT celui de cette exception.

Le contrôle échoue pour toute vulnérabilité nouvelle ou différente, de quelque sévérité que ce soit,
pour tout paquet dépendant de ``braces`` qui s'ajouterait aux sept connus, dès que ``braces`` entre dans
l'arbre de production, dès qu'un correctif devient disponible, si l'avis change, et après l'échéance.
L'audit de production (``npm audit --omit=dev``) reste un contrôle distinct, sans exception.

Code de sortie : 0 = ``PASS_WITH_EXACT_TEMPORARY_EXCEPTION`` ; 1 = refus ; 2 = entrée illisible.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Échéance de l'exception. Aucune extension automatique : après cette date le contrôle est rouge tant que
#: l'exception existe. Avant, il faut une mise à jour amont devenue disponible ou la migration Tailwind v4.
EXPIRES_AT = datetime(2026, 10, 17, 23, 59, 59, tzinfo=UTC)

GHSA = "GHSA-vfj7-8cjw-p6xm"
CVE = "CVE-2026-93687"
ADVISORY_URL = f"https://github.com/advisories/{GHSA}"
NPM_SOURCE = 1240992
ROOT_PACKAGE = "braces"
ADVISORY_RANGE = "<=3.0.3"
#: La population tolérée : ces sept paquets, ni un de plus. Un nouveau dépendant de ``braces`` est un
#: élargissement, donc un refus, même si sa chaîne causale remonte au même avis.
TOLERATED_PACKAGES = frozenset({
    "@next/eslint-plugin-next", "braces", "chokidar", "fast-glob", "micromatch",
    "tailwindcss", "tailwindcss-animate",
})
PASS_VERDICT = "PASS_WITH_EXACT_TEMPORARY_EXCEPTION"


def _roots(name: str, vulnerabilities: dict[str, Any], seen: tuple[str, ...] = ()) -> set[Any]:
    """Avis (identifiants npm) auxquels remonte la chaîne causale d'une vulnérabilité."""
    roots: set[Any] = set()
    for via in vulnerabilities[name].get("via", []):
        if isinstance(via, dict):
            roots.add(via.get("source"))
        elif isinstance(via, str) and via in vulnerabilities and via not in seen:
            roots |= _roots(via, vulnerabilities, (*seen, name))
        else:
            roots.add(f"inconnu:{via}")
    return roots


def _total(audit: Any) -> int | None:
    try:
        return int(audit["metadata"]["vulnerabilities"]["total"])
    except (KeyError, TypeError, ValueError):
        return None


def evaluate(full: Any, prod: Any, lockfile: Any, now: datetime) -> list[str]:
    """Raisons de refus ; liste vide si et seulement si l'exception s'applique exactement."""
    errors: list[str] = []
    if now > EXPIRES_AT:
        errors.append(f"exception expirée le {EXPIRES_AT.isoformat()} : supprimer l'exception ou la requalifier")

    # ── audit de production : aucune exception ────────────────────────────────
    total_prod = _total(prod)
    if total_prod is None or not isinstance(prod.get("vulnerabilities"), dict):
        errors.append("audit de production illisible")
    elif total_prod != 0 or prod["vulnerabilities"]:
        errors.append(f"audit de production non propre ({total_prod} vulnérabilité(s)) : aucune exception en production")

    # ── audit complet ─────────────────────────────────────────────────────────
    total_full = _total(full)
    vulnerabilities = full.get("vulnerabilities") if isinstance(full, dict) else None
    if total_full is None or not isinstance(vulnerabilities, dict):
        errors.append("audit complet illisible")
        return errors
    if total_full == 0 or not vulnerabilities:
        errors.append("l'audit complet est propre : l'exception est obsolète, la supprimer")
        return errors

    # L'avis exact doit être présent, identique, sur ``braces``.
    brace = vulnerabilities.get(ROOT_PACKAGE)
    advisory = next(
        (v for v in (brace or {}).get("via", []) if isinstance(v, dict) and v.get("source") == NPM_SOURCE), None)
    if advisory is None:
        errors.append(f"l'avis {GHSA} (source npm {NPM_SOURCE}) est absent de braces alors que l'audit est rouge")
    else:
        for champ, attendu in (("name", ROOT_PACKAGE), ("url", ADVISORY_URL), ("range", ADVISORY_RANGE),
                               ("severity", "high")):
            if advisory.get(champ) != attendu:
                errors.append(f"l'avis a changé : {champ}={advisory.get(champ)!r}, attendu {attendu!r}")

    # Toute vulnérabilité, de toute sévérité, doit remonter exclusivement à cet avis.
    for name, vuln in sorted(vulnerabilities.items()):
        if not isinstance(vuln, dict):
            errors.append(f"vulnérabilité illisible : {name}")
            continue
        roots = _roots(name, vulnerabilities)
        if roots != {NPM_SOURCE}:
            errors.append(f"{name} ne remonte pas exclusivement à {GHSA} (racines {sorted(map(str, roots))})")
        if vuln.get("severity") != "high":
            errors.append(f"{name} : sévérité {vuln.get('severity')!r} hors de l'exception (high seulement)")
    metadata = full["metadata"]["vulnerabilities"]
    if int(metadata.get("critical", 0)) != 0:
        errors.append("vulnérabilité critique présente")

    # Population exacte : ni plus, ni moins que les sept connus.
    noms = set(vulnerabilities)
    if noms != TOLERATED_PACKAGES:
        errors.append(
            f"population tolérée modifiée : en trop {sorted(noms - TOLERATED_PACKAGES)}, "
            f"en moins {sorted(TOLERATED_PACKAGES - noms)}")

    # Un correctif devenu disponible rend l'exception caduque.
    for name, vuln in sorted(vulnerabilities.items()):
        fix = vuln.get("fixAvailable") if isinstance(vuln, dict) else None
        if fix is True or (isinstance(fix, dict) and fix.get("name") == ROOT_PACKAGE):
            errors.append(f"un correctif de {ROOT_PACKAGE} est disponible ({name}) : supprimer l'exception")

    # braces, et tout paquet de l'exception, restent confinés au développement (lecture du lockfile).
    paquets = lockfile.get("packages") if isinstance(lockfile, dict) else None
    if not isinstance(paquets, dict):
        errors.append("package-lock.json illisible")
    else:
        for name in sorted(noms | {ROOT_PACKAGE}):
            entrees = [(chemin, e) for chemin, e in paquets.items()
                       if chemin == f"node_modules/{name}" or chemin.endswith(f"/node_modules/{name}")]
            if not entrees:
                errors.append(f"{name} absent du lockfile : confinement au développement non prouvé")
            for chemin, entree in entrees:
                if entree.get("dev") is not True:
                    errors.append(f"{chemin} n'est pas marqué dev:true : présent dans l'arbre de production")
    return errors


def _json(texte: str, quoi: str) -> Any:
    try:
        return json.loads(texte)
    except ValueError as exc:
        raise SystemExit(f"COCKPIT_AUDIT_POLICY_INPUT_ERROR : JSON npm illisible ({quoi}) : {exc}") from exc


def _npm(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["npm", *args], capture_output=True, text=True, check=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--full-json", type=Path, help="sortie de `npm audit --json` (tests)")
    parser.add_argument("--prod-json", type=Path, help="sortie de `npm audit --omit=dev --json` (tests)")
    parser.add_argument("--lockfile", type=Path, default=Path("package-lock.json"))
    parser.add_argument("--now", help="horodatage ISO 8601 (tests)")
    args = parser.parse_args(argv)

    if args.full_json and args.prod_json:
        full_texte, prod_texte = args.full_json.read_text(encoding="utf-8"), args.prod_json.read_text(encoding="utf-8")
    else:
        texte = _npm(["audit"])  # la sortie lisible n'est jamais masquée
        sys.stdout.write(texte.stdout + texte.stderr)
        full_texte, prod_texte = _npm(["audit", "--json"]).stdout, _npm(["audit", "--omit=dev", "--json"]).stdout
    full, prod = _json(full_texte, "audit complet"), _json(prod_texte, "audit de production")
    try:
        lockfile = json.loads(args.lockfile.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"COCKPIT_AUDIT_POLICY_INPUT_ERROR : lockfile illisible : {exc}") from exc
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(UTC)

    errors = evaluate(full, prod, lockfile, now)
    if errors:
        print("COCKPIT_AUDIT_POLICY=REFUSED", file=sys.stderr)
        for erreur in errors:
            print(f"  - {erreur}", file=sys.stderr)
        return 1
    print(f"COCKPIT_AUDIT_POLICY={PASS_VERDICT} advisory={GHSA} cve={CVE} package={ROOT_PACKAGE} "
          f"scope=development-only expires={EXPIRES_AT.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
