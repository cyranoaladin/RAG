from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from rag_pedago.paths import REPO_ROOT

CONFIG = REPO_ROOT / "configs/source_admission_policy.yml"
SAFETY_CONFIG = REPO_ROOT / "configs/make_target_safety.yml"
PROTOCOL_DOC = REPO_ROOT / "docs/SOURCE_ADMISSION_POLICY_PROTOCOL.md"
SCRIPT = REPO_ROOT / "scripts/source_admission_policy_audit.py"
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
    spec = importlib.util.spec_from_file_location("source_admission_policy_audit", SCRIPT)
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
    path = tmp_path / "source_admission_policy.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _first_source(config: dict[str, object]) -> dict[str, object]:
    sources = config["candidate_sources"]
    assert isinstance(sources, list)
    source = sources[0]
    assert isinstance(source, dict)
    return source


def _candidate_sources(config: dict[str, object]) -> list[object]:
    sources = config["candidate_sources"]
    assert isinstance(sources, list)
    return sources


def _unknown_rights_source(config: dict[str, object]) -> dict[str, object]:
    sources = config["candidate_sources"]
    assert isinstance(sources, list)
    source = sources[2]
    assert isinstance(source, dict)
    return source


def _run_cli(*, optimized: bool = False, config: Path = CONFIG) -> subprocess.CompletedProcess[str]:
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend(["scripts/source_admission_policy_audit.py", "--config", str(config)])
    return subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def _git_status() -> str:
    return subprocess.check_output(["git", "status", "--short", "--branch"], cwd=REPO_ROOT, text=True)


def test_source_admission_policy_artifacts_exist() -> None:
    assert PROTOCOL_DOC.is_file()
    assert CONFIG.is_file()
    assert SCRIPT.is_file()


def test_source_admission_policy_make_target_is_safe_and_has_no_sensitive_name() -> None:
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    safety_config = yaml.safe_load(SAFETY_CONFIG.read_text(encoding="utf-8"))

    assert "source-admission-policy-audit:" in makefile_text
    assert "$(PY) scripts/source_admission_policy_audit.py" in makefile_text
    assert "source-admission-policy-audit" in safety_config["SAFE_METADATA_ONLY"]
    for forbidden_target in [
        "source-ingestion-audit",
        "ingestion-policy-audit",
        "ingest-source-audit",
        "api-source-audit",
        "upload-source-audit",
    ]:
        assert forbidden_target not in makefile_text
        assert forbidden_target not in safety_config["SAFE_METADATA_ONLY"]


def test_source_admission_policy_script_has_no_destructive_network_or_process_tokens() -> None:
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


