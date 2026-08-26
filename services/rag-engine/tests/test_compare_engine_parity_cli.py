from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
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


def _recovery_capture(directory: Path) -> Path:
    recovery_directories = list(directory.glob(".nexus-rollback.*"))
    assert len(recovery_directories) == 1
    recovery_directory = recovery_directories[0]
    assert stat.S_IMODE(recovery_directory.stat().st_mode) == 0o700
    capture = recovery_directory / "captured"
    assert capture.is_file()
    return capture


def _staging_payload(directory: Path) -> Path:
    staging_directories = list(directory.glob(".nexus-staging.*"))
    assert len(staging_directories) == 1
    staging_directory = staging_directories[0]
    assert stat.S_IMODE(staging_directory.stat().st_mode) == 0o700
    payload = staging_directory / "payload"
    assert payload.is_file()
    return payload


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


def test_report_publication_uses_a_private_staging_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    output = tmp_path / "report.json"
    original_link = module.os.link
    staging_checked = False

    def inspect_staging(source: object, target: object, **kwargs: object) -> None:
        nonlocal staging_checked
        assert source == "payload"
        assert target == output.name
        staging_descriptor = kwargs["src_dir_fd"]
        assert isinstance(staging_descriptor, int)
        staging_status = module.os.fstat(staging_descriptor)
        assert stat.S_ISDIR(staging_status.st_mode)
        assert stat.S_IMODE(staging_status.st_mode) == 0o700
        assert staging_status.st_uid == module.os.geteuid()
        staging_checked = True
        original_link(source, target, **kwargs)

    monkeypatch.setattr(module.os, "link", inspect_staging)

    module._exclusive_write(output, b"complete report\n")

    assert staging_checked
    assert output.read_bytes() == b"complete report\n"
    assert list(tmp_path.iterdir()) == [output]


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


def test_report_publication_removes_link_on_directory_sync_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    output = tmp_path / "report.json"
    original_fsync = module.os.fsync

    def interrupt_directory_sync(descriptor: int) -> None:
        if stat.S_ISDIR(module.os.fstat(descriptor).st_mode):
            raise KeyboardInterrupt
        original_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", interrupt_directory_sync)

    with pytest.raises(KeyboardInterrupt):
        module._exclusive_write(output, b"complete report\n")

    assert not output.exists()
    assert _recovery_capture(tmp_path).read_bytes() == b"complete report\n"


def test_report_rollback_remains_bound_to_the_open_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    live_parent = tmp_path / "live"
    redirected_parent = tmp_path / "redirected"
    original_parent = tmp_path / "original"
    live_parent.mkdir()
    redirected_parent.mkdir()
    output = live_parent / "report.json"
    original_fsync = module.os.fsync
    redirected = False

    def redirect_then_interrupt(descriptor: int) -> None:
        nonlocal redirected
        if stat.S_ISDIR(module.os.fstat(descriptor).st_mode) and not redirected:
            redirected = True
            os.rename(live_parent, original_parent)
            os.rename(redirected_parent, live_parent)
            raise KeyboardInterrupt
        original_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", redirect_then_interrupt)

    with pytest.raises(KeyboardInterrupt):
        module._exclusive_write(output, b"complete report\n")

    assert not (original_parent / output.name).exists()
    assert not output.exists()
    assert _recovery_capture(original_parent).read_bytes() == b"complete report\n"


