"""Le sceau de répétition H2-E exige les deux chemins V2 observés."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "h2c_governed_rehearsal.py"
INTEGRATION = ROOT / "tests" / "integration" / "test_h2c_governed_rehearsal.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("h2c_governed_rehearsal", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result() -> dict[str, object]:
    return {
        "artifact_rows_for_sha": 1,
        "chunk_set_count": 1,
        "citation_traceability_pass": True,
        "duplicate_chunk_sets": 0,
        "duplicate_result_chunks": 0,
        "duplicate_vector_sets": 0,
        "full_governed_rehearsal_pass": True,
        "lot41a_v2_content_bound": True,
        "lot42_pipeline_path_implemented": True,
        "placement_rows": 7,
        "placement_traceability_pass": True,
        "positive_content_allowlist_gate": "PASS",
        "positive_extractor_calls": 1,
        "real_multi_placement_placements": 7,
        "real_multi_placement_sha": (
            "371d0c82ed1f47614ee9cbfdaa86cfb4add1f239a84882d9731fbd125105925d"
        ),
        "scope_a_retrieval_pass": True,
        "scope_b_retrieval_pass": True,
        "wrong_scope_retrieval_blocked": True,
        "negative_same_domain_unlisted": {
            "control_artifact_rows": 0,
            "domain_gate": "PASS",
            "content_allowlist_gate": "DENY",
            "extractor_called": False,
            "rights_agent_called": False,
            "quality_agent_called": False,
            "resource_state": "CANDIDATE",
            "retrieval_eligible": False,
            "store_called": False,
            "pgvector_rows_created": 0,
        },
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _materialized_inputs(
    module: ModuleType,
    tmp_path: Path,
) -> tuple[Path, dict[str, object], dict[str, object]]:
    pdf = tmp_path / "371d0c82ed.pdf"
    pdf.write_bytes(b"%PDF-1.7\nsealed bytes\n%%EOF\n")
    pii = tmp_path / "pii.json"
    pii.write_text('{"evidence_kind":"REAL_CORPUS_PII_SCAN"}\n', encoding="utf-8")
    placement_digest = "3" * 64
    catalog: dict[str, object] = {
        "catalog_kind": "REAL_SEALED_CORPUS",
        "manifest_sha256": "4" * 64,
        "placement_catalog_sha256": placement_digest,
        "manifest_entries": 11,
        "physical_object_count": 12,
        "eduscol_unique_artifacts": 9,
        "eduscol_placement_count": 14,
        "verification_passed": True,
        "verification_errors": [],
        "unclassified": 0,
        "multiple_primary_disposition": 0,
        "artifacts": {
            _sha256(pdf): {
                "pedagogical_placement_count": 7,
                "pedagogical_placements": [
                    {
                        "content_sha256": _sha256(pdf),
                        "classified": True,
                        "status": "actuel",
                    }
                    for _ in range(7)
                ],
            }
        },
    }
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    inputs: dict[str, object] = {
        "inputs_manifest_kind": "H2E_MATERIALIZED_REHEARSAL_INPUTS",
        "pdf_path": str(pdf),
        "pdf_sha256": _sha256(pdf),
        "catalog_path": str(catalog_path),
        "catalog_sha256": _sha256(catalog_path),
        "pii_evidence_path": str(pii),
        "pii_evidence_sha256": _sha256(pii),
        "placement_catalog_sha256": placement_digest,
        "manifest_sha256": "4" * 64,
        "remote_write_operations": 0,
    }
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text(json.dumps(inputs), encoding="utf-8")
    module.REAL_SHA = _sha256(pdf)
    module.CORPUS_MANIFEST_SHA = "4" * 64
    module.PII_EVIDENCE_SHA = _sha256(pii)
    module.EXPECTED_MANIFEST_ENTRIES = 11
    module.EXPECTED_PHYSICAL_OBJECTS = 12
    module.EXPECTED_EDUSCOL_ARTIFACTS = 9
    module.EXPECTED_EDUSCOL_PLACEMENTS = 14
    return inputs_path, inputs, catalog


def test_accepts_only_a_complete_v2_positive_and_negative_rehearsal() -> None:
    module = _module()
    module._validate_rehearsal_result(_result())


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("artifact_rows_for_sha",), False),
        (("chunk_set_count",), False),
        (("citation_traceability_pass",), 1),
        (("duplicate_chunk_sets",), False),
        (("duplicate_result_chunks",), False),
        (("duplicate_vector_sets",), False),
        (("full_governed_rehearsal_pass",), 1),
        (("lot41a_v2_content_bound",), 1),
        (("lot42_pipeline_path_implemented",), 1),
        (("placement_rows",), False),
        (("placement_traceability_pass",), 1),
        (("positive_content_allowlist_gate",), "DENY"),
        (("positive_extractor_calls",), True),
        (("real_multi_placement_placements",), False),
        (("real_multi_placement_sha",), "0" * 64),
        (("scope_a_retrieval_pass",), 1),
        (("scope_b_retrieval_pass",), 1),
        (("wrong_scope_retrieval_blocked",), 1),
        (("negative_same_domain_unlisted", "domain_gate"), "DENY"),
        (("negative_same_domain_unlisted", "content_allowlist_gate"), "PASS"),
        (("negative_same_domain_unlisted", "store_called"), 0),
        (("negative_same_domain_unlisted", "extractor_called"), 0),
        (("negative_same_domain_unlisted", "rights_agent_called"), 0),
        (("negative_same_domain_unlisted", "quality_agent_called"), 0),
        (("negative_same_domain_unlisted", "retrieval_eligible"), 0),
        (("negative_same_domain_unlisted", "resource_state"), "FETCHED"),
        (("negative_same_domain_unlisted", "control_artifact_rows"), False),
        (("negative_same_domain_unlisted", "pgvector_rows_created"), False),
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


def test_loads_only_a_sealed_materializer_manifest_and_real_catalog(
    tmp_path: Path,
) -> None:
    module = _module()
    inputs_path, inputs, catalog = _materialized_inputs(module, tmp_path)

    loaded = module._load_materialized_inputs(inputs_path)

    assert loaded.pdf_path == Path(str(inputs["pdf_path"])).resolve()
    assert loaded.catalog_path == Path(str(inputs["catalog_path"])).resolve()
    assert loaded.pii_evidence_path == Path(str(inputs["pii_evidence_path"])).resolve()
    assert loaded.inputs_manifest_sha256 == _sha256(inputs_path)
    assert loaded.placement_catalog_sha256 == catalog["placement_catalog_sha256"]
    assert len(loaded.placements) == 7


@pytest.mark.parametrize(
    ("target", "field", "value", "diagnostic"),
    [
        ("inputs", "inputs_manifest_kind", "SYNTHETIC", "INPUTS_MANIFEST_KIND_INVALID"),
        ("inputs", "remote_write_operations", 1, "REMOTE_WRITE_OPERATIONS_INVALID"),
        ("inputs", "manifest_sha256", "5" * 64, "INPUTS_MANIFEST_DIGEST_MISMATCH"),
        ("inputs", "pdf_sha256", "6" * 64, "MATERIALIZED_PDF_SHA256_MISMATCH"),
        ("inputs", "catalog_sha256", "7" * 64, "MATERIALIZED_CATALOG_SHA256_MISMATCH"),
        ("inputs", "pii_evidence_sha256", "8" * 64, "MATERIALIZED_PII_SHA256_MISMATCH"),
        ("inputs", "placement_catalog_sha256", "9" * 64, "PLACEMENT_CATALOG_DIGEST_MISMATCH"),
        ("catalog", "catalog_kind", "TEST_SYNTHETIC", "REAL_CATALOG_KIND_INVALID"),
        ("catalog", "manifest_sha256", "a" * 64, "REAL_CATALOG_MANIFEST_MISMATCH"),
        ("catalog", "verification_passed", False, "REAL_CATALOG_VERIFICATION_FAILED"),
        ("catalog", "verification_errors", ["drift"], "REAL_CATALOG_VERIFICATION_FAILED"),
        ("catalog", "manifest_entries", 10, "REAL_CATALOG_COUNTS_INVALID"),
        ("catalog", "physical_object_count", 11, "REAL_CATALOG_COUNTS_INVALID"),
        ("catalog", "eduscol_unique_artifacts", 8, "REAL_CATALOG_COUNTS_INVALID"),
        ("catalog", "eduscol_placement_count", 13, "REAL_CATALOG_COUNTS_INVALID"),
    ],
)
def test_rejects_synthetic_or_drifted_materialized_inputs(
    tmp_path: Path,
    target: str,
    field: str,
    value: object,
    diagnostic: str,
) -> None:
    module = _module()
    inputs_path, inputs, catalog = _materialized_inputs(module, tmp_path)
    if target == "inputs":
        inputs[field] = value
    else:
        catalog[field] = value
        catalog_path = Path(str(inputs["catalog_path"]))
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        inputs["catalog_sha256"] = _sha256(catalog_path)
    inputs_path.write_text(json.dumps(inputs), encoding="utf-8")

    with pytest.raises(RuntimeError, match=diagnostic):
        module._load_materialized_inputs(inputs_path)


def test_rejects_a_seven_row_catalog_without_real_placement_semantics(
    tmp_path: Path,
) -> None:
    module = _module()
    inputs_path, inputs, catalog = _materialized_inputs(module, tmp_path)
    artifacts = catalog["artifacts"]
    assert isinstance(artifacts, dict)
    entry = artifacts[module.REAL_SHA]
    assert isinstance(entry, dict)
    placements = entry["pedagogical_placements"]
    assert isinstance(placements, list)
    placement = placements[0]
    assert isinstance(placement, dict)
    placement["classified"] = False
    catalog_path = Path(str(inputs["catalog_path"]))
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    inputs["catalog_sha256"] = _sha256(catalog_path)
    inputs_path.write_text(json.dumps(inputs), encoding="utf-8")

    with pytest.raises(RuntimeError, match="REAL_MULTI_PLACEMENT_SEMANTICS_INVALID"):
        module._load_materialized_inputs(inputs_path)


def test_negative_rehearsal_uses_the_real_fetcher_and_observed_side_effects() -> None:
    content = INTEGRATION.read_text(encoding="utf-8")
    assert "run_fetcher(" in content
    assert "ThreadingHTTPServer" in content
    assert "httpx.get(" in content
    assert "negative_trace =" not in content
    assert '"store_called": bool(store_calls)' in content
    assert '"resource_state": negative_state.value' in content
    assert '"control_artifact_rows": negative_control_artifact_rows' in content


def test_positive_rehearsal_reports_the_measured_single_pdf_parse() -> None:
    content = INTEGRATION.read_text(encoding="utf-8")
    assert "extraction_calls += 1" in content
    assert "def cached_extract(" in content
    assert '"positive_extractor_calls": extraction_calls' in content
    assert content.count("return _extract_pdf(content)") == 1