def test_source_admission_policy_audit_returns_markdown(capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()

    status = module.main([])

    output = capsys.readouterr().out
    assert status == 0
    assert "# Source admission policy audit" in output
    assert "status: metadata_only_source_admission_policy" in output
    assert "policy_ready_for_review: true" in output
    assert "real_documents_allowed: false" in output
    assert "ingestion_allowed: false" in output
    assert "embeddings_allowed: false" in output
    assert "qdrant_allowed: false" in output
    assert "no real document read" in output
    for section in [
        "## Candidate sources",
        "## Allowed source kinds",
        "## Forbidden source kinds",
        "## Required source fields",
        "## License policy errors",
        "## Refusal reason errors",
        "## Source identity errors",
        "## Human review errors",
        "## Source kind policy errors",
        "## Blocking issues",
        "## Explicit non-actions",
    ]:
        assert section in output
    for counter in [
        "license_policy_errors_count: 0",
        "refusal_reason_errors_count: 0",
        "source_identity_errors_count: 0",
        "human_review_errors_count: 0",
        "source_kind_policy_errors_count: 0",
    ]:
        assert counter in output


@pytest.mark.parametrize("flag", DANGEROUS_FLAGS)
def test_source_admission_policy_rejects_any_dangerous_flag_enabled(
    tmp_path,
    capsys,
    flag: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    path = _write_config(tmp_path, **{flag: True})

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "policy_ready_for_review: false" in output
    assert f"{flag} must be false" in output


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("policy_id", "wrong_policy", "policy_id must be source_admission_metadata_policy_v1"),
        (
            "pilot_scope_ref",
            "wrong_scope",
            "pilot_scope_ref must be math_terminale_specialite_metadata_only_v1",
        ),
        (
            "pedago_interface_ref",
            "wrong_contract",
            "pedago_interface_ref must be pedago_interface_metadata_contract_v1",
        ),
    ],
)
def test_source_admission_policy_rejects_invalid_policy_references(
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


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("real_file_attached", True, "source official_programme_metadata_reference real_file_attached must be false"),
        (
            "external_url_required",
            True,
            "source official_programme_metadata_reference external_url_required must be false",
        ),
        ("file_path", "data/raw/source.pdf", "source official_programme_metadata_reference forbidden field: file_path"),
        ("url", "https://example.invalid", "source official_programme_metadata_reference forbidden field: url"),
        ("content", "document body", "source official_programme_metadata_reference forbidden field: content"),
    ],
)
def test_source_admission_policy_rejects_forbidden_source_fields(
    tmp_path,
    capsys,
    field: str,
    value: object,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_source(config)[field] = value
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


def test_source_admission_policy_rejects_admit_with_unknown_rights(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    source = _first_source(config)
    source["rights_status"] = "unknown"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "source official_programme_metadata_reference admit_metadata_only requires safe rights_status" in output


def test_source_admission_policy_rejects_unknown_provenance(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_source(config)["provenance"] = "external_unchecked"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "source official_programme_metadata_reference provenance must be declared" in output


def test_source_admission_policy_rejects_invalid_visibility(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_source(config)["visibility"] = "public"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "source official_programme_metadata_reference visibility must be internal_review_only or blocked" in output


def test_source_admission_policy_rejects_admitted_private_data(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_source(config)["pii_status"] = "private_student_data"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "source official_programme_metadata_reference admit_metadata_only requires no_personal_data" in output


def test_source_admission_policy_rejects_unknown_rights_without_refusal(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _unknown_rights_source(config)["admission_decision"] = "require_human_review"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "source refused_unknown_rights_example unknown_rights requires refuse_unknown_rights" in output


def test_source_admission_policy_rejects_private_student_data_without_refusal(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    source = _first_source(config)
    source["source_kind"] = "private_student_data"
    source["pii_status"] = "contains_private_student_data"
    source["admission_decision"] = "require_human_review"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "source official_programme_metadata_reference private_student_data requires refuse_private_data" in output


def test_source_admission_policy_rejects_source_kind_not_allowed(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_source(config)["source_kind"] = "blog_post"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "source official_programme_metadata_reference source_kind must be declared" in output


def test_source_admission_policy_rejects_unknown_admission_decision(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_source(config)["admission_decision"] = "publish_now"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "source official_programme_metadata_reference admission_decision must be allowed" in output


def test_source_admission_policy_rejects_malformed_source(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["candidate_sources"] = ["not-a-mapping"]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "source at index 0 must be a mapping" in output


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_id", "", "source index 0 source_id must be a non-empty string"),
        ("title", "", "source official_programme_metadata_reference title must be a non-empty string"),
    ],
)
def test_source_admission_policy_rejects_empty_identity_fields(
    tmp_path,
    capsys,
    field: str,
    value: object,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_source(config)[field] = value
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "source_identity_errors_count: 1" in output
    assert message in output


def test_source_admission_policy_rejects_duplicate_source_id(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    sources = _candidate_sources(config)
    assert isinstance(sources[1], dict)
    sources[1]["source_id"] = "official_programme_metadata_reference"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "source_identity_errors_count: 1" in output
    assert "duplicate source_id: official_programme_metadata_reference" in output


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (False, "source official_programme_metadata_reference human_review_required must be true"),
        ("yes", "source official_programme_metadata_reference human_review_required must be true"),
    ],
)
def test_source_admission_policy_requires_human_review_true(
    tmp_path,
    capsys,
    value: object,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_source(config)["human_review_required"] = value
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "human_review_errors_count: 1" in output
    assert message in output


def test_source_admission_policy_rejects_missing_required_source_field(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    del _first_source(config)["license_status"]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "source official_programme_metadata_reference missing required field license_status" in output


@pytest.mark.parametrize(
    ("license_status", "message"),
    [
        ("unknown", "source official_programme_metadata_reference admit_metadata_only requires safe license_status"),
        (
            "external_unverified",
            "source official_programme_metadata_reference admit_metadata_only requires safe license_status",
        ),
    ],
)
def test_source_admission_policy_rejects_admit_with_unsafe_license(
    tmp_path,
    capsys,
    license_status: str,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_source(config)["license_status"] = license_status
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "license_policy_errors_count: 1" in output
    assert message in output


def test_source_admission_policy_accepts_refuse_unknown_rights_with_unknown_license(capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()

    status = module.main([])

    output = capsys.readouterr().out
    assert status == 0
    assert "refused_unknown_rights_example: refuse_unknown_rights" in output
    assert "license_policy_errors_count: 0" in output


@pytest.mark.parametrize(
    ("decision", "reason", "message"),
    [
        (
            "admit_metadata_only",
            "rights_unknown",
            "source official_programme_metadata_reference refusal_reason must be none",
        ),
        (
            "refuse_unknown_rights",
            "none",
            "source official_programme_metadata_reference refusal_reason must be rights_unknown",
        ),
        (
            "refuse_private_data",
            "none",
            "source official_programme_metadata_reference refusal_reason must be private_student_data",
        ),
        (
            "refuse_real_document",
            "none",
            "source official_programme_metadata_reference refusal_reason must be real_document",
        ),
        (
            "require_human_review",
            "none",
            "source official_programme_metadata_reference refusal_reason must be human_review_required",
        ),
    ],
)
def test_source_admission_policy_requires_refusal_reason_matching_decision(
    tmp_path,
    capsys,
    decision: str,
    reason: str,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    source = _first_source(config)
    source["admission_decision"] = decision
    source["refusal_reason"] = reason
    if decision == "refuse_unknown_rights":
        source["rights_status"] = "unknown"
        source["license_status"] = "unknown"
    if decision == "refuse_private_data":
        source["source_kind"] = "private_student_data"
        source["pii_status"] = "private_student_data"
    if decision == "refuse_real_document":
        source["source_kind"] = "pdf_file"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "refusal_reason_errors_count: 1" in output
    assert message in output


@pytest.mark.parametrize(
    ("config_field", "value", "message"),
    [
        ("allowed_source_kinds", "pdf_file", "allowed_source_kinds must not contain forbidden kind: pdf_file"),
        (
            "allowed_source_kinds",
            "unknown_rights",
            "allowed_source_kinds must not contain forbidden kind: unknown_rights",
        ),
        (
            "forbidden_source_kinds",
            "synthetic_learning_resource",
            "forbidden_source_kinds must not contain allowed kind: synthetic_learning_resource",
        ),
        (
            "allowed_admission_decisions",
            "publish_now",
            "allowed_admission_decisions contains unknown decision: publish_now",
        ),
    ],
)
def test_source_admission_policy_rejects_invalid_policy_lists(
    tmp_path,
    capsys,
    config_field: str,
    value: str,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    values = config[config_field]
    assert isinstance(values, list)
    values.append(value)
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "source_kind_policy_errors_count: 1" in output
    assert message in output


@pytest.mark.parametrize(
    ("source_kind", "decision", "reason", "message"),
    [
        (
            "pdf_file",
            "require_human_review",
            "human_review_required",
            "source official_programme_metadata_reference document file source_kind requires refuse_real_document",
        ),
        (
            "real_document_file",
            "admit_metadata_only",
            "none",
            "source official_programme_metadata_reference document file source_kind requires refuse_real_document",
        ),
    ],
)
def test_source_admission_policy_rejects_document_file_kind_without_real_document_refusal(
    tmp_path,
    capsys,
    source_kind: str,
    decision: str,
    reason: str,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    source = _first_source(config)
    source["source_kind"] = source_kind
    source["admission_decision"] = decision
    source["refusal_reason"] = reason
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


def test_source_admission_policy_accepts_metadata_only_real_document_refusal(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    source = _first_source(config)
    source["source_kind"] = "pdf_file"
    source["rights_status"] = "unknown"
    source["license_status"] = "unknown"
    source["visibility"] = "blocked"
    source["pii_status"] = "unknown"
    source["admission_decision"] = "refuse_real_document"
    source["refusal_reason"] = "real_document"
    source["real_file_attached"] = False
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 0
    assert "policy_ready_for_review: true" in output


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("subject", "physique", "source official_programme_metadata_reference subject must be mathematiques"),
        ("level", "premiere", "source official_programme_metadata_reference level must be terminale"),
    ],
)
def test_source_admission_policy_rejects_scope_mismatch(
    tmp_path,
    capsys,
    field: str,
    value: str,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_source(config)[field] = value
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


def test_source_admission_policy_rejects_non_mapping_config_without_traceback(tmp_path) -> None:
    path = tmp_path / "source_admission_policy.yml"
    path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    result = _run_cli(config=path)

    assert result.returncode == 1
    assert "policy_ready_for_review: false" in result.stdout
    assert "config must be a YAML mapping" in result.stdout
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_source_admission_policy_does_not_modify_git_status() -> None:
    module = _load_audit_module()
    before = _git_status()

    status = module.main([])

    after = _git_status()
    assert status == 0
    assert after == before


def test_source_admission_policy_does_not_create_data_staging() -> None:
    module = _load_audit_module()
    _staging_before = set(DATA_STAGING.rglob("*")) if DATA_STAGING.exists() else set()

    status = module.main([])

    assert status == 0
    # Staging may exist (legitimate content); verify module didn't modify it
    _staging_after = set(DATA_STAGING.rglob("*")) if DATA_STAGING.exists() else set()
    assert _staging_after == _staging_before, "module must not create/modify staging"


def test_source_admission_policy_does_not_open_env(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    module = _load_audit_module()
    original_open = Path.open

    def guarded_open(self: Path, *args: object, **kwargs: object):  # noqa: ANN001
        if self.name == ".env":
            raise AssertionError(".env must not be opened")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    status = module.main(["--config", str(_write_config(tmp_path))])

    assert status == 0


def test_source_admission_policy_cli_real_execution_returns_markdown() -> None:
    result = _run_cli()

    assert result.returncode == 0
    assert "# Source admission policy audit" in result.stdout
    assert "status: metadata_only_source_admission_policy" in result.stdout
    assert result.stderr == ""


def test_source_admission_policy_cli_python_optimized_mode_returns_markdown() -> None:
    result = _run_cli(optimized=True)

    assert result.returncode == 0
    assert "# Source admission policy audit" in result.stdout
    assert "policy_ready_for_review: true" in result.stdout
    assert result.stderr == ""


def test_make_target_safety_audit_remains_green_after_source_admission_target() -> None:
    result = subprocess.run(
        ["make", "make-target-safety-audit"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "all_targets_classified: true" in result.stdout
    assert "source-admission-policy-audit" in result.stdout
