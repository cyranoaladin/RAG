# Multi-Authorization Release V2 Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan task-by-task, with spec-compliance review then code-quality review after each task.

**Goal:** Add a canonical multi-authorization composition protocol that proves the exact 72-content release union through campaign, H2, promotion, readiness, deploy, startup, and per-job execution without changing any legacy V1 bytes.

**Architecture:** Keep every `ScopeAuthorizationArtifactV2` and `ScopeAuthorizationReviewBindingV1` individual. Compose them in canonical `AuthorizationSetV1`, prove each content-to-scope assignment against an independent release placement projection, and reference the set digest from explicit Campaign/H2/Promotion/Readiness V2 protocols. Runtime jobs remain single-authorization and receive their ID from the republished catalog mapping.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, ruff, mypy, GitHub Actions YAML, canonical JSON + SHA-256, Ed25519 verification.

**Execution authorization:** The operator explicitly authorized implementation through the dedicated PR and requested stopping only at that PR's human gate. This plan is therefore executed automatically after review.

---

## Task 0: Freeze immutable V1 golden bytes before implementation

**Files:**
- Create: `packages/contracts/tests/fixtures/legacy_v1/h2_coverage_evidence_v1.json`
- Create: `packages/contracts/tests/fixtures/legacy_v1/production_readiness_signed_v1.json`
- Create: `services/rag-pedago/tests/fixtures/legacy_v1/corpus_campaign_v1.json`
- Create: `services/rag-pedago/tests/fixtures/legacy_v1/h2_evidence_bundle_v1.json`
- Modify: `packages/contracts/tests/test_h2_coverage_evidence_contract.py`
- Modify: `packages/contracts/tests/test_production_readiness_contract.py`
- Modify: `services/rag-pedago/tests/test_corpus_campaign.py`
- Modify: `services/rag-pedago/tests/test_h2_evidence.py`

**Step 1: Capture from the exact baseline implementation**

Generate each fixture once with the current V1 builder on baseline commit
`3548bf300c99685ff6ede0dce2e5bfe8c044d213`, using fixed timestamps, IDs,
digests and the existing deterministic test key. Record its SHA-256 beside
the fixture in the test. Never regenerate these files from a future model.

**Step 2: Add characterization tests**

For each fixture, assert exact fixture SHA-256, strict V1 parse, and exact
byte-for-byte reserialization. For signed readiness also assert signature
verification with the frozen public test key.

**Step 3: Run the four characterization tests**

Run the focused contract and `rag-pedago` modules listed above. Expected:
PASS on unmodified V1 code. This is a characterization checkpoint, not a
RED cycle.

**Step 4: Commit**

`git commit -m "contracts: freeze legacy V1 protocol bytes"`

## Task 1: Version the decision, audit, and release facts

**Files:**
- Create: `docs/adr/ADR-0044-composition-multi-autorisation-release.md`
- Create: `docs/reports/multi_authority_contract_surface_audit_20260823.md`
- Create: `docs/reports/proposed_production_profile_matrix_20260823.json`
- Verify: `docs/reports/final_authority_required_set_20260823.txt`
- Create: `services/rag-pedago/scripts/recompute_final_release_set.py`
- Create: `services/rag-pedago/tests/test_recompute_final_release_set.py`
- Modify: `packages/contracts/pyproject.toml`
- Modify: `packages/contracts/tests/test_schema_export.py`

**Step 1: Write the failing version and reproduction tests**

Update the existing package-version/schema-export assertion to require `0.13.0`, the first additive release containing the new protocols.

Add a deterministic test that runs the repository script against the sealed
catalogue, PII, rights, routing, currentness, manifest and golden inputs. It
must reproduce 73 base candidates, one non-authority block, the 72-line
LF-terminated sorted file, and digest
`3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0`.

**Step 2: Run the test and observe RED**

