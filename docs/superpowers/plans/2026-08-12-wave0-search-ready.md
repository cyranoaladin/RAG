# Wave 0 Search-Ready Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development
> for independent audits, strict Red-Green-Refactor for implementation, and
> superpowers:verification-before-completion before delivery.

**Goal:** Rendre les deux PDF Wave 0 interrogeables sur `/search/v2` via des
chunks page-aware, E5/reranker réels, scopes signés V2 et vingt requêtes HTTP.

**Architecture:** Le provider vérifié gouverne tokenisation, vecteurs et
provenance. Le scope signé V2 sépare cible élève et preuve curriculaire. Le
publisher et l'API utilisent les chemins gouvernés existants sur des bases
staging propres.

**Tech Stack:** Python 3.11+, Pydantic, psycopg 3, PostgreSQL 16, pgvector,
SentenceTransformers, FastAPI/uvicorn, pytest/testcontainers, ruff, mypy.

---

## Chunk 1: Chunking PDF et provenance

### Task 1: Mesures et chunking page-aware

**Files:**
- Create: `services/rag-engine/src/ingestor/publication_chunking.py`
- Create: `services/rag-engine/tests/test_pdf_page_aware_chunking.py`
- Modify: `services/rag-engine/src/ingestor/governed_publisher_v2.py`

- [ ] Mesurer pages/caractères/mots/chunk actuel des deux PDF sans journaliser le texte.
- [ ] Écrire les tests rouges PDF multi-pages, page longue, page courte, couverture, vide et hard split.
- [ ] Exécuter les tests ciblés et constater les échecs attendus.
- [ ] Ajouter `PublicationChunk` et le splitter page/token-aware minimal.
- [ ] Brancher les octets PDF réels dans le publisher et persister `page_start/page_end`.
- [ ] Vérifier que les tests Markdown historiques restent verts.

### Task 2: Provider d'embedding attesté

**Files:**
- Create: `services/rag-engine/src/ingestor/embedding_provider.py`
- Create: `services/rag-engine/tests/test_embedding_provider_provenance.py`
- Modify: `services/rag-engine/src/ingestor/governed_publisher_v2.py`
- Modify: tests publisher existants utilisant un embedder déterministe

- [ ] Écrire les tests rouges sur identité, dimension, cardinalité et faux provider canonique.
- [ ] Ajouter le protocole/provider déterministe explicitement debug.
- [ ] Ajouter le provider canonique constructible seulement depuis un artefact vérifié.
- [ ] Écrire `provider.model_id` dans `rag_chunks` et supprimer la constante déconnectée.
- [ ] Exécuter tests ciblés, ruff et mypy ciblés.

## Chunk 2: Modèles réels et ingestion propre

### Task 3: Matérialiser et vérifier les modèles

**Files:**
- Create: `services/rag-engine/scripts/materialize_model_artifact.py` si aucun outil compatible n'existe
- Create/Modify: tests ciblés des contrats modèle uniquement si un gap est démontré

- [ ] Inspecter cache local, espace disque et dépendances avant tout réseau.
- [ ] Matérialiser E5 hors Git sans symlink, produire manifest et inventaire déterministe.
- [ ] Vérifier, charger et valider dimension runtime/pgvector 1024.
- [ ] Matérialiser et vérifier le reranker canonique hors Git.
- [ ] Exécuter une inférence bornée réelle par modèle.

### Task 4: E2E ingestion réelle propre

**Files:**
- Create: `services/rag-engine/tests/integration/test_wave0_real_model_ingestion.py`
- Modify: `services/rag-engine/tests/integration/test_wave0_french_pgvector.py` ou extraction d'un harness partagé

- [ ] Écrire le test rouge de base propre avec vrai scope authorization et providers réels.
- [ ] Rejouer Worker A, LocalGitHub/LOT42 et Worker B pour les deux PDF.
- [ ] Vérifier chunks >1, pages complètes, modèle E5 partout, vecteurs 1024 non nuls.
- [ ] Calculer les statistiques tokenizer réelles sans imprimer les chunks.
- [ ] Vérifier zéro stub d'autorisation et zéro publication manuelle dans l'E2E principal.

## Chunk 3: Curriculum scope et registre signé V2

### Task 5: Étendre le contrat partagé

**Files:**
- Modify: `packages/contracts/src/nexus_contracts/retrieval.py`
- Modify: `packages/contracts/src/nexus_contracts/scope.py`
- Modify: `packages/contracts/src/nexus_contracts/__init__.py`
- Create/Modify: tests contrat/golden correspondants

