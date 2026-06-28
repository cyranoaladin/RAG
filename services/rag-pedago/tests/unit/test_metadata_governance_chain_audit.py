from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from rag_pedago.paths import REPO_ROOT

CONFIG = REPO_ROOT / "configs/metadata_governance_chain.yml"
SAFETY_CONFIG = REPO_ROOT / "configs/make_target_safety.yml"
PROTOCOL_DOC = REPO_ROOT / "docs/METADATA_GOVERNANCE_CHAIN_PROTOCOL.md"
SCRIPT = REPO_ROOT / "scripts/metadata_governance_chain_audit.py"
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
    spec = importlib.util.spec_from_file_location("metadata_governance_chain_audit", SCRIPT)
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
    path = tmp_path / "metadata_governance_chain.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _chain_lots(config: dict[str, object]) -> list[object]:
    lots = config["required_chain_lots"]
    assert isinstance(lots, list)
    return lots


def _first_lot(config: dict[str, object]) -> dict[str, object]:
    lot = _chain_lots(config)[0]
    assert isinstance(lot, dict)
    return lot


def _run_cli(*, optimized: bool = False, config: Path = CONFIG) -> subprocess.CompletedProcess[str]:
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend(["scripts/metadata_governance_chain_audit.py", "--config", str(config)])
    return subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def _git_status() -> str:
    return subprocess.check_output(["git", "status", "--short", "--branch"], cwd=REPO_ROOT, text=True)


def test_metadata_governance_chain_artifacts_exist() -> None:
    assert PROTOCOL_DOC.is_file()
    assert CONFIG.is_file()
    assert SCRIPT.is_file()


def test_metadata_governance_chain_make_target_is_safe() -> None:
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    safety_config = yaml.safe_load(SAFETY_CONFIG.read_text(encoding="utf-8"))

    assert "metadata-governance-chain-audit:" in makefile_text
    assert "$(PY) scripts/metadata_governance_chain_audit.py" in makefile_text
    assert "metadata-governance-chain-audit" in safety_config["SAFE_METADATA_ONLY"]


def test_metadata_governance_chain_does_not_add_sensitive_target_names() -> None:
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    safety_config = yaml.safe_load(SAFETY_CONFIG.read_text(encoding="utf-8"))
    safe_targets = safety_config["SAFE_METADATA_ONLY"]
    forbidden_targets = [
        "real-source-audit",
        "corpus-readiness-audit",
        "source-chain-audit",
        "ingestion-chain-audit",
        "api-chain-audit",
        "qdrant-chain-audit",
        "embedding-chain-audit",
    ]

    for target in forbidden_targets:
        assert target not in makefile_text
        assert target not in safe_targets


def test_metadata_governance_chain_script_has_no_process_or_network_tokens() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden_tokens = ["subprocess", "requests", "httpx", "urllib", "socket"]
    assert not any(token in text for token in forbidden_tokens)


def test_metadata_governance_chain_script_has_no_destructive_tokens() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden_tokens = ["unlink(", "remove(", "rmdir(", "shutil.rmtree", "shutil.move"]
    assert not any(token in text for token in forbidden_tokens)


def test_metadata_governance_chain_script_has_no_literal_destructive_shell_tokens() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden_literals = [
        "git clean",
        "find -delete",
        "rm -rf",
    ]
    assert not any(token in text for token in forbidden_literals)


def test_metadata_governance_chain_audit_returns_markdown(capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()

    status = module.main([])

    output = capsys.readouterr().out
    assert status == 0
    assert "# Metadata governance chain audit" in output
    assert "status: metadata_only_governance_chain" in output
    assert "chain_ready_for_review: true" in output
    assert "real_documents_allowed: false" in output
    assert "ingestion_allowed: false" in output
    assert "embeddings_allowed: false" in output
    assert "qdrant_allowed: false" in output
    assert "no real document read" in output


@pytest.mark.parametrize("flag", DANGEROUS_FLAGS)
def test_metadata_governance_chain_rejects_any_dangerous_flag_enabled(tmp_path, capsys, flag: str) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, **{flag: True})

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "chain_ready_for_review: false" in output
    assert f"{flag} must be false" in output


