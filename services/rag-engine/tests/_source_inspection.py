"""Lire le CODE d'un module, sans sa prose.

Plusieurs gardes de ce dépôt affirment qu'un module ne touche jamais à
quelque chose — ``PG_RAG_DSN``, la chaîne de readiness de production, une
fabrique de fixture. Ces modules le DISENT aussi, en toutes lettres, dans
leur docstring : « ne connaît pas ``PG_RAG_DSN`` », « ne l'appelle pas ».

Chercher la chaîne dans le fichier entier ferait donc échouer la garde sur
la documentation qui l'explique. Ce qu'on veut inspecter, c'est le code
exécutable.
"""

from __future__ import annotations

import io
import tokenize
from pathlib import Path


def code_sans_prose(path: Path) -> str:
    """Le source d'un fichier, commentaires et docstrings retirés."""
    source = path.read_text(encoding="utf-8")
    morceaux: list[str] = []
    for jeton in tokenize.generate_tokens(io.StringIO(source).readline):
        if jeton.type == tokenize.COMMENT:
            continue
        nu = jeton.string.lstrip("rbfuRBFU")
        if jeton.type == tokenize.STRING and (
            nu.startswith('"""') or nu.startswith("'''")
        ):
            continue
        morceaux.append(jeton.string)
    return " ".join(morceaux)


__all__ = ["code_sans_prose"]
