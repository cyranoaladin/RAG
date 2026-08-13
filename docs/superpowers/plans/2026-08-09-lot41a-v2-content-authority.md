# LOT41A-V2 Content-Bound Authority Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter LOT41A-V2, qui lie une autorisation GitHub canonique à une allowlist positive de SHA-256 et refuse tout contenu H2 non listé avant stockage ou extraction.

**Architecture:** Préserver le modèle public V1 et ajouter un modèle V2 strict, projeté par la migration ingestion-control 009 et relu octet à octet depuis GitHub. Le worker revérifie l'autorité après téléchargement, contrôle le SHA avant toute transition ou persistance, puis LOT42 et le compilateur H2 exigent explicitement cette autorité V2. PR #96 reste gelée ; seules des autorités V2 de test/staging sont utilisées.

**Tech Stack:** Python 3.12, Pydantic 2, psycopg 3, PostgreSQL 16, pytest, ruff, mypy, Bash, Docker/pgvector.

---

## Chunk 1: Contrat et projection d'autorité

### Task 1: Contrat canonique LOT41A-V2 et SemVer

**Files:**
- Modify: `packages/contracts/src/nexus_contracts/authority_artifacts.py`
- Modify: `packages/contracts/src/nexus_contracts/__init__.py`
- Modify: `packages/contracts/pyproject.toml`
- Modify: `packages/contracts/tests/test_schema_export.py`
- Modify: `services/rag-engine/tests/test_lot41a_authority_artifacts.py`
- Existing ADR: `docs/adr/ADR-0034-lot41a-v2-autorite-liee-contenu.md`

- [x] **Step 1: Write failing V2 contract tests**

Add tests constructing `ScopeAuthorizationArtifactV2` with a sorted non-empty
`allowed_content_sha256`, parsing its canonical bytes, and rejecting missing,
empty, duplicate, unsorted, uppercase and malformed values. Add explicit tests
that V1 rejects the V2 field, an unknown protocol fails closed, and one changed
SHA changes canonical bytes and digest.

- [x] **Step 2: Verify RED**

Run:
`services/rag-engine/.venv/bin/python -m pytest -q services/rag-engine/tests/test_lot41a_authority_artifacts.py`

Expected: collection fails because `ScopeAuthorizationArtifactV2` and V2
dispatch do not exist.

- [x] **Step 3: Implement the minimal discriminated contract**

Keep `ScopeAuthorizationArtifact` byte-compatible as V1, export
`ScopeAuthorizationArtifactV1` as its alias, add strict
`ScopeAuthorizationArtifactV2`, and define the closed annotation
`ScopeAuthorizationArtifactAny`. Dispatch `parse_scope_authorization_artifact`
on the exact `protocol_version`; never normalize a submitted list.

- [x] **Step 4: Bump shared SemVer and repair its assertion**

Set `packages/contracts/pyproject.toml` to `0.7.0` and update the obsolete
package-version assertion while keeping the schema namespace constant described
by ADR-0026.

- [x] **Step 5: Verify GREEN and quality**

Run:
`services/rag-engine/.venv/bin/python -m pytest -q services/rag-engine/tests/test_lot41a_authority_artifacts.py packages/contracts/tests/test_schema_export.py`

Run:
`services/rag-engine/.venv/bin/python -m ruff check packages/contracts/src/nexus_contracts/authority_artifacts.py services/rag-engine/tests/test_lot41a_authority_artifacts.py`

- [x] **Step 6: Commit**

`git commit -m "contracts: ajoute le protocole LOT41A-V2"`

### Task 2: Migration ingestion-control 009

**Files:**
- Create: `services/rag-engine/infra/postgres/ingestion_control/migrations/009_scope_authorization_content_allowlist.sql`
- Create: `services/rag-engine/infra/postgres/ingestion_control/rollbacks/009_scope_authorization_content_allowlist.down.sql`
- Modify: `services/rag-engine/infra/postgres/ingestion_control/migrations/HEAD`
- Create: `services/rag-engine/tests/test_lot41a_v2_migration_contract.py`
- Modify: `services/rag-engine/tests/integration/test_lot44f_migration_upgrade_paths.py`
- Modify: `services/rag-engine/tests/integration/test_lot44f_migration_rollback_rehearsal.py`

