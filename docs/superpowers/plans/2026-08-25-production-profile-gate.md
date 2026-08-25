# Production Profile Gate Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` and strict RED-GREEN-REFACTOR.

**Goal:** Produce the exact 26-content production profile set, executable
release registry, 18-profile manifest, exact Git-tree placement projection,
and final corpus disposition evidence, then open a green exact-head PR and
stop at the trusted-human-review gate.

**Architecture:** Preserve P01-P10 bytes, retain P24 semantics, resolve P11-P23
from versioned/primary evidence, fail closed on 46 residuals, reuse existing
profile/release/placement contracts, and derive every digest mechanically.

**Tech stack:** Python 3.11+, Pydantic v2, PyYAML, pypdf, canonical JSON,
SHA-256, pytest, ruff, mypy, Git/GitHub CLI.

---

## Task 1: Freeze profile-gate expectations

**Files:**
- Create `services/rag-pedago/tests/test_production_profile_gate.py`
- Create `services/rag-pedago/tests/fixtures/production_profile_gate_expected.json`
- Create `docs/reports/production_profile_primary_evidence_20260825.json`

1. Add RED tests requiring 56 individual P11-P23 records, exactly ten
   `EXACTLY_GROUNDED`, 46 review-required residuals, and no production
   `unknown` or fallback `lycee_gt`.
2. Add RED tests for the exact ten eligible SHA and their seven expected
   profile identities.
3. Add RED tests requiring a per-content primary-evidence record with exact
   PDF/Drive identity, page/section locators, bounded decisive facts and
   BO/NOR identifiers; validate its coverage and digest, not only paths.
4. Run the focused module and record the failures.
5. Commit tests only: `rag-pedago: specify production profile gate`.

## Task 2: Implement deterministic resolution records

**Files:**
- Create `services/rag-pedago/scripts/build_production_profile_gate.py`
- Create `services/rag-pedago/configs/production_profile_decisions_20260825.json`
- Create `docs/reports/production_profile_resolution_records_20260825.json`
- Create `docs/reports/final_production_profile_matrix_20260825.json`
- Modify `services/rag-pedago/tests/test_production_profile_gate.py`

1. Implement the minimum data-driven resolver over the frozen proposed
   matrix, Drive mapping, scope audit, primary-evidence artifact and the named
   versioned decisions document.
2. Require each record to expose every field requested by the Direction.
3. Produce only grounded rows in the final placement matrix; emit residuals
   with `REVIEW_REQUIRED` reason codes. Rewrite every P01-P10 dimension source
   and evidence list to the promoted production-root YAML; add RED coverage
   for `MATRIX_PROFILE_SOURCE_MISMATCH` on any staging path.
4. Run focused tests GREEN, refactor duplicated validation, run ruff/mypy.
5. Commit: `rag-pedago: resolve final production profile set`.

## Task 3: Promote P01-P10 byte-identically

**Files:**
- Create ten YAML files under
  `services/rag-engine/configs/ingestion_profiles/`
- Modify `services/rag-pedago/tests/test_production_profile_gate.py`

1. Add RED assertions that each production file exists and has the same raw
   bytes as its staging source.
2. Add the ten files using exact staging bytes.
3. Run GREEN and assert 10 profiles / 11 contents / scope drift zero.
4. Commit: `rag-engine: promote grounded staging profiles`.

## Task 4: Add seven grounded production profiles

**Files:**
- Create seven YAML profiles in the production profile root
- Modify `services/rag-engine/configs/rag_collections.yml`
- Modify `services/rag-pedago/configs/eduscol_sources.yml`
- Modify focused tests

1. Add RED contract tests for all seven exact scopes and versions.
2. Add RED config tests for the DGEMC option collection and official source.
3. Implement the seven profiles and only the missing DGEMC collection/source.
4. Run registry/config tests GREEN; run ruff/mypy where applicable.
5. Commit: `rag-engine: add grounded production profiles`.

## Task 5: Build the exact production profile manifest

**Files:**
- Modify `services/rag-engine/configs/ingestion_manifest.yml`
- Modify profile gate tests

1. Add RED tests requiring registry identity = manifest identity = 18 and
   exact fingerprint equality.
2. Recompute fingerprints with `nexus-contracts` and update the manifest.
3. Run shared profile-manifest and engine startup/profile tests GREEN.
4. Commit: `rag-engine: seal production profile manifest`.

## Task 6: Build the executable 26-content release

**Files:**
- Create `services/rag-pedago/scripts/build_production_profile_release.py`
- Create release manifests under
  `services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/`
- Modify `services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json`
- Modify `services/rag-engine/src/ingestor/multilevel_verified_placement.py`
- Create/modify focused tests in both services

