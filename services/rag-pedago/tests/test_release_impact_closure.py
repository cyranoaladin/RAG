"""Contrat de l'outil de fermeture transitive d'impact.

Le rescellement de la release production du 28/08/2026 a vu son périmètre annoncé
trois fois, et trois fois révisé — chaque couche suivante découverte par
collision, c'est-à-dire par un test rouge après coup. Cinq couches imbriquées,
chacune ayant correctement détecté la dérive : la gouvernance fonctionnait, nul
n'en avait la carte.

`scripts/release_impact_closure.py` est cette carte. Ces tests pincent les deux
propriétés dont elle dépend : la découverte par empreinte **du** fichier modifié
— et non seulement des valeurs qu'il contient — et la couverture des deux formes
d'empreinte qui coexistent dans le dépôt.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "scripts" / "release_impact_closure.py"


def _tool() -> Any:
    spec = importlib.util.spec_from_file_location("release_impact_closure", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_digests_cover_bytes_and_canonical_json() -> None:
    """Les deux modes d'empreinte doivent être calculés, car ils diffèrent.

    Le dépôt épingle tantôt les octets d'un fichier (inventaires `SHA256SUMS`,
    `input_blob_sha256` d'une provenance), tantôt son JSON canonique
    (`_RETRIEVAL_SCOPE_RESOURCES` stocke `sha256_digest()`, calculé sur le
    `model_dump` trié et compact). Pour un même fichier indenté, les deux valeurs
    sont différentes.

    Ne chercher que la première manquerait tout site épinglant la seconde — c'est
    ainsi que `scope.py` a été trouvé, en couche 2, alors que le mode octets seul
    concluait à une fermeture en une couche.
    """
    payload = b'{\n  "b": 2,\n  "a": 1\n}\n'
    digests = _tool()._digests_of(payload)

    canonical = json.dumps(
        {"a": 1, "b": 2}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    assert hashlib.sha256(payload).hexdigest() in digests
    assert hashlib.sha256(canonical).hexdigest() in digests
    assert len(digests) == 2, "les deux modes doivent être distincts ici"


def test_digests_of_non_json_yields_bytes_only() -> None:
    """Un contenu non-JSON n'a qu'une empreinte : celle de ses octets."""
    digests = _tool()._digests_of(b"ceci n'est pas du JSON")

    assert digests == {hashlib.sha256(b"ceci n'est pas du JSON").hexdigest()}


def test_repository_inventory_ignores_untracked_and_ignored_files(
    tmp_path: Path,
) -> None:
    """Le balayage porte sur le dépôt, jamais sur le répertoire de travail.

    Une sauvegarde locale (`.env.bak_*`), un artefact de build ou un fichier
    ignoré n'engage personne et disparaîtra : le compter comme site d'épinglage
    produit des faux positifs — et pour les sauvegardes de `.env`, ferait
    transiter des secrets dans un rapport d'impact.
    """
    inventory = {path.as_posix() for path in _tool()._repository_files()}
    tracked = {
        line
        for line in subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        if line
    }

    assert inventory <= tracked | {
        path.as_posix() for path in _tool()._repository_files()
    }
    assert not any(".venv" in path for path in inventory)
    assert not any("/__pycache__/" in path for path in inventory)
    assert not any(path.startswith(".git/") for path in inventory)


def test_closure_seeds_include_the_digest_of_each_changed_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le seed doit contenir l'empreinte DES fichiers, pas seulement celles DEDANS.

    C'est le point qu'ont manqué deux analyses successives.
    `release-registry.json` a changé de contenu ; son propre sha256 n'apparaît
    nulle part dans son diff, par construction — et c'est précisément lui
    qu'épinglaient la provenance du placement et le défaut `--registry-sha256`.
    """
    tool = _tool()
    module_source = TOOL.read_text(encoding="utf-8")

    assert "_digests_of(previous)" in module_source, (
        "le seed doit dériver les empreintes du contenu ANTÉRIEUR de chaque "
        "fichier modifié"
    )
    assert "values |= digests" in module_source

    # La docstring doit porter la raison, pas seulement le code.
    assert "n'apparaît jamais dans son propre diff" in module_source
    assert tool.EXCLUDED_DIRECTORIES, "le périmètre exclu doit être nommé"


def test_historical_reports_never_propagate() -> None:
    """Un rapport daté enregistre un état passé : il ne se réécrit pas.

    Le réécrire détruirait de la traçabilité, et le traiter comme propagateur
    ferait explorer des couches qui n'existent pas.
    """
    tool = _tool()

    assert tool._classify("docs/reports/lot_production_profiles_20260825.md") == (
        "historique"
    )
    assert tool._classify("docs/reports/master_go_live_state_20260815.json") == (
        "historique"
    )
    assert tool._classify("docs/adr/ADR-0052-quelque-chose.md") == "historique"
    assert tool._classify(
        "packages/contracts/src/nexus_contracts/scope.py"
    ) == "actif"
