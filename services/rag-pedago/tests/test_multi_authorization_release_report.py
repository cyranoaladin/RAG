from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import yaml
from nexus_contracts.ingestion import CollectionProfile, collection_profile_fingerprint

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
REPORT = REPO_ROOT / "docs/reports/lot_multi_authorization_release_v2_20260823.md"
GROUNDED_PROFILE_REPORT = (
    REPO_ROOT / "docs/reports/lot_grounded_production_profiles_20260824.md"
)
MASTER_JSON = REPO_ROOT / "docs/reports/master_go_live_state_20260815.json"
MASTER_MD = REPO_ROOT / "docs/reports/master_go_live_state_20260815.md"
CHECKLIST = REPO_ROOT / "docs/checklists/production_go_live_checklist.md"
ENVIRONMENT_PLAN = REPO_ROOT / "docs/reports/plan_production_github_environment.md"
FINAL_SET = REPO_ROOT / "docs/reports/final_authority_required_set_20260823.txt"
PROFILE_MATRIX = REPO_ROOT / "docs/reports/proposed_production_profile_matrix_20260823.json"
RECOMPUTATION_EVIDENCE = (
    REPO_ROOT / "docs/reports/final_release_recomputation_evidence_20260824.json"
)
GITHUB_ENVIRONMENT_EVIDENCE = (
    REPO_ROOT / "docs/reports/github_environment_read_only_observation_20260824.json"
)
SCOPE_AUDIT = REPO_ROOT / "docs/reports/tier_a_scope_profile_audit_clean_20260822.json"
SET_ALGEBRA = REPO_ROOT / "docs/reports/tier_a_set_algebra_reconciliation_20260822.json"
NETWORK_AUDIT = REPO_ROOT / "docs/reports/tier_a_byte_identity_network_audit_20260822.json"
CONTENT_LEDGER = REPO_ROOT / "docs/reports/evidence-index/content_ledger_20260814.jsonl"
PRODUCTION_PLACEMENT_POLICY = (
    REPO_ROOT / "services/rag-engine/configs/h2_initial_placement_policy.yml"
)
PRODUCTION_PROFILE = (
    REPO_ROOT
    / "services/rag-engine/configs/ingestion_profiles/philosophie_terminale_tc_h2c_v1.yml"
)
PRODUCTION_PROFILE_MANIFEST = (
    REPO_ROOT / "services/rag-engine/configs/ingestion_manifest.yml"
)

PR127_BASE_SHA = "3548bf300c99685ff6ede0dce2e5bfe8c044d213"
BASE_SHA = "8aa65fb3fb5f077bcd6dfa427c8902bd6d5c28b0"
FINAL_SET_SHA256 = "3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0"
PROFILE_MATRIX_SHA256 = "b1fb997b56f080101493ac1efb151fc228109e110a9d8d86ce74f730eff544fe"
PR129_PROFILE_MATRIX_SHA256 = (
    "8009596c0cce54f816a1a1307a9ba5663146cfa2d7d95e381e84819d3be9c963"
)
PRODUCTION_PROFILE_FINGERPRINT = (
    "993b350071ffa961c2be47738aa138b95db56317f117d7b4086461dbfd0acefc"
)
HEX64 = re.compile(r"[0-9a-f]{64}")


def _master() -> dict[str, object]:
    return json.loads(MASTER_JSON.read_text(encoding="utf-8"))


def test_final_authority_set_is_exact_canonical_artifact() -> None:
    payload = FINAL_SET.read_bytes()
    lines = payload.splitlines()

    assert payload.endswith(b"\n")
    assert payload == b"".join(line + b"\n" for line in lines)
    assert len(lines) == 72
    assert lines == sorted(lines)
    assert len(set(lines)) == 72
    assert all(HEX64.fullmatch(line.decode("ascii")) for line in lines)
    assert hashlib.sha256(payload).hexdigest() == FINAL_SET_SHA256


