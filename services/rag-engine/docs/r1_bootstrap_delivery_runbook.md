# R1 bootstrap delivery runbook

Operator runbook for the one-time governed `ResourceRegistryBootstrap` export
that closes RAG issue #155 (Nexus C05a, R1 phase). This is **not** an
automated pipeline: every step below is run by hand, by a human operator who
holds authorized production database credentials. No step here is executed
by this repository's CI, and none of it should be.

## What changed in R1E, and why

R1D closed the shell subshell variable-continuity bug
(`R1_RUNBOOK_ARTIFACT_VARIABLE_CONTINUITY=FAIL` for the earlier two-separate-
shell-blocks shape, where Phase A's resolved paths failed to survive into a
separate shell block) by having Phase A
print several `KEY=value` lines and having the operator `eval` them into
their shell. That fix removed the *subshell* bug class, but the `eval`
hand-off it introduced is itself unsafe in a different, more fundamental
way: `eval` executes its argument as shell code, so any value containing
shell metacharacters becomes arbitrary command execution in the operator's
own shell, not merely an assigned variable. Reproduced directly:

```console
$ FAKE_OUTPUT='BOOTSTRAP_OUT=/tmp/x; touch /tmp/PWNED'
$ eval "$FAKE_OUTPUT"
$ ls /tmp/PWNED
/tmp/PWNED
```

`R1_RUNBOOK_EVAL_HANDOFF_IS_UNSAFE_FOR_SHELL_METACHARACTERS=CONFIRMED` — a
single semicolon (or backtick, or `$(...)`) in any value Phase A ever prints
would execute as a command the moment the operator's shell evaluates it.
Nothing about R1D's own checks ever constrained what characters could reach
that `eval`; it happened to be safe only because every value R1D printed
was, in practice, already safe-looking. That is not a security property,
it is a coincidence — and this runbook must not depend on one.

The fix, again, is not more careful shell prose: it is removing `eval` from
this runbook entirely, and removing the reason to want it. Phase A now
publishes a single **immutable, atomically-written, no-clobber, `0600`
JSON file** — the attempt state — and prints only its own path. The
operator's shell needs to capture exactly one value (a filesystem path,
never executed as shell code), and Phase B takes exactly one argument,
`--attempt-state`, pointing at that file. Every other fact Phase B needs
(the qualified commit, the sealed release identity and digest, the profile
authority paths, the output paths) is loaded from that file and then
**independently re-verified against the live repository**, never trusted
merely for being present in it — this closes the same TOCTOU window R1D
already had to reason about (state could go stale between Phase A and
Phase B), but now as an explicit, tested revalidation step
(`revalidate_attempt_state_against_live_repo`) rather than an implicit
assumption.

`--release-id`, `--attempt-id`, `--generated-at`, `--producer-commit`,
`--profile-root`, and `--profile-manifest-path` are no longer operator-
supplied CLI arguments anywhere in this flow. Each is derived internally
from the sealed release registry, generated fresh, captured at the moment
of the actual export call, or freshly re-verified against live `git`
state — never accepted as a second, separately-typed fact that could
silently disagree with the sealed or attested truth.

Both phases are covered by their own test suites
(`tests/test_r1_operator_flow.py`, `tests/test_r1_attempt_preflight_cli.py`,
`tests/test_r1_export_and_verify_cli.py`), including an end-to-end test
that runs the real Phase A CLI, then feeds its exact printed attempt-state
path into Phase B, and adversarial tests proving that a checkout change, a
tracked edit, an untracked file, or a tampered attempt-state field between
the two phases all fail closed, before any database connection is ever
opened.

## What changed in R1F, and why

A further audit of the merged R1E flow found the attempt-state hand-off
was correct in its *content* but incomplete in two ways, plus one real bug
in this runbook's own capture pattern.

**The state's internal consistency was checked, but not its *placement*.**
R1E's `_validate_attempt_state_fields` correctly refused a state whose
`bootstrap_out`/`report_out` were not direct children of its own
`evidence_dir`. It never asked whether that `evidence_dir` itself was a
value Phase A would ever have produced. A state entirely self-consistent
with itself — `evidence_dir` redirected inside a repository worktree,
`bootstrap_out`/`report_out` correctly computed as children of that same
(forbidden) directory — passed every R1E check and would have reached the
database. Phase B now re-derives the live worktree list
(`git worktree list --porcelain`) and re-excludes `evidence_dir` from every
one of them, and separately re-derives the canonical output filenames from
the attempt's own (freshly re-verified) release id, commit, and attempt id
— rejecting a state whose `bootstrap_out`/`report_out`, or whose own
on-disk location, do not match. The sealed release-registry path is
likewise re-derived from the qualified checkout and compared to the
state's claim, so a redirected-but-byte-identical copy of the registry
file cannot substitute for the real one.