- [x] **Step 1: Write failing migration contract tests**

Require the new files, HEAD 009, nullable `TEXT[]`, protocol CHECK V1/V2, an
IMMUTABLE array validator, the cross-version constraint, and a rollback guard
`ROLLBACK_009_V2_DATA_PRESENT`.

In the same RED phase, add disposable-PostgreSQL tests that require valid V1
compatibility and valid V2, then reject V2 NULL/empty/malformed/uppercase/
duplicate/unsorted/noncanonical-array and V1 populated list. Add apply →
rollback → reapply plus rollback refusal with a V2 row.

- [x] **Step 2: Verify RED**

Run:
`services/rag-engine/.venv/bin/python -m pytest -q services/rag-engine/tests/test_lot41a_v2_migration_contract.py`

Run:
`cd services/rag-engine && .venv/bin/python -m pytest -q -m integration tests/integration/test_lot44f_migration_upgrade_paths.py -k ScopeAuthorizationContentAllowlist`

Expected: missing migration/rollback and absent column/constraints.

- [x] **Step 3: Implement migration and fail-closed rollback**

Add `allowed_content_sha256 TEXT[]`. The helper must return false for NULL,
non-1D arrays, lower bound not 1, empty arrays, NULL members, values outside
`^[0-9a-f]{64}$`, duplicates or order differing from bytewise `COLLATE "C"`.
Require V1+NULL and V2+valid-list. Rollback must lock the table, refuse any V2
row, restore the V1-only protocol CHECK, then drop the column/helper.

- [x] **Step 4: Verify GREEN**

Run:
`cd services/rag-engine && .venv/bin/python -m pytest -q tests/test_lot41a_v2_migration_contract.py`

Run:
`cd services/rag-engine && .venv/bin/python -m pytest -q -m integration tests/integration/test_lot44f_migration_upgrade_paths.py -k ScopeAuthorizationContentAllowlist`

Run:
`cd services/rag-engine && .venv/bin/python -m pytest -q -m integration tests/integration/test_lot44f_migration_rollback_rehearsal.py`

- [x] **Step 5: Commit**

`git commit -m "rag-engine: ajoute la migration d'autorité LOT41A-V2"`

### Task 3: Stockage, readback et tamper detection V2

**Files:**
- Modify: `services/rag-engine/src/ingestor/ingestion_control/scope_authority.py`
- Modify: `services/rag-engine/src/ingestor/ingestion_worker/authorize_scope_cli.py`
- Modify: `services/rag-engine/tests/_authorization_stub.py`
- Modify: `services/rag-engine/tests/integration/test_lot41a_scope_authority.py`
- Modify: `services/rag-engine/tests/integration/test_lot41a_operator_role_isolation.py`

- [x] **Step 1: Write failing readback and tampering tests**

Record a canonical V2 blob without any content CLI option. Require
`VerifiedAuthorization.protocol_version == "LOT41A-V2"` and the exact tuple.
Then mutate the DB by append/remove/replace/reorder, change V2 to V1, change
only digest and only blob SHA; each live verification must fail for its direct
field mismatch.

- [x] **Step 2: Verify RED**

Run the targeted integration tests; expect missing column/fields or mismatches
not detected.

Exact command:
`cd services/rag-engine && .venv/bin/python -m pytest -q -m integration tests/integration/test_lot41a_scope_authority.py tests/integration/test_lot41a_operator_role_isolation.py`

- [x] **Step 3: Implement exact storage and readback**

Extend `_AUTHORIZATION_COLUMNS`, row/artifact comparison, record SQL,
`VerifiedAuthorization` and test stubs. V1 maps to NULL, V2 to the exact list.
The operator CLI remains identity/PR/head-only. No compiler CLI accepts an
authority artifact, projection, or SHA list.

- [x] **Step 4: Verify GREEN and role isolation**