def test_master_freezes_recomputed_release_algebra_and_terminal_accounting() -> None:
    master = _master()
    corpus = master["corpus_eligibility"]
    terminal = master["terminal_disposition_20260823"]

    assert master["state_observed_at_main_sha"] == BASE_SHA
    assert master["pr_merges"]["PR127_MERGED"] is True
    assert master["pr_merges"]["PR129_MERGED"] is True
    assert master["multi_authorization_protocol_20260823"]["V2_MECHANISM_ON_MAIN"] is True
    assert corpus == {
        "PHYSICAL_FILES": 2584,
        "MANIFEST_ENTRIES": 2583,
        "UNIQUE_CONTENT_SHA256": 2582,
        "DUPLICATE_CONTENT_GROUPS": 1,
        "FINAL_BASE_INGEST_CANDIDATES": 73,
        "FINAL_NON_AUTHORITY_BLOCKED_COUNT": 1,
        "FINAL_AUTHORITY_REQUIRED_COUNT": 72,
        "FINAL_AUTHORITY_REQUIRED_SET_SHA256": FINAL_SET_SHA256,
        "FINAL_RELEASE_ELIGIBLE_ARTIFACTS": 72,
        "FINAL_ELIGIBLE_SET_FROZEN": True,
        "RECOMPUTATION_EVIDENCE_PATH": (
            "docs/reports/final_release_recomputation_evidence_20260824.json"
        ),
        "RECOMPUTATION_EVIDENCE_SHA256": (
            "f68f5c525c7bd9280e03a1bbc5fd4a434de1b1d64e8a0a4eff8e32a3caa4f47d"
        ),
        "AUTHORIZED_ELIGIBLE_ARTIFACTS": 0,
        "INGESTED_ELIGIBLE_ARTIFACTS": 0,
        "API_DISCOVERABLE_ELIGIBLE_ARTIFACTS": 0,
    }
    assert terminal == {
        "UNIQUE_CONTENTS": 2582,
        "INGEST_CANDIDATE": 72,
        "REVIEW_REQUIRED": 2399,
        "QUARANTINE": 2,
        "ARCHIVE_ONLY": 19,
        "EXCLUDE": 53,
        "UNSUPPORTED": 37,
        "UNACCOUNTED_CONTENTS": 0,
        "TERMINAL_DISPOSITION_COVERAGE": 100.0,
    }


def test_hermetic_evidence_independently_derives_release_set_and_dispositions() -> None:
    final_set = set(FINAL_SET.read_text(encoding="ascii").splitlines())
    scope_audit = json.loads(SCOPE_AUDIT.read_text(encoding="utf-8"))
    set_algebra = json.loads(SET_ALGEBRA.read_text(encoding="utf-8"))
    network_audit = json.loads(NETWORK_AUDIT.read_text(encoding="utf-8"))
    ledger_rows = [
        json.loads(line) for line in CONTENT_LEDGER.read_text(encoding="utf-8").splitlines()
    ]
    ledger = {row["content_sha256"]: row for row in ledger_rows}

    scope_set = {row["content_sha256"] for row in scope_audit["results"]}
    assert scope_set == final_set
    assert scope_audit["authority_required_set_sha256"] == FINAL_SET_SHA256

    baseline = set_algebra["h2_baseline_reproduction"]
    assert baseline["blocked_ingest_candidates"] == 73
    assert baseline["pii_blocked_count"] == 1
    assert baseline["authority_required_count"] == 72
    assert baseline["authority_required_set_sha256"] == FINAL_SET_SHA256

    assert len(ledger_rows) == len(ledger) == 2582
    dispositions = Counter(
        "INGEST_CANDIDATE" if sha256 in final_set else row["FINAL_DISPOSITION"]
        for sha256, row in ledger.items()
    )
    assert dispositions == {
        "ARCHIVE_ONLY": 19,
        "EXCLUDE": 53,
        "INGEST_CANDIDATE": 72,
        "QUARANTINE": 2,
        "REVIEW_REQUIRED": 2399,
        "UNSUPPORTED": 37,
    }

    cloudflare = network_audit["results"]
    cloudflare_set = {row["content_sha256"] for row in cloudflare}
    assert len(cloudflare) == len(cloudflare_set) == 138
    assert cloudflare_set.isdisjoint(final_set)
    assert {row["decision"] for row in cloudflare} == {"SOURCE_UNAVAILABLE"}
    assert {row["http_status"] for row in cloudflare} == {403}
    assert {ledger[sha256]["FINAL_DISPOSITION"] for sha256 in cloudflare_set} == {
        "REVIEW_REQUIRED"
    }


