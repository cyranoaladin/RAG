# H2-C Final Technical Remediation Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for every implementation task and superpowers:verification-before-completion before each passing/complete claim.

**Goal:** Fermer les blocages techniques H2 par un modèle produit artefact→placements 1:N, une publication interne gouvernée, un retrieval sans duplication, une matrice de mutations réellement non vacue et une autorisation LOT41A réelle, puis atteindre la frontière de revue humaine sans toucher la production.

**Architecture:** La migration produit 004 ajoute `rag_artifacts`, `rag_artifact_placements` et un FK nullable depuis `rag_chunks`. Les lignes historiques gardent leur prédicat scalarisé ; les chunks gouvernés sont filtrés par `EXISTS` sur leurs placements exacts. Un publisher interne consomme exclusivement des attestations LOT42 revérifiées et écrit artefact, placements et chunks dans une transaction idempotente. L'autorisation LOT41A initiale est bornée au seul scope terminale/philosophie réellement résolu et PII-clear.

**Tech Stack:** PostgreSQL 16 + pgvector, SQL migrations/rollback, Python 3.12 (`psycopg`, Pydantic, pytest, ruff, mypy), Bash integration harness, YAML collection/profile governance, GitHub CLI for live PR evidence.

---

## Task 1: Lock the additive 004 schema with failing tests

**Files:**
- Modify: `services/rag-engine/tests/integration/test_hybrid_integration.sh`
- Modify: `services/rag-engine/tests/test_schema_readiness_v2.py`
- Modify: `services/rag-engine/tests/test_runtime_role_provisioning.py`
- Create: `services/rag-engine/tests/test_artifact_placement_migration_contract.py`

**Step 1: Write failing migration lifecycle tests**

Assert manifest HEAD 004, exact new tables/columns/constraints/indexes, legacy-row preservation, governed uniqueness, guarded rollback, clean rollback, and reapply.

**Step 2: Run tests to verify RED**

Run: `python -m pytest services/rag-engine/tests/test_artifact_placement_migration_contract.py services/rag-engine/tests/test_schema_readiness_v2.py services/rag-engine/tests/test_runtime_role_provisioning.py -q`

Expected: FAIL because migration 004 and head metadata do not exist.

**Step 3: Commit tests only**

```bash
git add services/rag-engine/tests
git commit -m "test(rag-engine): exige le schéma artefact placement 004"
```

## Task 2: Implement migration 004, rollback, schema fingerprints, and roles

**Files:**
- Create: `services/rag-engine/infra/postgres/migrations/004_artifact_placements.sql`
- Create: `services/rag-engine/infra/postgres/rollbacks/004_artifact_placements.down.sql`
- Modify: `services/rag-engine/infra/postgres/migrations/HEAD`
- Modify: `services/rag-engine/infra/scripts/lib/pgvector_migration_state.sh`
- Modify: `services/rag-engine/src/ingestor/schema_readiness_v2.py`
- Create: `services/rag-engine/infra/postgres/schema_head_004_columns.tsv`
- Create: `services/rag-engine/infra/postgres/schema_head_004_fingerprints.env`
- Modify: `services/rag-engine/infra/postgres/provision_runtime_roles.sh`
- Modify: `services/rag-engine/infra/docker-compose.v2.yml`

**Step 1: Implement minimal additive DDL**

Create content-bound artifacts, exact placements, nullable chunk FK, partial unique chunk-set index, lookup indexes, and no data backfill.

**Step 2: Implement guarded rollback**

Refuse rollback while governed rows exist; otherwise remove only 004 objects and the registry row in the canonical harness.

**Step 3: Extend exact readiness and least-privilege provisioning**

Require exact tables, columns, constraints, indexes, permissions, vector dimension and no owner fallback. Add a publisher login with SELECT/INSERT only on product tables.

**Step 4: Run focused tests to GREEN**

Run the Task 1 pytest command and `bash services/rag-engine/tests/integration/test_hybrid_integration.sh`.

Expected: PASS including apply, rollback, reapply and unchanged legacy rows.

**Step 5: Commit**

```bash
git add services/rag-engine/infra services/rag-engine/src/ingestor/schema_readiness_v2.py services/rag-engine/tests
git commit -m "feat(rag-engine): ajoute le schéma normalisé artefact placement"
```

