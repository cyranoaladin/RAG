from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import yaml

from rag_pedago.paths import REPO_ROOT

CONFIG = REPO_ROOT / "configs/make_target_safety.yml"
PROTOCOL_DOC = REPO_ROOT / "docs/MAKE_TARGET_SAFETY_PROTOCOL.md"
SCRIPT = REPO_ROOT / "scripts/make_target_safety_audit.py"
MAKEFILE = REPO_ROOT / "Makefile"
DATA_STAGING = REPO_ROOT / "data/staging"

SAFE_CATEGORIES = {
    "SAFE_DIAGNOSTIC",
    "SAFE_METADATA_ONLY",
    "SAFE_CLEANUP_REVIEW",
    "SAFE_TESTING",
}
SENSITIVE_TARGETS = {
    "install",
    "init",
    "scrape-official",
    "ingest",
    "ingest-official",
    "ingest-internal",
    "verify",
    "eval-retrieval",
    "watch",
    "api",
    "backup",
    "format",
}


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("make_target_safety_audit", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_targets() -> set[str]:
    module = _load_audit_module()
    return set(module.extract_make_targets(MAKEFILE.read_text(encoding="utf-8")))


def _classified_targets() -> dict[str, str]:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    classified: dict[str, str] = {}
    for category, targets in config.items():
        for target in targets:
            classified[target] = category
    return classified


def _git_status() -> str:
    return subprocess.check_output(
        ["git", "status", "--short", "--branch"],
        cwd=REPO_ROOT,
        text=True,
    )


def _write_text(path: Path, content: str) -> Path:
    path.write_text(dedent(content).lstrip(), encoding="utf-8")
    return path


def _write_config(path: Path, content: str) -> Path:
    path.write_text(dedent(content).lstrip(), encoding="utf-8")
    return path


def _run_audit_for_files(tmp_path: Path, capsys, makefile_text: str, config_text: str):  # noqa: ANN001
    module = _load_audit_module()
    makefile = _write_text(tmp_path / "Makefile", makefile_text)
    config = _write_config(tmp_path / "make_target_safety.yml", config_text)

    status = module.main(["--makefile", str(makefile), "--config", str(config)])

    return status, capsys.readouterr().out


def _run_audit_cli(makefile: Path, config: Path, *, optimized: bool = False) -> subprocess.CompletedProcess[str]:
    command = ["python3"]
    if optimized:
        command.append("-O")
    command.extend(
        [
            "scripts/make_target_safety_audit.py",
            "--makefile",
            str(makefile),
            "--config",
            str(config),
        ]
    )
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_make_target_safety_artifacts_exist() -> None:
    assert CONFIG.is_file()
    assert PROTOCOL_DOC.is_file()
    assert SCRIPT.is_file()


def test_make_target_safety_make_target_exists() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    assert "make-target-safety-audit:" in text
    assert "$(PY) scripts/make_target_safety_audit.py" in text


def test_make_target_safety_script_has_no_destructive_network_or_subprocess_tokens() -> None:
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
        "git clean",
        "find -delete",
        "rm -rf",
        "--apply",
        "--delete",
        "--move",
        "--write",
        "--output",
    ]
    assert not any(token in text for token in forbidden_tokens)


