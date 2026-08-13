# Multi-Level Priority Ingestion Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest, reconcile and expose every safe release-eligible artifact for the ten approved collections.

**Architecture:** Extend the sealed Wave 0 release authority into a multi-collection aggregate. Select exact-grade first, require explicit evidence for reassignment, and create an append-only corpus delta only for proven official gaps. Reuse governed workers, real E5/reranker, exact readiness and signed V2 scopes.

**Tech Stack:** Python 3.11+, Pydantic, YAML/JSON, PostgreSQL/pgvector, pytest, ruff, mypy, uvicorn, local Hugging Face artifacts, LocalGitHub staging.

---

## Chunk 1: Inventory and contract

### Task 1: Deterministic ten-collection inventory

**Files:**
- Create: `services/rag-pedago/scripts/build_multilevel_release.py`
- Create: `services/rag-pedago/tests/test_build_multilevel_release.py`
- Create: `services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/candidate_inventory.json`
- Create: `docs/reports/lot_multilevel_ingestion_2026_2027.md`

- [ ] Add `test_target_matrix_is_exact_and_ordered`; run
  `cd services/rag-pedago && .venv/bin/pytest tests/test_build_multilevel_release.py::test_target_matrix_is_exact_and_ordered -q`; expect RED import error.
- [ ] Implement the ten-row matrix from the design; rerun and expect PASS.
- [ ] Add `test_inventory_deduplicates_artifacts_and_counts_placements`; run and expect RED missing builder behavior.
- [ ] Implement exact level/subject/official-PDF selection; rerun and expect PASS.
- [ ] Add `test_empty_or_no_eligible_collection_records_six_discovery_routes`
  and `test_candidate_partition_has_no_gap`; verify RED.
- [ ] Implement the six-route evidence record and exact partition; rerun all tests PASS.
- [ ] Generate the inventory twice; assert byte equality and record its SHA.

### Task 2: Quatrième contract and canonical collections

**Files:**
- Modify: `packages/contracts/src/nexus_contracts/document.py`
- Modify: `packages/contracts/pyproject.toml`
- Modify: `packages/contracts/tests/test_contracts.py`
- Modify: `packages/contracts/schema/retrieval-request.json`
- Modify: `packages/contracts/schema/chat-request.json`
- Modify: `packages/contracts/schema/internal-identity-envelope.json`
- Modify: `packages/contracts/schema/internal-identity.json`
- Modify: `packages/contracts/schema/pilot-retrieval-scope-artifact.json`
- Modify: `packages/contracts/schema/retrieval-scope-artifact-v2.json`
- Modify: `services/cockpit/src/generated/contracts.ts`
- Modify: `services/cockpit/src/generated/validators.ts`
- Modify: `services/cockpit/src/generated/schema/retrieval-request.json`
- Modify: `services/cockpit/src/generated/schema/chat-request.json`
- Modify: `services/cockpit/src/generated/schema/internal-identity-envelope.json`
- Modify: `services/cockpit/src/generated/schema/internal-identity.json`
- Modify: `services/cockpit/src/generated/schema/pilot-retrieval-scope-artifact.json`
- Modify: `services/cockpit/src/generated/schema/retrieval-scope-artifact-v2.json`
- Modify: `services/cockpit/src/types/ui.ts`
- Modify: `services/cockpit/src/sections/OverviewSection.tsx`
- Modify: `services/rag-engine/configs/rag_collections.yml`
- Modify: `services/rag-engine/src/ui/app_v2.py`
- Modify: `services/rag-engine/tests/test_rag_collections_config.py`
- Modify: `scripts/lib/validate_cockpit_snapshots.py`
- Create: `services/rag-pedago/taxonomy/maths/quatrieme.yml`
- Create: `services/rag-pedago/taxonomy/francais/quatrieme.yml`
- Create: `docs/adr/ADR-0040-extension-multi-niveaux-prioritaire.md`

- [ ] Add `test_niveau_quatrieme_is_contractual`; run
  `cd packages/contracts && .venv/bin/pytest tests/test_contracts.py::test_niveau_quatrieme_is_contractual -q`; expect RED enum error.
- [ ] Add `Niveau.quatrieme`, bump `0.10.0` to `0.11.0`; rerun PASS.
- [ ] Add RED config/taxonomy/index tests for two dormant collections and the
  exact applicable programme `BOEN_special_11_2018-07-26_aj_2020`.
- [ ] Add minimal collection entries and source-backed taxonomies; rerun PASS.
- [ ] Create/validate `corpus/College/Quatrieme/_index.yml` from the official
  cycle-4 authority before any Quatrième profile; a missing proof leaves both
  collections dormant rather than using a placeholder.
- [ ] Run `packages/contracts/.venv/bin/python packages/contracts/scripts/export_schemas.py`.
- [ ] Run `cd services/cockpit && npm run contracts:generate`.
- [ ] Run schema export, cockpit check and cross-service golden tests; expect PASS.

### Task 3: Seconde alignment, profiles and closed mappings

