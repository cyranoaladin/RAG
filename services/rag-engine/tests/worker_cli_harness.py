"""Foyer partagé des bancs qui pilotent `ingestion_worker.cli.main`.

L'argv complet du worker et le remplacement des autorités étaient recopiés
dans deux fichiers de tests. Toute évolution des arguments obligatoires de
`runtime_authority.py` devait donc être répercutée à la main aux deux endroits,
et un oubli aurait cassé une suite en silence — c'est exactement ce qui vient
de se produire avec `--repository-root`.

Ce module ne contient AUCUNE assertion : il ne fait que construire ce que les
tests consomment. Ce que chaque banc mesure lui reste propre.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def readiness_stub() -> object:
    """Résultat de readiness minimal — jamais un contournement du gate.

    Le gate réel est mesuré par ses propres suites ; ici il serait un bruit de
    fond qui ferait échouer un test pour une raison sans rapport."""
    return SimpleNamespace(
        environment="production",
        manifest=SimpleNamespace(
            merge_sha="0" * 40, release_tag="v0-test", run_id="run-test"
        ),
        authorization_mapping=None,
    )


def authorities_stub() -> object:
    """Autorités déjà vérifiées ailleurs, remplacées ici par leur forme."""
    return SimpleNamespace(
        pii_evidence_registry=SimpleNamespace(evidence_sha256="1" * 64, cleared_count=1),
        rights_evidence_registry=SimpleNamespace(
            registry_sha256="2" * 64, registry_id="worker-cli-harness"
        ),
        placement_resolver=SimpleNamespace(release_manifest_sha256="3" * 64),
    )


def write_sealed_evidence(root: Path) -> list[str]:
    """Preuves scellées minimales mais cohérentes.

    Leur contenu n'est pas le sujet des bancs qui les consomment ; leur
    PRÉSENCE l'est, puisqu'un worker de production ne démarre plus sans elles."""
    manifest = "d" * 64
    pii = root / "pii.json"
    pii.write_text(
        json.dumps(
            {
                "evidence_kind": "REAL_CORPUS_PII_SCAN",
                "corpus_manifest_sha256": manifest,
                "remote_access_mode": "READ_ONLY",
                "remote_write_operations": 0,
                "raw_pii_in_output": False,
                "raw_pii_in_logs": False,
                "results": [
                    {"content_sha256": "a" * 64, "status": "CLEARED", "pii_detected": False},
                ],
            }
        ),
        encoding="utf-8",
    )
    rights = root / "rights.yml"
    rights.write_text(
        "registry_id: test\n"
        "human_rights_decisions:\n"
        "  eduscol:\n"
        f'    scope_manifest_sha256: "{manifest}"\n'
        "    scope_zone: 01_EDUSCOL_OFFICIEL/\n"
        "    approved_for_production_rag: true\n"
        "source_evidence:\n"
        "  eduscol:\n"
        "    zone: 01_EDUSCOL_OFFICIEL/\n"
        "    recommended_rights_category: officiel_public\n",
        encoding="utf-8",
    )
    return [
        "--pii-evidence-path", str(pii),
        "--pii-evidence-sha256", hashlib.sha256(pii.read_bytes()).hexdigest(),
        "--rights-evidence-path", str(rights),
        "--rights-evidence-sha256", hashlib.sha256(rights.read_bytes()).hexdigest(),
        "--corpus-manifest-sha256", manifest,
    ]


def worker_argv(
    *,
    profiles_dir: Path,
    manifest_path: Path,
    artifact_dir: Path,
    expected_role: str,
    owner: str,
    extra: list[str] | None = None,
) -> list[str]:
    """L'argv complet qu'un worker de production exige aujourd'hui."""
    root = artifact_dir.parent
    argv = [
        "--profiles-dir", str(profiles_dir),
        "--manifest-path", str(manifest_path),
        "--artifact-store-dir", str(artifact_dir),
        "--expected-role", expected_role,
        "--owner", owner,
        *write_sealed_evidence(root),
        "--catalog-path", str(root / "catalog.json"),
        "--catalog-sha256", "3" * 64,
        "--candidate-inventory-path", str(root / "inventory.json"),
        "--candidate-inventory-sha256", "4" * 64,
        "--currentness-evidence-path", str(root / "currentness.yml"),
        "--currentness-evidence-sha256", "5" * 64,
        "--mapping-path", str(root / "mapping.yml"),
        "--mapping-sha256", "6" * 64,
        "--release-manifest-path", str(root / "release.json"),
        "--release-manifest-sha256", "7" * 64,
        "--programme-index-path", str(root / "programme.yml"),
        "--programme-index-sha256", "8" * 64,
        "--collection-config-path", str(root / "collections.yml"),
        "--collection-config-sha256", "9" * 64,
        "--repository-root", str(REPOSITORY_ROOT),
        "--once",
    ]
    return argv + list(extra or [])


def unused(*_args: Any) -> None:  # pragma: no cover - garde de lisibilité
    """Marque explicitement qu'un paramètre n'est pas consommé."""