**Phase A used to create the evidence directory before knowing it was
allowed to.** `mkdir` ran, then preflight ran. A forbidden request (an
evidence directory inside a worktree, say) still left an empty directory
behind. Every preflight gate — including evidence-directory exclusion —
now runs to completion before this process creates anything on disk at
all.

**This runbook's own Step 1 capture pattern could mask a failed Phase A.**
The previous form,

```console
$ R1_ATTEMPT_STATE_PATH=$(phase-a-command | grep '^R1_ATTEMPT_STATE_PATH=' | cut -d= -f2-)
```

captures the exit status of the *last* command in the pipeline (`cut`), not
of `phase-a-command` itself.
`R1_RUNBOOK_CAPTURE_PIPELINE_MASKS_PHASE_A_FAILURE=CONFIRMED` — if Phase A
fails and prints nothing matching that `grep`, `$R1_ATTEMPT_STATE_PATH` is
simply empty and the pipeline as a whole can still report success —
nothing in that line stopped the operator from proceeding straight to
Step 2's credential prompt on a failed Phase A.
Phase A now supports `--print-state-path-only`: on success its stdout is
*exactly* the attempt-state path and nothing else; on failure, stdout is
empty and the process exits non-zero. Step 1 below captures it with plain
command substitution and checks the real exit code directly — no `eval`,
no `grep`, no `cut`, no `source`, and no pipeline to mask a failure behind.

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
   to operator judgment. Phase B re-checks it independently, again, before
   ever opening a database connection.

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
     test/gate set against it, record the new SHA in a fresh RAG issue #155
     comment, and use that SHA instead.

   Never interpret "later" as equivalent to "qualified" — Phase A's own
   commit check enforces this mechanically, and Phase B re-enforces it
   independently a second time; it is not merely a documented expectation.

## Step 0 — restrictive operator shell setup

```bash
umask 077
R1_EVIDENCE_DIR=/secure/path/r1-evidence   # never inside this git repository or any of its worktrees
```

`umask 077` ensures every file this shell creates from here on defaults to
`0600`/`0700` regardless of the operator's own login umask. Phase A creates
`$R1_EVIDENCE_DIR` itself (`mkdir -p` semantics); both CLIs additionally
`fchmod(0o600)` every artifact they publish, so this is defense in depth,
not the only control.

The production bootstrap, its evidence report, and the attempt-state file
itself **must never** be written inside this repository's working tree or
any of its worktrees. Phase A resolves every worktree of this repository
(`git worktree list --porcelain`, not just the one you happen to be
standing in) and refuses to proceed if `$R1_EVIDENCE_DIR` resolves inside
any of them (symlinks included) — this is a mechanical gate, checked before
any credential is ever requested, not merely documented prose.

## Step 1 — Phase A: non-secret preflight and attempt-state publication

```bash
cd /path/to/RAG
git fetch origin
git checkout "$R1_QUALIFIED_EXPORTER_COMMIT"   # from "Pinning the exporter commit" above

cd services/rag-engine
```

The command below is shown first **without** `--print-state-path-only`, run
directly (not captured), purely so you can see what Phase A actually
checks and prints — do not use this exact form for the real attempt, go
straight to the capturing form further down:

```bash
PYTHONPATH=src ./.venv/bin/python scripts/r1_attempt_preflight_cli.py \
  --repo-root /path/to/RAG \
  --qualified-exporter-commit "$R1_QUALIFIED_EXPORTER_COMMIT" \
  --evidence-dir "$R1_EVIDENCE_DIR"
```

Notice what is absent: no `--release-registry-path`, no `--release-id`, no
`--attempt-id`. The sealed release-registry path is derived from
`--repo-root` alone; the release id is read from that sealed registry
itself (and cross-checked against a hardcoded expected digest, not
re-derived from the same file being checked); a fresh attempt id is
generated internally on every invocation. None of these is a fact an
operator can supply, override, or get wrong.

