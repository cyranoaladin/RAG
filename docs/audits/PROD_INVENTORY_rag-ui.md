# Inventaire de production — rag-ui.nexusreussite.academy

**Date de reconnaissance** : 30 juin 2026
**Méthode** : lecture seule via SSH (`root@88.99.254.59`), aucune mutation (hors rotation token A-8).
**Lot** : LOT 20, itération 3 — branche `lot-20-prod-preflight-rag-ui`.
**Règles** : R-01 (pas de secret en argument), R-02 (périmètre = pile RAG, hors PII), R-03 (commande incertaine non exécutée).

---

## 1. Topologie d'exécution

### 1.1 Projet Docker Compose RAG

Fichier : `/srv/nexusreussite/rag-ui/compose/docker-compose.yml`

| Conteneur | Image | Status | Port loopback | Limite mémoire | Limite CPU |
|---|---|---|---|---|---|
| compose-ingestor-1 | compose-ingestor (build local) | healthy | 127.0.0.1:18001→8001 | 8 GiB | 2.0 |
| compose-ui-1 | compose-ui (build local) | healthy | 127.0.0.1:18501→8501 | 2 GiB | 1.0 |
| compose-chroma-1 | chromadb/chroma:1.1.1 | healthy | 127.0.0.1:8000→8000 | 4 GiB | 2.0 |
| compose-ollama-1 | ollama/ollama:0.3.13 | healthy | 127.0.0.1:11434→11434 | 24 GiB | 6.0 |
| compose-autoheal-1 | willfarrell/autoheal:latest | healthy | — | illimité | illimité |

**Runtime** : Python 3.11.15, Uvicorn 1 worker, `read_only: true` + `no-new-privileges`.

### 1.2 Consommation mémoire (instantané)

| Conteneur | RAM effective |
|---|---|
| compose-ingestor-1 | 1 010 MiB / 8 GiB |
| compose-ui-1 | 93 MiB / 2 GiB |
| compose-chroma-1 | 77 MiB / 4 GiB |
| compose-ollama-1 | 10 MiB / 24 GiB (aucun modèle chargé en RAM) |

---

## 2. Périmètre in/out-of-scope (D-08)

### 2.1 Conteneurs

| Conteneur | Projet Compose | In-scope (RAG) ? |
|---|---|---|
| compose-ingestor-1 | compose | **OUI** |
| compose-ui-1 | compose | **OUI** |
| compose-chroma-1 | compose | **OUI** |
| compose-ollama-1 | compose | **OUI** |
| compose-autoheal-1 | compose | **OUI** |
| nexus-postgres-db | nexus | **NON** (base applicative PII, R-02) |
| docker-backend-1, docker-celery-*, docker-nginx-1, docker-redis-1, docker-db-1 | docker (Korrigo) | NON |
| infra-web-1, infra-postgres-1, infra-redis-1, infra-minio-1 | infra (NSI) | NON |
| math-correction-* | math-correction | NON |
| brevet-master-*, brevet-master-qdrant | repo | NON |
| journey-* | standalone | NON |

### 2.2 Volumes in-scope

| Volume | In-scope | Contenu |
|---|---|---|
| `compose_rag_ui_chroma_data` | **OUI** | Index ChromaDB |
| `compose_rag_ui_ollama_data` | **OUI** | Modèles Ollama |
| `compose_rag_ui_admin_data` | **OUI** | SQLite admin, données ingestor |
| `/srv/nexusreussite/rag-ui/data/uploads` | **OUI** | Fichiers uploadés |
| `/srv/nexusreussite/rag-ui/creds` | **OUI** | Credentials GDrive |
| `/srv/nexusreussite/rag-ui/backups` | **OUI** | Backups Chroma |
| Tous les autres volumes | NON | — |

---

## 3. Reverse proxy (nginx)

| Domaine | Cible loopback | TLS | Remarque |
|---|---|---|---|
| `rag-ui.nexusreussite.academy` | 127.0.0.1:18501 (Streamlit) | Let's Encrypt | WebSocket `/_stcore/`, passthrough `/api/` → :18001 |
| `rag-api.nexusreussite.academy` | 127.0.0.1:18001 (ingestor) | Let's Encrypt | `proxy_read_timeout 300s` |

