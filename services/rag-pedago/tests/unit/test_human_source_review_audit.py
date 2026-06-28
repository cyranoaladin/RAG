from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from rag_pedago.paths import REPO_ROOT

CONFIG = REPO_ROOT / "configs/human_source_review.yml"
SAFETY_CONFIG = REPO_ROOT / "configs/make_target_safety.yml"
PROTOCOL_DOC = REPO_ROOT / "docs/HUMAN_SOURCE_REVIEW_PROTOCOL.md"
SCRIPT = REPO_ROOT / "scripts/human_source_review_audit.py"
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


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("human_source_review_audit", SCRIPT)
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
    path = tmp_path / "human_source_review.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _review_cases(config: dict[str, object]) -> list[object]:
    cases = config["review_cases"]
    assert isinstance(cases, list)
    return cases


def _first_case(config: dict[str, object]) -> dict[str, object]:
    case = _review_cases(config)[0]
    assert isinstance(case, dict)
    return case


def _case_by_review_id(config: dict[str, object], review_id: str) -> dict[str, object]:
    for case in _review_cases(config):
        assert isinstance(case, dict)
        if case.get("review_id") == review_id:
            return case
    raise AssertionError(f"missing review case {review_id}")


def _approval_case(config: dict[str, object]) -> dict[str, object]:
    for case in _review_cases(config):
        assert isinstance(case, dict)
        if case.get("decision") == "approve_metadata_only":
            return case
    raise AssertionError("missing approve_metadata_only case")


def _run_cli(*, optimized: bool = False, config: Path = CONFIG) -> subprocess.CompletedProcess[str]:
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend(["scripts/human_source_review_audit.py", "--config", str(config)])
    return subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def _git_status() -> str:
    return subprocess.check_output(["git", "status", "--short", "--branch"], cwd=REPO_ROOT, text=True)


def test_human_source_review_artifacts_exist() -> None:
    assert PROTOCOL_DOC.is_file()
    assert CONFIG.is_file()
    assert SCRIPT.is_file()


def test_human_source_review_make_target_is_safe_and_has_no_sensitive_name() -> None:
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    safety_config = yaml.safe_load(SAFETY_CONFIG.read_text(encoding="utf-8"))

    assert "human-source-review-audit:" in makefile_text
    assert "$(PY) scripts/human_source_review_audit.py" in makefile_text
    assert "human-source-review-audit" in safety_config["SAFE_METADATA_ONLY"]
    for forbidden_target in [
        "source-admission-review-audit",
        "source-ingestion-review-audit",
        "human-ingestion-audit",
        "api-source-review-audit",
        "upload-review-audit",
    ]:
        assert forbidden_target not in makefile_text
        assert forbidden_target not in safety_config["SAFE_METADATA_ONLY"]


def test_human_source_review_script_has_no_destructive_network_or_process_tokens() -> None:
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


def test_human_source_review_audit_returns_markdown(capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()

    status = module.main([])

    output = capsys.readouterr().out
    assert status == 0
    assert "# Human source review audit" in output
    assert "status: metadata_only_human_source_review" in output
    assert "review_ready_for_review: true" in output
    assert "real_documents_allowed: false" in output
    assert "ingestion_allowed: false" in output
    assert "embeddings_allowed: false" in output
    assert "qdrant_allowed: false" in output
    assert "no real document read" in output
    for section in [
        "## Review cases",
        "## Required review roles",
        "## Allowed review decisions",
        "## Required review fields",
        "## Known source errors",
        "## Role coverage errors",
        "## Source decision conflicts",
        "## Blocking issues",
        "## Explicit non-actions",
    ]:
        assert section in output
    assert "known_source_errors_count: 0" in output
    assert "role_coverage_errors_count: 0" in output
    assert "source_decision_conflicts_count: 0" in output


@pytest.mark.parametrize("flag", DANGEROUS_FLAGS)
def test_human_source_review_rejects_any_dangerous_flag_enabled(tmp_path, capsys, flag: str) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, **{flag: True})

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "review_ready_for_review: false" in output
    assert f"{flag} must be false" in output


