# Convergence des API de retrieval

Statut: Lot 19, document de cadrage.

## Situation actuelle

Deux surfaces `/search` existent avec des contrats differents.

### API historique Chroma

Module : `services/rag-engine/src/ingestor/api.py`.

Payload courant :

```json
{
  "q": "texte de recherche",
  "k": 6,
  "collection": "rag_education",
  "section": "education",
  "filters": {"matiere": "Mathématiques"},
  "score_threshold": 0.55
}
```

Cette API sert la prod historique. Depuis le Lot 19, `collection` n'est plus arbitraire : elle doit etre une collection Nexus connue ou un nom legacy present dans `configs/legacy_collection_mapping.yml`.

### API Nexus pilote

Module : `services/rag-engine/scripts/retrieval_api.py`.

Payload courant :

```json
{
  "query": "derivee d'une fonction",
  "top_k": 5
}
```

Les filtres `niveau` et `audience` sont imposes par le profil HMAC signe. Cette API lit `rag_chunks_pilote` et reste read-only.

## Contrat canonique v2

La source de verite est `packages/contracts/src/nexus_contracts/retrieval.py`.

Endpoint exposé par le runtime v2 :

```text
POST /search/v2
```

Depuis LOT41U, il consomme directement `RetrievalRequest` et retourne
directement `RetrievalResponse`. Le Cockpit ne traduit plus un DTO moteur local
`q/collection/hits` : son BFF construit le profil depuis l'identité signée,
valide le contrat partagé, puis le moteur résout la collection à partir de la
matière et de l'artefact de scope versionné.

Principes :

- le client decrit un besoin pedagogique, pas une table ni une collection physique ;
- les filtres de profil viennent du contrat/profil verifie ;
- les domaines et collections physiques sont resolus cote serveur ;
- les citations utilisent `source_label`, `source_uri`, `rights` et `page` si disponible ;
- aucune génération de réponse n'est ajoutée ; la réponse de retrieval ne
  contient aucun champ de génération.

## Adaptateur Lot 19

Module ajoute : `services/rag-engine/src/ingestor/retrieval_contract_adapter.py`.

Il fournit :

- `adapt_legacy_search_payload()` pour convertir l'ancien payload UI en routage Nexus ;
- `adapt_retrieval_request()` pour convertir `RetrievalRequest` en query,
  top-k et filtres après résolution autoritative de la collection côté serveur ;
- `build_citation_payload()` pour produire le sous-ensemble compatible `Citation`.

L'adaptateur legacy reste isolé dans le monolithe historique. Le runtime v2
refuse l'ancien DTO et bloque tout élargissement de collection par le client.

## Resolution collection/domain

Source de verite :

- `services/rag-engine/configs/rag_collections.yml` ;
- `services/rag-engine/configs/legacy_collection_mapping.yml`.

Regles :

- collection inconnue => refus ;
- legacy connue => mapping explicite vers Nexus ;
- `rag_nexus_quarantine` => non retrievable ;
- Web3 et education ne sont jamais melanges dans une meme collection ;
- pgvector cible `rag_chunks`, avec `rag_chunks_pilote` conserve comme legacy pilote.

## Compatibilite

`POST /search` reste maintenu pour la prod historique. Les changements Lot 19 sont defensifs :

- pas de suppression de route ;
- pas de migration physique de Chroma ;
- pas de modification de secret ;
- refus des collections inconnues ;
- `/admin/reindex` protege par auth ;
- absence de token admin en production => 503.