**Files:**
- Modify: `services/rag-engine/configs/rag_collections.yml`
- Create: `services/rag-engine/configs/mappings/eduscol_multilevel_levels.yml`
- Create: `services/rag-engine/configs/mappings/eduscol_multilevel_subjects.yml`
- Create: `services/rag-engine/configs/mappings/eduscol_multilevel_document_types.yml`
- Create: ten YAML files under `services/rag-engine/configs/ingestion_profiles/staging/multilevel/`
- Create: `services/rag-engine/configs/ingestion_profiles/staging/multilevel_manifest.json`
- Modify: `services/rag-engine/src/ingestor/collection_config.py`
- Modify: `services/rag-engine/src/ingestor/verified_pedagogical_placement.py`
- Create: `services/rag-engine/tests/test_multilevel_verified_placement.py`

- [ ] Add RED tests for observed `4e/seconde/premiere/terminale`, aliases,
  document types and Seconde `voie=generale`.
- [ ] Run the focused file; expect failures for missing mappings/profiles.
- [ ] Resolve programme versions from canonical indexes, including NSI independently.
- [ ] Implement closed mappings; reject every unknown value.
- [ ] Add ten exact profiles plus manifest and negative tests for missing,
  disabled, programme/fingerprint drift; verify RED then GREEN.
- [ ] Run resolver/profile/index alignment tests PASS.
- [ ] Request spec then code-quality review for Chunk 1; fix all Important issues.

## Chunk 2: Governed authorities and releases

### Task 4: Currentness, rights, PII and preflight

**Files:**
- Create: `services/rag-pedago/configs/prerentree_2026_2027/multilevel_currentness_evidence.yml`
- Create externally then bind: targeted PII evidence for exact unique SHA set
- Modify: `services/rag-pedago/scripts/build_multilevel_release.py`
- Test: `services/rag-pedago/tests/test_build_multilevel_release.py`

- [ ] Add RED tests for root+artifact `school_year=2026-2027`, programme,
  catalog/inventory digests, path, official URL, served SHA and byte identity.
- [ ] Resolve official sources read-only and serialize `CURRENT`/`REVIEW_REQUIRED` for every candidate.
- [ ] Resolve rights only through `VerifiedRightsEvidenceRegistry`; assert zero unevaluated.
- [ ] Run existing PII scanner once per unique SHA under v5; bind inventory digest.
- [ ] Extract pages and preflight real-E5 chunks without logging text.
- [ ] Assert global/per-collection candidate partition has no gaps.

### Task 5: Governed corpus delta where required

**Files:**
- Create if needed: `services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/corpus_delta.json`
- Create if needed: `services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/corpus_manifest_vnext.json`
- Create if needed: `services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/sealed_catalog_vnext.json`
- Test: `services/rag-pedago/tests/test_multilevel_corpus_delta.py`

- [ ] For each zero/no-eligible target, serialize searches of placements, physical
  paths, multi-niveaux, non-classe, subject+programme and official sources.
- [ ] Add RED append-only delta test linked to parent manifest/catalog digest.
- [ ] Trigger delta when current official bytes are absent, not only on zero catalog rows.
- [ ] Download only official current resources, verify SHA/provenance and bind exact placements.
- [ ] Rebuild `candidate_inventory.json` from the vNext catalogue; regenerate
  currentness and targeted PII evidence whose SHA set equals that final inventory.
- [ ] Replay rights, extraction and chunking on the same final inventory.
- [ ] Refuse a release manifest that references any pre-delta inventory or proof.
- [ ] Keep unresolved gaps inactive with exact reason and `CORPUS_DELTA_REQUIRED=true`.

### Task 6: Collection releases and aggregate

**Files:**
- Create: ten `*.release.json` files under `services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/`
- Create: `services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/multilevel.release.json`
- Modify: `services/rag-engine/src/ingestor/wave0_release.py`
- Modify: `services/rag-engine/src/ingestor/ingestion_worker/runner.py`
- Modify: `services/rag-engine/src/ingestor/ingestion_worker/publication_resume.py`
- Create: `services/rag-engine/tests/test_multilevel_release_authority.py`

- [ ] Add RED tests for ten manifests, authority/model pins and exact partitions.
- [ ] Pin E5 ID/dimension/inventory and reranker ID/inventory exactly as in the
  design; assert `FAKE_VECTOR_ROWS=0` in the real acceptance.
- [ ] Add RED test allowing same SHA with identical physical/chunk facts across
  releases and refusing conflicting facts.
- [ ] Generate expected real-E5 chunks before DB writes.
- [ ] Load the aggregate fail-closed and expose per-collection sets.
- [ ] Add RED propagation test for `source_placement_id` Worker A → durable facts → Worker B.
- [ ] Implement propagation and real `1 artifact → N placements → 1 embedding set` E2E.
- [ ] Prove runtime contains no collection SHA allowlist.
- [ ] Request spec then quality review for Chunk 2; fix all Important issues.

## Chunk 3: Scopes, readiness and ingestion

