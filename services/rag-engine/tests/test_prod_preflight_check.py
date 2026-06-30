from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ENGINE_ROOT / "scripts" / "prod_preflight_check.py"
ADMIN_TOKEN_KEY = "INGESTOR_API_TOKEN"
ADMIN_TOKEN_VALUE = "a" * 64


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("prod_preflight_check", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_valid_tree(compose_dir: Path) -> None:
    (compose_dir / "configs").mkdir(parents=True)
    (compose_dir / "creds").mkdir()
    (compose_dir / "configs" / "rag_collections.yml").write_text(
        """
version: 1
physical_backends:
  chroma:
    collections:
      rag_nexus_quarantine:
        allowed_domains: ["quarantine"]
domains:
  quarantine:
    retrievable: false
""".strip(),
        encoding="utf-8",
    )
    (compose_dir / "configs" / "legacy_collection_mapping.yml").write_text(
        "rag_divers: rag_nexus_quarantine\n",
        encoding="utf-8",
    )
    (compose_dir / "creds" / "gdrive-sa.json").write_text(
        "placeholder-gdrive-json",
        encoding="utf-8",
    )
    (compose_dir / "docker-compose.yml").write_text(
        """
services:
  ingestor:
    image: example/ingestor
""".strip(),
        encoding="utf-8",
    )
    (compose_dir / ".env").write_text(
        "\n".join(
            [
                "RAG_ENV=production",
                "RAG_ENGINE_CONFIG_DIR=/app/configs",
                "RAG_CONFIGS_HOST_DIR=./configs",
                "ALLOW_UNAUTHENTICATED_ADMIN_DEV=false",
                f"{ADMIN_TOKEN_KEY}={ADMIN_TOKEN_VALUE}",
            ]
        ),
        encoding="utf-8",
    )


def _compose_result(
    compose_dir: Path,
    *,
    source: str | None = None,
    target: str = "/app/configs",
    read_only: bool = True,
    ingestor_host_ip: str | None = "127.0.0.1",
    ui_host_ip: str | None = "127.0.0.1",
) -> subprocess.CompletedProcess[str]:
    def port(host_ip: str | None, published: str, target_port: int) -> dict[str, object]:
        payload: dict[str, object] = {
            "mode": "ingress",
            "target": target_port,
            "published": published,
            "protocol": "tcp",
        }
        if host_ip is not None:
            payload["host_ip"] = host_ip
        return payload

    payload = {
        "services": {
            "ingestor": {
                "volumes": [
                    {
                        "type": "bind",
                        "source": source or str((compose_dir / "configs").resolve()),
                        "target": target,
                        "read_only": read_only,
                    }
                ],
                "ports": [port(ingestor_host_ip, "8001", 8001)],
                "environment": {"INGESTOR_API_TOKEN": ADMIN_TOKEN_VALUE},
            },
            "ui": {
                "ports": [port(ui_host_ip, "8501", 8501)],
            },
        }
    }
    return subprocess.CompletedProcess(
        args=["docker", "compose", "config", "--format", "json"],
        returncode=0,
        stdout=json.dumps(payload),
        stderr="",
    )


def _run_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    compose_result: subprocess.CompletedProcess[str] | None = None,
) -> tuple[int, str]:
    module = _load_module()
    compose_dir = tmp_path / "compose"
    expected_source = str((compose_dir / "configs").resolve())

    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return compose_result or _compose_result(compose_dir)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    code = module.main(
        [
            "--compose-dir",
            str(compose_dir),
            "--expected-config-source",
            expected_source,
            "--expected-config-target",
            "/app/configs",
        ]
    )
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_env_absent_fails_without_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)
    (compose_dir / ".env").unlink()

    code, output = _run_preflight(tmp_path, monkeypatch, capsys)

    assert code != 0
    assert ".env" in output
    assert ADMIN_TOKEN_VALUE not in output


def test_token_absent_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)
    env_text = (compose_dir / ".env").read_text(encoding="utf-8")
    (compose_dir / ".env").write_text(
        "\n".join(
            line for line in env_text.splitlines() if not line.startswith(f"{ADMIN_TOKEN_KEY}=")
        ),
        encoding="utf-8",
    )

    code, output = _run_preflight(tmp_path, monkeypatch, capsys)

    assert code != 0
    assert ADMIN_TOKEN_KEY in output


def test_ingest_auth_token_alias_is_not_enough(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)
    env_text = (compose_dir / ".env").read_text(encoding="utf-8")
    without_ingestor_token = "\n".join(
        line for line in env_text.splitlines() if not line.startswith(f"{ADMIN_TOKEN_KEY}=")
    )
    (compose_dir / ".env").write_text(
        f"{without_ingestor_token}\nINGEST_AUTH_TOKEN={ADMIN_TOKEN_VALUE}\n",
        encoding="utf-8",
    )

    code, output = _run_preflight(tmp_path, monkeypatch, capsys)

    assert code != 0
    assert ADMIN_TOKEN_KEY in output
    assert ADMIN_TOKEN_VALUE not in output


