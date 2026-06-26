from __future__ import annotations

import json
from pathlib import Path

import pytest

from rag_pedago.imports.approve_review_cli import main as approve_review_main
from rag_pedago.imports.quality import QualityPolicy
from rag_pedago.imports.review import (
    ReviewStatus,
    approve_review_package,
    build_review_package,
    sha256_directory_yaml,
)
from rag_pedago.imports.review_package_cli import main as review_package_main

ROOT = Path(__file__).resolve().parents[2]
BATCH_CLEAN = ROOT / "data/fixtures/manifests/batch_official_profiles_clean"
BATCH_MISMATCH = ROOT / "data/fixtures/manifests/batch_official_mismatch"
TAXONOMIES = [
    ROOT / "taxonomy/maths/terminale_specialite.yml",
    ROOT / "taxonomy/nsi/terminale.yml",
]


def test_review_package_ready_for_clean_batch(tmp_path) -> None:
    package = build_review_package(
        BATCH_CLEAN,
        "review-clean",
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    assert package.status is ReviewStatus.ready_for_review
    assert package.gate_status == "ready_for_controlled_import"
    assert package.json_path.exists()
    assert package.markdown_path.exists()


def test_review_package_blocked_for_mismatch_batch(tmp_path) -> None:
    package = build_review_package(
        BATCH_MISMATCH,
        "review-mismatch",
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    assert package.status is ReviewStatus.blocked_before_review
    assert package.gate_status == "blocked"


def test_review_package_contains_manifest_hashes(tmp_path) -> None:
    package = build_review_package(
        BATCH_CLEAN,
        "review-hashes",
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    assert package.manifests_sha256
    assert all(len(value) == 64 for value in package.manifests_sha256.values())


def test_review_package_contains_reference_and_taxonomy_hashes(tmp_path) -> None:
    package = build_review_package(
        BATCH_CLEAN,
        "review-reference",
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    assert package.official_reference_sha256 == sha256_directory_yaml(ROOT / "data/reference")
    assert set(package.taxonomy_sha256) == {str(path) for path in TAXONOMIES}
    assert all(len(value) == 64 for value in package.taxonomy_sha256.values())


def test_review_package_hash_is_cwd_independent(tmp_path, monkeypatch) -> None:
    reference = tmp_path / "reference"
    reference.mkdir()
    (reference / "a.yml").write_text("id: a\n", encoding="utf-8")
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()

    digest_before = sha256_directory_yaml(reference)
    monkeypatch.chdir(other_cwd)
    digest_after = sha256_directory_yaml(reference)

    assert digest_after == digest_before


def test_approve_review_package_creates_decision(tmp_path) -> None:
    package = build_review_package(
        BATCH_CLEAN,
        "review-approve",
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

    assert decision.decision == "approved"
    assert decision.batch_id == "review-approve"
    assert decision.review_package_sha256
    assert (tmp_path / "reviews" / f"review_{decision.review_id}.json").exists()


def test_approve_review_package_refuses_blocked_package(tmp_path) -> None:
    package = build_review_package(
        BATCH_MISMATCH,
        "review-blocked",
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    with pytest.raises(ValueError, match="blocked_before_review"):
        approve_review_package(
            package.json_path,
            reviewer="Nexus Direction",
            decision="approved",
            output_dir=tmp_path / "reviews",
        )


def test_reject_review_package_creates_rejection(tmp_path) -> None:
    package = build_review_package(
        BATCH_CLEAN,
        "review-reject",
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    decision = approve_review_package(
        package.json_path,
        reviewer="Nexus Direction",
        decision="rejected",
        notes="Revue refusée",
        output_dir=tmp_path / "reviews",
    )

    assert decision.decision == "rejected"
    payload = json.loads((tmp_path / "reviews" / f"review_{decision.review_id}.json").read_text())
    assert payload["decision"] == "rejected"


def test_review_package_does_not_create_ledger(tmp_path) -> None:
    build_review_package(
        BATCH_CLEAN,
        "review-no-ledger",
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    assert not (tmp_path / "rag_pedago.sqlite").exists()


def test_review_cli_outputs_paths(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "review_package_cli",
            str(BATCH_CLEAN),
            "--batch-id",
            "review-cli",
            "--taxonomy",
            str(TAXONOMIES[0]),
            "--taxonomy",
            str(TAXONOMIES[1]),
            "--output-dir",
            str(tmp_path / "reports"),
        ],
    )
    assert review_package_main() == 0
    output = capsys.readouterr().out
    assert "review package generated:" in output
    assert "json:" in output

    package_json = tmp_path / "reports" / "review_package_review-cli.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "approve_review_cli",
            str(package_json),
            "--reviewer",
            "Nexus Direction",
            "--decision",
            "approved",
            "--output-dir",
            str(tmp_path / "reviews"),
        ],
    )
    assert approve_review_main() == 0
    assert "review decision written:" in capsys.readouterr().out
