"""Jointure du successeur texte avec les preuves V4/V5 et l'allowlist privée."""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/go_live/prepare_student_public_candidate_inventory.py"
CHECKER = ROOT / "scripts/go_live/check_student_public_candidate_inventory.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def test_real_candidate_joins_all_text_shas_and_source_placements():
    builder = _load(SCRIPT, "student_inventory_builder")
    checker = _load(CHECKER, "student_inventory_checker")
    inputs = builder.load_sealed_inputs(ROOT)
    inventory, allowlist = builder.build_bundle(inputs)

    assert inventory["counts"] == {
        "collections": 11, "unique_artifacts": 253, "placements": 377,
    }
    rows = [candidate for collection in inventory["collections"]
            for candidate in collection["candidates"]]
    assert {row["content_sha256"] for row in rows} == {
        row["content_sha256"] for row in inputs["artifacts"]["artifacts"]
    }
    assert sum(len(row["placements"]) for row in rows) == 377
    assert all(row["physical_path"] == f"{row['content_sha256']}.txt"
               and row["media_type"] == "text/plain; charset=utf-8"
               for row in rows)
    assert allowlist["transfer_status"] == "NOT_TRANSFERRED"
    assert allowlist["allowed_file_count"] == 253
    assert all(row["file"].endswith(".txt") for row in allowlist["expected_files"])
    assert all("sha256_observed" not in row for row in allowlist["expected_files"])
    assert checker.verify_bundle(ROOT, inventory, allowlist)["placements"] == 377


def test_source_placement_sha_or_url_cannot_be_invented():
    builder = _load(SCRIPT, "student_inventory_builder")
    inputs = builder.load_sealed_inputs(ROOT)
    changed = copy.deepcopy(inputs)
    collection = changed["subjects"][0]["collection"]
    placement = changed["subjects"][0]["placements"][0]
    source = "v5" if "hggsp" in collection else "v4"
    for row in changed["source_inventories"][source]["collections"]:
        if row["collection"] != collection:
            continue
        for candidate in row["candidates"]:
            for original in candidate["placements"]:
                if original["source_placement_id"] == placement["source_placement_id"]:
                    candidate["content_sha256"] = "f" * 64
                    with pytest.raises(ValueError, match="source PDF SHA"):
                        builder.build_bundle(changed)
                    return
    pytest.fail("source placement fixture absent")


def test_unknown_placement_and_duplicate_identity_are_rejected():
    builder = _load(SCRIPT, "student_inventory_builder")
    inputs = builder.load_sealed_inputs(ROOT)
    changed = copy.deepcopy(inputs)
    changed["subjects"][0]["placements"][0]["source_placement_id"] = "f" * 64
    with pytest.raises(ValueError, match="source placement"):
        builder.build_bundle(changed)
    changed = copy.deepcopy(inputs)
    changed["subjects"][0]["placements"].append(
        copy.deepcopy(changed["subjects"][0]["placements"][0])
    )
    with pytest.raises(ValueError, match="duplicate"):
        builder.build_bundle(changed)


def test_pdf_or_tampered_allowlist_is_rejected():
    builder = _load(SCRIPT, "student_inventory_builder")
    checker = _load(CHECKER, "student_inventory_checker")
    inputs = builder.load_sealed_inputs(ROOT)
    inventory, allowlist = builder.build_bundle(inputs)
    bad = copy.deepcopy(inventory)
    bad["collections"][0]["candidates"][0]["physical_path"] = "source.pdf"
    with pytest.raises(ValueError, match="text path"):
        checker.verify_bundle(ROOT, bad, allowlist)
    bad_allowlist = copy.deepcopy(allowlist)
    bad_allowlist["expected_files"][0]["sha256_observed"] = "a" * 64
    with pytest.raises(ValueError, match="observed|transfer"):
        checker.verify_bundle(ROOT, inventory, bad_allowlist)


def test_missing_or_extra_derivative_and_edited_inventory_are_rejected():
    builder = _load(SCRIPT, "student_inventory_builder")
    checker = _load(CHECKER, "student_inventory_checker")
    inputs = builder.load_sealed_inputs(ROOT)
    inventory, allowlist = builder.build_bundle(inputs)
    changed = copy.deepcopy(inputs)
    changed["candidate_manifest"]["entries"].pop()
    with pytest.raises(ValueError, match="candidate manifest|derivative"):
        builder.build_bundle(changed)
    edited = copy.deepcopy(inventory)
    edited["collections"][0]["candidates"][0]["placements"][0]["source_url"] = (
        "https://example.invalid/invented"
    )
    with pytest.raises(ValueError, match="source URL|provenance"):
        checker.verify_bundle(ROOT, edited, allowlist)


def test_parent_inventory_authority_is_bound_to_its_registry(tmp_path):
    builder = _load(SCRIPT, "student_inventory_builder")
    source = ROOT / builder.SOURCES["v4"]
    replica = tmp_path / "profile_gate"
    replica.mkdir()
    for name in ("candidate_inventory.json", "production-profile-gate.release.json"):
        shutil.copy2(source / name, replica / name)
    shutil.copy2(source.parent / "release-registry.json", tmp_path / "release-registry.json")
    manifest_path = replica / "production-profile-gate.release.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["review_status"] = "FORGED"
    manifest_path.write_text(json.dumps(manifest))
    builder.SOURCES = {**builder.SOURCES, "v4": replica}
    with pytest.raises(ValueError, match="source v4 release manifest digest"):
        builder.load_sealed_inputs(ROOT)


def test_derivative_collection_scope_cannot_be_added_or_removed():
    builder = _load(SCRIPT, "student_inventory_builder")
    checker = _load(CHECKER, "student_inventory_checker")
    inputs = builder.load_sealed_inputs(ROOT)
    inventory, allowlist = builder.build_bundle(inputs)
    changed = copy.deepcopy(inputs)
    changed["candidate_manifest"]["entries"][0]["collections"] = []
    with pytest.raises(ValueError, match="derivative collection scope"):
        builder.build_bundle(changed)
    edited = copy.deepcopy(inventory)
    sha = inputs["candidate_manifest"]["entries"][0]["derivative_content_sha256"]
    for collection in edited["collections"]:
        collection["candidates"] = [
            candidate for candidate in collection["candidates"]
            if candidate["content_sha256"] != sha
        ]
    with pytest.raises(ValueError, match="derivative collection scope|placement set|population"):
        checker.verify_bundle(ROOT, edited, allowlist)


def test_operator_commands_generate_then_verify_without_pythonpath(tmp_path):
    for script, option in ((SCRIPT, "--output-dir"), (CHECKER, "--bundle-dir")):
        result = subprocess.run(
            [sys.executable, str(script), "--repository-root", str(ROOT),
             option, str(tmp_path)],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr
    assert (tmp_path / "candidate_inventory.json").is_file()
    assert (tmp_path / "private_transfer_allowlist.json").is_file()
