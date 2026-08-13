# Full Wave 0 Staging Ingestion Implementation Plan

> **For agentic workers:** Use strict Red-Green-Refactor, delegate independent
> audits, and run verification-before-completion before every success claim.

**Goal:** Produire puis ingérer le release set exact-grade 3e Maths/Français,
réconcilier pgvector avec ses manifests et rendre la readiness gouvernée.

**Architecture:** Les données versionnées (inventaire, currentness V2, mapping
fermé et manifests) deviennent l'autorité. Le resolver valide leur intersection
avec le catalogue, les profils et le programme sans SHA métier codé. Le batch
réutilise Worker A, LOT42, Worker B et les vrais modèles Search-Ready.

**Tech Stack:** Python 3.11+, Pydantic/dataclasses, YAML/JSON, psycopg 3,
PostgreSQL 16 + pgvector, pytest/testcontainers, ruff, mypy.

---

## Chunk 1 — Autorité release et resolver

### Task 1 — Inventaire exact et loaders stricts

**Files:**
- Create: `services/rag-pedago/data/releases/prerentree_2026_2027/wave0/wave0_candidate_inventory.json`
- Create: `services/rag-engine/src/ingestor/wave0_release.py`
- Create: `services/rag-engine/tests/test_wave0_release_authority.py`

- [ ] Écrire les tests rouges des digests, doublons, scope exact-grade et sets.
- [ ] Matérialiser l'inventaire déterministe depuis le catalogue scellé.
- [ ] Implémenter les loaders stricts et vérifier 1 Maths + 1 Français.
- [ ] Vérifier qu'aucun PDF ou texte extrait n'est versionné.

### Task 2 — Currentness V2 et mapping fermé

**Files:**
- Create: `services/rag-pedago/configs/prerentree_2026_2027/wave0_currentness_evidence_v2.yml`
- Create: `services/rag-engine/configs/mappings/eduscol_wave0_document_types.yml`
- Modify: `services/rag-engine/src/ingestor/verified_pedagogical_placement.py`
- Modify: `services/rag-engine/tests/test_wave0_verified_placement.py`

- [ ] Écrire les tests rouges : aucun SHA runtime, artifact hors release refusé,
  type inconnu refusé, digest/inventaire/currentness divergents refusés.
- [ ] Charger mapping, inventaire et preuve V2 au startup.
- [ ] Supprimer `_WAVE0_CURRENTNESS_SCOPE` et `_MAPPINGS` du runtime.
- [ ] Vérifier les faits catalogue/profile/programme/release sans fallback.

## Chunk 2 — Éligibilité et manifests

### Task 3 — Preflight batch complet

**Files:**
- Create: `services/rag-pedago/scripts/build_wave0_release.py`
- Create/Modify: tests ciblés rag-pedago et rag-engine
- Create outside Git: `wave0_pii_full_exact_3e_20260812.json`

- [ ] Écrire les tests rouges de partition exhaustive des candidats.
- [ ] Vérifier currentness officielle et byte identity en lecture seule.
- [ ] Scanner exactement les SHA uniques avec policy v5 et lier l'inventaire.
- [ ] Sceller les quatre liens PII : inventaire, corpus, policy et scanner.
- [ ] Résoudre droits par chemin scellé.
- [ ] Extraire/chunker les octets exacts avec le tokenizer E5 réel.
- [ ] Nommer chaque résultat noneligible sans arrêter le batch.

### Task 4 — Manifests release avant DB

**Files:**
- Create: `services/rag-pedago/data/releases/prerentree_2026_2027/wave0/maths_troisieme.release.json`
- Create: `services/rag-pedago/data/releases/prerentree_2026_2027/wave0/francais_troisieme.release.json`
- Create: `services/rag-pedago/data/releases/prerentree_2026_2027/wave0/wave0.release.json`
- Create/Modify: tests manifest

- [ ] Écrire les tests rouges de liens/digests/chunks/placements attendus.
- [ ] Générer les trois manifests déterministes sans vecteurs.
- [ ] Épingler E5 `e2c738…e22a` et reranker `bdcedc…fe1`.
- [ ] Recalculer les chunk IDs/SHA/pages depuis les octets et canonicaliser les sets.
- [ ] Vérifier les sets d'autorisation LOT41A égaux aux sets release.

- [ ] Asserter currentness évaluée=total, unevaluated=0, droits unresolved=0 et
  `candidate=eligible+named_noneligible`.

