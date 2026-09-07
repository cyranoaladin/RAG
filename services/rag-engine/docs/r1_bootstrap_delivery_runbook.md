# R1 bootstrap delivery runbook

Operator runbook for the one-time governed `ResourceRegistryBootstrap` export
that closes RAG issue #155 (Nexus C05a, R1 phase). This is **not** an
automated pipeline: every step below is run by hand, by a human operator who
holds authorized production database credentials. No step here is executed
by this repository's CI, and none of it should be.

This runbook does not introduce a new exporter or a new contract. It
sequences commands that already exist in this repository
(`resource_registry_bootstrap_cli` and `r1_evidence_verifier_cli`) around the
one credential an operator must supply, plus the operational-governance
discipline (immutable artifacts, secret handling, exact commit pinning)
this document itself is responsible for.

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
   handled as a production secret: never pass it on argv, never commit it,
   never log it, and never let it reach shell history (Step 4 below).
2. `services/rag-engine`'s Python environment is provisioned (`.venv` per
   `Makefile`'s `install` target) on the machine you run this from.
3. You are on the **exact qualified exporter commit** for this R1 event, not
   merely "a recent commit" — see "Pinning the exporter commit" below. This
   is a real behavior change from earlier revisions of this runbook, which
   permitted "`origin/main` at the commit this runbook ships with, or
   later": that phrasing was too permissive for a governed one-shot export
   and is retracted.

## Distinguishing the sealed release from the exporter code that runs it

The sealed corpus lineage (`production-profile-gate-2026-2027-v1`, its
`release-registry.json` digest, the per-subject release files) was created
before this hardening work and never changes as a result of it — a release
is sealed once, not re-sealed because exporter code improved. The Step 5
exporter, in contrast, always runs from whatever commit you are on right
now (Step 1). Both the exporter's own output and the verifier's report
print all four of these identities explicitly so they are never conflated:
`SEALED_RELEASE_ID`, `SEALED_RELEASE_AUTHORITY_SHA` (from the verifier),
`BOOTSTRAP_PRODUCER_REPOSITORY`, `BOOTSTRAP_PRODUCER_COMMIT` (the commit
that actually ran the export).

## Pinning the exporter commit

This runbook file cannot embed its own eventual merge commit's SHA (a
commit's hash is computed from a tree that includes this very file's final
content — a self-referential hash is not something to engineer around, it
is simply not writable). The qualified exporter commit for a given R1 event
is therefore established procedurally, not by a hardcoded value in this
document:

1. The PR that last hardened this exporter (operator-artifact immutability
   and secret handling, at the time of writing) records its own merge SHA
   in a closure comment on RAG issue #155 immediately after merging — this
   is the required last step of that PR, not optional follow-up.
2. Before Step 1 below, read that comment and treat its SHA as
   `R1_QUALIFIED_EXPORTER_COMMIT` for this run.
3. If `origin/main` has advanced past that SHA by the time you run this
   runbook, **do not** silently run from the newer commit. Choose one:
   - checkout the exact qualified commit in a clean, disposable worktree
     (`git worktree add /tmp/r1-export <qualified-sha>`) and run every step
     from there; or
   - explicitly requalify the newer commit first: run the full Section 16
     test/gate set (see the PR that introduced this rule) against it,
     record the new SHA in a fresh RAG issue #155 comment, and use that SHA
     as the new `R1_QUALIFIED_EXPORTER_COMMIT` instead.

   Never interpret "later" as equivalent to "qualified".

## Step 0 — restrictive operator shell setup

```bash
umask 077
R1_EVIDENCE_DIR=/secure/path/r1-evidence   # never inside this git repository/worktree
install -d -m 700 "$R1_EVIDENCE_DIR"
```

`umask 077` ensures every file this shell creates from here on defaults to
`0600`/`0700` regardless of the operator's own login umask; the exporter and
verifier CLIs additionally `fchmod(0o600)` every artifact they publish
themselves, so this is defense in depth, not the only control.

The production bootstrap and its evidence report **must never** be written
inside this repository's working tree or any of its worktrees. This
repository holds no production data; a bootstrap or report committed here
by accident is both a leak and a permanent, hard-to-scrub git history
problem. `$R1_EVIDENCE_DIR` above must resolve outside `git rev-parse
--show-toplevel` for this repository.

## Step 1 — verify and pin the repository commit

```bash
cd /path/to/RAG
git fetch origin
git checkout "$R1_QUALIFIED_EXPORTER_COMMIT"   # from "Pinning the exporter commit" above
test "$(git rev-parse HEAD)" = "$R1_QUALIFIED_EXPORTER_COMMIT" || {
  echo "refusing to proceed: not on the qualified exporter commit" >&2
  exit 1
}
git status --porcelain    # must print nothing: no local edits
```

