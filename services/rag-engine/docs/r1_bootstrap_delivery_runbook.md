# R1 bootstrap delivery runbook

Operator runbook for the one-time governed `ResourceRegistryBootstrap` export
that closes RAG issue #155 (Nexus C05a, R1 phase). This is **not** an
automated pipeline: every step below is run by hand, by a human operator who
holds authorized production database credentials. No step here is executed
by this repository's CI, and none of it should be.

This runbook does not introduce a new exporter or a new contract. It
sequences two commands that already exist in this repository
(`resource_registry_bootstrap_cli` and `r1_evidence_verifier_cli`) around the
one credential an operator must supply.

## Scope

Delivers **R1 only**: the governed `ResourceRegistryBootstrap` artifact for
release `production-profile-gate-2026-2027-v1`. Does **not** deliver a
`ServableCorpusManifest` (R2 phase, separately due) and does **not** touch
Nexus in any way — this repository has no write access to Nexus and this
runbook does not grant it any.

## Preconditions

1. You hold a PostgreSQL connection string with **read-only** access to the
   `ingestion_control` and `public` (rag_artifacts/rag_artifact_placements/
   rag_chunks) schemas of the **production** RAG database. The exporter opens
   a `REPEATABLE READ, READ ONLY, DEFERRABLE` transaction and issues a single
   `SELECT` — it cannot mutate anything, but the DSN itself must still be
   handled as a production secret (never pass it on argv, never commit it,
   never log it).
2. `services/rag-engine`'s Python environment is provisioned (`.venv` per
   `Makefile`'s `install` target) on the machine you run this from.
3. You are on a commit of this repository whose `services/rag-pedago/data/
   releases/prerentree_2026_2027/release-registry.json` you trust — normally
   `origin/main` at the commit this runbook ships with, or later.

## Distinguishing the sealed release from the exporter code that runs it

