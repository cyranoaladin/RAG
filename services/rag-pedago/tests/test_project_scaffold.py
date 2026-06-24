from __future__ import annotations

import importlib.util
import pathlib
import tomllib


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_required_scaffold_paths_exist() -> None:
    expected_files = [
        "AGENTS.md",
        "README.md",
        "pyproject.toml",
        ".env.example",
        ".gitignore",
        "Makefile",
        "docs/LEGACY_RAG_READONLY.md",
        "scripts/doctor.py",
    ]
    expected_dirs = [
        "configs",
        "docs",
        "schema",
        "taxonomy",
        "data/raw",
        "data/normalized",
        "data/extracted_assets",
        "data/manifests",
        "data/quarantine",
        "data/reports",
        "pipeline",
        "retrieval",
        "services/api",
        "services/workers",
        "services/mcp",
        "tests",
        "scripts",
        "ops/systemd",
        "ops/cron",
        "ops/backup",
        "ops/monitoring",
        "ops/runbooks",
        "ops/ci",
    ]

    missing_files = [path for path in expected_files if not (ROOT / path).is_file()]
    missing_dirs = [path for path in expected_dirs if not (ROOT / path).is_dir()]

    assert missing_files == []
    assert missing_dirs == []


def test_pyproject_declares_project_and_dev_tools() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["name"] == "nexus-rag-pedago"
    assert pyproject["project"]["requires-python"] == ">=3.11"
    assert "pytest" in pyproject["project"]["optional-dependencies"]["dev"]
    assert "ruff" in pyproject["project"]["optional-dependencies"]["dev"]


def test_doctor_script_is_importable() -> None:
    doctor_path = ROOT / "scripts" / "doctor.py"
    spec = importlib.util.spec_from_file_location("doctor", doctor_path)

    assert spec is not None
    assert spec.loader is not None
