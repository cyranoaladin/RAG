#!/usr/bin/env python3
"""Calculer la fermeture transitive de l'impact d'une ré-émission.

═══ POURQUOI CET OUTIL EXISTE ═══════════════════════════════════════════════

Le rescellement de la release production du 28/08/2026 a été analysé trois fois,
et trois fois le périmètre annoncé s'est révélé incomplet — chaque couche
suivante ayant été découverte par collision, c'est-à-dire par un test qui passe
au rouge après coup :

1. le bundle de release lui-même ;
2. `packages/contracts` — 18 `RetrievalScopeArtifactV2` épinglant `source_sha256` ;
3. les invariants de cardinalité et de nom (comptes de registre, fixtures) ;
4. le document de provenance `release_scope_placement_provenance_*.json` ;
5. le défaut `--registry-sha256` du script d'ingestion canonique.

Chacune de ces couches a **correctement** détecté la dérive. La gouvernance
fonctionne ; ce qui manquait, c'est sa carte.

═══ CE QUE L'OUTIL CALCULE ══════════════════════════════════════════════════

Un diff d'écriture n'est pas un diff d'impact. Quand une valeur change, la
question n'est pas « quels fichiers ai-je réécrits » mais « qui référence cette
valeur, où que ce soit » — puis, récursivement, « qui référence *ces* fichiers-là ».

    V := valeurs changées : contenus du diff ET empreintes des fichiers modifiés
    répéter :
        S := fichiers du dépôt contenant une valeur de V
        pour chaque fichier de S qui sera lui-même réécrit :
            ajouter son empreinte actuelle à V
    jusqu'à ce que S n'apporte aucun fichier nouveau

L'empreinte **actuelle** d'un fichier propagateur suffit à découvrir la couche
suivante : c'est elle qu'un tiers épingle. L'empreinte future ne sert qu'à écrire,
pas à découvrir.

Le point crucial est le premier : une valeur peut être l'empreinte **du** fichier
modifié, et non une valeur **dans** son contenu. `release-registry.json` a changé
de contenu ; son propre sha256 n'apparaît nulle part dans le diff, par
construction — et c'est précisément lui qu'épinglaient les couches 4 et 5.

═══ FRONTIÈRE DE VALIDITÉ — LE RUNTIME N'EST PAS LE DÉPÔT ═══════════════════

Cet outil balaie **le dépôt**. Tout ce qui exécute du code hors versionnement lui
est invisible **par construction**, et non par omission :

- **images Docker** : le contrat est copié dans l'image au build, puis figé ;
- **environnements virtuels** : `pip install -e` suit les sources, un
  `pip install` ordinaire fige une copie ;
- **caches** de toute nature.

Le 28/08/2026, la seconde émission des scopes a été committée, testée verte sur
trois paquets, et le runtime a continué de refuser de démarrer : l'image de
l'ingestor embarquait `nexus-contracts` 0.14.0, 31 scopes, aucun `_v2`. Aucun
balayage du dépôt ne pouvait le voir.

Une fermeture complète ne prouve donc **rien** sur ce que les runtimes exécutent.
`scripts/check_runtime_conformance.py` couvre cette seconde question ; les deux
outils sont complémentaires et aucun ne remplace l'autre.

═══ CLASSIFICATION ══════════════════════════════════════════════════════════

Chaque site est classé, et la classe décide du traitement :

- **historique** : rapport daté, enregistrement de ce qui était vrai à sa date.
  Ne se réécrit pas, ne propage pas. Le modifier détruirait de la traçabilité.
- **propagateur** : son contenu change, donc son empreinte change, donc il ouvre
  potentiellement une couche de plus.
- **terminal** : il référence une valeur mais rien ne référence son empreinte.

Limite connue : deux formes d'empreinte sont recherchées — octets et JSON
canonique compact. `nexus-contracts` en emploie au moins cinq, plus des
empreintes calculées sur une *projection de champs* (`canonical_document()`),
qu'aucune fonction générique appliquée au fichier ne peut reproduire. La carte
est complète **sous ces deux modes**, pas absolument (dettes n°23 et n°24).

═══ USAGE ═══════════════════════════════════════════════════════════════════

    python3 scripts/release_impact_closure.py                # diff courant
    python3 scripts/release_impact_closure.py --base HEAD~1  # diff d'un commit
    python3 scripts/release_impact_closure.py --json         # sortie machine

Deux modes d'empreinte sont recherchés pour chaque fichier : celle de ses
octets et celle de sa forme JSON canonique. Elles ne coïncident pas, et le
dépôt utilise les deux.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

#: Répertoires exclus du balayage. Nommés explicitement : un balayage qui
#: établit un négatif doit justifier son périmètre aussi rigoureusement que son
#: résultat. `find /home /mnt` prouve l'absence dans /home et /mnt, pas l'absence.
EXCLUDED_DIRECTORIES = frozenset(
    {".git", ".venv", ".worktrees", "node_modules", "__pycache__", ".next", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
)

#: Rapports datés : enregistrements d'un état passé, jamais réécrits.
#: Un rapport qui cite une empreinte périmée n'est pas un épinglage à corriger.
HISTORICAL_PATTERNS = (
    re.compile(r"^docs/reports/lot_.*\.md$"),
    re.compile(r"^docs/reports/master_go_live_state_\d{8}\.json$"),
    re.compile(r"^docs/reports/.*_audit_\d{8}\.json$"),
    re.compile(r"^docs/adr/"),
    re.compile(r"^docs/runbooks/"),
    re.compile(r"^docs/superpowers/"),
)

_SHA256 = re.compile(r"\b[0-9a-f]{64}\b")


def _run(*args: str) -> str:
    return subprocess.run(
        args, cwd=REPOSITORY_ROOT, check=True, capture_output=True, text=True
    ).stdout


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    """Forme canonique unique du dépôt.

    `nexus_contracts.scope.RetrievalScopeArtifactV2.canonical_bytes`,
    `rag_pedago.imports.review.canonical_json_bytes` et
    `build_production_profile_release.canonical_json_bytes` emploient tous ces
    trois paramètres. Une seule implémentation suffit donc à couvrir les
    empreintes sémantiques du dépôt.
    """
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digests_of(payload: bytes) -> set[str]:
    """Toutes les empreintes par lesquelles un contenu peut être épinglé.

    Deux modes coexistent dans le dépôt, et ne coïncident pas :

    - l'empreinte des **octets** du fichier, employée par les inventaires
      (`SHA256SUMS`, `input_blob_sha256` d'une provenance) ;
    - l'empreinte **canonique** du JSON désérialisé, employée par le registre
      de scopes (`_RETRIEVAL_SCOPE_RESOURCES` stocke
      `RetrievalScopeArtifactV2.sha256_digest()`).

    Pour un même artefact de scope, les deux diffèrent — indentation et ordre
    des clés du fichier ne sont pas la forme canonique. Ne chercher que la
    première manquerait tout site épinglant la seconde : c'est le même angle
    mort qui a fait découvrir trois couches par collision, déplacé d'un cran.
    """
    digests = {_sha256_bytes(payload)}
    try:
        parsed = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return digests
    try:
        digests.add(_sha256_bytes(_canonical_json_bytes(parsed)))
    except (TypeError, ValueError):
        pass
    return digests


def _is_excluded(relative: Path) -> bool:
    return any(part in EXCLUDED_DIRECTORIES for part in relative.parts)


def _repository_files() -> list[Path]:
    """Énumérer les fichiers du DÉPÔT, pas du répertoire de travail.

    `git ls-files` plutôt qu'un parcours du système de fichiers : une sauvegarde
    locale (`\u002eenv.bak_*`), un artefact de build ou un fichier ignoré n'est
    pas un site d'épinglage — il n'engage personne et disparaîtra. Les inclure
    produirait des faux positifs, et pour les sauvegardes de `\u002eenv`, ferait
    transiter des secrets dans un rapport d'impact.
    """
    output = _run("git", "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    files: list[Path] = []
    for entry in output.split("\0"):
        if not entry:
            continue
        relative = Path(entry)
        if _is_excluded(relative):
            continue
        absolute = REPOSITORY_ROOT / relative
        if absolute.is_file() and not absolute.is_symlink():
            files.append(relative)
    return files


def _classify(relative: str) -> str:
    return "historique" if any(p.match(relative) for p in HISTORICAL_PATTERNS) else "actif"


def _changed_files(base: str, paths: tuple[str, ...]) -> list[str]:
    output = _run("git", "diff", "--name-only", base, "--", *paths).strip()
    return [line for line in output.splitlines() if line]


def _seed_values(
    base: str, changed: list[str], paths: tuple[str, ...]
) -> tuple[set[str], dict[str, str]]:
    """Valeurs de départ : contenus du diff ET empreintes des fichiers modifiés."""
    diff = _run("git", "diff", "-U0", base, "--", *paths)
    removed = {
        value
        for line in diff.splitlines()
        if line.startswith("-")
        for value in _SHA256.findall(line)
    }
    added = {
        value
        for line in diff.splitlines()
        if line.startswith("+")
        for value in _SHA256.findall(line)
    }
    values = removed - added

    # ── Le point que deux analyses successives avaient manqué ──────────────
    # L'empreinte D'UN fichier modifié n'apparaît jamais dans son propre diff.
    file_digests: dict[str, list[str]] = {}
    for relative in changed:
        try:
            previous = _run("git", "show", f"{base}:{relative}").encode(
                "utf-8", "surrogateescape"
            )
        except subprocess.CalledProcessError:
            continue
        digests = _digests_of(previous)
        file_digests[relative] = sorted(digests)
        values |= digests
    return values, file_digests


def compute_closure(base: str, paths: tuple[str, ...] = (".",)) -> dict[str, object]:
    changed = _changed_files(base, paths)
    values, seed_digests = _seed_values(base, changed, paths)
    inventory = _repository_files()

    known: set[str] = set(changed)
    layers: list[dict[str, object]] = []
    frontier = set(values)

    while frontier:
        sites: dict[str, set[str]] = {}
        for relative in inventory:
            text = relative.as_posix()
            if text in known:
                continue
            try:
                payload = (REPOSITORY_ROOT / relative).read_bytes()
            except OSError:
                continue
            found = {value for value in frontier if value.encode() in payload}
            if found:
                sites[text] = found

        if not sites:
            break

        entries = []
        next_frontier: set[str] = set()
        for text, found in sorted(sites.items()):
            nature = _classify(text)
            digests = _digests_of((REPOSITORY_ROOT / text).read_bytes())
            propagates = nature == "actif"
            entries.append(
                {
                    "file": text,
                    "nature": nature,
                    "values": sorted(found),
                    "current_digests": sorted(digests),
                    "propagates": propagates,
                }
            )
            known.add(text)
            if propagates:
                next_frontier |= digests

        layers.append({"index": len(layers) + 1, "sites": entries})
        frontier = next_frontier

    return {
        "base": base,
        "changed_files": changed,
        "seed_values": sorted(values),
        "seed_file_digests": seed_digests,
        "layers": layers,
        "excluded_directories": sorted(EXCLUDED_DIRECTORIES),
    }


def _render(closure: dict[str, object]) -> None:
    changed = closure["changed_files"]
    assert isinstance(changed, list)
    print(f"Base de comparaison : {closure['base']}")
    print(f"Fichiers modifiés   : {len(changed)}")
    seed = closure["seed_values"]
    assert isinstance(seed, list)
    print(f"Valeurs de départ   : {len(seed)}")
    print(f"Périmètre exclu     : {', '.join(closure['excluded_directories'])}")  # type: ignore[arg-type]
    layers = closure["layers"]
    assert isinstance(layers, list)
    print(f"\nCouches d'impact    : {len(layers)}")
    for layer in layers:
        sites = layer["sites"]
        actifs = sum(1 for s in sites if s["propagates"])
        print(f"\n── Couche {layer['index']} : {len(sites)} site(s), dont {actifs} propagateur(s)")
        for site in sites:
            marque = "→" if site["propagates"] else "·"
            print(f"   {marque} [{site['nature']:<10}] {site['file']}")
            for value in site["values"][:2]:
                print(f"       {value[:24]}…")
            if len(site["values"]) > 2:
                print(f"       … et {len(site['values']) - 2} autre(s)")
    if not layers:
        print("\n   Aucun impact hors des fichiers modifiés.")
    print("\nFermeture atteinte : aucun fichier nouveau à la dernière itération.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="HEAD")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--path",
        action="append",
        default=None,
        help="Restreindre les fichiers de départ (répétable). Défaut : tout le dépôt.",
    )
    args = parser.parse_args(argv)

    closure = compute_closure(args.base, tuple(args.path or (".",)))
    if args.json:
        print(json.dumps(closure, indent=2, ensure_ascii=False))
    else:
        _render(closure)
    return 0


if __name__ == "__main__":
    sys.exit(main())
