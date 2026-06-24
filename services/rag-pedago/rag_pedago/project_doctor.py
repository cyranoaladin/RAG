from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_FILES = [
    "README.md",
    "AGENTS.md",
    "docs/ARCHITECTURE.md",
    "docs/WORKFLOWS.md",
    "docs/LOT_STATUS.md",
    "docs/contracts/pipeline_contract.yml",
    "docs/contracts/runtime_artifacts.yml",
    "docs/contracts/commands.yml",
    "docs/contracts/invariants.yml",
]

REQUIRED_GITIGNORE_PATTERNS = [
    "data/ledger/**",
    "data/reports/manifest_import_*.md",
    "data/reports/manifest_directory_import_*.md",
    "data/reports/readiness_*.md",
    "data/reports/coverage_*.md",
    "data/reports/gate_*.md",
    "data/reports/controlled_import_*.md",
    "data/reports/review_package_*.md",
    "data/reviews/review_*.json",
    "data/reviews/review_registry.jsonl",
]

SECRET_PATTERNS = [
    "OPENAI_API_KEY",
    "QDRANT_URL",
    "POSTGRES_URL",
]

NETWORK_IMPORT_PATTERNS = [
    re.compile(r"^\s*import\s+requests\b", re.MULTILINE),
    re.compile(r"^\s*import\s+httpx\b", re.MULTILINE),
    re.compile(r"^\s*import\s+urllib\.request\b", re.MULTILINE),
    re.compile(r"^\s*from\s+urllib\.request\s+import\b", re.MULTILINE),
    re.compile(r"\burlopen\s*\("),
]

SOURCE_URI_OPEN_PATTERNS = [
    re.compile(r"\bopen\s*\(\s*source_uri\b"),
    re.compile(r"\bopen\s*\(\s*meta\.source_uri\b"),
    re.compile(r"\bPath\s*\(\s*source_uri\b"),
    re.compile(r"\bPath\s*\(\s*meta\.source_uri\b"),
]


@dataclass
class ProjectDoctorResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _tracked_files(root: Path) -> list[Path]:
    try:
        output = subprocess.check_output(
            ["git", "-C", str(root), "ls-files"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [path.relative_to(root) for path in root.rglob("*") if path.is_file()]
    return [Path(line) for line in output.splitlines() if line]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""


def run_project_doctor(root: Path | None = None) -> ProjectDoctorResult:
    root = (root or Path.cwd()).resolve()
    errors: list[str] = []
    warnings: list[str] = []

    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            errors.append(f"missing required file: {relative}")

    gitignore_path = root / ".gitignore"
    if not gitignore_path.is_file():
        errors.append("missing required file: .gitignore")
        gitignore = ""
    else:
        gitignore = gitignore_path.read_text(encoding="utf-8")
        for pattern in REQUIRED_GITIGNORE_PATTERNS:
            if pattern not in gitignore:
                errors.append(f".gitignore missing runtime pattern: {pattern}")

    tracked = _tracked_files(root)
    tracked_env = [str(path) for path in tracked if path.name.startswith(".env") and path.name != ".env.example"]
    if tracked_env:
        errors.append(f"tracked env files are forbidden: {', '.join(sorted(tracked_env))}")

    for relative in tracked:
        if (
            relative == Path(".env.example")
            or relative == Path("rag_pedago/project_doctor.py")
            or relative.parts[:1] == ("docs",)
        ):
            continue
        text = _read_text(root / relative)
        for pattern in SECRET_PATTERNS:
            if pattern in text:
                errors.append(f"potential secret/config token outside docs/examples: {relative}: {pattern}")

    imports_dir = root / "rag_pedago" / "imports"
    if imports_dir.is_dir():
        for path in imports_dir.rglob("*.py"):
            text = _read_text(path)
            for pattern in NETWORK_IMPORT_PATTERNS:
                if pattern.search(text):
                    errors.append(f"network import forbidden in imports module: {path.relative_to(root)}")
            for pattern in SOURCE_URI_OPEN_PATTERNS:
                if pattern.search(text):
                    errors.append(f"source_uri opening pattern forbidden: {path.relative_to(root)}")
    else:
        warnings.append("imports directory not found")

    return ProjectDoctorResult(ok=not errors, errors=errors, warnings=warnings)


def main() -> int:
    result = run_project_doctor(Path.cwd())
    for warning in result.warnings:
        print(f"project-doctor warning: {warning}")
    if not result.ok:
        for error in result.errors:
            print(f"project-doctor error: {error}")
        return 1
    print("project-doctor: OK - documentation, contracts and invariants verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
