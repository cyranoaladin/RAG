"""R1C/R1D — the canonical R1 runbook must never regress on operator
security discipline, nor on the R1D fix for the subshell variable-
continuity bug (a real shell semantics bug the R1C runbook demonstrated:
variables assigned inside a subshell do not propagate to its parent).
Deliberately narrow, literal checks (not a broad credential regex, which
would false-positive on this file's own harmless prose about DSNs) so this
test stays meaningful rather than brittle. These checks cannot themselves
prove shell continuity -- that is what
``test_r1_export_and_verify_cli.py::test_phase_a_paths_survive_into_phase_b_without_any_shell_subshell``
proves executably; this file only guards against the runbook's *prose*
regressing back to the old, broken two-separate-shell-blocks shape.
"""

from __future__ import annotations

import re
from pathlib import Path

RUNBOOK = Path(__file__).resolve().parents[1] / "docs" / "r1_bootstrap_delivery_runbook.md"

#: The exact shape the runbook must never show again: a real-looking DSN
#: assigned inline to the exporter's DSN variable, which an operator could
#: copy-paste with a real secret filled in, landing it in shell history.
_INLINE_DSN_LITERAL = re.compile(r'NEXUS_RESOURCE_EXPORT_DSN\s*=\s*"postgresql://')


def _text() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


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