Run:
`cd services/rag-engine && .venv/bin/python -m pytest -q -m integration tests/integration/test_lot41a_scope_authority.py tests/integration/test_lot41a_operator_role_isolation.py`

- [x] **Step 5: Commit**

`git commit -m "rag-engine: vérifie l'allowlist LOT41A-V2 en lecture live"`

## Chunk 2: Enforcement, H2 et LOT42

### Task 4: Checkpoint contenu avant stockage/extraction

**Files:**
- Modify: `services/rag-engine/src/ingestor/ingestion_control/scope_enforcement.py`
- Modify: `services/rag-engine/src/ingestor/ingestion_agents/fetcher.py`
- Modify: `services/rag-engine/src/ingestor/ingestion_worker/runner.py`
- Modify: `services/rag-engine/tests/test_lot41a_scope_enforcement.py`
- Modify: `services/rag-engine/tests/integration/test_lot41a_worker_enforcement.py`
- Modify: `services/rag-engine/tests/test_lot44d_fetcher.py`

- [x] **Step 1: Write the pure guard RED tests**

Require V2 listed SHA to pass, V2 unlisted SHA to raise checkpoint `content`,
and V1 to retain its historical guard behavior. Add a separate
`require_h2_content_bound_authority` test that rejects V1 with
`CONTENT_ALLOWLIST_AUTHORITY_REQUIRED`.

- [x] **Step 2: Write the exact P1 worker RED test**

Return same-domain bytes not in the V2 list. Assert destination passed,
checkpoint is `content`, fetch occurred once, artifact store/extractor/rights/
quality were not called, no artifact row exists and resource never reached
`FETCHED`. Also test allowed bytes, wrong bytes at an approved-looking URL,
allowed bytes behind an excluded destination, and revocation between fetch and
content check.

- [x] **Step 3: Verify RED**

Run the pure guard and targeted worker tests. Expected: unlisted content
currently succeeds and reaches storage.

Exact command:
`cd services/rag-engine && .venv/bin/python -m pytest -q tests/test_lot41a_scope_enforcement.py tests/test_lot44d_fetcher.py tests/integration/test_lot41a_worker_enforcement.py`

- [x] **Step 4: Implement minimal ordered enforcement**

Add `enforce_content_sha256`. Give `run_fetcher` an injected post-hash,
pre-transition callback returning sanitized authorization-binding metadata.
Runner callback live-reverifies the named authority, performs membership, and
returns protocol/id/digest for the `FETCHED` event. Do not log or persist raw
bytes on denial.

- [x] **Step 5: Verify GREEN**

Run:
`cd services/rag-engine && .venv/bin/python -m pytest -q tests/test_lot41a_scope_enforcement.py tests/test_lot44d_fetcher.py tests/integration/test_lot41a_worker_enforcement.py`

Run:
`cd services/rag-engine && .venv/bin/python -m ruff check src/ingestor/ingestion_control/scope_enforcement.py src/ingestor/ingestion_agents/fetcher.py src/ingestor/ingestion_worker/runner.py tests/test_lot41a_scope_enforcement.py tests/test_lot44d_fetcher.py tests/integration/test_lot41a_worker_enforcement.py && .venv/bin/python -m mypy src/ingestor/ingestion_control/scope_enforcement.py src/ingestor/ingestion_agents/fetcher.py src/ingestor/ingestion_worker/runner.py`

- [x] **Step 6: Commit**

`git commit -m "rag-engine: bloque le contenu hors allowlist avant stockage"`

### Task 5: Compilateur H2 et LOT42 content-bound

**Files:**
- Modify: `services/rag-pedago/rag_pedago/imports/corpus_catalog_compiler.py`
- Modify: `services/rag-pedago/tests/test_corpus_catalog_compiler.py`
- Modify: `services/rag-engine/src/ingestor/h2c_placement_readiness.py`
- Modify: `services/rag-engine/src/ingestor/ingestion_control/publication_evidence.py`
- Modify: `services/rag-engine/src/ingestor/ingestion_control/publication_attestation.py`
- Modify: `services/rag-engine/src/ingestor/ingestion_control/governed_publication_path.py`
- Modify: `services/rag-engine/src/ingestor/governed_publisher_v2.py`
- Modify: `services/rag-engine/tests/test_h2c_placement_readiness.py`
- Modify: `services/rag-engine/tests/integration/test_lot42_publication_attestation.py`
- Modify: `services/rag-engine/tests/integration/test_h2c_governed_rehearsal.py`

