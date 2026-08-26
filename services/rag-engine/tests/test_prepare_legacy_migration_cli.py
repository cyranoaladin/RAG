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
SCRIPT_PATH = ENGINE_ROOT / "scripts" / "prepare_legacy_migration.py"
CAPTURE_PATH = ENGINE_ROOT / "tests" / "fixtures" / "legacy_convergence_capture_v1.jsonl"
POLICY_PATH = ENGINE_ROOT / "configs" / "engine_convergence_v1.yml"


def _load_cli_module():
    spec = importlib.util.spec_from_file_location(
        "prepare_legacy_migration_cli", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(ENGINE_ROOT), str(ENGINE_ROOT.parents[1] / "packages" / "contracts" / "src"))
    )
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--capture",
            str(CAPTURE_PATH),
            "--policy",
            str(POLICY_PATH),
            *arguments,
        ],
        cwd=ENGINE_ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )


def _recovery_capture(directory: Path) -> Path:
    recovery_directories = list(directory.glob(".nexus-staging.*"))
    assert len(recovery_directories) == 1
    recovery_directory = recovery_directories[0]
    assert stat.S_IMODE(recovery_directory.stat().st_mode) == 0o700
    capture = recovery_directory / "captured"
    assert capture.is_file()
    return capture


def _open_test_staging(directory: Path) -> int:
    staging_directory = directory / ".nexus-staging.test"
    staging_directory.mkdir(mode=0o700)
    return os.open(staging_directory, os.O_RDONLY | os.O_DIRECTORY)


def _staging_payload(directory: Path) -> Path:
    staging_directories = list(directory.glob(".nexus-staging.*"))
    assert len(staging_directories) == 1
    staging_directory = staging_directories[0]
    assert stat.S_IMODE(staging_directory.stat().st_mode) == 0o700
    payload = staging_directory / "payload"
    assert payload.is_file()
    return payload


def test_cli_defaults_to_summary_only_without_payload() -> None:
    result = _run()

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary == {
        "capture_context": "SYNTHETIC_TEST",
        "disposition_counts": {
            "BLOCKED": 1,
            "IGNORE_EMPTY": 0,
            "QUARANTINE": 1,
            "REINGEST_GOVERNED": 3,
            "REVIEW_REQUIRED": 2,
        },
        "duplicate_count": 1,
        "empty_collection_count": 5,
        "input_digest_sha256": hashlib.sha256(CAPTURE_PATH.read_bytes()).hexdigest(),
        "manifest_sha256": summary["manifest_sha256"],
        "migration_complete": False,
        "mode": "DRY_RUN",
        "prepared_object_count": 7,
        "protocol_version": "NEXUS-LEGACY-MIGRATION-SUMMARY-V1",
        "source_object_count": 7,
    }
    assert len(summary["manifest_sha256"]) == 64
    assert "legacy-" not in result.stdout
    assert "source_id" not in result.stdout
    assert result.stderr == ""


def test_cli_refuses_write_without_exact_input_digest(tmp_path: Path) -> None:
    output = tmp_path / "manifest.json"

    missing = _run("--write-manifest", str(output))
    mismatch = _run(
        "--write-manifest",
        str(output),
        "--expected-input-sha256",
        "0" * 64,
    )

    assert missing.returncode != 0
    assert mismatch.returncode != 0
    assert not output.exists()
    assert "expected-input-sha256" in missing.stderr
    assert "digest mismatch" in mismatch.stderr


def test_cli_publishes_new_manifest_exclusively(tmp_path: Path) -> None:
    output = tmp_path / "manifest.json"
    digest = hashlib.sha256(CAPTURE_PATH.read_bytes()).hexdigest()

    created = _run(
        "--write-manifest",
        str(output),
        "--expected-input-sha256",
        digest,
    )

    assert created.returncode == 0, created.stderr
    summary = json.loads(created.stdout)
    document = json.loads(output.read_text(encoding="utf-8"))
    assert summary["mode"] == "WRITE"
    assert document["input_digest_sha256"] == digest
    assert document["manifest_sha256"] == summary["manifest_sha256"]
    assert document["migration_complete"] is False
    assert output.read_bytes().endswith(b"\n")

    original = output.read_bytes()
    refused = _run(
        "--write-manifest",
        str(output),
        "--expected-input-sha256",
        digest,
    )
    assert refused.returncode != 0
    assert output.read_bytes() == original
    assert "already exists" in refused.stderr


