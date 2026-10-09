# Delegated Student Public Rights Adjudication v1 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development for independent components and superpowers:test-driven-development for behavior. The user supplied and approved the specification in the 2026-10-09 authority instruction; no intermediate human confirmation is requested.

**Goal:** Decide the 315 historical V4/V5 PDF identities individually, with full-document dual automated review, fail-closed rules, reproducible evidence, and one final exact-HEAD authority gate.

**Architecture:** The source packet remains an immutable historical inventory. A versioned policy and delegation mandate define restricted student-excerpt use. The scanner produces per-artifact CAS evidence from exact PDF bytes, every page, sources, and two independent review contexts. A deterministic engine emits one disposition per SHA. An independent verifier re-reads the inventory, policy, evidence, generated TSV, and counts; no existing internal rights authority is relabeled as student approval.

**Tech Stack:** Python 3.11+, PyMuPDF, Poppler/Tesseract, PyYAML/jsonschema, local vision model adapter with fixed identities/prompts, pytest/ruff, GitHub exact-HEAD trusted review.

---

## Phase 1: Authority and interfaces

### Task 1: Preserve the packet and define the policy

**Files:** `docs/adr/ADR-0068-delegation-agentique-droits-etudiants.md`; `governance/student_public_rights/delegated_review_policy_v1.yml`; `governance/student_public_rights/delegation_abenrhouma_20261009.yml`; `governance/student_public_rights/schemas/automated_artifact_review_v1.schema.json`.

- [ ] Write the ADR separating delegating authority, automated executor, final exact-HEAD approval, and prior internal zone rights.
- [ ] Define positive rights bases, use restrictions, fail-closed rules, CFTR override, evidence and reviewer identities. Ban generic `official`/`officiel_public` approval.
- [ ] Bind the mandate to the immutable source main commit/tree, 315-SHA inventory digest, policy/schema/code blob digests, both reviewer model identities/versions and specialized prompt digests, `automated_full_document_dual_review`, UTC validity, and explicit prohibitions. Record final PR HEAD externally in the approval challenge to avoid a self-referential commit.
- [ ] Define a strict per-artifact schema for every field in the authority instruction: page-level text/render/OCR and attachment status, signatures/faces/metadata check, source HTTP/identity proof, exact rights-basis enum and excerpt hash/page/URI, independent A/B outputs, PII/currentness/revocation states, rule outcomes, executor/delegation IDs, and final disposition/reason codes. No raw PII or chain of thought.
- [ ] Validate policy/mandate/schema loading and reject missing/mismatched digests in tests.

### Task 2: Tests for deterministic adjudication

**Files:** `scripts/tests/test_adjudicate_student_public_rights.py`; `scripts/go_live/adjudicate_student_public_rights.py`.

- [ ] Write red tests for all required `APPROVE_PUBLIC` predicates, each missing predicate causing `EXCLUDE`, CFTR forced exclusion, no `PENDING`, and no legacy `officiel_public` shortcut.
- [ ] Implement the minimal pure decision function and run targeted tests green.
- [ ] Add red/green tests for `REPLACE_WITH_NEW_CONTENT` only with a separately identified, fully qualified substitute; otherwise `EXCLUDE`.

## Phase 2: Exhaustive evidence acquisition

### Task 3: Exact-byte and full-page scanner

**Files:** scanner module under `scripts/go_live/`; scanner tests under `scripts/tests/`.

- [ ] Write red tests for SHA/size/page mismatches, encrypted/attachment-bearing PDFs, text/raster/metadata coverage, page and render hashes, interrupted/resumed artifact checkpoints, and absence of raw PII in output.
- [ ] Implement bounded-memory scanning of all pages, render every page with graphical content, OCR non-text/graphics, record page-level hashes and completeness. Stop on mismatch; do not rewrite source PDFs.
- [ ] Verify representative text-only, image-bearing, annex, and CFTR fixtures before the 315-document run.

### Task 4: Contemporary source and rights evidence

**Files:** source verifier module and tests under `scripts/go_live/` and `scripts/tests/`.

