---
name: start-lot
description: Démarre un lot Nexus RAG proprement — worktree dédié et branche créés depuis origin/main fraîchement relu, périmètre et critères d'arrêt écrits avant le code. À utiliser avant toute modification de code, de configuration ou de gouvernance.
argument-hint: "<slug-de-branche> [objectif]"
---

# /start-lot — un lot = un worktree = une branche = une PR = un rapport

## Préconditions

- Ne jamais réutiliser le worktree ou la branche d'un autre lot actif (`git worktree list`).
- Aucune modification dans le répertoire partagé si sa branche appartient à un autre lot.

## Inputs

`$ARGUMENTS` : nom de branche (`<type>/<slug>`, ex. `go-live/…`, `fix/…`, `chore/…`) et objectif.

## Workflow

1. `git fetch origin --prune` ; noter `origin/main` (SHA complet). Si l'utilisateur cite un
   SHA de base plus ancien, partir quand même du `main` courant et le signaler.
2. Vérifier que la branche n'existe ni localement ni sur `origin` (`git ls-remote --heads origin <branche>`).
3. `git worktree add -b <branche> .worktrees/<slug> origin/main`, puis
   `git -C .worktrees/<slug> branch --unset-upstream` (la branche ne doit pas suivre `main`).
4. Travailler depuis ce worktree uniquement (EnterWorktree ou `cd` du shell).
5. Écrire le cadrage avant le code, dans le rapport `docs/reports/lot_<id>_<slug>.md` :
   objectif, périmètre (fichiers/services), hors-périmètre, critères d'arrêt, tests prévus,
   verrous et PR à ne pas toucher.
6. Si le lot touche une migration : `/postgres-migration` ; une opération live : `/go-live-preflight`.
7. Venv : `make install` dans le service, venv propre au worktree.

## Arrêt

Worktree créé, cadrage écrit, rien d'autre. Faire valider le cadrage si le périmètre est ambigu.

## Sortie

Chemin du worktree, branche, SHA de base, chemin du rapport, périmètre en 3–5 lignes.
