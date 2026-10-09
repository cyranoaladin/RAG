# Lot 310 — dette de typage préexistante

- Date de contrôle : 2026-10-09, Python 3.12, `mypy` 1.11.2.
- Base **SEALED** : `origin/main` `59da01c9821cbbff8b12194394d232dc33ecf149` ; candidat code **SEALED** : `2be707a1331605abe28ac67fb5f06f3c36e04de7`.
- Commande identique dans deux worktrees propres, avec le même venv non éditable :
  `make -o install-dev typecheck VENVDIR=<venv-du-lot>`. L'option `-o`
  évite de réinstaller les dépendances dans le venv déjà préparé ; la recette
  officielle `python -m mypy src` est exécutée sans modification.
- Résultat : **5 erreurs sur 149 fichiers**, code retour `2`, sur la base
  comme sur le candidat. Le contrôle n'est pas vert ; aucune erreur nouvelle.

Erreurs identiques sur les deux SHAs :

| Fichier | Ligne | Diagnostic |
| --- | ---: | --- |
| `src/ingestor/tasks.py` | 205 | `Returning Any from function declared to return "str" [no-any-return]` |
| `src/ingestor/api.py` | 892 | `Returning Any from function declared to return "list[Any]" [no-any-return]` |
| `src/ingestor/api.py` | 1053 | Même diagnostic |
| `src/ingestor/api.py` | 1072 | Même diagnostic |
| `src/backend/deps.py` | 31 | `Returning Any from function declared to return "User" [no-any-return]` |

Un contrôle additionnel des quatre scripts de gouvernance du lot avec
`mypy --no-incremental` relève **41 diagnostics identiques** sur base et
candidat après normalisation des numéros de ligne. Il n'est pas la recette
`make typecheck` et n'est pas déclaré vert. La présente PR ne modifie aucun
des trois modules `src` concernés par la recette officielle.
