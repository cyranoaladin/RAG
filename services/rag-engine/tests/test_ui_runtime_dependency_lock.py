"""Contract checks for the pinned Streamlit UI runtime image."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parents[1]
COMPOSE_PATH = ENGINE_ROOT / "infra" / "docker-compose.v2.yml"
DOCKERFILE_PATH = ENGINE_ROOT / "src" / "ui" / "Dockerfile"
LOCK_PATH = ENGINE_ROOT / "requirements.lock"
SMOKE_PATH = REPO_ROOT / "scripts" / "e2e" / "smoke-ui-runtime-imports.sh"
DOCKERIGNORE_PATH = REPO_ROOT / ".dockerignore"

EXPECTED_LOCKS = {
    "streamlit": "1.39.0",
    "pyarrow": "24.0.0",
    "pandas": "2.2.3",
    "numpy": "1.26.4",
    "protobuf": "5.29.6",
    "tornado": "6.5.7",
    "watchdog": "5.0.3",
}


def test_ui_build_context_can_copy_the_central_lock() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    build = compose["services"]["ui"]["build"]

    assert build["context"] == "../../.."
    assert build["dockerfile"] == "services/rag-engine/src/ui/Dockerfile"


def test_ui_dockerfile_installs_requirements_with_central_lock() -> None:
    content = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "services/rag-engine/requirements.lock" in content
    assert "services/rag-engine/src/ui/requirements.txt" in content
    assert "scripts/e2e/smoke-ui-runtime-imports.sh" in content
    assert "-c /tmp/requirements.lock" in content
    assert "python -m pip check" in content


def test_docker_context_keeps_all_ui_build_inputs() -> None:
    content = DOCKERIGNORE_PATH.read_text(encoding="utf-8")

    assert "!services/rag-engine/requirements.lock" in content
    assert "!services/rag-engine/src/ui/**" in content
    assert "!scripts/e2e/smoke-ui-runtime-imports.sh" in content


def test_ui_runtime_lock_contains_exact_validated_versions() -> None:
    versions = {}
    for line in LOCK_PATH.read_text(encoding="utf-8").splitlines():
        if "==" in line:
            name, version = line.split("==", 1)
            versions[name] = version

    for package, expected in EXPECTED_LOCKS.items():
        assert versions.get(package) == expected


def test_runtime_smoke_exists_and_checks_native_dependencies() -> None:
    assert SMOKE_PATH.is_file()
    assert os.access(SMOKE_PATH, os.X_OK)
    content = SMOKE_PATH.read_text(encoding="utf-8")

    assert "UI_RUNTIME_IMPORTS_OK" in content
    assert '"pyarrow": "24.0.0"' in content
    assert '"numpy": "1.26.4"' in content
    assert "import pyarrow" in content
    assert "import numpy" in content


def test_ui_runtime_lock_change_does_not_modify_v2_routes() -> None:
    app_v2 = (ENGINE_ROOT / "src" / "ui" / "app_v2.py").read_text(encoding="utf-8")

    for route in (
        "/catalogue/v2",
        "/collections/v2",
        "/search/v2",
        "/ingest/v2/upload-files",
        "/ingest/v2/urls",
    ):
        assert route in app_v2
