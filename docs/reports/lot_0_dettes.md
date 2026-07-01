# Dettes identifiées — Lot 0

## Tests pré-existants en échec

### 1. `test_real_draft_guard::test_valid_fixture_passes_and_invalid_fixtures_fail`

- **Symptôme** : `AssertionError: assert 'ready_for_human_locked_metadata_validation' == 'blocked'`
- **Antériorité prouvée** : test exécuté sur le commit parent `e16cbed` (avant Lot 0), résultat identique : `FileNotFoundError` (fixture absente) puis assertion échouée.
- **Cause probable** : fixture `metadata_candidate.valid.jsonl` manquante ou logique de statut évoluée sans mise à jour du test.
- **Action** : dette pré-existante, à corriger dans un lot dédié.

### 2. `test_real_draft_unlock_gate` (INTERNALERROR pytest)

- **Symptôme** : monkey-patch de `Path.exists()` interfère avec le fonctionnement interne de pytest, provoquant un `INTERNALERROR`.
- **Antériorité prouvée** : test exécuté sur le commit parent `e16cbed`, même INTERNALERROR.
- **Cause** : le monkeypatch global de `Path.exists()` affecte les appels de pytest à `Path.exists()` pour la gestion du tmpdir et du traceback.
- **Action** : dette pré-existante, à corriger par scoping du monkeypatch.

## Résolution monorepo `nexus-contracts`

- `nexus-contracts` n'est pas publié sur PyPI ; il s'installe en éditable depuis `packages/contracts/`.
- La CI et `make install` gèrent l'installation dans l'ordre correct.
- **Amélioration future (Phase 6)** : industrialiser via `uv workspace` ou équivalent pour une résolution monorepo native.

## Commit ROADMAP poussé sur `main` hors PR

- Le commit `93f5ba8` (`docs: add project roadmap`) a été poussé directement sur `main`, en écart avec la règle « un lot = une branche = une PR ».
- Écart de process noté. L'historique n'est pas réécrit.

## Erreurs d'import rag-engine (préexistantes, LOT 21)

**Date de constat** : 30 juin 2026 (LOT 21)
**Statut** : préexistant, non régressé par LOT 21
**Antériorité prouvée** : ces erreurs d'import existaient sur le commit parent `31020f8` (main, merge PR #36). L'exécution locale de `pytest tests/test_retrieval_contract_adapter.py` sur ce commit retourne `ModuleNotFoundError: No module named 'nexus_contracts'`. Même résultat pour les 9 autres modules (dépendances `chromadb`, `langchain`, `google.oauth2` etc. non installées localement). En CI (GitHub Actions run `28470205150`, job `84380555833`), ces tests passent car les dépendances sont installées dans le venv CI.

Les 10 modules de test suivants échouent à l'import en environnement local (dépendances manquantes). En CI, ils passent car les dépendances sont installées.

| Module de test | Dépendance manquante | Cause |
|---|---|---|
| `test_admin_api.py` | `chromadb`, `langchain` | Moteur historique, dépendances lourdes |
| `test_admin_api_edges.py` | idem | idem |
| `test_admin_health_reindex.py` | idem | idem |
| `test_backfill_dedicated_collection.py` | idem | idem |
| `test_drive_sync.py` | `google.oauth2` | Intégration GDrive |
| `test_metrics.py` | `prometheus_client` | Instrumentation |
| `test_metrics_gating.py` | idem | idem |
| `test_retrieval_api.py` | `psycopg` | pgvector, pas installé localement |
| `test_retrieval_contract_adapter.py` | `nexus_contracts` | Pas installé localement |
| `test_security_ip_allowlist.py` | `chromadb` | Moteur historique |

**Intention** : ces tests seront isolés ou remplacés à mesure que le moteur historique est décommissionné. Les tests v2 (`test_collection_config_v2.py`, `test_rag_collections_config.py`) n'ont pas ces dépendances.

## api.py — moteur historique en sursis (LOT 22a)

**Date de constat** : 30 juin 2026 (LOT 22a, S-04)
**Statut** : dette active, moteur à décommissionner
**Antériorité prouvée** : `api.py` (2215 lignes, monolithe Chroma/Ollama) existait dès le commit `b483c2c` (main, avant LOT 20). Constaté comme A-02 dans l'audit `AUDIT_RAG_cyranoaladin.md`.

`api.py` et `retrieval_contract_adapter.py` constituent le moteur historique. Ils lisent `rag_collections_legacy.yml` (v1) via `resolve_collection()`. Le code neuf utilise `resolve_collection_v2()` + `rag_collections.yml` (v2). Les deux mondes sont étanches (D-LEGACY-ISOLE, ADR-0013).

**Action** : décommissionner `api.py` quand le moteur gouverné (pgvector, e5-large) est opérationnel (post-LOT 25).

## Vigilance : partage potentiel de table rag_chunks (T-02, LOT 22a)

`rag_collections_legacy.yml` déclare `pgvector.table: rag_chunks`, la même table que le v2 va peupler dans l'instance pgvector dédiée. Cependant :
- Le legacy (`api.py`) tourne sur **Chroma**, pas sur pgvector. Il n'exécute **aucun INSERT dans `rag_chunks`** (`grep INSERT.*rag_chunks api.py` = 0, `api.py` n'importe pas `database.py`).
- `database.py` contient un `INSERT INTO rag_chunks` (ligne 153) mais n'est **pas appelé** par `api.py`.
- Le v2 écrit dans `rag_chunks` de l'instance pgvector **dédiée** (séparée de `nexus_prod`, A-1).
- **Aucun chemin legacy actif n'écrit dans `rag_chunks`.**

