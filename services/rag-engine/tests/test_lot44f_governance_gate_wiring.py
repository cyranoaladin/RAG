"""LOT44f/ADR-0029 : câblage réel du gate LOT44c dans api.py et le worker.

Périmètre strict : le câblage lui-même (quand le gate est appelé, avec
quels paramètres, quel effet sur le démarrage) — pas une ré-vérification du
moteur LOT44c déjà couvert par ``test_lot44c_*.py``. Aucun profil
pédagogique/métier n'est fabriqué ici : fixtures de test génériques
uniquement, jamais présentées comme des profils de production réels.

Convention reprise de ``test_lot44c_profile_manifest.py`` : le répertoire
de profils et le fichier manifest vivent dans deux répertoires distincts
(``profiles_dir`` vs son parent), pour que le glob ``*.yml`` du registre ne
charge jamais accidentellement le manifest lui-même comme un profil.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from nexus_contracts.ingestion import CollectionProfile

from ingestor import api as api_module
from ingestor import ingestion_governance_gate
from ingestor.ingestion_governance_gate import (
    IngestionGovernanceConfigError,
    ingestion_control_plane_enabled,
)
from ingestor.ingestion_profiles.manifest import ProfileManifestError
from ingestor.ingestion_profiles.registry import ProfileRegistryLoadError, profile_fingerprint
from ingestor.ingestion_worker import cli as worker_cli

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


def _write_profile(directory: Path, filename: str = "a.yml", **overrides: object) -> None:
    (directory / filename).write_text(
        yaml.safe_dump(_profile_payload(**overrides)), encoding="utf-8"
    )


def _write_manifest(
    directory: Path,
    *,
    collection: str = "rag_nexus_nsi_terminale_specialite",
    profile_version: str = "v1",
    fingerprint: str | None = None,
    manifest_version: str = "1",
    profile_overrides: dict[str, object] | None = None,
) -> Path:
    computed = fingerprint
    if computed is None:
        profile = CollectionProfile.model_validate(
            _profile_payload(profile_version=profile_version, **(profile_overrides or {}))
        )
        computed = profile_fingerprint(profile)
    path = directory / "manifest.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "manifest_version": manifest_version,
                "provenance": "test-governance-export",
                "generated_at": "2026-08-05T00:00:00Z",
                "profiles": [
                    {
                        "collection": collection,
                        "profile_version": profile_version,
                        "fingerprint": computed,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def profiles_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "profiles"
    directory.mkdir()
    return directory


class TestResolveProfilesDirFallback:
    """LOT44f : resolve_profiles_dir() ne doit jamais lever IndexError,
    quelle que soit la profondeur réelle de ce fichier sur le filesystem —
    régression réelle découverte lors de la validation Docker go-live
    (image aplatie, ce fichier vit à /app/, trop proche de la racine pour
    un parents[2] fixe)."""

    def test_no_env_var_does_not_raise_regardless_of_depth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("RAG_ENGINE_INGESTION_PROFILES_DIR", raising=False)
        result = ingestion_governance_gate.resolve_profiles_dir()
        assert result.name == "ingestion_profiles"
        assert result.parent.name == "configs"

    def test_shallow_file_path_falls_back_to_containing_directory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simule le mode Docker aplati (ce fichier vivrait en
        ``/app/ingestion_governance_gate.py``, 2 parents seulement, pas 3)."""
        monkeypatch.delenv("RAG_ENGINE_INGESTION_PROFILES_DIR", raising=False)
        monkeypatch.setattr(ingestion_governance_gate, "__file__", "/app/ingestion_governance_gate.py")
        result = ingestion_governance_gate.resolve_profiles_dir()
        assert result == Path("/app/configs/ingestion_profiles")


