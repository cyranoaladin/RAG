"""Contrat statique du dataset Search full Wave 0."""
from __future__ import annotations

from pathlib import Path

import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[1]
DATASET = ENGINE_ROOT / "tests" / "fixtures" / "wave0_full_search_acceptance.yml"
MATHS_SHA = "49ccdca4d97ba4cf25875dfc731474e84d0332985c15396d3abfb9107f5f545a"
FR_SHA = "c8662b03ca8a7f08bedad5081bafc7da8d2cc8a31b07fa967421fb15304d76bf"


def test_full_wave0_search_dataset_covers_every_release_artifact() -> None:
    document = yaml.safe_load(DATASET.read_text(encoding="utf-8"))

    assert set(document) == {
        "entree_seconde_maths_v1",
        "entree_seconde_francais_v1",
    }
    expected = {
        "entree_seconde_maths_v1": MATHS_SHA,
        "entree_seconde_francais_v1": FR_SHA,
    }
    probes: set[str] = set()
    for scope_id, cases in document.items():
        assert isinstance(cases, list) and len(cases) >= 20
        assert len({case["query"] for case in cases}) == len(cases)
        assert all(case["expected_concepts_any"] for case in cases)
        assert all(case["expected_pages_any"] for case in cases)
        assert all(case["expected_artifacts_any"] == [expected[scope_id]] for case in cases)
        probes.update(
            case["expected_artifacts_any"][0]
            for case in cases
            if case.get("artifact_probe") is True
        )

    assert probes == {MATHS_SHA, FR_SHA}
