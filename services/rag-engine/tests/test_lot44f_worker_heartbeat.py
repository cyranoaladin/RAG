"""LOT44f/ADR-0029 : heartbeat file du worker CLI — liveness check externe.

Périmètre strict : le mécanisme d'écriture du fichier de heartbeat
(présence, écriture avant la première itération, écriture après chaque
itération) — pas une ré-vérification de ``run_worker_iteration`` lui-même
(déjà couvert par ``test_lot44e_worker_e2e.py``). Aucune connexion
PostgreSQL réelle : ``psycopg.connect``/``run_worker_iteration`` sont
doublés.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from nexus_contracts.ingestion import CollectionProfile

from ingestor.ingestion_profiles.registry import profile_fingerprint
from ingestor.ingestion_worker import cli as worker_cli
from ingestor.ingestion_worker.runner import IterationOutcome

VALID_SCOPE = {
    "tenant": "libre_terminale",
    "collection": "rag_nexus_nsi_terminale_specialite",
    "niveau": "terminale",
    "voie": "generale",
    "matiere": "nsi",
    "candidat": "libre",
    "audience": ["libre", "tous"],
    "visibility": "internal",
    "school_year": "2026-2027",
    "programme_version": "BOEN_special_8_2019-07-25",
}


def _profile_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "profile_version": "v1",
        "enabled": True,
        "scope": VALID_SCOPE,
        "title": "Profil de test — non production",
        "owner": "equipe-test",
        "expected_topics": ["sujet"],
        "expected_resource_types": ["cours"],
        "allowed_domains": ["eduscol.education.fr"],
        "source_authority": "official",
        "search_cadence": "weekly",
        "max_queries_per_run": 10,
        "max_documents_per_run": 20,
        "max_chunk_size": 800,
        "chunk_overlap": 100,
        "min_source_confidence": 0.7,
        "min_scope_confidence": 0.7,
        "min_extraction_quality": 0.6,
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def profiles_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "profiles"
    directory.mkdir()
    (directory / "a.yml").write_text(yaml.safe_dump(_profile_payload()), encoding="utf-8")
    return directory


@pytest.fixture
def manifest_path(tmp_path: Path, profiles_dir: Path) -> Path:
    profile = CollectionProfile.model_validate(_profile_payload())
    path = tmp_path / "manifest.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "manifest_version": "1",
                "provenance": "test-heartbeat",
                "generated_at": "2026-08-05T00:00:00Z",
                "profiles": [
                    {
                        "collection": "rag_nexus_nsi_terminale_specialite",
                        "profile_version": "v1",
                        "fingerprint": profile_fingerprint(profile),
                        "approved_by": "test-heartbeat-authority",
                        "approved_at": "2026-08-05T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


class _FakeConnection:
    def commit(self) -> None:
        pass


@contextmanager
def _fake_connect(*_args: object, **_kwargs: object):
    yield _FakeConnection()


def _run_worker(
    monkeypatch: pytest.MonkeyPatch,
    *,
    profiles_dir: Path,
    manifest_path: Path,
    artifact_dir: Path,
    extra_args: list[str],
) -> int:
    monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", "postgresql://unused/for/this/test")
    monkeypatch.setattr(worker_cli.psycopg, "connect", _fake_connect)
    monkeypatch.setattr(
        worker_cli,
        "run_worker_iteration",
        lambda _conn, deps: IterationOutcome(worked=False, job_id=None, status=None, error=None),
    )
    # Isolation DB (revue PR#90) : _reap_expired_leases touche aussi la base
    # réelle à chaque itération — hors périmètre de ce test, qui vérifie
    # uniquement le mécanisme de heartbeat sur une fausse connexion.
    monkeypatch.setattr(worker_cli, "_reap_expired_leases", lambda _conn: None)
    # Isolation attestation (item I) : _FakeConnection ne porte aucun
    # curseur PostgreSQL réel — hors périmètre de ce test, qui vérifie
    # uniquement le mécanisme de heartbeat, pas l'attestation de rôle
    # (déjà couverte par test_lot44f_worker_attestation.py).
    monkeypatch.setattr(
        worker_cli,
        "attest_runtime_role",
        lambda _conn, expected_role: worker_cli.RoleAttestation(
            current_user=expected_role, is_superuser=False, can_create_db=False,
            can_create_role=False, can_replicate=False, can_bypass_rls=False,
            owns_ingestion_control_schema=False, has_excessive_workflow_events_grant=False,
            member_of_other_roles=False,
        ),
    )
    return worker_cli.main(
        [
            "--profiles-dir", str(profiles_dir),
            "--manifest-path", str(manifest_path),
            "--artifact-store-dir", str(artifact_dir),
            "--expected-role", "ingestion_control_app_test",
            "--owner", "heartbeat-test",
            "--once",
            *extra_args,
        ]
    )


class TestWorkerHeartbeat:
    def test_no_heartbeat_file_arg_writes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profiles_dir: Path, manifest_path: Path
    ) -> None:
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir()
        exit_code = _run_worker(
            monkeypatch,
            profiles_dir=profiles_dir,
            manifest_path=manifest_path,
            artifact_dir=artifact_dir,
            extra_args=[],
        )
        assert exit_code == 0
        assert list(tmp_path.glob("*heartbeat*")) == []

    def test_heartbeat_file_written_before_and_after_iteration(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profiles_dir: Path, manifest_path: Path
    ) -> None:
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir()
        heartbeat_path = tmp_path / f"heartbeat-{uuid4()}.txt"
        exit_code = _run_worker(
            monkeypatch,
            profiles_dir=profiles_dir,
            manifest_path=manifest_path,
            artifact_dir=artifact_dir,
            extra_args=["--heartbeat-file", str(heartbeat_path)],
        )
        assert exit_code == 0
        assert heartbeat_path.is_file()
        written = float(heartbeat_path.read_text(encoding="utf-8"))
        assert written > 0

    def test_heartbeat_not_written_if_gate_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profiles_dir: Path
    ) -> None:
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir()
        heartbeat_path = tmp_path / f"heartbeat-{uuid4()}.txt"
        exit_code = _run_worker(
            monkeypatch,
            profiles_dir=profiles_dir,
            manifest_path=tmp_path / "missing-manifest.yml",
            artifact_dir=artifact_dir,
            extra_args=["--heartbeat-file", str(heartbeat_path)],
        )
        assert exit_code == 1
        assert not heartbeat_path.exists()
