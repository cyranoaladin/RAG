from __future__ import annotations

import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "AGENTS.md",
    "README.md",
    "pyproject.toml",
    ".env.example",
    ".gitignore",
    "Makefile",
    "docs/LEGACY_RAG_READONLY.md",
]

REQUIRED_DIRS = [
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

FORBIDDEN_FILES = [
    ".env",
    "gdrive-sa.json",
    "creds/gdrive-sa.json",
]


def main() -> int:
    missing_files = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
    missing_dirs = [path for path in REQUIRED_DIRS if not (ROOT / path).is_dir()]
    forbidden_present = [path for path in FORBIDDEN_FILES if (ROOT / path).exists()]

    if missing_files or missing_dirs or forbidden_present:
        if missing_files:
            print("Missing files:")
            for path in missing_files:
                print(f"- {path}")
        if missing_dirs:
            print("Missing directories:")
            for path in missing_dirs:
                print(f"- {path}")
        if forbidden_present:
            print("Forbidden local secrets or production files:")
            for path in forbidden_present:
                print(f"- {path}")
        return 1

    print("doctor: OK - socle local présent, aucun secret interdit détecté")
    return 0


if __name__ == "__main__":
    sys.exit(main())