### Task 7: Ten signed scopes and multi-release readiness

**Files:**
- Create: ten JSON artifacts named from the ten scope IDs in the design under `packages/contracts/src/nexus_contracts/artifacts/`
- Modify: `packages/contracts/src/nexus_contracts/scope.py`
- Modify: `services/rag-engine/src/ingestor/identity_v2.py`
- Modify: `services/rag-engine/src/ingestor/release_readiness.py`
- Modify: `services/rag-engine/src/ingestor/api_v2.py`
- Create: `services/rag-engine/tests/test_multilevel_scope_registry.py`

- [ ] Add RED tests for all IDs, single collections, target/evidence levels,
  `teacher/internal`, unknown ID, wrong digest, cross-scope, wrong dimensions and role.
- [ ] Extend explicit registry without wildcard; rerun PASS.
- [ ] Add RED readiness tests for multiple releases and exact per-collection sets.
- [ ] Generalize readiness; preserve legacy collections outside the aggregate.
- [ ] Gate new NSI scopes on exact new release and prove historical rows cannot satisfy it.

### Task 8: Phase A/B/C governed ingestion

**Files:**
- Create: `services/rag-engine/tests/integration/test_multilevel_real_ingestion.py`
- Modify minimally: runtime authority/CLI files for generic aggregate support

- [ ] Add opt-in `test_multilevel_batch_reaches_retrieval_eligible` driving real
  LOT41A, Worker A, LOT42 and Worker B for all eligible placements.
- [ ] Run with real PostgreSQL/E5 CPU; expect RED at first unsupported collection.
- [ ] Ingest Phase A, B then C, continuing after isolated job failures.
- [ ] Reconcile full artifact/placement/chunk/page/model/governance-pin sets.
- [ ] Replay the complete batch; assert zero duplicates and new embeddings.

### Task 9: NSI legacy and CLI proof

**Files:**
- Create: `services/rag-engine/tests/integration/test_multilevel_worker_cli_e2e.py`
- Create: `services/rag-engine/src/ingestor/nsi_legacy_diagnostic.py`
- Test: `services/rag-engine/tests/test_nsi_legacy_diagnostic.py`

- [ ] Add RED tests separating total, governed and legacy NSI rows.
- [ ] Implement read-only diagnostics; never mutate/certify history.
- [ ] Run Worker A/B `--once` against the aggregate on a clean DB.
- [ ] Assert both CLI PASS and `NSI_LEGACY_CERTIFIED_AS_GOVERNED=false`.
- [ ] Request spec then quality review for Chunk 3; fix all Important issues.

## Chunk 4: Search, activation and delivery

### Task 10: Search smoke and discoverability

**Files:**
- Create: `services/rag-engine/tests/fixtures/multilevel_search_acceptance.yml`
- Create: `services/rag-engine/tests/integration/test_multilevel_http_search.py`

- [ ] Add RED dataset contract tests for ≥3 natural queries per ingested collection
  and one probe per release artifact.
- [ ] Run real uvicorn with BFF, signed identities, E5 and reranker.
- [ ] Require hits, pages, citations, right collection and zero scope leaks.
- [ ] Record 100% artifact discoverability per ingested collection.
- [ ] Re-run the existing Maths/Français Troisième real-HTTP queries and scope
  isolation checks on the same server.

### Task 11: Activation and report

**Files:**
- Modify: `services/rag-engine/configs/rag_collections.yml`
- Modify: `services/cockpit/src/data/collections.json`
- Modify: `docs/reports/lot_multilevel_ingestion_2026_2027.md`
- Modify: `docs/adr/ADR-0040-extension-multi-niveaux-prioritaire.md`

- [ ] Add RED activation tests requiring non-empty exact-ready releases.
- [ ] Activate only reconciled target collections; preserve genuine zeros false.
- [ ] Mirror cockpit state mechanically and verify snapshots.
- [ ] Populate ten report rows, globals, NSI legacy and safety metrics.

### Task 12: Verification and PR delivery

- [ ] Run focused ruff/mypy/unit/governance tests after each chunk.
- [ ] Run real-model ingestion, idempotence and HTTP acceptance fresh.
- [ ] Run canonical `bash scripts/ci-local.sh` and require zero failures.
- [ ] Request final independent spec and code-quality review; fix Critical/Important.
- [ ] Commit the coherent vertical slice, push without force, update PR #95 body
  while keeping Draft, and wait for native GitHub CI on the exact final HEAD.

## Execution ledger: 2–5 minute checkpoints and commits

The following order is mandatory; every checkbox has one observable command or
artifact and is small enough to stop/review independently.

