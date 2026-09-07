# R1 bootstrap delivery runbook

Operator runbook for the one-time governed `ResourceRegistryBootstrap` export
that closes RAG issue #155 (Nexus C05a, R1 phase). This is **not** an
automated pipeline: every step below is run by hand, by a human operator who
holds authorized production database credentials. No step here is executed
by this repository's CI, and none of it should be.

## What changed in R1D, and why

Earlier revisions of this runbook demonstrated the exporter run and the
credential entry as one shell subshell, then referenced the paths it
computed (`$SHORT_SHA`, `$BOOTSTRAP_OUT`) from a *separate* shell block for
the verifier step. That is not valid shell semantics: a subshell's variable
assignments never propagate back to its parent shell. Reproduced directly:

```console
$ (
>     SHORT_SHA="abc123"
>     BOOTSTRAP_OUT="/tmp/bootstrap-${SHORT_SHA}.json"
>     echo "inside subshell: BOOTSTRAP_OUT=$BOOTSTRAP_OUT"
> )
inside subshell: BOOTSTRAP_OUT=/tmp/bootstrap-abc123.json
$ echo "outside subshell: BOOTSTRAP_OUT=${BOOTSTRAP_OUT:-<unset>}"
outside subshell: BOOTSTRAP_OUT=<unset>
```

`R1_RUNBOOK_ARTIFACT_VARIABLE_CONTINUITY=FAIL` for that flow — an operator
following it verbatim would have hit an unbound variable at the verifier
step, not a subtle silent bug, but still real breakage in a governed
procedure that must work exactly as written.

The fix is not more careful shell prose: it is removing the class of bug
entirely. This runbook now delegates to two small, tested Python programs
instead of hand-copy-pasted shell blocks:

- **Phase A** (`r1_attempt_preflight_cli.py`) — every non-secret check
  (qualified commit, clean worktree, sealed release-registry digest,
  evidence directory outside the repository) plus resolving this attempt's
  identity and output paths. Runs in the operator's ordinary shell, prints
  the resolved paths, never touches a credential.
- **Phase B** (`r1_export_and_verify_cli.py`) — the one step that ever
  opens a database connection: runs the governed exporter, discards the
  credential from its own process immediately afterward, then runs the R1
  evidence verifier against the exact bootstrap path Phase A resolved.
  Because both the exporter and the verifier run in the same Python
  process, there is no subshell boundary between them for state to fail to
  cross — the bug class above cannot recur here by construction, not
  merely by careful editing.

Both are covered by their own test suites
(`tests/test_r1_operator_flow.py`, `tests/test_r1_attempt_preflight_cli.py`,
`tests/test_r1_export_and_verify_cli.py`), including an end-to-end test
that runs Phase A then feeds its exact printed paths into Phase B, proving
the continuity this runbook depends on rather than merely asserting it in
prose.

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
   never log it, and never let it reach shell history (Step 2 below).
2. `services/rag-engine`'s Python environment is provisioned (`.venv` per
   `Makefile`'s `install` target) on the machine you run this from.
3. You are on the **exact qualified exporter commit** for this R1 event —
   see "Pinning the exporter commit" below. Phase A refuses to proceed on
   any other commit; this precondition is enforced mechanically, not left
   to operator judgment.

## Pinning the exporter commit

This runbook file cannot embed its own eventual merge commit's SHA (a
commit's hash is computed from a tree that includes this very file's final
content — a self-referential hash is not something to engineer around, it
is simply not writable). The qualified exporter commit for a given R1 event
is therefore established procedurally:

1. The PR that last hardened this exporter records its own merge SHA in a
   closure comment on RAG issue #155 immediately after merging — the
   required last step of that PR, not optional follow-up. All historical
   qualification comments are kept; the most recent one is authoritative.
2. Before Step 1 below, read that comment and use its SHA as
   `R1_QUALIFIED_EXPORTER_COMMIT` for this run.
3. If `origin/main` has advanced past that SHA by the time you run this
   runbook, **do not** silently run from the newer commit. Choose one:
   - checkout the exact qualified commit in a clean, disposable worktree
     (`git worktree add /tmp/r1-export <qualified-sha>`) and run every step
     from there; or
   - explicitly requalify the newer commit first: run the full relevant
     test/gate set against it (Section 16 of the PR that introduced this
     rule), record the new SHA in a fresh RAG issue #155 comment, and use
     that SHA instead.

   Never interpret "later" as equivalent to "qualified" — Phase A's own
   commit check enforces this mechanically; it is not merely a documented
   expectation.

## Step 0 — restrictive operator shell setup

```bash
umask 077
R1_EVIDENCE_DIR=/secure/path/r1-evidence   # never inside this git repository/worktree
```

`umask 077` ensures every file this shell creates from here on defaults to
`0600`/`0700` regardless of the operator's own login umask. Phase A creates
`$R1_EVIDENCE_DIR` itself (`mkdir -p` semantics); both CLIs additionally
`fchmod(0o600)` every artifact they publish, so this is defense in depth,
not the only control.

