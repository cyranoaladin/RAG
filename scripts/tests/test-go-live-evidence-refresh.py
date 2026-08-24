#!/usr/bin/env python3
"""Cohérence des preuves ops go-live rafraîchies le 2026-08-24."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER_EVIDENCE = (
    REPO_ROOT / "docs/reports/evidence/atomic_docker_rehearsal_20260824.json"
)
DOCKER_PROTOCOL = (
    REPO_ROOT
    / "docs/reports/evidence/atomic_docker_rehearsal_protocol_20260824.md"
)
DB_EVIDENCE = (
    REPO_ROOT / "docs/reports/evidence/production_db_read_only_audit_20260824.json"
)
ENVIRONMENT_EVIDENCE = (
    REPO_ROOT / "docs/reports/github_environment_read_only_observation_20260824.json"
)
REPORT = REPO_ROOT / "docs/reports/lot_go_live_evidence_refresh_20260824.md"
RUNBOOK = REPO_ROOT / "docs/runbooks/go_live.md"
README_PROD = REPO_ROOT / "services/rag-engine/README-PROD.md"
CI_LOCAL = REPO_ROOT / "scripts/ci-local.sh"


def _load_canonical_json(path: Path) -> tuple[dict[str, object], bytes]:
    raw = path.read_bytes()
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    canonical = (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    if raw != canonical:
        raise AssertionError(f"{path} must use canonical sorted JSON")
    return document, raw


class GoLiveEvidenceRefreshTests(unittest.TestCase):
    def test_guard_is_wired_into_local_ci(self) -> None:
        ci_source = CI_LOCAL.read_text(encoding="utf-8")
        self.assertIn(
            'run_target "go-live-evidence-refresh-tests" '
            '"$PYTHON_BIN" scripts/tests/test-go-live-evidence-refresh.py',
            ci_source,
        )

    def test_atomic_docker_rehearsal_is_exact_and_isolated(self) -> None:
        document, raw = _load_canonical_json(DOCKER_EVIDENCE)
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            "0fe6d56453462dd76360ae45627a4d4549bd486cf039a163140bc28987b34865",
        )
        self.assertEqual(
            document,
            {
                "ATOMIC_DOCKER_REHEARSAL_PASS": True,
                "BAD_DIGEST_REFUSED": True,
                "BAD_READINESS_REFUSED": True,
                "FOREIGN_SERVICES_TOUCHED": 0,
                "ROLLBACK_REHEARSAL_PASS": True,
                "foreign_changes_after_rollback": [],
                "foreign_changes_after_up": [],
                "main_sha": "8aa65fb3fb5f077bcd6dfa427c8902bd6d5c28b0",
                "main_tree_sha": "184613ba98608fd358f41859061e0a99156e469d",
                "pass": True,
                "production_project_name_used": False,
                "project_containers_remaining": [],
                "project_name": "nexus-go-live-rehearsal-2455258",
                "protocol_version": "NEXUS-ATOMIC-DOCKER-REHEARSAL-EVIDENCE-V1",
                "remove_orphans_used": False,
            },
        )

        protocol = DOCKER_PROTOCOL.read_text(encoding="utf-8")
        self.assertIn("fixture synthétique", protocol)
        self.assertIn("clé Ed25519 éphémère", protocol)
        self.assertIn("`--remove-orphans` n'est jamais utilisé", protocol)
        self.assertIn("la future release de production", protocol)
        self.assertNotIn("/home/", protocol)
        self.assertNotIn("TEST_SEED", protocol)

    def test_production_db_audit_is_read_only_and_complete(self) -> None:
        document, raw = _load_canonical_json(DB_EVIDENCE)
        self.assertEqual(document["protocol_version"], "NEXUS-PROD-DB-READ-ONLY-AUDIT-V1")
        self.assertEqual(document["main_sha"], "8aa65fb3fb5f077bcd6dfa427c8902bd6d5c28b0")
        self.assertEqual(document["main_tree_sha"], "184613ba98608fd358f41859061e0a99156e469d")
        self.assertIs(document["read_only"], True)
        self.assertEqual(document["PROD_DB_WRITES"], 0)
        self.assertIs(document["PROD_DB_TARGET_VERIFIED"], True)
        self.assertIs(document["PROD_DB_MIGRATION_PLAN_READY"], True)
        self.assertEqual(document["target"], {
            "container": "rag_pgvector",
            "database": "ragdb",
            "postgres_version": "16.14",
            "vector_extension_version": "0.8.2",
        })
        self.assertEqual(document["schema"], {
            "ingestion_control_applied": [],
            "ingestion_control_pending": list(range(1, 14)),
            "product_applied_registered": [],
            "product_pending": [2, 3, 4],
            "product_structural_head": 1,
            "product_structural_head_registered": False,
        })
        self.assertEqual(document["rag_chunks_exact_count"], 0)
        self.assertEqual(document["table_exact_counts"], {
            "rag_api_keys": 0,
            "rag_chunks": 0,
            "rag_eval_runs": 0,
        })
        self.assertEqual(document["rag_chunks_indexes"], {
            "idx_rag_chunks_text_tsv_present": False,
            "primary_key": "rag_chunks_pkey",
            "secondary_indexes": [
                "idx_rag_chunks_audience",
                "idx_rag_chunks_collection",
                "idx_rag_chunks_matiere",
                "idx_rag_chunks_niveau",
                "idx_rag_chunks_review",
                "idx_rag_chunks_rights",
                "idx_rag_chunks_vector",
            ],
        })
        self.assertEqual(document["waiting_locks"], 0)
        self.assertEqual(document["connections"], {
            "active": 1,
            "audit_session_included": True,
            "total": 1,
        })
        self.assertEqual(document["storage"], {
            "filesystem_available": "151G",
            "filesystem_device": "/dev/md2",
            "filesystem_total": "929G",
            "filesystem_used_percent": 83,
            "postgres_data_directory_size": "47M",
        })
        self.assertEqual(document["latest_database_backup_date"], "2026-07-13")
        self.assertEqual(document["latest_database_backup_age_days"], 42)
        self.assertIs(document["latest_database_backup_stale"], True)
        self.assertIs(document["fresh_backup_required_before_migration"], True)
        decoded = raw.decode()
        self.assertNotIn("/home/", decoded)
        self.assertNotIn("88.99.", decoded)
        self.assertNotIn("HostName", decoded)

    def test_report_publishes_proven_booleans_and_defers_master_reconciliation(self) -> None:
        report = REPORT.read_text(encoding="utf-8")
        normalized_report = " ".join(report.split())
        for expected in (
            "ATOMIC_DOCKER_REHEARSAL_PASS=true",
            "FOREIGN_SERVICES_TOUCHED=0",
            "ROLLBACK_REHEARSAL_PASS=true",
            "BAD_DIGEST_REFUSED=true",
            "BAD_READINESS_REFUSED=true",
            "PROD_DB_TARGET_VERIFIED=true",
            "PROD_DB_MIGRATION_PLAN_READY=true",
            "PROD_DB_WRITES=0",
            "PRODUCTION_ENVIRONMENT_EXISTS=false",
            "MASTER_RECONCILIATION_DEFERRED=true",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, report)
        self.assertIn(DOCKER_EVIDENCE.relative_to(REPO_ROOT).as_posix(), report)
        self.assertIn(DOCKER_PROTOCOL.relative_to(REPO_ROOT).as_posix(), report)
        self.assertIn(DB_EVIDENCE.relative_to(REPO_ROOT).as_posix(), report)
        self.assertIn(ENVIRONMENT_EVIDENCE.relative_to(REPO_ROOT).as_posix(), report)
        self.assertIn("fixture synthétique signée V1", normalized_report)
        self.assertIn("pas la future release de production", normalized_report)

    def test_operator_docs_require_head_004_and_exact_migration_sequence(self) -> None:
        runbook = RUNBOOK.read_text(encoding="utf-8")
        readme = README_PROD.read_text(encoding="utf-8")
        normalized_runbook = " ".join(runbook.split())
        self.assertNotIn("head `003_profile_filtering`", runbook)
        self.assertNotIn("head 003", runbook)
        self.assertNotIn('"003_profile_filtering"', runbook)
        self.assertNotIn("head `003_profile_filtering`", readme)
        self.assertNotIn("les 31 colonnes", readme)
        self.assertIn("les 32 colonnes de `rag_chunks`", readme)
        self.assertIn("`rag_artifacts`", readme)
        self.assertIn("`rag_artifact_placements`", readme)
        for expected in (
            "004_artifact_placements",
            "adopter le head structurel non enregistré `001`",
            "appliquer `002`, `003`, puis `004`",
            "backup frais",
            "`001` à `013`",
            "rollback",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, normalized_runbook)


if __name__ == "__main__":
    unittest.main()