Run: `PYTHONPATH=src pytest -q tests/test_schema_export.py`
Expected: FAIL because the current version is `0.12.0`.

Run: `PYTHONPATH=rag_pedago:../../packages/contracts/src pytest -q tests/test_recompute_final_release_set.py`
Expected: FAIL because the reproducible producer does not exist.

**Step 3: Write the minimum decision artifacts**

- Bump only the package version to `0.13.0`.
- Record ADR-0044 with problem, exhaustive singularity inventory, selected `AuthorizationSet`, V1/V2 compatibility, canonicalization, independent placement proof, exact union, anti-overlap, revocation, expiry, binding freshness, H2, campaign, readiness, signer, deploy/startup, job mapping, migration, and rollback.
- State explicitly that ADR-0043 is `UNREVIEWED_WIP`, `NON_AUTHORITATIVE`, `NOT_REUSED`.
- Version the exhaustive audit matrix with columns `FILE`, `FUNCTION/CLASS`, `CURRENT_CARDINALITY`, `TRUST_SEMANTICS`, `NEEDS_CHANGE_FOR_N_AUTH`, `WHY`.
- Version the exact 24-row profile proposal with per-dimension source and grounded flag; retain 14 decision-required partitions without invented values.
- Implement the read-only producer by composing existing compilers/gates; do
  not embed the answer as a constant and do not write outside an explicit
  output directory.

**Step 4: Run the version test and document checks**

Run: `PYTHONPATH=src pytest -q tests/test_schema_export.py`
Expected: PASS.

Run: `PYTHONPATH=rag_pedago:../../packages/contracts/src pytest -q tests/test_recompute_final_release_set.py`
Expected: PASS, including the exact line count, final LF, digest and terminal
2,582-content disposition accounting.

Run: `rg -n "ADR-0043|UNREVIEWED_WIP|NON_AUTHORITATIVE|NOT_REUSED|AuthorizationSet|rollback" docs/adr/ADR-0044-composition-multi-autorisation-release.md`
Expected: every required decision is present.

**Step 5: Commit**

`git commit -m "contracts: record multi-authorization architecture"`

## Task 2: Add the canonical AuthorizationSet contract

**Files:**
- Create: `packages/contracts/src/nexus_contracts/authorization_set.py`
- Modify: `packages/contracts/src/nexus_contracts/__init__.py`
- Create: `packages/contracts/tests/test_authorization_set_contract.py`

**Cycle A: Structure and canonicalization — RED then GREEN**

Write only structure tests: zero members, duplicate IDs/digests/scopes,
permuted input producing one stable digest, changed member changing the
digest, and noncanonical persisted bytes refusing. Run the module and observe
RED on the missing model. Implement strict `AuthorizationSetMemberV1`,
`ReleaseScopePlacementV1`, and `AuthorizationSetV1` plus canonical bytes and
parse/digest. Run again and observe GREEN.

**Cycle B: Exact member material — RED then GREEN**

Add tests for derived paths, missing member material, supplied extra member
material, wrong authorization digest, wrong binding digest, and coexistence
of unrelated historical files. Observe each new test fail against Cycle A;
then implement exact supplied-material verification and observe GREEN.

**Cycle C: Independent placement and profile facts — RED then GREEN**

Add wrong placement mapping, wrong profile ID/version/fingerprint/scope, and
wrong projection digest tests. Observe RED, then implement only pure
comparisons between the set, `ReleaseScopePlacementV1`, authorization
artifacts, and caller-supplied verified profile facts. `nexus-contracts`
must not import `rag-pedago` or `rag-engine` and must not read a service
registry.

**Cycle D: Revocation, time, overlap, and exact union — RED then GREEN**

Add one revoked, one expired, one future, boundary `now == valid_until`,
overlap, duplicate content, required-set gap, and extra-content tests. Observe
every class of refusal fail first. Then reuse the shared canonical revocation
model, apply `valid_from <= now < valid_until`, compute aggregate validity,
and require union equality. Observe GREEN.

