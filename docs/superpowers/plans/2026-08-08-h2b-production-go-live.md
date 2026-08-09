# H2-B Production Go-Live Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clore H2-B sur le corpus réel puis conduire, sous gates fail-closed, l’audit indépendant, le merge et les phases P1 à P4 jusqu’à l’ingestion gouvernée.

**Architecture:** `SHA256SUMS.txt` définit les objets physiques et le sceau ; `catalogue-complet.tsv` définit les placements Eduscol joints par SHA. Le plan de contrôle compile une décision exhaustive, le scan distant séquentiel produit une preuve PII aseptisée, et le plan de données consomme uniquement un manifest gouverné via ses interfaces existantes. Chaque phase publie une preuve non sensible avant la suivante.

**Tech Stack:** Python 3.11, YAML/TSV/JSON, pypdf, pytest, ruff, mypy, PostgreSQL 16/pgvector, Docker Compose, Bash, rclone read-only, Git/GitHub CLI.

---

## Chunk 1: Catalogue réel et décisions de droits

### Task 1: Verrouiller les tests du manifest scellé

**Files:**
- Modify: `services/rag-pedago/tests/test_artifact_placement_model.py`
- Modify: `services/rag-pedago/tests/test_corpus_catalog_compiler.py`
- Test fixture: `/tmp/nexus-h2b-metadata.*/00_ADMIN/SHA256SUMS.txt`
- Test fixture: `/tmp/nexus-h2b-metadata.*/00_INDEX_PROVENANCE/EDUSCOL_CATALOGUES/catalogue-complet.tsv`

- [ ] Écrire les tests rouges couvrant 2 583 entrées, l’objet self, un SHA à deux chemins, 2 451 SHA Eduscol, 2 956 placements et 433 multi-placement.
- [ ] Exiger que les compteurs attendus soient dérivés des entrées, jamais acceptés depuis une constante YAML.
- [ ] Lancer les tests ciblés et confirmer RED pour intégration absente.

### Task 2: Intégrer objets physiques, contenus et placements

**Files:**
- Modify: `services/rag-pedago/rag_pedago/imports/artifact_placement_model.py`
- Modify: `services/rag-pedago/rag_pedago/imports/corpus_catalog_compiler.py`
- Modify: `services/rag-pedago/configs/corpus_zone_routing.yml`

- [ ] Ajouter les modèles d’objet physique et d’identité de contenu tout en conservant les interfaces historiques utiles.
- [ ] Parser strictement le format GNU SHA256, refuser les chemins absolus/traversals, hashes invalides et doublons chemin.
- [ ] Représenter `00_ADMIN/SHA256SUMS.txt` comme `EXCLUDE/MANIFEST_SELF_OBJECT` sans toucher au fichier scellé.
- [ ] Joindre les placements Eduscol au bon SHA, conserver niveau/matière/scope/type/année/statut et refuser tout SHA inconnu.
- [ ] Appliquer la disposition par objet physique avec `INGEST` comme résultat AND final.
- [ ] Rejouer les tests ciblés jusqu’à GREEN puis `ruff` et `mypy` sur les modules modifiés.

### Task 3: Enregistrer les décisions humaines de droits

**Files:**
- Modify: `services/rag-pedago/configs/rights_evidence_registry.yml`
- Modify: `services/rag-pedago/rag_pedago/imports/rights_evidence_gate.py`
- Modify: `services/rag-pedago/tests/test_rights_evidence_gate.py`

- [ ] Écrire les tests rouges pour `CLEARED_BY_HUMAN_DECISION`, les exceptions documentaires, DEPP non globalement bloquant et l’absence d’instructions humaines Eduscol obsolètes.
- [ ] Lier la décision Eduscol au manifest `d7e5…cc1e` et la décision Nexus aux 39 SHA triés, digestés avec une nouvelle ligne finale.
- [ ] Conserver les deux DEPP en `REVIEW_REQUIRED` et GeoGebra en `UNSUPPORTED`.
- [ ] Exiger `INGEST_WITHOUT_RIGHTS_CLEARANCE=0` au niveau objet, pas « zéro objet unresolved global ».
- [ ] Vérifier GREEN et consigner la décision comme organisationnelle, jamais comme avis juridique ou signature.

## Chunk 2: Scan réel et catalogue final

### Task 4: Durcir le contrat de preuve PII

**Files:**
- Modify: `services/rag-pedago/rag_pedago/imports/pii_scanner.py`
- Modify: `services/rag-pedago/tests/test_pii_scanner.py`
- Create: `services/rag-pedago/rag_pedago/imports/remote_pii_scan.py`
- Create: `services/rag-pedago/tests/test_remote_pii_scan.py`

