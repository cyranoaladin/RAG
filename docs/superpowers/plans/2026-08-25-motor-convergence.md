# Motor A/B Safe Convergence Implementation Plan

> **For agentic workers:** REQUIRED: Use
> `superpowers:subagent-driven-development` to implement this plan. Each code
> task follows strict Red → Green → Refactor and receives a specification then
> quality review before the next task.

**Goal:** Fermer les chemins de migration directe A→B, produire une préparation
legacy exhaustive et scellée, mesurer la parité sur passages canoniques et
forcer le cutover à `NO_GO` tant que les preuves réelles de parité,
restauration et rollback ne sont pas présentes.

**Architecture:** Le moteur B reste l'unique cible canonique ; aucune route ni
écriture publique n'est ajoutée. Une politique YAML hors runtime décrit la
convergence, un module Python pur valide les captures read-only et produit des
manifestes sans texte/vecteur, un comparateur hors réseau mesure A/B, et un
validateur de cutover distingue déclaration et preuve réelle. Le moteur A
reste intact pour continuité/rollback.

**Tech Stack:** Python 3.11+, dataclasses/stdlib, PyYAML, pytest, ruff, mypy,
Git/GitHub CLI.

---

## Chunk 0 — Conception et baseline

### Task 0: Figer la conception validée

**Files:**
- Add: `docs/superpowers/specs/2026-08-25-motor-convergence-design.md`

- [x] **Step 1: Consolider les audits A, B et cutover**

Établir les chemins exacts, les contournements de gouvernance, les lacunes de
parité et de rollback, sans modifier le code.

- [x] **Step 2: Faire relire la conception contradictoirement**

Corriger quiescence, états non substituables, collection discovery, précédence
des dispositions, conservation quarantine, passage canonique et snapshot
SQLite cohérent.

- [x] **Step 3: Commit de conception**

Commit observé : `ae4c85f` (`rag-engine: concevoir la convergence sûre des
moteurs`).

## Chunk 1 — Neutralisation de la copie directe

### Task 1: Transformer le migrateur dangereux en tombstone constant

**Files:**
- Add: `services/rag-engine/tests/test_legacy_convergence_tombstone.py`
- Modify: `services/rag-engine/scripts/migrate_chroma_to_pgvector.py`

- [ ] **Step 1: Écrire le test rouge du refus avant mutation**

Le test lance le script avec plusieurs argumentaires, dont options inconnues et
une valeur canari sensible. Il exige : code 78 constant, stdout vide, stderr
constant ne contenant aucun argument, aucun import `asyncpg`/`chromadb`, aucun
`INSERT`, aucune fonction de migration et aucune ouverture réseau/DB.

- [ ] **Step 2: Vérifier le rouge attendu**

```bash
PYTHONPATH=services/rag-engine/src python3 -m pytest -q \
  services/rag-engine/tests/test_legacy_convergence_tombstone.py
```

Expected : échec parce que le script parse encore les arguments et contient le
writer direct.

- [ ] **Step 3: Implémenter le tombstone minimal**

Le script ne lit pas `sys.argv`, n'importe aucune dépendance réseau/DB, écrit un
message constant sur stderr et retourne `EX_CONFIG=78`.

- [ ] **Step 4: Rejouer le test et refactorer**

Expected : PASS, sans duplication de message ni logique CLI superflue.

- [ ] **Step 5: Commit**

```bash
git add services/rag-engine/scripts/migrate_chroma_to_pgvector.py \
  services/rag-engine/tests/test_legacy_convergence_tombstone.py
git commit -m "rag-engine: bloquer la migration directe Chroma pgvector"
```

## Chunk 2 — Politique canonique de convergence

### Task 2: Valider la politique et la frontière runtime

**Files:**
- Add: `services/rag-engine/configs/engine_convergence_v1.yml`
- Add: `services/rag-engine/src/ingestor/engine_convergence_policy.py`
- Add: `services/rag-engine/tests/test_engine_convergence_policy.py`

- [ ] **Step 1: Cycle protocole et propriétaire canonique**

Ajouter `test_policy_requires_v1_protocol_and_engine_b`, lancer ce seul test et
observer le rouge. Ajouter le YAML minimal et les dataclasses immuables qui
valident protocole, moteur B et contrat `packages/contracts`. Rejouer le test au
vert, puis supprimer toute généralisation non utilisée.

- [ ] **Step 2: Cycle états et capacités fermés**