En-têtes : `nosniff`, `no-referrer`, `SAMEORIGIN`, `HSTS 63072000`.
Contrôle d'accès : token Bearer (rotation effectuée le 30/06/2026). `/health` et `/metrics` sont publics.

---

## 4. Backend vectoriel — ChromaDB

### 4.1 Version et configuration

**ChromaDB 1.1.1**, persistent, volume 204 MiB. HNSW : `space=cosine`, `ef_construction=100`, `ef_search=100`, `max_neighbors=16`.

### 4.2 Collections — dimension mesurée (D-01)

Dimension vérifiée par `len(embedding)` sur un vecteur extrait (`include=embeddings`, limit 1) :

| Collection | UUID | Vecteurs | Dim déclarée | **Dim mesurée** |
|---|---|---|---|---|
| **rag_education** | `839598b7-…` | **7 181** | 768 | **768** |
| rag_francais_premiere | `f57e5aa1-…` | 5 948 | 768 | **768** |
| nsi_corpus | `d0ee9196-…` | 4 716 | 768 | **768** |
| rag_math_correction | `a77c77ff-…` | 67 | 768 | **768** |
| ressources_pedagogiques_terminale | `b250b5e6-…` | 0 | null | N/A (vide). **Décision** : suppression au décommissionnement de la prod. Résiduelle, plus interrogée (`app.py` morte, K-02). |

**Total** : **17 912 vecteurs** dans **4 collections peuplées**, tous **768 dim mesurées**, via **nomic-embed-text**.