## Chunk 3 — Readiness et premier batch réel

### Task 5 — Réconciliation/readiness exacte

**Files:**
- Create: `services/rag-engine/src/ingestor/release_readiness.py`
- Create: `services/rag-engine/tests/test_release_readiness.py`
- Modify: `services/rag-engine/src/ingestor/retrieval_v2_endpoint.py`

- [ ] Écrire les neuf tests rouges absence/drift/missing/unexpected/model/review/current.
- [ ] Implémenter le comparateur de sets complet et fail-closed.
- [ ] Brancher `/collections/readiness` sur manifest path + expected SHA.

### Task 6 — Ingestion réelle et idempotence

**Files:**
- Extend: `services/rag-engine/tests/integration/test_wave0_french_pgvector.py`
- Create/Modify: fixtures release batch

- [ ] Partir de bases control/product propres et du provider E5 attesté CPU.
- [ ] Créer grants LOT41A exacts, jobs Worker A, approvals LOT42 et jobs Worker B.
- [ ] Réconcilier tous les sets et pins avec les manifests.
- [ ] Vérifier `ORPHAN_AUTHORITY_PINS=0` et `MISSING_ATTESTATION_PINS=0`.
- [ ] Rejouer le batch complet et vérifier zéro création/embedding/duplication,
  dont `ARTIFACT_CREATED_ON_SECOND_RUN=0`.

## Chunk 4 — CLIs, reprise et search

### Task 7 — CLIs publiables

**Files:**
- Modify: `services/rag-engine/src/ingestor/ingestion_worker/cli.py`
- Create: `services/rag-engine/src/ingestor/ingestion_worker/publication_resume_cli.py`
- Create/Modify: tests CLI unitaires et PostgreSQL

- [ ] Écrire les tests rouges startup sans resolver/digest drift.
- [ ] Construire le resolver une fois avec tous les inputs requis.
- [ ] Ajouter Worker B `--once` limité à `publication_resume`.
- [ ] Exécuter Worker A et Worker B CLI E2E sans monkeypatch.

### Task 8 — Reprise Phase B

**Files:**
- Modify: tests `publication_resume`/publisher/ingestion-control

- [ ] Écrire les scénarios rouges crash après eligibility/produit et lease expiry.
- [ ] Implémenter seulement les corrections observées nécessaires.
- [ ] Vérifier retry exact sans doublon ni nouvelle inférence.

### Task 9 — Acceptance search full

**Files:**
- Modify: `services/rag-engine/tests/fixtures/wave0_search_acceptance.yml`
- Modify: acceptance HTTP/CLI Wave 0

- [ ] Étendre à vingt requêtes réelles par matière sur plusieurs pages/concepts.
- [ ] Exécuter uvicorn, 20/20 + 20/20, discoverability 100% et isolation zéro.
- [ ] Relancer `scripts/rag_query.py` pour chaque scope.
- [ ] Prouver explicitement que le release set ne contient qu'un artefact par
  matière et couvrir plusieurs pages/concepts sans élargir au cycle 4.

## Chunk 5 — Activation et livraison

### Task 10 — Activation canonique après preuve

**Files:**
- Modify: `services/rag-engine/configs/rag_collections.yml`
- Modify: snapshot cockpit correspondant si gouverné par les tests
- Create: `docs/reports/lot_wave0_full_staging_ingestion.md`

- [ ] Faire échouer le test tant que readiness réelle n'est pas verte.
- [ ] Activer uniquement les deux collections Wave 0 après réconciliation.
- [ ] Rédiger le rapport sans secret/PII et consigner GitGuardian historique.
- [ ] Rechercher explicitement au HEAD les deux littéraux/findings GitGuardian,
  sans inspection ni réécriture destructive de l'historique.

### Task 11 — Vérification, revue et PR Draft

- [ ] Exécuter ruff, mypy, unit, PostgreSQL governance, modèles réels, HTTP,
  manifests, reconciliation et CLIs.
- [ ] Exécuter `bash scripts/ci-local.sh` puis la CI GitHub native.
- [ ] Demander une revue indépendante code/sécurité et corriger tout finding.
- [ ] Vérifier diff, absence de secrets/poids/PDF et HEAD exact.
- [ ] Committer/pousser un slice cohérent et mettre à jour le body de PR #95
  sans la rendre Ready.
