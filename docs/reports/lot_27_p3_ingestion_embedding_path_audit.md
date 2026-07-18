# LOT 27 P3 — Audit des chemins d'embedding d'ingestion

## Date

2026-07-18

## Baseline

| Élément | Valeur |
|---|---|
| Base `main` auditée | `6417277949674a0ad3bbc630dae923166842509a` |
| Head PR #70 réaudité | `f7ebd340f4a20be9723caba3b9dcfa1627445cc1` |
| Méthode | Inspection statique locale, sans appel d'API ni ingestion |

## Fichiers inspectés

| Fichier | Rôle vérifié |
|---|---|
| `services/rag-engine/src/ingestor/api.py` | Montage du routeur v2 et coexistence des routes legacy |
| `services/rag-engine/src/ingestor/ingest_v2_endpoint.py` | Préfixe `/ingest/v2` et appels à `ingest_document` |
| `services/rag-engine/src/ingestor/ingest_v2.py` | Embedding local certifié et écriture pgvector |
| `services/rag-engine/src/ingestor/tasks.py` | Tâche Celery d'ingestion asynchrone |
| `services/rag-engine/src/ingestor/embedding_service.py` | Client d'embedding Ollama du worker legacy |
| `services/rag-engine/src/ingestor/retrieval_v2_endpoint.py` | Embedding local de la recherche v2 |
| `services/rag-engine/src/ingestor/embedding_contract.py` | Chargement local et validation fail-closed du contrat 1024d |
| `services/rag-engine/infra/docker-compose.v2.yml` | Déclaration du service worker Celery, preuve complémentaire en lecture seule |

## Chemin A — `/ingest/v2` routé

`api.py` monte `ingest_v2_endpoint.router`. Ce routeur porte le préfixe
`/ingest/v2`. Les routes implémentées `/upload-files` et `/urls` construisent
une `IngestV2Request` puis appellent `ingest_document`. La route `/drive`
valide actuellement la collection puis retourne `501` : elle n'écrit rien.

| Contrôle | État | Preuve |
|---|---|---|
| Routeur v2 monté dans l'API | Conforme | `api.py:331` |
| Préfixe `/ingest/v2` | Conforme | `ingest_v2_endpoint.py:28` |
| Appel de `ingest_document` | Conforme pour upload et URLs | `ingest_v2_endpoint.py:185,252` |
| Chargement via `_get_embed_model` | Conforme | `ingest_v2.py:70-75,217` |
| Chargement via `load_embedding_model` | Conforme | `ingest_v2.py:74` |
| Validation `validate_runtime_embedding_contract` | Conforme, avant embedding et écriture | `ingest_v2.py:218-224` |
| Préfixe E5 passage | Conforme : `format_passage(c["text"])` | `ingest_v2.py:159,223` |
| Encodage normalisé | Conforme : `encode(..., normalize_embeddings=True)` | `ingest_v2.py:224` |
| Écriture pgvector | Conforme au chemin : `INSERT INTO rag_chunks` | `ingest_v2.py:226-290` |
| Dépendance Ollama pour l'embedding | Aucune dans ce chemin d'appel | `ingest_v2.py` utilise le modèle local du contrat |

Conclusion : `ACTIVE_INGEST_V2_PATH_OK_LOCAL_EMBEDDING`. Le défaut
`format_passage()` précédemment attribué à toute ingestion v2 était faux. Il
ne bloque pas la route active, qui applique déjà le préfixe avant l'encodage.

## Cohérence avec la recherche v2

| Contrôle | État | Preuve |
|---|---|---|
| Chargeur du modèle | `load_embedding_model()` | `retrieval_v2_endpoint.py:147-152` |
| Préfixe requête | `format_query` via `_format_embedding_query` | `retrieval_v2_endpoint.py:83-91,634` |
| Encodage normalisé | `encode(..., normalize_embeddings=True)` | `retrieval_v2_endpoint.py:635-636` |
| Accès vectoriel | pgvector | `retrieval_v2_endpoint.py:631-648` |

La recherche v2 et le chemin A utilisent donc le même chargeur local, la même
normalisation et les préfixes E5 complémentaires passage/requête.

## Chemin B — legacy / worker / Celery