## Task 3: Define governed publication inputs and identity tests

**Files:**
- Create: `services/rag-engine/tests/test_governed_publisher.py`
- Create: `services/rag-engine/src/ingestor/governed_publisher.py`

**Step 1: Write failing pure tests**

Cover content-bound identity, deterministic placement IDs, missing/duplicate/unknown scope refusal, content SHA drift, attestation/scope mismatch, no environment bypass and absence of any new HTTP route.

**Step 2: Run RED**

Run: `python -m pytest services/rag-engine/tests/test_governed_publisher.py -q`

Expected: import/behavior failures.

**Step 3: Implement strict immutable models and validators**

Use frozen dataclasses or strict Pydantic models. Require one verified LOT42 attestation per resolved placement and exact alignment with content/profile/manifest/authorization.

**Step 4: Run GREEN and commit**

```bash
git add services/rag-engine/src/ingestor/governed_publisher.py services/rag-engine/tests/test_governed_publisher.py
git commit -m "feat(rag-engine): valide les publications produit gouvernées"
```

## Task 4: Implement transactional idempotent publication

**Files:**
- Modify: `services/rag-engine/tests/test_governed_publisher.py`
- Create: `services/rag-engine/tests/integration/test_governed_publisher_pgvector.py`
- Modify: `services/rag-engine/src/ingestor/governed_publisher.py`

**Step 1: Write failing database tests**

Prove first publication, exact retry, new placement without embedding, changed bytes as new artifact, mismatch rollback, extraction failure rollback, and unique artifact/placement/chunk rows.

**Step 2: Run RED on disposable pgvector**

Run: `python -m pytest services/rag-engine/tests/integration/test_governed_publisher_pgvector.py -q`

Expected: FAIL because SQL publication is absent.

**Step 3: Implement one-transaction publisher**

Check existing rows before extraction, insert-only idempotency, deterministic chunk IDs, single embed pass and explicit rollback on every failure.

**Step 4: Run GREEN and commit**

```bash
git add services/rag-engine/src/ingestor/governed_publisher.py services/rag-engine/tests
git commit -m "feat(rag-engine): publie un artefact sans dupliquer ses chunks"
```

## Task 5: Retrieve governed chunks through placements

**Files:**
- Modify: `services/rag-engine/tests/test_retrieval_pg_v2.py`
- Modify: `services/rag-engine/tests/test_retrieval_hybrid_v2.py`
- Modify: `services/rag-engine/tests/test_retrieval_v2_endpoint.py`
- Modify: `services/rag-engine/src/ingestor/retrieval_pg_v2.py`
- Modify: `services/rag-engine/src/ingestor/retrieval_hybrid_v2.py`
- Modify: `services/rag-engine/src/ingestor/retrieval_v2_endpoint.py`

**Step 1: Write failing dual-path tests**

Prove unchanged legacy scope, governed `EXISTS` scope, wrong-scope exclusion, two matching placements without duplicate result, and trace fields in response metadata.

**Step 2: Run RED**

Run: `python -m pytest services/rag-engine/tests/test_retrieval_pg_v2.py services/rag-engine/tests/test_retrieval_hybrid_v2.py services/rag-engine/tests/test_retrieval_v2_endpoint.py -q`

**Step 3: Implement dual SQL and trace mapping**

Use a lateral/aggregate trace subquery that returns one row per chunk and validates all returned governed metadata. Keep RRF/MMR keyed by chunk ID.

**Step 4: Run GREEN and commit**

```bash
git add services/rag-engine/src/ingestor/retrieval_* services/rag-engine/tests
git commit -m "feat(rag-engine): filtre le retrieval par placements gouvernés"
```

## Task 6: Prove the real multi-placement control

**Files:**
- Create: `services/rag-engine/scripts/h2c_real_multiplacement_rehearsal.py`
- Create: `services/rag-engine/tests/integration/test_h2c_real_multiplacement.py`
- Modify: `docs/reports/lot_h2b_production_readiness.md`

**Step 1: Write an integration test bound to real evidence**

Read the sealed metadata and the real PDF SHA
`371d0c82ed1f47614ee9cbfdaa86cfb4add1f239a84882d9731fbd125105925d`.
Require seven source placements, verify bytes, publish one artifact/chunk set
with at least two explicitly staging-resolved placements, retrieve both scopes,
block a third scope, and count zero duplicate chunks/results.

