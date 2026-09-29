@AGENTS.md

# Claude Code — adaptateur

`AGENTS.md` (ci-dessus) est le contrat commun à tous les agents. Ce qui suit ne
concerne que la façon dont Claude Code l'applique. Carte de la configuration :
`docs/agentic/CLAUDE_CONFIGURATION.md`.

## Avant d'agir

- Investiguer avant d'affirmer : ouvrir les fichiers concernés, lancer la commande, lire la sortie.
  Ne jamais raisonner sur un fichier non lu ni deviner un résultat qu'un outil peut donner.
- Avant toute modification : `git branch --show-current`, `git worktree list`, état propre ou non.
  Jamais de modification sur `main` ; jamais d'écriture dans le worktree d'un autre lot actif.
  Un nouveau lot commence par `/start-lot` (worktree + branche depuis `origin/main` fraîchement relu).
- La pile `git stash` est partagée entre worktrees : jamais de `git stash`/`pop` nus.

## Sources de vérité

Distinguer et nommer, dans chaque rapport :

| Catégorie | Exemples | Comment la lire |
|---|---|---|
| Git scellé | commit, manifeste, SHA, ADR | `git show`, `sha256sum` — citer le SHA |
| Machine locale | worktrees, venvs, Docker local, journaux opérateur | commande locale, datée |
| GitHub live | PR, revues, CI, protection | `gh` au moment de la décision |
| Serveur live | staging, production, base, conteneurs, jobs | uniquement après autorisation, via le runbook |

- L'état live se relit toujours ; un README, un rapport, un résumé de session ou la
  mémoire automatique n'en sont jamais la source. La mémoire peut garder des habitudes
  de travail, jamais un HEAD, un état de PR, de CI, de release ou de serveur.
- Le hook SessionStart donne un point de départ (branche, HEAD, dernier fetch) ; il ne
  remplace pas un `git fetch` avant décision.

## Périmètre et arrêt

- Limiter le changement au périmètre demandé ; pas de refactor opportuniste, pas de
  fichier « pour plus tard ». Un besoin métier découvert hors périmètre se consigne dans
  le rapport de lot comme prochaine tâche.
- Poursuivre jusqu'au vrai point d'arrêt : livrable fait et vérifié, ou blocage réel
  documenté (cause, preuve, décision attendue et de qui).
- S'arrêter avant toute action irréversible ou non autorisée : fusion, fermeture de PR,
  push forcé, SSH, migration, publication, bascule `current`, suppression hors worktree.
  Les hooks `scripts/claude/` imposent un refus ou une confirmation ; ne jamais les
  contourner (autre forme de commande, script intermédiaire).
- Une autorisation humaine vaut pour une opération précise, pas pour la suivante.

## Preuves

- Un test n'est « passé » que s'il a été exécuté dans cette session sur ce code : citer la
  commande, le compteur et le SHA. Un test non lancé se déclare « non exécuté ».
- Un test synthétique, une fixture ou un mock ne prouvent pas le scénario réel : le dire.
- `CI verte ≠ GO_LIVE_READY` : voir `docs/agentic/GO_LIVE_DEFINITION_OF_DONE.md`.
- Les suites d'intégration Docker ne tournent jamais en parallèle (ports partagés) ;
  avant d'imputer un rouge go-live à un lot, vérifier `df -h` (40 Go libres requis).

## Délégation

Opus travaille longtemps et délègue bien ; ne pas sur-déléguer.

- Sous-agent seulement si : pistes réellement indépendantes, contexte isolé utile
  (grosse lecture dont seule la conclusion compte), ou investigation large parallélisable.
- Jamais pour : lire quelques fichiers, une modification locale, revérifier
  mécaniquement le travail du parent.
- Les experts de `.claude/agents/` sont en lecture seule et rapportent au parent, qui
  reste responsable de l'intégration. Profondeur 1, trois au plus en parallèle
  (`.claude/settings.json`). Les Agent Teams restent désactivées par défaut.
- Pas de relecture systématique par plusieurs reviewers après chaque changement :
  `/review-pr` une fois, avant la revue humaine.

## Flux de travail

- Lot de code : `/project-status` → `/start-lot` → investigation → implémentation →
  tests ciblés → `/qualify-lot` → `/review-pr` → revue humaine → fusion humaine.
- Lot go-live : `/project-status` → `/go-live-preflight` → porte humaine →
  `/staging-operation` (manuel) → vérification indépendante → readiness →
  autorisation production → `/production-deploy` (manuel).
- Incident : `/incident-response` (manuel).
- Les runbooks (`docs/runbooks/`) se lisent au moment de l'opération, pas en début de session.
