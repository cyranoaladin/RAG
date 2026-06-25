from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from rag_pedago.paths import REPO_ROOT

CONFIG = REPO_ROOT / "configs/pedago_interface_contract.yml"
SAFETY_CONFIG = REPO_ROOT / "configs/make_target_safety.yml"
PROTOCOL_DOC = REPO_ROOT / "docs/PEDAGO_INTERFACE_CONTRACT_PROTOCOL.md"
SCRIPT = REPO_ROOT / "scripts/pedago_interface_contract_audit.py"
MAKEFILE = REPO_ROOT / "Makefile"
DATA_STAGING = REPO_ROOT / "data/staging"

DANGEROUS_FLAGS = [
    "runtime_api_allowed",
    "server_start_allowed",
    "ui_runtime_allowed",
    "real_documents_allowed",
    "pdf_allowed",
    "ingestion_allowed",
    "parsing_allowed",
    "chunking_allowed",
    "embeddings_allowed",
    "qdrant_allowed",
    "network_allowed",
    "answer_generation_allowed",
    "data_staging_allowed",
]

# Flags authorized at true via transition_authorization.yml
AUTHORIZED_TRUE_FLAGS = {"network_allowed", "data_staging_allowed"}


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("pedago_interface_contract_audit", SCRIPT)
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
    path = tmp_path / "pedago_interface_contract.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _first_interaction(config: dict[str, object]) -> dict[str, object]:
    interactions = config["interactions"]
    assert isinstance(interactions, list)
    interaction = interactions[0]
    assert isinstance(interaction, dict)
    return interaction


def _refusal_interaction(config: dict[str, object]) -> dict[str, object]:
    interactions = config["interactions"]
    assert isinstance(interactions, list)
    interaction = interactions[2]
    assert isinstance(interaction, dict)
    return interaction


def _run_cli(*, optimized: bool = False, config: Path = CONFIG) -> subprocess.CompletedProcess[str]:
    command = ["python3"]
    if optimized:
        command.append("-O")
    command.extend(["scripts/pedago_interface_contract_audit.py", "--config", str(config)])
    return subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def _git_status() -> str:
    return subprocess.check_output(["git", "status", "--short", "--branch"], cwd=REPO_ROOT, text=True)


def test_pedago_interface_contract_artifacts_exist() -> None:
    assert PROTOCOL_DOC.is_file()
    assert CONFIG.is_file()
    assert SCRIPT.is_file()


def test_pedago_interface_contract_make_target_is_safe_and_no_api_target_added() -> None:
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    safety_config = yaml.safe_load(SAFETY_CONFIG.read_text(encoding="utf-8"))

    assert "pedago-interface-contract-audit:" in makefile_text
    assert "$(PY) scripts/pedago_interface_contract_audit.py" in makefile_text
    assert "pedago-interface-contract-audit" in safety_config["SAFE_METADATA_ONLY"]
    assert "api" in safety_config["RESTRICTED_RUNTIME"]
    for forbidden_target in [
        "api-ui-audit",
        "api-contract-audit",
        "ui-api-audit",
        "api-metadata-audit",
    ]:
        assert forbidden_target not in makefile_text
        assert forbidden_target not in safety_config["SAFE_METADATA_ONLY"]


def test_pedago_interface_contract_script_has_no_destructive_network_or_process_tokens() -> None:
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


