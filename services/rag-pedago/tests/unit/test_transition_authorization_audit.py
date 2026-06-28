from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from rag_pedago.paths import REPO_ROOT

CONFIG = REPO_ROOT / "configs/transition_authorization.yml"
SAFETY_CONFIG = REPO_ROOT / "configs/make_target_safety.yml"
PROTOCOL_DOC = REPO_ROOT / "docs/TRANSITION_AUTHORIZATION_PROTOCOL.md"
SCRIPT = REPO_ROOT / "scripts/transition_authorization_audit.py"
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

# Flags authorized at true via transition_authorization.yml
AUTHORIZED_TRUE_FLAGS = {"network_allowed", "data_staging_allowed", "pdf_allowed", "parsing_allowed", "chunking_allowed", "embeddings_allowed", "ingestion_allowed", "server_start_allowed", "runtime_api_allowed"}


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("transition_authorization_audit", SCRIPT)
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
    path = tmp_path / "transition_authorization.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _authorization_cases(config: dict[str, object]) -> list[object]:
    cases = config["authorization_cases"]
    assert isinstance(cases, list)
    return cases


def _first_case(config: dict[str, object]) -> dict[str, object]:
    case = _authorization_cases(config)[0]
    assert isinstance(case, dict)
    return case


def _case_by_id(config: dict[str, object], authorization_case_id: str) -> dict[str, object]:
    for case in _authorization_cases(config):
        assert isinstance(case, dict)
        if case.get("authorization_case_id") == authorization_case_id:
            return case
    raise AssertionError(f"missing authorization case {authorization_case_id}")


def _run_cli(*, optimized: bool = False, config: Path = CONFIG) -> subprocess.CompletedProcess[str]:
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend(["scripts/transition_authorization_audit.py", "--config", str(config)])
    return subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def _git_status() -> str:
    return subprocess.check_output(["git", "status", "--short", "--branch"], cwd=REPO_ROOT, text=True)


def test_transition_authorization_artifacts_exist() -> None:
    assert PROTOCOL_DOC.is_file()
    assert CONFIG.is_file()
    assert SCRIPT.is_file()


def test_transition_authorization_make_target_is_safe_and_has_no_sensitive_name() -> None:
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    safety_config = yaml.safe_load(SAFETY_CONFIG.read_text(encoding="utf-8"))

    assert "transition-authorization-audit:" in makefile_text
    assert "$(PY) scripts/transition_authorization_audit.py" in makefile_text
    assert "transition-authorization-audit" in safety_config["SAFE_METADATA_ONLY"]
    for forbidden_target in [
        "real-source-authorization-audit",
        "source-authorization-audit",
        "ingestion-authorization-audit",
        "api-authorization-audit",
        "qdrant-authorization-audit",
        "embedding-authorization-audit",
    ]:
        assert forbidden_target not in makefile_text
        assert forbidden_target not in safety_config["SAFE_METADATA_ONLY"]


def test_transition_authorization_script_has_no_destructive_network_or_process_tokens() -> None:
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


def test_transition_authorization_audit_returns_markdown(capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()

    status = module.main([])

    output = capsys.readouterr().out
    assert status == 0
    assert "# Transition authorization audit" in output
    assert "status: metadata_only_transition_authorization" in output
    assert "authorization_ready_for_review: true" in output
    assert "real_documents_allowed: false" in output
    assert "ingestion_allowed: true" in output
    assert "embeddings_allowed: true" in output
    assert "qdrant_allowed: false" in output
    assert "deferred_real_lot_count: 1" in output
    assert "authorization_decision_coverage_errors_count: 0" in output
    assert "## Authorization decision coverage errors" in output
    assert "no real document read" in output


@pytest.mark.parametrize("flag", [f for f in DANGEROUS_FLAGS if f not in AUTHORIZED_TRUE_FLAGS])
def test_transition_authorization_rejects_any_dangerous_flag_enabled(tmp_path, capsys, flag: str) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, **{flag: True})

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "authorization_ready_for_review: false" in output
    assert f"{flag} must be false" in output