**Step 5: Run the complete module**

Run: `PYTHONPATH=src pytest -q tests/test_authorization_set_contract.py tests/test_authorization_revocations_contract.py`
Expected: PASS.

**Step 6: Refactor and lint**

Run: `ruff check src/nexus_contracts/authorization_set.py tests/test_authorization_set_contract.py`
Expected: PASS.

**Step 7: Commit**

`git commit -m "contracts: add canonical authorization set"`

## Task 2B: Produce and verify the independent release placement projection

**Files:**
- Create: `services/rag-pedago/rag_pedago/governance/release_scope_placement.py`
- Modify: `services/rag-pedago/rag_pedago/governance/cli.py`
- Create: `services/rag-pedago/tests/test_release_scope_placement.py`
- Create: `services/rag-engine/src/ingestor/release_scope_placement.py`
- Create: `services/rag-engine/tests/test_release_scope_placement.py`

**Cycle A: Producer — RED then GREEN**

Write a `rag-pedago` test with two accepted placements, a release registry
and two verified profile records. Require a canonical
`ReleaseScopePlacementV1` artifact keyed by content SHA. Observe RED, then
implement the producer using only local `rag-pedago` loaders and the shared
pure contract. Add failures for ambiguous placement, unknown profile,
unrepresentable scope, and missing content; observe RED then GREEN one
invariant at a time.

**Cycle B: Service-local verification adapters — RED then GREEN**

Write `rag-engine` tests that load profiles through its own registry,
project verified profile facts, and compare them to the shared artifact.
Test changed profile manifest, changed scope and changed placement digest.
Observe RED, then implement the adapter without importing `rag-pedago`.

**Step 3: Run both modules**

Run each service-local module with its service `PYTHONPATH`; expected PASS.
The current 72-content production projection is intentionally not emitted
until the 14 product profile decisions are grounded; the producer must
instead return an explicit `PROFILE_DECISION_REQUIRED` failure for those
inputs, never invent values.

**Step 4: Commit**

`git commit -m "rag-pedago: produce canonical release scope placements"`

## Task 3: Add explicit H2 and readiness V2 contracts

**Files:**
- Modify: `packages/contracts/src/nexus_contracts/h2_coverage_evidence.py`
- Modify: `packages/contracts/src/nexus_contracts/production_readiness.py`
- Modify: `packages/contracts/src/nexus_contracts/__init__.py`
- Modify: `packages/contracts/tests/test_h2_coverage_evidence_contract.py`
- Modify: `packages/contracts/tests/test_production_readiness_contract.py`

**Cycle A: H2 V2 structure — RED then GREEN**

Add tests that H2 V2 uses the authorization-set identity, exact coverage
aggregates and real input-file digests. Observe RED, implement only
`H2CoverageEvidenceV2`, then observe GREEN.

**Cycle B: Readiness V2 structure and signature — RED then GREEN**

Add tests that readiness V2 uses `authorization_set_digest`, not singular
authorization/binding fields, and that signed V2 canonical bytes and
signature verify. Observe RED, implement only V2 models/sign/verify, then
observe GREEN.

**Cycle C: Strict protocol dispatch — RED then GREEN**

Add crossed-parser tests: H2 V2 as V1, readiness V2 as V1, and both V1
fixtures as V2. Observe RED if any parser is permissive; add exact dispatch
and observe GREEN. Re-run all four immutable Task 0 golden tests and require
the recorded fixture digests and byte reserialization unchanged.

**Step 4: Run focused tests**

Run: `PYTHONPATH=src pytest -q tests/test_h2_coverage_evidence_contract.py tests/test_production_readiness_contract.py`
Expected: PASS.

**Step 5: Run all contract tests**

Run: `PYTHONPATH=src pytest -q`
Expected: PASS.

**Step 6: Commit**

`git commit -m "contracts: add H2 and readiness V2 protocols"`

