"""LOT41A (ADR-0032) : falsification, révocation, replay, scope, digest —
PostgreSQL réel + frontière GitHub réelle (``gh`` remplacé sur PATH par un
fake déterministe, cf. ``_fake_github.py`` — tout le reste de la chaîne de
vérification, y compris ``scripts/github/trusted_human_review_github.py``
non modifié, est exercé pour de vrai).

Preuve centrale de ce fichier : la révocation est réelle sans dépendre
d'aucune mise à jour PostgreSQL — dismissre la review GitHub sous-jacente
invalide immédiatement une autorisation par ailleurs non-``revoked``, non-
expirée, stockée telle quelle (``test_live_review_dismissal_denies_...``).
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

from ingestor.ingestion_control.scope_authority import (  # noqa: E402
    ScopeAuthorizationDeniedError,
    verify_scope_authorization,
    verify_scope_authorization_by_id,
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

OTHER_SCOPE = {**VALID_SCOPE, "niveau": "premiere"}


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
    container_name = f"nexus-lot41a-{uuid.uuid4().hex[:10]}"
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


def _authority_dsn(pg_container: dict[str, str]) -> str:
    return (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user=ingestion_control_authority "
        f"password={AUTHORITY_PASSWORD}"
    )


def _superuser_dsn(pg_container: dict[str, str]) -> str:
    return (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
    )


@pytest.fixture(autouse=True)
def _clean_scope_authorizations(pg_container: dict[str, str]) -> Iterator[None]:
    """Chaque test démarre sur une table vide — isolation totale entre cas,
    même connexion superutilisateur que les suites LOT44f existantes."""
    with psycopg.connect(_superuser_dsn(pg_container)) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ingestion_control.scope_authorizations")
        conn.commit()
    yield


@pytest.fixture
def gh_scenario_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = fake_gh_bin_dir(tmp_path)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return bin_dir


def _manifest_digest(seed: str = "m") -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _scope_payload_file(tmp_path: Path, *, scope: dict[str, object], manifest_digest: str) -> Path:
    payload = {
        "scope": scope,
        "manifest_digest": manifest_digest,
        "profile_id": "nsi_terminale_v1",
        "profile_version": "v1",
        "profile_fingerprint": _manifest_digest("profile"),
        "allowed_domains": ["eduscol.education.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "pii_absence_attested": True,
        "pii_absence_evidence": "audit manuel 2026-08-07",
        "valid_from": datetime.now(UTC).isoformat(),
        "valid_until": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
    }
    path = tmp_path / "scope.yml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _record_authorization(
    *, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path,
    authorization_id: str, pull_request: int, scope: dict[str, object] | None = None,
    manifest_digest: str | None = None, expired: bool = False,
) -> tuple[dict[str, object], str, str]:
    """Enregistre une autorisation via le vrai CLI, avec une PR fake
    approuvée. Renvoie (pull_request_dict, head_sha, base_sha)."""
    scope = scope or VALID_SCOPE
    manifest_digest = manifest_digest or _manifest_digest()
    head_sha = secrets.token_hex(20)
    base_sha = secrets.token_hex(20)
    pr = approved_pull_request(number=pull_request, head_sha=head_sha, base_sha=base_sha)
    review = approved_review(review_id=pull_request * 10 + 1, pull_request=pr)
    write_scenario(gh_scenario_dir, pull_request=pr, reviews=[review])

    scope_file = _scope_payload_file(tmp_path, scope=scope, manifest_digest=manifest_digest)
    if expired:
        data = yaml.safe_load(scope_file.read_text())
        data["valid_from"] = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        data["valid_until"] = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        scope_file.write_text(yaml.safe_dump(data), encoding="utf-8")

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
    return pr, head_sha, base_sha


class TestRecordAndVerifyHappyPath:
    def test_record_then_verify_succeeds(
        self, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path
    ) -> None:
        _record_authorization(
            pg_container=pg_container, tmp_path=tmp_path, gh_scenario_dir=gh_scenario_dir,
            authorization_id="auth-happy-1", pull_request=101,
        )
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            scope = ResourceScope.model_validate(VALID_SCOPE)
            verified = verify_scope_authorization(conn, scope=scope)
        assert verified.authorization_id == "auth-happy-1"
        assert verified.evidence_pull_request == 101


class TestFailClosedAbsenceAndExpiry:
    def test_verify_denied_when_no_authorization_exists(self, pg_container: dict[str, str]) -> None:
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            scope = ResourceScope.model_validate(VALID_SCOPE)
            with pytest.raises(ScopeAuthorizationDeniedError, match="no non-revoked"):
                verify_scope_authorization(conn, scope=scope)

    def test_verify_denied_when_expired(
        self, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path
    ) -> None:
        _record_authorization(
            pg_container=pg_container, tmp_path=tmp_path, gh_scenario_dir=gh_scenario_dir,
            authorization_id="auth-expired-1", pull_request=102, expired=True,
        )
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            scope = ResourceScope.model_validate(VALID_SCOPE)
            with pytest.raises(ScopeAuthorizationDeniedError, match="expired"):
                verify_scope_authorization(conn, scope=scope)


class TestScopeMismatch:
    def test_verify_denied_for_different_scope(
        self, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path
    ) -> None:
        _record_authorization(
            pg_container=pg_container, tmp_path=tmp_path, gh_scenario_dir=gh_scenario_dir,
            authorization_id="auth-scope-1", pull_request=103, scope=VALID_SCOPE,
        )
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            other_scope = ResourceScope.model_validate(OTHER_SCOPE)
            with pytest.raises(ScopeAuthorizationDeniedError, match="no non-revoked"):
                verify_scope_authorization(conn, scope=other_scope)


class TestRevocation:
    def test_db_revocation_via_cli_denies_verification(
        self, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path
    ) -> None:
        _record_authorization(
            pg_container=pg_container, tmp_path=tmp_path, gh_scenario_dir=gh_scenario_dir,
            authorization_id="auth-revoke-1", pull_request=104,
        )
        rev_pr = approved_pull_request(number=105, head_sha=secrets.token_hex(20), base_sha=secrets.token_hex(20))
        rev_review = approved_review(review_id=1050, pull_request=rev_pr)
        write_scenario(gh_scenario_dir, pull_request=rev_pr, reviews=[rev_review])

        os.environ["PG_INGESTION_CONTROL_DSN"] = _authority_dsn(pg_container)
        rc = authorize_scope_main([
            "revoke-authorization",
            "--authorization-id", "auth-revoke-1",
            "--reason", "test revocation",
            "--repository", REPOSITORY,
            "--pull-request", "105",
            "--expected-head", rev_pr["head"]["sha"],
        ])
        assert rc == 0

        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            scope = ResourceScope.model_validate(VALID_SCOPE)
            with pytest.raises(ScopeAuthorizationDeniedError, match="no non-revoked"):
                verify_scope_authorization(conn, scope=scope)

    def test_live_review_dismissal_denies_verification_without_db_update(
        self, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path
    ) -> None:
        """Preuve centrale ADR-0032 § 4 : révocation réelle sans écriture
        PostgreSQL — la ligne stockée reste non-``revoked``, non-expirée,
        inchangée ; seule la review GitHub sous-jacente est dismissée."""
        pr, head_sha, _base_sha = _record_authorization(
            pg_container=pg_container, tmp_path=tmp_path, gh_scenario_dir=gh_scenario_dir,
            authorization_id="auth-live-dismiss-1", pull_request=106,
        )
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            scope = ResourceScope.model_validate(VALID_SCOPE)
            verify_scope_authorization(conn, scope=scope)  # sanity : encore valide

        dismissal = approved_review(
            review_id=1061, pull_request=pr, submitted_at="2026-08-07T12:00:00Z", state="DISMISSED",
        )
        original_review = approved_review(review_id=1060, pull_request=pr)
        write_scenario(gh_scenario_dir, pull_request=pr, reviews=[original_review, dismissal])

        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT revoked_at, valid_until > now() FROM ingestion_control.scope_authorizations "
                    "WHERE authorization_id = %s", ("auth-live-dismiss-1",),
                )
                revoked_at, still_valid = cur.fetchone()
            assert revoked_at is None
            assert still_valid is True

            scope = ResourceScope.model_validate(VALID_SCOPE)
            with pytest.raises(ScopeAuthorizationDeniedError):
                verify_scope_authorization(conn, scope=scope)


class TestReplay:
    def test_verify_denied_when_head_changes_after_recording(
        self, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path
    ) -> None:
        """Rejeu d'une évidence périmée : le PR est mis à jour (nouveau
        head) après l'autorisation — la ligne stockée référence toujours
        l'ancien head, la relecture live doit refuser."""
        pr, head_sha, base_sha = _record_authorization(
            pg_container=pg_container, tmp_path=tmp_path, gh_scenario_dir=gh_scenario_dir,
            authorization_id="auth-replay-1", pull_request=107,
        )
        new_head = secrets.token_hex(20)
        moved_pr = {**pr, "head": {"sha": new_head, "repo": pr["head"]["repo"]}}
        moved_review = approved_review(review_id=1070, pull_request=moved_pr)
        write_scenario(gh_scenario_dir, pull_request=moved_pr, reviews=[moved_review])

        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            scope = ResourceScope.model_validate(VALID_SCOPE)
            with pytest.raises(ScopeAuthorizationDeniedError):
                verify_scope_authorization(conn, scope=scope)


