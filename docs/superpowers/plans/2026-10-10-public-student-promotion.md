# Public Student Successor Promotion Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development for independent tasks. Steps use checkbox syntax for tracking.

**Goal:** Produce a governed, ingestible public text-derivative release from the approved #300/#312 candidate, without changing the rehearsal releases or deploying anything.

**Architecture:** Preserve the immutable #312 candidate. Build a distinct release from its verified manifests and private CAS, bind every derived SHA to the #300 delegated evidence and the #312 exact-head approval, and seal new public profiles, inventory, rights/PII/currentness evidence and scope authorities. The final approval must bind the exact HEAD and all new digests; until then the package remains non-activable.

**Tech Stack:** Python 3.12, Pydantic contracts, canonical JSON/YAML, pytest, GitHub trusted-review verifier.

---

## Chunk 1: Provenance and public profile projection

### Task 1: Verify the approved candidate

**Files:** `scripts/go_live/pr312_authority_receipt.py`, `scripts/tests/test_pr312_authority_receipt.py`, a versioned #312 receipt.

- [ ] Write failing tests for exact HEAD/tree, pre-merge trusted status, and candidate digest mismatch.
- [ ] Run targeted pytest and confirm each test fails for the intended reason.
- [ ] Implement a live fail-closed receipt check using the canonical GitHub verifier.
- [ ] Re-run tests; record the exact #312 review and candidate digests.

### Task 2: Produce full public collection profiles

**Files:** `services/rag-pedago/scripts/build_student_public_promotion.py`, `services/rag-pedago/tests/test_build_student_public_promotion.py`, successor profile YAML and manifest.

- [ ] Write failing tests that project all eleven source profiles into complete `CollectionProfile` values with `visibility=public`, new version and unchanged pedagogical dimensions.
- [ ] Run targeted pytest and verify the intended red result.
- [ ] Implement strict source digest checks and deterministic profile YAML/manifest generation.
- [ ] Re-run tests, including source tampering, internal scope and invalid audience sabotages.

## Chunk 2: Ingestible successor and evidence

### Task 3: Rebuild the sealed inventory and private transfer allowlist

- [ ] Test exact joins of 253 derivative SHA / 377 placement IDs to the candidate, with no PDF, unknown SHA or missing private bytes.
- [ ] Generate a new inventory and transfer allowlist; only a completed byte-verified transfer may claim a transfer manifest.
- [ ] Verify Worker A reads the sealed inputs in a temporary target without control writes.

### Task 4: Bind rights, PII and currentness to derivatives

- [ ] Test that #300 source-level approval alone cannot authorize an arbitrary derivative.
- [ ] Build verified registries from the exact derivative receipts, full scan evidence and source dates.
- [ ] Extend the canonical attestor with a closed derivative evidence branch, preserving old PDF behavior.

## Chunk 3: Public scopes and review gate

### Task 5: Seal a new release and eleven public scopes

- [ ] Test rejection of a renamed candidate or internal student scope.
- [ ] Issue new release/subject IDs, complete authority digests, LOT41A-V2 authorizations and LOT42 batch review proposal.
- [ ] Emit eleven new public scope artifacts without changing historical scopes; test exact IDs/digests.

### Task 6: Independently verify and publish the reviewable pack

- [ ] Run sabotage tests, all targeted unit/integration suites, static checks and CI.
- [ ] Record actual counts, digests and limitations in the lot report and update ADR-0064/runbook.
- [ ] Open the technical PR with no staging/production mutation; after all contexts pass, generate one exact-HEAD authority challenge.