The sealed corpus lineage (`production-profile-gate-2026-2027-v1`, its
`release-registry.json` digest, the per-subject release files) was created
before this hardening work and never changes as a result of it — a release
is sealed once, not re-sealed because exporter code improved. The Step 4
exporter, in contrast, always runs from whatever commit you are on right
now (Step 1). Both the exporter's own output and the verifier's report
print all four of these identities explicitly so they are never conflated:
`SEALED_RELEASE_ID`, `SEALED_RELEASE_AUTHORITY_SHA` (from the verifier),
`BOOTSTRAP_PRODUCER_REPOSITORY`, `BOOTSTRAP_PRODUCER_COMMIT` (the commit
that actually ran the export — normally the current merged HEAD, not the
historical pre-hardening commit this file's earlier revisions referenced).

## Step 1 — verify the repository commit

```bash
git -C /path/to/RAG rev-parse HEAD
git -C /path/to/RAG status --short   # must be empty: no local edits
```

Record this commit; it becomes `--producer-commit` in Step 4 and must be the
one attached to the delivered artifact and to the issue #155 evidence
comment.

## Step 2 — verify the sealed release authorities (no DB, no secrets)

```bash
cd services/rag-engine
RELEASE_REGISTRY=../rag-pedago/data/releases/prerentree_2026_2027/release-registry.json
sha256sum "$RELEASE_REGISTRY"
```

Confirm the printed digest against the value already recorded in RAG issue
#155 and in this runbook's own PR description
(`c9a844d4d2cc15caf9694b24ac53e77d65d50608d8a0daaef4963183d7d374fa` at the
time this runbook was written — re-derive it yourself, never trust a copied
value blindly). `load_release_registry_file` (used by both commands below)
re-verifies this digest and the full SHA256 chain down to every per-subject
release file itself; a mismatch anywhere in that chain raises loudly before
any row is ever read.

## Step 3 — verify the profile manifest + profiles (no DB, no secrets)

`audience` (and every other CollectionProfile scope dimension) is sealed
transitively through the signed ingestion profile manifest, not through the
subject-release files directly — see the module docstring on
`ingestor.r1_evidence_verifier` for the full proof chain. Confirm the real
files exist and are internally consistent before using them in Step 5:

```bash
cd services/rag-engine
PROFILE_ROOT=configs/ingestion_profiles/v2_livraison_319
PROFILE_MANIFEST=configs/ingestion_profiles/ingestion_manifest_v2_livraison_319.yml
sha256sum "$PROFILE_MANIFEST"
```

Never trust `$PROFILE_ROOT`/`$PROFILE_MANIFEST` merely because they sit at
this familiar, documented path — Step 5's verifier independently
recomputes every profile's real fingerprint against the sealed release and
refuses a mismatch, so a wrong or tampered directory fails loudly rather
than silently passing.

## Step 4 — run the existing governed exporter

```bash
cd services/rag-engine
export NEXUS_RESOURCE_EXPORT_DSN="postgresql://<read-only-role>@<prod-host>/<db>?sslmode=require"

PYTHONPATH=src ./.venv/bin/python scripts/build_resource_registry_bootstrap_inventory_cli.py \
  --producer-commit "$(git rev-parse HEAD)" \
  --generated-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --output /secure/path/resource-registry-bootstrap-production-profile-gate-2026-2027-v1.json \
  --release-registry-path ../rag-pedago/data/releases/prerentree_2026_2027/release-registry.json \
  --release-registry-sha256 <the digest confirmed in Step 2>
```

Notes:

- `--generated-at` **must** be the actual wall-clock time of this run, taken
  live from the command substitution above. Never precompute or hardcode it
  — a fabricated timestamp breaks the artifact's own provenance claim.
- `NEXUS_RESOURCE_EXPORT_DSN` is read from the environment, never accepted on
  argv (`resource_registry_bootstrap_cli.main` refuses to start without it
  and never echoes it).
- On success the command prints `RESOURCE_REGISTRY_BOOTSTRAP_SHA256=...` and
  `RESOURCE_REGISTRY_BOOTSTRAP_ROWS=...`. Record both.
- On failure (`BootstrapInventoryError`, including
  `"governed inventory differs from the exact promoted release artifact
  bindings"`, `"conflicting semantic placements share collection"`, or the
  new `"duplicate semantic placement"` guard) **stop here**. Do not proceed
  to Step 5 with a partial or hand-edited file. Escalate the exact error
  instead.

## Step 5 — immediately run the R1 evidence verifier

Never skip this step and never treat Step 4's success alone as sufficient —
the exporter proves internal consistency against the DB at read time; the
verifier independently proves the resulting **file** matches the sealed
release (across all 11 canonical dimensions, `audience` included) and the
signed profile authority, with zero trust that Step 4 ran uncorrupted.

```bash
cd services/rag-engine
PYTHONPATH=src ./.venv/bin/python scripts/r1_evidence_verifier_cli.py \
  --bootstrap /secure/path/resource-registry-bootstrap-production-profile-gate-2026-2027-v1.json \
  --release-registry-path ../rag-pedago/data/releases/prerentree_2026_2027/release-registry.json \
  --release-registry-sha256 <the same digest confirmed in Step 2> \
  --profile-root "$PROFILE_ROOT" \
  --profile-manifest-path "$PROFILE_MANIFEST" \
  --out /secure/path/r1-evidence-report.json
```

This step never opens a database connection and never mutates anything.
Production export must not proceed unless ALL of these gates in its output
read as shown:

```text
R1_PROFILE_MANIFEST_AUTHORITY=PASS
R1_PROFILE_RELEASE_SCOPE_CONSISTENCY=PASS
AUDIENCE_COMPARED_AGAINST_SEALED_AUTHORITY=True
R1_CANONICAL_PLACEMENT_DIMENSIONS=11
```

and finally:

- `R1_EVIDENCE_READY=YES` (exit code 0): every gate passed. Proceed to Step 6.
- `R1_EVIDENCE_READY=NO` (exit code 1) or `R1_EVIDENCE_VERIFIER_ERROR=...`
  (exit code 2): **do not publish the bootstrap.** Read
  `/secure/path/r1-evidence-report.json`'s `blockers` array (and, for a
  scope disagreement, its `gates.profile_scope_mismatches`) for the exact
  reason(s) and escalate.

## Step 6 — hash and retain evidence

```bash
sha256sum /secure/path/resource-registry-bootstrap-production-profile-gate-2026-2027-v1.json
sha256sum /secure/path/r1-evidence-report.json
```

Retain, alongside the artifact itself, in the operator's own secure evidence
store (never committed to this repository, which holds no production data):

- the exact command lines from Steps 4 and 5 (DSN redacted),
- their full stdout,
- the two SHA256 sums above,
- the git commit recorded in Step 1.

## Step 7 — hand off

Post the evidence (artifact SHA256, `RESOURCE_REGISTRY_BOOTSTRAP_ROWS`,
`R1_EVIDENCE_READY=YES`, and the retained command/output evidence) to RAG
issue #155 and notify the Nexus side. This runbook's job ends here: R1 is a
bootstrap-delivery-only phase. A `ServableCorpusManifest` is not required for
R1 completion (R2 is separate, separately gated, and out of scope for this
runbook).

## Any-gate-fails rule

If Step 4 (the exporter) fails: stop, do not retry blindly, escalate the
exact `BootstrapInventoryError`.

If Step 5 (the verifier) reports `R1_EVIDENCE_READY=NO`, any of
`R1_PROFILE_MANIFEST_AUTHORITY=FAIL` /
`R1_PROFILE_RELEASE_SCOPE_CONSISTENCY=FAIL`, or raises
`R1_EVIDENCE_VERIFIER_ERROR`: stop, do not publish the artifact, escalate
the exact blocker(s) or scope mismatch(es).

There is no partial-success path in this runbook. Production export does
not proceed until every gate in Step 5 reads PASS/YES/True as documented
there.