def test_recomputation_evidence_records_actual_non_skipped_producer_run() -> None:
    evidence_bytes = RECOMPUTATION_EVIDENCE.read_bytes()
    evidence = json.loads(evidence_bytes)

    assert hashlib.sha256(evidence_bytes).hexdigest() == _master()["corpus_eligibility"][
        "RECOMPUTATION_EVIDENCE_SHA256"
    ]
    assert evidence["protocol_version"] == "NEXUS-FINAL-RELEASE-RECOMPUTATION-EVIDENCE-V1"
    assert evidence["baseline_main_sha"] == PR127_BASE_SHA
    assert evidence["producer"] == "services/rag-pedago/scripts/recompute_final_release_set.py"
    assert evidence["producer_exit_code"] == 0
    assert evidence["committed_set_byte_identity"] is True
    assert evidence["input_digests"] == {
        "sealed_manifest": "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e",
        "placements": "25cf40cec8a98692d4532a71b58a9685821bbc2b9a4785c25fac7138a49906ec",
        "pii_exhaustive": "0229a0f2d7edbd1bb1b1412a8ccd447b3c6d2ce71dc73a0f2e726751156fa357",
        "pii_campaign": "76e6ba3cd5b1c116c8647b611eb3fdeb2aba6b8c7fdfbad9e71048354956f311",
        "routing": "0d4d25215cb0ed40c439ff172c9dbce3f2a1b0b945313a042285b2e57bffc833",
        "rights": "e3c9a157f1f78171c0052750fa08b7726b99ea4dd348728f1b90db07f93ef1ff",
        "golden": "28856e0655eca7695f273a5934925785c49ecf828d930804984f6e58f4da6f69",
        "currentness": "2ad7209f28cd7cbf9f1ea91724b687983579c36c91619e8d107d28b72b849122",
    }
    assert evidence["output_digests"] == {
        "generated_summary": "ff0d8a156e82717fdea3b18b9c26083b6c96361c680301bcaca8036e6034b4b5",
        "final_authority_required_set": FINAL_SET_SHA256,
        "terminal_content_dispositions": (
            "127231629e94260170c69c841b29278bf4b74b56a276097e885c574853464a10"
        ),
    }
    assert evidence["result"]["release_terminal_disposition_counts"] == {
        "ARCHIVE_ONLY": 19,
        "EXCLUDE": 53,
        "INGEST_CANDIDATE": 72,
        "QUARANTINE": 2,
        "REVIEW_REQUIRED": 2399,
        "UNSUPPORTED": 37,
    }
    assert b"/tmp/" not in evidence_bytes
    assert b"/home/" not in evidence_bytes


def test_master_records_closed_cloudflare_work_and_unresolved_profile_decisions() -> None:
    master = _master()
    cloudflare = master["cloudflare_release_decision_20260823"]
    profiles = master["production_profile_proposal_20260823"]

    assert cloudflare == {
        "CLOUDFLARE_OPERATOR_DECISION": "ACCEPT_REVIEW_REQUIRED_FOR_THIS_RELEASE",
        "INVESTIGATED_CONTENT_COUNT": 138,
        "TERMINAL_DISPOSITION": "REVIEW_REQUIRED",
        "NETWORK_WORK_CLOSED_FOR_RELEASE": True,
        "CLOUDFLARE_BLOCKS_GO_LIVE": False,
    }
    assert profiles == {
        "MATRIX_PATH": "docs/reports/proposed_production_profile_matrix_20260823.json",
        "MATRIX_SHA256": PROFILE_MATRIX_SHA256,
        "PARTITION_COUNT": 24,
        "DISTINCT_LEVEL_SUBJECT_PAIRS_MINIMUM": 22,
        "MATRIX_RAW_DISTINCT_LEVEL_SUBJECT_PAIRS": 23,
        "MATRIX_FULLY_SPECIFIED_LEVEL_SUBJECT_PAIRS": 21,
        "GROUNDED_PARTITION_COUNT": 11,
        "GROUNDED_CONTENT_COUNT": 16,
        "STAGING_NON_PRODUCTION_PARTITION_COUNT": 10,
        "STAGING_NON_PRODUCTION_CONTENT_COUNT": 11,
        "DECISION_REQUIRED_PARTITION_COUNT": 13,
        "DECISION_REQUIRED_CONTENT_COUNT": 56,
        "PROFILE_EXACT_MATCH_COUNT": 5,
        "PROFILE_NO_MATCH_COUNT": 67,
        "PROFILE_AMBIGUOUS_COUNT": 0,
        "GROUNDED_DISTINCT_CANONICAL_RESOURCE_SCOPES": 1,
        "DISTINCT_CANONICAL_RESOURCE_SCOPES": "UNKNOWN_PENDING_PROFILE_DECISIONS",
        "PROFILE_MAPPED_COUNT": 0,
        "P24_RELEASE_REGISTRY_MAPPING_READY": False,
        "PROFILE_DECISION_REQUIRED": True,
        "FABRICATED_PROFILE_COUNT": 0,
    }
    matrix_bytes = PROFILE_MATRIX.read_bytes()
    matrix = json.loads(matrix_bytes)
    assert hashlib.sha256(matrix_bytes).hexdigest() == PROFILE_MATRIX_SHA256
    assert len(matrix) == 24
    assert sum(row["content_count"] for row in matrix) == 72
    assert {sha for row in matrix for sha in row["content_sha256"]} == set(
        FINAL_SET.read_text(encoding="ascii").splitlines()
    )
    assert sum(not row["profile_decision_required"] for row in matrix) == 11
    assert sum(
        row["content_count"] for row in matrix if not row["profile_decision_required"]
    ) == 16
    assert sum(row["profile_decision_required"] for row in matrix) == 13
    assert sum(row["content_count"] for row in matrix if row["profile_decision_required"]) == 56
    raw_pairs = {
        (row["dimensions"]["niveau"]["value"], row["dimensions"]["matiere"]["value"])
        for row in matrix
    }
    assert len(raw_pairs) == 23
    assert sum(None not in pair for pair in raw_pairs) == 21