- [x] **Step 1: Write compiler policy RED tests**

Remove the raw `authority_cleared_sha256` input from the `rag-pedago` compiler.
Prove it always leaves real candidates `REVIEW_REQUIRED` on the authority gate
and that its public CLI exposes no authority artifact, projection or SHA-list
input. In `rag-engine`, write the finalizer RED tests against the in-process
`VerifiedAuthorization`: verified V2 listed SHA passes, same-scope unlisted SHA
is blocked, V1 returns `CONTENT_ALLOWLIST_AUTHORITY_REQUIRED`, and absent
authority leaves every candidate blocked.

- [x] **Step 2: Write LOT42 RED tests**

Require H2 promotion/publisher to validate the durable `FETCHED` content event,
including authorization protocol/id/digest and SHA. V1, missing event, unlisted
SHA, caller-supplied mismatch, or tampered event must prevent
`RETRIEVAL_ELIGIBLE` and product writes.

- [x] **Step 3: Verify RED**

Run the targeted compiler and LOT42 tests; expect V1/broad authority to be
accepted today.

Exact commands:
`cd services/rag-pedago && .venv/bin/python -m pytest -q tests/test_corpus_catalog_compiler.py`

`cd services/rag-engine && .venv/bin/python -m pytest -q tests/test_h2c_placement_readiness.py tests/integration/test_lot42_publication_attestation.py tests/integration/test_h2c_governed_rehearsal.py tests/test_lot42_retrieval_eligible_anchor.py`

- [x] **Step 4: Implement H2 and durable-event binding**

Make the real `rag-pedago` compiler candidate-only by deleting its raw authority
set input. Add the authority finalization to `rag-engine` placement readiness,
where it consumes the in-process `VerifiedAuthorization` returned by live
Git/DB readback; V1/None yields no clearance and no authority crosses the
service boundary. Extend `PublicationFacts` with the content event and binding;
include its ID in canonical evidence events. Add an opt-in
`require_content_bound_authority` parameter to general LOT42 verification and
require it unconditionally from the dormant H2 path and governed publisher.

- [x] **Step 5: Verify GREEN**

Run:
`cd services/rag-pedago && .venv/bin/python -m pytest -q tests/test_corpus_catalog_compiler.py`

Run:
`cd services/rag-engine && .venv/bin/python -m pytest -q tests/test_h2c_placement_readiness.py tests/test_governed_publisher_v2.py tests/integration/test_lot42_publication_attestation.py tests/integration/test_h2c_governed_rehearsal.py tests/test_lot42_retrieval_eligible_anchor.py`

- [x] **Step 6: Commit**

`git commit -m "rag-engine: lie LOT42 et le compilateur H2 au contenu V2"`

### Task 6: V2 rehearsals and mutation 13

**Files:**
- Create: `scripts/h2e_materialize_rehearsal_inputs.py`
- Create: `services/rag-pedago/tests/test_h2e_materialize_rehearsal_inputs.py`
- Modify: `services/rag-engine/tests/integration/test_h2c_governed_rehearsal.py`
- Modify: `services/rag-engine/scripts/h2c_governed_rehearsal.py`
- Modify: `services/rag-pedago/scripts/h2b_true_mutation_harness.py`
- Modify: `services/rag-engine/tests/test_lot41a_scope_enforcement.py`
- Modify: `services/rag-pedago/tests/test_h2b_true_mutation_harness.py` if present

- [x] **Step 1: Add staging V2 positive and negative rehearsals**

Use a V2 fixture listing the real sealed SHA for the positive path. Add a
same-domain unlisted-byte path and assert no extraction, rights, quality,
eligibility or pgvector row.