- [ ] Écrire les canaris rouges qui interdisent PII brute dans stdout, stderr, JSON et exceptions.
- [ ] Définir une preuve liée à scanner, policy, content SHA et manifest SHA.
- [ ] Implémenter un runner rclone strictement read-only, un fichier à la fois, SHA vérifié, scratch borné et nettoyage `finally`.
- [ ] Dédupliquer le travail par SHA tout en comptant la couverture des objets physiques.
- [ ] Classer toute extraction impossible en `REVIEW_REQUIRED` ou `QUARANTINE`, jamais cleared.
- [ ] Vérifier les canaris GREEN avant tout téléchargement réel.

### Task 5: Scanner les 2 476 PDF réels

**Files:**
- External output: `$HOME/Documents/NEXUS_RAG_H2_EVIDENCE/h2b_pii_evidence_20260808.json`
- External output: `$HOME/Documents/NEXUS_RAG_H2_EVIDENCE/H2B_EVIDENCE_MANIFEST.json`

- [ ] Mesurer disque, nombre et taille ; refuser si la marge devient insuffisante.
- [ ] Exécuter le scan séquentiel complet depuis le remote Drive en lecture seule.
- [ ] Vérifier l’absence d’opération distante d’écriture et de PII brute dans les sorties.
- [ ] Sceller la preuve et relire ses compteurs/hash avant de nettoyer le scratch.

### Task 6: Compiler et vérifier le catalogue final

**Files:**
- Modify: `services/rag-pedago/rag_pedago/imports/h2b_coverage_report.py`
- Modify: `services/rag-pedago/rag_pedago/imports/golden_corpus_validator.py`
- Modify: `services/rag-pedago/tests/test_h2b_mutations.py`
- Create: `services/rag-pedago/data/reports/h2b_real_corpus_catalog_20260808.json`
- Modify: `services/rag-pedago/data/reports/h2b_technical_completion_20260808.md`

- [ ] Écrire les tests rouges prouvant que coverage et golden consomment le modèle intégré et refusent un catalogue synthétique/non scellé.
- [ ] Joindre droits, PII, currentness, format, provenance, autorité et attribution avant la disposition finale.
- [ ] Produire 2 584 dispositions primaires, zéro gap, zéro multiple et tous les invariants `INGEST_WITHOUT_*=0`.
- [ ] Générer un rapport H2 réel marqué incomplet tant qu’un autre gate reste rouge.

## Chunk 3: Autorité, mutations, retrieval et CI H2

### Task 7: Exécuter la matrice d’autorité externe

**Files:**
- Existing tests: `services/rag-engine/tests/integration/test_lot41a_scope_authority.py`
- Existing tests: `services/rag-engine/tests/integration/test_lot41a_worker_enforcement.py`
- Existing tests: `services/rag-engine/tests/integration/test_lot42_publication_attestation.py`

- [ ] Démarrer PostgreSQL/pgvector éphémère via les fixtures du service.
- [ ] Exécuter les cas exact, octets, content SHA, manifest, revue, autorisation, expiration, révocation et mauvais scope.
- [ ] Ajouter seulement les cas réellement absents, en TDD, sans faux SHA Git pour le corpus.
- [ ] Capturer les sorties et détruire uniquement l’environnement éphémère identifié.

### Task 8: Construire les douze mutations temporaires réelles

**Files:**
- Create: `services/rag-pedago/scripts/h2b_true_mutation_matrix.py`
- Create: `services/rag-pedago/tests/test_h2b_true_mutation_matrix.py`

- [ ] Écrire les tests rouges du protocole baseline → mutation → rouge ciblé → restauration → vert.
- [ ] Définir exactement douze guards : droits, PII, currentness, exclusion, format, objet inconnu, content SHA, manifest, autorité, révocation, extraction, disposition unique.
- [ ] Restaurer les octets dans `finally`, vérifier leur SHA et refuser toute mutation ambiguë ou non vacueuse.
- [ ] Exécuter la matrice et prouver `12/12` puis worktree identique hors preuves attendues.

### Task 9: Prouver le retrieval multi-placement réel

**Files:**
- Create: `services/rag-engine/tests/integration/test_h2b_real_corpus_retrieval.py`
- Modify only if required: `services/rag-engine/src/ingestor/*`

- [ ] Sélectionner un SHA Eduscol réel multi-placement sans copier de contenu dans les logs.
- [ ] Écrire RED pour un seul jeu de chunks, deux scopes autorisés, mauvais scope bloqué, attribution/SHA/citation présents.
- [ ] Étendre la fixture aux strates collège, seconde, première, terminale, STMG et plusieurs matières.
- [ ] Implémenter uniquement l’adaptation de métadonnées nécessaire via le contrat/API existant.
- [ ] Exécuter le pipeline extraction → chunk → vecteur test → index → retrieval dans pgvector éphémère.

