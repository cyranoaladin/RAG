"""Tests for the bounded, read-only real-corpus PII scan runner."""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest

from rag_pedago.imports.pii_scanner import PIIMatch, PIIScanResult
from rag_pedago.imports.remote_pii_scan import (
    CANONICAL_REMOTE_ROOT,
    pii_scan_exit_code,
    scan_remote_corpus,
)


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, dict[str, bytes]]:
    content = {
        "first": b"first-pdf-content",
        "second": b"second-pdf-content",
    }
    manifest = tmp_path / "SHA256SUMS.txt"
    manifest.write_text(
        f"{_digest(content['first'])}  01_EDUSCOL_OFFICIEL/a.pdf\n"
        f"{_digest(content['first'])}  00_INDEX_PROVENANCE/a-copy.pdf\n"
        f"{_digest(content['second'])}  02_NEXUS_DIAGNOSTICS/b.pdf\n"
        f"{'c' * 64}  00_ADMIN/info.json\n",
        encoding="utf-8",
    )
    policy = tmp_path / "pii_gate_policy.yml"
    policy.write_text("policy_id: pii-test-v1\n", encoding="utf-8")
    return manifest, policy, content


def _write_mirror(
    tmp_path: Path,
    content: dict[str, bytes],
    *,
    corrupt: bool = False,
) -> Path:
    mirror = tmp_path / "mirror"
    for relative_path, payload in (
        ("01_EDUSCOL_OFFICIEL/a.pdf", content["first"]),
        ("00_INDEX_PROVENANCE/a-copy.pdf", content["first"]),
        ("02_NEXUS_DIAGNOSTICS/b.pdf", content["second"]),
    ):
        target = mirror / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"corrupted" if corrupt else payload)
    return mirror


def _clean_scan(path: Path) -> PIIScanResult:
    return PIIScanResult(
        file_path=str(path),
        sha256=_digest(path.read_bytes()),
        pages_scanned=1,
        characters_scanned=100,
        pii_detected=False,
    )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, 0),
        ({"pii_not_scanned": 1, "pii_scan_coverage": 0.5}, 1),
        ({"pii_extraction_failed": 1, "pii_not_scanned": 1}, 1),
        ({"pii_extraction_failed": 1}, 1),
        ({"pii_review_required": 1, "pii_not_scanned": 1}, 1),
        ({"pii_review_required": 1}, 1),
        ({"sha256_mismatches": 1, "pii_not_scanned": 1}, 1),
        ({"pii_scan_required": 0, "pii_scanned": 0}, 1),
        ({"pii_not_scanned": False}, 1),
        ({"pii_review_required": False}, 1),
        ({"pii_extraction_failed": False}, 1),
        ({"sha256_mismatches": False}, 1),
        ({"pii_scan_coverage": True}, 1),
    ],
    ids=(
        "complete",
        "missing-local-file",
        "extraction-failed",
        "inconsistent-extraction-failed",
        "scanner-failed",
        "inconsistent-review-required",
        "sha-mismatch",
        "empty-perimeter",
        "boolean-not-scanned",
        "boolean-review-required",
        "boolean-extraction-failed",
        "boolean-mismatch",
        "boolean-coverage",
    ),
)
def test_cli_exit_code_requires_conclusive_scan_coverage(
    overrides: dict[str, int | float], expected: int
) -> None:
    summary: dict[str, int | float | str] = {
        "pii_scan_required": 2,
        "pii_scanned": 2,
        "pii_cleared": 2,
        "pii_quarantined": 0,
        "pii_review_required": 0,
        "pii_extraction_failed": 0,
        "pii_not_scanned": 0,
        "pii_scan_coverage": 1.0,
        "sha256_mismatches": 0,
    }
    summary.update(overrides)

    assert pii_scan_exit_code(summary) == expected


@pytest.mark.parametrize(
    "overrides",
    (
        {"pii_cleared": 1},
        {"pii_quarantined": 1},
        {"pii_cleared": True},
        {"pii_quarantined": False},
    ),
    ids=(
        "unaccounted-scanned-object",
        "inconsistent-quarantine-total",
        "boolean-cleared",
        "boolean-quarantined",
    ),
)
def test_cli_exit_code_rejects_inconsistent_disposition_totals(
    overrides: dict[str, int | bool],
) -> None:
    summary: dict[str, int | float | str] = {
        "pii_scan_required": 2,
        "pii_scanned": 2,
        "pii_cleared": 2,
        "pii_quarantined": 0,
        "pii_review_required": 0,
        "pii_extraction_failed": 0,
        "pii_not_scanned": 0,
        "pii_scan_coverage": 1.0,
        "sha256_mismatches": 0,
    }
    summary.update(overrides)

    assert pii_scan_exit_code(summary) == 1


