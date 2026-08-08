"""LOT41A (ADR-0032) — autorité d'autorisation de scope, bout en bout.

Remédiation GATE H1, items **B**, **C** et **G**.

**Ce qui est réel dans ce fichier.** PostgreSQL est un vrai conteneur,
migré et provisionné par les vrais scripts. La décision d'autorité est
rendue par la vraie fonction ``evaluate_trusted_review`` d'ADR-0025, non
modifiée, jamais monkeypatchée. Le transport HTTP est le vrai adaptateur
``github_authority``. Seul le *serveur* GitHub est local (cf.
``tests/_local_github.py``), ce qui rend les scénarios adverses
reproductibles sans dépendre du réseau.

**La matrice adverse.** Chaque cas ci-dessous modifie exactement *une*
chose par rapport à une autorisation qui vérifie, et exige un refus. C'est
cette unicité qui prouve que chaque maillon porte réellement, plutôt qu'un
seul maillon strict masquant tous les autres.
"""
from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _local_github import (  # noqa: E402
    REPOSITORY,
    REVIEWER,
    VALID_TOKEN,
    LocalGitHub,
    git_blob_sha,
    local_github_server,
)
from _pg_authority import (  # noqa: E402
    authority_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)
from nexus_contracts.authority_artifacts import (  # noqa: E402
    ScopeAuthorizationArtifact,
    canonical_authorization_path,
)
from nexus_contracts.ingestion import ResourceScope  # noqa: E402

from ingestor.ingestion_control.scope_authority import (  # noqa: E402
    ScopeAuthorizationDeniedError,
    verify_scope_authorization,
)
from ingestor.ingestion_worker.authorize_scope_cli import main as authorize_scope_main  # noqa: E402

pytestmark = [pytest.mark.integration, requires_docker]

AUTHORIZATION_ID = "auth-nsi-terminale-2026"
OTHER_AUTHORIZATION_ID = "auth-nsi-terminale-2027"
PR_NUMBER = 4242
REVIEW_ID = 777
HEAD_SHA = "b" * 40
BASE_SHA = "a" * 40
SUBMITTED_AT = "2026-08-08T10:00:00Z"

