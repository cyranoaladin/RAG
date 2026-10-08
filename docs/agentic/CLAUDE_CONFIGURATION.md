# Configuration Claude Code du dépôt

Vérifiée contre Claude Code 2.1.284 et la documentation officielle
(<https://code.claude.com/docs/>). Tests : `python3 -m pytest -q scripts/tests/test_claude_config.py`.

## Quel fichier pour quel besoin

| Besoin | Fichier | Chargement |
|---|---|---|
| Règle valable pour tous les agents | `AGENTS.md` | chaque session (importé par `CLAUDE.md`) |
| Façon dont Claude Code applique ces règles | `CLAUDE.md` | chaque session |
| Règles d'un service | `services/<svc>/AGENTS.md` (importé par `services/<svc>/CLAUDE.md`) | quand Claude lit un fichier du service |
| Règle liée à des chemins | `.claude/rules/<sujet>.md` avec `paths:` | quand Claude lit un fichier correspondant |
| Procédure répétable | `.claude/skills/<nom>/SKILL.md` | à l'invocation `/<nom>` (ou par Claude si autorisé) |
| Expert à contexte isolé | `.claude/agents/<nom>.md` | quand le parent délègue |
| Permissions, hooks, variables sûres | `.claude/settings.json` | chaque session |
| Logique des hooks | `scripts/claude/*` | à chaque événement |
| Préférences personnelles | `.claude/settings.local.json`, `CLAUDE.local.md` (ignorés par Git) | chaque session, pour vous seul |

Pas de `RULES.md` ni `SKILLS.md` à la racine : Claude Code ne les lit pas.
Pas de `.mcp.json` ni de `.worktreeinclude` : aucun besoin actuel (voir plus bas).

## Inventaire

- Rules : `postgres-migrations`, `go-live-operations`, `governance-artifacts`, `contracts`, `testing`.
- Skills : `/project-status`, `/start-lot`, `/qualify-lot`, `/review-pr`, `/postgres-migration`,
  `/go-live-preflight` ; manuels uniquement (`disable-model-invocation: true`) :
  `/staging-operation`, `/production-deploy`, `/incident-response`.
- Agents (lecture seule, `Write`/`Edit`/`Agent` retirés) : `postgres-reviewer`,
  `governance-auditor`, `go-live-auditor`, `retrieval-evaluator`. Pour l'architecture, utiliser
  l'agent intégré `Plan` ; pour la sécurité, `/security-review`.
- Hooks :

| Événement | Script | Effet |
|---|---|---|
| SessionStart | `session-context.sh` | worktree, branche, HEAD, `origin/main` du dernier fetch (daté), PR de la branche |
| PreToolUse | `pretool-guard.sh` → `pretool-guard.py` | `deny` : écriture sur `main`, push forcé ou vers `main`, lecture de secret (chemin, motif, lien, lecture récursive, redirection), auto-approbation, affichage de jeton ; `ask` : SSH/scp/rsync, psql distant, `sudo`, mutations `gh` (options héritées `-R/--repo` comprises), push, `reset --hard`, `clean -f`, `rm -r` hors worktree ou sur motif, bascule `current`, Docker distant/prune, et toute commande que le garde ne sait pas classer |
| PostToolUse (Write/Edit) | `post-edit-check.sh` | `git diff --check`, syntaxe Python/Bash/JSON/YAML, ruff (erreurs fatales), chemin absolu ajouté — quelques secondes, jamais de suite de tests |
| Stop | `stop-check.sh` | espaces fautifs, secret probable dans un fichier modifié, fichier non suivi suspect |

- Variables : `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1` (pas de sous-agent imbriqué),
  `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS=3`.
- Mode de permissions : le dépôt n'impose aucun `defaultMode` et n'interdit plus `bypassPermissions`,
  choisi explicitement par le propriétaire au lancement (`--permission-mode bypassPermissions`).
  Ce choix ne s'applique qu'à la session qui le demande. En bypass, les confirmations `ask` ne sont
  plus présentées à l'opérateur ; l'effet exact sur les décisions des hooks n'est pas qualifié ici.
  Le mode ne vaut autorisation d'aucune fusion, suppression de données ni opération serveur.
- Les `allow` de `.claude/settings.json` ne s'appliquent qu'après acceptation interactive de la
  confiance du dossier (jamais en `claude -p`) ; `deny`, `ask` et les hooks s'appliquent toujours.

## Deux couches de protection, et leurs limites

Les règles natives (`deny`/`ask`) et le garde PreToolUse sont indépendants. Ni l'une ni
l'autre n'est une frontière de sécurité : aucune isolation OS (sandbox) n'est installée par
ce dépôt, et un programme qui ouvre lui-même des fichiers (script Python, Node…) échappe
aux deux.

| Couche | Ce qu'elle voit | Ce qu'elle ne voit pas (mesuré) |
|---|---|---|
| Règles natives | texte de la commande après retrait des préfixes `timeout`, `nice`, `nohup`, `command`… ; fichiers nommés par `cat`, `head`, `tail`, `sed` ; outils Read/Edit/Write (liens résolus) | `sudo` et options de `gh` placées avant la sous-commande sans règle dédiée ; lecture récursive (`grep -r`) ; tout ce qui n'est pas écrit en clair |
| Garde (`pretool-guard.sh`) | préfixes et leurs options, options héritées de `gh`, motifs développés en Python, liens, arbres parcourus pour `grep -r`/`find -exec`, substitutions `$(…)`, heredocs vers un shell, composition | programmes qui lisent sans nommer (scripts), alias shell, commandes construites dynamiquement hors `eval` (reçoivent `ask`) |

Comportement réel en panne (Claude Code 2.1.284, mesuré par
`scripts/tests/claude_permissions_integration.py`) :

| Panne | Effet | Défense restante |
|---|---|---|
| Exception dans le garde Python | `deny` | — |
| Interpréteur Python absent | `deny` (enveloppe `sh`) | — |
| Garde plus lent que 10 s | `deny` (enveloppe, avant le délai de 15 s de Claude Code) | — |
| Délai du hook dépassé côté Claude Code | l'action **passe** | règles natives |
| Script du hook absent (mesuré) ; `/bin/sh` indisponible (non mesuré, même mécanisme) | l'action **passe** | règles natives |

Les règles natives du dépôt arrêtent seules sudo, `gh` avec `-R`, les motifs `.env*`,
les graines `*.seed.hex` et les liens vers un secret ; `grep -r` sur un arbre qui contient un
secret n'est arrêté que par le garde.

Qualifier après chaque changement de `settings.json` ou du garde (quelques centimes, bac à
sable jetable, exécutables factices, cibles `.invalid`) :

```
python3 scripts/tests/claude_permissions_integration.py --model sonnet --out rapport.json
```

Les hooks utilisateur (`~/.claude/settings.json`) s'ajoutent à ceux du projet. Au
29/09/2026, le seul hook utilisateur (`nexus-s5-tests.sh`) est inerte hors d'un autre dépôt :
pas de double exécution.

## Utilisation quotidienne

```
claude -w <slug>          # ou /start-lot dans une session ouverte
/project-status           # état live
… travail …
/qualify-lot              # preuves
/review-pr                # une passe, avant la revue humaine
/context  /compact        # si le contexte s'alourdit
```

Commandes intégrées utiles : `/status`, `/model`, `/effort`, `/context`, `/compact`, `/plan`,
`/diff`, `/agents`, `/skills`, `/hooks`, `/permissions`, `/code-review`, `/security-review`,
`/insights`, `/fewer-permission-prompts`, `/doctor`.

## Sous-agents : quand et quand pas

- Oui : revue d'une migration volumineuse (`postgres-reviewer`), audit d'une chaîne
  d'autorisations (`governance-auditor`), contre-vérification indépendante d'une release ou
  d'une readiness (`go-live-auditor`), analyse de nombreux résultats de sonde
  (`retrieval-evaluator`), exploration large du dépôt (`Explore`).
- Non : lire trois fichiers, corriger une fonction, « revérifier » ce que le parent vient de
  faire, enchaîner plusieurs reviewers par réflexe.

## Opération sensible

`/go-live-preflight` → autorisation humaine → `/staging-operation` ou `/production-deploy`
tapé par l'humain. Session en mode `default`, voir `docs/agentic/OPERATING_MODEL.md` §7.
Toute commande SSH, psql distante ou bascule `current` déclenche une confirmation.

## Déboguer les hooks

- `/hooks` liste les hooks chargés ; `claude --debug hooks` trace leurs exécutions.
- Rejouer un hook à la main :
  `echo '{"tool_name":"Bash","tool_input":{"command":"git push -f"},"cwd":"'$PWD'"}' | scripts/claude/pretool-guard.sh`
- Un hook qui sort avec un code autre que 0 ou 2, qui expire ou qui manque **laisse passer
  l'action** : voir le tableau des pannes ci-dessus. `jq` est requis par les hooks
  d'information (SessionStart, PostToolUse, Stop) ; `scripts/tests/test_claude_config.py`
  vérifie sa présence.
- Faux positif du garde : corriger le motif dans `pretool-guard.py` et ajouter un cas au
  test, par PR. Ne pas contourner par une autre forme de commande.
- Désactiver ponctuellement tous les hooks (diagnostic seulement, jamais en opération) :
  `claude --settings '{"disableAllHooks": true}'`.

## `.worktreeinclude` et MCP

`.worktreeinclude` copierait des fichiers ignorés dans chaque nouveau worktree. Le seul
candidat, `.claude/settings.local.json`, contient des autorisations personnelles (dont un
accès SSH à la production) : il ne doit pas se propager. Aucun fichier n'est donc listé ; si
un jour un fichier est ajouté, jamais `.env`, clé, `*.pem`, seed, token, credentials, dump ni
sauvegarde (le test de configuration le refuse).

MCP : aucun serveur projet ; `gh` suffit pour GitHub. L'exposition MCP du retrieval est un
objectif produit : `docs/agentic/EXTERNAL_AGENT_ACCESS.md`.
