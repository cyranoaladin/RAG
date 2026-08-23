from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
SCRIPT = SERVICE_ROOT / "scripts" / "recompute_final_release_set.py"
SEALED_ROOT = Path(
    os.environ.get(
        "NEXUS_SEALED_CORPUS_ROOT",
        Path.home() / "Téléchargements" / "NEXUS_RAG_GDRIVE_READY",
    )
)
EVIDENCE_ROOT = Path(
    os.environ.get(
        "NEXUS_H2_EVIDENCE_ROOT",
        Path.home() / "Documents" / "NEXUS_RAG_H2_EVIDENCE",
    )
)
REAL_INPUTS = {
    "manifest": SEALED_ROOT / "00_ADMIN" / "SHA256SUMS.txt",
    "placements": SEALED_ROOT / "00_ADMIN" / "eduscol_affectations.tsv",
    "pii_exhaustive": EVIDENCE_ROOT / "h2b_exhaustive_pii_scan_20260813.jsonl",
    "pii_campaign": EVIDENCE_ROOT / "h2b_pii_evidence_20260808.json",
}

SHA_A = "a" * 64
SHA_B = "b" * 64


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("recompute_final_release_set", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _physical(
    sha256: str,
    *,
    disposition: str,
    base_disposition: str,
    path: str,
) -> dict[str, object]:
    return {
        "content_sha256": sha256,
        "disposition": disposition,
        "base_disposition": base_disposition,
        "path": path,
    }


def test_required_content_with_conflicting_final_dispositions_is_refused() -> None:
    module = _load_script()
    physical = [
        _physical(
            SHA_A,
            disposition="INGEST",
            base_disposition="INGEST",
            path="a.pdf",
        ),
        _physical(
            SHA_A,
            disposition="REVIEW_REQUIRED",
            base_disposition="INGEST",
            path="alias-a.pdf",
        ),
    ]

    with pytest.raises(ValueError, match="authority-required.*final dispositions"):
        module._terminal_accounting(physical, frozenset({SHA_A}))


def test_required_content_with_conflicting_base_dispositions_is_refused() -> None:
    module = _load_script()
    physical = [
        _physical(
            SHA_A,
            disposition="INGEST",
            base_disposition="INGEST",
            path="a.pdf",
        ),
        _physical(
            SHA_A,
            disposition="INGEST",
            base_disposition="REVIEW_REQUIRED",
            path="alias-a.pdf",
        ),
    ]

    with pytest.raises(ValueError, match="authority-required.*base dispositions"):
        module._terminal_accounting(physical, frozenset({SHA_A}))


def test_non_required_conflict_is_terminal_review_and_does_not_mutate_input() -> None:
    module = _load_script()
    physical = [
        _physical(
            SHA_A,
            disposition="EXCLUDE",
            base_disposition="EXCLUDE",
            path="a.pdf",
        ),
        _physical(
            SHA_A,
            disposition="REVIEW_REQUIRED",
            base_disposition="REVIEW_REQUIRED",
            path="alias-a.pdf",
        ),
    ]
    before = copy.deepcopy(physical)

    rows, conflicts = module._terminal_accounting(physical, frozenset())

    assert physical == before
    assert rows == [
        {
            "base_dispositions": ["EXCLUDE", "REVIEW_REQUIRED"],
            "canonical_disposition": "REVIEW_REQUIRED",
            "content_sha256": SHA_A,
            "paths": ["a.pdf", "alias-a.pdf"],
            "release_terminal_disposition": "REVIEW_REQUIRED",
        }
    ]
    assert conflicts == [
        {
            "base_dispositions": ["EXCLUDE", "REVIEW_REQUIRED"],
            "content_sha256": SHA_A,
            "dispositions": ["EXCLUDE", "REVIEW_REQUIRED"],
        }
    ]


def test_exact_set_and_accounting_are_deterministic() -> None:
    module = _load_script()
    first_input = [
        _physical(
            SHA_B,
            disposition="REVIEW_REQUIRED",
            base_disposition="REVIEW_REQUIRED",
            path="b.pdf",
        ),
        _physical(
            SHA_A,
            disposition="INGEST",
            base_disposition="INGEST",
            path="a.pdf",
        ),
    ]
    second_input = list(reversed(copy.deepcopy(first_input)))
    required = frozenset({SHA_B, SHA_A})

    first_bytes = module._canonical_sha_set_bytes(required)
    second_bytes = module._canonical_sha_set_bytes(frozenset(reversed(tuple(required))))
    first_rows = module._terminal_accounting(first_input, required)
    second_rows = module._terminal_accounting(second_input, required)

    assert first_bytes == second_bytes == f"{SHA_A}\n{SHA_B}\n".encode("ascii")
    assert hashlib.sha256(first_bytes).hexdigest() == module.h2b.authority_required_set_digest(
        required
    )
    assert first_rows == second_rows


def test_parser_uses_portable_evidence_root_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_script()
    sealed = tmp_path / "sealed"
    evidence = tmp_path / "evidence"
    monkeypatch.setenv("NEXUS_SEALED_CORPUS_ROOT", str(sealed))
    monkeypatch.setenv("NEXUS_H2_EVIDENCE_ROOT", str(evidence))

    args = module._parser().parse_args(["--output-dir", str(tmp_path / "out")])

    assert args.manifest == sealed / "00_ADMIN/SHA256SUMS.txt"
    assert args.placements == sealed / "00_ADMIN/eduscol_affectations.tsv"
    assert args.pii_exhaustive == evidence / "h2b_exhaustive_pii_scan_20260813.jsonl"
    assert args.pii_campaign == evidence / "h2b_pii_evidence_20260808.json"


@pytest.mark.skipif(
    not all(path.is_file() for path in REAL_INPUTS.values()),
    reason="les preuves scellées externes ne sont pas disponibles",
)
def test_recompute_final_release_set_from_real_inputs(tmp_path: Path) -> None:
    output = tmp_path / "release-recalculation"
    command = [
        sys.executable,
        str(SCRIPT),
        "--manifest",
        str(REAL_INPUTS["manifest"]),
        "--placements",
        str(REAL_INPUTS["placements"]),
        "--pii-exhaustive",
        str(REAL_INPUTS["pii_exhaustive"]),
        "--pii-campaign",
        str(REAL_INPUTS["pii_campaign"]),
        "--output-dir",
        str(output),
    ]

    subprocess.run(command, cwd=SERVICE_ROOT, check=True)

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    exact_set = (output / "final_authority_required_set.txt").read_bytes()
    expected_set = (
        REPO_ROOT / "docs/reports/final_authority_required_set_20260823.txt"
    ).read_bytes()
    terminal_rows = (
        (output / "terminal_content_dispositions.jsonl").read_text(encoding="utf-8").splitlines()
    )

    assert summary["final_base_ingest_candidates"] == 73
    assert summary["final_non_authority_blocked_count"] == 1
    assert summary["final_authority_required_count"] == 72
    assert summary["final_authority_required_set_sha256"] == (
        "3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0"
    )
    assert exact_set == expected_set
    assert exact_set.endswith(b"\n")
    assert len(exact_set.splitlines()) == 72
    assert hashlib.sha256(exact_set).hexdigest() == summary["final_authority_required_set_sha256"]
    assert len(terminal_rows) == 2582
    assert summary["terminal_content_accounting"]["unaccounted_contents"] == 0
    assert summary["terminal_content_accounting"]["unexpected_contents"] == 0
    assert summary["terminal_content_accounting"]["coverage_percent"] == 100.0
    assert summary["terminal_content_accounting"]["release_terminal_disposition_counts"] == {
        "ARCHIVE_ONLY": 19,
        "EXCLUDE": 53,
        "INGEST_CANDIDATE": 72,
        "QUARANTINE": 2,
        "REVIEW_REQUIRED": 2399,
        "UNSUPPORTED": 37,
    }
