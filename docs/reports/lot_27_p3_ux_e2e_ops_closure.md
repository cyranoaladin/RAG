# LOT 27 P3 — UX, E2E et clôture Ops

## Phase

`LOT_27_P3_UX_E2E_AND_OPS_CLOSURE`

Branche de travail : `codex/lot27-p3-ux-e2e-ops-closure`.
Référence parent vérifiée : `38af9e2672614b158a8ddf14cc599e6461bdce1a`.

## Périmètre et invariants

Ce lot est limité au polissage de l'interface Streamlit, aux contrôles E2E
read-only et à la documentation Ops. Il ne modifie ni le contrat backend, ni
la base de données, ni Nginx, ni DNS, ni la production. Aucun déploiement,
ingestion ou action Docker de mutation n'a été effectué.

## TDD et E2E préparatoires

| Horodatage / preuve | Commande ou contrôle | Résultat | Évidence |
|---|---|---|---|
| Avant le commit `5042f83` (2026-07-14T18:29:38+01:00) | Test statique UI avant le polissage | RED, 3 échecs | Les trois assertions ajoutées pour les libellés et la hiérarchie P3 échouaient contre la version antérieure de `app_v2.py`. Le journal d'exécution détaillé n'a pas été conservé ; le commit suivant est la preuve horodatée de la correction. |
| 2026-07-14T18:32:10+01:00, commit `08f8a18` | `PYTHONPATH=src pytest -q tests/test_ui_app_v2_admin.py` | GREEN, 7 passés, exit 0 | Les 3 tests historiques et les 4 contrôles P3 vérifient les libellés, les routes v2 seules, l'absence de legacy et l'absence de rendu de `API_BASE`. |
| Avant le commit `0be8a07` (2026-07-14T18:42:06+01:00) | Stub du runner `scripts/e2e/run-lot27-p3-ui-readonly.sh` sans Playwright | RED, exit 1 attendu | Le runner échoue explicitement avec `Playwright introuvable`, ce qui interdit un faux vert E2E. |
| 2026-07-14T18:49:24+01:00 et 2026-07-14T18:51:37+01:00, commits `dd303d2`, `c242a19` | Contrôle syntaxique et garde réseau E2E | GREEN | Le script est syntaxiquement valide et la garde bloque toute méthode hors `GET`, `HEAD`, `OPTIONS`, ainsi que les erreurs HTTP et contenus/réponses interdits. |

## PR #56 et E2E historique

| Élément | État factuel |
|---|---|
| PR #56 | Ouverte en brouillon, SHA `ca471616ae4270e96561f56724f14f2b7728bfd3`. Elle n'est ni fusionnée ni modifiée par ce lot. |
| Libellé Administration | Les contrôles P3 exigent désormais `Catalogue v2 complet`; ils ne requièrent plus `Collections RAG v2`. |
| Runner historique | Une tentative de worktree temporaire a été retirée. La forme littérale `git -C ... bash scripts/e2e/run-rag-v2-prod-readonly.sh` est invalide (`git` ne connaît pas la sous-commande `bash`). L'équivalent correct est `bash scripts/e2e/run-rag-v2-prod-readonly.sh` depuis la racine. |
| Exécution historique du runner | Bloquée localement par l'absence de `@playwright/test`; aucun correctif de dépendance hors périmètre n'a été appliqué. |
| E2E public P3 antérieur | Exit 1 : la branche P3, non déployée par conception, n'était pas présente dans la release. Les diagnostics ont relevé des 502 sur `/_stcore/health` et `host-config`. Cette exécution n'a produit aucune mutation de production. |

## Validation exécutée pendant la clôture

Les commandes ci-dessous ont été exécutées depuis le worktree P3. Le venv neuf
du worktree a d'abord échoué (2026-07-14T17:54:46Z, `make lint`, exit 2) : au
premier appel, le `Makefile` évalue `PY` avant la création du venv puis appelle
le Python système, refusé par PEP 668 (`externally-managed-environment`). Le
`Makefile` est identique dans `38af9e2`; il s'agit donc d'une dette
d'environnement préexistante, non liée à ce lot. Les résolveurs pip lancés par
les tentatives suivantes ont été arrêtés après observation bornée, sans paquet
installé dans le venv du worktree.

Pour valider le code sans modifier le dépôt, les commandes `make` ont ensuite
utilisé le venv local déjà existant du worktree principal via `VENVDIR`. Ce
venv ne contient aucun changement versionné ; les cibles sont exécutées depuis
le worktree P3 courant.

| Horodatage | Commande | Résultat | Évidence / décision |
|---|---|---|---|
| 2026-07-14T17:54:46Z | `make lint` | Échec, exit 2 | PEP 668 au premier bootstrap du venv; préexistant (`Makefile` identique à `38af9e2`). |
| 2026-07-14T17:58Z | `make VENVDIR=/home/alaeddine/Bureau/RAG/services/rag-engine/.venv lint` | OK, exit 0 | `ruff check .` : `All checks passed!` |
| 2026-07-14T17:59Z–18:01Z | `make VENVDIR=/home/alaeddine/Bureau/RAG/services/rag-engine/.venv typecheck` | Interrompu sans résultat terminal | `mypy src` dépassait 104 s; arrêt borné, sans signaler d'erreur de type. À rejouer dans une CI/venv dédié. |
| 2026-07-14T17:55Z | `make test` | Non conclu | Dépendances du venv neuf encore en résolution; processus arrêté pour ne pas laisser de tâche non bornée. À rejouer dans une CI/venv dédié. |
| 2026-07-14T18:02:33Z | `PYTHONPATH=src …/python -m pytest -q tests/test_ui_app_v2_admin.py` | OK, exit 0 | 7 passés. Contrôle ciblé des changements UI P3 sur le code du worktree. |
| 2026-07-14T17:58:34Z | `bash scripts/check-governance-locks.sh` | OK, exit 0 | 18 verrous conformes au baseline. |
| 2026-07-14T17:58:34Z | `bash scripts/tests/test-governance-locks.sh` | OK, exit 0 | 16 passés, 0 échec. |
| 2026-07-14T17:58:34Z | `git diff --check` | OK, exit 0 | Aucune erreur d'espacement détectée. |
| 2026-07-14T17:58:34Z | `node --check scripts/e2e/lot27-p3-ui-readonly.js` | OK, exit 0 | Syntaxe JavaScript valide. |
| 2026-07-14T17:58:34Z | `bash -n scripts/e2e/run-lot27-p3-ui-readonly.sh` | OK, exit 0 | Syntaxe Bash valide. |

## Décision de validation

Le lint, les garde-fous de gouvernance, les vérifications de diff et la
syntaxe E2E sont verts. Le typecheck et la suite complète `make test` restent
à confirmer dans une CI ou un venv propre préparé, car le bootstrap du venv
isolé présente une dette préexistante et le typecheck n'a pas terminé dans la
fenêtre bornée. Ce point est un blocage de validation locale, pas une action
autorisant une modification backend, de production ou de la PR #56.
