#!/usr/bin/env python3
"""Vérifier que les runtimes portent bien le code du dépôt.

═══ POURQUOI CET OUTIL EXISTE ═══════════════════════════════════════════════

`scripts/release_impact_closure.py` calcule la fermeture transitive d'un
changement **dans le dépôt**. Son domaine de validité s'arrête là : le runtime
n'est pas le dépôt.

Le 28/08/2026, la seconde émission des scopes de retrieval a été committée,
testée verte sur trois paquets, et le runtime a continué de refuser de démarrer
sur `scope source SHA differs from subject release`. L'image Docker de
l'ingestor embarquait `nexus-contracts` 0.14.0 — 31 scopes, aucun `_v2` — figé
au moment de son build. Aucun balayage du dépôt ne pouvait le voir : cette copie
ne vit pas dans le dépôt.

C'est une **frontière de méthode**, pas un oubli de l'outil de fermeture.

═══ CE QUE L'OUTIL VÉRIFIE ══════════════════════════════════════════════════

Pour chaque paquet local du dépôt (identifié par son `pyproject.toml`), et pour
chaque runtime qui le porte, l'outil établit **comment** il le porte :

- **lié** — installation éditable : le runtime lit les sources du dépôt, son code
  est donc toujours à jour. Sa *métadonnée* de version peut en revanche dater de
  l'installation ;
- **figé** — copie embarquée (image Docker, `pip install` non éditable) : code et
  métadonnée datent tous deux de la copie, et divergent silencieusement dès que
  le dépôt change.

La distinction décide de tout : un runtime lié suit le dépôt, un runtime figé
doit être reconstruit.

═══ USAGE ═══════════════════════════════════════════════════════════════════

    python3 scripts/check_runtime_conformance.py
    python3 scripts/check_runtime_conformance.py --json

Code de sortie non nul si un runtime figé diverge du dépôt.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

#: Environnements virtuels du dépôt.
VIRTUAL_ENVIRONMENTS = (
    "services/rag-engine/.venv",
    "services/rag-pedago/.venv",
)

#: Images Docker portant du code du dépôt, avec l'interpréteur à interroger.
DOCKER_IMAGES = ("nexusrag-ingestor:latest",)

_PROBE = """
import importlib.metadata as metadata
import json
import os
report = {}
for name in %(names)r:
    entry = {}
    try:
        entry["version"] = metadata.version(name)
    except Exception as error:
        entry["version"] = None
        entry["error"] = type(error).__name__
    try:
        module = __import__(name.replace("-", "_"))
        entry["path"] = os.path.dirname(module.__file__ or "")
    except Exception as error:
        entry["path"] = None
        entry.setdefault("error", type(error).__name__)
    report[name] = entry
print(json.dumps(report))
"""


def _local_packages() -> dict[str, str]:
    """Paquets locaux du dépôt : nom de distribution -> version déclarée."""
    packages: dict[str, str] = {}
    for pyproject in REPOSITORY_ROOT.glob("packages/*/pyproject.toml"):
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = data.get("project") or {}
        name, version = project.get("name"), project.get("version")
        if isinstance(name, str) and isinstance(version, str):
            packages[name] = version
    return packages


def _probe(command: list[str], names: list[str]) -> dict[str, dict[str, object]]:
    completed = subprocess.run(
        [*command, "-c", _PROBE % {"names": names}],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return {name: {"version": None, "error": "PROBE_FAILED"} for name in names}
    try:
        parsed = json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {name: {"version": None, "error": "PROBE_UNREADABLE"} for name in names}
    return parsed


def _linkage(path: object) -> str:
    """« lié » si le runtime lit les sources du dépôt, « figé » sinon."""
    if not isinstance(path, str) or not path:
        return "absent"
    try:
        Path(path).resolve().relative_to(REPOSITORY_ROOT)
    except ValueError:
        return "figé"
    return "lié"


def check() -> dict[str, object]:
    packages = _local_packages()
    names = sorted(packages)
    runtimes: list[dict[str, object]] = []

    for relative in VIRTUAL_ENVIRONMENTS:
        interpreter = REPOSITORY_ROOT / relative / "bin" / "python"
        if not interpreter.is_file():
            runtimes.append({"runtime": relative, "kind": "venv", "absent": True})
            continue
        runtimes.append(
            {
                "runtime": relative,
                "kind": "venv",
                "packages": _probe([str(interpreter)], names),
            }
        )

    for image in DOCKER_IMAGES:
        runtimes.append(
            {
                "runtime": image,
                "kind": "image",
                "packages": _probe(
                    ["docker", "run", "--rm", "--entrypoint", "python", image], names
                ),
            }
        )

    findings: list[dict[str, object]] = []
    for runtime in runtimes:
        reported = runtime.get("packages")
        if not isinstance(reported, dict):
            continue
        for name, entry in reported.items():
            linkage = _linkage(entry.get("path"))
            declared = packages[name]
            installed = entry.get("version")
            runtime["linkage"] = linkage
            if linkage == "absent":
                findings.append(
                    {
                        "runtime": runtime["runtime"],
                        "package": name,
                        "severity": "bloquant",
                        "reason": "paquet introuvable dans ce runtime",
                    }
                )
            elif linkage == "figé" and installed != declared:
                findings.append(
                    {
                        "runtime": runtime["runtime"],
                        "package": name,
                        "severity": "bloquant",
                        "reason": (
                            f"copie figée en {installed}, dépôt en {declared} — "
                            "reconstruire ce runtime"
                        ),
                    }
                )
            elif linkage == "lié" and installed != declared:
                findings.append(
                    {
                        "runtime": runtime["runtime"],
                        "package": name,
                        "severity": "mineur",
                        "reason": (
                            f"code à jour (lié aux sources), métadonnée figée en "
                            f"{installed} au lieu de {declared} — "
                            "réinstaller en éditable pour la rafraîchir"
                        ),
                    }
                )

    return {"packages": packages, "runtimes": runtimes, "findings": findings}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = check()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        packages = report["packages"]
        assert isinstance(packages, dict)
        print("Paquets locaux du dépôt :")
        for name, version in sorted(packages.items()):
            print(f"  {name} {version}")
        print("\nRuntimes :")
        runtimes = report["runtimes"]
        assert isinstance(runtimes, list)
        for runtime in runtimes:
            reported = runtime.get("packages")
            if not isinstance(reported, dict):
                print(f"  {runtime['runtime']:<34} ABSENT")
                continue
            for name, entry in sorted(reported.items()):
                print(
                    f"  {str(runtime['runtime']):<34} {name} "
                    f"{entry.get('version')}  [{_linkage(entry.get('path'))}]"
                )
        findings = report["findings"]
        assert isinstance(findings, list)
        print(f"\nÉcarts : {len(findings)}")
        for finding in findings:
            print(
                f"  [{finding['severity']:<9}] {finding['runtime']} / "
                f"{finding['package']} : {finding['reason']}"
            )

    findings = report["findings"]
    assert isinstance(findings, list)
    return 1 if any(f["severity"] == "bloquant" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