This commit becomes `--producer-commit` in Step 5 and must be the one
attached to the delivered artifact and to the issue #155 evidence comment.
Never substitute a different, unqualified commit here, even one you
personally trust — qualification is what Section 16 of the hardening PR
proved, not a matter of individual judgment at export time.

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
files exist and are internally consistent before using them in Step 6:

```bash
cd services/rag-engine
PROFILE_ROOT=configs/ingestion_profiles/v2_livraison_319
PROFILE_MANIFEST=configs/ingestion_profiles/ingestion_manifest_v2_livraison_319.yml
sha256sum "$PROFILE_MANIFEST"
```

Never trust `$PROFILE_ROOT`/`$PROFILE_MANIFEST` merely because they sit at
this familiar, documented path — Step 6's verifier independently
recomputes every profile's real fingerprint against the sealed release and
refuses a mismatch, so a wrong or tampered directory fails loudly rather
than silently passing.

## Step 4 — read the production DSN without exposing it

Never write the real DSN as a literal `export VAR="postgresql://..."` line
in a terminal — every such line is a shell-history entry containing a
production credential.

```bash
(
  set +x                        # so xtrace can never echo the secret below
  read -r -s -p 'R1 read-only PostgreSQL DSN: ' NEXUS_RESOURCE_EXPORT_DSN
  printf '\n'
  export NEXUS_RESOURCE_EXPORT_DSN

  # --- Step 5 (the exporter run) belongs INSIDE this same subshell ---
  # so the credential exists only for this subshell's lifetime and is
  # never available to any command run after it exits.
)
```

If your environment cannot use a subshell, you must instead run:

```bash
unset NEXUS_RESOURCE_EXPORT_DSN
```

immediately after Step 5 completes, before doing anything else in that
shell. The R1 evidence verifier (Step 6) does not need the DSN and must
never inherit it — run it in a separate shell/subshell that never had the
variable set, not merely one that unset it afterward.

## Step 5 — run the existing governed exporter

Run this **inside** the Step 4 subshell, while `NEXUS_RESOURCE_EXPORT_DSN`
is set:

```bash
cd services/rag-engine
SHORT_SHA="$(git rev-parse --short=12 HEAD)"
BOOTSTRAP_OUT="$R1_EVIDENCE_DIR/resource-registry-bootstrap-production-profile-gate-2026-2027-v1-${SHORT_SHA}.json"

PYTHONPATH=src ./.venv/bin/python scripts/build_resource_registry_bootstrap_inventory_cli.py \
  --producer-commit "$(git rev-parse HEAD)" \
  --generated-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --output "$BOOTSTRAP_OUT" \
  --release-registry-path ../rag-pedago/data/releases/prerentree_2026_2027/release-registry.json \
  --release-registry-sha256 <the digest confirmed in Step 2>
```

Notes:

- The output filename embeds the release id and the qualified exporter's
  short commit SHA so two runs (a failed attempt and a later successful
  one, or two genuinely distinct events) can never collide on one path.
  This does **not** replace the no-clobber guarantee below — both apply.
- `--output` is checked for safety (must not already exist, must not be a
  directory, its parent directory must be usable) **before** any
  connection to PostgreSQL is opened. An existing `$BOOTSTRAP_OUT` fails
  immediately with a non-zero exit and `psycopg.connect` is never called —
  you will never discover an unusable destination only after already
  reaching production.
- The final write is atomic and refuses outright to overwrite an existing
  target (`ingestor.atomic_artifact.publish_atomic_no_clobber`): no partial
  file is ever visible at `$BOOTSTRAP_OUT`, and a second attempt at the
  same exact path always fails rather than silently replacing the first
  artifact — see "If something fails" below for what to do instead of
  retrying in place.
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
  `"duplicate semantic placement"` guard) **stop here**. Do not proceed
  to Step 6 with a partial or hand-edited file. Escalate the exact error
  instead — see "If something fails" below.

## Step 6 — immediately run the R1 evidence verifier

Run this **outside** the Step 4 subshell (or after `unset
NEXUS_RESOURCE_EXPORT_DSN` if you did not use one) — the verifier must
never have production credentials in its environment; it never needs them.

Never skip this step and never treat Step 5's success alone as sufficient —
the exporter proves internal consistency against the DB at read time; the
verifier independently proves the resulting **file** matches the sealed
release (across all 11 canonical dimensions, `audience` included) and the
signed profile authority, with zero trust that Step 5 ran uncorrupted.

