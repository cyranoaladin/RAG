from __future__ import annotations

import json
from pathlib import Path

import pytest

from rag_pedago.imports.controlled_import import (
    ControlledImportStatus,
    controlled_import_manifest_directory,
)
from rag_pedago.imports.quality import QualityPolicy
from rag_pedago.imports.review import (
    ReviewerPolicy,
    approve_review_package,
    build_review_package,
    canonical_json_bytes,
    sha256_canonical_json,
)

ROOT = Path(__file__).resolve().parents[2]
BATCH_CLEAN = ROOT / "data/fixtures/manifests/batch_official_profiles_clean"
TAXONOMIES = [
    ROOT / "taxonomy/maths/terminale_specialite.yml",
    ROOT / "taxonomy/nsi/terminale.yml",
]


def make_package_and_decision(tmp_path, batch_id: str = "review-hardening"):
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
    return package, tmp_path / "reviews" / f"review_{decision.review_id}.json"


def import_with_review(tmp_path, batch_dir: Path, batch_id: str, package_path: Path, decision_path: Path):
    return controlled_import_manifest_directory(
        batch_dir,
        db_path=tmp_path / "ledger.sqlite",
        batch_id=batch_id,
        taxonomy_paths=TAXONOMIES,
        policy=QualityPolicy(),
        output_dir=tmp_path / "reports",
        require_review=True,
        review_package_path=package_path,
        review_decision_path=decision_path,
    )


def copy_batch(tmp_path: Path) -> Path:
    directory = tmp_path / "batch"
    directory.mkdir()
    for path in BATCH_CLEAN.glob("*.jsonl"):
        (directory / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return directory


def test_canonical_json_hash_independent_of_key_order() -> None:
    first = {"b": 2, "a": {"d": 4, "c": 3}}
    second = {"a": {"c": 3, "d": 4}, "b": 2}

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert sha256_canonical_json(first) == sha256_canonical_json(second)
    assert sha256_canonical_json(first) != sha256_canonical_json({"b": 2, "a": {"c": 9}})


def test_reviewed_import_requires_review_package_when_review_required(tmp_path) -> None:
    _, decision_path = make_package_and_decision(tmp_path, "review-package-required")

    with pytest.raises(ValueError, match="review_package_path is required"):
        controlled_import_manifest_directory(
            BATCH_CLEAN,
            db_path=tmp_path / "ledger.sqlite",
            batch_id="review-package-required",
            taxonomy_paths=TAXONOMIES,
            policy=QualityPolicy(),
            output_dir=tmp_path / "reports",
            require_review=True,
            review_decision_path=decision_path,
        )


def test_reviewed_import_rejects_modified_review_package(tmp_path) -> None:
    package, decision_path = make_package_and_decision(tmp_path, "review-package-modified")
    payload = json.loads(package.json_path.read_text(encoding="utf-8"))
    payload["recommended_actions"] = ["modified"]
    package.json_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="review_package_sha256 mismatch"):
        import_with_review(tmp_path, BATCH_CLEAN, "review-package-modified", package.json_path, decision_path)