**Note N-04** : à l'arrivée de la reconnaissance, la prod comptait **5 collections** (les 4 peuplées + `ressources_pedagogiques_terminale` vide). Au terme du diagnostic, **8 collections** existent : 3 collections vides ont été auto-créées involontairement :
- `rag_maths_premiere` : créée par le fallback `maths_premiere` en **fonctionnement nominal** (chaque clic « Maths 1ère » dans l'UI déclenche `get_or_create_collection`)
- `rag_web3` : créée par le test L-02 (rubrique Web3)
- `rag_divers` : créée par le test L-02 (rubrique Divers)

### 4.3 Réconciliation collections prod ↔ config dépôt (D-02)

#### Collections prod vs `legacy_collection_mapping.yml`

| Collection prod | Dans le mapping ? | Mapping cible Nexus |
|---|---|---|
| `rag_education` | ✅ → `rag_nexus_education` | `rag_nexus_education` |
| `rag_francais_premiere` | ✅ → `rag_nexus_education` | `rag_nexus_education` |
| `nsi_corpus` | ❌ **Absente** | — |
| `rag_math_correction` | ❌ **Absente** | — |
| `ressources_pedagogiques_terminale` | ❌ **Absente** (vide) | — |

#### Entrées du mapping sans collection prod

| Entrée mapping | Existe en prod ? |
|---|---|
| `rag_maths_premiere` | ❌ |
| `rag_web3` | ❌ |
| `rag_divers` | ❌ |

#### Routing `rag_collections.yml` vs prod

| Section | Legacy (config) | Prod ? | Nexus (config) | Prod ? |
|---|---|---|---|---|
| education | `rag_education` | ✅ (7 181) | `rag_nexus_education` | ❌ |
| francais_premiere | `rag_francais_premiere` | ✅ (5 948) | `rag_nexus_education` | ❌ |
| maths_premiere | `rag_maths_premiere` | ❌ | `rag_nexus_education` | ❌ |
| web3 / blockchain | `rag_web3` | ❌ | `rag_nexus_web3` | ❌ |
| divers | `rag_divers` | ❌ | `rag_nexus_quarantine` | ❌ |
| default | `rag_education` | ✅ | `rag_nexus_education` | ❌ |

#### COLLECTION_MAP prod (extrait du code en cours d'exécution, I-05)

```python
{'education': 'rag_education', 'nsi': 'nsi_corpus', 'nsi_corpus': 'nsi_corpus',
 'web3': 'rag_web3', 'blockchain': 'rag_web3', 'divers': 'rag_divers',
 'maths_premiere': 'rag_maths_premiere', 'francais_premiere': 'rag_francais_premiere',
 'default': 'rag_education'}
```

Écarts nommés :
1. `nsi_corpus` et `rag_math_correction` existent en prod mais sont **absentes de `rag_collections.yml`**.
2. `rag_maths_premiere`, `rag_web3`, `rag_divers` sont dans la config mais **n'existent pas en prod**.
3. Aucune collection Nexus (`rag_nexus_*`) n'existe en prod.

### 4.4 Chevauchement `rag_education` ↔ `nsi_corpus` (D-03)

| Critère | Résultat |
|---|---|
| Chevauchement d'IDs (sha256) | **0** — aucun ID commun |
| Chevauchement thématique | **OUI** — `rag_education` : 4 362 chunks NSI (GDrive). `nsi_corpus` : 4 716 chunks NSI (rag-pedago). |
| Même contenu ? | **Non** — sources différentes (GDrive vs corpus structuré `03_progressions/`). |
| Risque post-fusion | **Pollution de ranking** : ~8 500 chunks NSI sur deux corpus qui se chevauchent thématiquement sans dédup. |

**Définition de « education »** : en prod, `section=education` route vers `rag_education`. C'est un **silo d'ingestion GDrive**, pas une discipline. Il agrège tous les contenus ingérés via un unique folder GDrive, toutes matières confondues. **Ce n'est pas une unité migrable** : il devra être **décomposé par matière** avant indexation dans le moteur gouverné (I-08).

### 4.5 Complétude des métadonnées — intersection exacte (D-04, I-01 corrigé)

Scan exhaustif. Critère d'admissibilité : `matiere` (ou `notion`) **ET** `niveau` (ou `level`) **ET** `source_uri` (URL commençant par `http`).

| Collection | Total | matiere | niveau | URL source | **matiere ∧ niveau ∧ URL** | **% admissible** |
|---|---|---|---|---|---|---|
| **rag_education** | 7 181 | 4 362 | 4 362 | 5 852 | **3 366** | **46 %** |
| **rag_francais_premiere** | 5 948 | 5 948 | 5 948 | 5 833 | **5 833** | **98 %** |
| **nsi_corpus** | 4 716 | 4 349 | 4 286 | 0 | **0** | **0 %** |
| **rag_math_correction** | 67 | 0 | 0 | 0 | **0** | **0 %** |
| **TOTAL** | **17 912** | 14 659 | 14 596 | 11 685 | **9 199** | **51 %** |

**Volume admissible en l'état** (avant enrichissement `rights` et avant re-chunking) : **9 199 chunks** (51 %).

**Volume nécessitant quarantaine ou enrichissement** : **8 713 chunks** (49 %), dont :
- 3 815 chunks `rag_education` avec matière/niveau mais sans URL (996 + 2 819 pop B sans classification) → quarantaine
- 4 716 chunks `nsi_corpus` sans `source_uri` → re-ingestion par chaîne gouvernée depuis sources `rag-pedago` (A-6)
- 67 chunks `rag_math_correction` → quarantaine
- 115 chunks `rag_francais_premiere` sans URL → enrichissement ponctuel

**Note critique** : `rights` = **0 %** sur la totalité du corpus. Aucun chunk n'est migrable tel quel ; même les 9 199 admissibles nécessitent un enrichissement `rights` **par provenance** (A-4), jamais par classification de texte. Contenu Nexus-owned → droits connus ; contenu tiers → droits à établir explicitement ou **quarantaine** (A-5).

**Exposition IP** : les PDFs tiers de `rag_education` (pop B, 2 819 chunks issus de GDrive) sont de provenance non établie. Leurs droits d'exploitation ne sont pas documentés. Risque juridique à évaluer avant indexation.

### 4.6 Mapping champ-à-champ prod → contrat `nexus-contracts` (D-05)

#### `ChunkMetadata` du contrat (champs obligatoires)

| Champ contrat | `rag_education` (pop A) | `rag_education` (pop B) | `nsi_corpus` | `rag_francais` | Transformable ? |
|---|---|---|---|---|---|
| `tenant` | ❌ | ❌ | ❌ | ❌ | Dérivable (hardcode) |
| `niveau` (enum) | texte libre | ❌ | `level` | texte libre | Mapping texte→enum |
| `voie` (enum) | ❌ | ❌ | ❌ | ❌ | Inférable de la matière |
| `matiere` | ✅ | ❌ | `notion` (≠ matière) | ✅ | Partiel |
| `audience` | ❌ | ❌ | ❌ | ❌ | Défaut `["tous"]` |
| `type_doc` (enum) | `type_ressource` | ❌ | `document_type` | `type_ressource` | Mapping partiel |
| `notions` | ❌ | ❌ | `notion` (str) | ❌ | NSI : `[notion]` |
| `source_label` | `source` (nom fichier) | `title` (nom PDF) | ❌ | `source`/`original_filename` | Partiel |
| `source_uri` | URL (81 %) | URL (100 %) | `path` (local) | URL (98 %) | Partiel |
| `rights` | **❌ ABSENT** | **❌ ABSENT** | **❌ ABSENT** | **❌ ABSENT** | **Par provenance** (A-4), jamais par classification |
| `official` | ❌ | ❌ | ❌ | ❌ | Par provenance |
| `doc_id` | `sha256` (= chunk, pas doc) | idem | idem | idem | ≠ doc_id |

### 4.7 Provenance et citation (D-06)

| Collection | URL source | `rights` | Citation F-01 possible ? |
|---|---|---|---|
| rag_education (pop A) | 77 % URL GDrive | **0 %** | ❌ |
| rag_education (pop B) | 100 % URL GDrive | **0 %** | ❌ |
| nsi_corpus | 0 % (chemins locaux) | **0 %** | ❌ |
| rag_francais_premiere | 98 % URL | **0 %** | ❌ |
| rag_math_correction | 0 % | **0 %** | ❌ |

**Verdict** : F-01 insatisfaisable sur **100 %** du corpus. `rights` doit être établi **par provenance** (A-4).

### 4.8 Contenu non revu servi en prod — `nsi_corpus` (I-06, escalade)

**Constat critique** : la collection `nsi_corpus` (4 716 chunks) contient :
- **4 437 chunks** (94 %) avec `status: needs_review`
- **279 chunks** (6 %) avec `status` vide (= non revu non plus)

**100 % du contenu `nsi_corpus` est non revu** et servi aux utilisateurs via le routing `section=nsi` → `nsi_corpus`.

**Recommandation** : retirer `nsi_corpus` du routing prod (`COLLECTION_MAP`) ou ajouter un filtre `status=reviewed` obligatoire. En l'absence de chunks avec `status=reviewed`, cela revient à désactiver la rubrique `nsi` en prod. Alternativement, prioriser la revue de ce corpus. **Violation de gouvernance à traiter avant la migration.**

---

## 5. Modèles locaux (Ollama)

| Modèle | Taille | Usage |
|---|---|---|
| **nomic-embed-text:latest** | 274 MiB | **Embedding** (768 dim, nomic-bert 137M params, F16, BERT tokenizer, contexte 2048) |
| qwen2.5:1.5b | 986 MiB | **SMALL_LLM** configuré pour `/rag/query` |
| llama2:latest | 3,8 GiB | Historique, non utilisé |
| qwen2.5:7b | 4,7 GiB | Téléchargé, non configuré |

---

## 6. API applicative (ingestor)

### 6.1 Provenance de l'image en cours (I-05)

| Propriété | Valeur |
|---|---|
| Image SHA | `sha256:2cbdad9bfc1a…` |
| Date de création | 2026-06-28T13:12:20Z |
| Build context | `/srv/nexusreussite/rag-ui/compose/ingestor/` |
| `api.py` prod | 91 501 octets (Jun 28 15:12) |
| `api.py` dépôt | 90 357 octets |
| **Verdict** | **Divergence confirmée : prod ≠ dépôt** |

Preuves de divergence dans le code exécuté :
- Prod `_resolve_search_target` : pas de paramètre `allow_quarantine`, pas de check `explicit_collection_override`.
- Prod `COLLECTION_MAP` : contient `'nsi': 'nsi_corpus'` absent de la config dépôt.
- Prod `MATHS_PREMIERE_FALLBACK_FILTERS` : contient `'groupe': 'Enseignements de spécialité (EDS)'` (3 filtres), le dépôt n'en a que 2.

**Conséquence** : tout comportement décrit dans l'inventaire est basé sur le **code extrait du conteneur en cours** (via `inspect.getsource`), pas sur le code du dépôt.

**Build-context hôte** : `/srv/nexusreussite/rag-ui/compose/ingestor/` contient `api.py` (91 501 o, Jun 28 15:12) et de multiples `.bak_*`. **`docker save` des images ingestor + UI obligatoire avant tout rebuild** — il n'y a pas de registry et le build-context hôte est la seule source.

### 6.2 Endpoints exposés

| Méthode | Route | Auth | Description |
|---|---|---|---|
| GET | `/health` | Non | Healthcheck |
| GET | `/metrics` | Non | Prometheus |
| GET | `/collections` | Oui | Liste collections |
| **POST** | **`/search`** | Oui | Recherche vectorielle |
| POST | `/rag/query` | Oui | RAG avec génération LLM |
| POST | `/ingest`, `/ingest/urls`, `/ingest/upload-files`, `/ingest/drive` | Oui | Ingestion |
| GET/POST/DELETE/PATCH | `/admin/*` | Oui | Administration |

### 6.3 Sémantique de `score_threshold` et `maths_premiere_fallback` (D-07)

#### `score_threshold`

Comportement **extrait du code en cours d'exécution** : si un hit a une distance Chroma (cosine) > `score_threshold`, il est exclu. `null` = pas de seuil.

**Répliqué par `retrieval_api.py` (pilote) ?** Non. **Risque de régression au cutover.**

#### `maths_premiere_fallback`

Comportement **extrait du code prod** : quand `section=maths_premiere` et que `rag_maths_premiere` est vide (ce qui est le cas), le système rabat sur `rag_education` avec filtres `{"matiere": "Mathématiques", "niveau": "Première", "groupe": "Enseignements de spécialité (EDS)"}`.

**Répliqué par `retrieval_api.py` (pilote) ?** Non. **Risque de régression.**

### 6.4 Hybride / Rerank / Citations

- **Hybride BM25/RRF** : code dans l'image, **non activé** dans `/search`.
- **Rerank CrossEncoder** : code présent, **non activé**.
- **Citations** : absentes de la réponse.
- **Filtres** : `filters` passé tel quel à ChromaDB `where`, non lié à un token signé.

---

## 7. Données et persistance

### 7.1 Volumes

| Volume | Taille | Contenu |
|---|---|---|
| `compose_rag_ui_chroma_data` | 204 MiB | Index ChromaDB |
| `compose_rag_ui_ollama_data` | 9,1 GiB | Modèles Ollama |
| `compose_rag_ui_admin_data` | 168 MiB | SQLite admin (`catalog.sqlite`) |
| `/srv/nexusreussite/rag-ui/data/uploads` | 5,4 MiB | Fichiers uploadés |

### 7.2 nexus-postgres-db (hors périmètre, R-02)

pgvector v0.8.2 installé, aucune table RAG. **Hors périmètre.**

### 7.3 Sauvegarde ChromaDB (D-10)

| Élément | Valeur |
|---|---|
| Script | `/srv/nexusreussite/rag-ui/backup_chroma.sh` |
| Planification | Cron `0 3 * * *` (quotidien, 03h) — **vérifié** |
| Mécanisme | `docker exec chroma tar czf` → `docker cp` → rétention 7 |
| Derniers backups | 2026-06-29 (119 MiB), 2026-06-30 (119 MiB) |
| **Restore testé ?** | **NON** — pas de procédure documentée |
| **Backup frais avant migration** | **EXIGÉ** |

### 7.4 Catalogue SQLite admin — non sauvegardé (I-11)

Le catalogue `catalog.sqlite` (168 MiB dans `compose_rag_ui_admin_data`) contient l'inventaire des documents ingérés. Il est **nécessaire** pour savoir quoi migrer. **Non sauvegardé automatiquement.**

**Must-fix pré-migration** : sauvegarder le catalogue avant toute opération de bascule. Ajouté aux préalables Phase 4.

---

## 8. Observabilité

Métriques Prometheus `/metrics` (public) : ingestion uniquement (`rag_local_ingest_*`). Pas de métriques de retrieval. Pas de scraper ni d'alertes côté RAG.

---

## 9. Diagramme du flux prod

```
Utilisateur → nginx (TLS) → Streamlit (:18501) → /api/ → ingestor (:18001)
                                                              │
                                                    ┌─────────┼─────────┐
                                                    ▼                   ▼
                                              Ollama (:11434)    ChromaDB (:8000)
                                              nomic-embed 768d   HNSW cosine
                                                    │                   │
                                                    └─────────┬─────────┘
                                                              ▼
                                                    {hits[{id, metadata, document, score}],
                                                     score_threshold, maths_premiere_fallback}
```

Pour `/rag/query` : + `Ollama qwen2.5:1.5b` pour générer la réponse.

---

## 10. Écarts prod ↔ dépôt

| Composant | Prod | Dépôt | Écart |
|---|---|---|---|
| **Code ingestor** | 91 501 octets, build 28/06 | 90 357 octets | **DIVERGENT** (I-05) |
| **Embedding** | nomic-embed-text **768 dim** | e5-large **1024 dim** | **INCOMPATIBLE** |
| **Store** | ChromaDB 1.1.1 | pgvector | **DIFFÉRENT** |
| **Hybride/Rerank** | Non activé | Non branché au pilote | Inactif partout |
| **LLM génération** | qwen2.5:1.5b | `answer_generation_allowed: false` | Prod active, pilote interdit |
| **Auth** | Token Bearer partagé | HMAC-SHA256 par profil | Mécanisme ≠ |
| **`score_threshold`** | Supporté | **Non répliqué** | Régression potentielle |
| **`maths_premiere_fallback`** | Actif (3 filtres) | **Non répliqué** | Régression potentielle |
| **`section` routing** | `COLLECTION_MAP` dans code prod | Pas d'équivalent dans `retrieval_api.py` | Régression |
| **Table pgvector** | N'existe pas | Déclarée dans code | Absente |

---

## 11. Capacité machine (D-09)

| Ressource | Total | Utilisé | Disponible |
|---|---|---|---|
| **RAM** | 64 GiB | 6,7 GiB | **55 GiB** |
| **CPU** | 12 cœurs | load avg 0.47 | ~11 libres |
| **Disque** | 929 GiB | 695 GiB | **188 GiB** (79 %) |

Run parallèle (prod + e5 + pgvector dédié) : **possible**. Re-embedding en off-peak recommandé.

---

## 12. Baseline de qualité retrieval prod (D-11)

**Capturée** : `docs/audits/baseline_retrieval_prod.json` (v2, J-02/J-03 corrigée)
- **Timestamp** : 2026-06-30T17:49:24Z
- **Corpus de référence** : `rag_education` 7 181, `rag_francais_premiere` 5 948, `nsi_corpus` 4 716, `rag_math_correction` 67
- **Requêtes** : 16, couvrant **4 sections** : `education` (5), `nsi` (3), `francais_premiere` (4), `maths_premiere` (4)
- **Sections atteintes** : `education` → `rag_education` (4 hits/requête) ; `nsi` → `nsi_corpus` (4 hits/requête) ; `francais_premiere` → `rag_francais_premiere` (4 hits/requête) ; `maths_premiere` → `rag_education` avec **fallback actif, 0 résultats** (les filtres matière/niveau/groupe ne matchent rien)
- **Pas de texte de document** dans l'artefact (J-03 : `rights` non établis, contenu non droité exclu du versionnement)
- **Constat** : le fallback `maths_premiere` est fonctionnel (routing correct, `maths_premiere_fallback: true`) mais les filtres appliqués ne matchent aucun chunk (pas de contenu mathématiques dans `rag_education`)

**Note I-10** : corpus mouvant. Baseline à re-capturer **au plus près du cutover** contre un corpus **gelé**.

### Format exigé pour la baseline de cutover (K-03)

La baseline actuelle fige des scores et un nombre de hits. Pour mesurer la parité au cutover (recall ≥ baseline), la re-capture doit respecter ce format **par requête** :

```json
{
  "query": "...",
  "section_requested": "...",
  "collection_reached": "...",
  "chunk_ids_ordered": ["id1", "id2", "id3", "id4"],
  "scores": [0.28, 0.31, 0.33, 0.34]
}
```

La parité se mesure sur l'**intersection ordonnée des chunk_ids** : pour chaque requête, le moteur cible doit retrouver au moins les mêmes chunk_ids dans le top-k (ou des chunks jugés équivalents par un gold set).

---

## 13. Table de régression au cutover (D-07 + I-09 complétée)

| Fonctionnalité prod | Répliquée dans le pilote ? | Action |
|---|---|---|
| `score_threshold` (seuil distance) | Non | Implémenter dans `retrieval_api.py` |
| `maths_premiere_fallback` (3 filtres) | Non | **Non-fonctionnel par construction** (L-01) : les valeurs des filtres (`Mathématiques`, `Première`, `EDS`) ne matchent pas le schéma réel (`Numérique et sciences informatiques`, `Première et Terminale`). Ne pas répliquer tel quel ; le moteur cible doit filtrer sur un schéma de métadonnées cohérent. |
| `/rag/query` (génération LLM) | Non (`answer_generation_allowed: false`) | Cap G-3→G-1 (A-3), ADR distinct |
| Filtres libres dans body (`groupe`, `type_ressource`) | Non (pilote : `niveau` + `audience` liés au token) | Implémenter les filtres pertinents dans le pilote |
| Document complet dans la réponse | Oui (`retrieval_api.py` renvoie `text`) / **Non** (F-19 : `query_subject_agent` ne prend que `preview` 200 c) | Vérifier que le chemin de bout en bout expose le texte complet |
| Routing par `section` (education, nsi, francais_premiere…) | Non (`retrieval_api.py` : table unique `rag_chunks_pilote`) | Implémenter le routing par collection/section dans le moteur cible |
| Auth Bearer partagé (1 token, accès global) | Non (HMAC par profil élève) | **Refonte UI Streamlit** pour intégrer la signature HMAC, pas un simple « adapter » |
| **Rubriques UI** (`app_v2.py` `st.radio`) : Français 1re, Maths 1re, Éducation, Web3, Divers, Toutes | Non (le pilote n'a pas d'UI) | Répliquer les rubriques dans la future UI ou le cockpit |
| **Maths 1ère** : rubrique **cassée** (0 résultat, fallback non-fonctionnel par construction L-01) | — | Masquée dans l'UI (L-03) |
| **Web3** : rubrique **cassée** (`rag_web3` inexistante, auto-créée vide, L-02) | — | Masquée dans l'UI (L-03) |
| **Divers** : rubrique **cassée** (`rag_divers` inexistante, auto-créée vide, L-02) | — | Masquée dans l'UI (L-03) |

---

## 14. Contraintes de migration consolidées

### 14.1 Incompatibilité de dimension

768 dim (prod) ≠ 1024 dim (cible). Script `migrate_chroma_to_pgvector.py` **inopérant**. Re-embedding complet requis.

### 14.2 Re-chunking exige les documents GDrive originaux (I-03)

Le re-chunking heading-aware ne peut pas opérer sur des fragments déjà découpés extraits de ChromaDB. Il exige les **documents GDrive originaux** (PDF, Google Docs).

**Préalable bloquant** : vérifier l'accès au folder GDrive (`1-LXTKCv5XQ...`) et la validité des credentials du service account (`/srv/nexusreussite/rag-ui/creds/gdrive-sa.json`).

**Mode dégradé** (si GDrive indisponible) : re-split des fragments ChromaDB par taille (≤ 384 tokens), sans hiérarchie H1/H2/H3. Perte de qualité du chunking.

### 14.3 « education » n'est pas une unité migrable (I-08)

`rag_education` est un silo d'ingestion GDrive, pas une discipline. La migration impose une **décomposition par matière** : les 4 362 chunks classifiés → ventilés par `matiere` ; les 2 819 non classifiés → quarantaine ou reclassification.

### 14.4 Politique de gel du corpus (I-10)

Le corpus prod est mouvant (ingestion continue). La migration exige :
1. **Gel** : suspendre l'ingestion avant le cutover (désactiver `/ingest/*` ou couper le cron GDrive s'il existe).
2. **Snapshot** : backup ChromaDB frais + baseline D-11 re-capturée.
3. **Cutover** : fenêtre de maintenance pendant laquelle le corpus est stable.
4. **Dégel** : reprendre l'ingestion vers le nouveau moteur une fois la bascule validée.

