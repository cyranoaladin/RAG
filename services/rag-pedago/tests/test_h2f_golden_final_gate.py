"""Non-vacuity tests for the H2-F real sealed-corpus golden gate."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

from rag_pedago.imports.golden_corpus_validator import validate_golden_corpus
from rag_pedago.imports.h2b_coverage_report import (
    generate_coverage_report,
    main,
    render_markdown,
)

MANIFEST_SHA256 = "d" * 64


def _sha(index: int) -> str:
    return hashlib.sha256(str(index).encode()).hexdigest()


def _object(
    index: int,
    *,
    path: str,
    base: str,
    final: str,
    currentness: str | None,
    gates: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "content_sha256": _sha(index),
        "path": path,
        "base_disposition": base,
        "disposition": final,
        "currentness": currentness,
        "gate_statuses": gates or {},
        "provenance_status": "VERIFIED",
        "attribution_metadata": {
            "source": path.split("/", maxsplit=1)[0],
            "source_reference": path,
        },
    }


def _catalog() -> dict[str, object]:
    objects = [
        _object(
            1,
            path="01_EDUSCOL_OFFICIEL/LYCEE/10_ACTUEL_CONFIRME/PHILOSOPHIE/a.pdf",
            base="INGEST",
            final="REVIEW_REQUIRED",
            currentness="actuel",
            gates={
                "rights": "PASS",
                "pii": "PASS",
                "authority": "BLOCKED_NOT_CLEARED",
            },
        ),
        _object(
            2,
            path="01_EDUSCOL_OFFICIEL/LYCEE/80_A_VERIFIER/b.pdf",
            base="REVIEW_REQUIRED",
            final="REVIEW_REQUIRED",
            currentness="a_verifier",
        ),
        _object(
            3,
            path="01_EDUSCOL_OFFICIEL/LYCEE/80_A_VERIFIER/c.pdf",
            base="REVIEW_REQUIRED",
            final="REVIEW_REQUIRED",
            currentness="a_verifier",
        ),
        _object(
            4,
            path="03_RESSOURCES_INTERACTIVES/a.ggb",
            base="UNSUPPORTED",
            final="UNSUPPORTED",
            currentness=None,
        ),
        _object(
            5,
            path="03_RESSOURCES_INTERACTIVES/b.ggb",
            base="UNSUPPORTED",
            final="UNSUPPORTED",
            currentness=None,
        ),
        _object(
            6,
            path="00_ADMIN/SHA256SUMS.txt",
            base="EXCLUDE",
            final="EXCLUDE",
            currentness=None,
        ),
    ]
    counts: dict[str, int] = {}
    for item in objects:
        disposition = str(item["disposition"])
        counts[disposition] = counts.get(disposition, 0) + 1
    return {
        "catalog_kind": "REAL_SEALED_CORPUS",
        "manifest_sha256": MANIFEST_SHA256,
        "physical_object_count": len(objects),
        "disposition_counts": counts,
        "unclassified": 0,
        "multiple_primary_disposition": 0,
        "verification_passed": True,
        "physical_objects": objects,
    }


def _refresh_catalog_summary(catalog: dict[str, object]) -> None:
    objects = catalog["physical_objects"]
    counts: dict[str, int] = {}
    for item in objects:  # type: ignore[union-attr]
        disposition = str(item["disposition"])
        counts[disposition] = counts.get(disposition, 0) + 1
    catalog["physical_object_count"] = len(objects)  # type: ignore[arg-type]
    catalog["disposition_counts"] = counts


def _spec() -> dict[str, object]:
    return {
        "spec_id": "golden_h2f_test_v2",
        "catalog_kind_required": "REAL_SEALED_CORPUS",
        "positive_controls": [
            {
                "control_id": "pos_01",
                "sha256_prefix": _sha(1)[:12],
                "expected_base_disposition": "INGEST",
                "expected_final_disposition": "REVIEW_REQUIRED",
                "expected_currentness": "actuel",
                "expected_gate_statuses": {
                    "rights": "PASS",
                    "pii": "PASS",
                    "authority": "BLOCKED_NOT_CLEARED",
                },
            }
        ],
        "boundary_controls": [
            {
                "control_id": "bnd_01",
                "zone": "01_EDUSCOL_OFFICIEL/LYCEE/80_A_VERIFIER/",
                "expected_count_in_zone": 2,
                "expected_disposition": "REVIEW_REQUIRED",
                "expected_currentness": "a_verifier",
            }
        ],
        "negative_controls": [
            {
                "control_id": "neg_01",
                "path": "00_ADMIN/SHA256SUMS.txt",
                "expected_count": 1,
                "expected_disposition": "EXCLUDE",
            },
            {
                "control_id": "neg_02",
                "zone": "03_RESSOURCES_INTERACTIVES/",
                "expected_count_in_zone": 2,
                "expected_disposition": "UNSUPPORTED",
            },
        ],
        "descriptive_assertions": {
            "authoritative": False,
            "reason": "Human-readable summary only; controls above are executable.",
            "items": [{"assertion_id": "summary_only"}],
        },
        "coverage_summary": {
            "total_controls": 4,
            "positive_controls": 1,
            "boundary_controls": 1,
            "negative_controls": 2,
        },
    }


def _write_inputs(
    tmp_path: Path,
    *,
    catalog: dict[str, object] | None = None,
    spec: dict[str, object] | None = None,
) -> tuple[Path, Path]:
    catalog_path = tmp_path / "real-catalog.json"
    spec_path = tmp_path / "golden.yml"
    catalog_path.write_text(
        json.dumps(catalog or _catalog(), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    spec_path.write_text(
        yaml.safe_dump(spec or _spec(), sort_keys=False),
        encoding="utf-8",
    )
    return catalog_path, spec_path


def _validate(
    tmp_path: Path,
    *,
    catalog: dict[str, object] | None = None,
    spec: dict[str, object] | None = None,
):
    catalog_path, spec_path = _write_inputs(
        tmp_path,
        catalog=catalog,
        spec=spec,
    )
    return validate_golden_corpus(
        spec or _spec(),
        catalog or _catalog(),
        spec_path,
        catalog_path,
    )


def test_real_sealed_baseline_is_green_and_bound_to_full_digests(
    tmp_path: Path,
) -> None:
    report = _validate(tmp_path)

    assert report.validation_passed is True
    assert report.total_controls == 4
    assert report.passed_controls == 4
    assert report.failed_controls == 0
    assert report.objects_evaluated == 6
    assert len(report.catalog_sha256) == 64
    assert len(report.spec_sha256) == 64
    assert report.catalog_manifest_sha256 == MANIFEST_SHA256
    assert len(report.git_head) == 40
    machine = report.to_dict()
    assert machine["golden_controls_total"] == 4
    assert machine["golden_controls_passed"] == 4
    assert machine["golden_controls_failed"] == 0
    assert machine["golden_validation_passed"] is True
    assert machine["positive_controls_total"] == 1
    assert machine["boundary_controls_total"] == 1
    assert machine["negative_controls_total"] == 2
    assert machine["objects_evaluated"] == 6


def test_final_gate_rejects_legacy_objects_schema(tmp_path: Path) -> None:
    catalog = _catalog()
    catalog["objects"] = catalog.pop("physical_objects")

    with pytest.raises(ValueError, match="physical_objects"):
        _validate(tmp_path, catalog=catalog)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("content_sha256", "not-a-sha", "content_sha256"),
        ("provenance_status", None, "provenance_status"),
        ("attribution_metadata", {}, "attribution_metadata"),
        ("gate_statuses", None, "gate_statuses"),
    ],
)
def test_final_gate_rejects_malformed_real_object(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    catalog = _catalog()
    catalog["physical_objects"][0][field] = value  # type: ignore[index]

    with pytest.raises(ValueError, match=message):
        _validate(tmp_path, catalog=catalog)


def test_final_gate_rejects_missing_currentness_field(tmp_path: Path) -> None:
    catalog = _catalog()
    del catalog["physical_objects"][0]["currentness"]  # type: ignore[index]

    with pytest.raises(ValueError, match="currentness field is missing"):
        _validate(tmp_path, catalog=catalog)


def test_final_gate_rejects_duplicate_control_ids(tmp_path: Path) -> None:
    spec = _spec()
    spec["negative_controls"][0]["control_id"] = "pos_01"  # type: ignore[index]

    with pytest.raises(ValueError, match="control_id values must be unique"):
        _validate(tmp_path, spec=spec)


def test_positive_control_requires_unique_sha_prefix(tmp_path: Path) -> None:
    spec = _spec()
    spec["positive_controls"][0]["sha256_prefix"] = ""  # type: ignore[index]
    with pytest.raises(ValueError, match="non-empty SHA256 prefix"):
        _validate(tmp_path, spec=spec)

    spec = _spec()
    spec["positive_controls"][0]["sha256_prefix"] = "f" * 12  # type: ignore[index]
    report = _validate(tmp_path, spec=spec)
    assert report.validation_passed is False
    assert "zero objects" in report.control_results[0].failure_reason

    catalog = _catalog()
    first_sha = catalog["physical_objects"][0]["content_sha256"]  # type: ignore[index]
    catalog["physical_objects"][1]["content_sha256"] = (  # type: ignore[index]
        first_sha[:-1] + ("0" if first_sha[-1] != "0" else "1")
    )
    spec = _spec()
    spec["positive_controls"][0]["sha256_prefix"] = _sha(1)[:10]  # type: ignore[index]
    report = _validate(tmp_path, catalog=catalog, spec=spec)
    assert report.validation_passed is False
    assert "ambiguous" in report.control_results[0].failure_reason


def test_currentness_never_shortcuts_wrong_positive_disposition(tmp_path: Path) -> None:
    catalog = _catalog()
    catalog["physical_objects"][0]["base_disposition"] = "REVIEW_REQUIRED"  # type: ignore[index]

    report = _validate(tmp_path, catalog=catalog)

    assert report.validation_passed is False
    assert report.control_results[0].actual_base_disposition == "REVIEW_REQUIRED"


def test_positive_final_disposition_mutation_is_detected(tmp_path: Path) -> None:
    catalog = _catalog()
    catalog["physical_objects"][0]["disposition"] = "INGEST"  # type: ignore[index]

    report = _validate(tmp_path, catalog=catalog)

    assert report.validation_passed is False
    assert report.control_results[0].actual_disposition == "INGEST"


@pytest.mark.parametrize(
    ("mutation", "expected_actual"),
    [
        ("wrong_disposition", 2),
        ("remove", 1),
        ("add", 3),
    ],
)
def test_boundary_control_is_exhaustive_and_count_bound(
    tmp_path: Path,
    mutation: str,
    expected_actual: int,
) -> None:
    catalog = _catalog()
    objects = catalog["physical_objects"]
    if mutation == "wrong_disposition":
        objects[2]["disposition"] = "INGEST"  # type: ignore[index]
    elif mutation == "remove":
        objects.pop(2)  # type: ignore[union-attr]
    else:
        objects.append(  # type: ignore[union-attr]
            _object(
                7,
                path="01_EDUSCOL_OFFICIEL/LYCEE/80_A_VERIFIER/extra.pdf",
                base="REVIEW_REQUIRED",
                final="REVIEW_REQUIRED",
                currentness="a_verifier",
            )
        )
    _refresh_catalog_summary(catalog)

    report = _validate(tmp_path, catalog=catalog)
    boundary = report.control_results[1]
    assert boundary.passed is False
    assert boundary.actual_count == expected_actual
    if mutation == "wrong_disposition":
        assert boundary.mismatching_count == 1


def test_archive_boundary_disposition_mutation_is_detected(tmp_path: Path) -> None:
    catalog = _catalog()
    objects = catalog["physical_objects"]
    objects[1]["path"] = "01_EDUSCOL_OFFICIEL/90_ARCHIVE_CATALOGUE/b.pdf"  # type: ignore[index]
    objects[1]["base_disposition"] = "ARCHIVE_ONLY"  # type: ignore[index]
    objects[1]["disposition"] = "REVIEW_REQUIRED"  # type: ignore[index]
    objects[1]["currentness"] = "archive"  # type: ignore[index]
    spec = _spec()
    spec["boundary_controls"][0] = {  # type: ignore[index]
        "control_id": "bnd_archive",
        "zone": "01_EDUSCOL_OFFICIEL/90_ARCHIVE_CATALOGUE/",
        "expected_count_in_zone": 1,
        "expected_disposition": "ARCHIVE_ONLY",
        "expected_currentness": "archive",
    }
    _refresh_catalog_summary(catalog)

    report = _validate(tmp_path, catalog=catalog, spec=spec)

    assert report.validation_passed is False
    assert report.control_results[1].actual_count == 1
    assert report.control_results[1].mismatching_count == 1


def test_negative_absence_and_one_wrong_match_fail_closed(tmp_path: Path) -> None:
    catalog = _catalog()
    catalog["physical_objects"] = [  # type: ignore[index]
        item
        for item in catalog["physical_objects"]  # type: ignore[union-attr]
        if item["path"] != "00_ADMIN/SHA256SUMS.txt"
    ]
    _refresh_catalog_summary(catalog)
    report = _validate(tmp_path, catalog=catalog)
    assert report.control_results[2].passed is False
    assert report.control_results[2].actual_count == 0

    catalog = _catalog()
    catalog["physical_objects"][4]["disposition"] = "INGEST"  # type: ignore[index]
    report = _validate(tmp_path, catalog=catalog)
    assert report.control_results[3].passed is False
    assert report.control_results[3].mismatching_count == 1


def test_coverage_gate_executes_golden_and_separates_decision_coverage(
    tmp_path: Path,
) -> None:
    catalog_path, spec_path = _write_inputs(tmp_path)

    report = generate_coverage_report(
        catalog_path,
        golden_path=spec_path,
        expected_total=6,
        expected_manifest_sha256=MANIFEST_SHA256,
    )

    assert report.decision_coverage_complete is True
    assert report.golden_controls_total == 4
    assert report.golden_controls_passed == 4
    assert report.golden_controls_failed == 0
    assert report.golden_validation_pass is True
    assert report.h2_coverage_gate_pass is True
    assert report.coverage_complete is True
    assert len(report.input_files["catalog"]) == 64
    assert len(report.input_files["golden"]) == 64
    markdown = render_markdown(report)
    assert "DECISION_COVERAGE_COMPLETE=true" in markdown
    assert "GOLDEN_VALIDATION_PASS=true" in markdown
    assert "H2_COVERAGE_GATE_PASS=true" in markdown


def test_perfect_counts_with_one_golden_failure_keep_coverage_red(
    tmp_path: Path,
) -> None:
    spec = _spec()
    spec["boundary_controls"][0]["expected_disposition"] = "ARCHIVE_ONLY"  # type: ignore[index]
    catalog_path, spec_path = _write_inputs(tmp_path, spec=spec)

    report = generate_coverage_report(
        catalog_path,
        golden_path=spec_path,
        expected_total=6,
        expected_manifest_sha256=MANIFEST_SHA256,
    )

    assert report.decision_coverage_complete is True
    assert report.golden_validation_pass is False
    assert report.h2_coverage_gate_pass is False
    assert report.coverage_complete is False


def test_final_coverage_gate_requires_golden_spec(tmp_path: Path) -> None:
    catalog_path, _ = _write_inputs(tmp_path)

    with pytest.raises(ValueError, match="golden specification is required"):
        generate_coverage_report(
            catalog_path,
            expected_total=6,
            expected_manifest_sha256=MANIFEST_SHA256,
        )


def test_cli_returns_nonzero_for_golden_failure_and_malformed_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec()
    spec["boundary_controls"][0]["expected_disposition"] = "ARCHIVE_ONLY"  # type: ignore[index]
    catalog_path, spec_path = _write_inputs(tmp_path, spec=spec)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "h2b_coverage_report",
            "--catalog",
            str(catalog_path),
            "--golden",
            str(spec_path),
            "--expected-total",
            "6",
            "--expected-manifest-sha256",
            MANIFEST_SHA256,
        ],
    )
    assert main() != 0

    spec_path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid spec format"):
        main()


def test_golden_controls_are_non_vacuous(tmp_path: Path) -> None:
    baseline = _validate(tmp_path)
    mutant_catalog = copy.deepcopy(_catalog())
    mutant_catalog["physical_objects"][4]["disposition"] = "INGEST"  # type: ignore[index]
    mutant = _validate(tmp_path, catalog=mutant_catalog)
    restored = _validate(tmp_path)

    assert baseline.validation_passed is True
    assert mutant.validation_passed is False
    assert mutant.control_results[3].mismatching_count == 1
    assert restored.validation_passed is True