def test_reviewed_import_rejects_modified_manifest(tmp_path) -> None:
    package, decision_path = make_package_and_decision(tmp_path, "review-manifest-modified")
    directory = copy_batch(tmp_path)
    path = directory / "aefe_scolarise_clean.jsonl"
    path.write_text(path.read_text(encoding="utf-8").replace("fonction_exponentielle", "suites"), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest hashes mismatch"):
        import_with_review(tmp_path, directory, "review-manifest-modified", package.json_path, decision_path)


def test_reviewed_import_rejects_added_manifest(tmp_path) -> None:
    package, decision_path = make_package_and_decision(tmp_path, "review-manifest-added")
    directory = copy_batch(tmp_path)
    (directory / "extra.jsonl").write_text((directory / "aefe_scolarise_clean.jsonl").read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest hashes mismatch"):
        import_with_review(tmp_path, directory, "review-manifest-added", package.json_path, decision_path)


def test_reviewed_import_rejects_deleted_manifest(tmp_path) -> None:
    package, decision_path = make_package_and_decision(tmp_path, "review-manifest-deleted")
    directory = copy_batch(tmp_path)
    (directory / "aefe_scolarise_clean.jsonl").unlink()

    with pytest.raises(ValueError, match="manifest hashes mismatch"):
        import_with_review(tmp_path, directory, "review-manifest-deleted", package.json_path, decision_path)


def test_reviewed_import_rejects_modified_taxonomy(tmp_path) -> None:
    taxonomy = tmp_path / "taxonomy.yml"
    taxonomy.write_text(TAXONOMIES[0].read_text(encoding="utf-8"), encoding="utf-8")
    package = build_review_package(
        BATCH_CLEAN,
        "review-taxonomy-modified",
        [taxonomy, TAXONOMIES[1]],
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )
    decision = approve_review_package(
        package.json_path,
        reviewer="Nexus Direction",
        decision="approved",
        output_dir=tmp_path / "reviews",
    )
    taxonomy.write_text(taxonomy.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="taxonomy hashes mismatch"):
        controlled_import_manifest_directory(
            BATCH_CLEAN,
            db_path=tmp_path / "ledger.sqlite",
            batch_id="review-taxonomy-modified",
            taxonomy_paths=[taxonomy, TAXONOMIES[1]],
            policy=QualityPolicy(),
            output_dir=tmp_path / "reports",
            require_review=True,
            review_package_path=package.json_path,
            review_decision_path=tmp_path / "reviews" / f"review_{decision.review_id}.json",
        )


def test_reviewed_import_rejects_modified_official_reference(tmp_path, monkeypatch) -> None:
    package, decision_path = make_package_and_decision(tmp_path, "review-reference-modified")
    import rag_pedago.imports.controlled_import as controlled_import

    monkeypatch.setattr(controlled_import, "sha256_directory_yaml", lambda path: "0" * 64)

    with pytest.raises(ValueError, match="official_reference_sha256 mismatch"):
        import_with_review(tmp_path, BATCH_CLEAN, "review-reference-modified", package.json_path, decision_path)


def test_reviewed_import_accepts_valid_decision_and_package(tmp_path) -> None:
    package, decision_path = make_package_and_decision(tmp_path, "review-valid")

    report = import_with_review(tmp_path, BATCH_CLEAN, "review-valid", package.json_path, decision_path)

    assert report.status is ControlledImportStatus.imported
    assert report.review_package_hash_verified is True
    assert report.official_reference_hash_verified is True
    assert report.taxonomy_hash_verified is True
    assert report.manifest_hashes_verified is True


def test_approval_refuses_empty_reviewer(tmp_path) -> None:
    package = build_review_package(
        BATCH_CLEAN,
        "review-empty-reviewer",
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    with pytest.raises(ValueError, match="reviewer is required"):
        approve_review_package(package.json_path, reviewer="", decision="approved", output_dir=tmp_path / "reviews")


def test_approval_rejects_unknown_reviewer_when_policy_requires(tmp_path) -> None:
    package = build_review_package(
        BATCH_CLEAN,
        "review-unknown-reviewer",
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    with pytest.raises(ValueError, match="reviewer is not allowed"):
        approve_review_package(
            package.json_path,
            reviewer="Unknown",
            decision="approved",
            output_dir=tmp_path / "reviews",
            reviewer_policy=ReviewerPolicy(
                allowed_reviewers=["Nexus Direction"],
                require_known_reviewer=True,
            ),
        )


def test_approval_registry_appends_decisions(tmp_path) -> None:
    package = build_review_package(
        BATCH_CLEAN,
        "review-registry",
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )
    approve_review_package(package.json_path, reviewer="Nexus Direction", decision="approved", output_dir=tmp_path / "reviews")
    approve_review_package(package.json_path, reviewer="Nexus Direction", decision="rejected", output_dir=tmp_path / "reviews")

    registry = tmp_path / "reviews" / "review_registry.jsonl"
    lines = registry.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["decision"] for line in lines] == ["approved", "rejected"]


def test_controlled_import_report_contains_review_verification_fields(tmp_path) -> None:
    package, decision_path = make_package_and_decision(tmp_path, "review-report-fields")

    report = import_with_review(tmp_path, BATCH_CLEAN, "review-report-fields", package.json_path, decision_path)
    markdown = report.markdown_path.read_text(encoding="utf-8")
    payload = json.loads(report.json_path.read_text(encoding="utf-8"))

    assert "Review package hash verified: true" in markdown
    assert "Official reference hash verified: true" in markdown
    assert payload["review"]["package_hash_verified"] is True
    assert payload["review"]["manifest_hashes_verified"] is True
