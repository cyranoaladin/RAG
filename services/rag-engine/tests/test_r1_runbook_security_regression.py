"""R1C — the canonical R1 runbook must never regress on operator security
discipline. Deliberately narrow, literal checks (not a broad credential
regex, which would false-positive on this file's own harmless prose about
DSNs) so this test stays meaningful rather than brittle.
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
