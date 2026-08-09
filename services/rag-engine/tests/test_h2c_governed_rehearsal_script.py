"""Le sceau de répétition H2-E exige les deux chemins V2 observés."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "h2c_governed_rehearsal.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("h2c_governed_rehearsal", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result() -> dict[str, object]:
    return {
        "full_governed_rehearsal_pass": True,
        "lot41a_v2_content_bound": True,
        "positive_content_allowlist_gate": "PASS",
        "positive_extractor_calls": 1,
        "negative_same_domain_unlisted": {
            "domain_gate": "PASS",
            "content_allowlist_gate": "DENY",
            "extractor_called": False,
            "rights_agent_called": False,
            "quality_agent_called": False,
            "retrieval_eligible": False,
            "pgvector_rows_created": 0,
        },
    }


def test_accepts_only_a_complete_v2_positive_and_negative_rehearsal() -> None:
    module = _module()
    module._validate_rehearsal_result(_result())


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("lot41a_v2_content_bound",), False),
        (("positive_content_allowlist_gate",), "DENY"),
        (("positive_extractor_calls",), 2),
        (("negative_same_domain_unlisted", "domain_gate"), "DENY"),
        (("negative_same_domain_unlisted", "content_allowlist_gate"), "PASS"),
        (("negative_same_domain_unlisted", "extractor_called"), True),
        (("negative_same_domain_unlisted", "rights_agent_called"), True),
        (("negative_same_domain_unlisted", "quality_agent_called"), True),
        (("negative_same_domain_unlisted", "retrieval_eligible"), True),
        (("negative_same_domain_unlisted", "pgvector_rows_created"), 1),
    ],
)
def test_refuses_to_seal_any_missing_or_weakened_v2_metric(
    path: tuple[str, ...], value: object
) -> None:
    module = _module()
    result = _result()
    target = result
    for key in path[:-1]:
        nested = target[key]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = value
    with pytest.raises(RuntimeError, match="H2E_V2_REHEARSAL_NOT_GREEN"):
        module._validate_rehearsal_result(result)
