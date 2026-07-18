# ADR : certifier l'ingestion v2 locale et neutraliser le worker Ollama legacy

## Statut

Proposé

## Contexte

L'audit corrigé distingue trois ensembles qui coexistent dans `rag-engine` :

1. **Chemin actif routé `/ingest/v2`** : `api.py` monte
   `ingest_v2_endpoint.py`; les routes upload et URLs appellent
   `ingest_v2.ingest_document`. Ce pipeline charge localement
   `intfloat/multilingual-e5-large` via `load_embedding_model()`, valide le
   contrat runtime/pgvector, applique `format_passage()` à chaque chunk,
   encode avec `normalize_embeddings=True`, puis écrit dans pgvector.
2. **Recherche `/search/v2`** : `retrieval_v2_endpoint.py` charge le même modèle
   local, applique `format_query()` et encode avec la même normalisation avant
   la recherche pgvector.
3. **Chemins legacy** : `tasks.py` enregistre une tâche Celery qui utilise
   `EmbeddingService`; ce service appelle Ollama `/api/tags` et
   `/api/embeddings`. L'application expose aussi des routes `/ingest*` legacy
   utilisant Ollama/Chroma, en parallèle de `/ingest/v2`.

L'affirmation précédente selon laquelle toute ingestion v2 omettait
`format_passage()` était incorrecte. Cette omission concerne le worker
Celery/Ollama, pas le chemin actif `/ingest/v2`.

## État établi par le LOT 27 P3

- Le chemin `/ingest/v2` implémenté est déjà cohérent avec la recherche v2 pour
  le modèle, les préfixes E5 complémentaires, la normalisation et la dimension
  pgvector 1024.
- La route `/ingest/v2/drive` retourne actuellement `501` après validation de
  collection et n'écrit rien.
- Le worker Celery reste déclaré dans `docker-compose.v2.yml` et sa tâche
  `ingest_document` reste enregistrée.
- Le worker produit encore ses embeddings via Ollama, sans
  `format_passage()` ni normalisation explicite.
- Les routes legacy `/ingest*` restent exposées par la même application.
- Les verrous de gouvernance restent fermés. Aucune ingestion n'est activée.

## Décision

### 1. Conserver le chemin actif conforme

Le chemin routé `/ingest/v2` fondé sur `ingest_v2.py` reste la cible certifiée.
Il ne doit pas être migré vers `EmbeddingService` ni vers Ollama. Son contrat
reste : modèle SentenceTransformer local, aucun téléchargement runtime,
`format_passage()`, normalisation, validation 1024d et écriture pgvector avec
`review_status=needs_review`.

### 2. Neutraliser, migrer ou interdire le worker legacy

Avant toute activation d'ingestion réelle, le chemin `tasks.py` →
`EmbeddingService` doit satisfaire exactement l'une des options suivantes :

- être neutralisé et rendu impossible à démarrer ou à recevoir une tâche ;
- être migré vers le même pipeline local certifié que `/ingest/v2` ;
- être explicitement interdit par la configuration et les contrôles
  d'exploitation, avec un test fail-closed prouvant l'interdiction.

Tant qu'aucune option n'est démontrée, toute ingestion par le worker est
interdite. La simple validation 1024d effectuée dans `tasks.py` ne certifie pas
les vecteurs ensuite produits par Ollama.

### 3. Éliminer l'ambiguïté de propriété des routes

Chaque commande d'ingestion doit avoir un propriétaire et un chemin certifié
uniques. Les routes `/ingest*` legacy et le point d'entrée admin qui appelle
`/ingest` doivent être neutralisés, migrés ou explicitement exclus du périmètre
de réingestion. Aucun chemin non certifié ne peut écrire dans le magasin cible.

### 4. Maintenir le fail-closed de gouvernance

Aucun verrou `*_allowed` ne peut être activé par effet de bord. Une activation
ultérieure exige tous les critères suivants :

1. inventaire exhaustif des routes, producteurs de tâches et workers pouvant
   déclencher une ingestion ;
2. preuve que chaque chemin autorisé utilise le modèle local certifié,
   `format_passage()`, `normalize_embeddings=True` et la validation du contrat
   avant toute écriture pgvector ;