1. Add RED unit tests for SHA mismatch, missing PDF, wrong profile,
   out-of-set content, empty page/chunk, non-E5-bounded chunk and unstable
   output ordering.
2. Add RED exact-coverage and mutation tests for candidate inventory,
   currentness, PII, rights, preflight, programme registry, catalog/mappings,
   model inventories and profile manifest. Name every source path/digest in
   `authority_bindings.json`; never accept a shape-only digest.
3. Implement the producer by reusing the runtime page-aware chunking
   primitives and real local E5 tokenizer; do not create a second splitter.
   Reuse P01-P10 historical chunk facts only after exact validation.
4. Generate 18 subject manifests plus one aggregate for all 26 contents,
   each bound to the production profile manifest. Replace every historical
   registry entry, including Wave 0 and multilevel; retain their files
   unmodified as unregistered audit evidence.
5. Extend the multilevel resolver with strict production-manifest dispatch,
   preserving strict staging behavior. Add crossed-schema refusals.
6. Add the pinned registry entry and digest.
7. Assert that the registered artifact union is exactly the final 26 contents
   and 18 collections, with no Wave 0 or other extra.
8. Run `load_release_registry_file`, the actual production runtime consumer,
   and profile release tests GREEN, including P24 5/5/profile match 5/5.
9. Commit: `rag-pedago: register production profile release`.

## Task 7: Produce exact accepted placements from a Git tree

**Files:**
- Create `governance/release-scope/accepted-production-placements-20260825.json`
- Create `governance/profiles/verified-production-profiles-20260825.json`
- Create `governance/release-scope/release-scope-placement-20260825.json`
- Create `docs/reports/final_production_eligible_set_20260825.txt`
- Modify release-scope tests

1. Add RED tests for 26/26 exact coverage and mutations: profile source,
   fingerprint, manifest, release, gap, extra, overlap, residual placement.
2. Generate verified profile facts and accepted placements mechanically.
3. Commit every producer input and every referenced evidence/profile blob as
   an immutable source-tree commit. Record its commit and tree SHA.
4. Run `produce_release_scope_placement_from_git` against that exact commit.
   Add only the canonical output/provenance in a second commit.
5. Add a final HEAD check comparing all producer input blob SHA to the source
   commit; any rebase or mutation forces regeneration.
6. Run focused tests GREEN.
7. Commit: `rag-pedago: place final production release scopes`.

## Task 8: Recompute terminal dispositions and Master Go-Live

**Files:**
- Modify `services/rag-pedago/scripts/recompute_final_release_set.py`
- Modify `services/rag-pedago/tests/test_recompute_final_release_set.py`
- Modify `services/rag-pedago/tests/test_multi_authorization_release_report.py`
- Create `docs/reports/terminal_disposition_summary_20260825.json`
- Create `docs/reports/lot_production_profiles_20260825.md`
- Modify Master Go-Live JSON/Markdown and checklist

1. Add RED tests for final N=26, review count 46, new set digest, 2 582
   unique/accounted contents and 100% terminal disposition coverage.
2. Implement profile-gate filtering without changing historical evidence.
3. Generate final artifacts and update Master Go-Live vocabulary from
   historical final to pre-profile where required.
4. Keep downstream authorization/republish/H2/ingestion/API facts at zero or
   false.
5. Run report/recompute tests GREEN.
6. Commit: `rag-pedago: freeze final production eligible set`.

## Task 9: Full verification and adversarial review

1. Run contracts tests, service lint/typecheck/test, engine release/profile
   tests, governance locks, repository controls and differential gitleaks.
2. Run mutation/adversarial focused tests.
3. Run the full local CI when disk capacity permits; otherwise free only
   task-created caches and record exact environmental failure without
   claiming green.
4. Dispatch two fresh contradictory reviews: correctness/spec and
   security/fail-closed. Turn every valid finding into RED, fix, rerun.
5. Finalize the lot report with commands and results.

## Task 10: Push, PR, CI and exact-head human gate

1. Rebase/merge latest `origin/main` only if the baseline moved; rerun all
   verification after any tree change.
2. Push branch and open one production profile PR, with no authorization.
3. Monitor GitHub CI, repair failures through TDD, and resolve all threads.
4. Close PR #96 as superseded. Leave #98 evidence-only until the new P24
   authorization exists.
5. Freeze final PR base/head/tree, compute the real trusted-review challenge,
   and stop without self-review or merge.

Expected gate payload: PR number, exact base/head/tree SHA, final N and set
digest, profile/release placement counts, CI green, zero unresolved threads,
and trusted-human-review challenge.
