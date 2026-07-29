# PR 76 Merge Resolution Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebase the CI baseline lot onto current `main` without regressing the public Next.js/BFF cockpit.

**Architecture:** Merge `origin/main` into the published lot branch. Resolve runtime conflicts in favour of the canonical BFF implementation and retain CI/catalogue protections only where their tests prove compatibility.

**Tech Stack:** Git, Bash, GitHub Actions, Next.js, TypeScript, Vitest, Python.

---

## Chunk 1: merge and conflict boundaries

### Task 1: Establish the conflicting baseline

**Files:**
- Modify: merge index for `services/cockpit/**`, `.github/workflows/ci.yml`, and `scripts/**`
- Test: `scripts/tests/test-ci-local-failsafe.sh`

- [ ] **Step 1: Create the merge state**

Run: `git merge --no-commit origin/main`
Expected: conflict list is limited to the reported cockpit overlap.

- [ ] **Step 2: Verify the CI regression test before resolving**

Run: `bash scripts/tests/test-ci-local-failsafe.sh`
Expected: failure or non-executable state demonstrates that the unresolved merge cannot be shipped.

- [ ] **Step 3: Resolve CI and runtime boundaries**

Keep the BFF files and APIs from `main`; retain only compatible lot-34 CI and snapshot files.

- [ ] **Step 4: Verify the resolved CI guard**

Run: `bash scripts/tests/test-ci-local-failsafe.sh`
Expected: all assertions pass.

## Chunk 2: cockpit compatibility

### Task 2: Reconcile dependencies, search and snapshots

**Files:**
- Modify: `services/cockpit/package.json`, `services/cockpit/package-lock.json`
- Modify: `services/cockpit/src/sections/SearchSection.tsx`
- Test: `services/cockpit/src/sections/SearchSection.test.tsx`

- [ ] **Step 1: Preserve the BFF public-search test contract**

Run: `npm --prefix services/cockpit test -- --run src/sections/SearchSection.test.tsx`
Expected: the conflict must not replace source-backed search with the deleted direct API client.

- [ ] **Step 2: Resolve dependencies from the canonical package manifest**

Regenerate the lockfile only if required by the selected manifest.

- [ ] **Step 3: Run cockpit checks**

Run: `npm --prefix services/cockpit run contracts:check && npm --prefix services/cockpit run lint && npm --prefix services/cockpit test -- --run && npm --prefix services/cockpit run build`
Expected: all commands exit 0.

## Chunk 3: publication

### Task 3: Publish the resolved lot

**Files:**
- Modify: `docs/reports/lot_34_baseline_ci.md`

- [ ] **Step 1: Record the new integration evidence**

Document the merge parent, exact checks and any retained scope.

- [ ] **Step 2: Verify no unresolved files remain**

Run: `git diff --check && git diff --name-only --diff-filter=U`
Expected: exit 0 and no output for unmerged paths.

- [ ] **Step 3: Commit and push**

Run: `git commit -m "ci: réconcilie le lot 34 avec main" && git push origin lot-34-baseline-ci`
Expected: PR #76 becomes mergeable and CI is triggered.