def test_report_publication_removes_link_when_link_is_interrupted_after_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    output = tmp_path / "report.json"
    original_link = module.os.link

    def interrupt_after_link(source: Path, target: Path, **kwargs: object) -> None:
        original_link(source, target, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(module.os, "link", interrupt_after_link)

    with pytest.raises(KeyboardInterrupt):
        module._exclusive_write(output, b"complete report\n")

    assert not output.exists()
    assert _recovery_capture(tmp_path).read_bytes() == b"complete report\n"


def test_report_rollback_preserves_target_replaced_during_identity_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    temporary = tmp_path / ".parity-report.owned.tmp"
    output = tmp_path / "report.json"
    foreign = tmp_path / "foreign.json"
    temporary.write_bytes(b"owned")
    foreign.write_bytes(b"foreign")
    os.link(temporary, output)
    parent_descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    temporary_descriptor = os.open(temporary, os.O_RDONLY)
    original_fstat = module.os.fstat
    replaced = False

    def fstat_then_replace(candidate: int):
        nonlocal replaced
        status = original_fstat(candidate)
        if candidate == temporary_descriptor and not replaced:
            replaced = True
            if output.exists():
                output.unlink()
            os.link(foreign, output)
        return status

    monkeypatch.setattr(module.os, "fstat", fstat_then_replace)

    try:
        module._rollback_matching_link(
            parent_descriptor, output.name, temporary_descriptor
        )
    finally:
        os.close(temporary_descriptor)
        os.close(parent_descriptor)

    assert output.read_bytes() == b"foreign"


def test_report_rollback_never_unlinks_a_substituted_recovery_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    temporary = tmp_path / ".parity-report.owned.tmp"
    output = tmp_path / "report.json"
    foreign = tmp_path / "foreign.json"
    temporary.write_bytes(b"owned")
    foreign.write_bytes(b"foreign")
    os.link(temporary, output)
    parent_descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    temporary_descriptor = os.open(temporary, os.O_RDONLY)
    foreign_descriptor = os.open(foreign, os.O_RDONLY)
    original_fstat = module.os.fstat
    original_replace = module.os.replace
    substituted = False

    def fstat_then_substitute(candidate: int):
        nonlocal substituted
        status = original_fstat(candidate)
        if candidate == temporary_descriptor and not substituted:
            substituted = True
            rescue_path = next(tmp_path.glob(".nexus-rollback.*")) / "captured"
            rescue_path.unlink()
            original_replace(foreign, rescue_path)
        return status

    monkeypatch.setattr(module.os, "fstat", fstat_then_substitute)

    try:
        module._rollback_matching_link(
            parent_descriptor, output.name, temporary_descriptor
        )
        assert os.fstat(foreign_descriptor).st_nlink >= 1
    finally:
        os.close(temporary_descriptor)
        os.close(parent_descriptor)
        os.close(foreign_descriptor)


def test_report_rollback_preserves_captured_target_when_replace_is_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    temporary = tmp_path / ".parity-report.owned.tmp"
    output = tmp_path / "report.json"
    temporary.write_bytes(b"owned")
    output.write_bytes(b"foreign")
    parent_descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    temporary_descriptor = os.open(temporary, os.O_RDONLY)
    original_replace = module.os.replace

    def interrupt_after_replace(
        source: object, target: object, **kwargs: object
    ) -> None:
        original_replace(source, target, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(module.os, "replace", interrupt_after_replace)

    try:
        with pytest.raises(KeyboardInterrupt):
            module._rollback_matching_link(
                parent_descriptor, output.name, temporary_descriptor
            )
    finally:
        os.close(temporary_descriptor)
        os.close(parent_descriptor)

    assert output.read_bytes() == b"foreign"
    assert _recovery_capture(tmp_path).read_bytes() == b"foreign"


def test_report_cleanup_close_error_does_not_mask_write_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    output = tmp_path / "report.json"
    original_close = module.os.close

    def interrupt_write(descriptor: int, raw: memoryview) -> int:
        del descriptor, raw
        raise KeyboardInterrupt

    def fail_after_close(descriptor: int) -> None:
        original_close(descriptor)
        raise OSError("simulated cleanup close failure")

    monkeypatch.setattr(module.os, "write", interrupt_write)
    monkeypatch.setattr(module.os, "close", fail_after_close)

    with pytest.raises(KeyboardInterrupt):
        module._exclusive_write(output, b"complete report\n")

    assert not output.exists()
    assert list(tmp_path.iterdir()) == []


def test_existing_report_refusal_does_not_invoke_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    output = tmp_path / "report.json"
    output.write_bytes(b"existing")

    def unexpected_rollback(
        parent_descriptor: int,
        output_name: str,
        temporary_descriptor: int,
    ) -> None:
        del parent_descriptor, output_name, temporary_descriptor
        raise AssertionError("rollback must not inspect a pre-existing target")

    monkeypatch.setattr(module, "_rollback_matching_link", unexpected_rollback)

    with pytest.raises(module.ParityCliError, match="output already exists"):
        module._exclusive_write(output, b"complete report\n")

    assert output.read_bytes() == b"existing"


def test_report_sync_interrupt_retains_private_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    output = tmp_path / "report.json"
    original_fsync = module.os.fsync

    def interrupt_directory_sync(descriptor: int) -> None:
        if stat.S_ISDIR(module.os.fstat(descriptor).st_mode):
            raise KeyboardInterrupt
        original_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", interrupt_directory_sync)

    with pytest.raises(KeyboardInterrupt):
        module._exclusive_write(output, b"complete report\n")

    assert not output.exists()
    assert _recovery_capture(tmp_path).read_bytes() == b"complete report\n"
    assert _staging_payload(tmp_path).read_bytes() == b"complete report\n"


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
    assert _staging_payload(tmp_path).is_file()


def test_cli_refuses_network_or_database_arguments_without_echoing_values() -> None:
    for option in ("--dsn", "--url", "--database-url"):
        result = _run(option, "CANARY-CONNECTION-SECRET")
        assert result.returncode != 0
        assert "CANARY-CONNECTION-SECRET" not in result.stdout
        assert "CANARY-CONNECTION-SECRET" not in result.stderr
