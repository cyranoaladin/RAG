"""LOT42 (ADR-0033) : falsification, révocation, replay, dérive de contenu/
profil/manifest, scope — PostgreSQL réel + frontière GitHub réelle (fake
``gh`` déterministe, cf. ``_fake_github.py`` — même discipline que
``test_lot41a_scope_authority.py``).

Preuve centrale : une attestation par ailleurs intacte (non invalidée,
scope toujours valide) devient invalide dès que le contenu/profil/manifest
courant diverge de ce qui a été attesté, ou que le scope LOT41A référencé
ou la revue humaine finale ne revérifient plus en direct — jamais un
oubli, jamais un simple drapeau stocké et jamais relu.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[2]
INFRA_ROOT = ENGINE_ROOT / "infra"
BOOTSTRAP_SCRIPT = INFRA_ROOT / "scripts" / "bootstrap_ingestion_control_schema.sh"
PROVISION_SCRIPT = INFRA_ROOT / "scripts" / "provision_ingestion_control_roles.sh"

sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _fake_github import (  # noqa: E402
    REPOSITORY,
    approved_pull_request,
    approved_review,
    fake_gh_bin_dir,
    write_scenario,
)
from nexus_contracts.ingestion import ResourceScope  # noqa: E402

from ingestor.ingestion_control.provisioning import create_resource  # noqa: E402
from ingestor.ingestion_control.publication_attestation import (  # noqa: E402
    PublicationAttestationInvalidError,
    attempt_retrieval_eligible_transition,
    verify_publication_attestation,
)
from ingestor.ingestion_worker.attest_publication_cli import (  # noqa: E402
    main as attest_publication_main,
)
from ingestor.ingestion_worker.authorize_scope_cli import main as authorize_scope_main  # noqa: E402

PG_IMAGE = "pgvector/pgvector:pg16"
PG_SUPERUSER = "raguser"
PG_SUPERUSER_PASSWORD = secrets.token_urlsafe(24)
PG_DB = "ragdb"
APP_PASSWORD = secrets.token_urlsafe(24)
MIGRATOR_PASSWORD = secrets.token_urlsafe(24)
AUTHORITY_PASSWORD = secrets.token_urlsafe(24)
ATTESTOR_PASSWORD = secrets.token_urlsafe(24)

_DOCKER_AVAILABLE = shutil.which("docker") is not None and (
    subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DOCKER_AVAILABLE, reason="Docker not available"),
]

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


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_pg_isready(port: int, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["pg_isready", "-h", "127.0.0.1", "-p", str(port), "-U", PG_SUPERUSER],
            capture_output=True, check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise TimeoutError(f"Postgres not ready on port {port} after {timeout_s}s")


@pytest.fixture(scope="module")
def pg_container() -> Iterator[dict[str, str]]:
    container_name = f"nexus-lot42-{uuid.uuid4().hex[:10]}"
    port = _free_port()
    subprocess.run(
        [
            "docker", "run", "-d", "--rm",
            "--name", container_name,
            "-e", f"POSTGRES_USER={PG_SUPERUSER}",
            "-e", f"POSTGRES_PASSWORD={PG_SUPERUSER_PASSWORD}",
            "-e", f"POSTGRES_DB={PG_DB}",
            "-p", f"{port}:5432",
            PG_IMAGE,
        ],
        check=True, capture_output=True,
    )
    try:
        _wait_pg_isready(port)
        env = {
            "PATH": os.environ["PATH"],
            "PGHOST": "127.0.0.1", "PGPORT": str(port), "PGUSER": PG_SUPERUSER,
            "PGPASSWORD": PG_SUPERUSER_PASSWORD, "PGDATABASE": PG_DB,
        }
        bootstrap = subprocess.run(
            [str(BOOTSTRAP_SCRIPT)], cwd=ENGINE_ROOT, env=env,
            capture_output=True, text=True, check=False,
        )
        assert bootstrap.returncode == 0, bootstrap.stderr
        assert "BOOTSTRAP_COMPLETE" in bootstrap.stdout

        provision_env = dict(env)
        provision_env.update({
            "INGESTION_CONTROL_MIGRATOR_PASSWORD": MIGRATOR_PASSWORD,
            "INGESTION_CONTROL_APP_PASSWORD": APP_PASSWORD,
            "INGESTION_CONTROL_AUTHORITY_PASSWORD": AUTHORITY_PASSWORD,
            "INGESTION_CONTROL_ATTESTOR_PASSWORD": ATTESTOR_PASSWORD,
        })
        provision = subprocess.run(
            [str(PROVISION_SCRIPT)], cwd=ENGINE_ROOT, env=provision_env,
            capture_output=True, text=True, check=False,
        )
        assert provision.returncode == 0, provision.stderr
        assert "ROLES_PROVISIONED=1" in provision.stdout

        yield {"host": "127.0.0.1", "port": str(port), "dbname": PG_DB}
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)


def _superuser_dsn(pg_container: dict[str, str]) -> str:
    return (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
    )


def _authority_dsn(pg_container: dict[str, str]) -> str:
    return (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user=ingestion_control_authority "
        f"password={AUTHORITY_PASSWORD}"
    )


def _attestor_dsn(pg_container: dict[str, str]) -> str:
    return (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user=ingestion_control_attestor "
        f"password={ATTESTOR_PASSWORD}"
    )


@pytest.fixture(autouse=True)
def _clean_tables(pg_container: dict[str, str]) -> Iterator[None]:
    with psycopg.connect(_superuser_dsn(pg_container)) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ingestion_control.publication_attestations")
            cur.execute("DELETE FROM ingestion_control.artifacts")
            cur.execute("DELETE FROM ingestion_control.resource_candidates")
            cur.execute("DELETE FROM ingestion_control.resources")
            cur.execute("DELETE FROM ingestion_control.scope_authorizations")
            cur.execute("DELETE FROM ingestion_control.jobs")
            cur.execute("DELETE FROM ingestion_control.ingestion_runs")
        conn.commit()
    yield


@pytest.fixture
def gh_scenario_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = fake_gh_bin_dir(tmp_path)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return bin_dir


def _digest(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _record_scope_authorization(
    *, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path,
    authorization_id: str, pull_request: int, manifest_digest: str,
) -> None:
    head_sha = secrets.token_hex(20)
    base_sha = secrets.token_hex(20)
    pr = approved_pull_request(number=pull_request, head_sha=head_sha, base_sha=base_sha)
    review = approved_review(review_id=pull_request * 10 + 1, pull_request=pr)
    write_scenario(gh_scenario_dir, pull_request=pr, reviews=[review])

    payload = {
        "scope": VALID_SCOPE,
        "manifest_digest": manifest_digest,
        "profile_id": "nsi_terminale_v1",
        "profile_version": "v1",
        "profile_fingerprint": _digest("profile"),
        "allowed_domains": ["eduscol.education.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "pii_absence_attested": True,
        "pii_absence_evidence": "audit manuel 2026-08-07",
        "valid_from": datetime.now(UTC).isoformat(),
        "valid_until": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
    }
    scope_file = tmp_path / f"scope-{pull_request}.yml"
    scope_file.write_text(yaml.safe_dump(payload), encoding="utf-8")

    os.environ["PG_INGESTION_CONTROL_DSN"] = _authority_dsn(pg_container)
    rc = authorize_scope_main([
        "record-authorization",
        "--authorization-id", authorization_id,
        "--scope-file", str(scope_file),
        "--repository", REPOSITORY,
        "--pull-request", str(pull_request),
        "--expected-head", head_sha,
    ])
    assert rc == 0, f"record-authorization failed for {authorization_id}"


def _create_resource_and_artifact(
    pg_container: dict[str, str], *, content_sha256: str, canonical_url: str = "https://eduscol.education.fr/x",
) -> tuple[UUID, UUID]:
    with psycopg.connect(_superuser_dsn(pg_container)) as conn:
        scope = ResourceScope.model_validate(VALID_SCOPE)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_control.ingestion_runs
                    (run_id, tenant, collection, niveau, voie, matiere, candidat,
                     audience, visibility, school_year, programme_version,
                     profile_version, trigger)
                VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'manual')
                RETURNING run_id
                """,
                (
                    scope.tenant, scope.collection, scope.niveau, scope.voie, scope.matiere,
                    scope.candidat, list(scope.audience), scope.visibility, scope.school_year,
                    scope.programme_version, "v1",
                ),
            )
            (run_id,) = cur.fetchone()
        resource_id = create_resource(
            conn, run_id=run_id, dedup_key=_digest(canonical_url), scope=scope
        )
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_control.resource_candidates
                    (candidate_id, resource_id, run_id, dedup_key, source_url,
                     canonical_url, domain, proposed_type_doc)
                VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s, 'cours')
                """,
                (resource_id, run_id, _digest(canonical_url), canonical_url, canonical_url, "eduscol.education.fr"),
            )
            cur.execute(
                """
                INSERT INTO ingestion_control.artifacts
                    (artifact_id, resource_id, run_id, sha256, size_bytes,
                     mime_declared, mime_detected, original_url, final_url)
                VALUES (gen_random_uuid(), %s, %s, %s, 100, 'text/html', 'text/html', %s, %s)
                RETURNING artifact_id
                """,
                (resource_id, run_id, content_sha256, canonical_url, canonical_url),
            )
            (artifact_id,) = cur.fetchone()
        conn.commit()
    return resource_id, artifact_id


def _record_attestation(
    *, pg_container: dict[str, str], gh_scenario_dir: Path,
    resource_id: UUID, artifact_id: UUID, scope_authorization_id: str,
    profile_fingerprint: str, manifest_digest: str, pull_request: int,
) -> None:
    head_sha = secrets.token_hex(20)
    pr = approved_pull_request(number=pull_request, head_sha=head_sha, base_sha=secrets.token_hex(20))
    review = approved_review(review_id=pull_request * 10 + 2, pull_request=pr)
    write_scenario(gh_scenario_dir, pull_request=pr, reviews=[review])

    os.environ["PG_INGESTION_CONTROL_DSN"] = _attestor_dsn(pg_container)
    rc = attest_publication_main([
        "record-attestation",
        "--resource-id", str(resource_id),
        "--artifact-id", str(artifact_id),
        "--scope-authorization-id", scope_authorization_id,
        "--profile-id", "nsi_terminale_v1",
        "--profile-version", "v1",
        "--profile-fingerprint", profile_fingerprint,
        "--manifest-digest", manifest_digest,
        "--rights-status", "officiel_public",
        "--rights-assessed-at", datetime.now(UTC).isoformat(),
        "--quality-passed", "true",
        "--quality-score", "0.9",
        "--quality-assessed-at", datetime.now(UTC).isoformat(),
        "--gate-passed", "true",
        "--gate-name", "production_manifest_gate",
        "--gate-evaluated-at", datetime.now(UTC).isoformat(),
        "--repository", REPOSITORY,
        "--pull-request", str(pull_request),
        "--expected-head", head_sha,
    ])
    assert rc == 0, "attest-publication record-attestation failed"


class TestHappyPath:
    def test_record_and_verify_succeeds(
        self, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path
    ) -> None:
        content_sha = _digest("content-1")
        profile_fingerprint = _digest("profile")
        manifest_digest = _digest("manifest")
        _record_scope_authorization(
            pg_container=pg_container, tmp_path=tmp_path, gh_scenario_dir=gh_scenario_dir,
            authorization_id="auth-1", pull_request=201, manifest_digest=manifest_digest,
        )
        resource_id, artifact_id = _create_resource_and_artifact(pg_container, content_sha256=content_sha)
        _record_attestation(
            pg_container=pg_container, gh_scenario_dir=gh_scenario_dir,
            resource_id=resource_id, artifact_id=artifact_id, scope_authorization_id="auth-1",
            profile_fingerprint=profile_fingerprint, manifest_digest=manifest_digest, pull_request=202,
        )
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            verified = verify_publication_attestation(
                conn, resource_id=resource_id,
                current_content_sha256=content_sha,
                current_profile_fingerprint=profile_fingerprint,
                current_manifest_digest=manifest_digest,
            )
        assert verified.resource_id == resource_id
        assert verified.artifact_id == artifact_id


class TestDriftInvalidation:
    def test_content_sha_drift_invalidates(
        self, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path
    ) -> None:
        content_sha = _digest("content-2")
        profile_fingerprint = _digest("profile")
        manifest_digest = _digest("manifest")
        _record_scope_authorization(
            pg_container=pg_container, tmp_path=tmp_path, gh_scenario_dir=gh_scenario_dir,
            authorization_id="auth-2", pull_request=203, manifest_digest=manifest_digest,
        )
        resource_id, artifact_id = _create_resource_and_artifact(pg_container, content_sha256=content_sha)
        _record_attestation(
            pg_container=pg_container, gh_scenario_dir=gh_scenario_dir,
            resource_id=resource_id, artifact_id=artifact_id, scope_authorization_id="auth-2",
            profile_fingerprint=profile_fingerprint, manifest_digest=manifest_digest, pull_request=204,
        )
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            with pytest.raises(PublicationAttestationInvalidError, match="content_sha256"):
                verify_publication_attestation(
                    conn, resource_id=resource_id,
                    current_content_sha256=_digest("tampered-content"),
                    current_profile_fingerprint=profile_fingerprint,
                    current_manifest_digest=manifest_digest,
                )
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT invalidated_reason FROM ingestion_control.publication_attestations "
                    "WHERE resource_id = %s", (resource_id,),
                )
                (reason,) = cur.fetchone()
            assert reason == "content_sha256_drift"

    def test_profile_fingerprint_drift_invalidates(
        self, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path
    ) -> None:
        content_sha = _digest("content-3")
        profile_fingerprint = _digest("profile")
        manifest_digest = _digest("manifest")
        _record_scope_authorization(
            pg_container=pg_container, tmp_path=tmp_path, gh_scenario_dir=gh_scenario_dir,
            authorization_id="auth-3", pull_request=205, manifest_digest=manifest_digest,
        )
        resource_id, artifact_id = _create_resource_and_artifact(pg_container, content_sha256=content_sha)
        _record_attestation(
            pg_container=pg_container, gh_scenario_dir=gh_scenario_dir,
            resource_id=resource_id, artifact_id=artifact_id, scope_authorization_id="auth-3",
            profile_fingerprint=profile_fingerprint, manifest_digest=manifest_digest, pull_request=206,
        )
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            with pytest.raises(PublicationAttestationInvalidError, match="profile_fingerprint"):
                verify_publication_attestation(
                    conn, resource_id=resource_id,
                    current_content_sha256=content_sha,
                    current_profile_fingerprint=_digest("tampered-profile"),
                    current_manifest_digest=manifest_digest,
                )

    def test_manifest_digest_drift_invalidates(
        self, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path
    ) -> None:
        content_sha = _digest("content-4")
        profile_fingerprint = _digest("profile")
        manifest_digest = _digest("manifest")
        _record_scope_authorization(
            pg_container=pg_container, tmp_path=tmp_path, gh_scenario_dir=gh_scenario_dir,
            authorization_id="auth-4", pull_request=207, manifest_digest=manifest_digest,
        )
        resource_id, artifact_id = _create_resource_and_artifact(pg_container, content_sha256=content_sha)
        _record_attestation(
            pg_container=pg_container, gh_scenario_dir=gh_scenario_dir,
            resource_id=resource_id, artifact_id=artifact_id, scope_authorization_id="auth-4",
            profile_fingerprint=profile_fingerprint, manifest_digest=manifest_digest, pull_request=208,
        )
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            with pytest.raises(PublicationAttestationInvalidError, match="manifest_digest"):
                verify_publication_attestation(
                    conn, resource_id=resource_id,
                    current_content_sha256=content_sha,
                    current_profile_fingerprint=profile_fingerprint,
                    current_manifest_digest=_digest("tampered-manifest"),
                )


class TestScopeRevocationPropagates:
    def test_live_scope_dismissal_invalidates_attestation_without_db_update(
        self, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path
    ) -> None:
        """Preuve centrale ADR-0033 § 4 : la révocation live du scope LOT41A
        référencé invalide l'attestation, sans qu'aucune ligne
        ``publication_attestations`` ni ``scope_authorizations`` n'ait été
        modifiée avant la vérification elle-même."""
        content_sha = _digest("content-5")
        profile_fingerprint = _digest("profile")
        manifest_digest = _digest("manifest")
        _record_scope_authorization(
            pg_container=pg_container, tmp_path=tmp_path, gh_scenario_dir=gh_scenario_dir,
            authorization_id="auth-5", pull_request=209, manifest_digest=manifest_digest,
        )
        resource_id, artifact_id = _create_resource_and_artifact(pg_container, content_sha256=content_sha)
        _record_attestation(
            pg_container=pg_container, gh_scenario_dir=gh_scenario_dir,
            resource_id=resource_id, artifact_id=artifact_id, scope_authorization_id="auth-5",
            profile_fingerprint=profile_fingerprint, manifest_digest=manifest_digest, pull_request=210,
        )

        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pull_request FROM (SELECT evidence_pull_request AS pull_request "
                    "FROM ingestion_control.scope_authorizations WHERE authorization_id = %s) s",
                    ("auth-5",),
                )
                (scope_pr,) = cur.fetchone()

        scenario_path = gh_scenario_dir / "scenario.json"
        import json as _json

        scenario = _json.loads(scenario_path.read_text())
        pr_entry = scenario["prs"][str(scope_pr)]
        dismissal = approved_review(
            review_id=999001, pull_request=pr_entry["pull_request"],
            submitted_at="2026-08-07T13:00:00Z", state="DISMISSED",
        )
        pr_entry["reviews"].append(dismissal)
        scenario_path.write_text(_json.dumps(scenario))

        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT revoked_at FROM ingestion_control.scope_authorizations "
                    "WHERE authorization_id = %s", ("auth-5",),
                )
                (revoked_at,) = cur.fetchone()
            assert revoked_at is None

            with pytest.raises(PublicationAttestationInvalidError, match="scope_authorization"):
                verify_publication_attestation(
                    conn, resource_id=resource_id,
                    current_content_sha256=content_sha,
                    current_profile_fingerprint=profile_fingerprint,
                    current_manifest_digest=manifest_digest,
                )


class TestHumanReviewRevocationAndReplay:
    def test_live_human_review_dismissal_invalidates_attestation(
        self, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path
    ) -> None:
        content_sha = _digest("content-6")
        profile_fingerprint = _digest("profile")
        manifest_digest = _digest("manifest")
        _record_scope_authorization(
            pg_container=pg_container, tmp_path=tmp_path, gh_scenario_dir=gh_scenario_dir,
            authorization_id="auth-6", pull_request=211, manifest_digest=manifest_digest,
        )
        resource_id, artifact_id = _create_resource_and_artifact(pg_container, content_sha256=content_sha)
        _record_attestation(
            pg_container=pg_container, gh_scenario_dir=gh_scenario_dir,
            resource_id=resource_id, artifact_id=artifact_id, scope_authorization_id="auth-6",
            profile_fingerprint=profile_fingerprint, manifest_digest=manifest_digest, pull_request=212,
        )

        import json as _json

        scenario_path = gh_scenario_dir / "scenario.json"
        scenario = _json.loads(scenario_path.read_text())
        pr_entry = scenario["prs"]["212"]
        dismissal = approved_review(
            review_id=999002, pull_request=pr_entry["pull_request"],
            submitted_at="2026-08-07T14:00:00Z", state="DISMISSED",
        )
        pr_entry["reviews"].append(dismissal)
        scenario_path.write_text(_json.dumps(scenario))

        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            with pytest.raises(PublicationAttestationInvalidError, match="human_review"):
                verify_publication_attestation(
                    conn, resource_id=resource_id,
                    current_content_sha256=content_sha,
                    current_profile_fingerprint=profile_fingerprint,
                    current_manifest_digest=manifest_digest,
                )


class TestFalsification:
    def test_tampered_human_review_challenge_is_rejected(
        self, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path
    ) -> None:
        content_sha = _digest("content-7")
        profile_fingerprint = _digest("profile")
        manifest_digest = _digest("manifest")
        _record_scope_authorization(
            pg_container=pg_container, tmp_path=tmp_path, gh_scenario_dir=gh_scenario_dir,
            authorization_id="auth-7", pull_request=213, manifest_digest=manifest_digest,
        )
        resource_id, artifact_id = _create_resource_and_artifact(pg_container, content_sha256=content_sha)
        _record_attestation(
            pg_container=pg_container, gh_scenario_dir=gh_scenario_dir,
            resource_id=resource_id, artifact_id=artifact_id, scope_authorization_id="auth-7",
            profile_fingerprint=profile_fingerprint, manifest_digest=manifest_digest, pull_request=214,
        )
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ingestion_control.publication_attestations "
                    "SET human_review_challenge = %s WHERE resource_id = %s",
                    ("NEXUS-TRUSTED-REVIEW-V1:" + "1" * 64, resource_id),
                )
            conn.commit()

            with pytest.raises(PublicationAttestationInvalidError, match="replay"):
                verify_publication_attestation(
                    conn, resource_id=resource_id,
                    current_content_sha256=content_sha,
                    current_profile_fingerprint=profile_fingerprint,
                    current_manifest_digest=manifest_digest,
                )


class TestNoAttestation:
    def test_verify_denied_when_no_attestation_exists(self, pg_container: dict[str, str]) -> None:
        resource_id, _artifact_id = _create_resource_and_artifact(pg_container, content_sha256=_digest("orphan"))
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            with pytest.raises(PublicationAttestationInvalidError, match="no active"):
                verify_publication_attestation(
                    conn, resource_id=resource_id,
                    current_content_sha256=_digest("orphan"),
                    current_profile_fingerprint=_digest("profile"),
                    current_manifest_digest=_digest("manifest"),
                )


class TestRetrievalEligibleGate:
    def test_attempt_transition_denied_when_attestation_invalid(
        self, pg_container: dict[str, str]
    ) -> None:
        resource_id, _artifact_id = _create_resource_and_artifact(pg_container, content_sha256=_digest("gate-1"))
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ingestion_control.resources SET resource_state = 'REVIEWED' "
                    "WHERE resource_id = %s", (resource_id,),
                )
                cur.execute("SELECT run_id, state_version FROM ingestion_control.resources WHERE resource_id = %s", (resource_id,))
                run_id, state_version = cur.fetchone()
            conn.commit()

            with pytest.raises(PublicationAttestationInvalidError):
                attempt_retrieval_eligible_transition(
                    conn, resource_id=resource_id, run_id=run_id, expected_version=state_version,
                    actor="test-actor", current_content_sha256=_digest("gate-1"),
                    current_profile_fingerprint=_digest("profile"), current_manifest_digest=_digest("manifest"),
                )
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT resource_state FROM ingestion_control.resources WHERE resource_id = %s",
                    (resource_id,),
                )
                (state,) = cur.fetchone()
            assert state == "REVIEWED"

    def test_attempt_transition_succeeds_when_attestation_valid(
        self, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path
    ) -> None:
        content_sha = _digest("gate-2")
        profile_fingerprint = _digest("profile")
        manifest_digest = _digest("manifest")
        _record_scope_authorization(
            pg_container=pg_container, tmp_path=tmp_path, gh_scenario_dir=gh_scenario_dir,
            authorization_id="auth-gate-2", pull_request=215, manifest_digest=manifest_digest,
        )
        resource_id, artifact_id = _create_resource_and_artifact(pg_container, content_sha256=content_sha)
        _record_attestation(
            pg_container=pg_container, gh_scenario_dir=gh_scenario_dir,
            resource_id=resource_id, artifact_id=artifact_id, scope_authorization_id="auth-gate-2",
            profile_fingerprint=profile_fingerprint, manifest_digest=manifest_digest, pull_request=216,
        )
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ingestion_control.resources SET resource_state = 'REVIEWED' "
                    "WHERE resource_id = %s", (resource_id,),
                )
                cur.execute("SELECT run_id, state_version FROM ingestion_control.resources WHERE resource_id = %s", (resource_id,))
                run_id, state_version = cur.fetchone()
            conn.commit()

            result = attempt_retrieval_eligible_transition(
                conn, resource_id=resource_id, run_id=run_id, expected_version=state_version,
                actor="test-actor", current_content_sha256=content_sha,
                current_profile_fingerprint=profile_fingerprint, current_manifest_digest=manifest_digest,
            )
            conn.commit()
            assert result.to_state.value == "RETRIEVAL_ELIGIBLE"

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT resource_state FROM ingestion_control.resources WHERE resource_id = %s",
                    (resource_id,),
                )
                (state,) = cur.fetchone()
            assert state == "RETRIEVAL_ELIGIBLE"
