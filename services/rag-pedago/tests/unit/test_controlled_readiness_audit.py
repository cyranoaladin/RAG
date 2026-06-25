from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from rag_pedago.paths import REPO_ROOT

CONFIG = REPO_ROOT / "configs/controlled_readiness.yml"
SAFETY_CONFIG = REPO_ROOT / "configs/make_target_safety.yml"
PROTOCOL_DOC = REPO_ROOT / "docs/CONTROLLED_READINESS_PROTOCOL.md"
SCRIPT = REPO_ROOT / "scripts/controlled_readiness_audit.py"
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
    spec = importlib.util.spec_from_file_location("controlled_readiness_audit", SCRIPT)
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
    path = tmp_path / "controlled_readiness.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _transition_checks(config: dict[str, object]) -> list[object]:
    checks = config["transition_checks"]
    assert isinstance(checks, list)
    return checks


def _gate_evidence(config: dict[str, object]) -> list[object]:
    evidence = config["gate_evidence"]
    assert isinstance(evidence, list)
    return evidence


def _first_check(config: dict[str, object]) -> dict[str, object]:
    check = _transition_checks(config)[0]
    assert isinstance(check, dict)
    return check


def _check_by_id(config: dict[str, object], transition_id: str) -> dict[str, object]:
    for check in _transition_checks(config):
        assert isinstance(check, dict)
        if check.get("transition_id") == transition_id:
            return check
    raise AssertionError(f"missing transition check {transition_id}")


def _evidence_by_gate(config: dict[str, object], gate_id: str) -> dict[str, object]:
    for evidence in _gate_evidence(config):
        assert isinstance(evidence, dict)
        if evidence.get("gate_id") == gate_id:
            return evidence
    raise AssertionError(f"missing gate evidence {gate_id}")


def _run_cli(*, optimized: bool = False, config: Path = CONFIG) -> subprocess.CompletedProcess[str]:
    command = ["python3"]
    if optimized:
        command.append("-O")
    command.extend(["scripts/controlled_readiness_audit.py", "--config", str(config)])
    return subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def _git_status() -> str:
    return subprocess.check_output(["git", "status", "--short", "--branch"], cwd=REPO_ROOT, text=True)


def test_controlled_readiness_artifacts_exist() -> None:
    assert PROTOCOL_DOC.is_file()
    assert CONFIG.is_file()
    assert SCRIPT.is_file()


def test_controlled_readiness_make_target_is_safe_and_has_no_sensitive_name() -> None:
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    safety_config = yaml.safe_load(SAFETY_CONFIG.read_text(encoding="utf-8"))

    assert "controlled-readiness-audit:" in makefile_text
    assert "$(PY) scripts/controlled_readiness_audit.py" in makefile_text
    assert "controlled-readiness-audit" in safety_config["SAFE_METADATA_ONLY"]
    for forbidden_target in [
        "real-source-transition-audit",
        "source-ingestion-readiness-audit",
        "ingestion-readiness-audit",
        "api-readiness-audit",
        "qdrant-readiness-audit",
        "embedding-readiness-audit",
    ]:
        assert forbidden_target not in makefile_text
        assert forbidden_target not in safety_config["SAFE_METADATA_ONLY"]


def test_controlled_readiness_script_has_no_destructive_network_or_process_tokens() -> None:
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