class TestApiLifespanGateDisabledByDefault:
    def test_dsn_unset_lifespan_starts_without_calling_gate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PG_INGESTION_CONTROL_DSN", raising=False)
        assert ingestion_control_plane_enabled() is False
        with TestClient(api_module.app):
            pass  # no exception on __enter__/__exit__ = lifespan started and stopped cleanly

    def test_dsn_unset_manifest_env_vars_also_ignored(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("PG_INGESTION_CONTROL_DSN", raising=False)
        monkeypatch.setenv("RAG_ENGINE_INGESTION_MANIFEST_PATH", str(tmp_path / "does_not_exist.yml"))
        with TestClient(api_module.app):
            pass


class TestApiLifespanGateEnabledPositive:
    def test_valid_manifest_and_registry_starts_cleanly(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profiles_dir: Path
    ) -> None:
        _write_profile(profiles_dir)
        manifest_path = _write_manifest(tmp_path)
        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", "postgresql://unused/for/this/test")
        monkeypatch.setenv("RAG_ENGINE_INGESTION_PROFILES_DIR", str(profiles_dir))
        monkeypatch.setenv("RAG_ENGINE_INGESTION_MANIFEST_PATH", str(manifest_path))
        with TestClient(api_module.app):
            pass


class TestApiLifespanGateEnabledNegative:
    def test_manifest_path_env_var_missing_blocks_startup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profiles_dir: Path
    ) -> None:
        _write_profile(profiles_dir)
        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", "postgresql://unused/for/this/test")
        monkeypatch.setenv("RAG_ENGINE_INGESTION_PROFILES_DIR", str(profiles_dir))
        monkeypatch.delenv("RAG_ENGINE_INGESTION_MANIFEST_PATH", raising=False)
        with pytest.raises(IngestionGovernanceConfigError):
            with TestClient(api_module.app):
                pass

    def test_missing_manifest_file_blocks_startup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profiles_dir: Path
    ) -> None:
        _write_profile(profiles_dir)
        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", "postgresql://unused/for/this/test")
        monkeypatch.setenv("RAG_ENGINE_INGESTION_PROFILES_DIR", str(profiles_dir))
        monkeypatch.setenv(
            "RAG_ENGINE_INGESTION_MANIFEST_PATH", str(tmp_path / "missing_manifest.yml")
        )
        with pytest.raises(ProfileManifestError):
            with TestClient(api_module.app):
                pass

    def test_empty_profiles_dir_blocks_startup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        manifest_path = _write_manifest(tmp_path)
        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", "postgresql://unused/for/this/test")
        monkeypatch.setenv("RAG_ENGINE_INGESTION_PROFILES_DIR", str(empty_dir))
        monkeypatch.setenv("RAG_ENGINE_INGESTION_MANIFEST_PATH", str(manifest_path))
        with pytest.raises(ProfileManifestError):
            with TestClient(api_module.app):
                pass

    def test_fingerprint_drift_blocks_startup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profiles_dir: Path
    ) -> None:
        _write_profile(profiles_dir)
        manifest_path = _write_manifest(tmp_path, fingerprint="0" * 64)
        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", "postgresql://unused/for/this/test")
        monkeypatch.setenv("RAG_ENGINE_INGESTION_PROFILES_DIR", str(profiles_dir))
        monkeypatch.setenv("RAG_ENGINE_INGESTION_MANIFEST_PATH", str(manifest_path))
        with pytest.raises(ProfileManifestError, match="Fingerprint mismatch"):
            with TestClient(api_module.app):
                pass

    def test_unsupported_manifest_version_blocks_startup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profiles_dir: Path
    ) -> None:
        _write_profile(profiles_dir)
        manifest_path = _write_manifest(tmp_path, manifest_version="99")
        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", "postgresql://unused/for/this/test")
        monkeypatch.setenv("RAG_ENGINE_INGESTION_PROFILES_DIR", str(profiles_dir))
        monkeypatch.setenv("RAG_ENGINE_INGESTION_MANIFEST_PATH", str(manifest_path))
        with pytest.raises(ProfileManifestError):
            with TestClient(api_module.app):
                pass

    def test_structurally_invalid_profile_blocks_startup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profiles_dir: Path
    ) -> None:
        (profiles_dir / "bad.yml").write_text("not: [a, valid, profile", encoding="utf-8")
        manifest_path = _write_manifest(tmp_path)
        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", "postgresql://unused/for/this/test")
        monkeypatch.setenv("RAG_ENGINE_INGESTION_PROFILES_DIR", str(profiles_dir))
        monkeypatch.setenv("RAG_ENGINE_INGESTION_MANIFEST_PATH", str(manifest_path))
        with pytest.raises(ProfileRegistryLoadError):
            with TestClient(api_module.app):
                pass


class _DbConnectAttempted(RuntimeError):
    """Sentinelle : prouve que l'exécution a dépassé le gate et atteint la
    tentative de connexion PostgreSQL, sans avoir besoin d'une base réelle."""


class TestWorkerCliGatePositive:
    def test_valid_manifest_reaches_db_connect_step(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profiles_dir: Path
    ) -> None:
        _write_profile(profiles_dir)
        manifest_path = _write_manifest(tmp_path)
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir()

        def _fake_connect(*_args: object, **_kwargs: object) -> None:
            raise _DbConnectAttempted("gate passed, reached db connect")

        monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", "postgresql://unused/for/this/test")
        monkeypatch.setattr(worker_cli.psycopg, "connect", _fake_connect)
        with pytest.raises(_DbConnectAttempted):
            worker_cli.main(
                [
                    "--profiles-dir",
                    str(profiles_dir),
                    "--manifest-path",
                    str(manifest_path),
                    "--artifact-store-dir",
                    str(artifact_dir),
                    "--owner",
                    "worker-test",
                    "--once",
                ]
            )


class TestWorkerCliGateNegative:
    def _assert_gate_blocks_before_db_connect(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        *,
        profiles_dir: Path,
        manifest_path: Path,
    ) -> None:
        def _fail_if_called(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("psycopg.connect must never be reached when the gate fails")

        monkeypatch.setattr(worker_cli.psycopg, "connect", _fail_if_called)
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir()
        exit_code = worker_cli.main(
            [
                "--profiles-dir",
                str(profiles_dir),
                "--manifest-path",
                str(manifest_path),
                "--artifact-store-dir",
                str(artifact_dir),
                "--owner",
                "worker-test",
                "--once",
            ]
        )
        assert exit_code == 1

    def test_missing_manifest_file_blocks_worker_startup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profiles_dir: Path
    ) -> None:
        _write_profile(profiles_dir)
        self._assert_gate_blocks_before_db_connect(
            monkeypatch,
            tmp_path,
            profiles_dir=profiles_dir,
            manifest_path=tmp_path / "missing.yml",
        )

    def test_empty_profiles_dir_blocks_worker_startup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        manifest_path = _write_manifest(tmp_path)
        self._assert_gate_blocks_before_db_connect(
            monkeypatch,
            tmp_path,
            profiles_dir=empty_dir,
            manifest_path=manifest_path,
        )

    def test_fingerprint_drift_blocks_worker_startup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profiles_dir: Path
    ) -> None:
        _write_profile(profiles_dir)
        manifest_path = _write_manifest(tmp_path, fingerprint="0" * 64)
        self._assert_gate_blocks_before_db_connect(
            monkeypatch,
            tmp_path,
            profiles_dir=profiles_dir,
            manifest_path=manifest_path,
        )

    def test_worker_has_no_bypass_argument(self) -> None:
        parser = worker_cli._build_arg_parser()
        dest_names = {action.dest for action in parser._actions}
        assert not {"skip_gate", "no_gate", "bypass_gate"} & dest_names
        assert "manifest_path" in dest_names