Add a tested read-only materializer which accepts a caller-created bounded
`/tmp` directory, downloads only `00_ADMIN/SHA256SUMS.txt`,
`00_INDEX_PROVENANCE/EDUSCOL_CATALOGUES/catalogue-complet.tsv`, and the selected
real PDF with `rclone copyto` from the canonical remote, recompiles the governed
catalog from versioned routing/rights inputs, and verifies the manifest, PII
evidence and PDF SHA before emitting paths. It must expose no remote-write verb.

First add RED tests with a fake `rclone` executable. Require exactly three
remote-to-local `copyto` calls, canonical remote paths, a JSON output manifest
with top-level `pdf_path`, `pdf_sha256`, `catalog_path`, `catalog_sha256`,
`pii_evidence_path`, `pii_evidence_sha256`, `manifest_sha256` and
`remote_write_operations`, and rejection of manifest/PII/PDF drift. Assert that
`sync`, `delete`, `move`, `copy` and every local-to-remote command are absent.
Run and observe RED:
`cd services/rag-pedago && .venv/bin/python -m pytest -q tests/test_h2e_materialize_rehearsal_inputs.py`.

- [x] **Step 2: Add MUT-H2B-13 test-first**

Add the target test whose message appears only if
`if content_sha256 not in authorization.allowed_content_sha256` is neutralized.
Then add Check 13 to the harness with one exact textual mutation anchor.

- [x] **Step 3: Verify mutation RED/GREEN/restore**

Run `--only 13`; require baseline green, mutant red for the exact message,
restored SHA match and restored green.

Exact command:
`services/rag-pedago/.venv/bin/python services/rag-pedago/scripts/h2b_true_mutation_harness.py --only 13 --report /tmp/h2b_mutation_13.json`

- [x] **Step 4: Run full 13-mutation matrix**

Write non-sensitive evidence outside Git and require `13/13` plus byte-perfect
restoration.

Exact command:
`services/rag-pedago/.venv/bin/python services/rag-pedago/scripts/h2b_true_mutation_harness.py --report "$HOME/Documents/NEXUS_RAG_H2_EVIDENCE/h2b_true_mutations_h2e.json"`

Run the isolated V2 rehearsal with:
create `nexus_h2e_scratch="$(mktemp -d /tmp/nexus-h2e.XXXXXX)"` and install:

```bash
cleanup_nexus_h2e() {
  case "${nexus_h2e_scratch:-}" in
    /tmp/nexus-h2e.*) rm -rf -- "$nexus_h2e_scratch" ;;
    *) return 1 ;;
  esac
}
trap cleanup_nexus_h2e EXIT
```

Then run:

`services/rag-pedago/.venv/bin/python scripts/h2e_materialize_rehearsal_inputs.py --scratch-dir "$nexus_h2e_scratch" --pii-evidence "$HOME/Documents/NEXUS_RAG_H2_EVIDENCE/h2b_pii_evidence_20260808.json" --output-manifest "$nexus_h2e_scratch/inputs.json"`

Read the three paths with:

```bash
nexus_h2e_pdf="$(jq -er .pdf_path "$nexus_h2e_scratch/inputs.json")"
nexus_h2e_catalog="$(jq -er .catalog_path "$nexus_h2e_scratch/inputs.json")"
nexus_h2e_pii="$(jq -er .pii_evidence_path "$nexus_h2e_scratch/inputs.json")"
```

Recompute each path's SHA-256 and compare it with its adjacent `*_sha256`
field; require `remote_write_operations=0` and the sealed manifest digest. Then
run:

`services/rag-engine/.venv/bin/python services/rag-engine/scripts/h2c_governed_rehearsal.py --pdf "$nexus_h2e_pdf" --catalog "$nexus_h2e_catalog" --pii-evidence "$nexus_h2e_pii" --output "$HOME/Documents/NEXUS_RAG_H2_EVIDENCE/h2e_v2_governed_rehearsal.json"`

Finally run the materializer unit test GREEN and let the validated trap remove
only the new scratch directory.

- [x] **Step 5: Commit**

`git commit -m "test(governance): étend les mutations H2 à l'allowlist contenu"`

## Chunk 3: Exact-head closure