This step never touches PostgreSQL and never requests a credential. On
success it prints:

```text
R1_ATTEMPT_STATE_PATH=<the one file Phase B needs>
R1_ATTEMPT_ID=<a fresh, collision-resistant identity for this governed attempt>
SEALED_RELEASE_ID=<production-profile-gate-2026-2027-v1>
BOOTSTRAP_OUT=<the exact path Phase B will write the bootstrap to>
REPORT_OUT=<the exact path Phase B will write the evidence report to>
R1_PREFLIGHT_READY=YES
```

For the real attempt, run it instead with `--print-state-path-only`, which
makes stdout on success contain nothing but the attempt-state path, and
capture it with plain command substitution while checking the real exit
code directly — never through a pipeline that could mask it:

```bash
if ! R1_ATTEMPT_STATE_PATH="$(
  PYTHONPATH=src ./.venv/bin/python scripts/r1_attempt_preflight_cli.py \
    --repo-root /path/to/RAG \
    --qualified-exporter-commit "$R1_QUALIFIED_EXPORTER_COMMIT" \
    --evidence-dir "$R1_EVIDENCE_DIR" \
    --print-state-path-only
)"; then
  echo "R1 Phase A failed; refusing to request a production credential" >&2
  exit 1
fi

test -n "$R1_ATTEMPT_STATE_PATH" || {
  echo "R1 Phase A returned no attempt state" >&2
  exit 1
}
```

No `eval`. No `grep`. No `cut`. No `source`. The `if ! VAR=$(...); then`
form checks the command substitution's own exit code directly — there is
no intermediate pipeline stage whose own (unrelated) success could mask a
failed Phase A, and no way to reach Step 2's credential prompt on a run
that did not actually succeed.

If Phase A fails, it printed `R1_OPERATOR_FLOW_ERROR=...` to stderr
identifying exactly which precondition failed (wrong commit, dirty
worktree, sealed release-registry digest mismatch, evidence directory
inside a repository worktree, or a runtime-provenance mismatch — see
"Runtime-provenance attestation" below), stdout was empty, and — because
every preflight gate runs before this process creates anything on disk —
nothing was written, not even an empty `$R1_EVIDENCE_DIR`. **Stop and
resolve that condition — do not proceed to Step 2 with a credential prompt
regardless.**

### Runtime-provenance attestation

Git HEAD alone does not prove that the *imported Python code* running this
CLI comes from the checkout at `--repo-root` — an editable install's `.pth`
file can point anywhere on disk, including a sibling checkout that happens
to share this same virtual environment. Phase A additionally attests that
the actually-imported `ingestor` and `nexus_contracts` modules resolve
beneath `--repo-root` itself, and that the installed `nexus-contracts`
package metadata version matches that exact checkout's own
`packages/contracts/pyproject.toml` declared version — not a stale value
left behind by an earlier install. If you see
`R1_OPERATOR_FLOW_ERROR=...nexus-contracts...reinstall...`, your virtual
environment's installed metadata is stale for this checkout: reinstall
(`pip install -e packages/contracts --no-deps`) from `--repo-root` before
retrying, rather than proceeding with a mismatched attestation.

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
    --attempt-state "$R1_ATTEMPT_STATE_PATH"
)
```

This is genuinely **one** executable block: the credential read, its
export, and the entire exporter-then-verifier run all happen inside the
same subshell invocation, in the same command the operator runs. The only
non-secret input this step takes is the attempt-state path already
established in Step 1's parent shell; nothing here relies on any other
variable escaping a subshell, because there is no other variable to carry.

Inside `scripts/r1_export_and_verify_cli.py` itself (one Python process,
not two shell blocks), before any database connection is opened:

1. The attempt-state file is loaded and every field on it is re-validated
   for format — a loaded file is never trusted merely for having the right
   shape.
2. **Every fact the state carries is independently re-verified against the
   live repository, right now** (`revalidate_attempt_state_against_live_repo`):
   the actual git HEAD still matches the state's claimed qualified commit,
   the worktree is still clean, the running interpreter is still bound to
   the qualified checkout, the sealed release-registry digest and release id
   are unchanged since Phase A ran, and neither `$BOOTSTRAP_OUT` nor
   `$REPORT_OUT` already exists. This closes the exact window between Phase
   A and Phase B during which any of those facts could have gone stale —
   whether by a legitimate later checkout, an accidental edit, or a
   tampered attempt-state file. The actual, freshly re-verified HEAD from
   this step — never the state's own claimed value on its own — becomes
   the exporter's `producer_commit`.
3. The governed exporter runs, exactly as before (same
   `export_resource_registry_bootstrap_inventory`, same
   `BootstrapInventoryError` guards, including
   `"conflicting semantic placements share collection"` and `"duplicate
   semantic placement"`), with `generated_at` captured internally at the
   moment of this exact call — never an operator-supplied timestamp.