**Step 2: Run RED, implement script, run GREEN**

The script accepts evidence paths by CLI/env; it never versions an absolute path or PDF.

**Step 3: Commit**

```bash
git add services/rag-engine/scripts services/rag-engine/tests/integration docs/reports/lot_h2b_production_readiness.md
git commit -m "test(rag-engine): prouve le retrieval multi-placement réel"
```

## Task 7: Resolve production placements and collections fail-closed

**Files:**
- Create: `services/rag-pedago/tests/test_h2c_placement_readiness.py`
- Create: `services/rag-pedago/scripts/h2c_placement_readiness.py`
- Modify: `services/rag-engine/configs/rag_collections.yml`
- Create/Modify only justified taxonomy files under: `services/rag-engine/configs/taxonomies/`
- Create: `services/rag-engine/configs/ingestion_profiles/philosophie_terminale_tc_v1.yml`
- Create: `services/rag-engine/configs/ingestion_profiles/manifest.yml`

**Step 1: Write failing real-catalog tests**

Measure all 63 cleared candidates and 86 placements. Prove unknown scopes stay review-required. Prove the five terminale philosophy artifacts resolve exactly and the quarantined SHA is absent.

**Step 2: Add only justified collection activation/profile**

Set `rag_nexus_philo_terminale_tc.instanciee=true` only after taxonomy, profile, readiness and retrieval tests pass. Do not activate the other collections.

**Step 3: Run focused readiness tests and commit**

```bash
git add services/rag-pedago services/rag-engine/configs
git commit -m "feat(rag-engine): borne la collection philosophie initiale"
```

## Task 8: Wire the dormant LOT42 path without live activation

**Files:**
- Create: `services/rag-engine/tests/test_lot42_pipeline_path.py`
- Modify: `services/rag-engine/tests/test_lot42_retrieval_eligible_anchor.py`
- Create: `services/rag-engine/src/ingestor/ingestion_control/publication_pipeline.py`
- Modify: `services/rag-engine/src/ingestor/ingestion_worker/runner.py`
- Modify: `services/rag-engine/src/ingestor/ingestion_control/publication_attestation.py`

**Step 1: Write failing state-flow/AST tests**

Require ROUTED→STAGED→NEEDS_REVIEW→REVIEWED, a real reviewed LOT42 attestation, the existing unique anchor, then governed publisher invocation. Refuse unreviewed, invalid, stale or revoked chains.

**Step 2: Implement a dormant operator-invoked continuation**

Do not auto-promote from the worker and do not add an endpoint. The continuation requires durable human-review evidence and an explicit invocation; the production activation flag remains false.

**Step 3: Run GREEN and commit**

```bash
git add services/rag-engine/src/ingestor services/rag-engine/tests
git commit -m "feat(rag-engine): câble le chemin LOT42 gouverné hors production"
```

## Task 9: Build the true 12-guard mutation harness

**Files:**
- Create: `services/rag-pedago/tests/test_h2b_true_mutation_harness.py`
- Create: `services/rag-pedago/scripts/h2b_true_mutation_harness.py`
- Modify: `docs/reports/lot_h2b_production_readiness.md`

**Step 1: Write a meta-test that rejects vacuous mutations**

Each mutation must snapshot a target file SHA, prove baseline green, replace one exact guard, prove one named targeted test red for the expected direct reason, restore in `finally`, verify exact SHA, then prove green.

**Step 2: Implement the 12 mutations**

Map rights, PII, currentness, exclusion, unsupported, unknown object, content SHA, manifest, scope authority, revocation, extraction failure and single disposition to exact source guard + exact test.

**Step 3: Run full matrix**

Run: `python services/rag-pedago/scripts/h2b_true_mutation_harness.py --report /tmp/h2b_true_mutations.json`

Expected: `H2B_TRUE_MUTATIONS_NON_VACUOUS=12/12`, original SHAs restored, worktree clean except intended H2 files.

**Step 4: Commit**

```bash
git add services/rag-pedago docs/reports/lot_h2b_production_readiness.md
git commit -m "test(governance): exécute douze mutations H2-B non vacues"
```