## Task 4: Add Campaign V2 and multi-authorization coverage

**Files:**
- Modify: `services/rag-pedago/rag_pedago/governance/corpus_campaign.py`
- Modify: `services/rag-pedago/rag_pedago/imports/h2b_coverage_report.py`
- Modify: `services/rag-pedago/tests/test_corpus_campaign.py`
- Modify: `services/rag-pedago/tests/test_h2b_coverage_report.py`

**Cycle A: Campaign V2 identity — RED then GREEN**

Test one authorization-set digest plus exact required count/set digest/profile
manifest while preserving corpus manifest identity. Observe RED, implement
Campaign V2 build/load/verify, observe GREEN. Add crossed V1/V2 parsing RED,
make dispatch strict, and re-run the immutable Campaign V1 golden.

**Cycle B: Exact material and manifest domains — RED then GREEN**

Add missing/extra/duplicate member, bad authorization/binding digest, wrong
corpus manifest, and crossed corpus/profile manifest tests. Observe RED, wire
the shared set verifier and separate domains, observe GREEN.

**Cycle C: Placement, union and overlap — RED then GREEN**

Add wrong placement, gap, extra and overlap tests. Observe each fail before
implementing the typed counts/digests and exact-equality gate.

**Cycle D: Revocation and review times — RED then GREEN**

Add one revoked, one expired/future authorization, bad/expired binding and
stale human submission/binding verification tests. Observe RED, then expose
separate `authorization_set_verified_at`, earliest human `submitted_at`,
earliest binding `verified_at`, and earliest expiry aggregates. Observe
GREEN.

**Step 4: Run focused tests and observe GREEN**

Run: `PYTHONPATH=rag_pedago:../../packages/contracts/src pytest -q tests/test_corpus_campaign.py tests/test_h2b_coverage_report.py -k 'v2 or multi_authorization or authorization_set'`
Expected: PASS.

**Step 5: Run legacy regression tests**

Run: `PYTHONPATH=rag_pedago:../../packages/contracts/src pytest -q tests/test_corpus_campaign.py tests/test_h2b_coverage_report.py`
Expected: PASS.

**Step 6: Commit**

`git commit -m "rag-pedago: verify multi-authorization campaign coverage"`

## Task 5: Republish exact content-to-authorization mappings

**Files:**
- Modify: `services/rag-pedago/rag_pedago/governance/catalog_republish.py`
- Modify: `services/rag-pedago/tests/test_catalog_republish.py`
- Create: `services/rag-engine/src/ingestor/ingestion_worker/authorization_mapping.py`
- Create: `services/rag-engine/tests/test_authorization_mapping.py`

**Cycle A: Republished content mapping — RED then GREEN**

- Republish V2 promotes exactly the set union and writes one `scope_authorization_id`, profile identity, and exact scope for each content.
- A gap, extra, overlap, or placement mismatch refuses publication.
Observe those adversarial tests fail, then build the mapping only from the
verified set and placement artifact. Observe GREEN.

**Cycle B: Immutable lookup helpers — RED then GREEN**

Write pure engine tests for two explicit lookups over a parsed, digest-checked
set: `content_sha256 -> authorization_id` for already republished batch
content, and `scope_digest -> authorization_id` for pre-fetch operator jobs.
Require exactly one match and reject unknown/ambiguous scope, changed set
digest and any "latest" selection. Observe RED, implement the helper, then
observe GREEN.

The immutable inputs are the canonical AuthorizationSet bytes and the
`authorization_set_digest` already signed by readiness. Content lookup key is
the lowercase `content_sha256`; pre-fetch lookup key is the canonical
`scope_digest`. The helper never reads the republished catalog by URL and
never guesses an authorization.

There is no batch job producer consuming the republished catalog on current
`main`. This PR therefore delivers and tests the canonical content mapping
but does not claim a batch caller integration. The later real-campaign lot
must add that caller end-to-end and copy the mapped ID into the singular
payload; this deferral is recorded in ADR-0044 and the lot report.

