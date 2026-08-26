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
    assert list(tmp_path.iterdir()) == []


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
    assert list(tmp_path.iterdir()) == []


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
    assert list(tmp_path.iterdir()) == []


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
    original_stat = module.os.stat
    replaced = False

    def stat_then_replace(candidate: Path, **kwargs: object):
        nonlocal replaced
        status = original_stat(candidate, **kwargs)
        if Path(candidate) == temporary and not replaced:
            replaced = True
            if output.exists():
                output.unlink()
            os.link(foreign, output)
        return status

    monkeypatch.setattr(module.os, "stat", stat_then_replace)

    module._rollback_matching_link(output, temporary)

    assert output.read_bytes() == b"foreign"


def test_existing_manifest_refusal_does_not_invoke_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    output = tmp_path / "manifest.json"
    output.write_bytes(b"existing")

    def unexpected_rollback(path: Path, temporary_path: Path) -> None:
        del path, temporary_path
        raise AssertionError("rollback must not inspect a pre-existing target")

    monkeypatch.setattr(module, "_rollback_matching_link", unexpected_rollback)

    with pytest.raises(module.PreparationCliError, match="output already exists"):
        module._exclusive_publish(output, b"complete manifest\n")

    assert output.read_bytes() == b"existing"


def test_manifest_cleanup_error_does_not_mask_directory_sync_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_cli_module()
    output = tmp_path / "manifest.json"
    original_fsync = module.os.fsync
    original_unlink = module.Path.unlink

    def interrupt_directory_sync(descriptor: int) -> None:
        if stat.S_ISDIR(module.os.fstat(descriptor).st_mode):
            raise KeyboardInterrupt
        original_fsync(descriptor)

    def fail_temporary_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path.name.startswith(".manifest.json."):
            raise OSError("simulated temporary cleanup failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(module.os, "fsync", interrupt_directory_sync)
    monkeypatch.setattr(module.Path, "unlink", fail_temporary_unlink)

    with pytest.raises(KeyboardInterrupt):
        module._exclusive_publish(output, b"complete manifest\n")

    assert not output.exists()
    for leftover in tmp_path.iterdir():
        original_unlink(leftover)


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
