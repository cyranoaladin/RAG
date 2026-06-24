from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def load_contract(name: str) -> dict:
    return yaml.safe_load((ROOT / "docs" / "contracts" / name).read_text(encoding="utf-8"))


def test_agent_ready_docs_exist() -> None:
    for path in [
        "README.md",
        "AGENTS.md",
        "docs/ARCHITECTURE.md",
        "docs/WORKFLOWS.md",
        "docs/LOT_STATUS.md",
    ]:
        assert (ROOT / path).is_file(), path


def test_contract_files_exist() -> None:
    for name in [
        "pipeline_contract.yml",
        "runtime_artifacts.yml",
        "commands.yml",
        "invariants.yml",
    ]:
        assert (ROOT / "docs" / "contracts" / name).is_file(), name


def test_pipeline_contract_current_steps_do_not_read_sources_use_network_or_parse() -> None:
    contract = load_contract("pipeline_contract.yml")

    assert {step["id"] for step in contract["steps"]} >= {
        "manifest_import",
        "manifest_directory_import",
        "quality",
        "readiness",
        "coverage",
        "gate",
        "review_package",
        "approval",
        "controlled_import",
        "audit_ledger",
    }
    for step in contract["steps"]:
        assert step["may_read_source_uri"] is False, step["id"]
        assert step["may_use_network"] is False, step["id"]
        assert step["may_parse_document"] is False, step["id"]


def test_commands_contract_lists_public_commands() -> None:
    commands = load_contract("commands.yml")
    command_names = {entry["command"] for entry in commands["commands"]}

    assert {
        "make doctor",
        "make test",
        "make ledger-init",
        "make ledger-doctor",
        "make manifest-readiness",
        "make manifest-coverage",
        "make manifest-gate",
        "python -m rag_pedago.imports.controlled_import_cli",
    } <= command_names


def test_runtime_artifacts_contract_matches_gitignore() -> None:
    runtime = load_contract("runtime_artifacts.yml")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    for pattern in runtime["gitignored_runtime_patterns"]:
        assert pattern in gitignore
    assert "data/reports/codex_lot_*.md" in runtime["versioned_report_patterns"]


def test_invariants_contract_lists_absolute_forbidden_integrations() -> None:
    invariants = load_contract("invariants.yml")
    text = yaml.safe_dump(invariants, allow_unicode=True)

    for forbidden in ["Qdrant", "PostgreSQL", "LLM", "source_uri", "network"]:
        assert forbidden in text


def test_agents_preserves_historical_guardrails() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    for required in [
        "schema/document.py",
        "taxonomies officielles",
        "document source",
        "data/raw",
        "hash",
        "doublon vectoriel",
        "scraping massif",
        "robots.txt",
        "rights",
        "visibility",
        "ressource propriétaire",
        "rights=unknown",
        "LLM",
        "validation",
        "logs structurés",
        "reprise après interruption",
    ]:
        assert required in agents


def test_invariants_contract_includes_historical_guardrails() -> None:
    invariants = load_contract("invariants.yml")
    text = yaml.safe_dump(invariants, allow_unicode=True)

    for required in [
        "schema/document.py",
        "taxonomies officielles",
        "document source",
        "data/raw",
        "hash",
        "doublon vectoriel",
        "scraping massif",
        "robots.txt",
        "rights",
        "visibility",
        "ressource propriétaire",
        "rights=unknown",
        "LLM",
        "validation",
    ]:
        assert required in text


def test_codex_reports_are_discoverable() -> None:
    reports = sorted((ROOT / "data" / "reports").glob("codex_lot_*.md"))

    assert reports
    assert any(report.name == "codex_lot_13_review_audit_ledger.md" for report in reports)