VALID_SCOPE: dict[str, Any] = {
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


def artifact_document(**overrides: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    document: dict[str, Any] = {
        "protocol_version": "LOT41A-V1",
        "authorization_id": AUTHORIZATION_ID,
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "scope": dict(VALID_SCOPE),
        "manifest_digest": "a" * 64,
        "profile_id": "rag_nexus_nsi_terminale_specialite",
        "profile_version": "v1",
        "profile_fingerprint": "b" * 64,
        "allowed_domains": ["eduscol.education.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "pii_absence_attested": True,
        "pii_absence_evidence": "Corpus officiel, aucune donnee personnelle.",
        "valid_from": (now - timedelta(days=1)).isoformat(),
        "valid_until": (now + timedelta(days=365)).isoformat(),
    }
    document.update(overrides)
    return document


def canonical_bytes(**overrides: Any) -> bytes:
    return ScopeAuthorizationArtifact.model_validate(
        artifact_document(**overrides)
    ).canonical_bytes()


@pytest.fixture(scope="module")
def pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("lot41a")


@pytest.fixture(autouse=True)
def _clean(pg: dict[str, str]) -> Iterator[None]:
    with psycopg.connect(superuser_dsn(pg)) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ingestion_control.publication_attestations")
            cur.execute("DELETE FROM ingestion_control.scope_authorizations")
        conn.commit()
    yield


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[LocalGitHub]:
    state = LocalGitHub()
    state.add_approved_pr(
        number=PR_NUMBER, head_sha=HEAD_SHA, base_sha=BASE_SHA,
        review_id=REVIEW_ID, submitted_at=SUBMITTED_AT,
    )
    token_file = tmp_path / "gh-token"
    token_file.write_text(VALID_TOKEN, encoding="utf-8")
    with local_github_server(state) as base_url:
        monkeypatch.setenv("NEXUS_GITHUB_API_BASE", base_url)
        monkeypatch.setenv("NEXUS_GITHUB_TOKEN_FILE", str(token_file))
        monkeypatch.delenv("NEXUS_GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("NEXUS_GITHUB_TOTAL_TIMEOUT_S", raising=False)
        yield state


@pytest.fixture
def authority_env(pg: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_INGESTION_CONTROL_AUTHORITY_DSN", authority_dsn(pg))
    monkeypatch.delenv("PG_INGESTION_CONTROL_DSN", raising=False)


def publish_artifact(
    github: LocalGitHub, *, authorization_id: str = AUTHORIZATION_ID,
    ref: str = HEAD_SHA, **overrides: Any,
) -> bytes:
    """Commite l'artefact canonique au chemin canonique, au commit donné."""
    raw = canonical_bytes(authorization_id=authorization_id, **overrides)
    github.put_blob(path=canonical_authorization_path(authorization_id), ref=ref, content=raw)
    return raw


def record(
    *, authorization_id: str = AUTHORIZATION_ID, pull_request: int = PR_NUMBER,
    expected_head: str = HEAD_SHA,
) -> int:
    return authorize_scope_main([
        "record-authorization",
        "--authorization-id", authorization_id,
        "--repository", REPOSITORY,
        "--pull-request", str(pull_request),
        "--expected-head", expected_head,
    ])


@pytest.fixture
def recorded(
    github: LocalGitHub, authority_env: None, pg: dict[str, str]
) -> dict[str, Any]:
    """Une autorisation enregistrée par la chaîne RÉELLE de bout en bout."""
    raw = publish_artifact(github)
    assert record() == 0
    with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT authorization_digest, artifact_blob_sha, artifact_path "
            "FROM ingestion_control.scope_authorizations WHERE authorization_id = %s",
            (AUTHORIZATION_ID,),
        )
        row = cur.fetchone()
    assert row is not None
    return {"raw": raw, "digest": row[0], "blob_sha": row[1], "path": row[2]}


def verify(pg: dict[str, str], *, authorization_id: str = AUTHORIZATION_ID,
           scope: dict[str, Any] | None = None) -> Any:
    with psycopg.connect(superuser_dsn(pg)) as conn:
        return verify_scope_authorization(
            conn,
            authorization_id=authorization_id,
            scope=ResourceScope.model_validate(scope) if scope else None,
        )


def tamper(pg: dict[str, str], *, column: str, value: Any) -> None:
    """Modifie une colonne DIRECTEMENT en base, en contournant tout le code
    applicatif — simule un attaquant disposant d'un accès SQL privilégié."""
    with psycopg.connect(superuser_dsn(pg)) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE ingestion_control.scope_authorizations "  # noqa: S608 - nom de colonne littéral fourni par le test
                f"SET {column} = %s WHERE authorization_id = %s",
                (value, AUTHORIZATION_ID),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Chemin nominal
# ---------------------------------------------------------------------------


class TestRecordingBindsTheReviewedBytes:
    def test_records_from_the_approved_blob_and_verifies(
        self, pg: dict[str, str], recorded: dict[str, Any]
    ) -> None:
        result = verify(pg)
        assert result.authorization_id == AUTHORIZATION_ID
        assert result.allowed_domains == ("eduscol.education.fr",)
        assert result.rights_categories == ("officiel_public",)
        assert result.evidence_review_id == REVIEW_ID
        assert result.evidence_reviewer == REVIEWER

    def test_the_stored_digest_is_the_digest_of_the_reviewed_bytes(
        self, recorded: dict[str, Any]
    ) -> None:
        from hashlib import sha256

        assert recorded["digest"] == sha256(recorded["raw"]).hexdigest()
        assert recorded["blob_sha"] == git_blob_sha(recorded["raw"])
        assert recorded["path"] == canonical_authorization_path(AUTHORIZATION_ID)

    def test_the_verification_never_mutates_github(
        self, pg: dict[str, str], github: LocalGitHub, recorded: dict[str, Any]
    ) -> None:
        """Item I : la lecture seule est prouvée par observation du serveur,
        pas seulement par relecture du code."""
        verify(pg)
        assert github.non_get_requests == []


class TestScopeBindingIsExplicit:
    def test_matching_scope_passes(self, pg: dict[str, str], recorded: dict[str, Any]) -> None:
        assert verify(pg, scope=VALID_SCOPE).authorization_id == AUTHORIZATION_ID

    def test_a_different_scope_is_denied(
        self, pg: dict[str, str], recorded: dict[str, Any]
    ) -> None:
        other = {**VALID_SCOPE, "niveau": "premiere"}
        with pytest.raises(ScopeAuthorizationDeniedError, match="not the requested scope"):
            verify(pg, scope=other)


# ---------------------------------------------------------------------------
# Item C — aucune sélection implicite « la plus récente »
# ---------------------------------------------------------------------------


class TestNoImplicitLatestAuthorization:
    def test_a_second_broader_authorization_never_supersedes_the_named_one(
        self, pg: dict[str, str], github: LocalGitHub, authority_env: None
    ) -> None:
        """Cœur de l'item C : deux autorisations coexistent pour le MÊME
        scope, la seconde plus large et valide plus longtemps. Vérifier la
        première doit continuer de rendre la première — jamais la seconde,
        quel que soit son ``valid_until``."""
        publish_artifact(github)
        assert record() == 0

        later_pr = 4243
        later_head = "c" * 40
        github.add_approved_pr(
            number=later_pr, head_sha=later_head, base_sha=BASE_SHA,
            review_id=888, submitted_at="2026-08-09T10:00:00Z",
        )
        far_future = (datetime.now(UTC) + timedelta(days=3650)).isoformat()
        publish_artifact(
            github,
            authorization_id=OTHER_AUTHORIZATION_ID,
            ref=later_head,
            allowed_domains=["eduscol.education.fr", "www.education.fr"],
            valid_until=far_future,
        )
        assert record(
            authorization_id=OTHER_AUTHORIZATION_ID,
            pull_request=later_pr,
            expected_head=later_head,
        ) == 0

        narrow = verify(pg, authorization_id=AUTHORIZATION_ID)
        assert narrow.allowed_domains == ("eduscol.education.fr",)
        broad = verify(pg, authorization_id=OTHER_AUTHORIZATION_ID)
        assert broad.allowed_domains == ("eduscol.education.fr", "www.education.fr")

    def test_an_unknown_authorization_id_is_denied(
        self, pg: dict[str, str], recorded: dict[str, Any]
    ) -> None:
        with pytest.raises(ScopeAuthorizationDeniedError, match="no scope_authorizations row"):
            verify(pg, authorization_id="auth-does-not-exist")

    def test_no_recency_ordering_index_exists(self, pg: dict[str, str]) -> None:
        """Garde-fou structurel : aucun index ne matérialise plus la notion
        d'« autorisation la plus récente », qui inviterait un futur lot à
        réintroduire ``ORDER BY valid_until DESC LIMIT 1``."""
        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = 'ingestion_control' "
                "AND tablename = 'scope_authorizations'"
            )
            definitions = [row[0] for row in cur.fetchall()]
        assert definitions, "expected at least one index on scope_authorizations"
        assert not any("valid_until" in definition for definition in definitions), definitions

    def test_the_verifier_source_contains_no_recency_selection(self) -> None:
        source = (
            ENGINE_ROOT / "src" / "ingestor" / "ingestion_control" / "scope_authority.py"
        ).read_text(encoding="utf-8")
        lowered = source.lower()
        assert "order by valid_until" not in lowered
        assert "limit 1" not in lowered


# ---------------------------------------------------------------------------
# Item B — liaison aux octets exacts
# ---------------------------------------------------------------------------


class TestArtifactBytesAreBinding:
    def test_modified_bytes_at_the_same_head_are_denied(
        self, pg: dict[str, str], github: LocalGitHub, recorded: dict[str, Any]
    ) -> None:
        """Même PR, même head approuvé, un seul champ modifié dans le
        fichier : la vérification doit refuser."""
        publish_artifact(github, allowed_domains=["attacker.test"])
        with pytest.raises(ScopeAuthorizationDeniedError, match="artifact_blob_sha"):
            verify(pg)

    def test_a_single_byte_of_whitespace_is_denied(
        self, pg: dict[str, str], github: LocalGitHub, recorded: dict[str, Any]
    ) -> None:
        github.put_blob(
            path=canonical_authorization_path(AUTHORIZATION_ID),
            ref=HEAD_SHA,
            content=recorded["raw"] + b" ",
        )
        with pytest.raises(ScopeAuthorizationDeniedError, match="artifact_blob_sha"):
            verify(pg)

    def test_a_non_canonical_but_equivalent_file_is_denied(
        self, pg: dict[str, str], github: LocalGitHub, recorded: dict[str, Any]
    ) -> None:
        """Un fichier au contenu logiquement identique mais réencodé (JSON
        compact) est refusé : sinon deux fichiers différents porteraient la
        même décision."""
        document = json.loads(recorded["raw"].decode())
        github.put_blob(
            path=canonical_authorization_path(AUTHORIZATION_ID),
            ref=HEAD_SHA,
            content=json.dumps(document, sort_keys=True).encode(),
        )
        with pytest.raises(ScopeAuthorizationDeniedError, match="artifact_blob_sha"):
            verify(pg)

    def test_a_missing_artifact_is_denied(
        self, pg: dict[str, str], github: LocalGitHub, recorded: dict[str, Any]
    ) -> None:
        github.blobs.clear()
        with pytest.raises(ScopeAuthorizationDeniedError, match="cannot re-read"):
            verify(pg)

    def test_an_artifact_committed_at_another_path_is_denied(
        self, pg: dict[str, str], github: LocalGitHub, recorded: dict[str, Any]
    ) -> None:
        """Le chemin relu est dérivé de l'identifiant : republier le même
        contenu ailleurs ne le rend pas lisible."""
        github.blobs.clear()
        github.put_blob(
            path="governance/authorizations/somewhere-else.json",
            ref=HEAD_SHA,
            content=recorded["raw"],
        )
        with pytest.raises(ScopeAuthorizationDeniedError, match="cannot re-read"):
            verify(pg)

    def test_recording_refuses_a_non_canonical_committed_artifact(
        self, github: LocalGitHub, authority_env: None
    ) -> None:
        document = json.loads(canonical_bytes().decode())
        github.put_blob(
            path=canonical_authorization_path(AUTHORIZATION_ID),
            ref=HEAD_SHA,
            content=json.dumps(document, indent=4).encode(),
        )
        assert record() == 1

    def test_recording_refuses_an_artifact_declaring_another_id(
        self, github: LocalGitHub, authority_env: None
    ) -> None:
        """Le contenu ne peut jamais revendiquer un autre identifiant que
        celui sous lequel il est enregistré."""
        github.put_blob(
            path=canonical_authorization_path(AUTHORIZATION_ID),
            ref=HEAD_SHA,
            content=canonical_bytes(authorization_id=OTHER_AUTHORIZATION_ID),
        )
        assert record() == 1


class TestDatabaseTamperingNeverSurvives:
    """Une ligne modifiée directement en base ne survit jamais à sa propre
    relecture : le digest et le blob restent ceux de l'artefact revu."""

    @pytest.mark.parametrize(
        ("column", "value", "expected"),
        [
            ("allowed_domains", ["attacker.test"], "allowed_domains"),
            ("rights_categories", ["restricted"], "rights_categories"),
            ("manifest_digest", "9" * 64, "manifest_digest"),
            ("profile_fingerprint", "9" * 64, "profile_fingerprint"),
            ("profile_version", "v99", "profile_version"),
            ("pii_absence_evidence", "elargi a la main", "pii_absence_evidence"),
            ("authorization_digest", "0" * 64, "authorization_digest"),
            ("artifact_blob_sha", "0" * 40, "artifact_blob_sha"),
        ],
    )
    def test_column_tampering_is_denied(
        self, pg: dict[str, str], recorded: dict[str, Any],
        column: str, value: Any, expected: str,
    ) -> None:
        tamper(pg, column=column, value=value)
        with pytest.raises(ScopeAuthorizationDeniedError, match=expected):
            verify(pg)

    def test_extending_the_validity_window_is_denied(
        self, pg: dict[str, str], recorded: dict[str, Any]
    ) -> None:
        tamper(pg, column="valid_until", value=datetime.now(UTC) + timedelta(days=99999))
        with pytest.raises(ScopeAuthorizationDeniedError, match="valid_until"):
            verify(pg)

    def test_artifact_path_tampering_is_denied(
        self, pg: dict[str, str], recorded: dict[str, Any]
    ) -> None:
        with psycopg.connect(superuser_dsn(pg)) as conn:
            with conn.cursor() as cur:
                # La contrainte CHECK de la migration 007 lie déjà artifact_path
                # à authorization_id : la falsification est refusée AVANT même
                # d'atteindre le vérificateur. C'est la propriété recherchée.
                with pytest.raises(psycopg.errors.CheckViolation):
                    cur.execute(
                        "UPDATE ingestion_control.scope_authorizations "
                        "SET artifact_path = %s WHERE authorization_id = %s",
                        ("governance/authorizations/other.json", AUTHORIZATION_ID),
                    )
            conn.rollback()


# ---------------------------------------------------------------------------
# Item G — preuve GitHub exacte, champ par champ
# ---------------------------------------------------------------------------


class TestLiveGitHubProofIsFieldByField:
    @pytest.mark.parametrize(
        ("column", "value"),
        [
            ("evidence_review_id", 999_999),
            ("evidence_reviewer", "someone-else"),
            ("evidence_base_sha", "9" * 40),
            ("evidence_challenge", "NEXUS-TRUSTED-REVIEW-V1:" + "9" * 64),
        ],
    )
    def test_a_single_diverging_evidence_field_is_denied(
        self, pg: dict[str, str], recorded: dict[str, Any], column: str, value: Any
    ) -> None:
        """Chaque champ d'évidence est vérifié séparément. L'ancienne forme
        (« le challenge stocké appartient-il aux challenges live ? »)
        acceptait un reviewer ou une review différents ; ici, aucune
        divergence isolée ne passe."""
        tamper(pg, column=column, value=value)
        with pytest.raises(ScopeAuthorizationDeniedError, match=column):
            verify(pg)

    def test_a_diverging_submitted_at_is_denied(
        self, pg: dict[str, str], recorded: dict[str, Any]
    ) -> None:
        tamper(
            pg, column="evidence_submitted_at",
            value=datetime(2020, 1, 1, tzinfo=UTC),
        )
        with pytest.raises(ScopeAuthorizationDeniedError, match="evidence_submitted_at"):
            verify(pg)

    def test_a_challenge_belonging_to_another_pr_is_denied(
        self, pg: dict[str, str], github: LocalGitHub, recorded: dict[str, Any]
    ) -> None:
        """Rejeu ciblé : un challenge parfaitement valide, mais celui d'une
        AUTRE PR approuvée. La comparaison ensembliste l'aurait accepté si
        les deux PR avaient partagé un vérificateur ; l'égalité stricte le
        refuse."""
        from _local_github import challenge_for

        other = github.add_approved_pr(
            number=5555, head_sha="d" * 40, base_sha=BASE_SHA, review_id=555,
        )
        tamper(pg, column="evidence_challenge", value=challenge_for(other))
        with pytest.raises(ScopeAuthorizationDeniedError, match="evidence_challenge"):
            verify(pg)

    def test_pull_request_closure_is_denied(
        self, pg: dict[str, str], github: LocalGitHub, recorded: dict[str, Any]
    ) -> None:
        github.close_pr(PR_NUMBER)
        with pytest.raises(ScopeAuthorizationDeniedError, match="no longer approved"):
            verify(pg)

    def test_review_dismissal_is_denied(
        self, pg: dict[str, str], github: LocalGitHub, recorded: dict[str, Any]
    ) -> None:
        """La révocation est RÉELLE sans aucune écriture PostgreSQL : la
        ligne reste non-révoquée et non-expirée, et pourtant la
        vérification échoue."""
        github.dismiss_reviews(PR_NUMBER)
        with pytest.raises(ScopeAuthorizationDeniedError, match="no longer approved"):
            verify(pg)

        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT revoked_at FROM ingestion_control.scope_authorizations "
                "WHERE authorization_id = %s",
                (AUTHORIZATION_ID,),
            )
            assert cur.fetchone() == (None,)

    def test_a_new_head_is_denied(
        self, pg: dict[str, str], github: LocalGitHub, recorded: dict[str, Any]
    ) -> None:
        github.move_head(PR_NUMBER, "e" * 40)
        with pytest.raises(ScopeAuthorizationDeniedError, match="no longer approved"):
            verify(pg)

    def test_losing_reviewer_write_permission_is_denied(
        self, pg: dict[str, str], github: LocalGitHub, recorded: dict[str, Any]
    ) -> None:
        github.permissions[REVIEWER] = {"permission": "read", "role_name": "read"}
        with pytest.raises(ScopeAuthorizationDeniedError, match="no longer approved"):
            verify(pg)

    def test_github_outage_is_denied_not_assumed_valid(
        self, pg: dict[str, str], github: LocalGitHub, recorded: dict[str, Any]
    ) -> None:
        github.force_status = 503
        with pytest.raises(ScopeAuthorizationDeniedError, match="live GitHub verification failed"):
            verify(pg)

    def test_missing_credential_is_denied(
        self, pg: dict[str, str], recorded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NEXUS_GITHUB_TOKEN_FILE", raising=False)
        monkeypatch.delenv("NEXUS_GITHUB_TOKEN", raising=False)
        with pytest.raises(ScopeAuthorizationDeniedError, match="no GitHub read credential"):
            verify(pg)


class TestRevocationAndValidityWindow:
    def test_revoked_authorization_is_denied(
        self, pg: dict[str, str], github: LocalGitHub, recorded: dict[str, Any],
        authority_env: None,
    ) -> None:
        revocation_pr, revocation_head = 4400, "f" * 40
        github.add_approved_pr(
            number=revocation_pr, head_sha=revocation_head, base_sha=BASE_SHA, review_id=910,
        )
        assert authorize_scope_main([
            "revoke-authorization",
            "--authorization-id", AUTHORIZATION_ID,
            "--reason", "scope elargi par erreur",
            "--repository", REPOSITORY,
            "--pull-request", str(revocation_pr),
            "--expected-head", revocation_head,
        ]) == 0
        with pytest.raises(ScopeAuthorizationDeniedError, match="was revoked"):
            verify(pg)

    def test_revocation_requires_its_own_approved_pr(
        self, pg: dict[str, str], github: LocalGitHub, recorded: dict[str, Any],
        authority_env: None,
    ) -> None:
        github.add_approved_pr(
            number=4401, head_sha="9" * 40, base_sha=BASE_SHA, review_id=911,
        )
        github.close_pr(4401)
        assert authorize_scope_main([
            "revoke-authorization",
            "--authorization-id", AUTHORIZATION_ID,
            "--reason", "tentative sans approbation",
            "--repository", REPOSITORY,
            "--pull-request", "4401",
            "--expected-head", "9" * 40,
        ]) == 1
        verify(pg)  # toujours valide : la révocation non approuvée n'a rien fait

    def test_an_authorization_not_yet_valid_is_denied(
        self, pg: dict[str, str], github: LocalGitHub, authority_env: None
    ) -> None:
        future = datetime.now(UTC) + timedelta(days=10)
        publish_artifact(
            github,
            valid_from=future.isoformat(),
            valid_until=(future + timedelta(days=30)).isoformat(),
        )
        assert record() == 0
        with pytest.raises(ScopeAuthorizationDeniedError, match="not valid yet"):
            verify(pg)

    def test_an_expired_authorization_is_denied(
        self, pg: dict[str, str], github: LocalGitHub, authority_env: None
    ) -> None:
        past = datetime.now(UTC) - timedelta(days=10)
        publish_artifact(
            github,
            valid_from=(past - timedelta(days=30)).isoformat(),
            valid_until=past.isoformat(),
        )
        assert record() == 0
        with pytest.raises(ScopeAuthorizationDeniedError, match="expired"):
            verify(pg)


class TestRecordingRefusesUnapprovedEvidence:
    def test_closed_pr_records_nothing(
        self, pg: dict[str, str], github: LocalGitHub, authority_env: None
    ) -> None:
        publish_artifact(github)
        github.close_pr(PR_NUMBER)
        assert record() == 1
        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM ingestion_control.scope_authorizations")
            assert cur.fetchone() == (0,)

    def test_wrong_expected_head_records_nothing(
        self, pg: dict[str, str], github: LocalGitHub, authority_env: None
    ) -> None:
        publish_artifact(github)
        assert record(expected_head="0" * 40) == 1
        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM ingestion_control.scope_authorizations")
            assert cur.fetchone() == (0,)

    def test_a_repository_outside_the_trusted_config_records_nothing(
        self, github: LocalGitHub, authority_env: None
    ) -> None:
        publish_artifact(github)
        assert authorize_scope_main([
            "record-authorization",
            "--authorization-id", AUTHORIZATION_ID,
            "--repository", "attacker/RAG",
            "--pull-request", str(PR_NUMBER),
            "--expected-head", HEAD_SHA,
        ]) == 1
