"""R1C/R1D/R1E — the canonical R1 runbook must never regress on operator
security discipline: not on the R1D fix for the subshell variable-
continuity bug (a real shell semantics bug the R1C runbook demonstrated:
variables assigned inside a subshell do not propagate to its parent), and
not on the R1E fix for the `eval` hand-off R1D introduced while fixing that
(a real shell semantics bug of its own: `eval` executes its argument as
shell code, so any Phase-A-printed value containing shell metacharacters
becomes arbitrary command execution). Deliberately narrow, literal checks
(not a broad credential regex, which would false-positive on this file's
own harmless prose about DSNs) so this test stays meaningful rather than
brittle. These checks cannot themselves prove the underlying mechanics --
that is what ``test_r1_export_and_verify_cli.py``'s end-to-end and TOCTOU
tests prove executably; this file only guards against the runbook's
*prose* regressing back to either broken shape.
"""

from __future__ import annotations

import re
from pathlib import Path

RUNBOOK = Path(__file__).resolve().parents[1] / "docs" / "r1_bootstrap_delivery_runbook.md"

#: The exact shape the runbook must never show again: a real-looking DSN
#: assigned inline to the exporter's DSN variable, which an operator could
#: copy-paste with a real secret filled in, landing it in shell history.
_INLINE_DSN_LITERAL = re.compile(r'NEXUS_RESOURCE_EXPORT_DSN\s*=\s*"postgresql://')

#: The exact shape R1E removed: capturing Phase A's stdout via ``eval``,
#: which would execute any shell metacharacter in a printed value as a
#: command rather than merely assign it to a variable.
_EVAL_HANDOFF = re.compile(r"eval\s+[\"'(]")

_BASH_CODE_BLOCK = re.compile(r"```bash\n(.*?)```", re.DOTALL)


def _text() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def _bash_code_blocks(text: str) -> list[str]:
    """Only the fenced ``bash`` blocks are actual operator instructions --
    a ``console`` block may deliberately illustrate a *wrong* pattern (as
    the eval-unsafety reproduction does) without instructing the operator
    to run it for real."""
    return _BASH_CODE_BLOCK.findall(text)


def test_runbook_file_exists() -> None:
    assert RUNBOOK.is_file()


def test_runbook_never_shows_an_inline_dsn_literal() -> None:
    assert _INLINE_DSN_LITERAL.search(_text()) is None


def test_runbook_requires_disabling_xtrace_before_secret_entry() -> None:
    assert "set +x" in _text()


def test_runbook_requires_a_restrictive_umask() -> None:
    assert "umask 077" in _text()


def test_runbook_requires_pinning_the_qualified_exporter_commit() -> None:
    text = _text()
    assert "R1_QUALIFIED_EXPORTER_COMMIT" in text
    assert "qualified exporter commit" in text


def test_runbook_requires_no_clobber_publication() -> None:
    assert "no-clobber" in _text()


def test_runbook_prohibits_writing_artifacts_inside_the_repository() -> None:
    text = _text().lower()
    assert "must never" in text
    assert "working tree" in text or "worktree" in text


def test_runbook_delegates_to_the_two_tested_operator_flow_scripts() -> None:
    """R1D: the runbook must invoke the tested Phase A/B scripts rather
    than duplicate their orchestration as freestanding shell prose -- the
    exact thing that let the subshell-continuity bug ship undetected."""
    text = _text()
    assert "r1_attempt_preflight_cli.py" in text
    assert "r1_export_and_verify_cli.py" in text


def test_runbook_uses_an_attempt_identity_not_only_release_and_commit() -> None:
    assert "R1_ATTEMPT_ID" in _text()


def test_runbook_documents_the_subshell_continuity_bug_it_fixed() -> None:
    """Not merely fixed silently -- the runbook records the reproduction
    so a future edit does not casually reintroduce the two-shell-blocks
    shape without realizing why it was removed."""
    text = _text()
    assert "R1_RUNBOOK_ARTIFACT_VARIABLE_CONTINUITY" in text
    assert "subshell" in text.lower()


def test_runbook_never_instructs_evaluating_phase_a_output_as_shell_code() -> None:
    """R1E: no actual operator-instruction (``bash``) code block may ``eval``
    Phase A's stdout -- doing so would let any shell metacharacter in a
    printed value execute as a command in the operator's own shell. The
    reproduction of exactly this danger lives in an illustrative
    ``console`` block, which this check deliberately does not scan."""
    for block in _bash_code_blocks(_text()):
        assert _EVAL_HANDOFF.search(block) is None


def test_runbook_documents_the_eval_handoff_bug_it_fixed() -> None:
    """Not merely fixed silently -- the runbook records the reproduction
    so a future edit does not casually reintroduce an ``eval``-based
    hand-off without realizing why it was removed."""
    text = _text()
    assert "R1_RUNBOOK_EVAL_HANDOFF_IS_UNSAFE_FOR_SHELL_METACHARACTERS" in text
    assert "eval" in text.lower()


def test_runbook_hands_off_through_a_single_attempt_state_file() -> None:
    """R1E: Phase A must publish one attempt-state artifact and Phase B
    must accept exactly one non-secret argument pointing at it -- not
    several separately-supplied, potentially-inconsistent facts."""
    text = _text()
    assert "R1_ATTEMPT_STATE_PATH" in text
    assert "--attempt-state" in text


def test_runbook_never_lets_the_operator_supply_governed_facts_as_flags() -> None:
    """R1E: release id, attempt id, generated-at, producer commit, and the
    profile authority paths must never appear as operator-supplied CLI
    flags in any actual operator-instruction (``bash``) code block in this
    runbook -- each is derived, generated, or captured internally instead.
    Prose explaining that a flag is *no longer accepted* is fine and is
    exactly what this runbook's own "What changed" section says."""
    blocks = _bash_code_blocks(_text())
    for forbidden_flag in (
        "--release-id",
        "--attempt-id",
        "--generated-at",
        "--producer-commit",
        "--profile-root",
        "--profile-manifest-path",
        "--release-registry-path",
    ):
        assert not any(forbidden_flag in block for block in blocks), (
            f"{forbidden_flag} must not appear in an operator-instruction code block"
        )


def test_runbook_documents_revalidation_against_the_live_repository() -> None:
    """R1E: Phase B's TOCTOU closure -- re-verifying every fact against the
    live repository before ever opening a database connection -- must be
    documented, not merely implemented silently."""
    text = _text()
    assert "revalidate_attempt_state_against_live_repo" in text
    assert "before any database connection" in text.lower() or "before ever opening a database" in text.lower()