### 14.5 Préalables de bascule (Phase 4)

1. **Backup frais** ChromaDB (D-10)
2. **Sauvegarde catalogue SQLite admin** (I-11, 168 MiB)
3. **`docker save`** des images **ingestor ET UI** actuelles (pas de registry) — les deux images contiennent du code divergent du dépôt (K-04)
4. **Vérification accès GDrive** (I-03)
5. **Gel du corpus** (I-10)
6. **Baseline D-11 re-capturée** au plus près du cutover

---

## 15. Politique de déduplication NSI (I-07)

Après migration, les collections NSI cibles (`rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`) agrégeront :
- Chunks NSI de `rag_education` (pop A, ~4 362 chunks GDrive, triés par niveau)
- Chunks NSI de `nsi_corpus` (4 716 chunks `rag-pedago`, re-ingérés par A-6)

**Stratégie de dédup** :
- **Clé de dédup** : `chunk_sha256` (identique = même contenu exact).
- **Priorité** : le corpus `rag-pedago` (gouverné, structuré, `notion`/`theme`/`capacities`) prévaut sur les chunks GDrive bruts quand le contenu se recouvre.
- **Arbitrage** : si deux chunks couvrent la même notion mais diffèrent en contenu (ex. un sujet bac GDrive vs une fiche de cours rag-pedago), les deux sont conservés avec des `type_doc` différents.
- **Mise en œuvre** : à exécuter lors de l'indexation (Phase 3, step 7) avec un gate de dédup avant `INSERT`.