Ajouter `test_policy_rejects_unknown_state_or_ownerless_capability`, rouge avec
état inconnu/capacité sans propriétaire, puis implémenter uniquement les enums
`compatibility_only|rollback_only|blocked`, les lots responsables et le rejet
du writer A déclaré. Rejouer au vert.

- [ ] **Step 3: Cycle collections découvertes et cibles fines**

Ajouter `test_policy_closes_legacy_collections_and_rejects_silos`, rouge sur
collection absente, doublon, cible `rag_nexus_education`/`rag_nexus_web3` et
cible absente du catalogue. Implémenter la liste exacte observée et la
validation contre `rag_collections.yml`, puis vert.

- [ ] **Step 4: Cycle frontière `api_v2.py`**

Ajouter `test_canonical_api_has_no_legacy_writer_or_fallback`, constater le
rouge tant que l'audit n'est pas codé, puis implémenter le contrôle séparé des
imports et routes canoniques. Ne jamais utiliser le YAML comme preuve runtime.

- [ ] **Step 5: Cycle frontière image v2**

Ajouter `test_canonical_image_excludes_chroma_and_writer_sources`, rouge puis
contrôle minimal de `Dockerfile.ingestor-v2`; exiger aucune source writer A,
aucun client Chroma et aucun fallback. Rejouer au vert.

- [ ] **Step 6: Rejouer la suite et refactorer**

```bash
PYTHONPATH=services/rag-engine/src python3 -m pytest -q \
  services/rag-engine/tests/test_engine_convergence_policy.py
```

Expected : PASS. Les erreurs ne reprennent aucune valeur non validée.

- [ ] **Step 7: Commit**

```bash
git add services/rag-engine/configs/engine_convergence_v1.yml \
  services/rag-engine/src/ingestor/engine_convergence_policy.py \
  services/rag-engine/tests/test_engine_convergence_policy.py
git commit -m "rag-engine: verrouiller la politique de convergence"
```

## Chunk 3 — Capture et disposition legacy

### Task 3: Définir une fixture exhaustive sans contenu

**Files:**
- Add: `services/rag-engine/tests/fixtures/legacy_convergence_capture_v1.jsonl`
- Add: `services/rag-engine/tests/test_legacy_convergence.py`

- [ ] **Step 1: Écrire une capture miniature exhaustive**

La ligne d'en-tête contient le producteur, sa version/commit, l'instant UTC, la
preuve read-only et les composants explicitement séparés :

- Chroma : identité volume/service, dimension, comptes et digest par collection ;
- `catalog.sqlite` : identité, schéma, état WAL, méthode de backup et
  `integrity_check` ;
- `drive_sync_state.db` : mêmes preuves séparées ;
- pgvector : identité base/service, head de migration, comptes et digest ;
- uploads/fichiers reconstructibles : racine logique, compte et digest ;
- configurations, images immuables et modèles épinglés ;
- liste des collections découverte et comptes sources.

Les lignes objets contiennent seulement IDs, hashes, longueurs, provenance et
scope. Aucun texte, embedding ou secret.

- [ ] **Step 2: Vérifier que la fixture elle-même est sans contenu**

Ajouter un test statique qui refuse les clés `text`, `document`, `embedding`,
`embeddings` et les images non digestées. Ce test peut être vert avant le
module : il protège l'actif témoin, sans prétendre tester le préparateur.

### Task 4: Implémenter le préparateur pur

**Files:**
- Add: `services/rag-engine/src/ingestor/legacy_convergence.py`
- Test: `services/rag-engine/tests/test_legacy_convergence.py`

- [ ] **Step 1: Cycle en-tête, protocole et provenance**

Ajouter `test_capture_requires_producer_read_only_identity`, lancer avec `-k`
et observer l'import rouge. Implémenter seulement les types immuables et la
validation de protocole/producteur/version/commit/instant/preuve read-only.
Rejouer au vert.

- [ ] **Step 2: Cycle inventaire Chroma**

Ajouter `test_capture_requires_chroma_identity_dimension_counts_and_digests`,
rouge sur chaque omission, puis implémenter ce composant et vert.

- [ ] **Step 3: Cycle des deux SQLite indépendants**

Ajouter `test_capture_requires_both_sqlite_consistent_backups`, rouge si une
base manque ou sans schéma/WAL/méthode/integrity. Implémenter la validation
distincte de `catalog.sqlite` et `drive_sync_state.db`, puis vert.

