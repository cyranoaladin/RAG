# Accès des agents externes au retrieval Nexus RAG

> Objectif produit (gates G8–G9 de `docs/ROADMAP.md`). Ce document fixe l'architecture
> cible et ses invariants ; il n'autorise ni n'implémente rien. Toute implémentation est un
> lot dédié, avec ADR et revue humaine.

## Architecture cible

```
agent externe (LLM, outil tiers, MCP client)
        │  HTTPS, credentials propres au client
        ▼
API Nexus authentifiée  ──ou──  adaptateur MCP Nexus (optionnel, G9)
        │  RetrievalRequest (nexus-contracts)
        ▼
rag-engine  api_v2 : /search/v2, /catalogue/v2   (lecture seule)
        │  rôle PostgreSQL runtime à privilège SELECT minimal
        ▼
PostgreSQL + pgvector
```

**Jamais** : agent externe → PostgreSQL, ni agent externe → fichiers bruts du corpus, ni
agent externe → endpoints de revue (`/review/v2/*`, portée `ADMIN`).

## Existant (STATIC, à relire dans le code avant tout lot)

- `rag-engine` expose `/search/v2` et `/catalogue/v2` sous la portée `SEARCH`
  (`services/rag-engine/src/ingestor/api_scopes.py`) ; `/chat` existe mais la génération de
  réponses est verrouillée (`answer_generation_allowed: false`).
- Un appel exige trois credentials distincts, sans repli de l'un sur l'autre
  (`scripts/rag_query_external.py`) : jeton de service BFF (`Authorization`), clé API client
  (`X-RAG-API-Key`), identité signée à courte durée émise par l'émetteur canonique
  (`X-Nexus-Identity`). Un client externe ne détient jamais le secret de signature interne.
- Le scope de retrieval est dérivé côté serveur ; le client ne choisit pas ses droits.

## Invariants de l'accès externe

1. Le contrat est `nexus-contracts` (`RetrievalRequest → RetrievalResponse`), versionné ;
   l'adaptateur ne définit aucun schéma parallèle.
2. Chaque client externe a une identité propre, révocable, avec quotas et scopes
   (collections, profils) attribués par une autorité versionnée ; jamais de clé partagée.
3. Réponses sourcées : chaque chunk porte sa provenance et ses droits ; aucun contenu à
   droits inconnus ni propriétaire hors audience autorisée.
4. Rate limiting, taille de requête bornée, `top_k` plafonné, timeouts inférieurs à ceux du
   moteur.
5. Journalisation sans secret ni PII : identifiant client, scope, empreinte de requête,
   nombre de résultats, latence.
6. L'adaptateur MCP (G9) n'est qu'une traduction du même contrat vers des outils MCP
   (`search`, `catalogue`) ; il n'a pas plus de droits que l'API et ne parle jamais SQL.
7. Aucune donnée élève n'entre par cette voie ; les requêtes ne sont pas conservées au-delà
   de la durée de rétention définie par l'ADR d'ouverture.

## Pré-requis avant ouverture (G8)

GO_LIVE_READY et production validée (G7) ; ADR d'ouverture externe (modèle de menace,
registre des clients, quotas, rétention) ; émetteur d'identité pour clients externes en
production ; tests de refus (credential manquant, scope hors attribution, révocation) ;
sonde indépendante par client pilote ; procédure de révocation d'urgence.

## Pourquoi pas de `.mcp.json` dans le dépôt aujourd'hui

`.mcp.json` configure les serveurs MCP utilisés **par Claude Code pendant le
développement**. Aucun besoin actuel ne le justifie (GitHub passe par `gh`). Le serveur MCP
Nexus du G9 est un **produit** exposé aux agents externes, pas une configuration de
développement ; il ne se déclarera dans `.mcp.json` que si l'équipe veut l'utiliser pour
tester, avec des credentials hors dépôt.
