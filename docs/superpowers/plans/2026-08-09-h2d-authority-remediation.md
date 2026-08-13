# H2-D Authority Remediation Implementation Plan

> **For Codex:** use test-driven development for each correction and verification-before-completion before every commit, push, or passing claim.

**Goal:** Correct the Terminale philosophy programme binding, regenerate every cryptographic dependency, publish the real H2-C head, and reach the LOT41A trusted-human-review boundary without touching production.

**Architecture:** The canonical Terminale corpus index supplies the machine programme identifier; the pedagogical registry and corpus fiche independently confirm the official BO reference. The H2 profile keeps its pre-release identity `h2c-v1`, while its content fingerprint and the manifest fingerprint rotate. PR #96 keeps the same authorization ID but receives newly serialized canonical bytes bound to those regenerated values. All final evidence is rebound to the final H2 commit.

**Tech Stack:** Python 3.12, Pydantic canonical authority contracts, pytest, YAML, SHA-256, GitHub trusted-review protocol, PostgreSQL/pgvector only in disposable integration environments.

---

## Task 1: Lock the programme source of truth

**Files:**
- Modify: `services/rag-engine/tests/test_h2c_placement_readiness.py`
- Read: `corpus/Lycee/Terminale/Tronc_commun/T_PHILOSOPHIE.md`
- Read: `corpus/Lycee/Terminale/Tronc_commun/_index.yml`
- Read: `services/rag-pedago/data/programmes/registre_programmes.yml`

1. Add a repository-level regression assertion that the H2 profile programme matches the philosophy entry in the Terminale corpus index and that the two human-readable authoritative sources identify BOEN special n°8 of 25 July 2019.
2. Run the focused test and record RED against `BO_2019-01-22`.

## Task 2: Regenerate profile and manifest bindings

**Files:**
- Modify: `services/rag-engine/configs/ingestion_profiles/philosophie_terminale_tc_h2c_v1.yml`
- Modify: `services/rag-engine/configs/ingestion_manifest.yml`
- Modify: `services/rag-engine/tests/test_h2c_placement_readiness.py`

1. Replace the incorrect programme with `BOEN_special_8_2019-07-25`.
2. Keep `profile_version=h2c-v1`: the profile has never been merged or authorized, and the correction precedes its first governed release. Do not create a second active profile for the same initial grant.
3. Recompute the profile fingerprint and manifest fingerprint with repository functions, then verify the production manifest exactly.
4. Run focused tests to GREEN.

## Task 3: Recompute the real philosophy scope and authority artifact

**Files:**
- Read: `/tmp/h2b_real_governed_catalog_20260808.json`
- Read: `$HOME/Documents/NEXUS_RAG_H2_EVIDENCE/h2b_pii_evidence_20260808.json`
- Read: `$HOME/Documents/NEXUS_RAG_H2_EVIDENCE/h2c_placement_readiness_20260809.json`
- Modify in authority worktree: `governance/authorizations/h2-initial-philosophie-20260809.json`

1. Reverify all external evidence hashes and corpus-manifest bindings.
2. Recompute philosophy current/PII/rights/placement counts and prove the quarantined SHA is excluded.
3. Build `ScopeAuthorizationArtifact` from regenerated values and write only `canonical_bytes()`.
4. Prove canonical serialization, path derivation, unknown-field rejection, digest recomputation, and the full authority drift matrix.

## Task 4: Rebind final H2 evidence

**Files:**
- Modify as required: `services/rag-pedago/scripts/h2b_true_mutation_harness.py`
- Modify as required: `services/rag-engine/scripts/h2c_governed_rehearsal.py`
- Modify: H2 technical report/evidence references

1. Bind mutation and rehearsal evidence explicitly to the final H2 Git SHA.
2. Re-run 12/12 real mutations and prove byte restoration.
3. Re-run real multi-placement PostgreSQL/pgvector rehearsal and prove one artifact/chunk/vector set, seven placements, deduplicated retrieval, and wrong-scope refusal.
4. Do not claim real LOT41A live verification before trusted approval.

## Task 5: Commit and push both branches without rewriting history

1. Commit coherent H2 changes on `track-a/lot-h2b-corpus-production-readiness`.
2. Verify every local-only commit is H2-C/H2-D and push a normal fast-forward to PR #95.
3. Commit canonical authority bytes on `governance/authorization/h2-initial-philosophie-20260809` and push a normal fast-forward to PR #96.
4. Confirm PR #96 remains open, ready, and unmerged; confirm PR #95 contains the actual H2-C implementation.

## Task 6: Close automated review and freeze the human challenge

1. Reply to the P1 thread with the exact regenerated values only after the fix is on GitHub.
2. Trigger/re-read automated review and resolve the thread only when the finding is obsolete and blocking findings are zero.
3. Derive a new LOT41V challenge from the live PR #96 base/head/author/reviewer dimensions. Never reuse the old challenge.

## Task 7: Verify the exact final H2 head

1. Freeze `H2_FINAL_HEAD`.
2. Run `bash scripts/ci-local.sh` with the valid Python 3.12 / Node 22.22 host environment.
3. Run secret, raw-PII, corpus-PDF, and credential tracking scans over `main..H2_FINAL_HEAD`.
4. Read every GitHub technical check on that exact head.
5. Stop at `LOT41A_TRUSTED_HUMAN_REVIEW` if no exact trusted approval exists. No production action is permitted.
