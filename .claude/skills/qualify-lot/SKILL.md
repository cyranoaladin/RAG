---
name: qualify-lot
description: Qualifie un lot Nexus RAG avant revue — lint, typecheck, tests des services touchés, gardes de gouvernance, puis CI locale complète si demandé ; distingue régressions et échecs préexistants prouvés sur le commit parent. À utiliser quand l'implémentation est terminée, avant /review-pr.
argument-hint: "[full]"
---

# /qualify-lot — preuves d'exécution, pas d'affirmations

## Préconditions

- Worktree du lot, arbre propre ou changements identifiés ; `git diff --stat origin/main...HEAD` relu.
- `df -h .` : au moins 40 Go libres si la CI complète ou des suites Docker sont prévues.

## Workflow

1. Recenser les services touchés : `git diff --name-only origin/main...HEAD`.
2. Pour chaque service Python touché (`services/<svc>`) : `make lint`, `make typecheck`, `make test`.
   `services/cockpit` : `npm run lint`, `npm test -- --run`, `npm run build`.
3. Toujours : `bash scripts/check-governance-locks.sh`, `bash scripts/check-authority-uniqueness.sh`,
   `bash scripts/check-repository-hygiene.sh`, `python3 -m pytest -q scripts/tests/`.
4. Contrat touché : tests de `packages/contracts` + `export_schemas.py --check`.
5. Migration ou `ingestion_control` touché : suites d'intégration ciblées, une à la fois
   (`make test-integration*`, Docker requis).
6. `$ARGUMENTS` = `full`, ou lot transverse : `bash scripts/ci-local.sh` (long ; jamais deux
   exécutions concurrentes).
7. Tout rouge : reproduire sur le commit parent (worktree temporaire détaché) avant de le
   qualifier de préexistant ; sinon c'est une régression du lot, à corriger.
8. `git diff --check origin/main...HEAD`.

## Arrêt

Tout vert, ou rouges préexistants prouvés et tracés dans `docs/reports/*_dettes.md`.
Ne pas pousser ni ouvrir de PR dans ce skill.

## Sortie (à recopier dans le rapport de lot)

| Cible | Commande | Résultat (compteurs) | SHA | Statut |
|---|---|---|---|---|

Puis : non exécuté (et pourquoi), rouges préexistants avec preuve parent, régressions.