The production bootstrap and its evidence report **must never** be written
inside this repository's working tree or any of its worktrees. Phase A
refuses to proceed if `$R1_EVIDENCE_DIR` resolves inside the repository
(symlinks included) — this is a mechanical gate, checked before any
credential is ever requested, not merely documented prose.

## Step 1 — Phase A: non-secret preflight and attempt resolution

```bash
cd /path/to/RAG
git fetch origin
git checkout "$R1_QUALIFIED_EXPORTER_COMMIT"   # from "Pinning the exporter commit" above

cd services/rag-engine
RELEASE_REGISTRY=../rag-pedago/data/releases/prerentree_2026_2027/release-registry.json

PYTHONPATH=src ./.venv/bin/python scripts/r1_attempt_preflight_cli.py \
  --repo-root /path/to/RAG \
  --qualified-exporter-commit "$R1_QUALIFIED_EXPORTER_COMMIT" \
  --release-registry-path "$RELEASE_REGISTRY" \
  --release-id production-profile-gate-2026-2027-v1 \
  --evidence-dir "$R1_EVIDENCE_DIR"
```

This step never touches PostgreSQL and never requests a credential. On
success it prints, and you must capture into this same (non-secret) shell:

```text
R1_ATTEMPT_ID=<a fresh, collision-resistant identity for this governed attempt>
SHORT_SHA=<qualified commit, short form>
BOOTSTRAP_OUT=<the exact path Phase B must write the bootstrap to>
REPORT_OUT=<the exact path Phase B must write the evidence report to>
R1_PREFLIGHT_READY=YES
```

Capture them, e.g.:

```bash
eval "$(PYTHONPATH=src ./.venv/bin/python scripts/r1_attempt_preflight_cli.py \
  --repo-root /path/to/RAG \
  --qualified-exporter-commit "$R1_QUALIFIED_EXPORTER_COMMIT" \
  --release-registry-path "$RELEASE_REGISTRY" \
  --release-id production-profile-gate-2026-2027-v1 \
  --evidence-dir "$R1_EVIDENCE_DIR" | grep -v READY)"
```

If Phase A exits non-zero, it printed `R1_OPERATOR_FLOW_ERROR=...` to
stderr identifying exactly which precondition failed (wrong commit, dirty
worktree, release-registry digest mismatch, or evidence directory inside
the repository). **Stop and resolve that condition — do not proceed to
Step 2 with a credential prompt regardless.**

The release-registry digest Phase A checks is compared against an
independent, hardcoded expected value
(`ingestor.r1_operator_flow.EXPECTED_SEALED_RELEASE_REGISTRY_SHA256`,
currently `c9a844d4d2cc15caf9694b24ac53e77d65d50608d8a0daaef4963183d7d374fa`)
— never a digest freshly computed from the same file being checked, which
would always trivially match and prove nothing.

`$BOOTSTRAP_OUT`/`$REPORT_OUT`/`$SHORT_SHA`/`$R1_ATTEMPT_ID` are now
ordinary variables in your current, non-secret shell. They survive into
Step 2 and Step 3 because nothing here ever entered a subshell to lose them
in.

## Step 2 — Phase B: the one credential-handling step

Never write the real DSN as a literal `export VAR="postgresql://..."` line
in a terminal — every such line is a shell-history entry containing a
production credential.

```bash
(
  set +x                        # so xtrace can never echo the secret below
  read -r -s -p 'R1 read-only PostgreSQL DSN: ' NEXUS_RESOURCE_EXPORT_DSN
  printf '\n'
  export NEXUS_RESOURCE_EXPORT_DSN

  PYTHONPATH=src ./.venv/bin/python scripts/r1_export_and_verify_cli.py \
    --producer-commit "$R1_QUALIFIED_EXPORTER_COMMIT" \
    --generated-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --bootstrap-out "$BOOTSTRAP_OUT" \
    --report-out "$REPORT_OUT" \
    --release-registry-path "$RELEASE_REGISTRY" \
    --profile-root configs/ingestion_profiles/v2_livraison_319 \
    --profile-manifest-path configs/ingestion_profiles/ingestion_manifest_v2_livraison_319.yml
)
```

This is now genuinely **one** executable block: the credential read, its
export, and the entire exporter-then-verifier run all happen inside the
same subshell invocation, in the same command the operator runs. There is
no second code block to splice in afterward, and nothing here relies on
any variable escaping this subshell — `$BOOTSTRAP_OUT`/`$REPORT_OUT`/
`$SHORT_SHA`/`$R1_ATTEMPT_ID` were already established in Step 1's parent
shell and are merely read here, not assigned.

Inside `scripts/r1_export_and_verify_cli.py` itself (one Python process,
not two shell blocks):

1. `--bootstrap-out`/`--report-out` are checked for safety (not already
   present, not a directory, parent directory usable) **before** any
   connection to PostgreSQL is opened.
2. The governed exporter runs, exactly as before (same
   `export_resource_registry_bootstrap_inventory`, same
   `BootstrapInventoryError` guards, including
   `"conflicting semantic placements share collection"` and `"duplicate
   semantic placement"`).
