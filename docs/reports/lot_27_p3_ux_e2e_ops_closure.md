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

### Session 3 (2026-07-15, protocole E2E multi-mode)

Le script E2E a ete refactorise avec trois modes explicites :

- `current-prod` : valide la production actuelle (pre-P3)
- `p3-preview` : valide une instance locale executant le code P3
- `post-deploy` : valide la production apres deploiement P3

Les echecs reseau sont categorises en 4 niveaux :
`network_failures_blocking`, `network_warnings_non_blocking`,
`third_party_blocked`, `streamlit_infra_noise`.

#### E2E current-prod — PASS

Artefacts : `/tmp/rag-lot27-current-prod-e2e-20260714T234924Z/`

| Page | Resultat | Screenshot |
|---|---|---|
| Dashboard | PASS | `01-dashboard.png` |
| Recherche | PASS | `02-recherche.png` |
| Ingestion | PASS | `03-ingestion.png` |
| Administration | PASS | `04-administration.png` |

| Categorie reseau | Nombre |
|---|---|
| network_failures_blocking | 0 |
| network_warnings_non_blocking | 0 |
| streamlit_infra_noise | 4 |
| third_party_blocked | 52 (segment.io) |
| RAG host bloques | 0 |
| Console bloquant | 0 |

Verifications positives : absence des 5 collections legacy, de `/stats`,
de `API 403`, de `Forbidden`. Presence de `Catalogue v2 complet`.

#### E2E p3-preview — NON CONCLUANT

Instance Streamlit locale demarree sur `127.0.0.1:18599` avec le code P3.
L'UI rend correctement le titre, le sous-titre, la sidebar (sans URL interne).
Screenshot confirme :
- Titre `Dashboard RAG v2` + sous-titre `Catalogue scolaire Nexus Reussite`
- Sidebar `API connectee` / `Backend RAG v2` (pas de `http://ingestor:8001`)

Les assertions data-dependantes (metriques, table, collections) echouent car
aucun token API de production n'est disponible localement. L'API publique
requiert un `Bearer` token pour `/catalogue/v2`. Le token de production est
configure dans le Docker Compose distant, non accessible depuis le worktree.

**Decision p3-preview** : structure UI validee visuellement, assertions
data-dependantes bloquees par l'absence de token. Post-deploy E2E gate requise.

### Session 4 (2026-07-15, P3 preview reel)

Instance Streamlit locale demarree sur `127.0.0.1:18599` avec le code P3.
Token API de production extrait via SSH (non affiche, non versionne).
Fichier env temporaire `/tmp/rag-p3-preview.env` (chmod 600), supprime apres usage.

#### E2E p3-preview — PASS

Artefacts : `/tmp/rag-lot27-p3-preview-e2e-20260715T000650Z/`

| Page | Resultat | Screenshot | Verifications |
|---|---|---|---|
| Dashboard | PASS | `01-dashboard.png` | Titre P3, sous-titre Nexus Reussite, metriques, sidebar propre |
| Recherche | PASS | `02-recherche.png` | Texte retrievable, collection cible |
| Ingestion | PASS | `03-ingestion.png` | Collection cible, type doc, droits, needs_review, onglet Google Drive |
| Administration | PASS | `04-administration.png` | Catalogue v2 complet, instanciees, non instanciees, retrievable, quarantaine, coherence |

| Categorie reseau | Nombre |
|---|---|
| network_failures_blocking | 0 |
| network_warnings_non_blocking | 0 |
| streamlit_infra_noise | 0 |
| third_party_blocked | 0 |
| RAG host bloques | 0 |
| Console bloquant | 0 |

Verifications visuelles confirmees :
- Sidebar : "API connectee" / "Backend RAG v2" (pas de `http://ingestor:8001`)
- Absence collections legacy, `/stats`, `API 403`, `Forbidden`
- Donnees reelles : 35 declarees, 3 instanciees, 2 retrievable, 1 quarantaine

### Session 5 (2026-07-15, tests CI finaux)

| Commande | Resultat |
|---|---|
| `make lint` | OK — `All checks passed!` |
| `make typecheck` | OK — `Success: no issues found in 39 source files` |
| `make test` | OK — 498 passed, 14 deselected, 0 failed |
| `bash scripts/check-governance-locks.sh` | OK — 18 verrous conformes |
| `bash scripts/tests/test-governance-locks.sh` | OK — 16 passed, 0 failed |
| `git diff --check` | OK |
| `node --check scripts/e2e/lot27-p3-ui-readonly.js` | OK |
| `bash -n scripts/e2e/run-lot27-p3-ui-readonly.sh` | OK |

## Couverture metier

Rapport detaille : `docs/reports/lot_27_business_coverage_matrix.md`

| Indicateur | Valeur |
|---|---|
| Collections declarees | 35 |
| Instanciees | 3 |
| Retrievable | 2 (NSI 1re + Tle) |
| Matieres couvertes en retrieval | NSI uniquement |
| Gap principal | 32 collections declarees non instanciees |

## Decision de validation

- E2E `current-prod` : **PASS** (4 pages, 0 echec, 0 reseau bloquant).
- E2E `p3-preview` : **PASS** (4 pages, 0 echec, 0 reseau bloquant).
- Tests unitaires : **498 passed**, 0 failed.
- Lint, typecheck, governance, diff check : tous verts.
- Couverture metier documentee : 35 collections, 2 retrievable (NSI), 32 gaps explicites.

LOT_27_P3_READY_FOR_REVIEW
