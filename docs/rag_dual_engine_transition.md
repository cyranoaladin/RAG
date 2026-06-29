# Transition double moteur RAG

Statut: Lot 19, document de cadrage.

## Objet

Le depot contient deux realites qui doivent coexister sans confusion :

- moteur A, historique/prod actuelle : `rag-local`, Streamlit, FastAPI ingestor, ChromaDB, Ollama, uploads, Google Drive, admin API et catalogue SQLite ;
- moteur B, Nexus pedagogique nouveau : `rag-pedago`, chunks et embeddings 1024, manifeste de revue, pgvector, API read-only filtree par profil HMAC et agents `context_only`.

La production publique `https://rag-ui.nexusreussite.academy` correspond encore au moteur A. Le moteur B n'est pas encore branche a cette UI.

## Moteur A - historique prod

Composants principaux :

- UI Streamlit : `services/rag-engine/src/ui/app_v2.py` ;
- ingestor FastAPI : `services/rag-engine/src/ingestor/api.py` ;
- admin API : `services/rag-engine/src/ingestor/admin_api.py` ;
- stockage vectoriel : ChromaDB ;
- embeddings : Ollama ;
- catalogue : SQLite admin ;
- sources : upload fichiers, URL, Google Drive.

Endpoints historiques :

- `POST /ingest` ;
- `POST /ingest/urls` ;
- `POST /ingest/drive` ;
- `POST /search` ;
- `GET /collections` ;
- `GET /stats/{collection}` ;
- `/admin/*`.

Collections Chroma historiques observees ou attendues :

| Legacy Chroma | Cible Nexus logique |
|---|---|
| `rag_education` | `rag_nexus_education` |
| `rag_francais_premiere` | `rag_nexus_education` |
| `rag_maths_premiere` | `rag_nexus_education` |
| `rag_web3` | `rag_nexus_web3` |
| `rag_divers` | `rag_nexus_quarantine` |

Ces collections ne doivent pas etre renommees physiquement en production sans migration explicite, backup et rollback.

## Moteur B - Nexus gouverne

Composants principaux :

- plan de controle : `services/rag-pedago/` ;
- contrat partage : `packages/contracts/` ;
- chunks pedagogiques : `services/rag-pedago/data/chunks/` ;
- embeddings : `intfloat/multilingual-e5-large`, 1024 dimensions ;
- review manifest : `services/rag-pedago/data/embeddings/review_manifest.json` ;
- indexation pilote : `services/rag-engine/scripts/index_pgvector.py` ;
- API read-only : `services/rag-engine/scripts/retrieval_api.py` ;
- agents de requete : `services/rag-pedago/query_agents/`.

Contraintes :

- aucun chunk n'entre dans pgvector hors `quality -> gate -> review` ;
- `answer_generation_allowed=false`, donc les agents ne generent pas de reponse ;
- le profil est signe HMAC cote serveur ;
- le client ne fournit pas `niveau`, `audience` ou collection physique.

## Architecture cible des collections

La source versionnee est `services/rag-engine/configs/rag_collections.yml`.

Collections cibles :

- `rag_nexus_education` : corpus pedagogique general ;
- `rag_nexus_official` : programmes, BO, textes officiels ;
- `rag_nexus_exams` : annales, sujets, corriges, grilles ;
- `rag_nexus_owned` : ressources proprietaires Nexus validees ;
- `rag_nexus_web3` : blockchain, Web3, Solana ;
- `rag_nexus_quarantine` : sources non admises, non retrievable.

Le filtrage metier doit se faire par metadonnees, pas par multiplication de collections par notion. Les metadonnees obligatoires sont listees dans `rag_collections.yml`.

## Regle de transition

La prod historique peut continuer a servir `rag-ui`, mais toute evolution Nexus doit passer vers une API contractuelle et des metadonnees compatibles.

Interdictions de transition :

- ne pas connecter le cockpit directement a Chroma ou pgvector ;
- ne pas laisser un client choisir une collection physique arbitraire ;
- ne pas melanger Web3, lycee, examens, officiels et ressources proprietaires sans metadonnees strictes ;
- ne pas rendre `rag_nexus_quarantine` retrievable ;
- ne pas renommer les collections Chroma de prod sans migration controlee.

## A migrer progressivement

1. Aligner les ingestions historiques sur les metadonnees Nexus obligatoires.
2. Remplacer les choix UI de collections physiques par des domaines/metadonnees serveur-side.
3. Introduire `POST /retrieve` consommant `RetrievalRequest`.
4. Migrer les donnees Chroma admises vers `rag_chunks` pgvector non pilote.
5. Declasser `rag_chunks_pilote` une fois `rag_chunks` gouverne et teste.
6. Decommissionner ou renommer `rag-local` quand l'UI Nexus contractuelle est livree.