def test_pedago_interface_contract_audit_returns_markdown(capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()

    status = module.main([])

    output = capsys.readouterr().out
    assert status == 0
    assert "# Pedagogical interface contract audit" in output
    assert "status: metadata_only_interface_contract" in output
    assert "interface_ready_for_review: true" in output
    assert "runtime_api_allowed: false" in output
    assert "server_start_allowed: false" in output
    assert "ui_runtime_allowed: false" in output
    assert "answer_generation_allowed: false" in output
    assert "embeddings_allowed: false" in output
    assert "qdrant_allowed: false" in output
    assert "destructive_action_available: false" in output
    assert "no API server started" in output
    assert "invalid_contract_values_count: 0" in output
    assert "interaction_contract_errors_count: 0" in output
    assert "forbidden_runtime_fields_count: 0" in output
    for section in [
        "## Invalid contract values",
        "## Personas",
        "## Interactions",
        "## Citation policy",
        "## Refusal policy",
        "## Interaction contract errors",
        "## Forbidden runtime fields",
        "## Blocking issues",
        "## Explicit non-actions",
    ]:
        assert section in output


@pytest.mark.parametrize("flag", [f for f in DANGEROUS_FLAGS if f not in AUTHORIZED_TRUE_FLAGS])
def test_pedago_interface_contract_rejects_any_dangerous_flag_enabled(
    tmp_path,
    capsys,
    flag: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _write_config(tmp_path, **{flag: True})

    status = module.main(["--config", str(config)])

    output = capsys.readouterr().out
    assert status == 1
    assert "interface_ready_for_review: false" in output
    assert f"{flag} must be false" in output


@pytest.mark.parametrize("flag", list(AUTHORIZED_TRUE_FLAGS))
def test_pedago_interface_contract_rejects_authorized_flag_if_false(
    tmp_path,
    capsys,
    flag: str,
) -> None:  # noqa: ANN001
    """An authorized-true flag set to false should be rejected."""
    module = _load_audit_module()
    config = _write_config(tmp_path, **{flag: False})

    status = module.main(["--config", str(config)])

    output = capsys.readouterr().out
    assert status == 1
    assert f"{flag} must be true" in output


def test_pedago_interface_contract_rejects_missing_required_persona(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["allowed_personas"] = ["eleve", "enseignant"]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "missing_required_personas_count: 1" in output
    assert "missing required persona: administrateur_pedagogique" in output


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "contract_id",
            "wrong_contract",
            "contract_id must be pedago_interface_metadata_contract_v1",
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
    ],
)
def test_pedago_interface_contract_rejects_invalid_contract_references(
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
    assert "invalid_contract_values_count: 1" in output
    assert message in output


def test_pedago_interface_contract_rejects_unknown_interaction_persona(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_interaction(config)["persona"] = "parent"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "invalid_personas_count: 1" in output
    assert "interaction eleve_recherche_fiche_cours persona must be allowed" in output


def test_pedago_interface_contract_rejects_unknown_expected_behavior(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_interaction(config)["expected_behavior"] = "final_answer"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "invalid_expected_behaviors_count: 1" in output
    assert "invalid expected_behavior for eleve_recherche_fiche_cours: final_answer" in output


def test_pedago_interface_contract_rejects_global_citations_not_required(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["citation_policy"]["citations_required"] = False  # type: ignore[index]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "citations_required must be true" in output


def test_pedago_interface_contract_rejects_global_answer_without_source_allowed(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["citation_policy"]["answer_without_source_allowed"] = True  # type: ignore[index]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "answer_without_source_allowed must be false" in output


def test_pedago_interface_contract_rejects_global_source_trace_not_required(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["citation_policy"]["source_trace_required"] = False  # type: ignore[index]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "global citation_policy source_trace_required must be true" in output


def test_pedago_interface_contract_rejects_interaction_citation_policy_not_mapping(
    tmp_path,
    capsys,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_interaction(config)["citation_policy"] = "required"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "citation_policy for interaction eleve_recherche_fiche_cours must be a mapping" in output


def test_pedago_interface_contract_rejects_interaction_citations_not_required(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_interaction(config)["citation_policy"]["citations_required"] = False  # type: ignore[index]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "interaction eleve_recherche_fiche_cours citations_required must be true" in output


def test_pedago_interface_contract_rejects_interaction_answer_without_source_allowed(
    tmp_path,
    capsys,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_interaction(config)["citation_policy"]["answer_without_source_allowed"] = True  # type: ignore[index]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "interaction eleve_recherche_fiche_cours answer_without_source_allowed must be false" in output


def test_pedago_interface_contract_rejects_interaction_source_trace_contradiction(
    tmp_path,
    capsys,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_interaction(config)["citation_policy"]["source_trace_required"] = False  # type: ignore[index]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "interaction eleve_recherche_fiche_cours source_trace_required must not be false" in output


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("refusal_required_when_no_source", "global refusal_policy refusal_required_when_no_source must be true"),
        (
            "refusal_required_for_real_document_request",
            "global refusal_policy refusal_required_for_real_document_request must be true",
        ),
        (
            "refusal_required_for_unknown_rights",
            "global refusal_policy refusal_required_for_unknown_rights must be true",
        ),
    ],
)
def test_pedago_interface_contract_rejects_incomplete_global_refusal_policy(
    tmp_path,
    capsys,
    field: str,
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    config["refusal_policy"][field] = False  # type: ignore[index]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


def test_pedago_interface_contract_rejects_interaction_refusal_policy_not_mapping(
    tmp_path,
    capsys,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _refusal_interaction(config)["refusal_policy"] = "refuse"
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "refusal_policy for interaction administrateur_validation_refus must be a mapping" in output


def test_pedago_interface_contract_rejects_controlled_refusal_without_explicit_rule(
    tmp_path,
    capsys,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _refusal_interaction(config)["refusal_policy"] = {"no_answer_generation_on_refusal": True}
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "controlled_refusal interaction administrateur_validation_refus must include an explicit refusal rule" in output


def test_pedago_interface_contract_rejects_interaction_refusal_answer_generation(
    tmp_path,
    capsys,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_interaction(config)["refusal_policy"]["no_answer_generation_on_refusal"] = False  # type: ignore[index]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "interaction eleve_recherche_fiche_cours no_answer_generation_on_refusal must be true" in output


def test_pedago_interface_contract_rejects_non_refusal_without_metadata_filters(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_interaction(config)["metadata_filters_required"] = []
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "interaction eleve_recherche_fiche_cours metadata_filters_required must be non-empty" in output


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda interaction: interaction.__setitem__("interaction_id", ""),
            "interaction_id at index 0 must be a non-empty string",
        ),
        (
            lambda interaction: interaction.__setitem__("intent", ""),
            "interaction eleve_recherche_fiche_cours intent must be a non-empty string",
        ),
        (
            lambda interaction: interaction.__setitem__("input_kind", "real_user_prompt"),
            "interaction eleve_recherche_fiche_cours input_kind must be allowed",
        ),
        (
            lambda interaction: interaction.__setitem__("human_review_required", "yes"),
            "interaction eleve_recherche_fiche_cours human_review_required must be boolean",
        ),
        (
            lambda interaction: interaction.__setitem__("metadata_filters_required", "niveau"),
            "interaction eleve_recherche_fiche_cours metadata_filters_required must be a list of strings",
        ),
        (
            lambda interaction: interaction.__setitem__(
                "metadata_filters_required",
                ["niveau", "voie", "matiere", "statut_enseignement", "visibility"],
            ),
            "interaction eleve_recherche_fiche_cours missing metadata_filters_required: rights",
        ),
        (
            lambda interaction: interaction.__setitem__("output_kind", "final_answer"),
            "interaction eleve_recherche_fiche_cours output_kind final_answer is forbidden",
        ),
        (
            lambda interaction: interaction.__setitem__("endpoint", "/ask"),
            "interaction eleve_recherche_fiche_cours forbidden runtime field: endpoint",
        ),
        (
            lambda interaction: interaction.__setitem__("http_method", "POST"),
            "interaction eleve_recherche_fiche_cours forbidden runtime field: http_method",
        ),
        (
            lambda interaction: interaction.__setitem__("component_runtime", "react"),
            "interaction eleve_recherche_fiche_cours forbidden runtime field: component_runtime",
        ),
    ],
)
def test_pedago_interface_contract_rejects_malformed_interaction_contract(
    tmp_path,
    capsys,
    mutation,  # noqa: ANN001
    message: str,
) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    mutation(_first_interaction(config))
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert message in output


def test_pedago_interface_contract_rejects_refusal_with_metadata_filters(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _refusal_interaction(config)["metadata_filters_required"] = ["niveau"]
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "refusal interaction administrateur_validation_refus metadata_filters_required must be empty" in output


def test_pedago_interface_contract_rejects_answer_generation_expected(tmp_path, capsys) -> None:  # noqa: ANN001
    module = _load_audit_module()
    config = _base_config()
    _first_interaction(config)["answer_generation_expected"] = True
    path = _write_config(tmp_path, config)

    status = module.main(["--config", str(path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "interaction eleve_recherche_fiche_cours must not request answer generation" in output


def test_pedago_interface_contract_rejects_non_mapping_config_without_traceback(tmp_path) -> None:
    path = tmp_path / "pedago_interface_contract.yml"
    path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    result = _run_cli(config=path)

    assert result.returncode == 1
    assert "interface_ready_for_review: false" in result.stdout
    assert "config must be a YAML mapping" in result.stdout
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_pedago_interface_contract_does_not_modify_git_status() -> None:
    module = _load_audit_module()
    before = _git_status()

    status = module.main([])

    after = _git_status()
    assert status == 0
    assert after == before


def test_pedago_interface_contract_does_not_create_data_staging() -> None:
    module = _load_audit_module()

    status = module.main([])

    assert status == 0
    assert not DATA_STAGING.exists()


def test_pedago_interface_contract_does_not_open_env(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    module = _load_audit_module()
    original_open = Path.open

    def guarded_open(self: Path, *args: object, **kwargs: object):  # noqa: ANN001
        if self.name == ".env":
            raise AssertionError(".env must not be opened")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    status = module.main(["--config", str(_write_config(tmp_path))])

    assert status == 0


def test_pedago_interface_contract_cli_real_execution_returns_markdown() -> None:
    result = _run_cli()

    assert result.returncode == 0
    assert "# Pedagogical interface contract audit" in result.stdout
    assert "status: metadata_only_interface_contract" in result.stdout
    assert result.stderr == ""


def test_pedago_interface_contract_cli_python_optimized_mode_returns_markdown() -> None:
    result = _run_cli(optimized=True)

    assert result.returncode == 0
    assert "# Pedagogical interface contract audit" in result.stdout
    assert "interface_ready_for_review: true" in result.stdout
    assert result.stderr == ""


def test_make_target_safety_audit_remains_green_after_pedago_interface_target() -> None:
    result = subprocess.run(
        ["make", "make-target-safety-audit"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "all_targets_classified: true" in result.stdout
    assert "pedago-interface-contract-audit" in result.stdout