### Task 10: Clore la qualité H2

**Files:**
- Create: `docs/reports/lot_h2b_production_readiness.md`

- [ ] Exécuter `make lint`, `make typecheck`, `make test` dans `rag-pedago` et `rag-engine` selon le périmètre.
- [ ] Exécuter `bash scripts/ci-local.sh`, `git diff --check`, le scan secret et les contrôles de gouvernance.
- [ ] Réconcilier tout échec avec le commit parent ; ne documenter comme dette que ce qui est prouvé préexistant.
- [ ] Committer par unités logiques avec messages impératifs et scopés, puis pousser sans force.

## Chunk 4: Audit indépendant et merge H2

### Task 11: Faire auditer le head exact

**Files:**
- Create: `docs/reports/lot_h2b_independent_audit.md`

- [ ] Figer le head, les hashes de preuve et les commandes reproductibles.
- [ ] Confier l’audit à un contexte reviewer séparé explicitement demandé par Nexus Réussite.
- [ ] Auditer sécurité, fail-closed, corpus réel, PII, droits, autorité, mutations, retrieval, CI, writer paths et rollback.
- [ ] Remédier tout finding bloquant puis relancer un nouvel audit du nouveau head.

### Task 12: Satisfaire GitHub et fusionner

**Files:**
- No planned code file.

- [ ] Passer la PR 95 en ready-for-review seulement après audit vert.
- [ ] Résoudre les threads actionnables, obtenir la review humaine de confiance sur le challenge du head exact et attendre tous les checks requis.
- [ ] Fusionner par la méthode protégée du dépôt, sans bypass ni force.
- [ ] Fast-forward local `main`, exécuter la CI exacte de `main` et enregistrer le merge SHA.

## Chunk 5: P1, sauvegarde et P2

### Task 13: Inventorier la cible réelle

**Files:**
- Modify: `docs/reports/lot_h2b_production_readiness.md`

- [ ] Identifier l’hôte, les services, images, digests, volumes, DB, réseau, TLS, proxy, monitoring et exigences de secrets sans afficher de valeur.
- [ ] Comparer la cible aux runbooks `go_live.md`, `ingestion_control_go_live.md` et `rollback.md`.
- [ ] Arrêter P1 si aucune cible authentifiée/canonique n’est découvrable.

### Task 14: Sauvegarder et tester le rollback

**Files:**
- External production evidence only.

- [ ] Quiescer les writers selon runbook et produire dump DB, snapshot config/manifests, digests images et référence de release.
- [ ] Vérifier les archives et restaurer dans une cible isolée.
- [ ] Rejouer le rollback applicatif et DB sans toucher aux objets hors scope.

### Task 15: Exécuter P2 production-equivalent

**Files:**
- External rehearsal evidence only.

- [ ] Construire exactement les images candidates et enregistrer leurs digests.
- [ ] Déployer sur DB isolée, appliquer seulement les migrations réellement requises, ingérer un échantillon gouverné et retrieve.
- [ ] Tester restart, rollback, redeploy, santé, autorité et absence de writer alternatif.

## Chunk 6: P3, P4 et clôture

### Task 16: Canary P3

**Files:**
- External canary evidence only.

- [ ] Déployer le plus petit canary canonique et vérifier santé, auth, scope, PII, citations, latence, erreurs, DB et ressources.
- [ ] Rollback immédiat sur toute condition rouge listée dans l’autorisation.

### Task 17: Production P4 et ingestion exhaustive

**Files:**
- External deployment and ingestion manifests only.

- [ ] Déployer la release approuvée et seulement alors activer le wiring LOT42 live.
- [ ] Ingest tous et seulement les objets `INGEST`; exiger attempted=success=eligible.
- [ ] Vérifier zéro jeu de chunks dupliqué pour les contenus multi-placement et zéro objet non autorisé.

### Task 18: Retrieval, soak et rapport final

**Files:**
- Modify: `docs/reports/lot_h2b_production_readiness.md`
- External output: non-sensitive deployment evidence package.

- [ ] Exécuter les smokes read-only collège, seconde, première, terminale, STMG, multi-matières, citations et SHA.
- [ ] Comparer le manifest d’ingestion à l’ensemble `INGEST` et exiger zéro manquant/zéro intrus.
- [ ] Observer le soak canonique, vérifier monitoring sans contenu PII et conserver la référence de rollback.
- [ ] Produire le rapport final demandé avec `NEXT_ACTION` déterminé uniquement par les gates observés.