- [ ] **Step 4: Cycle pgvector et actifs reconstructibles**

Ajouter `test_capture_requires_pgvector_uploads_configs_images_and_models`,
rouge sur identité/head/comptes/digests ou image mutable, puis implémenter le
minimum et vert.

- [ ] **Step 5: Cycle lecteur borné et champs interdits**

Ajouter deux tests ciblés : ligne trop grande et champ texte/embedding. Pour
chacun : rouge, implémentation streaming minimale, vert. L'exception ne reprend
jamais la ligne fautive.

- [ ] **Step 6: Cycle digest et découverte exhaustive**

Ajouter successivement un test mauvais SHA-256, un test compte source faux, un
test collection découverte omise et un test collection inconnue. Effectuer un
petit cycle rouge/vert pour chaque invariant, puis factoriser la comparaison
exacte politique↔découverte.

- [ ] **Step 7: Cycle précédence de disposition**

Ajouter un test paramétré par reason code, mais faire passer les cas un à un :
`SOURCE_UNAVAILABLE`, quarantine, scope/droits/provenance incomplets,
NSI Première/Terminale exact, collection ambiguë et collection vide. Chaque
nouveau cas est rouge avant le minimum de logique qui le rend vert.

- [ ] **Step 8: Cycle non-autorisation de `REINGEST_GOVERNED`**

Ajouter `test_reingest_candidate_never_grants_rights_review_or_retrieval`,
rouge si le manifeste transporte un droit, `reviewed`, `retrievable` ou une
autorisation. Implémenter une sortie candidate sans ces pouvoirs, puis vert.

- [ ] **Step 9: Cycle déduplication sans perte**

Ajouter d'abord le test d'identité canonique et `duplicate_of`, rouge/vert,
puis le test que chaque doublon reste compté exactement une fois, rouge/vert.

- [ ] **Step 10: Cycle scellement canonique**

Ajouter les tests du tri, compteurs, digest d'entrée et digest de sortie un par
un. Finir par `migration_complete=false` et l'absence d'API d'écriture
pgvector/Chroma.

- [ ] **Step 11: Rejouer et refactorer**

```bash
PYTHONPATH=services/rag-engine/src python3 -m pytest -q \
  services/rag-engine/tests/test_legacy_convergence.py
```

Expected : PASS.

### Task 5: Ajouter le CLI dry-run/write explicite

**Files:**
- Add: `services/rag-engine/scripts/prepare_legacy_migration.py`
- Add: `services/rag-engine/tests/test_prepare_legacy_migration_cli.py`

- [ ] **Step 1: Cycle dry-run sans contenu**

Ajouter `test_cli_defaults_to_summary_only`, rouge car le script manque,
implémenter le parseur minimal et la sortie compteurs/digest, puis vert. Ajouter
ensuite le canari contenu, rouge si écho, corriger sans afficher l'entrée.

- [ ] **Step 2: Cycle scellement obligatoire pour écriture**

Ajouter le refus sans `--expected-input-sha256`, rouge/vert, puis le mauvais
digest, rouge/vert. Aucun argument DSN ou réseau n'est accepté.

- [ ] **Step 3: Cycle création exclusive**

Ajouter le test chemin existant, rouge/vert, puis le test fichier nouveau.
Implémenter ouverture exclusive, écriture complète, flush/fsync et publication
sans écrasement.

- [ ] **Step 4: Cycle erreurs assainies**

Ajouter une entrée invalide contenant un canari, constater le rouge si la ligne
est répétée, puis réduire l'erreur à type/numéro de ligne sans contenu.

- [ ] **Step 5: Rejouer les deux suites**

```bash
PYTHONPATH=services/rag-engine/src python3 -m pytest -q \
  services/rag-engine/tests/test_legacy_convergence.py \
  services/rag-engine/tests/test_prepare_legacy_migration_cli.py
```

- [ ] **Step 6: Commit**

```bash
git add services/rag-engine/src/ingestor/legacy_convergence.py \
  services/rag-engine/scripts/prepare_legacy_migration.py \
  services/rag-engine/tests/test_legacy_convergence.py \
  services/rag-engine/tests/test_prepare_legacy_migration_cli.py \
  services/rag-engine/tests/fixtures/legacy_convergence_capture_v1.jsonl
git commit -m "rag-engine: préparer la réingestion legacy gouvernée"
```

## Chunk 4 — Parité A/B hors runtime

