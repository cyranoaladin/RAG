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
ADMIN_TOKEN_KEY = "LEGACY_ADMIN_API_TOKEN"
ADMIN_TOKEN_VALUE = "a" * 64
INGESTOR_TOKEN_KEY = "INGESTOR_API_TOKEN"
INGESTOR_TOKEN_VALUE = "b" * 64
V2_ADMIN_TOKEN_KEY = "RAG_ADMIN_TOKEN"
V2_ADMIN_TOKEN_VALUE = "c" * 64
REVIEWER_TOKEN_VALUE = "d" * 64
TEACHER_TOKEN_VALUE = "e" * 64
INGEST_AGENT_TOKEN_VALUE = "f" * 64
STUDENT_TOKEN_VALUE = "1" * 64


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
                f"{INGESTOR_TOKEN_KEY}={INGESTOR_TOKEN_VALUE}",
                f"{V2_ADMIN_TOKEN_KEY}={V2_ADMIN_TOKEN_VALUE}",
                f"RAG_REVIEWER_TOKEN={REVIEWER_TOKEN_VALUE}",
                f"RAG_TEACHER_TOKEN={TEACHER_TOKEN_VALUE}",
                f"RAG_INGEST_AGENT_TOKEN={INGEST_AGENT_TOKEN_VALUE}",
                f"RAG_STUDENT_TOKEN={STUDENT_TOKEN_VALUE}",
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
                "environment": {
                    ADMIN_TOKEN_KEY: ADMIN_TOKEN_VALUE,
                    INGESTOR_TOKEN_KEY: INGESTOR_TOKEN_VALUE,
                },
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


def test_ingestion_tokens_do_not_replace_admin_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)
    env_text = (compose_dir / ".env").read_text(encoding="utf-8")
    without_admin_token = "\n".join(
        line for line in env_text.splitlines() if not line.startswith(f"{ADMIN_TOKEN_KEY}=")
    )
    (compose_dir / ".env").write_text(
        f"{without_admin_token}\nINGEST_AUTH_TOKEN={ADMIN_TOKEN_VALUE}\n",
        encoding="utf-8",
    )

    code, output = _run_preflight(tmp_path, monkeypatch, capsys)

    assert code != 0
    assert ADMIN_TOKEN_KEY in output
    assert ADMIN_TOKEN_VALUE not in output


def test_admin_and_ingestion_tokens_must_be_distinct(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)
    env_text = (compose_dir / ".env").read_text(encoding="utf-8")
    (compose_dir / ".env").write_text(
        env_text.replace(
            f"{INGESTOR_TOKEN_KEY}={INGESTOR_TOKEN_VALUE}",
            f"{INGESTOR_TOKEN_KEY}={ADMIN_TOKEN_VALUE}",
        ),
        encoding="utf-8",
    )

    code, output = _run_preflight(tmp_path, monkeypatch, capsys)

    assert code != 0
    assert "distinct" in output.lower()
    assert ADMIN_TOKEN_VALUE not in output


def test_admin_and_ingest_auth_tokens_must_be_distinct(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)
    env_text = (compose_dir / ".env").read_text(encoding="utf-8")
    (compose_dir / ".env").write_text(
        f"{env_text}\nINGEST_AUTH_TOKEN={ADMIN_TOKEN_VALUE}\n",
        encoding="utf-8",
    )

    code, output = _run_preflight(tmp_path, monkeypatch, capsys)

    assert code != 0
    assert "distinct" in output.lower()
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


def test_legacy_admin_and_v2_admin_tokens_must_be_distinct(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)
    env_text = (compose_dir / ".env").read_text(encoding="utf-8")
    (compose_dir / ".env").write_text(
        env_text.replace(
            f"{V2_ADMIN_TOKEN_KEY}={V2_ADMIN_TOKEN_VALUE}",
            f"{V2_ADMIN_TOKEN_KEY}={ADMIN_TOKEN_VALUE}",
        ),
        encoding="utf-8",
    )

    code, output = _run_preflight(tmp_path, monkeypatch, capsys)

    assert code != 0
    assert "distinct" in output.lower()
    assert ADMIN_TOKEN_VALUE not in output


def test_v2_admin_token_must_be_64_hex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)
    env_text = (compose_dir / ".env").read_text(encoding="utf-8")
    (compose_dir / ".env").write_text(
        env_text.replace(
            f"{V2_ADMIN_TOKEN_KEY}={V2_ADMIN_TOKEN_VALUE}",
            f"{V2_ADMIN_TOKEN_KEY}=not-a-valid-hex-token",
        ),
        encoding="utf-8",
    )

    code, output = _run_preflight(tmp_path, monkeypatch, capsys)

    assert code != 0
    assert "RAG_ADMIN_TOKEN" in output
    assert "64" in output
    assert "not-a-valid-hex-token" not in output


# ── v2 role collision tests ──────────────────────────────────────────


def _set_env_token(compose_dir: Path, key: str, value: str) -> None:
    env_path = compose_dir / ".env"
    env_text = env_path.read_text(encoding="utf-8")
    lines = env_text.splitlines()
    replaced = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines), encoding="utf-8")


@pytest.mark.parametrize(
    ("colliding_key", "colliding_with"),
    [
        ("RAG_STUDENT_TOKEN", V2_ADMIN_TOKEN_VALUE),
        ("RAG_INGEST_AGENT_TOKEN", V2_ADMIN_TOKEN_VALUE),
        ("RAG_REVIEWER_TOKEN", TEACHER_TOKEN_VALUE),
        ("INGESTOR_API_TOKEN", TEACHER_TOKEN_VALUE),
    ],
    ids=[
        "admin-student",
        "admin-ingest_agent",
        "reviewer-teacher",
        "ingest_agent-teacher",
    ],
)
def test_v2_cross_role_collision_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    colliding_key: str,
    colliding_with: str,
) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)
    _set_env_token(compose_dir, colliding_key, colliding_with)

    code, output = _run_preflight(tmp_path, monkeypatch, capsys)

    assert code != 0
    assert "distinct across roles" in output.lower()


@pytest.mark.parametrize(
    ("alias_key", "alias_value_source"),
    [
        ("REVIEWER_API_TOKEN", REVIEWER_TOKEN_VALUE),
        ("INGESTOR_API_TOKEN", INGEST_AGENT_TOKEN_VALUE),
        ("INGEST_AUTH_TOKEN", INGEST_AGENT_TOKEN_VALUE),
    ],
    ids=[
        "reviewer-alias",
        "ingest_agent-ingestor-alias",
        "ingest_agent-ingest_auth-alias",
    ],
)
def test_v2_intra_role_alias_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    alias_key: str,
    alias_value_source: str,
) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)
    _set_env_token(compose_dir, alias_key, alias_value_source)

    code, output = _run_preflight(tmp_path, monkeypatch, capsys)

    assert code == 0


# ── v2 role token format tests ───────────────────────────────────────


@pytest.mark.parametrize(
    "bad_key",
    [
        "RAG_REVIEWER_TOKEN",
        "RAG_INGEST_AGENT_TOKEN",
        "REVIEWER_API_TOKEN",
        "INGEST_AUTH_TOKEN",
        "RAG_STUDENT_TOKEN",
    ],
)
def test_v2_role_token_must_be_64_hex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bad_key: str,
) -> None:
    compose_dir = tmp_path / "compose"
    _write_valid_tree(compose_dir)
    _set_env_token(compose_dir, bad_key, "not-a-valid-token")

    code, output = _run_preflight(tmp_path, monkeypatch, capsys)

    assert code != 0
    assert bad_key in output
    assert "64" in output
    assert "not-a-valid-token" not in output
