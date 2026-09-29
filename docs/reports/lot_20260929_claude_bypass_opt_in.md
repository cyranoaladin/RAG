# Lot configuration — bypass au choix explicite du propriétaire

Base : `main` = `95e8aabb9bba1b52b6542ae533ab3432a4532c09`. Décision de
l'opérateur (propriétaire du dépôt), 29/09/2026 : pouvoir lancer ses sessions
Nexus RAG en `bypassPermissions`.

## Changements

- `.claude/settings.json` : suppression de
  `permissions.disableBypassPermissionsMode: "disable"` — modification faite
  **par l'opérateur hors de Claude Code** (le classifieur du mode auto avait
  refusé que l'agent la réalise). Aucune autre clé modifiée : 26 `allow`,
  41 `ask`, 25 `deny`, hooks SessionStart / PreToolUse / PostToolUse / Stop
  inchangés ; aucun `defaultMode`.
- `scripts/tests/test_claude_config.py` : le test qui exigeait le verrou
  devient `test_settings_laisse_le_choix_du_mode_sans_l_imposer` — verrou
  absent, aucun `defaultMode` sans garde (`bypassPermissions`, `dontAsk`,
  `auto`), aucune mention de `bypassPermissions` dans le fichier, hooks non
  désactivés, `deny` et `ask` non vides. Hooks et skills manuels restent
  vérifiés par les tests existants.
- `docs/agentic/CLAUDE_CONFIGURATION.md` : le passage « le mode sans garde est
  refusé » est remplacé par le nouveau contrat. Le rapport #272
  (`lot_20260929_claude_agentic_operating_model.md`) reste un document daté.

## Qualification

`python3 -m pytest -q scripts/tests/test_claude_config.py` : 150 réussis ;
`git diff --check` propre ; verrous de gouvernance : 18 clés conformes.

## Limites

- Le bypass se choisit au lancement, pour la seule session concernée ; rien
  n'est modifié dans `~/.claude`, `settings.local.json` ni aucune politique
  administrée.
- En bypass, les confirmations `ask` ne sont plus présentées ; l'effet exact
  sur les décisions des hooks PreToolUse n'est pas qualifié. L'exécution
  effective du garde dans une session reste non prouvée (canari du
  29/09 : exécuté sans confirmation, session alors en mode auto).
- Le mode ne vaut autorisation d'aucune fusion, approbation, migration réelle,
  opération serveur ni suppression de données.