def test_p24_is_bound_to_the_exact_production_profile_and_staging_is_not_production() -> None:
    matrix = json.loads(PROFILE_MATRIX.read_text(encoding="utf-8"))
    p24 = next(row for row in matrix if row["partition_id"] == "P24")
    policy = yaml.safe_load(PRODUCTION_PLACEMENT_POLICY.read_text(encoding="utf-8"))
    profile = CollectionProfile.model_validate(
        yaml.safe_load(PRODUCTION_PROFILE.read_text(encoding="utf-8"))
    )
    manifest = yaml.safe_load(PRODUCTION_PROFILE_MANIFEST.read_text(encoding="utf-8"))
    profile_path = PRODUCTION_PROFILE.relative_to(REPO_ROOT).as_posix()
    policy_path = PRODUCTION_PLACEMENT_POLICY.relative_to(REPO_ROOT).as_posix()
    manifest_path = PRODUCTION_PROFILE_MANIFEST.relative_to(REPO_ROOT).as_posix()

    assert p24["content_sha256"] == sorted(policy["approved_artifacts"])
    assert len(p24["content_sha256"]) == 5
    assert {
        rule["collection"] for rule in policy["approved_artifacts"].values()
    } == {profile.scope.collection}
    assert p24["partition_kind"] == "EXACT_VERSIONED_RELEASE_PROFILE"
    assert p24["profile_decision_required"] is False
    assert p24["evidence_sources"] == [policy_path, profile_path, manifest_path]
    assert all(
        dimension == {
            "grounded": True,
            "source_of_truth": profile_path,
            "value": profile.scope.model_dump(mode="json")[name],
        }
        for name, dimension in p24["dimensions"].items()
    )

    fingerprint = collection_profile_fingerprint(profile)
    assert fingerprint == PRODUCTION_PROFILE_FINGERPRINT
    assert manifest["profiles"] == [
        {
            "collection": profile.scope.collection,
            "profile_version": profile.profile_version,
            "fingerprint": fingerprint,
            "approved_by": "Nexus Réussite",
            "approved_at": "2026-08-09T00:00:00+01:00",
        }
    ]

    staging = [
        row
        for row in matrix
        if any("/ingestion_profiles/staging/" in source for source in row["evidence_sources"])
    ]
    production = [
        row
        for row in matrix
        if PRODUCTION_PROFILE.relative_to(REPO_ROOT).as_posix() in row["evidence_sources"]
    ]
    assert len(staging) == 10
    assert sum(row["content_count"] for row in staging) == 11
    assert all(row["partition_id"] != "P24" for row in staging)
    assert [row["partition_id"] for row in production] == ["P24"]
    assert sum(row["content_count"] for row in production) == 5
    assert 72 - sum(row["content_count"] for row in production) == 67


