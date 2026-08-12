"""Les points d'application du gate de readiness (ADR-0036).

Vérifier le parseur ne suffit pas : ce qui compte est qu'un worker réel
refuse de démarrer et qu'un job réel refuse d'être créé. Ces tests
appellent donc les ``main()`` de production et mesurent leur code de
sortie, leur message et — surtout — le fait qu'ils s'arrêtent **avant**
tout le reste.

Aucune base n'est nécessaire : le refus intervient avant la moindre
connexion, et c'est précisément ce qu'on veut prouver. Un gate qui ne
refuserait qu'après avoir ouvert une transaction laisserait une fenêtre.
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT / "src"))

from nexus_contracts.production_readiness import (  # noqa: E402
    PRODUCTION_READINESS_PROTOCOL_VERSION,
    ProductionReadinessManifestV1,
    public_readiness_key_hex,
    sign_production_readiness_manifest,
)

from ingestor.ingestion_profiles import readiness_gate as gate_module  # noqa: E402
from ingestor.ingestion_worker import cli as worker_cli  # noqa: E402
from ingestor.ingestion_worker import create_job_cli  # noqa: E402

SEED = "55" * 32
KEY_ID = "nexus-readiness-test-1"
MERGE_SHA = "a" * 40
TREE_SHA = "b" * 40


def _signed_manifest_bytes() -> bytes:
    manifest = ProductionReadinessManifestV1(
        protocol_version=PRODUCTION_READINESS_PROTOCOL_VERSION,
        repository="cyranoaladin/RAG",
        pr_number=95,
        pr_head_sha="c" * 40,
        pr_head_tree_sha=TREE_SHA,
        merge_sha=MERGE_SHA,
        merge_tree_sha=TREE_SHA,
        release_tag=f"release/rag/20260811-{MERGE_SHA[:12]}",
        environment="production",
        review_binding_digest="11" * 32,
        authorization_digest="22" * 32,
        trust_anchor_digest="33" * 32,
        revocation_registry_digest="44" * 32,
        catalog_digest="55" * 32,
        sealed_manifest_digest="66" * 32,
        h2b_report_digest="77" * 32,
        gate_result="pass",
        application_image_digests={
            "ingestion-worker": "ghcr.io/o/rag-ingestion-worker@sha256:" + "1" * 64
        },
        upstream_image_digests={"pgvector": "pgvector/pgvector@sha256:" + "3" * 64},
        compose_digest="88" * 32,
        workflow_path=".github/workflows/promote-rag-production.yml",
        workflow_ref="refs/heads/main",
        run_id=4242,
        run_attempt=1,
        issued_at=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
        key_id=KEY_ID,
    )
    return sign_production_readiness_manifest(
        manifest, private_key_hex=SEED, key_id=KEY_ID
    ).canonical_bytes()


def _install_governed_anchor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, present: bool = True
) -> None:
    root = tmp_path / "governed_root"
    for marker in gate_module._GOVERNED_ROOT_MARKERS:
        (root / marker).mkdir(parents=True, exist_ok=True)
    if present:
        target = root / gate_module.GOVERNED_TRUST_ANCHOR_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            json.dumps(
                {
                    "protocol_version": PRODUCTION_READINESS_PROTOCOL_VERSION,
                    "keys": [
                        {
                            "key_id": KEY_ID,
                            "algorithm": "ed25519",
                            "public_key": public_readiness_key_hex(SEED),
                            "environment": "production",
                        }
                    ],
                }
            ).encode("utf-8")
        )
    monkeypatch.setattr(gate_module, "_GOVERNED_REPOSITORY_ROOT", root)


def _worker_argv(tmp_path: Path) -> list[str]:
    """Jeu d'arguments complet : argparse s'exécute avant le gate, ce qui
    est sans effet de bord, mais impose de fournir le tout."""
    return [
        "--profiles-dir", str(tmp_path / "profiles"),
        "--manifest-path", str(tmp_path / "manifest.yml"),
        "--artifact-store-dir", str(tmp_path / "artifacts"),
        "--owner", "readiness-test",
        "--expected-role", "ingestion_control_app",
        "--pii-evidence-path", str(tmp_path / "pii.json"),
        "--pii-evidence-sha256", "1" * 64,
        "--rights-evidence-path", str(tmp_path / "rights.yml"),
        "--rights-evidence-sha256", "2" * 64,
        "--corpus-manifest-sha256", "3" * 64,
        "--catalog-path", str(tmp_path / "catalog.json"),
        "--catalog-sha256", "4" * 64,
        "--candidate-inventory-path", str(tmp_path / "inventory.json"),
        "--candidate-inventory-sha256", "5" * 64,
        "--currentness-evidence-path", str(tmp_path / "currentness.yml"),
        "--currentness-evidence-sha256", "6" * 64,
        "--mapping-path", str(tmp_path / "mapping.yml"),
        "--mapping-sha256", "7" * 64,
        "--release-manifest-path", str(tmp_path / "release.json"),
        "--release-manifest-sha256", "8" * 64,
        "--programme-index-path", str(tmp_path / "programme.yml"),
        "--programme-index-sha256", "9" * 64,
        "--collection-config-path", str(tmp_path / "collections.yml"),
        "--collection-config-sha256", "a" * 64,
    ]


def _create_job_argv(tmp_path: Path) -> list[str]:
    return [
        "--profiles-dir", str(tmp_path / "profiles"),
        "--manifest-path", str(tmp_path / "manifest.yml"),
        "--tenant", "nexus",
        "--collection", "libre_terminale_philosophie",
        "--niveau", "terminale",
        "--voie", "generale",
        "--matiere", "philosophie",
        "--candidat", "libre",
        "--audience", "libre",
        "--visibility", "internal",
        "--school-year", "2026-2027",
        "--programme-version", "BOEN_special_8_2019-07-25",
        "--profile-version", "1.0.0",
        "--scope-authorization-id", "auth-readiness-test",
        "--source-url", "https://eduscol.education.gouv.fr/a",
        "--canonical-url", "https://eduscol.education.gouv.fr/a",
        "--domain", "eduscol.education.gouv.fr",
        "--proposed-type-doc", "cours",
    ]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        gate_module.MANIFEST_PATH_ENV,
        gate_module.RELEASE_SHA_ENV,
        gate_module.ENVIRONMENT_ENV,
        gate_module.REHEARSAL_TRUST_ANCHOR_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


class TestWorkerStartupApplicationPoint:
    def test_the_worker_refuses_to_start_without_a_readiness_manifest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _install_governed_anchor(monkeypatch, tmp_path)

        def never(*_args: object, **_kwargs: object) -> object:
            pytest.fail(
                "the profile manifest gate ran despite a missing readiness "
                "manifest — the readiness check is not the first barrier"
            )

        monkeypatch.setattr(worker_cli, "enforce_production_manifest_gate", never)

        exit_code = worker_cli.main(_worker_argv(tmp_path))
        assert exit_code == 1
        assert "WORKER_READINESS_GATE_FAILED" in capsys.readouterr().err

    def test_the_worker_refuses_a_manifest_for_another_release(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _install_governed_anchor(monkeypatch, tmp_path)
        path = tmp_path / "readiness-manifest.json"
        path.write_bytes(_signed_manifest_bytes())
        path.chmod(0o444)
        monkeypatch.setenv(gate_module.MANIFEST_PATH_ENV, str(path))
        monkeypatch.setenv(gate_module.RELEASE_SHA_ENV, "e" * 40)
        monkeypatch.setattr(
            worker_cli,
            "enforce_production_manifest_gate",
            lambda *_a, **_k: pytest.fail("startup continued past readiness"),
        )

        assert worker_cli.main(_worker_argv(tmp_path)) == 1
        assert "but the release being deployed" in capsys.readouterr().err


class TestJobCreationApplicationPoint:
    def test_no_job_is_created_without_a_readiness_manifest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _install_governed_anchor(monkeypatch, tmp_path)
        monkeypatch.setattr(
            create_job_cli,
            "enforce_production_manifest_gate",
            lambda *_a, **_k: pytest.fail("job creation continued past readiness"),
        )

        exit_code = create_job_cli.main(_create_job_argv(tmp_path))
        assert exit_code == 1
        assert "WORKER_READINESS_GATE_FAILED" in capsys.readouterr().err

    def test_a_manifest_removed_after_startup_blocks_the_next_mutation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Le point du second contrôle : un manifeste retiré après le
        démarrage ne serait jamais vu par un gate qui ne s'exécuterait
        qu'une fois — or la création de job est la mutation qui compte."""
        _install_governed_anchor(monkeypatch, tmp_path)
        path = tmp_path / "readiness-manifest.json"
        path.write_bytes(_signed_manifest_bytes())
        path.chmod(0o444)
        monkeypatch.setenv(gate_module.MANIFEST_PATH_ENV, str(path))
        monkeypatch.setenv(gate_module.RELEASE_SHA_ENV, MERGE_SHA)

        # Le gate passe tant que le manifeste est là.
        assert gate_module.enforce_readiness_gate().manifest.merge_sha == MERGE_SHA

        # Puis il disparaît — comme le ferait une substitution maladroite.
        path.unlink()
        monkeypatch.setattr(
            create_job_cli,
            "enforce_production_manifest_gate",
            lambda *_a, **_k: pytest.fail("job creation continued past readiness"),
        )
        assert create_job_cli.main(_create_job_argv(tmp_path)) == 1
        assert "does not exist" in capsys.readouterr().err
