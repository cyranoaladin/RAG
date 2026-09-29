# Lot 2026-09-29 — Modèle opératoire agentique et configuration Claude Code

Branche `chore/claude-agentic-operating-model`, worktree dédié, créée depuis `origin/main`
= `2bc65c9386aafb80d66ce25096b50c75eeeb5412` (lu le 29/09/2026). Aucun code métier, aucun
schéma, aucune opération staging ou serveur, aucune PR existante touchée (#262, #270, #271
lus seulement).

## 1. Audit de l'installation (machine locale, 29/09/2026)

- Claude Code **2.1.284** (natif, `claude doctor` : aucun problème). Modèle de session :
  `claude-opus-5-5`.
- Capacités confirmées dans le binaire installé et la documentation officielle :
  `.claude/rules/` avec `paths:`, skills avec `disable-model-invocation`, agents avec
  `tools`/`disallowedTools`/`memory`, hooks SessionStart/PreToolUse/PostToolUse/Stop,
  `permissions.disableBypassPermissionsMode`, `.worktreeinclude`,
  `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`, `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`,
  `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`, `/insights`, `/fewer-permission-prompts`.
- Faits de la documentation qui ont orienté la conception :
  - un hook qui sort avec un code ≠ 0 et ≠ 2, expire ou manque **laisse passer l'action** ;
  - `deny` puis `ask` puis `allow`, toutes portées confondues : un `ask` projet l'emporte sur
    un `allow` local, même en mode auto ;
  - avec un `CLAUDE.md` racine, les `AGENTS.md` des sous-répertoires **ne sont pas lus**.

Configuration utilisateur (`~/.claude/`, non modifiée) : `defaultMode: auto` ; 13 skills
Superpowers désactivés ; un hook PostToolUse `nexus-s5-tests.sh` inerte hors d'un autre dépôt
(pas de double exécution) ; ni `rules/` ni `agents/` utilisateur ; aucun plugin actif.
`.claude/settings.local.json` du dépôt principal (non versionné) autorise `Bash(gh pr *)` et
`Bash(ssh -o BatchMode=yes nexus-prod-direct *)` sans confirmation.

## 2. Audit du dépôt — constats

