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

Deux sessions de validation ont eu lieu.

### Session 1 (2026-07-14, venv neuf)

Le venv neuf du worktree a échoué au premier bootstrap (PEP 668). Les
commandes `make` ont utilisé le venv du worktree principal via `VENVDIR`.
Le lint passait, le typecheck dépassait la fenêtre bornée, le test complet
n'a pas pu conclure.

### Session 2 (2026-07-15, venv installé via `make install`)

Après `make install` dans le worktree, toutes les commandes passent :

| Commande | Résultat |
|---|---|
| `make lint` | OK — `All checks passed!` |
| `make typecheck` | OK — `Success: no issues found in 39 source files` |
| `make test` | OK — 479 passed, 14 deselected, 0 failed |
| `bash scripts/check-governance-locks.sh` | OK — 18 verrous conformes au baseline |
| `bash scripts/tests/test-governance-locks.sh` | OK — 16 passed, 0 failed |
| `git diff --check` | OK — aucune erreur d'espacement |
| E2E Playwright (`scripts/e2e/run-lot27-p3-ui-readonly.sh`) | Non exécuté — Playwright non installé dans le worktree. Le script vérifie Dashboard, Recherche, Ingestion, Administration en read-only. À exécuter quand un noeud Playwright est disponible. |
| E2E PR #56 (`scripts/e2e/run-rag-v2-prod-readonly.sh`) | Non présent sur cette branche (fait partie de PR #56). |

## Décision de validation

Tous les contrôles de qualité passent. Le lint, le typecheck, les 479 tests
unitaires, les garde-fous de gouvernance et les vérifications de diff sont
verts. Les E2E Playwright sont préparés mais non exécutés faute de runtime
Playwright local.
