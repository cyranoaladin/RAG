from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from nexus_contracts import (
    BootstrapChunk,
    BootstrapResourceVersion,
    ResourceRegistryBootstrapPayload,
    seal_resource_registry_bootstrap,
)

from ingestor import r1_attempt_preflight_cli, r1_export_and_verify_cli
from ingestor.r1_evidence_verifier import R1EvidenceReport
from ingestor.r1_operator_flow import EXPECTED_SEALED_RELEASE_REGISTRY_SHA256

SHA_A = "a" * 64
SHA_B = "b" * 64


def _inventory():
    return seal_resource_registry_bootstrap(
        ResourceRegistryBootstrapPayload.model_validate(
            {
                "protocol_version": "1",
                "producer_repository": "cyranoaladin/RAG",
                "producer_commit": SHA_A[:40],
                "package_version": "0.15.0",
                "source_snapshot_sha256": SHA_B,
                "generated_at": datetime(2026, 8, 30, 12, tzinfo=UTC),
                "resources": [
                    BootstrapResourceVersion(
                        resource_id="11111111-1111-4111-8111-111111111111",
                        resource_version_id="22222222-2222-4222-8222-222222222222",
                        content_sha256=SHA_A,
                        rag_artifact_id=SHA_A,
                        size_bytes=42,
                        mime_type="application/pdf",
                        source_label="Programme officiel",
                        source_uri="https://eduscol.education.fr/programme.pdf",
                        rights="officiel_public",
                        official=True,
                        source_kind="eduscol.education.fr",
                        type_doc="programme_officiel",
                        placements=[
                            {
                                "tenant": "nexus",
                                "collection": "terminale_maths",
                                "niveau": "terminale",
                                "voie": "generale",
                                "matiere": "mathematiques",
                                "statut_enseignement": "specialite",
                                "candidat": "scolarise",
                                "audience": ["aefe"],
                                "visibility": "internal",
                                "school_year": "2026-2027",
                                "programme_version": "fr-national-2026",
                            }
                        ],
                        chunks=[
                            BootstrapChunk(
                                chunk_id="chunk-001",
                                locator={"chunk_index": 0, "page": 1},
                            )
                        ],
                    )
                ],
            }
        )
    )


class _ConnectionContext:
    def __enter__(self):
        return object()

    def __exit__(self, *_args: object) -> None:
        return None


class _ReleaseRegistry:
    collections = ("terminale_maths",)
    manifests = (
        type(
            "ManifestBinding",
            (),
            {
                "expectation": type(
                    "ReleaseExpectation",
                    (),
                    {
                        "artifacts": (
                            type(
                                "Artifact",
                                (),
                                {"collection": "terminale_maths", "content_sha256": SHA_A},
                            )(),
                        )
                    },
                )()
            },
        )(),
    )


PASSING_REPORT = R1EvidenceReport(ready=True, gates={"BOOTSTRAP_RESOURCE_ROWS": 1})


def _common_args(tmp_path: Path, *, bootstrap_out: Path, report_out: Path) -> list[str]:
    return [
        "--producer-commit",
        SHA_A[:40],
        "--generated-at",
        "2026-08-30T12:00:00Z",
        "--bootstrap-out",
        str(bootstrap_out),
        "--report-out",
        str(report_out),
        "--release-registry-path",
        str(tmp_path / "release-registry.json"),
        "--profile-root",
        str(tmp_path / "profiles"),
        "--profile-manifest-path",
        str(tmp_path / "manifest.yml"),
    ]


def test_dsn_is_gone_from_environment_before_the_verifier_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    inventory = _inventory()
    secret_dsn = "postgresql://operator:super-secret@example.invalid/rag"
    monkeypatch.setenv("NEXUS_RESOURCE_EXPORT_DSN", secret_dsn)
    monkeypatch.setattr(
        r1_export_and_verify_cli.psycopg,
        "connect",
        lambda dsn: _ConnectionContext() if dsn == secret_dsn else None,
    )
    monkeypatch.setattr(
        r1_export_and_verify_cli,
        "export_resource_registry_bootstrap_inventory",
        lambda *_a, **_kw: inventory,
    )
    monkeypatch.setattr(
        r1_export_and_verify_cli.metadata,
        "version",
        lambda package: "0.15.0" if package == "nexus-contracts" else "",
    )
    monkeypatch.setattr(
        r1_export_and_verify_cli,
        "load_release_registry_file",
        lambda path, digest: _ReleaseRegistry()
        if digest == EXPECTED_SEALED_RELEASE_REGISTRY_SHA256
        else None,
    )

    seen_dsn_during_verify: dict[str, object] = {}

    def _verify_r1_evidence(**kwargs: object) -> R1EvidenceReport:
        seen_dsn_during_verify["present"] = "NEXUS_RESOURCE_EXPORT_DSN" in os.environ
        seen_dsn_during_verify["bootstrap_path"] = kwargs["bootstrap_path"]
        return PASSING_REPORT

    monkeypatch.setattr(r1_export_and_verify_cli, "verify_r1_evidence", _verify_r1_evidence)

    bootstrap_out = tmp_path / "bootstrap.json"
    report_out = tmp_path / "report.json"
    result = r1_export_and_verify_cli.main(
        _common_args(tmp_path, bootstrap_out=bootstrap_out, report_out=report_out)
    )

    assert result == 0
    assert seen_dsn_during_verify["present"] is False
    assert "NEXUS_RESOURCE_EXPORT_DSN" not in os.environ
    assert seen_dsn_during_verify["bootstrap_path"] == bootstrap_out
    assert bootstrap_out.exists()
    assert report_out.exists()