**Step 3: Run focused tests and observe GREEN**

Run the same modules; expected PASS.

**Step 4: Commit**

`git commit -m "rag-engine: bind jobs to republished authorization mapping"`

## Task 6: Produce H2 bundle and promotion evidence V2

**Files:**
- Modify: `services/rag-pedago/rag_pedago/governance/h2_evidence.py`
- Modify: `services/rag-pedago/rag_pedago/governance/cli.py`
- Modify: `services/rag-pedago/tests/test_h2_evidence.py`
- Modify: `services/rag-pedago/tests/test_h2_evidence_e2e_rehearsal.py`
- Modify: `services/rag-pedago/tests/test_h2_evidence_workflow_paths.py`
- Modify: `.github/workflows/_produce-h2-evidence.yml`
- Modify: `.github/workflows/promote.yml`

**Cycle A: H2 bundle identity and dispatch — RED then GREEN**

Test that H2 bundle V2 binds Campaign V2, H2 coverage V2, authorization
set and real input digests. Observe RED, implement the model/parser, observe
GREEN. Add V1/V2 crossed parsing tests, observe RED if permissive, fix and
re-run the immutable H2 bundle V1 golden.

**Cycle B: Human-review freshness — RED then GREEN**

Add oldest human submission older than seven days, oldest binding verified
older than seven days, future date, expired binding, and freshly reverified
set with stale review tests. Observe RED, implement the three independent
aggregates and existing seven-day boundary, observe GREEN.

**Cycle C: Promotion link — RED then GREEN**

Add wrong set digest, wrong campaign, gap/overlap/extra and changed H2 bundle
tests. Observe RED, implement Promotion Evidence V2 with set digest, observe
GREEN.

**Cycle D: CLI/workflow plumbing — RED then GREEN**

Add path tests requiring `--authorization-set`, `--json-output`, aggregated
binding dates and no singular authority flags on the V2 route. Observe RED,
modify CLI/workflows, observe GREEN.

**Step 4: Run tests and observe GREEN**

Run the same three modules; expected PASS.

**Step 5: Commit**

`git commit -m "rag-pedago: bind H2 promotion to authorization set"`

## Task 7: Sign and verify readiness V2

**Files:**
- Modify: `services/rag-engine/scripts/sign_production_readiness_manifest_cli.py`
- Modify: `services/rag-engine/tests/test_sign_production_readiness_manifest_cli.py`
- Modify: `services/rag-engine/scripts/deploy_verified_release_cli.py`
- Modify: `services/rag-engine/tests/test_deploy_verified_release_cli.py`

**Cycle A: Signer exact material — RED then GREEN**

Add missing/extra/duplicate member, bad authorization/binding/set digest and
wrong derived path tests. Observe RED, wire the shared set verifier and
governed-root resolution, observe GREEN.

**Cycle B: Signer trust gates — RED then GREEN**

Add overlap/gap/extra union, wrong placement/profile/corpus domain, one
revoked, one expired/future, bad binding, and exact expiry boundary tests.
Observe each refusal RED, then implement the minimum reuse of shared
verification and observe GREEN.

**Cycle C: Deploy material and time — RED then GREEN**

Add changed set, registry, profile manifest and aggregate-window tests.
Observe RED, implement V2 materialization/re-hashing, observe GREEN.

**Cycle D: Legacy dispatch — RED then GREEN**

Add signed V2-as-V1 and signed V1-as-V2 tests. Observe RED if any fallback
exists, then require explicit protocol selection. Re-run the immutable signed
readiness V1 golden including signature verification.

**Step 4: Run focused then full modules**

Run the focused selection, then both full modules; expected PASS.

**Step 5: Commit**

`git commit -m "rag-engine: sign and deploy authorization-set readiness"`