3. preuve que chaque chemin legacy est neutralisé, migré ou interdit
   fail-closed ;
4. passage obligatoire `quality → gate → review`, avec
   `review_status=needs_review` avant toute visibilité retrieval ;
5. tests de contrat et CI locale verts sur le périmètre complet ;
6. autorisation explicite conforme à `transition_authorization.yml`, ADR
   référencé et mise à jour contrôlée des verrous de gouvernance.

Sans ces six preuves, aucune ingestion ni réingestion n'est autorisée.

## Architecture cible

```text
Chemin certifié d'ingestion :
  texte
    → format_passage(texte)
    → SentenceTransformer local, normalize_embeddings=True
    → validation modèle + dimension runtime + pgvector 1024d
    → quality → gate → review
    → pgvector INSERT avec needs_review

Recherche v2 :
  requête
    → format_query(requête)
    → même SentenceTransformer local, normalize_embeddings=True
    → pgvector SELECT

Tout autre chemin :
  refus fail-closed avant production de vecteur ou écriture
```

## Critères d'acceptation d'un futur lot runtime

1. Le contrat statique confirme que `/ingest/v2` conserve
   `format_passage()`, `encode(..., normalize_embeddings=True)` et
   `validate_runtime_embedding_contract()`.
2. Le contrat statique confirme que la recherche v2 utilise
   `load_embedding_model()`.
3. Un test échoue si un worker autorisé appelle `/api/tags` ou
   `/api/embeddings` pour produire les vecteurs d'ingestion.
4. Un test échoue si une route d'ingestion exposée contourne le chemin certifié.
5. Les contrôles de gouvernance prouvent qu'aucune écriture ne contourne
   `quality → gate → review`.
6. Aucun test d'acceptation ne lance une ingestion réelle sans autorisation de
   transition distincte.

## Non-objectifs de ce lot

- Aucune modification de `ingest_v2.py`, `tasks.py`, `EmbeddingService` ou de
  tout autre code runtime.
- Aucune migration pgvector ou ChromaDB.
- Aucune modification Docker Compose.
- Aucune ingestion ou réingestion.
- Aucun démarrage de worker.
- Aucun déploiement ni accès production.
- Aucun téléchargement de modèle ni régénération d'artefact.
- Aucune activation de verrou de gouvernance.

## Conséquences

- Le faux P0 sur `format_passage()` dans `/ingest/v2` est supprimé.
- Le chemin actif local reste inchangé et explicitement reconnu conforme sur
  le point audité.
- La dette est recentrée sur le worker Celery/Ollama et sur la coexistence de
  routes legacy.
- La réingestion reste bloquée jusqu'à neutralisation ou certification de tous
  les chemins et autorisation de gouvernance.

## Risques

| Risque | Traitement requis |
|---|---|
| Une tâche externe cible le nom Celery `ingest_document` | Neutraliser le worker ou refuser la tâche avant embedding/écriture |
| Une route legacy est utilisée à la place de `/ingest/v2` | Rendre le routage univoque et tester l'absence de contournement |
| Le worker Ollama produit un espace vectoriel divergent | Interdire ce chemin ou le migrer vers le modèle local certifié |
| Un verrou est activé avant certification complète | Conserver le fail-closed et exiger `transition_authorization.yml` + ADR |

## Retour arrière

Ce lot ne modifie aucun runtime : aucun retour arrière opérationnel ni migration
de données n'est requis. La documentation peut être rétablie par revert du
commit si une preuve de routage ultérieure invalide cet audit.

## Blocages restants

| ID | Niveau | Description |
|---|---|---|
| `LEGACY_WORKER_OLLAMA_PATH_STILL_ACTIVE` | P1 | Le worker Celery déployable produit encore les embeddings via Ollama |
| `ROUTE_OWNERSHIP_AMBIGUITY` | P1 | Routes v2 et legacy coexistent sans propriétaire d'ingestion unique |
| `GOVERNANCE_ACTIVATION_NOT_AUTHORIZED` | P1 | Les critères d'activation et la transition autorisée ne sont pas satisfaits |