def test_metadata_governance_chain_rejects_wrong_latest_committed_lot(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, latest_committed_lot="17H")

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "latest_committed_lot must be 17I" in output


def test_metadata_governance_chain_rejects_wrong_latest_commit_ref(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, latest_commit_ref="wrong")

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "latest_commit_ref must be cbc4655e51c9e09e396cff957620359c9005b2e9" in output


def test_metadata_governance_chain_rejects_missing_required_lot(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["required_chain_lots"] = [lot for lot in _chain_lots(config) if isinstance(lot, dict) and lot["lot_id"] != "17C"]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing required chain lot: 17C" in output


def test_metadata_governance_chain_rejects_duplicate_required_lot(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    lots = _chain_lots(config)
    lots.append(dict(_first_lot(config)))
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "duplicate chain lot: 17C" in output


@pytest.mark.parametrize("value", [None, [], "not-a-list"])
def test_metadata_governance_chain_rejects_malformed_required_chain_lots(tmp_path, capsys, value: object) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, required_chain_lots=value)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "required_chain_lots must be a non-empty list" in output


def test_metadata_governance_chain_rejects_non_mapping_lot_entry(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["required_chain_lots"] = ["not-a-mapping"]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "chain lot at index 0 must be a mapping" in output


@pytest.mark.parametrize("field", ["config_ref", "report_ref", "make_target"])
def test_metadata_governance_chain_rejects_missing_lot_required_field(tmp_path, capsys, field: str) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_lot(config).pop(field)
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert f"lot 17C missing required field {field}" in output


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("config_ref", "https://example.test/config.yml", "unsafe path for 17C config_ref"),
        ("protocol_ref", "data/staging/protocol.md", "unsafe path for 17C protocol_ref"),
        ("script_ref", ".env", "unsafe path for 17C script_ref"),
        ("report_ref", "docs/sample.pdf", "unsafe path for 17C report_ref"),
    ],
)
def test_metadata_governance_chain_rejects_unsafe_paths(
    tmp_path,
    capsys,
    field: str,
    value: str,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_lot(config)[field] = value
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


@pytest.mark.parametrize("target", ["ingest", "api"])
def test_metadata_governance_chain_rejects_sensitive_make_target(tmp_path, capsys, target: str) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_lot(config)["make_target"] = target
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert f"unsafe make target for 17C: {target}" in output


def test_metadata_governance_chain_rejects_make_target_not_classified_safe_metadata_only(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_lot(config)["make_target"] = "typecheck"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "make_target typecheck must be classified SAFE_METADATA_ONLY" in output


def test_metadata_governance_chain_rejects_missing_referenced_file(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_lot(config)["protocol_ref"] = "docs/MISSING_METADATA_PROTOCOL.md"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing referenced file for 17C protocol_ref" in output


def test_metadata_governance_chain_rejects_config_without_expected_status(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_lot(config)["expected_status"] = "impossible_status"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "config for 17C missing expected_status impossible_status" in output


def test_metadata_governance_chain_rejects_script_containing_process_token(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_lot(config)["script_ref"] = "tests/unit/test_transition_authorization_audit.py"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "script for 17C contains forbidden token" in output


def test_metadata_governance_chain_rejects_report_without_expected_marker(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_lot(config)["report_ref"] = "data/reports/codex_lot_17I_transition_authorization.md"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "report for 17C missing expected_ready_marker" in output


def test_metadata_governance_chain_rejects_unknown_allowed_chain_decision(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    decisions = config["allowed_chain_decisions"]
    assert isinstance(decisions, list)
    decisions.append("publish_real_corpus")
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "allowed_chain_decisions contains unknown decision: publish_real_corpus" in output


def test_metadata_governance_chain_rejects_unknown_chain_decision(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    chain_decision = config["chain_decision"]
    assert isinstance(chain_decision, dict)
    chain_decision["decision"] = "publish_real_corpus"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "chain_decision.decision must be allowed" in output


@pytest.mark.parametrize(
    "decision",
    [
        "chain_requires_human_review",
        "chain_blocked_for_real_corpus",
        "chain_requires_followup_metadata_lot",
    ],
)
def test_metadata_governance_chain_rejects_alternative_chain_decision(
    tmp_path,
    capsys,
    decision: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    chain_decision = config["chain_decision"]
    assert isinstance(chain_decision, dict)
    chain_decision["decision"] = decision
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "chain_ready_for_review: false" in output
    assert "chain_decision.decision must be chain_ready_for_metadata_review" in output
    assert "Traceback" not in output


def test_metadata_governance_chain_rejects_wrong_final_chain_decision_reason(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    chain_decision = config["chain_decision"]
    assert isinstance(chain_decision, dict)
    chain_decision["decision_reason"] = "wrong_reason"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "chain_ready_for_review: false" in output
    assert "chain_decision.decision_reason must be metadata_governance_chain_complete" in output
    assert "Traceback" not in output


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("real_corpus_allowed", True, "chain_decision.real_corpus_allowed must be false"),
        ("real_file_allowed", True, "chain_decision.real_file_allowed must be false"),
        ("pipeline_allowed", True, "chain_decision.pipeline_allowed must be false"),
        ("human_review_required", False, "chain_decision.human_review_required must be true"),
        ("followup_lot_required", False, "chain_decision.followup_lot_required must be true"),
    ],
)
def test_metadata_governance_chain_rejects_unsafe_chain_decision_fields(
    tmp_path,
    capsys,
    field: str,
    value: bool,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    chain_decision = config["chain_decision"]
    assert isinstance(chain_decision, dict)
    chain_decision[field] = value
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


def test_metadata_governance_chain_rejects_missing_chain_decision_reason(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    chain_decision = config["chain_decision"]
    assert isinstance(chain_decision, dict)
    chain_decision["decision_reason"] = ""
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "chain_decision.decision_reason must be a non-empty string" in output


def test_metadata_governance_chain_rejects_non_mapping_config_without_traceback(tmp_path) -> None:
    path = tmp_path / "not_mapping.yml"
    path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    result = _run_cli(config=path)

    assert result.returncode == 1
    assert "chain_ready_for_review: false" in result.stdout
    assert "config must be a YAML mapping" in result.stdout
    assert "Traceback" not in result.stderr


def test_metadata_governance_chain_audit_does_not_modify_git_status() -> None:
    module = _load_audit_module()
    before = _git_status()

    status = module.main([])

    after = _git_status()
    assert status == 0
    assert after == before


def test_metadata_governance_chain_audit_does_not_create_data_staging() -> None:
    module = _load_audit_module()
    _staging_before = set(DATA_STAGING.rglob("*")) if DATA_STAGING.exists() else set()

    status = module.main([])

    assert status == 0
    # Staging may exist (legitimate content); verify module didn't modify it
    _staging_after = set(DATA_STAGING.rglob("*")) if DATA_STAGING.exists() else set()
    assert _staging_after == _staging_before, "module must not create/modify staging"


def test_metadata_governance_chain_audit_does_not_open_env(monkeypatch, tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    original_read_text = Path.read_text
    config = _base_config()
    _first_lot(config)["config_ref"] = ".env"
    path = _write_config(tmp_path, config)

    def guarded_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == ".env":
            raise AssertionError(".env must not be opened")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "unsafe path for 17C config_ref" in output


def test_metadata_governance_chain_cli_returns_zero() -> None:
    result = _run_cli()

    assert result.returncode == 0
    assert "chain_ready_for_review: true" in result.stdout


def test_metadata_governance_chain_cli_optimized_returns_zero() -> None:
    result = _run_cli(optimized=True)

    assert result.returncode == 0
    assert "chain_ready_for_review: true" in result.stdout


def test_metadata_governance_chain_keeps_make_target_safety_audit_green() -> None:
    result = subprocess.run(
        ["make", "make-target-safety-audit"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "all_targets_classified: true" in result.stdout