def test_human_source_review_rejects_missing_required_role(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    roles = config["required_review_roles"]
    assert isinstance(roles, list)
    roles.remove("reviewer_droits")
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing required_review_roles: reviewer_droits" in output


def test_human_source_review_rejects_missing_known_source_ids(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config.pop("known_source_ids", None)
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "known_source_ids must be a non-empty list of strings" in output


def test_human_source_review_rejects_empty_known_source_ids(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, known_source_ids=[])

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "known_source_ids must be a non-empty list of strings" in output


def test_human_source_review_rejects_duplicate_known_source_id(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["known_source_ids"] = [
        "official_programme_metadata_reference",
        "refused_unknown_rights_example",
        "future_real_source_placeholder",
        "official_programme_metadata_reference",
    ]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "duplicate known_source_ids: official_programme_metadata_reference" in output


def test_human_source_review_rejects_unknown_review_case_source_id(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["known_source_ids"] = [
        "official_programme_metadata_reference",
        "refused_unknown_rights_example",
        "future_real_source_placeholder",
    ]
    _first_case(config)["source_id"] = "unknown_source"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "review review_official_programme_metadata_reference source_id must be listed in known_source_ids" in output


def test_human_source_review_rejects_missing_reviewer_technique_coverage(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    cases = [
        case
        for case in _review_cases(config)
        if not (isinstance(case, dict) and case.get("reviewer_role") == "reviewer_technique")
    ]
    config["review_cases"] = cases
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "required role reviewer_technique must appear in review_cases" in output


def test_human_source_review_rejects_missing_responsable_validation_coverage(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    cases = [
        case
        for case in _review_cases(config)
        if not (isinstance(case, dict) and case.get("reviewer_role") == "responsable_validation")
    ]
    config["review_cases"] = cases
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "required role responsable_validation must appear in review_cases" in output


def test_human_source_review_rejects_declared_role_never_used(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    roles = config["required_review_roles"]
    assert isinstance(roles, list)
    roles.append("reviewer_archive")
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "required role reviewer_archive must appear in review_cases" in output


def test_human_source_review_rejects_unknown_declared_decision(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    decisions = config["allowed_review_decisions"]
    assert isinstance(decisions, list)
    decisions.append("publish_now")
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "allowed_review_decisions contains unknown decision: publish_now" in output


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "source_admission_policy_ref",
            "wrong_policy",
            "source_admission_policy_ref must be source_admission_metadata_policy_v1",
        ),
        (
            "pilot_scope_ref",
            "wrong_scope",
            "pilot_scope_ref must be math_terminale_specialite_metadata_only_v1",
        ),
        (
            "retrieval_eval_ref",
            "wrong_eval",
            "retrieval_eval_ref must be math_terminale_specialite_metadata_retrieval_eval_v1",
        ),
        (
            "pedago_interface_ref",
            "wrong_interface",
            "pedago_interface_ref must be pedago_interface_metadata_contract_v1",
        ),
    ],
)
def test_human_source_review_rejects_invalid_policy_references(
    tmp_path,
    capsys,
    field: str,
    value: str,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, **{field: value})

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


def test_human_source_review_rejects_missing_required_review_field(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    fields = config["required_review_fields"]
    assert isinstance(fields, list)
    fields.remove("decision_reason")
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing required_review_fields: decision_reason" in output


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("review_id", "", "review index 0 review_id must be a non-empty string"),
        ("source_id", "", "review review_official_programme_metadata_reference source_id must be a non-empty string"),
        ("reviewer_role", "unknown_role", "review review_official_programme_metadata_reference reviewer_role must be allowed"),
        ("decision", "publish_now", "review review_official_programme_metadata_reference decision must be allowed"),
        ("decision_reason", "", "review review_official_programme_metadata_reference decision_reason must be a non-empty string"),
        (
            "human_validation_required",
            False,
            "review review_official_programme_metadata_reference human_validation_required must be true",
        ),
        (
            "no_real_file_confirmed",
            False,
            "review review_official_programme_metadata_reference no_real_file_confirmed must be true",
        ),
        (
            "no_external_url_confirmed",
            False,
            "review review_official_programme_metadata_reference no_external_url_confirmed must be true",
        ),
    ],
)
def test_human_source_review_rejects_invalid_review_case_fields(
    tmp_path,
    capsys,
    field: str,
    value: object,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_case(config)[field] = value
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


def test_human_source_review_rejects_approval_by_non_responsable_role(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _approval_case(config)["reviewer_role"] = "reviewer_pedagogique"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "approve_metadata_only must be reviewed by responsable_validation" in output


def test_human_source_review_accepts_approval_by_responsable_with_checks(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    approval = _approval_case(config)
    approval["reviewer_role"] = "responsable_validation"
    for check_field in ["rights_checked", "provenance_checked", "pii_checked", "visibility_checked"]:
        approval[check_field] = True
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 0
    assert "review_ready_for_review: true" in output


def test_human_source_review_rejects_duplicate_review_id(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    cases = _review_cases(config)
    assert isinstance(cases[1], dict)
    cases[1]["review_id"] = "review_official_programme_metadata_reference"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "duplicate review_id: review_official_programme_metadata_reference" in output


@pytest.mark.parametrize(
    ("check_field", "message"),
    [
        ("rights_checked", "review review_official_programme_metadata_reference approve_metadata_only requires rights_checked true"),
        (
            "provenance_checked",
            "review review_official_programme_metadata_reference approve_metadata_only requires provenance_checked true",
        ),
        ("pii_checked", "review review_official_programme_metadata_reference approve_metadata_only requires pii_checked true"),
        (
            "visibility_checked",
            "review review_official_programme_metadata_reference approve_metadata_only requires visibility_checked true",
        ),
    ],
)
def test_human_source_review_rejects_approve_metadata_only_without_required_checks(
    tmp_path,
    capsys,
    check_field: str,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_case(config)[check_field] = False
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


def test_human_source_review_rejects_approval_and_rejection_for_same_source(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    rejected_case = _case_by_review_id(config, "review_refused_unknown_rights_example")
    rejected_case["source_id"] = "official_programme_metadata_reference"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "source official_programme_metadata_reference cannot be both approved and rejected" in output


def test_human_source_review_rejects_approval_and_defer_for_same_source(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    deferred_case = _case_by_review_id(config, "review_defer_real_source_lot")
    deferred_case["source_id"] = "official_programme_metadata_reference"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "source official_programme_metadata_reference cannot be both approved and deferred" in output


def test_human_source_review_allows_non_contradictory_reviews_for_same_source(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    technical_case = _case_by_review_id(config, "review_official_programme_technique")
    technical_case["source_id"] = "official_programme_metadata_reference"
    technical_case["decision"] = "request_more_information"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 0
    assert "review_ready_for_review: true" in output


@pytest.mark.parametrize(
    ("decision", "expected_reason", "message"),
    [
        ("reject_unknown_rights", "metadata_only_scope_valid", "reject_unknown_rights requires decision_reason rights_unknown"),
        ("reject_private_data", "metadata_only_scope_valid", "reject_private_data requires decision_reason private_student_data"),
        ("reject_real_document", "metadata_only_scope_valid", "reject_real_document requires decision_reason real_document"),
        (
            "defer_until_real_source_lot",
            "metadata_only_scope_valid",
            "defer_until_real_source_lot requires decision_reason real_source_requires_separate_lot",
        ),
    ],
)
def test_human_source_review_rejects_incoherent_decision_reason(
    tmp_path,
    capsys,
    decision: str,
    expected_reason: str,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    case = _first_case(config)
    case["decision"] = decision
    case["decision_reason"] = expected_reason
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


def test_human_source_review_rejects_defer_by_non_responsable_role(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    deferred_case = _case_by_review_id(config, "review_defer_real_source_lot")
    deferred_case["reviewer_role"] = "reviewer_pedagogique"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "defer_until_real_source_lot must be reviewed by responsable_validation" in output


def test_human_source_review_rejects_defer_without_real_file_confirmation(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _case_by_review_id(config, "review_defer_real_source_lot")["no_real_file_confirmed"] = False
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "review review_defer_real_source_lot no_real_file_confirmed must be true" in output


def test_human_source_review_rejects_defer_without_human_validation(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _case_by_review_id(config, "review_defer_real_source_lot")["human_validation_required"] = False
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "review review_defer_real_source_lot human_validation_required must be true" in output


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("file_path", "data/raw/source.pdf", "review review_official_programme_metadata_reference forbidden field: file_path"),
        ("url", "https://example.invalid", "review review_official_programme_metadata_reference forbidden field: url"),
        ("content", "document body", "review review_official_programme_metadata_reference forbidden field: content"),
    ],
)
def test_human_source_review_rejects_forbidden_review_fields(
    tmp_path,
    capsys,
    field: str,
    value: str,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_case(config)[field] = value
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


def test_human_source_review_rejects_non_mapping_config_without_traceback(tmp_path) -> None:
    path = tmp_path / "human_source_review.yml"
    path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    result = _run_cli(config=path)

    assert result.returncode == 1
    assert "review_ready_for_review: false" in result.stdout
    assert "config must be a YAML mapping" in result.stdout
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_human_source_review_does_not_modify_git_status() -> None:
    module = _load_audit_module()
    before = _git_status()

    status = module.main([])

    after = _git_status()
    assert status == 0
    assert after == before


def test_human_source_review_does_not_create_data_staging() -> None:
    module = _load_audit_module()
    _staging_before = set(DATA_STAGING.rglob("*")) if DATA_STAGING.exists() else set()

    status = module.main([])

    assert status == 0
    # Staging may exist (legitimate content); verify module didn't modify it
    _staging_after = set(DATA_STAGING.rglob("*")) if DATA_STAGING.exists() else set()
    assert _staging_after == _staging_before, "module must not create/modify staging"


def test_human_source_review_does_not_open_env(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    module = _load_audit_module()
    original_open = Path.open

    def guarded_open(self: Path, *args: object, **kwargs: object):  # noqa: ANN001
        if self.name == ".env":
            raise AssertionError(".env must not be opened")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    status = module.main(["--config", str(_write_config(tmp_path))])

    assert status == 0


def test_human_source_review_cli_real_execution_returns_markdown() -> None:
    result = _run_cli()

    assert result.returncode == 0
    assert "# Human source review audit" in result.stdout
    assert "status: metadata_only_human_source_review" in result.stdout
    assert result.stderr == ""


def test_human_source_review_cli_python_optimized_mode_returns_markdown() -> None:
    result = _run_cli(optimized=True)

    assert result.returncode == 0
    assert "# Human source review audit" in result.stdout
    assert "review_ready_for_review: true" in result.stdout
    assert result.stderr == ""


def test_make_target_safety_audit_remains_green_after_human_source_review_target() -> None:
    result = subprocess.run(
        ["make", "make-target-safety-audit"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "all_targets_classified: true" in result.stdout
    assert "human-source-review-audit" in result.stdout