### Task 6: Définir le témoin et les captures A/B

**Files:**
- Add: `services/rag-engine/tests/fixtures/engine_parity_witness_v1.json`
- Add: `services/rag-engine/tests/fixtures/engine_parity_a_v1.json`
- Add: `services/rag-engine/tests/fixtures/engine_parity_b_v1.json`
- Add: `services/rag-engine/tests/test_engine_parity.py`

- [ ] **Step 1: Écrire des fixtures minimales scellables**

Inclure requêtes allowlistées, scope attendu, unités
`source_sha256 + canonical_span_id + content_hash`, résultats ordonnés,
citations, droits et review status. Ajouter un témoin hors collection pour la
tolérance zéro.

- [ ] **Step 2: Vérifier statiquement les fixtures**

Un test sans module contrôle l'absence de réponses longues/contenu sensible et
la présence des trois composantes de chaque passage. Le comportement du
comparateur sera développé par petits cycles dans Task 7.

### Task 7: Implémenter le comparateur pur et son CLI

**Files:**
- Add: `services/rag-engine/src/ingestor/engine_parity.py`
- Add: `services/rag-engine/scripts/compare_engine_parity.py`
- Add: `services/rag-engine/tests/test_compare_engine_parity_cli.py`

- [ ] **Step 1: Cycle unité canonique de passage**

Ajouter le test de composante manquante, observer le rouge, implémenter la
dataclass `source_sha256 + canonical_span_id + content_hash`, puis vert. Ajouter
ensuite le résultat non mappable, rouge/vert.

- [ ] **Step 2: Cycle liaison témoin/captures**

Ajouter successivement mauvais digest témoin, requête en trop et requête
manquante. Chaque invariant suit son propre rouge/vert. Ne lire que du JSON
local et ne jamais reprendre une réponse brute dans l'erreur.

- [ ] **Step 3: Cycle bornes `k` et taille**

Ajouter `k=0`, `k` trop grand puis capture trop volumineuse comme trois petits
cycles. Implémenter uniquement les bornes décidées dans le témoin.

- [ ] **Step 4: Cycle tolérance zéro — scope**

Ajouter fuite collection puis fuite niveau séparément ; chacune doit d'abord
échouer puis produire `FAIL_CLOSED` avec un reason code sans contenu.

- [ ] **Step 5: Cycle tolérance zéro — citation et gouvernance**

Ajouter citation incomplète, droit inconnu et statut non reviewé comme trois
cycles rouges/verts distincts. Aucun seuil opérateur ne peut neutraliser ces
refus.

- [ ] **Step 6: Cycle métriques**

Ajouter rappel, rang réciproque, couverture puis divergences par passage un par
un, avec valeurs calculables à la main. Refactorer seulement après les quatre
verts.

- [ ] **Step 7: Cycle verdict sans seuil**

Ajouter le nominal attendu
`METRICS_ONLY_THRESHOLDS_UNAPPROVED`, constater le rouge si `PASS`, implémenter
la règle puis vérifier le déterminisme/digests des trois entrées.

- [ ] **Step 8: Cycle CLI hors réseau**

Dans `test_compare_engine_parity_cli.py`, ajouter successivement : entrées
explicites, stdout résumé seulement, fichier nouveau seulement et erreur
assainie. Pour chaque test : rouge, code minimal, vert.

- [ ] **Step 9: Rejouer les tests**

```bash
PYTHONPATH=services/rag-engine/src python3 -m pytest -q \
  services/rag-engine/tests/test_engine_parity.py \
  services/rag-engine/tests/test_compare_engine_parity_cli.py
```

- [ ] **Step 10: Commit**

```bash
git add services/rag-engine/src/ingestor/engine_parity.py \
  services/rag-engine/scripts/compare_engine_parity.py \
  services/rag-engine/tests/test_engine_parity.py \
  services/rag-engine/tests/test_compare_engine_parity_cli.py \
  services/rag-engine/tests/fixtures/engine_parity_*.json
git commit -m "rag-engine: mesurer la parité sur passages scellés"
```

## Chunk 5 — Cutover et rollback fail-closed

### Task 8: Valider un manifeste explicitement NO_GO

**Files:**
- Add: `services/rag-engine/src/ingestor/engine_cutover.py`
- Add: `services/rag-engine/tests/fixtures/engine_cutover_no_go_v1.json`
- Add: `services/rag-engine/tests/test_engine_cutover.py`

