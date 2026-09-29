---
name: project-status
description: Relit l'état LIVE du projet Nexus RAG (main, PR ouvertes, CI, worktrees, lot courant) et le classe en scellé / local / live. À utiliser en début de session, avant de choisir ou reprendre un lot, ou quand l'utilisateur demande « où en est-on ».
allowed-tools: Bash(git fetch *) Bash(git log *) Bash(git worktree list *) Bash(git status *) Bash(git rev-parse *) Bash(gh pr list *) Bash(gh pr view *) Bash(gh pr checks *) Bash(gh run list *)
---

# /project-status — état live, lecture seule

Aucune mutation : ni commit, ni push, ni commentaire, ni opération serveur.

## Workflow

1. `git fetch origin --prune`, puis `git log -1 --format='%H %cI %s' origin/main`.
2. CI de `main` : `gh run list --branch main --limit 5 --json name,headSha,status,conclusion`.
   Ne retenir que les runs dont `headSha` = `origin/main`.
3. PR ouvertes : `gh pr list --state open --json number,title,isDraft,reviewDecision,mergeStateStatus,headRefName,headRefOid`.
4. Worktrees : `git worktree list` ; pour la session courante, branche, HEAD, avance/retard sur `origin/main`, fichiers modifiés.
5. Si l'utilisateur nomme des PR ou SHA « attendus », les comparer au live et signaler tout écart.
6. Readiness : ne PAS lire `go_live_readiness_state.json` comme état courant ; au besoin,
   `python3 scripts/go_live/check_go_live_readiness.py --verify-snapshot docs/reports/go_live/go_live_readiness_state.json`.

## Arrêt

Rapport produit. Ne pas enchaîner sur un lot sans instruction.

## Sortie

```
LIVE (lu à <heure>) : main=<sha12> CI main=<succès|échec|en cours|absente>
PR ouvertes : #n titre — draft/approved/behind — head=<sha12>
Worktree courant : <chemin> <branche>@<sha12> +<ahead>/-<behind> dirty=<n>
Écarts avec l'attendu : …
SCELLÉ pertinent : ADR/release/manifeste cités avec SHA
Non vérifié : serveur, base, jobs (hors périmètre de ce skill)
```