def test_manifest_publication_uses_a_private_staging_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    output = tmp_path / "manifest.json"
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

    module._exclusive_publish(output, b"complete manifest\n")

    assert staging_checked
    assert output.read_bytes() == b"complete manifest\n"
    assert list(tmp_path.iterdir()) == [output]


def test_manifest_publication_removes_link_when_directory_sync_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    output = tmp_path / "manifest.json"
    original_fsync = module.os.fsync

    def fail_directory_sync(descriptor: int) -> None:
        if stat.S_ISDIR(module.os.fstat(descriptor).st_mode):
            raise OSError("simulated directory sync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", fail_directory_sync)

    with pytest.raises(
        module.PreparationCliError, match="output publication failed"
    ):
        module._exclusive_publish(output, b"complete manifest\n")

    assert not output.exists()
    assert _recovery_capture(tmp_path).read_bytes() == b"complete manifest\n"


def test_manifest_publication_removes_link_on_directory_sync_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    output = tmp_path / "manifest.json"
    original_fsync = module.os.fsync

    def interrupt_directory_sync(descriptor: int) -> None:
        if stat.S_ISDIR(module.os.fstat(descriptor).st_mode):
            raise KeyboardInterrupt
        original_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", interrupt_directory_sync)

    with pytest.raises(KeyboardInterrupt):
        module._exclusive_publish(output, b"complete manifest\n")

    assert not output.exists()
    assert _recovery_capture(tmp_path).read_bytes() == b"complete manifest\n"


def test_manifest_rollback_remains_bound_to_the_open_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    live_parent = tmp_path / "live"
    redirected_parent = tmp_path / "redirected"
    original_parent = tmp_path / "original"
    live_parent.mkdir()
    redirected_parent.mkdir()
    output = live_parent / "manifest.json"
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
        module._exclusive_publish(output, b"complete manifest\n")

    assert not (original_parent / output.name).exists()
    assert not output.exists()
    assert _recovery_capture(original_parent).read_bytes() == b"complete manifest\n"


def test_manifest_rollback_does_not_allocate_after_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    output = tmp_path / "manifest.json"
    original_fsync = module.os.fsync
    original_mkdir = module.os.mkdir
    rollback_mkdir_calls = 0

    def fail_parent_sync(descriptor: int) -> None:
        if stat.S_ISDIR(module.os.fstat(descriptor).st_mode):
            raise OSError("simulated directory sync failure")
        original_fsync(descriptor)

    def interrupt_rollback_mkdir(
        candidate: object,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> None:
        nonlocal rollback_mkdir_calls
        original_mkdir(candidate, mode, dir_fd=dir_fd)
        if str(candidate).startswith(".nexus-rollback."):
            rollback_mkdir_calls += 1
            raise KeyboardInterrupt

    monkeypatch.setattr(module.os, "fsync", fail_parent_sync)
    monkeypatch.setattr(module.os, "mkdir", interrupt_rollback_mkdir)

    with pytest.raises((KeyboardInterrupt, module.PreparationCliError)):
        module._exclusive_publish(output, b"complete manifest\n")

    assert rollback_mkdir_calls == 0
    assert not output.exists()


def test_manifest_publication_removes_link_when_link_is_interrupted_after_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    output = tmp_path / "manifest.json"
    original_link = module.os.link

    def interrupt_after_link(source: Path, target: Path, **kwargs: object) -> None:
        original_link(source, target, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(module.os, "link", interrupt_after_link)

    with pytest.raises(KeyboardInterrupt):
        module._exclusive_publish(output, b"complete manifest\n")

    assert not output.exists()
    assert _recovery_capture(tmp_path).read_bytes() == b"complete manifest\n"


def test_manifest_rollback_preserves_target_replaced_during_identity_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    temporary = tmp_path / ".manifest.json.owned"
    output = tmp_path / "manifest.json"
    foreign = tmp_path / "foreign.json"
    temporary.write_bytes(b"owned")
    foreign.write_bytes(b"foreign")
    os.link(temporary, output)
    parent_descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    staging_descriptor = _open_test_staging(tmp_path)
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
            parent_descriptor,
            staging_descriptor,
            output.name,
            temporary_descriptor,
        )
    finally:
        os.close(temporary_descriptor)
        os.close(staging_descriptor)
        os.close(parent_descriptor)

    assert output.read_bytes() == b"foreign"


def test_manifest_rollback_never_unlinks_a_substituted_recovery_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    temporary = tmp_path / ".manifest.json.owned"
    output = tmp_path / "manifest.json"
    foreign = tmp_path / "foreign.json"
    temporary.write_bytes(b"owned")
    foreign.write_bytes(b"foreign")
    os.link(temporary, output)
    parent_descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    staging_descriptor = _open_test_staging(tmp_path)
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
            rescue_path = next(tmp_path.glob(".nexus-staging.*")) / "captured"
            rescue_path.unlink()
            original_replace(foreign, rescue_path)
        return status

    monkeypatch.setattr(module.os, "fstat", fstat_then_substitute)

    try:
        module._rollback_matching_link(
            parent_descriptor,
            staging_descriptor,
            output.name,
            temporary_descriptor,
        )
        assert os.fstat(foreign_descriptor).st_nlink >= 1
    finally:
        os.close(temporary_descriptor)
        os.close(staging_descriptor)
        os.close(parent_descriptor)
        os.close(foreign_descriptor)


def test_manifest_rollback_preserves_captured_target_when_replace_is_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    temporary = tmp_path / ".manifest.json.owned"
    output = tmp_path / "manifest.json"
    temporary.write_bytes(b"owned")
    output.write_bytes(b"foreign")
    parent_descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    staging_descriptor = _open_test_staging(tmp_path)
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
                parent_descriptor,
                staging_descriptor,
                output.name,
                temporary_descriptor,
            )
    finally:
        os.close(temporary_descriptor)
        os.close(staging_descriptor)
        os.close(parent_descriptor)

    assert output.read_bytes() == b"foreign"
    assert _recovery_capture(tmp_path).read_bytes() == b"foreign"