- [ ] **Step 1: Cycle identité release et images**

Ajouter le test SHA Git/digests d'images immuables, rouge, implémenter seulement
ces types et validations, puis vert.

- [ ] **Step 2: Cycle inventaire A/B reconstructible**

Ajouter d'abord le composant Chroma, puis les deux SQLite séparés, puis
uploads/config/modèles, puis pgvector/migrations. Chaque omission est un cycle
rouge/vert distinct ; réutiliser les types validés du manifeste legacy si
possible, sans dupliquer le schéma.

- [ ] **Step 3: Cycle quiescence et stabilité**

Ajouter writers/cron désactivés, ordre de capture et comptes/digests
avant-après comme trois cycles. Une archive live ne peut pas poser
`snapshot_declared=true`.

- [ ] **Step 4: Cycle topologie et smokes bornés**

Ajouter cible canary=rollback (rouge/vert), puis smoke sans timeout/borne
(rouge/vert).

- [ ] **Step 5: Matrice de non-substitution des preuves**

Paramétrer les cinq faits : `snapshot_restored_verified`,
`real_parity_executed`, `restore_rehearsal_verified`,
`traffic_rollback_tested`, `cutover_authorized`. Pour chacun séparément :

1. poser le booléen à `true` avec seulement `snapshot_declared`, une fixture
   locale ou un digest déclaré ;
2. observer le rouge attendu du futur validateur ;
3. implémenter le rejet faute d'évidence scellée de type exact ;
4. rejouer au vert avec verdict systématique `NO_GO`.

Aucune évidence d'un type ne peut satisfaire un autre fait.

- [ ] **Step 6: Cycle verdict et vocabulaire interdits**

Ajouter `READY`, `GO_LIVE_READY` puis un synonyme de readiness comme petits
cycles rouges/verts. Le résultat nominal Lot 2 doit lister les cinq gates et
rendre exclusivement `NO_GO`.

- [ ] **Step 7: Vérifier l'absence de primitives de mutation**

Ajouter un test statique avant l'implémentation finale : aucun subprocess,
client Docker/DB, commande restore/deploy ou écriture de service dans le
module.

- [ ] **Step 8: Rejouer et commit**

```bash
PYTHONPATH=services/rag-engine/src python3 -m pytest -q \
  services/rag-engine/tests/test_engine_cutover.py
git add services/rag-engine/src/ingestor/engine_cutover.py \
  services/rag-engine/tests/test_engine_cutover.py \
  services/rag-engine/tests/fixtures/engine_cutover_no_go_v1.json
git commit -m "rag-engine: rendre le cutover fail-closed"
```

## Chunk 6 — ADR, matrice de parité et rapport

### Task 9: Documenter la convergence sans faux vert

**Files:**
- Modify: `docs/adr/ADR-0013-convergence-dual-engine.md`
- Add: `docs/reports/lot_2_motor_convergence_20260825.md`
- Add: `docs/runbooks/engine_convergence_shadow_cutover.md`

- [ ] **Step 1: Amendement ADR**

Documenter tombstone, capture/disposition exhaustive, passage canonique,
quiescence, états A et preuve cutover non substituable. Ne lever aucun verrou.

- [ ] **Step 2: Runbook shadow/canary/rollback**

Décrire l'ordre exact sans exécuter : quiescence, capture, backup, inventaire,
réingestion gouvernée, parité réelle, restore rehearsal isolé, canary, rollback
trafic, observation et gates humaines.

- [ ] **Step 3: Rapport de lot**

Inclure matrice A/B par fonctionnalité, fichiers/commits, cycles Red/Green,
tests, digests locaux, statut `VERIFIED_LOCAL`, preuves réelles absentes et
verdict global `NO_GO`. Reporter Web/Drive/API/UI aux lots propriétaires.

- [ ] **Step 4: Vérifier la cohérence documentaire**

```bash
rg -n "GO_LIVE_READY|VERIFIED_PRODUCTION|migration_complete.*true" \
  docs/adr/ADR-0013-convergence-dual-engine.md \
  docs/reports/lot_2_motor_convergence_20260825.md \
  docs/runbooks/engine_convergence_shadow_cutover.md
```

Toute occurrence doit être une condition/refus explicite, jamais un verdict.

- [ ] **Step 5: Commit**