def test_scans_each_unique_pdf_content_once_and_covers_every_physical_object(
    tmp_path: Path,
) -> None:
    manifest, policy, content = _write_inputs(tmp_path)
    mirror = _write_mirror(tmp_path, content)
    scan_calls = 0

    def scan(path: Path) -> PIIScanResult:
        nonlocal scan_calls
        scan_calls += 1
        return _clean_scan(path)

    evidence = scan_remote_corpus(
        manifest,
        policy,
        CANONICAL_REMOTE_ROOT,
        mirror,
        expected_manifest_sha256=_digest(manifest.read_bytes()),
        scan_file=scan,
    )

    assert scan_calls == 2
    assert evidence["summary"] == {
        "pdf_total": 3,
        "pii_scan_scope": "ALL_CORPUS_PDFS",
        "pii_scan_required": 3,
        "pii_scan_exempt": 0,
        "unique_pdf_content": 2,
        "unique_content_attempted": 2,
        "pii_scanned": 3,
        "pii_cleared": 3,
        "pii_review_required": 0,
        "pii_quarantined": 0,
        "pii_extraction_failed": 0,
        "pii_not_scanned": 0,
        "pii_scan_coverage": 1.0,
        "sha256_mismatches": 0,
    }
    assert len(evidence["results"]) == 2
    assert sorted(item["physical_object_count"] for item in evidence["results"]) == [1, 2]
    assert len(list(mirror.rglob("*.pdf"))) == 3
    assert evidence["remote_write_operations"] == 0


def test_initial_promotion_scope_scans_every_candidate_and_counts_exemptions(
    tmp_path: Path,
) -> None:
    manifest, policy, content = _write_inputs(tmp_path)
    mirror = _write_mirror(tmp_path, content)
    required_paths = {
        "01_EDUSCOL_OFFICIEL/a.pdf",
        "00_INDEX_PROVENANCE/a-copy.pdf",
    }

    evidence = scan_remote_corpus(
        manifest,
        policy,
        CANONICAL_REMOTE_ROOT,
        mirror,
        expected_manifest_sha256=_digest(manifest.read_bytes()),
        scan_file=_clean_scan,
        required_pdf_paths=required_paths,
    )

    assert evidence["summary"] == {
        "pdf_total": 3,
        "pii_scan_scope": "INITIAL_PRODUCTION_ELIGIBLE_PDFS",
        "pii_scan_required": 2,
        "pii_scan_exempt": 1,
        "unique_pdf_content": 1,
        "unique_content_attempted": 1,
        "pii_scanned": 2,
        "pii_cleared": 2,
        "pii_review_required": 0,
        "pii_quarantined": 0,
        "pii_extraction_failed": 0,
        "pii_not_scanned": 0,
        "pii_scan_coverage": 1.0,
        "sha256_mismatches": 0,
    }
    assert evidence["required_pdf_path_count"] == 2
    assert len(evidence["required_pdf_path_set_digest"]) == 64
    assert len(evidence["results"]) == 1