class TestFalsification:
    def test_tampered_stored_challenge_is_rejected(
        self, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path
    ) -> None:
        """Une ligne PostgreSQL falsifiée (challenge modifié à la main,
        contournant le CLI) ne peut jamais passer la revérification live —
        le challenge stocké ne correspond plus à celui recalculé par
        trusted_human_review depuis le PR/review réels."""
        _record_authorization(
            pg_container=pg_container, tmp_path=tmp_path, gh_scenario_dir=gh_scenario_dir,
            authorization_id="auth-falsify-1", pull_request=108,
        )
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ingestion_control.scope_authorizations "
                    "SET evidence_challenge = %s WHERE authorization_id = %s",
                    ("NEXUS-TRUSTED-REVIEW-V1:" + "0" * 64, "auth-falsify-1"),
                )
            conn.commit()

            scope = ResourceScope.model_validate(VALID_SCOPE)
            with pytest.raises(ScopeAuthorizationDeniedError, match="does not match"):
                verify_scope_authorization(conn, scope=scope)


class TestVerifyByIdIsExact:
    def test_by_id_lookup_does_not_silently_pick_a_newer_authorization(
        self, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path
    ) -> None:
        """Deux autorisations valides pour le même scope, digests
        différents — ``verify_scope_authorization_by_id`` doit revérifier
        exactement celle demandée, jamais silencieusement basculer sur
        l'autre (plus récente) via une délégation à la recherche par
        scope."""
        digest_a = _manifest_digest("digest-a")
        digest_b = _manifest_digest("digest-b")
        _record_authorization(
            pg_container=pg_container, tmp_path=tmp_path, gh_scenario_dir=gh_scenario_dir,
            authorization_id="auth-digest-a", pull_request=109, manifest_digest=digest_a,
        )
        _record_authorization(
            pg_container=pg_container, tmp_path=tmp_path, gh_scenario_dir=gh_scenario_dir,
            authorization_id="auth-digest-b", pull_request=110, manifest_digest=digest_b,
        )
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            verified_a = verify_scope_authorization_by_id(conn, authorization_id="auth-digest-a")
            verified_b = verify_scope_authorization_by_id(conn, authorization_id="auth-digest-b")
        assert verified_a.manifest_digest == digest_a
        assert verified_b.manifest_digest == digest_b
        assert verified_a.authorization_id == "auth-digest-a"
        assert verified_b.authorization_id == "auth-digest-b"


class TestCliRefusesWhenPrNotApproved:
    def test_record_authorization_refuses_unapproved_pr(
        self, pg_container: dict[str, str], tmp_path: Path, gh_scenario_dir: Path
    ) -> None:
        head_sha = secrets.token_hex(20)
        pr = approved_pull_request(number=111, head_sha=head_sha, base_sha=secrets.token_hex(20))
        write_scenario(gh_scenario_dir, pull_request=pr, reviews=[])  # aucune review

        scope_file = _scope_payload_file(tmp_path, scope=VALID_SCOPE, manifest_digest=_manifest_digest())
        os.environ["PG_INGESTION_CONTROL_DSN"] = _authority_dsn(pg_container)
        rc = authorize_scope_main([
            "record-authorization",
            "--authorization-id", "auth-unapproved-1",
            "--scope-file", str(scope_file),
            "--repository", REPOSITORY,
            "--pull-request", "111",
            "--expected-head", head_sha,
        ])
        assert rc != 0

        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM ingestion_control.scope_authorizations "
                    "WHERE authorization_id = %s", ("auth-unapproved-1",),
                )
                (count,) = cur.fetchone()
        assert count == 0
