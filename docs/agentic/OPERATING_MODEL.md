# Modèle opératoire agentique — Nexus RAG

Commun à tous les agents (Claude Code, Codex, autres). Les règles impératives sont dans
`AGENTS.md` ; ce document explique le « comment » et le « pourquoi ».

## 1. Trois catégories de faits

| Catégorie | Contenu | Durée de validité | Lecture |
|---|---|---|---|
| STATIC | architecture, invariants, procédures | jusqu'au prochain commit qui les change | dépôt |
| SEALED | manifestes, SHA, ADR, releases, autorisations | immuable une fois fusionné | `git show`, `sha256sum` |
| LIVE | `main`, PR, CI, serveur, base, conteneurs, jobs | minutes | source, au moment de décider |

Un fait LIVE rapporté porte son heure de lecture. Les README, rapports, instantanés
JSON, résumés de session et mémoires d'agent ne sont jamais une source LIVE.

## 2. Cycle d'un lot de code

```
/project-status → /start-lot → investigation → implémentation → tests ciblés
  → /qualify-lot → /review-pr → revue humaine → fusion humaine → vérification post-fusion
```

- Un lot = un worktree = une branche = une PR = un rapport `docs/reports/lot_<id>_<slug>.md`.
- Vérification post-fusion : CI `push` du SHA fusionné sur `main`, relue sur GitHub.

## 3. Cycle d'un lot go-live

```
/project-status → /go-live-preflight → plan / autorité / provenance → PORTE HUMAINE
  → /staging-operation → vérification indépendante → readiness
  → AUTORISATION PRODUCTION → /production-deploy
```

- Chaque flèche vers une opération live est une porte humaine explicite, pour une
  opération précise. Une autorisation ne se reporte pas sur l'opération suivante.
- Une autorisation ou attestation s'enregistre pendant que sa PR approuvée est ouverte,
  puis on fusionne.
- `GO_LIVE_READY` : `docs/agentic/GO_LIVE_DEFINITION_OF_DONE.md`.

## 4. Défense en profondeur

| Couche | Rôle | Limite |
|---|---|---|
| `AGENTS.md`, `CLAUDE.md`, rules | orienter le comportement | contexte, pas contrainte |
| Permissions (`.claude/settings.json`) | `deny` secrets, `ask` mutations externes | une commande reformulée peut échapper à un motif |
| Hook `pretool-guard.sh` | analyse chaque commande : `deny`/`ask` | heuristique ; échoue fermé sur erreur, interpréteur absent ou lenteur, pas si le script manque ou si Claude Code coupe le hook |
| CI (gardes de gouvernance, tests de refus) | non-régression mécanique | ne voit pas le live |
| Revue humaine sur head exact | autorité de fusion et d'activation | — |

Aucune couche ne suffit seule ; aucune ne se contourne. Aucune n'est une isolation du
système : ce dépôt n'installe pas de sandbox OS.

## 5. Sous-agents

Utiles quand les pistes sont indépendantes, que le contexte isolé évite de polluer le
parent, ou qu'une investigation large se parallélise. Inutiles pour lire quelques
fichiers, une modification locale, ou revérifier le parent. Les experts du dépôt sont en
lecture seule ; le parent intègre et répond de l'ensemble.

## 6. Agent Teams

Expérimentales, **désactivées par défaut** dans ce dépôt. Envisageables uniquement pour
une investigation massive et parallèle sans mutation (audit de tout le corpus, revue
croisée de nombreuses PR), activées par l'opérateur pour une session
(`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` dans son shell), jamais pour une opération live.

## 7. Session « opérateur sensible »

Pour une opération staging/production qui manipule des sorties sensibles :

- worktree dédié, propre, sur le SHA préflighté ;
- mode de permission `default` (pas `auto`), afin que chaque commande à effet soit vue ;
- ne jamais afficher de valeur de secret : vérifier la présence (`test -f`, `test -n`),
  jamais le contenu ;
- les transcripts Claude Code sont conservés localement (`~/.claude/projects/`) :
  pour une exécution non interactive, `claude -p --no-session-persistence` ; sinon,
  purger le transcript de la session après archivage du journal d'opération ;
- journal d'opération dans le rapport de lot, sans secret ni DSN complet.

## 8. Mémoire et contexte

- La mémoire automatique garde habitudes de travail, commandes utiles et pièges connus.
  Elle n'est jamais l'autorité pour un HEAD, une PR, une CI, un SHA, une release active,
  une autorisation ou un état serveur.
- Le contexte permanent reste minimal : `CLAUDE.md` + `AGENTS.md`. Les rules se chargent
  avec les fichiers de leur chemin, les skills à l'invocation, les runbooks à l'usage.

## 9. Amélioration continue

Après plusieurs sessions réelles, `/insights` (et `/fewer-permission-prompts`) signalent
prompts répétés, permissions redemandées, erreurs récurrentes. Les propositions passent
par une PR de configuration ; aucune permission n'est élargie automatiquement.
