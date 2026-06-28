from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from rag_pedago.paths import REPO_ROOT

CONFIG = REPO_ROOT / "configs/metadata_review_handoff.yml"
SAFETY_CONFIG = REPO_ROOT / "configs/make_target_safety.yml"
PROTOCOL_DOC = REPO_ROOT / "docs/METADATA_REVIEW_HANDOFF_PROTOCOL.md"
SCRIPT = REPO_ROOT / "scripts/metadata_review_handoff_audit.py"
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
    "server_start_allowed",
    "runtime_api_allowed",
    "data_staging_allowed",
]

REQUIRED_CASE_FIELDS = [
    "handoff_case_id",
    "reviewed_chain_ref",
    "decision",
    "decision_reason",
    "reviewer_role",
    "human_review_required",
    "real_action_allowed",
    "real_file_allowed",
    "pipeline_allowed",
    "followup_lot_required",
    "rollback_later_required",
    "checksum_later_required",
]


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("metadata_review_handoff_audit", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _base_config() -> dict[str, object]:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def _write_config(tmp_path: Path, config: dict[str, object] | None = None, **overrides: object) -> Path:
    data = dict(_base_config() if config is None else config)
    for key, value in overrides.items():
        data[key] = value
    path = tmp_path / "metadata_review_handoff.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _handoff_cases(config: dict[str, object]) -> list[object]:
    cases = config["handoff_cases"]
    assert isinstance(cases, list)
    return cases


def _first_case(config: dict[str, object]) -> dict[str, object]:
    case = _handoff_cases(config)[0]
    assert isinstance(case, dict)
    return case


def _case_by_decision(config: dict[str, object], decision: str) -> dict[str, object]:
    for case in _handoff_cases(config):
        if isinstance(case, dict) and case.get("decision") == decision:
            return case
    raise AssertionError(f"missing case for decision: {decision}")


def _run_cli(*, optimized: bool = False, config: Path = CONFIG) -> subprocess.CompletedProcess[str]:
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend(["scripts/metadata_review_handoff_audit.py", "--config", str(config)])
    return subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def _git_status() -> str:
    return subprocess.check_output(["git", "status", "--short", "--branch"], cwd=REPO_ROOT, text=True)


def test_metadata_review_handoff_artifacts_exist() -> None:
    assert PROTOCOL_DOC.is_file()
    assert CONFIG.is_file()
    assert SCRIPT.is_file()


def test_metadata_review_handoff_make_target_is_safe() -> None:
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    safety_config = yaml.safe_load(SAFETY_CONFIG.read_text(encoding="utf-8"))

    assert "metadata-review-handoff-audit:" in makefile_text
    assert "$(PY) scripts/metadata_review_handoff_audit.py" in makefile_text
    assert "metadata-review-handoff-audit" in safety_config["SAFE_METADATA_ONLY"]


def test_metadata_review_handoff_does_not_add_sensitive_target_names() -> None:
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    safety_config = yaml.safe_load(SAFETY_CONFIG.read_text(encoding="utf-8"))
    safe_targets = safety_config["SAFE_METADATA_ONLY"]
    forbidden_targets = [
        "real-source-audit",
        "corpus-readiness-audit",
        "source-handoff-audit",
        "ingestion-handoff-audit",
        "api-handoff-audit",
        "qdrant-handoff-audit",
        "embedding-handoff-audit",
    ]

    for target in forbidden_targets:
        assert target not in makefile_text
        assert target not in safe_targets


def test_metadata_review_handoff_script_has_no_process_or_network_tokens() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden_tokens = ["subprocess", "requests", "httpx", "urllib", "socket"]
    assert not any(token in text for token in forbidden_tokens)


def test_metadata_review_handoff_script_has_no_destructive_tokens() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden_tokens = [
        "unlink(",
        "remove(",
        "rmdir(",
        "shutil.rmtree",
        "shutil.move",
        "git clean",
        "find -delete",
        "rm -rf",
    ]
    assert not any(token in text for token in forbidden_tokens)


def test_metadata_review_handoff_audit_returns_markdown(capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()

    status = module.main([])

    output = capsys.readouterr().out
    assert status == 0
    assert "# Metadata review handoff audit" in output
    assert "status: metadata_only_review_handoff" in output
    assert "handoff_ready_for_review: true" in output
    assert "handoff_cases_count: 4" in output
    assert "hardening_required_count: 1" in output
    assert "handoff_decision_coverage_errors_count: 0" in output
    assert "real_documents_allowed: false" in output
    assert "ingestion_allowed: false" in output
    assert "embeddings_allowed: false" in output
    assert "qdrant_allowed: false" in output
    assert "no real document read" in output


@pytest.mark.parametrize("flag", DANGEROUS_FLAGS)
def test_metadata_review_handoff_rejects_any_dangerous_flag_enabled(tmp_path, capsys, flag: str) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, **{flag: True})

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "handoff_ready_for_review: false" in output
    assert f"{flag} must be false" in output


def test_metadata_review_handoff_rejects_wrong_governance_chain_ref(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, governance_chain_ref="wrong")

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "governance_chain_ref must be metadata_governance_chain_17C_17I_v1" in output


def test_metadata_review_handoff_rejects_wrong_latest_lot_ref(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, latest_lot_ref="17I")

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "latest_lot_ref must be 17J" in output


def test_metadata_review_handoff_rejects_wrong_latest_commit_ref(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, latest_commit_ref="wrong")

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "latest_commit_ref must be d78b5dbae68d493266e89257781a3ec7df47e44b" in output


def test_metadata_review_handoff_rejects_missing_required_review_role(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, required_review_roles=["reviewer_pedagogique"])

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing required review role: reviewer_droits" in output


def test_metadata_review_handoff_rejects_unknown_allowed_decision(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["allowed_handoff_decisions"] = [*config["allowed_handoff_decisions"], "publish_now"]  # type: ignore[index]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "unknown allowed handoff decision: publish_now" in output


@pytest.mark.parametrize("field", REQUIRED_CASE_FIELDS)
def test_metadata_review_handoff_rejects_missing_required_handoff_field(tmp_path, capsys, field: str) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    required_fields = config["required_handoff_fields"]
    assert isinstance(required_fields, list)
    config["required_handoff_fields"] = [item for item in required_fields if item != field]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert f"missing required handoff field declaration: {field}" in output


@pytest.mark.parametrize("value", [None, [], "not-a-list"])
def test_metadata_review_handoff_rejects_malformed_handoff_cases(tmp_path, capsys, value: object) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, handoff_cases=value)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "handoff_cases must be a non-empty list" in output


def test_metadata_review_handoff_rejects_non_mapping_case(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["handoff_cases"] = ["not-a-mapping"]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "handoff case at index 0 must be a mapping" in output


def test_metadata_review_handoff_rejects_empty_handoff_case_id(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_case(config)["handoff_case_id"] = ""
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "handoff case at index 0 missing non-empty handoff_case_id" in output


def test_metadata_review_handoff_rejects_duplicate_handoff_case_id(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    cases = _handoff_cases(config)
    cases.append(dict(_first_case(config)))
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "duplicate handoff_case_id: governance_chain_ready_for_review" in output


def test_metadata_review_handoff_rejects_wrong_reviewed_chain_ref(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_case(config)["reviewed_chain_ref"] = "wrong"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "handoff governance_chain_ready_for_review reviewed_chain_ref must be metadata_governance_chain_17C_17I_v1" in output


def test_metadata_review_handoff_rejects_unknown_reviewer_role(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_case(config)["reviewer_role"] = "unknown_role"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "handoff governance_chain_ready_for_review unknown reviewer_role: unknown_role" in output


def test_metadata_review_handoff_rejects_empty_decision_reason(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_case(config)["decision_reason"] = ""
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "handoff governance_chain_ready_for_review decision_reason must be non-empty" in output


@pytest.mark.parametrize(
    "field, value",
    [
        ("human_review_required", False),
        ("real_action_allowed", True),
        ("real_file_allowed", True),
        ("pipeline_allowed", True),
        ("followup_lot_required", False),
        ("rollback_later_required", False),
        ("checksum_later_required", False),
    ],
)
def test_metadata_review_handoff_rejects_unsafe_handoff_fields(
    tmp_path, capsys, field: str, value: bool  # noqa: ANN001
) -> None:
    module = _load_audit_module()
    config = _base_config()
    _first_case(config)[field] = value
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    expected = "true" if value is False else "false"
    assert f"handoff governance_chain_ready_for_review {field} must be {expected}" in output


@pytest.mark.parametrize(
    "decision, reason",
    [
        ("ready_for_human_metadata_review", "wrong_reason"),
        ("require_more_metadata_hardening", "wrong_reason"),
        ("block_any_real_action", "wrong_reason"),
        ("defer_until_named_followup_lot", "wrong_reason"),
    ],
)
def test_metadata_review_handoff_rejects_wrong_decision_reason(
    tmp_path, capsys, decision: str, reason: str  # noqa: ANN001
) -> None:
    module = _load_audit_module()
    config = _base_config()
    case = _first_case(config)
    case["decision"] = decision
    case["decision_reason"] = reason
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert f"handoff governance_chain_ready_for_review decision_reason mismatch for {decision}" in output


def test_metadata_review_handoff_accepts_require_more_metadata_hardening_reason(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    case = _case_by_decision(config, "require_more_metadata_hardening")
    case["decision_reason"] = "metadata_hardening_required_before_handoff"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 0
    assert "handoff_ready_for_review: true" in output
    assert "hardening_required_count: 1" in output


def test_metadata_review_handoff_rejects_missing_critical_decision_coverage(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["handoff_cases"] = [
        case
        for case in _handoff_cases(config)
        if isinstance(case, dict) and case["decision"] != "defer_until_named_followup_lot"
    ]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing critical handoff decision coverage: defer_until_named_followup_lot" in output


def test_metadata_review_handoff_rejects_missing_hardening_decision_coverage(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["handoff_cases"] = [
        case
        for case in _handoff_cases(config)
        if isinstance(case, dict) and case["decision"] != "require_more_metadata_hardening"
    ]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing critical handoff decision coverage: require_more_metadata_hardening" in output


@pytest.mark.parametrize("field", ["file_path", "source_uri", "url", "content"])
def test_metadata_review_handoff_rejects_forbidden_case_fields(tmp_path, capsys, field: str) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_case(config)[field] = "forbidden"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert f"handoff governance_chain_ready_for_review forbidden field: {field}" in output


def test_metadata_review_handoff_rejects_missing_17j_report(tmp_path, capsys, monkeypatch) -> None:  # noqa: ANN001
    module = _load_audit_module()
    monkeypatch.setattr(module, "GOVERNANCE_REPORT", REPO_ROOT / "data/reports/missing_17J.md")

    status = module.main([])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing 17J governance report" in output


def test_metadata_review_handoff_rejects_17j_report_without_ready_marker(tmp_path, capsys, monkeypatch) -> None:  # noqa: ANN001
    module = _load_audit_module()
    report = tmp_path / "codex_lot_17J_metadata_governance_chain.md"
    report.write_text("not ready", encoding="utf-8")
    monkeypatch.setattr(module, "GOVERNANCE_REPORT", report)

    status = module.main([])

    output = capsys.readouterr().out
    assert status == 1
    assert "17J governance report must contain READY_FOR_METADATA_GOVERNANCE_CHAIN_REVIEW" in output


def test_metadata_review_handoff_rejects_non_mapping_config_without_traceback(tmp_path) -> None:
    path = tmp_path / "metadata_review_handoff.yml"
    path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    result = _run_cli(config=path)

    assert result.returncode == 1
    assert "handoff_ready_for_review: false" in result.stdout
    assert "config must be a YAML mapping" in result.stdout
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_metadata_review_handoff_audit_does_not_modify_git_status() -> None:
    before = _git_status()
    module = _load_audit_module()

    status = module.main([])

    after = _git_status()
    assert status == 0
    assert after == before


def test_metadata_review_handoff_audit_does_not_create_data_staging() -> None:
    module = _load_audit_module()
    _staging_before = set(DATA_STAGING.rglob("*")) if DATA_STAGING.exists() else set()

    status = module.main([])

    assert status == 0
    # Staging may exist (legitimate content); verify module didn't modify it
    _staging_after = set(DATA_STAGING.rglob("*")) if DATA_STAGING.exists() else set()
    assert _staging_after == _staging_before, "module must not create/modify staging"


def test_metadata_review_handoff_audit_does_not_open_env(monkeypatch, tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    original_read_text = Path.read_text

    def guarded_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == ".env" or ".env" in self.parts:
            raise AssertionError(f".env must not be opened: {self}")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    path = _write_config(tmp_path)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 0
    assert "handoff_ready_for_review: true" in output


def test_metadata_review_handoff_cli_returns_zero() -> None:
    result = _run_cli()

    assert result.returncode == 0
    assert "handoff_ready_for_review: true" in result.stdout


def test_metadata_review_handoff_cli_optimized_returns_zero() -> None:
    result = _run_cli(optimized=True)

    assert result.returncode == 0
    assert "handoff_ready_for_review: true" in result.stdout


def test_metadata_review_handoff_keeps_make_target_safety_audit_green() -> None:
    module = _load_audit_module()

    status = module.main([])

    assert status == 0
    assert "metadata-review-handoff-audit" in yaml.safe_load(SAFETY_CONFIG.read_text(encoding="utf-8"))[
        "SAFE_METADATA_ONLY"
    ]