| # | Constat | Traitement |
|---|---|---|
| A1 | `CLAUDE.md` = `@AGENTS.md` seul ; aucune configuration Claude versionnée | adaptateur + `.claude/` |
| A2 | Les `AGENTS.md` de service étaient invisibles pour Claude Code | `services/*/CLAUDE.md` = `@AGENTS.md` |
| A3 | `AGENTS.md` : « tant que GitHub Actions est indisponible » est périmé ; pas de règle état scellé/live, preuves, go-live, opérations live | mis à jour, invariants ajoutés |
| A4 | Garde-fous absolus reposant sur le seul prompt ; `allow` local couvrant `gh pr merge` et SSH production | hook `pretool-guard.py` + règles `ask`/`deny` |
| A5 | `.claude/worktrees/` et `settings.local.json` non ignorés (`.claude/` non suivi dans le dépôt principal) | `.gitignore` |
| A6 | `docs/ROADMAP.md` : phases 2025 obsolètes, sans gates vers la production | gates G0–G10, historique en annexe |
| A7 | Pas de définition écrite de `GO_LIVE_READY` distincte de la CI | `docs/agentic/GO_LIVE_DEFINITION_OF_DONE.md` |
| A8 | `services/rag-pedago/AGENTS.md` : consignes historiques contradictoires (« ne jamais connecter PostgreSQL » alors que le service l'utilise ; rapports `data/reports/codex_lot_*`) | **non modifié** : contenu épinglé par `tests/unit/test_project_contracts.py` ; clause de précédence ajoutée à la racine ; à traiter dans un lot dédié |
| A9 | `services/rag-engine/AGENTS.md` : « bascule planifiée au Lot 1.2 » périmé | non modifié (épinglé par `test_v2_runtime_surface.py`) ; lot dédié |
| A10 | `docs/runbooks/rollback.md`, `rag_incident_response.md` décrivent l'ancienne pile (`/opt/rag-local`, build sur serveur, ollama) | signalé (G10), non réécrit faute de source sur la topologie production actuelle |
| A11 | README : `nexus-contracts` v0.21.0, `pyproject.toml` en 0.22.0 | signalé |
| A12 | Conventions de migration connues seulement par l'expérience | `.claude/rules/postgres-migrations.md`, vérifiées contre `sql_transaction_control.sh` |

## 3. Matrice des fichiers

| Fichier | Action | Problème résolu |
|---|---|---|
| `AGENTS.md` | MODIFIER | A3 ; invariants cross-agent (faits, preuves, go-live, worktrees, accès externe) |
| `CLAUDE.md` | MODIFIER | A1 ; adaptateur de 79 lignes |
| `services/{rag-engine,rag-pedago,cockpit}/CLAUDE.md` | CRÉER | A2 |
| `services/*/AGENTS.md` | GARDER | épinglés par des tests ; A8/A9 en lot dédié |
| `.claude/settings.json` | CRÉER | permissions, hooks, limites de sous-agents, bypass désactivé |
| `.claude/rules/*.md` (5) | CRÉER | règles chargées par chemin (A12) |
| `.claude/skills/*/SKILL.md` (9) | CRÉER | workflows répétés ; 3 manuels |
| `.claude/agents/*.md` (4) | CRÉER | experts en lecture seule |
| `scripts/claude/*` (4) | CRÉER | hooks déterministes (A4) |
| `scripts/tests/test_claude_config.py` | CRÉER | qualification de la configuration (76 épreuves) |
| `.gitignore` | MODIFIER | A5 |
| `docs/ROADMAP.md` | MODIFIER | A6 |
| `docs/agentic/*.md` (4) | CRÉER | modèle opératoire, DoD go-live, accès externe, carte de configuration |
| `.mcp.json` | NE PAS CRÉER | aucun besoin ; `gh` suffit |
| `.worktreeinclude` | NE PAS CRÉER | le seul candidat (`settings.local.json`) contient un accès SSH production |
| `RULES.md`, `SKILLS.md` | NE PAS CRÉER | non lus par Claude Code |
| Agents `architect`, `security-reviewer`, `test-strategist`, `release-auditor` | NE PAS CRÉER | doublons de `Plan`, `/security-review`, `/qualify-lot`, `go-live-auditor` |
| Skills `release-provenance`, `rag-evaluation` | NE PAS CRÉER | couverts par `/go-live-preflight` et `retrieval-evaluator` |

## 4. Qualification (exécutée dans ce worktree)

| Contrôle | Commande | Résultat |
|---|---|---|
| Configuration Claude | `python3 -m pytest -q scripts/tests/test_claude_config.py` | 76 passed |
| Suite `scripts/tests` (job CI `script-tests`, Python 3.12 local) | `python -m pytest -q scripts/tests/` | 627 passed, 17 skipped, 4 failed — **préexistants** (voir ci-dessous) |
| Schéma des réglages | validation `jsonschema` contre `json.schemastore.org/claude-code-settings.json` | VALID |
| Installation | `claude doctor` dans le worktree | aucun problème |
| Session réelle | `claude -p` (Sonnet, budget 0,60 $, sans persistance) | SessionStart injecté ; 4 agents et 9 skills chargés, 6 visibles du modèle (les 3 manuels masqués) ; `git push --force` refusé par le garde |
| Hygiène | `bash scripts/check-repository-hygiene.sh` | PASS |
| Verrous | `bash scripts/check-governance-locks.sh` | 18/18 conformes |
| Unicité d'autorité | `bash scripts/check-authority-uniqueness.sh` (après indexation) | PASS |
| Lint | `ruff check` sur les deux fichiers Python ajoutés ; `bash -n` sur les hooks | OK |

Les 4 échecs de `test_go_live_readiness.py` (`disk_policy_ok`) viennent de l'état de la
machine : 20 Go libres pour 40 Go exigés. Reproduits à l'identique sur le parent
`2bc65c93` (4 failed, 94 passed). Aucun rapport avec ce lot.

Non exécutés : CI locale complète `scripts/ci-local.sh` (disque insuffisant, et aucun
service modifié) ; suites des services (aucun code de service modifié ; les tests qui
épinglent les `AGENTS.md` de service portent sur des fichiers inchangés).

Avant indexation, ce contrôle refuse de conclure (`UNTRACKED_CODE_FILES_INVISIBLE 5`) : c'est
son comportement voulu, pas un échec du lot.

## 5. Risques résiduels

- Le garde est heuristique : une commande reformulée (script intermédiaire, interpréteur)
  peut échapper à l'analyse. Il complète les permissions et la revue humaine, il ne les remplace pas.
- `git push` passe désormais en `ask` : une confirmation par push, voulue (mutation externe).
- Si `python3` ou `jq` manquent, les hooks sont inopérants (échec ouvert documenté par
  Claude Code) ; le test de configuration le détecte en CI.
- `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS=3` s'applique aussi aux sessions qui orchestrent
  des workflows multi-agents ; l'opérateur peut le relever pour une session.
- Faux positifs possibles du garde (ex. un segment de commande commençant par `ssh` dans un
  texte) : ils demandent confirmation, jamais un refus silencieux.

## 6. Recommandations personnelles `~/.claude` — NON appliquées

1. Retirer de `.claude/settings.local.json` (dépôt principal) `Bash(gh pr *)` et
   `Bash(ssh -o BatchMode=yes nexus-prod-direct *)` : les règles `ask` du projet les
   neutralisent déjà, mais un `allow` production ne devrait pas exister.
2. `~/.claude/CLAUDE.md` impose « TDD strict » et une validation utilisateur à chaque étape :
   à confronter au modèle opératoire (autonomie jusqu'au vrai point d'arrêt).
3. `autoMode.environment` décrit un autre dépôt comme dépôt de confiance : à compléter pour
   `cyranoaladin/RAG` et les hôtes `nexus-*` (cibles sensibles).
4. Supprimer les sauvegardes `settings.json.avant-*` si elles n'ont plus d'usage.
5. Envisager `cleanupPeriodDays` plus court si des sessions d'opération sont conduites
   localement.

## 7. Prochaines étapes

1. Lot dédié : actualiser `services/rag-pedago/AGENTS.md` et `services/rag-engine/AGENTS.md`
   (A8, A9) avec leurs tests épinglés.
2. Lot G10 : réécrire `rollback.md` et `rag_incident_response.md` pour la pile v2 par digest,
   à partir d'une lecture autorisée de la production.
3. Libérer au moins 20 Go (sans élaguer Docker sans accord) pour rendre la CI locale et
   `disk_policy_ok` exploitables.
4. Après quelques sessions : `/insights` et `/fewer-permission-prompts`, ajustements par PR.
5. Trajectoire go-live : gates G0 → G5 de `docs/ROADMAP.md`.