- [ ] Write red tests for thematic listing URL, 403, redirects, wrong PDF bytes, missing terms, revoked source, third-party exception, and exact PDF URL + matching bytes + applicable rights notice.
- [ ] Implement read-only HTTP collection of final URL/status/ETag/Last-Modified/UTC and immutable evidence hashes. A thematic listing URL is not the PDF; link any accepted license and update date to the exact downloaded PDF identity and every third-party element, not merely its host. Missing link or terms means `EXCLUDE`.
- [ ] Snapshot official Éduscol terms and Etalab 2.0 with source URLs and digests; require attribution source and update date for public excerpts.

### Task 5: Independent automated reviews

**Files:** specialized prompt files and model adapter under `governance/student_public_rights/` and `scripts/go_live/`; tests under `scripts/tests/`.

- [ ] Write red tests proving A and B have separate requests/contexts, fixed model/prompt digests/temperature, structured outputs, complete page accounting, and fail-closed handling of timeout, parse failure, disagreement, low confidence, or image omission.
- [ ] Implement reviewer A for rights/third-party/currentness/revocation and reviewer B for student suitability/PII/teacher-only/annexes. Model text is observation only; the pure engine decides.
- [ ] Re-run every candidate approval through both reviews; any divergence becomes `EXCLUDE`.

## Phase 3: Independent proof and full population

### Task 6: Output builder and independent verifier

**Files:** `scripts/go_live/check_delegated_student_rights_gate.py`; verifier tests under `scripts/tests/`; generated TSV and report under `docs/reports/go_live/`.

- [ ] Write red tests for all ten specified sabotage cases, exact 315-SHA equality, zero pending, CFTR exclusion, evidence-pack digest, generated TSV hash, final counts, reviewer identity/completeness, and final HEAD/delegation binding.
- [ ] Implement verifier independently of the adjudicator; replay deterministic predicates from evidence and regenerate TSV bytes for comparison.
- [ ] Generate machine JSON and French Markdown summary from verified evidence only.
- [ ] Derive final artifact/placement/chunk counts by filtering manifests by the approved SHA set; never subtract a presumed fixed amount from historical counts.

### Task 6b: Enforce the pack at public release construction

**Files:** `services/rag-pedago/scripts/build_multilevel_release.py` and focused tests; the final public release/readiness validator.

- [ ] Write a failing bypass test: a `public/student` successor cannot be built from the old zone-level `human_rights_decisions` registry alone or include an `EXCLUDE` SHA.
- [ ] Require a verified delegated pack and exact approved SHA set before emitting public student subjects; keep internal/rehearsal behavior unchanged.
- [ ] Recheck this binding in readiness; until integration is green, explicitly mark successor publication blocked.

### Task 7: Run on all 315 PDFs

- [ ] Create a clean non-editable venv for this worktree and record tool/model versions, prompts, policy/schema/code/inventory digests.
- [ ] Run scanner and two reviews over all 315 exact SHA PDFs with per-artifact checkpoints; rerun failed/partial artifacts until every record is complete or safely `EXCLUDE` with complete scan/review evidence.
- [ ] Run source checks and the independent verifier; confirm 315 decisions, zero pending, 315 scans, 315 dual reviews, CFTR `EXCLUDE`; report actual approval/exclusion/replacement and release counts without preserving historical counts artificially.
- [ ] Run targeted tests, sabotage suite, contracts/CI local checks, independent code review, and GitHub CI. Keep #300 draft until fully green.

### Task 8: Final authority gate

- [ ] Bind final base/head/tree, inventory, policy, mandate, sheet, evidence-pack digest, counts, and engine identity in a business challenge alongside the existing `NEXUS-TRUSTED-REVIEW-V1` challenge; ensure zero open blocking threads. Both lines must be checked independently against the same exact base/head/tree.
- [ ] Present one GitHub APPROVED review to `abenrhouma` carrying both exact challenges and explicitly stating that it does not attest individual human PDF reading. Never put `abenrhouma` in `human_reviewer` for generated per-file rows.
- [ ] After valid review, trigger `trusted-human-review/head-pinned`, merge #300 per repository convention, then build public successor releases from the approved SHA set. No staging or production mutation in this lot.
