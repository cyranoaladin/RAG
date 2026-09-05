"""Outillage partagé des tests `rag-pedago`.

Le producteur de release est un script, pas un module installé : les tests le
chargent par chemin. Fait naïvement, ce chargement laisse le module absent de
`sys.modules`, et `dataclasses` — qui y cherche l'espace de noms de la classe
pour résoudre ses annotations — échoue par un `AttributeError` obscur dès qu'une
`@dataclass` apparaît dans le script. Le chargement est donc fait ici, une fois,
correctement, plutôt que réinventé dans chaque fichier de test.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

SERVICE_ROOT = Path(__file__).resolve().parents[1]
PRODUCER_PATH = SERVICE_ROOT / "scripts" / "build_production_profile_release.py"

_CACHE: dict[str, Any] = {}


def load_script_module(path: Path, name: str) -> Any:
    """Charge un script par chemin, enregistré et mis en cache.

    Mis en cache parce que l'import du producteur est lourd : le recharger par
    test multipliait le coût de la suite sans rien prouver de plus."""
    if name not in _CACHE:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:  # pragma: no cover - chemin invalide
            raise RuntimeError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        # Enregistré AVANT exécution : `dataclasses` résout ses annotations en
        # relisant `sys.modules[cls.__module__]`, et une entrée absente y devient
        # un `None` déréférencé.
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
        _CACHE[name] = module
    return _CACHE[name]


def load_producer() -> Any:
    """Le producteur de release, chargé une fois pour toute la suite."""
    return load_script_module(PRODUCER_PATH, "build_production_profile_release")
