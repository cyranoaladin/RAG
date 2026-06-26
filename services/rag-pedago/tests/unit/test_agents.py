"""Tests for multi-agent acquisition framework."""
from __future__ import annotations

from textwrap import dedent

from agents.subject_agent import SubjectAgent


def _taxonomy_yaml(matiere: str = "mathematiques", niveau: str = "terminale") -> str:
    return dedent(f"""\
        id: test_{matiere}_{niveau}
        matiere: {matiere}
        niveau: {niveau}
        voie: generale
        statut_enseignement: specialite
        programme_version: BOEN_test
        themes:
          - id: theme1
            label: Theme 1
            notions:
              - id: notion_a
                label: Notion A
              - id: notion_b
                label: Notion B
        competences:
          - raisonner
    """)


def test_subject_agent_plan(tmp_path) -> None:
    taxo = tmp_path / "taxo.yml"
    taxo.write_text(_taxonomy_yaml(), encoding="utf-8")
    agent = SubjectAgent(taxo, tmp_path / "staging")
    plan = agent.plan()
    assert plan["matiere"] == "mathematiques"
    assert plan["notions_count"] == 2
    assert plan["notions"][0]["notion_id"] == "notion_a"


def test_subject_agent_refuses_when_staging_not_allowed(tmp_path, monkeypatch) -> None:
    taxo = tmp_path / "taxo.yml"
    taxo.write_text(_taxonomy_yaml(), encoding="utf-8")
    agent = SubjectAgent(taxo, tmp_path / "staging")

    # Patch contract to disallow staging
    fake_contract = tmp_path / "contract.yml"
    fake_contract.write_text("data_staging_allowed: false\n", encoding="utf-8")
    monkeypatch.setattr("agents.base.CONTRACT_PATH", fake_contract)

    result = agent.fetch()
    assert "error" in result
    assert "staging" in result["error"].lower()


def test_orchestrator_checks_ingestion_blocked(tmp_path, monkeypatch) -> None:
    from agents.orchestrator import OrchestratorAgent

    # Patch contract: staging allowed but ingestion also allowed (should block)
    fake_contract = tmp_path / "contract.yml"
    fake_contract.write_text(
        "data_staging_allowed: true\ningestion_allowed: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("agents.base.CONTRACT_PATH", fake_contract)

    orch = OrchestratorAgent(niveaux=["terminale"], staging_root=tmp_path / "staging")
    result = orch.fetch()
    assert "error" in result
    assert "ingestion" in result["error"].lower()
