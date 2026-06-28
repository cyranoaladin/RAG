from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from rag_pedago.paths import REPO_ROOT

CONFIG = REPO_ROOT / "configs/retrieval_metadata_eval.yml"
SAFETY_CONFIG = REPO_ROOT / "configs/make_target_safety.yml"
PROTOCOL_DOC = REPO_ROOT / "docs/RETRIEVAL_METADATA_EVAL_PROTOCOL.md"
SCRIPT = REPO_ROOT / "scripts/retrieval_metadata_eval_audit.py"
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
    "answer_generation_allowed",
    "data_staging_allowed",
]

METADATA_FILTER_ERROR_CASES = [
    ("type_doc", None, "missing expected_filters for cours_limites_continuite: type_doc"),
    ("rights", None, "missing expected_filters for cours_limites_continuite: rights"),
    ("rights", "unknown", "expected_filters for cours_limites_continuite rights must be allowed_for_retrieval"),
    ("visibility", "internal_only", "expected_filters for cours_limites_continuite visibility must be student_visible"),
    ("notions", None, "missing expected_filters for cours_limites_continuite: notions"),
    ("notions", [], "expected_filters for cours_limites_continuite notions must be a non-empty list"),
    ("competences", None, "missing expected_filters for cours_limites_continuite: competences"),
    ("competences", [], "expected_filters for cours_limites_continuite competences must be a non-empty list"),
    ("niveau", "seconde", "expected_filters for cours_limites_continuite niveau must be terminale"),
]


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("retrieval_metadata_eval_audit", SCRIPT)
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
    path = tmp_path / "retrieval_metadata_eval.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _metadata_case(config: dict[str, object]) -> dict[str, object]:
    cases = config["cases"]
    assert isinstance(cases, list)
    case = cases[0]
    assert isinstance(case, dict)
    return case


def _refusal_case(config: dict[str, object], case_id: str = "refus_document_reel_requis") -> dict[str, object]:
    cases = config["cases"]
    assert isinstance(cases, list)
    for case in cases:
        assert isinstance(case, dict)
        if case.get("case_id") == case_id:
            return case
    raise AssertionError(f"missing case {case_id}")


def _run_cli(*, optimized: bool = False, config: Path = CONFIG) -> subprocess.CompletedProcess[str]:
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend(["scripts/retrieval_metadata_eval_audit.py", "--config", str(config)])
    return subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def _git_status() -> str:
    return subprocess.check_output(["git", "status", "--short", "--branch"], cwd=REPO_ROOT, text=True)


def test_retrieval_metadata_eval_artifacts_exist() -> None:
    assert PROTOCOL_DOC.is_file()
    assert CONFIG.is_file()
    assert SCRIPT.is_file()


def test_retrieval_metadata_eval_make_target_is_safe_and_eval_retrieval_remains_future() -> None:
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    safety_config = yaml.safe_load(SAFETY_CONFIG.read_text(encoding="utf-8"))

    assert "retrieval-metadata-eval-audit:" in makefile_text
    assert "$(PY) scripts/retrieval_metadata_eval_audit.py" in makefile_text
    assert "retrieval-metadata-eval-audit" in safety_config["SAFE_METADATA_ONLY"]
    assert "eval-retrieval" in safety_config["FUTURE_NOT_READY"]


def test_retrieval_metadata_eval_script_has_no_destructive_network_or_process_tokens() -> None:
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


