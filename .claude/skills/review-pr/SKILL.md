---
name: review-pr
description: Prépare une PR Nexus RAG pour la revue humaine — vérifie périmètre, invariants AGENTS.md, gouvernance, preuves de tests et head exact ; rédige ou vérifie la description. Une passe, avant la revue humaine ; n'approuve et ne fusionne jamais.
argument-hint: "[numéro de PR]"
---

# /review-pr — revue d'invariants, pas d'approbation

Ne jamais : approuver, fusionner, fermer, passer « ready », pousser. Ces actions sont humaines
(les hooks les bloquent ou demandent confirmation).

## Workflow

1. Cible : PR `$ARGUMENTS` (`gh pr view <n> --json headRefOid,baseRefName,isDraft,files,reviewDecision,statusCheckRollup`)
   ou diff local `origin/main...HEAD`. Noter le head exact : la revue ne vaut que pour lui.
2. Périmètre : chaque fichier modifié relève-t-il du lot ? Signaler tout fichier hors périmètre.
3. Invariants (AGENTS.md) : frontières de service, contrat, écritures pgvector, verrous,
   secrets/PII, chemins absolus, `git mv` pour les déplacements.
4. Selon les chemins touchés, déléguer UNE analyse isolée si utile :
   migrations → agent `postgres-reviewer` ; gouvernance/autorisations → `governance-auditor` ;
   go-live/release → `go-live-auditor`. Pas de délégation pour un petit diff.
5. Preuves : le rapport de lot cite-t-il des commandes réellement exécutées sur ce head ?
   CI GitHub sur ce head : `gh pr checks <n>`.
6. Pour une revue de correction approfondie, proposer `/code-review` ou `/security-review`
   (commandes intégrées) plutôt que de la refaire ici.
7. PR en brouillon : la revue de confiance exige « ready » ; le signaler, ne pas le faire.

## Sortie

Verdict (`prête pour revue humaine` / `à corriger`), constats classés par gravité avec
`fichier:ligne`, preuves manquantes, head revu. Aucun commentaire posté sans demande explicite.