def test_manifest_cleanup_close_error_does_not_mask_write_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    output = tmp_path / "manifest.json"
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
        module._exclusive_publish(output, b"complete manifest\n")

    assert not output.exists()
    assert list(tmp_path.iterdir()) == []


def test_existing_manifest_refusal_does_not_invoke_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    output = tmp_path / "manifest.json"
    output.write_bytes(b"existing")

    def unexpected_rollback(
        parent_descriptor: int,
        staging_descriptor: int,
        output_name: str,
        temporary_descriptor: int,
    ) -> None:
        del parent_descriptor, staging_descriptor, output_name, temporary_descriptor
        raise AssertionError("rollback must not inspect a pre-existing target")

    monkeypatch.setattr(module, "_rollback_matching_link", unexpected_rollback)

    with pytest.raises(module.PreparationCliError, match="output already exists"):
        module._exclusive_publish(output, b"complete manifest\n")

    assert output.read_bytes() == b"existing"


def test_manifest_sync_interrupt_retains_private_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    output = tmp_path / "manifest.json"
    original_fsync = module.os.fsync

    def interrupt_directory_sync(descriptor: int) -> None:
        if stat.S_ISDIR(module.os.fstat(descriptor).st_mode):
            raise KeyboardInterrupt
        original_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", interrupt_directory_sync)

    with pytest.raises(KeyboardInterrupt):
        module._exclusive_publish(output, b"complete manifest\n")

    assert not output.exists()
    assert _recovery_capture(tmp_path).read_bytes() == b"complete manifest\n"
    assert _staging_payload(tmp_path).read_bytes() == b"complete manifest\n"


def test_cli_sanitizes_invalid_capture_errors(tmp_path: Path) -> None:
    canary = "CANARY-DOCUMENT-CONTENT-MUST-NOT-LEAK"
    capture = tmp_path / "invalid.jsonl"
    capture.write_text(json.dumps({"record_type": "capture_header", "text": canary}) + "\n")

    result = _run("--capture", str(capture))

    assert result.returncode != 0
    assert canary not in result.stdout
    assert canary not in result.stderr
    assert result.stdout == ""


def test_cli_accepts_no_database_or_network_destination(tmp_path: Path) -> None:
    output = tmp_path / "manifest.json"

    for forbidden_option in ("--dsn", "--database-url", "--chroma-url"):
        result = _run(forbidden_option, "CANARY-CONNECTION", "--write-manifest", str(output))
        assert result.returncode != 0
        assert not output.exists()
        assert "CANARY-CONNECTION" not in result.stdout
        assert "CANARY-CONNECTION" not in result.stderr