def test_grounded_production_profile_report_records_only_proven_p24_promotion() -> None:
    report = GROUNDED_PROFILE_REPORT.read_text(encoding="utf-8")

    for fragment in (
        "BASE_SHA=8aa65fb3fb5f077bcd6dfa427c8902bd6d5c28b0",
        "PRODUCTION_PROFILE_EXACT_MATCH_COUNT=5",
        "PROFILE_NO_MATCH_COUNT=67",
        "DECISION_REQUIRED_PARTITION_COUNT=13",
        "DECISION_REQUIRED_CONTENT_COUNT=56",
        "STAGING_NON_PRODUCTION_PARTITION_COUNT=10",
        "STAGING_NON_PRODUCTION_CONTENT_COUNT=11",
        PRODUCTION_PROFILE_FINGERPRINT,
        "services/rag-engine/configs/h2_initial_placement_policy.yml",
        "services/rag-engine/configs/ingestion_profiles/philosophie_terminale_tc_h2c_v1.yml",
        "services/rag-engine/configs/ingestion_manifest.yml",
        "P01-P10_NOT_PROMOTED=true",
        "P24_RELEASE_REGISTRY_MAPPING_READY=false",
        "PROFILE_MAPPED_COUNT=0",
        "PRODUCTION_READY=false",
        "GO_LIVE_READY=false",
        "RAG_PRODUCTION_DEPLOYED=false",
    ):
        assert fragment in report
    assert "PRODUCTION_PROFILE_EXACT_MATCH_COUNT=16" not in report


def test_current_master_and_checklist_do_not_claim_final_scope_count() -> None:
    master = _master()
    profile_state = master["production_profile_proposal_20260823"]
    master_md = MASTER_MD.read_text(encoding="utf-8")
    checklist = CHECKLIST.read_text(encoding="utf-8")

    assert profile_state["GROUNDED_DISTINCT_CANONICAL_RESOURCE_SCOPES"] == 1
    assert (
        profile_state["DISTINCT_CANONICAL_RESOURCE_SCOPES"]
        == "UNKNOWN_PENDING_PROFILE_DECISIONS"
    )
    assert "GROUNDED_DISTINCT_CANONICAL_RESOURCE_SCOPES=1" in master_md
    assert "DISTINCT_CANONICAL_RESOURCE_SCOPES=UNKNOWN_PENDING_PROFILE_DECISIONS" in master_md
    assert "PR129_MERGED=true" in master_md
    assert "61 contenus encore non ancrés" not in checklist
    assert "56 contenus encore non ancrés" in checklist


def test_master_marks_unversioned_parallel_observations_unknown() -> None:
    master = _master()

    assert master["docker_rehearsal_20260823"] == {
        "DOCKER_REHEARSAL_EVIDENCE_STATUS": "UNVERIFIED_TRANSCRIPT_NOT_VERSIONED",
        "ATOMIC_DOCKER_REHEARSAL_PASS": None,
        "FOREIGN_SERVICES_TOUCHED": None,
        "ROLLBACK_REHEARSAL_PASS": None,
        "BAD_DIGEST_REFUSED": None,
        "BAD_READINESS_REFUSED": None,
        "EXACT_TECHNICAL_BLOCKER": "UNKNOWN_TRANSCRIPT_UNAVAILABLE",
        "TECHNICAL_FIX_REQUIRES_SEPARATE_PR": None,
        "HISTORICAL_OPERATOR_OBSERVATION_UNVERIFIED": {
            "ATOMIC_DOCKER_REHEARSAL_PASS": False,
            "FOREIGN_SERVICES_TOUCHED": 0,
            "ROLLBACK_REHEARSAL_PASS": False,
            "BAD_DIGEST_REFUSED": True,
            "BAD_READINESS_REFUSED": True,
            "TECHNICAL_FIX_REQUIRES_SEPARATE_PR": True,
        },
    }
    assert master["production_database_read_only_audit_20260823"] == {
        "DB_AUDIT_EVIDENCE_STATUS": "UNVERIFIED_TRANSCRIPT_NOT_VERSIONED",
        "AUDIT_ATTEMPTED": None,
        "BLOCKER": None,
        "LOCAL_DEVELOPMENT_DATABASE_TREATED_AS_PRODUCTION": False,
        "PROD_DB_TARGET_VERIFIED": None,
        "PROD_DB_MIGRATION_PLAN_READY": None,
        "PROD_DB_WRITES": None,
        "HISTORICAL_OPERATOR_OBSERVATION_UNVERIFIED": {
            "AUDIT_ATTEMPTED": True,
            "BLOCKER": "SSH_UNKNOWN_HOST_KEY",
            "PROD_DB_TARGET_VERIFIED": False,
            "PROD_DB_MIGRATION_PLAN_READY": False,
            "PROD_DB_WRITES": 0,
        },
    }
    assert master["production_github_environment"] == {
        "PRODUCTION_ENVIRONMENT_EXISTS": False,
        "PRODUCTION_ENVIRONMENT_PROVISIONED": False,
        "REQUIRED_REVIEWER": "abenrhouma",
        "REQUIRED_REVIEWER_USER_ID": 67140603,
        "MAIN_ONLY": True,
        "PREVENT_SELF_REVIEW": True,
        "ADMIN_BYPASS": False,
        "WAIT_TIMER_MINUTES": 0,
        "SECRETS": 0,
        "HUMAN_ADMIN_ACTION_REQUIRED": True,
        "READ_ONLY_EVIDENCE_PATH": (
            "docs/reports/github_environment_read_only_observation_20260824.json"
        ),
        "READ_ONLY_EVIDENCE_SHA256": (
            "8880808bf1b46032e69141793d34815f4db836692a2e3f44d8f280db9f020d8a"
        ),
    }
    assert master["release_status"] == {
        "PRODUCTION_READY": False,
        "GO_LIVE_READY": False,
        "RAG_PRODUCTION_DEPLOYED": False,
        "DRIVE_MIRROR_COMPLETE": True,
    }


