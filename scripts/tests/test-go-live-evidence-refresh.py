#!/usr/bin/env python3
"""Cohérence des preuves ops go-live rafraîchies le 2026-08-24."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
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
INGESTION_CONTROL_HEAD = (
    REPO_ROOT
    / "services/rag-engine/infra/postgres/ingestion_control/migrations/HEAD"
)
CI_LOCAL = REPO_ROOT / "scripts/ci-local.sh"
DOCKER_V2_EVIDENCE = (
    REPO_ROOT / "docs/reports/evidence/atomic_docker_v2_rehearsal_20260825.json"
)
DOCKER_V2_TRANSCRIPT = (
    REPO_ROOT
    / "docs/reports/evidence/atomic_docker_v2_rehearsal_20260825.transcript.txt"
)
DOCKER_V2_HASHES = (
    REPO_ROOT / "docs/reports/evidence/atomic_docker_v2_rehearsal_20260825.sha256"
)
DOCKER_V2_HARNESS = (
    REPO_ROOT / "services/rag-engine/scripts/atomic_docker_v2_rehearsal.py"
)
DOCKER_V2_FIXTURE = (
    REPO_ROOT / "services/rag-engine/scripts/atomic_docker_v2_rehearsal_fixture.py"
)


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

    def test_atomic_docker_v2_rehearsal_is_canonical_complete_and_bound(self) -> None:
        document, _raw = _load_canonical_json(DOCKER_V2_EVIDENCE)
        self.assertEqual(
            document["protocol_version"],
            "NEXUS-ATOMIC-DOCKER-V2-REHEARSAL-EVIDENCE-V1",
        )
        self.assertEqual(document["evidence_class"], "SYNTHETIC_V2_REPRODUCIBLE")
        self.assertEqual(document["verification_status"], "VERIFIED")
        self.assertEqual(document["readiness_protocol"], "NEXUS-PRODUCTION-READINESS-V2")
        self.assertEqual(document["authorization_set_protocol"], "NEXUS-AUTHORIZATION-SET-V1")
        self.assertRegex(document["git_commit"], r"^[0-9a-f]{40}$")
        self.assertRegex(document["git_tree"], r"^[0-9a-f]{40}$")
        self.assertRegex(document["bundle_digest"], r"^[0-9a-f]{64}$")
        self.assertRegex(document["image"]["reference"], r"@sha256:[0-9a-f]{64}$")
        self.assertRegex(document["image"]["local_id"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            document["image"],
            {
                "build_invoked": False,
                "compose_pull_invoked": True,
                "local_id": document["image"]["local_id"],
                "preexisting_before_harness": True,
                "reference": document["image"]["reference"],
            },
        )
        self.assertTrue(document["docker"]["engine_version"])
        self.assertTrue(document["docker"]["compose_version"])

        verdicts = document["verdicts"]
        self.assertEqual(
            verdicts,
            {
                "ATOMIC_DOCKER_V2_REHEARSAL_PASS": True,
                "BAD_AUTHORIZATION_SET_REFUSED": True,
                "BAD_DIGEST_REFUSED": True,
                "BAD_READINESS_REFUSED": True,
                "FOREIGN_COLLISION_REFUSED": True,
                "FOREIGN_SERVICES_TOUCHED": 0,
                "ISOLATION_PREFLIGHT_PASS": True,
                "PROJECT_CONTAINERS_REMAINING": 0,
                "PRODUCTION_PORTS_PUBLISHED": 0,
                "PRODUCTION_PROJECT_NAME_USED": False,
                "REMOVE_ORPHANS_USED": False,
                "ROLLBACK_REHEARSAL_PASS": True,
            },
        )
        for name in (
            "bad_digest",
            "bad_readiness",
            "bad_authorization_set",
            "foreign_collision",
        ):
            with self.subTest(name=name):
                scenario = document["scenarios"][name]
                self.assertIs(scenario["passed"], True)
                self.assertEqual(scenario["exit_code"], 1)
                self.assertEqual(scenario["mutation_boundary_calls"], 0)
                self.assertEqual(scenario["docker_events"], [])
                self.assertEqual(
                    scenario["docker_inventory_before"],
                    scenario["docker_inventory_after"],
                )

        self.assertEqual(document["generated_project_residue"], {
            "containers": [],
            "networks": [],
            "volumes": [],
        })
        self.assertRegex(
            document["bundle_attestation"]["bundle_manifest_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertEqual(
            document["bundle_attestation"]["bundle_digest"],
            document["bundle_digest"],
        )
        member_paths = {
            member["path"]
            for member in document["bundle_attestation"]["member_sha256"]
        }
        self.assertIn("authorization-set.json", member_paths)
        self.assertIn(
            "readiness-manifest.json",
            member_paths,
        )
        self.assertEqual(
            set(document["health_observation"]),
            {
                "fixture-upstream",
                "ingestor",
                "multilevel-worker-a-production",
                "multilevel-worker-b-production",
            },
        )
        self.assertTrue(
            all(
                fact["health"] == "healthy"
                for fact in document["health_observation"].values()
            )
        )
        self.assertEqual(document["rollback"]["exit_code"], 0)
        self.assertEqual(document["rollback"]["project_inventory_after"], {
            "containers": [],
            "networks": [],
            "volumes": [],
        })
        self.assertEqual(
            document["harness"]["sha256"],
            hashlib.sha256(DOCKER_V2_HARNESS.read_bytes()).hexdigest(),
        )
        source_tree = subprocess.run(
            ["git", "rev-parse", f"{document['git_commit']}^{{tree}}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.assertEqual(document["git_tree"], source_tree)
        harness_at_source = subprocess.run(
            ["git", "show", f"{document['git_commit']}:{document['harness']['path']}"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
        self.assertEqual(
            document["harness"]["sha256"],
            hashlib.sha256(harness_at_source).hexdigest(),
        )
        fixture_relative = DOCKER_V2_FIXTURE.relative_to(REPO_ROOT).as_posix()
        fixture_at_source = subprocess.run(
            ["git", "show", f"{document['git_commit']}:{fixture_relative}"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
        self.assertEqual(
            document["fixture_builder_sha256"],
            hashlib.sha256(DOCKER_V2_FIXTURE.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            document["fixture_builder_sha256"],
            hashlib.sha256(fixture_at_source).hexdigest(),
        )
        self.assertEqual(
            document["transcript_sha256"],
            hashlib.sha256(DOCKER_V2_TRANSCRIPT.read_bytes()).hexdigest(),
        )

    def test_atomic_docker_v2_transcript_and_hash_inventory_are_sanitized(self) -> None:
        transcript = DOCKER_V2_TRANSCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("/home/", transcript)
        self.assertNotIn("/tmp/", transcript)
        self.assertNotIn("private_key", transcript.lower())
        self.assertNotIn("seed=", transcript.lower())
        self.assertNotIn("--remove-orphans", transcript)
        hashes = DOCKER_V2_HASHES.read_text(encoding="utf-8").splitlines()
        parsed = {}
        for line in hashes:
            digest, relative = line.split("  ", 1)
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            parsed[relative] = digest
        for relative in (
            "services/rag-engine/scripts/atomic_docker_v2_rehearsal.py",
            "services/rag-engine/scripts/atomic_docker_v2_rehearsal_fixture.py",
            "docs/reports/evidence/atomic_docker_v2_rehearsal_20260825.json",
            "docs/reports/evidence/atomic_docker_v2_rehearsal_20260825.transcript.txt",
        ):
            with self.subTest(relative=relative):
                self.assertEqual(
                    parsed[relative],
                    hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest(),
                )

    def test_atomic_docker_v1_historical_evidence_is_unchanged(self) -> None:
        self.assertEqual(
            hashlib.sha256(DOCKER_EVIDENCE.read_bytes()).hexdigest(),
            "58f55e7e499dfb3e9648387932af9a8edda35e8a51170afc3fd47ee52d70525c",
        )
        self.assertEqual(
            hashlib.sha256(DOCKER_PROTOCOL.read_bytes()).hexdigest(),
            "63df9f357c6b20a0ced8b15e19099a40a61004110fe27aed09c67278efc6d563",
        )

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
            "MASTER_RECONCILIATION_COMPLETE=true",
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

    def test_operator_docs_require_declared_migration_heads(self) -> None:
        runbook = RUNBOOK.read_text(encoding="utf-8")
        readme = README_PROD.read_text(encoding="utf-8")
        rollback = ROLLBACK_RUNBOOK.read_text(encoding="utf-8")
        ingestion_control_head = INGESTION_CONTROL_HEAD.read_text(encoding="utf-8").strip()
        ingestion_control_version = ingestion_control_head.partition("_")[0]
        normalized_runbook = " ".join(runbook.split())
        self.assertNotIn("head `003_profile_filtering`", runbook)
        self.assertNotIn("head 003", runbook)
        self.assertNotIn('"003_profile_filtering"', runbook)
        self.assertNotIn("head `003_profile_filtering`", readme)
        self.assertNotIn("les 31 colonnes", readme)
        self.assertNotIn("head `004_artifact_placements`", runbook)
        self.assertNotIn('"004_artifact_placements"', runbook)
        self.assertNotIn("head `004_artifact_placements`", readme)
        self.assertIn("`005_official_snapshot_currentness`", readme)
        self.assertIn("les 32 colonnes de `rag_chunks`", readme)
        self.assertIn("`rag_artifacts`", readme)
        self.assertIn("`rag_artifact_placements`", readme)
        for expected in (
            "004_artifact_placements",
            "005_official_snapshot_currentness",
            "adopter le head structurel non enregistré `001`",
            "appliquer `002`, `003`, `004`, puis `005`",
            "backup frais",
            f"`001` à `{ingestion_control_version}`",
            f"`{ingestion_control_head}`",
            "rollback",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, normalized_runbook)
        for migration in (
            "019_sealed_release_publication_authorizations.sql",
            "020_successor_control_resource_identity.sql",
        ):
            with self.subTest(migration=migration):
                self.assertIn(f"`{migration}`", normalized_runbook)
        self.assertIn(
            "SHA-256 recalculé pour chaque fichier enregistré, y compris les "
            "versions `019` et `020`",
            normalized_runbook,
        )
        self.assertIn(
            f"`ingestion_control.schema_migrations` doit être la suite contiguë "
            f"`1..{int(ingestion_control_version)}`",
            normalized_runbook,
        )
        self.assertIn(f"`SCHEMA_HEAD={int(ingestion_control_version)}`", normalized_runbook)
        self.assertIn(f"`{ingestion_control_head}`", rollback)

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

    def test_restore_identity_guard_rejects_encoding_and_locale_drift(self) -> None:
        rollback = ROLLBACK_RUNBOOK.read_text(encoding="utf-8")
        guard = re.search(
            r"(?ms)^assert_restore_compatible_identity\(\) \{\n.*?^\}", rollback
        )
        self.assertIsNotNone(guard, "garde exécutable absent du runbook")
        assert guard is not None
        script = guard.group(0) + '\nassert_restore_compatible_identity "$1" "$2"\n'

        for source, restored, accepted in (
            ("UTF8|C|C", "UTF8|C|C", True),
            ("UTF8|C|C", "SQL_ASCII|C|C", False),
            ("UTF8|C|C", "UTF8|en_US.utf8|en_US.utf8", False),
            ("SQL_ASCII|C|C", "SQL_ASCII|C|C", False),
            ("UTF8|C|C", "", False),
        ):
            with self.subTest(source=source, restored=restored):
                result = subprocess.run(
                    ["bash", "-c", script, "restore-guard", source, restored],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode == 0, accepted, result.stderr)

    def test_restore_paths_are_resolved_before_changing_directory(self) -> None:
        rollback = ROLLBACK_RUNBOOK.read_text(encoding="utf-8")
        normalizer = re.search(r"(?ms)^normalize_restore_paths\(\) \{\n.*?^\}", rollback)
        self.assertIsNotNone(normalizer)
        assert normalizer is not None
        self.assertIn("normalize_restore_paths\ncd services/rag-engine/infra", rollback)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "backup.dump").touch()
            (root / "credentials.env").touch()
            script = (
                normalizer.group(0)
                + '\nRESTORE_BACKUP_FILE=backup.dump\nRESTORE_ENV_FILE=credentials.env\n'
                + 'normalize_restore_paths\nprintf "%s\\n%s\\n" "$RESTORE_BACKUP_FILE" "$RESTORE_ENV_FILE"\n'
            )
            result = subprocess.run(
                ["bash", "-c", script],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(
                result.stdout.splitlines(),
                [str(root / "backup.dump"), str(root / "credentials.env")],
            )

    def test_historical_restore_is_readability_only(self) -> None:
        rollback = ROLLBACK_RUNBOOK.read_text(encoding="utf-8")
        classifier = re.search(r"(?ms)^classify_restore_schema_heads\(\) \{\n.*?^\}", rollback)
        self.assertIsNotNone(classifier)
        assert classifier is not None
        final_branch = rollback.index('if [[ "$RESTORE_SCHEMA_VERDICT" == FINAL_SCHEMA_CANDIDATE ]]; then')
        self.assertLess(final_branch, rollback.index('cat >"$RESTORE_FINGERPRINT_SQL"', final_branch))
        self.assertIn("FINAL_SCHEMA_UNVERIFIED=true", rollback[final_branch:])
        for heads, expected in (
            ("5|20", "FINAL_SCHEMA_CANDIDATE"),
            ("", "FINAL_SCHEMA_UNVERIFIED"),
            ("5|19", "FINAL_SCHEMA_UNVERIFIED"),
        ):
            with self.subTest(heads=heads):
                script = classifier.group(0) + '\nclassify_restore_schema_heads "$1"\n'
                result = subprocess.run(
                    ["bash", "-c", script, "restore-heads", heads],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertEqual(result.stdout.strip(), expected)

    def test_final_restore_validates_complete_canonical_migration_registries(self) -> None:
        rollback = ROLLBACK_RUNBOOK.read_text(encoding="utf-8")
        helper = re.search(r"(?ms)^assert_canonical_registry_rows\(\) \{\n.*?^\}", rollback)
        self.assertIsNotNone(helper)
        assert helper is not None
        self.assertIn('source "$MIGRATION_STATE_LIB"', rollback)
        self.assertIn('test "$SOURCE_PRODUCT_REGISTRY" = "$RESTORE_PRODUCT_REGISTRY"', rollback)
        self.assertIn('test "$SOURCE_CONTROL_REGISTRY" = "$RESTORE_CONTROL_REGISTRY"', rollback)
        product_validation = rollback.index('assert_canonical_registry_rows "$RESTORE_PRODUCT_REGISTRY"')
        control_validation = rollback.index('assert_canonical_registry_rows "$RESTORE_CONTROL_REGISTRY"')
        verified = rollback.index("RESTORE_SCHEMA_VERDICT=FINAL_SCHEMA_VERIFIED")
        self.assertLess(product_validation, verified)
        self.assertLess(control_validation, verified)
        for directory, head in (
            (REPO_ROOT / "services/rag-engine/infra/postgres/migrations", 5),
            (REPO_ROOT / "services/rag-engine/infra/postgres/ingestion_control/migrations", 20),
        ):
            rows = [
                f"{int(path.name[:3])}|{path.name}|{hashlib.sha256(path.read_bytes()).hexdigest()}"
                for path in sorted(directory.glob("*.sql"))
            ]
            valid = "\n".join(rows)
            cases = (
                (valid, True),
                ("\n".join(rows[:1] + rows[2:]), False),
                (valid.replace(rows[1], rows[1].replace(".sql", "_changed.sql")), False),
                (valid.replace(rows[1], rows[1][:-1] + ("0" if rows[1][-1] != "0" else "1")), False),
                (valid + "\n" + rows[-1], False),
            )
            for registry, accepted in cases:
                with self.subTest(directory=directory.name, accepted=accepted, rows=registry.count("\n")):
                    script = (
                        'set -euo pipefail\nsource "$1"\n'
                        + helper.group(0)
                        + '\nassert_canonical_registry_rows "$2" "$3" "$4"\n'
                    )
                    result = subprocess.run(
                        [
                            "bash", "-c", script, "registry-guard",
                            str(REPO_ROOT / "services/rag-engine/infra/scripts/lib/pgvector_migration_state.sh"),
                            registry, str(directory), str(head),
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode == 0, accepted, result.stderr)

    def test_restore_project_name_is_accepted_by_compose(self) -> None:
        rollback = ROLLBACK_RUNBOOK.read_text(encoding="utf-8")
        assignment = re.search(r'^RESTORE_PROJECT=".*"$', rollback, re.MULTILINE)
        self.assertIsNotNone(assignment)
        assert assignment is not None
        result = subprocess.run(
            ["bash", "-c", assignment.group(0) + '\nprintf "%s" "$RESTORE_PROJECT"\n'],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertRegex(result.stdout, r"^nexus-pg-restore-rehearsal-[a-z0-9-]+$")

    def test_restore_target_database_matches_compose_interpolation(self) -> None:
        rollback = ROLLBACK_RUNBOOK.read_text(encoding="utf-8")
        self.assertIn('PGVECTOR_DB="${PGVECTOR_DB:-ragdb}"', rollback)
        self.assertIn('PGVECTOR_USER="${PGVECTOR_USER:-raguser}"', rollback)
        self.assertIn("export PGVECTOR_DB PGVECTOR_USER", rollback)
        self.assertLess(
            rollback.index("export PGVECTOR_DB PGVECTOR_USER"),
            rollback.index('restore_compose=('),
        )

    def test_restore_guard_precedes_mutation_and_compares_generated_tsv(self) -> None:
        rollback = ROLLBACK_RUNBOOK.read_text(encoding="utf-8")
        self.assertIn('POSTGRES_INITDB_ARGS: "--locale=C --encoding=UTF8"', rollback)
        self.assertIn("pg_encoding_to_char(encoding)", rollback)
        self.assertIn("text_tsv::text", rollback)
        self.assertIn('test "$SOURCE_FINGERPRINT" = "$RESTORE_FINGERPRINT"', rollback)
        self.assertIn('assert_restore_compatible_identity "$SOURCE_DB_IDENTITY" "$RESTORE_DB_IDENTITY"', rollback)
        self.assertLess(
            rollback.index('assert_restore_compatible_identity "$SOURCE_DB_IDENTITY" "$RESTORE_DB_IDENTITY"'),
            rollback.index("--exit-on-error --clean --if-exists"),
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
        self.assertLess(
            rollback.index('if [[ "$RESTORE_SCHEMA_VERDICT" == FINAL_SCHEMA_CANDIDATE ]]; then'),
            reprovision,
        )
        self.assertLess(reprovision, rollback.index("\nelse\n  printf 'FINAL_SCHEMA_UNVERIFIED=true", reprovision))
        migrator = rollback.index("  restore-migrator:")
        migrator_environment = rollback[migrator : rollback.index("    networks:", migrator)]
        for variable in (
            "PGVECTOR_RETRIEVAL_USER",
            "PGVECTOR_RETRIEVAL_PASSWORD",
            "PGVECTOR_REVIEW_USER",
            "PGVECTOR_REVIEW_PASSWORD",
            "PGVECTOR_PUBLISHER_USER",
            "PGVECTOR_PUBLISHER_PASSWORD",
        ):
            with self.subTest(variable=variable):
                self.assertIn(variable, migrator_environment)


if __name__ == "__main__":
    unittest.main()
