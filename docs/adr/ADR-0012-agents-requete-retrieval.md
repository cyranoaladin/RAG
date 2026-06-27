# ADR-0012 — Agents de requête / orchestration du retrieval en lecture seule

- **Statut** : Accepté
- **Date** : 2026-06-27
- **Décideur** : Alaeddine Ben Rhouma (Shark)
- **Découle de** : ADR-0005 (agents d'acquisition), ADR-0011 (API retrieval)

## Contexte

Les agents existants (ADR-0005) sont des agents d'**acquisition** (peuplent le corpus). Le retrieval est exposé via l'API filtrée (ADR-0011). Il faut une chaîne d'agents de **requête** pour interroger l'API et assembler un contexte, sans générer de réponse.

## Décision

- **Module séparé** : `services/rag-pedago/query_agents/` (pas dans `agents/`). Les agents d'acquisition restent intacts.
- **Chaîne** : `QueryOrchestrator` → `QueryLevelAgent` → `QuerySubjectAgent` → API `/search`.
- **Profil signé** : rag-pedago signe le jeton HMAC avec `PROFILE_SECRET` (service de confiance). Le profil provient de l'auth amont, jamais auto-attribué par l'agent.
- **`PROFILE_SECRET` partagé** : rag-engine (vérifie) et rag-pedago (signe) sont des services de confiance. Le secret vient de l'env, jamais commité.
- **Mode context_only** : tant que `answer_generation_allowed=false`, la sortie est un contexte structuré (passages + métadonnées). Aucune prose générée.
- **Filtrage imposé par l'API** : le jeton porte le profil, l'API filtre. L'agent ne réimplémente pas le filtrage et ne peut pas élargir l'audience.

## Conséquences

- La génération de réponse est découplée du retrieval. Le contexte est prêt pour un futur LLM (quand `answer_generation_allowed` sera levé).
- Le filtrage est garanti par construction (API + HMAC), pas par la bonne volonté de l'agent.