@pytest.mark.parametrize("flag", list(AUTHORIZED_TRUE_FLAGS))
def test_transition_authorization_rejects_authorized_flag_if_false(tmp_path, capsys, flag: str) -> None:  # noqa: ANN001
    """An authorized-true flag set to false should be rejected."""
    module = _load_audit_module()
    path = _write_config(tmp_path, **{flag: False})

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert f"{flag} must be true" in output


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "controlled_readiness_ref",
            "wrong_readiness",
            "controlled_readiness_ref must be controlled_readiness_metadata_gate_v1",
        ),
        (
            "human_source_review_ref",
            "wrong_review",
            "human_source_review_ref must be human_source_review_metadata_policy_v1",
        ),
        (
            "source_admission_policy_ref",
            "wrong_policy",
            "source_admission_policy_ref must be source_admission_metadata_policy_v1",
        ),
        (
            "pedago_interface_ref",
            "wrong_interface",
            "pedago_interface_ref must be pedago_interface_metadata_contract_v1",
        ),
        (
            "retrieval_eval_ref",
            "wrong_eval",
            "retrieval_eval_ref must be math_terminale_specialite_metadata_retrieval_eval_v1",
        ),
        ("pilot_scope_ref", "wrong_scope", "pilot_scope_ref must be math_terminale_specialite_metadata_only_v1"),
    ],
)
def test_transition_authorization_rejects_invalid_lot_references(
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


def test_transition_authorization_rejects_unknown_declared_decision(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    decisions = config["allowed_authorization_decisions"]
    assert isinstance(decisions, list)
    decisions.append("authorize_real_corpus")
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "allowed_authorization_decisions contains unknown decision: authorize_real_corpus" in output


def test_transition_authorization_rejects_missing_required_authorization_field(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    fields = config["required_authorization_fields"]
    assert isinstance(fields, list)
    fields.remove("decision_reason")
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing required_authorization_fields: decision_reason" in output


def test_transition_authorization_requires_non_empty_authorization_cases(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config.pop("authorization_cases")
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "authorization_cases must be a non-empty list" in output


def test_transition_authorization_rejects_empty_authorization_cases(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, authorization_cases=[])

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "authorization_cases must be a non-empty list" in output


def test_transition_authorization_rejects_non_list_authorization_cases(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, authorization_cases="not-a-list")

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "authorization_cases must be a non-empty list" in output


def test_transition_authorization_rejects_non_mapping_authorization_case(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _authorization_cases(config)[0] = "not-a-mapping"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "authorization case at index 0 must be a mapping" in output


@pytest.mark.parametrize(
    ("decision", "message"),
    [
        (
            "authorize_metadata_only_preparation",
            "missing authorization case for decision: authorize_metadata_only_preparation",
        ),
        ("require_final_human_signoff", "missing authorization case for decision: require_final_human_signoff"),
        ("block_real_corpus_transition", "missing authorization case for decision: block_real_corpus_transition"),
        ("defer_to_separate_real_lot", "missing authorization case for decision: defer_to_separate_real_lot"),
    ],
)
def test_transition_authorization_rejects_missing_decision_coverage(
    tmp_path,
    capsys,
    decision: str,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["authorization_cases"] = [
        case for case in _authorization_cases(config) if isinstance(case, dict) and case.get("decision") != decision
    ]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


def test_transition_authorization_accepts_defer_reason_but_still_requires_full_decision_coverage(
    tmp_path,
    capsys,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["authorization_cases"] = [_case_by_id(config, "separate_real_lot_deferred")]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "defer_to_separate_real_lot requires decision_reason" not in output
    assert "missing authorization case for decision: defer_to_separate_real_lot" not in output


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("authorization_case_id", "", "authorization case index 0 authorization_case_id must be a non-empty string"),
        (
            "readiness_gate",
            "wrong_gate",
            "authorization metadata_preparation_authorized readiness_gate must be controlled_readiness_metadata_gate_v1",
        ),
        ("decision", "authorize_real_corpus", "authorization metadata_preparation_authorized decision must be allowed"),
        (
            "decision_reason",
            "",
            "authorization metadata_preparation_authorized decision_reason must be a non-empty string",
        ),
        (
            "final_human_signoff_required",
            False,
            "authorization metadata_preparation_authorized final_human_signoff_required must be true",
        ),
        (
            "rights_confirmation_required",
            False,
            "authorization metadata_preparation_authorized rights_confirmation_required must be true",
        ),
        (
            "provenance_confirmation_required",
            False,
            "authorization metadata_preparation_authorized provenance_confirmation_required must be true",
        ),
        (
            "pii_absence_required",
            False,
            "authorization metadata_preparation_authorized pii_absence_required must be true",
        ),
        (
            "rollback_plan_required",
            False,
            "authorization metadata_preparation_authorized rollback_plan_required must be true",
        ),
        (
            "checksum_plan_required",
            False,
            "authorization metadata_preparation_authorized checksum_plan_required must be true",
        ),
        (
            "separate_real_lot_required",
            False,
            "authorization metadata_preparation_authorized separate_real_lot_required must be true",
        ),
        (
            "real_corpus_authorized",
            True,
            "authorization metadata_preparation_authorized real_corpus_authorized must be false",
        ),
        ("real_file_authorized", True, "authorization metadata_preparation_authorized real_file_authorized must be false"),
        ("pipeline_authorized", True, "authorization metadata_preparation_authorized pipeline_authorized must be false"),
    ],
)
def test_transition_authorization_rejects_invalid_authorization_case_fields(
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


def test_transition_authorization_rejects_duplicate_authorization_case_id(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    cases = _authorization_cases(config)
    assert isinstance(cases[1], dict)
    cases[1]["authorization_case_id"] = "metadata_preparation_authorized"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "duplicate authorization_case_id: metadata_preparation_authorized" in output


@pytest.mark.parametrize(
    ("authorization_case_id", "reason", "message"),
    [
        (
            "real_corpus_blocked_until_separate_lot",
            "metadata_only_preparation_allowed",
            "block_real_corpus_transition requires decision_reason real_corpus_requires_separate_authorization",
        ),
        (
            "final_human_signoff_required",
            "metadata_only_preparation_allowed",
            "require_final_human_signoff requires decision_reason final_human_signoff_missing",
        ),
        (
            "metadata_preparation_authorized",
            "final_human_signoff_missing",
            "authorize_metadata_only_preparation requires decision_reason metadata_only_preparation_allowed",
        ),
        (
            "separate_real_lot_deferred",
            "metadata_only_preparation_allowed",
            "defer_to_separate_real_lot requires decision_reason separate_real_lot_required",
        ),
    ],
)
def test_transition_authorization_rejects_incoherent_decision_reason(
    tmp_path,
    capsys,
    authorization_case_id: str,
    reason: str,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _case_by_id(config, authorization_case_id)["decision_reason"] = reason
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("file_path", "data/raw/source.pdf", "authorization metadata_preparation_authorized forbidden field: file_path"),
        ("url", "https://example.invalid", "authorization metadata_preparation_authorized forbidden field: url"),
        ("source_uri", "data/raw/source.pdf", "authorization metadata_preparation_authorized forbidden field: source_uri"),
        ("content", "document body", "authorization metadata_preparation_authorized forbidden field: content"),
    ],
)
def test_transition_authorization_rejects_forbidden_authorization_fields(
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


def test_transition_authorization_rejects_non_mapping_config_without_traceback(tmp_path) -> None:
    path = tmp_path / "transition_authorization.yml"
    path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    result = _run_cli(config=path)

    assert result.returncode == 1
    assert "authorization_ready_for_review: false" in result.stdout
    assert "config must be a YAML mapping" in result.stdout
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_transition_authorization_does_not_modify_git_status() -> None:
    module = _load_audit_module()
    before = _git_status()

    status = module.main([])

    after = _git_status()
    assert status == 0
    assert after == before


def test_transition_authorization_does_not_create_data_staging() -> None:
    module = _load_audit_module()
    _staging_before = set(DATA_STAGING.rglob("*")) if DATA_STAGING.exists() else set()

    status = module.main([])

    assert status == 0
    # Staging may exist (legitimate content); verify module didn't modify it
    _staging_after = set(DATA_STAGING.rglob("*")) if DATA_STAGING.exists() else set()
    assert _staging_after == _staging_before, "module must not create/modify staging"


def test_transition_authorization_does_not_open_env(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    module = _load_audit_module()
    original_open = Path.open

    def guarded_open(self: Path, *args: object, **kwargs: object):  # noqa: ANN001
        if self.name == ".env":
            raise AssertionError(".env must not be opened")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    status = module.main(["--config", str(_write_config(tmp_path))])

    assert status == 0


def test_transition_authorization_cli_real_execution_returns_markdown() -> None:
    result = _run_cli()

    assert result.returncode == 0
    assert "# Transition authorization audit" in result.stdout
    assert "status: metadata_only_transition_authorization" in result.stdout
    assert result.stderr == ""


def test_transition_authorization_cli_python_optimized_mode_returns_markdown() -> None:
    result = _run_cli(optimized=True)

    assert result.returncode == 0
    assert "# Transition authorization audit" in result.stdout
    assert "authorization_ready_for_review: true" in result.stdout
    assert result.stderr == ""


def test_make_target_safety_audit_remains_green_after_transition_authorization_target() -> None:
    result = subprocess.run(
        ["make", "make-target-safety-audit"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "all_targets_classified: true" in result.stdout
    assert "transition-authorization-audit" in result.stdout