def test_controlled_readiness_audit_returns_markdown(capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()

    status = module.main([])

    output = capsys.readouterr().out
    assert status == 0
    assert "# Controlled readiness audit" in output
    assert "status: metadata_only_controlled_readiness" in output
    assert "readiness_ready_for_review: true" in output
    assert "real_documents_allowed: false" in output
    assert "ingestion_allowed: false" in output
    assert "embeddings_allowed: false" in output
    assert "qdrant_allowed: false" in output
    assert "no real document read" in output
    for section in [
        "## Transition checks",
        "## Gate evidence",
        "## Gate evidence errors",
        "## Gate coverage errors",
        "## Sensitive target errors",
        "## Transition status decision errors",
        "## Required gates",
        "## Allowed transition decisions",
        "## Required transition fields",
        "## Blocking issues",
        "## Explicit non-actions",
    ]:
        assert section in output


@pytest.mark.parametrize("flag", DANGEROUS_FLAGS)
def test_controlled_readiness_rejects_any_dangerous_flag_enabled(tmp_path, capsys, flag: str) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, **{flag: True})

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "readiness_ready_for_review: false" in output
    assert f"{flag} must be false" in output


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("pilot_scope_ref", "wrong_scope", "pilot_scope_ref must be math_terminale_specialite_metadata_only_v1"),
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
        (
            "source_admission_policy_ref",
            "wrong_policy",
            "source_admission_policy_ref must be source_admission_metadata_policy_v1",
        ),
        (
            "human_source_review_ref",
            "wrong_review",
            "human_source_review_ref must be human_source_review_metadata_policy_v1",
        ),
    ],
)
def test_controlled_readiness_rejects_invalid_lot_references(
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


def test_controlled_readiness_rejects_missing_required_gate(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    gates = config["required_gates"]
    assert isinstance(gates, list)
    gates.remove("project_doctor_gate")
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing required_gates: project_doctor_gate" in output


def test_controlled_readiness_rejects_unknown_declared_decision(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    decisions = config["allowed_transition_decisions"]
    assert isinstance(decisions, list)
    decisions.append("start_real_corpus")
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "allowed_transition_decisions contains unknown decision: start_real_corpus" in output


def test_controlled_readiness_rejects_missing_required_transition_field(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    fields = config["required_transition_fields"]
    assert isinstance(fields, list)
    fields.remove("decision_reason")
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing required_transition_fields: decision_reason" in output


def test_controlled_readiness_rejects_missing_required_gate_evidence_field(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    fields = config["required_gate_evidence_fields"]
    assert isinstance(fields, list)
    fields.remove("safe_target")
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing required_gate_evidence_fields: safe_target" in output


def test_controlled_readiness_rejects_malformed_transition_check(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _transition_checks(config)[0] = "not-a-mapping"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "transition check at index 0 must be a mapping" in output


def test_controlled_readiness_rejects_missing_gate_evidence(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config.pop("gate_evidence")
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "gate_evidence must be a non-empty list" in output


def test_controlled_readiness_rejects_empty_gate_evidence(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, gate_evidence=[])

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "gate_evidence must be a non-empty list" in output


def test_controlled_readiness_rejects_non_list_gate_evidence(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, gate_evidence="not-a-list")

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "gate_evidence must be a non-empty list" in output


def test_controlled_readiness_rejects_non_mapping_gate_evidence_entry(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _gate_evidence(config)[0] = "not-a-mapping"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "gate_evidence at index 0 must be a mapping" in output


def test_controlled_readiness_rejects_missing_gate_evidence_for_required_gate(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["gate_evidence"] = [
        evidence for evidence in _gate_evidence(config) if isinstance(evidence, dict) and evidence.get("gate_id") != "pilot_scope_gate"
    ]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing gate_evidence for required gate: pilot_scope_gate" in output


def test_controlled_readiness_rejects_duplicate_gate_evidence(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    first = dict(_gate_evidence(config)[0])
    _gate_evidence(config).append(first)
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "duplicate gate_evidence gate_id: pilot_scope_gate" in output


def test_controlled_readiness_rejects_unknown_gate_evidence_gate_id(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _evidence_by_gate(config, "pilot_scope_gate")["gate_id"] = "unknown_gate"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "gate_evidence unknown_gate gate_id must be declared in required_gates" in output


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("evidence_kind", "real_document", "gate_evidence pilot_scope_gate evidence_kind must be allowed"),
        ("evidence_ref", "", "gate_evidence pilot_scope_gate evidence_ref must be a non-empty string"),
        ("expected_status", "blocked", "gate_evidence pilot_scope_gate expected_status must be passed"),
        ("destructive_action_allowed", True, "gate_evidence pilot_scope_gate destructive_action_allowed must be false"),
        ("real_document_allowed", True, "gate_evidence pilot_scope_gate real_document_allowed must be false"),
        ("network_allowed", True, "gate_evidence pilot_scope_gate network_allowed must be false"),
    ],
)
def test_controlled_readiness_rejects_invalid_gate_evidence_fields(
    tmp_path,
    capsys,
    field: str,
    value: object,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _evidence_by_gate(config, "pilot_scope_gate")[field] = value
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


@pytest.mark.parametrize(
    ("evidence_ref", "message"),
    [
        ("https://example.invalid/report.md", "gate_evidence pilot_scope_gate evidence_ref must not contain a URL"),
        ("data/reports/source.pdf", "gate_evidence pilot_scope_gate evidence_ref must not point to a real document"),
        ("data/staging/report.md", "gate_evidence pilot_scope_gate evidence_ref must not contain data/staging"),
        ("source_uri:data/reports/report.md", "gate_evidence pilot_scope_gate evidence_ref must not contain source_uri"),
    ],
)
def test_controlled_readiness_rejects_sensitive_evidence_ref(
    tmp_path,
    capsys,
    evidence_ref: str,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _evidence_by_gate(config, "pilot_scope_gate")["evidence_ref"] = evidence_ref
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


@pytest.mark.parametrize(
    ("safe_target", "message"),
    [
        ("source-ingest-audit", "gate_evidence pilot_scope_gate safe_target contains sensitive term: ingest"),
        ("api-readiness-audit", "gate_evidence pilot_scope_gate safe_target contains sensitive term: api"),
        ("qdrant-readiness-audit", "gate_evidence pilot_scope_gate safe_target contains sensitive term: qdrant"),
        ("embedding-readiness-audit", "gate_evidence pilot_scope_gate safe_target contains sensitive term: embed"),
    ],
)
def test_controlled_readiness_rejects_sensitive_safe_target(
    tmp_path,
    capsys,
    safe_target: str,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _evidence_by_gate(config, "pilot_scope_gate")["safe_target"] = safe_target
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("transition_id", "", "transition index 0 transition_id must be a non-empty string"),
        ("gate_id", "unknown_gate", "transition all_metadata_gates_green gate_id must be declared in required_gates"),
        ("gate_status", "ready", "transition all_metadata_gates_green gate_status must be allowed"),
        ("decision", "start_real_corpus", "transition all_metadata_gates_green decision must be allowed"),
        ("decision_reason", "", "transition all_metadata_gates_green decision_reason must be a non-empty string"),
        ("human_signoff_required", False, "transition all_metadata_gates_green human_signoff_required must be true"),
        ("real_corpus_allowed", True, "transition all_metadata_gates_green real_corpus_allowed must be false"),
        ("real_file_allowed", True, "transition all_metadata_gates_green real_file_allowed must be false"),
        ("external_url_allowed", True, "transition all_metadata_gates_green external_url_allowed must be false"),
        ("rollback_required", False, "transition all_metadata_gates_green rollback_required must be true"),
        ("next_lot_required", False, "transition all_metadata_gates_green next_lot_required must be true"),
    ],
)
def test_controlled_readiness_rejects_invalid_transition_check_fields(
    tmp_path,
    capsys,
    field: str,
    value: object,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_check(config)[field] = value
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


def test_controlled_readiness_rejects_duplicate_transition_id(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    checks = _transition_checks(config)
    assert isinstance(checks[1], dict)
    checks[1]["transition_id"] = "all_metadata_gates_green"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "duplicate transition_id: all_metadata_gates_green" in output


@pytest.mark.parametrize(
    ("transition_id", "reason", "message"),
    [
        (
            "real_corpus_deferred",
            "metadata_only_gates_valid",
            "defer_real_corpus_lot requires decision_reason real_corpus_requires_separate_lot",
        ),
        (
            "missing_human_signoff",
            "metadata_only_gates_valid",
            "require_human_signoff requires decision_reason human_signoff_missing",
        ),
    ],
)
def test_controlled_readiness_rejects_incoherent_decision_reason(
    tmp_path,
    capsys,
    transition_id: str,
    reason: str,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _check_by_id(config, transition_id)["decision_reason"] = reason
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


def test_controlled_readiness_rejects_continue_metadata_only_with_real_corpus_allowed(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _check_by_id(config, "all_metadata_gates_green")["real_corpus_allowed"] = True
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "transition all_metadata_gates_green real_corpus_allowed must be false" in output


@pytest.mark.parametrize(
    ("transition_id", "gate_status", "decision", "decision_reason", "message"),
    [
        (
            "all_metadata_gates_green",
            "passed",
            "defer_real_corpus_lot",
            "real_corpus_requires_separate_lot",
            "transition all_metadata_gates_green gate_status passed cannot use decision defer_real_corpus_lot",
        ),
        (
            "missing_human_signoff",
            "blocked",
            "continue_metadata_only",
            "metadata_only_gates_valid",
            "transition missing_human_signoff gate_status blocked cannot use decision continue_metadata_only",
        ),
        (
            "real_corpus_deferred",
            "deferred",
            "continue_metadata_only",
            "metadata_only_gates_valid",
            "transition real_corpus_deferred gate_status deferred cannot use decision continue_metadata_only",
        ),
    ],
)
def test_controlled_readiness_rejects_incoherent_gate_status_decision(
    tmp_path,
    capsys,
    transition_id: str,
    gate_status: str,
    decision: str,
    decision_reason: str,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    check = _check_by_id(config, transition_id)
    check["gate_status"] = gate_status
    check["decision"] = decision
    check["decision_reason"] = decision_reason
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


@pytest.mark.parametrize(
    "transition_id",
    [
        "real_corpus_deferred",
        "missing_human_signoff",
    ],
)
def test_controlled_readiness_accepts_coherent_deferred_and_blocked_decisions(tmp_path, capsys, transition_id: str) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    checks = [_check_by_id(config, transition_id)]
    config["transition_checks"] = checks
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 0
    assert "readiness_ready_for_review: true" in output


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("file_path", "data/raw/source.pdf", "transition all_metadata_gates_green forbidden field: file_path"),
        ("url", "https://example.invalid", "transition all_metadata_gates_green forbidden field: url"),
        ("content", "document body", "transition all_metadata_gates_green forbidden field: content"),
    ],
)
def test_controlled_readiness_rejects_forbidden_transition_fields(
    tmp_path,
    capsys,
    field: str,
    value: str,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_check(config)[field] = value
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


def test_controlled_readiness_rejects_non_mapping_config_without_traceback(tmp_path) -> None:
    path = tmp_path / "controlled_readiness.yml"
    path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    result = _run_cli(config=path)

    assert result.returncode == 1
    assert "readiness_ready_for_review: false" in result.stdout
    assert "config must be a YAML mapping" in result.stdout
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_controlled_readiness_does_not_modify_git_status() -> None:
    module = _load_audit_module()
    before = _git_status()

    status = module.main([])

    after = _git_status()
    assert status == 0
    assert after == before


def test_controlled_readiness_does_not_create_data_staging() -> None:
    module = _load_audit_module()
    _staging_before = set(DATA_STAGING.rglob("*")) if DATA_STAGING.exists() else set()

    status = module.main([])

    assert status == 0
    # Staging may exist (legitimate content); verify module didn't modify it
    _staging_after = set(DATA_STAGING.rglob("*")) if DATA_STAGING.exists() else set()
    assert _staging_after == _staging_before, "module must not create/modify staging"


def test_controlled_readiness_does_not_open_env(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    module = _load_audit_module()
    original_open = Path.open

    def guarded_open(self: Path, *args: object, **kwargs: object):  # noqa: ANN001
        if self.name == ".env":
            raise AssertionError(".env must not be opened")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    status = module.main(["--config", str(_write_config(tmp_path))])

    assert status == 0


def test_controlled_readiness_cli_real_execution_returns_markdown() -> None:
    result = _run_cli()

    assert result.returncode == 0
    assert "# Controlled readiness audit" in result.stdout
    assert "status: metadata_only_controlled_readiness" in result.stdout
    assert result.stderr == ""


def test_controlled_readiness_cli_python_optimized_mode_returns_markdown() -> None:
    result = _run_cli(optimized=True)

    assert result.returncode == 0
    assert "# Controlled readiness audit" in result.stdout
    assert "readiness_ready_for_review: true" in result.stdout
    assert result.stderr == ""


def test_make_target_safety_audit_remains_green_after_controlled_readiness_target() -> None:
    result = subprocess.run(
        ["make", "make-target-safety-audit"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "all_targets_classified: true" in result.stdout
    assert "controlled-readiness-audit" in result.stdout
