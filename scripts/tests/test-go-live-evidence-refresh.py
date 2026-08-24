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
ROLLBACK_RUNBOOK = REPO_ROOT / "docs/runbooks/rollback.md"
CI_LOCAL = REPO_ROOT / "scripts/ci-local.sh"


def _canonical_json_bytes(document: object) -> bytes:
    return (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def _load_canonical_json(path: Path) -> tuple[dict[str, object], bytes]:
    raw = path.read_bytes()
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    canonical = _canonical_json_bytes(document)
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

    def test_atomic_docker_rehearsal_is_synthetic_v1_and_unverified_for_v2(
        self,
    ) -> None:
        document, raw = _load_canonical_json(DOCKER_EVIDENCE)
        observation = document["synthetic_v1_observation"]
        self.assertEqual(
            document["source_evidence_sha256"],
            "0fe6d56453462dd76360ae45627a4d4549bd486cf039a163140bc28987b34865",
        )
        self.assertEqual(
            hashlib.sha256(_canonical_json_bytes(observation)).hexdigest(),
            document["source_evidence_sha256"],
        )
        self.assertEqual(document["evidence_class"], "SYNTHETIC_V1")
        self.assertEqual(document["verification_status"], "UNVERIFIED")
        self.assertEqual(
            observation,
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
        self.assertEqual(
            document["production_v2_rehearsal"],
            {
                "ATOMIC_DOCKER_REHEARSAL_PASS": None,
                "BAD_DIGEST_REFUSED": None,
                "BAD_READINESS_REFUSED": None,
                "FOREIGN_SERVICES_TOUCHED": None,
                "ROLLBACK_REHEARSAL_PASS": None,
                "readiness_protocol_required": "NEXUS-PRODUCTION-READINESS-V2",
                "reproducible_harness_versioned": False,
                "transcript_versioned": False,
            },
        )
        self.assertNotIn(b'"ATOMIC_DOCKER_REHEARSAL_PASS": true', raw.split(b'"synthetic_v1_observation"')[0])

        protocol = DOCKER_PROTOCOL.read_text(encoding="utf-8")
        self.assertIn("fixture synthétique", protocol)
        self.assertIn("clé Ed25519 éphémère", protocol)
        self.assertIn("`--remove-orphans` n'est jamais utilisé", protocol)
        self.assertIn("futures images de production", protocol)
        self.assertNotIn("/home/", protocol)
        self.assertNotIn("TEST_SEED", protocol)

    def test_production_db_summary_stays_unverified_without_transcript(self) -> None:
        document, raw = _load_canonical_json(DB_EVIDENCE)
        self.assertEqual(
            document["protocol_version"],
            "NEXUS-PROD-DB-READ-ONLY-AUDIT-ASSESSMENT-V1",
        )
        self.assertEqual(document["main_sha"], "8aa65fb3fb5f077bcd6dfa427c8902bd6d5c28b0")
        self.assertEqual(document["main_tree_sha"], "184613ba98608fd358f41859061e0a99156e469d")
        self.assertEqual(document["evidence_status"], "UNVERIFIED_SUMMARY_NO_TRANSCRIPT")
        self.assertIsNone(document["PROD_DB_WRITES"])
        self.assertIsNone(document["PROD_DB_TARGET_VERIFIED"])
        self.assertIsNone(document["PROD_DB_MIGRATION_PLAN_READY"])
        self.assertIs(document["commands_versioned"], False)
        self.assertIs(document["transcript_versioned"], False)
        observation = document["unverified_operator_observation"]
        self.assertIs(observation["reported_read_only"], True)
        self.assertEqual(observation["reported_target"], {
            "container": "rag_pgvector",
            "database": "ragdb",
            "postgres_version": "16.14",
            "vector_extension_version": "0.8.2",
        })
        self.assertEqual(observation["reported_schema"], {
            "ingestion_control_applied": [],
            "ingestion_control_pending": list(range(1, 14)),
            "product_applied_registered": [],
            "product_pending": [2, 3, 4],
            "product_structural_head": 1,
            "product_structural_head_registered": False,
        })
        self.assertEqual(observation["reported_table_exact_counts"], {
            "rag_api_keys": 0,
            "rag_chunks": 0,
            "rag_eval_runs": 0,
        })
        self.assertEqual(observation["reported_rag_chunks_indexes"], {
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
        self.assertEqual(observation["reported_waiting_locks"], 0)
        self.assertEqual(observation["reported_connections"], {
            "active": 1,
            "audit_session_included": True,
            "total": 1,
        })
        self.assertEqual(observation["reported_storage"], {
            "filesystem_available": "151G",
            "filesystem_total": "929G",
            "filesystem_used_percent": 83,
            "postgres_data_directory_size": "47M",
        })
        self.assertEqual(observation["reported_latest_database_backup_date"], "2026-07-13")
        self.assertEqual(observation["reported_latest_database_backup_age_days"], 42)
        self.assertIs(observation["reported_latest_database_backup_stale"], True)
        self.assertIs(observation["fresh_backup_required_before_migration"], True)
        decoded = raw.decode()
        self.assertNotIn("/home/", decoded)
        self.assertNotIn("/dev/md2", decoded)
        self.assertNotIn("88.99.", decoded)
        self.assertNotIn("HostName", decoded)

    def test_environment_observation_is_refreshed_and_point_in_time(self) -> None:
        document, _ = _load_canonical_json(ENVIRONMENT_EVIDENCE)
        self.assertEqual(document["observed_at"], "2026-08-24T22:51:18Z")
        self.assertIs(document["point_in_time_only"], True)
        self.assertEqual(document["environment_query_result"], {"names": [], "total_count": 0})
        self.assertEqual(document["reviewer_query_result"], {
            "login": "abenrhouma",
            "permission": "write",
            "user_id": 67140603,
        })
        self.assertIs(document["mutation_performed"], False)

    def test_report_publishes_proven_booleans_and_defers_master_reconciliation(self) -> None:
        report = REPORT.read_text(encoding="utf-8")
        normalized_report = " ".join(report.split())
        for expected in (
            "DOCKER_REHEARSAL_EVIDENCE_CLASS=SYNTHETIC_V1",
            "DOCKER_REHEARSAL_VERIFICATION_STATUS=UNVERIFIED",
            "ATOMIC_DOCKER_REHEARSAL_PASS=UNKNOWN",
            "PROD_DB_AUDIT_VERIFICATION_STATUS=UNVERIFIED_SUMMARY_NO_TRANSCRIPT",
            "PROD_DB_TARGET_VERIFIED=UNKNOWN",
            "PROD_DB_MIGRATION_PLAN_READY=UNKNOWN",
            "PROD_DB_WRITES=UNKNOWN",
            "PRODUCTION_ENVIRONMENT_OBSERVED_AT=2026-08-24T22:51:18Z",
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
        self.assertIn("future release de production V2", normalized_report)
        for forbidden in (
            "ATOMIC_DOCKER_REHEARSAL_PASS=true",
            "PROD_DB_TARGET_VERIFIED=true",
            "PROD_DB_MIGRATION_PLAN_READY=true",
            "PROD_DB_WRITES=0",
            "/dev/md2",
        ):
            self.assertNotIn(forbidden, report)

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

    def test_custom_dump_restore_is_isolated_and_migrator_only(self) -> None:
        rollback = ROLLBACK_RUNBOOK.read_text(encoding="utf-8")
        normalized = " ".join(rollback.split())
        for expected in (
            "pg_dump -Fc",
            "pg_restore",
            "--format=custom",
            "--exit-on-error",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "--single-transaction",
            "restore-migrator",
            "run --rm --no-deps",
            "nexus-pg-restore-rehearsal-",
            "up -d --wait pgvector",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, normalized)
        self.assertNotIn("psql -U raguser ragdb < /backup/ragdb_YYYYMMDD.sql", rollback)
        self.assertNotIn("docker-compose.ingestion.yml", rollback)
        self.assertNotIn("ports:", rollback)
        self.assertNotIn("down --remove-orphans", rollback)
        self.assertIn("ne démarre ni API, ni worker", normalized)
        self.assertIn(
            '"${restore_compose[@]}" config --services | sort',
            rollback,
        )

    def test_restore_requires_the_real_backup_path_without_overwriting_it(self) -> None:
        rollback = ROLLBACK_RUNBOOK.read_text(encoding="utf-8")

        self.assertIn(': "${RESTORE_BACKUP_FILE:?', rollback)
        self.assertNotIn(
            "RESTORE_BACKUP_FILE=/backup/rag/pgvector-migration-YYYYMMDD/",
            rollback,
        )

    def test_restore_reprovisions_runtime_roles_after_acl_free_restore(self) -> None:
        rollback = ROLLBACK_RUNBOOK.read_text(encoding="utf-8")

        restore = rollback.index("--no-privileges")
        reprovision = rollback.index("provision_runtime_roles.sh", restore)
        self.assertLess(restore, reprovision)
        for variable in (
            "PGVECTOR_RETRIEVAL_USER",
            "PGVECTOR_RETRIEVAL_PASSWORD",
            "PGVECTOR_REVIEW_USER",
            "PGVECTOR_REVIEW_PASSWORD",
            "PGVECTOR_PUBLISHER_USER",
            "PGVECTOR_PUBLISHER_PASSWORD",
        ):
            with self.subTest(variable=variable):
                self.assertIn(variable, rollback[reprovision - 2500 :])


if __name__ == "__main__":
    unittest.main()