def test_github_environment_observation_is_sanitized_and_state_timestamp_is_real() -> None:
    evidence_bytes = GITHUB_ENVIRONMENT_EVIDENCE.read_bytes()
    evidence = json.loads(evidence_bytes)
    master = _master()

    assert hashlib.sha256(evidence_bytes).hexdigest() == master[
        "production_github_environment"
    ]["READ_ONLY_EVIDENCE_SHA256"]
    assert evidence["read_only"] is True
    assert evidence["repository"] == "cyranoaladin/RAG"
    assert evidence["environment_query_result"] == {"total_count": 0, "names": []}
    assert evidence["reviewer_query_result"] == {
        "login": "abenrhouma",
        "user_id": 67140603,
        "permission": "write",
    }
    assert b"token" not in evidence_bytes.lower()
    assert b"authorization:" not in evidence_bytes.lower()
    generated_at = datetime.fromisoformat(master["state_generated_at"].replace("Z", "+00:00"))
    github_observed_at = datetime.fromisoformat(evidence["observed_at"].replace("Z", "+00:00"))
    recompute_observed_at = datetime.fromisoformat(
        json.loads(RECOMPUTATION_EVIDENCE.read_text(encoding="utf-8"))["observed_at"].replace(
            "Z", "+00:00"
        )
    )
    assert generated_at.tzinfo is not None
    assert generated_at >= github_observed_at
    assert generated_at >= recompute_observed_at
    assert generated_at <= datetime.now(UTC)


def test_master_replaces_narrow_audit_with_v2_architecture_without_mutating_v1() -> None:
    master = _master()
    multi_auth = master["multi_authorization_protocol_20260823"]

    assert multi_auth["AUDIT_SURFACE_COUNT"] == 45
    assert multi_auth["OLD_NARROW_CONCLUSION_SUPERSEDED"] is True
    assert multi_auth["ADR"] == "ADR-0044"
    assert multi_auth["CONTRACT_VERSION"] == "0.13.0"
    assert multi_auth["AUTHORIZATION_SET_PROTOCOL"] == "NEXUS-AUTHORIZATION-SET-V1"
    assert multi_auth["V1_LEGACY_READABLE_AND_UNCHANGED"] is True
    assert multi_auth["V2_MECHANISM_ON_MAIN"] is True
    assert multi_auth["REAL_AUTHORIZATION_SET_CREATED"] is False
    assert multi_auth["REAL_H2_GATE_PASS"] is False
    assert master["quarantine_20260822"]["ADR0043_STATUS"] == (
        "UNREVIEWED_WIP/NON_AUTHORITATIVE/NOT_REUSED"
    )