- [ ] Écrire les tests rouges `seconde` cible + `troisieme` curriculum et filtres.
- [ ] Ajouter `RetrievalCurriculumScope` avec `extra=forbid`.
- [ ] Conserver le comportement V1 et exiger curriculum_scope pour V2.
- [ ] Ajouter `RetrievalScopeArtifactV2` target/evidence sans wildcard.
- [ ] Exécuter les tests du package contrat.

### Task 6: Registre identité et scopes Wave 0

**Files:**
- Create: deux artifacts JSON V2 sous `packages/contracts/src/nexus_contracts/artifacts/`
- Modify: `services/rag-engine/src/ingestor/identity_v2.py`
- Modify: `services/rag-engine/src/ingestor/retrieval_scope_v2.py`
- Modify: `services/rag-engine/src/ingestor/retrieval_v2_endpoint.py`
- Create: `services/rag-engine/tests/test_retrieval_scope_registry_v2.py`
- Create: `services/rag-engine/tests/test_retrieval_curriculum_scope.py`

- [ ] Écrire les tests rouges registre, digest, collection, cible et curriculum divergents.
- [ ] Généraliser le loader singleton vers un registre V1/V2 exact.
- [ ] Résoudre la collection depuis curriculum + evidence signée.
- [ ] Séparer target match et evidence match dans l'endpoint.
- [ ] Vérifier 200 Wave 0 et refus 403 croisés.

### Task 7: Catalogue staging étroit

**Files:**
- Create: `services/rag-engine/configs/staging/rag_collections_wave0.yml`
- Create/Modify: tests `collection_config`

- [ ] Écrire l'assertion rouge des deux activations exactes.
- [ ] Dériver le fichier staging du canonique sans modifier celui-ci.
- [ ] Vérifier `STAGING_INSTANCIATED_COLLECTIONS=2` et zéro activation inattendue.

## Chunk 4: API HTTP et recherches réelles

### Task 8: Acceptance HTTP authentifiée

**Files:**
- Create: `services/rag-engine/tests/integration/test_wave0_http_search.py`
- Modify: fixtures staging réutilisables si nécessaire

- [ ] Provisionner les schémas produit/review canoniques sur la DB acceptance.
- [ ] Lancer uvicorn sur un port localhost libre avec modèles preloadés et config staging.
- [ ] Tester BFF absent/invalide, identité absente/invalide/expirée et scope 403.
- [ ] Tester `/collections/v2` isolé par scope.
- [ ] Confirmer que le rôle student ne lit pas internal et que teacher le peut.

### Task 9: Dataset 10+10 et diagnostic de scores

**Files:**
- Create: `services/rag-engine/tests/fixtures/wave0_search_acceptance.yml`
- Extend: `services/rag-engine/tests/integration/test_wave0_http_search.py`

- [ ] Dériver dix requêtes naturelles et concepts attendus par PDF, sans copier le texte brut.
- [ ] Exécuter les vingt requêtes via la socket réelle.
- [ ] Pour chaque échec, collecter uniquement dense/lexical/RRF/rerank/final et diagnostiquer.
- [ ] Vérifier top hit, SHA, reviewed, citation/page, source path et concept.
- [ ] Vérifier zéro résultat nul et zéro fuite inter-collection.

### Task 10: Client officiel local

**Files:**
- Create: `scripts/rag_query.py`
- Create: tests CLI ciblés

- [ ] Écrire le test rouge de construction sûre des deux requêtes scopeées.
- [ ] Implémenter env URL/BFF/identité, validation de réponse et affichage borné.
- [ ] Vérifier qu'aucun secret ou token ne peut être imprimé.

## Chunk 5: Vérification et livraison

### Task 11: Vérifications fraîches et revue indépendante

- [ ] Exécuter ruff, mypy, unit et gouvernance PostgreSQL.
- [ ] Exécuter les acceptances modèles réels et HTTP réelles fraîches.
- [ ] Exécuter `bash scripts/ci-local.sh` et relever toute dette préexistante prouvée.
- [ ] Demander une revue code/sécurité indépendante et corriger tout finding important.
- [ ] Vérifier `git diff --check`, absence de poids/secrets/PII et métriques finales.
- [ ] Committer un vertical slice cohérent, pousser la branche et vérifier GitHub CI sans rendre PR #95 Ready.