## Décision D-LEGACY-CI (LOT 22a, T-03)

Les tests `@pytest.mark.legacy_engine` restent **dans la CI** et doivent rester **verts** tant que `api.py` sert la prod (D-LEGACY-CI). Le marqueur isole le périmètre (legacy vs v2), il n'exclut pas de l'exécution. À décommissionner avec `api.py` (post-LOT 25). Un futur contributeur ne doit pas les désactiver en croyant le marqueur destiné à les exclure.

## Dettes LOT 22 (consignées à la ratification du manifest)

### R1 — Dédup fallback base-name : faux positifs possibles
Le fallback base-name (C23) suppose que deux fichiers même-nom même-dossier en formats différents sont le même document. Faux dans le cas limite de versions différentes (v1.pdf / v2.docx homonymes). Risque faible : le PDF (généralement le plus à jour) est gardé. Coût d'erreur : perte d'une variante, pas injection de faux.

### R2 — OCR : 30 PDFs scannés en holding list
30 PDFs sans couche texte sont en holding list (signal réel non ingéré). Hors-scope LOT 22. Un lot OCR ultérieur les récupérera.

### R3 — Chunker : proxy mots×1.3 non unifié
Le LOT 22 utilise le tokenizer e5 réel (budget 480) en local. Le `pedagogical_chunker.py` partagé garde le proxy `len(words)*1.3` défaillant (F-07). Unification au LOT 25.

### R4 — notions[] vide sur 100 % des chunks LOT 22
**Date de constat** : 1er juillet 2026 (LOT 22)
**Statut** : dette active
**Impact** : aucun routage thématique possible ; le filtrage repose sur `collection` + `matiere` + `type_doc` uniquement. Les 22 518 chunks n'ont pas de dimension `notions`.
**Renvoi** : lot d'enrichissement dédié (heuristique nom/dossier ou classification LLM).

### R5 — Seuil de similarité (score_threshold)
**Date de constat** : 1er juillet 2026 (LOT 22, W-03). **RÉSOLU** le 1er juillet (LOT 24).
**Statut** : RÉSOLU
**Solution** : seuil rerank **+1.90** (score CrossEncoder, recalé FF-02b après suppression troncature 512 chars). Marge : plancher in +2.30, plafond out +1.51. 15/15 in conservé, 10/10 out rejeté. Implémenté dans `retrieval_v2.py`. **Provisoire** : lié au chunking actuel, à réviser après LOT 25.

### R6 — Hybride BM25/RRF + rerank CrossEncoder
**Date de constat** : 1er juillet 2026 (LOT 22, W-03). Mesuré le 1er juillet (LOT 24).
**Statut** : rerank **RÉSOLU** (CrossEncoder ms-marco-MiniLM-L-6-v2, écart 10.18). Hybride **DIFFÉRÉ** (pas abandonné).
**Rerank** : implémenté dans `retrieval_v2.py`. Écart in/out transformé de 0.05 à 10.18.
**Hybride** : inutile/nuisible sur corpus NSI mono-matière (DD-01 : collision lexicale inter-domaine). Code présent (`hybrid_search.py`) mais désactivé. À **RE-TESTER** quand le corpus deviendra multi-matières.

### R7 — review_status=needs_review sur 100 % des chunks, servables
**Date de constat** : 1er juillet 2026 (LOT 22, V-02/D-REVIEW)
**Statut** : dette active, décision tracée (D-REVIEW : mise en service sous autorité lead + revue a posteriori)
**Impact** : contenu non revu servi en retrieval. answer_generation_allowed=false atténue le risque.
**Renvoi** : revue lead (10 % par type_doc, avant LOT 25).

### R8 — Chunker heading-aware non implémenté → ré-ingestion LOT 25
**Date de constat** : 1er juillet 2026 (LOT 22, W-04). Enrichi LOT 24 (DD-02).
**Statut** : dette active. 187 chunks base64 quarantinés (lot 22b, quarantaine base64 du 1er juillet).
**Impact** : le LOT 22 utilise un split par phrases/tokens, PAS le chunker heading-aware cible. Les chunks devront être ré-ingérés au LOT 25. DD-02 prouve que les scores in-domain bas (+2.99 à +3.81) sont causés par le chunking (passage adjacent remonté plutôt que la définition), pas par un manque de contenu.
**Critère de succès LOT 25** (PRÉDICTION à valider) : les 4 questions faibles (clé étrangère, récursivité, jointure SQL, boucle while) doivent passer de +3 à > +5 après ré-ingestion heading-aware. Si non → investiguer.
**Renvoi** : LOT 25 (unification chunker + filtrage base64 + validation DD-02).

### R9 — requirements-ingestion.txt non versionné
**Date de constat** : 1er juillet 2026 (LOT 22, V-04)
**Statut** : dette active
**Impact** : sentence-transformers, psycopg, torch, python-docx, odfpy installés ad hoc (--user --break-system-packages), hors environnement reproductible. Le prochain run d'ingestion ne retrouvera pas l'état.
**Renvoi** : LOT 23 (fichier requirements-ingestion.txt versionné avec versions épinglées).
