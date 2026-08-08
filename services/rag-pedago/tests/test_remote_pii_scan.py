"""Tests for the bounded, read-only real-corpus PII scan runner."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from rag_pedago.imports.pii_scanner import PIIMatch, PIIScanResult
from rag_pedago.imports.remote_pii_scan import (
    CANONICAL_REMOTE_ROOT,
    rclone_bulk_download,
    rclone_download,
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


def _clean_scan(path: Path) -> PIIScanResult:
    return PIIScanResult(
        file_path=str(path),
        sha256=_digest(path.read_bytes()),
        pages_scanned=1,
        characters_scanned=100,
        pii_detected=False,
    )


def test_scans_each_unique_pdf_content_once_and_covers_every_physical_object(
    tmp_path: Path,
) -> None:
    manifest, policy, content = _write_inputs(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    downloads: list[str] = []
    scan_calls = 0

    def download(source: str, target: Path) -> None:
        downloads.append(source)
        target.write_bytes(
            content["first"]
            if source.endswith(("a.pdf", "a-copy.pdf"))
            else content["second"]
        )

    def scan(path: Path) -> PIIScanResult:
        nonlocal scan_calls
        scan_calls += 1
        return _clean_scan(path)

    evidence = scan_remote_corpus(
        manifest,
        policy,
        CANONICAL_REMOTE_ROOT,
        scratch,
        expected_manifest_sha256=_digest(manifest.read_bytes()),
        download_file=download,
        scan_file=scan,
    )

    assert len(downloads) == 3
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
    assert list(scratch.iterdir()) == []
    assert evidence["remote_write_operations"] == 0


def test_external_evidence_never_contains_raw_pii_or_exception_text(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest, policy, content = _write_inputs(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    canary = "CANARY.student@example.invalid"

    def download(source: str, target: Path) -> None:
        target.write_bytes(
            content["first"]
            if source.endswith(("a.pdf", "a-copy.pdf"))
            else content["second"]
        )

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
        scratch,
        expected_manifest_sha256=_digest(manifest.read_bytes()),
        download_file=download,
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
    manifest, policy, _content = _write_inputs(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    scan_calls = 0

    def corrupt_download(_source: str, target: Path) -> None:
        target.write_bytes(b"corrupted")

    def scan(_path: Path) -> PIIScanResult:
        nonlocal scan_calls
        scan_calls += 1
        raise AssertionError("scanner must not run on mismatching bytes")

    evidence = scan_remote_corpus(
        manifest,
        policy,
        CANONICAL_REMOTE_ROOT,
        scratch,
        expected_manifest_sha256=_digest(manifest.read_bytes()),
        download_file=corrupt_download,
        scan_file=scan,
    )

    assert scan_calls == 0
    assert evidence["summary"]["sha256_mismatches"] == 3
    assert evidence["summary"]["pii_quarantined"] == 3
    assert evidence["summary"]["pii_not_scanned"] == 3
    assert all(item["status"] == "QUARANTINED_SHA_MISMATCH" for item in evidence["results"])
    assert list(scratch.iterdir()) == []


def test_evidence_is_bound_to_scanner_policy_content_and_manifest(
    tmp_path: Path,
) -> None:
    manifest, policy, content = _write_inputs(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    def download(source: str, target: Path) -> None:
        target.write_bytes(
            content["first"] if source.endswith("a.pdf") else content["second"]
        )

    evidence = scan_remote_corpus(
        manifest,
        policy,
        CANONICAL_REMOTE_ROOT,
        scratch,
        expected_manifest_sha256=_digest(manifest.read_bytes()),
        download_file=download,
        scan_file=_clean_scan,
    )

    assert evidence["corpus_manifest_sha256"] == _digest(manifest.read_bytes())
    assert evidence["policy_sha256"] == _digest(policy.read_bytes())
    assert evidence["policy_version"] == "pii-test-v1"
    assert len(evidence["scanner_sha256"]) == 64
    assert evidence["scanner_version"].startswith("pii_scanner_h2b_v")
    assert all(len(item["content_sha256"]) == 64 for item in evidence["results"])


def test_rejects_noncanonical_remote_before_any_download(tmp_path: Path) -> None:
    manifest, policy, _content = _write_inputs(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    with pytest.raises(ValueError, match="canonical read-only corpus remote"):
        scan_remote_corpus(
            manifest,
            policy,
            "gdrive_ert:another-folder",
            scratch,
            expected_manifest_sha256=_digest(manifest.read_bytes()),
            download_file=lambda _source, _target: None,
            scan_file=_clean_scan,
        )


def test_rclone_download_only_builds_remote_to_local_copyto(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(command: list[str], **kwargs: Any) -> object:
        calls.append((command, kwargs))
        return object()

    monkeypatch.setattr("rag_pedago.imports.remote_pii_scan.subprocess.run", fake_run)
    target = tmp_path / "content.pdf"

    rclone_download(f"{CANONICAL_REMOTE_ROOT}/01_EDUSCOL_OFFICIEL/a.pdf", target)

    assert calls == [
        (
            [
                "rclone",
                "copyto",
                "--no-traverse",
                "--retries",
                "3",
                "--low-level-retries",
                "5",
                f"{CANONICAL_REMOTE_ROOT}/01_EDUSCOL_OFFICIEL/a.pdf",
                str(target),
            ],
            {
                "capture_output": True,
                "check": True,
                "text": False,
                "timeout": 300,
            },
        )
    ]


def test_bulk_transport_scans_local_mirror_without_per_file_rclone(
    tmp_path: Path,
) -> None:
    manifest, policy, content = _write_inputs(tmp_path)
    mirror = tmp_path / "mirror"
    for relative_path, payload in (
        ("01_EDUSCOL_OFFICIEL/a.pdf", content["first"]),
        ("00_INDEX_PROVENANCE/a-copy.pdf", content["first"]),
        ("02_NEXUS_DIAGNOSTICS/b.pdf", content["second"]),
    ):
        target = mirror / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    evidence = scan_remote_corpus(
        manifest,
        policy,
        CANONICAL_REMOTE_ROOT,
        mirror,
        expected_manifest_sha256=_digest(manifest.read_bytes()),
        download_file=lambda _source, _target: pytest.fail(
            "per-file rclone must not run in bulk mode"
        ),
        scan_file=_clean_scan,
        local_mirror=mirror,
    )

    assert evidence["summary"]["pii_cleared"] == 3
    assert list(mirror.rglob("*.pdf")) == []


def test_rclone_bulk_download_is_canonical_remote_to_bounded_local(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(command: list[str], **kwargs: Any) -> object:
        calls.append((command, kwargs))
        return object()

    monkeypatch.setattr("rag_pedago.imports.remote_pii_scan.subprocess.run", fake_run)
    mirror = tmp_path / "mirror"
    mirror.mkdir()

    rclone_bulk_download(CANONICAL_REMOTE_ROOT, mirror)

    assert calls == [
        (
            [
                "rclone",
                "copy",
                "--include",
                "*.pdf",
                "--transfers",
                "8",
                "--checkers",
                "16",
                "--retries",
                "3",
                "--low-level-retries",
                "5",
                CANONICAL_REMOTE_ROOT,
                str(mirror),
            ],
            {
                "capture_output": True,
                "check": True,
                "text": False,
                "timeout": 7200,
            },
        )
    ]
