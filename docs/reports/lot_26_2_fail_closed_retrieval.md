# LOT 26.2 — Fail-closed retrieval v2

**Date** : 2026-07-09
**Issue pilotage** : #50
**Branche** : `codex/lot26-2-fail-closed-retrieval`
**Statut** : prêt à revue

---

## Objectif du lot

Garantir que `/search/v2` ne puisse jamais exposer de chunk non `reviewed` côté parcours étudiant/public.

## Travaux réalisés

- Mise à jour de [services/rag-engine/src/ingestor/retrieval_v2_endpoint.py](../../services/rag-engine/src/ingestor/retrieval_v2_endpoint.py) :
  - filtrage SQL strict sur `review_status = 'reviewed'` pour le pipeline de `/search/v2` et le warmup cache.
  - filtrage applicatif post-DB pour rejeter toute ligne non-`reviewed` même en cas de contamination DB :
    - après chaque `cur.fetchall()` via `candidates = _filter_reviewed_candidates(...)`
    - garde dans la boucle `if candidate[8] != "reviewed": continue`
  - `SearchV2Hit.review_status` typé `Literal["reviewed"]`.
  - garde-fou cache : refus d’utiliser un cache contenant des statuts hors `reviewed`.
  - warmup cache : ne met en cache que des hits `reviewed`.

## Tests de non-régression ajoutés

- [services/rag-engine/tests/test_retrieval_v2_endpoint.py](../../services/rag-engine/tests/test_retrieval_v2_endpoint.py)
  - vérification de la clause SQL fail-closed `review_status = 'reviewed'`.
  - validation du type `SearchV2Hit` : refus de `review_status` non `reviewed`.
- [services/rag-engine/tests/test_review_visibility.py](../../services/rag-engine/tests/test_review_visibility.py)
  - `test_search_v2_source_filters_reviewed_only` : source SQL sans `needs_review`.
  - `test_student_search_does_not_return_non_reviewed` : DB mock retourne `reviewed`, `needs_review`, `rejected`, `quarantined` avec scores rerank élevés ; `/search/v2` retourne uniquement le chunk `reviewed`.
  - `test_search_v2_cache_stale_status_is_not_returned` : un cache stale avec statut non `reviewed` déclenche un recompute DB puis retient uniquement `reviewed`.
  - `test_cache_warmup_ignores_non_reviewed_candidates` : warmup ne met pas en cache de chunks non `reviewed`.
  - ajout d’un fixture `clear_cache_between_tests` (`invalidate_cache` avant/après) pour éviter la pollution croisée.

## Contraintes respectées

- Pas d’ingestion modifiée.
- Pas de workflow review modifié.
- Pas de sécurité/rôles modifiés.
- Pas de cockpit modifié.
- Pas de production touchée.

## Garde-fous gouvernance racine

- `bash scripts/check-governance-locks.sh` :

```text
Governance locks: baseline=18, config=18
OK: all governance locks match baseline (18 keys verified).
```

- `bash scripts/tests/test-governance-locks.sh` :

```text
=== Test 1: Nominal (config == baseline, all false) ===
Governance locks: baseline=3, config=3
OK: all governance locks match baseline (3 keys verified).
  PASS  nominal_exit (exit 0)
  PASS  nominal_msg (contains 'all governance locks match baseline')

=== Test 2: Lock removed from config ===
Governance locks: baseline=3, config=2
FAIL: config deviates from baseline:
  Expected but missing/changed in config:
    chunking_allowed: false
BLOCKED: 1 governance violation(s).
  PASS  removed_exit (exit 1)
  PASS  removed_msg (contains 'chunking_allowed: false')

=== Test 3: Swap (same count, different key) ===
Governance locks: baseline=3, config=3
FAIL: config deviates from baseline:
  Expected but missing/changed in config:
    chunking_allowed: false
  In config but not matching baseline:
    network_allowed: false
BLOCKED: 1 governance violation(s).
  PASS  swap_exit (exit 1)
  PASS  swap_msg (contains 'chunking_allowed: false')

=== Test 4: All locks flipped to true ===
Governance locks: baseline=3, config=3
FAIL: config deviates from baseline:
  Expected but missing/changed in config:
    chunking_allowed: false
    embeddings_allowed: false
    parsing_allowed: false
  In config but not matching baseline:
    chunking_allowed: true
    embeddings_allowed: true
    parsing_allowed: true
BLOCKED: 1 governance violation(s).
  PASS  allflip_exit (exit 1)
  PASS  allflip_msg (contains 'deviate')

=== Test 5: Nominal with authorized true (ADR on baseline line) ===
Governance locks: baseline=3, config=3
OK: all governance locks match baseline (3 keys verified).
  PASS  auth_true_exit (exit 0)
  PASS  auth_true_msg (contains 'all governance locks match baseline')

=== Test 6: FLAW — second lock activated while ADR exists elsewhere ===
    (ingestion_allowed:true in config, baseline has it false)
Governance locks: baseline=4, config=4
FAIL: config deviates from baseline:
  Expected but missing/changed in config:
    ingestion_allowed: false
  In config but not matching baseline:
    ingestion_allowed: true
BLOCKED: 1 governance violation(s).
  PASS  flaw_exit (exit 1)
  PASS  flaw_msg (contains 'ingestion_allowed')

=== Test 7: Baseline has true WITHOUT ADR ===
Governance locks: baseline=3, config=3
FAIL: network_allowed is true in baseline without ADR reference on its line.
BLOCKED: 1 governance violation(s).
  PASS  noADR_exit (exit 1)
  PASS  noADR_msg (contains 'without ADR')

=== Test 8: ADR reference to nonexistent file ===
Governance locks: baseline=3, config=3
FAIL: network_allowed references ADR-9999 but no file docs/adr/ADR-9999*.md exists.
BLOCKED: 1 governance violation(s).
  PASS  nofile_exit (exit 1)
  PASS  nofile_msg (contains 'ADR-9999')

==============================
  GOVERNANCE GUARD TESTS
==============================
  16 passed, 0 failed, 16 total
```

- confirmation : aucun verrou modifié
- confirmation : aucun secret ajouté
- confirmation : aucun déploiement production

## CI locale racine

Commande :

```bash
bash scripts/ci-local.sh
```

Résultat :

```text
CI LOCAL — SUMMARY
  PASS  packages/contracts
  PASS  services/rag-pedago
  PASS  services/rag-engine
  PASS  governance-locks
  PASS  taxonomy-validation
  PASS  governance-guard-tests
  PASS  ci-failsafe-tests

Total: 7 passed, 0 failed
```

## Prochaine étape

LOT 26.2 est strictement en vue fail-closed retrieval; lots suivants restent découpés.