Initialize the command context once, without machine-local paths in versioned
files:

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
PEDAGO_ROOT="$REPO_ROOT/services/rag-pedago"
ENGINE_ROOT="$REPO_ROOT/services/rag-engine"
CONTRACTS_ROOT="$REPO_ROOT/packages/contracts"
COCKPIT_ROOT="$REPO_ROOT/services/cockpit"
SEALED_CATALOG="${NEXUS_SEALED_CATALOG_PATH:?set NEXUS_SEALED_CATALOG_PATH}"
RIGHTS_EVIDENCE="${NEXUS_RIGHTS_EVIDENCE_PATH:?set NEXUS_RIGHTS_EVIDENCE_PATH}"
MULTILEVEL_PII_EVIDENCE="${NEXUS_MULTILEVEL_PII_EVIDENCE_PATH:?set NEXUS_MULTILEVEL_PII_EVIDENCE_PATH}"
BOUNDED_SCRATCH="$(mktemp -d)"
chmod 0700 "$BOUNDED_SCRATCH"
TARGET_COLLECTIONS=(rag_nexus_maths_seconde_tc rag_nexus_francais_seconde_tc rag_nexus_maths_quatrieme_tc rag_nexus_francais_quatrieme_tc rag_nexus_maths_premiere_gen_specialite rag_nexus_nsi_premiere_specialite rag_nexus_francais_premiere_tc rag_nexus_maths_terminale_gen_specialite rag_nexus_nsi_terminale_specialite rag_nexus_pc_terminale_specialite)
PHASE_A_COLLECTIONS=(rag_nexus_maths_seconde_tc rag_nexus_francais_seconde_tc rag_nexus_maths_quatrieme_tc rag_nexus_francais_quatrieme_tc)
PHASE_B_COLLECTIONS=(rag_nexus_maths_premiere_gen_specialite rag_nexus_nsi_premiere_specialite rag_nexus_francais_premiere_tc)
PHASE_C_COLLECTIONS=(rag_nexus_maths_terminale_gen_specialite rag_nexus_nsi_terminale_specialite rag_nexus_pc_terminale_specialite)
test "${RAG_EMBEDDING_MODEL_INVENTORY_SHA256:?}" = e2c7384ba36096b3f3bdfff4973f728596104aff0f1d38f1b6463e60765fe22a
test "${RAG_RERANKER_MODEL_INVENTORY_SHA256:?}" = bdcedc4d7cfe647b9aaa5a7546822dfee7826ebb3c64472bf89eae7592e08fe1
```

### Commit A — `docs(rag): design governed multilevel ingestion`

- [ ] Run `git -C "$REPO_ROOT" diff --check -- docs/superpowers`; expect exit 0.
- [ ] Run independent plan review; require no Critical/Important finding.
- [ ] Run `git -C "$REPO_ROOT" add -- docs/superpowers/specs/2026-08-12-multilevel-priority-ingestion-design.md docs/superpowers/plans/2026-08-12-multilevel-priority-ingestion.md`.
- [ ] Run `git -C "$REPO_ROOT" diff --cached --name-only && git -C "$REPO_ROOT" diff --cached --check`; expect exactly two files and exit 0.
- [ ] Run `git -C "$REPO_ROOT" commit -m "docs(rag): design governed multilevel ingestion"`.

### Commit B — `rag-pedago: inventory multilevel release candidates`

- [ ] Create the RED target-matrix test; run its single pytest node.
- [ ] Implement only the frozen ten-row matrix; rerun the node GREEN.
- [ ] Create the RED dedup/placement test; run its single node.
- [ ] Implement exact-grade selection; rerun GREEN.
- [ ] Create the RED six-route/partition tests; run both nodes.
- [ ] Implement route evidence and reason codes; rerun the builder file GREEN.
- [ ] Run `(cd "$PEDAGO_ROOT" && .venv/bin/python scripts/build_multilevel_release.py inventory --catalog "$SEALED_CATALOG" --output "$BOUNDED_SCRATCH/inventory-a.json")`; expect 10 rows.
- [ ] Repeat to `$BOUNDED_SCRATCH/inventory-b.json`; run `cmp "$BOUNDED_SCRATCH/inventory-a.json" "$BOUNDED_SCRATCH/inventory-b.json"`; expect exit 0.
- [ ] Run `git -C "$REPO_ROOT" add -- services/rag-pedago/scripts/build_multilevel_release.py services/rag-pedago/tests/test_build_multilevel_release.py services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/candidate_inventory.json docs/reports/lot_multilevel_ingestion_2026_2027.md`.
- [ ] Run `git -C "$REPO_ROOT" diff --cached --name-only && git -C "$REPO_ROOT" diff --cached --check`; expect only those four paths.
- [ ] Run `git -C "$REPO_ROOT" commit -m "rag-pedago: inventory multilevel release candidates"`.

### Commit C — `contracts: add quatrieme retrieval level`

- [ ] Add and run the single RED enum test.
- [ ] Add enum plus package version `0.11.0`; rerun GREEN.
- [ ] Add RED Quatrième index/taxonomy/config tests; run the focused nodes.
- [ ] Add index, taxonomies and dormant collections; rerun GREEN.
- [ ] Export all six affected package schemas; run `git diff --check`.
- [ ] Generate cockpit schemas/types; run `npm run contracts:check`.
- [ ] Run package contracts plus collection config tests; expect PASS.
- [ ] Run `git -C "$REPO_ROOT" add -- packages/contracts/src/nexus_contracts/document.py packages/contracts/pyproject.toml packages/contracts/tests/test_contracts.py packages/contracts/schema/chat-request.json packages/contracts/schema/internal-identity-envelope.json packages/contracts/schema/internal-identity.json packages/contracts/schema/pilot-retrieval-scope-artifact.json packages/contracts/schema/retrieval-request.json packages/contracts/schema/retrieval-scope-artifact-v2.json services/cockpit/src/generated/contracts.ts services/cockpit/src/generated/validators.ts services/cockpit/src/generated/schema/chat-request.json services/cockpit/src/generated/schema/internal-identity-envelope.json services/cockpit/src/generated/schema/internal-identity.json services/cockpit/src/generated/schema/pilot-retrieval-scope-artifact.json services/cockpit/src/generated/schema/retrieval-request.json services/cockpit/src/generated/schema/retrieval-scope-artifact-v2.json services/cockpit/src/types/ui.ts services/cockpit/src/sections/OverviewSection.tsx services/rag-engine/configs/rag_collections.yml services/rag-engine/src/ui/app_v2.py services/rag-engine/tests/test_rag_collections_config.py services/rag-pedago/taxonomy/maths/quatrieme.yml services/rag-pedago/taxonomy/francais/quatrieme.yml corpus/College/Quatrieme/_index.yml scripts/lib/validate_cockpit_snapshots.py docs/adr/ADR-0040-extension-multi-niveaux-prioritaire.md`.
- [ ] Run `git -C "$REPO_ROOT" diff --cached --name-only && git -C "$REPO_ROOT" diff --cached --check`; compare to the command’s exact path list.
- [ ] Run `git -C "$REPO_ROOT" commit -m "contracts: add quatrieme retrieval level"`.

### Commit D — `rag-engine: govern multilevel placements and profiles`

- [ ] Add one RED node per level, subject alias and document type table.
- [ ] Add closed YAML mappings only for observed values; rerun nodes GREEN.
- [ ] Add RED Seconde voie and NSI programme alignment tests.
- [ ] Add/fix canonical indexes; rerun alignment tests GREEN.
- [ ] Add ten named profiles and RED manifest drift tests.
- [ ] Generate profile manifest; rerun resolver/profile suite GREEN.
- [ ] Run ruff and mypy on changed engine files; expect PASS.
- [ ] Run `git -C "$REPO_ROOT" add -- services/rag-engine/configs/rag_collections.yml services/rag-engine/configs/mappings/eduscol_multilevel_levels.yml services/rag-engine/configs/mappings/eduscol_multilevel_subjects.yml services/rag-engine/configs/mappings/eduscol_multilevel_document_types.yml services/rag-engine/configs/ingestion_profiles/staging/multilevel/maths_seconde_tc_multilevel_v1.yml services/rag-engine/configs/ingestion_profiles/staging/multilevel/francais_seconde_tc_multilevel_v1.yml services/rag-engine/configs/ingestion_profiles/staging/multilevel/maths_quatrieme_tc_multilevel_v1.yml services/rag-engine/configs/ingestion_profiles/staging/multilevel/francais_quatrieme_tc_multilevel_v1.yml services/rag-engine/configs/ingestion_profiles/staging/multilevel/maths_premiere_gen_specialite_multilevel_v1.yml services/rag-engine/configs/ingestion_profiles/staging/multilevel/nsi_premiere_specialite_multilevel_v1.yml services/rag-engine/configs/ingestion_profiles/staging/multilevel/francais_premiere_tc_multilevel_v1.yml services/rag-engine/configs/ingestion_profiles/staging/multilevel/maths_terminale_gen_specialite_multilevel_v1.yml services/rag-engine/configs/ingestion_profiles/staging/multilevel/nsi_terminale_specialite_multilevel_v1.yml services/rag-engine/configs/ingestion_profiles/staging/multilevel/pc_terminale_specialite_multilevel_v1.yml services/rag-engine/configs/ingestion_profiles/staging/multilevel_manifest.json services/rag-engine/src/ingestor/collection_config.py services/rag-engine/src/ingestor/verified_pedagogical_placement.py services/rag-engine/tests/test_multilevel_verified_placement.py corpus/Lycee/Premiere/Specialites/_index.yml corpus/Lycee/Terminale/Specialites/_index.yml`.
- [ ] Run `git -C "$REPO_ROOT" diff --cached --name-only && git -C "$REPO_ROOT" diff --cached --check`; compare to the exact list.
- [ ] Run `git -C "$REPO_ROOT" commit -m "rag-engine: govern multilevel placements and profiles"`.

### Commit E — `rag-pedago: seal multilevel release evidence`

- [ ] Add RED currentness schema/set equality tests.
- [ ] Run `for slug in "${TARGET_COLLECTIONS[@]}"; do (cd "$PEDAGO_ROOT" && .venv/bin/python scripts/build_multilevel_release.py currentness --collection "$slug" --inventory data/releases/prerentree_2026_2027/multilevel/candidate_inventory.json --scratch "$BOUNDED_SCRATCH") || exit; done`; expect every candidate classified `CURRENT` or `REVIEW_REQUIRED` and zero unevaluated.
- [ ] Add RED rights/PII/preflight partition tests.
- [ ] Run `(cd "$PEDAGO_ROOT" && .venv/bin/python scripts/build_multilevel_release.py rights --inventory data/releases/prerentree_2026_2027/multilevel/candidate_inventory.json --rights-evidence "$RIGHTS_EVIDENCE")`; expect unresolved=0.
- [ ] Run `(cd "$PEDAGO_ROOT" && .venv/bin/python scripts/build_multilevel_release.py pii-inputs --inventory data/releases/prerentree_2026_2027/multilevel/candidate_inventory.json --output "$BOUNDED_SCRATCH/multilevel-required-paths.json")`; expect unique SHA cardinality.
- [ ] Run `(cd "$PEDAGO_ROOT" && .venv/bin/python scripts/build_multilevel_release.py pii-scan --required-paths "$BOUNDED_SCRATCH/multilevel-required-paths.json" --output "$MULTILEVEL_PII_EVIDENCE")`; expect coverage=1.0, mismatch=0.
- [ ] Run `for slug in "${TARGET_COLLECTIONS[@]}"; do (cd "$PEDAGO_ROOT" && .venv/bin/python scripts/build_multilevel_release.py preflight --collection "$slug" --embedding-artifact "$RAG_EMBEDDING_MODEL_CACHE_DIR") || exit; done`; expect every eligible artifact pages/chunks>0, coverage=100%, oversized=0.
- [ ] If needed, add RED append-only corpus-delta test and materialize vNext.
- [ ] If delta exists, run `(cd "$PEDAGO_ROOT" && .venv/bin/python scripts/build_multilevel_release.py inventory --catalog data/releases/prerentree_2026_2027/multilevel/sealed_catalog_vnext.json --output data/releases/prerentree_2026_2027/multilevel/candidate_inventory.json)`; expect parent digest recorded.
- [ ] If delta exists, rerun the ten `currentness` commands and the one `pii-scan` command; run `(cd "$PEDAGO_ROOT" && .venv/bin/pytest tests/test_build_multilevel_release.py::test_final_authority_sets_equal_final_inventory -q)`; expect PASS.
- [ ] Run `for slug in "${TARGET_COLLECTIONS[@]}"; do (cd "$PEDAGO_ROOT" && .venv/bin/python scripts/build_multilevel_release.py release --collection "$slug" --output data/releases/prerentree_2026_2027/multilevel) || exit; done`; expect one subject manifest with exact authority/model pins.
- [ ] Run `(cd "$PEDAGO_ROOT" && .venv/bin/python scripts/build_multilevel_release.py aggregate --release-root data/releases/prerentree_2026_2027/multilevel --output data/releases/prerentree_2026_2027/multilevel/multilevel.release.json)`; expect 10 subject references.
- [ ] Repeat aggregate generation to `$BOUNDED_SCRATCH/multilevel.release.json`; run `cmp "$PEDAGO_ROOT/data/releases/prerentree_2026_2027/multilevel/multilevel.release.json" "$BOUNDED_SCRATCH/multilevel.release.json"`; expect exit 0.
- [ ] Run `git -C "$REPO_ROOT" add -- services/rag-pedago/configs/prerentree_2026_2027/multilevel_currentness_evidence.yml services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/candidate_inventory.json services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/seconde/maths.release.json services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/seconde/francais.release.json services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/quatrieme/maths.release.json services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/quatrieme/francais.release.json services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/premiere/maths_specialite.release.json services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/premiere/nsi_specialite.release.json services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/premiere/francais.release.json services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/terminale/maths_specialite.release.json services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/terminale/nsi_specialite.release.json services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/terminale/physique_chimie_specialite.release.json services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/multilevel.release.json services/rag-pedago/scripts/build_multilevel_release.py services/rag-pedago/tests/test_build_multilevel_release.py services/rag-pedago/tests/test_multilevel_corpus_delta.py`.
- [ ] Run `for path in services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/corpus_delta.json services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/corpus_manifest_vnext.json services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/sealed_catalog_vnext.json; do test ! -e "$REPO_ROOT/$path" || git -C "$REPO_ROOT" add -- "$path"; done`.
- [ ] Run `git -C "$REPO_ROOT" diff --cached --name-only && git -C "$REPO_ROOT" diff --cached --check`; compare to existing paths from the exact list (optional delta paths may be absent).
- [ ] Run `git -C "$REPO_ROOT" commit -m "rag-pedago: seal multilevel release evidence"`.

### Commit F — `rag-engine: ingest multilevel releases end to end`

- [ ] Add RED aggregate multi-placement and conflicting-facts nodes.
- [ ] Generalize loader/placement propagation minimally; rerun GREEN.
- [ ] Add RED ten-scope registry/readiness nodes; implement and rerun GREEN.
- [ ] Run `for slug in "${PHASE_A_COLLECTIONS[@]}"; do (cd "$ENGINE_ROOT" && NEXUS_REQUIRE_DOCKER=1 CUDA_VISIBLE_DEVICES='' .venv/bin/pytest -q "tests/integration/test_multilevel_real_ingestion.py::test_multilevel_collection_ingests[$slug]") || exit; done`; expect PASS or a durable named noneligible reason already present in the manifest.
- [ ] Run `(cd "$ENGINE_ROOT" && NEXUS_REQUIRE_DOCKER=1 .venv/bin/pytest -q 'tests/integration/test_multilevel_real_ingestion.py::test_phase_reconciliation[A]')`; expect exact sets and pins.
- [ ] Run `for slug in "${PHASE_B_COLLECTIONS[@]}"; do (cd "$ENGINE_ROOT" && NEXUS_REQUIRE_DOCKER=1 CUDA_VISIBLE_DEVICES='' .venv/bin/pytest -q "tests/integration/test_multilevel_real_ingestion.py::test_multilevel_collection_ingests[$slug]") || exit; done`, then `(cd "$ENGINE_ROOT" && NEXUS_REQUIRE_DOCKER=1 .venv/bin/pytest -q 'tests/integration/test_multilevel_real_ingestion.py::test_phase_reconciliation[B]')`.
- [ ] Run `for slug in "${PHASE_C_COLLECTIONS[@]}"; do (cd "$ENGINE_ROOT" && NEXUS_REQUIRE_DOCKER=1 CUDA_VISIBLE_DEVICES='' .venv/bin/pytest -q "tests/integration/test_multilevel_real_ingestion.py::test_multilevel_collection_ingests[$slug]") || exit; done`, then `(cd "$ENGINE_ROOT" && NEXUS_REQUIRE_DOCKER=1 .venv/bin/pytest -q 'tests/integration/test_multilevel_real_ingestion.py::test_phase_reconciliation[C]')`.
- [ ] Run `(cd "$ENGINE_ROOT" && NEXUS_REQUIRE_DOCKER=1 .venv/bin/pytest -q tests/integration/test_multilevel_real_ingestion.py::test_multilevel_release_reconciliation)`; expect all collection deltas zero.
- [ ] Run `(cd "$ENGINE_ROOT" && NEXUS_REQUIRE_DOCKER=1 CUDA_VISIBLE_DEVICES='' .venv/bin/pytest -q tests/integration/test_multilevel_real_ingestion.py::test_complete_batch_is_idempotent)`; expect duplicates/new embeddings zero.
- [ ] Run `(cd "$ENGINE_ROOT" && .venv/bin/pytest -q tests/test_nsi_legacy_diagnostic.py)`; expect governed/legacy partition PASS.
- [ ] Run `(cd "$ENGINE_ROOT" && NEXUS_REQUIRE_DOCKER=1 .venv/bin/pytest -q tests/integration/test_multilevel_worker_cli_e2e.py::test_worker_a_cli_multicollection)`; expect PASS.
- [ ] Run `(cd "$ENGINE_ROOT" && NEXUS_REQUIRE_DOCKER=1 CUDA_VISIBLE_DEVICES='' .venv/bin/pytest -q tests/integration/test_multilevel_worker_cli_e2e.py::test_worker_b_cli_multicollection)`; expect PASS.
- [ ] Run `git -C "$REPO_ROOT" add -- services/rag-engine/src/ingestor/wave0_release.py services/rag-engine/src/ingestor/ingestion_worker/runner.py services/rag-engine/src/ingestor/ingestion_worker/publication_resume.py services/rag-engine/src/ingestor/ingestion_worker/runtime_authority.py services/rag-engine/src/ingestor/ingestion_worker/cli.py services/rag-engine/src/ingestor/ingestion_worker/publication_resume_cli.py services/rag-engine/src/ingestor/identity_v2.py services/rag-engine/src/ingestor/release_readiness.py services/rag-engine/src/ingestor/api_v2.py services/rag-engine/src/ingestor/nsi_legacy_diagnostic.py services/rag-engine/tests/test_multilevel_release_authority.py services/rag-engine/tests/test_multilevel_scope_registry.py services/rag-engine/tests/test_nsi_legacy_diagnostic.py services/rag-engine/tests/integration/test_multilevel_real_ingestion.py services/rag-engine/tests/integration/test_multilevel_worker_cli_e2e.py packages/contracts/src/nexus_contracts/scope.py packages/contracts/src/nexus_contracts/artifacts/retrieval-scope-entree-premiere-maths-v1.json packages/contracts/src/nexus_contracts/artifacts/retrieval-scope-entree-premiere-francais-v1.json packages/contracts/src/nexus_contracts/artifacts/retrieval-scope-entree-troisieme-maths-v1.json packages/contracts/src/nexus_contracts/artifacts/retrieval-scope-entree-troisieme-francais-v1.json packages/contracts/src/nexus_contracts/artifacts/retrieval-scope-entree-terminale-maths-v1.json packages/contracts/src/nexus_contracts/artifacts/retrieval-scope-entree-terminale-nsi-v1.json packages/contracts/src/nexus_contracts/artifacts/retrieval-scope-eaf-premiere-francais-v1.json packages/contracts/src/nexus_contracts/artifacts/retrieval-scope-terminale-maths-v1.json packages/contracts/src/nexus_contracts/artifacts/retrieval-scope-terminale-nsi-v1.json packages/contracts/src/nexus_contracts/artifacts/retrieval-scope-terminale-physique-chimie-v1.json`.
- [ ] Run `git -C "$REPO_ROOT" diff --cached --name-only && git -C "$REPO_ROOT" diff --cached --check`; compare to the exact list.
- [ ] Run `git -C "$REPO_ROOT" commit -m "rag-engine: ingest multilevel releases end to end"`.

### Commit G — `rag-engine: accept multilevel search and readiness`

- [ ] Add RED dataset contract (three queries/collection + artifact probes).
- [ ] Run `for slug in "${TARGET_COLLECTIONS[@]}"; do (cd "$ENGINE_ROOT" && NEXUS_REQUIRE_DOCKER=1 CUDA_VISIBLE_DEVICES='' .venv/bin/pytest -q "tests/integration/test_multilevel_http_search.py::test_collection_search_smoke[$slug]") || exit; done`; expect 3/3, citations/pages present for each ingested collection and an explicit inactive skip for a genuine zero.
- [ ] Run `for slug in "${TARGET_COLLECTIONS[@]}"; do (cd "$ENGINE_ROOT" && NEXUS_REQUIRE_DOCKER=1 CUDA_VISIBLE_DEVICES='' .venv/bin/pytest -q "tests/integration/test_multilevel_http_search.py::test_artifact_discoverability[$slug]") || exit; done`; expect 100% for every active release.
- [ ] Run `(cd "$ENGINE_ROOT" && NEXUS_REQUIRE_DOCKER=1 CUDA_VISIBLE_DEVICES='' .venv/bin/pytest -q tests/integration/test_multilevel_http_search.py::test_cross_scope_isolation)`; expect leaks=0.
- [ ] Run `(cd "$ENGINE_ROOT" && NEXUS_REQUIRE_DOCKER=1 CUDA_VISIBLE_DEVICES='' .venv/bin/pytest -q tests/integration/test_wave0_french_pgvector.py::test_wave0_real_http_search_is_authenticated_isolated_and_semantic)`; expect existing Troisième 20/20 regression PASS.
- [ ] Add RED activation test, then activate only exact-ready nonempty collections.
- [ ] Mirror cockpit collection flags and run snapshot tests.
- [ ] Complete the ten-row report and ADR; commit.
- [ ] Run `git -C "$REPO_ROOT" add -- services/rag-engine/tests/fixtures/multilevel_search_acceptance.yml services/rag-engine/tests/integration/test_multilevel_http_search.py services/rag-engine/configs/rag_collections.yml services/cockpit/src/data/collections.json docs/reports/lot_multilevel_ingestion_2026_2027.md docs/adr/ADR-0040-extension-multi-niveaux-prioritaire.md`.
- [ ] Run `git -C "$REPO_ROOT" diff --cached --name-only && git -C "$REPO_ROOT" diff --cached --check`; expect only those six paths.
- [ ] Run `git -C "$REPO_ROOT" commit -m "rag-engine: accept multilevel search and readiness"`.

### Exact-head delivery

- [ ] Run `(cd "$CONTRACTS_ROOT" && make lint && make typecheck && make test)`; expect exit 0.
- [ ] Run `(cd "$PEDAGO_ROOT" && make lint && make typecheck && make test)`; expect exit 0.
- [ ] Run `(cd "$ENGINE_ROOT" && make lint && make typecheck && make test)`; expect exit 0.
- [ ] Run `(cd "$COCKPIT_ROOT" && npm run contracts:check)`; expect exit 0.
- [ ] Run `bash "$REPO_ROOT/scripts/check-governance-locks.sh"`; expect exit 0.
- [ ] Run `(cd "$ENGINE_ROOT" && NEXUS_REQUIRE_DOCKER=1 CUDA_VISIBLE_DEVICES='' .venv/bin/pytest -q tests/integration/test_multilevel_real_ingestion.py tests/integration/test_multilevel_worker_cli_e2e.py)`; expect exit 0.
- [ ] Run `(cd "$ENGINE_ROOT" && NEXUS_REQUIRE_DOCKER=1 CUDA_VISIBLE_DEVICES='' .venv/bin/pytest -q tests/integration/test_multilevel_http_search.py)`; expect exit 0.
- [ ] Run `bash "$REPO_ROOT/scripts/ci-local.sh"`; capture exact exit 0.
- [ ] Request independent spec/code review and resolve every Critical/Important.
- [ ] Commit any review fixes, rerun affected suites and local CI.
- [ ] Push normally, update PR #95 body, keep Draft and wait for GitHub native CI.
