from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from rag_pedago.paths import REPO_ROOT

CONFIG = REPO_ROOT / "configs/pilot_corpus_scope.yml"
SAFETY_CONFIG = REPO_ROOT / "configs/make_target_safety.yml"
PROTOCOL_DOC = REPO_ROOT / "docs/PILOT_CORPUS_SCOPE_PROTOCOL.md"
SCRIPT = REPO_ROOT / "scripts/pilot_corpus_scope_audit.py"
MAKEFILE = REPO_ROOT / "Makefile"
DATA_STAGING = REPO_ROOT / "data/staging"
DANGEROUS_FLAGS = [
    "real_documents_allowed",
    "pdf_allowed",
    "docx_allowed",
    "pptx_allowed",
    "xlsx_allowed",
    "ingestion_allowed",
    "parsing_allowed",
    "chunking_allowed",
    "embeddings_allowed",
    "qdrant_allowed",
    "network_allowed",
    "data_staging_allowed",
]


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("pilot_corpus_scope_audit", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git_status() -> str:
    return subprocess.check_output(
        ["git", "status", "--short", "--branch"],
        cwd=REPO_ROOT,
        text=True,
    )


def _write_config(tmp_path: Path, **overrides: object) -> Path:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    for key, value in overrides.items():
        if value is None:
            config.pop(key)
        else:
            config[key] = value
    path = tmp_path / "pilot_corpus_scope.yml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _write_raw_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "pilot_corpus_scope.yml"
    path.write_text(content, encoding="utf-8")
    return path


def _run_cli(*, optimized: bool = False, config: Path = CONFIG) -> subprocess.CompletedProcess[str]:
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend(["scripts/pilot_corpus_scope_audit.py", "--config", str(config)])
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_pilot_corpus_scope_artifacts_exist() -> None:
    assert PROTOCOL_DOC.is_file()
    assert CONFIG.is_file()
    assert SCRIPT.is_file()


def test_pilot_corpus_scope_make_target_exists_and_is_safe_metadata_only() -> None:
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    safety_config = yaml.safe_load(SAFETY_CONFIG.read_text(encoding="utf-8"))

    assert "pilot-corpus-scope-audit:" in makefile_text
    assert "$(PY) scripts/pilot_corpus_scope_audit.py" in makefile_text
    assert "pilot-corpus-scope-audit" in safety_config["SAFE_METADATA_ONLY"]


def test_pilot_corpus_scope_script_has_no_destructive_network_or_process_tokens() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden_tokens = [
        "subprocess",
        "requests",
        "httpx",
        "urllib",
        "socket",
        "unlink(",
        "remove(",
        "rmdir(",
        "shutil.rmtree",
        "shutil.move",
    ]
    assert not any(token in text for token in forbidden_tokens)


def test_pilot_corpus_scope_audit_returns_markdown(capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()

    status = module.main([])

    output = capsys.readouterr().out
    assert status == 0
    assert "# Pilot corpus scope audit" in output
    assert "status: metadata_only_scope" in output
    assert "scope_ready_for_review: true" in output
    assert "real_documents_allowed: false" in output
    assert "ingestion_allowed: false" in output
    assert "embeddings_allowed: false" in output
    assert "qdrant_allowed: false" in output
    assert "network_allowed: false" in output
    assert "data_staging_allowed: false" in output
    assert "destructive_action_available: false" in output
    assert "invalid_scope_values_count: 0" in output
    assert "dangerous_flags_enabled_count: 0" in output
    assert "missing_required_metadata_fields_count: 0" in output
    assert "unsafe_allowed_resource_kinds_count: 0" in output
    assert "missing_allowed_resource_kinds_count: 0" in output
    assert "missing_excluded_resource_kinds_count: 0" in output
    assert "missing_acceptance_checks_count: 0" in output
    for section in [
        "## Invalid scope values",
        "## Scope",
        "## Allowed resource kinds",
        "## Excluded resource kinds",
        "## Required metadata fields",
        "## Acceptance checks",
        "## Blocking issues",
        "## Explicit non-actions",
    ]:
        assert section in output
    for non_action in [
        "no real document copied",
        "no PDF copied",
        "no ingestion launched",
        "no parsing launched",
        "no chunking launched",
        "no embedding created",
        "no Qdrant touched",
        "no network call",
        "no .env opened",
        "no data/staging created",
    ]:
        assert non_action in output


@pytest.mark.parametrize("flag", DANGEROUS_FLAGS)
def test_pilot_corpus_scope_rejects_any_dangerous_flag_enabled(tmp_path, capsys, flag: str) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _write_config(tmp_path, **{flag: True})

    status = module.main(["--config", str(config)])

    output = capsys.readouterr().out
    assert status == 1
    assert f"{flag} must be false" in output
    assert "scope_ready_for_review: false" in output


def test_pilot_corpus_scope_rejects_missing_required_metadata_field(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    fields = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["required_metadata_fields"]
    config = _write_config(tmp_path, required_metadata_fields=[field for field in fields if field != "rights"])

    status = module.main(["--config", str(config)])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing required_metadata_fields: rights" in output


def test_pilot_corpus_scope_rejects_invalid_context_scope_value(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _write_config(tmp_path, context="france")

    status = module.main(["--config", str(config)])

    output = capsys.readouterr().out
    assert status == 1
    assert "invalid_scope_values_count: 1" in output
    assert "context must be aefe_tunisie" in output


def test_pilot_corpus_scope_rejects_invalid_candidate_status(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _write_config(tmp_path, candidate_status="candidat_libre")

    status = module.main(["--config", str(config)])

    output = capsys.readouterr().out
    assert status == 1
    assert "candidate_status must be candidat_scolarise" in output


def test_pilot_corpus_scope_rejects_missing_official_exam_ref(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    fields = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["required_metadata_fields"]
    config = _write_config(tmp_path, required_metadata_fields=[field for field in fields if field != "official_exam_ref"])

    status = module.main(["--config", str(config)])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing required_metadata_fields: official_exam_ref" in output


def test_pilot_corpus_scope_rejects_missing_difficulty(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    fields = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["required_metadata_fields"]
    config = _write_config(tmp_path, required_metadata_fields=[field for field in fields if field != "difficulty"])

    status = module.main(["--config", str(config)])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing required_metadata_fields: difficulty" in output


def test_pilot_corpus_scope_rejects_unsafe_allowed_resource_kind(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    kinds = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["allowed_resource_kinds"]
    config = _write_config(tmp_path, allowed_resource_kinds=[*kinds, "real_document"])

    status = module.main(["--config", str(config)])

    output = capsys.readouterr().out
    assert status == 1
    assert "unsafe allowed_resource_kinds: real_document" in output


def test_pilot_corpus_scope_rejects_missing_allowed_resource_kind(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    kinds = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["allowed_resource_kinds"]
    config = _write_config(tmp_path, allowed_resource_kinds=[kind for kind in kinds if kind != "taxonomy_reference"])

    status = module.main(["--config", str(config)])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing allowed_resource_kinds: taxonomy_reference" in output


def test_pilot_corpus_scope_rejects_missing_excluded_resource_kind(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    kinds = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["excluded_resource_kinds"]
    config = _write_config(tmp_path, excluded_resource_kinds=[kind for kind in kinds if kind != "unknown_rights"])

    status = module.main(["--config", str(config)])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing excluded_resource_kinds: unknown_rights" in output


def test_pilot_corpus_scope_rejects_non_mapping_config_without_traceback(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _write_raw_config(tmp_path, "- not\n- a\n- mapping\n")

    status = module.main(["--config", str(config)])

    output = capsys.readouterr().out
    assert status == 1
    assert "scope_ready_for_review: false" in output
    assert "config must be a YAML mapping" in output
    assert "Traceback" not in output
    assert "Traceback" not in capsys.readouterr().err


def test_pilot_corpus_scope_real_config_reports_complete_lock_counts(capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()

    status = module.main([])

    output = capsys.readouterr().out
    assert status == 0
    assert "scope_ready_for_review: true" in output
    assert "invalid_scope_values_count: 0" in output
    assert "missing_required_metadata_fields_count: 0" in output
    assert "unsafe_allowed_resource_kinds_count: 0" in output
    assert "missing_allowed_resource_kinds_count: 0" in output
    assert "missing_excluded_resource_kinds_count: 0" in output


def test_pilot_corpus_scope_does_not_modify_git_status() -> None:
    module = _load_audit_module()
    before = _git_status()

    status = module.main([])

    after = _git_status()
    assert status == 0
    assert after == before


def test_pilot_corpus_scope_does_not_create_data_staging() -> None:
    module = _load_audit_module()
    _staging_before = set(DATA_STAGING.rglob("*")) if DATA_STAGING.exists() else set()

    status = module.main([])

    assert status == 0
    # Staging may exist (legitimate content); verify module didn't modify it
    _staging_after = set(DATA_STAGING.rglob("*")) if DATA_STAGING.exists() else set()
    assert _staging_after == _staging_before, "module must not create/modify staging"


def test_pilot_corpus_scope_does_not_open_env(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    module = _load_audit_module()
    original_open = Path.open

    def guarded_open(self: Path, *args: object, **kwargs: object):  # noqa: ANN001
        if self.name == ".env":
            raise AssertionError(".env must not be opened")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    status = module.main(["--config", str(_write_config(tmp_path))])

    assert status == 0


def test_pilot_corpus_scope_cli_real_execution_returns_markdown() -> None:
    result = _run_cli()

    assert result.returncode == 0
    assert "# Pilot corpus scope audit" in result.stdout
    assert "status: metadata_only_scope" in result.stdout
    assert "destructive_action_available: false" in result.stdout
    assert result.stderr == ""


def test_pilot_corpus_scope_cli_python_optimized_mode_returns_markdown() -> None:
    result = _run_cli(optimized=True)

    assert result.returncode == 0
    assert "# Pilot corpus scope audit" in result.stdout
    assert "scope_ready_for_review: true" in result.stdout
    assert result.stderr == ""