def test_exporter_failure_means_verifier_is_never_invoked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NEXUS_RESOURCE_EXPORT_DSN", "postgresql://fixture")
    monkeypatch.setattr(
        r1_export_and_verify_cli.psycopg, "connect", lambda dsn: _ConnectionContext()
    )

    def _export_fails(*_a: object, **_kw: object):
        raise RuntimeError("simulated BootstrapInventoryError")

    monkeypatch.setattr(
        r1_export_and_verify_cli, "export_resource_registry_bootstrap_inventory", _export_fails
    )
    monkeypatch.setattr(
        r1_export_and_verify_cli,
        "load_release_registry_file",
        lambda path, digest: _ReleaseRegistry(),
    )

    def _verify_must_never_be_called(**_kwargs: object) -> R1EvidenceReport:
        raise AssertionError("verify_r1_evidence must never run when the exporter failed")

    monkeypatch.setattr(
        r1_export_and_verify_cli, "verify_r1_evidence", _verify_must_never_be_called
    )

    bootstrap_out = tmp_path / "bootstrap.json"
    report_out = tmp_path / "report.json"
    with pytest.raises(RuntimeError, match="simulated BootstrapInventoryError"):
        r1_export_and_verify_cli.main(
            _common_args(tmp_path, bootstrap_out=bootstrap_out, report_out=report_out)
        )

    assert not bootstrap_out.exists()
    assert not report_out.exists()


def test_existing_bootstrap_output_refused_before_touching_the_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bootstrap_out = tmp_path / "bootstrap.json"
    bootstrap_out.write_bytes(b"already published")
    report_out = tmp_path / "report.json"
    monkeypatch.setenv("NEXUS_RESOURCE_EXPORT_DSN", "postgresql://fixture")

    def _connect_must_never_be_called(dsn: str) -> None:
        raise AssertionError("psycopg.connect must never be called when --bootstrap-out already exists")

    monkeypatch.setattr(
        r1_export_and_verify_cli.psycopg, "connect", _connect_must_never_be_called
    )

    with pytest.raises(SystemExit, match="already exists"):
        r1_export_and_verify_cli.main(
            _common_args(tmp_path, bootstrap_out=bootstrap_out, report_out=report_out)
        )

    assert bootstrap_out.read_bytes() == b"already published"


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def test_phase_a_paths_survive_into_phase_b_without_any_shell_subshell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """End-to-end proof of the actual bug class this module exists to
    close: Phase A (non-secret) resolves the attempt's paths in what would
    be the operator's PARENT shell; Phase B (secret-handling) is hen given
    those exact paths as explicit arguments -- never rediscovered, never
    dependent on a shell variable surviving a subshell it was never set
    inside to begin with."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run("git", "init", "-q", cwd=repo)
    _run("git", "config", "user.email", "fixture@example.invalid", cwd=repo)
    _run("git", "config", "user.name", "Fixture", cwd=repo)
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    _run("git", "add", "README.md", cwd=repo)
    _run("git", "commit", "-q", "-m", "initial", cwd=repo)
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()

    real_registry = (
        Path(__file__).resolve().parents[2]
        / "rag-pedago"
        / "data"
        / "releases"
        / "prerentree_2026_2027"
        / "release-registry.json"
    )
    registry = tmp_path / "release-registry.json"
    registry.write_bytes(real_registry.read_bytes())
    evidence_dir = tmp_path / "evidence"

    # -- Phase A: the operator's non-secret parent shell --
    phase_a_result = r1_attempt_preflight_cli.main(
        [
            "--repo-root",
            str(repo),
            "--qualified-exporter-commit",
            head,
            "--release-registry-path",
            str(registry),
            "--release-id",
            "production-profile-gate-2026-2027-v1",
            "--evidence-dir",
            str(evidence_dir),
        ]
    )
    assert phase_a_result == 0
    phase_a_output = capsys.readouterr().out
    resolved = dict(line.split("=", 1) for line in phase_a_output.splitlines() if "=" in line)
    bootstrap_out = Path(resolved["BOOTSTRAP_OUT"])
    report_out = Path(resolved["REPORT_OUT"])

    # -- Phase B: the operator's separate, secret-handling invocation,
    # receiving exactly the paths Phase A printed, nothing recomputed --
    inventory = _inventory()
    monkeypatch.setenv("NEXUS_RESOURCE_EXPORT_DSN", "postgresql://fixture")
    monkeypatch.setattr(
        r1_export_and_verify_cli.psycopg, "connect", lambda dsn: _ConnectionContext()
    )
    monkeypatch.setattr(
        r1_export_and_verify_cli,
        "export_resource_registry_bootstrap_inventory",
        lambda *_a, **_kw: inventory,
    )
    monkeypatch.setattr(
        r1_export_and_verify_cli.metadata,
        "version",
        lambda package: "0.15.0" if package == "nexus-contracts" else "",
    )
    monkeypatch.setattr(
        r1_export_and_verify_cli,
        "load_release_registry_file",
        lambda path, digest: _ReleaseRegistry(),
    )
    monkeypatch.setattr(
        r1_export_and_verify_cli, "verify_r1_evidence", lambda **_kwargs: PASSING_REPORT
    )

    phase_b_result = r1_export_and_verify_cli.main(
        _common_args(tmp_path, bootstrap_out=bootstrap_out, report_out=report_out)
    )

    assert phase_b_result == 0
    assert bootstrap_out.exists()
    assert report_out.exists()