### Task 7: Revalidate the complete H2 technical gate

**Files:**
- Modify: `docs/reports/lot_h2b_production_readiness.md`
- Modify: PR #95 body only after evidence is final

- [x] **Step 1: Finalize and commit the evidence report after the final gates**

La correction de trajectoire H2 du 10 août 2026 remplace l'ordre initial :
exécuter les gates sur la tête d'implémentation figée, puis mettre à jour et
committer ce plan et le rapport avec les vrais digests externes. Le commit
documentaire ne modifie aucun octet d'implémentation vérifié.

- [x] **Step 2: Re-run disposable migrations**

Run product migration 004 apply/rollback/reapply:
`cd services/rag-engine && bash infra/scripts/test_hybrid_integration.sh`

The harness must emit the 004 apply, rollback, data-guard and reapply markers;
the targeted pytest suite alone is not accepted as rollback evidence.

Run ingestion-control 009 apply/schema/V1/V2/rollback/reapply:
`cd services/rag-engine && .venv/bin/python -m pytest -q tests/test_lot41a_v2_migration_contract.py`

Then:
`cd services/rag-engine && .venv/bin/python -m pytest -q -m integration tests/integration/test_lot44f_migration_upgrade_paths.py tests/integration/test_lot44f_migration_rollback_rehearsal.py`

No production DSN may be present.

- [x] **Step 3: Re-run real multi-placement and V2 governed rehearsals**

Use the sealed real PDF/catalog evidence outside Git. Record artifact=1,
placement count, chunk set=1, duplicate vectors/chunks/results=0, positive V2
retrieval and negative same-domain denial.

Repeat the exact Task 6 materializer and rehearsal commands with a new bounded
`mktemp -d` directory and a cleanup trap restricted by a
`/tmp/nexus-h2e.*` case check. Never reuse a path from a prior run.

- [x] **Step 4: Run canonical local CI on exact HEAD**

Use Python 3.12 and Node 22.22 without changing CI semantics:
`bash scripts/ci-local.sh` after selecting the host's Python 3.12 and Node
22.22 installations through the normal version managers.

- [x] **Step 5: Run final security scans**

Run:
`gitleaks detect --source . --log-opts="$(git rev-parse origin/main)..$(git rev-parse HEAD)" --redact --no-banner`

Run:
`test -z "$(git diff --name-only origin/main..HEAD | rg -i '\\.pdf$')"`

Run:
`test -z "$(git diff --name-only origin/main..HEAD | rg -i '(^|/)(\\.env($|\\.)|credentials?|secrets?|id_rsa|id_ed25519)')"`

Run the PII sanitization/output tests:
`cd services/rag-pedago && .venv/bin/python -m pytest -q tests/test_pii_scanner.py tests/test_remote_pii_scan.py`

- [ ] **Step 6: Push the already-verified exact head normally**

Push without force, then wait for all technical GitHub checks on that exact
SHA. Record final results in the external evidence package and PR body; do not
change a versioned report after the final-head run.

### Task 8: Independent audit and PR #95 human boundary

**Files:**
- Modify: `docs/reports/lot_h2b_production_readiness.md` only if audit findings require documentation
- Modify: PR #95 body through GitHub

- [ ] **Step 1: Freeze H2_FINAL_HEAD**

Confirm local=remote=PR95 head and a clean worktree. Any remediation creates a
new head and invalidates this step.

- [ ] **Step 2: Launch a fresh independent reviewer**

Audit the final repository/evidence against the ten V2 questions in the H2-E
mandate, migration rollback, roles, multi-placement, mutation restoration, CI
and security. The reviewer must not rely on the implementation report.

- [ ] **Step 3: Remediate and repeat if needed**

For each blocking finding: write a failing regression test, implement the
minimal fix, rerun all head-bound gates, and re-audit a new frozen HEAD.

- [ ] **Step 4: Finalize PR #95**

With audit PASS and zero blockers, update the body from exact evidence, mark it
ready, request `abenrhouma`, and derive the canonical trusted-review challenge
for PR #95 only. Do not approve, merge, touch PR #96 authority bytes, or start
production.
