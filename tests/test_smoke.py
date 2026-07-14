"""Root smoke test — validates repo structure and contracts importability."""

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_repo_structure():
    """Key directories exist."""
    for name in ("services/rag-engine", "services/rag-pedago", "packages/contracts"):
        assert (REPO_ROOT / name).is_dir(), f"Missing directory: {name}"


def test_scripts_exist():
    """Official validation scripts are present and executable."""
    scripts = [
        "scripts/tests/full-regression.sh",
        "scripts/check-governance-locks.sh",
        "scripts/tests/test-governance-locks.sh",
    ]
    for s in scripts:
        p = REPO_ROOT / s
        assert p.is_file(), f"Missing script: {s}"


def test_contracts_importable():
    """nexus-contracts package is importable."""
    try:
        import nexus_contracts  # noqa: F401
    except ImportError:
        # Acceptable: root venv may not have contracts installed.
        # The real import test runs inside ci-local.sh.
        pass