def test_report_cites_reproducible_recomputation_inputs_commands_and_commits() -> None:
    report = REPORT.read_text(encoding="utf-8")
    required_fragments = (
        PR127_BASE_SHA,
        "services/rag-pedago/scripts/recompute_final_release_set.py",
        "NEXUS_SEALED_CORPUS_ROOT",
        "NEXUS_H2_EVIDENCE_ROOT",
        "cmp --silent",
        "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e",
        "25cf40cec8a98692d4532a71b58a9685821bbc2b9a4785c25fac7138a49906ec",
        "0229a0f2d7edbd1bb1b1412a8ccd447b3c6d2ce71dc73a0f2e726751156fa357",
        "76e6ba3cd5b1c116c8647b611eb3fdeb2aba6b8c7fdfbad9e71048354956f311",
        "0d4d25215cb0ed40c439ff172c9dbce3f2a1b0b945313a042285b2e57bffc833",
        "e3c9a157f1f78171c0052750fa08b7726b99ea4dd348728f1b90db07f93ef1ff",
        "28856e0655eca7695f273a5934925785c49ecf828d930804984f6e58f4da6f69",
        "2ad7209f28cd7cbf9f1ea91724b687983579c36c91619e8d107d28b72b849122",
        FINAL_SET_SHA256,
        PR129_PROFILE_MATRIX_SHA256,
        "ADR-0044",
        "CONTRACT_VERSION=0.13.0",
        "CI_GREEN=false",
        "MAKE_INTERPRETER_PYYAML_ENV_FAILURE",
        "KNOWN_UNTOUCHED_MYPY_ERRORS",
    )
    for fragment in required_fragments:
        assert fragment in report

    expected_commits = {
        "7f0fbb4c0b2151034a48c0921a9f867a11d4fa57",
        "73890c7777d9c59a3747787bc50be88c4fd46c7e",
        "e165eb5c78bd4bbf9648a7d55905123f37f0142d",
        "268e9dfd964c229fc76c1f69f428a81063acfe28",
        "54a0507533f8dc2b171bc0f52855655c79f77b66",
        "ea80579236d235b7d4c8f19b16c4430cb3ef0cb0",
        "c44c53ee300b99cae3e38e998dc599e00e79cd99",
        "d14e1e03c5bdb2b12c2dcb3b4016fb17f6043583",
        "37aa68ca51e52a9c1a96a72a97b5673c4f20e770",
        "7ec6132dc9c2196889b55bef71faa6f1ea590f7d",
    }
    for commit in expected_commits:
        assert commit in report


def test_human_gate_documents_are_exact_and_do_not_mark_real_execution_done() -> None:
    master_md = MASTER_MD.read_text(encoding="utf-8")
    checklist = CHECKLIST.read_text(encoding="utf-8")
    environment_plan = ENVIRONMENT_PLAN.read_text(encoding="utf-8")

    for token in (
        "FINAL_RELEASE_ELIGIBLE_ARTIFACTS=72",
        "FINAL_ELIGIBLE_SET_FROZEN=true",
        "UNACCOUNTED_CONTENTS=0",
        "TERMINAL_DISPOSITION_COVERAGE=100%",
        "PROFILE_DECISION_REQUIRED=true",
        "PRODUCTION_READY=false",
        "GO_LIVE_READY=false",
        "RAG_PRODUCTION_DEPLOYED=false",
    ):
        assert token in master_md

    for pending in (
        "REAL_AUTHORIZATIONS_CREATED=false",
        "REAL_CAMPAIGN_EXECUTED=false",
        "REAL_GOVERNED_REPUBLISH_EXECUTED=false",
        "REAL_H2_GATE_PASS=false",
        "PRODUCTION_ENVIRONMENT_PROVISIONED=false",
        "PROD_DB_TARGET_VERIFIED=UNKNOWN",
        "ATOMIC_DOCKER_REHEARSAL_PASS=UNKNOWN",
    ):
        assert pending in checklist

    for exact_gate in (
        "REQUIRED_REVIEWER=abenrhouma",
        "REQUIRED_REVIEWER_USER_ID=67140603",
        "DEPLOYMENT_BRANCH_POLICY=main-only",
        "PREVENT_SELF_REVIEW=true",
        "ADMIN_BYPASS=false",
        "WAIT_TIMER_MINUTES=0",
        "ENVIRONMENT_SECRETS=0",
        "PRODUCTION_GITHUB_ENVIRONMENT_PROVISIONED=false",
    ):
        assert exact_gate in environment_plan