def test_retrieval_metadata_eval_audit_returns_markdown(capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()

    status = module.main([])

    output = capsys.readouterr().out
    assert status == 0
    assert "# Retrieval metadata eval audit" in output
    assert "status: metadata_only_eval" in output
    assert "eval_ready_for_review: true" in output
    assert "embeddings_allowed: false" in output
    assert "qdrant_allowed: false" in output
    assert "real_documents_allowed: false" in output
    assert "answer_generation_allowed: false" in output
    assert "destructive_action_available: false" in output
    assert "no answer generated" in output
    for count in [
        "student_profile_errors_count: 0",
        "expected_filter_errors_count: 0",
        "case_citation_policy_errors_count: 0",
        "pedagogical_criteria_errors_count: 0",
        "refusal_case_errors_count: 0",
    ]:
        assert count in output
    for section in [
        "## Cases",
        "## Required filter fields",
        "## Citation policy",
        "## Student profile errors",
        "## Expected filter errors",
        "## Case citation policy errors",
        "## Pedagogical criteria errors",
        "## Refusal case errors",
        "## Blocking issues",
        "## Explicit non-actions",
    ]:
        assert section in output


@pytest.mark.parametrize("flag", DANGEROUS_FLAGS)
def test_retrieval_metadata_eval_rejects_any_dangerous_flag_enabled(tmp_path, capsys, flag: str) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _write_config(tmp_path, **{flag: True})

    status = module.main(["--config", str(config)])

    output = capsys.readouterr().out
    assert status == 1
    assert "eval_ready_for_review: false" in output
    assert f"{flag} must be false" in output


def test_retrieval_metadata_eval_rejects_citations_not_required(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["citation_policy"]["citations_required"] = False  # type: ignore[index]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "citations_required must be true" in output


def test_retrieval_metadata_eval_rejects_answer_without_source_allowed(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["citation_policy"]["answer_without_source_allowed"] = True  # type: ignore[index]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "answer_without_source_allowed must be false" in output


def test_retrieval_metadata_eval_rejects_metadata_case_without_filters(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["cases"][0]["expected_filters"] = {}  # type: ignore[index]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "metadata_filter_only case cours_limites_continuite must define expected_filters" in output


def test_retrieval_metadata_eval_rejects_invalid_student_profile_value(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    profile = _metadata_case(config)["student_profile"]
    assert isinstance(profile, dict)
    profile["niveau"] = "seconde"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "student_profile_errors_count: 1" in output
    assert "student_profile for cours_limites_continuite niveau must be terminale" in output


def test_retrieval_metadata_eval_rejects_non_mapping_student_profile(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _metadata_case(config)["student_profile"] = "terminale"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "student_profile for cours_limites_continuite must be a mapping" in output


@pytest.mark.parametrize(("field", "value", "expected_issue"), METADATA_FILTER_ERROR_CASES)
def test_retrieval_metadata_eval_rejects_incomplete_or_invalid_metadata_filters(
    tmp_path,
    capsys,
    field: str,
    value: object,
    expected_issue: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    filters = _metadata_case(config)["expected_filters"]
    assert isinstance(filters, dict)
    if value is None:
        filters.pop(field)
    else:
        filters[field] = value
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "expected_filter_errors_count: 1" in output
    assert expected_issue in output


def test_retrieval_metadata_eval_rejects_unknown_expected_behavior(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["cases"][0]["expected_behavior"] = "generate_answer"  # type: ignore[index]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "invalid expected_behavior for cours_limites_continuite: generate_answer" in output


def test_retrieval_metadata_eval_rejects_case_missing_case_id(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    del config["cases"][0]["case_id"]  # type: ignore[index]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "case at index 0 missing required field case_id" in output


def test_retrieval_metadata_eval_rejects_case_missing_expected_citation_policy(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    del config["cases"][0]["expected_citation_policy"]  # type: ignore[index]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "case cours_limites_continuite missing required field expected_citation_policy" in output


def test_retrieval_metadata_eval_rejects_non_mapping_case_citation_policy(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _metadata_case(config)["expected_citation_policy"] = "required"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "case_citation_policy_errors_count: 1" in output
    assert "expected_citation_policy for cours_limites_continuite must be a mapping" in output


def test_retrieval_metadata_eval_rejects_case_citations_not_required(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    citation_policy = _metadata_case(config)["expected_citation_policy"]
    assert isinstance(citation_policy, dict)
    citation_policy["citations_required"] = False
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "case_citation_policy_errors_count: 1" in output
    assert "case cours_limites_continuite citations_required must be true" in output


def test_retrieval_metadata_eval_rejects_case_answer_without_source_allowed(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    citation_policy = _metadata_case(config)["expected_citation_policy"]
    assert isinstance(citation_policy, dict)
    citation_policy["answer_without_source_allowed"] = True
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "case_citation_policy_errors_count: 1" in output
    assert "case cours_limites_continuite answer_without_source_allowed must be false" in output


def test_retrieval_metadata_eval_rejects_missing_pedagogical_criteria(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    del _metadata_case(config)["pedagogical_relevance_criteria"]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "case cours_limites_continuite missing required field pedagogical_relevance_criteria" in output


def test_retrieval_metadata_eval_rejects_empty_pedagogical_criteria(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _metadata_case(config)["pedagogical_relevance_criteria"] = []
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "pedagogical_criteria_errors_count: 1" in output
    assert "pedagogical_relevance_criteria for cours_limites_continuite must be a non-empty list" in output


def test_retrieval_metadata_eval_rejects_metadata_case_without_citation_required_criterion(
    tmp_path,
    capsys,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _metadata_case(config)["pedagogical_relevance_criteria"] = ["notion_match"]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "metadata_filter_only case cours_limites_continuite must include citation_required criterion" in output


def test_retrieval_metadata_eval_rejects_refusal_without_refusal_or_no_answer_criterion(
    tmp_path,
    capsys,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _refusal_case(config)["pedagogical_relevance_criteria"] = ["citation_required"]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "refusal case refus_document_reel_requis must include no_answer_generation or must_refuse_* criterion" in output


def test_retrieval_metadata_eval_rejects_refusal_case_with_filters(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _refusal_case(config)["expected_filters"] = {"niveau": "terminale"}
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "refusal_case_errors_count: 1" in output
    assert "refusal case refus_document_reel_requis expected_filters must be empty" in output


def test_retrieval_metadata_eval_rejects_refusal_case_with_answer_generation_expected(
    tmp_path,
    capsys,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _refusal_case(config)["answer_generation_expected"] = True
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "refusal case refus_document_reel_requis must not request answer generation" in output


def test_retrieval_metadata_eval_rejects_real_document_refusal_without_specific_criterion(
    tmp_path,
    capsys,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _refusal_case(config)["pedagogical_relevance_criteria"] = ["no_answer_generation"]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "refuse_no_real_document_access case refus_document_reel_requis must include must_refuse_real_document_access" in output


def test_retrieval_metadata_eval_rejects_rights_refusal_without_specific_criterion(
    tmp_path,
    capsys,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _refusal_case(config, "refus_droits_inconnus")["pedagogical_relevance_criteria"] = ["no_answer_generation"]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "refuse_rights_unknown case refus_droits_inconnus must include must_refuse_unknown_rights" in output


def test_retrieval_metadata_eval_rejects_non_mapping_config_without_traceback(tmp_path) -> None:
    config = tmp_path / "retrieval_metadata_eval.yml"
    config.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    result = _run_cli(config=config)

    assert result.returncode == 1
    assert "eval_ready_for_review: false" in result.stdout
    assert "config must be a YAML mapping" in result.stdout
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_retrieval_metadata_eval_does_not_modify_git_status() -> None:
    module = _load_audit_module()
    before = _git_status()

    status = module.main([])

    after = _git_status()
    assert status == 0
    assert after == before


def test_retrieval_metadata_eval_does_not_create_data_staging() -> None:
    module = _load_audit_module()
    _staging_before = set(DATA_STAGING.rglob("*")) if DATA_STAGING.exists() else set()

    status = module.main([])

    assert status == 0
    # Staging may exist (legitimate content); verify module didn't modify it
    _staging_after = set(DATA_STAGING.rglob("*")) if DATA_STAGING.exists() else set()
    assert _staging_after == _staging_before, "module must not create/modify staging"


def test_retrieval_metadata_eval_does_not_open_env(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    module = _load_audit_module()
    original_open = Path.open

    def guarded_open(self: Path, *args: object, **kwargs: object):  # noqa: ANN001
        if self.name == ".env":
            raise AssertionError(".env must not be opened")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    status = module.main(["--config", str(_write_config(tmp_path))])

    assert status == 0


def test_retrieval_metadata_eval_cli_real_execution_returns_markdown() -> None:
    result = _run_cli()

    assert result.returncode == 0
    assert "# Retrieval metadata eval audit" in result.stdout
    assert "status: metadata_only_eval" in result.stdout
    assert result.stderr == ""


def test_retrieval_metadata_eval_cli_python_optimized_mode_returns_markdown() -> None:
    result = _run_cli(optimized=True)

    assert result.returncode == 0
    assert "# Retrieval metadata eval audit" in result.stdout
    assert "eval_ready_for_review: true" in result.stdout
    assert result.stderr == ""


def test_make_target_safety_audit_remains_green_after_retrieval_target() -> None:
    result = subprocess.run(
        ["make", "make-target-safety-audit"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "all_targets_classified: true" in result.stdout
    assert "retrieval-metadata-eval-audit" in result.stdout