## Task 8: Enforce readiness V2 at startup with one revocation schema

**Files:**
- Modify: `services/rag-engine/src/ingestor/ingestion_profiles/readiness_gate.py`
- Modify: `services/rag-engine/src/ingestor/ingestion_profiles/startup_gate.py`
- Modify: `services/rag-engine/src/ingestor/ingestion_control/revocation_registry.py`
- Modify: `services/rag-engine/src/ingestor/ingestion_worker/create_job_cli.py`
- Modify: `services/rag-engine/src/ingestor/ingestion_worker/runner.py`
- Modify: `services/rag-engine/infra/docker-compose.production-workers.yml`
- Modify: `services/rag-engine/tests/test_readiness_gate.py`
- Modify: `services/rag-engine/tests/test_revocation_registry.py`
- Modify: `services/rag-engine/tests/test_deployment_image_inventory.py`
- Create: `services/rag-engine/tests/test_production_authorization_set_wiring.py`
- Modify: `services/rag-engine/tests/integration/test_lot44f_create_job_cli_idempotency.py`
- Modify: `services/rag-engine/tests/test_lot41a_scope_enforcement.py`
- Modify: `services/rag-engine/tests/integration/test_startup_gate_requires_readiness_manifest.py`

**Cycle A: Revocation schema dispatch — RED then GREEN**

Test shared `NEXUS-AUTHORIZATION-REVOCATIONS-V1` on V2 and historical
runtime schema only on explicit legacy V1. Add both crossed-schema refusals.
Observe RED, add named dispatch, observe GREEN.

**Cycle B: Startup material — RED then GREEN**

Test signed readiness V2, set digest, current registry digest, aggregate
validity, changed set, revoked member, and `now == valid_until`. Observe RED,
implement the V2 gate, observe GREEN.

**Cycle B2: Production material wiring — RED then GREEN**

Add Compose tests proving both production worker services require
`PRODUCTION_AUTHORIZATION_SET_HOST_FILE`, mount it read-only at exactly
`/app/production/authorization-set.json`, and expose
`NEXUS_AUTHORIZATION_SET_PATH` with that same path. Assert the deploy bundle
contains the exact set bytes selected by the signed digest. Add the
adversarial case "correct bundle + bind source pointing to different set
bytes" and assert deploy refuses before `docker compose pull` or `up`.
Observe RED, then make deploy resolve and hash the effective bind source (or
materialize the variable itself to exactly
`<verified-bundle>/authorization-set.json`) and compare it to the signed set
digest before any mutation. Wire the host-file/mount/env and bundle output,
then observe GREEN. No wildcard authority directory lookup substitutes for
this explicit file.

**Cycle C: Runtime profile identity — RED then GREEN**

Test a profile manifest that passes local schema verification but has a
different digest from the set. Observe RED, compare the digest of the
actually loaded manifest, observe GREEN.

**Cycle D: Per-job two-checkpoint mapping — RED then GREEN**

The readiness gate returns the parsed set whose bytes matched the signed
digest. Before fetch, `create_job_cli` validates the operator's singular ID
against the unique `scope_digest` lookup from Task 5; add wrong/ambiguous ID
tests in the real integration path and observe RED before wiring it. After
fetch, the worker verifies the actual lowercase `content_sha256` belongs to
that individual authorization; add a wrong-content test and observe RED
before wiring it. The payload remains singular and never stores the global
set. Observe GREEN for both checkpoints.

**Step 4: Run tests and observe GREEN**

Run the same tests; expected PASS.

**Step 5: Commit**

`git commit -m "rag-engine: enforce authorization set at startup"`

## Task 9: Integrate exact release evidence and close the lot report