def test_admin_token_must_be_64_hex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)
    env_text = (compose_dir / ".env").read_text(encoding="utf-8")
    (compose_dir / ".env").write_text(
        env_text.replace(f"{ADMIN_TOKEN_KEY}={ADMIN_TOKEN_VALUE}", f"{ADMIN_TOKEN_KEY}=not-a-token"),
        encoding="utf-8",
    )

    code, output = _run_preflight(tmp_path, monkeypatch, capsys)

    assert code != 0
    assert "64" in output
    assert "hex" in output.lower()
    assert "not-a-token" not in output


def test_token_present_succeeds_without_printing_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_valid_tree(tmp_path / "compose")

    code, output = _run_preflight(tmp_path, monkeypatch, capsys)

    assert code == 0
    assert ADMIN_TOKEN_VALUE not in output


def test_wrong_rag_env_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)
    env_text = (compose_dir / ".env").read_text(encoding="utf-8")
    (compose_dir / ".env").write_text(env_text.replace("RAG_ENV=production", "RAG_ENV=dev"), encoding="utf-8")

    code, output = _run_preflight(tmp_path, monkeypatch, capsys)

    assert code != 0
    assert "RAG_ENV" in output


def test_dev_admin_override_fails_in_prod(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)
    env_text = (compose_dir / ".env").read_text(encoding="utf-8")
    (compose_dir / ".env").write_text(
        env_text.replace(
            "ALLOW_UNAUTHENTICATED_ADMIN_DEV=false",
            "ALLOW_UNAUTHENTICATED_ADMIN_DEV=true",
        ),
        encoding="utf-8",
    )

    code, output = _run_preflight(tmp_path, monkeypatch, capsys)

    assert code != 0
    assert "ALLOW_UNAUTHENTICATED_ADMIN_DEV" in output


def test_missing_configs_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)
    (compose_dir / "configs" / "rag_collections.yml").unlink()

    code, output = _run_preflight(tmp_path, monkeypatch, capsys)

    assert code != 0
    assert "rag_collections.yml" in output


def test_mount_must_be_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)

    code, output = _run_preflight(
        tmp_path,
        monkeypatch,
        capsys,
        compose_result=_compose_result(compose_dir, read_only=False),
    )

    assert code != 0
    assert "read-only" in output


def test_mount_target_must_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)

    code, output = _run_preflight(
        tmp_path,
        monkeypatch,
        capsys,
        compose_result=_compose_result(compose_dir, target="/wrong"),
    )

    assert code != 0
    assert "/app/configs" in output


def test_mount_source_must_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)

    code, output = _run_preflight(
        tmp_path,
        monkeypatch,
        capsys,
        compose_result=_compose_result(compose_dir, source=str(tmp_path / "wrong-configs")),
    )

    assert code != 0
    assert "source" in output.lower()


def test_public_host_port_binding_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)

    code, output = _run_preflight(
        tmp_path,
        monkeypatch,
        capsys,
        compose_result=_compose_result(compose_dir, ingestor_host_ip="0.0.0.0"),
    )

    assert code != 0
    assert "loopback" in output.lower()


def test_missing_host_port_binding_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)

    code, output = _run_preflight(
        tmp_path,
        monkeypatch,
        capsys,
        compose_result=_compose_result(compose_dir, ui_host_ip=None),
    )

    assert code != 0
    assert "loopback" in output.lower()


def test_public_host_port_binding_on_any_service_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)
    result = _compose_result(compose_dir)
    payload = json.loads(result.stdout)
    payload["services"]["metrics"] = {
        "ports": [
            {
                "mode": "ingress",
                "target": 9090,
                "published": "9090",
                "protocol": "tcp",
                "host_ip": "0.0.0.0",
            }
        ]
    }
    result = subprocess.CompletedProcess(
        args=result.args,
        returncode=0,
        stdout=json.dumps(payload),
        stderr="",
    )

    code, output = _run_preflight(tmp_path, monkeypatch, capsys, compose_result=result)

    assert code != 0
    assert "metrics" in output
    assert "loopback" in output.lower()


def test_rendered_compose_with_token_is_not_written_or_printed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)

    code, output = _run_preflight(tmp_path, monkeypatch, capsys)

    assert code == 0
    assert ADMIN_TOKEN_VALUE not in output
    assert not list(tmp_path.rglob("*compose.rendered*"))
