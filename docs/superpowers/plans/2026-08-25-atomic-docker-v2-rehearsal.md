# Atomic Docker V2 Rehearsal Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a reproducible V2 Docker rehearsal that proves valid deployment, all mandated pre-mutation refusals, foreign-service isolation, rollback, and complete cleanup.

**Architecture:** Add one focused Python CLI around the existing atomic deployment wrapper plus a parameterized, non-test V2 fixture builder with no default key material. Keep project-name validation, snapshots, bundle mutation and evidence serialization pure; keep Docker orchestration at the CLI boundary and always clean only generated projects in `finally`.

**Tech Stack:** Python 3.11+, pytest, Docker Engine/Compose, existing `nexus_contracts` and `rag-engine` deployment/signing modules.

---

## Chunk 1: Harnais et garde-fous

### Task 1: Pure safety and evidence primitives

**Files:**
- Create: `services/rag-engine/scripts/atomic_docker_v2_rehearsal_fixture.py`
- Create: `services/rag-engine/scripts/atomic_docker_v2_rehearsal.py`
- Create: `services/rag-engine/tests/test_atomic_docker_v2_rehearsal.py`

- [ ] **Step 1: Write failing tests** for accepted/rejected project names,
  exact snapshot changes, canonical JSON and transcript secret/path redaction.
- [ ] **Step 2: Run** `python3 -m pytest services/rag-engine/tests/test_atomic_docker_v2_rehearsal.py -q` and verify failure because the module does not exist.
- [ ] **Step 3: Implement the minimum pure helpers** with no Docker mutation.
- [ ] **Step 4: Run the focused tests** and verify they pass.
- [ ] **Step 5: Commit** with `rag-engine: add Docker V2 rehearsal safety primitives`.

### Task 2: Contract-valid ephemeral V2 bundle

**Files:**
- Modify: `services/rag-engine/scripts/atomic_docker_v2_rehearsal_fixture.py`
- Modify: `services/rag-engine/scripts/atomic_docker_v2_rehearsal.py`
- Modify: `services/rag-engine/tests/test_atomic_docker_v2_rehearsal.py`

- [ ] **Step 1: Write failing tests** proving both seeds are explicit required
  arguments, two fresh builds have distinct public-anchor digests, no private
  seed is serialized, the AuthorizationSet parses as V1, the readiness parses as
  V2, three application images are exact, binds are read-only and no port is
  declared.
- [ ] **Step 2: Run the focused tests** and confirm the expected missing fixture
  builder failure.
- [ ] **Step 3: Implement minimum fixture creation** in the dedicated module,
  calling the canonical signer/material verifier and atomic bundle materializer;
  never import a fixture or key from `tests/`.
- [ ] **Step 4: Run focused tests** and the existing deployment/signer tests.
- [ ] **Step 5: Commit** with `rag-engine: build ephemeral V2 rehearsal bundle`.

### Task 3: Real Docker scenarios and cleanup

**Files:**
- Modify: `services/rag-engine/scripts/atomic_docker_v2_rehearsal.py`
- Modify: `services/rag-engine/tests/test_atomic_docker_v2_rehearsal.py`

- [ ] **Step 1: Write failing orchestration tests** with injected process
  boundaries for valid up, three pre-mutation refusals, foreign collision,
  unchanged witness, explicit rollback and cleanup.
- [ ] **Step 2: Run focused tests** and verify they fail for missing orchestration.
- [ ] **Step 3: Implement the minimum orchestration**. Invoke every negative case
  with `execute=True`; make bad readiness a correctly signed V2 document with a
  wrong Compose digest; record mutation-boundary calls, daemon event changes and
  generated container/network/volume inventories. Add
  `FOREIGN_COLLISION_REFUSED` to the mandatory global verdict and use only exact
  generated project names.
- [ ] **Step 4: Run focused and existing wrapper suites** until green.
- [ ] **Step 5: Commit** with `rag-engine: exercise atomic Docker V2 scenarios`.

## Chunk 2: Preuve réelle et intégration

### Task 4: Run and version evidence

**Files:**
- Create: `docs/reports/evidence/atomic_docker_v2_rehearsal_20260825.json`
- Create: `docs/reports/evidence/atomic_docker_v2_rehearsal_20260825.transcript.txt`
- Create: `docs/reports/evidence/atomic_docker_v2_rehearsal_20260825.sha256`
- Create: `docs/reports/lot_atomic_docker_v2_rehearsal_20260825.md`
- Modify: `scripts/ci-local.sh`
- Modify: `scripts/tests/test-go-live-evidence-refresh.py`

- [ ] **Step 1: Write failing repository-control tests** for the eight exact
  verdicts, canonical JSON, transcript sanitation, SHA inventory and CI wiring.
  Require commit/tree, harness SHA-256, bundle digest, pinned image reference and
  local ID, Docker/Compose versions, transcript digest, and per-scenario
  exit/error/mutation/event facts. Confirm the historical V1 evidence is
  byte-identical to baseline.
- [ ] **Step 2: Run them and verify RED** because evidence is absent.
- [ ] **Step 3: Run the real harness** once against Docker; never pull/build an
  image unless the exact pinned Alpine digest is already local.
- [ ] **Step 4: Version the generated evidence and concise report**, then wire
  the guard test into local CI.
- [ ] **Step 5: Run targeted tests, Ruff, mypy, governance locks, repository
  controls and differential secret scanning.** Exercise cleanup-failure tests and
  require no generated container, network or volume residue.
- [ ] **Step 6: Commit** with `ops: attest atomic Docker V2 rehearsal`.

### Task 5: Reviews and PR

- [ ] **Step 1: Run fresh full verification** and preserve exact outputs.
- [ ] **Step 2: Request two fresh contradictory reviews** against the exact
  branch head; fix every P0-P3 and re-run verification.
- [ ] **Step 3: Push the isolated branch and create one technical PR** with no
  production mutation or secret.
- [ ] **Step 4: Report exact branch, commit/tree SHA, PR URL, evidence digests and
  any external gate without overstating repository-wide readiness.
