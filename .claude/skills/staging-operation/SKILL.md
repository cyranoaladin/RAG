---
name: staging-operation
description: Exécute une opération staging Nexus RAG déjà préflightée et autorisée (publication, migration, sonde) en suivant son plan d'exécution pas à pas. Invocation manuelle uniquement.
disable-model-invocation: true
argument-hint: "<plan d'exécution> <autorisation humaine citée>"
---

# /staging-operation — manuel, autorisé, pas à pas

## Préconditions (toutes, sinon arrêt)

- Un préflight `/go-live-preflight` de cette session, pour cette opération, sur le `main` courant.
- Une autorisation humaine explicite donnée dans cette session pour CETTE opération, citée
  dans `$ARGUMENTS` ou le message. Une autorisation d'une session antérieure ne vaut pas.
- Le plan d'exécution (`docs/runbooks/*_EXECUTION_PLAN.md`) fixe commandes, SHA et points d'arrêt.
- Session « opérateur sensible » recommandée (`docs/agentic/OPERATING_MODEL.md`).

## Workflow

1. Relire le live (main, PR gouvernantes, état du serveur via la commande de lecture du plan).
   Tout écart avec le préflight = arrêt et nouveau préflight.
2. Exécuter une étape à la fois. Chaque commande à effet est confirmée par l'humain (les
   hooks demandent confirmation pour SSH, psql distant, bascule `current`).
3. Après chaque étape : lecture de contrôle prévue par le plan ; comparer à l'attendu.
4. Écart ou erreur : s'arrêter, ne pas improviser de correctif en live ; appliquer le
   rollback du plan seulement sur instruction.
5. Ne jamais afficher un secret, un DSN complet ni un seed ; vérifier leur présence, pas leur valeur.

## Arrêt

Fin du plan, ou premier écart. Ni fusion de PR, ni bascule production.

## Sortie

Journal horodaté : étape, commande (sans secret), code de sortie, lecture de contrôle,
attendu vs mesuré, puis vérification indépendante à confier (agent `retrieval-evaluator`).
