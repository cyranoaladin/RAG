from __future__ import annotations

import json
from pathlib import Path

import pytest

from rag_pedago.imports.controlled_import import (
    ControlledImportStatus,
    controlled_import_manifest_directory,
)
from rag_pedago.imports.quality import QualityPolicy
from rag_pedago.imports.review import approve_review_package, build_review_package

ROOT = Path(__file__).resolve().parents[2]
BATCH_CLEAN = ROOT / "data/fixtures/manifests/batch_official_profiles_clean"
TAXONOMIES = [
    ROOT / "taxonomy/maths/terminale_specialite.yml",
    ROOT / "taxonomy/nsi/terminale.yml",
]


def approved_decision(tmp_path, batch_id: str = "reviewed-import"):
    package = build_review_package(
        BATCH_CLEAN,
        batch_id,
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )
    decision = approve_review_package(
        package.json_path,
        reviewer="Nexus Direction",
        decision="approved",
        notes="Fixture clean validée",
        output_dir=tmp_path / "reviews",
    )
    return package, package.json_path, tmp_path / "reviews" / f"review_{decision.review_id}.json"


def test_reviewed_import_requires_review_when_enabled(tmp_path) -> None:
    with pytest.raises(ValueError, match="review_package_path is required"):
        controlled_import_manifest_directory(
            BATCH_CLEAN,
            db_path=tmp_path / "ledger.sqlite",
            batch_id="review-required",
            taxonomy_paths=TAXONOMIES,
            policy=QualityPolicy(),
            output_dir=tmp_path / "reports",
            require_review=True,
        )


def test_reviewed_import_rejects_wrong_batch_id(tmp_path) -> None:
    _, package_path, decision_path = approved_decision(tmp_path, "reviewed-import-source")

    with pytest.raises(ValueError, match="batch_id mismatch"):
        controlled_import_manifest_directory(
            BATCH_CLEAN,
            db_path=tmp_path / "ledger.sqlite",
            batch_id="reviewed-import-other",
            taxonomy_paths=TAXONOMIES,
            policy=QualityPolicy(),
            output_dir=tmp_path / "reports",
            require_review=True,
            review_package_path=package_path,
            review_decision_path=decision_path,
        )


def test_reviewed_import_rejects_gate_hash_mismatch(tmp_path) -> None:
    _, package_path, decision_path = approved_decision(tmp_path, "reviewed-import-hash")
    payload = json.loads(decision_path.read_text())
    payload["gate_json_sha256"] = "0" * 64
    decision_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="gate_json_sha256 mismatch"):
        controlled_import_manifest_directory(
            BATCH_CLEAN,
            db_path=tmp_path / "ledger.sqlite",
            batch_id="reviewed-import-hash",
            taxonomy_paths=TAXONOMIES,
            policy=QualityPolicy(),
            output_dir=tmp_path / "reports",
            require_review=True,
            review_package_path=package_path,
            review_decision_path=decision_path,
        )


def test_reviewed_import_imports_clean_batch_with_valid_approval(tmp_path) -> None:
    _, package_path, decision_path = approved_decision(tmp_path, "reviewed-import-ok")

    report = controlled_import_manifest_directory(
        BATCH_CLEAN,
        db_path=tmp_path / "ledger.sqlite",
        batch_id="reviewed-import-ok",
        taxonomy_paths=TAXONOMIES,
        policy=QualityPolicy(),
        output_dir=tmp_path / "reports",
        require_review=True,
        review_package_path=package_path,
        review_decision_path=decision_path,
    )

    assert report.status is ControlledImportStatus.imported
    assert report.review_required is True
    assert report.review_hash_verified is True
    assert report.review_decision == "approved"
    assert report.run_ids


def test_reviewed_import_blocks_if_manifest_changes_after_approval(tmp_path) -> None:
    _, package_path, decision_path = approved_decision(tmp_path, "reviewed-import-changed")
    changed_dir = tmp_path / "changed"
    changed_dir.mkdir()
    source = BATCH_CLEAN / "aefe_scolarise_clean.jsonl"
    target = changed_dir / source.name
    target.write_text(source.read_text() + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="manifest hashes mismatch"):
        controlled_import_manifest_directory(
            changed_dir,
            db_path=tmp_path / "ledger.sqlite",
            batch_id="reviewed-import-changed",
            taxonomy_paths=TAXONOMIES,
            policy=QualityPolicy(),
            output_dir=tmp_path / "reports",
            require_review=True,
            review_package_path=package_path,
            review_decision_path=decision_path,
        )