4. The credential is discarded from this process's own environment
   immediately afterward (`os.environ.pop("NEXUS_RESOURCE_EXPORT_DSN",
   None)`), before the verifier ever runs — a checked fact about this
   process's state (`test_dsn_is_gone_from_environment_before_the_verifier_runs`),
   not merely a true statement about what the verifier happens not to use.
5. The bootstrap is published atomically, no-clobber, `0600`.
6. The R1 evidence verifier runs against the exact bootstrap path this
   same invocation just wrote — never a rediscovered or globbed path.
7. The evidence report is published atomically, no-clobber, `0600`,
   recording this attempt's `attempt_id` alongside the verifier's gates.

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
exit code `2`; or an `R1_OPERATOR_FLOW_ERROR=...` before any database
connection was ever opened, meaning revalidation itself failed) means:
**do not treat the bootstrap as delivered.** Read the report's `blockers`
array (and, for a scope disagreement, its `gates.profile_scope_mismatches`)
and see "If something fails" below.

## Step 3 — hash and retain evidence

The attempt-state file is JSON; parse it as JSON, not with `grep`/`cut`
against a text representation that happens to look regular:

```bash
BOOTSTRAP_OUT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["bootstrap_out"])' "$R1_ATTEMPT_STATE_PATH")
REPORT_OUT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["report_out"])' "$R1_ATTEMPT_STATE_PATH")
sha256sum "$BOOTSTRAP_OUT"
sha256sum "$REPORT_OUT"
```

Retain, in `$R1_EVIDENCE_DIR` (never committed to this repository, which
holds no production data), a record containing at minimum:

```text
R1_ATTEMPT_ID (also recorded inside the evidence report itself)
R1_QUALIFIED_EXPORTER_COMMIT
SEALED_RELEASE_ID (production-profile-gate-2026-2027-v1)
the sealed release-registry digest (inside the attempt-state file)
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

- If Phase A fails: nothing was created at all, not even an empty
  `$R1_EVIDENCE_DIR` — every preflight gate runs to completion before this
  process creates anything on disk. Diagnose the reported precondition, fix
  it, and re-run Phase A — it will mint a fresh `R1_ATTEMPT_ID`, a fresh
  attempt-state file, and fresh output paths automatically.
- If Phase B fails during revalidation (before ever opening a database
  connection): nothing was created. This means some fact has changed since
  Phase A ran — diagnose which one from the `R1_OPERATOR_FLOW_ERROR`
  message, then re-run Phase A for a **new** attempt from the corrected
  state. Never assume the old attempt-state file is still usable once
  anything about the repository has changed underneath it.
- If Phase B fails after revalidation but before writing `$BOOTSTRAP_OUT`
  (a `BootstrapInventoryError`, a connection failure): no partial file is
  ever left visible at `$BOOTSTRAP_OUT`. Diagnose, then re-run Phase A for a
  **new** attempt — never reuse the failed attempt's paths.
- If Phase B reports `R1_EVIDENCE_READY=NO` **after** it already wrote a
  complete, valid `$BOOTSTRAP_OUT`: do **not** edit or delete that
  bootstrap file. Quarantine it (move it, with its evidence report if one
  was written, into a clearly labeled `failed/` subdirectory of
  `$R1_EVIDENCE_DIR`) and retain both as diagnostic evidence. A report may
  legitimately not exist yet if the verifier itself failed to run at all
  (an `R1_EVIDENCE_VERIFIER_ERROR`) — check for its existence before any
  hash/move operation on it. Diagnose the exact blocker, then start a
  genuinely new, authorized attempt.
- A previously successful, verified (`R1_EVIDENCE_READY=YES`) artifact is
  immutable forever. There is no update path in this runbook. If the sealed
  release or the qualified exporter commit ever genuinely changes, that is
  a new R1 event with its own new attempt, not a re-run of this one.

There is no partial-success path in this runbook.
