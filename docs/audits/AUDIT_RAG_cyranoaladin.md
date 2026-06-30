# Rapport d'audit — dépôt `cyranoaladin/RAG`

**Destinataire** : agent de codage Claude (remédiation).
**Auditeur** : revue senior RAG (conception, ingestion, retrieval, performance, métadonnées, agents, MCP, LLM locale).
**Commit audité** : `b483c2c` (Merge PR #35, lot 19), branche `main`.
**Date d'audit** : 30 juin 2026.
**Périmètre** : 100 % du dépôt (251 fichiers Python, ~46 900 lignes, 251 Markdown, 92 YAML, 105 fichiers de test).

> Principe directeur de ce rapport : **aucun « vert » n'est accepté sur déclaration**. Chaque constat est rattaché à une preuve (fichier:ligne, sortie de commande, ou comptage exécuté localement). Les sévérités sont : **BLOQUANT**, **MAJEUR**, **MOYEN**, **MINEUR**.

---

## 1. Méthodologie et preuves recueillies

Actions exécutées localement (et non simplement lues dans `docs/reports/`) :

| Action | Résultat empirique |
|---|---|
| Clone + `git rev-list --count HEAD` | 94 commits, 24→29 juin 2026, **une seule branche `main`** active. |
| `pytest` sur `packages/contracts` | **32 passés** / 0,17 s. |
| `pytest` sur `services/rag-pedago` (venv léger, sans torch ni psycopg) | **1086 passés** / 104 s, **zéro erreur d'import**. |
| `ruff check` sur `rag-pedago` | `All checks passed`. |
| `ruff check src scripts` sur `rag-engine` (ruff courant) | **25 erreurs** (majoritairement `UP031` percent-format). |
| Comptage chunks pilotes `rag-pedago/data/chunks` | 16 fichiers JSONL, **124 chunks** (conforme au README). |
| Inspection des clés d'une entrée d'embedding vs son sidecar `.meta.json` | **Divergence prouvée** (cf. §6). |

**Lecture clé** : les 1086 tests passent **sans le modèle d'embedding ni PostgreSQL installés**. Cela démontre empiriquement que la suite valide la **mécanique de gouvernance** (gates, manifestes, schémas, audits) et **non la qualité de retrieval** ni la cohérence vectorielle réelle. C'est le point aveugle central (cf. §13).

---

## 2. Résumé exécutif et verdict

Le dépôt est un **monorepo de plateforme RAG pédagogique** structuré en trois plans (`rag-pedago` contrôle, `rag-engine` données, `cockpit` futur SaaS) reliés par un contrat partagé `nexus-contracts`. La discipline d'ingénierie est réelle et au-dessus de la moyenne : ADR nombreux, gates de gouvernance testés, manifeste de revue, traçabilité par lots, lint propre côté `rag-pedago`.

**Mais l'objet « RAG opérationnel » n'est pas atteint.** Le dépôt contient **deux moteurs RAG distincts, parallèles et divergents**, dont aucun ne satisfait à lui seul les exigences métier déclarées (citation systématique, filtrage par matière, pertinence mesurée) :

1. un **moteur historique** (`rag-engine/src/ingestor`, ex-`rag-local`) : Ollama `nomic-embed-text` **768 dim**, ChromaDB, recherche hybride réelle (BM25 + RRF + CrossEncoder), LLM local `llama3.2` ;
2. un **pilote gouverné Nexus** : `sentence-transformers intfloat/multilingual-e5-large` **1024 dim**, pgvector, retrieval **purement vectoriel** (ni hybride, ni rerank, ni citation, ni filtre matière), HMAC.

Ces deux moteurs ont des **dimensions vectorielles incompatibles (768 ≠ 1024)** et des **stores incompatibles (Chroma ≠ pgvector)**. La « transition dual-engine » documentée est **inachevée** : chaque étape RAG (chunking, embeddings, recherche) existe **en double exemplaire divergent**.

**Verdict** : architecture de gouvernance solide, **chaîne RAG de bout en bout non convergée et non prouvée en qualité**. Le système n'est pas prêt pour un usage de production en l'état du pilote.

### Top 8 des constats par sévérité

| # | Constat | Sévérité |
|---|---|---|
| F-01 | Citations et droits **structurellement impossibles** dans le retrieval pilote (champs perdus entre chunking et indexation) alors que « citer chaque ressource » est une exigence métier | **BLOQUANT** |
| F-02 | Double moteur divergent : 768 vs 1024 dim, Chroma vs pgvector, deux chunkers, deux moteurs de recherche | **MAJEUR** |
| F-03 | **Aucune évaluation de qualité de retrieval** (recall@k / MRR / nDCG) ; `golden_queries/` vide ; gold sets non exploités par un harnais | **MAJEUR** |
| F-04 | Le contrat promet `hybrid=True, rerank=True` mais le pilote ne fait **ni hybride ni rerank** ; le filtre `matiere` n'est **pas appliqué** | **MAJEUR** |
| F-05 | **MCP totalement absent** : `services/mcp/__init__.py` est un placeholder vide | **MAJEUR** |
| F-06 | `retrieval_api.py` : **une seule connexion psycopg globale** partagée par des endpoints synchrones → bug de concurrence | **MAJEUR** |
| F-07 | Chunks ciblés à 750 « tokens estimés » > **fenêtre 512 tokens de e5** → troncature silencieuse à l'embedding | **MOYEN** |
| F-08 | Jeton HMAC sans **expiration / nonce / kid** (rejouable indéfiniment) ; ne lie que `niveau`+`audience` | **MOYEN** |

---

## 3. Cartographie architecturale

```
packages/contracts/         nexus-contracts (Pydantic) — contrat de retrieval, source de vérité
services/rag-pedago/         PLAN DE CONTRÔLE : taxonomie, référentiel, gates, ledger, agents
  ├─ agents/                 acquisition (orchestrator → level → subject) — séquentiel, sans LLM
  ├─ query_agents/           requête (orchestrator → level → subject) — context_only
  ├─ scripts/build_chunks.py CHUNKER A (750 tokens, regex)
  ├─ scripts/build_embeddings.py  e5-large 1024 dim
  ├─ services/mcp/           VIDE (placeholder)
  └─ data/chunks|embeddings/ 124 chunks/embeddings pilotes versionnés
services/rag-engine/         PLAN DE DONNÉES
  ├─ src/ingestor/api.py     MONOLITHE 2215 lignes — Ollama nomic-embed 768 dim, llama3.2, langchain
  ├─ src/ingestor/hybrid_search.py  BM25 + RRF + CrossEncoder (UNIQUEMENT ici)
  ├─ src/ingestor/pedagogical_chunker.py  CHUNKER B (500 tokens, heading-aware)
  ├─ scripts/index_pgvector.py   pgvector rag_chunks_pilote (1024 dim)
  ├─ scripts/retrieval_api.py    API /search vectorielle pure (1024 dim)
  └─ scripts/migrate_{chroma,qdrant}_to_pgvector.py  3 backends historiques
services/cockpit/            placeholder (doc only)
```

**Constat A-01 (MAJEUR)** — *Aucun service ne porte la chaîne RAG complète.* Le chunking et l'embedding « gouvernés » vivent dans `rag-pedago`, mais l'indexation et le retrieval dans `rag-engine/scripts/`, tandis qu'un **deuxième** chunking/embedding/retrieval complet et fonctionnel (hybride) vit dans `rag-engine/src/ingestor/`. La frontière « contrôle/données » de l'ADR-0001 est respectée pour le pilote mais **le moteur historique la court-circuite entièrement** (il chunk, embed, indexe et répond seul).

**Constat A-02 (MOYEN)** — `rag-engine/src/ingestor/api.py` fait **2215 lignes** (monolithe), `admin_api.py` 541, `database.py` 399. Le module `api.py` mélange embeddings, recherche, ingestion, routes admin. Maintenabilité dégradée ; surface de test difficile.

---

## 4. Ingestion — chunking

**Preuves** : `services/rag-pedago/scripts/build_chunks.py` (TARGET_TOKENS=750, OVERLAP_RATIO=0.12) ; `services/rag-engine/src/ingestor/pedagogical_chunker.py` (TARGET_MAX_TOKENS=500, OVERLAP_SENTENCES=1).

- **F-09 (MAJEUR — duplication)** : deux chunkers aux paramètres et stratégies différents. Le pilote (`build_chunks.py`) découpe par regex paragraphe/phrase et **n'est pas conscient de la hiérarchie de titres** ; le chunker du moteur historique l'est (arbre H1/H2/H3). Risque de dérive : un même corpus produit des chunks différents selon le chemin.
- **F-07 (MOYEN — correctness)** : l'estimation de tokens est `len(text.split()) * 1.3` dans les deux chunkers. Pour le français, le tokenizer e5 (sous-mots) produit nettement plus de tokens que de mots. Un chunk ciblé à **750 « tokens estimés »** peut dépasser **1000 tokens réels**, alors que `intfloat/multilingual-e5-large` a une **fenêtre de 512 tokens**. `SentenceTransformer.encode` **tronque par défaut** au-delà → la fin des longs chunks **n'est jamais embeddée**, perte de signal silencieuse. *Aucun test ne vérifie la longueur réelle des chunks contre le tokenizer.*
- **F-10 (MINEUR)** : `chunk_text` joint les parties par un simple espace (`" ".join`), effaçant la structure (sauts de paragraphe, listes), ce qui dégrade la lisibilité des `preview` et le rerank potentiel.

**Remédiation** : unifier sur un **seul chunker** (conserver le heading-aware), borner la taille via `model.tokenizer` réel (cible 256–384 tokens, marge sous 512), ajouter un test qui rejette tout chunk > seuil de tokens *mesurés*.

---

## 5. Embeddings et modèle local (LLM locale)

**Preuves** : `build_embeddings.py` (e5-large, 1024, `normalize_embeddings=True`, idempotence par `(chunk_sha256, model, dim, input_format)`) ; `ingestor/api.py:88-89` (`OLLAMA_URL`, `EMBED_MODEL=nomic-embed-text`) ; `ingestor/tasks.py:115` (`EMBED_DIM` défaut **768**) ; `infra/docker-compose.yml:69-70` (`EMBED_MODEL=nomic-embed-text`, `SMALL_LLM=llama3.2:latest`).

- **F-02 (MAJEUR — incohérence vectorielle)** : **deux modèles d'embedding incompatibles** coexistent.
  - Pilote Nexus : e5-large **1024 dim** (sentence-transformers, local, pas Ollama).
  - Historique : nomic-embed-text **768 dim** (Ollama).
  Les index ne sont **pas interchangeables** ; une requête embeddée par l'un est inexploitable contre l'index de l'autre. Le `rag_collections.yml` déclare pourtant **les deux backends** (collections Chroma `rag_nexus_*` ET table pgvector), entretenant l'ambiguïté.
- **F-11 (MOYEN)** : la convention de préfixe e5 (`passage:` / `query:`) est bien centralisée dans `nexus_contracts.embedding_utils` et réutilisée (point **positif**, `scrapers/embedding_utils.py` ré-exporte proprement). En revanche **aucun test ne vérifie que le préfixe a réellement été appliqué** dans les artefacts committés (seules la forme/dimension sont vérifiées).
- **F-12 (MINEUR — performance)** : `build_embeddings` n'expose ni `batch_size`, ni sélection de device (CPU/GPU), ni `fp16`. e5-large en CPU est lent ; pour passer du pilote (124) à l'échelle (≥ 420 notions × n chunks) c'est un goulot.
- **LLM locale (génération)** : `llama3.2` est câblé **uniquement** dans le moteur historique. Le pilote gouverné **n'a aucune génération** (`answer_generation_allowed: false`), ce qui est **conforme et voulu** — mais cela signifie que « LLM locale » au sens génération n'existe que dans le chemin non-gouverné.

---

## 6. Métadonnées et citations — le trou structurel

**Preuve directe (exécutée)** :
- Clés d'une entrée d'embedding committée : `['audience','chunk_id','chunk_sha256','dim','doc_id','matiere','model','niveau','notions','vector','voie']`
- Clés du sidecar `.meta.json` correspondant : `['audience','doc_id','matiere','niveau','notions','official','rights','source_label','source_uri','tenant','type_doc','voie']`

- **F-01 (BLOQUANT pour l'objectif métier)** : `source_label`, `source_uri`, `rights`, `type_doc`, `official` **existent dans le sidecar mais sont perdus** lors de `build_embeddings.py` (qui ne recopie que niveau/voie/audience/matière/notions). Conséquence en cascade :
  - le schéma `rag_chunks_pilote` (créé dans `index_pgvector.py`) **n'a pas de colonnes** `source_*`, `rights`, `type_doc`, `chunk_sha256`, `review_status` ;
  - `retrieval_api.py::_search_pgvector` ne peut donc **pas renvoyer de citation** ; `SearchResult` n'a pas de champ citation ;
  - le modèle `Citation` du contrat (`source_label`, `source_uri`, `rights` obligatoires) **n'est jamais peuplé** par le chemin pilote.
  Or le README §2.1 pose comme exigences : « citer chaque ressource avec une source et des droits » et « refuser quand les droits ne sont pas établis ». **Ces exigences sont structurellement insatisfaisables dans le pilote actuel.**
- **F-13 (MAJEUR — dérive contrat ↔ schéma)** : `rag_collections.yml::metadata_required` impose **15 champs** ; la table pilote en porte **6 filtrables** (niveau, voie, audience, matière, notions) + texte. La liste « metadata_required » est donc **aspirationnelle**, non vérifiée à l'indexation.
- **F-14 (MOYEN — dérive config ↔ code)** : `rag_collections.yml` déclare `pgvector.table: rag_chunks` (cible) et `legacy_table: rag_chunks_pilote`, mais **tout le code** (`index_pgvector.py`, `retrieval_api.py`) écrit/lit en dur `rag_chunks_pilote`. La table « cible » n'existe pas en code.

**Remédiation P0** : propager `source_label/source_uri/rights/type_doc/official/chunk_sha256` du sidecar jusqu'à l'entrée d'embedding **et** au schéma pgvector ; ajouter ces colonnes ; remplir `Citation` dans la réponse ; ajouter un test qui **échoue** si un chunk indexé n'a pas de `rights`/`source_uri`.

---

## 7. Indexation pgvector

**Preuve** : `services/rag-engine/scripts/index_pgvector.py`.

- **Positif** : index **HNSW** créé (`vector_cosine_ops`, `m=16`, `ef_construction=64`), cohérent avec l'opérateur `<=>` cosine et la normalisation des embeddings. Gate `ingestion_allowed` + manifeste de revue (`is_admitted` : `not_in_manifest`/`sha_mismatch`/`ok`). Bonne discipline.
- **F-15 (MOYEN — recall sous filtre)** : la recherche combine HNSW **et** `WHERE niveau=… AND audience…`. Sans `iterative scan` (pgvector ≥ 0.8) ni index B-tree sur `niveau`/`audience`, le filtre s'applique **après** l'ANN → risque de renvoyer **moins de `top_k`** résultats, voire de manquer des pertinents quand le corpus grossit. Inoffensif à 124 chunks, piège à l'échelle. Aucun index sur les colonnes de filtre.
- **F-16 (MOYEN — scalabilité)** : insertion **ligne par ligne** (`cur.execute` par entrée) au lieu de `executemany`/`COPY`. Acceptable à 124, lent à grande échelle.
- **F-17 (MINEUR — duplication)** : deux implémentations de `search()` coexistent — la démo dans `index_pgvector.py` (filtre `audience` **sans** repli `'tous'`) et `retrieval_api.py::_search_pgvector` (**avec** repli `'tous'`). Sémantiques divergentes pour la même intention → risque de dérive. **DETTE-16-ITEST-RETRIEVAL** (README) confirme l'absence de test d'intégration pgvector réel.
- **F-18 (MINEUR — précision)** : le vecteur est sérialisé par `",".join(str(v))`. `str(float)` peut produire de la notation scientifique ou perdre des décimales selon la plateforme ; préférer l'adaptateur binaire pgvector ou un format contrôlé.

---

## 8. Retrieval — pertinence, filtrage, hybridation

**Preuve** : `services/rag-engine/scripts/retrieval_api.py`.

- **F-04 (MAJEUR — écart contrat/implémentation)** : `nexus_contracts.RetrievalOptions` défaut `hybrid=True, rerank=True`, et `RetrievalRequest.to_payload_filters()` produit **6 filtres** (niveau, voie, matière, statut_enseignement, candidat, audience). L'API pilote **ignore tout cela** : recherche **vectorielle pure**, filtres **niveau + audience uniquement**. Donc :
  - **pas de filtre `matiere`** → un élève de Terminale en maths reçoit aussi des chunks de philosophie/NSI ; la pertinence métier (« pertinent pour leur niveau et leur statut ») est partielle.
  - **pas d'hybride / pas de rerank** dans le pilote, alors que `hybrid_search.py` (BM25+RRF+CrossEncoder) existe… mais **seulement dans le moteur historique** (768/Chroma), non branché au pilote.
- **F-19 (MOYEN)** : `query_subject_agent.assemble_context` ne récupère que `preview` (200 caractères, `LEFT(text,200)`) comme « texte ». Les agents context_only ne voient **jamais le chunk complet** → contexte appauvri pour tout usage aval.
- **F-20 (MINEUR)** : `assemble_context` accède aux clés (`r["matiere"]`, `r["notions"]`…) sans `.get` → `KeyError` si la forme de réponse évolue. Couplage fort non défensif.

**Remédiation** : faire converger le retrieval sur **un** moteur ; appliquer les 6 filtres (a minima `matiere`) ; rebrancher RRF + CrossEncoder rerank sur le store cible 1024 dim ; renvoyer le chunk complet + citation.

---

## 9. Agents (acquisition et requête)

**Preuve** : `agents/{base,orchestrator,level_agent,subject_agent}.py`, `query_agents/*`.

- **F-21 (MOYEN — « multi-agents » nominal)** : les « agents » sont des **classes procédurales séquentielles** (orchestrator → level → subject → notion), **sans LLM, sans boucle agentique, sans tool-calling, sans parallélisme, sans backoff**. C'est une orchestration hiérarchique déterministe, pas un système multi-agents au sens ADR-0005. Le label « agentique » est généreux. *(Ce n'est pas un défaut en soi — c'est sain et testable — mais la documentation surcharge sémantiquement le terme.)*
- **F-22 (MOYEN — performance)** : `agents/base.py::check_staging_allowed/check_ingestion_blocked` **relisent et reparsent le YAML du contrat à chaque appel** (idem dans tous les scripts de gate). En boucle sur 420 notions, c'est de l'I/O et du parsing répétés inutiles. Mettre en cache la lecture du contrat.
- **F-23 (MINEUR — robustesse incohérente)** : `agents/base.py` appelle `yaml.safe_load` **sans `try/except`** (peut lever sur YAML malformé), alors que `build_chunks.py`/`build_embeddings.py`/`index_pgvector.py` enveloppent toujours dans `try/except`. Comportement de gate **divergent** selon le point d'entrée.
- **F-24 (MINEUR)** : `query_subject_agent.search_api` utilise `requests` synchrone, `timeout=30`, **sans session réutilisée ni retry**. Acceptable en pilote, à durcir.

---

## 10. MCP — absent

**Preuve** : `services/rag-pedago/services/mcp/__init__.py` contient uniquement `"""Future MCP service package."""`. Aucune occurrence de `fastmcp`, `mcp.server`, `McpServer`, `@mcp` dans le code.

- **F-05 (MAJEUR — fonctionnalité demandée manquante)** : **aucune implémentation MCP**. Pas de serveur MCP, pas d'outils exposés (`search`, `get_chunk`, `list_collections`…), pas de schéma d'outil. Le retrieval n'est accessible que via l'API HTTP `/search`. Compte tenu de l'intérêt explicite pour MCP, c'est un manque de premier plan.

**Remédiation** : exposer le retrieval gouverné en **serveur MCP** (transport stdio + HTTP/SSE), outils en **lecture seule** dérivés du contrat (`retrieve(profile_token, query, k)` → `RetrievalResponse`), gating sur `runtime_api_allowed`, jamais d'outil d'écriture. Tests de contrat MCP basés sur les golden queries.

---

## 11. Performance et efficacité

| ID | Constat | Sévérité |
|---|---|---|
| F-06 | `retrieval_api.py` : **`state.conn = psycopg.connect(...)` unique et global**, partagé par un endpoint `def search_endpoint` (synchrone, exécuté dans le threadpool FastAPI). Les connexions psycopg ne sont pas sûres en usage concurrent multi-thread → corruption d'état / erreurs sous charge. **Manque un `psycopg_pool.ConnectionPool`.** | **MAJEUR** |
| F-25 | `model.encode` exécuté **par requête, de façon synchrone**, bloque un worker du threadpool ; pas de cache d'embedding de requête, pas de batching. (Le moteur historique, lui, a un cache Redis — `embedding_service.py` — non réutilisé par le pilote.) | MOYEN |
| F-16 | Indexation ligne-par-ligne (cf. §7). | MOYEN |
| F-15 | Pas d'index B-tree sur les colonnes de filtre ; recall HNSW sous filtre à l'échelle. | MOYEN |
| F-22 | Relecture/parse YAML du contrat à chaque gate. | MOYEN |
| F-12 | Embeddings sans batch/device tuning. | MINEUR |
| F-26 | `vector <=> %s::vector` apparaît **deux fois** dans la requête (calcul de similarité + ORDER BY) avec le vecteur inliné deux fois → double calcul potentiel et payload SQL volumineux. | MINEUR |

---

## 12. Sécurité

**Preuve** : `nexus_contracts/profile_auth.py`, `retrieval_api.py`, defaults DSN.

- **Positifs** : HMAC-SHA256 avec `hmac.compare_digest` (anti timing), validation stricte du token par regex, `PROFILE_SECRET` vide → **500** (refuse de démarrer en clair), gating `server_start_allowed`+`runtime_api_allowed`, aucune route d'écriture exposée, aucun secret committé, `.env.example` sans secret réel.
- **F-08 (MOYEN)** : jeton HMAC **sans `exp`, sans `nonce`/`jti`, sans `kid`** → **rejouable indéfiniment**, pas de rotation de clé, pas de révocation. À durcir avant prod (ajouter `exp` + horloge, voire fenêtre de validité).
- **F-27 (MOYEN — surface de spoofing)** : le token ne lie que `niveau`+`audience` (dataclass `profile_auth.StudentProfile`), alors que le contrat `RetrievalRequest` porte 6 dimensions. Tant que l'API ne filtre que sur niveau+audience c'est cohérent ; mais **si** l'on ajoute le filtre `matiere`/`candidat` (recommandé en F-04) **en le prenant du corps de requête non signé**, le client pourra élargir/altérer son périmètre. Toute dimension de filtrage doit être **liée au token signé**, pas lue du corps.
- **F-28 (MINEUR)** : DSN par défaut `postgresql://nexus:nexus@localhost:5433/nexus_rag` (identifiants faibles) en dur comme valeur par défaut dans `index_pgvector.py` et `retrieval_api.py`. Acceptable en dev (override `PG_DSN`), mais à ne jamais laisser fuiter en prod ; ajouter un garde-fou refusant les creds par défaut hors `APP_ENV=local`.
- **F-29 (MINEUR)** : deux définitions du nom `StudentProfile` (`student_profile.py` modèle Pydantic complet ↔ `profile_auth.py` dataclass à 2 champs). Collision de nom prêtant à confusion ; renommer la dataclass (ex. `VerifiedProfile`).

---

## 13. Tests et évaluation de la qualité de retrieval

**Preuve** : 1086 tests pedago + 32 contracts **passent sans modèle ni DB** ; `tests/golden_queries/` ne contient qu'un `.gitkeep` ; `gold_set_{nsi,nexus,mfai}.json` existent (questions + `relevant_keywords`) mais **le seul code qui les référence est `database.py`** (colonnes de stockage de métriques : `ndcg`, `avg_latency_ms`, `gold_set_version`), **pas un harnais d'évaluation**.

- **F-03 (MAJEUR — point aveugle qualité)** : il n'existe **aucune mesure de qualité de retrieval** (recall@k, MRR, nDCG, précision) **calculée** dans le dépôt. Les gold sets sont des données dormantes ; `golden_queries/` est vide. La suite de tests valide la **gouvernance et les schémas**, jamais la **pertinence**. C'est précisément ce que `AGENTS.md` interdit (« une métrique doit mesurer la substance, pas la présence »). Le « vert » massif (1086) **ne prouve pas que le RAG retrouve les bons passages**.
- **F-30 (MOYEN)** : les tests de `build_embeddings`/`build_chunks` valident la **forme** des artefacts committés (dimension, présence), pas la régénération réelle ni l'application effective du préfixe e5. Si les artefacts committés étaient faux, les tests resteraient verts.
- **F-31 (MOYEN)** : pas de test d'intégration `index_pgvector` ↔ pgvector réel (DETTE-16, reconnue), donc le chemin d'indexation+recherche **n'est jamais exécuté de bout en bout** en CI.

**Remédiation P1** : créer un harnais d'éval qui (1) reconstruit l'index pgvector sur un fixture, (2) exécute les golden queries, (3) calcule recall@k/MRR/nDCG, (4) **échoue** sous un seuil. Peupler `golden_queries/` (≥ 20 requêtes par matière pilote avec chunk_ids attendus). Ajouter un service pgvector éphémère en CI (`docker-compose.pgvector.yml` existe déjà).

---

## 14. CI/CD et outillage

**Preuve** : `.github/workflows/ci.yml` (racine) + workflows `rag-engine/.github/workflows/{ci,ci-smoke-compose,codeql-security,obs-smoke}.yml` ; `scripts/check-governance-locks.sh` + baseline 18 entrées ; `pyproject.toml` par service.

- **Positifs** : CI multi-jobs, CodeQL, smoke compose, garde-fou de verrous de gouvernance comparé ligne-à-ligne, CI locale (`scripts/ci-local.sh`).
- **F-32 (MOYEN — divergence d'outillage)** : versions divergentes entre services (`rag-pedago` : pydantic 2.13.4, mypy 2.1.0, pytest 9.1.1, ruff 0.15.19 ; `rag-engine` doit rester **compatible Python 3.9** au runtime pour l'ingestor, d'où des `per-file-ignores` `UP007/UP017/UP038`). Reconnu (README 18.1) mais non résorbé : deux régimes de typage/lint dans un même monorepo.
- **F-33 (MINEUR)** : `ruff` courant relève **25 erreurs** sur `rag-engine/src` (surtout `UP031` percent-format dans `hybrid_search.py`, etc.). Sous le ruff **épinglé** du service ces règles passent ; mais cela confirme un code de style ancien dans le moteur historique.
- **F-34 (MINEUR — artefacts de travail committés)** : présence de `patch-ci.diff`, `patch-ci-smoke.diff`, `patch-metrics-quickcheck.diff`, `patch-readme-metrics.diff`, `github_push.sh`, `rag-ui-...-tree-20260613_222121.txt` dans `rag-engine/` — résidus de développement à nettoyer du versionnement.

---

## 15. Observabilité

**Preuve** : `ingestor/metrics.py` (prometheus_client : Counter/Histogram, registry singleton), `infra/prometheus/*`, `docs/observability.md`.

- **Positif** : le moteur historique est instrumenté (Prometheus, règles d'alerte, smoke obs).
- **F-35 (MOYEN)** : le **chemin pilote** (`retrieval_api.py`) n'a **aucune métrique** (latence de recherche, taux 401/503, nb résultats, hit/miss). Pas de logging structuré de la latence. L'observabilité existe sur le moteur qu'on cherche à déprécier, pas sur le pilote cible.

---

## 16. Documentation et reproductibilité

- **Positif** : documentation exceptionnellement dense (README racine de 44 ko honnête sur ses dettes §18, 12 ADR racine, 47 rapports de lots, ADR par service). La traçabilité décisionnelle est un atout réel.
- **F-36 (MOYEN — reproductibilité)** : le **`requirements.lock` racine (272 lignes) est pollué** par des paquets système Ubuntu (`Brlapi`, `cupshelpers`, `dbus-python`, `command-not-found`, `systemd`…). C'est un `pip freeze` d'environnement, **pas un lock de projet** : non reproductible, trompeur. *(Les locks par service sont propres : `rag-engine/requirements.lock` = 175 lignes, 0 paquet système.)* Supprimer/refaire le lock racine via un outil déterministe (`pip-compile`/`uv`).
- **F-37 (MOYEN — dérive doc/état)** : incohérences reconnues mais persistantes : `AGENTS.md` impose la nomenclature tenant `{population}_{niveau}` alors que le code/ADR-0003 utilise tenant=niveau + filtre `audience` ; `pedago_interface_contract.yml` porte `status: metadata_only_interface_contract` alors que `ingestion_allowed/runtime_api_allowed/server_start_allowed` sont **`true`** ; `.env.example` pedago référence `QDRANT_URL`/`REDIS_URL` alors que `qdrant_allowed: false` et que le pilote est pgvector. Un lot de consolidation documentaire est dû.
- **F-38 (MINEUR)** : 3 backends vectoriels ont coexisté (Chroma, Qdrant, pgvector — cf. `migrate_*_to_pgvector.py`). Le churn d'infrastructure n'est pas entièrement résorbé dans la config (`rag_collections.yml` déclare encore Chroma).

---

## 17. Registre de dettes consolidé

| ID | Dimension | Sévérité | Preuve |
|---|---|---|---|
| F-01 | Citations/droits impossibles (pilote) | **BLOQUANT** | clés embedding vs sidecar ; schéma `rag_chunks_pilote` |
| F-02 | Double modèle 768/1024 + Chroma/pgvector | **MAJEUR** | `tasks.py:115`, `build_embeddings.py`, `rag_collections.yml` |
| F-03 | Aucune éval qualité retrieval | **MAJEUR** | `golden_queries/` vide ; grep gold_set |
| F-04 | Ni hybride ni rerank ni filtre matière (pilote) | **MAJEUR** | `retrieval_api.py`, contrat `RetrievalOptions` |
| F-05 | MCP absent | **MAJEUR** | `services/mcp/__init__.py` |
| F-06 | Connexion psycopg unique partagée | **MAJEUR** | `retrieval_api.py` lifespan/endpoint |
| A-01 | Aucun service ne porte la chaîne complète | MAJEUR | cartographie §3 |
| F-09 | Deux chunkers divergents | MAJEUR | `build_chunks.py` vs `pedagogical_chunker.py` |
| F-07 | Chunks > fenêtre 512 → troncature | MOYEN | `TARGET_TOKENS=750`, e5 512 |
| F-08 | HMAC sans exp/nonce/kid | MOYEN | `profile_auth.py` |
| F-13 | metadata_required non appliqué | MOYEN | `rag_collections.yml` vs schéma |
| F-14 | Table cible `rag_chunks` non utilisée | MOYEN | config vs code |
| F-15 | Recall HNSW sous filtre / pas d'index B-tree | MOYEN | `index_pgvector.py` |
| F-16 | Insertion ligne-par-ligne | MOYEN | `index_pgvector.py` |
| F-19 | Contexte limité au preview 200c | MOYEN | `_search_pgvector`, `assemble_context` |
| F-22 | Re-parse YAML du contrat à chaque gate | MOYEN | `agents/base.py` et gates |
| F-25 | encode synchrone, sans cache requête | MOYEN | `retrieval_api.py` |
| F-27 | Filtres non liés au token (si étendus) | MOYEN | `profile_auth` vs contrat |
| F-30 | Tests embeddings = forme, pas substance | MOYEN | `test_build_embeddings.py` |
| F-31 | Pas d'itest pgvector e2e | MOYEN | DETTE-16 |
| F-32 | Divergence outillage / py39 vs py311 | MOYEN | pyproject par service |
| F-35 | Pilote non instrumenté | MOYEN | `retrieval_api.py` |
| F-36 | requirements.lock racine pollué | MOYEN | 272 lignes, paquets système |
| F-37 | Dérive doc/état (tenant, status, env) | MOYEN | AGENTS.md, contrat, .env.example |
| A-02 | Monolithe api.py 2215 lignes | MOYEN | `wc -l` |
| F-10 | Chunks joints par espace | MINEUR | `build_chunks.py` |
| F-11 | Préfixe e5 non testé sur artefacts | MINEUR | tests |
| F-12 | Embeddings sans batch/device | MINEUR | `build_embeddings.py` |
| F-17 | Deux `search()` divergents | MINEUR | `index_pgvector.py` vs API |
| F-18 | Sérialisation vecteur via str(float) | MINEUR | `index_pgvector.py` |
| F-20 | Accès clés non défensif | MINEUR | `assemble_context` |
| F-21 | « Multi-agents » nominal | MINEUR | `agents/*` |
| F-23 | Gate base.py sans try/except | MINEUR | `agents/base.py` |
| F-24 | requests sans session/retry | MINEUR | `query_subject_agent.py` |
| F-26 | Double `<=>` dans la requête | MINEUR | `retrieval_api.py` |
| F-28 | DSN par défaut faible | MINEUR | scripts |
| F-29 | Collision de nom `StudentProfile` | MINEUR | contracts |
| F-33 | 25 lint ruff (moteur historique) | MINEUR | `ruff check` |
| F-34 | Artefacts de travail committés | MINEUR | `rag-engine/patch-*.diff` |
| F-38 | Config Chroma résiduelle | MINEUR | `rag_collections.yml` |

---

## 18. Backlog de remédiation priorisé (pour l'agent de codage)

> Convention : un lot = une branche = une PR = un rapport `docs/reports/lot_<n>_*.md` (cf. `AGENTS.md`). Ne pas lever de verrou de gouvernance sans ADR. Toute correction doit être **prouvée** (test rouge→vert, sortie de commande dans le rapport).

### P0 — Décision d'architecture (préalable, sans quoi le reste est instable)

- **P0-1** : Trancher par ADR la **convergence dual-engine**. Décision attendue : un seul modèle d'embedding (recommandation : conserver e5-large 1024 dim, multilingue FR, déjà gouverné) + un seul store (pgvector). Déprécier/archiver le chemin nomic-embed/Chroma **ou** le documenter comme legacy figé et non-cible. Sortie : ADR + suppression des déclarations Chroma de `rag_collections.yml` (F-02, F-14, F-38).
- **P0-2** : **Restaurer la chaîne de citation** (F-01). Propager `source_label/source_uri/rights/type_doc/official/chunk_sha256` du sidecar → entrée d'embedding → colonnes pgvector ; remplir `Citation` dans la réponse ; **test bloquant** : tout chunk indexé sans `rights` ou `source_uri` fait échouer la CI. *Critère de Done : une requête `/search` renvoie au moins un résultat avec citation complète, prouvé par sortie.*

### P1 — Pertinence et qualité (cœur RAG)

- **P1-1** : Harnais d'**évaluation de retrieval** (F-03, F-31) : fixture pgvector éphémère en CI (`docker-compose.pgvector.yml`), reconstruction de l'index, exécution des golden queries, calcul recall@k/MRR/nDCG, seuil bloquant. Peupler `golden_queries/` (≥ 20 req/matière avec `chunk_id` attendus). *Done : métriques imprimées + seuil testé.*
- **P1-2** : Appliquer le **filtre `matiere`** (a minima) et les dimensions du contrat, **liés au token signé** (F-04, F-27). Étendre `profile_auth` pour signer aussi `matiere` (ou un scope), refuser tout filtre venu du corps non signé.
- **P1-3** : Rebrancher **hybride (BM25/RRF) + rerank CrossEncoder** sur le store cible 1024 dim (F-04). Réutiliser `hybrid_search.py` adapté à pgvector au lieu de Chroma.
- **P1-4** : **Unifier le chunker** (F-09) sur la version heading-aware, **borner par tokens mesurés** via `model.tokenizer` (cible ≤ 384) (F-07) ; test rejetant tout chunk > seuil mesuré (F-30).

### P2 — Robustesse, performance, surface MCP

- **P2-1** : **Pool de connexions** psycopg (`psycopg_pool.ConnectionPool`) dans `retrieval_api.py` (F-06) ; instrumenter la latence/codes retour (Prometheus) (F-35).
- **P2-2** : **Serveur MCP** lecture seule dérivé du contrat (F-05) : outil `retrieve(profile_token, query, k)`, gating `runtime_api_allowed`, aucun outil d'écriture, tests de contrat MCP sur golden queries.
- **P2-3** : Indexation **batch/COPY** + index B-tree sur colonnes de filtre + activer iterative scan pgvector (F-15, F-16) ; cache d'embedding de requête (réutiliser le Redis de `embedding_service.py`) (F-25).
- **P2-4** : Cache de lecture du contrat de gouvernance (F-22) ; uniformiser le `try/except` des gates (F-23).

### P3 — Hygiène et cohérence documentaire

- **P3-1** : Régénérer un **`requirements.lock` racine propre** (déterministe) (F-36) ; nettoyer les `patch-*.diff` et fichiers de travail (F-34).
- **P3-2** : Lot de **consolidation documentaire** (F-37) : aligner `AGENTS.md` (tenant), le `status` du contrat, `.env.example` (retirer Qdrant/Redis si non utilisés) sur l'état réel du code/ADR.
- **P3-3** : Renommer la dataclass `StudentProfile` de `profile_auth` (F-29) ; résorber les 25 lint du moteur historique ou figer son périmètre (F-33) ; refactor incrémental de `api.py` (F-A02).

---

## 19. Synthèse pour l'agent

Le dépôt est **fort en gouvernance, faible en RAG opérationnel prouvé**. Avant toute nouvelle fonctionnalité : trancher la convergence dual-engine (P0-1), rétablir les citations (P0-2), puis instrumenter la qualité (P1-1). Tant que F-01, F-03 et F-04 ne sont pas levés, **aucune affirmation de « RAG fonctionnel » n'est démontrable** : le chemin gouverné ne cite pas, ne filtre pas par matière, ne fait ni hybride ni rerank, et n'est mesuré par aucune métrique de pertinence. Les 1086 tests verts attestent la mécanique de contrôle, **pas** la performance de recherche — distinction à maintenir explicitement dans tout rapport de lot ultérieur.
