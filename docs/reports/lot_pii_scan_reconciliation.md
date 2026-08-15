# Lot — Réconciliation par union stricte des deux scans PII réels

## 1. Constat traité

`h2b_coverage_report.py`/`corpus_catalog_compiler.py` exigent une évidence
PII au format `REAL_CORPUS_PII_SCAN` déjà complète — mais l'évidence PII
réelle du corpus scellé existe en deux morceaux distincts, jamais fusionnés :
un scan exhaustif brut (`h2b_exhaustive_pii_scan_20260813.jsonl`, 2411
empreintes) et une campagne antérieure ciblée sur les 64 objets INGEST
d'origine (`h2b_pii_evidence_20260808.json`, déjà au bon format, 64
empreintes). Sans réconciliation, aucune exécution réelle du gate H2 n'est
possible.

## 2. Ce qui a été construit

`services/rag-pedago/rag_pedago/imports/pii_scan_reconciliation.py` :

- `load_exhaustive_scan_results` / `load_campaign_scan_results` : parseurs
  fail-closed pour chaque format source.
- `union_pii_scan_results` : union stricte, **jamais "latest wins"** — un
  désaccord entre les deux sources sur la même empreinte est un
  `EVIDENCE_CONFLICT`, refus explicite.
- `build_all_corpus_pdfs_pii_evidence` : assemble le document
  `REAL_CORPUS_PII_SCAN` complet, périmètre `ALL_CORPUS_PDFS` —
  `physical_object_count` recalculé depuis le manifeste réel, jamais recopié
  d'une source ; refuse toute couverture partielle (`seen != tous les PDF
  réels`) avant même que `_derive_pii_clearances` ne le referait de toute
  façon.
- `reconcile_pii_scan_evidence` : point d'entrée unique.

## 3. Vérification contre les données réelles

Exécuté pour de vrai contre les deux fichiers d'évidence réels et le
manifeste scellé local (`SEALED_MANIFEST_SHA256=d7e5caa5...`) :

```
required_pdf_path_count=2476, results=2475 (1 duplicate-content group, comme attendu)
status breakdown: CLEARED=2286, QUARANTINED_PII=146, REVIEW_REQUIRED_EXTRACTION_FAILED=43
```

Ces trois nombres **correspondent exactement** à
`docs/reports/evidence-index/summary_20260814.json` (`content_pii_counts`),
calculé indépendamment par PR#108 — validation croisée forte entre deux
implémentations indépendantes.

Le document produit a ensuite servi à compiler un catalogue réellement gaté
(`compile_governed_sealed_catalog`) et à exécuter le vrai gate H2 (`--catalog`
+ `--currentness-verification`, sans autorité — aucune n'existe encore) :

```
BLOCKED_INGEST_CANDIDATES=73 (breakdown: {authority: 73, pii: 1})
DECISION_COVERAGE_COMPLETE=true
GOLDEN_VALIDATION_PASS=true (13/13)
Tous les invariants de sécurité INGEST_* = 0
H2_COVERAGE_GATE_PASS=false  # attendu : aucune autorité fournie
```

**64 → 73 candidats INGEST réels** (base_disposition), confirmant précisément
les 9 objets promus par la vérification de currentness (PR#122) parmi les 12
de `multilevel_currentness_evidence.yml` (2 étaient déjà `10_ACTUEL_CONFIRME`,
1 a échoué droits/PII). Sur ces 73, 72 sont aussi PII-clairs — 1 reste bloqué
PII indépendamment de toute autorité.

## 4. Ce qui n'a délibérément pas changé

- `corpus_catalog_compiler.py`/`h2b_coverage_report.py` : jamais touchés
  (réutilisés tels quels).
- Aucune autorité n'est fournie ni fabriquée ici — `H2_COVERAGE_GATE_PASS`
  reste honnêtement `false`.
- Les deux fichiers d'évidence source
  (`h2b_exhaustive_pii_scan_20260813.jsonl`,
  `h2b_pii_evidence_20260808.json`) restent hors dépôt (trove local), comme
  toute la matière première d'évidence de cette mission — seul le
  **mécanisme** de réconciliation est versionné.

## 5. Tests

- `services/rag-pedago/tests/test_pii_scan_reconciliation.py` — 17 tests.
- Mutation-testing sur les 3 branches de sécurité (refus `EVIDENCE_CONFLICT`,
  refus couverture incomplète, refus statut inconnu) : chacune désactivée
  fait échouer son test dédié pour la bonne raison, restaurée, suite verte.
- `ruff check`/`mypy` : propres.
- Vérification contre les données réelles : §3 ci-dessus (pas seulement des
  fixtures synthétiques — l'exécution réelle a produit des nombres qui
  recoupent exactement une source indépendante déjà revue, PR#108).

## 6. Booléens finaux

```
PII_SCAN_RECONCILIATION_STEP_EXISTS=true
PII_SCAN_RECONCILIATION_TESTED=true
PII_SCAN_RECONCILIATION_MUTATION_TESTED=true
PII_SCAN_RECONCILIATION_VERIFIED_AGAINST_REAL_DATA=true
REAL_H2_GATE_RUN_WITHOUT_AUTHORITY_SUCCEEDED=true
REAL_BASE_INGEST_CANDIDATES=73   # 64 originaux + 9 promus par currentness (PR#122)
REAL_PII_CLEAR_AMONG_CANDIDATES=72
H2_COVERAGE_GATE_PASS=false   # honnête -- aucune autorité fournie, jamais simulée
```