```bash
cd services/rag-engine
test -z "${NEXUS_RESOURCE_EXPORT_DSN:-}" || { echo "refusing to run with a DSN still set" >&2; exit 1; }

REPORT_OUT="$R1_EVIDENCE_DIR/r1-evidence-production-profile-gate-2026-2027-v1-${SHORT_SHA}.json"

PYTHONPATH=src ./.venv/bin/python scripts/r1_evidence_verifier_cli.py \
  --bootstrap "$BOOTSTRAP_OUT" \
  --release-registry-path ../rag-pedago/data/releases/prerentree_2026_2027/release-registry.json \
  --release-registry-sha256 <the same digest confirmed in Step 2> \
  --profile-root "$PROFILE_ROOT" \
  --profile-manifest-path "$PROFILE_MANIFEST" \
  --out "$REPORT_OUT"
```

This step never opens a database connection and never mutates anything.
`--out` follows the exact same before-DB-doesn't-apply-but-still-no-clobber
discipline as Step 5's `--output`: an existing `$REPORT_OUT` is refused
before any verification work runs, and a successful report is written
atomically, never overwriting a prior one. Production export must not
proceed unless ALL of these gates in its output read as shown:

```text
R1_PROFILE_MANIFEST_AUTHORITY=PASS
R1_PROFILE_RELEASE_SCOPE_CONSISTENCY=PASS
AUDIENCE_COMPARED_AGAINST_SEALED_AUTHORITY=True
R1_CANONICAL_PLACEMENT_DIMENSIONS=11
```

and finally:

- `R1_EVIDENCE_READY=YES` (exit code 0): every gate passed. Proceed to Step 7.
- `R1_EVIDENCE_READY=NO` (exit code 1) or `R1_EVIDENCE_VERIFIER_ERROR=...`
  (exit code 2): **do not publish the bootstrap.** Read `$REPORT_OUT`'s
  `blockers` array (and, for a scope disagreement, its
  `gates.profile_scope_mismatches`) for the exact reason(s) and escalate —
  see "If something fails" below.

## Step 7 — hash and retain evidence

```bash
sha256sum "$BOOTSTRAP_OUT"
sha256sum "$REPORT_OUT"
```

Retain, alongside the artifacts themselves, in `$R1_EVIDENCE_DIR` (never
committed to this repository, which holds no production data):

- the exact command lines from Steps 5 and 6 (DSN redacted — it was never
  in the command line to begin with, per Step 4),
- their full stdout,
- the two SHA256 sums above,
- the qualified exporter commit recorded in Step 1.

## Step 8 — hand off

Post the evidence (artifact SHA256, `RESOURCE_REGISTRY_BOOTSTRAP_ROWS`,
`R1_EVIDENCE_READY=YES`, `R1_QUALIFIED_EXPORTER_COMMIT`, and the retained
command/output evidence) to RAG issue #155 and notify the Nexus side. This
runbook's job ends here: R1 is a bootstrap-delivery-only phase. A
`ServableCorpusManifest` is not required for R1 completion (R2 is separate,
separately gated, and out of scope for this runbook).

## If something fails: never retry in place

A failed Step 5 or Step 6 must never be "fixed" by editing, overwriting, or
retrying against the same output path — the atomic no-clobber writes above
make that structurally impossible for a *successful* prior artifact, but
discipline still matters for an *unpublished* one too:

- If Step 5 fails before writing `$BOOTSTRAP_OUT` at all: nothing to clean
  up — no partial file is ever left visible. Diagnose, then start a
  genuinely new attempt with a fresh output path (a new `$SHORT_SHA`
  naturally provides this if you re-qualify a new commit; otherwise add
  your own disambiguating suffix).
- If Step 6 reports `R1_EVIDENCE_READY=NO` **after** Step 5 already wrote a
  complete, valid `$BOOTSTRAP_OUT`: do **not** edit or delete that
  bootstrap file. Quarantine it (move it, with its failing evidence report,
  into a clearly labeled `failed/` subdirectory of `$R1_EVIDENCE_DIR`) and
  retain both as diagnostic evidence of what went wrong. Diagnose the exact
  blocker. A subsequent, corrected, authorized attempt writes to a **new**
  distinct target path — it never reuses or replaces the failed one.
- A previously successful, verified (`R1_EVIDENCE_READY=YES`) artifact is
  immutable forever. There is no update path in this runbook. If the sealed
  release or the qualified exporter commit ever genuinely changes, that is
  a new R1 event with its own new output paths, not a re-run of this one.

There is no partial-success path in this runbook.
