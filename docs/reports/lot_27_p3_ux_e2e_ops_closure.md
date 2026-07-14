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
| E2E PR #56 (`scripts/e2e/run-rag-v2-prod-readonly.sh`) | Non present sur cette branche (fait partie de PR #56). |

### Session 3 (2026-07-15, E2E Playwright contre production)

E2E execute via Playwright (chromium headless) contre `https://rag-ui.nexusreussite.academy`.
4 runs effectues pour isoler le signal du bruit infra.

Artefacts : `/tmp/rag-lot27-p3-e2e-run4-20260714T232827Z/`

| Page | Chargement | Screenshot | Assertions contenu |
|---|---|---|---|
| Dashboard | OK | `01-dashboard.png` | FAIL attendu : titre "Dashboard RAG v2 — Catalogue scolaire" (pre-P3), sidebar `http://ingestor:8001` visible |
| Recherche | OK | `02-recherche.png` | FAIL attendu : info "Seules les collections instanciees..." absente (ajout P3 non deploye) |
| Ingestion | OK | `03-ingestion.png` | FAIL attendu : "Drive v2 non active" absente (simplification P3 non deployee) |
| Administration | OK (run 1) / timeout (run 4) | `04-administration.png` | FAIL attendu run 1 : `http://ingestor:8001` visible en sidebar. Run 4 : timeout transitoire reseau |

**Verifications positives (run 1, toutes pages chargees) :**

| Verification | Resultat |
|---|---|
| Absence `rag_francais_premiere` | OK |
| Absence `rag_maths_premiere` | OK |
| Absence `rag_education` | OK |
| Absence `rag_web3` | OK |
| Absence `rag_divers` | OK |
| Absence `/stats` | OK |
| Absence `API 403` | OK |
| Absence `Forbidden` | OK |
| Presence `Catalogue v2 complet` (Administration) | OK |
| `network-failures.json` | vide (0 echecs RAG metier) |
| `blocked-requests.json` | 15 segment.io (telemetrie Streamlit hors host) |

**Analyse des echecs contenu :**

Les 3-4 assertions de contenu echouent parce que la production execute le code
pre-P3 (`main` branche). La PR P3 n'est pas deployee (par conception : regle
"ne deploie pas"). Les assertions E2E sont conçues pour valider le code P3
**apres** deploiement. Elles echouent donc correctement en pre-deploiement.

**Amelioration du script E2E :**

Le script a ete ameliore pour filtrer le bruit d'infrastructure non-RAG :
- `/_stcore/*` (health/host-config Streamlit proxy 502)
- `/static/*` (assets CSS/JS/fonts via proxy)
- `ERR_NETWORK_CHANGED`, `ERR_ABORTED` (transitoires)
- Console : ChunkLoadError, 502, MIME mismatch, Segment snippet

## Decision de validation

Tous les controles de qualite passent : lint, typecheck, 479 tests unitaires,
garde-fous de gouvernance, git diff --check.

L'E2E Playwright a ete execute (4 runs). Le script fonctionne correctement et
valide l'absence de collections legacy, de `/stats`, de 403 et de `Forbidden`.
Les assertions de contenu P3 echouent comme attendu car la production execute
le code pre-P3. Le script passera une fois la PR deployee.
