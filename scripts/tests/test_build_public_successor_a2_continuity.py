"""L'écriture du pack A2 doit refuser un chemin ambigu ou divergent."""

from __future__ import annotations

from pathlib import Path

import pytest
from build_public_successor_a2_continuity import write_output_pair
from nexus_release_chain.public_successor_temporal import PublicSuccessorTemporalError


def test_report_is_written_before_authority_and_is_idempotent(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    authority = tmp_path / "authority.json"
    write_output_pair(authority, b"authority\n", report, b"report\n")
    assert authority.read_bytes() == b"authority\n"
    assert report.read_bytes() == b"report\n"
    write_output_pair(authority, b"authority\n", report, b"report\n")
    assert authority.stat().st_mode & 0o777 == 0o600


def test_refuses_symlink_or_divergent_report_without_partial_authority(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    authority = tmp_path / "authority.json"
    report.write_bytes(b"other")
    with pytest.raises(PublicSuccessorTemporalError):
        write_output_pair(authority, b"authority\n", report, b"report\n")
    assert not authority.exists()
    report.unlink()
    target = tmp_path / "target"
    target.write_bytes(b"other")
    report.symlink_to(target)
    with pytest.raises(PublicSuccessorTemporalError):
        write_output_pair(authority, b"authority\n", report, b"report\n")
    assert not authority.exists()
