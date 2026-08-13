"""Contrat statique minimal de l'acceptance HTTP réelle Wave 0."""

from pathlib import Path

import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[1]
DATASET = ENGINE_ROOT / "tests" / "fixtures" / "wave0_search_acceptance.yml"
ACCEPTANCE = ENGINE_ROOT / "tests" / "integration" / "test_wave0_french_pgvector.py"


def test_wave0_http_acceptance_declares_ten_queries_per_narrow_scope() -> None:
    payload = yaml.safe_load(DATASET.read_text(encoding="utf-8"))

    assert set(payload) == {"entree_seconde_maths_v1", "entree_seconde_francais_v1"}
    assert all(len(cases) >= 10 for cases in payload.values())
    assert all(
        case["query"].strip() and case["expected_concepts_any"]
        for cases in payload.values()
        for case in cases
    )


def test_wave0_acceptance_uses_a_real_uvicorn_socket_and_no_testclient() -> None:
    source = ACCEPTANCE.read_text(encoding="utf-8")

    assert '"-m"' in source
    assert '"uvicorn"' in source
    assert '"src.ingestor.api_v2:app"' in source
    assert "httpx.Client(" in source
    assert "TestClient" not in source
    assert "API_V2_REAL_HTTP=true" in source