---

## 16. Dette : création non gouvernée de collections ChromaDB (M-01)

Le code prod utilise `get_or_create_collection` : toute requête `/search` avec un `section` inconnu **crée automatiquement** une collection ChromaDB vide. C'est une mutation non gouvernée, contraire au principe d'arborescence maîtrisée.

### Collections vides constatées en prod (lecture seule, 30/06/2026)

| Collection | Origine | Fonctionnement | Statut |
|---|---|---|---|
| `rag_web3` | Auto-créée par le test L-02 | Diagnostic | **Supprimée** (A-CLEANUP-COLLECTIONS) |
| `rag_divers` | Auto-créée par le test L-02 | Diagnostic | **Supprimée** (A-CLEANUP-COLLECTIONS) |
| `rag_maths_premiere` | Auto-créée par le fallback `maths_premiere` | **Fonctionnement nominal** : chaque clic « Maths 1ère » dans l'UI déclenche `get_or_create_collection` → la prod s'auto-pollue | **Conservée** — la supprimer est inutile tant que la rubrique UI existe (A-CLEANUP-COLLECTIONS) |
| `ressources_pedagogiques_terminale` | Résiduelle | Inerte (`app.py` morte) | Suppression au décommissionnement (L-04) |

### Invariant cible

Le moteur gouverné **NE DOIT PAS** auto-créer de collection. La création de collections passe par la gouvernance (ADR, `rag_collections.yml`). Une rubrique UI n'est exposée que si sa collection cible est peuplée et passée par `quality → gate → review` (M-04).