```bash
git add docs/adr/ADR-0013-convergence-dual-engine.md \
  docs/reports/lot_2_motor_convergence_20260825.md \
  docs/runbooks/engine_convergence_shadow_cutover.md \
  docs/superpowers/plans/2026-08-25-motor-convergence.md
git commit -m "docs: consigner la convergence des moteurs RAG"
```

## Chunk 7 — Vérification, revues et PR

### Task 10: Vérifier le lot complet

**Files:**
- Verify all Lot 2 files

- [ ] **Step 1: Tests ciblés frais**

```bash
PYTHONPATH=services/rag-engine/src python3 -m pytest -q \
  services/rag-engine/tests/test_legacy_convergence_tombstone.py \
  services/rag-engine/tests/test_engine_convergence_policy.py \
  services/rag-engine/tests/test_legacy_convergence.py \
  services/rag-engine/tests/test_prepare_legacy_migration_cli.py \
  services/rag-engine/tests/test_engine_parity.py \
  services/rag-engine/tests/test_compare_engine_parity_cli.py \
  services/rag-engine/tests/test_engine_cutover.py
```

- [ ] **Step 2: Tests de non-régression des frontières existantes**

```bash
PYTHONPATH=services/rag-engine/src python3 -m pytest -q \
  services/rag-engine/tests/test_v2_runtime_surface.py \
  services/rag-engine/tests/test_rag_collections_config.py \
  services/rag-engine/tests/test_collection_config_v2.py \
  services/rag-engine/tests/test_retrieval_v2_endpoint.py \
  services/rag-engine/tests/test_ingestion_embedding_path_audit_contract.py
```

- [ ] **Step 3: Qualité Python**

```bash
(cd services/rag-engine && python3 -m ruff check \
  src/ingestor/engine_convergence_policy.py \
  src/ingestor/legacy_convergence.py \
  src/ingestor/engine_parity.py \
  src/ingestor/engine_cutover.py \
  scripts/migrate_chroma_to_pgvector.py \
  scripts/prepare_legacy_migration.py \
  scripts/compare_engine_parity.py \
  tests/test_legacy_convergence_tombstone.py \
  tests/test_engine_convergence_policy.py \
  tests/test_legacy_convergence.py \
  tests/test_prepare_legacy_migration_cli.py \
  tests/test_engine_parity.py \
  tests/test_engine_cutover.py \
  tests/test_compare_engine_parity_cli.py)
(cd services/rag-engine && python3 -m mypy \
  src/ingestor/engine_convergence_policy.py \
  src/ingestor/legacy_convergence.py \
  src/ingestor/engine_parity.py \
  src/ingestor/engine_cutover.py)
```

- [ ] **Step 4: Garde-fous dépôt**

```bash
bash scripts/check-governance-locks.sh
bash scripts/check-repository-hygiene.sh
git diff --check origin/main...HEAD
```

Exécuter ensuite le scanner de secrets différentiel avec redaction totale, puis
la CI locale obligatoire :

```bash
gitleaks git --log-opts='origin/main..HEAD' --redact=100 --no-banner --exit-code 1
bash scripts/ci-local.sh
```

Tout échec préexistant doit être reproduit contre le commit parent et consigné
selon `AGENTS.md`. Aucun secret ni contenu legacy brut ne doit être détecté.

- [ ] **Step 5: Deux revues indépendantes**

Faire relire le diff complet par deux agents contradictoires : sécurité/
correctness et respect spec/tests. Corriger tout P0/P1 avec nouveau cycle TDD.

- [ ] **Step 6: Commit final de rapport si nécessaire**

Mettre à jour uniquement les résultats réellement observés, puis commit scoped.

### Task 11: Ouvrir la PR et atteindre le HUMAN GATE

- [ ] **Step 1: Push et PR unique**

```bash
git push -u origin rag-engine/motor-convergence-20260825
gh pr create --base main --head rag-engine/motor-convergence-20260825 \
  --title "rag-engine: converger les moteurs A et B sans migration directe" \
  --body-file docs/reports/lot_2_motor_convergence_20260825.md
```

- [ ] **Step 2: Corriger CI et commentaires dans la même branche**

Ne fusionner aucun autre lot dans ce checkout. Attendre CI verte et threads 0.

- [ ] **Step 3: Figer base/head et demander la trusted-human-review**

Présenter le challenge exact-head selon le protocole du dépôt. Ne jamais
auto-attester l'identité humaine et ne jamais fusionner sans autorisation.

Expected stop : `=== HUMAN GATE — LOT 2 MOTOR CONVERGENCE PR ===`.