def test_external_evidence_never_contains_raw_pii_or_exception_text(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest, policy, content = _write_inputs(tmp_path)
    mirror = _write_mirror(tmp_path, content)
    canary = "CANARY.student@example.invalid"

    def scan(path: Path) -> PIIScanResult:
        if path.read_bytes() == content["first"]:
            return PIIScanResult(
                file_path=f"/tmp/{canary}.pdf",
                sha256=_digest(content["first"]),
                pages_scanned=1,
                characters_scanned=100,
                pii_detected=True,
                matches=[
                    PIIMatch(
                        pattern_id="email_address",
                        description="email",
                        match_text=canary,
                        page_number=1,
                        char_offset=4,
                        context=f"Contact {canary}",
                    )
                ],
            )
        return PIIScanResult(
            file_path=str(path),
            sha256=_digest(content["second"]),
            pages_scanned=0,
            characters_scanned=0,
            pii_detected=False,
            extraction_error=f"failed near {canary}",
        )

    evidence = scan_remote_corpus(
        manifest,
        policy,
        CANONICAL_REMOTE_ROOT,
        mirror,
        expected_manifest_sha256=_digest(manifest.read_bytes()),
        scan_file=scan,
    )
    serialized = json.dumps(evidence)
    captured = capsys.readouterr()

    assert canary not in serialized
    assert canary not in captured.out
    assert canary not in captured.err
    assert evidence["raw_pii_in_output"] is False
    assert evidence["raw_pii_in_logs"] is False
    assert evidence["summary"]["pii_quarantined"] == 2
    assert evidence["summary"]["pii_extraction_failed"] == 1
    assert evidence["summary"]["pii_not_scanned"] == 1


def test_sha_mismatch_blocks_before_scanner_execution(tmp_path: Path) -> None:
    manifest, policy, content = _write_inputs(tmp_path)
    mirror = _write_mirror(tmp_path, content, corrupt=True)
    scan_calls = 0

    def scan(_path: Path) -> PIIScanResult:
        nonlocal scan_calls
        scan_calls += 1
        raise AssertionError("scanner must not run on mismatching bytes")

    evidence = scan_remote_corpus(
        manifest,
        policy,
        CANONICAL_REMOTE_ROOT,
        mirror,
        expected_manifest_sha256=_digest(manifest.read_bytes()),
        scan_file=scan,
    )

    assert scan_calls == 0
    assert evidence["summary"]["sha256_mismatches"] == 3
    assert evidence["summary"]["pii_quarantined"] == 3
    assert evidence["summary"]["pii_not_scanned"] == 3
    assert all(item["status"] == "QUARANTINED_SHA_MISMATCH" for item in evidence["results"])
    assert len(list(mirror.rglob("*.pdf"))) == 3


def test_evidence_is_bound_to_scanner_policy_content_and_manifest(
    tmp_path: Path,
) -> None:
    manifest, policy, content = _write_inputs(tmp_path)
    mirror = _write_mirror(tmp_path, content)

    evidence = scan_remote_corpus(
        manifest,
        policy,
        CANONICAL_REMOTE_ROOT,
        mirror,
        expected_manifest_sha256=_digest(manifest.read_bytes()),
        scan_file=_clean_scan,
    )

    assert evidence["corpus_manifest_sha256"] == _digest(manifest.read_bytes())
    assert evidence["policy_sha256"] == _digest(policy.read_bytes())
    assert evidence["policy_version"] == "pii-test-v1"
    assert len(evidence["scanner_sha256"]) == 64
    assert evidence["scanner_version"].startswith("pii_scanner_h2b_v")
    assert all(len(item["content_sha256"]) == 64 for item in evidence["results"])


def test_rejects_noncanonical_remote_before_local_read(tmp_path: Path) -> None:
    manifest, policy, content = _write_inputs(tmp_path)
    mirror = _write_mirror(tmp_path, content)

    with pytest.raises(ValueError, match="canonical read-only corpus remote"):
        scan_remote_corpus(
            manifest,
            policy,
            "gdrive_ert:another-folder",
            mirror,
            expected_manifest_sha256=_digest(manifest.read_bytes()),
            scan_file=_clean_scan,
        )


def test_scans_pre_staged_local_mirror_without_mutating_it(
    tmp_path: Path,
) -> None:
    manifest, policy, content = _write_inputs(tmp_path)
    mirror = _write_mirror(tmp_path, content)

    evidence = scan_remote_corpus(
        manifest,
        policy,
        CANONICAL_REMOTE_ROOT,
        mirror,
        expected_manifest_sha256=_digest(manifest.read_bytes()),
        scan_file=_clean_scan,
    )

    assert evidence["summary"]["pii_cleared"] == 3
    assert len(list(mirror.rglob("*.pdf"))) == 3


def test_accepts_a_mirror_under_the_explicit_configured_scratch_root(
    tmp_path: Path,
) -> None:
    manifest, policy, content = _write_inputs(tmp_path)
    scratch_root = tmp_path / "approved-scratch"
    scratch_root.mkdir()
    mirror = _write_mirror(scratch_root, content)

    evidence = scan_remote_corpus(
        manifest,
        policy,
        CANONICAL_REMOTE_ROOT,
        mirror,
        expected_manifest_sha256=_digest(manifest.read_bytes()),
        scan_file=_clean_scan,
        scratch_root=scratch_root,
    )

    assert evidence["summary"]["pii_scanned"] == 3


def test_rejects_a_mirror_outside_the_explicit_configured_scratch_root(
    tmp_path: Path,
) -> None:
    manifest, policy, content = _write_inputs(tmp_path)
    scratch_root = tmp_path / "approved-scratch"
    scratch_root.mkdir()
    mirror = _write_mirror(tmp_path / "other", content)

    with pytest.raises(ValueError, match="configured scratch root"):
        scan_remote_corpus(
            manifest,
            policy,
            CANONICAL_REMOTE_ROOT,
            mirror,
            expected_manifest_sha256=_digest(manifest.read_bytes()),
            scan_file=_clean_scan,
            scratch_root=scratch_root,
        )


def test_cli_exposes_a_configurable_scratch_root_without_literal_tmp() -> None:
    import rag_pedago.imports.remote_pii_scan as module

    source = inspect.getsource(module)
    assert "--scratch-root" in source
    assert "NEXUS_H2_PII_SCRATCH_ROOT" in source
    assert 'Path("/tmp")' not in source


def test_control_plane_scanner_has_no_network_or_rclone_dependency() -> None:
    module_path = (
        Path(__file__).parent.parent
        / "rag_pedago/imports/remote_pii_scan.py"
    )
    source = module_path.read_text(encoding="utf-8")

    assert "import subprocess" not in source
    assert "rclone" not in source.lower()
    assert "download_file" not in inspect.signature(scan_remote_corpus).parameters


def test_h2e_network_materializer_lives_outside_rag_pedago_service() -> None:
    repository_root = Path(__file__).resolve().parents[3]

    assert not (
        repository_root
        / "services/rag-pedago/scripts/h2e_materialize_rehearsal_inputs.py"
    ).exists()
    assert (repository_root / "scripts/h2e_materialize_rehearsal_inputs.py").is_file()