---

## 17. Rubriques UI cassées — documentées, non masquées (L-03 requalifié)

**Décision lead (A-L03-REQUALIFIE)** : les 3 rubriques cassées de l'UI legacy (`app_v2.py`) ne sont **pas masquées**. L'UI legacy reste en l'état jusqu'à son remplacement. Les rubriques cassées sont documentées comme connues :

| Rubrique UI | Section | Collection atteinte | Hits | Cause |
|---|---|---|---|---|
| Maths 1ère | `maths_premiere` | `rag_education` (fallback) | 0 | Fallback non-fonctionnel par construction (L-01) |
| Web3 | `web3` | `rag_web3` (auto-créée vide) | 0 | Collection inexistante, auto-créée vide (M-01) |
| Divers | `divers` | `rag_divers` (auto-créée vide) | 0 | Collection inexistante, auto-créée vide (M-01) |

**Traitement** : différé au remplacement de l'UI (cockpit ou nouvelle interface, M-03).

---

## 18. Secrets identifiés (emplacements uniquement)

| Secret | Emplacement | Statut |
|---|---|---|
| `INGESTOR_API_TOKEN` | env conteneur + `.env` compose | **Rotation effectuée** 30/06/2026 |
| Credentials PostgreSQL | env de `nexus-postgres-db` | Hors périmètre. Rotation recommandée — décision et échéance à fixer avec le responsable Nexus (I-14). |
| `gdrive-sa.json` | `/srv/nexusreussite/rag-ui/creds/` | Service account GDrive |

---

## 19. Commandes non exécutées (R-03)

Aucune commande à risque de mutation n'a été envisagée, hormis : la rotation de token (A-8, autorisée) et le test L-02 qui a involontairement créé `rag_web3` et `rag_divers` (M-01, consigné).