## Task 10: Run a full governed LOT42 rehearsal

**Files:**
- Create: `services/rag-engine/tests/integration/test_h2c_governed_rehearsal.py`
- Create: `services/rag-engine/scripts/h2c_governed_rehearsal.py`
- Modify: `docs/reports/lot_h2b_production_readiness.md`

**Step 1: Write the disposable end-to-end test**

Use real PII-clear bytes and genuine staging workflow events: scope authority stub explicitly marked staging, rights, quality, gate, staging human review boundary, LOT42 verification, RETRIEVAL_ELIGIBLE, product publication, retrieval and citations. Never claim it as production attestation.

**Step 2: Implement and run on disposable PostgreSQL/pgvector**

Expected: `FULL_GOVERNED_REHEARSAL_PASS=true`, production targets absent.

**Step 3: Commit**

```bash
git add services/rag-engine/scripts services/rag-engine/tests/integration docs/reports/lot_h2b_production_readiness.md
git commit -m "test(rag-engine): répète la publication LOT42 gouvernée"
```

## Task 11: Create the real dedicated LOT41A authorization PR

**Files:**
- Create in isolated governance worktree: `governance/authorizations/<authorization_id>.json`
- Update evidence only on H2 branch after live observation: `docs/reports/lot_h2b_production_readiness.md`

**Step 1: Verify H2 branch technical prerequisite tests**

Recompute philosophy profile fingerprint, manifest digest, the five covered content SHAs, PII evidence binding, domains, rights and validity. Abort on any drift.

**Step 2: Create an isolated worktree from the canonical base**

Create branch `governance/h2-initial-corpus-scope-20260808` in `.worktrees/` after verifying the directory is ignored.

**Step 3: Generate canonical bytes through `ScopeAuthorizationArtifact`**

Do not hand-author JSON. Parse the written bytes back and compare exact canonical bytes/digest.

**Step 4: Commit, push, and open one dedicated ready PR**

PR must stay open, not draft, not merged, and must not be self-approved. Derive the LOT41V challenge from live PR head using repository code.

**Step 5: Stop if trusted approval is absent**

Expected normal boundary: `NEXT_ACTION=LOT41A_TRUSTED_HUMAN_REVIEW`.
Do not record the authorization, claim real authority, run final audit, or mark PR95 ready until `abenrhouma` approves the exact authority head.

## Task 12: After trusted LOT41A approval, close the technical gate

**Files:**
- Modify: `docs/reports/lot_h2b_production_readiness.md`
- Modify: PR #95 body via GitHub only after evidence is final

**Step 1: Verify live exact approval and record in disposable DB**

Use the canonical operator CLI, then reverify the real GitHub PR/blob. Test revocation with a separate disposable authority artifact/PR, never by dismissing the production-intended review.

**Step 2: Recompile the real corpus**

Measure every disposition and all old/new eligibility invariants. Do not assume five eligible artifacts; record actual counts.

**Step 3: Run canonical CI and security gates**

Run Python 3.12/Node 22 canonical local CI, integration suites, gitleaks/GitGuardian equivalents, PDF/PII/credential tracking scans, and exact GitHub checks on current head.

**Step 4: Commit final technical evidence and push**

Use a scoped documentation commit; update PR #95 body from observed results. Keep PR draft until the audit passes.

## Task 13: Independent H2 audit and final human boundary

**Files:**
- Create: `docs/reports/lot_h2c_independent_audit.md`

**Step 1: Freeze exact HEAD and launch an independent reviewer context**

The independent reviewer reads repository code and evidence, not this plan or the implementation report as authority. Audit schema, rollback, identities, isolation, dedup, PII, LOT41A, LOT42, mutations, citations, roles, writers, CI and evidence.

**Step 2: Remediate every blocking finding**

Any code change creates a new head and requires rerunning all gates plus a new independent audit.

**Step 3: Mark PR #95 ready only on zero blocking findings**

Derive the current H2 review challenge, request `abenrhouma`, never approve from the author account, and do not merge in this pass without a real exact-head approval.

**Step 4: Final safety assertions**

Verify production DB untouched, deployment/ingestion false, public/hidden writers false, LOT42 live wiring false, mutation bytes restored, and worktree clean.

