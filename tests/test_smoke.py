"""Smoke tests limited to repository-level validation tooling."""

from __future__ import annotations

from pathlib import Path
import socket

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_root_regression_entrypoints_are_versioned() -> None:
    """The repository exposes the deterministic regression entrypoints."""
    for relative_path in (
        "Makefile",
        "pytest.ini",
        "scripts/tests/full-regression.sh",
        "scripts/tests/check-zombies-and-duplicates.sh",
    ):
        assert (REPO_ROOT / relative_path).is_file(), relative_path


def test_root_never_contains_lot_manifest_or_archive() -> None:
    """Release artifacts must live outside the repository root."""
    forbidden = [
        path.name
        for path in REPO_ROOT.iterdir()
        if path.is_file() and (path.match("MANIFEST_LOT*.md") or path.name.endswith(".tar.gz"))
    ]
    assert forbidden == []


def test_unit_tests_cannot_open_socket() -> None:
    """The hermetic test fixture rejects accidental network access."""
    with pytest.raises(RuntimeError, match="réseau interdit"):
        socket.socket()


def test_full_regression_never_installs_javascript_dependencies() -> None:
    """The hermetic gate must not perform a network-capable npm install."""
    clean_build = (
        REPO_ROOT / "scripts/tests/test-cockpit-clean-build.sh"
    ).read_text(encoding="utf-8")
    assert "npm ci" not in clean_build