def test_make_target_safety_audit_returns_markdown(capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()

    status = module.main([])

    output = capsys.readouterr().out
    assert status == 0
    assert "# Make target safety audit" in output
    assert "all_targets_classified: true" in output
    assert "phony_targets_count:" in output
    assert "rule_targets_count:" in output
    assert "all_make_targets_count:" in output
    assert "rule_targets_not_phony_count: 0" in output
    assert "phony_targets_without_rule_count: 0" in output
    assert "extra_config_targets_count: 0" in output
    assert "invalid_config_categories_count: 0" in output
    assert "duplicate_classifications_count: 0" in output
    assert "malformed_config_entries_count: 0" in output
    assert "unknown_targets_count: 0" in output
    assert "unsafe_safe_classifications_count: 0" in output
    assert "targets_executed: false" in output
    assert "destructive_action_available: false" in output
    for section in [
        "## Target counts by category",
        "## Unclassified targets",
        "## Rule targets not declared PHONY",
        "## PHONY targets without rule",
        "## Extra config targets",
        "## Invalid config categories",
        "## Duplicate classifications",
        "## Malformed config entries",
        "## UNKNOWN targets",
        "## Unsafe SAFE classifications",
        "## Restricted targets",
        "## Future-not-ready targets",
        "## Safe targets",
        "## Explicit non-actions",
    ]:
        assert section in output
    for non_action in [
        "no make target executed",
        "no file deleted",
        "no file moved",
        "no archive created",
        "no network call",
        "no .env opened",
        "no data/staging created",
    ]:
        assert non_action in output


def test_all_makefile_targets_are_classified() -> None:
    make_targets = _make_targets()
    classified = _classified_targets()

    assert make_targets
    assert make_targets <= set(classified)


def test_no_sensitive_target_is_classified_safe() -> None:
    classified = _classified_targets()

    for target in SENSITIVE_TARGETS:
        assert classified[target] not in SAFE_CATEGORIES


def test_required_target_categories_are_stable() -> None:
    classified = _classified_targets()

    for target in ["ingest", "ingest-official", "ingest-internal"]:
        assert classified[target] != "SAFE_METADATA_ONLY"
        assert classified[target] not in SAFE_CATEGORIES
    assert classified["scrape-official"] == "RESTRICTED_NETWORK"
    assert classified["api"] == "RESTRICTED_RUNTIME"
    assert classified["watch"] == "RESTRICTED_RUNTIME"
    assert classified["backup"] == "RESTRICTED_DESTRUCTIVE_OR_BACKUP"
    assert classified["eval-retrieval"] == "FUTURE_NOT_READY"
    for target in ["cleanup-dry-run", "cleanup-review", "cleanup-decision-draft"]:
        assert classified[target] == "SAFE_CLEANUP_REVIEW"


def test_make_target_safety_script_does_not_touch_git_or_staging() -> None:
    before_status = _git_status()
    before_staging_exists = DATA_STAGING.exists()
    module = _load_audit_module()

    status = module.main([])

    assert status == 0
    assert _git_status() == before_status
    assert DATA_STAGING.exists() is before_staging_exists


def test_make_target_safety_script_does_not_read_env(monkeypatch) -> None:  # noqa: ANN001
    module = _load_audit_module()
    original_read_text = Path.read_text

    def guarded_read_text(path: Path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        assert path.name != ".env"
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    assert module.main([]) == 0


def test_phony_and_real_rules_are_consistent(tmp_path, capsys) -> None:  # noqa: ANN001
    status, output = _run_audit_for_files(
        tmp_path,
        capsys,
        """
        .PHONY: test doctor cleanup-dry-run

        test:
        \tpytest

        doctor:
        \tpython3 scripts/doctor.py

        cleanup-dry-run:
        \tpython3 scripts/cleanup_dry_run.py
        """,
        """
        SAFE_TESTING:
          - test
        SAFE_DIAGNOSTIC:
          - doctor
        SAFE_CLEANUP_REVIEW:
          - cleanup-dry-run
        """,
    )

    assert status == 0
    assert "rule_targets_not_phony_count: 0" in output
    assert "phony_targets_without_rule_count: 0" in output


def test_real_rule_missing_from_phony_fails_audit(tmp_path, capsys) -> None:  # noqa: ANN001
    status, output = _run_audit_for_files(
        tmp_path,
        capsys,
        """
        .PHONY: test

        test:
        \tpytest

        dangerous:
        \techo "danger"
        """,
        """
        SAFE_TESTING:
          - test
        """,
    )

    assert status == 1
    assert "rule_targets_not_phony_count: 1" in output
    assert "unclassified_targets_count: 1" in output
    assert "dangerous" in output


def test_phony_target_without_real_rule_fails_audit(tmp_path, capsys) -> None:  # noqa: ANN001
    status, output = _run_audit_for_files(
        tmp_path,
        capsys,
        """
        .PHONY: test ghost

        test:
        \tpytest
        """,
        """
        SAFE_TESTING:
          - test
          - ghost
        """,
    )

    assert status == 1
    assert "phony_targets_without_rule_count: 1" in output
    assert "ghost" in output


def test_extra_config_target_fails_audit(tmp_path, capsys) -> None:  # noqa: ANN001
    status, output = _run_audit_for_files(
        tmp_path,
        capsys,
        """
        .PHONY: test

        test:
        \tpytest
        """,
        """
        SAFE_TESTING:
          - test
          - obsolete-target
        """,
    )

    assert status == 1
    assert "extra_config_targets_count: 1" in output
    assert "obsolete-target" in output


def test_phony_continuation_is_detected(tmp_path) -> None:
    module = _load_audit_module()
    makefile_text = dedent(
        """
        .PHONY: test doctor \\
                cleanup-dry-run

        test:
        \tpytest

        doctor:
        \tpython3 scripts/doctor.py

        cleanup-dry-run:
        \tpython3 scripts/cleanup_dry_run.py
        """
    ).lstrip()

    assert module.extract_phony_targets(makefile_text) == [
        "cleanup-dry-run",
        "doctor",
        "test",
    ]


def test_rule_with_multiple_targets_is_detected(tmp_path) -> None:
    module = _load_audit_module()
    makefile_text = dedent(
        """
        .PHONY: lint typecheck

        lint typecheck:
        \techo "check"
        """
    ).lstrip()

    assert module.extract_rule_targets(makefile_text) == ["lint", "typecheck"]


def test_real_makefile_has_consistent_phony_rules_and_config(capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()

    status = module.main([])

    output = capsys.readouterr().out
    assert status == 0
    assert "all_targets_classified: true" in output
    assert "rule_targets_not_phony_count: 0" in output
    assert "phony_targets_without_rule_count: 0" in output
    assert "extra_config_targets_count: 0" in output
    assert "unsafe_safe_classifications_count: 0" in output
    assert "targets_executed: false" in output


def test_typecheck_target_has_mypy_available_after_install() -> None:
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    requirements_text = (REPO_ROOT / "requirements.lock").read_text(encoding="utf-8")

    assert "VENVDIR ?= .venv" in makefile_text
    assert "PY_VENV := $(VENVDIR)/bin/python" in makefile_text
    assert "\ninstall: venv\n" in makefile_text
    assert '"$(PY_VENV)" -m pip install -r requirements.lock' in makefile_text
    assert "\ntypecheck:\n\t$(PY) -m mypy" in makefile_text
    assert any(line.startswith("mypy==") for line in requirements_text.splitlines())


def test_unknown_category_fails_audit(tmp_path, capsys) -> None:  # noqa: ANN001
    status, output = _run_audit_for_files(
        tmp_path,
        capsys,
        """
        .PHONY: test

        test:
        \tpytest
        """,
        """
        UNKNOWN:
          - test
        """,
    )

    assert status == 1
    assert "UNKNOWN: 1" in output
    assert "test" in output


def test_invalid_yaml_category_fails_audit_without_traceback(tmp_path, capsys) -> None:  # noqa: ANN001
    status, output = _run_audit_for_files(
        tmp_path,
        capsys,
        """
        .PHONY: test doctor

        test:
        \tpytest

        doctor:
        \tpython3 scripts/doctor.py
        """,
        """
        SAFE_TESTING:
          - test

        SAFE_DIAGNOSITC:
          - doctor
        """,
    )

    assert status == 1
    assert "invalid_config_categories_count: 1" in output
    assert "SAFE_DIAGNOSITC" in output
    assert "Traceback" not in output


def test_duplicate_classification_fails_audit_without_traceback(tmp_path, capsys) -> None:  # noqa: ANN001
    status, output = _run_audit_for_files(
        tmp_path,
        capsys,
        """
        .PHONY: test

        test:
        \tpytest
        """,
        """
        SAFE_TESTING:
          - test

        RESTRICTED_RUNTIME:
          - test
        """,
    )

    assert status == 1
    assert "duplicate_classifications_count: 1" in output
    assert "test" in output
    assert "Traceback" not in output


def test_non_list_category_value_fails_audit_without_traceback(tmp_path, capsys) -> None:  # noqa: ANN001
    status, output = _run_audit_for_files(
        tmp_path,
        capsys,
        """
        .PHONY: test

        test:
        \tpytest
        """,
        "SAFE_TESTING: test\n",
    )

    assert status == 1
    assert "malformed_config_entries_count: 1" in output
    assert "SAFE_TESTING" in output
    assert "Traceback" not in output


def test_non_string_category_entry_fails_audit_without_traceback(tmp_path, capsys) -> None:  # noqa: ANN001
    status, output = _run_audit_for_files(
        tmp_path,
        capsys,
        """
        .PHONY: test

        test:
        \tpytest
        """,
        """
        SAFE_TESTING:
          - test
          - 42
        """,
    )

    assert status == 1
    assert "malformed_config_entries_count: 1" in output
    assert "SAFE_TESTING" in output
    assert "Traceback" not in output


def test_make_target_safety_cli_outputs_markdown() -> None:
    result = subprocess.run(
        ["python3", "scripts/make_target_safety_audit.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "# Make target safety audit" in result.stdout
    assert "all_targets_classified: true" in result.stdout
    assert "targets_executed: false" in result.stdout
    assert "destructive_action_available: false" in result.stdout


def test_make_target_safety_cli_python_optimized_mode_outputs_markdown() -> None:
    result = subprocess.run(
        ["python3", "-O", "scripts/make_target_safety_audit.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "# Make target safety audit" in result.stdout
    assert "all_targets_classified: true" in result.stdout
    assert "targets_executed: false" in result.stdout


def test_invalid_config_cli_has_no_traceback(tmp_path) -> None:
    makefile = _write_text(
        tmp_path / "Makefile",
        """
        .PHONY: test

        test:
        \tpytest
        """,
    )
    config = _write_config(
        tmp_path / "make_target_safety.yml",
        """
        SAFE_TESTING: test
        """,
    )

    result = _run_audit_cli(makefile, config)

    assert result.returncode == 1
    assert "malformed_config_entries_count: 1" in result.stdout
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_future_deploy_target_classified_safe_fails_audit(tmp_path, capsys) -> None:  # noqa: ANN001
    status, output = _run_audit_for_files(
        tmp_path,
        capsys,
        """
        .PHONY: deploy-prod

        deploy-prod:
        \techo "deploy"
        """,
        """
        SAFE_DIAGNOSTIC:
          - deploy-prod
        """,
    )

    assert status == 1
    assert "suspicious_safe_classifications_count: 1" in output
    assert "deploy-prod" in output


def test_qdrant_target_classified_safe_fails_audit(tmp_path, capsys) -> None:  # noqa: ANN001
    status, output = _run_audit_for_files(
        tmp_path,
        capsys,
        """
        .PHONY: qdrant-upsert

        qdrant-upsert:
        \techo "qdrant"
        """,
        """
        SAFE_DIAGNOSTIC:
          - qdrant-upsert
        """,
    )

    assert status == 1
    assert "suspicious_safe_classifications_count: 1" in output
    assert "qdrant-upsert" in output


def test_embedding_target_classified_safe_fails_audit(tmp_path, capsys) -> None:  # noqa: ANN001
    status, output = _run_audit_for_files(
        tmp_path,
        capsys,
        """
        .PHONY: embed-corpus

        embed-corpus:
        \techo "embed"
        """,
        """
        SAFE_METADATA_ONLY:
          - embed-corpus
        """,
    )

    assert status == 1
    assert "suspicious_safe_classifications_count: 1" in output
    assert "embed-corpus" in output


def test_sensitive_pattern_safe_exceptions_are_allowed(tmp_path, capsys) -> None:  # noqa: ANN001
    status, output = _run_audit_for_files(
        tmp_path,
        capsys,
        """
        .PHONY: cleanup-dry-run cleanup-review cleanup-decision-draft make-target-safety-audit

        cleanup-dry-run:
        \tpython3 scripts/cleanup_dry_run.py

        cleanup-review:
        \tpython3 scripts/cleanup_review_package.py

        cleanup-decision-draft:
        \tpython3 scripts/cleanup_decision_draft.py

        make-target-safety-audit:
        \tpython3 scripts/make_target_safety_audit.py
        """,
        """
        SAFE_CLEANUP_REVIEW:
          - cleanup-dry-run
          - cleanup-review
          - cleanup-decision-draft
        SAFE_DIAGNOSTIC:
          - make-target-safety-audit
        """,
    )

    assert status == 0
    assert "suspicious_safe_classifications_count: 0" in output


def test_real_makefile_has_no_suspicious_safe_classifications(capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()

    status = module.main([])

    output = capsys.readouterr().out
    assert status == 0
    assert "all_targets_classified: true" in output
    assert "suspicious_safe_classifications_count: 0" in output
    assert "unsafe_safe_classifications_count: 0" in output
    assert "targets_executed: false" in output