`tasks.py` enregistre la tâche Celery `ingest_document` et délègue la production
des vecteurs à `EmbeddingService`. `docker-compose.v2.yml` déclare un worker
`celery -A tasks worker`, ce qui rend ce chemin déployable. Son utilisation
effective sur un environnement externe n'a pas été vérifiée : aucun SSH ni
contrôle de production n'entre dans ce lot.

| Contrôle | État | Preuve |
|---|---|---|
| Tâche Celery enregistrée | Présente | `tasks.py:249-250` |
| Worker dans la stack v2 | Déclaré | `docker-compose.v2.yml:217-224` |
| Service d'embedding | `EmbeddingService` instancié | `tasks.py:74,92-96` |
| Contrôle modèle Ollama | Appel `/api/tags` | `embedding_service.py:87-106` |
| Production des embeddings | Appel `/api/embeddings` | `embedding_service.py:141-158` |
| Préfixe passage | Absent du worker ; texte brut transmis | `tasks.py:142`, `embedding_service.py:145-147` |
| Normalisation explicite | Absente du worker | Aucun `normalize_embeddings=True` dans ce chemin |
| Écriture pgvector | Possible via `db.insert_chunks` | `tasks.py:144-158` |
| Appartenance à `/ingest/v2` | Aucune | Le routeur v2 importe `ingest_v2.ingest_document`, pas `tasks.py` |

Conclusion : `LEGACY_WORKER_OLLAMA_PATH_STILL_ACTIVE` est une dette P1
bloquante si le worker peut recevoir une tâche. Ce défaut ne doit pas être
présenté comme un défaut du chemin A.

## Ambiguïté de propriété des routes

La même application monte le routeur `/ingest/v2` et expose encore
`/ingest`, `/ingest/urls`, `/ingest/upload-files` et `/ingest/drive`. Ces routes
legacy passent par `TimedOllamaEmbeddings` et ChromaDB. Le routeur admin expose
en plus `/documents/{document_id}/ingest`, qui appelle la route legacy
`/ingest`. Elles ne sont ni des alias ni des appels vers `ingest_v2.py`.

Conclusion : `ROUTE_OWNERSHIP_AMBIGUITY` est une dette P1 bloquante avant toute
réingestion certifiée. La présence simultanée de chemins actifs ou déployables
ne permet pas de garantir qu'une commande d'ingestion empruntera le chemin A.

## Conclusions corrigées

| ID | Niveau | État exact | Effet sur une réingestion |
|---|---|---|---|
| `ACTIVE_INGEST_V2_PATH_OK_LOCAL_EMBEDDING` | OK | `/ingest/v2` applique déjà `format_passage`, charge le modèle local, normalise et valide le contrat avant pgvector | Ne bloque pas ; aucune migration de ce chemin n'est requise |
| `LEGACY_WORKER_OLLAMA_PATH_STILL_ACTIVE` | P1 | Worker Celery déclaré, tâche enregistrée, embeddings Ollama sans préfixe passage ni normalisation explicite | Bloque tant que ce chemin n'est pas neutralisé, migré ou interdit |
| `ROUTE_OWNERSHIP_AMBIGUITY` | P1 | Routes v2 et routes legacy Ollama/Chroma coexistent dans l'application | Bloque tant que la route autorisée pour la réingestion n'est pas unique et certifiée |
| `GOVERNANCE_ACTIVATION_NOT_AUTHORIZED` | P1 | Aucun verrou `*_allowed` n'est activé par ce lot | Bloque toute ingestion réelle jusqu'à autorisation conforme |

## Ce qui bloque et ce qui ne bloque pas

Bloque toute réingestion :

- le worker Celery/Ollama reste déployable et non certifié ;
- plusieurs routes d'ingestion legacy restent exposées à côté de `/ingest/v2` ;
- les verrous de gouvernance restent fermés et aucune transition n'est autorisée.

Ne bloque pas au titre du défaut signalé :

- le formatage passage du chemin `/ingest/v2`, déjà appliqué ;
- le chargement local SentenceTransformer de ce chemin ;
- la normalisation et la validation du contrat 1024d avant son écriture pgvector.

## Interdictions du lot

- Aucun déploiement.
- Aucune ingestion ni tâche worker lancée.
- Aucune modification runtime, DB, Nginx ou DNS.
- Aucun téléchargement de modèle ni régénération d'artefact.
- Aucun verrou de gouvernance modifié.

## Décision d'architecture

Voir `docs/adr/ADR-LOT27-P3-embedding-ingestion-local-sentence-transformer.md`.