**Files:**
- Create: `docs/reports/lot_multi_authorization_release_v2_20260823.md`
- Modify: `docs/reports/master_go_live_state_20260815.json`
- Modify: `docs/reports/master_go_live_state_20260815.md`
- Modify: `docs/checklists/production_go_live_checklist.md`
- Verify: `docs/reports/final_authority_required_set_20260823.txt`
- Create: `services/rag-pedago/tests/test_multi_authorization_release_report.py`

**Step 1: Write report assertions before report updates**

Create `test_multi_authorization_release_report.py` to require:

- final 73/1/72 algebra and exact set digest;
- `FINAL_ELIGIBLE_SET_FROZEN=true`;
- terminal 2,582-content disposition counts, `UNACCOUNTED_CONTENTS=0`, coverage 100%;
- Cloudflare network work closed and nonblocking;
- Docker rehearsal false/untouched facts, DB read-only blocked facts, and exact proposed GitHub Environment settings;
- explicit unresolved profile decisions for 61 contents.
- exact 72 lines, sorted lowercase SHA-256, final LF, and file SHA-256
  `3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0`.

**Step 2: Run the test and observe RED**

Run: `PYTHONPATH=rag_pedago:../../packages/contracts/src pytest -q tests/test_multi_authorization_release_report.py`
Expected: FAIL on stale master value 63 or absent facts.

**Step 3: Update reports from reproduced evidence only**

- Never hand-replace 63 with 72 without recording the recomputation command and input digests.
- Record the baseline full-suite transient failure and its isolated passing rerun as preexisting test pollution evidence.
- Record Docker/DB/environment truth without claiming unavailable production verification.
- Record every implementation commit and CI command.

**Step 4: Run report test and observe GREEN**

Run: `PYTHONPATH=rag_pedago:../../packages/contracts/src pytest -q tests/test_multi_authorization_release_report.py tests/test_recompute_final_release_set.py`
Expected: PASS and exact byte identity between the committed set and the
producer output.

**Step 5: Commit**

`git commit -m "rag-pedago: freeze final release authority set"`

## Task 10: Verify, review, push, and open the human-gate PR

**Files:**
- Modify only defects found by verification/review.
- Update: `docs/reports/lot_multi_authorization_release_v2_20260823.md`

**Step 1: Run service quality gates**

From `packages/contracts`: full pytest, ruff, mypy according to `pyproject.toml`.

From `services/rag-pedago`: `make lint`, `make typecheck`, `make test`.

From `services/rag-engine`: `make lint`, `make typecheck`, `make test`, `make smoke` when available.

From repository root: `bash scripts/ci-local.sh`.

Expected: all green. Any new failure returns to RED-GREEN-REFACTOR before proceeding.

**Step 2: Run independent code and security review**

Review the complete diff against ADR-0044 and the operator's adversarial cases. Fix every valid finding with a reproducing test. Repeat until no findings.

**Step 3: Finalize the non-self-referential lot report**

Commit the report with base SHA, ADR, contract version and verification
command outcomes. Do not put final HEAD/TREE, PR number or trusted-review
challenge in a committed file: those values do not exist until the final PR
head and would make the commit self-referential.

**Step 4: Push and create the dedicated PR**

Push `rag-pedago/multi-auth-contract-v2-20260823`, open one PR against `main`, monitor CI and review threads, resolve actionable failures/comments, and require `THREADS_UNRESOLVED=0`. Any correction creates a new head and restarts full verification and review.

**Step 5: Stop at the human gate**

Only after CI is green and threads are zero, calculate `HEAD_SHA`,
`TREE_SHA` and the trusted-review challenge from that immutable final head.
Do not recommit those values. Return only when the PR has exact:

- `PR_NUMBER`
- `BASE_SHA`
- `HEAD_SHA`
- `TREE_SHA`
- `ADR=ADR-0044`
- `CONTRACT_VERSION=0.13.0`
- `CI_GREEN=true`
- `THREADS_UNRESOLVED=0`
- `TRUSTED_REVIEW_CHALLENGE`

Do not merge the PR. This is the next real HUMAN GATE.
