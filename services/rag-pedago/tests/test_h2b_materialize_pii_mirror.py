"""Le transport Drive PII reste une orchestration hors du plan de contrôle."""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
from typing import Any, Protocol, cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/h2b_materialize_pii_mirror.py"
REMOTE_ROOT = "gdrive_ert:NEXUS_RAG/NEXUS_RAG_GDRIVE_READY"


class MaterializerModule(Protocol):
    subprocess: Any

    def materialize_pii_mirror(
        self,
        *,
        manifest_path: Path,
        expected_manifest_sha256: str,
        remote_root: str,
        local_mirror: Path,
        required_pdf_paths: set[str] | None = None,
    ) -> dict[str, object]: ...


def _module() -> MaterializerModule:
    spec = importlib.util.spec_from_file_location("h2b_materialize_pii_mirror", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(MaterializerModule, module)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _mirror(tmp_path: Path) -> Path:
    path = Path("/tmp") / f"nexus-h2b-pii.pytest-{os.getpid()}-{tmp_path.name}"
    path.mkdir(mode=0o700)
    return path


def test_materializer_uses_one_bounded_read_only_bulk_transport(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    first = "a" * 64
    second = "b" * 64
    manifest_bytes = (
        f"{first}  01_EDUSCOL_OFFICIEL/a.pdf\n"
        f"{second}  02_NEXUS_DIAGNOSTICS/b.pdf\n"
        f"{'c' * 64}  00_ADMIN/info.json\n"
    ).encode()
    manifest = tmp_path / "SHA256SUMS.txt"
    manifest.write_bytes(manifest_bytes)
    mirror = _mirror(tmp_path)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(command: list[str], **kwargs: Any) -> object:
        calls.append((command, kwargs))
        return object()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    try:
        receipt = module.materialize_pii_mirror(
            manifest_path=manifest,
            expected_manifest_sha256=_sha256(manifest_bytes),
            remote_root=REMOTE_ROOT,
            local_mirror=mirror,
        )
    finally:
        mirror.rmdir()

    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:4] == ["rclone", "copy", "--immutable", "--files-from-raw"]
    assert command[-2:] == [REMOTE_ROOT, str(mirror)]
    assert kwargs["input"] == (
        b"01_EDUSCOL_OFFICIEL/a.pdf\n02_NEXUS_DIAGNOSTICS/b.pdf\n"
    )
    assert receipt["corpus_manifest_sha256"] == _sha256(manifest_bytes)
    assert receipt["pdf_path_count"] == 2
    assert receipt["remote_access_mode"] == "READ_ONLY"
    assert receipt["remote_write_operations"] == 0


def test_materializer_rejects_noncanonical_remote_before_transport(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    manifest = tmp_path / "SHA256SUMS.txt"
    manifest.write_text(f"{'a' * 64}  a.pdf\n", encoding="utf-8")
    mirror = _mirror(tmp_path)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("transport must not run"),
    )
    try:
        with pytest.raises(ValueError, match="canonical read-only"):
            module.materialize_pii_mirror(
                manifest_path=manifest,
                expected_manifest_sha256=_sha256(manifest.read_bytes()),
                remote_root="gdrive_ert:wrong",
                local_mirror=mirror,
            )
    finally:
        mirror.rmdir()