3. The credential is discarded from this process's own environment
   immediately afterward (`os.environ.pop("NEXUS_RESOURCE_EXPORT_DSN",
   None)`), before the verifier ever runs — a checked fact about this
   process's state (`test_dsn_is_gone_from_environment_before_the_verifier_runs`),
   not merely a true statement about what the verifier happens not to use.
4. The bootstrap is published atomically, no-clobber, `0600`.
5. The R1 evidence verifier runs against the exact `$BOOTSTRAP_OUT` this
   same invocation just wrote — never a rediscovered or globbed path.
6. The evidence report is published atomically, no-clobber, `0600`, to the
   exact `$REPORT_OUT` from Step 1.

If your environment truly cannot use a subshell, at minimum run:

```bash
unset NEXUS_RESOURCE_EXPORT_DSN
```

immediately after this command completes, in whatever shell you ran it in.

Production export must not proceed unless the printed report includes ALL
of:

```text
R1_PROFILE_MANIFEST_AUTHORITY=PASS
R1_PROFILE_RELEASE_SCOPE_CONSISTENCY=PASS
AUDIENCE_COMPARED_AGAINST_SEALED_AUTHORITY=True
R1_CANONICAL_PLACEMENT_DIMENSIONS=11
```

and finally `R1_EVIDENCE_READY=YES` (exit code `0`). Any other outcome
(`R1_EVIDENCE_READY=NO`, exit code `1`; or `R1_EVIDENCE_VERIFIER_ERROR=...`,
exit code `2`) means: **do not treat the bootstrap as delivered.** Read
`$REPORT_OUT`'s `blockers` array (and, for a scope disagreement, its
`gates.profile_scope_mismatches`) and see "If something fails" below.

## Step 3 — hash and retain evidence

```bash
sha256sum "$BOOTSTRAP_OUT"
sha256sum "$REPORT_OUT"
```

Retain, in `$R1_EVIDENCE_DIR` (never committed to this repository, which
holds no production data), a record containing at minimum:

```text
R1_ATTEMPT_ID
R1_QUALIFIED_EXPORTER_COMMIT
SEALED_RELEASE_ID (production-profile-gate-2026-2027-v1)
SEALED_RELEASE_AUTHORITY_SHA (the release-registry.json digest from Step 1)
basename of $BOOTSTRAP_OUT
basename of $REPORT_OUT
the bootstrap's own generated_at (printed by Phase B)
the two SHA256 sums above
```

Never the DSN, never a host/password fragment, never any credential
material — none of it was ever in this shell's command line or history to
begin with.

## Step 4 — hand off

Post the evidence (`RESOURCE_REGISTRY_BOOTSTRAP_SHA256`,
`RESOURCE_REGISTRY_BOOTSTRAP_ROWS`, `R1_EVIDENCE_READY=YES`,
`R1_ATTEMPT_ID`, `R1_QUALIFIED_EXPORTER_COMMIT`, and the retained
command/output evidence) to RAG issue #155 and notify the Nexus side. This
runbook's job ends here: R1 is a bootstrap-delivery-only phase. A
`ServableCorpusManifest` is not required for R1 completion (R2 is separate,
separately gated, and out of scope for this runbook).

## If something fails: never retry in place

- If Phase A fails: nothing was created except possibly the (empty, until
  a successful run) `$R1_EVIDENCE_DIR` itself. Diagnose the reported
  precondition, fix it, and re-run Phase A — it will mint a fresh
  `R1_ATTEMPT_ID` and fresh paths automatically unless you pass
  `--attempt-id` explicitly.
- If Phase B fails before writing `$BOOTSTRAP_OUT` (a `BootstrapInventoryError`,
  a connection failure): no partial file is ever left visible at
  `$BOOTSTRAP_OUT`. Diagnose, then re-run Phase A for a **new**
  `R1_ATTEMPT_ID` and fresh paths — never reuse the failed attempt's paths.
- If Phase B reports `R1_EVIDENCE_READY=NO` **after** it already wrote a
  complete, valid `$BOOTSTRAP_OUT`: do **not** edit or delete that
  bootstrap file. Quarantine it (move it, with its evidence report if one
  was written, into a clearly labeled `failed/` subdirectory of
  `$R1_EVIDENCE_DIR`) and retain both as diagnostic evidence. A report may
  legitimately not exist yet if the verifier itself failed to run at all
  (an `R1_EVIDENCE_VERIFIER_ERROR`) — check for its existence before any
  hash/move operation on it. Diagnose the exact blocker, then start a
  genuinely new, authorized attempt with a fresh `R1_ATTEMPT_ID`.
- A previously successful, verified (`R1_EVIDENCE_READY=YES`) artifact is
  immutable forever. There is no update path in this runbook. If the sealed
  release or the qualified exporter commit ever genuinely changes, that is
  a new R1 event with its own new attempt, not a re-run of this one.

There is no partial-success path in this runbook.
