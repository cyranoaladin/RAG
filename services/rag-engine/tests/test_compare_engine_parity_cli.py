from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ENGINE_ROOT / "scripts" / "compare_engine_parity.py"
FIXTURES = ENGINE_ROOT / "tests" / "fixtures"
WITNESS = FIXTURES / "engine_parity_witness_v1.json"
ENGINE_A = FIXTURES / "engine_parity_a_v1.json"
ENGINE_B = FIXTURES / "engine_parity_b_v1.json"


def _load_cli_module():
    spec = importlib.util.spec_from_file_location("compare_engine_parity_cli", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run(
    *arguments: str, timeout: float = 10
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(ENGINE_ROOT), str(ENGINE_ROOT.parents[1] / "packages" / "contracts" / "src"))
    )
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--witness",
            str(WITNESS),
            "--engine-a",
            str(ENGINE_A),
            "--engine-b",
            str(ENGINE_B),
            *arguments,
        ],
        cwd=ENGINE_ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
    )


def test_cli_emits_summary_only_for_explicit_local_inputs() -> None:
    result = _run()

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["protocol_version"] == "NEXUS-ENGINE-PARITY-REPORT-V1"
    assert summary["verdict"] == "METRICS_ONLY_THRESHOLDS_UNAPPROVED"
    assert summary["reason_codes"] == []
    assert summary["passage_divergence_count"] == 0
    assert summary["synthetic_evidence"] is True
    assert {item["engine"] for item in summary["metrics"]} == {"A", "B"}
    assert len(summary["report_sha256"]) == 64
    assert "Définir une pile" not in result.stdout
    assert "ordered_results" not in result.stdout
    assert result.stderr == ""


def test_cli_writes_only_a_new_report(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    created = _run("--write-report", str(output))

    assert created.returncode == 0, created.stderr
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["report_sha256"] == json.loads(created.stdout)["report_sha256"]
    assert output.read_bytes().endswith(b"\n")

    before = output.read_bytes()
    refused = _run("--write-report", str(output))
    assert refused.returncode != 0
    assert output.read_bytes() == before
    assert "already exists" in refused.stderr


def test_report_digest_seals_the_protocol_envelope(tmp_path: Path) -> None:
    output = tmp_path / "report.json"

    created = _run("--write-report", str(output))

    assert created.returncode == 0, created.stderr
    document = json.loads(output.read_text(encoding="utf-8"))
    unsigned = {
        key: value for key, value in document.items() if key != "report_sha256"
    }
    expected = hashlib.sha256(
        (
            json.dumps(
                unsigned,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    ).hexdigest()
    assert document["report_sha256"] == expected


def test_cli_sanitizes_invalid_capture_content(tmp_path: Path) -> None:
    canary = "CANARY-PARITY-PAYLOAD-MUST-NOT-LEAK"
    invalid = json.loads(ENGINE_B.read_text(encoding="utf-8"))
    invalid["queries"][0]["ordered_results"][0]["unexpected"] = canary
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(invalid), encoding="utf-8")

    result = _run("--engine-b", str(path))

    assert result.returncode != 0
    assert result.stdout == ""
    assert canary not in result.stderr
    assert result.stderr.startswith("REFUSED:")


def test_cli_refuses_non_regular_input_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "CANARY-FIFO-SECRET.json"
    os.mkfifo(fifo, mode=0o600)

    result = _run("--engine-b", str(fifo), timeout=1)

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "REFUSED: parity input is unavailable\n"
    assert "CANARY-FIFO-SECRET" not in result.stderr


def test_cli_returns_nonzero_for_fail_closed_report(tmp_path: Path) -> None:
    unsafe = json.loads(ENGINE_B.read_text(encoding="utf-8"))
    unsafe["queries"][0]["ordered_results"][0]["scope"]["collection"] = (
        "rag_divers"
    )
    path = tmp_path / "unsafe.json"
    path.write_text(json.dumps(unsafe), encoding="utf-8")

    result = _run("--engine-b", str(path))

    assert result.returncode == 3
    assert json.loads(result.stdout)["verdict"] == "FAIL_CLOSED"
    assert result.stderr == ""


def test_report_publication_is_atomic_on_interrupted_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    output = tmp_path / "report.json"
    original_write = module.os.write
    calls = 0

    def interrupted_write(descriptor: int, raw: memoryview) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            original_write(descriptor, raw[:1])
        raise KeyboardInterrupt

    monkeypatch.setattr(module.os, "write", interrupted_write)

    with pytest.raises(KeyboardInterrupt):
        module._exclusive_write(output, b"complete report\n")

    assert not output.exists()
    assert list(tmp_path.iterdir()) == []


def test_report_publication_sanitizes_temporary_creation_failure(
    tmp_path: Path,
) -> None:
    canary = "CANARY-OUTPUT-SECRET"
    output = tmp_path / f"{canary}-{'x' * 260}.json"

    result = _run("--write-report", str(output))

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "REFUSED: output publication failed\n"
    assert canary not in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_cli_refuses_network_or_database_arguments_without_echoing_values() -> None:
    for option in ("--dsn", "--url", "--database-url"):
        result = _run(option, "CANARY-CONNECTION-SECRET")
        assert result.returncode != 0
        assert "CANARY-CONNECTION-SECRET" not in result.stdout
        assert "CANARY-CONNECTION-SECRET" not in result.stderr
